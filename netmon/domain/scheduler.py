"""MonitorScheduler (Singleton): runs each sensor every `interval` seconds on a thread pool (FR-35)."""
from __future__ import annotations

import heapq
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from netmon.domain.sensors.base import Sensor
from netmon.domain.status import CheckResult, Status

log = logging.getLogger(__name__)


class MonitorScheduler:
    _instance: "MonitorScheduler | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args: Any, **kw: Any) -> "MonitorScheduler":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, max_workers: int = 16, clock: Callable[[], float] = time.monotonic) -> None:
        with self._instance_lock:
            if self._initialized:
                return
            self._max_workers = max_workers
            self._clock = clock
            self._sensors: dict[int, Sensor] = {}
            self._due: dict[int, float] = {}
            self._heap: list[tuple[float, int]] = []
            self._inflight: set[int] = set()
            self._lock = threading.RLock()
            self._lifecycle_lock = threading.Lock()
            self._wake = threading.Event()
            self._stop = threading.Event()
            self._thread: threading.Thread | None = None
            self._pool: ThreadPoolExecutor | None = None
            self._initialized = True

    @classmethod
    def instance(cls) -> "MonitorScheduler":
        return cls()

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            inst, cls._instance = cls._instance, None
        if inst is not None:
            inst.stop()

    # ---- sensor management ----
    def add_sensor(self, sensor: Sensor, run_immediately: bool = True) -> None:
        if sensor.id is None:
            raise ValueError("sensor must have an id before scheduling")
        with self._lock:
            self._sensors[sensor.id] = sensor
            self._push(sensor.id, self._clock() + (0 if run_immediately else sensor.interval))
        self._wake.set()

    def remove_sensor(self, sensor_id: int) -> None:
        with self._lock:
            self._sensors.pop(sensor_id, None)
            self._due.pop(sensor_id, None)  # stale heap entries are skipped

    def reschedule(self, sensor_id: int) -> None:
        """Call after a sensor's interval changed; next run = now + interval."""
        with self._lock:
            s = self._sensors.get(sensor_id)
            if s is None:
                raise KeyError(sensor_id)
            self._push(sensor_id, self._clock() + s.interval)
        self._wake.set()

    def get_sensor(self, sensor_id: int) -> Sensor | None:
        with self._lock:
            return self._sensors.get(sensor_id)

    def run_now(self, sensor_id: int) -> CheckResult:
        """Run synchronously in the caller's thread (UI 'check now')."""
        s = self.get_sensor(sensor_id)
        if s is None:
            raise KeyError(sensor_id)
        return self._safe_run(s)

    def _push(self, sensor_id: int, due: float) -> None:
        self._due[sensor_id] = due
        heapq.heappush(self._heap, (due, sensor_id))

    # ---- lifecycle ----
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                if self.running:
                    return
                self._stop.clear()
                self._pool = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="sensor")
                self._thread = threading.Thread(target=self._loop, name="monitor-scheduler", daemon=True)
                self._thread.start()

    def stop(self, wait: bool = True) -> None:
        with self._lifecycle_lock:
            with self._lock:
                self._stop.set()
                self._wake.set()
                thread, pool = self._thread, self._pool
                self._pool = None
            if thread is not None and thread is not threading.current_thread():
                thread.join()
            if pool is not None:
                pool.shutdown(wait=wait, cancel_futures=True)
            self._thread = None

    def stats(self) -> dict[str, Any]:
        return {"running": self.running, "sensor_count": len(self._sensors),
                "threads": self._max_workers if self.running else 0, "in_flight": len(self._inflight)}

    # ---- loop ----
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                timeout = self.tick()
            except Exception:  # never let the loop die
                log.exception("scheduler tick failed")
                timeout = 1.0
            self._wake.wait(timeout)
            self._wake.clear()

    def tick(self) -> float:
        """Submit all due sensors; return seconds until next due item (capped at 1s)."""
        now = self._clock()
        due: list[Sensor] = []
        with self._lock:
            while self._heap and self._heap[0][0] <= now:
                t, sid = heapq.heappop(self._heap)
                if self._due.get(sid) != t or sid not in self._sensors:
                    continue  # stale entry (removed or rescheduled)
                s = self._sensors[sid]
                self._push(sid, now + s.interval)
                if sid not in self._inflight:  # skip if previous run still going
                    self._inflight.add(sid)
                    due.append(s)
            nxt = self._heap[0][0] - now if self._heap else 1.0
            for s in due:
                if self._stop.is_set():
                    self._inflight.discard(s.id)
                elif self._pool is not None:
                    try:
                        future = self._pool.submit(self._run_and_release, s)
                        future.add_done_callback(lambda f, sid=s.id: self._release(sid) if f.cancelled() else None)
                    except RuntimeError:
                        self._inflight.discard(s.id)
                        raise
            inline = self._pool is None and not self._stop.is_set()
        if inline:
            for s in due:
                self._run_and_release(s)
        return max(0.0, min(nxt, 1.0))

    def _run_and_release(self, s: Sensor) -> CheckResult:
        try:
            with self._lock:
                if self._sensors.get(s.id) is not s or self._stop.is_set():
                    return CheckResult(Status.UNKNOWN, None, "Sensor removed or scheduler stopped")
            return self._safe_run(s)
        finally:
            self._release(s.id)

    def _release(self, sensor_id: int) -> None:
        with self._lock:
            self._inflight.discard(sensor_id)

    @staticmethod
    def _safe_run(sensor: Sensor) -> CheckResult:
        try:
            return sensor.run()
        except Exception as exc:  # run() already guards check(); this guards observers etc.
            log.exception("sensor %s run failed", sensor.id)
            return CheckResult(Status.UNKNOWN, None, f"Run error: {exc}")
