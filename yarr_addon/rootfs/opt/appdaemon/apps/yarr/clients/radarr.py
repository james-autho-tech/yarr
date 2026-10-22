"""Thin network wrapper around Radarr's REST API v3 — adapter-side,
not unit tested (see clients/tmdb.py's docstring for why)."""

import json
import posixpath
import urllib.error
import urllib.request


class RadarrError(Exception):
    pass


def _poster_url(images):
    """Radarr's own `images` array already carries a publicly-reachable
    TMDB-hosted poster URL (remoteUrl) per movie — used as-is for the
    Library tab's poster grid instead of Radarr's own /MediaCover/...
    path, since the browser can't authenticate to Radarr directly and
    may not even be able to reach it on the network Home Assistant runs
    on, whereas TMDB's image CDN is always public."""
    for img in images or []:
        if img.get("coverType") == "poster" and img.get("remoteUrl"):
            return img["remoteUrl"]
    return None


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

    def get_library_movies(self) -> list:
        """Full-object library listing for the web UI's Library tab —
        title/year/size/monitored, everything get_library_tmdb_ids()
        throws away. Kept separate from that method rather than
        building on top of it, so the existing (load-bearing) call
        path is never touched."""
        _, movies = self._request("GET", "/movie")
        return [{
            "id": m["id"], "tmdb_id": m.get("tmdbId"), "title": m.get("title", ""),
            "year": m.get("year"), "monitored": bool(m.get("monitored", False)),
            "poster_url": _poster_url(m.get("images")),
            "genres": m.get("genres", []), "overview": m.get("overview", ""),
            "size": (m.get("movieFile") or {}).get("size", 0),
            "added": m.get("added"),
            "quality_profile_id": m.get("qualityProfileId"),
            "has_file": bool(m.get("hasFile", False)),
        } for m in (movies or [])]

    def get_excluded_tmdb_ids(self) -> set:
        """Radarr's own import-list exclusion list — what "Delete + Add
        exclusion" writes. yArr treats it as a hard veto on auto-adds
        (see core/discovery.filter_candidates). Newer Radarr versions
        deprecate the unpaged endpoint in favour of /paged, so falls
        back to that if the unpaged one is gone."""
        try:
            _, body = self._request("GET", "/exclusions")
        except RadarrError:
            _, body = self._request("GET", "/exclusions/paged?pageSize=100000")
        records = (body or {}).get("records") if isinstance(body, dict) else body
        return {r["tmdbId"] for r in (records or []) if r.get("tmdbId")}

    def get_queue(self) -> list:
        """Radarr's own Activity/Queue listing — used to find stuck/dead
        downloads (see core/queue.py). Response shape varies by version:
        some return a bare list, others {"records": [...]}."""
        _, body = self._request("GET", "/queue?pageSize=250")
        records = (body or {}).get("records") if isinstance(body, dict) else body
        return [{
            "id": r["id"], "title": r.get("title") or "",
            "added": r.get("added"),
            "status": r.get("status"),
            "tracked_download_status": r.get("trackedDownloadStatus"),
            "error_message": r.get("errorMessage") or
                             "; ".join(m.get("title", "") for m in r.get("statusMessages", [])),
        } for r in (records or [])]

    def remove_queue_item(self, queue_id: int, blocklist: bool = True) -> None:
        """Removes a queue entry, cancels it in the download client, and
        (with blocklist=True) tells Radarr never to grab that release
        again and to search for a replacement immediately — the same
        single call as manually pressing Remove+Blocklist in the
        Activity/Queue UI."""
        self._request(
            "DELETE",
            f"/queue/{queue_id}?removeFromClient=true&blocklist={'true' if blocklist else 'false'}"
            "&skipRedownload=false")

    def get_calendar(self, start: str, end: str) -> list:
        """Radarr's own Calendar data — one entry per release-date type
        (inCinemas/digitalRelease/physicalRelease) that falls in [start,
        end], since a single movie can have distinct dates for each.
        unmonitored=false excludes movies you're not tracking."""
        _, movies = self._request(
            "GET", f"/calendar?start={start}&end={end}&unmonitored=false")
        entries = []
        for m in (movies or []):
            for field, label in (("inCinemas", "In Cinemas"),
                                  ("digitalRelease", "Digital Release"),
                                  ("physicalRelease", "Physical Release")):
                date = m.get(field)
                if date and start <= date[:10] <= end:
                    entries.append({
                        "date": date, "title": m.get("title", ""),
                        "release_type": label,
                        "has_file": bool(m.get("hasFile", False)),
                    })
        return entries

    # -- Profile / library management (the Profiles tab and the Library
    # tab's detail panel). Profiles are always edited read-modify-write
    # on the full object Radarr returns (see core/arr_profiles.py), so
    # fields yArr doesn't model — custom format scores, language — ride
    # along untouched instead of being reset by a partial PUT.

    def get_quality_profiles(self) -> list:
        _, body = self._request("GET", "/qualityprofile")
        return body or []

    def get_quality_profile(self, profile_id: int) -> dict:
        _, body = self._request("GET", f"/qualityprofile/{profile_id}")
        return body

    def create_quality_profile(self, profile: dict) -> dict:
        _, body = self._request("POST", "/qualityprofile", profile)
        return body

    def update_quality_profile(self, profile: dict) -> dict:
        _, body = self._request("PUT", f"/qualityprofile/{profile['id']}", profile)
        return body

    def delete_quality_profile(self, profile_id: int) -> None:
        """Radarr itself refuses (HTTP 400) to delete a profile any
        movie still uses — that error is surfaced as-is rather than
        pre-checked here."""
        self._request("DELETE", f"/qualityprofile/{profile_id}")

    def get_root_folders(self) -> list:
        _, body = self._request("GET", "/rootfolder")
        return [{"path": r.get("path"), "free_space": r.get("freeSpace")}
                for r in (body or []) if r.get("path")]

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

    def get_all_movie_file_paths(self) -> set:
        """Every file path Radarr currently tracks — used to tell a
        duplicate scan's tracked copy apart from a stray leftover
        (bulk duplicate delete), without a per-file lookup."""
        _, movies = self._request("GET", "/movie")
        return {m["movieFile"]["path"] for m in (movies or []) if m.get("movieFile")}

    def find_movie_id_by_file_path(self, path: str):
        """Looks up which movie owns a given file path — used to
        rename the surviving copy after a duplicate delete, since
        Radarr's RenameMovie command needs a movieId, not a path.
        Matches on basename, not the full path: Radarr sees this file
        through its own container's mount, yArr through Home
        Assistant's /media share — the prefixes routinely differ even
        for the identical physical file."""
        target = posixpath.basename(path)
        _, movies = self._request("GET", "/movie")
        for m in movies or []:
            movie_file = m.get("movieFile")
            if movie_file and posixpath.basename(movie_file.get("path", "")) == target:
                return m["id"]
        return None

    def set_movies_quality_profile(self, movie_ids: list, profile_id: int) -> None:
        self._request("PUT", "/movie/editor", {"movieIds": movie_ids, "qualityProfileId": profile_id})

    def set_movies_monitored(self, movie_ids: list, monitored: bool) -> None:
        self._request("PUT", "/movie/editor", {"movieIds": movie_ids, "monitored": monitored})

    def search_movies(self, movie_ids: list) -> None:
        self._request("POST", "/command", {"name": "MoviesSearch", "movieIds": movie_ids})

    def search_missing(self) -> None:
        self._request("POST", "/command", {"name": "MissingMoviesSearch"})

    def rename_movie_files(self, movie_id: int) -> None:
        self._request("POST", "/command", {"name": "RenameMovie", "movieIds": [movie_id]})
