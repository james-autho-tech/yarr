"""Persisted yArr state — dedup/suggestion-history/surprise-tracking,
for both movies (tmdb_id-keyed) and shows (tvdb_id-keyed — see
core/discovery.TVCandidate's docstring for why Sonarr needs its own key).

Single JSON file: /config/apps/yarr/yarr_state.json. All transform
functions here are pure (return a new YarrState) — only load()/save()
touch disk.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
import json


@dataclass(frozen=True)
class SuggestedFilm:
    tmdb_id: int
    imdb_id: str = None
    title: str = ""
    year: int = None
    source: str = "genre"          # "genre" | "surprise"
    decision: str = "added"         # "added" | "rejected_low_rating" | "rejected_in_radarr" | "rejected_watched"
    suggested_at: str = ""          # ISO8601
    radarr_movie_id: int = None


@dataclass(frozen=True)
class PendingDeletion:
    delete_at: str
    keep_requested: bool = False
    notified: bool = False


@dataclass(frozen=True)
class SurpriseFilm:
    tmdb_id: int
    imdb_id: str = None
    title: str = ""
    year: int = None
    radarr_movie_id: int = None
    added_at: str = ""
    watched: bool = False
    watched_at: str = None
    pending_deletion: PendingDeletion = None


@dataclass(frozen=True)
class SuggestedShow:
    tvdb_id: int
    tmdb_id: int = None
    imdb_id: str = None
    title: str = ""
    year: int = None
    source: str = "genre"
    decision: str = "added"
    suggested_at: str = ""
    sonarr_series_id: int = None


@dataclass(frozen=True)
class SurpriseShow:
    tvdb_id: int
    tmdb_id: int = None
    imdb_id: str = None
    title: str = ""
    year: int = None
    sonarr_series_id: int = None
    added_at: str = ""
    watched: bool = False
    watched_at: str = None
    pending_deletion: PendingDeletion = None


@dataclass
class YarrState:
    version: int = 1
    suggested: dict = field(default_factory=dict)          # str(tmdb_id) -> SuggestedFilm
    surprises: dict = field(default_factory=dict)           # str(tmdb_id) -> SurpriseFilm
    next_surprise_at: str = None
    watched_tmdb_cache: list = field(default_factory=list)
    watched_cache_synced_at: str = None

    suggested_shows: dict = field(default_factory=dict)     # str(tvdb_id) -> SuggestedShow
    surprises_shows: dict = field(default_factory=dict)      # str(tvdb_id) -> SurpriseShow
    next_tv_surprise_at: str = None
    watched_tvdb_cache: list = field(default_factory=list)

    # Library-derived genre preferences (see core/taste.py) — populated
    # only when apps.yaml's learn_genres_from_library is enabled;
    # otherwise left empty and yarr.py falls back to the configured
    # genres/tv_genres lists.
    learned_genres: list = field(default_factory=list)
    learned_tv_genres: list = field(default_factory=list)

    # Rolling human-readable event log (additions/surprises/deletions/
    # errors) for the web UI's Log section — persisted (not just kept
    # in memory) so a restart doesn't wipe today's activity, capped by
    # add_log_event() so this file can't grow unbounded.
    event_log: list = field(default_factory=list)


def _film_to_dict(film):
    return asdict(film)


def _suggested_from_dict(d):
    return SuggestedFilm(**d)


def _surprise_from_dict(d):
    d = dict(d)
    pd = d.get("pending_deletion")
    d["pending_deletion"] = PendingDeletion(**pd) if pd else None
    return SurpriseFilm(**d)


def _suggested_show_from_dict(d):
    return SuggestedShow(**d)


def _surprise_show_from_dict(d):
    d = dict(d)
    pd = d.get("pending_deletion")
    d["pending_deletion"] = PendingDeletion(**pd) if pd else None
    return SurpriseShow(**d)


def load(path: str) -> YarrState:
    try:
        with open(path) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return YarrState()
    return YarrState(
        version=raw.get("version", 1),
        suggested={k: _suggested_from_dict(v) for k, v in raw.get("suggested", {}).items()},
        surprises={k: _surprise_from_dict(v) for k, v in raw.get("surprises", {}).items()},
        next_surprise_at=raw.get("next_surprise_at"),
        watched_tmdb_cache=list(raw.get("watched_tmdb_cache", [])),
        watched_cache_synced_at=raw.get("watched_cache_synced_at"),
        suggested_shows={k: _suggested_show_from_dict(v)
                          for k, v in raw.get("suggested_shows", {}).items()},
        surprises_shows={k: _surprise_show_from_dict(v)
                          for k, v in raw.get("surprises_shows", {}).items()},
        next_tv_surprise_at=raw.get("next_tv_surprise_at"),
        watched_tvdb_cache=list(raw.get("watched_tvdb_cache", [])),
        learned_genres=list(raw.get("learned_genres", [])),
        learned_tv_genres=list(raw.get("learned_tv_genres", [])),
        event_log=list(raw.get("event_log", [])),
    )


def save(state: YarrState, path: str) -> None:
    payload = {
        "version": state.version,
        "suggested": {k: _film_to_dict(v) for k, v in state.suggested.items()},
        "surprises": {k: _film_to_dict(v) for k, v in state.surprises.items()},
        "next_surprise_at": state.next_surprise_at,
        "watched_tmdb_cache": state.watched_tmdb_cache,
        "watched_cache_synced_at": state.watched_cache_synced_at,
        "suggested_shows": {k: _film_to_dict(v) for k, v in state.suggested_shows.items()},
        "surprises_shows": {k: _film_to_dict(v) for k, v in state.surprises_shows.items()},
        "next_tv_surprise_at": state.next_tv_surprise_at,
        "watched_tvdb_cache": state.watched_tvdb_cache,
        "learned_genres": state.learned_genres,
        "learned_tv_genres": state.learned_tv_genres,
        "event_log": state.event_log,
    }
    try:
        with open(path, "w") as f:
            json.dump(payload, f)
    except OSError:
        pass


# ------------------------------------------------------------------
# MOVIES
# ------------------------------------------------------------------

def already_suggested(state: YarrState, tmdb_id: int) -> bool:
    return str(tmdb_id) in state.suggested or str(tmdb_id) in state.surprises


def record_suggestion(state: YarrState, film: SuggestedFilm) -> YarrState:
    suggested = dict(state.suggested)
    suggested[str(film.tmdb_id)] = film
    return _replace(state, suggested=suggested)


def record_surprise_added(state: YarrState, *, tmdb_id: int, imdb_id, title: str,
                           radarr_movie_id: int, now: datetime, year: int = None) -> YarrState:
    surprises = dict(state.surprises)
    surprises[str(tmdb_id)] = SurpriseFilm(
        tmdb_id=tmdb_id, imdb_id=imdb_id, title=title, year=year,
        radarr_movie_id=radarr_movie_id, added_at=now.isoformat())
    return _replace(state, surprises=surprises)


def mark_watched(state: YarrState, tmdb_id: int, now: datetime) -> YarrState:
    key = str(tmdb_id)
    if key not in state.surprises:
        return state
    surprises = dict(state.surprises)
    film = surprises[key]
    surprises[key] = _replace_dc(film, watched=True, watched_at=now.isoformat())
    return _replace(state, surprises=surprises)


def schedule_deletion(state: YarrState, tmdb_id: int, now: datetime, grace_hours: float) -> YarrState:
    from . import delete_guard
    key = str(tmdb_id)
    if key not in state.surprises:
        return state
    surprises = dict(state.surprises)
    film = surprises[key]
    pending = PendingDeletion(delete_at=delete_guard.schedule(now, grace_hours), notified=True)
    surprises[key] = _replace_dc(film, pending_deletion=pending)
    return _replace(state, surprises=surprises)


def cancel_deletion(state: YarrState, tmdb_id: int) -> YarrState:
    key = str(tmdb_id)
    if key not in state.surprises:
        return state
    surprises = dict(state.surprises)
    surprises[key] = _replace_dc(surprises[key], pending_deletion=None)
    return _replace(state, surprises=surprises)


def confirm_deleted(state: YarrState, tmdb_id: int) -> YarrState:
    surprises = dict(state.surprises)
    surprises.pop(str(tmdb_id), None)
    return _replace(state, surprises=surprises)


def due_deletions(state: YarrState, now: datetime) -> list:
    from . import delete_guard
    return [film for film in state.surprises.values()
            if film.pending_deletion and delete_guard.is_due(film.pending_deletion, now)]


# ------------------------------------------------------------------
# SHOWS — same shape as the movie functions above, tvdb_id-keyed
# ------------------------------------------------------------------

def already_suggested_show(state: YarrState, tvdb_id: int) -> bool:
    return str(tvdb_id) in state.suggested_shows or str(tvdb_id) in state.surprises_shows


def record_suggestion_show(state: YarrState, show: SuggestedShow) -> YarrState:
    suggested_shows = dict(state.suggested_shows)
    suggested_shows[str(show.tvdb_id)] = show
    return _replace(state, suggested_shows=suggested_shows)


def record_surprise_show_added(state: YarrState, *, tvdb_id: int, tmdb_id, imdb_id, title: str,
                                sonarr_series_id: int, now: datetime, year: int = None) -> YarrState:
    surprises_shows = dict(state.surprises_shows)
    surprises_shows[str(tvdb_id)] = SurpriseShow(
        tvdb_id=tvdb_id, tmdb_id=tmdb_id, imdb_id=imdb_id, title=title, year=year,
        sonarr_series_id=sonarr_series_id, added_at=now.isoformat())
    return _replace(state, surprises_shows=surprises_shows)


def mark_show_watched(state: YarrState, tvdb_id: int, now: datetime) -> YarrState:
    key = str(tvdb_id)
    if key not in state.surprises_shows:
        return state
    surprises_shows = dict(state.surprises_shows)
    show = surprises_shows[key]
    surprises_shows[key] = _replace_dc(show, watched=True, watched_at=now.isoformat())
    return _replace(state, surprises_shows=surprises_shows)


def schedule_show_deletion(state: YarrState, tvdb_id: int, now: datetime, grace_hours: float) -> YarrState:
    from . import delete_guard
    key = str(tvdb_id)
    if key not in state.surprises_shows:
        return state
    surprises_shows = dict(state.surprises_shows)
    show = surprises_shows[key]
    pending = PendingDeletion(delete_at=delete_guard.schedule(now, grace_hours), notified=True)
    surprises_shows[key] = _replace_dc(show, pending_deletion=pending)
    return _replace(state, surprises_shows=surprises_shows)


def cancel_show_deletion(state: YarrState, tvdb_id: int) -> YarrState:
    key = str(tvdb_id)
    if key not in state.surprises_shows:
        return state
    surprises_shows = dict(state.surprises_shows)
    surprises_shows[key] = _replace_dc(surprises_shows[key], pending_deletion=None)
    return _replace(state, surprises_shows=surprises_shows)


def confirm_show_deleted(state: YarrState, tvdb_id: int) -> YarrState:
    surprises_shows = dict(state.surprises_shows)
    surprises_shows.pop(str(tvdb_id), None)
    return _replace(state, surprises_shows=surprises_shows)


def due_show_deletions(state: YarrState, now: datetime) -> list:
    from . import delete_guard
    return [show for show in state.surprises_shows.values()
            if show.pending_deletion and delete_guard.is_due(show.pending_deletion, now)]


# ------------------------------------------------------------------
# EVENT LOG
# ------------------------------------------------------------------

def add_log_event(state: YarrState, message: str, now: datetime,
                   level: str = "info", limit: int = 50) -> YarrState:
    entry = {"ts": now.isoformat(), "level": level, "message": message}
    log = (state.event_log + [entry])[-limit:]
    return _replace(state, event_log=log)


def _replace(state: YarrState, **changes) -> YarrState:
    from dataclasses import replace
    return replace(state, **changes)


def _replace_dc(obj, **changes):
    from dataclasses import replace
    return replace(obj, **changes)
