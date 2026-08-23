"""Optional Jellyfin API fallback — only used when a webhook payload
omits provider ids (some Jellyfin webhook-template configs do), keyed
off the item id the payload does always carry."""

import json
import urllib.error
import urllib.request


class JellyfinClient:
    def __init__(self, url, api_key):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key

    def get_item_provider_ids(self, item_id: str):
        """-> (tmdb_id | None, imdb_id | None)"""
        req = urllib.request.Request(
            f"{self.url}/Items/{item_id}",
            headers={"X-Emby-Token": self.api_key})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            return None, None
        provider_ids = body.get("ProviderIds", {})
        tmdb = provider_ids.get("Tmdb")
        imdb = provider_ids.get("Imdb")
        return (int(tmdb) if tmdb else None), imdb
