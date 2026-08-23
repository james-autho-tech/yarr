"""Parses Jellyfin's Webhook-plugin PlaybackStop payload and matches it
against a tracked surprise film. Field names match Jellyfin's default
webhook template (NotificationType, ItemType, Name, PlaybackPercentage,
Provider_tmdb, Provider_imdb) — see DOCS.md for the exact template."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybackStopEvent:
    tmdb_id: int
    imdb_id: str
    item_name: str
    percentage: float


def parse_jellyfin_payload(payload: dict):
    if not isinstance(payload, dict):
        return None
    if payload.get("NotificationType") != "PlaybackStop":
        return None
    if payload.get("ItemType") != "Movie":
        return None
    tmdb_raw = payload.get("Provider_tmdb")
    imdb_raw = payload.get("Provider_imdb")
    if not tmdb_raw and not imdb_raw:
        return None
    try:
        tmdb_id = int(tmdb_raw) if tmdb_raw else None
    except (TypeError, ValueError):
        tmdb_id = None
    try:
        percentage = float(payload.get("PlaybackPercentage", 0))
    except (TypeError, ValueError):
        percentage = 0.0
    return PlaybackStopEvent(
        tmdb_id=tmdb_id,
        imdb_id=str(imdb_raw) if imdb_raw else None,
        item_name=str(payload.get("Name", "")),
        percentage=percentage,
    )


def matches_surprise(event: PlaybackStopEvent, surprises: dict):
    """tmdb_id match first, imdb_id fallback — never matches by title."""
    if event is None:
        return None
    if event.tmdb_id is not None and str(event.tmdb_id) in surprises:
        return surprises[str(event.tmdb_id)]
    if event.imdb_id:
        for film in surprises.values():
            if film.imdb_id == event.imdb_id:
                return film
    return None
