from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from geo_data_prep.exports.combined import write_combined_boundaries
from geo_data_prep.exports.crosswalks import write_crosswalk_exports
from geo_data_prep.exports.splits import write_zone_splits
from geo_data_prep.exports.universe import build_unit_universe_dataframe, write_unit_universe_csv
from shapely.geometry import Polygon


def _toy_zones(crs: str = "EPSG:3857") -> gpd.GeoDataFrame:
    z1 = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    z2 = Polygon([(2000, 0), (3000, 0), (3000, 1000), (2000, 1000)])
    return gpd.GeoDataFrame(
        {
            "zone_id": ["coastal_savanna", "forest"],
            "zone_name": ["Coastal savanna", "Forest"],
            "zone_code": ["CS", "FO"],
        },
        geometry=[z1, z2],
        crs=crs,
    )


def _toy_districts(crs: str = "EPSG:3857") -> gpd.GeoDataFrame:
    d1 = Polygon([(0, 0), (500, 0), (500, 500), (0, 500)])
    d2 = Polygon([(500, 0), (1000, 0), (1000, 500), (500, 500)])
    d3 = Polygon([(2000, 0), (2500, 0), (2500, 500), (2000, 500)])
    return gpd.GeoDataFrame(
        {
            "district_id": ["Awutu_Senya", "Cape_Coast", "Bekwai"],
            "district_name": ["Awutu Senya", "Cape Coast", "Bekwai"],
            "district_code": ["AWS", "CAP", "BEK"],
            "zone_id": ["coastal_savanna", "coastal_savanna", "forest"],
            "zone_name": ["Coastal savanna", "Coastal savanna", "Forest"],
            "zone_code": ["CS", "CS", "FO"],
            "ovl_share": [1.0, 1.0, 1.0],
        },
        geometry=[d1, d2, d3],
        crs=crs,
    )


def test_unit_universe_schema_roundtrip_and_deterministic_order(tmp_path: Path) -> None:
    zones = _toy_zones()
    dists = _toy_districts()

    df = build_unit_universe_dataframe(
        zones,
        dists,
        zone_level_label="acz",
        district_level_label="district",
        district_area_policy="compute",
        area_method="projected",
        area_projected_crs="EPSG:3857",
        area_units="sq_km",
    )

    assert list(df.columns) == [
        "unit_type",
        "level",
        "unit_id",
        "unit_code",
        "unit_name",
        "parent_level",
        "parent_id",
        "parent_code",
        "parent_name",
        "area_sqkm",
    ]
    assert df["unit_type"].tolist() == ["zone", "zone", "district", "district", "district"]
    assert df["unit_id"].tolist() == [
        "coastal_savanna",
        "forest",
        "Awutu_Senya",
        "Cape_Coast",
        "Bekwai",
    ]
    assert df["unit_code"].tolist() == ["CS", "FO", "AWS", "CAP", "BEK"]
    assert df.loc[df["unit_type"] == "zone", "level"].tolist() == ["acz", "acz"]
    assert df.loc[df["unit_type"] == "zone", "parent_code"].tolist() == ["", ""]
    assert df.loc[df["unit_type"] == "district", "parent_level"].tolist() == ["acz", "acz", "acz"]
    assert df.loc[df["unit_type"] == "district", "parent_id"].tolist() == [
        "coastal_savanna",
        "coastal_savanna",
        "forest",
    ]
    assert df.loc[df["unit_type"] == "district", "parent_code"].tolist() == ["CS", "CS", "FO"]
    assert df.loc[df["unit_type"] == "zone", "area_sqkm"].tolist() == pytest.approx([1.0, 1.0])
    assert df.loc[df["unit_type"] == "district", "area_sqkm"].tolist() == pytest.approx(
        [0.25, 0.25, 0.25]
    )

    out = write_unit_universe_csv(
        zones,
        dists,
        out_dir=tmp_path,
        zone_level_label="acz",
        district_level_label="district",
        district_area_policy="compute",
        filename="unit_universe.csv",
        area_method="projected",
        area_projected_crs="EPSG:3857",
        area_units="sq_km",
    )
    assert out.name == "unit_universe.csv"

    roundtrip = pd.read_csv(out, keep_default_na=False)
    assert list(roundtrip.columns) == list(df.columns)
    assert roundtrip["unit_id"].tolist() == df["unit_id"].tolist()
    assert roundtrip["unit_code"].tolist() == df["unit_code"].tolist()
    assert roundtrip["parent_code"].tolist() == df["parent_code"].tolist()
    assert roundtrip.loc[roundtrip["unit_type"] == "zone", "area_sqkm"].tolist() == pytest.approx(
        [1.0, 1.0], abs=1e-6
    )


def test_unit_universe_leaves_district_unit_code_blank_when_upstream_code_absent() -> None:
    zones = _toy_zones()
    dists = _toy_districts().drop(columns=["district_code"])

    df = build_unit_universe_dataframe(
        zones,
        dists,
        zone_level_label="acz",
        district_level_label="district",
        district_area_policy="compute",
        area_method="projected",
        area_projected_crs="EPSG:3857",
        area_units="sq_km",
    )

    district_rows = df.loc[df["unit_type"] == "district"].reset_index(drop=True)
    assert district_rows["unit_code"].tolist() == ["", "", ""]
    assert district_rows["parent_code"].tolist() == ["CS", "CS", "FO"]


def test_combined_export_honours_basenames_and_manifest_crosswalk(tmp_path: Path) -> None:
    zones = _toy_zones()
    dists = _toy_districts()

    out = write_combined_boundaries(
        zones,
        dists,
        out_dir=tmp_path,
        zones_basename="zones_stage1_acz",
        districts_basename="districts_stage1",
    )

    zones_shp = tmp_path / "boundaries" / "zones_stage1_acz.shp"
    districts_shp = tmp_path / "boundaries" / "districts_stage1.shp"
    assert out.zones.shp_path == zones_shp
    assert out.districts.shp_path == districts_shp
    assert zones_shp.exists()
    assert districts_shp.exists()

    manifest = json.loads(out.manifest_path.read_text(encoding="utf-8"))
    assert manifest["zones"]["basename"] == "zones_stage1_acz"
    assert manifest["districts"]["basename"] == "districts_stage1"
    assert manifest["zones"]["shp"] == "boundaries/zones_stage1_acz.shp"
    assert manifest["districts"]["shp"] == "boundaries/districts_stage1.shp"
    assert manifest["schema"]["logical_fields"]["zones"] == ["zone_id", "zone_name", "zone_code"]
    assert manifest["schema"]["logical_fields"]["districts"] == [
        "district_id",
        "district_name",
        "district_code",
        "zone_id",
        "zone_name",
        "zone_code",
        "ovl_share",
    ]
    assert manifest["schema"]["field_crosswalk"]["districts"]["logical_to_physical"] == {
        "district_id": "dist_id",
        "district_name": "dist_name",
        "district_code": "dist_code",
        "zone_id": "zone_id",
        "zone_name": "zone_name",
        "zone_code": "zone_code",
        "ovl_share": "ovl_share",
    }

    districts_physical = gpd.read_file(districts_shp)
    assert list(districts_physical.columns) == [
        "dist_id",
        "dist_name",
        "dist_code",
        "zone_id",
        "zone_name",
        "zone_code",
        "ovl_share",
        "geometry",
    ]


def test_zone_splits_honour_basenames_and_manifest_rows(tmp_path: Path) -> None:
    zones = _toy_zones()
    dists = _toy_districts()

    out = write_zone_splits(
        zones,
        dists,
        out_dir=tmp_path,
        zones_basename="zones_stage1_acz",
        districts_basename="districts_stage1",
    )

    zs = tmp_path / "splits" / "zones_split"
    ds = tmp_path / "splits" / "zone_districts"

    expected_zone_files = {
        "coastal_savanna": zs / "zones_stage1_acz__zone_coastal_savanna.shp",
        "forest": zs / "zones_stage1_acz__zone_forest.shp",
    }
    expected_district_files = {
        "coastal_savanna": ds / "districts_stage1__zone_coastal_savanna.shp",
        "forest": ds / "districts_stage1__zone_forest.shp",
    }

    for zone_id, shp_path in expected_zone_files.items():
        assert shp_path.exists(), f"missing zone split for {zone_id}"
        for ext in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
            assert shp_path.with_suffix(ext).exists()
    for zone_id, shp_path in expected_district_files.items():
        assert shp_path.exists(), f"missing district split for {zone_id}"
        for ext in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
            assert shp_path.with_suffix(ext).exists()

    manifest = json.loads(out.manifest_path.read_text(encoding="utf-8"))
    assert manifest["zones_basename"] == "zones_stage1_acz"
    assert manifest["districts_basename"] == "districts_stage1"
    assert manifest["rows"] == [
        {
            "district_count": 2,
            "district_layer": "splits/zone_districts/districts_stage1__zone_coastal_savanna.shp",
            "zone_code": "CS",
            "zone_id": "coastal_savanna",
            "zone_layer": "splits/zones_split/zones_stage1_acz__zone_coastal_savanna.shp",
            "zone_name": "Coastal savanna",
        },
        {
            "district_count": 1,
            "district_layer": "splits/zone_districts/districts_stage1__zone_forest.shp",
            "zone_code": "FO",
            "zone_id": "forest",
            "zone_layer": "splits/zones_split/zones_stage1_acz__zone_forest.shp",
            "zone_name": "Forest",
        },
    ]
    assert len(out.districts_written) == 2
    assert len(out.zones_written) == 2


def test_crosswalk_exports_write_expected_csvs_and_json(tmp_path: Path) -> None:
    zones = _toy_zones()
    dists = _toy_districts()

    out = write_crosswalk_exports(zones, dists, out_dir=tmp_path)

    zone_lookup = pd.read_csv(out.zone_lookup_path)
    district_crosswalk = pd.read_csv(out.district_zone_crosswalk_path)
    field_crosswalk = json.loads(out.shapefile_field_crosswalk_path.read_text(encoding="utf-8"))
    manifest = json.loads(out.manifest_path.read_text(encoding="utf-8"))

    assert list(zone_lookup.columns) == ["zone_id", "zone_name", "zone_code"]
    assert zone_lookup.to_dict(orient="records") == [
        {"zone_id": "coastal_savanna", "zone_name": "Coastal savanna", "zone_code": "CS"},
        {"zone_id": "forest", "zone_name": "Forest", "zone_code": "FO"},
    ]

    assert list(district_crosswalk.columns) == [
        "district_id",
        "district_name",
        "district_code",
        "zone_id",
        "zone_name",
        "zone_code",
        "ovl_share",
    ]
    assert district_crosswalk.to_dict(orient="records") == [
        {
            "district_id": "Awutu_Senya",
            "district_name": "Awutu Senya",
            "district_code": "AWS",
            "zone_id": "coastal_savanna",
            "zone_name": "Coastal savanna",
            "zone_code": "CS",
            "ovl_share": 1.0,
        },
        {
            "district_id": "Cape_Coast",
            "district_name": "Cape Coast",
            "district_code": "CAP",
            "zone_id": "coastal_savanna",
            "zone_name": "Coastal savanna",
            "zone_code": "CS",
            "ovl_share": 1.0,
        },
        {
            "district_id": "Bekwai",
            "district_name": "Bekwai",
            "district_code": "BEK",
            "zone_id": "forest",
            "zone_name": "Forest",
            "zone_code": "FO",
            "ovl_share": 1.0,
        },
    ]
    assert field_crosswalk["zones"] == {
        "logical_to_physical": {
            "zone_id": "zone_id",
            "zone_name": "zone_name",
            "zone_code": "zone_code",
        },
        "physical_to_logical": {
            "zone_id": "zone_id",
            "zone_name": "zone_name",
            "zone_code": "zone_code",
        },
    }
    assert field_crosswalk["districts"] == {
        "logical_to_physical": {
            "district_id": "dist_id",
            "district_name": "dist_name",
            "district_code": "dist_code",
            "zone_id": "zone_id",
            "zone_name": "zone_name",
            "zone_code": "zone_code",
            "ovl_share": "ovl_share",
        },
        "physical_to_logical": {
            "dist_id": "district_id",
            "dist_name": "district_name",
            "dist_code": "district_code",
            "zone_id": "zone_id",
            "zone_name": "zone_name",
            "zone_code": "zone_code",
            "ovl_share": "ovl_share",
        },
    }
    assert manifest == {
        "district_rows": 3,
        "district_zone_crosswalk_csv": "crosswalks/district_zone_crosswalk.csv",
        "shapefile_field_crosswalk_json": "crosswalks/shapefile_field_crosswalk.json",
        "zone_lookup_csv": "crosswalks/zone_lookup.csv",
        "zone_rows": 2,
    }
