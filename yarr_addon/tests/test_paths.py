import pytest

from core.paths import overlaps, validate_complete_dir

ROOTS = ["/data/media/downloads/tv", "/data/media/downloads/movies"]


def test_overlaps():
    assert overlaps("/data/media/downloads", "/data/media/downloads/tv")      # parent
    assert overlaps("/data/media/downloads/tv/x", "/data/media/downloads/tv")  # child
    assert overlaps("/data/media/downloads/tv/", "/data/media/downloads/tv")   # same
    assert not overlaps("/data/media/downloads-old", "/data/media/downloads")  # prefix, not parent
    assert not overlaps("/data/media/completed", "/data/media/downloads/tv")


def test_validate_complete_dir():
    assert validate_complete_dir("/data/media/completed/", ROOTS) == "/data/media/completed"
    for bad in ("/data/media/downloads", "/data/media/downloads/tv/incoming", "relative/path", ""):
        with pytest.raises(ValueError):
            validate_complete_dir(bad, ROOTS)
