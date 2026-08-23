import random
from datetime import datetime, timedelta, timezone

from core.surprise import SurpriseWindow, next_surprise_time, is_surprise_due


def test_next_surprise_time_within_window():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    window = SurpriseWindow(min_days=5, max_days=10)
    rng = random.Random(7)
    for _ in range(50):
        t = next_surprise_time(now, window, rng=rng)
        assert now + timedelta(days=5) <= t <= now + timedelta(days=10)


def test_is_surprise_due_when_none():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert is_surprise_due(now, None) is True


def test_is_surprise_due_boundary():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert is_surprise_due(now, now) is True
    assert is_surprise_due(now, now - timedelta(seconds=1)) is True
    assert is_surprise_due(now, now + timedelta(seconds=1)) is False


def test_is_surprise_due_accepts_iso_string():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    future = (now + timedelta(days=1)).isoformat()
    assert is_surprise_due(now, future) is False
