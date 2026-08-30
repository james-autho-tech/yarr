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
class PendingSurprise:
    """A surprise pick awaiting accept/deny in the web UI — not yet
    added to Radarr/Sonarr. tvdb_id is only set for a TV proposal."""
    tmdb_id: int
    tvdb_id: int = None
    imdb_id: str = None
    title: str = ""
    year: int = None
    genres: list = field(default_factory=list)
    rating: float = 0.0
    proposed_at: str = ""


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

    # A surprise pick waits here for accept/deny in the web UI before
    # ever touching Radarr/Sonarr — at most one outstanding per medium
    # at a time (a new pick isn't proposed until the current one is
    # resolved). Accept/deny feedback is tallied per genre (lowercased)
    # so denied genres can be actively suppressed from future picks,
    # not just logged — see yarr.py's _denied_genres().
    pending_surprise: PendingSurprise = None
    pending_tv_surprise: PendingSurprise = None
    denied_genre_counts: dict = field(default_factory=dict)
    accepted_genre_counts: dict = field(default_factory=dict)

    # Last duplicate-media scan's results (see core/dupes.py) — a plain
    # list of groups, each a list of {"path", "size"} dicts. Deleting is
    # always an explicit user action (single-file or bulk button in the
    # web UI), never automatic; just carried across restarts so the web
    # UI has something to show before the next scan completes.
    duplicate_groups: list = field(default_factory=list)
    duplicate_scan_at: str = None

    # How many of the current duplicate_groups' files the bulk-delete
    # button would remove, and how many bytes that'd free — computed at
    # scan time (see yarr.py's tick_scan_duplicates) by cross-checking
    # against Radarr/Sonarr's actually-tracked file paths. None means
    # that check couldn't be done (e.g. Radarr/Sonarr unreachable at
    # scan time), which the web UI treats as "unknown", not zero.
    duplicate_deletable_count: int = None
    duplicate_deletable_bytes: int = None

    # Last scan's leftover-SABnzbd-unpack junk (see core/junk.py) — a
    # plain list of {"path", "size", "is_dir"} dicts, found in the same
    # filesystem walk as duplicate_groups. Deleting is always an
    # explicit per-item user action in the web UI, never automatic.
    junk_entries: list = field(default_factory=list)
    junk_scan_at: str = None

    # Full existing Radarr/Sonarr library (Library tab) — everything
    # already in your library, not just what yArr itself suggested or
    # surprised you with. Refreshed periodically and on demand (see
    # yarr.py's tick_refresh_library); a plain list of {"id", "tmdb_id"
    # or "tvdb_id", "title", "year", "monitored", "size"} dicts.
    library_movies: list = field(default_factory=list)
    library_shows: list = field(default_factory=list)
    library_synced_at: str = None

    # Last TMDB text search (Library tab's request hub) — a plain list
    # of {"tmdb_id", "tvdb_id", "title", "year", "rating", "in_library"}
    # dicts (see core/library.mark_in_library). Adding a result is only
    # ever allowed for an id present in this list, same "only act on
    # what was just listed" rule as everything else destructive/
    # write-y in yArr.
    last_search_query: str = None
    last_search_media_type: str = None      # "movie" | "tv"
    last_search_results: list = field(default_factory=list)
    last_search_at: str = None


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
        pending_surprise=(PendingSurprise(**raw["pending_surprise"])
                          if raw.get("pending_surprise") else None),
        pending_tv_surprise=(PendingSurprise(**raw["pending_tv_surprise"])
                             if raw.get("pending_tv_surprise") else None),
        denied_genre_counts=dict(raw.get("denied_genre_counts", {})),
        accepted_genre_counts=dict(raw.get("accepted_genre_counts", {})),
        duplicate_groups=list(raw.get("duplicate_groups", [])),
        duplicate_scan_at=raw.get("duplicate_scan_at"),
        duplicate_deletable_count=raw.get("duplicate_deletable_count"),
        duplicate_deletable_bytes=raw.get("duplicate_deletable_bytes"),
        junk_entries=list(raw.get("junk_entries", [])),
        junk_scan_at=raw.get("junk_scan_at"),
        library_movies=list(raw.get("library_movies", [])),
        library_shows=list(raw.get("library_shows", [])),
        library_synced_at=raw.get("library_synced_at"),
        last_search_query=raw.get("last_search_query"),
        last_search_media_type=raw.get("last_search_media_type"),
        last_search_results=list(raw.get("last_search_results", [])),
        last_search_at=raw.get("last_search_at"),
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
        "pending_surprise": _film_to_dict(state.pending_surprise) if state.pending_surprise else None,
        "pending_tv_surprise": (_film_to_dict(state.pending_tv_surprise)
                                if state.pending_tv_surprise else None),
        "denied_genre_counts": state.denied_genre_counts,
        "accepted_genre_counts": state.accepted_genre_counts,
        "duplicate_groups": state.duplicate_groups,
        "duplicate_scan_at": state.duplicate_scan_at,
        "duplicate_deletable_count": state.duplicate_deletable_count,
        "duplicate_deletable_bytes": state.duplicate_deletable_bytes,
        "junk_entries": state.junk_entries,
        "junk_scan_at": state.junk_scan_at,
        "library_movies": state.library_movies,
        "library_shows": state.library_shows,
        "library_synced_at": state.library_synced_at,
        "last_search_query": state.last_search_query,
        "last_search_media_type": state.last_search_media_type,
        "last_search_results": state.last_search_results,
        "last_search_at": state.last_search_at,
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


# ------------------------------------------------------------------
# SURPRISE APPROVAL / GENRE FEEDBACK
# ------------------------------------------------------------------

def set_pending_surprise(state: YarrState, proposal: PendingSurprise) -> YarrState:
    return _replace(state, pending_surprise=proposal)


def clear_pending_surprise(state: YarrState) -> YarrState:
    return _replace(state, pending_surprise=None)


def set_pending_tv_surprise(state: YarrState, proposal: PendingSurprise) -> YarrState:
    return _replace(state, pending_tv_surprise=proposal)


def clear_pending_tv_surprise(state: YarrState) -> YarrState:
    return _replace(state, pending_tv_surprise=None)


def record_genre_feedback(state: YarrState, genres: list, accepted: bool) -> YarrState:
    """Tallies one accept/deny decision against each of its genres
    (lowercased). Denied counts are what yarr.py uses to actively
    suppress a genre going forward (see denied_genres_over_threshold);
    accepted counts are tracked for symmetry/visibility only."""
    field_name = "accepted_genre_counts" if accepted else "denied_genre_counts"
    counts = dict(getattr(state, field_name))
    for g in genres:
        key = str(g).lower()
        counts[key] = counts.get(key, 0) + 1
    return _replace(state, **{field_name: counts})


def denied_genres_over_threshold(state: YarrState, threshold: int) -> list:
    return [g for g, count in state.denied_genre_counts.items() if count >= threshold]


def _replace(state: YarrState, **changes) -> YarrState:
    from dataclasses import replace
    return replace(state, **changes)


def _replace_dc(obj, **changes):
    from dataclasses import replace
    return replace(obj, **changes)
