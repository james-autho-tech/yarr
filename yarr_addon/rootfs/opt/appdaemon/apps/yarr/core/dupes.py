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
