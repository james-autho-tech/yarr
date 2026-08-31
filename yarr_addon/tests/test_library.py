from core.discovery import Candidate, TVCandidate
from core.library import mark_in_library, poster_url, rank_cycle_candidates


def make(tmdb_id, rating=8.0, poster_path=None, genres=(), overview=None):
    return Candidate(tmdb_id=tmdb_id, imdb_id=None, title=f"Film {tmdb_id}",
                      year=2020, genres=list(genres), rating=rating,
                      poster_path=poster_path, overview=overview)


def make_tv(tvdb_id, tmdb_id=None, rating=8.0):
    return TVCandidate(tmdb_id=tmdb_id or tvdb_id * 100, tvdb_id=tvdb_id,
                        imdb_id=None, title=f"Show {tvdb_id}", year=2020,
                        genres=[], rating=rating)


def test_marks_movie_already_in_library():
    rows = mark_in_library([make(1), make(2)], library_ids={1})
    assert rows[0]["in_library"] is True
    assert rows[1]["in_library"] is False


def test_marks_tv_by_tvdb_key():
    rows = mark_in_library([make_tv(10), make_tv(20)], library_ids={10}, key="tvdb_id")
    assert rows[0]["in_library"] is True
    assert rows[1]["in_library"] is False


def test_result_dict_carries_title_year_rating():
    rows = mark_in_library([make(1, rating=7.5)], library_ids=set())
    assert rows[0]["title"] == "Film 1"
    assert rows[0]["year"] == 2020
    assert rows[0]["rating"] == 7.5


def test_movie_candidate_has_no_tvdb_id():
    rows = mark_in_library([make(1)], library_ids=set())
    assert rows[0]["tvdb_id"] is None


def test_empty_candidates_returns_empty_list():
    assert mark_in_library([], library_ids={1, 2}) == []


def test_poster_url_builds_full_tmdb_url():
    assert poster_url("/abc.jpg") == "https://image.tmdb.org/t/p/w300/abc.jpg"


def test_poster_url_none_when_no_path():
    assert poster_url(None) is None


def test_mark_in_library_carries_poster_url():
    rows = mark_in_library([make(1, poster_path="/abc.jpg")], library_ids=set())
    assert rows[0]["poster_url"] == "https://image.tmdb.org/t/p/w300/abc.jpg"


def test_mark_in_library_poster_url_none_when_missing():
    rows = mark_in_library([make(1)], library_ids=set())
    assert rows[0]["poster_url"] is None


def test_mark_in_library_carries_genres_and_overview():
    rows = mark_in_library([make(1, genres=["Action", "Comedy"], overview="A plot.")], library_ids=set())
    assert rows[0]["genres"] == ["Action", "Comedy"]
    assert rows[0]["overview"] == "A plot."


def test_mark_in_library_overview_defaults_to_empty_string():
    rows = mark_in_library([make(1)], library_ids=set())
    assert rows[0]["overview"] == ""
    assert rows[0]["genres"] == []


def test_rank_cycle_candidates_never_watched_sorts_by_added_date_oldest_first():
    items = [
        {"tmdb_id": 1, "title": "Newer Add", "added": "2026-06-01T00:00:00Z"},
        {"tmdb_id": 2, "title": "Older Add", "added": "2024-01-01T00:00:00Z"},
    ]
    rows = rank_cycle_candidates(items, last_played_by_id={})
    assert [r["title"] for r in rows] == ["Older Add", "Newer Add"]
    assert all(r["never_watched"] for r in rows)
    assert all(r["last_played_at"] is None for r in rows)


def test_rank_cycle_candidates_watched_sorts_by_last_played_oldest_first():
    items = [
        {"tmdb_id": 1, "title": "Watched Recently", "added": "2020-01-01T00:00:00Z"},
        {"tmdb_id": 2, "title": "Watched Long Ago", "added": "2020-01-01T00:00:00Z"},
    ]
    last_played = {"1": "2026-06-01T00:00:00Z", "2": "2021-01-01T00:00:00Z"}
    rows = rank_cycle_candidates(items, last_played_by_id=last_played)
    assert [r["title"] for r in rows] == ["Watched Long Ago", "Watched Recently"]
    assert all(r["never_watched"] is False for r in rows)


def test_rank_cycle_candidates_mixes_never_watched_and_watched_on_one_timeline():
    items = [
        {"tmdb_id": 1, "title": "Watched 2023", "added": "2019-01-01T00:00:00Z"},
        {"tmdb_id": 2, "title": "Never Watched, Added 2022", "added": "2022-01-01T00:00:00Z"},
    ]
    last_played = {"1": "2023-01-01T00:00:00Z"}
    rows = rank_cycle_candidates(items, last_played_by_id=last_played)
    assert [r["title"] for r in rows] == ["Never Watched, Added 2022", "Watched 2023"]


def test_rank_cycle_candidates_missing_both_dates_sorts_last():
    items = [
        {"tmdb_id": 1, "title": "No Dates At All"},
        {"tmdb_id": 2, "title": "Has Added Date", "added": "2020-01-01T00:00:00Z"},
    ]
    rows = rank_cycle_candidates(items, last_played_by_id={})
    assert [r["title"] for r in rows] == ["Has Added Date", "No Dates At All"]


def test_rank_cycle_candidates_respects_limit():
    items = [{"tmdb_id": i, "title": f"Film {i}", "added": "2020-01-01T00:00:00Z"} for i in range(5)]
    rows = rank_cycle_candidates(items, last_played_by_id={}, limit=2)
    assert len(rows) == 2


def test_rank_cycle_candidates_uses_tvdb_key_for_shows():
    items = [{"tvdb_id": 1, "title": "Show", "added": "2020-01-01T00:00:00Z"}]
    last_played = {"1": "2025-01-01T00:00:00Z"}
    rows = rank_cycle_candidates(items, last_played_by_id=last_played, key="tvdb_id")
    assert rows[0]["last_played_at"] == "2025-01-01T00:00:00Z"
    assert rows[0]["never_watched"] is False
