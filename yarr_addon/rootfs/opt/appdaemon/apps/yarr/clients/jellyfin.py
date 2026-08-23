"""Jellyfin API client — adapter-side, not unit tested (see
clients/tmdb.py's docstring for why). Several jobs:

1. Watch-history exclusion: since discovery comes from TMDB (which has
   no concept of "what have I watched"), Jellyfin's own per-user
   played-status is the source of truth for what to exclude, for both
   movies (tmdb-keyed) and shows (tvdb-keyed).
2. A fallback provider-id lookup for when a webhook payload omits
   Provider_tmdb/Provider_imdb (some webhook-template configs do),
   keyed off the item id the payload does always carry.
3. Resolving an episode webhook's SeriesId to the series' own tvdb_id,
   and checking whether a whole series is now fully watched.
4. Library genre-preference learning (core/taste.py) — reads your
   watched movies/shows with genres/play-count/favourite status.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from core.taste import WatchedItem


class JellyfinError(Exception):
    pass


class JellyfinClient:
    def __init__(self, url, api_key):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key

    def _headers(self):
        return {"X-Emby-Token": self.api_key}

    def _get(self, path, params=None, timeout=15):
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        req = urllib.request.Request(f"{self.url}{path}{query}", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise JellyfinError(f"GET {path} failed: HTTP {exc.code}") from exc

    def get_item_provider_ids(self, item_id: str):
        """-> (tmdb_id | None, imdb_id | None). Swallows errors (returns
        (None, None)) — this is only ever a best-effort fallback."""
        try:
            body = self._get(f"/Items/{item_id}")
        except (JellyfinError, urllib.error.URLError, TimeoutError, ValueError):
            return None, None
        provider_ids = body.get("ProviderIds", {})
        tmdb = provider_ids.get("Tmdb")
        imdb = provider_ids.get("Imdb")
        return (int(tmdb) if tmdb else None), imdb

    def get_series_tvdb_id(self, series_item_id: str):
        """-> tvdb_id | None, resolving an episode webhook's SeriesId
        (Jellyfin's own internal item id) to the id Sonarr's library
        actually uses. Swallows errors — best-effort, same as above."""
        try:
            body = self._get(f"/Items/{series_item_id}")
        except (JellyfinError, urllib.error.URLError, TimeoutError, ValueError):
            return None
        tvdb = body.get("ProviderIds", {}).get("Tvdb")
        return int(tvdb) if tvdb else None

    def is_series_fully_watched(self, user_id: str, series_item_id: str) -> bool:
        try:
            body = self._get(f"/Users/{user_id}/Items/{series_item_id}")
        except (JellyfinError, urllib.error.URLError, TimeoutError, ValueError):
            return False
        user_data = body.get("UserData", {})
        if user_data.get("Played"):
            return True
        return user_data.get("UnplayedItemCount") == 0

    def resolve_user_id(self, username=None) -> str:
        users = self._get("/Users")
        if username:
            for u in users:
                if u.get("Name") == username:
                    return u["Id"]
            raise JellyfinError(f"No Jellyfin user named {username!r}")
        if not users:
            raise JellyfinError("No Jellyfin users found")
        return users[0]["Id"]

    def get_watched_tmdb_ids(self, user_id: str) -> set:
        body = self._get(f"/Users/{user_id}/Items", {
            "Recursive": "true",
            "IncludeItemTypes": "Movie",
            "Filters": "IsPlayed",
            "Fields": "ProviderIds",
        })
        out = set()
        for item in body.get("Items", []):
            tmdb = item.get("ProviderIds", {}).get("Tmdb")
            if tmdb:
                try:
                    out.add(int(tmdb))
                except ValueError:
                    continue
        return out

    def get_watched_tvdb_ids(self, user_id: str) -> set:
        body = self._get(f"/Users/{user_id}/Items", {
            "Recursive": "true",
            "IncludeItemTypes": "Series",
            "Filters": "IsPlayed",
            "Fields": "ProviderIds",
        })
        out = set()
        for item in body.get("Items", []):
            tvdb = item.get("ProviderIds", {}).get("Tvdb")
            if tvdb:
                try:
                    out.add(int(tvdb))
                except ValueError:
                    continue
        return out

    def get_watched_items_for_taste(self, user_id: str, item_type: str) -> list:
        """item_type: "Movie" or "Series". Returns core.taste.WatchedItem
        entries for every played item, genres/play-count/favourite as
        reported by Jellyfin's own library metadata — used to derive a
        weighted genre profile (core/taste.py) instead of a hand-typed
        genre list."""
        body = self._get(f"/Users/{user_id}/Items", {
            "Recursive": "true",
            "IncludeItemTypes": item_type,
            "Filters": "IsPlayed",
            "Fields": "Genres,UserData",
        })
        out = []
        for item in body.get("Items", []):
            user_data = item.get("UserData", {})
            out.append(WatchedItem(
                genres=list(item.get("Genres", [])),
                play_count=int(user_data.get("PlayCount", 0) or 0),
                is_favorite=bool(user_data.get("IsFavorite", False)),
            ))
        return out
