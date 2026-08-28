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
from core import taste as core_taste

from clients.tmdb import TMDBClient, TMDBError
from clients.radarr import RadarrClient, RadarrError
from clients.sonarr import SonarrClient, SonarrError
from clients.jellyfin import JellyfinClient, JellyfinError
from clients.sabnzbd import SABnzbdClient, SABnzbdError

CONFIG_DIR = "/config/apps/yarr"
STATE_PATH = os.path.join(CONFIG_DIR, "yarr_state.json")
SECRETS_PATH = os.path.join(CONFIG_DIR, "addon_secrets.json")


class Yarr(hass.Hass):

    # ------------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------------

    def initialize(self):
        self.state_data = core_state.load(STATE_PATH)

        try:
            secrets = self._load_json(SECRETS_PATH) or {}
            self.cfg = build_config(self.args, secrets)
        except ConfigError as exc:
            self._log_event(f"apps.yaml is invalid: {exc}", level="error")
            self.cfg = build_config({}, {})

        self.missing_secrets = required_secrets_ok(self.cfg)
        if self.missing_secrets:
            self._log_event(f"Not fully configured — missing: {', '.join(self.missing_secrets)}. "
                             "Set these in the add-on's Configuration tab.", level="warn")

        self.tmdb = TMDBClient(self.cfg.tmdb_api_key)
        self.radarr = RadarrClient(self.cfg.radarr_url, self.cfg.radarr_api_key)
        self.jellyfin = JellyfinClient(self.cfg.jellyfin_url, self.cfg.jellyfin_api_key)
        self.sonarr = SonarrClient(self.cfg.sonarr_url, self.cfg.sonarr_api_key) if self.cfg.tv_enabled else None
        self.sabnzbd = (SABnzbdClient(self.cfg.sabnzbd_url, self.cfg.sabnzbd_api_key)
                         if self.cfg.sabnzbd_enabled else None)
        self._jellyfin_user_id = None

        self.listen_state(self.on_surprise_now_pressed, "input_button.yarr_surprise_me_now")
        if self.cfg.tv_enabled:
            self.listen_state(self.on_surprise_tv_now_pressed, "input_button.yarr_surprise_tv_now")
        self.listen_event(self.on_jellyfin_webhook, "yarr_jellyfin_webhook")

        self.run_every(self.tick_discovery, "now", self.cfg.discovery_interval_hours * 3600)
        self.run_every(self.tick_surprise_check, "now", 3600)
        if self.cfg.tv_enabled:
            self.run_every(self.tick_tv_discovery, "now", self.cfg.tv_discovery_interval_hours * 3600)
            self.run_every(self.tick_tv_surprise_check, "now", 3600)
        self.run_every(self.tick_delete_guard, "now", 900)
        if self.cfg.sabnzbd_enabled:
            self.run_every(self.tick_sabnzbd_status, "now", 60)
        self.run_every(self.publish_status, "now", 60)

        self._log_event(f"yArr v{VERSION} started"
                         f"{' (TV enabled)' if self.cfg.tv_enabled else ''}"
                         f"{' (SABnzbd monitoring enabled)' if self.cfg.sabnzbd_enabled else ''}.")

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

    def _log_event(self, message, level="info"):
        """Appends to the persisted rolling event log (surfaced in the
        web UI's Log section) in addition to AppDaemon's own log —
        persisted so a restart doesn't wipe today's activity, and
        capped by core_state.add_log_event() so the state file can't
        grow unbounded."""
        self.state_data = core_state.add_log_event(
            self.state_data, message, datetime.now(timezone.utc), level=level)
        self._save_state()
        if level == "error":
            self.error(message)
        else:
            self.log(message)

    def _jellyfin_user(self):
        if self._jellyfin_user_id is None:
            self._jellyfin_user_id = self.jellyfin.resolve_user_id(self.cfg.jellyfin_username)
        return self._jellyfin_user_id

    def _effective_genres(self):
        if self.cfg.learn_genres_from_library and self.state_data.learned_genres:
            return self.state_data.learned_genres
        return self.cfg.genres

    def _effective_tv_genres(self):
        if self.cfg.learn_genres_from_library and self.state_data.learned_tv_genres:
            return self.state_data.learned_tv_genres
        return self.cfg.tv_genres

    # ------------------------------------------------------------------
    # WATCHED-CACHE / TASTE RESYNC — shared cadence for movies + TV
    # ------------------------------------------------------------------

    def _resync_watched_and_taste_if_stale(self, now):
        synced_at = self.state_data.watched_cache_synced_at
        stale = (synced_at is None or
                 now >= datetime.fromisoformat(synced_at) +
                 timedelta(hours=self.cfg.watched_resync_hours))
        if not stale:
            return
        user_id = self._jellyfin_user()
        self.state_data.watched_tmdb_cache = list(self.jellyfin.get_watched_tmdb_ids(user_id))
        if self.cfg.tv_enabled:
            self.state_data.watched_tvdb_cache = list(self.jellyfin.get_watched_tvdb_ids(user_id))
        self.state_data.watched_cache_synced_at = now.isoformat()

        if self.cfg.learn_genres_from_library:
            movie_items = self.jellyfin.get_watched_items_for_taste(user_id, "Movie")
            self.state_data.learned_genres = core_taste.top_genres(
                movie_items, top_n=self.cfg.taste_top_n_genres, exclude=self.cfg.excluded_genres)
            if self.cfg.tv_enabled:
                show_items = self.jellyfin.get_watched_items_for_taste(user_id, "Series")
                self.state_data.learned_tv_genres = core_taste.top_genres(
                    show_items, top_n=self.cfg.taste_top_n_genres, exclude=self.cfg.excluded_genres)

        self._save_state()

    # ------------------------------------------------------------------
    # MOVIE DISCOVERY / SURPRISE
    # ------------------------------------------------------------------

    def tick_discovery(self, kwargs):
        if not self._enabled() or self.missing_secrets:
            return
        now = datetime.now(timezone.utc)
        try:
            self._resync_watched_and_taste_if_stale(now)
            candidates = self.tmdb.discover(self._effective_genres(), self.cfg.min_rating)
            radarr_ids = self.radarr.get_library_tmdb_ids()
        except (TMDBError, RadarrError, JellyfinError) as exc:
            self._log_event(f"tick_discovery failed: {exc}", level="error")
            return

        picks = core_discovery.filter_candidates(
            candidates,
            allowed_genres=self._effective_genres(),
            min_rating=self.cfg.min_rating,
            watched_tmdb_ids=set(self.state_data.watched_tmdb_cache),
            radarr_tmdb_ids=radarr_ids,
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested},
            excluded_genres=self.cfg.excluded_genres)
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
                    self._log_event(f"Could not add {c.title!r} to Radarr: {exc}", level="error")
                    continue
            self._log_event(f"Added {c.title!r} ({c.year}) — rating {c.rating}")
            self.state_data = core_state.record_suggestion(self.state_data, core_state.SuggestedFilm(
                tmdb_id=c.tmdb_id, imdb_id=c.imdb_id, title=c.title, year=c.year, source="genre",
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
        genres = self.cfg.surprise_genres if self.cfg.surprise_genres is not None else self._effective_genres()
        try:
            self._resync_watched_and_taste_if_stale(now)
            candidates = self.tmdb.discover(genres, self.cfg.min_rating)
            radarr_ids = self.radarr.get_library_tmdb_ids()
        except (TMDBError, RadarrError, JellyfinError) as exc:
            self._log_event(f"surprise pick failed: {exc}", level="error")
            return

        pool = core_discovery.filter_candidates(
            candidates, allowed_genres=genres, min_rating=self.cfg.min_rating,
            watched_tmdb_ids=set(self.state_data.watched_tmdb_cache),
            radarr_tmdb_ids=radarr_ids,
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested} |
                                        {int(k) for k in self.state_data.surprises},
            excluded_genres=self.cfg.excluded_genres)
        pick = core_discovery.pick_surprise(pool, exclude_tmdb_ids=set())

        window = core_surprise.SurpriseWindow(self.cfg.surprise_min_days, self.cfg.surprise_max_days)
        self.state_data.next_surprise_at = core_surprise.next_surprise_time(now, window).isoformat()

        if pick is None:
            self._log_event("No surprise candidate matched your filters this time.")
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
                self._log_event(f"Could not add surprise {pick.title!r} to Radarr: {exc}", level="error")
                return
            try:
                # A surprise film's imdb_id is worth the extra call (unlike
                # regular suggestions, which never get deleted) — it's the
                # fallback match key if a Jellyfin webhook payload ever
                # omits Provider_tmdb.
                imdb_id = self.tmdb.get_imdb_id(pick.tmdb_id)
            except TMDBError:
                pass

        self._log_event(f"Surprise: {pick.title!r} ({pick.year})")
        self.state_data = core_state.record_surprise_added(
            self.state_data, tmdb_id=pick.tmdb_id, imdb_id=imdb_id, year=pick.year,
            title=pick.title, radarr_movie_id=radarr_movie_id, now=now)
        self._save_state()
        self.call_service("persistent_notification/create", title="yArr surprise",
                           message=f"Tonight's surprise: {pick.title} ({pick.year})")

    # ------------------------------------------------------------------
    # TV DISCOVERY / SURPRISE (opt-in — only wired up when cfg.tv_enabled)
    # ------------------------------------------------------------------

    def tick_tv_discovery(self, kwargs):
        if not self._enabled() or self.missing_secrets:
            return
        now = datetime.now(timezone.utc)
        try:
            self._resync_watched_and_taste_if_stale(now)
            candidates = self.tmdb.discover_tv(self._effective_tv_genres(), self.cfg.tv_min_rating)
            sonarr_ids = self.sonarr.get_library_tvdb_ids()
        except (TMDBError, SonarrError, JellyfinError) as exc:
            self._log_event(f"tick_tv_discovery failed: {exc}", level="error")
            return

        picks = core_discovery.filter_candidates(
            candidates,
            allowed_genres=self._effective_tv_genres(),
            min_rating=self.cfg.tv_min_rating,
            watched_tmdb_ids=set(self.state_data.watched_tvdb_cache),
            radarr_tmdb_ids=sonarr_ids,
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested_shows},
            key="tvdb_id", excluded_genres=self.cfg.excluded_genres)
        picks = picks[: self.cfg.tv_max_suggestions_per_run]

        for c in picks:
            sonarr_series_id = None
            if not self.cfg.dry_run:
                try:
                    qp_id = self.sonarr.resolve_quality_profile_id(self.cfg.sonarr_quality_profile_name)
                    sonarr_series_id = self.sonarr.add_series(
                        c, root_folder=self.cfg.sonarr_root_folder,
                        quality_profile_id=qp_id,
                        language_profile_id=self.cfg.sonarr_language_profile_id)
                except SonarrError as exc:
                    self._log_event(f"Could not add {c.title!r} to Sonarr: {exc}", level="error")
                    continue
            self._log_event(f"Added show {c.title!r} ({c.year}) — rating {c.rating}")
            self.state_data = core_state.record_suggestion_show(
                self.state_data, core_state.SuggestedShow(
                    tvdb_id=c.tvdb_id, tmdb_id=c.tmdb_id, imdb_id=c.imdb_id, title=c.title,
                    year=c.year, source="genre", decision="added", suggested_at=now.isoformat(),
                    sonarr_series_id=sonarr_series_id))
        if picks:
            self._save_state()

    def on_surprise_tv_now_pressed(self, entity, attribute, old, new, kwargs):
        self._run_tv_surprise_pick()

    def tick_tv_surprise_check(self, kwargs):
        if not self._enabled() or not self.cfg.tv_surprise_enabled:
            return
        now = datetime.now(timezone.utc)
        if not core_surprise.is_surprise_due(now, self.state_data.next_tv_surprise_at):
            return
        self._run_tv_surprise_pick()

    def _run_tv_surprise_pick(self):
        if self.missing_secrets or not self.cfg.tv_enabled:
            return
        now = datetime.now(timezone.utc)
        genres = (self.cfg.tv_surprise_genres if self.cfg.tv_surprise_genres is not None
                  else self._effective_tv_genres())
        try:
            self._resync_watched_and_taste_if_stale(now)
            candidates = self.tmdb.discover_tv(genres, self.cfg.tv_min_rating)
            sonarr_ids = self.sonarr.get_library_tvdb_ids()
        except (TMDBError, SonarrError, JellyfinError) as exc:
            self._log_event(f"TV surprise pick failed: {exc}", level="error")
            return

        pool = core_discovery.filter_candidates(
            candidates, allowed_genres=genres, min_rating=self.cfg.tv_min_rating,
            watched_tmdb_ids=set(self.state_data.watched_tvdb_cache),
            radarr_tmdb_ids=sonarr_ids,
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested_shows} |
                                        {int(k) for k in self.state_data.surprises_shows},
            key="tvdb_id", excluded_genres=self.cfg.excluded_genres)
        pick = core_discovery.pick_surprise(pool, exclude_tmdb_ids=set(), key="tvdb_id")

        window = core_surprise.SurpriseWindow(self.cfg.tv_surprise_min_days, self.cfg.tv_surprise_max_days)
        self.state_data.next_tv_surprise_at = core_surprise.next_surprise_time(now, window).isoformat()

        if pick is None:
            self._log_event("No TV surprise candidate matched your filters this time.")
            return

        sonarr_series_id = None
        if not self.cfg.dry_run:
            try:
                qp_id = self.sonarr.resolve_quality_profile_id(self.cfg.sonarr_quality_profile_name)
                tag_id = self.sonarr.ensure_tag(self.cfg.tv_surprise_tag)
                sonarr_series_id = self.sonarr.add_series(
                    pick, root_folder=self.cfg.sonarr_root_folder,
                    quality_profile_id=qp_id, tag_ids=[tag_id],
                    language_profile_id=self.cfg.sonarr_language_profile_id)
            except SonarrError as exc:
                self._log_event(f"Could not add surprise show {pick.title!r} to Sonarr: {exc}", level="error")
                return

        self._log_event(f"TV surprise: {pick.title!r} ({pick.year})")
        self.state_data = core_state.record_surprise_show_added(
            self.state_data, tvdb_id=pick.tvdb_id, tmdb_id=pick.tmdb_id, imdb_id=pick.imdb_id,
            title=pick.title, year=pick.year, sonarr_series_id=sonarr_series_id, now=now)
        self._save_state()
        self.call_service("persistent_notification/create", title="yArr TV surprise",
                           message=f"Tonight's surprise show: {pick.title} ({pick.year})")

    # ------------------------------------------------------------------
    # JELLYFIN WEBHOOK (movie PlaybackStop + episode PlaybackStop) / DELETE GUARD
    # ------------------------------------------------------------------

    def on_jellyfin_webhook(self, event_name, data, kwargs):
        payload = (data or {}).get("payload")

        movie_event = core_webhook.parse_jellyfin_payload(payload)
        if movie_event is not None:
            self._handle_movie_watched(movie_event)
            return

        episode_event = core_webhook.parse_jellyfin_episode_payload(payload)
        if episode_event is not None:
            self._handle_episode_watched(episode_event)

    def _handle_movie_watched(self, event):
        film = core_webhook.matches_surprise(event, self.state_data.surprises)
        if film is None:
            return
        if event.percentage < self.cfg.completion_threshold_pct:
            return

        now = datetime.now(timezone.utc)
        self.state_data = core_state.mark_watched(self.state_data, film.tmdb_id, now)
        self.state_data = core_state.schedule_deletion(
            self.state_data, film.tmdb_id, now, self.cfg.delete_grace_period_hours)
        self.set_state("input_boolean.yarr_keep_surprise", state="off")
        self._log_event(f"Watched {film.title!r} — deleting in "
                         f"{self.cfg.delete_grace_period_hours:g}h unless kept.")
        self.call_service(
            "persistent_notification/create", title="yArr: surprise film watched",
            message=(f"{film.title} will be deleted in {self.cfg.delete_grace_period_hours:g}h. "
                     "Flip 'yArr: Keep the pending surprise film' on to keep it instead."))

    def _handle_episode_watched(self, event):
        if not self.cfg.tv_enabled:
            return
        if event.percentage < self.cfg.completion_threshold_pct:
            return
        tvdb_id = self.jellyfin.get_series_tvdb_id(event.series_item_id)
        show = core_webhook.matches_surprise_show(tvdb_id, self.state_data.surprises_shows)
        if show is None:
            return
        # Only the LAST episode finishing the whole series counts as
        # "watched" for deletion purposes — a mid-series episode
        # crossing the completion threshold shouldn't trigger it.
        try:
            fully_watched = self.jellyfin.is_series_fully_watched(
                self._jellyfin_user(), event.series_item_id)
        except JellyfinError as exc:
            self._log_event(f"Could not confirm series watched status for {show.title!r}: {exc}",
                             level="error")
            return
        if not fully_watched:
            return

        now = datetime.now(timezone.utc)
        self.state_data = core_state.mark_show_watched(self.state_data, show.tvdb_id, now)
        self.state_data = core_state.schedule_show_deletion(
            self.state_data, show.tvdb_id, now, self.cfg.delete_grace_period_hours)
        self.set_state("input_boolean.yarr_keep_surprise_tv", state="off")
        self._log_event(f"Finished {show.title!r} — deleting in "
                         f"{self.cfg.delete_grace_period_hours:g}h unless kept.")
        self.call_service(
            "persistent_notification/create", title="yArr: surprise show finished",
            message=(f"{show.title} will be deleted in {self.cfg.delete_grace_period_hours:g}h. "
                     "Flip 'yArr: Keep the pending surprise show' on to keep it instead."))

    def tick_delete_guard(self, kwargs):
        now = datetime.now(timezone.utc)

        due = core_state.due_deletions(self.state_data, now)
        if due:
            keep = self.get_state("input_boolean.yarr_keep_surprise") == "on"
            for film in due:
                if keep:
                    self.state_data = core_state.cancel_deletion(self.state_data, film.tmdb_id)
                    self._log_event(f"Kept {film.title!r} — deletion cancelled.")
                    continue
                if not self.cfg.dry_run and film.radarr_movie_id is not None:
                    try:
                        self.radarr.delete_movie(film.radarr_movie_id)
                    except RadarrError as exc:
                        self._log_event(f"Could not delete {film.title!r} from Radarr: {exc}", level="error")
                        continue
                self._log_event(f"Deleted {film.title!r} after the grace period.")
                self.state_data = core_state.confirm_deleted(self.state_data, film.tmdb_id)
            self.set_state("input_boolean.yarr_keep_surprise", state="off")

        if self.cfg.tv_enabled:
            due_shows = core_state.due_show_deletions(self.state_data, now)
            if due_shows:
                keep_tv = self.get_state("input_boolean.yarr_keep_surprise_tv") == "on"
                for show in due_shows:
                    if keep_tv:
                        self.state_data = core_state.cancel_show_deletion(self.state_data, show.tvdb_id)
                        self._log_event(f"Kept {show.title!r} — deletion cancelled.")
                        continue
                    if not self.cfg.dry_run and show.sonarr_series_id is not None:
                        try:
                            self.sonarr.delete_series(show.sonarr_series_id)
                        except SonarrError as exc:
                            self._log_event(f"Could not delete {show.title!r} from Sonarr: {exc}", level="error")
                            continue
                    self._log_event(f"Deleted {show.title!r} after the grace period.")
                    self.state_data = core_state.confirm_show_deleted(self.state_data, show.tvdb_id)
                self.set_state("input_boolean.yarr_keep_surprise_tv", state="off")

        self._save_state()

    # ------------------------------------------------------------------
    # SABNZBD MONITORING (read-only)
    # ------------------------------------------------------------------

    def tick_sabnzbd_status(self, kwargs):
        try:
            queue = self.sabnzbd.get_queue()
        except SABnzbdError as exc:
            self.error(f"SABnzbd queue fetch failed: {exc}")
            return
        self.set_state("sensor.yarr_sabnzbd_status", state=queue["status"], attributes={
            "speed_kbps": queue["speed_kbps"],
            "size_left": queue["size_left"],
            "eta": queue["eta"],
            "paused": queue["paused"],
            "queue_count": len(queue["items"]),
            "items": queue["items"][:10],
        })

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    @staticmethod
    def _film_status(film):
        if film.pending_deletion and not film.pending_deletion.keep_requested:
            return "deleting_soon"
        if film.watched:
            return "watched"
        return "pending_watch"

    def _recent_suggested(self, suggested_dict, limit=8):
        rows = sorted(suggested_dict.values(), key=lambda f: f.suggested_at, reverse=True)
        return [{"title": f.title, "year": f.year, "decision": f.decision} for f in rows[:limit]]

    def _surprise_rows(self, surprises_dict):
        rows = sorted(surprises_dict.values(), key=lambda f: f.added_at, reverse=True)
        out = []
        for f in rows:
            row = {"title": f.title, "year": f.year, "status": self._film_status(f)}
            if f.pending_deletion:
                row["delete_at"] = f.pending_deletion.delete_at
            out.append(row)
        return out

    def publish_status(self, kwargs):
        attrs = {
            "suggested_count": len(self.state_data.suggested),
            "surprise_count": len(self.state_data.surprises),
            "next_surprise_at": self.state_data.next_surprise_at,
            "missing_secrets": self.missing_secrets,
            "tv_enabled": self.cfg.tv_enabled,
            "sabnzbd_enabled": self.cfg.sabnzbd_enabled,
            "learn_genres_from_library": self.cfg.learn_genres_from_library,
            "excluded_genres": self.cfg.excluded_genres,
            "effective_genres": self._effective_genres(),
            "learned_genres": self.state_data.learned_genres,
            "recent_suggested": self._recent_suggested(self.state_data.suggested),
            "surprises": self._surprise_rows(self.state_data.surprises),
            "log": list(reversed(self.state_data.event_log[-30:])),
        }
        if self.cfg.tv_enabled:
            attrs.update({
                "suggested_shows_count": len(self.state_data.suggested_shows),
                "surprise_shows_count": len(self.state_data.surprises_shows),
                "next_tv_surprise_at": self.state_data.next_tv_surprise_at,
                "effective_tv_genres": self._effective_tv_genres(),
                "learned_tv_genres": self.state_data.learned_tv_genres,
                "recent_suggested_shows": self._recent_suggested(self.state_data.suggested_shows),
                "surprise_shows": self._surprise_rows(self.state_data.surprises_shows),
            })
        self.set_state("sensor.yarr_status",
                        state="Not Configured" if self.missing_secrets else "OK",
                        attributes=attrs)
        self.set_state("sensor.yarr_heartbeat", state=datetime.now(timezone.utc).isoformat())
