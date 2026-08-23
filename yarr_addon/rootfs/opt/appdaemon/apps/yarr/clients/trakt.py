"""Thin network wrapper around the Trakt API — adapter-side, not unit
tested (all the decision logic this calls out to lives in
core/trakt_auth.py and is tested there)."""

from datetime import datetime, timedelta, timezone
import json
import urllib.error
import urllib.request

from core.discovery import Candidate
from core.trakt_auth import DeviceCodeResponse, TokenSet

API_BASE = "https://api.trakt.tv"


class TraktError(Exception):
    pass


class TraktClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret

    def _headers(self, access_token=None):
        headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": self.client_id,
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def _post(self, path, body, access_token=None, timeout=10):
        req = urllib.request.Request(
            f"{API_BASE}{path}", method="POST",
            data=json.dumps(body).encode(),
            headers=self._headers(access_token))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, {}

    def _get(self, path, access_token=None, timeout=15):
        req = urllib.request.Request(f"{API_BASE}{path}", headers=self._headers(access_token))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def request_device_code(self) -> DeviceCodeResponse:
        status, body = self._post("/oauth/device/code", {"client_id": self.client_id})
        if status != 200:
            raise TraktError(f"device/code failed: HTTP {status}")
        return DeviceCodeResponse(
            device_code=body["device_code"],
            user_code=body["user_code"],
            verification_url=body["verification_url"],
            expires_in=body["expires_in"],
            interval=body["interval"],
            issued_at=datetime.now(timezone.utc),
        )

    def poll_token(self, device_code: str):
        """Returns a TokenSet on success, None while still pending
        (HTTP 400). Any other status raises — the caller decides
        whether that means "give up" (410 expired, 418 denied)."""
        status, body = self._post("/oauth/device/token", {
            "code": device_code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        if status == 200:
            return self._tokens_from_body(body)
        if status == 400:
            return None
        raise TraktError(f"device/token failed: HTTP {status}")

    def refresh(self, refresh_token: str) -> TokenSet:
        status, body = self._post("/oauth/token", {
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "grant_type": "refresh_token",
        })
        if status != 200:
            raise TraktError(f"token refresh failed: HTTP {status}")
        return self._tokens_from_body(body)

    @staticmethod
    def _tokens_from_body(body) -> TokenSet:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=body["expires_in"])
        return TokenSet(access_token=body["access_token"],
                         refresh_token=body["refresh_token"],
                         expires_at=expires_at)

    def get_recommendations(self, access_token: str) -> list:
        body = self._get("/recommendations/movies?extended=full", access_token)
        out = []
        for m in body:
            ids = m.get("ids", {})
            if ids.get("tmdb") is None:
                continue
            out.append(Candidate(
                tmdb_id=ids["tmdb"],
                imdb_id=ids.get("imdb"),
                title=m.get("title", ""),
                year=m.get("year"),
                genres=list(m.get("genres", [])),
                rating=float(m.get("rating") or 0.0),
            ))
        return out

    def get_history_tmdb_ids(self, access_token: str) -> set:
        body = self._get("/sync/watched/movies", access_token)
        return {m["movie"]["ids"]["tmdb"] for m in body
                if m.get("movie", {}).get("ids", {}).get("tmdb") is not None}
