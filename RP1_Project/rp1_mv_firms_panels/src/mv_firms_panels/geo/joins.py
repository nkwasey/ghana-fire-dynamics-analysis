# file: src/mv_firms_panels/geo/joins.py
"""Spatial joins between FIRMS point detections and polygon unit boundaries.

Requirements (binding)
----------------------
- No ArcPy; open-source stack only (GeoPandas/Shapely/PyProj).
- Explicit CRS alignment; fail-fast on missing CRS.
- Deterministic behaviour: stable tie-breaks for ambiguous matches.
- QA: unmatched points must be identifiable downstream.

Join policy
-----------
Default join predicate is 'intersects' so points on boundaries are not dropped.
If polygons overlap (should not happen in clean administrative boundaries),
multiple matches are resolved deterministically:
1) choose the polygon with smallest area (computed in a deterministic projected CRS)
2) then choose the lowest unit_id (string comparison)
3) then choose the lowest polygon row order

STRtree result normalisation:
- Shapely STRtree.query() returns *indices* in Shapely 2.x, but may return
  geometries in some supported stacks. We normalise candidates to polygon indices.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from mv_firms_panels.geo.crs import choose_area_crs_from_bounds, ensure_common_crs


class GeoJoinError(ValueError):
    """Raised when a spatial join cannot be performed safely."""


def _require_columns(gdf: gpd.GeoDataFrame, cols: tuple[str, ...], *, name: str) -> None:
    missing = [c for c in cols if c not in gdf.columns]
    if missing:
        raise GeoJoinError(f"{name} missing required columns: {missing}")


def _require_point_geometries(points: gpd.GeoDataFrame) -> None:
    if points.geometry is None:
        raise GeoJoinError("points GeoDataFrame has no active geometry column")
    if len(points) > 0:
        g0 = points.geometry.iloc[0]
        if g0 is not None and g0.geom_type != "Point":
            raise GeoJoinError(f"Expected point geometries; got {g0.geom_type!r}")


def _build_strtree(polys: gpd.GeoDataFrame) -> tuple[STRtree, list[BaseGeometry], dict[int, int]]:
    geoms = list(polys.geometry)
    if any(g is None for g in geoms):
        raise GeoJoinError("polygons contain null geometries")
    tree = STRtree(geoms)
    # Used for Shapely 1.x mode (geometries returned)
    id_to_pos = {id(g): i for i, g in enumerate(geoms)}
    return tree, geoms, id_to_pos


def _iter_candidate_indices(*, candidates, id_to_pos: dict[int, int]) -> list[int]:
    """Return candidate polygon indices from STRtree.query output."""
    out: list[int] = []
    for cand in candidates:
        if isinstance(cand, (int, np.integer)):
            out.append(int(cand))
        else:
            pos = id_to_pos.get(id(cand))
            if pos is None:
                raise GeoJoinError("STRtree returned an unknown geometry candidate")
            out.append(pos)
    return out


def _compute_polygon_areas_for_tiebreak(
    polygons_aligned: gpd.GeoDataFrame,
) -> pd.Series:
    """Compute polygon areas in a deterministic projected CRS for tie-breaks."""
    polys_wgs84 = polygons_aligned.to_crs(CRS.from_epsg(4326))
    bounds = tuple(polys_wgs84.total_bounds.tolist())  # (minx,miny,maxx,maxy)
    area_crs = choose_area_crs_from_bounds(bounds_wgs84=bounds)
    polys_area = polygons_aligned.to_crs(area_crs)
    return polys_area.geometry.area


def join_points_to_units(
    *,
    points: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
    level: str,
    unit_id_field: str,
    unit_name_field: str | None = None,
    predicate: str = "intersects",
) -> gpd.GeoDataFrame:
    """Attach (level, unit_id, unit_name) to each point via spatial join.

    Returns a copy of points with added columns:
      - level (constant)
      - unit_id (string; null when unmatched)
      - unit_name (string; null when not provided/unmatched)

    The returned GeoDataFrame has the same row count as input points.
    """
    if predicate not in {"intersects", "within"}:
        raise ValueError("predicate must be one of {'intersects','within'}")

    _require_point_geometries(points)
    _require_columns(polygons, (unit_id_field,), name="polygons")
    if unit_name_field is not None:
        _require_columns(polygons, (unit_name_field,), name="polygons")

    pts, polys, _ = ensure_common_crs(points=points, polygons=polygons, prefer="polygons")
    polys = polys.reset_index(drop=True).copy()

    if len(polys) == 0:
        raise GeoJoinError("polygons is empty (0 features)")

    poly_area = _compute_polygon_areas_for_tiebreak(polys).reset_index(drop=True)

    # Build tree on the same reset-index geometry order
    tree, geoms, id_to_pos = _build_strtree(polys)

    polys[unit_id_field] = polys[unit_id_field].astype(str)
    unit_ids = polys[unit_id_field].tolist()
    unit_names = (
        polys[unit_name_field].astype(str).tolist() if unit_name_field is not None else None
    )

    out_unit_id: list[str | None] = []
    out_unit_name: list[str | None] = []

    for geom in pts.geometry:
        if geom is None:
            out_unit_id.append(None)
            out_unit_name.append(None)
            continue

        candidates = tree.query(geom)
        cand_idx = _iter_candidate_indices(candidates=candidates, id_to_pos=id_to_pos)

        matches: list[int] = []
        for pos in cand_idx:
            cand_geom = geoms[pos]
            ok = geom.intersects(cand_geom) if predicate == "intersects" else geom.within(cand_geom)
            if ok:
                matches.append(pos)

        if not matches:
            out_unit_id.append(None)
            out_unit_name.append(None)
            continue

        # Deterministic tie-break
        matches_sorted = sorted(matches, key=lambda i: (float(poly_area.iloc[i]), unit_ids[i], i))
        best = matches_sorted[0]
        out_unit_id.append(unit_ids[best])
        out_unit_name.append(unit_names[best] if unit_names is not None else None)

    out = pts.copy()
    out["level"] = level
    out["unit_id"] = out_unit_id
    out["unit_name"] = out_unit_name if unit_name_field is not None else None
    return out


def join_coverage_stats(
    *,
    joined_points: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Return join coverage statistics as a 1-row DataFrame."""
    if "unit_id" not in joined_points.columns:
        raise GeoJoinError("joined_points must contain 'unit_id' column")

    n = int(len(joined_points))
    n_matched = int(joined_points["unit_id"].notna().sum())
    n_unmatched = n - n_matched
    matched_rate = (n_matched / n) if n > 0 else 0.0

    return pd.DataFrame(
        [
            {
                "n_points": n,
                "n_matched": n_matched,
                "n_unmatched": n_unmatched,
                "matched_rate": matched_rate,
            }
        ]
    )
