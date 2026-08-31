from core.taste import WatchedItem, library_items_as_watched, top_genres


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


def test_top_genres_excludes_even_if_most_watched():
    items = [
        WatchedItem(genres=["horror"]),
        WatchedItem(genres=["horror"]),
        WatchedItem(genres=["horror"]),
        WatchedItem(genres=["comedy"]),
    ]
    result = top_genres(items, top_n=5, exclude=["horror"])
    assert "horror" not in result
    assert result == ["comedy"]


def test_top_genres_exclude_is_case_insensitive():
    items = [WatchedItem(genres=["Horror"]), WatchedItem(genres=["comedy"])]
    result = top_genres(items, top_n=5, exclude=["horror"])
    assert result == ["comedy"]


def test_library_items_as_watched_carries_genres_with_no_bonus():
    rows = [{"genres": ["Action", "Comedy"]}, {"genres": ["Drama"]}]
    items = library_items_as_watched(rows)
    assert items[0].genres == ["Action", "Comedy"]
    assert items[0].play_count == 0
    assert items[0].is_favorite is False


def test_library_items_as_watched_handles_missing_genres_key():
    assert library_items_as_watched([{}])[0].genres == []


def test_library_items_as_watched_blends_with_real_watched_items():
    # A merely-owned title (library only) should rank below one that's
    # both owned AND watched, since the watched one contributes to both
    # the library-baseline pass and the real-watched-item pass.
    library_rows = [{"genres": ["comedy"]}, {"genres": ["drama"]}]
    watched = [WatchedItem(genres=["drama"], play_count=5)]
    combined = library_items_as_watched(library_rows) + watched
    assert top_genres(combined, top_n=1) == ["drama"]
