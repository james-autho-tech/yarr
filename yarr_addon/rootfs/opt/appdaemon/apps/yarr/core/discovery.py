"""Pure filtering/matching over Trakt candidates — no network calls
here (those live in clients/trakt.py, clients/radarr.py, called from
yarr.py; core/ stays free of HTTP/AppDaemon dependencies)."""

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class Candidate:
    tmdb_id: int
    imdb_id: str
    title: str
    year: int
    genres: list
    rating: float


def filter_candidates(candidates, *, allowed_genres, min_rating,
                       watched_tmdb_ids, radarr_tmdb_ids, already_suggested_tmdb_ids):
    """Empty allowed_genres = no genre filter."""
    allowed = {g.lower() for g in (allowed_genres or [])}
    out = []
    for c in candidates:
        if c.rating < min_rating:
            continue
        if allowed and not (allowed & {g.lower() for g in c.genres}):
            continue
        if c.tmdb_id in watched_tmdb_ids:
            continue
        if c.tmdb_id in radarr_tmdb_ids:
            continue
        if c.tmdb_id in already_suggested_tmdb_ids:
            continue
        out.append(c)
    return out


def pick_surprise(candidates, *, exclude_tmdb_ids, rng: random.Random = None):
    rng = rng or random.Random()
    pool = [c for c in candidates if c.tmdb_id not in exclude_tmdb_ids]
    if not pool:
        return None
    return rng.choice(pool)
