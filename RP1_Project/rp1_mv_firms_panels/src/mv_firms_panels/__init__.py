# file: src/mv_firms_panels/__init__.py
"""mv_firms_panels.

Audit-grade, deterministic processing of NASA FIRMS active-fire detections (VIIRS + MODIS)
into balanced monthly polygon panels.

This package is designed to be:
- scientifically explicit (assumptions are configurable and documented),
- deterministic (stable sorts, fixed column order, explicit dedup keys),
- schema-governed (JSON schema contracts for tabular artefacts).
"""

from .version import __version__

__all__ = ["__version__"]
