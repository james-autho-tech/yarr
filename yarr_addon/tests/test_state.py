import os
from datetime import datetime, timedelta, timezone

from core import state


def test_record_suggestion_roundtrip():
    s = state.YarrState()
    film = state.SuggestedFilm(tmdb_id=1, imdb_id="tt1", title="X",
                                suggested_at="2026-01-01T00:00:00+00:00", radarr_movie_id=5)
    s = state.record_suggestion(s, film)
    assert state.already_suggested(s, 1) is True
    assert state.already_suggested(s, 2) is False


def test_record_surprise_added_and_mark_watched():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.YarrState()
    s = state.record_surprise_added(s, tmdb_id=27205, imdb_id="tt1", title="Inception",
                                     radarr_movie_id=10, now=now)
    assert "27205" in s.surprises
    assert s.surprises["27205"].watched is False

    s = state.mark_watched(s, 27205, now + timedelta(hours=1))
    assert s.surprises["27205"].watched is True
    assert s.surprises["27205"].watched_at is not None


def test_schedule_and_cancel_and_due_deletion():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.YarrState()
    s = state.record_surprise_added(s, tmdb_id=1, imdb_id="tt1", title="X",
                                     radarr_movie_id=1, now=now)
    s = state.schedule_deletion(s, 1, now, grace_hours=1)
    assert state.due_deletions(s, now) == []
    assert len(state.due_deletions(s, now + timedelta(hours=2))) == 1

    s = state.cancel_deletion(s, 1)
    assert state.due_deletions(s, now + timedelta(hours=2)) == []


def test_confirm_deleted_removes_entry():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.YarrState()
    s = state.record_surprise_added(s, tmdb_id=1, imdb_id="tt1", title="X",
                                     radarr_movie_id=1, now=now)
    s = state.confirm_deleted(s, 1)
    assert "1" not in s.surprises


def test_save_and_load_roundtrip(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.YarrState()
    s = state.record_suggestion(s, state.SuggestedFilm(
        tmdb_id=1, imdb_id="tt1", title="X", suggested_at=now.isoformat(), radarr_movie_id=5))
    s = state.record_surprise_added(s, tmdb_id=2, imdb_id="tt2", title="Y",
                                     radarr_movie_id=6, now=now)
    s = state.schedule_deletion(s, 2, now, grace_hours=1)
    s.next_surprise_at = now.isoformat()
    s.watched_tmdb_cache = [1, 2]
    s.watched_cache_synced_at = now.isoformat()

    path = os.path.join(tmp_path, "yarr_state.json")
    state.save(s, path)
    loaded = state.load(path)

    assert loaded.suggested["1"] == s.suggested["1"]
    assert loaded.surprises["2"] == s.surprises["2"]
    assert loaded.next_surprise_at == s.next_surprise_at
    assert loaded.watched_tmdb_cache == s.watched_tmdb_cache


def test_load_missing_file_returns_empty_state(tmp_path):
    loaded = state.load(os.path.join(tmp_path, "nope.json"))
    assert loaded.suggested == {}
    assert loaded.surprises == {}
    assert loaded.suggested_shows == {}
    assert loaded.surprises_shows == {}


def test_record_suggestion_show_roundtrip():
    s = state.YarrState()
    show = state.SuggestedShow(tvdb_id=1, tmdb_id=100, title="X",
                                suggested_at="2026-01-01T00:00:00+00:00", sonarr_series_id=5)
    s = state.record_suggestion_show(s, show)
    assert state.already_suggested_show(s, 1) is True
    assert state.already_suggested_show(s, 2) is False


def test_record_surprise_show_added_and_mark_watched():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.YarrState()
    s = state.record_surprise_show_added(s, tvdb_id=12345, tmdb_id=1, imdb_id="tt1",
                                          title="Breaking Bad", sonarr_series_id=10, now=now)
    assert "12345" in s.surprises_shows
    assert s.surprises_shows["12345"].watched is False

    s = state.mark_show_watched(s, 12345, now + timedelta(hours=1))
    assert s.surprises_shows["12345"].watched is True
    assert s.surprises_shows["12345"].watched_at is not None


def test_schedule_and_cancel_and_due_show_deletion():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.YarrState()
    s = state.record_surprise_show_added(s, tvdb_id=1, tmdb_id=1, imdb_id="tt1",
                                          title="X", sonarr_series_id=1, now=now)
    s = state.schedule_show_deletion(s, 1, now, grace_hours=1)
    assert state.due_show_deletions(s, now) == []
    assert len(state.due_show_deletions(s, now + timedelta(hours=2))) == 1

    s = state.cancel_show_deletion(s, 1)
    assert state.due_show_deletions(s, now + timedelta(hours=2)) == []


def test_confirm_show_deleted_removes_entry():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.YarrState()
    s = state.record_surprise_show_added(s, tvdb_id=1, tmdb_id=1, imdb_id="tt1",
                                          title="X", sonarr_series_id=1, now=now)
    s = state.confirm_show_deleted(s, 1)
    assert "1" not in s.surprises_shows


def test_save_and_load_roundtrip_includes_shows(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.YarrState()
    s = state.record_suggestion_show(s, state.SuggestedShow(
        tvdb_id=1, tmdb_id=100, title="X", suggested_at=now.isoformat(), sonarr_series_id=5))
    s = state.record_surprise_show_added(s, tvdb_id=2, tmdb_id=200, imdb_id="tt2",
                                          title="Y", sonarr_series_id=6, now=now)
    s = state.schedule_show_deletion(s, 2, now, grace_hours=1)
    s.next_tv_surprise_at = now.isoformat()
    s.watched_tvdb_cache = [1, 2]
    s.learned_genres = ["drama", "comedy"]
    s.learned_tv_genres = ["thriller"]

    path = os.path.join(tmp_path, "yarr_state.json")
    state.save(s, path)
    loaded = state.load(path)

    assert loaded.suggested_shows["1"] == s.suggested_shows["1"]
    assert loaded.surprises_shows["2"] == s.surprises_shows["2"]
    assert loaded.next_tv_surprise_at == s.next_tv_surprise_at
    assert loaded.watched_tvdb_cache == s.watched_tvdb_cache
    assert loaded.learned_genres == ["drama", "comedy"]
    assert loaded.learned_tv_genres == ["thriller"]


def test_add_log_event_appends_and_caps():
    s = state.YarrState()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.add_log_event(s, "added Inception", now)
    assert len(s.event_log) == 1
    assert s.event_log[0]["message"] == "added Inception"
    assert s.event_log[0]["level"] == "info"

    for i in range(60):
        s = state.add_log_event(s, f"event {i}", now + timedelta(minutes=i), limit=50)
    assert len(s.event_log) == 50
    assert s.event_log[-1]["message"] == "event 59"


def test_add_log_event_persists_through_save_load(tmp_path):
    s = state.YarrState()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = state.add_log_event(s, "deleted X after grace period", now, level="error")

    path = os.path.join(tmp_path, "yarr_state.json")
    state.save(s, path)
    loaded = state.load(path)
    assert loaded.event_log == s.event_log
