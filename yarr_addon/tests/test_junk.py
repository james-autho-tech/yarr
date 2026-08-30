from core.junk import is_junk_dir_name, is_junk_file_name


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
