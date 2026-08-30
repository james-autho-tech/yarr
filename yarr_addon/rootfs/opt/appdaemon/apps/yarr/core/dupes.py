"""Duplicate-media detection — pure, no filesystem I/O here (the actual
directory walk lives in yarr.py, which hands this module a plain list
of files to reason about, mirroring core/'s general adapter/pure split).

Detection signal: exact file size. For real-world video files above a
sane size floor (default 50MB, well past trailers/samples/subtitles),
two files sharing an identical byte count is an extremely strong
duplicate signal on its own — a full-content hash would be more
rigorous but means reading every byte of a whole media library, which
is far too slow to run regularly. Report-only by design: this never
deletes anything, only groups candidates for a human to review.
"""

import posixpath
from dataclasses import dataclass


@dataclass(frozen=True)
class MediaFile:
    path: str
    size: int


def find_duplicate_groups(files, min_size_bytes: int = 50_000_000) -> list:
    """Returns a list of groups (each a list of MediaFile, len >= 2)
    sharing an identical size at or above min_size_bytes. Order of
    groups and of files within a group follows first-seen order in
    `files`, for stable, deterministic output."""
    by_size = {}
    for f in files:
        if f.size < min_size_bytes:
            continue
        by_size.setdefault(f.size, []).append(f)
    return [group for group in by_size.values() if len(group) > 1]


def wasted_bytes(groups) -> int:
    """Every file in a group shares the same size by construction —
    "wasted" is all but one copy per group."""
    return sum(group[0].size * (len(group) - 1) for group in groups)


def files_to_delete(group, tracked_basenames) -> list:
    """Given a duplicate group (list of {"path", "size"} dicts, as
    persisted in state) and the set of file BASENAMES Radarr/Sonarr
    actually track, returns the ones to delete — everything in the
    group except the single tracked copy. Deliberately returns an
    empty list (leave the group for manual review) unless EXACTLY one
    file in the group is tracked: guessing when zero or more than one
    match would risk deleting the wrong copy, or the only copy.

    Matches on basename, not the full path: Radarr/Sonarr and yArr
    routinely see the same physical file through different mount
    prefixes (e.g. Radarr's own Docker container mounts it at
    /data/media/..., while yArr sees it via Home Assistant's /media
    share) — comparing full paths would never match in that (normal,
    not edge-case) setup, silently leaving every group "ambiguous"
    forever. The filename itself is identical either way."""
    tracked_in_group = [f for f in group if posixpath.basename(f["path"]) in tracked_basenames]
    if len(tracked_in_group) != 1:
        return []
    tracked_path = tracked_in_group[0]["path"]
    return [f for f in group if f["path"] != tracked_path]
