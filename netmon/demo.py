"""Demo data so the dashboard, charts and reports have something to show.

Enabled by NETMON_DEMO=1: create_app seeds once when the DB has no devices. Also runnable by hand:
    SECRET_KEY=... FERNET_KEY=... DATABASE_URL=... python -m netmon.demo

What is real vs. fake:
- Device IPs are made-up lab addresses (192.168.100.x). Each sensor's *target* is a reachable public host, so
  live status/latency are real checks. SRV-DB targets 192.0.2.10 (TEST-NET-1, unroutable) so it is truly DOWN;
  PC-LAB-01 has a 1 ms ping threshold so it is truly WARNING.
- The 7-day check history, past outages and past alerts are generated. Every device note says so.
- Config backups/changes on CORE-R1 run through the real service with protocol "fake" (FakeConnection).
ponytail: demo-only; before go-live unset NETMON_DEMO and delete the demo devices (or reset the DB).
"""
import os
import random
from datetime import datetime, timedelta

from netmon.infra import db as m

NOTE = "Dữ liệu demo: IP lab tự đặt; lịch sử 7 ngày và cảnh báo cũ là dữ liệu sinh tự động."
STEP = timedelta(minutes=10)
DAYS = 7
HTTP_TARGET = "https://example.com/"
DNS_TARGET = "example.com"

# group path -> devices: (name, type, lab ip, vendor, location, extra, sensors)
# sensor: (type, name, params, warning_threshold, base_ms, live target or None = HTTP/DNS default)
LAYOUT = {
    ("Tòa A", "Tầng 1"): [
        ("CORE-R1", "router", "192.168.100.1", "VyOS", "Tủ rack T1", {"interfaces": 4},
         [("ping", "Ping", {"count": 3}, 80, 2, "1.1.1.1"), ("dns", "DNS example.com", {}, None, 15, None)]),
        ("PRINTER-T1", "printer", "192.168.100.41", "HP", "Phòng hành chính", {"model": "LaserJet M404"},
         [("ping", "Ping", {"count": 3}, 80, 4, "149.112.112.112")]),
    ],
    ("Tòa A", "Tầng 2"): [
        ("EDGE-R2", "router", "192.168.100.2", "MikroTik", "Tủ rack T2", {"interfaces": 8},
         [("ping", "Ping", {"count": 3}, 80, 3, "8.8.8.8")]),
        ("SW-T2", "switch", "192.168.100.3", "Open vSwitch", "Tủ rack T2", {"ports": 24, "vlans": "10,20,30"},
         [("ping", "Ping", {"count": 3}, 80, 3, "8.8.4.4"), ("port", "TCP 53", {"port": 53}, None, 5, "8.8.4.4")]),
        ("PC-LAB-01", "pc", "192.168.100.101", "Dell", "Phòng Lab A", {},
         [("ping", "Ping", {"count": 3}, 1, 6, "9.9.9.9")]),
    ],
    ("Tòa B", "Phòng Server"): [
        ("SRV-WEB", "server", "192.168.100.10", "Supermicro", "Phòng Server", {"os": "Ubuntu 24.04", "services": "nginx"},
         [("ping", "Ping", {"count": 3}, 80, 2, "1.0.0.1"), ("http", "HTTP example.com", {"contains": ""}, 300, 180, None)]),
        ("SRV-DB", "server", "192.168.100.20", "Dell", "Phòng Server", {"os": "Debian 12", "services": "postgresql"},
         [("ping", "Ping", {"count": 3}, 80, 1, "192.0.2.10"), ("port", "PostgreSQL 5432", {"port": 5432}, None, 1, "192.0.2.10")]),
    ],
    ("Lab ảo",): [
        ("LAB-R3", "router", "192.168.100.200", "VyOS", "GNS3", {"interfaces": 2},
         [("ping", "Ping", {"count": 3}, 80, 5, "208.67.222.222")]),
    ],
}
# Past outages: device -> [(days_ago, minutes, status, ack note or None)]
OUTAGES = {
    "EDGE-R2": [(3.2, 40, "DOWN", "Mất điện tủ rack, đã khôi phục"), (0.6, 20, "WARNING", None)],
    "SW-T2": [(5.5, 30, "DOWN", None)],
    "PC-LAB-01": [(1.8, 90, "DOWN", "Máy tắt cuối tuần")],
    "SRV-WEB": [(4.1, 15, "DOWN", None), (2.3, 30, "WARNING", "Phản hồi chậm giờ cao điểm"), (0.2, 20, "WARNING", None)],
}
SRV_DB_DOWN_FOR = timedelta(hours=2)  # still down now (target is unroutable)


def seed(svc):
    """Seed into an empty inventory. Returns False (no-op) if any device exists."""
    if svc.inventory.list_devices(paginated=False):
        return False
    rng = random.Random(2026)
    admin = next(u for u in svc.auth.users() if u["role"] == "admin")
    now = datetime.now().replace(second=0, microsecond=0)

    groups = {}
    for path in LAYOUT:
        for depth in range(len(path)):
            key = path[: depth + 1]
            if key not in groups:
                groups[key] = svc.inventory.create_group(key[-1], groups.get(key[:-1]), admin)["id"]

    sensors = []  # (sensor_id, device_id, device_name, sensor_name, base_ms, warn)
    for path, devices in LAYOUT.items():
        for name, kind, ip, vendor, location, extra, specs in devices:
            dev = svc.inventory.create_device({"name": name, "ip": ip, "device_type": kind, "group_id": groups[path],
                "vendor": vendor, "location": location, "notes": NOTE, "extra": extra}, admin, default_sensors=[])
            if kind == "router":
                svc.config.save_credentials(dev["id"], {"protocol": "fake", "port": 22, "username": "admin",
                    "password": "demo-only", "driver": "mikrotik" if vendor == "MikroTik" else "vyos"}, admin)
            for stype, sname, params, warn, base, target in specs:
                target = target or {"http": HTTP_TARGET, "dns": DNS_TARGET}[stype]
                s = svc.monitor.add_sensor(dev["id"], {"type": stype, "name": sname, "target": target, "params": params,
                    "interval": 60 if stype == "http" else 30, "timeout": 3, "warning_threshold": warn, "down_after": 3}, admin)
                sensors.append((s["id"], dev["id"], name, sname, base, warn))

    with svc.db.session() as s:
        _history(s, sensors, now, rng)
        _alerts(s, sensors, now)

    core = next(d for d in svc.inventory.list_devices(paginated=False) if d["name"] == "CORE-R1")
    svc.config.create_backup(core["id"], admin)
    svc.config.execute(core["id"], "set_hostname", {"name": "CORE1"}, admin)
    svc.config.create_backup(core["id"], admin)  # diff of the two backups shows the hostname line
    svc.config.execute(core["id"], "toggle_interface", {"iface": "eth2", "enable": False}, admin)
    latest = max(svc.config.history(core["id"]), key=lambda c: c["id"])
    svc.config.undo(latest["id"], admin)
    svc.monitor.pause_group(groups[("Lab ảo",)], True, admin)
    return True


def _status_at(name, ts, now):
    if name == "SRV-DB" and ts >= now - SRV_DB_DOWN_FOR:
        return "DOWN"
    for days_ago, minutes, status, _ in OUTAGES.get(name, []):
        begin = now - timedelta(days=days_ago)
        if begin <= ts < begin + timedelta(minutes=minutes):
            return status
    return "UP"


def _history(s, sensors, now, rng):
    for sid, _, dname, _, base, warn in sensors:
        if dname == "LAB-R3":
            continue  # paused group: no history
        ts, last = now - timedelta(days=DAYS), "UP"
        while ts <= now:
            last = _status_at(dname, ts, now)
            value = None if last == "DOWN" else round(max(0.3, rng.gauss(base, base * 0.25)) * (4 if last == "WARNING" else 1), 2)
            msg = {"DOWN": "Không phản hồi (timeout)", "WARNING": f"Vượt ngưỡng {warn:g} ms" if warn else "Chậm"}.get(last, "OK")
            s.add(m.CheckResult(sensor_id=sid, ts=ts, status=last, value=value, message=msg))
            ts += STEP
        s.get(m.Sensor, sid).status = last


def _alerts(s, sensors, now):
    first = {}
    for sid, did, dname, sname, *_ in sensors:
        first.setdefault(dname, (sid, did, sname))
    for dname, windows in OUTAGES.items():
        sid, did, sname = first[dname]
        for days_ago, minutes, status, note in windows:
            opened = now - timedelta(days=days_ago)
            s.add(m.Alert(sensor_id=sid, device_id=did, device_name=dname, sensor_name=sname,
                level="CRITICAL" if status == "DOWN" else "WARNING", state="RESOLVED",
                message=f"{sname}: UP → {status}", old_status="UP", new_status=status, opened_at=opened,
                ack_by="admin" if note else None, ack_note=note or "", ack_at=opened + timedelta(minutes=5) if note else None,
                resolved_at=opened + timedelta(minutes=minutes)))
    # SRV-DB's current DOWN alert is raised by the app itself on its first real check.

if __name__ == "__main__":
    from netmon.services.facade import NetMonService
    service = NetMonService.create(os.environ["DATABASE_URL"], os.environ["FERNET_KEY"], lambda *a: None, False)
    try:
        print("seeded" if seed(service) else "DB already has devices; nothing seeded")
    finally:
        service.close()
