"""Thin network wrapper around Sonarr's REST API v3 — adapter-side,
not unit tested (see clients/tmdb.py's docstring for why). Mirrors
clients/radarr.py's shape, keyed on tvdbId instead of tmdbId since
that's what Sonarr's own Series resource uses natively."""

import json
import urllib.error
import urllib.request


class SonarrError(Exception):
    pass


class SonarrClient:
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
            # Sonarr's error responses carry the real reason (e.g. a
            # bad rootFolderPath, a missing languageProfileId) as a
            # JSON body — surfacing only the status code here made every
            # failure look identical and undebuggable from the log alone.
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 — best-effort, never let this mask the real error
                pass
            raise SonarrError(f"{method} {path} failed: HTTP {exc.code} {detail}".rstrip()) from exc

    def get_library_tvdb_ids(self) -> set:
        _, body = self._request("GET", "/series")
        return {s["tvdbId"] for s in (body or []) if s.get("tvdbId")}

    def resolve_quality_profile_id(self, name: str) -> int:
        _, body = self._request("GET", "/qualityprofile")
        for p in body or []:
            if p.get("name") == name:
                return p["id"]
        raise SonarrError(f"No Sonarr quality profile named {name!r}")

    def ensure_tag(self, label: str) -> int:
        _, body = self._request("GET", "/tag")
        for t in body or []:
            if t.get("label") == label:
                return t["id"]
        _, created = self._request("POST", "/tag", {"label": label})
        return created["id"]

    def add_series(self, candidate, *, root_folder, quality_profile_id,
                   tag_ids=None, language_profile_id=None, season_folder=True) -> int:
        body = {
            "tvdbId": candidate.tvdb_id,
            "title": candidate.title,
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder,
            "seasonFolder": season_folder,
            "monitored": True,
            "tags": tag_ids or [],
            "addOptions": {"monitor": "all", "searchForMissingEpisodes": True},
        }
        # Sonarr v3 requires languageProfileId; v4 dropped the concept
        # entirely — only send it if apps.yaml sets one, so v4 users
        # don't get a rejected request over a field their version
        # doesn't recognise.
        if language_profile_id is not None:
            body["languageProfileId"] = language_profile_id
        _, created = self._request("POST", "/series", body)
        return created["id"]

    def delete_series(self, series_id: int, delete_files: bool = True) -> None:
        self._request("DELETE", f"/series/{series_id}?deleteFiles={'true' if delete_files else 'false'}")

    def rescan_library(self) -> None:
        """Full-library refresh/rescan (no seriesId) — used after
        deleting a duplicate file directly off disk (bypassing Sonarr's
        own delete flow) so Sonarr notices the file is gone right away
        instead of waiting for its own periodic disk scan."""
        self._request("POST", "/command", {"name": "RefreshSeries"})

    def get_all_episode_file_paths(self) -> set:
        """Every episode file path Sonarr currently tracks — used to
        tell a duplicate scan's tracked copy apart from a stray
        leftover (bulk duplicate delete). Unlike Radarr's /movie
        (which embeds each movie's file inline), Sonarr's /episodefile
        rejects an unscoped GET ("seriesId or episodeFileIds must be
        provided" — confirmed via a real 400 on a live install), so
        this fetches the series list first and queries per series."""
        _, series_list = self._request("GET", "/series")
        paths = set()
        for s in series_list or []:
            series_id = s.get("id")
            if series_id is None:
                continue
            _, files = self._request("GET", f"/episodefile?seriesId={series_id}")
            paths.update(f["path"] for f in (files or []) if f.get("path"))
        return paths

    def find_series_id_by_file_path(self, path: str):
        """Looks up which series owns a given episode file path — used
        to rename the surviving copy after a duplicate delete, since
        Sonarr's RenameSeries command needs a seriesId, not a path.
        Episode files are their own resource in Sonarr (unlike Radarr,
        where movieFile is embedded on the movie itself), and
        /episodefile needs a seriesId to query at all — see
        get_all_episode_file_paths's docstring — so this checks each
        series' files in turn and stops at the first path match."""
        _, series_list = self._request("GET", "/series")
        for s in series_list or []:
            series_id = s.get("id")
            if series_id is None:
                continue
            _, files = self._request("GET", f"/episodefile?seriesId={series_id}")
            for f in files or []:
                if f.get("path") == path:
                    return series_id
        return None

    def rename_series_files(self, series_id: int) -> None:
        self._request("POST", "/command", {"name": "RenameSeries", "seriesIds": [series_id]})
