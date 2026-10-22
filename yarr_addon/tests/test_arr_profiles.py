import pytest

from core.arr_profiles import ProfileEditError, apply_profile_edit, clone_profile, summarize_profile


def make_profile():
    # Shape as returned by Radarr/Sonarr's GET /qualityprofile/{id}:
    # lowest quality first, one group, plus fields yArr doesn't model.
    return {
        "id": 4, "name": "HD-1080p", "upgradeAllowed": False, "cutoff": 7,
        "minFormatScore": 0, "formatItems": [{"format": 1, "score": 50}],
        "items": [
            {"quality": {"id": 1, "name": "SDTV"}, "items": [], "allowed": False},
            {"id": 1000, "name": "WEB 1080p", "allowed": True, "items": [
                {"quality": {"id": 3, "name": "WEBDL-1080p"}, "items": [], "allowed": True},
                {"quality": {"id": 15, "name": "WEBRip-1080p"}, "items": [], "allowed": True},
            ]},
            {"quality": {"id": 7, "name": "Bluray-1080p"}, "items": [], "allowed": True},
            {"quality": {"id": 19, "name": "Bluray-2160p"}, "items": [], "allowed": False},
        ],
    }


def test_summarize_orders_highest_first_and_keys_groups_by_group_id():
    s = summarize_profile(make_profile())
    assert [q["key"] for q in s["qualities"]] == [19, 7, 1000, 1]
    assert s["qualities"][2]["name"] == "WEB 1080p"
    assert s["qualities"][2]["group"] == ["WEBDL-1080p", "WEBRip-1080p"]
    assert s["cutoff"] == 7 and s["upgrade_allowed"] is False


def test_apply_edit_sets_flags_and_preserves_unmodelled_fields():
    original = make_profile()
    edited = apply_profile_edit(original, name="4K", upgrade_allowed=True,
                                cutoff=19, allowed_keys=[19, 7])
    assert edited["name"] == "4K" and edited["upgradeAllowed"] is True and edited["cutoff"] == 19
    assert [i["allowed"] for i in edited["items"]] == [False, False, True, True]
    # Group members follow the group.
    assert all(sub["allowed"] is False for sub in edited["items"][1]["items"])
    assert edited["formatItems"] == [{"format": 1, "score": 50}]
    # Never mutates the input.
    assert original["name"] == "HD-1080p" and original["items"][1]["allowed"] is True


@pytest.mark.parametrize("kwargs, msg", [
    ({"name": " ", "cutoff": 7, "allowed_keys": [7]}, "empty"),
    ({"name": "x", "cutoff": 7, "allowed_keys": []}, "At least one"),
    ({"name": "x", "cutoff": 19, "allowed_keys": [7]}, "cutoff"),
    ({"name": "x", "cutoff": 7, "allowed_keys": [7, 999]}, "Unknown"),
])
def test_apply_edit_rejects_invalid(kwargs, msg):
    with pytest.raises(ProfileEditError, match=msg):
        apply_profile_edit(make_profile(), upgrade_allowed=False, **kwargs)


def test_clone_drops_id_and_renames():
    c = clone_profile(make_profile(), "  HD copy ")
    assert "id" not in c and c["name"] == "HD copy"
    assert c["formatItems"] == [{"format": 1, "score": 50}]
    with pytest.raises(ProfileEditError):
        clone_profile(make_profile(), "")
