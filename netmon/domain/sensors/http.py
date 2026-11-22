"""HttpSensor: GET url; DOWN unless 2xx/3xx; optional body 'contains' check (FR-33)."""
from __future__ import annotations

import time
import urllib.error
import urllib.request

from netmon.domain.sensors.base import Sensor, SensorFactory
from netmon.domain.status import CheckResult, Status


@SensorFactory.register("http")
class HttpSensor(Sensor):
    params_schema = {"contains": {"label": "Nội dung phải chứa", "type": "str", "default": ""}}

    def check(self) -> CheckResult:
        url = self.target if "://" in self.target else f"http://{self.target}"
        if not url.lower().startswith(("http://", "https://")):
            return CheckResult(Status.UNKNOWN, None, f"Unsupported URL: {url}")
        start = time.perf_counter()
        try:
            # ponytail: urllib follows redirects, so 3xx usually resolves to the final code.
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:  # noqa: S310 (scheme checked)
                code, body = resp.status, resp.read(1_000_000)
        except urllib.error.HTTPError as exc:
            code, body = exc.code, b""
        except (urllib.error.URLError, OSError) as exc:
            return CheckResult(Status.DOWN, None, f"HTTP error: {getattr(exc, 'reason', exc)}")
        ms = self._elapsed_ms(start)
        if not 200 <= code < 400:
            return CheckResult(Status.DOWN, ms, f"HTTP {code}")
        needle = self.params.get("contains") or ""
        if needle and needle not in body.decode("utf-8", errors="replace"):
            return CheckResult(Status.DOWN, ms, f"HTTP {code}, missing text {needle!r}")
        return CheckResult(Status.UP, ms, f"HTTP {code} ({ms:g} ms)")
