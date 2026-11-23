import os
import pytest
from cryptography.fernet import Fernet

from netmon.web import create_app, socketio


@pytest.fixture
def app(tmp_path, monkeypatch, db_url):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-api-integration")
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret-key", "FERNET_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": db_url() if os.getenv("NETMON_TEST_DB") else "sqlite://", "START_SCHEDULER": False, "FRONTEND_DIST": str(tmp_path / "dist")})
    yield app
    app.extensions["netmon"].close()


@pytest.fixture
def client(app):
    return app.test_client()


def token(client):
    return client.get("/api/auth/session").json["csrf_token"]


def login(client, username="admin", password="test-admin-password"):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers={"X-CSRFToken": token(client)})


def mutation(client, method, path, data=None):
    return client.open(path, method=method, json=data or {}, headers={"X-CSRFToken": token(client)})


def test_health_session_csrf(client):
    assert client.get("/healthz").json == {"ok": True}
    assert client.get("/api/auth/session").json["user"] is None
    assert client.get("/api/devices").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"}).status_code == 400
    assert login(client).status_code == 200
    assert client.post("/api/groups", json={"name": "No token"}).status_code == 400


def test_tc01_invalid_logins_lock(client):
    for _ in range(4):
        assert login(client, password="wrong").status_code == 401
    result = login(client, password="wrong")
    assert result.status_code == 423
    assert result.json["locked_seconds"] > 0
    assert login(client).status_code == 423


def test_tc02_viewer_delete_and_live_role_lock(app, client):
    service = app.extensions["netmon"]
    viewer = service.auth.create("viewer", "viewer-pass", "viewer")
    assert login(client, "viewer", "viewer-pass").status_code == 200
    assert mutation(client, "DELETE", "/api/devices/999").status_code == 403
    service.auth.set_role(viewer["id"], "admin")
    assert mutation(client, "DELETE", "/api/devices/999").status_code == 404
    service.auth.lock(viewer["id"])
    assert client.get("/api/devices").status_code == 401


def test_socket_refuses_anonymous_and_locked(app, client):
    ws = socketio.test_client(app, flask_test_client=client, namespace="/ws/status")
    assert not ws.is_connected("/ws/status")
    user = app.extensions["netmon"].auth.create("viewer", "viewer-pass", "viewer")
    assert login(client, "viewer", "viewer-pass").status_code == 200
    ws = socketio.test_client(app, flask_test_client=client, namespace="/ws/status")
    assert ws.is_connected("/ws/status")
    app.extensions["netmon"].auth.lock(user["id"])
    denied = socketio.test_client(app, flask_test_client=client, namespace="/ws/status")
    assert not denied.is_connected("/ws/status")
    ws.disconnect(namespace="/ws/status")


def test_socket_push_revoked_after_lock(app, client):
    service = app.extensions["netmon"]
    user = service.auth.create("op", "operator-pass", "operator")
    login(client, "op", "operator-pass")
    ws = socketio.test_client(app, flask_test_client=client, namespace="/ws/status")
    service.alerts.publisher("ping", {"n": 1})
    assert [m["name"] for m in ws.get_received("/ws/status")] == ["ping"]
    service.auth.lock(user["id"])
    service.alerts.publisher("ping", {"n": 2})
    assert ws.get_received("/ws/status") == []


def test_channel_secret_write_only(client):
    login(client)
    assert mutation(client, "PUT", "/api/alerts/channels/telegram", {"enabled": False, "token": "tg-secret-token", "chat_id": "42"}).status_code == 200
    text = client.get("/api/alerts/channels").text
    assert "tg-secret-token" not in text
    channel = next(c for c in client.get("/api/alerts/channels").json["channels"] if c["id"] == "telegram")
    assert {"name": "chat_id", "label": "chat_id", "type": "text", "value": "42"} in channel["fields"]
    assert "value" not in next(f for f in channel["fields"] if f["name"] == "token")


def test_device_validation_and_credentials_not_leaked(app, client):
    login(client)
    invalid = mutation(client, "POST", "/api/devices", {"name": "Bad", "ip": "999.1.2.3", "device_type": "pc"})
    assert invalid.status_code == 400
    assert "ip" in invalid.json["errors"]
    result = mutation(client, "POST", "/api/devices", {"name": "Router", "ip": "127.0.0.1", "device_type": "router",
        "default_sensors": [], "protocol": "fake", "driver": "vyos", "username": "root", "password": "never-leak-this"})
    assert result.status_code == 201
    id = result.json["id"]
    for path in ("/api/devices", f"/api/devices/{id}", f"/api/devices/form?id={id}", "/api/users", "/api/logs"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.json)
        assert "never-leak-this" not in response.text
        assert "password_enc" not in response.text
        assert "password_hash" not in response.text
    app.extensions["netmon"].auth.create("viewer", "viewer-pass")
    mutation(client, "POST", "/api/auth/logout")
    login(client, "viewer", "viewer-pass")
    detail = client.get(f"/api/devices/{id}").json
    assert "credential" not in detail["device"]
    assert detail["backups"] == []
    assert not detail["capabilities"]["config"]
    assert client.get(f"/api/devices/{id}/config/running").status_code == 403


def router(client):
    return mutation(client, "POST", "/api/devices", {"name": "Router", "ip": "127.0.0.1", "device_type": "router",
        "default_sensors": [], "protocol": "fake", "driver": "vyos", "username": "root", "password": "secret"}).json["id"]


def test_execute_rejected_not_200_and_payload_fields(app, client, monkeypatch):
    from netmon.domain.remote.connection import FakeConnection
    login(client)
    id = router(client)
    body = {"command_type": "set_hostname", "params": {"name": "r1"}}
    ok = mutation(client, "POST", f"/api/devices/{id}/config/execute", body)
    assert ok.status_code == 200 and ok.json["ok"]
    monkeypatch.setattr(FakeConnection, "send_config", lambda self, cmds: "Invalid command: x")
    rejected = mutation(client, "POST", f"/api/devices/{id}/config/execute", body)
    assert rejected.status_code == 400 and rejected.json["ok"] is False
    undo = mutation(client, "POST", f"/api/devices/{id}/config/undo", {"command_id": ok.json["id"]})
    assert undo.status_code == 400
    assert isinstance(mutation(client, "POST", f"/api/devices/{id}/config/connection").json["elapsed_ms"], int)
    device = client.get(f"/api/devices/{id}").json["device"]
    assert {"paused", "protocol", "driver", "group_name", "last_check"} <= set(device)
    assert "password" not in device["credential"] and "password_enc" not in device["credential"]
    system = client.get("/api/settings").json["system"]
    assert {"scheduler_running", "worker_count", "version", "running"} <= set(system)
    assert "last_test" in client.get("/api/alerts/channels").json["channels"][0]
    actions = [r["action"] for r in client.get("/api/logs").json["logs"]]
    mutation(client, "POST", "/api/auth/logout")
    login(client)
    assert "logout" in [r["action"] for r in client.get("/api/logs").json["logs"]]
    assert "logout" not in actions


def test_password_change_revokes_other_sessions(app, client):
    service = app.extensions["netmon"]
    user = service.auth.create("op", "old-password", "operator")
    other = app.test_client()
    login(client, "op", "old-password")
    login(other, "op", "old-password")
    assert mutation(client, "POST", "/api/account/password",
        {"current_password": "old-password", "new_password": "new-password", "confirm_password": "new-password"}).status_code == 200
    assert client.get("/api/devices").status_code == 200
    assert other.get("/api/devices").status_code == 401
    service.auth.reset_password(user["id"], "admin-reset")
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/auth/session").json["user"] is None


def test_domain_value_error_message_kept(client):
    login(client)
    id = router(client)
    result = mutation(client, "POST", f"/api/devices/{id}/config/execute", {"command_type": "toggle_interface", "params": {"iface": "nope9", "enable": False}})
    assert result.status_code == 400
    assert "nope9" in result.json["message"]


def test_spa_missing_and_build(app, client, tmp_path):
    assert client.get("/devices").status_code == 503
    login(client)
    assert client.get("/api/not-a-route").status_code == 404
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>React app</html>", encoding="utf-8")
    (dist / "app.js").write_text("console.log('app')", encoding="utf-8")
    assert "React app" in client.get("/devices/3").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/assets/missing.js").status_code == 404


def test_read_endpoints_and_config_flow(app, client):
    login(client)
    result = mutation(client, "POST", "/api/devices", {"name": "Router", "ip": "127.0.0.1", "device_type": "router",
        "default_sensors": [], "protocol": "fake", "driver": "vyos", "username": "root", "password": "secret"})
    id = result.json["id"]
    for path in ("/api/dashboard", "/api/sensors", "/api/sensors/form", "/api/alerts", "/api/alerts/channels", "/api/reports", "/api/settings", "/api/groups"):
        result = client.get(path)
        assert result.status_code == 200, (path, result.json)
    assert mutation(client, "POST", f"/api/devices/{id}/config/connection").json["ok"]
    assert client.get(f"/api/devices/{id}/config/running").status_code == 200
    result = mutation(client, "POST", f"/api/devices/{id}/config/backup")
    assert result.status_code == 200, result.json
    assert result.json["backup"]["config"]
    assert client.get(f"/api/devices/{id}").status_code == 200
    assert client.get("/api/reports/export.csv").mimetype == "text/csv"
    assert client.get("/api/reports/export.pdf").data.startswith(b"%PDF")


def test_device_form_lists_default_sensors_per_type(client):
    login(client)
    types = client.get("/api/devices/form").get_json()["device_types"]
    assert types["router"]["default_sensors"] == ["ping", "port"]
    assert types["server"]["default_sensors"] == ["ping", "http"]


def test_dashboard_tree_devices_carry_sensors(client):
    login(client)
    csrf = client.get("/api/auth/session").get_json()["csrf_token"]
    gid = client.post("/api/settings/groups", json={"name": "G", "parent_id": None}, headers={"X-CSRFToken": csrf}).get_json()
    groups = client.get("/api/groups").get_json()["groups"]
    r = client.post("/api/devices", json={"name": "S1", "ip": "127.0.0.9", "device_type": "server", "group_id": groups[0]["id"]}, headers={"X-CSRFToken": csrf})
    assert r.status_code == 201
    tree = client.get("/api/dashboard").get_json()["tree"]
    device = tree[0]["devices"][0]
    assert [s["type"] for s in device["sensors"]] == ["ping", "http"]


def test_logs_visible_to_viewer_with_all_actions(client, app):
    login(client)
    csrf = client.get("/api/auth/session").get_json()["csrf_token"]
    client.post("/api/settings/users", json={"username": "v1", "role": "viewer", "password": "Viewer-Pass-123"}, headers={"X-CSRFToken": csrf})
    for i in range(25):  # push the login entry off page 1
        client.post("/api/settings/groups", json={"name": f"G{i}", "parent_id": None}, headers={"X-CSRFToken": csrf})
    client.post("/api/auth/logout", headers={"X-CSRFToken": csrf})
    login(client, "v1", "Viewer-Pass-123")
    r = client.get("/api/logs")
    assert r.status_code == 200
    data = r.get_json()
    assert "login" in data["actions"] and "group_create" in data["actions"]
    assert all(set(u) == {"id", "username"} for u in data["users"])


def test_reports_default_to_seven_days(client, app):
    from datetime import datetime, timedelta
    from netmon.infra import db as m
    login(client)
    csrf = client.get("/api/auth/session").get_json()["csrf_token"]
    client.post("/api/settings/groups", json={"name": "G", "parent_id": None}, headers={"X-CSRFToken": csrf})
    gid = client.get("/api/groups").get_json()["groups"][0]["id"]
    dev = client.post("/api/devices", json={"name": "D", "ip": "127.0.0.7", "device_type": "pc", "group_id": gid}, headers={"X-CSRFToken": csrf}).get_json()
    svc = app.extensions["netmon"]
    sid = svc.inventory.get_device(dev["id"])["sensors"][0]["id"]
    now = datetime.now()
    with svc.db.session() as s:  # outage 3 days ago, outside the 24h default
        for hours, status in [(-100, "UP"), (-72, "DOWN"), (-71, "UP")]:
            s.add(m.CheckResult(sensor_id=sid, ts=now + timedelta(hours=hours), status=status, value=1, message=""))
    row = client.get("/api/reports").get_json()["rows"][0]
    assert row["down_count"] == 1 and row["down_seconds"] == 3600
