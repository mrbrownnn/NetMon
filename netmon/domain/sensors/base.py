"""Sensor base class (Template Method + Observer subject) and SensorFactory registry."""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, ClassVar, Protocol

from netmon.domain.status import CheckResult, Status

log = logging.getLogger(__name__)

INTERVAL_MIN, INTERVAL_MAX = 10, 3600


class SensorObserver(Protocol):
    def on_status_changed(self, sensor: "Sensor", old: Status, result: CheckResult) -> None: ...
    def on_result(self, sensor: "Sensor", result: CheckResult) -> None: ...


class Sensor(ABC):
    type_name: ClassVar[str] = ""
    params_schema: ClassVar[dict[str, dict]] = {}  # name -> {label, type, default}

    def __init__(self, id: int | None, device_id: int, name: str, target: str, interval: int = 30,
                 timeout: float = 5.0, warning_threshold: float | None = None, down_after: int = 3,
                 params: dict | None = None, paused: bool = False) -> None:
        self.id, self.device_id = id, device_id
        self.name, self.target = name, target
        self.interval, self.timeout = interval, timeout
        self.warning_threshold, self.down_after = warning_threshold, down_after
        self.params = params or {}
        self._paused = paused
        self._status = Status.PAUSED if paused else Status.UNKNOWN
        self._last_result: CheckResult | None = None
        self._failures = 0
        self._observers: list[SensorObserver] = []
        self._lock = threading.RLock()

    # ---- validated properties (encapsulation) ----
    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        if not value or not str(value).strip():
            raise ValueError("name is required")
        self._name = str(value).strip()

    @property
    def target(self) -> str:
        return self._target

    @target.setter
    def target(self, value: str) -> None:
        if not value or not str(value).strip():
            raise ValueError("target is required")
        self._target = str(value).strip()

    @property
    def interval(self) -> int:
        return self._interval

    @interval.setter
    def interval(self, value: int) -> None:
        value = int(value)
        if not INTERVAL_MIN <= value <= INTERVAL_MAX:
            raise ValueError(f"interval must be {INTERVAL_MIN}-{INTERVAL_MAX} seconds")
        self._interval = value

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        value = float(value)
        if value <= 0:
            raise ValueError("timeout must be > 0")
        self._timeout = value

    @property
    def warning_threshold(self) -> float | None:
        return self._warning_threshold

    @warning_threshold.setter
    def warning_threshold(self, value: float | None) -> None:
        if value is not None and float(value) < 0:
            raise ValueError("warning_threshold must be >= 0")
        self._warning_threshold = None if value is None else float(value)

    @property
    def down_after(self) -> int:
        return self._down_after

    @down_after.setter
    def down_after(self, value: int) -> None:
        if int(value) < 1:
            raise ValueError("down_after must be >= 1")
        self._down_after = int(value)

    @property
    def params(self) -> dict[str, Any]:
        return self._params

    @params.setter
    def params(self, value: dict | None) -> None:
        merged = {k: f.get("default") for k, f in self.params_schema.items()}
        merged.update(value or {})
        self._params = merged

    @property
    def status(self) -> Status:
        return self._status

    @property
    def last_result(self) -> CheckResult | None:
        return self._last_result

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def consecutive_failures(self) -> int:
        return self._failures

    # ---- observer ----
    def attach(self, observer: SensorObserver) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: SensorObserver) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    def _notify(self, method: str, *args: Any) -> None:
        for o in list(self._observers):
            try:
                getattr(o, method)(self, *args)
            except Exception:  # one bad observer must not break the others
                log.exception("observer %r failed in %s", o, method)

    # ---- lifecycle ----
    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self._failures = 0
            self._update_status(CheckResult(Status.PAUSED, None, "Paused"))

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._update_status(CheckResult(Status.UNKNOWN, None, "Resumed"))

    # ---- template method ----
    def run(self) -> CheckResult:
        with self._lock:
            if self._paused:
                self._last_result = CheckResult(Status.PAUSED, None, "Paused")
                return self._last_result
            try:
                result = self.check()
            except Exception as exc:
                log.exception("sensor %s check failed", self.id)
                result = CheckResult(Status.UNKNOWN, None, f"Check error: {exc}")
            result = self._count_failures(self._apply_threshold(result))
            self._last_result = result
            self._update_status(result)
        self._notify("on_result", result)
        return result

    @abstractmethod
    def check(self) -> CheckResult: ...

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)

    def _apply_threshold(self, result: CheckResult) -> CheckResult:
        t = self._warning_threshold
        if result.status == Status.UP and t is not None and result.value is not None and result.value > t:
            return CheckResult(Status.WARNING, result.value,
                               f"{result.message} (> threshold {t:g})".strip(), result.ts)
        return result

    def _count_failures(self, result: CheckResult) -> CheckResult:
        if result.status != Status.DOWN:
            self._failures = 0
            return result
        self._failures += 1
        if self._failures >= self._down_after:
            return result
        # Not DOWN yet: keep previous status, record the failure message.
        return CheckResult(self._status, result.value,
                           f"{result.message} (fail {self._failures}/{self._down_after})", result.ts)

    def _update_status(self, result: CheckResult) -> None:
        """Only place status changes, so observers always get the event."""
        if result.status != self._status:
            old, self._status = self._status, result.status
            self._notify("on_status_changed", old, result)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id} {self.name!r} {self.status.value}>"


class SensorFactory:
    _registry: ClassVar[dict[str, type[Sensor]]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[type[Sensor]], type[Sensor]]:
        def deco(klass: type[Sensor]) -> type[Sensor]:
            klass.type_name = name
            cls._registry[name] = klass
            return klass
        return deco

    @classmethod
    def create(cls, type_name: str, **kw: Any) -> Sensor:
        try:
            klass = cls._registry[type_name]
        except KeyError:
            raise ValueError(f"unknown sensor type: {type_name}") from None
        return klass(**kw)

    @classmethod
    def types(cls) -> dict[str, type[Sensor]]:
        return dict(cls._registry)
