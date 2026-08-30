from core.junk import contains_likely_video, is_junk_dir_name, is_junk_file_name, matches_active_job


def test_unpack_dir_matches():
    assert is_junk_dir_name("_UNPACK_The.Movie.2020.1080p")
    assert is_junk_dir_name("_unpack_lowercase")


def test_failed_dir_matches():
    assert is_junk_dir_name("_FAILED_The.Movie.2020.1080p")


def test_ordinary_dir_does_not_match():
    assert not is_junk_dir_name("The Movie (2020)")
    assert not is_junk_dir_name("Season 04")


def test_rar_and_par2_match():
    assert is_junk_file_name("archive.rar")
    assert is_junk_file_name("archive.r00")
    assert is_junk_file_name("archive.r99")
    assert is_junk_file_name("archive.PAR2")


def test_multipart_rar_naming_matches():
    assert is_junk_file_name("The.Movie.part1.rar")


def test_ordinary_media_file_does_not_match():
    assert not is_junk_file_name("The.Movie.2020.1080p.mkv")
    assert not is_junk_file_name("Season04Episode01.mp4")


def test_matches_active_job_strips_unpack_prefix_and_normalizes():
    assert matches_active_job(
        "_UNPACK_Good Luck Have Fun Dont Die 2026 UHD BluRay",
        ["Good.Luck.Have.Fun.Dont.Die.2026.UHD.BluRay"])


def test_matches_active_job_false_when_no_overlap():
    assert not matches_active_job("_UNPACK_Some Other Show S01E01", ["A.Totally.Different.Movie.2020"])


def test_matches_active_job_false_when_queue_empty():
    assert not matches_active_job("_UNPACK_Anything", [])


def test_matches_active_job_handles_failed_prefix_too():
    assert matches_active_job("_FAILED_Reacher S04E12 2160p AMZN WEB-DL", ["Reacher.S04E12.2160p.AMZN.WEB-DL"])


def test_contains_likely_video_true_for_large_video_file():
    assert contains_likely_video([("Movie.2020.mkv", 4_000_000_000), ("Movie.2020.nfo", 500)])


def test_contains_likely_video_false_when_only_archive_fragments():
    assert not contains_likely_video([("archive.rar", 4_000_000_000), ("archive.r00", 4_000_000_000)])


def test_contains_likely_video_false_when_video_too_small():
    # A tiny .mkv (e.g. a sample or a corrupt partial write) shouldn't
    # be mistaken for a complete, watchable file.
    assert not contains_likely_video([("sample.mkv", 5_000_000)])


def test_contains_likely_video_false_when_empty():
    assert not contains_likely_video([])
