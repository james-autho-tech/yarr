"""Thin network wrapper around the TMDB (The Movie Database) API —
adapter-side, not unit tested (see clients/radarr.py's docstring for
why). Just an API key, no OAuth — https://www.themoviedb.org/settings/api.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from core.discovery import Candidate, TVCandidate

API_BASE = "https://api.themoviedb.org/3"


class TMDBError(Exception):
    pass


class TMDBClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self._movie_genre_name_to_id = None
        self._tv_genre_name_to_id = None

    def _get(self, path, params=None, timeout=15):
        query = {"api_key": self.api_key, **(params or {})}
        url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise TMDBError(f"GET {path} failed: HTTP {exc.code}") from exc

    def _movie_genre_ids_for(self, genre_names):
        if self._movie_genre_name_to_id is None:
            body = self._get("/genre/movie/list")
            self._movie_genre_name_to_id = {g["name"].lower(): g["id"] for g in body.get("genres", [])}
        return [self._movie_genre_name_to_id[g] for g in genre_names if g in self._movie_genre_name_to_id]

    def _tv_genre_ids_for(self, genre_names):
        if self._tv_genre_name_to_id is None:
            body = self._get("/genre/tv/list")
            self._tv_genre_name_to_id = {g["name"].lower(): g["id"] for g in body.get("genres", [])}
        return [self._tv_genre_name_to_id[g] for g in genre_names if g in self._tv_genre_name_to_id]

    def discover(self, genres, min_rating, *, pages=1) -> list:
        """Empty genres -> no genre filter (just the rating floor,
        matching core/discovery.filter_candidates' own convention)."""
        params = {
            "sort_by": "popularity.desc",
            "vote_average.gte": min_rating,
            "vote_count.gte": 50,  # excludes near-zero-vote outliers with a fluke high rating
            "include_adult": "false",
        }
        genre_ids = self._movie_genre_ids_for(genres) if genres else []
        if genres and genre_ids:
            params["with_genres"] = ",".join(str(i) for i in genre_ids)

        out = []
        for page in range(1, pages + 1):
            body = self._get("/discover/movie", {**params, "page": page})
            for m in body.get("results", []):
                genre_names = [name for name, gid in self._movie_genre_name_to_id.items()
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

    def search_movies(self, query: str, *, page=1) -> list:
        """Text search (Library tab's request hub/detail view). Not
        genre-filtered like discover() (no allowed-genre list to check
        against), but genre *names* are still resolved for display —
        same reverse-lookup cache discover() populates."""
        self._movie_genre_ids_for([])  # force-populate the name->id cache, ignoring the (empty) result
        body = self._get("/search/movie", {"query": query, "page": page, "include_adult": "false"})
        out = []
        for m in body.get("results", []):
            year = None
            if m.get("release_date"):
                try:
                    year = int(m["release_date"][:4])
                except ValueError:
                    pass
            genre_names = [name for name, gid in self._movie_genre_name_to_id.items()
                           if gid in m.get("genre_ids", [])]
            out.append(Candidate(
                tmdb_id=m["id"], imdb_id=None, title=m.get("title", ""),
                year=year, genres=genre_names, rating=float(m.get("vote_average") or 0.0),
                poster_path=m.get("poster_path"), overview=m.get("overview", "")))
        return out

    def search_tv(self, query: str, *, page=1) -> list:
        """Same tvdb_id-resolution requirement as discover_tv() — a
        result without one is dropped, Sonarr couldn't add it anyway."""
        self._tv_genre_ids_for([])
        body = self._get("/search/tv", {"query": query, "page": page, "include_adult": "false"})
        out = []
        for m in body.get("results", []):
            year = None
            if m.get("first_air_date"):
                try:
                    year = int(m["first_air_date"][:4])
                except ValueError:
                    pass
            try:
                ext = self._get(f"/tv/{m['id']}/external_ids")
            except TMDBError:
                continue
            tvdb_id = ext.get("tvdb_id")
            if not tvdb_id:
                continue
            genre_names = [name for name, gid in self._tv_genre_name_to_id.items()
                           if gid in m.get("genre_ids", [])]
            out.append(TVCandidate(
                tmdb_id=m["id"], tvdb_id=tvdb_id, imdb_id=ext.get("imdb_id"),
                title=m.get("name", ""), year=year, genres=genre_names,
                rating=float(m.get("vote_average") or 0.0),
                poster_path=m.get("poster_path"), overview=m.get("overview", "")))
        return out

    def discover_tv(self, genres, min_rating, *, pages=1) -> list:
        """Sonarr needs a tvdb_id to add anything (it has no native
        TMDB concept — see TVCandidate's docstring), so this resolves
        external_ids for every result up front, one extra TMDB call
        per candidate, rather than lazily like get_imdb_id() does for
        movies. A result without a resolvable tvdb_id is dropped —
        Sonarr couldn't add it anyway."""
        params = {
            "sort_by": "popularity.desc",
            "vote_average.gte": min_rating,
            "vote_count.gte": 50,
            "include_adult": "false",
        }
        genre_ids = self._tv_genre_ids_for(genres) if genres else []
        if genres and genre_ids:
            params["with_genres"] = ",".join(str(i) for i in genre_ids)

        out = []
        for page in range(1, pages + 1):
            body = self._get("/discover/tv", {**params, "page": page})
            for m in body.get("results", []):
                genre_names = [name for name, gid in self._tv_genre_name_to_id.items()
                               if gid in m.get("genre_ids", [])]
                year = None
                if m.get("first_air_date"):
                    try:
                        year = int(m["first_air_date"][:4])
                    except ValueError:
                        pass
                try:
                    ext = self._get(f"/tv/{m['id']}/external_ids")
                except TMDBError:
                    continue
                tvdb_id = ext.get("tvdb_id")
                if not tvdb_id:
                    continue
                out.append(TVCandidate(
                    tmdb_id=m["id"], tvdb_id=tvdb_id, imdb_id=ext.get("imdb_id"),
                    title=m.get("name", ""), year=year, genres=genre_names,
                    rating=float(m.get("vote_average") or 0.0)))
        return out
