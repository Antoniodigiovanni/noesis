from datetime import datetime, timezone

from noesis.scheduler.fsrs_adapter import FsrsAdapter


def test_fsrs_fixed_clock_is_deterministic():
    adapter = FsrsAdapter()
    now = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    first = adapter.schedule(None, 3, now, 0.9)
    second = adapter.schedule(None, 3, now, 0.9)
    assert first.state == second.state
    assert first.next_due == second.next_due
    assert first.explanation["algorithm"] == "fsrs-6.3.2"

