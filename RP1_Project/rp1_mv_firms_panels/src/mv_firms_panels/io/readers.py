# file: src/mv_firms_panels/io/readers.py
"""Vector readers (points/polygons) with strict, audit-grade defaults.

Goals
-----
- Prefer fast open-source engines where available (pyogrio), but *do not* require them.
- Fail fast on missing files.
- Preserve CRS, and optionally enforce expected geometry types.
- Keep behaviour deterministic (no implicit column renaming).

This module does not implement FIRMS column mapping; that is handled by the
sensor adapters in mv_firms_panels.sensors.*.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd


class ReadError(ValueError):
    """Raised when a vector read fails."""


def _read_file(path: Path, *, layer: str | None = None) -> gpd.GeoDataFrame:
    if not path.exists():
        raise ReadError(f"Input file not found: {path}")
    try:
        import pyogrio  # noqa: F401

        return gpd.read_file(path, layer=layer, engine="pyogrio")
    except Exception:
        return gpd.read_file(path, layer=layer)


def read_points(
    path: str | Path,
    *,
    layer: str | None = None,
    columns: Sequence[str] | None = None,
) -> gpd.GeoDataFrame:
    """Read point detections as a GeoDataFrame."""
    gdf = _read_file(Path(path), layer=layer)
    if columns is not None:
        missing = [c for c in columns if c not in gdf.columns]
        if missing:
            raise ReadError(f"Requested columns missing in points: {missing}")
        gdf = gdf.loc[:, list(columns) + [gdf.geometry.name]].copy()
    if len(gdf) > 0:
        g0 = gdf.geometry.iloc[0]
        if g0 is not None and g0.geom_type != "Point":
            raise ReadError(f"Expected Point geometries for points; got {g0.geom_type!r}")
    return gdf


def read_polygons(
    path: str | Path,
    *,
    layer: str | None = None,
    columns: Sequence[str] | None = None,
    allow_empty: bool = False,
) -> gpd.GeoDataFrame:
    """Read polygon boundaries as a GeoDataFrame."""
    gdf = _read_file(Path(path), layer=layer)
    if not allow_empty and len(gdf) == 0:
        raise ReadError(f"Polygon file is empty: {path}")
    if columns is not None:
        missing = [c for c in columns if c not in gdf.columns]
        if missing:
            raise ReadError(f"Requested columns missing in polygons: {missing}")
        gdf = gdf.loc[:, list(columns) + [gdf.geometry.name]].copy()
    if len(gdf) > 0:
        g0 = gdf.geometry.iloc[0]
        if g0 is not None and g0.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ReadError(f"Expected Polygon/MultiPolygon geometries; got {g0.geom_type!r}")
    return gdf
