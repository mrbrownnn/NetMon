"""Alerts (FR-40..43): Alert entity, AlertManager observer, notification channels."""
from __future__ import annotations

import json
import logging
import smtplib
import threading
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from enum import Enum
from typing import Any, Callable

from netmon.domain.repositories import InMemoryRepository, Repository
from netmon.domain.status import CheckResult, Status

log = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertState(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


LEVEL_FOR_STATUS = {Status.DOWN: AlertLevel.CRITICAL, Status.WARNING: AlertLevel.WARNING,
                    Status.UP: AlertLevel.INFO}


@dataclass
class Alert:
    sensor_id: int | None
    device_id: int | None
    level: AlertLevel
    message: str
    status: Status
    sensor_name: str = ""
    id: int | None = None
    state: AlertState = AlertState.OPEN
    created_at: datetime = field(default_factory=datetime.now)
    acked_by: str | None = None
    ack_note: str = ""
    acked_at: datetime | None = None
    resolved_at: datetime | None = None

    def ack(self, user: str, note: str = "") -> None:
        if self.state == AlertState.RESOLVED:
            raise ValueError("cannot acknowledge a resolved alert")
        self.state, self.acked_by, self.ack_note, self.acked_at = AlertState.ACKNOWLEDGED, user, note, datetime.now()

    def resolve(self) -> None:
        if self.state != AlertState.RESOLVED:
            self.state, self.resolved_at = AlertState.RESOLVED, datetime.now()

    def to_dict(self) -> dict[str, Any]:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"id": self.id, "sensor_id": self.sensor_id, "device_id": self.device_id,
                "sensor_name": self.sensor_name, "level": self.level.value, "state": self.state.value,
                "status": self.status.value, "message": self.message, "created_at": iso(self.created_at),
                "acked_by": self.acked_by, "ack_note": self.ack_note, "acked_at": iso(self.acked_at),
                "resolved_at": iso(self.resolved_at)}


# ---------------- notifiers ----------------
class Notifier(ABC):
    name: str = "notifier"

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    @abstractmethod
    def send(self, alert: Alert) -> None: ...

    def send_test(self) -> None:
        """Send a sample alert regardless of `enabled`; raises on failure (UI shows error)."""
        self.send(Alert(None, None, AlertLevel.INFO, "NetMon test notification", Status.UP, "test"))

    @staticmethod
    def format(alert: Alert) -> str:
        return f"[{alert.level.value}] {alert.sensor_name or alert.sensor_id}: {alert.status.value} - {alert.message}"


class LogNotifier(Notifier):
    name = "log"

    def __init__(self, enabled: bool = True, logger: logging.Logger | None = None) -> None:
        super().__init__(enabled)
        self.logger = logger or logging.getLogger("netmon.alerts")

    def send(self, alert: Alert) -> None:
        lvl = {AlertLevel.CRITICAL: logging.ERROR, AlertLevel.WARNING: logging.WARNING}.get(alert.level, logging.INFO)
        self.logger.log(lvl, self.format(alert))


class WebNotifier(Notifier):
    """Pushes alerts to the web layer through a publisher(event, data) callback."""
    name = "web"

    def __init__(self, publisher: Callable[[str, dict], None], enabled: bool = True) -> None:
        super().__init__(enabled)
        self.publisher = publisher

    def send(self, alert: Alert) -> None:
        self.publisher("alert_opened", alert.to_dict())


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, host: str, port: int = 587, sender: str = "", recipients: list[str] | None = None,
                 username: str = "", password: str = "", use_tls: bool = True, timeout: float = 10,
                 enabled: bool = True) -> None:
        super().__init__(enabled)
        self.host, self.port, self.sender = host, port, sender
        self.recipients = recipients or []
        self.username, self._password, self.use_tls, self.timeout = username, password, use_tls, timeout

    def send(self, alert: Alert) -> None:
        if not self.recipients:
            raise ValueError("no email recipients configured")
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = self.format(alert), self.sender, ", ".join(self.recipients)
        msg.set_content(f"{self.format(alert)}\nTime: {alert.created_at:%Y-%m-%d %H:%M:%S}")
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self._password)
            smtp.send_message(msg)


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, token: str, chat_id: str, enabled: bool = True, timeout: float = 10) -> None:
        super().__init__(enabled)
        self._token, self.chat_id, self.timeout = token, chat_id, timeout

    def send(self, alert: Alert) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": self.format(alert)}).encode()
        with urllib.request.urlopen(url, data=data, timeout=self.timeout) as resp:  # noqa: S310
            body = json.loads(resp.read() or b"{}")
        if not body.get("ok", False):
            raise RuntimeError(f"telegram error: {body.get('description', body)}")


# ---------------- manager ----------------
class AlertManager:
    """SensorObserver: one alert per status change (FR-40), auto-resolve on UP (FR-42)."""

    def __init__(self, repository: Repository[Alert] | None = None, notifiers: list[Notifier] | None = None,
                 on_change: Callable[[str, Alert], None] | None = None) -> None:
        self.repository = repository if repository is not None else InMemoryRepository()
        self.notifiers: list[Notifier] = notifiers or []
        self.on_change = on_change  # (event "alert_opened"|"alert_updated", alert)
        self._lock = threading.RLock()

    def on_result(self, sensor: Any, result: CheckResult) -> None:
        pass

    def on_status_changed(self, sensor: Any, old: Status, result: CheckResult) -> None:
        new = result.status
        if new not in LEVEL_FOR_STATUS:  # PAUSED / UNKNOWN never alert (FR-36)
            return
        with self._lock:
            opened = self.open_alerts(sensor.id)
            if new == old or (new == Status.UP and old in (Status.UNKNOWN, Status.PAUSED) and not opened):
                return  # startup / resume without an outstanding alert is not recovery
            for a in opened:  # superseded or recovered
                a.resolve()
                self.repository.update(a)
                self._emit("alert_updated", a)
            alert = Alert(sensor.id, getattr(sensor, "device_id", None), LEVEL_FOR_STATUS[new],
                          result.message, new, getattr(sensor, "name", ""))
            if new == Status.UP:
                alert.resolve()  # recovery notice is informational only
            self.repository.add(alert)
            self._emit("alert_opened", alert)
        self.dispatch(alert)

    def open_alerts(self, sensor_id: int | None = None) -> list[Alert]:
        return [a for a in self.repository.list() if a.state != AlertState.RESOLVED
                and (sensor_id is None or a.sensor_id == sensor_id)]

    def acknowledge(self, alert_id: int, user: str, note: str = "") -> Alert:
        with self._lock:
            alert = self.repository.get(alert_id)
            if alert is None:
                raise KeyError(alert_id)
            alert.ack(user, note)
            self.repository.update(alert)
            self._emit("alert_updated", alert)
            return alert

    def dispatch(self, alert: Alert) -> dict[str, str]:
        """Send to every enabled notifier; a failing channel is logged and skipped (FR-43)."""
        results: dict[str, str] = {}
        for n in self.notifiers:
            if not n.enabled:
                continue
            try:
                n.send(alert)
                results[n.name] = "ok"
            except Exception as exc:
                # Transport exceptions may contain credentials or token-bearing URLs.
                log.error("notifier %s failed (%s)", n.name, type(exc).__name__)
                results[n.name] = "error: notification failed"
        return results

    def _emit(self, event: str, alert: Alert) -> None:
        if self.on_change:
            try:
                self.on_change(event, alert)
            except Exception:
                log.exception("alert on_change callback failed")
