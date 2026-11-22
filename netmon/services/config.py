"""Remote device operations, durable backup/history and per-device fake state."""
import time
from threading import RLock

from sqlalchemy import select
from netmon.domain.remote import (CommandError, ConnectionError_, DriverFactory, SetHostname,
    SetInterfaceIP, ToggleInterface, diff_configs, make_connection)
from netmon.domain.remote.commands import _check_config_output
from netmon.infra import db as m
from .common import require, row_dict
from .errors import ValidationError


class ConfigService:
    commands = {"set_hostname": SetHostname, "set_interface_ip": SetInterfaceIP, "toggle_interface": ToggleInterface}

    def __init__(self, db, audit, crypto, alerts):
        self.db, self.audit, self.crypto, self.alerts = db, audit, crypto, alerts
        self.fake_connections = {}
        self.locks = {}
        self.lock = RLock()

    def _lock(self, device_id):
        with self.lock:
            return self.locks.setdefault(device_id, RLock())

    def credentials(self, device_id):
        with self.db.session() as s:
            require(s, m.Device, device_id)
            row = s.scalar(select(m.Credential).where(m.Credential.device_id == device_id))
            return row_dict(row, ("password_enc",)) if row else None

    def save_credentials(self, device_id, data, actor=None):
        protocol = data.get("protocol", "ssh")
        driver = data.get("driver", "vyos")
        try:
            port = int(data.get("port", 23 if protocol == "telnet" else 22))
            if protocol not in ("ssh", "telnet", "fake") or not 1 <= port <= 65535:
                raise ValueError()
            DriverFactory.create(driver)
        except (TypeError, ValueError):
            raise ValidationError({"credential": "Giao thức, port hoặc driver không hợp lệ"}) from None
        with self._lock(device_id), self.db.session() as s:
            require(s, m.Device, device_id)
            row = s.scalar(select(m.Credential).where(m.Credential.device_id == device_id))
            if not row:
                row = m.Credential(device_id=device_id, password_enc=self.crypto.encrypt(""))
                s.add(row)
            row.protocol, row.port, row.driver = protocol, port, driver
            row.username = data.get("username", row.username or "")
            if "password" in data:
                row.password_enc = self.crypto.encrypt(str(data["password"]))
            self.fake_connections.pop(device_id, None)
        self.audit.log(actor, "credential_save", device_id)
        return self.credentials(device_id)

    def _connection(self, device_id):
        with self.db.session() as s:
            device = require(s, m.Device, device_id)
            cred = s.scalar(select(m.Credential).where(m.Credential.device_id == device_id))
            if not cred:
                raise ValidationError({"credential": "Chưa có thông tin kết nối"})
            args = {"protocol": cred.protocol, "host": device.ip, "port": cred.port,
                "username": cred.username, "password": self.crypto.decrypt(cred.password_enc), "driver": cred.driver}
        if args["protocol"] == "fake":
            if device_id not in self.fake_connections:
                self.fake_connections[device_id] = make_connection(**args)
            return self.fake_connections[device_id]
        return make_connection(**args)

    def connection_test(self, device_id, actor=None):
        start = time.perf_counter()
        try:
            with self._lock(device_id), self._connection(device_id):
                pass
            result = {"ok": True, "kind": "ok", "message": "Kết nối thành công"}
        except ConnectionError_ as e:
            result = {"ok": False, "kind": e.kind, "message": self._connection_message(e.kind)}
        result["elapsed"] = round(time.perf_counter() - start, 3)
        self.audit.log(actor, "connection_test", device_id, result)
        return result

    def _connection_message(self, kind):
        return {"auth": "Sai thông tin đăng nhập (username/password)", "timeout": "Hết thời gian chờ kết nối",
            "refused": "Thiết bị từ chối kết nối", "other": "Lỗi kết nối"}.get(kind, "Lỗi kết nối")

    def _read(self, device_id, method):
        with self._lock(device_id), self._connection(device_id) as conn:
            return getattr(conn.driver, method)(conn)

    def running_config(self, device_id):
        return {"device_id": device_id, "content": self._read(device_id, "get_running_config")}

    def interfaces(self, device_id):
        return self._read(device_id, "get_interfaces")

    def routes(self, device_id):
        return self._read(device_id, "get_routes")

    def create_backup(self, device_id, actor=None):
        with self._lock(device_id):
            try:
                content = self._read(device_id, "get_running_config")
            except ConnectionError_ as e:
                msg = self._connection_message(e.kind)
                self.audit.log(actor, "backup_failed", device_id, {"kind": e.kind})
                self.alerts.warning(device_id, msg)
                return {"ok": False, "kind": e.kind, "message": msg}
            with self.db.session() as s:
                row = m.ConfigBackup(device_id=device_id, content=content)
                s.add(row)
                s.flush()
                result = row_dict(row)
                old = s.scalars(select(m.ConfigBackup).where(m.ConfigBackup.device_id == device_id)
                    .order_by(m.ConfigBackup.ts.desc(), m.ConfigBackup.id.desc()).offset(10)).all()
                for item in old:
                    s.delete(item)
        self.audit.log(actor, "backup_create", device_id, {"backup_id": result["id"]})
        return {"ok": True, **result}

    def list_backups(self, device_id):
        with self.db.session() as s:
            require(s, m.Device, device_id)
            return [row_dict(r, ("content",)) for r in s.scalars(select(m.ConfigBackup)
                .where(m.ConfigBackup.device_id == device_id).order_by(m.ConfigBackup.ts.desc(), m.ConfigBackup.id.desc()))]

    def get_backup(self, backup_id):
        with self.db.session() as s:
            return row_dict(require(s, m.ConfigBackup, backup_id))

    def diff(self, a, b):
        left, right = self.get_backup(a), self.get_backup(b)
        if left["device_id"] != right["device_id"]:
            raise ValidationError({"backup": "Hai bản phải thuộc cùng thiết bị"})
        return diff_configs(left["content"], right["content"])

    def _command(self, device_id, command_type, params):
        if command_type not in self.commands:
            raise ValidationError({"command_type": "Thao tác không hợp lệ"})
        with self.db.session() as s:
            require(s, m.Device, device_id)
            cred = s.scalar(select(m.Credential).where(m.Credential.device_id == device_id))
            if not cred:
                raise ValidationError({"credential": "Chưa có thông tin kết nối"})
            driver = DriverFactory.create(cred.driver)
        try:
            return self.commands[command_type](driver, **params)
        except (TypeError, ValueError) as e:
            raise ValidationError({"params": str(e)}) from None

    def preview(self, device_id, command_type, params):
        cmd = self._command(device_id, command_type, params)
        return {"commands": cmd.preview(), "description": cmd.describe()}

    def execute(self, device_id, command_type, params, actor=None):
        cmd = self._command(device_id, command_type, params)
        with self._lock(device_id):
            backup = self.create_backup(device_id, actor)
            if not backup["ok"]:
                return backup
            try:
                with self._connection(device_id) as conn:
                    output = cmd.execute(conn)
            except CommandError as e:
                self.audit.log(actor, "config_command_failed", device_id, {"command_type": command_type})
                return {"ok": False, "kind": "command", "output": e.output}
            with self.db.session() as s:
                row = m.ConfigChange(device_id=device_id, user_id=(actor or {}).get("id"),
                    command_type=command_type, params=cmd.params, forward_cmds=cmd.preview(),
                    undo_cmds=cmd.undo_commands(), output=output)
                s.add(row)
                s.flush()
                result = row_dict(row)
        self.audit.log(actor, "config_command", device_id, {"command_type": command_type, "commands": cmd.preview()})
        return {"ok": True, **result}

    def history(self, device_id):
        with self.db.session() as s:
            require(s, m.Device, device_id)
            items = [row_dict(r) for r in s.scalars(select(m.ConfigChange).where(m.ConfigChange.device_id == device_id)
                .order_by(m.ConfigChange.id.desc()))]
        latest = next((r["id"] for r in items if not r["undone"]), None)
        return [{**r, "can_undo": r["id"] == latest} for r in items]

    def undo(self, change_id, actor=None):
        with self.db.session() as s:
            device_id = require(s, m.ConfigChange, change_id).device_id
        with self._lock(device_id):
            with self.db.session() as s:
                row = require(s, m.ConfigChange, change_id)
                latest = s.scalar(select(m.ConfigChange.id).where(m.ConfigChange.device_id == device_id,
                    m.ConfigChange.undone.is_(False)).order_by(m.ConfigChange.id.desc()).limit(1))
                if latest != change_id:
                    raise ValidationError({"change_id": "Phải hoàn tác thao tác mới nhất trước"})
                commands = list(row.undo_cmds)
            try:
                with self._connection(device_id) as conn:
                    output = _check_config_output(conn.send_config(commands), commands)
            except CommandError as e:
                self.audit.log(actor, "config_undo_failed", change_id)
                return {"ok": False, "kind": "command", "output": e.output}
            with self.db.session() as s:
                row = require(s, m.ConfigChange, change_id)
                row.undone = True
                result = row_dict(row)
        self.audit.log(actor, "config_undo", change_id, {"commands": commands})
        return {"ok": True, "output": output, **result}

    def daily_backups(self):
        with self.db.session() as s:
            ids = list(s.scalars(select(m.Credential.device_id)))
        results = []
        for device_id in ids:
            try:
                results.append(self.create_backup(device_id))
            except Exception:
                self.audit.log(None, "backup_failed", device_id, {"kind": "other"})
        return results
