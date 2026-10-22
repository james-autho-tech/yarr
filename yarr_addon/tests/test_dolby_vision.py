import pytest

from core.dolby_vision import (BLOCK_SCORE, FORMAT_NAME, find_format_id, is_blocked,
                               is_dv_without_fallback, title_matches, with_block_score)


@pytest.mark.parametrize("title, blocked", [
    ("Show.S01E01.2160p.NF.WEB-DL.DDP5.1.Atmos.DV.H.265-GRP", True),
    ("Movie.2023.2160p.AMZN.WEB-DL.DoVi.H.265-GRP", True),
    ("Movie 2023 2160p Dolby Vision WEB-DL", True),
    ("Movie.2023.2160p.WEB-DL.DV.HDR10.H.265-GRP", False),     # hybrid — has fallback
    ("Movie.2023.2160p.WEB-DL.DV.HDR10Plus.H.265-GRP", False),
    ("Movie.2023.2160p.UHD.BluRay.HDR.x265-GRP", False),        # no DV at all
    ("Movie.2023.1080p.WEB-DL.x264-GRP", False),
    ("DVD.Rip.Movie.2001", False),                               # 'DVD' isn't DV
])
def test_custom_format_matches_only_dv_without_fallback(title, blocked):
    assert title_matches(title) is blocked


def test_with_block_score_updates_existing_or_appends():
    profile = {"minFormatScore": 0, "formatItems": [{"format": 5, "name": FORMAT_NAME, "score": 0}]}
    assert with_block_score(profile, 5)["formatItems"] == [
        {"format": 5, "name": FORMAT_NAME, "score": BLOCK_SCORE}]
    assert profile["formatItems"][0]["score"] == 0  # input untouched
    appended = with_block_score({"minFormatScore": 0}, 9)
    assert appended["formatItems"] == [{"format": 9, "name": FORMAT_NAME, "score": BLOCK_SCORE}]


def test_is_blocked_compares_against_min_format_score():
    profile = {"minFormatScore": 0, "formatItems": [{"format": 5, "score": BLOCK_SCORE}]}
    assert is_blocked(profile, 5)
    assert not is_blocked({"minFormatScore": 0, "formatItems": [{"format": 5, "score": 0}]}, 5)
    assert not is_blocked(profile, None)


def test_find_format_id_and_file_detection():
    assert find_format_id([{"id": 1, "name": "x"}, {"id": 7, "name": FORMAT_NAME}]) == 7
    assert find_format_id([]) is None
    assert is_dv_without_fallback("DV") and is_dv_without_fallback(" dv ")
    for fine in ("DV HDR10", "DV HLG", "DV SDR", "HDR10", "", None):
        assert not is_dv_without_fallback(fine)
