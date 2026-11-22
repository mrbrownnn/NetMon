"""Explicit, bounded scans of configured authorized IPv4 lab networks."""
import ipaddress
import os
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, RLock, Thread

from netmon.domain.sensors import PingSensor
from netmon.domain.status import Status
from .errors import ValidationError


class DiscoveryService:
    def __init__(self, inventory, audit):
        self.inventory, self.audit = inventory, audit
        raw = os.getenv("ALLOWED_NETWORKS", "192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,127.0.0.0/8")
        self.allowed_networks = [ipaddress.ip_network(x.strip()) for x in raw.split(",") if x.strip()]
        self.jobs, self.stops, self.threads = {}, {}, {}
        self.lock = RLock()

    def start(self, cidr, ports=None, actor=None):
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            if network.version != 4 or network.prefixlen < 22:
                raise ValueError("Chỉ quét IPv4 tối đa /22")
            if not any(network.subnet_of(n) for n in self.allowed_networks if n.version == 4):
                raise ValueError("Mạng ngoài ALLOWED_NETWORKS được cho phép")
            ports = [int(p) for p in (ports if ports is not None else [22, 23, 80, 443, 161])]
            if len(ports) > 32 or any(not 1 <= p <= 65535 for p in ports):
                raise ValueError("Danh sách port không hợp lệ (tối đa 32)")
        except (TypeError, ValueError) as e:
            raise ValidationError({"cidr": str(e)}) from None
        job_id = uuid.uuid4().hex
        hosts = list(network.hosts())
        with self.lock:
            if any(not job["finished"] for job in self.jobs.values()):
                raise ValidationError({"cidr": "Đang có lượt quét; hãy chờ hoặc hủy"})
            self.jobs[job_id] = {"done": 0, "total": len(hosts), "found": 0, "results": [], "finished": False, "cancelled": False}
            self.stops[job_id] = Event()
            worker = Thread(target=self._run, args=(job_id, hosts, ports), daemon=True, name="discovery")
            self.threads[job_id] = worker
        self.audit.log(actor, "discovery_start", job_id, {"cidr": str(network), "ports": ports})
        worker.start()
        return job_id

    def _probe(self, ip, ports, stop):
        if stop.is_set():
            return None
        result = PingSensor(id=None, device_id=0, name="Discovery", target=ip, timeout=0.5, params={"count": 1}).check()
        open_ports = []
        for port in ports:
            if stop.is_set():
                return None
            try:
                with socket.create_connection((ip, port), timeout=0.25):
                    open_ports.append(port)
            except OSError:
                pass
        if result.status not in (Status.UP, Status.WARNING) and not open_ports:
            return None
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except OSError:
            hostname = ""
        guess = "router" if set(open_ports) & {161, 23} else "server" if set(open_ports) & {80, 443} else "printer" if 9100 in open_ports else "pc"
        return {"ip": ip, "hostname": hostname, "open_ports": open_ports, "guess": guess}

    def _run(self, job_id, hosts, ports):
        stop = self.stops[job_id]
        inventory_ips = {d["ip"] for d in self.inventory.list_devices(paginated=False)}
        try:
            with ThreadPoolExecutor(max_workers=32, thread_name_prefix="discovery-probe") as pool:
                futures = [pool.submit(self._probe, str(ip), ports, stop) for ip in hosts]
                for future in as_completed(futures):
                    if stop.is_set():
                        for f in futures:
                            f.cancel()
                        break
                    try:
                        result = future.result()
                    except Exception:
                        result = None
                    with self.lock:
                        job = self.jobs[job_id]
                        job["done"] += 1
                        if result:
                            result["in_inventory"] = result["ip"] in inventory_ips
                            job["results"].append(result)
                            job["found"] += 1
        finally:
            with self.lock:
                self.jobs[job_id]["finished"] = True
                self.jobs[job_id]["cancelled"] = stop.is_set()

    def status(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            return {**job, "results": [dict(r) for r in job["results"]]}

    def cancel(self, job_id, actor=None):
        with self.lock:
            self.stops[job_id].set()
            self.jobs[job_id]["cancelled"] = True
        self.audit.log(actor, "discovery_cancel", job_id)
        return self.status(job_id)

    def add_selected(self, ips, group_id=None, actor=None):
        with self.lock:
            found = {r["ip"]: dict(r) for job in self.jobs.values() for r in job["results"]}
        result = {"imported": 0, "errors": []}
        for ip in dict.fromkeys(ips):
            try:
                row = found.get(ip)
                if row is None:
                    raise ValueError("IP không có trong kết quả quét")
                self.inventory.create_device({"name": row["hostname"] or ip, "ip": ip,
                    "device_type": row["guess"], "group_id": group_id}, actor)
                result["imported"] += 1
            except (ValueError, KeyError) as e:
                result["errors"].append({"ip": ip, "msg": str(e)})
        self.audit.log(actor, "discovery_add", "inventory", {"imported": result["imported"]})
        return result

    def close(self):
        for stop in self.stops.values():
            stop.set()
        for thread in self.threads.values():
            thread.join(timeout=5)
