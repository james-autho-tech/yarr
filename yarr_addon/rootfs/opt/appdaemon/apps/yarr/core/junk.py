"""Detects leftover SABnzbd extraction junk sitting in your media
library — pure name/pattern matching only, no filesystem I/O here (the
actual directory walk lives in yarr.py, mirroring core/dupes.py's
adapter/pure split).

Two things this looks for, both pure noise that Radarr/Sonarr never
imported and that Jellyfin can end up showing as bogus library entries
if they sit inside a scanned library path:

- SABnzbd renames a download's working folder to `_UNPACK_<name>`
  during extraction, or `_FAILED_<name>` if extraction errors out, and
  normally cleans up after a successful unpack. A failed or
  interrupted unpack can leave that folder behind indefinitely.
- Stray raw archive pieces (.rar/.r00-r99/.par2) that never actually
  got extracted into a usable file at all — same root cause, different
  shape.
"""

import re

UNPACK_DIR_PREFIXES = ("_unpack_", "_failed_")

_ARCHIVE_PART_RE = re.compile(r"\.(par2|rar|r\d{2})$", re.IGNORECASE)
_UNPACK_PREFIX_RE = re.compile(r"^_(unpack|failed)_", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def is_junk_dir_name(name: str) -> bool:
    return name.lower().startswith(UNPACK_DIR_PREFIXES)


def is_junk_file_name(name: str) -> bool:
    return bool(_ARCHIVE_PART_RE.search(name))


def _normalize(s: str) -> str:
    return _NON_ALNUM_RE.sub("", s.lower())


def matches_active_job(candidate_name: str, active_job_names) -> bool:
    """True if a junk candidate's name (an _UNPACK_/_FAILED_ folder, or
    a stray archive file) looks like it belongs to a job SABnzbd's own
    live queue still considers active — downloading, paused, or stuck
    mid-repair/extraction (which can legitimately sit untouched for a
    long time waiting on slow par2 blocks, well past any reasonable
    age cutoff, without actually being abandoned). File-age alone can't
    tell an active job apart from a truly abandoned one, which is
    exactly the gap that let a real, wanted download get swept up as
    "junk" and deleted — this checks the thing that actually knows:
    SABnzbd itself.

    Matched loosely (normalized, substring either direction) since
    SABnzbd's display name and the on-disk folder name are usually the
    same release name but not always byte-identical (category
    prefixes, sanitized punctuation)."""
    candidate = _normalize(_UNPACK_PREFIX_RE.sub("", candidate_name))
    if not candidate:
        return False
    for name in active_job_names:
        norm = _normalize(name)
        if norm and (norm in candidate or candidate in norm):
            return True
    return False


VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts", ".m2ts", ".webm")


def contains_likely_video(file_sizes, min_video_bytes: int = 100_000_000) -> bool:
    """True if any (name, size) pair in this folder looks like a real,
    substantially-complete video file rather than an archive fragment.
    A folder can end up sitting under an _UNPACK_ name with a fully
    extracted, watchable video already inside it — something
    interrupted just the final rename/import step, not the extraction
    itself — and that is not leftover junk at all, it's unimported
    content that needs a human to look at it, not a delete."""
    for name, size in file_sizes:
        if size >= min_video_bytes and name.lower().endswith(VIDEO_EXTENSIONS):
            return True
    return False
