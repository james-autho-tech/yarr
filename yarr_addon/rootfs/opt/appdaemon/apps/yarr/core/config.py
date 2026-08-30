"""YarrConfig — behaviour (apps.yaml) + credentials (addon_secrets.json)
as two disjoint namespaces. There's no auto-discovery concept here, so
no precedence chain is needed between them — each key lives in exactly
one of the two files."""

from dataclasses import dataclass, field

# jellyfin_*/radarr_*/tmdb_api_key are required — movies plus the
# shared discovery/watch-history dependencies. sonarr_url/sonarr_api_key
# are intentionally NOT required: TV support is opt-in on top of the
# movie feature set, so an install with only Radarr configured should
# still start cleanly with the TV ticks silently skipped.
REQUIRED_SECRETS = ("radarr_url", "radarr_api_key", "tmdb_api_key",
                     "jellyfin_url", "jellyfin_api_key")


class ConfigError(Exception):
    """Raised by build_config() for a structurally broken apps.yaml
    (e.g. genres not a list). Missing secrets are NOT raised as an
    error — see required_secrets_ok() — so the app can still start and
    publish a "Not Configured" status instead of crash-looping."""


@dataclass(frozen=True)
class YarrConfig:
    # --- apps.yaml (non-secret behaviour) — movies ---
    genres: list = field(default_factory=list)
    min_rating: float = 7.0
    discovery_interval_hours: float = 24.0
    max_suggestions_per_run: int = 3
    radarr_root_folder: str = "/movies"
    radarr_quality_profile_name: str = "HD-1080p"
    radarr_minimum_availability: str = "announced"
    surprise_enabled: bool = True
    surprise_genres: list = None
    surprise_min_days: float = 5.0
    surprise_max_days: float = 10.0
    surprise_tag: str = "yarr-surprise"
    # When true (default), a surprise pick waits for Accept/Deny in the
    # web UI before ever touching Radarr/Sonarr, instead of being added
    # automatically. Shared with TV — one approval model for both.
    surprise_requires_approval: bool = True
    # A genre denied at least this many times is actively excluded from
    # future surprise picks (movies and TV both draw from the same
    # feedback tally — see core/state.denied_genres_over_threshold).
    surprise_feedback_deny_threshold: int = 2

    # --- apps.yaml (non-secret behaviour) — TV, opt-in via sonarr_url/
    # sonarr_api_key being set. Threshold/grace-period/resync cadence
    # are shared with movies (same concepts, no need to duplicate the
    # knob) — only the genre/rating/cadence/Sonarr-specific settings
    # get their own tv_/sonarr_ prefixed keys.
    tv_genres: list = field(default_factory=list)
    tv_min_rating: float = 7.0
    tv_discovery_interval_hours: float = 24.0
    tv_max_suggestions_per_run: int = 3
    sonarr_root_folder: str = "/tv"
    sonarr_quality_profile_name: str = "HD-1080p"
    # Only sent to Sonarr if set — Sonarr v4 dropped Language Profiles,
    # so this is optional rather than assumed present.
    sonarr_language_profile_id: int = None
    tv_surprise_enabled: bool = True
    tv_surprise_genres: list = None
    tv_surprise_min_days: float = 5.0
    tv_surprise_max_days: float = 10.0
    tv_surprise_tag: str = "yarr-surprise"

    # --- shared ---
    completion_threshold_pct: float = 90.0
    delete_grace_period_hours: float = 24.0
    # Which Jellyfin user's watch history to read — leave unset to use
    # whichever account the API key's own /Users lookup returns first
    # (fine for a single-user Jellyfin instance).
    jellyfin_username: str = None
    watched_resync_hours: float = 24.0
    # When true, `genres`/`tv_genres` are ignored in favour of a
    # weighted profile learned from your Jellyfin watch history (see
    # core/taste.py) — refreshed on the same watched_resync_hours
    # cadence as the watched-id caches. Falls back to the configured
    # genre lists if your library doesn't yield any (e.g. brand new).
    learn_genres_from_library: bool = False
    taste_top_n_genres: int = 5
    # Hard veto, checked independently of genres/tv_genres (or a
    # learned profile) — a title carrying one of these is never
    # suggested/surprised regardless of anything else matching.
    excluded_genres: list = field(default_factory=list)
    # TMDB returns 20 results per page; page 1 alone gets exhausted fast
    # once genre/rating/exclusion/already-suggested filters are applied,
    # producing "no candidate matched" more often than the actual pool
    # of decent titles would suggest. Shared by movie and TV discovery.
    tmdb_pages: int = 3
    dry_run: bool = False

    # Duplicate-media scan — entirely opt-in via media_scan_paths being
    # non-empty (needs the `media` map in config.yaml, i.e. HA's own
    # /media share configured to point at wherever your library lives —
    # see DOCS.md). Report-only: yArr never deletes anything it finds
    # here, only lists candidate groups for you to review.
    media_scan_paths: list = field(default_factory=list)
    media_scan_min_size_mb: float = 50.0
    media_scan_interval_hours: float = 24.0

    # Failed-unpack/junk detection (same scan pass, see core/junk.py) —
    # an _UNPACK_/_FAILED_ folder or stray archive piece is only ever
    # reported (or auto-deleted, if empty) once it hasn't been modified
    # for this long. Without this, a folder SABnzbd is actively
    # extracting into right now — which looks identical to an
    # abandoned one at a glance — could get deleted mid-extraction.
    junk_min_age_hours: float = 1.0

    # --- addon_secrets.json (config.yaml options — never in apps.yaml) ---
    radarr_url: str = ""
    radarr_api_key: str = ""
    sonarr_url: str = ""
    sonarr_api_key: str = ""
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    tmdb_api_key: str = ""
    # Optional — read-only queue monitoring only, never required.
    sabnzbd_url: str = ""
    sabnzbd_api_key: str = ""

    @property
    def tv_enabled(self) -> bool:
        return bool(self.sonarr_url and self.sonarr_api_key)

    @property
    def sabnzbd_enabled(self) -> bool:
        return bool(self.sabnzbd_url and self.sabnzbd_api_key)

    @property
    def media_scan_enabled(self) -> bool:
        return bool(self.media_scan_paths)


def _as_genre_list(a: dict, key: str) -> list:
    val = a.get(key)
    if val is None:
        return None if key.endswith("surprise_genres") else []
    if not isinstance(val, list):
        raise ConfigError(f"apps.yaml {key!r} must be a list, got {type(val).__name__}")
    return [str(g).lower() for g in val]


def _as_path_list(a: dict, key: str) -> list:
    val = a.get(key)
    if val is None:
        return []
    if not isinstance(val, list):
        raise ConfigError(f"apps.yaml {key!r} must be a list, got {type(val).__name__}")
    return [str(p) for p in val]


def build_config(apps_yaml_dict: dict, secrets_dict: dict) -> YarrConfig:
    a = apps_yaml_dict or {}
    s = secrets_dict or {}

    genres = _as_genre_list(a, "genres") or []
    surprise_genres = _as_genre_list(a, "surprise_genres")
    tv_genres = _as_genre_list(a, "tv_genres") or []
    tv_surprise_genres = _as_genre_list(a, "tv_surprise_genres")
    excluded_genres = _as_genre_list(a, "excluded_genres") or []
    media_scan_paths = _as_path_list(a, "media_scan_paths")

    return YarrConfig(
        genres=genres,
        min_rating=float(a.get("min_rating", 7.0)),
        discovery_interval_hours=float(a.get("discovery_interval_hours", 24.0)),
        max_suggestions_per_run=int(a.get("max_suggestions_per_run", 3)),
        radarr_root_folder=str(a.get("radarr_root_folder", "/movies")),
        radarr_quality_profile_name=str(a.get("radarr_quality_profile_name", "HD-1080p")),
        radarr_minimum_availability=str(a.get("radarr_minimum_availability", "announced")),
        surprise_enabled=bool(a.get("surprise_enabled", True)),
        surprise_genres=surprise_genres,
        surprise_min_days=float(a.get("surprise_min_days", 5.0)),
        surprise_max_days=float(a.get("surprise_max_days", 10.0)),
        surprise_tag=str(a.get("surprise_tag", "yarr-surprise")),
        surprise_requires_approval=bool(a.get("surprise_requires_approval", True)),
        surprise_feedback_deny_threshold=int(a.get("surprise_feedback_deny_threshold", 2)),

        tv_genres=tv_genres,
        tv_min_rating=float(a.get("tv_min_rating", 7.0)),
        tv_discovery_interval_hours=float(a.get("tv_discovery_interval_hours", 24.0)),
        tv_max_suggestions_per_run=int(a.get("tv_max_suggestions_per_run", 3)),
        sonarr_root_folder=str(a.get("sonarr_root_folder", "/tv")),
        sonarr_quality_profile_name=str(a.get("sonarr_quality_profile_name", "HD-1080p")),
        sonarr_language_profile_id=(int(a["sonarr_language_profile_id"])
                                     if a.get("sonarr_language_profile_id") else None),
        tv_surprise_enabled=bool(a.get("tv_surprise_enabled", True)),
        tv_surprise_genres=tv_surprise_genres,
        tv_surprise_min_days=float(a.get("tv_surprise_min_days", 5.0)),
        tv_surprise_max_days=float(a.get("tv_surprise_max_days", 10.0)),
        tv_surprise_tag=str(a.get("tv_surprise_tag", "yarr-surprise")),

        completion_threshold_pct=float(a.get("completion_threshold_pct", 90.0)),
        delete_grace_period_hours=float(a.get("delete_grace_period_hours", 24.0)),
        jellyfin_username=(str(a["jellyfin_username"]) if a.get("jellyfin_username") else None),
        watched_resync_hours=float(a.get("watched_resync_hours", 24.0)),
        learn_genres_from_library=bool(a.get("learn_genres_from_library", False)),
        taste_top_n_genres=int(a.get("taste_top_n_genres", 5)),
        excluded_genres=excluded_genres,
        tmdb_pages=int(a.get("tmdb_pages", 3)),
        dry_run=bool(a.get("dry_run", False)),

        media_scan_paths=media_scan_paths,
        media_scan_min_size_mb=float(a.get("media_scan_min_size_mb", 50.0)),
        media_scan_interval_hours=float(a.get("media_scan_interval_hours", 24.0)),
        junk_min_age_hours=float(a.get("junk_min_age_hours", 1.0)),

        radarr_url=str(s.get("radarr_url", "")),
        radarr_api_key=str(s.get("radarr_api_key", "")),
        sonarr_url=str(s.get("sonarr_url", "")),
        sonarr_api_key=str(s.get("sonarr_api_key", "")),
        jellyfin_url=str(s.get("jellyfin_url", "")),
        jellyfin_api_key=str(s.get("jellyfin_api_key", "")),
        tmdb_api_key=str(s.get("tmdb_api_key", "")),
        sabnzbd_url=str(s.get("sabnzbd_url", "")),
        sabnzbd_api_key=str(s.get("sabnzbd_api_key", "")),
    )


def required_secrets_ok(cfg: YarrConfig) -> list:
    """Returns the list of missing required secret field names."""
    return [name for name in REQUIRED_SECRETS if not getattr(cfg, name)]
