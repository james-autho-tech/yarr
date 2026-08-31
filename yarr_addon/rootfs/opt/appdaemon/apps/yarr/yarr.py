import os
import shutil
import time
from datetime import datetime, timedelta, timezone

import appdaemon.plugins.hass.hassapi as hass

from core.config import build_config, required_secrets_ok, ConfigError
from core import state as core_state
from core import discovery as core_discovery
from core import surprise as core_surprise
from core import webhook as core_webhook
from core import taste as core_taste
from core import dupes as core_dupes
from core import junk as core_junk
from core import library as core_library

from clients.tmdb import TMDBClient, TMDBError
from clients.radarr import RadarrClient, RadarrError
from clients.sonarr import SonarrClient, SonarrError
from clients.jellyfin import JellyfinClient, JellyfinError
from clients.sabnzbd import SABnzbdClient, SABnzbdError

# config.yaml's version is the single source of truth (set by `run`
# via YARR_VERSION) instead of a separate hardcoded constant.
VERSION = os.environ.get("YARR_VERSION") or "dev"

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
        self._ensure_boolean_states()

        # Plain custom HA events, not input_button entities — a real
        # install showed HA's Config REST API 404s on input_boolean/
        # input_button (modern HA moved simple helpers to a config-entry
        # flow that endpoint doesn't serve; only automation/scene/script
        # still support it), so the web UI drives all of this by firing
        # bare events via POST /api/events/<type> instead, which needs
        # no entity to exist at all.
        self.listen_event(self.on_surprise_now_pressed, "yarr_surprise_me_now")
        self.listen_event(self.on_accept_surprise, "yarr_accept_surprise")
        self.listen_event(self.on_deny_surprise, "yarr_deny_surprise")
        self.listen_event(self.on_delete_surprise_now, "yarr_delete_surprise_now")
        self.listen_event(self.on_unblock_movie, "yarr_unblock_movie")
        if self.cfg.tv_enabled:
            self.listen_event(self.on_surprise_tv_now_pressed, "yarr_surprise_tv_now")
            self.listen_event(self.on_accept_tv_surprise, "yarr_accept_tv_surprise")
            self.listen_event(self.on_deny_tv_surprise, "yarr_deny_tv_surprise")
            self.listen_event(self.on_delete_tv_surprise_now, "yarr_delete_tv_surprise_now")
            self.listen_event(self.on_unblock_show, "yarr_unblock_show")
        if self.cfg.media_scan_enabled:
            self.listen_event(self.on_scan_duplicates_now_pressed, "yarr_scan_duplicates_now")
            self.listen_event(self.on_delete_duplicate_file, "yarr_delete_duplicate_file")
            self.listen_event(self.on_bulk_delete_duplicates_pressed, "yarr_bulk_delete_duplicates")
            self.listen_event(self.on_delete_junk_entry, "yarr_delete_junk_entry")
            self.listen_event(self.on_bulk_delete_junk_pressed, "yarr_bulk_delete_junk")
        self.listen_event(self.on_jellyfin_webhook, "yarr_jellyfin_webhook")

        # Library tab: full-library browse/manage + request hub —
        # always registered (not gated on an opt-in feature toggle like
        # media_scan_enabled/sabnzbd_enabled above), since browsing and
        # searching are core functionality once shipped. Only
        # library-delete itself is gated (on cfg.allow_library_delete,
        # checked inside the handler, not here — see its docstring).
        self.listen_event(self.on_search_media, "yarr_search_media")
        self.listen_event(self.on_request_add_movie, "yarr_request_add_movie")
        self.listen_event(self.on_refresh_library_pressed, "yarr_refresh_library")
        self.listen_event(self.on_library_delete_movie, "yarr_library_delete_movie")
        if self.cfg.tv_enabled:
            self.listen_event(self.on_request_add_show, "yarr_request_add_show")
            self.listen_event(self.on_library_delete_show, "yarr_library_delete_show")

        self.run_every(self.tick_discovery, "now", self.cfg.discovery_interval_hours * 3600)
        self.run_every(self.tick_surprise_check, "now", 3600)
        if self.cfg.tv_enabled:
            self.run_every(self.tick_tv_discovery, "now", self.cfg.tv_discovery_interval_hours * 3600)
            self.run_every(self.tick_tv_surprise_check, "now", 3600)
        self.run_every(self.tick_delete_guard, "now", 900)
        self.run_every(self.tick_reconcile_surprises, "now", 1800)
        if self.cfg.sabnzbd_enabled:
            self.run_every(self.tick_sabnzbd_status, "now", 60)
        if self.cfg.media_scan_enabled:
            self.run_every(self.tick_scan_duplicates, "now", self.cfg.media_scan_interval_hours * 3600)
        self.run_every(self.tick_refresh_library, "now", self.cfg.library_refresh_interval_hours * 3600)
        self.run_every(self.publish_status, "now", 60)

        self._log_event(f"yArr v{VERSION} started"
                         f"{' (TV enabled)' if self.cfg.tv_enabled else ''}"
                         f"{' (SABnzbd monitoring enabled)' if self.cfg.sabnzbd_enabled else ''}"
                         f"{' (media duplicate scan enabled)' if self.cfg.media_scan_enabled else ''}.")

    # ------------------------------------------------------------------
    # ENABLE GATE
    # ------------------------------------------------------------------

    def _enabled(self) -> bool:
        return self.get_state("input_boolean.yarr_enable") != "off"

    def _dry_run(self) -> bool:
        return self.get_state("input_boolean.yarr_dry_run") == "on"

    def _surprise_enabled(self) -> bool:
        return self.get_state("input_boolean.yarr_surprise_enabled") == "on"

    def _tv_surprise_enabled(self) -> bool:
        return self.get_state("input_boolean.yarr_tv_surprise_enabled") == "on"

    def _surprise_requires_approval(self) -> bool:
        return self.get_state("input_boolean.yarr_surprise_requires_approval") == "on"

    def _learn_genres_from_library(self) -> bool:
        return self.get_state("input_boolean.yarr_learn_genres_from_library") == "on"

    def _ensure_boolean_states(self):
        """Creates the toggle states yArr uses if they don't already
        exist, so they survive an AppDaemon restart without being
        reset — these are AppDaemon-owned virtual states, not real
        input_boolean helpers (see the run script's comment on why),
        so the web UI sets them via HA's raw /api/states/<id> endpoint
        rather than an input_boolean service call.

        dry_run/surprise_enabled/tv_surprise_enabled/
        surprise_requires_approval/learn_genres_from_library used to be
        apps.yaml-only settings requiring a file edit + restart to
        change — now live toggles in the web UI's Settings tab instead,
        seeded from whatever apps.yaml currently says the FIRST time
        each is created, so upgrading doesn't silently change anyone's
        existing behaviour. After that first creation, apps.yaml's
        value for these five is never consulted again — the toggle is
        the sole source of truth, exactly like yarr_enable already is."""
        defaults = {
            "input_boolean.yarr_enable": ("on", "yArr Engine Master Switch", "mdi:movie-open-play"),
            "input_boolean.yarr_keep_surprise": (
                "off", "yArr: Keep the pending surprise film", "mdi:heart"),
            "input_boolean.yarr_keep_surprise_tv": (
                "off", "yArr: Keep the pending surprise show", "mdi:heart"),
            "input_boolean.yarr_dry_run": (
                "on" if self.cfg.dry_run else "off",
                "yArr: Dry run (log only, no real adds/deletes)", "mdi:test-tube"),
            "input_boolean.yarr_surprise_enabled": (
                "on" if self.cfg.surprise_enabled else "off",
                "yArr: Surprise me (movies)", "mdi:dice-5-outline"),
            "input_boolean.yarr_tv_surprise_enabled": (
                "on" if self.cfg.tv_surprise_enabled else "off",
                "yArr: Surprise me (TV)", "mdi:dice-5-outline"),
            "input_boolean.yarr_surprise_requires_approval": (
                "on" if self.cfg.surprise_requires_approval else "off",
                "yArr: Surprises need Accept/Deny", "mdi:check-decagram-outline"),
            "input_boolean.yarr_learn_genres_from_library": (
                "on" if self.cfg.learn_genres_from_library else "off",
                "yArr: Learn genres from library", "mdi:brain"),
        }
        for entity_id, (default_state, name, icon) in defaults.items():
            if not self.entity_exists(entity_id):
                self.set_state(entity_id, state=default_state,
                                attributes={"friendly_name": name, "icon": icon})

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
        if self._learn_genres_from_library() and self.state_data.learned_genres:
            return self.state_data.learned_genres
        return self.cfg.genres

    def _effective_tv_genres(self):
        if self._learn_genres_from_library() and self.state_data.learned_tv_genres:
            return self.state_data.learned_tv_genres
        return self.cfg.tv_genres

    def _denied_genres(self):
        """Genres denied at least surprise_feedback_deny_threshold times
        via the web UI's Deny button — actively excluded from future
        surprise picks on top of the configured excluded_genres, not
        just logged. Only ever affects surprises, never the regular
        genre auto-add (which the user never explicitly rejected)."""
        return core_state.denied_genres_over_threshold(
            self.state_data, self.cfg.surprise_feedback_deny_threshold)

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

        if self._learn_genres_from_library():
            # Blends two signals: what Jellyfin says you've actually
            # watched (real play_count/favourite weighting) and what's
            # sitting in your full Radarr/Sonarr library at all (the
            # Library tab's data — a weaker signal on its own, since
            # owning something isn't the same as liking it, but still
            # worth counting). A title that's both owned and watched
            # naturally ends up weighted higher than one merely owned,
            # since it contributes to both lists — no special-cased
            # blending math needed, see core_taste.library_items_as_watched.
            movie_items = (self.jellyfin.get_watched_items_for_taste(user_id, "Movie")
                           + core_taste.library_items_as_watched(self.state_data.library_movies))
            self.state_data.learned_genres = core_taste.top_genres(
                movie_items, top_n=self.cfg.taste_top_n_genres, exclude=self.cfg.excluded_genres)
            if self.cfg.tv_enabled:
                show_items = (self.jellyfin.get_watched_items_for_taste(user_id, "Series")
                              + core_taste.library_items_as_watched(self.state_data.library_shows))
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
            candidates = self.tmdb.discover(self._effective_genres(), self.cfg.min_rating,
                                             pages=self.cfg.tmdb_pages)
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
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested} |
                                        {int(k) for k in self.state_data.blocked_movies},
            excluded_genres=self.cfg.excluded_genres)
        picks = picks[: self.cfg.max_suggestions_per_run]

        for c in picks:
            radarr_movie_id = None
            if not self._dry_run():
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

    def on_surprise_now_pressed(self, event_name, data, kwargs):
        # publish_status normally only runs on its own 60s tick — a
        # button press republishes immediately afterward so the web UI
        # (polling every 5s) doesn't look like it did nothing for up to
        # a minute.
        self._run_surprise_pick()
        self.publish_status({})

    def tick_surprise_check(self, kwargs):
        if not self._enabled() or not self._surprise_enabled():
            return
        now = datetime.now(timezone.utc)
        if not core_surprise.is_surprise_due(now, self.state_data.next_surprise_at):
            return
        self._run_surprise_pick()

    def _run_surprise_pick(self):
        if self.missing_secrets:
            return
        if self._surprise_requires_approval() and self.state_data.pending_surprise is not None:
            self._log_event("A surprise proposal is already awaiting accept/deny — skipping.")
            return
        now = datetime.now(timezone.utc)
        genres = self.cfg.surprise_genres if self.cfg.surprise_genres is not None else self._effective_genres()
        excluded = list(self.cfg.excluded_genres) + self._denied_genres()
        try:
            self._resync_watched_and_taste_if_stale(now)
            candidates = self.tmdb.discover(genres, self.cfg.min_rating, pages=self.cfg.tmdb_pages)
            radarr_ids = self.radarr.get_library_tmdb_ids()
        except (TMDBError, RadarrError, JellyfinError) as exc:
            self._log_event(f"surprise pick failed: {exc}", level="error")
            return

        pool = core_discovery.filter_candidates(
            candidates, allowed_genres=genres, min_rating=self.cfg.min_rating,
            watched_tmdb_ids=set(self.state_data.watched_tmdb_cache),
            radarr_tmdb_ids=radarr_ids,
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested} |
                                        {int(k) for k in self.state_data.surprises} |
                                        {int(k) for k in self.state_data.blocked_movies},
            excluded_genres=excluded)
        pick = core_discovery.pick_surprise(pool, exclude_tmdb_ids=set())

        window = core_surprise.SurpriseWindow(self.cfg.surprise_min_days, self.cfg.surprise_max_days)
        self.state_data.next_surprise_at = core_surprise.next_surprise_time(now, window).isoformat()

        if pick is None:
            self._log_event("No surprise candidate matched your filters this time.")
            return

        if self._surprise_requires_approval():
            proposal = core_state.PendingSurprise(
                tmdb_id=pick.tmdb_id, imdb_id=pick.imdb_id, title=pick.title, year=pick.year,
                genres=list(pick.genres), rating=pick.rating, proposed_at=now.isoformat())
            self.state_data = core_state.set_pending_surprise(self.state_data, proposal)
            self._log_event(f"Proposed surprise: {pick.title!r} ({pick.year}) — "
                             "accept or deny in the web UI.")
            self.call_service(
                "persistent_notification/create", title="yArr surprise proposed",
                message=f"{pick.title} ({pick.year}) — check yArr's web UI to accept or deny.")
            return

        self._add_surprise_movie(pick, now)

    def _add_surprise_movie(self, pick, now):
        """pick may be a core_discovery.Candidate (approval disabled)
        or a core_state.PendingSurprise (approval accepted) — both
        carry the tmdb_id/title/year/imdb_id fields add_movie() and
        record_surprise_added() need."""
        radarr_movie_id = None
        imdb_id = pick.imdb_id
        if not self._dry_run():
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
            if not imdb_id:
                try:
                    # Worth the extra call now (unlike regular
                    # suggestions, which never get deleted) — it's the
                    # fallback match key if a Jellyfin webhook payload
                    # ever omits Provider_tmdb.
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

    def on_accept_surprise(self, event_name, data, kwargs):
        pending = self.state_data.pending_surprise
        if pending is None:
            return
        now = datetime.now(timezone.utc)
        self.state_data = core_state.record_genre_feedback(self.state_data, pending.genres, accepted=True)
        self.state_data = core_state.clear_pending_surprise(self.state_data)
        self._add_surprise_movie(pending, now)
        self.publish_status({})

    def on_deny_surprise(self, event_name, data, kwargs):
        pending = self.state_data.pending_surprise
        if pending is None:
            return
        now = datetime.now(timezone.utc)
        self.state_data = core_state.record_genre_feedback(self.state_data, pending.genres, accepted=False)
        # Denying blocks the exact title outright, not just its genres
        # — a genre only gets suppressed after surprise_feedback_deny_threshold
        # denials (see _denied_genres()), but a title you've explicitly
        # said no to should never come back via genre auto-add or a
        # future surprise pick, on the first denial.
        self.state_data = core_state.block_movie(
            self.state_data, pending.tmdb_id, pending.title, pending.year, now)
        self.state_data = core_state.clear_pending_surprise(self.state_data)
        self._log_event(f"Denied and blocked surprise: {pending.title!r} "
                         f"(genres: {', '.join(pending.genres) or 'none'}).")
        self.publish_status({})

    def on_delete_surprise_now(self, event_name, data, kwargs):
        """Immediate manual delete of an already-added surprise —
        independent of the watched/grace-period flow, for "this was
        rubbish, get rid of it now" regardless of watch status."""
        tmdb_id = (data or {}).get("tmdb_id")
        if tmdb_id is None:
            return
        film = self.state_data.surprises.get(str(tmdb_id))
        if film is None:
            return
        if not self._dry_run() and film.radarr_movie_id is not None:
            try:
                self.radarr.delete_movie(film.radarr_movie_id)
            except RadarrError as exc:
                # Untrack anyway rather than leaving this stuck forever —
                # the usual cause is it's already gone from Radarr (e.g.
                # deleted there directly), which makes every future
                # attempt fail identically. Worst case if it wasn't
                # actually gone: it just sits in Radarr untracked.
                self._log_event(f"Could not delete {film.title!r} from Radarr ({exc}) — "
                                 "untracking anyway, probably already removed there directly.",
                                 level="warn")
        self.state_data = core_state.confirm_deleted(self.state_data, int(tmdb_id))
        self._log_event(f"Deleted {film.title!r} — removed manually.")
        self.publish_status({})

    # ------------------------------------------------------------------
    # TV DISCOVERY / SURPRISE (opt-in — only wired up when cfg.tv_enabled)
    # ------------------------------------------------------------------

    def tick_tv_discovery(self, kwargs):
        if not self._enabled() or self.missing_secrets:
            return
        now = datetime.now(timezone.utc)
        try:
            self._resync_watched_and_taste_if_stale(now)
            candidates = self.tmdb.discover_tv(self._effective_tv_genres(), self.cfg.tv_min_rating,
                                                pages=self.cfg.tmdb_pages)
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
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested_shows} |
                                        {int(k) for k in self.state_data.blocked_shows},
            key="tvdb_id", excluded_genres=self.cfg.excluded_genres)
        picks = picks[: self.cfg.tv_max_suggestions_per_run]

        for c in picks:
            sonarr_series_id = None
            if not self._dry_run():
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

    def on_surprise_tv_now_pressed(self, event_name, data, kwargs):
        self._run_tv_surprise_pick()
        self.publish_status({})

    def tick_tv_surprise_check(self, kwargs):
        if not self._enabled() or not self._tv_surprise_enabled():
            return
        now = datetime.now(timezone.utc)
        if not core_surprise.is_surprise_due(now, self.state_data.next_tv_surprise_at):
            return
        self._run_tv_surprise_pick()

    def _run_tv_surprise_pick(self):
        if self.missing_secrets or not self.cfg.tv_enabled:
            return
        if self._surprise_requires_approval() and self.state_data.pending_tv_surprise is not None:
            self._log_event("A TV surprise proposal is already awaiting accept/deny — skipping.")
            return
        now = datetime.now(timezone.utc)
        genres = (self.cfg.tv_surprise_genres if self.cfg.tv_surprise_genres is not None
                  else self._effective_tv_genres())
        excluded = list(self.cfg.excluded_genres) + self._denied_genres()
        try:
            self._resync_watched_and_taste_if_stale(now)
            candidates = self.tmdb.discover_tv(genres, self.cfg.tv_min_rating, pages=self.cfg.tmdb_pages)
            sonarr_ids = self.sonarr.get_library_tvdb_ids()
        except (TMDBError, SonarrError, JellyfinError) as exc:
            self._log_event(f"TV surprise pick failed: {exc}", level="error")
            return

        pool = core_discovery.filter_candidates(
            candidates, allowed_genres=genres, min_rating=self.cfg.tv_min_rating,
            watched_tmdb_ids=set(self.state_data.watched_tvdb_cache),
            radarr_tmdb_ids=sonarr_ids,
            already_suggested_tmdb_ids={int(k) for k in self.state_data.suggested_shows} |
                                        {int(k) for k in self.state_data.surprises_shows} |
                                        {int(k) for k in self.state_data.blocked_shows},
            key="tvdb_id", excluded_genres=excluded)
        pick = core_discovery.pick_surprise(pool, exclude_tmdb_ids=set(), key="tvdb_id")

        window = core_surprise.SurpriseWindow(self.cfg.tv_surprise_min_days, self.cfg.tv_surprise_max_days)
        self.state_data.next_tv_surprise_at = core_surprise.next_surprise_time(now, window).isoformat()

        if pick is None:
            self._log_event("No TV surprise candidate matched your filters this time.")
            return

        if self._surprise_requires_approval():
            proposal = core_state.PendingSurprise(
                tmdb_id=pick.tmdb_id, tvdb_id=pick.tvdb_id, imdb_id=pick.imdb_id, title=pick.title,
                year=pick.year, genres=list(pick.genres), rating=pick.rating, proposed_at=now.isoformat())
            self.state_data = core_state.set_pending_tv_surprise(self.state_data, proposal)
            self._log_event(f"Proposed TV surprise: {pick.title!r} ({pick.year}) — "
                             "accept or deny in the web UI.")
            self.call_service(
                "persistent_notification/create", title="yArr TV surprise proposed",
                message=f"{pick.title} ({pick.year}) — check yArr's web UI to accept or deny.")
            return

        self._add_surprise_show(pick, now)

    def _add_surprise_show(self, pick, now):
        """pick may be a core_discovery.TVCandidate (approval disabled)
        or a core_state.PendingSurprise (approval accepted) — both
        carry the tvdb_id/tmdb_id/title/year/imdb_id fields
        add_series()/record_surprise_show_added() need."""
        sonarr_series_id = None
        if not self._dry_run():
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

    def on_accept_tv_surprise(self, event_name, data, kwargs):
        pending = self.state_data.pending_tv_surprise
        if pending is None:
            return
        now = datetime.now(timezone.utc)
        self.state_data = core_state.record_genre_feedback(self.state_data, pending.genres, accepted=True)
        self.state_data = core_state.clear_pending_tv_surprise(self.state_data)
        self._add_surprise_show(pending, now)
        self.publish_status({})

    def on_deny_tv_surprise(self, event_name, data, kwargs):
        pending = self.state_data.pending_tv_surprise
        if pending is None:
            return
        now = datetime.now(timezone.utc)
        self.state_data = core_state.record_genre_feedback(self.state_data, pending.genres, accepted=False)
        self.state_data = core_state.block_show(
            self.state_data, pending.tvdb_id, pending.title, pending.year, now)
        self.state_data = core_state.clear_pending_tv_surprise(self.state_data)
        self._log_event(f"Denied and blocked TV surprise: {pending.title!r} "
                         f"(genres: {', '.join(pending.genres) or 'none'}).")
        self.publish_status({})

    def on_unblock_movie(self, event_name, data, kwargs):
        tmdb_id = (data or {}).get("tmdb_id")
        if tmdb_id is None:
            return
        item = self.state_data.blocked_movies.get(str(tmdb_id))
        if item is None:
            return
        self.state_data = core_state.unblock_movie(self.state_data, tmdb_id)
        self._log_event(f"Unblocked {item['title']!r} — eligible for auto-add/surprise again.")
        self.publish_status({})

    def on_unblock_show(self, event_name, data, kwargs):
        tvdb_id = (data or {}).get("tvdb_id")
        if tvdb_id is None or not self.cfg.tv_enabled:
            return
        item = self.state_data.blocked_shows.get(str(tvdb_id))
        if item is None:
            return
        self.state_data = core_state.unblock_show(self.state_data, tvdb_id)
        self._log_event(f"Unblocked {item['title']!r} — eligible for auto-add/surprise again.")
        self.publish_status({})

    def on_delete_tv_surprise_now(self, event_name, data, kwargs):
        tvdb_id = (data or {}).get("tvdb_id")
        if tvdb_id is None or not self.cfg.tv_enabled:
            return
        show = self.state_data.surprises_shows.get(str(tvdb_id))
        if show is None:
            return
        if not self._dry_run() and show.sonarr_series_id is not None:
            try:
                self.sonarr.delete_series(show.sonarr_series_id)
            except SonarrError as exc:
                # Untrack anyway — see on_delete_surprise_now's comment.
                self._log_event(f"Could not delete {show.title!r} from Sonarr ({exc}) — "
                                 "untracking anyway, probably already removed there directly.",
                                 level="warn")
        self.state_data = core_state.confirm_show_deleted(self.state_data, int(tvdb_id))
        self._log_event(f"Deleted {show.title!r} — removed manually.")
        self.publish_status({})

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
                if not self._dry_run() and film.radarr_movie_id is not None:
                    try:
                        self.radarr.delete_movie(film.radarr_movie_id)
                    except RadarrError as exc:
                        # Untrack anyway — see on_delete_surprise_now's
                        # comment; otherwise a title already removed
                        # from Radarr directly fails this same way every
                        # 15 minutes forever.
                        self._log_event(f"Could not delete {film.title!r} from Radarr ({exc}) — "
                                         "untracking anyway, probably already removed there directly.",
                                         level="warn")
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
                    if not self._dry_run() and show.sonarr_series_id is not None:
                        try:
                            self.sonarr.delete_series(show.sonarr_series_id)
                        except SonarrError as exc:
                            self._log_event(f"Could not delete {show.title!r} from Sonarr ({exc}) — "
                                             "untracking anyway, probably already removed there directly.",
                                             level="warn")
                    self._log_event(f"Deleted {show.title!r} after the grace period.")
                    self.state_data = core_state.confirm_show_deleted(self.state_data, show.tvdb_id)
                self.set_state("input_boolean.yarr_keep_surprise_tv", state="off")

        self._save_state()

    def tick_reconcile_surprises(self, kwargs):
        """yArr only learns about a deletion through its own delete
        flow — if a tracked surprise is removed directly in Radarr/
        Sonarr instead, yArr's state never finds out and keeps showing
        it as tracked forever. Periodically cross-checks the current
        library against what's tracked and untracks anything that's no
        longer actually there, regardless of how it disappeared."""
        if self.missing_secrets:
            return
        try:
            radarr_ids = self.radarr.get_library_tmdb_ids()
        except RadarrError as exc:
            self._log_event(f"tick_reconcile_surprises (movies) failed: {exc}", level="error")
            radarr_ids = None
        if radarr_ids is not None:
            for key, film in list(self.state_data.surprises.items()):
                if film.radarr_movie_id is not None and film.tmdb_id not in radarr_ids:
                    self.state_data = core_state.confirm_deleted(self.state_data, film.tmdb_id)
                    self._log_event(f"{film.title!r} is no longer in Radarr — untracked "
                                     "(deleted outside yArr?).")

        if self.cfg.tv_enabled:
            try:
                sonarr_ids = self.sonarr.get_library_tvdb_ids()
            except SonarrError as exc:
                self._log_event(f"tick_reconcile_surprises (TV) failed: {exc}", level="error")
                sonarr_ids = None
            if sonarr_ids is not None:
                for key, show in list(self.state_data.surprises_shows.items()):
                    if show.sonarr_series_id is not None and show.tvdb_id not in sonarr_ids:
                        self.state_data = core_state.confirm_show_deleted(self.state_data, show.tvdb_id)
                        self._log_event(f"{show.title!r} is no longer in Sonarr — untracked "
                                         "(deleted outside yArr?).")

        self._save_state()

    # ------------------------------------------------------------------
    # DUPLICATE MEDIA SCAN (read-only, report-only)
    # ------------------------------------------------------------------

    @staticmethod
    def _dir_contents(path):
        """(total_bytes, [(name, size), ...]) for everything under this
        directory, or None if any file couldn't be measured. A network
        hiccup mid-walk must never silently look like "this folder is
        empty" — an undercounted size was exactly the kind of false
        signal that could make a real, wanted, multi-GB download look
        safe to auto-delete as if it were 0 bytes. None means
        couldn't-tell-try-again-later, never assume-it-was-zero. The
        per-file listing feeds core_junk.contains_likely_video — a
        folder that actually has a complete video sitting in it isn't
        junk, however it's named."""
        total = 0
        files = []
        for dirpath, _dirnames, filenames in os.walk(path):
            for name in filenames:
                try:
                    size = os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    return None
                total += size
                files.append((name, size))
        return total, files

    @staticmethod
    def _latest_mtime_in_dir(path) -> float:
        """Newest mtime of anything in this directory tree — used to
        tell a genuinely abandoned unpack folder apart from one
        SABnzbd is actively writing to right now, which would
        otherwise look identical. Biased toward "this looks fresh" on
        any read failure (returns right now, not the Unix epoch): an
        inability to determine a folder's age must never be mistaken
        for confirmation that it's old enough to be safe."""
        try:
            latest = os.path.getmtime(path)
        except OSError:
            return time.time()
        for dirpath, _dirnames, filenames in os.walk(path):
            for name in filenames:
                try:
                    latest = max(latest, os.path.getmtime(os.path.join(dirpath, name)))
                except OSError:
                    return time.time()
        return latest

    def _sabnzbd_active_names(self) -> set:
        """Display names of everything currently in SABnzbd's own
        queue (downloading, paused, or mid-repair/extraction) — the
        one signal that actually knows whether a job is still active,
        as opposed to guessing from file age alone. Empty set (never
        raises) if SABnzbd isn't configured or is unreachable right
        now, in which case age is the only signal available."""
        if not self.cfg.sabnzbd_enabled:
            return set()
        try:
            queue = self.sabnzbd.get_queue()
        except SABnzbdError:
            return set()
        return {item["filename"] for item in queue["items"] if item.get("filename")}

    def _walk_media_and_junk(self, active_job_names):
        """The actual filesystem I/O — deliberately kept out of
        core/dupes.py and core/junk.py so those stay pure/unit-testable.
        Single os.walk pass per root feeding both the duplicate scan
        and the leftover-SABnzbd-unpack-junk scan, rather than walking
        a (potentially huge, network-mounted) library twice. Any
        unreadable file/directory is skipped rather than aborting the
        whole scan (permissions quirks on a network share are common
        and shouldn't take out the rest of the results). A directory
        matching core_junk's _UNPACK_/_FAILED_ naming is recorded whole
        and never descended into — everything inside it is being
        deleted as one unit, not inspected file-by-file.

        Four independent gates before anything is ever called junk —
        all four defaulting toward "leave it alone" on any doubt, since
        the failure mode here is real, wanted data getting deleted:
        (1) old enough (_latest_mtime_in_dir, biased toward "looks
        fresh" on a read error), (2) its contents could actually be
        measured (_dir_contents returning None means "unknown," not
        "empty"), (3) it doesn't match anything SABnzbd's own live
        queue still considers active (active_job_names) — file age
        alone can't tell a stalled job apart from one stuck on slow
        par2 repair or one you paused on purpose, which is exactly what
        let a real download get swept up as "junk" once — and (4) it
        doesn't actually contain a complete-looking video file, since
        something can finish extracting and still sit under an
        _UNPACK_ name if only the final rename/import step got
        interrupted."""
        age_cutoff = time.time() - self.cfg.junk_min_age_hours * 3600
        media_files = []
        junk_entries = []
        for root_path in self.cfg.media_scan_paths:
            for dirpath, dirnames, filenames in os.walk(root_path):
                keep_dirs = []
                for d in dirnames:
                    full_path = os.path.join(dirpath, d)
                    is_candidate = (
                        core_junk.is_junk_dir_name(d)
                        and self._latest_mtime_in_dir(full_path) <= age_cutoff
                        and not core_junk.matches_active_job(d, active_job_names))
                    contents = self._dir_contents(full_path) if is_candidate else None
                    if is_candidate and contents is not None and not core_junk.contains_likely_video(contents[1]):
                        junk_entries.append({"path": full_path, "size": contents[0], "is_dir": True})
                    else:
                        keep_dirs.append(d)
                dirnames[:] = keep_dirs

                for name in filenames:
                    full_path = os.path.join(dirpath, name)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        continue
                    if core_junk.is_junk_file_name(name):
                        try:
                            mtime = os.path.getmtime(full_path)
                        except OSError:
                            continue
                        if mtime <= age_cutoff and not core_junk.matches_active_job(name, active_job_names):
                            junk_entries.append({"path": full_path, "size": size, "is_dir": False})
                        continue
                    media_files.append(core_dupes.MediaFile(path=full_path, size=size))
        return media_files, junk_entries

    def _all_tracked_media_basenames(self) -> set:
        """Every tracked file's BASENAME — not full path — that Radarr
        (and Sonarr, if enabled) currently track. Used by
        core_dupes.files_to_delete to tell a duplicate group's real,
        tracked copy apart from a stray leftover. Basename, because
        Radarr/Sonarr and yArr routinely see the same physical file
        through different mount prefixes (their own Docker container's
        mount vs. Home Assistant's /media share) — comparing full paths
        would never match in that setup, which is the normal case, not
        an edge case, and previously left every group's bulk-delete
        count stuck at 0 with no error at all."""
        paths = set(self.radarr.get_all_movie_file_paths())
        if self.cfg.tv_enabled:
            paths |= self.sonarr.get_all_episode_file_paths()
        return {os.path.basename(p) for p in paths}

    def on_scan_duplicates_now_pressed(self, event_name, data, kwargs):
        self.tick_scan_duplicates({})

    def tick_scan_duplicates(self, kwargs):
        if not self.cfg.media_scan_enabled:
            return
        active_job_names = self._sabnzbd_active_names()
        try:
            files, junk_entries = self._walk_media_and_junk(active_job_names)
        except OSError as exc:
            self._log_event(f"Media duplicate scan failed: {exc}", level="error")
            self.publish_status({})
            return

        min_size_bytes = int(self.cfg.media_scan_min_size_mb * 1_000_000)
        groups = core_dupes.find_duplicate_groups(files, min_size_bytes=min_size_bytes)
        self.state_data.duplicate_groups = [
            [{"path": f.path, "size": f.size} for f in group] for group in groups]
        self.state_data.duplicate_scan_at = datetime.now(timezone.utc).isoformat()
        self.state_data.junk_scan_at = self.state_data.duplicate_scan_at

        # A junk item with nothing in it (SABnzbd created the folder
        # but never wrote any real data before dying, or a truly
        # zero-byte stray archive fragment) can't cost you anything by
        # removing it — no media content is at risk — so this is the
        # one case in the whole add-on where a delete happens without a
        # button press. Anything with real bytes in it still needs one.
        auto_delete_now, remaining_junk = [], []
        for e in junk_entries:
            (auto_delete_now if e["size"] == 0 else remaining_junk).append(e)

        auto_deleted = []
        if auto_delete_now and self._dry_run():
            self._log_event(f"[dry_run] Would auto-delete {len(auto_delete_now)} empty junk item(s).")
            remaining_junk.extend(auto_delete_now)
        elif auto_delete_now:
            for e in auto_delete_now:
                try:
                    if e["is_dir"]:
                        shutil.rmtree(e["path"])
                    else:
                        os.remove(e["path"])
                except OSError as exc:
                    self._log_event(f"Could not auto-delete empty junk {e['path']!r}: {exc}", level="warn")
                    remaining_junk.append(e)
                    continue
                self._cleanup_empty_dirs(e["path"])
                auto_deleted.append(e)

        self.state_data.junk_entries = remaining_junk
        if auto_deleted:
            self._log_event(f"Auto-deleted {len(auto_deleted)} empty leftover-unpack item(s) "
                             "(0 bytes — nothing to lose).")
            try:
                self.jellyfin.refresh_library()
            except JellyfinError as exc:
                self._log_event(f"Jellyfin library refresh after junk auto-delete failed: {exc}",
                                 level="warn")

        try:
            tracked_basenames = self._all_tracked_media_basenames()
        except (RadarrError, SonarrError) as exc:
            self._log_event(f"Could not compute bulk-deletable duplicates: {exc}", level="warn")
            self.state_data.duplicate_deletable_count = None
            self.state_data.duplicate_deletable_bytes = None
        else:
            deletable = [f for group in self.state_data.duplicate_groups
                         for f in core_dupes.files_to_delete(group, tracked_basenames)]
            self.state_data.duplicate_deletable_count = len(deletable)
            self.state_data.duplicate_deletable_bytes = sum(f["size"] for f in deletable)

        self._save_state()

        if groups:
            wasted_gb = core_dupes.wasted_bytes(groups) / 1_000_000_000
            self._log_event(f"Media scan: {len(groups)} possible duplicate group(s) found "
                             f"(~{wasted_gb:.1f} GB) — review in the web UI.")
        else:
            self._log_event("Media scan: no duplicates found.")
        if remaining_junk:
            junk_gb = sum(e["size"] for e in remaining_junk) / 1_000_000_000
            self._log_event(f"Media scan: {len(remaining_junk)} leftover unpack/junk item(s) found "
                             f"(~{junk_gb:.1f} GB) — review in the web UI.")
        self.publish_status({})

    def on_bulk_delete_duplicates_pressed(self, event_name, data, kwargs):
        """Deletes every duplicate whose group has exactly one file
        that matches Radarr/Sonarr's actually-tracked path, in one go —
        the group is left alone if zero or more than one file in it
        matches (core_dupes.files_to_delete's ambiguity rule), so this
        never guesses which copy to keep."""
        if not self.cfg.media_scan_enabled:
            return
        try:
            tracked_basenames = self._all_tracked_media_basenames()
        except (RadarrError, SonarrError) as exc:
            self._log_event(f"Bulk duplicate delete aborted — could not fetch tracked files: {exc}",
                             level="error")
            self.publish_status({})
            return

        to_delete_by_group = [
            (group, core_dupes.files_to_delete(group, tracked_basenames))
            for group in self.state_data.duplicate_groups]
        total_to_delete = sum(len(d) for _, d in to_delete_by_group)

        if self._dry_run():
            self._log_event(f"[dry_run] Would bulk-delete {total_to_delete} duplicate file(s).")
            self.publish_status({})
            return

        deleted = []
        skipped_groups = 0
        new_groups = []
        for group, to_delete in to_delete_by_group:
            if not to_delete:
                skipped_groups += 1
                new_groups.append(group)
                continue
            deleted_paths = set()
            for f in to_delete:
                try:
                    os.remove(f["path"])
                except OSError as exc:
                    self._log_event(f"Could not delete {f['path']!r}: {exc}", level="error")
                    continue
                self._cleanup_empty_dirs(f["path"])
                deleted.append(f)
                deleted_paths.add(f["path"])
            remaining = [f for f in group if f["path"] not in deleted_paths]
            if len(remaining) > 1:
                new_groups.append(remaining)

        self.state_data.duplicate_groups = new_groups
        self.state_data.duplicate_deletable_count = 0
        self.state_data.duplicate_deletable_bytes = 0

        freed_gb = sum(f["size"] for f in deleted) / 1_000_000_000
        self._log_event(
            f"Bulk duplicate cleanup: deleted {len(deleted)} file(s) (~{freed_gb:.1f} GB freed)"
            + (f", skipped {skipped_groups} ambiguous group(s) for manual review" if skipped_groups else "")
            + ".")

        if deleted:
            try:
                self.radarr.rescan_library()
            except RadarrError as exc:
                self._log_event(f"Radarr rescan after bulk delete failed: {exc}", level="warn")
            if self.cfg.tv_enabled:
                try:
                    self.sonarr.rescan_library()
                except SonarrError as exc:
                    self._log_event(f"Sonarr rescan after bulk delete failed: {exc}", level="warn")

        self._save_state()
        self.publish_status({})

    def _cleanup_empty_dirs(self, deleted_path):
        """Walks upward from a just-deleted file's directory, removing
        it and its parents while they're empty — stops the moment a
        directory still has content, or the moment it reaches one of
        the configured scan roots (never deletes the root itself, and
        never walks outside it either, so this can't reach anywhere on
        the mount yArr wasn't told to manage)."""
        roots = [os.path.normpath(p) for p in self.cfg.media_scan_paths]
        directory = os.path.dirname(os.path.normpath(deleted_path))
        while directory not in roots and any(
                directory.startswith(root + os.sep) for root in roots):
            try:
                if os.listdir(directory):
                    break
                os.rmdir(directory)
            except OSError as exc:
                self._log_event(f"Could not remove empty folder {directory!r}: {exc}", level="warn")
                break
            self._log_event(f"Removed empty folder: {directory!r}.")
            directory = os.path.dirname(directory)

    def _rename_surviving_copy(self, survivor_path):
        """Best-effort: after a duplicate is deleted, the copy that's
        left behind may not match your configured naming format (it's
        arbitrary which of the duplicates got tagged as "the" file by
        Radarr/Sonarr originally) — this looks it up and asks
        Radarr/Sonarr to rename it properly. Failures here are logged
        but never block the delete itself from having succeeded."""
        try:
            movie_id = self.radarr.find_movie_id_by_file_path(survivor_path)
            if movie_id is not None:
                self.radarr.rename_movie_files(movie_id)
        except RadarrError as exc:
            self._log_event(f"Radarr rename after duplicate delete failed: {exc}", level="warn")
        if self.cfg.tv_enabled:
            try:
                series_id = self.sonarr.find_series_id_by_file_path(survivor_path)
                if series_id is not None:
                    self.sonarr.rename_series_files(series_id)
            except SonarrError as exc:
                self._log_event(f"Sonarr rename after duplicate delete failed: {exc}", level="warn")

    def on_delete_duplicate_file(self, event_name, data, kwargs):
        """Deletes exactly one file off the NAS mount, cleans up any
        now-empty parent folders, renames the surviving copy to match
        your naming format, then tells Radarr/Sonarr to rescan so their
        databases don't go stale after a delete that bypassed their own
        delete flow entirely. Only ever acts on a path that was
        actually part of the last scan's results — never an arbitrary
        path from the event payload — since this is the one place yArr
        writes to the media mount at all."""
        path = (data or {}).get("path")
        if not path:
            return
        known_paths = {f["path"] for group in self.state_data.duplicate_groups for f in group}
        if path not in known_paths:
            self._log_event(f"Refused to delete {path!r} — not part of the last duplicate scan.",
                             level="error")
            self.publish_status({})
            return
        if self._dry_run():
            self._log_event(f"[dry_run] Would delete duplicate file: {path!r}.")
            self.publish_status({})
            return
        try:
            os.remove(path)
        except OSError as exc:
            self._log_event(f"Could not delete {path!r}: {exc}", level="error")
            self.publish_status({})
            return
        self._cleanup_empty_dirs(path)

        survivor_paths = []
        new_groups = []
        for group in self.state_data.duplicate_groups:
            if any(f["path"] == path for f in group):
                survivor_paths = [f["path"] for f in group if f["path"] != path]
            remaining = [f for f in group if f["path"] != path]
            if len(remaining) > 1:
                new_groups.append(remaining)
        self.state_data.duplicate_groups = new_groups
        self._log_event(f"Deleted duplicate file: {path!r}.")

        try:
            self.radarr.rescan_library()
        except RadarrError as exc:
            self._log_event(f"Radarr rescan after duplicate delete failed: {exc}", level="warn")
        if self.cfg.tv_enabled:
            try:
                self.sonarr.rescan_library()
            except SonarrError as exc:
                self._log_event(f"Sonarr rescan after duplicate delete failed: {exc}", level="warn")

        for survivor in survivor_paths:
            self._rename_surviving_copy(survivor)

        self.publish_status({})

    def on_delete_junk_entry(self, event_name, data, kwargs):
        """Deletes exactly one leftover-SABnzbd-unpack junk entry — a
        whole directory (shutil.rmtree) for an _UNPACK_/_FAILED_
        folder, or a single stray archive-part file. Same safety rule
        as on_delete_duplicate_file: only ever acts on a path that was
        actually part of the last scan's results, never an arbitrary
        path from the event payload. Refreshes Jellyfin's library
        afterward — the one write this add-on ever makes to Jellyfin —
        so the bogus entry these folders cause disappears without
        waiting for Jellyfin's own scheduled scan."""
        path = (data or {}).get("path")
        if not path:
            return
        entry = next((e for e in self.state_data.junk_entries if e["path"] == path), None)
        if entry is None:
            self._log_event(f"Refused to delete {path!r} — not part of the last scan.", level="error")
            self.publish_status({})
            return
        if self._dry_run():
            self._log_event(f"[dry_run] Would delete junk {'folder' if entry['is_dir'] else 'file'}: "
                             f"{path!r}.")
            self.publish_status({})
            return
        try:
            if entry["is_dir"]:
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as exc:
            self._log_event(f"Could not delete {path!r}: {exc}", level="error")
            self.publish_status({})
            return
        self._cleanup_empty_dirs(path)

        self.state_data.junk_entries = [e for e in self.state_data.junk_entries if e["path"] != path]
        self._log_event(f"Deleted junk {'folder' if entry['is_dir'] else 'file'}: {path!r}.")

        try:
            self.jellyfin.refresh_library()
        except JellyfinError as exc:
            self._log_event(f"Jellyfin library refresh after junk delete failed: {exc}", level="warn")

        self.publish_status({})

    def on_bulk_delete_junk_pressed(self, event_name, data, kwargs):
        """Deletes every junk item the last scan reported, in one pass.
        Unlike bulk duplicate delete there's no ambiguity to resolve —
        a junk entry is unambiguously junk by definition (name pattern
        plus old enough to not be an active unpack) — so this just
        clears out everything currently listed."""
        if not self.cfg.media_scan_enabled:
            return
        entries = list(self.state_data.junk_entries)
        if not entries:
            self.publish_status({})
            return
        if self._dry_run():
            self._log_event(f"[dry_run] Would bulk-delete {len(entries)} junk item(s).")
            self.publish_status({})
            return

        deleted = []
        remaining = []
        for e in entries:
            try:
                if e["is_dir"]:
                    shutil.rmtree(e["path"])
                else:
                    os.remove(e["path"])
            except OSError as exc:
                self._log_event(f"Could not delete {e['path']!r}: {exc}", level="error")
                remaining.append(e)
                continue
            self._cleanup_empty_dirs(e["path"])
            deleted.append(e)

        self.state_data.junk_entries = remaining
        freed_gb = sum(e["size"] for e in deleted) / 1_000_000_000
        self._log_event(f"Bulk junk cleanup: deleted {len(deleted)} item(s) (~{freed_gb:.1f} GB freed).")

        if deleted:
            try:
                self.jellyfin.refresh_library()
            except JellyfinError as exc:
                self._log_event(f"Jellyfin library refresh after bulk junk delete failed: {exc}",
                                 level="warn")

        self.publish_status({})

    # ------------------------------------------------------------------
    # LIBRARY: full-library browse/manage + search-and-request hub
    # ------------------------------------------------------------------

    def tick_refresh_library(self, kwargs):
        """Cheap compared to the NAS duplicate/junk scan — just a
        Radarr/Sonarr GET each, no filesystem walk — so this runs far
        more often (library_refresh_interval_hours, default 1h)."""
        if self.missing_secrets:
            return
        try:
            self.state_data.library_movies = self.radarr.get_library_movies()
            if self.cfg.tv_enabled:
                self.state_data.library_shows = self.sonarr.get_library_series()
        except (RadarrError, SonarrError) as exc:
            self._log_event(f"Library refresh failed: {exc}", level="error")
            return
        self.state_data.library_synced_at = datetime.now(timezone.utc).isoformat()
        self._save_state()

    def on_refresh_library_pressed(self, event_name, data, kwargs):
        self.tick_refresh_library({})
        self.publish_status({})

    def on_search_media(self, event_name, data, kwargs):
        """query/media_type come straight from the event payload — the
        one place in this feature trusting the raw payload is fine,
        since this only drives a read-only TMDB search, never a write.
        Cross-checks results against the current library so the web UI
        can show "already have it" instead of offering to re-add."""
        if self.missing_secrets:
            return
        query = (data or {}).get("query", "").strip()
        if not query:
            return
        media_type = "tv" if (data or {}).get("media_type") == "tv" and self.cfg.tv_enabled else "movie"
        try:
            if media_type == "tv":
                results = self.tmdb.search_tv(query)
                library_ids = self.sonarr.get_library_tvdb_ids()
                key = "tvdb_id"
            else:
                results = self.tmdb.search_movies(query)
                library_ids = self.radarr.get_library_tmdb_ids()
                key = "tmdb_id"
        except (TMDBError, RadarrError, SonarrError) as exc:
            self._log_event(f"Search failed: {exc}", level="error")
            self.publish_status({})
            return

        rows = core_library.mark_in_library(results, library_ids, key=key)
        self.state_data.last_search_query = query
        self.state_data.last_search_media_type = media_type
        self.state_data.last_search_results = rows
        self.state_data.last_search_at = datetime.now(timezone.utc).isoformat()
        self._log_event(f"Searched {media_type} for {query!r} — {len(rows)} result(s).")
        self.publish_status({})

    def on_request_add_movie(self, event_name, data, kwargs):
        """Adds a specific search result to Radarr — only ever acts on
        a tmdb_id present in the last search's results (never trusts
        the raw event payload alone for a write, same rule as
        on_delete_duplicate_file), and reuses the exact same add path
        as genre auto-add/surprise-add: same root folder, same quality
        profile, same Radarr client call."""
        tmdb_id = (data or {}).get("tmdb_id")
        if tmdb_id is None:
            return
        row = next((r for r in self.state_data.last_search_results if r.get("tmdb_id") == tmdb_id), None)
        if row is None or self.state_data.last_search_media_type != "movie":
            self._log_event(f"Refused to add tmdb_id {tmdb_id!r} — not part of the last search.",
                             level="error")
            self.publish_status({})
            return
        if row["in_library"]:
            self.publish_status({})
            return

        radarr_movie_id = None
        if not self._dry_run():
            try:
                qp_id = self.radarr.resolve_quality_profile_id(self.cfg.radarr_quality_profile_name)
                candidate = core_discovery.Candidate(
                    tmdb_id=row["tmdb_id"], imdb_id=None, title=row["title"],
                    year=row["year"], genres=[], rating=row.get("rating", 0.0))
                radarr_movie_id = self.radarr.add_movie(
                    candidate, root_folder=self.cfg.radarr_root_folder, quality_profile_id=qp_id,
                    minimum_availability=self.cfg.radarr_minimum_availability)
            except RadarrError as exc:
                self._log_event(f"Could not add requested {row['title']!r}: {exc}", level="error")
                self.publish_status({})
                return

        self._log_event(f"Requested and added {row['title']!r} ({row['year']}).")
        self.state_data = core_state.record_suggestion(self.state_data, core_state.SuggestedFilm(
            tmdb_id=row["tmdb_id"], title=row["title"], year=row["year"], source="requested",
            decision="added", suggested_at=datetime.now(timezone.utc).isoformat(),
            radarr_movie_id=radarr_movie_id))
        # Mark it in_library in the still-displayed search results too,
        # so the Add button doesn't stay clickable for what was just added.
        self.state_data.last_search_results = [
            {**r, "in_library": True} if r.get("tmdb_id") == tmdb_id else r
            for r in self.state_data.last_search_results]
        self._save_state()
        self.publish_status({})

    def on_request_add_show(self, event_name, data, kwargs):
        tvdb_id = (data or {}).get("tvdb_id")
        if tvdb_id is None or not self.cfg.tv_enabled:
            return
        row = next((r for r in self.state_data.last_search_results if r.get("tvdb_id") == tvdb_id), None)
        if row is None or self.state_data.last_search_media_type != "tv":
            self._log_event(f"Refused to add tvdb_id {tvdb_id!r} — not part of the last search.",
                             level="error")
            self.publish_status({})
            return
        if row["in_library"]:
            self.publish_status({})
            return

        sonarr_series_id = None
        if not self._dry_run():
            try:
                qp_id = self.sonarr.resolve_quality_profile_id(self.cfg.sonarr_quality_profile_name)
                candidate = core_discovery.TVCandidate(
                    tmdb_id=row["tmdb_id"], tvdb_id=row["tvdb_id"], imdb_id=None,
                    title=row["title"], year=row["year"], genres=[], rating=row.get("rating", 0.0))
                sonarr_series_id = self.sonarr.add_series(
                    candidate, root_folder=self.cfg.sonarr_root_folder, quality_profile_id=qp_id,
                    language_profile_id=self.cfg.sonarr_language_profile_id)
            except SonarrError as exc:
                self._log_event(f"Could not add requested show {row['title']!r}: {exc}", level="error")
                self.publish_status({})
                return

        self._log_event(f"Requested and added show {row['title']!r} ({row['year']}).")
        self.state_data = core_state.record_suggestion_show(
            self.state_data, core_state.SuggestedShow(
                tvdb_id=row["tvdb_id"], tmdb_id=row["tmdb_id"], title=row["title"], year=row["year"],
                source="requested", decision="added", suggested_at=datetime.now(timezone.utc).isoformat(),
                sonarr_series_id=sonarr_series_id))
        self.state_data.last_search_results = [
            {**r, "in_library": True} if r.get("tvdb_id") == tvdb_id else r
            for r in self.state_data.last_search_results]
        self._save_state()
        self.publish_status({})

    def on_library_delete_movie(self, event_name, data, kwargs):
        """The highest-blast-radius delete in yArr: unlike every other
        delete here, this can remove a movie you've had for years and
        never touched by yArr at all — so it's gated behind an
        explicit, separate apps.yaml opt-in on top of the web UI's own
        confirm dialog. Deliberately never touches state_data.surprises
        /suggested even if the deleted movie happens to also be
        tracked there — tick_reconcile_surprises already notices
        anything that vanishes from Radarr and untracks it on its own,
        with its own log line, so there's no need to duplicate that
        here and risk two code paths racing on the same state key."""
        if not self.cfg.allow_library_delete:
            self._log_event("Library delete refused — allow_library_delete is not enabled in apps.yaml.",
                             level="error")
            self.publish_status({})
            return
        movie_id = (data or {}).get("id")
        item = next((m for m in self.state_data.library_movies if m["id"] == movie_id), None)
        if item is None:
            self._log_event(f"Refused to delete library movie id {movie_id!r} — not part of the "
                             "last library listing.", level="error")
            self.publish_status({})
            return
        if self._dry_run():
            self._log_event(f"[dry_run] Would permanently delete {item['title']!r} from the library.")
            self.publish_status({})
            return
        try:
            self.radarr.delete_movie(item["id"])
        except RadarrError as exc:
            self._log_event(f"Could not delete {item['title']!r} from Radarr: {exc}", level="error")
            self.publish_status({})
            return
        self._log_event(f"Library delete: permanently removed {item['title']!r} ({item['year']}) "
                         "— requested from the Library tab.")
        self.state_data.library_movies = [m for m in self.state_data.library_movies if m["id"] != movie_id]
        self._save_state()
        self.publish_status({})

    def on_library_delete_show(self, event_name, data, kwargs):
        if not self.cfg.tv_enabled:
            return
        if not self.cfg.allow_library_delete:
            self._log_event("Library delete refused — allow_library_delete is not enabled in apps.yaml.",
                             level="error")
            self.publish_status({})
            return
        series_id = (data or {}).get("id")
        item = next((s for s in self.state_data.library_shows if s["id"] == series_id), None)
        if item is None:
            self._log_event(f"Refused to delete library show id {series_id!r} — not part of the "
                             "last library listing.", level="error")
            self.publish_status({})
            return
        if self._dry_run():
            self._log_event(f"[dry_run] Would permanently delete {item['title']!r} from the library.")
            self.publish_status({})
            return
        try:
            self.sonarr.delete_series(item["id"])
        except SonarrError as exc:
            self._log_event(f"Could not delete {item['title']!r} from Sonarr: {exc}", level="error")
            self.publish_status({})
            return
        self._log_event(f"Library delete: permanently removed {item['title']!r} ({item['year']}) "
                         "— requested from the Library tab.")
        self.state_data.library_shows = [s for s in self.state_data.library_shows if s["id"] != series_id]
        self._save_state()
        self.publish_status({})

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

    @staticmethod
    def _blocked_rows(blocked_dict):
        rows = [{"id": int(k), "title": v["title"], "year": v["year"], "blocked_at": v["blocked_at"]}
                for k, v in blocked_dict.items()]
        return sorted(rows, key=lambda r: r["blocked_at"], reverse=True)

    def _surprise_rows(self, surprises_dict, id_field="tmdb_id"):
        rows = sorted(surprises_dict.values(), key=lambda f: f.added_at, reverse=True)
        out = []
        for f in rows:
            row = {"id": getattr(f, id_field), "title": f.title, "year": f.year,
                   "status": self._film_status(f)}
            if f.pending_deletion:
                row["delete_at"] = f.pending_deletion.delete_at
            out.append(row)
        return out

    @staticmethod
    def _pending_row(pending):
        if pending is None:
            return None
        return {"title": pending.title, "year": pending.year, "rating": pending.rating,
                "genres": pending.genres}

    def publish_status(self, kwargs):
        attrs = {
            "suggested_count": len(self.state_data.suggested),
            "surprise_count": len(self.state_data.surprises),
            "next_surprise_at": self.state_data.next_surprise_at,
            "missing_secrets": self.missing_secrets,
            "tv_enabled": self.cfg.tv_enabled,
            "sabnzbd_enabled": self.cfg.sabnzbd_enabled,
            "media_scan_enabled": self.cfg.media_scan_enabled,
            "excluded_genres": self.cfg.excluded_genres,
            "denied_genres": self._denied_genres(),
            "effective_genres": self._effective_genres(),
            "learned_genres": self.state_data.learned_genres,
            "recent_suggested": self._recent_suggested(self.state_data.suggested),
            "surprises": self._surprise_rows(self.state_data.surprises, id_field="tmdb_id"),
            "pending_surprise": self._pending_row(self.state_data.pending_surprise),
            "blocked_movies": self._blocked_rows(self.state_data.blocked_movies),
            "log": list(reversed(self.state_data.event_log[-30:])),
            # Library tab — always published (not gated on an opt-in
            # feature flag like the sections below), since browsing and
            # searching are core functionality once shipped. Capped
            # generously (not the [:50] used for duplicate/junk lists,
            # which would be useless for a real library) as a hard
            # ceiling against unbounded HA attribute payload size.
            "library_movies": self.state_data.library_movies[:2000],
            "library_movie_count": len(self.state_data.library_movies),
            "library_synced_at": self.state_data.library_synced_at,
            "last_search_query": self.state_data.last_search_query,
            "last_search_media_type": self.state_data.last_search_media_type,
            "last_search_results": self.state_data.last_search_results,
            "last_search_at": self.state_data.last_search_at,
            "allow_library_delete": self.cfg.allow_library_delete,
        }
        if self.cfg.tv_enabled:
            attrs.update({
                "suggested_shows_count": len(self.state_data.suggested_shows),
                "surprise_shows_count": len(self.state_data.surprises_shows),
                "next_tv_surprise_at": self.state_data.next_tv_surprise_at,
                "effective_tv_genres": self._effective_tv_genres(),
                "learned_tv_genres": self.state_data.learned_tv_genres,
                "recent_suggested_shows": self._recent_suggested(self.state_data.suggested_shows),
                "surprise_shows": self._surprise_rows(self.state_data.surprises_shows, id_field="tvdb_id"),
                "pending_tv_surprise": self._pending_row(self.state_data.pending_tv_surprise),
                "blocked_shows": self._blocked_rows(self.state_data.blocked_shows),
                "library_shows": self.state_data.library_shows[:2000],
                "library_show_count": len(self.state_data.library_shows),
            })
        if self.cfg.media_scan_enabled:
            attrs.update({
                "duplicate_groups": self.state_data.duplicate_groups[:50],
                "duplicate_group_count": len(self.state_data.duplicate_groups),
                "duplicate_wasted_bytes": sum(
                    group[0]["size"] * (len(group) - 1) for group in self.state_data.duplicate_groups
                    if group),
                "duplicate_scan_at": self.state_data.duplicate_scan_at,
                "duplicate_deletable_count": self.state_data.duplicate_deletable_count,
                "duplicate_deletable_bytes": self.state_data.duplicate_deletable_bytes,
                "junk_entries": self.state_data.junk_entries[:50],
                "junk_count": len(self.state_data.junk_entries),
                "junk_bytes": sum(e["size"] for e in self.state_data.junk_entries),
                "junk_scan_at": self.state_data.junk_scan_at,
            })
        self.set_state("sensor.yarr_status",
                        state="Not Configured" if self.missing_secrets else "OK",
                        attributes=attrs)
        self.set_state("sensor.yarr_heartbeat", state=datetime.now(timezone.utc).isoformat())
