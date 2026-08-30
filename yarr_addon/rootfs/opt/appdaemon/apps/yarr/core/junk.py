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


def is_junk_dir_name(name: str) -> bool:
    return name.lower().startswith(UNPACK_DIR_PREFIXES)


def is_junk_file_name(name: str) -> bool:
    return bool(_ARCHIVE_PART_RE.search(name))
