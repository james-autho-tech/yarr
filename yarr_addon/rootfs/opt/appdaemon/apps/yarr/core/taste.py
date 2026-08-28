"""Derives a weighted genre preference list from what's already in your
Jellyfin library, as an alternative to hand-listing genres in
apps.yaml. Pure — the actual Jellyfin library fetch lives in
clients/jellyfin.py; this module only scores/ranks what it's handed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WatchedItem:
    genres: list
    play_count: int = 0
    is_favorite: bool = False


def top_genres(items, *, top_n=5, favorite_bonus=3.0, play_count_weight=0.1, exclude=None) -> list:
    """Score = 1 (base, for appearing at all) + play_count*play_count_weight
    + favorite_bonus if favourited, summed per genre across every item
    that carries it, then the top_n highest-scoring genre names are
    returned lowercase, highest first. An empty/near-empty library
    naturally yields an empty list — callers should fall back to a
    configured genre list in that case, not treat this as "no genre
    filter" (see yarr.py).

    `exclude` is applied before ranking, not as a post-filter — a
    genre you've watched a lot of but explicitly excluded (e.g.
    horror) never occupies one of the top_n slots and pushes out a
    genre you'd actually want, rather than just being stripped from an
    already-decided top_n afterwards."""
    excluded = {str(g).lower() for g in (exclude or [])}
    scores = {}
    for item in items:
        weight = 1.0 + item.play_count * play_count_weight + (favorite_bonus if item.is_favorite else 0.0)
        for g in item.genres:
            key = str(g).lower()
            if key in excluded:
                continue
            scores[key] = scores.get(key, 0.0) + weight
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [name for name, _ in ranked[:top_n]]
