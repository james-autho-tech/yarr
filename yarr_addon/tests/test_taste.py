from core.taste import WatchedItem, top_genres


def test_top_genres_ranks_by_frequency():
    items = [
        WatchedItem(genres=["drama"]),
        WatchedItem(genres=["drama"]),
        WatchedItem(genres=["comedy"]),
    ]
    assert top_genres(items, top_n=1) == ["drama"]


def test_top_genres_weights_by_play_count():
    items = [
        WatchedItem(genres=["comedy"], play_count=0),
        WatchedItem(genres=["drama"], play_count=20),
    ]
    assert top_genres(items, top_n=1) == ["drama"]


def test_top_genres_favorite_bonus_can_outweigh_frequency():
    items = [
        WatchedItem(genres=["comedy"]),
        WatchedItem(genres=["comedy"]),
        WatchedItem(genres=["drama"], is_favorite=True),
    ]
    assert top_genres(items, top_n=1, favorite_bonus=5.0) == ["drama"]


def test_top_genres_empty_input_returns_empty():
    assert top_genres([], top_n=5) == []


def test_top_genres_case_insensitive_and_multi_genre_items():
    items = [
        WatchedItem(genres=["Drama", "Thriller"]),
        WatchedItem(genres=["drama"]),
    ]
    result = top_genres(items, top_n=2)
    assert result[0] == "drama"
    assert "thriller" in result
