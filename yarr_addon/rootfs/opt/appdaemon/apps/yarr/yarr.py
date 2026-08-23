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

from clients.tmdb import TMDBClient, TMDBError
from clients.radarr import RadarrClient, RadarrError
from clients.jellyfin import JellyfinClient, JellyfinError

CONFIG_DIR = "/config/apps/yarr"
STATE_PATH = os.path.join(CONFIG_DIR, "yarr_state.json")
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

        self.tmdb = TMDBClient(self.cfg.tmdb_api_key)
        self.radarr = RadarrClient(self.cfg.radarr_url, self.cfg.radarr_api_key)
        self.jellyfin = JellyfinClient(self.cfg.jellyfin_url, self.cfg.jellyfin_api_key)
        self._jellyfin_user_id = None

        self.listen_state(self.on_surprise_now_pressed, "input_button.yarr_surprise_me_now")
        self.listen_event(self.on_jellyfin_webhook, "yarr_jellyfin_webhook")

        self.run_every(self.tick_discovery, "now", self.cfg.discovery_interval_hours * 3600)
        self.run_every(self.tick_surprise_check, "now", 3600)
        self.run_every(self.tick_delete_guard, "now", 900)
        self.run_every(self.publish_status, "now", 60)

        self.log(f"yArr v{VERSION} started.")

    # ------------------------------------------------------------------
    # ENABLE GATE
    # ------------------------------------------------------------------

    def _enabled(self) -> bool:
        return self.get_state("input_boolean.yarr_enable") != "off"

    # ------------------------------------------------------------------
    # LOCAL STATE
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json(path):
        import json
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _save_state(self):
        core_state.save(self.state_data, STATE_PATH)

    def _jellyfin_user(self):
        if self._jellyfin_user_id is None:
            self._jellyfin_user_id = self.jellyfin.resolve_user_id(self.cfg.jellyfin_username)
        return self._jellyfin_user_id

    # ------------------------------------------------------------------
    # DISCOVERY / SURPRISE
    # ------------------------------------------------------------------

    def _resync_watched_cache_if_stale(self, now):
        synced_at = self.state_data.watched_cache_synced_at
        stale = (synced_at is None or
                 now >= datetime.fromisoformat(synced_at) +
                 timedelta(hours=self.cfg.watched_resync_hours))
        if not stale:
            return
        ids = self.jellyfin.get_watched_tmdb_ids(self._jellyfin_user())
        self.state_data.watched_tmdb_cache = list(ids)
        self.state_data.watched_cache_synced_at = now.isoformat()
        self._save_state()

    def tick_discovery(self, kwargs):
        if not self._enabled() or self.missing_secrets:
            return
        now = datetime.now(timezone.utc)
        try:
            self._resync_watched_cache_if_stale(now)
            candidates = self.tmdb.discover(self.cfg.genres, self.cfg.min_rating)
            radarr_ids = self.radarr.get_library_tmdb_ids()
        except (TMDBError, RadarrError, JellyfinError) as exc:
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
        if self.missing_secrets:
            return
        now = datetime.now(timezone.utc)
        genres = self.cfg.surprise_genres if self.cfg.surprise_genres is not None else self.cfg.genres
        try:
            self._resync_watched_cache_if_stale(now)
            candidates = self.tmdb.discover(genres, self.cfg.min_rating)
            radarr_ids = self.radarr.get_library_tmdb_ids()
        except (TMDBError, RadarrError, JellyfinError) as exc:
            self.error(f"surprise pick failed: {exc}")
            return

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
        imdb_id = pick.imdb_id
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
            try:
                # A surprise film's imdb_id is worth the extra call (unlike
                # regular suggestions, which never get deleted) — it's the
                # fallback match key if a Jellyfin webhook payload ever
                # omits Provider_tmdb.
                imdb_id = self.tmdb.get_imdb_id(pick.tmdb_id)
            except TMDBError:
                pass

        self.log(f"yArr surprise: {pick.title!r} ({pick.year})")
        self.state_data = core_state.record_surprise_added(
            self.state_data, tmdb_id=pick.tmdb_id, imdb_id=imdb_id,
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
        attrs = {
            "suggested_count": len(self.state_data.suggested),
            "surprise_count": len(self.state_data.surprises),
            "next_surprise_at": self.state_data.next_surprise_at,
            "missing_secrets": self.missing_secrets,
        }
        self.set_state("sensor.yarr_status",
                        state="Not Configured" if self.missing_secrets else "OK",
                        attributes=attrs)
        self.set_state("sensor.yarr_heartbeat", state=datetime.now(timezone.utc).isoformat())
