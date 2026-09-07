"""Pure detection logic for stuck/dead entries in Radarr's or Sonarr's
own download queue — see clients/radarr.py's/sonarr.py's get_queue().
No network calls here (mirrors core/junk.py's/core/dupes.py's split)."""

from datetime import datetime


def find_stuck_downloads(queue_items: list, now: datetime, max_age_hours: float) -> list:
    """An item is stuck if Radarr/Sonarr itself already reports an error
    status (a dead/incomplete NZB usually surfaces this way once the
    download client's own post-processing gives up), or if it's simply
    been in the queue longer than max_age_hours with no sign of that (a
    slow but genuinely progressing download would still trip this
    eventually — the threshold is deliberately generous, and Settings-
    tab editable, so it can be raised for a slow connection/indexer).
    Missing an "added" timestamp (a real Radarr/Sonarr API-version
    difference, not an error) means age can't be judged — such an item
    is only flagged if it's already in an error state, never guessed at."""
    stuck = []
    for item in queue_items:
        is_error = item.get("tracked_download_status") == "error" or item.get("status") in (
            "failed", "warning")
        is_old = False
        added = item.get("added")
        if added:
            try:
                age_hours = (now - datetime.fromisoformat(added.replace("Z", "+00:00"))
                             ).total_seconds() / 3600
                is_old = age_hours >= max_age_hours
            except ValueError:
                pass
        if is_error or is_old:
            stuck.append({**item, "stuck_reason": "error" if is_error else "stalled"})
    return stuck
