# file: tests/test_geo_join_smoke.py
"""Smoke tests for geospatial join + land mask logic.

Constraints
-----------
- Must use synthetic in-memory geometries only (no file IO).
- Exercises CRS alignment, join assignment, unmatched detection, and land-mask split.

Note on environment robustness
------------------------------
Some older Shapely/NumPy combinations can raise NotImplementedError when
constructing GeoSeries/GeoDataFrames. In that case we skip these tests with
a clear message rather than failing the whole suite.
"""

from __future__ import annotations

import geopandas as gpd
import pytest
from mv_firms_panels.geo.joins import join_coverage_stats, join_points_to_units
from mv_firms_panels.geo.masks import split_points_by_land_mask
from mv_firms_panels.geo.qa_geo import build_unmatched_points
from shapely.geometry import Point, Polygon


def _safe_geoseries(geoms, crs: str) -> gpd.GeoSeries:
    try:
        return gpd.GeoSeries(list(geoms), crs=crs)
    except NotImplementedError:
        pytest.skip(
            "GeoSeries construction failed due to Shapely/NumPy compatibility. "
            "Upgrade Shapely (>=2.0) and GeoPandas for full geo-join test coverage."
        )


def test_join_points_to_units_and_unmatched():
    poly_a = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
    poly_b = Polygon([(1, 0), (1, 1), (2, 1), (2, 0)])

    polys = gpd.GeoDataFrame(
        {"UNIT_ID": ["A", "B"], "UNIT_NAME": ["Alpha", "Beta"]},
        geometry=_safe_geoseries([poly_a, poly_b], "EPSG:4326"),
    )

    pts = gpd.GeoDataFrame(
        {"source_file": ["x", "x", "x"]},
        geometry=_safe_geoseries([Point(0.5, 0.5), Point(1.5, 0.5), Point(10, 10)], "EPSG:4326"),
    )

    joined = join_points_to_units(
        points=pts,
        polygons=polys,
        level="admin2",
        unit_id_field="UNIT_ID",
        unit_name_field="UNIT_NAME",
    )
    assert list(joined["unit_id"].fillna("")) == ["A", "B", ""]
    assert list(joined["unit_name"].fillna("")) == ["Alpha", "Beta", ""]

    stats = join_coverage_stats(joined_points=joined)
    assert int(stats.iloc[0]["n_points"]) == 3
    assert int(stats.iloc[0]["n_matched"]) == 2
    assert int(stats.iloc[0]["n_unmatched"]) == 1

    unmatched = build_unmatched_points(
        joined_points=joined, keep_columns=["source_file", "unit_id"]
    )
    assert len(unmatched) == 1


def test_land_mask_split():
    land = gpd.GeoDataFrame(
        {},
        geometry=_safe_geoseries([Polygon([(0, 0), (0, 2), (2, 2), (2, 0)])], "EPSG:4326"),
    )
    pts = gpd.GeoDataFrame(
        {},
        geometry=_safe_geoseries([Point(0.5, 0.5), Point(1.5, 1.5), Point(10, 10)], "EPSG:4326"),
    )

    inside, outside, stats = split_points_by_land_mask(
        points=pts, land_mask=land, predicate="intersects"
    )
    assert len(inside) == 2
    assert len(outside) == 1
    assert stats["n_points"] == 3.0
    assert stats["n_outside"] == 1.0
