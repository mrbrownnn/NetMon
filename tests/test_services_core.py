"""Application acceptance tests; no network/lab required."""
from datetime import datetime, timedelta
import json
import threading

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from netmon.domain.remote import CommandError
from netmon.domain.scheduler import MonitorScheduler
from netmon.domain.status import CheckResult, Status
from netmon.infra import db as m
from netmon.infra.repositories import SqlDeviceRepository, SqlGroupRepository, SqlSensorRepository
from netmon.services.errors import AuthError, ValidationError
from netmon.services.facade import NetMonService


@pytest.fixture
def svc(tmp_path, monkeypatch, db_url):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-at-least-32-characters")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    MonitorScheduler.reset_instance()
    events = []
    service = NetMonService.create(db_url(), Fernet.generate_key(), lambda e, d: events.append((e, d)), False)
    service.events = events
    yield service
    service.close()
    MonitorScheduler.reset_instance()


def create(svc, kind="router", **kw):
    return svc.inventory.create_device({"name": "R1", "ip": "127.0.0.1", "device_type": kind, **kw})


def force(svc, sensor_id, status, count=1, value=2):
    sensor = svc.monitor.sensors[sensor_id]
    sensor.check = lambda: CheckResult(status, value, "forced")
    for _ in range(count):
        svc.monitor.run_now(sensor_id)


def test_tc01_auth_and_user_management(svc):
    for i in range(5):
        with pytest.raises(AuthError) as e:
            svc.auth.login("admin", "wrong")
        assert e.value.kind == ("locked" if i == 4 else "invalid")
    assert e.value.locked_seconds == 300
    with pytest.raises(AuthError, match="khóa"):
        svc.auth.login("admin", "test-admin-password")
    svc.auth.unlock(1)
    actor = svc.auth.login("admin", "test-admin-password")
    user = svc.auth.create("operator", "password", "operator", actor)
    assert svc.auth.set_role(user["id"], "viewer", actor)["role"] == "viewer"
    svc.auth.change_password(user["id"], "password", "new password", actor)
    svc.auth.lock(user["id"], actor)
    with pytest.raises(AuthError):
        svc.auth.login("operator", "new password")
    svc.auth.unlock(user["id"], actor)
    assert svc.auth.login("operator", "new password")["id"] == user["id"]
    svc.auth.delete(user["id"], actor)
    with svc.db.session() as s:
        assert s.get(m.User, 1).password_hash.startswith("pbkdf2:sha256:")


def test_tc03_validation_no_partial_writes(svc):
    with pytest.raises(ValidationError) as e:
        create(svc, ip="192.168.1.300")
    assert "ip" in e.value.field_errors
    assert svc.inventory.list_devices()["total"] == 0
    create(svc)
    with pytest.raises(ValidationError) as e:
        create(svc, name="Different")
    assert "ip" in e.value.field_errors
    with pytest.raises(ValidationError):
        create(svc, name="Other", ip="10.0.0.2", extra={"interfaces": -1})


def test_tc04_defaults_selection_and_schema(svc):
    d = create(svc, "server")
    assert {r["sensor_type"] for r in d["sensors"]} == {"ping", "http"}
    assert svc.monitor.stats()["sensor_count"] == 2
    assert not svc.monitor.stats()["running"]
    selected = svc.inventory.create_device({"name": "R2", "ip": "10.0.0.2", "device_type": "router", "default_sensors": ["ping"]})
    assert len(selected["sensors"]) == 1
    assert any(t["type"] == "router" and "interfaces" in t["extra_fields"] for t in svc.inventory.device_types())
    assert any(t["type"] == "port" and "port" in t["params_schema"] for t in svc.monitor.sensor_types())


def test_tc05_tree_filters_cycles_delete(svc):
    root = svc.inventory.create_group("A")
    child = svc.inventory.create_group("B", root["id"])
    for i in range(4):
        d = svc.inventory.create_device({"name": f"D{i}", "ip": f"10.0.0.{i+1}", "group_id": child["id"]})
        force(svc, d["sensors"][0]["id"], Status.DOWN if i == 0 else Status.UP, 3)
    tree = svc.inventory.groups_tree()[0]
    assert tree["status"] == "DOWN"
    assert tree["counts"]["UP"] == 3 and tree["device_count"] == 4
    assert svc.inventory.list_devices(group=root["id"], status="UP")["total"] == 3
    assert svc.inventory.list_devices(q="10.0.0", type="pc", sort="ip", order="desc")["items"][0]["name"] == "D3"
    with pytest.raises(ValidationError):
        svc.inventory.move_group(root["id"], child["id"])
    with pytest.raises(ValidationError):
        svc.inventory.delete_group(root["id"])
    svc.inventory.rename_group(child["id"], "C")
    svc.inventory.move_group(child["id"], None)
    svc.inventory.delete_group(root["id"])


def test_tc08_tc09_events_ack_and_alert_survival(svc):
    d = create(svc, "pc")
    sid = d["sensors"][0]["id"]
    force(svc, sid, Status.UP)
    force(svc, sid, Status.DOWN, 3)
    assert svc.alerts.open_count() == 1
    count = svc.alerts.list()["total"]
    force(svc, sid, Status.DOWN, 5)
    assert svc.alerts.list()["total"] == count
    alert = svc.alerts.list()["items"][0]
    assert alert["old_status"] == "UP"
    assert svc.alerts.ack(alert["id"], "investigating", {"id": 1, "username": "admin"})["state"] == "ACKNOWLEDGED"
    force(svc, sid, Status.UP)
    assert svc.alerts.open_count() == 0
    with pytest.raises(ValidationError):
        svc.alerts.ack(alert["id"])
    changes = [payload for event, payload in svc.events if event == "sensor_status_changed"]
    assert set(changes[-1]) == {"sensor_id", "device_id", "group_ids", "old", "new", "value", "message", "counts", "device_status", "group_statuses"}
    assert changes[-1]["counts"]["UP"] == 1
    assert all(set(payload) == {"open_count", "alert"} for event, payload in svc.events if event.startswith("alert_"))
    assert len(svc.monitor.sensor_results(sid)) == 10
    svc.inventory.delete_device(d["id"])
    assert svc.alerts.list()["total"] == count + 1
    saved = svc.alerts.list()["items"][0]
    assert saved["device_id"] is None and saved["sensor_id"] is None and saved["device_name"] == "R1"


def test_tc11_pause_resume_and_sensor_crud(svc):
    group = svc.inventory.create_group("Lab")
    d = create(svc, group_id=group["id"])
    svc.monitor.pause_group(group["id"])
    for r in d["sensors"]:
        force(svc, r["id"], Status.DOWN, 3)
    assert svc.inventory.groups_tree()[0]["status"] == "PAUSED"
    assert svc.alerts.open_count() == 0
    svc.monitor.resume_group(group["id"])
    added = svc.monitor.add_sensor(d["id"], {"type": "port", "name": "Web", "params": {"port": 80}})
    assert svc.monitor.update_sensor(added["id"], {"interval": 60})["interval"] == 60
    with pytest.raises(ValidationError):
        svc.monitor.update_sensor(added["id"], {"interval": 9})
    with pytest.raises(ValidationError):
        svc.monitor.add_sensor(d["id"], {"type": "port", "params": {"port": 70000}})
    svc.monitor.delete_sensor(added["id"])
    assert svc.monitor.list_sensors(device_id=d["id"])["total"] == 2


def test_tc12_tc13_tc14_tc16_config(svc):
    d = create(svc)
    did = d["id"]
    svc.config.save_credentials(did, {"protocol": "fake", "password": "never-in-plaintext", "username": "admin"})
    with svc.db.session() as s:
        encrypted = s.scalar(select(m.Credential.password_enc))
        assert "never-in-plaintext" not in encrypted
        assert svc.crypto.decrypt(encrypted) == "never-in-plaintext"
    assert "password" not in json.dumps(svc.config.credentials(did))
    assert svc.config.connection_test(did)["ok"]
    b1 = svc.config.create_backup(did)
    assert "new-router" in " ".join(svc.config.preview(did, "set_hostname", {"name": "new-router"})["commands"])
    c1 = svc.config.execute(did, "set_hostname", {"name": "new-router"})
    b2 = svc.config.create_backup(did)
    diff = svc.config.diff(b1["id"], b2["id"])
    assert len([r for r in diff if r["kind"] != "same"]) == 2
    c2 = svc.config.execute(did, "toggle_interface", {"iface": "eth1", "enable": False})
    assert next(r for r in svc.config.interfaces(did) if r["name"] == "eth1")["status"] == "down"
    with pytest.raises(ValidationError):
        svc.config.undo(c1["id"])
    assert svc.config.undo(c2["id"])["undone"]
    assert next(r for r in svc.config.interfaces(did) if r["name"] == "eth1")["status"] == "up"
    conn = svc.config.fake_connections[did]
    conn.fail = "auth"
    assert svc.config.connection_test(did)["kind"] == "auth"
    assert not svc.config.create_backup(did)["ok"]
    assert svc.alerts.list(level="WARNING")["total"] == 1
    conn.fail = None
    for _ in range(12):
        svc.config.create_backup(did)
    assert len(svc.config.list_backups(did)) == 10
    assert svc.config.routes(did)
    assert svc.config.history(did)[0]["undone"]
    assert "never-in-plaintext" not in json.dumps(svc.audit.query())


def test_command_error_does_not_save(svc, monkeypatch):
    d = create(svc)
    svc.config.save_credentials(d["id"], {"protocol": "fake"})
    conn = svc.config._connection(d["id"])
    monkeypatch.setattr(conn, "send_config", lambda commands: "Invalid command: broken")
    result = svc.config.execute(d["id"], "set_hostname", {"name": "NewName"})
    assert not result["ok"] and "Invalid command" in result["output"]
    assert svc.config.history(d["id"]) == []


def test_uptime_intervals_series_and_exports(svc):
    d = create(svc, "pc")
    sid = d["sensors"][0]["id"]
    start = datetime(2026, 1, 1)
    with svc.db.session() as s:
        for minutes, status in [(-10, "UP"), (30, "DOWN"), (45, "PAUSED"), (60, "UP")]:
            s.add(m.CheckResult(sensor_id=sid, ts=start + timedelta(minutes=minutes), status=status, value=5, message=""))
    end = start + timedelta(minutes=90)
    report = svc.reports.uptime(sid, start, end)
    assert report["uptime"] == 80
    assert report["down_count"] == 1 and report["total_down_seconds"] == 900
    assert svc.reports.device_summary(d["id"], start, end)["uptime"] == 80
    series = svc.reports.latency_series(sid, from_=start, to=end)
    assert len(series["points"]) <= 300
    assert [band["status"] for band in series["bands"]] == ["DOWN", "PAUSED"]
    assert svc.reports.group_report(from_=start, to=end)["uptime"] == 80
    assert "R1" in svc.reports.export_csv(from_=start, to=end)
    assert svc.reports.export_pdf(from_=start, to=end).startswith(b"%PDF")
    svc.settings.set({"retention_days": 1})
    assert svc.monitor.purge_results()["deleted"] == 4


def test_csv_import_filters_and_errors(svc):
    content = 'name,ip,device_type\nGood,10.0.0.1,pc\nBad,300.1.1.1,pc\nDuplicate,10.0.0.1,router\n'
    result = svc.inventory.import_csv(content)
    assert result["imported"] == 1
    assert [r["line"] for r in result["errors"]] == [3, 4]
    exported = svc.inventory.export_csv(q="Good")
    assert "Good" in exported and "Duplicate" not in exported
    assert svc.inventory.import_csv("no,headers\na,b")["errors"][0]["line"] == 1
    assert svc.inventory.list_devices(page=2)["items"] == []


def test_discovery_bounded_mock_scan(svc, monkeypatch):
    with pytest.raises(ValidationError):
        svc.discovery.start("192.168.0.0/21")
    with pytest.raises(ValidationError):
        svc.discovery.start("8.8.8.0/24")
    monkeypatch.setattr(svc.discovery, "_probe", lambda ip, ports, stop: {
        "ip": ip, "hostname": "", "open_ports": [22], "guess": "router"})
    job_id = svc.discovery.start("127.0.0.0/30")
    svc.discovery.threads[job_id].join(5)
    job = svc.discovery.status(job_id)
    assert job["finished"] and job["found"] == 2 and job["done"] == 2
    assert svc.discovery.add_selected([job["results"][0]["ip"]])["imported"] == 1
    svc.discovery.cancel(job_id)
    assert svc.discovery.status(job_id)["cancelled"]


def test_restart_loads_saved_sensors(tmp_path, monkeypatch, db_url):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-at-least-32-characters")
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    MonitorScheduler.reset_instance()
    key = Fernet.generate_key()
    url = db_url("persist.db")
    first = NetMonService.create(url, key, lambda *args: None, False)
    device = create(first)
    first.monitor.pause_sensor(device["sensors"][0]["id"])
    first.close()
    second = NetMonService.create(url, key, lambda *args: None, False)
    try:
        assert second.monitor.stats()["sensor_count"] == 2
        assert second.monitor.sensors[device["sensors"][0]["id"]].paused
    finally:
        second.close()
        MonitorScheduler.reset_instance()


def test_sql_repositories_and_thread_sessions(svc):
    d = create(svc)
    repository = SqlDeviceRepository(svc.db)
    assert repository.get(d["id"]).name == "R1"
    group = svc.inventory.create_group("Lab")
    svc.inventory.move_device(d["id"], group["id"])
    assert SqlGroupRepository(svc.db).get(group["id"]).children[0].id == d["id"]
    sensor_repo = SqlSensorRepository(svc.db)
    sensor = sensor_repo.list()[0]
    sensor.name = "New Ping"
    sensor_repo.update(sensor)
    assert sensor_repo.get(sensor.id).name == "New Ping"
    threads = [threading.Thread(target=lambda: svc.audit.log(None, "parallel", "test")) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert svc.audit.query(action="parallel")["total"] == 10


def test_channels_mask_secrets_and_audit(svc):
    channel = svc.alerts.update_channel("email", False, {"host": "localhost", "password": "smtp-secret"})
    assert channel["config"]["password"] == "********"
    channel = svc.alerts.update_channel("email", False, {"password": "********", "port": 587})
    with svc.db.session() as s:
        assert svc.crypto.decrypt(s.get(m.NotifierChannel, "email").config["password"]) == "smtp-secret"
    assert svc.alerts.send_test("web")["ok"]
    svc.audit.log(None, "test", "secrets", {"nested": {"password": "hidden", "token": "hidden"}})
    assert "hidden" not in json.dumps(svc.audit.query(action="test"))
    assert "smtp-secret" not in json.dumps(channel)


def test_sole_admin_protected(svc):
    for operation in (lambda: svc.auth.set_role(1, "viewer"), lambda: svc.auth.lock(1), lambda: svc.auth.delete(1)):
        with pytest.raises(ValidationError):
            operation()
    backup = svc.auth.create("backup-admin", "strong-test-password", "admin")
    assert svc.auth.set_role(1, "viewer")["role"] == "viewer"
    with pytest.raises(ValidationError):
        svc.auth.lock(backup["id"])


def test_undo_ignores_command_echo(svc, monkeypatch):
    device = create(svc)
    svc.config.save_credentials(device["id"], {"protocol": "fake"})
    svc.config.execute(device["id"], "set_hostname", {"name": "error-original"})
    change = svc.config.execute(device["id"], "set_hostname", {"name": "Other"})
    conn = svc.config.fake_connections[device["id"]]
    original = conn.send_config
    def echo(commands):
        output = original(commands)
        return "\n".join(commands) + "\n" + output
    monkeypatch.setattr(conn, "send_config", echo)
    assert svc.config.undo(change["id"])["ok"]
    assert conn.state["hostname"] == "error-original"


def test_stable_explicit_settings_keys(monkeypatch):
    from netmon.infra.config import Settings
    from netmon.infra.crypto import Crypto
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-at-least-32-characters")
    monkeypatch.setenv("FERNET_KEY", key)
    ciphertext = Crypto(Settings().FERNET_KEY).encrypt("restart-secret")
    assert Crypto(Settings().FERNET_KEY).decrypt(ciphertext) == "restart-secret"
    monkeypatch.delenv("FERNET_KEY")
    monkeypatch.setattr("netmon.infra.config.load_dotenv", lambda: None)
    with pytest.raises(ValueError, match="FERNET_KEY"):
        Settings()


def test_admin_cannot_lock_demote_delete_self(svc):
    other = svc.auth.create("second-admin", "strong-test-password", "admin")
    me = {"id": 1, "username": "admin"}
    for operation in (lambda: svc.auth.set_role(1, "viewer", me), lambda: svc.auth.lock(1, me), lambda: svc.auth.delete(1, me)):
        with pytest.raises(ValidationError):
            operation()
    assert svc.auth.lock(other["id"], me)["is_locked"]
