"""Pure detection logic for stuck/dead entries in Radarr's or Sonarr's
own download queue — see clients/radarr.py's/sonarr.py's get_queue().
No network calls here (mirrors core/junk.py's/core/dupes.py's split)."""

from datetime import datetime


def find_stuck_downloads(queue_items: list, now: datetime, max_age_hours: float) -> list:
    """An item is stuck if:

    - it has a non-empty errorMessage — confirmed against a real
      instance that this is the ONLY reliable error signal: Sonarr kept
      `status: "downloading"` and `trackedDownloadStatus: "ok"` even on
      items with errorMessage "Corrupt RAR file" or SABnzbd's own
      "Aborted, cannot be completed" (a dead NZB with missing articles)
      — status/trackedDownloadStatus are checked too, as a defensive
      fallback for Sonarr/Radarr versions that behave differently, but
      errorMessage is what actually catches a dead download in practice;
    - (Sonarr only) it has no resolved episode at all — "episode_id" is
      present in the item but null, meaning Sonarr could never work out
      which episode this release even is. That will never resolve no
      matter how long it sits, regardless of age or error status. Movie
      queue items never carry this key at all, so this never applies to
      Radarr; presence of the key, not just its value, is what scopes
      this to Sonarr items;
    - or it's simply been queued longer than max_age_hours with no
      sign of either of the above (a slow but genuinely progressing
      download would still trip this eventually — the threshold is
      deliberately generous, and Settings-tab editable, so it can be
      raised for a slow connection/indexer). Missing an "added"
      timestamp (a real Radarr/Sonarr API-version difference, not an
      error) means age can't be judged — such an item is only flagged
      via the two checks above, never guessed at."""
    stuck = []
    for item in queue_items:
        is_error = (bool(item.get("error_message"))
                    or item.get("tracked_download_status") == "error"
                    or item.get("status") in ("failed", "warning"))
        is_unmatched = "episode_id" in item and item.get("episode_id") is None
        is_old = False
        added = item.get("added")
        if added:
            try:
                age_hours = (now - datetime.fromisoformat(added.replace("Z", "+00:00"))
                             ).total_seconds() / 3600
                is_old = age_hours >= max_age_hours
            except ValueError:
                pass
        if is_error or is_unmatched or is_old:
            reason = "error" if is_error else ("unmatched" if is_unmatched else "stalled")
            stuck.append({**item, "stuck_reason": reason})
    return stuck
