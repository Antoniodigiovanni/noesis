from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ScheduleResult:
    state: dict[str, Any]
    next_due: datetime
    explanation: dict[str, Any]


class Scheduler(Protocol):
    version: str

    def schedule(self, state: dict[str, Any] | None, grade: int, reviewed_at: datetime, desired_retention: float) -> ScheduleResult: ...

