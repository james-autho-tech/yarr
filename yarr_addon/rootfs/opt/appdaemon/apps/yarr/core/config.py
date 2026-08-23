"""YarrConfig — behaviour (apps.yaml) + credentials (addon_secrets.json)
as two disjoint namespaces. There's no auto-discovery concept here, so
no precedence chain is needed between them — each key lives in exactly
one of the two files."""

from dataclasses import dataclass, field

REQUIRED_SECRETS = ("radarr_url", "radarr_api_key", "trakt_client_id", "trakt_client_secret")


class ConfigError(Exception):
    """Raised by build_config() for a structurally broken apps.yaml
    (e.g. genres not a list). Missing secrets are NOT raised as an
    error — see required_secrets_ok() — so the app can still start and
    publish a "Not Configured" status instead of crash-looping."""


@dataclass(frozen=True)
class YarrConfig:
    # --- apps.yaml (non-secret behaviour) ---
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
    completion_threshold_pct: float = 90.0
    delete_grace_period_hours: float = 24.0
    trakt_history_resync_hours: float = 24.0
    dry_run: bool = False

    # --- addon_secrets.json (config.yaml options — never in apps.yaml) ---
    radarr_url: str = ""
    radarr_api_key: str = ""
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    trakt_client_id: str = ""
    trakt_client_secret: str = ""


def build_config(apps_yaml_dict: dict, secrets_dict: dict) -> YarrConfig:
    a = apps_yaml_dict or {}
    s = secrets_dict or {}

    genres = a.get("genres", [])
    if not isinstance(genres, list):
        raise ConfigError(f"apps.yaml 'genres' must be a list, got {type(genres).__name__}")
    surprise_genres = a.get("surprise_genres")
    if surprise_genres is not None and not isinstance(surprise_genres, list):
        raise ConfigError(
            f"apps.yaml 'surprise_genres' must be a list, got {type(surprise_genres).__name__}")

    return YarrConfig(
        genres=[str(g).lower() for g in genres],
        min_rating=float(a.get("min_rating", 7.0)),
        discovery_interval_hours=float(a.get("discovery_interval_hours", 24.0)),
        max_suggestions_per_run=int(a.get("max_suggestions_per_run", 3)),
        radarr_root_folder=str(a.get("radarr_root_folder", "/movies")),
        radarr_quality_profile_name=str(a.get("radarr_quality_profile_name", "HD-1080p")),
        radarr_minimum_availability=str(a.get("radarr_minimum_availability", "announced")),
        surprise_enabled=bool(a.get("surprise_enabled", True)),
        surprise_genres=([str(g).lower() for g in surprise_genres]
                         if surprise_genres is not None else None),
        surprise_min_days=float(a.get("surprise_min_days", 5.0)),
        surprise_max_days=float(a.get("surprise_max_days", 10.0)),
        surprise_tag=str(a.get("surprise_tag", "yarr-surprise")),
        completion_threshold_pct=float(a.get("completion_threshold_pct", 90.0)),
        delete_grace_period_hours=float(a.get("delete_grace_period_hours", 24.0)),
        trakt_history_resync_hours=float(a.get("trakt_history_resync_hours", 24.0)),
        dry_run=bool(a.get("dry_run", False)),
        radarr_url=str(s.get("radarr_url", "")),
        radarr_api_key=str(s.get("radarr_api_key", "")),
        jellyfin_url=str(s.get("jellyfin_url", "")),
        jellyfin_api_key=str(s.get("jellyfin_api_key", "")),
        trakt_client_id=str(s.get("trakt_client_id", "")),
        trakt_client_secret=str(s.get("trakt_client_secret", "")),
    )


def required_secrets_ok(cfg: YarrConfig) -> list:
    """Returns the list of missing required secret field names.
    jellyfin_* is intentionally excluded — it's only needed for the
    provider-id fallback lookup, not for the webhook path itself."""
    return [name for name in REQUIRED_SECRETS if not getattr(cfg, name)]
