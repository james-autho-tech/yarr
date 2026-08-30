"""Pure filtering/matching over TMDB candidates — no network calls
here (those live in clients/tmdb.py, clients/radarr.py, clients/sonarr.py,
called from yarr.py; core/ stays free of HTTP/AppDaemon dependencies)."""

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
    poster_path: str = None  # TMDB's own relative path (e.g. "/xyz.jpg") — only
                              # ever set by clients/tmdb.py's search methods, since
                              # nothing else (genre discovery, surprise picks) needs it
    overview: str = None     # plot synopsis — same story as poster_path, only the
                              # Library tab's search/detail view needs it


@dataclass(frozen=True)
class TVCandidate:
    """Same shape as Candidate, plus tvdb_id — Sonarr keys its library
    on TheTVDB's id, not TMDB's, so both id fields are carried through:
    tmdb_id for TMDB-side lookups (e.g. a second external_ids call),
    tvdb_id for everything Sonarr-facing (library membership, adding,
    deleting). filter_candidates/pick_surprise take a `key` parameter
    naming which one to use as the identity key for a given call."""
    tmdb_id: int
    tvdb_id: int
    imdb_id: str
    title: str
    year: int
    genres: list
    rating: float
    poster_path: str = None
    overview: str = None


def filter_candidates(candidates, *, allowed_genres, min_rating,
                       watched_tmdb_ids, radarr_tmdb_ids, already_suggested_tmdb_ids,
                       key="tmdb_id", excluded_genres=None):
    """Empty allowed_genres = no genre filter. Works identically for
    Candidate and TVCandidate — pass key="tvdb_id" for TV, where
    Sonarr/Jellyfin exclusion sets are naturally TVDB-keyed.

    excluded_genres is a hard veto checked independently of
    allowed_genres — a candidate carrying an excluded genre is dropped
    even if it also matches an allowed one, and even when
    allowed_genres is empty ("no genre filter" only ever means no
    *inclusion* filter, never bypasses an explicit exclusion)."""
    allowed = {g.lower() for g in (allowed_genres or [])}
    excluded = {g.lower() for g in (excluded_genres or [])}
    out = []
    for c in candidates:
        if c.rating < min_rating:
            continue
        genre_set = {g.lower() for g in c.genres}
        if excluded and (excluded & genre_set):
            continue
        if allowed and not (allowed & genre_set):
            continue
        cid = getattr(c, key)
        if cid in watched_tmdb_ids:
            continue
        if cid in radarr_tmdb_ids:
            continue
        if cid in already_suggested_tmdb_ids:
            continue
        out.append(c)
    return out


def pick_surprise(candidates, *, exclude_tmdb_ids, rng: random.Random = None, key="tmdb_id"):
    rng = rng or random.Random()
    pool = [c for c in candidates if getattr(c, key) not in exclude_tmdb_ids]
    if not pool:
        return None
    return rng.choice(pool)
