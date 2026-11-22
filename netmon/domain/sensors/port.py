"""PortSensor: TCP connect within timeout (FR-32)."""
from __future__ import annotations

import socket
import time

from netmon.domain.sensors.base import Sensor, SensorFactory
from netmon.domain.status import CheckResult, Status


@SensorFactory.register("port")
class PortSensor(Sensor):
    params_schema = {"port": {"label": "Port", "type": "int", "default": 22}}

    def check(self) -> CheckResult:
        port = int(self.params.get("port") or 0)
        if not 1 <= port <= 65535:
            return CheckResult(Status.UNKNOWN, None, f"Invalid port: {port}")
        start = time.perf_counter()
        try:
            with socket.create_connection((self.target, port), timeout=self.timeout):
                pass
        except OSError as exc:
            return CheckResult(Status.DOWN, None, f"TCP {port} closed: {exc}")
        ms = self._elapsed_ms(start)
        return CheckResult(Status.UP, ms, f"TCP {port} open ({ms:g} ms)")
