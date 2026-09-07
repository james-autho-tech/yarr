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
