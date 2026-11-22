"""Connection (Strategy): SSH / Telnet qua netmiko, Fake trong RAM cho test (FR-60, FR-61)."""
from __future__ import annotations

import copy
import ipaddress
import re
import socket
from abc import ABC, abstractmethod
from typing import Any

from .drivers import DeviceDriver, DriverFactory

MESSAGES = {
    "timeout": "Hết thời gian chờ kết nối tới thiết bị",
    "auth": "Sai thông tin đăng nhập (username/password)",
    "refused": "Thiết bị từ chối kết nối (kiểm tra port/dịch vụ)",
    "other": "Lỗi kết nối",
}


class ConnectionError_(Exception):
    def __init__(self, kind: str, message: str | None = None):
        self.kind = kind if kind in MESSAGES else "other"
        self.message = message or MESSAGES[self.kind]
        super().__init__(self.message)


class Connection(ABC):
    def __init__(self, host: str, port: int, username: str, password: str, driver: DeviceDriver | str):
        self.host, self.port, self.username, self.password = host, port, username, password
        self.driver = DriverFactory.create(driver) if isinstance(driver, str) else driver

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def send_command(self, cmd: str) -> str: ...

    @abstractmethod
    def send_config(self, cmds: list[str]) -> str: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> Connection:
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _map_exception(e: Exception) -> ConnectionError_:
    import netmiko  # lazy
    if isinstance(e, netmiko.NetmikoAuthenticationException):
        return ConnectionError_("auth")
    if isinstance(e, ConnectionRefusedError):
        return ConnectionError_("refused")
    if isinstance(e, (netmiko.NetmikoTimeoutException, socket.timeout, TimeoutError)):
        msg = str(e).lower()
        return ConnectionError_("refused" if "refused" in msg else "timeout")
    return ConnectionError_("other", f"{MESSAGES['other']}: {e}")


class SSHConnection(Connection):
    suffix = ""
    timeout = 10

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self._conn: Any = None

    def connect(self) -> None:
        from netmiko import ConnectHandler  # lazy: netmiko nặng, test không cần
        try:
            self._conn = ConnectHandler(
                device_type=self.driver.netmiko_type + self.suffix, host=self.host, port=self.port,
                username=self.username, password=self.password,
                timeout=self.timeout, auth_timeout=self.timeout, conn_timeout=self.timeout)
        except Exception as e:
            raise _map_exception(e) from e

    def _call(self, fn: str, arg: Any) -> str:
        if self._conn is None:
            self.connect()
        try:
            return getattr(self._conn, fn)(arg)
        except Exception as e:
            raise _map_exception(e) from e

    def send_command(self, cmd: str) -> str:
        return self._call("send_command", cmd)

    def send_config(self, cmds: list[str]) -> str:
        return self._call("send_config_set", cmds)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.disconnect()
            finally:
                self._conn = None


class TelnetConnection(SSHConnection):
    suffix = "_telnet"


class FakeConnection(Connection):
    """Thiết bị giả kiểu VyOS trong RAM; hiểu lệnh của cả 3 driver. fail=auth|timeout|refused để giả lỗi."""

    def __init__(self, host: str = "10.0.0.1", port: int = 22, username: str = "admin", password: str = "",
                 driver: DeviceDriver | str = "vyos", fail: str | None = None, state: dict | None = None):
        super().__init__(host, port, username, password, driver)
        self.fail = fail
        self.connected = False
        self.log: list[str] = []
        self.state = copy.deepcopy(state) if state else {
            "hostname": "R1",
            "interfaces": {
                "eth0": {"ip": "10.0.0.1/24", "enabled": True, "description": "WAN"},
                "eth1": {"ip": "192.168.1.1/24", "enabled": True, "description": "LAN"},
                "eth2": {"ip": "", "enabled": True, "description": ""},
            },
            "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.0.254", "interface": "eth0"}],
        }
        self._ctx: str | None = None  # interface đang cấu hình (Cisco)

    # --- vòng đời ---
    def connect(self) -> None:
        if self.fail:
            raise ConnectionError_(self.fail)
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def _check(self) -> None:
        if not self.connected:
            self.connect()

    # --- show ---
    def send_command(self, cmd: str) -> str:
        self._check()
        self.log.append(cmd)
        cmd = cmd.strip()
        views = {
            "show configuration commands": self._vyos_config,
            "show configuration": self._vyos_config,
            "show running-config": self._cisco_config,
            "/export": self._mikrotik_config,
            "show interfaces": self._vyos_interfaces,
            "show ip route": self._quagga_routes,
            "/interface print terse": self._mt_interfaces,
            "/ip address print terse": self._mt_addresses,
            "/ip route print terse": self._mt_routes,
        }
        if cmd in views:
            return views[cmd]()
        return self._apply(cmd) or ""

    def send_config(self, cmds: list[str]) -> str:
        self._check()
        out = []
        for c in cmds:
            self.log.append(c)
            r = self._apply(c.strip())
            if r:
                out.append(r)
        self._ctx = None
        return "\n".join(out)

    def _connected_routes(self) -> list[dict]:
        return [{"destination": str(ipaddress.ip_interface(i["ip"]).network), "interface": n}
                for n, i in self.state["interfaces"].items() if i["ip"] and i["enabled"]]

    def _vyos_config(self) -> str:
        s = self.state
        lines = []
        for n, i in s["interfaces"].items():
            if i["ip"]:
                lines.append(f"set interfaces ethernet {n} address '{i['ip']}'")
            if i["description"]:
                lines.append(f"set interfaces ethernet {n} description '{i['description']}'")
            if not i["enabled"]:
                lines.append(f"set interfaces ethernet {n} disable")
        lines += [f"set protocols static route {r['destination']} next-hop {r['gateway']}" for r in s["routes"]]
        lines.append(f"set system host-name '{s['hostname']}'")
        return "\n".join(lines)

    def _cisco_config(self) -> str:
        s = self.state
        lines = ["!", f"hostname {s['hostname']}", "!"]
        for n, i in s["interfaces"].items():
            lines.append(f"interface {n}")
            if i["description"]:
                lines.append(f" description {i['description']}")
            if i["ip"]:
                ii = ipaddress.ip_interface(i["ip"])
                lines.append(f" ip address {ii.ip} {ii.netmask}")
            else:
                lines.append(" no ip address")
            if not i["enabled"]:
                lines.append(" shutdown")
            lines.append("!")
        lines += [f"ip route {ipaddress.ip_network(r['destination']).network_address} "
                  f"{ipaddress.ip_network(r['destination']).netmask} {r['gateway']}" for r in s["routes"]]
        return "\n".join(lines + ["end"])

    def _mikrotik_config(self) -> str:
        s = self.state
        lines = ["/interface ethernet"]
        lines += [f"set [ find default-name={n} ]" + (" disabled=yes" if not i["enabled"] else "")
                  for n, i in s["interfaces"].items()]
        lines.append("/ip address")
        lines += [f"add address={i['ip']} interface={n}" for n, i in s["interfaces"].items() if i["ip"]]
        lines.append("/ip route")
        lines += [f"add dst-address={r['destination']} gateway={r['gateway']}" for r in s["routes"]]
        lines += ["/system identity", f"set name={s['hostname']}"]
        return "\n".join(lines)

    def _vyos_interfaces(self) -> str:
        lines = ["Codes: S - State, L - Link, u - Up, D - Down, A - Admin Down",
                 "Interface        IP Address                        S/L  Description",
                 "---------        ----------                        ---  -----------"]
        for n, i in self.state["interfaces"].items():
            st = "u/u" if i["enabled"] else "A/D"
            lines.append(f"{n:<16} {i['ip'] or '-':<33} {st}  {i['description']}".rstrip())
        return "\n".join(lines)

    def _quagga_routes(self) -> str:
        lines = ["Codes: K - kernel route, C - connected, S - static", ""]
        lines += [f"S>* {r['destination']} [1/0] via {r['gateway']}, {r['interface']}" for r in self.state["routes"]]
        lines += [f"C>* {r['destination']} is directly connected, {r['interface']}" for r in self._connected_routes()]
        return "\n".join(lines)

    def _mt_interfaces(self) -> str:
        return "\n".join(f" {k} {'R' if i['enabled'] else 'X'}  name={n} type=ether"
                         + (f' comment="{i["description"]}"' if i["description"] else "")
                         for k, (n, i) in enumerate(self.state["interfaces"].items()))

    def _mt_addresses(self) -> str:
        return "\n".join(f" {k}   address={i['ip']} interface={n}"
                         for k, (n, i) in enumerate((n, i) for n, i in self.state["interfaces"].items() if i["ip"]))

    def _mt_routes(self) -> str:
        rows = [f" {k} AS  dst-address={r['destination']} gateway={r['gateway']}"
                for k, r in enumerate(self.state["routes"])]
        rows += [f" {k + len(rows)} ADC dst-address={r['destination']} gateway={r['interface']}"
                 for k, r in enumerate(self._connected_routes())]
        return "\n".join(rows)

    # --- set (3 phương ngữ) ---
    def _iface(self, name: str) -> dict:
        return self.state["interfaces"].setdefault(name, {"ip": "", "enabled": True, "description": ""})

    def _apply(self, c: str) -> str | None:
        """Áp lệnh cấu hình; trả chuỗi lỗi kiểu thiết bị nếu không hiểu lệnh."""
        s = self.state
        if c in ("commit", "save", "configure", "conf t", "configure terminal", "end", "") or c.startswith("!"):
            return None
        if c == "exit":
            self._ctx = None
            return None
        patterns: list[tuple[str, Any]] = [
            # VyOS
            (r"set system host-name '?([^'\s]+)'?", lambda m: s.update(hostname=m[1])),
            (r"set interfaces ethernet (\S+) address '?([^'\s]+)'?", lambda m: self._set_ip(m[1], m[2])),
            (r"delete interfaces ethernet (\S+) address(?: \S+)?", lambda m: self._set_ip(m[1], "")),
            (r"set interfaces ethernet (\S+) disable", lambda m: self._iface(m[1]).update(enabled=False)),
            (r"delete interfaces ethernet (\S+) disable", lambda m: self._iface(m[1]).update(enabled=True)),
            # MikroTik
            (r"/system identity set name=\"?([^\"\s]+)\"?", lambda m: s.update(hostname=m[1])),
            (r"/ip address add address=(\S+) interface=(\S+)", lambda m: self._set_ip(m[2], m[1])),
            (r"/ip address remove \[find interface=(\S+)\]", lambda m: self._set_ip(m[1], "")),
            (r"/interface (enable|disable) (\S+)", lambda m: self._iface(m[2]).update(enabled=m[1] == "enable")),
            # Cisco
            (r"hostname (\S+)", lambda m: s.update(hostname=m[1])),
            (r"interface (\S+)", lambda m: setattr(self, "_ctx", self._iface(m[1]) and m[1])),
        ]
        if self._ctx:
            patterns += [
                (r"ip address (\S+) (\S+)",
                 lambda m: self._set_ip(self._ctx, ipaddress.ip_interface(f"{m[1]}/{m[2]}").with_prefixlen)),
                (r"no ip address", lambda m: self._set_ip(self._ctx, "")),
                (r"shutdown", lambda m: self._iface(self._ctx).update(enabled=False)),
                (r"no shutdown", lambda m: self._iface(self._ctx).update(enabled=True)),
            ]
        for pat, fn in patterns:
            m = re.fullmatch(pat, c)
            if m:
                try:
                    fn(m)
                except ValueError as e:
                    return f"Error: {e}"
                return None
        return {"cisco_ios": f"% Invalid input detected at '^' marker: {c}",
                "mikrotik": f"syntax error (line 1 column 1): {c}"}.get(self.driver.name, f"Invalid command: {c}")

    def _set_ip(self, iface: str, cidr: str) -> None:
        if cidr:
            ipaddress.ip_interface(cidr)  # ValueError -> lỗi thiết bị
        self._iface(iface)["ip"] = cidr


def make_connection(protocol: str, host: str, port: int, username: str, password: str,
                    driver: DeviceDriver | str, **kw: Any) -> Connection:
    classes: dict[str, type[Connection]] = {"ssh": SSHConnection, "telnet": TelnetConnection, "fake": FakeConnection}
    try:
        cls = classes[protocol.lower()]
    except KeyError:
        raise ValueError(f"Giao thức không hỗ trợ: {protocol}") from None
    return cls(host, port, username, password, driver, **kw)
