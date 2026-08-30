from core.dupes import MediaFile, find_duplicate_groups, files_to_delete, wasted_bytes


def test_finds_group_with_matching_size():
    files = [
        MediaFile("/media/movies/A/film.mkv", 4_000_000_000),
        MediaFile("/media/movies/A (copy)/film.mkv", 4_000_000_000),
        MediaFile("/media/movies/B/other.mkv", 2_000_000_000),
    ]
    groups = find_duplicate_groups(files, min_size_bytes=50_000_000)
    assert len(groups) == 1
    assert {f.path for f in groups[0]} == {
        "/media/movies/A/film.mkv", "/media/movies/A (copy)/film.mkv"}


def test_no_groups_when_all_sizes_unique():
    files = [MediaFile(f"/media/{i}.mkv", i * 1_000_000_000) for i in range(1, 4)]
    assert find_duplicate_groups(files, min_size_bytes=50_000_000) == []


def test_small_files_ignored_below_min_size():
    files = [
        MediaFile("/media/sample1.mkv", 1_000_000),
        MediaFile("/media/sample2.mkv", 1_000_000),
    ]
    assert find_duplicate_groups(files, min_size_bytes=50_000_000) == []


def test_three_way_duplicate_group():
    files = [MediaFile(f"/media/copy{i}.mkv", 3_000_000_000) for i in range(3)]
    groups = find_duplicate_groups(files, min_size_bytes=50_000_000)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_wasted_bytes_counts_all_but_one_per_group():
    groups = [
        [MediaFile("a", 4_000_000_000), MediaFile("b", 4_000_000_000)],
        [MediaFile("c", 1_000_000_000), MediaFile("d", 1_000_000_000), MediaFile("e", 1_000_000_000)],
    ]
    assert wasted_bytes(groups) == 4_000_000_000 + 2_000_000_000


def test_wasted_bytes_empty_groups():
    assert wasted_bytes([]) == 0


def test_files_to_delete_keeps_the_one_tracked_basename():
    group = [{"path": "/media/a.mkv", "size": 1}, {"path": "/media/b.mkv", "size": 1}]
    result = files_to_delete(group, tracked_basenames={"a.mkv"})
    assert result == [{"path": "/media/b.mkv", "size": 1}]


def test_files_to_delete_matches_across_different_mount_prefixes():
    # Radarr/Sonarr see the file via their own container's mount
    # (/data/...), yArr sees the identical physical file via Home
    # Assistant's /media share — different full paths, same basename.
    group = [
        {"path": "/media/unas_pro/downloads/tv/Show/S01E01.mkv", "size": 1},
        {"path": "/media/unas_pro/downloads/tv/Show/S01E01 (copy).mkv", "size": 1},
    ]
    result = files_to_delete(group, tracked_basenames={"S01E01.mkv"})
    assert result == [{"path": "/media/unas_pro/downloads/tv/Show/S01E01 (copy).mkv", "size": 1}]


def test_files_to_delete_skips_group_when_nothing_tracked():
    group = [{"path": "/media/a.mkv", "size": 1}, {"path": "/media/b.mkv", "size": 1}]
    assert files_to_delete(group, tracked_basenames=set()) == []


def test_files_to_delete_skips_group_when_multiple_tracked():
    group = [{"path": "/media/a.mkv", "size": 1}, {"path": "/media/b.mkv", "size": 1}]
    assert files_to_delete(group, tracked_basenames={"a.mkv", "b.mkv"}) == []
