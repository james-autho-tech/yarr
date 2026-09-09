from core.calendar import merge_calendar_entries


def make_movie(date="2026-09-10", title="Some Movie", release_type="In Cinemas", has_file=False):
    return {"date": date, "title": title, "release_type": release_type, "has_file": has_file}


def make_episode(date="2026-09-10", series_title="Some Show", episode_title="Pilot",
                  season_number=1, episode_number=1, has_file=False):
    return {"date": date, "series_title": series_title, "episode_title": episode_title,
            "season_number": season_number, "episode_number": episode_number, "has_file": has_file}


def test_merges_movies_and_episodes():
    entries = merge_calendar_entries([make_movie()], [make_episode()])
    assert len(entries) == 2
    types = {e["type"] for e in entries}
    assert types == {"movie", "episode"}


def test_sorts_by_date():
    entries = merge_calendar_entries(
        [make_movie(date="2026-09-15", title="Later Movie")],
        [make_episode(date="2026-09-05", series_title="Earlier Show")])
    assert [e["title"] for e in entries] == ["Earlier Show", "Later Movie"]


def test_movie_entry_shape():
    entries = merge_calendar_entries([make_movie(title="Dune", release_type="Digital Release",
                                                  has_file=True)], [])
    assert entries[0]["title"] == "Dune"
    assert entries[0]["subtitle"] == "Digital Release"
    assert entries[0]["available"] is True
    assert entries[0]["type"] == "movie"


def test_episode_subtitle_includes_episode_title():
    entries = merge_calendar_entries([], [make_episode(
        series_title="Monk", episode_title="Mr. Monk Buys a House", season_number=7, episode_number=1)])
    assert entries[0]["title"] == "Monk"
    assert entries[0]["subtitle"] == "S07E01 — Mr. Monk Buys a House"
    assert entries[0]["type"] == "episode"


def test_episode_subtitle_omits_dash_when_no_episode_title():
    entries = merge_calendar_entries([], [make_episode(episode_title="", season_number=2, episode_number=3)])
    assert entries[0]["subtitle"] == "S02E03"


def test_episode_available_field_preserved():
    entries = merge_calendar_entries([], [make_episode(has_file=True)])
    assert entries[0]["available"] is True


def test_empty_lists_return_empty():
    assert merge_calendar_entries([], []) == []
