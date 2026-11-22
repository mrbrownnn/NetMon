"""ConfigCommand (Command) + CommandHistory: execute/undo theo thứ tự ngược (FR-64, FR-65, UC-06, UC-07)."""
from __future__ import annotations

import ipaddress
import itertools
import re
import shlex
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar

from .connection import Connection
from .drivers import DeviceDriver

ERROR_RE = re.compile(r"invalid|%\s|error|failure", re.I)


class CommandError(Exception):
    """Thiết bị trả lỗi cú pháp; .output giữ nguyên output để hiển thị."""

    def __init__(self, output: str):
        self.output = output
        super().__init__(f"Thiết bị báo lỗi: {output}")


def check_output(output: str) -> str:
    if ERROR_RE.search(output or ""):
        raise CommandError(output)
    return output


def _check_config_output(output: str, commands: list[str]) -> str:
    # Ignore exact command echoes and prompt-only lines, not device error lines.
    lines = []
    for line in (output or "").splitlines():
        text = line.strip()
        if text in commands or any(text.endswith(prompt + cmd) for cmd in commands for prompt in ("#", "# ", ">", "> ", "$", "$ ")):
            continue
        if re.fullmatch(r"\S+[#$>]", text):
            continue
        lines.append(line)
    check_output("\n".join(lines))
    return output

class ConfigCommand(ABC):
    command_type: ClassVar[str]

    def __init__(self, driver: DeviceDriver):
        self.driver = driver
        self.id: int | None = None
        self.undone = False
        self.executed_at: datetime | None = None
        self.output = ""
        self._undo: list[str] | None = None

    @property
    @abstractmethod
    def params(self) -> dict[str, Any]: ...

    @abstractmethod
    def preview(self) -> list[str]: ...

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    def _capture(self, conn: Connection) -> list[str]:
        """Đọc trạng thái cũ từ thiết bị, trả lệnh ngược."""

    def execute(self, conn: Connection) -> str:
        undo = self._capture(conn)
        commands = self.preview()
        self.output = _check_config_output(conn.send_config(commands), commands)
        self._undo, self.executed_at = undo, datetime.now(timezone.utc)
        return self.output

    def undo_commands(self) -> list[str]:
        if self._undo is None:
            raise RuntimeError("Lệnh chưa được thực thi")
        return list(self._undo)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "command_type": self.command_type, "params": self.params,
                "description": self.describe(), "commands": self.preview(),
                "undo_commands": self._undo or [], "output": self.output, "undone": self.undone,
                "executed_at": self.executed_at.isoformat() if self.executed_at else None}

    def _iface(self, conn: Connection, name: str) -> dict:
        for i in self.driver.get_interfaces(conn):
            if i["name"] == name:
                return i
        raise ValueError(f"Không tìm thấy interface {name}")


class SetHostname(ConfigCommand):
    command_type = "set_hostname"

    def __init__(self, driver: DeviceDriver, name: str):
        super().__init__(driver)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", name or ""):
            raise ValueError("Hostname không hợp lệ")
        self.name = name

    @property
    def params(self) -> dict[str, Any]:
        return {"name": self.name}

    def preview(self) -> list[str]:
        return self.driver.cmd_set_hostname(self.name)

    def describe(self) -> str:
        return f"Đổi hostname thành {self.name}"

    def _capture(self, conn: Connection) -> list[str]:
        return self.driver.cmd_set_hostname(self.driver.get_hostname(conn))


class SetInterfaceIP(ConfigCommand):
    command_type = "set_interface_ip"

    def __init__(self, driver: DeviceDriver, iface: str, cidr: str):
        super().__init__(driver)
        self.iface, self.cidr = iface, ipaddress.ip_interface(cidr).with_prefixlen  # ValueError nếu sai

    @property
    def params(self) -> dict[str, Any]:
        return {"iface": self.iface, "cidr": self.cidr}

    def preview(self) -> list[str]:
        return self.driver.cmd_set_interface_ip(self.iface, self.cidr)

    def describe(self) -> str:
        return f"Đặt IP {self.cidr} cho {self.iface}"

    def _capture(self, conn: Connection) -> list[str]:
        old = self._iface(conn, self.iface)["ip"]
        d = self.driver
        if d.name == "vyos":
            addresses = []
            for line in d.get_running_config(conn).splitlines():
                tokens = shlex.split(line)
                if tokens[:5] == ["set", "interfaces", "ethernet", self.iface, "address"]:
                    addresses.extend(tokens[5:])
        elif d.name == "mikrotik":
            from .drivers import _kv
            addresses = [row.get("address", "") for line in conn.send_command("/ip address print terse").splitlines()
                         if (row := _kv(line)).get("interface") == self.iface]
        else:
            addresses = []
        # ponytail: single-address model; reject multi-address writes until undo stores every address.
        if len(addresses) > 1:
            raise ValueError("Cannot change IP on an interface with multiple addresses; no commands sent")
        return d.cmd_set_interface_ip(self.iface, old) if old else d.cmd_remove_interface_ip(self.iface)


class ToggleInterface(ConfigCommand):
    command_type = "toggle_interface"

    def __init__(self, driver: DeviceDriver, iface: str, enable: bool):
        super().__init__(driver)
        self.iface, self.enable = iface, bool(enable)

    @property
    def params(self) -> dict[str, Any]:
        return {"iface": self.iface, "enable": self.enable}

    def preview(self) -> list[str]:
        return self.driver.cmd_toggle_interface(self.iface, self.enable)

    def describe(self) -> str:
        return f"{'Bật' if self.enable else 'Tắt'} interface {self.iface}"

    def _capture(self, conn: Connection) -> list[str]:
        was_up = self._iface(conn, self.iface)["status"] == "up"
        return self.driver.cmd_toggle_interface(self.iface, was_up)


class CommandHistory:
    """Lịch sử trong RAM; chỉ hoàn tác được lệnh mới nhất chưa undo."""

    def __init__(self) -> None:
        self._items: list[ConfigCommand] = []
        self._ids = itertools.count(1)

    def push(self, cmd: ConfigCommand) -> ConfigCommand:
        if cmd.id is None:
            cmd.id = next(self._ids)
        self._items.append(cmd)
        return cmd

    def execute(self, cmd: ConfigCommand, conn: Connection) -> str:
        """Thực thi rồi mới lưu; lỗi cú pháp (CommandError) -> không lưu lịch sử (UC-06)."""
        out = cmd.execute(conn)
        self.push(cmd)
        return out

    @property
    def items(self) -> list[ConfigCommand]:
        return list(self._items)

    def latest_undoable(self) -> ConfigCommand | None:
        return next((c for c in reversed(self._items) if not c.undone), None)

    def can_undo(self, cmd_id: int) -> bool:
        latest = self.latest_undoable()
        return latest is not None and latest.id == cmd_id

    def undo(self, cmd_id: int, conn: Connection) -> str:
        if not self.can_undo(cmd_id):
            raise ValueError("Còn thao tác mới hơn chưa hoàn tác — hãy hoàn tác theo thứ tự ngược")
        cmd = self.latest_undoable()
        assert cmd is not None
        commands = cmd.undo_commands()
        out = _check_config_output(conn.send_config(commands), commands)
        cmd.undone = True
        return out

    def undo_last(self, conn: Connection) -> str:
        latest = self.latest_undoable()
        if latest is None:
            raise ValueError("Không có thao tác để hoàn tác")
        return self.undo(latest.id, conn)  # type: ignore[arg-type]
