"""PingSensor: OS `ping` via subprocess; RTT (ms) and packet loss (FR-31)."""
from __future__ import annotations

import re
import subprocess
import sys

from netmon.domain.sensors.base import Sensor, SensorFactory
from netmon.domain.status import CheckResult, Status

LOSS_WARNING_PCT = 20.0
# Regexes are ASCII-only so they work on English/Vietnamese Windows and Linux output
# regardless of console code page.
_LINUX_RTT = re.compile(r"=\s*[\d.]+/([\d.]+)/")              # rtt min/avg/max/mdev = a/b/c/d ms
_WIN_RTT = re.compile(r"[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.I)    # last match = Average / Trung binh
_LOSS = re.compile(r"(\d+(?:[.,]\d+)?)\s*%(?!\d)")


def parse_ping_output(text: str) -> tuple[float | None, float | None]:
    """Return (avg_rtt_ms, loss_pct); None when not found."""
    loss_m = _LOSS.search(text)
    loss = float(loss_m.group(1).replace(",", ".")) if loss_m else None
    m = _LINUX_RTT.search(text)
    if m:
        return float(m.group(1)), loss
    rtts = _WIN_RTT.findall(text)
    return (float(rtts[-1]) if rtts else None), loss


@SensorFactory.register("ping")
class PingSensor(Sensor):
    params_schema = {"count": {"label": "Số gói", "type": "int", "default": 3}}

    def _command(self) -> list[str]:
        count = str(max(1, int(self.params.get("count") or 3)))
        if sys.platform.startswith("win"):
            return ["ping", "-n", count, "-w", str(int(self.timeout * 1000)), self.target]
        return ["ping", "-c", count, "-W", str(max(1, int(self.timeout))), self.target]

    def check(self) -> CheckResult:
        cmd = self._command()
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=self.timeout * int(cmd[2]) + 5)
        except subprocess.TimeoutExpired:
            return CheckResult(Status.DOWN, None, "Ping timed out")
        except OSError as exc:
            return CheckResult(Status.UNKNOWN, None, f"Cannot run ping: {exc}")
        text = proc.stdout.decode("utf-8", errors="replace")
        rtt, loss = parse_ping_output(text)
        if rtt is None or loss is None or loss >= 100:
            return CheckResult(Status.DOWN, None, f"No reply from {self.target}")
        msg = f"RTT {rtt:g} ms, loss {loss:g}%"
        if loss > LOSS_WARNING_PCT:
            return CheckResult(Status.WARNING, rtt, msg)
        return CheckResult(Status.UP, rtt, msg)
