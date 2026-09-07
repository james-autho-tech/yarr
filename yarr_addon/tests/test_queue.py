from datetime import datetime, timedelta, timezone

from core.queue import find_stuck_downloads


def test_flags_error_status_item_regardless_of_age():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "Some Release", "added": now.isoformat(),
              "status": "downloading", "tracked_download_status": "error"}]
    stuck = find_stuck_downloads(items, now, max_age_hours=12.0)
    assert len(stuck) == 1
    assert stuck[0]["stuck_reason"] == "error"


def test_flags_failed_status_even_without_tracked_download_status():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "Some Release", "added": now.isoformat(), "status": "failed"}]
    stuck = find_stuck_downloads(items, now, max_age_hours=12.0)
    assert len(stuck) == 1
    assert stuck[0]["stuck_reason"] == "error"


def test_flags_old_item_with_no_error_as_stalled():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    added = (now - timedelta(hours=20)).isoformat()
    items = [{"id": 1, "title": "Some Release", "added": added,
              "status": "downloading", "tracked_download_status": "ok"}]
    stuck = find_stuck_downloads(items, now, max_age_hours=12.0)
    assert len(stuck) == 1
    assert stuck[0]["stuck_reason"] == "stalled"


def test_ignores_recent_healthy_item():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    added = (now - timedelta(hours=1)).isoformat()
    items = [{"id": 1, "title": "Some Release", "added": added,
              "status": "downloading", "tracked_download_status": "ok"}]
    assert find_stuck_downloads(items, now, max_age_hours=12.0) == []


def test_ignores_old_item_when_added_missing_and_no_error():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "Some Release", "added": None,
              "status": "downloading", "tracked_download_status": "ok"}]
    assert find_stuck_downloads(items, now, max_age_hours=12.0) == []


def test_unparseable_added_is_handled_gracefully():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "Some Release", "added": "not-a-date",
              "status": "downloading", "tracked_download_status": "ok"}]
    assert find_stuck_downloads(items, now, max_age_hours=12.0) == []


def test_empty_list_returns_empty():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert find_stuck_downloads([], now, max_age_hours=12.0) == []


def test_boundary_age_exactly_at_threshold_is_flagged():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    added = (now - timedelta(hours=12)).isoformat()
    items = [{"id": 1, "title": "Some Release", "added": added,
              "status": "downloading", "tracked_download_status": "ok"}]
    stuck = find_stuck_downloads(items, now, max_age_hours=12.0)
    assert len(stuck) == 1


def test_flags_nonempty_error_message_even_when_status_and_tracked_status_are_healthy():
    # Confirmed against a real Sonarr instance: status stayed
    # "downloading" and trackedDownloadStatus stayed "ok" on an item
    # with errorMessage "Corrupt RAR file" — errorMessage is the only
    # signal that actually caught it.
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "Monk S04E06", "added": now.isoformat(),
              "status": "downloading", "tracked_download_status": "ok",
              "error_message": "Corrupt RAR file"}]
    stuck = find_stuck_downloads(items, now, max_age_hours=12.0)
    assert len(stuck) == 1
    assert stuck[0]["stuck_reason"] == "error"


def test_flags_sabnzbd_aborted_error_message():
    # The real-world case that started all this: a dead NZB (missing
    # articles) that SABnzbd gives up on, surfaced only via errorMessage.
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "NCIS S15E14", "added": now.isoformat(),
              "status": "downloading", "tracked_download_status": "ok",
              "error_message": "Aborted, cannot be completed - https://sabnzbd.org/not-complete"}]
    stuck = find_stuck_downloads(items, now, max_age_hours=12.0)
    assert len(stuck) == 1
    assert stuck[0]["stuck_reason"] == "error"


def test_flags_sonarr_item_with_unresolved_episode_id_as_unmatched():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "Body of Proof S02E10 1080p WEB h264-FaiLED", "added": now.isoformat(),
              "status": "downloading", "tracked_download_status": "ok",
              "error_message": "", "episode_id": None}]
    stuck = find_stuck_downloads(items, now, max_age_hours=12.0)
    assert len(stuck) == 1
    assert stuck[0]["stuck_reason"] == "unmatched"


def test_movie_item_with_no_episode_id_key_is_not_flagged_as_unmatched():
    # Radarr's get_queue() never includes "episode_id" at all — the
    # unmatched check must only apply when the key is actually present.
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "Some Movie", "added": now.isoformat(),
              "status": "downloading", "tracked_download_status": "ok", "error_message": ""}]
    assert find_stuck_downloads(items, now, max_age_hours=12.0) == []


def test_resolved_episode_id_is_not_flagged_as_unmatched():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = [{"id": 1, "title": "White Collar S04E04", "added": now.isoformat(),
              "status": "downloading", "tracked_download_status": "ok",
              "error_message": "", "episode_id": 9681}]
    assert find_stuck_downloads(items, now, max_age_hours=12.0) == []
