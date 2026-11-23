"""Build a small real GNS3 2.2 lab through its REST API (no GUI needed).

    python scripts/gns3_lab.py http://127.0.0.1:3080

Creates project "NetMon Lab" with nodes that need no VM images or KVM:
SW-CORE (ethernet_switch) + PC-LAB-01, PC-LAB-02, SRV-WEB (VPCS) wired to it, starts them and gives the
VPCS hosts IPs over their telnet consoles. Idempotent: an existing "NetMon Lab" project is reused.
Routers (VyOS/MikroTik) need a QEMU image + KVM, which this Windows/Docker setup does not have.
"""
import json
import socket
import sys
import time
import urllib.request

BASE = sys.argv[1].rstrip("/") + "/v2" if len(sys.argv) > 1 else "http://127.0.0.1:3080/v2"
NAME = "NetMon Lab"
HOSTS = {"PC-LAB-01": "192.168.100.101", "PC-LAB-02": "192.168.100.102", "SRV-WEB": "192.168.100.10"}


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body or {}).encode() if method != "GET" else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return json.loads(data) if data else None


def project():
    for p in call("GET", "/projects"):
        if p["name"] == NAME:
            call("POST", f"/projects/{p['project_id']}/open")
            return p["project_id"]
    return call("POST", "/projects", {"name": NAME})["project_id"]


def node(pid, existing, name, node_type, x, y, properties=None):
    if name in existing:
        return existing[name]
    return call("POST", f"/projects/{pid}/nodes", {"name": name, "node_type": node_type, "compute_id": "local",
                "x": x, "y": y, "properties": properties or {}})


def vpcs_ip(host, port, ip):
    """VPCS console: 'ip <addr>/<mask> <gw>' then 'save'."""
    with socket.create_connection((host, port), timeout=10) as s:
        time.sleep(1)
        s.sendall(f"ip {ip}/24 192.168.100.1\r\nsave\r\n".encode())
        time.sleep(2)


def main():
    pid = project()
    existing = {n["name"]: n for n in call("GET", f"/projects/{pid}/nodes")}
    sw = node(pid, existing, "SW-CORE", "ethernet_switch", 0, -150)
    hosts = [node(pid, existing, name, "vpcs", -300 + i * 300, 100) for i, name in enumerate(HOSTS)]
    if not call("GET", f"/projects/{pid}/links"):
        for i, h in enumerate(hosts):
            call("POST", f"/projects/{pid}/links", {"nodes": [
                {"node_id": sw["node_id"], "adapter_number": 0, "port_number": i},
                {"node_id": h["node_id"], "adapter_number": 0, "port_number": 0}]})
    call("POST", f"/projects/{pid}/nodes/start")
    time.sleep(3)
    for n in call("GET", f"/projects/{pid}/nodes"):
        if n["name"] in HOSTS:
            vpcs_ip("127.0.0.1", n["console"], HOSTS[n["name"]])
    nodes = call("GET", f"/projects/{pid}/nodes")
    print(f"project {pid}: " + ", ".join(f"{n['name']}={n['status']}:{n['console']}" for n in nodes))
    print(f"links: {len(call('GET', f'/projects/{pid}/links'))}")


if __name__ == "__main__":
    main()
