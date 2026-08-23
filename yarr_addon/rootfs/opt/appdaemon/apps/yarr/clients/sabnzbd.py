"""Thin network wrapper around SABnzbd's API — adapter-side, not unit
tested (see clients/tmdb.py's docstring for why). Read-only monitoring
only; yArr never queues/pauses/cancels anything in SABnzbd, it just
surfaces queue status as an HA sensor."""

import json
import urllib.error
import urllib.parse
import urllib.request


class SABnzbdError(Exception):
    pass


class SABnzbdClient:
    def __init__(self, url, api_key):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key

    def get_queue(self, timeout=10) -> dict:
        """-> {status, speed_kbps, mb_left, mb_total, eta, size_left_str,
        items: [{filename, percentage, mb_left, mb_total, status}]}"""
        params = {"mode": "queue", "output": "json", "apikey": self.api_key}
        url = f"{self.url}/api?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            raise SABnzbdError(f"queue fetch failed: {exc}") from exc

        queue = body.get("queue", {})
        try:
            speed_kbps = float(queue.get("kbpersec", 0) or 0)
        except (TypeError, ValueError):
            speed_kbps = 0.0
        items = []
        for slot in queue.get("slots", []):
            try:
                pct = float(slot.get("percentage", 0) or 0)
            except (TypeError, ValueError):
                pct = 0.0
            items.append({
                "filename": slot.get("filename", ""),
                "percentage": pct,
                "size": slot.get("size", ""),
                "sizeleft": slot.get("sizeleft", ""),
                "status": slot.get("status", ""),
            })
        return {
            "status": queue.get("status", "unknown"),
            "speed_kbps": speed_kbps,
            "size_left": queue.get("sizeleft", ""),
            "eta": queue.get("timeleft", ""),
            "paused": bool(queue.get("paused", False)),
            "items": items,
        }
