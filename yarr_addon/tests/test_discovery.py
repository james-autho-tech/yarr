import random

from core.discovery import Candidate, filter_candidates, pick_surprise


def make(tmdb_id, rating=8.0, genres=("sci-fi",)):
    return Candidate(tmdb_id=tmdb_id, imdb_id=f"tt{tmdb_id}", title=f"Film {tmdb_id}",
                      year=2020, genres=list(genres), rating=rating)


def test_rating_floor_excludes_low_rated():
    cands = [make(1, rating=5.0), make(2, rating=8.0)]
    out = filter_candidates(cands, allowed_genres=[], min_rating=7.0,
                             watched_tmdb_ids=set(), radarr_tmdb_ids=set(),
                             already_suggested_tmdb_ids=set())
    assert [c.tmdb_id for c in out] == [2]


def test_empty_genre_list_means_no_genre_filter():
    cands = [make(1, genres=("horror",)), make(2, genres=("comedy",))]
    out = filter_candidates(cands, allowed_genres=[], min_rating=0,
                             watched_tmdb_ids=set(), radarr_tmdb_ids=set(),
                             already_suggested_tmdb_ids=set())
    assert {c.tmdb_id for c in out} == {1, 2}


def test_genre_overlap_required():
    cands = [make(1, genres=("horror",)), make(2, genres=("comedy",))]
    out = filter_candidates(cands, allowed_genres=["comedy"], min_rating=0,
                             watched_tmdb_ids=set(), radarr_tmdb_ids=set(),
                             already_suggested_tmdb_ids=set())
    assert [c.tmdb_id for c in out] == [2]


def test_excludes_watched_in_radarr_and_already_suggested():
    cands = [make(1), make(2), make(3), make(4)]
    out = filter_candidates(cands, allowed_genres=[], min_rating=0,
                             watched_tmdb_ids={1}, radarr_tmdb_ids={2},
                             already_suggested_tmdb_ids={3})
    assert [c.tmdb_id for c in out] == [4]


def test_pick_surprise_excludes_given_ids_deterministically():
    cands = [make(1), make(2), make(3)]
    rng = random.Random(42)
    pick = pick_surprise(cands, exclude_tmdb_ids={1, 2}, rng=rng)
    assert pick.tmdb_id == 3


def test_pick_surprise_returns_none_when_pool_empty():
    cands = [make(1), make(2)]
    pick = pick_surprise(cands, exclude_tmdb_ids={1, 2}, rng=random.Random(1))
    assert pick is None
