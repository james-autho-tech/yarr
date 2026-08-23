from core.webhook import (parse_jellyfin_payload, matches_surprise,
                          parse_jellyfin_episode_payload, matches_surprise_show)
from core.state import SurpriseFilm, SurpriseShow


def test_parses_valid_movie_playback_stop():
    payload = {"NotificationType": "PlaybackStop", "ItemType": "Movie",
               "Name": "Inception", "PlaybackPercentage": "95.5",
               "Provider_tmdb": "27205", "Provider_imdb": "tt1375666"}
    event = parse_jellyfin_payload(payload)
    assert event.tmdb_id == 27205
    assert event.imdb_id == "tt1375666"
    assert event.item_name == "Inception"
    assert event.percentage == 95.5


def test_non_movie_item_returns_none():
    payload = {"NotificationType": "PlaybackStop", "ItemType": "Episode",
               "Provider_tmdb": "1"}
    assert parse_jellyfin_payload(payload) is None


def test_missing_notification_type_returns_none():
    assert parse_jellyfin_payload({"ItemType": "Movie"}) is None


def test_missing_provider_ids_returns_none():
    payload = {"NotificationType": "PlaybackStop", "ItemType": "Movie", "Name": "X"}
    assert parse_jellyfin_payload(payload) is None


def test_matches_surprise_tmdb_first():
    film = SurpriseFilm(tmdb_id=27205, imdb_id="tt1375666", title="Inception")
    surprises = {"27205": film}
    event = parse_jellyfin_payload({
        "NotificationType": "PlaybackStop", "ItemType": "Movie", "Name": "Inception",
        "PlaybackPercentage": "99", "Provider_tmdb": "27205"})
    assert matches_surprise(event, surprises) is film


def test_matches_surprise_imdb_fallback():
    film = SurpriseFilm(tmdb_id=27205, imdb_id="tt1375666", title="Inception")
    surprises = {"27205": film}
    event = parse_jellyfin_payload({
        "NotificationType": "PlaybackStop", "ItemType": "Movie", "Name": "Inception",
        "PlaybackPercentage": "99", "Provider_imdb": "tt1375666"})
    assert matches_surprise(event, surprises) is film


def test_no_match_returns_none():
    surprises = {"1": SurpriseFilm(tmdb_id=1, imdb_id="tt1", title="X")}
    event = parse_jellyfin_payload({
        "NotificationType": "PlaybackStop", "ItemType": "Movie", "Name": "Y",
        "PlaybackPercentage": "99", "Provider_tmdb": "999"})
    assert matches_surprise(event, surprises) is None


def test_parses_valid_episode_playback_stop():
    payload = {"NotificationType": "PlaybackStop", "ItemType": "Episode",
               "SeriesId": "abc-123", "SeriesName": "Breaking Bad",
               "PlaybackPercentage": "97"}
    event = parse_jellyfin_episode_payload(payload)
    assert event.series_item_id == "abc-123"
    assert event.series_name == "Breaking Bad"
    assert event.percentage == 97.0


def test_episode_payload_wrong_item_type_returns_none():
    payload = {"NotificationType": "PlaybackStop", "ItemType": "Movie", "SeriesId": "abc"}
    assert parse_jellyfin_episode_payload(payload) is None


def test_episode_payload_missing_series_id_returns_none():
    payload = {"NotificationType": "PlaybackStop", "ItemType": "Episode"}
    assert parse_jellyfin_episode_payload(payload) is None


def test_matches_surprise_show_by_tvdb_id():
    show = SurpriseShow(tvdb_id=12345, title="Breaking Bad")
    surprises_shows = {"12345": show}
    assert matches_surprise_show(12345, surprises_shows) is show


def test_matches_surprise_show_no_match():
    surprises_shows = {"1": SurpriseShow(tvdb_id=1, title="X")}
    assert matches_surprise_show(999, surprises_shows) is None
    assert matches_surprise_show(None, surprises_shows) is None
