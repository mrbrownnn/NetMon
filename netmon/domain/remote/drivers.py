"""DeviceDriver (Adapter): cùng giao diện, lệnh/parse khác nhau theo hãng (FR-62)."""
from __future__ import annotations

import ipaddress
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, ClassVar

if TYPE_CHECKING:
    from .connection import Connection

# Route kiểu Quagga/IOS: "S>* 0.0.0.0/0 [1/0] via 10.0.0.254, eth0" / "C 10.0.0.0/24 is directly connected, eth0"
_ROUTE_RE = re.compile(
    r"^([A-Z])\S*\s+(\d+\.\d+\.\d+\.\d+/\d+)\s+(?:\[\S+\]\s+)?"
    r"(?:via\s+([\d.]+)|is directly connected)(?:,\s*(\S+))?"
)
_KV_RE = re.compile(r'([\w-]+)=("[^"]*"|\S*)')
_PROTO = {"S": "static", "C": "connected", "O": "ospf", "R": "rip", "B": "bgp", "D": "dynamic"}


def _parse_quagga_routes(output: str) -> list[dict]:
    out = []
    for line in output.splitlines():
        m = _ROUTE_RE.match(line.strip())
        if m:
            out.append({"protocol": _PROTO.get(m[1], m[1]), "destination": m[2],
                        "gateway": m[3] or "", "interface": m[4] or ""})
    return out


def _kv(line: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in _KV_RE.findall(line)}


class DeviceDriver(ABC):
    name: ClassVar[str] = ""
    netmiko_type: ClassVar[str] = ""
    config_command: ClassVar[str] = ""
    hostname_re: ClassVar[re.Pattern]

    def get_running_config(self, conn: Connection) -> str:
        return conn.send_command(self.config_command)

    def get_hostname(self, conn: Connection) -> str:
        m = self.hostname_re.search(self.get_running_config(conn))
        return m[1] if m else ""

    @abstractmethod
    def get_interfaces(self, conn: Connection) -> list[dict]: ...

    @abstractmethod
    def get_routes(self, conn: Connection) -> list[dict]: ...

    @abstractmethod
    def cmd_set_hostname(self, name: str) -> list[str]: ...

    @abstractmethod
    def cmd_set_interface_ip(self, iface: str, cidr: str) -> list[str]: ...

    @abstractmethod
    def cmd_remove_interface_ip(self, iface: str) -> list[str]: ...

    @abstractmethod
    def cmd_toggle_interface(self, iface: str, enable: bool) -> list[str]: ...


class DriverFactory:
    _registry: ClassVar[dict[str, type[DeviceDriver]]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[type[DeviceDriver]], type[DeviceDriver]]:
        def deco(klass: type[DeviceDriver]) -> type[DeviceDriver]:
            klass.name = name
            cls._registry[name] = klass
            return klass
        return deco

    @classmethod
    def create(cls, name: str) -> DeviceDriver:
        try:
            return cls._registry[name]()
        except KeyError:
            raise ValueError(f"Driver không hỗ trợ: {name}") from None

    @classmethod
    def types(cls) -> dict[str, type[DeviceDriver]]:
        return dict(cls._registry)


@DriverFactory.register("vyos")
class VyOSDriver(DeviceDriver):
    netmiko_type = "vyos"
    config_command = "show configuration commands"
    hostname_re = re.compile(r"^set system host-name '?([^'\s]+)'?", re.M)
    _IF_RE = re.compile(r"^(\S+)\s+(\S+)\s+([uAD])/([uD])\s*(.*)$")

    def get_interfaces(self, conn: Connection) -> list[dict]:
        out = []
        for line in conn.send_command("show interfaces").splitlines():
            m = self._IF_RE.match(line.strip())
            if m:
                out.append({"name": m[1], "ip": "" if m[2] == "-" else m[2],
                            "status": "up" if m[3] == "u" else "down", "description": m[5].strip()})
        return out

    def get_routes(self, conn: Connection) -> list[dict]:
        return _parse_quagga_routes(conn.send_command("show ip route"))

    def cmd_set_hostname(self, name: str) -> list[str]:
        return [f"set system host-name {name}", "commit"]

    def cmd_set_interface_ip(self, iface: str, cidr: str) -> list[str]:
        return [f"delete interfaces ethernet {iface} address",
                f"set interfaces ethernet {iface} address {cidr}", "commit"]

    def cmd_remove_interface_ip(self, iface: str) -> list[str]:
        return [f"delete interfaces ethernet {iface} address", "commit"]

    def cmd_toggle_interface(self, iface: str, enable: bool) -> list[str]:
        return [f"{'delete' if enable else 'set'} interfaces ethernet {iface} disable", "commit"]


@DriverFactory.register("mikrotik")
class MikroTikDriver(DeviceDriver):
    netmiko_type = "mikrotik_routeros"
    config_command = "/export"
    hostname_re = re.compile(r"^/system identity\s*\n\s*set name=\"?([^\"\s]+)", re.M)

    def get_interfaces(self, conn: Connection) -> list[dict]:
        ips = {}
        for line in conn.send_command("/ip address print terse").splitlines():
            kv = _kv(line)
            if "interface" in kv:
                ips.setdefault(kv["interface"], kv.get("address", ""))
        out = []
        for line in conn.send_command("/interface print terse").splitlines():
            kv = _kv(line)
            if "name" not in kv:
                continue
            flags = line.split("name=")[0]
            out.append({"name": kv["name"], "ip": ips.get(kv["name"], ""),
                        "status": "down" if "X" in flags else "up", "description": kv.get("comment", "")})
        return out

    def get_routes(self, conn: Connection) -> list[dict]:
        out = []
        for line in conn.send_command("/ip route print terse").splitlines():
            kv = _kv(line)
            if "dst-address" not in kv:
                continue
            connected = "C" in line.split("dst-address=")[0]
            gw = kv.get("gateway", "")
            out.append({"protocol": "connected" if connected else "static", "destination": kv["dst-address"],
                        "gateway": "" if connected else gw, "interface": gw if connected else ""})
        return out

    def cmd_set_hostname(self, name: str) -> list[str]:
        return [f"/system identity set name={name}"]

    def cmd_set_interface_ip(self, iface: str, cidr: str) -> list[str]:
        return self.cmd_remove_interface_ip(iface) + [f"/ip address add address={cidr} interface={iface}"]

    def cmd_remove_interface_ip(self, iface: str) -> list[str]:
        return [f"/ip address remove [find interface={iface}]"]

    def cmd_toggle_interface(self, iface: str, enable: bool) -> list[str]:
        return [f"/interface {'enable' if enable else 'disable'} {iface}"]


@DriverFactory.register("cisco_ios")
class CiscoIOSDriver(DeviceDriver):
    netmiko_type = "cisco_ios"
    config_command = "show running-config"
    hostname_re = re.compile(r"^hostname (\S+)", re.M)

    def get_interfaces(self, conn: Connection) -> list[dict]:
        # ponytail: trạng thái lấy từ cấu hình admin (shutdown), không phải link thật; thêm "show ip interface brief" nếu cần link.
        out: list[dict] = []
        cur: dict | None = None
        for line in self.get_running_config(conn).splitlines():
            if line.startswith("interface "):
                cur = {"name": line.split(None, 1)[1].strip(), "ip": "", "status": "up", "description": ""}
                out.append(cur)
            elif cur is not None and line.startswith(" "):
                s = line.strip()
                if s.startswith("description "):
                    cur["description"] = s[12:]
                elif s.startswith("ip address "):
                    a, m = s.split()[2:4]
                    cur["ip"] = ipaddress.ip_interface(f"{a}/{m}").with_prefixlen
                elif s == "shutdown":
                    cur["status"] = "down"
            else:
                cur = None
        return out

    def get_routes(self, conn: Connection) -> list[dict]:
        return _parse_quagga_routes(conn.send_command("show ip route"))

    def cmd_set_hostname(self, name: str) -> list[str]:
        return [f"hostname {name}"]

    def cmd_set_interface_ip(self, iface: str, cidr: str) -> list[str]:
        i = ipaddress.ip_interface(cidr)
        return [f"interface {iface}", f"ip address {i.ip} {i.netmask}", "exit"]

    def cmd_remove_interface_ip(self, iface: str) -> list[str]:
        return [f"interface {iface}", "no ip address", "exit"]

    def cmd_toggle_interface(self, iface: str, enable: bool) -> list[str]:
        return [f"interface {iface}", "no shutdown" if enable else "shutdown", "exit"]
