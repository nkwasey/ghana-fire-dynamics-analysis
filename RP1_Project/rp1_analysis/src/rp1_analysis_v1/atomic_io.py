"""Standard-library atomic file publication without replacing a destination."""
from __future__ import annotations

import os
from pathlib import Path


def publish_file_no_replace(staging: Path, destination: Path) -> None:
    """Publish complete same-filesystem staging bytes, refusing any collision.

    The caller must close/flush staging first and clean it up afterwards. Windows
    rename consumes staging and atomically refuses an existing destination;
    POSIX hard-link publication preserves staging and atomically refuses one.
    POSIX rename cannot be substituted because it may replace another writer's
    destination. No permission-error fallback weakens these guarantees.
    """
    if os.name == "nt":
        os.rename(staging, destination)
    else:
        os.link(staging, destination)
