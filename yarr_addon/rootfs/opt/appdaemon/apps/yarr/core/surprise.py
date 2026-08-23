"""Surprise-film cadence — pure scheduling *decision* only; the actual
AppDaemon run_every call is adapter-side (yarr.py).

Poll-based (adapter checks a persisted next_surprise_at every hour),
not a one-shot run_at: an in-memory run_at timer is lost on any add-on
restart/update, silently pushing the surprise out indefinitely. A
persisted timestamp checked on every poll is restart-safe for free."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import random


@dataclass(frozen=True)
class SurpriseWindow:
    min_days: float = 5.0
    max_days: float = 10.0


def next_surprise_time(now: datetime, window: SurpriseWindow,
                        rng: random.Random = None) -> datetime:
    rng = rng or random.Random()
    return now + timedelta(days=rng.uniform(window.min_days, window.max_days))


def is_surprise_due(now: datetime, scheduled_at) -> bool:
    if scheduled_at is None:
        return True
    if isinstance(scheduled_at, str):
        scheduled_at = datetime.fromisoformat(scheduled_at)
    return now >= scheduled_at
