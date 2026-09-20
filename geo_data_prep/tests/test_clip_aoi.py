from __future__ import annotations

import geopandas as gpd
import pytest
from geo_data_prep.spatial.clip import maybe_clip_to_aoi
from shapely.geometry import Polygon


def _square(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_maybe_clip_to_aoi_disabled_returns_input() -> None:
    crs = "EPSG:3857"
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[_square(0, 0, 2, 2)], crs=crs)
    out = maybe_clip_to_aoi(gdf, aoi=None, enabled=False, working_crs=crs)
    assert len(out) == 1
    assert float(out.geometry.area.iloc[0]) == pytest.approx(4.0)


def test_maybe_clip_to_aoi_enabled_clips() -> None:
    crs = "EPSG:3857"
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[_square(0, 0, 2, 2)], crs=crs)
    aoi = gpd.GeoDataFrame({"a": [1]}, geometry=[_square(0, 0, 1, 2)], crs=crs)

    out = maybe_clip_to_aoi(gdf, aoi=aoi, enabled=True, working_crs=crs)
    assert len(out) == 1
    assert float(out.geometry.area.iloc[0]) == pytest.approx(2.0)
