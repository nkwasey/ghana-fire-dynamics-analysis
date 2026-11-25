"""Validation for provenance-only paths, which are never used for file access."""
from pathlib import PurePosixPath, PureWindowsPath


def valid_origin_path(value: object) -> bool:
    """Accept relative POSIX or absolute POSIX/Windows paths without traversal."""
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    if any(ord(char) < 32 for char in value):
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if ".." in posix.parts or value in (".", "/"):
        return False
    # Reject Windows drive-relative paths; absolute Windows paths use forward slashes.
    if windows.drive and not windows.is_absolute():
        return False
    return True
