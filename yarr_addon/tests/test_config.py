import pytest

from core.config import build_config, required_secrets_ok, ConfigError


def test_defaults_when_apps_yaml_empty():
    cfg = build_config({}, {})
    assert cfg.genres == []
    assert cfg.min_rating == 7.0
    assert cfg.radarr_root_folder == "/movies"
    assert cfg.surprise_genres is None
    assert cfg.surprise_requires_approval is True


def test_surprise_approval_can_be_disabled():
    cfg = build_config({"surprise_requires_approval": False}, {})
    assert cfg.surprise_requires_approval is False


def test_genre_auto_add_enabled_default_true_and_parsed():
    assert build_config({}, {}).genre_auto_add_enabled is True
    cfg = build_config({"genre_auto_add_enabled": False}, {})
    assert cfg.genre_auto_add_enabled is False


def test_tv_genre_auto_add_enabled_default_true_and_parsed():
    assert build_config({}, {}).tv_genre_auto_add_enabled is True
    cfg = build_config({"tv_genre_auto_add_enabled": False}, {})
    assert cfg.tv_genre_auto_add_enabled is False


def test_tmdb_pages_default_and_parsed():
    assert build_config({}, {}).tmdb_pages == 3
    cfg = build_config({"tmdb_pages": 5}, {})
    assert cfg.tmdb_pages == 5


def test_media_scan_disabled_by_default():
    cfg = build_config({}, {})
    assert cfg.media_scan_paths == []
    assert cfg.media_scan_enabled is False
    assert cfg.media_scan_min_size_mb == 50.0
    assert cfg.media_scan_interval_hours == 24.0
    assert cfg.junk_min_age_hours == 1.0


def test_library_delete_disabled_by_default():
    cfg = build_config({}, {})
    assert cfg.allow_library_delete is False
    assert cfg.library_refresh_interval_hours == 1.0


def test_allow_library_delete_parsed():
    cfg = build_config({"allow_library_delete": True}, {})
    assert cfg.allow_library_delete is True


def test_junk_min_age_hours_parsed():
    cfg = build_config({"junk_min_age_hours": 3}, {})
    assert cfg.junk_min_age_hours == 3.0


def test_media_scan_enabled_when_paths_set():
    cfg = build_config({"media_scan_paths": ["/media/movies", "/media/tv"]}, {})
    assert cfg.media_scan_enabled is True
    assert cfg.media_scan_paths == ["/media/movies", "/media/tv"]


def test_media_scan_paths_must_be_a_list():
    with pytest.raises(ConfigError):
        build_config({"media_scan_paths": "/media/movies"}, {})


def test_merges_behaviour_and_secrets():
    cfg = build_config(
        {"genres": ["Sci-Fi", "Comedy"], "min_rating": 8.0},
        {"radarr_url": "http://radarr:7878", "radarr_api_key": "abc"})
    assert cfg.genres == ["sci-fi", "comedy"]
    assert cfg.min_rating == 8.0
    assert cfg.radarr_url == "http://radarr:7878"
    assert cfg.radarr_api_key == "abc"


def test_genres_must_be_a_list():
    with pytest.raises(ConfigError):
        build_config({"genres": "sci-fi"}, {})


def test_surprise_genres_must_be_a_list():
    with pytest.raises(ConfigError):
        build_config({"surprise_genres": "horror"}, {})


def test_required_secrets_ok_lists_missing():
    cfg = build_config({}, {"radarr_url": "http://radarr:7878"})
    missing = required_secrets_ok(cfg)
    assert "radarr_url" not in missing
    assert "radarr_api_key" in missing
    assert "tmdb_api_key" in missing
    # jellyfin is required now — watch-history exclusion reads it directly
    assert "jellyfin_url" in missing
    assert "jellyfin_api_key" in missing


def test_required_secrets_ok_empty_when_all_set():
    cfg = build_config({}, {
        "radarr_url": "u", "radarr_api_key": "k", "tmdb_api_key": "t",
        "jellyfin_url": "j", "jellyfin_api_key": "jk"})
    assert required_secrets_ok(cfg) == []


def test_sonarr_and_sabnzbd_not_required():
    cfg = build_config({}, {
        "radarr_url": "u", "radarr_api_key": "k", "tmdb_api_key": "t",
        "jellyfin_url": "j", "jellyfin_api_key": "jk"})
    assert required_secrets_ok(cfg) == []
    assert cfg.tv_enabled is False
    assert cfg.sabnzbd_enabled is False


def test_tv_enabled_only_when_both_sonarr_fields_set():
    cfg = build_config({}, {"sonarr_url": "http://sonarr:8989"})
    assert cfg.tv_enabled is False
    cfg = build_config({}, {"sonarr_url": "http://sonarr:8989", "sonarr_api_key": "k"})
    assert cfg.tv_enabled is True


def test_sabnzbd_enabled_only_when_both_fields_set():
    cfg = build_config({}, {"sabnzbd_url": "http://sab:8080", "sabnzbd_api_key": "k"})
    assert cfg.sabnzbd_enabled is True


def test_tv_genres_default_and_parsed():
    cfg = build_config({"tv_genres": ["Drama", "Comedy"]}, {})
    assert cfg.tv_genres == ["drama", "comedy"]
    assert build_config({}, {}).tv_genres == []


def test_tv_genres_must_be_a_list():
    with pytest.raises(ConfigError):
        build_config({"tv_genres": "drama"}, {})


def test_learn_genres_from_library_default_off():
    cfg = build_config({}, {})
    assert cfg.learn_genres_from_library is False
    assert cfg.taste_top_n_genres == 5


def test_excluded_genres_default_empty_and_parsed():
    assert build_config({}, {}).excluded_genres == []
    cfg = build_config({"excluded_genres": ["Horror", "War"]}, {})
    assert cfg.excluded_genres == ["horror", "war"]


def test_excluded_genres_must_be_a_list():
    with pytest.raises(ConfigError):
        build_config({"excluded_genres": "horror"}, {})
