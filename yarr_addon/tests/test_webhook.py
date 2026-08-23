from core.webhook import parse_jellyfin_payload, matches_surprise
from core.state import SurpriseFilm


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
