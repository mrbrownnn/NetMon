"""DnsSensor: resolve hostname via socket.getaddrinfo (FR-34)."""
from __future__ import annotations

import socket
import time

from netmon.domain.sensors.base import Sensor, SensorFactory
from netmon.domain.status import CheckResult, Status


@SensorFactory.register("dns")
class DnsSensor(Sensor):
    params_schema = {"expected_ip": {"label": "IP mong đợi (tùy chọn)", "type": "str", "default": ""}}

    def check(self) -> CheckResult:
        # ponytail: getaddrinfo uses OS resolver and ignores self.timeout; add dnspython if per-query timeout needed.
        start = time.perf_counter()
        try:
            infos = socket.getaddrinfo(self.target, None)
        except (socket.gaierror, UnicodeError, OSError) as exc:
            return CheckResult(Status.DOWN, None, f"Resolve failed: {exc}")
        ms = self._elapsed_ms(start)
        ips = sorted({i[4][0] for i in infos})
        expected = self.params.get("expected_ip") or ""
        if expected and expected not in ips:
            return CheckResult(Status.DOWN, ms, f"{self.target} -> {', '.join(ips)} (expected {expected})")
        return CheckResult(Status.UP, ms, f"{self.target} -> {', '.join(ips)}")
