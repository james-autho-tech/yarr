"""Dolby Vision without an HDR fallback ("purple picture") — pure
functions only; the Radarr/Sonarr calls live in yarr.py/clients.

Dolby Vision profile 5 (common on streaming WEB-DLs) has no HDR10 base
layer. A player or Jellyfin client that can't decode Dolby Vision itself,
with no hardware tone mapping on the server to transcode it, shows the
raw stream with a purple/green cast. Profile 8 files carry an HDR10 (or
HLG/SDR) base layer and fall back to that instead, so they play fine.

Two halves:
- Block future grabs: a Radarr/Sonarr custom format matching DV release
  titles that don't also advertise HDR10/HLG, scored far below any
  profile's minimum so those releases are rejected outright.
- Find existing files: Radarr/Sonarr's own media info reports
  videoDynamicRangeType "DV" (alone) for exactly these files, versus
  "DV HDR10"/"DV HLG"/"DV SDR" for ones with a fallback layer."""

import copy
import re

FORMAT_NAME = "yArr: Dolby Vision without HDR fallback"
BLOCK_SCORE = -10000

# Release-title regexes (.NET flavour, case-insensitive in Radarr/Sonarr).
_DV_RE = r"\b(DV|DoVi|Dolby[ ._-]?Vision)\b"
_FALLBACK_RE = r"\b(HDR(10)?(\+|P(lus)?)?|HLG)\b"


def block_custom_format() -> dict:
    """The custom format POSTed to Radarr's/Sonarr's /customformat —
    both required: the title says Dolby Vision, AND it does not also
    say HDR10/HDR10+/HLG (a hybrid release with a fallback layer)."""
    return {
        "name": FORMAT_NAME,
        "includeCustomFormatWhenRenaming": False,
        "specifications": [
            {"name": "Dolby Vision", "implementation": "ReleaseTitleSpecification",
             "negate": False, "required": True,
             "fields": [{"name": "value", "value": _DV_RE}]},
            {"name": "No HDR10/HLG fallback", "implementation": "ReleaseTitleSpecification",
             "negate": True, "required": True,
             "fields": [{"name": "value", "value": _FALLBACK_RE}]},
        ],
    }


def title_matches(title) -> bool:
    """Python-side evaluation of block_custom_format() against a release
    title, the way Radarr/Sonarr evaluate it (every spec is required; a
    negated spec must NOT match) — used to find already-queued releases
    the new rule would have rejected."""
    for spec in block_custom_format()["specifications"]:
        hit = re.search(spec["fields"][0]["value"], title or "", re.IGNORECASE) is not None
        if hit == spec["negate"]:
            return False
    return True


def find_format_id(custom_formats) -> int:
    return next((f.get("id") for f in custom_formats or [] if f.get("name") == FORMAT_NAME), None)


def format_score(profile: dict, format_id) -> int:
    return next((fi.get("score", 0) for fi in profile.get("formatItems") or []
                 if fi.get("format") == format_id), 0)


def is_blocked(profile: dict, format_id) -> bool:
    """A release scoring BLOCK_SCORE always falls below the profile's
    minimum custom format score, so Radarr/Sonarr reject it."""
    return format_id is not None and format_score(profile, format_id) < profile.get("minFormatScore", 0)


def with_block_score(profile: dict, format_id: int) -> dict:
    """Edited deep copy of `profile` with the DV format scored
    BLOCK_SCORE — adds the formatItems entry if Radarr/Sonarr hasn't
    listed it yet (a just-created format can be missing until the
    profile is next saved)."""
    edited = copy.deepcopy(profile)
    items = edited.setdefault("formatItems", [])
    for fi in items:
        if fi.get("format") == format_id:
            fi["score"] = BLOCK_SCORE
            break
    else:
        items.append({"format": format_id, "name": FORMAT_NAME, "score": BLOCK_SCORE})
    return edited


def is_dv_without_fallback(dynamic_range_type) -> bool:
    """Radarr/Sonarr report "DV" alone only when there's no HDR10/HLG/
    SDR base layer to fall back to — "DV HDR10" etc. play fine."""
    return (dynamic_range_type or "").strip().upper() == "DV"
