from core.discovery import Candidate, TVCandidate
from core.library import mark_in_library


def make(tmdb_id, rating=8.0):
    return Candidate(tmdb_id=tmdb_id, imdb_id=None, title=f"Film {tmdb_id}",
                      year=2020, genres=[], rating=rating)


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
