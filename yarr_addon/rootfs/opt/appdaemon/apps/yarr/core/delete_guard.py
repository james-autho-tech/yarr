"""Grace-period delete safety net — pure, poll-based (not a one-shot
timer) so an add-on restart mid-grace-period can't silently drop or
skip a pending deletion: tick_delete_guard just re-checks the persisted
delete_at timestamp on its next 15-minute pass."""

from datetime import datetime, timedelta


def schedule(now: datetime, grace_hours: float) -> str:
    return (now + timedelta(hours=grace_hours)).isoformat()


def is_due(pending, now: datetime) -> bool:
    if pending.keep_requested:
        return False
    return now >= datetime.fromisoformat(pending.delete_at)
