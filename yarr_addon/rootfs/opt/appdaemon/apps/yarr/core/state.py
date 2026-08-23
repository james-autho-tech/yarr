"""Persisted yArr state — dedup/suggestion-history/surprise-tracking.

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
    radarr_movie_id: int = None
    added_at: str = ""
    watched: bool = False
    watched_at: str = None
    pending_deletion: PendingDeletion = None


@dataclass
class YarrState:
    version: int = 1
    suggested: dict = field(default_factory=dict)    # str(tmdb_id) -> SuggestedFilm
    surprises: dict = field(default_factory=dict)     # str(tmdb_id) -> SurpriseFilm
    next_surprise_at: str = None
    watched_tmdb_cache: list = field(default_factory=list)
    watched_cache_synced_at: str = None


def _film_to_dict(film):
    d = asdict(film)
    return d


def _suggested_from_dict(d):
    return SuggestedFilm(**d)


def _surprise_from_dict(d):
    d = dict(d)
    pd = d.get("pending_deletion")
    d["pending_deletion"] = PendingDeletion(**pd) if pd else None
    return SurpriseFilm(**d)


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
    )


def save(state: YarrState, path: str) -> None:
    payload = {
        "version": state.version,
        "suggested": {k: _film_to_dict(v) for k, v in state.suggested.items()},
        "surprises": {k: _film_to_dict(v) for k, v in state.surprises.items()},
        "next_surprise_at": state.next_surprise_at,
        "watched_tmdb_cache": state.watched_tmdb_cache,
        "watched_cache_synced_at": state.watched_cache_synced_at,
    }
    try:
        with open(path, "w") as f:
            json.dump(payload, f)
    except OSError:
        pass


def already_suggested(state: YarrState, tmdb_id: int) -> bool:
    return str(tmdb_id) in state.suggested or str(tmdb_id) in state.surprises


def record_suggestion(state: YarrState, film: SuggestedFilm) -> YarrState:
    suggested = dict(state.suggested)
    suggested[str(film.tmdb_id)] = film
    return _replace(state, suggested=suggested)


def record_surprise_added(state: YarrState, *, tmdb_id: int, imdb_id, title: str,
                           radarr_movie_id: int, now: datetime) -> YarrState:
    surprises = dict(state.surprises)
    surprises[str(tmdb_id)] = SurpriseFilm(
        tmdb_id=tmdb_id, imdb_id=imdb_id, title=title,
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


def _replace(state: YarrState, **changes) -> YarrState:
    from dataclasses import replace
    return replace(state, **changes)


def _replace_dc(obj, **changes):
    from dataclasses import replace
    return replace(obj, **changes)
