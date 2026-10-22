"""Folder-overlap check for moving SABnzbd's completed-download folder —
pure posixpath logic, no I/O."""

import posixpath


def _norm(path: str) -> str:
    return posixpath.normpath(path or "/")


def overlaps(a: str, b: str) -> bool:
    """True if a and b are the same folder or either contains the other."""
    a, b = _norm(a), _norm(b)
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


def validate_complete_dir(path: str, library_roots) -> str:
    """Returns the normalized folder, or raises ValueError. SABnzbd's
    completed folder must be absolute and must not overlap any
    Radarr/Sonarr library root — overlapping is exactly what makes
    half-finished unpacks show up in the library (and in Jellyfin)."""
    if not path or not posixpath.isabs(path):
        raise ValueError("Completed folder must be an absolute path.")
    clash = [r for r in library_roots if r and overlaps(path, r)]
    if clash:
        raise ValueError(f"{path!r} overlaps library folder(s) {clash} — pick a folder outside them.")
    return _norm(path)
