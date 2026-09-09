"""Pure merge logic for the Calendar tab — shaping already happened in
clients/radarr.py's/sonarr.py's get_calendar(); this just combines and
sorts. No network calls here (mirrors core/library.py's split)."""


def merge_calendar_entries(movies: list, episodes: list) -> list:
    """Combines Radarr's movie-release entries and Sonarr's episode-air
    entries into one date-sorted list for the web UI's Calendar tab."""
    entries = [{
        "date": m["date"], "type": "movie", "title": m["title"],
        "subtitle": m["release_type"], "available": m["has_file"],
    } for m in movies]
    entries += [{
        "date": e["date"], "type": "episode", "title": e["series_title"],
        "subtitle": f"S{e['season_number']:02d}E{e['episode_number']:02d}"
                    + (f" — {e['episode_title']}" if e["episode_title"] else ""),
        "available": e["has_file"],
    } for e in episodes]
    entries.sort(key=lambda x: x["date"])
    return entries
