import pytest

from core.config import build_config, required_secrets_ok, ConfigError


def test_defaults_when_apps_yaml_empty():
    cfg = build_config({}, {})
    assert cfg.genres == []
    assert cfg.min_rating == 7.0
    assert cfg.radarr_root_folder == "/movies"
    assert cfg.surprise_genres is None


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
