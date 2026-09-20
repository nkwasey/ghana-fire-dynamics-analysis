# file: src/mv_firms_panels/geo/crs.py
"""CRS utilities for audit-grade geospatial processing.

This project must behave deterministically across platforms and avoid silent CRS
mismatches. These helpers provide:
- Fail-fast checks for missing/invalid CRS
- Explicit alignment of GeoDataFrames to a target CRS
- A deterministic 'area CRS' selection for tie-breaks (e.g. overlapping polygons)

Notes on scientific robustness
------------------------------
Spatial joins and mask filters are *topological* operations. They are valid in
either geographic or projected CRSs, but *area-based* tie-breaks are not.
Therefore, when resolving ambiguous matches (overlaps), we compute polygon
areas in an explicit projected CRS chosen deterministically from geometry
bounds (local UTM where possible; otherwise a global equal-area fallback).

All functions here are pure (no IO).
"""

from __future__ import annotations

import geopandas as gpd
from pyproj import CRS


class CRSAlignmentError(ValueError):
    """Raised when CRS alignment cannot be performed safely."""


def require_crs(gdf: gpd.GeoDataFrame, *, name: str) -> CRS:
    """Return CRS as a pyproj.CRS, or raise if missing/invalid."""
    if gdf.crs is None:
        raise CRSAlignmentError(f"{name} has no CRS set (gdf.crs is None)")
    try:
        return CRS.from_user_input(gdf.crs)
    except Exception as e:  # pragma: no cover
        raise CRSAlignmentError(f"{name} has invalid CRS: {gdf.crs!r}") from e


def align_to_crs(
    gdf: gpd.GeoDataFrame,
    *,
    target_crs: CRS,
    name: str,
) -> gpd.GeoDataFrame:
    """Reproject GeoDataFrame to target_crs, failing fast if CRS is missing."""
    _ = require_crs(gdf, name=name)
    if CRS.from_user_input(gdf.crs) == target_crs:
        return gdf.copy()
    try:
        return gdf.to_crs(target_crs).copy()
    except Exception as e:
        raise CRSAlignmentError(
            f"Failed to reproject {name} from {gdf.crs!r} to {target_crs.to_string()!r}"
        ) from e


def _utm_epsg_for_lon_lat(lon: float, lat: float) -> int | None:
    """Deterministically pick a UTM EPSG code from a lon/lat point.

    Returns None if latitude is outside UTM coverage.
    """
    if lat < -80.0 or lat > 84.0:
        return None
    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(zone, 60))
    if lat >= 0:
        return 32600 + zone  # WGS84 / UTM Northern Hemisphere
    return 32700 + zone  # WGS84 / UTM Southern Hemisphere


def choose_area_crs_from_bounds(
    *,
    bounds_wgs84: tuple[float, float, float, float],
) -> CRS:
    """Choose an explicit projected CRS for area computations.

    Strategy (deterministic):
    - Convert bounds centroid to a UTM zone (WGS84) if within UTM coverage.
    - Otherwise fall back to a global equal-area CRS (EPSG:6933).
    """
    minx, miny, maxx, maxy = bounds_wgs84
    lon = (minx + maxx) / 2.0
    lat = (miny + maxy) / 2.0
    epsg = _utm_epsg_for_lon_lat(lon, lat)
    if epsg is not None:
        return CRS.from_epsg(epsg)
    # WGS 84 / NSIDC EASE-Grid 2.0 Global (equal-area)
    return CRS.from_epsg(6933)


def ensure_common_crs(
    *,
    points: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
    prefer: str = "polygons",
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, CRS]:
    """Align points and polygons to a common CRS.

    prefer:
      - "polygons": use polygons CRS as target and reproject points
      - "points": use points CRS as target and reproject polygons

    Returns (points_aligned, polygons_aligned, target_crs).
    """
    p_crs = require_crs(points, name="points")
    g_crs = require_crs(polygons, name="polygons")

    if prefer not in {"polygons", "points"}:
        raise ValueError("prefer must be one of {'polygons','points'}")

    target = g_crs if prefer == "polygons" else p_crs
    points2 = align_to_crs(points, target_crs=target, name="points")
    polys2 = align_to_crs(polygons, target_crs=target, name="polygons")
    return points2, polys2, target
