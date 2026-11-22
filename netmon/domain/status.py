"""Status enum, CheckResult value object and worst-status aggregation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable


class Status(str, Enum):
    UP = "UP"
    WARNING = "WARNING"
    DOWN = "DOWN"
    PAUSED = "PAUSED"
    UNKNOWN = "UNKNOWN"


SEVERITY: dict[Status, int] = {
    Status.UP: 0, Status.PAUSED: 0, Status.UNKNOWN: 1, Status.WARNING: 2, Status.DOWN: 3,
}


def worst(statuses: Iterable[Status]) -> Status:
    """Worst status (FR-15). Empty -> UNKNOWN; all PAUSED -> PAUSED."""
    items = list(statuses)
    if not items:
        return Status.UNKNOWN
    if all(s == Status.PAUSED for s in items):
        return Status.PAUSED
    # PAUSED ranks like UP but must not win over a real UP/other status.
    return max((s for s in items if s != Status.PAUSED), key=SEVERITY.__getitem__)


@dataclass(frozen=True)
class CheckResult:
    status: Status
    value: float | None = None
    message: str = ""
    ts: datetime = field(default_factory=datetime.now)
