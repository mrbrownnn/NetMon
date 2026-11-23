"""GNS3 integration (Strategy): one interface, a real REST client for GNS3 2.2 (/v2) and an in-memory demo lab.

Gns3Client.create("demo") gives the demo lab (no server needed, e.g. on Railway); any http(s) URL gives the
real client. Only the 2.2 API is supported (no auth); 3.x needs /v3 + token and is not implemented.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod


class Gns3Error(Exception):
    """Server unreachable or returned an error; message is user-facing Vietnamese."""


class Gns3Client(ABC):
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def projects(self) -> list[dict]:
        """[{project_id, name, status}]"""

    @abstractmethod
    def nodes(self, project_id: str) -> list[dict]:
        """[{node_id, name, node_type, status, console_host, console, console_type, x, y}]"""

    @abstractmethod
    def links(self, project_id: str) -> list[dict]:
        """[{link_id, nodes: [{node_id, adapter_number, port_number, label}]}]"""

    @abstractmethod
    def node_action(self, project_id: str, node_id: str, action: str) -> None:
        """action: start | stop | reload"""

    @staticmethod
    def create(url: str, timeout: float = 5) -> "Gns3Client":
        return DemoGns3() if url == "demo" else HttpGns3(url, timeout)


class HttpGns3(Gns3Client):
    def __init__(self, url: str, timeout: float = 5):
        self.base, self.timeout = url.rstrip("/") + "/v2", timeout

    def _call(self, method: str, path: str):
        req = urllib.request.Request(self.base + path, method=method, data=b"{}" if method == "POST" else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            raise Gns3Error(f"GNS3 trả lỗi HTTP {e.code} cho {path}") from None
        except (urllib.error.URLError, OSError) as e:
            raise Gns3Error(f"Không kết nối được GNS3 server ({e.__class__.__name__})") from None
        return json.loads(body) if body else None

    def version(self):
        return self._call("GET", "/version")["version"]

    def projects(self):
        return [{k: p.get(k) for k in ("project_id", "name", "status")} for p in self._call("GET", "/projects")]

    def nodes(self, project_id):
        keys = ("node_id", "name", "node_type", "status", "console_host", "console", "console_type", "x", "y")
        host = urllib.parse.urlsplit(self.base).hostname
        result = []
        for n in self._call("GET", f"/projects/{project_id}/nodes"):
            item = {k: n.get(k) for k in keys}
            if item["console_host"] in ("0.0.0.0", "::", None):  # bind-all address: console is on the server host
                item["console_host"] = host
            result.append(item)
        return result

    def links(self, project_id):
        # Port names (e.g. "Ethernet0") come from the nodes; link labels are only "adapter/port" text.
        names = {(n["node_id"], p["adapter_number"], p["port_number"]): p["name"]
                 for n in self._call("GET", f"/projects/{project_id}/nodes") for p in n.get("ports") or []}
        return [{"link_id": link["link_id"], "nodes": [{"node_id": e["node_id"], "adapter_number": e.get("adapter_number"),
                 "port_number": e.get("port_number"),
                 "label": names.get((e["node_id"], e.get("adapter_number"), e.get("port_number")))
                          or (e.get("label") or {}).get("text", "")} for e in link["nodes"]]}
                for link in self._call("GET", f"/projects/{project_id}/links")]

    def node_action(self, project_id, node_id, action):
        if action not in ("start", "stop", "reload"):
            raise ValueError(action)
        self._call("POST", f"/projects/{project_id}/nodes/{node_id}/{action}")


class DemoGns3(Gns3Client):
    """Fake lab matching the demo inventory (netmon.demo): node names equal device names so they pair up."""
    PROJECT = "11111111-0000-4000-8000-000000000001"

    def __init__(self):
        spec = [("CORE-R1", "qemu", 100, 100), ("EDGE-R2", "qemu", 350, 100), ("SW-T2", "ethernet_switch", 225, 250),
                ("LAB-R3", "qemu", 500, 250), ("PC-LAB-01", "vpcs", 100, 400), ("SRV-WEB", "docker", 350, 400)]
        self._nodes = {f"n{i}": {"node_id": f"n{i}", "name": name, "node_type": kind, "x": x, "y": y,
                                 "status": "stopped" if name == "LAB-R3" else "started", "console_host": "127.0.0.1",
                                 "console": 5000 + i, "console_type": "none" if kind == "ethernet_switch" else "telnet"}
                       for i, (name, kind, x, y) in enumerate(spec, 1)}
        wires = [("n1", 0, "eth1", "n3", 0, "e0"), ("n2", 0, "eth1", "n3", 1, "e1"), ("n5", 0, "eth0", "n3", 2, "e2"),
                 ("n6", 0, "eth0", "n3", 3, "e3"), ("n1", 1, "eth2", "n2", 1, "ether2"), ("n2", 2, "ether3", "n4", 0, "eth0")]
        self._links = [{"link_id": f"l{i}", "nodes": [{"node_id": a, "adapter_number": pa, "port_number": 0, "label": la},
                                                      {"node_id": b, "adapter_number": pb, "port_number": 0, "label": lb}]}
                       for i, (a, pa, la, b, pb, lb) in enumerate(wires, 1)]

    def version(self):
        return "2.2 (demo)"

    def projects(self):
        return [{"project_id": self.PROJECT, "name": "NetMon Lab (demo)", "status": "opened"}]

    def _check(self, project_id):
        if project_id != self.PROJECT:
            raise Gns3Error(f"GNS3 trả lỗi HTTP 404 cho /projects/{project_id}")

    def nodes(self, project_id):
        self._check(project_id)
        return [dict(n) for n in self._nodes.values()]

    def links(self, project_id):
        self._check(project_id)
        return [json.loads(json.dumps(link)) for link in self._links]

    def node_action(self, project_id, node_id, action):
        self._check(project_id)
        if action not in ("start", "stop", "reload") or node_id not in self._nodes:
            raise Gns3Error(f"GNS3 trả lỗi HTTP 404 cho node {node_id}")
        self._nodes[node_id]["status"] = "stopped" if action == "stop" else "started"
