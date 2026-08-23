from datetime import datetime, timedelta, timezone

from core.delete_guard import schedule, is_due
from core.state import PendingDeletion


def test_schedule_computes_delete_at():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    delete_at = schedule(now, grace_hours=24)
    assert delete_at == (now + timedelta(hours=24)).isoformat()


def test_is_due_true_once_past_delete_at():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pending = PendingDeletion(delete_at=(now - timedelta(seconds=1)).isoformat())
    assert is_due(pending, now) is True


def test_is_due_false_before_delete_at():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pending = PendingDeletion(delete_at=(now + timedelta(seconds=1)).isoformat())
    assert is_due(pending, now) is False


def test_is_due_false_when_keep_requested_even_if_time_passed():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pending = PendingDeletion(delete_at=(now - timedelta(hours=1)).isoformat(), keep_requested=True)
    assert is_due(pending, now) is False
