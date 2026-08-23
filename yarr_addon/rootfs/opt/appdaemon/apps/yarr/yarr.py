import json
import os
from datetime import datetime, timedelta, timezone

# config.yaml's version is the single source of truth (set by `run`
# via YARR_VERSION) instead of a separate hardcoded constant.
VERSION = os.environ.get("YARR_VERSION") or "dev"

import appdaemon.plugins.hass.hassapi as hass

from core.config import build_config, required_secrets_ok, ConfigError
from core import state as core_state
from core import discovery as core_discovery
from core import surprise as core_surprise
from core import webhook as core_webhook
from core import delete_guard as core_delete_guard
from core import trakt_auth as core_trakt_auth

from clients.trakt import TraktClient, TraktError
from clients.radarr import RadarrClient, RadarrError

CONFIG_DIR = "/config/apps/yarr"
STATE_PATH = os.path.join(CONFIG_DIR, "yarr_state.json")
TOKENS_PATH = os.path.join(CONFIG_DIR, "trakt_tokens.json")
DEVICE_FLOW_PATH = os.path.join(CONFIG_DIR, "trakt_device_flow.json")
SECRETS_PATH = os.path.join(CONFIG_DIR, "addon_secrets.json")


class Yarr(hass.Hass):

    # ------------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------------

    def initialize(self):
        try:
            secrets = self._load_json(SECRETS_PATH) or {}
            self.cfg = build_config(self.args, secrets)
        except ConfigError as exc:
            self.error(f"apps.yaml is invalid: {exc}")
            self.cfg = build_config({}, {})

        self.missing_secrets = required_secrets_ok(self.cfg)
        if self.missing_secrets:
            self.log(f"Not fully configured — missing: {', '.join(self.missing_secrets)}. "
                     "Set these in the add-on's Configuration tab.")

        self.state_data = core_state.load(STATE_PATH)
        self.tokens = self._load_tokens()
        self.device_flow = self._load_device_flow()
        self._last_poll_at = None

        self.trakt = TraktClient(self.cfg.trakt_client_id, self.cfg.trakt_client_secret)
        self.radarr = RadarrClient(self.cfg.radarr_url, self.cfg.radarr_api_key)

        self.listen_state(self.on_connect_trakt_pressed, "input_button.yarr_connect_trakt")
        self.listen_state(self.on_surprise_now_pressed, "input_button.yarr_surprise_me_now")
        self.listen_event(self.on_jellyfin_webhook, "yarr_jellyfin_webhook")

        self.run_every(self.tick_discovery, "now", self.cfg.discovery_interval_hours * 3600)
        self.run_every(self.tick_surprise_check, "now", 3600)
        self.run_every(self.tick_delete_guard, "now", 900)
        self.run_every(self.tick_trakt_refresh, "now", 3600)
        self.run_every(self.tick_trakt_poll, "now", 30)
        self.run_every(self.publish_status, "now", 60)

        self.log(f"yArr v{VERSION} started.")

    # ------------------------------------------------------------------
    # ENABLE GATE
    # ------------------------------------------------------------------

    def _enabled(self) -> bool:
        return self.get_state("input_boolean.yarr_enable") != "off"

    # ------------------------------------------------------------------
    # LOCAL STATE / TOKEN PERSISTENCE
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _load_tokens(self):
        raw = self._load_json(TOKENS_PATH)
        if not raw:
            return None
        return core_trakt_auth.TokenSet(
            access_token=raw["access_token"],
            refresh_token=raw["refresh_token"],
            expires_at=datetime.fromisoformat(raw["expires_at"]),
        )

    def _save_tokens(self, tokens):
        self.tokens = tokens
        try:
            with open(TOKENS_PATH, "w") as f:
                json.dump({
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                    "expires_at": tokens.expires_at.isoformat(),
                }, f)
            os.chmod(TOKENS_PATH, 0o600)
        except OSError as exc:
            self.error(f"Could not persist Trakt tokens: {exc}")

    def _load_device_flow(self):
        raw = self._load_json(DEVICE_FLOW_PATH)
        if not raw:
            return None
        return core_trakt_auth.DeviceCodeResponse(
            device_code=raw["device_code"], user_code=raw["user_code"],
            verification_url=raw["verification_url"], expires_in=raw["expires_in"],
            interval=raw["interval"], issued_at=datetime.fromisoformat(raw["issued_at"]))

    def _save_device_flow(self, resp):
        self.device_flow = resp
        if resp is None:
            try:
                os.remove(DEVICE_FLOW_PATH)
            except OSError:
                pass
            return
        with open(DEVICE_FLOW_PATH, "w") as f:
            json.dump({
                "device_code": resp.device_code, "user_code": resp.user_code,
                "verification_url": resp.verification_url, "expires_in": resp.expires_in,
                "interval": resp.interval, "issued_at": resp.issued_at.isoformat(),
            }, f)

    def _save_state(self):
        core_state.save(self.state_data, STATE_PATH)

    # ------------------------------------------------------------------
    # TRAKT CONNECT / REFRESH
    # ------------------------------------------------------------------

    def on_connect_trakt_pressed(self, entity, attribute, old, new, kwargs):
        if not self.cfg.trakt_client_id or not self.cfg.trakt_client_secret:
            self.error("Cannot connect Trakt — trakt_client_id/trakt_client_secret not set.")
            return
        try:
            resp = self.trakt.request_device_code()
        except TraktError as exc:
            self.error(f"Trakt device-code request failed: {exc}")
            return
        self._save_device_flow(resp)
        self._last_poll_at = None
        self.log(f"Trakt: visit {resp.verification_url} and enter code {resp.user_code}")

    def tick_trakt_poll(self, kwargs):
        if self.tokens is not None or self.device_flow is None:
            return
        now = datetime.now(timezone.utc)
        if core_trakt_auth.is_device_code_expired(self.device_flow, now):
            self.log("Trakt device code expired before approval — press Connect Trakt again.")
            self._save_device_flow(None)
            return
        if not core_trakt_auth.should_poll(self.device_flow, now, self._last_poll_at):
            return
        self._last_poll_at = now
        try:
            tokens = self.trakt.poll_token(self.device_flow.device_code)
        except TraktError as exc:
            self.error(f"Trakt token poll failed: {exc}")
            return
        if tokens is not None:
            self._save_tokens(tokens)
            self._save_device_flow(None)
            self.log("Trakt connected.")

    def tick_trakt_refresh(self, kwargs):
        if self.tokens is None:
            return
        now = datetime.now(timezone.utc)
        if not core_trakt_auth.needs_refresh(self.tokens, now):
            return
        try:
            self._save_tokens(self.trakt.refresh(self.tokens.refresh_token))
            self.log("Trakt token refreshed.")
        except TraktError as exc:
            self.error(f"Trakt token refresh failed — reconnect may be required: {exc}")
            self.tokens = None
            try:
                os.remove(TOKENS_PATH)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # DISCOVERY / SURPRISE
    # ------------------------------------------------------------------

    def _resync_watched_cache_if_stale(self, now):
        synced_at = self.state_data.watched_cache_synced_at
        stale = (synced_at is None or
                 now >= datetime.fromisoformat(synced_at) +
                 timedelta(hours=self.cfg.trakt_history_resync_hours))
        if not stale:
            return
        ids = self.trakt.get_history_tmdb_ids(self.tokens.access_token)
        self.state_data.watched_tmdb_cache = list(ids)
        self.state_data.watched_cache_synced_at = now.isoformat()
        self._save_state()

    def tick_discovery(self, kwargs):
        if not self._enabled() or self.tokens is None or self.missing_secrets:
            return
        now = datetime.now(timezone.utc)
        try:
            self._resync_watched_cache_if_stale(now)
            candidates = self.trakt.get_recommendations(self.tokens.access_token)
            radarr_ids = self.radarr.get_library_tmdb_ids()
        except (TraktError, RadarrError) as exc:
            self.error(f"tick_discovery failed: {exc}")
            return

        picks = core_discovery.filter_candidates(
            candidates,
            allowed_genres=self.cfg.genres,
            min_rating=self.cfg.min_rating,
            watched_tmdb_ids=set(self.state_data.watched_tmdb_cache),
            radarr_tmdb_ids=radarr_ids,
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested})
        picks = picks[: self.cfg.max_suggestions_per_run]

        for c in picks:
            radarr_movie_id = None
            if not self.cfg.dry_run:
                try:
                    qp_id = self.radarr.resolve_quality_profile_id(self.cfg.radarr_quality_profile_name)
                    radarr_movie_id = self.radarr.add_movie(
                        c, root_folder=self.cfg.radarr_root_folder,
                        quality_profile_id=qp_id,
                        minimum_availability=self.cfg.radarr_minimum_availability)
                except RadarrError as exc:
                    self.error(f"Could not add {c.title!r} to Radarr: {exc}")
                    continue
            self.log(f"yArr: added {c.title!r} ({c.year}) — rating {c.rating}")
            self.state_data = core_state.record_suggestion(self.state_data, core_state.SuggestedFilm(
                tmdb_id=c.tmdb_id, imdb_id=c.imdb_id, title=c.title, source="genre",
                decision="added", suggested_at=now.isoformat(), radarr_movie_id=radarr_movie_id))
        if picks:
            self._save_state()

    def on_surprise_now_pressed(self, entity, attribute, old, new, kwargs):
        self._run_surprise_pick()

    def tick_surprise_check(self, kwargs):
        if not self._enabled() or not self.cfg.surprise_enabled:
            return
        now = datetime.now(timezone.utc)
        if not core_surprise.is_surprise_due(now, self.state_data.next_surprise_at):
            return
        self._run_surprise_pick()

    def _run_surprise_pick(self):
        if self.tokens is None or self.missing_secrets:
            return
        now = datetime.now(timezone.utc)
        try:
            self._resync_watched_cache_if_stale(now)
            candidates = self.trakt.get_recommendations(self.tokens.access_token)
            radarr_ids = self.radarr.get_library_tmdb_ids()
        except (TraktError, RadarrError) as exc:
            self.error(f"surprise pick failed: {exc}")
            return

        genres = self.cfg.surprise_genres if self.cfg.surprise_genres is not None else self.cfg.genres
        pool = core_discovery.filter_candidates(
            candidates, allowed_genres=genres, min_rating=self.cfg.min_rating,
            watched_tmdb_ids=set(self.state_data.watched_tmdb_cache),
            radarr_tmdb_ids=radarr_ids,
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested} |
                                        {int(k) for k in self.state_data.surprises})
        pick = core_discovery.pick_surprise(pool, exclude_tmdb_ids=set())

        window = core_surprise.SurpriseWindow(self.cfg.surprise_min_days, self.cfg.surprise_max_days)
        self.state_data.next_surprise_at = core_surprise.next_surprise_time(now, window).isoformat()

        if pick is None:
            self.log("yArr: no surprise candidate matched your filters this time.")
            self._save_state()
            return

        radarr_movie_id = None
        if not self.cfg.dry_run:
            try:
                qp_id = self.radarr.resolve_quality_profile_id(self.cfg.radarr_quality_profile_name)
                tag_id = self.radarr.ensure_tag(self.cfg.surprise_tag)
                radarr_movie_id = self.radarr.add_movie(
                    pick, root_folder=self.cfg.radarr_root_folder,
                    quality_profile_id=qp_id, tag_ids=[tag_id],
                    minimum_availability=self.cfg.radarr_minimum_availability)
            except RadarrError as exc:
                self.error(f"Could not add surprise {pick.title!r} to Radarr: {exc}")
                self._save_state()
                return

        self.log(f"yArr surprise: {pick.title!r} ({pick.year})")
        self.state_data = core_state.record_surprise_added(
            self.state_data, tmdb_id=pick.tmdb_id, imdb_id=pick.imdb_id,
            title=pick.title, radarr_movie_id=radarr_movie_id, now=now)
        self._save_state()
        self.call_service("persistent_notification/create", title="yArr surprise",
                           message=f"Tonight's surprise: {pick.title} ({pick.year})")

    # ------------------------------------------------------------------
    # JELLYFIN WEBHOOK / DELETE GUARD
    # ------------------------------------------------------------------

    def on_jellyfin_webhook(self, event_name, data, kwargs):
        payload = (data or {}).get("payload")
        event = core_webhook.parse_jellyfin_payload(payload)
        if event is None:
            return
        film = core_webhook.matches_surprise(event, self.state_data.surprises)
        if film is None:
            return
        if event.percentage < self.cfg.completion_threshold_pct:
            return

        now = datetime.now(timezone.utc)
        self.state_data = core_state.mark_watched(self.state_data, film.tmdb_id, now)
        self.state_data = core_state.schedule_deletion(
            self.state_data, film.tmdb_id, now, self.cfg.delete_grace_period_hours)
        self._save_state()
        self.set_state("input_boolean.yarr_keep_surprise", state="off")
        self.call_service(
            "persistent_notification/create", title="yArr: surprise film watched",
            message=(f"{film.title} will be deleted in {self.cfg.delete_grace_period_hours:g}h. "
                     "Flip 'yArr: Keep the pending surprise film' on to keep it instead."))

    def tick_delete_guard(self, kwargs):
        now = datetime.now(timezone.utc)
        due = core_state.due_deletions(self.state_data, now)
        if not due:
            return
        keep = self.get_state("input_boolean.yarr_keep_surprise") == "on"
        for film in due:
            if keep:
                self.state_data = core_state.cancel_deletion(self.state_data, film.tmdb_id)
                self.log(f"yArr: kept {film.title!r} per yarr_keep_surprise.")
                continue
            if not self.cfg.dry_run and film.radarr_movie_id is not None:
                try:
                    self.radarr.delete_movie(film.radarr_movie_id)
                except RadarrError as exc:
                    self.error(f"Could not delete {film.title!r} from Radarr: {exc}")
                    continue
            self.log(f"yArr: deleted {film.title!r} after the grace period.")
            self.state_data = core_state.confirm_deleted(self.state_data, film.tmdb_id)
        self.set_state("input_boolean.yarr_keep_surprise", state="off")
        self._save_state()

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    def publish_status(self, kwargs):
        if self.missing_secrets:
            trakt_status = "not_configured"
        elif self.device_flow is not None and self.tokens is None:
            trakt_status = "awaiting_approval"
        elif self.tokens is not None:
            trakt_status = "connected"
        else:
            trakt_status = "disconnected"

        attrs = {
            "trakt_status": trakt_status,
            "suggested_count": len(self.state_data.suggested),
            "surprise_count": len(self.state_data.surprises),
            "next_surprise_at": self.state_data.next_surprise_at,
            "missing_secrets": self.missing_secrets,
        }
        if self.device_flow is not None and self.tokens is None:
            attrs["user_code"] = self.device_flow.user_code
            attrs["verification_url"] = self.device_flow.verification_url

        self.set_state("sensor.yarr_status",
                        state="Not Configured" if self.missing_secrets else "OK",
                        attributes=attrs)
        self.set_state("sensor.yarr_heartbeat", state=datetime.now(timezone.utc).isoformat())
