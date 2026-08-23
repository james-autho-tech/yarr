"""Thin network wrapper around the TMDB (The Movie Database) API —
adapter-side, not unit tested (see clients/radarr.py's docstring for
why). Just an API key, no OAuth — https://www.themoviedb.org/settings/api.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from core.discovery import Candidate

API_BASE = "https://api.themoviedb.org/3"


class TMDBError(Exception):
    pass


class TMDBClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self._genre_name_to_id = None

    def _get(self, path, params=None, timeout=15):
        query = {"api_key": self.api_key, **(params or {})}
        url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise TMDBError(f"GET {path} failed: HTTP {exc.code}") from exc

    def _genre_ids_for(self, genre_names):
        if self._genre_name_to_id is None:
            body = self._get("/genre/movie/list")
            self._genre_name_to_id = {g["name"].lower(): g["id"] for g in body.get("genres", [])}
        return [self._genre_name_to_id[g] for g in genre_names if g in self._genre_name_to_id]

    def discover(self, genres, min_rating, *, pages=1) -> list:
        """Empty genres -> no genre filter (just the rating floor,
        matching core/discovery.filter_candidates' own convention)."""
        params = {
            "sort_by": "popularity.desc",
            "vote_average.gte": min_rating,
            "vote_count.gte": 50,  # excludes near-zero-vote outliers with a fluke high rating
            "include_adult": "false",
        }
        genre_ids = self._genre_ids_for(genres) if genres else []
        if genres and genre_ids:
            params["with_genres"] = ",".join(str(i) for i in genre_ids)

        out = []
        for page in range(1, pages + 1):
            body = self._get("/discover/movie", {**params, "page": page})
            for m in body.get("results", []):
                genre_names = [name for name, gid in self._genre_name_to_id.items()
                               if gid in m.get("genre_ids", [])]
                year = None
                if m.get("release_date"):
                    try:
                        year = int(m["release_date"][:4])
                    except ValueError:
                        pass
                out.append(Candidate(
                    tmdb_id=m["id"], imdb_id=None, title=m.get("title", ""),
                    year=year, genres=genre_names, rating=float(m.get("vote_average") or 0.0)))
        return out

    def get_imdb_id(self, tmdb_id: int):
        body = self._get(f"/movie/{tmdb_id}/external_ids")
        return body.get("imdb_id") or None
