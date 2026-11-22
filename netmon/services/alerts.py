"""Alert queries and secret-safe notification channel configuration."""
from datetime import datetime
from sqlalchemy import select

from netmon.domain.alerts import Alert, AlertLevel, AlertState, EmailNotifier, LogNotifier, TelegramNotifier
from netmon.domain.status import Status
from netmon.infra.db import Alert as AlertRow, NotifierChannel
from .common import date, paginate, require, row_dict
from .errors import ValidationError


class AlertService:
    def __init__(self, db, audit, crypto, publisher, repository):
        self.db, self.audit, self.crypto = db, audit, crypto
        self.publisher, self.repository = publisher, repository
        self.manager = None
        with db.session() as s:
            for name in ("web", "log", "email", "telegram"):
                if not s.get(NotifierChannel, name):
                    s.add(NotifierChannel(name=name, enabled=name in ("web", "log")))

    def list(self, state=None, level=None, from_=None, to=None, page=1, device_id=None):
        with self.db.session() as s:
            q = select(AlertRow).order_by(AlertRow.opened_at.desc(), AlertRow.id.desc())
            for col, val in ((AlertRow.state, state), (AlertRow.level, level), (AlertRow.device_id, device_id)):
                if val not in (None, ""):
                    q = q.where(col == val)
            if from_:
                q = q.where(AlertRow.opened_at >= date(from_))
            if to:
                q = q.where(AlertRow.opened_at <= date(to))
            items = [self._public(r) for r in s.scalars(q)]
        return {**paginate(items, page), "open_count": self.open_count()}

    def _public(self, row):
        return {**row_dict(row), "created_at": row.opened_at.isoformat(),
                "status": row.new_status, "acked_by": row.ack_by,
                "acked_at": row.ack_at.isoformat() if row.ack_at else None}

    def open_count(self):
        from sqlalchemy import func
        with self.db.session() as s:
            return s.scalar(select(func.count()).select_from(AlertRow).where(AlertRow.state != "RESOLVED"))

    def on_change(self, event, alert):
        with self.db.session() as s:
            row = require(s, AlertRow, alert.id)
            payload = self._public(row)
            web = require(s, NotifierChannel, "web").enabled
        if web:
            self.publisher(event, {"open_count": self.open_count(), "alert": payload})

    def ack(self, alert_id, note="", actor=None):
        try:
            alert = self.manager.acknowledge(alert_id, (actor or {}).get("username", "system"), note)
        except ValueError as e:
            raise ValidationError({"state": str(e)}) from None
        self.audit.log(actor, "alert_ack", alert_id, {"note": note})
        return alert.to_dict()

    def warning(self, device_id, message):
        alert = Alert(None, device_id, AlertLevel.WARNING, message, Status.WARNING, "Backup")
        self.repository.add(alert)
        self.on_change("alert_opened", alert)
        self.manager.dispatch(alert)
        return alert.to_dict()

    def channels(self):
        with self.db.session() as s:
            items = [row_dict(r) for r in s.scalars(select(NotifierChannel))]
        for item in items:
            item["config"] = {k: "********" if k in ("password", "token") and v else v for k, v in item["config"].items()}
        return items

    def _notifier(self, name, config, enabled=True):
        config = dict(config)
        for key in ("password", "token"):
            if config.get(key):
                config[key] = self.crypto.decrypt(config[key])
        try:
            if name == "log":
                return LogNotifier(enabled=enabled)
            if name == "email":
                return EmailNotifier(enabled=enabled, **config)
            if name == "telegram":
                return TelegramNotifier(enabled=enabled, **config)
        except TypeError:
            raise ValidationError({"config": "Cấu hình kênh không hợp lệ"}) from None

    def reload_notifiers(self):
        notifiers = []
        with self.db.session() as s:
            rows = [row_dict(r) for r in s.scalars(select(NotifierChannel))]
        for r in rows:
            if r["enabled"] and r["name"] != "web":
                n = self._notifier(r["name"], r["config"])
                if n:
                    notifiers.append(n)
        if self.manager:
            self.manager.notifiers = notifiers
        return notifiers

    def update_channel(self, name, enabled, config=None, actor=None):
        allowed = {"web": set(), "log": set(),
            "email": {"host", "port", "sender", "recipients", "username", "password", "use_tls", "timeout"},
            "telegram": {"token", "chat_id", "timeout"}}
        if name not in allowed:
            raise ValidationError({"name": "Kênh không hợp lệ"})
        config = config or {}
        if set(config) - allowed[name]:
            raise ValidationError({"config": "Tham số không hợp lệ"})
        with self.db.session() as s:
            row = require(s, NotifierChannel, name)
            values = dict(row.config)
            for k, v in config.items():
                if k in ("password", "token"):
                    if v == "********":
                        continue
                    v = self.crypto.encrypt(str(v)) if v else ""
                values[k] = v
            if enabled and name != "web":
                self._notifier(name, values)
            row.enabled, row.config = bool(enabled), values
        self.reload_notifiers()
        self.audit.log(actor, "notifier_update", name)
        return next(r for r in self.channels() if r["name"] == name)

    def send_test(self, name, actor=None):
        with self.db.session() as s:
            row = require(s, NotifierChannel, name)
            config = dict(row.config)
        try:
            if name == "web":
                self.publisher("alert_opened", {"open_count": self.open_count(), "alert": {
                    "level": "INFO", "message": "NetMon test notification", "state": "RESOLVED"}})
            else:
                self._notifier(name, config).send_test()
            result = {"ok": True, "message": "Đã gửi thử"}
        except Exception:
            # Third-party errors can include credentials or token-bearing URLs.
            result = {"ok": False, "message": "Gửi thử thất bại; kiểm tra cấu hình kênh"}
        with self.db.session() as s:
            row = require(s, NotifierChannel, name)
            row.last_test_at, row.last_test_result = datetime.now(), result["message"]
        self.audit.log(actor, "notifier_test", name, result)
        return result
