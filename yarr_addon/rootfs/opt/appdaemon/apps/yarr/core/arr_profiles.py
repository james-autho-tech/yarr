"""Quality profile shaping for the Profiles tab — pure functions only,
no network I/O (clients/radarr.py and clients/sonarr.py do the actual
GET/PUT). Radarr and Sonarr share the same QualityProfile resource
shape, so everything here works for both.

A profile's `items` list is ordered lowest quality first, and each
entry is either a single quality ({"quality": {"id", "name"},
"items": [], "allowed"}) or a named group of qualities treated as
equal ({"id", "name", "items": [...], "allowed"}). Radarr/Sonarr's own
`cutoff` refers to a single quality's quality.id or a group's own id —
that same id is used as each entry's `key` here.

Edits are always applied to a deep copy of the full profile object as
Radarr/Sonarr returned it, never rebuilt from the summary, so fields
yArr doesn't model (custom format scores, minFormatScore, language,
...) are sent back exactly as they were instead of being reset."""

import copy


class ProfileEditError(ValueError):
    pass


def _item_key(item):
    if item.get("items"):
        return item.get("id")
    return (item.get("quality") or {}).get("id")


def _item_name(item):
    if item.get("items"):
        return item.get("name") or "Group"
    return (item.get("quality") or {}).get("name") or "Unknown"


def summarize_profile(profile: dict) -> dict:
    """-> {id, name, upgrade_allowed, cutoff, qualities: [{key, name,
    allowed, group}]}, qualities ordered highest first — the same order
    Radarr/Sonarr's own profile editor shows them in."""
    qualities = []
    for item in reversed(profile.get("items") or []):
        key = _item_key(item)
        if key is None:
            continue
        qualities.append({
            "key": key, "name": _item_name(item),
            "allowed": bool(item.get("allowed", False)),
            "group": [(sub.get("quality") or {}).get("name") for sub in item.get("items") or []],
        })
    return {
        "id": profile.get("id"), "name": profile.get("name", ""),
        "upgrade_allowed": bool(profile.get("upgradeAllowed", False)),
        "cutoff": profile.get("cutoff"), "qualities": qualities,
    }


def apply_profile_edit(profile: dict, *, name: str, upgrade_allowed: bool,
                       cutoff, allowed_keys) -> dict:
    """Returns an edited deep copy of `profile`. Raises ProfileEditError
    for anything Radarr/Sonarr would reject anyway (or silently accept
    into a broken state), so the user gets a clear reason in the Log
    instead of a raw HTTP 400 body."""
    name = (name or "").strip()
    if not name:
        raise ProfileEditError("Profile name can't be empty.")
    known = {_item_key(i) for i in profile.get("items") or []} - {None}
    allowed = set(allowed_keys or [])
    unknown = allowed - known
    if unknown:
        raise ProfileEditError(f"Unknown quality id(s) {sorted(unknown)} for this profile.")
    if not allowed:
        raise ProfileEditError("At least one quality must be allowed.")
    if cutoff not in allowed:
        raise ProfileEditError("The cutoff ('upgrade until') must be one of the allowed qualities.")

    edited = copy.deepcopy(profile)
    edited["name"] = name
    edited["upgradeAllowed"] = bool(upgrade_allowed)
    edited["cutoff"] = cutoff
    for item in edited.get("items") or []:
        on = _item_key(item) in allowed
        item["allowed"] = on
        # Radarr/Sonarr's own UI flips a group's members along with
        # the group itself — mirror that so the saved profile looks
        # identical to one edited there.
        for sub in item.get("items") or []:
            sub["allowed"] = on
    return edited


def clone_profile(profile: dict, new_name: str) -> dict:
    """A copy of `profile` ready to POST as a new profile — same
    qualities, cutoff and custom format scores, new name, no id."""
    new_name = (new_name or "").strip()
    if not new_name:
        raise ProfileEditError("New profile name can't be empty.")
    cloned = copy.deepcopy(profile)
    cloned.pop("id", None)
    cloned["name"] = new_name
    return cloned
