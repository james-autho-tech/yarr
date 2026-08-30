"""Thin network wrapper around Radarr's REST API v3 — adapter-side,
not unit tested (see clients/tmdb.py's docstring for why)."""

import json
import urllib.error
import urllib.request


class RadarrError(Exception):
    pass


class RadarrClient:
    def __init__(self, url, api_key):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key

    def _headers(self):
        return {"X-Api-Key": self.api_key, "Content-Type": "application/json"}

    def _request(self, method, path, body=None, timeout=15):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.url}/api/v3{path}", method=method, data=data, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            # Radarr's error responses carry the real reason (e.g. a
            # bad rootFolderPath, an already-added movie) as a JSON body
            # — surfacing only the status code here made every failure
            # look identical and undebuggable from the log alone.
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 — best-effort, never let this mask the real error
                pass
            raise RadarrError(f"{method} {path} failed: HTTP {exc.code} {detail}".rstrip()) from exc

    def get_library_tmdb_ids(self) -> set:
        _, body = self._request("GET", "/movie")
        return {m["tmdbId"] for m in (body or [])}

    def resolve_quality_profile_id(self, name: str) -> int:
        _, body = self._request("GET", "/qualityprofile")
        for p in body or []:
            if p.get("name") == name:
                return p["id"]
        raise RadarrError(f"No Radarr quality profile named {name!r}")

    def ensure_tag(self, label: str) -> int:
        _, body = self._request("GET", "/tag")
        for t in body or []:
            if t.get("label") == label:
                return t["id"]
        _, created = self._request("POST", "/tag", {"label": label})
        return created["id"]

    def add_movie(self, candidate, *, root_folder, quality_profile_id,
                  tag_ids=None, minimum_availability="announced") -> int:
        body = {
            "tmdbId": candidate.tmdb_id,
            "title": candidate.title,
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            "minimumAvailability": minimum_availability,
            "tags": tag_ids or [],
            "addOptions": {"searchForMovie": True},
        }
        _, created = self._request("POST", "/movie", body)
        return created["id"]

    def delete_movie(self, movie_id: int, delete_files: bool = True) -> None:
        self._request("DELETE", f"/movie/{movie_id}?deleteFiles={'true' if delete_files else 'false'}")

    def rescan_library(self) -> None:
        """Full-library refresh/rescan (no movieId) — used after
        deleting a duplicate file directly off disk (bypassing Radarr's
        own delete flow) so Radarr notices the file is gone right away
        instead of waiting for its own periodic disk scan."""
        self._request("POST", "/command", {"name": "RefreshMovie"})

    def find_movie_id_by_file_path(self, path: str):
        """Looks up which movie owns a given file path — used to
        rename the surviving copy after a duplicate delete, since
        Radarr's RenameMovie command needs a movieId, not a path."""
        _, movies = self._request("GET", "/movie")
        for m in movies or []:
            movie_file = m.get("movieFile")
            if movie_file and movie_file.get("path") == path:
                return m["id"]
        return None

    def rename_movie_files(self, movie_id: int) -> None:
        self._request("POST", "/command", {"name": "RenameMovie", "movieIds": [movie_id]})
