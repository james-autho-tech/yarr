"""Pure helpers for the Library tab's request hub — no network calls
here (those live in clients/tmdb.py, clients/radarr.py,
clients/sonarr.py, called from yarr.py; core/ stays free of
HTTP/AppDaemon dependencies, mirroring core/discovery.py's split)."""

# TMDB's own image CDN — poster_path is always a bare relative path
# (e.g. "/xyz.jpg") from their API; w300 is a fixed, reasonably-sized
# width, plenty for a card-grid thumbnail without pulling full-res art.
TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w300"


def poster_url(poster_path):
    return f"{TMDB_POSTER_BASE}{poster_path}" if poster_path else None


def mark_in_library(candidates, library_ids: set, key="tmdb_id") -> list:
    """Shapes TMDB search Candidates/TVCandidates into plain dicts
    ready for state storage, flagging whether each is already in your
    Radarr/Sonarr library — the one thing a raw TMDB search result
    can't tell you on its own."""
    return [{
        "tmdb_id": c.tmdb_id,
        "tvdb_id": getattr(c, "tvdb_id", None),
        "title": c.title,
        "year": c.year,
        "rating": c.rating,
        "poster_url": poster_url(getattr(c, "poster_path", None)),
        "genres": list(getattr(c, "genres", []) or []),
        "overview": getattr(c, "overview", None) or "",
        "in_library": getattr(c, key) in library_ids,
    } for c in candidates]


def rank_cycle_candidates(library_items, last_played_by_id: dict,
                           key="tmdb_id", limit=20) -> list:
    """Ranks existing library items as space-cycling candidates: never-
    watched items (by how long they've sat unwatched, using Radarr/
    Sonarr's own "added" date) and long-ago-watched items (by Jellyfin's
    last-played date) sort together on one timeline, oldest activity
    first — that's the title that has done the least for you lately.
    Items with neither an "added" nor a last-played date sort last
    (nothing to rank them by, safest default). Recommend-only: this
    never deletes anything, just orders what's shown in the web UI."""
    rows = []
    for item in library_items:
        last_played = last_played_by_id.get(str(item.get(key)))
        last_activity = last_played or item.get("added")
        rows.append({**item, "last_played_at": last_played,
                     "never_watched": last_played is None,
                     "last_activity": last_activity})
    rows.sort(key=lambda r: r["last_activity"] or "9999")
    return rows[:limit]
