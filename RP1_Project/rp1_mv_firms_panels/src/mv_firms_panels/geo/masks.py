# file: src/mv_firms_panels/geo/masks.py
"""Land-mask filtering and related helpers.

This module implements an optional 'land mask' step:
- Points that do not intersect the land-mask polygons are flagged as outside-land.
- The predicate is configurable, but the default (intersects) treats boundary
  points as inside-land, which is conservative for QA.

Implementation detail:
- We avoid geopandas.sjoin() to remove optional dependencies (rtree/pygeos).
  Instead we use shapely's STRtree for spatial indexing.

STRtree result normalisation:
- Shapely STRtree.query() returns *indices* in Shapely 2.x, but may return
  geometries in some supported stacks. We normalise candidates to geometries.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from mv_firms_panels.geo.crs import ensure_common_crs


class LandMaskError(ValueError):
    """Raised when land-mask filtering cannot be performed safely."""


def _require_point_geometries(points: gpd.GeoDataFrame) -> None:
    if points.geometry is None:
        raise LandMaskError("points GeoDataFrame has no active geometry column")
    if len(points) > 0:
        geom0 = points.geometry.iloc[0]
        if geom0 is not None and geom0.geom_type != "Point":
            raise LandMaskError(f"Expected point geometries; got {geom0.geom_type!r}")


def _build_strtree(polys: gpd.GeoDataFrame) -> tuple[STRtree, list[BaseGeometry]]:
    geoms = list(polys.geometry)
    if any(g is None for g in geoms):
        raise LandMaskError("land-mask polygons contain null geometries")
    return STRtree(geoms), geoms


def _iter_candidate_geometries(
    *,
    candidates,
    geoms: list[BaseGeometry],
):
    """Yield candidate geometries from STRtree.query output."""
    for cand in candidates:
        if isinstance(cand, (int, np.integer)):
            yield geoms[int(cand)]
        else:
            # Shapely 1.x may return geometry objects directly
            yield cand


def split_points_by_land_mask(
    *,
    points: gpd.GeoDataFrame,
    land_mask: gpd.GeoDataFrame,
    predicate: str = "intersects",
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict[str, float]]:
    """Split points into inside-land and outside-land sets.

    Returns (inside_points, outside_points, stats_dict).

    Stats include:
    - n_points
    - n_inside
    - n_outside
    - outside_rate
    """
    if predicate not in {"intersects", "within"}:
        raise ValueError("predicate must be one of {'intersects','within'}")

    _require_point_geometries(points)

    pts, land, _ = ensure_common_crs(points=points, polygons=land_mask, prefer="polygons")
    land = land.reset_index(drop=True).copy()

    if len(land) == 0:
        raise LandMaskError("land_mask is empty (0 features)")

    tree, geoms = _build_strtree(land)

    inside_flags: list[bool] = []
    for geom in pts.geometry:
        if geom is None:
            inside_flags.append(False)
            continue

        candidates = tree.query(geom)
        ok = False
        for cand_geom in _iter_candidate_geometries(candidates=candidates, geoms=geoms):
            if predicate == "intersects":
                if geom.intersects(cand_geom):
                    ok = True
                    break
            else:  # within
                if geom.within(cand_geom):
                    ok = True
                    break
        inside_flags.append(ok)

    inside = pts.loc[inside_flags].copy()
    outside = pts.loc[[not b for b in inside_flags]].copy()

    n = float(len(pts))
    n_in = float(len(inside))
    n_out = float(len(outside))
    stats = {
        "n_points": n,
        "n_inside": n_in,
        "n_outside": n_out,
        "outside_rate": (n_out / n) if n > 0 else 0.0,
    }
    return inside, outside, stats
