from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from geo_data_prep.io.read import read_shapefile
from geo_data_prep.io.write import WriteError, write_shapefile
from shapely.geometry import Polygon


def _toy_gdf(crs: str = "EPSG:4326") -> object:
    poly = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    return gpd.GeoDataFrame(
        {
            "zone_canon": ["COASTAL"],
            "zone_name": ["coastal"],
            "zone_id": ["coastal"],
            "zone_code": ["CO"],
        },
        geometry=[poly],
        crs=crs,
    )


def test_shapefile_write_read_roundtrip_sidecars(tmp_path: Path) -> None:
    gdf = _toy_gdf(crs="EPSG:4326")
    required = ["zone_canon", "zone_name", "zone_id", "zone_code"]

    shp = tmp_path / "toy_zones.shp"
    wr = write_shapefile(gdf, shp_path=shp, required_columns=required)

    for ext in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
        assert wr.sidecars[ext].exists(), f"Missing sidecar {ext}"

    rr = read_shapefile(shp, working_crs="EPSG:3857", required_fields=required)
    gdf2 = rr.gdf

    assert str(gdf2.crs) == "EPSG:3857"
    assert set(gdf2.columns) == set(gdf.columns)
    for c in required:
        assert c in gdf2.columns


def test_write_rejects_long_field_names(tmp_path: Path) -> None:
    gdf = _toy_gdf(crs="EPSG:4326")
    gdf["this_is_too_long"] = "x"  # >10 chars

    with pytest.raises(WriteError):
        write_shapefile(
            gdf,
            shp_path=tmp_path / "bad.shp",
            required_columns=["zone_canon", "zone_name", "zone_id", "zone_code"],
        )
