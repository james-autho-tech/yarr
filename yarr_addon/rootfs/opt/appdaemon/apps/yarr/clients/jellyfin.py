"""Jellyfin API client — two jobs, adapter-side, not unit tested (see
clients/radarr.py's docstring for why):

1. Watch-history exclusion: since discovery now comes from TMDB (which
   has no concept of "what have I watched"), Jellyfin's own per-user
   played-status is the source of truth for what to exclude.
2. A fallback provider-id lookup for when a webhook payload omits
   Provider_tmdb/Provider_imdb (some webhook-template configs do),
   keyed off the item id the payload does always carry.
"""

import json
import urllib.error
import urllib.parse
import urllib.request


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
