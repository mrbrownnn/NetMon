"""Composite inventory model: NetworkNode <- Group, Device <- Router/Switch/Server/PC/Printer."""
from __future__ import annotations

import ipaddress
from abc import ABC, abstractmethod
from typing import Any, Callable, ClassVar

from netmon.domain.status import Status, worst


class NetworkNode(ABC):
    def __init__(self, id: int | None, name: str, parent: "Group | None" = None) -> None:
        self.id = id
        self.name = name
        self._parent: Group | None = None
        if parent is not None:
            parent.add(self)

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        if not value or not str(value).strip():
            raise ValueError("name is required")
        self._name = str(value).strip()

    @property
    def parent(self) -> "Group | None":
        return self._parent

    @property
    @abstractmethod
    def status(self) -> Status: ...

    @abstractmethod
    def pause(self) -> None: ...

    @abstractmethod
    def resume(self) -> None: ...


class Group(NetworkNode):
    def __init__(self, id: int | None, name: str, parent: "Group | None" = None) -> None:
        self._children: list[NetworkNode] = []
        super().__init__(id, name, parent)

    @property
    def children(self) -> list[NetworkNode]:
        return list(self._children)

    def is_ancestor_of(self, node: NetworkNode) -> bool:
        p = node.parent
        while p is not None:
            if p is self:
                return True
            p = p.parent
        return False

    def add(self, node: NetworkNode) -> None:
        if node is self or (isinstance(node, Group) and node.is_ancestor_of(self)):
            raise ValueError("group cycle not allowed")  # FR-14
        if node.parent is not None:
            node.parent.remove(node)
        self._children.append(node)
        node._parent = self

    def remove(self, node: NetworkNode) -> None:
        self._children.remove(node)
        node._parent = None

    @property
    def status(self) -> Status:
        return worst(c.status for c in self._children)

    def pause(self) -> None:
        for c in self._children:
            c.pause()

    def resume(self) -> None:
        for c in self._children:
            c.resume()


class Device(NetworkNode):
    device_type: ClassVar[str] = "device"
    extra_fields: ClassVar[dict[str, dict]] = {}

    def __init__(self, id: int | None, name: str, ip: str, parent: Group | None = None,
                 mac: str = "", vendor: str = "", location: str = "", notes: str = "",
                 extra: dict | None = None) -> None:
        self.ip = ip
        self.mac, self.vendor, self.location, self.notes = mac, vendor, location, notes
        self.extra: dict[str, Any] = {k: f.get("default") for k, f in self.extra_fields.items()}
        self.extra.update(extra or {})
        self.sensors: list = []
        super().__init__(id, name, parent)

    @property
    def ip(self) -> str:
        return self._ip

    @ip.setter
    def ip(self, value: str) -> None:
        try:
            self._ip = str(ipaddress.IPv4Address(str(value).strip()))
        except ValueError:
            raise ValueError(f"invalid IPv4 address: {value!r}") from None

    @property
    def status(self) -> Status:
        return worst(s.status for s in self.sensors)

    def pause(self) -> None:
        for s in self.sensors:
            s.pause()

    def resume(self) -> None:
        for s in self.sensors:
            s.resume()

    def default_sensors(self) -> list[dict]:
        return [{"type": "ping", "name": "Ping", "target": self.ip}]


class DeviceFactory:
    _registry: ClassVar[dict[str, type[Device]]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[type[Device]], type[Device]]:
        def deco(klass: type[Device]) -> type[Device]:
            klass.device_type = name
            cls._registry[name] = klass
            return klass
        return deco

    @classmethod
    def create(cls, device_type: str, **kw: Any) -> Device:
        try:
            klass = cls._registry[device_type]
        except KeyError:
            raise ValueError(f"unknown device type: {device_type}") from None
        return klass(**kw)

    @classmethod
    def types(cls) -> dict[str, type[Device]]:
        return dict(cls._registry)


def _port_sensor(ip: str, port: int, name: str) -> dict:
    return {"type": "port", "name": name, "target": ip, "params": {"port": port}}


@DeviceFactory.register("router")
class Router(Device):
    extra_fields = {"interfaces": {"label": "Số interface", "type": "int", "default": 0}}

    def default_sensors(self) -> list[dict]:
        return super().default_sensors() + [_port_sensor(self.ip, 22, "SSH")]


@DeviceFactory.register("switch")
class Switch(Device):
    extra_fields = {"ports": {"label": "Số port", "type": "int", "default": 0},
                    "vlans": {"label": "VLAN", "type": "str", "default": ""}}

    def default_sensors(self) -> list[dict]:
        return super().default_sensors() + [_port_sensor(self.ip, 22, "SSH")]


@DeviceFactory.register("server")
class Server(Device):
    extra_fields = {"os": {"label": "Hệ điều hành", "type": "str", "default": ""},
                    "services": {"label": "Dịch vụ", "type": "str", "default": ""}}

    def default_sensors(self) -> list[dict]:
        return super().default_sensors() + [
            {"type": "http", "name": "HTTP", "target": f"http://{self.ip}/"}]


@DeviceFactory.register("pc")
class PC(Device):
    pass


@DeviceFactory.register("printer")
class Printer(Device):
    extra_fields = {"model": {"label": "Model", "type": "str", "default": ""}}
