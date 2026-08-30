"""Pure helpers for the Library tab's request hub — no network calls
here (those live in clients/tmdb.py, clients/radarr.py,
clients/sonarr.py, called from yarr.py; core/ stays free of
HTTP/AppDaemon dependencies, mirroring core/discovery.py's split)."""


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
        "in_library": getattr(c, key) in library_ids,
    } for c in candidates]
