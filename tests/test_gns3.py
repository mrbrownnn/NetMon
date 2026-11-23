"""GNS3 integration: real HTTP client against a stub /v2 server, demo lab, service pairing, API roles."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.fernet import Fernet

from netmon.domain.gns3 import DemoGns3, Gns3Client, Gns3Error, HttpGns3

PID = "p-1"
CALLS = []


class Stub(BaseHTTPRequestHandler):
    """Minimal GNS3 2.2 REST surface used by HttpGns3."""
    routes = {
        "/v2/version": {"version": "2.2.49", "local": True},
        "/v2/projects": [{"project_id": PID, "name": "Lab", "status": "opened", "path": "/x"}],
        f"/v2/projects/{PID}/nodes": [{"node_id": "a", "name": "R1", "node_type": "qemu", "status": "started",
            "console_host": "127.0.0.1", "console": 5001, "console_type": "telnet", "x": 1, "y": 2, "ports": []}],
        f"/v2/projects/{PID}/links": [{"link_id": "l1", "nodes": [
            {"node_id": "a", "adapter_number": 0, "port_number": 0, "label": {"text": "eth0"}},
            {"node_id": "b", "adapter_number": 1, "port_number": 0}]}],
    }

    def do_GET(self):
        body = self.routes.get(self.path)
        self._send(200 if body is not None else 404, body or {"message": "nope"})

    def do_POST(self):
        CALLS.append(self.path)
        self._send(200 if self.path.endswith(("/start", "/stop", "/reload")) else 404, {})

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_http_client_reads_v2_api(server):
    c = Gns3Client.create(server)
    assert isinstance(c, HttpGns3) and c.version() == "2.2.49"
    assert c.projects() == [{"project_id": PID, "name": "Lab", "status": "opened"}]
    assert c.nodes(PID)[0]["console"] == 5001 and "ports" not in c.nodes(PID)[0]
    assert c.links(PID)[0]["nodes"][0]["label"] == "eth0" and c.links(PID)[0]["nodes"][1]["label"] == ""
    c.node_action(PID, "a", "stop")
    assert CALLS[-1] == f"/v2/projects/{PID}/nodes/a/stop"
    with pytest.raises(Gns3Error, match="404"):
        c.nodes("missing")
    with pytest.raises(ValueError):
        c.node_action(PID, "a", "delete")


def test_http_client_unreachable_is_gns3error():
    with pytest.raises(Gns3Error, match="Không kết nối"):
        HttpGns3("http://127.0.0.1:9", timeout=1).version()


def test_demo_lab_start_stop():
    c = Gns3Client.create("demo")
    pid = c.projects()[0]["project_id"]
    node = next(n for n in c.nodes(pid) if n["name"] == "LAB-R3")
    assert isinstance(c, DemoGns3) and node["status"] == "stopped"
    c.node_action(pid, node["node_id"], "start")
    assert next(n for n in c.nodes(pid) if n["name"] == "LAB-R3")["status"] == "started"
    ids = {n["node_id"] for n in c.nodes(pid)}
    assert all(e["node_id"] in ids for link in c.links(pid) for e in link["nodes"])
    with pytest.raises(Gns3Error):
        c.node_action(pid, "nope", "stop")


@pytest.fixture
def app(tmp_path, monkeypatch):
    from netmon.web import create_app
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-api-integration")
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("GNS3_URL", "demo")
    app = create_app({"TESTING": True, "DATABASE_URL": "sqlite://", "START_SCHEDULER": False, "FRONTEND_DIST": str(tmp_path)})
    yield app
    app.extensions["netmon"].close()


def login(client, user="admin", pw="test-admin-password"):
    csrf = client.get("/api/auth/session").get_json()["csrf_token"]
    client.post("/api/auth/login", json={"username": user, "password": pw}, headers={"X-CSRFToken": csrf})
    return client.get("/api/auth/session").get_json()["csrf_token"]


def test_api_pairs_nodes_and_enforces_roles(app):
    c = app.test_client()
    csrf = login(c)
    c.post("/api/settings/groups", json={"name": "G", "parent_id": None}, headers={"X-CSRFToken": csrf})
    gid = c.get("/api/groups").get_json()["groups"][0]["id"]
    c.post("/api/devices", json={"name": "CORE-R1", "ip": "192.168.100.1", "device_type": "router", "group_id": gid},
           headers={"X-CSRFToken": csrf})
    overview = c.get("/api/gns3").get_json()
    assert overview["demo"] and overview["error"] is None
    pid = overview["projects"][0]["project_id"]
    nodes = {n["name"]: n for n in c.get(f"/api/gns3/projects/{pid}").get_json()["nodes"]}
    assert nodes["CORE-R1"]["device"]["ip"] == "192.168.100.1" and nodes["EDGE-R2"]["device"] is None
    lab = nodes["LAB-R3"]["node_id"]
    assert c.post(f"/api/gns3/projects/{pid}/nodes/{lab}/start", headers={"X-CSRFToken": csrf}).status_code == 200
    assert c.post(f"/api/gns3/projects/{pid}/nodes/{lab}/explode", headers={"X-CSRFToken": csrf}).status_code == 400
    assert c.get("/api/logs?action=gns3_node_start").get_json()["pagination"]["total"] == 1
    assert c.get("/api/gns3/projects/nope").status_code == 502

    c.post("/api/settings/users", json={"username": "v", "role": "viewer", "password": "Viewer-Pass-123"}, headers={"X-CSRFToken": csrf})
    viewer = app.test_client()
    vcsrf = login(viewer, "v", "Viewer-Pass-123")
    assert viewer.get(f"/api/gns3/projects/{pid}").status_code == 200
    assert viewer.post(f"/api/gns3/projects/{pid}/nodes/{lab}/stop", headers={"X-CSRFToken": vcsrf}).status_code == 403


def test_gns3_not_configured(app, monkeypatch):
    app.extensions["netmon"].gns3.__init__("", app.extensions["netmon"].inventory, app.extensions["netmon"].audit)
    c = app.test_client()
    login(c)
    assert c.get("/api/gns3").get_json() == {"configured": False, "demo": False, "url": None, "version": None, "error": None, "projects": []}
    assert c.get("/api/gns3/projects/x").status_code == 400
