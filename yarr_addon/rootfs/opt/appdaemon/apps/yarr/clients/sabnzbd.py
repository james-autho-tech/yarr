"""Thin network wrapper around SABnzbd's API — adapter-side, not unit
tested (see clients/tmdb.py's docstring for why). Monitoring plus the
SABnzbd tab's global Pause/Resume buttons, plus moving the completed-
download folder out of the library — yArr never queues, deletes or
reorders individual jobs."""

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

    def _command(self, mode, timeout=10) -> None:
        params = {"mode": mode, "output": "json", "apikey": self.api_key}
        url = f"{self.url}/api?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            raise SABnzbdError(f"{mode} failed: {exc}") from exc
        if not body.get("status", False):
            raise SABnzbdError(f"{mode} failed: {body.get('error') or body}")

    def get_folder_config(self, timeout=10) -> dict:
        """-> {download_dir, complete_dir, categories: [{name, dir}]} —
        only the folder settings; the rest of get_config (API keys,
        server passwords) is deliberately dropped here, never returned."""
        params = {"mode": "get_config", "output": "json", "apikey": self.api_key}
        url = f"{self.url}/api?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                config = json.loads(resp.read()).get("config", {})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            raise SABnzbdError(f"get_config failed: {exc}") from exc
        misc = config.get("misc", {})
        return {
            "download_dir": misc.get("download_dir"), "complete_dir": misc.get("complete_dir"),
            "categories": [{"name": c.get("name"), "dir": c.get("dir")}
                           for c in config.get("categories", []) if c.get("name")],
        }

    def set_complete_dir(self, path: str, timeout=10) -> None:
        """Sets SABnzbd's completed-download folder (Config → Folders).
        Category folders are relative to it, so they move along."""
        params = {"mode": "set_config", "section": "misc", "keyword": "complete_dir",
                  "value": path, "output": "json", "apikey": self.api_key}
        url = f"{self.url}/api?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            raise SABnzbdError(f"set_config complete_dir failed: {exc}") from exc
        if isinstance(body, dict) and body.get("status") is False:
            raise SABnzbdError(f"set_config complete_dir failed: {body.get('error') or body}")

    def pause(self) -> None:
        """Pauses the whole queue — same as SABnzbd's own global pause
        button. A SABnzbd schedule entry can still resume it later."""
        self._command("pause")

    def resume(self) -> None:
        """Resumes the whole queue. A SABnzbd schedule entry can still
        pause it again at its next scheduled time."""
        self._command("resume")
