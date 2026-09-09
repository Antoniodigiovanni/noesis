from __future__ import annotations

from datetime import datetime, timezone

from fsrs import Card, Rating, Scheduler as FsrsScheduler

from noesis.scheduler.interface import ScheduleResult


class FsrsAdapter:
    version = "fsrs-6.3.2"

    def schedule(self, state: dict | None, grade: int, reviewed_at: datetime, desired_retention: float) -> ScheduleResult:
        # SQLite returns naive values even for DateTime(timezone=True); the
        # persistence contract stores every timestamp as UTC.
        if reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
        card = Card.from_dict(state) if state else Card(card_id=0, due=reviewed_at)
        scheduler = FsrsScheduler(desired_retention=desired_retention, enable_fuzzing=False)
        updated, _log = scheduler.review_card(card, Rating(grade), review_datetime=reviewed_at)
        return ScheduleResult(
            state=updated.to_dict(),
            next_due=updated.due,
            explanation={
                "algorithm": self.version,
                "grade": Rating(grade).name,
                "desired_retention": desired_retention,
                "stability": updated.stability,
                "difficulty": updated.difficulty,
            },
        )
