from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from geo_data_prep.core.config import LevelConfig
from geo_data_prep.core.runtime import RunError, run_from_config
from geo_data_prep.exports.universe import UniverseExportError, build_unit_universe_dataframe
from geo_data_prep.spatial.area import geodesic_area_series, projected_area_series
from shapely.geometry import Polygon


def _square(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _toy_geo_zones(crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "zone_id": ["z1", "z2"],
            "zone_name": ["Zone 1", "Zone 2"],
            "zone_code": ["Z1", "Z2"],
        },
        geometry=[_square(0.00, 0.00, 0.05, 0.05), _square(0.10, 0.00, 0.15, 0.05)],
        crs=crs,
    )


def _toy_geo_districts(crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "district_id": ["d1", "d2"],
            "district_name": ["District 1", "District 2"],
            "zone_id": ["z1", "z2"],
            "zone_name": ["Zone 1", "Zone 2"],
            "zone_code": ["Z1", "Z2"],
            "ovl_share": [1.0, 1.0],
        },
        geometry=[_square(0.00, 0.00, 0.025, 0.05), _square(0.10, 0.00, 0.125, 0.05)],
        crs=crs,
    )


def _level_config_key() -> str:
    """Return the strict-schema key used for level labels.

    The uploaded ZIP uses ``level_name`` in ``LevelConfig``, while the local
    failure trace shows a working tree that expects ``level`` instead. The test
    fixture should follow the active installed schema rather than hard-coding
    one variant, otherwise it can fail during config validation before reaching
    the runtime path being tested.
    """

    model_fields = getattr(LevelConfig, "model_fields", {})
    if "level" in model_fields:
        return "level"
    if "level_name" in model_fields:
        return "level_name"
    raise AssertionError("LevelConfig exposes neither 'level' nor 'level_name'")


def _write_toy_repo(tmp_path: Path, *, area_method: str, area_units: str = "sq_km") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        """[project]
name = "toy_repo"
version = "0.0.0"
""",
        encoding="utf-8",
    )

    zones_dir = tmp_path / "data" / "raw" / "zones"
    dists_dir = tmp_path / "data" / "raw" / "districts"
    zones_dir.mkdir(parents=True, exist_ok=True)
    dists_dir.mkdir(parents=True, exist_ok=True)

    working_crs = "EPSG:3857"
    zones = gpd.GeoDataFrame(
        {"z_label": ["Zone A", "Zone B"]},
        geometry=[_square(0, 0, 1000, 1000), _square(1000, 0, 2000, 1000)],
        crs=working_crs,
    )
    districts = gpd.GeoDataFrame(
        {"d_label": ["District 1", "District 2"]},
        geometry=[_square(0, 0, 1000, 1000), _square(1000, 0, 2000, 1000)],
        crs=working_crs,
    )
    zones.to_file(zones_dir / "zones.shp", driver="ESRI Shapefile", index=False)
    districts.to_file(dists_dir / "districts.shp", driver="ESRI Shapefile", index=False)

    level_key = _level_config_key()

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"""
schema_version: "1.0"
inputs:
  zones:
    path: "data/raw/zones/zones.shp"
    label_field: "z_label"
  districts:
    path: "data/raw/districts/districts.shp"
    label_field: "d_label"
  aoi:
    enabled: false
    path: "data/raw/aoi/aoi.shp"
levels:
  zone:
    {level_key}: "acz"
  district:
    {level_key}: "district"
crs:
  working_crs: "{working_crs}"
  plot_crs: "EPSG:4326"
outputs:
  out_dir: "out"
  toggles:
    splits: false
    plots: false
  basenames:
    zones: "zones_stage1"
    districts: "districts_stage1"
derivations:
  zone_code:
    mapping: {{}}
    fallback:
      method: "initials"
      collision: "suffix"
area_policy:
  method: "{area_method}"
  projected_crs: "{working_crs}"
  geodesic_ellipsoid: "WGS84"
  units: "{area_units}"
qa:
  enabled: true
contract:
  stage: "stage_1"
  name: "geo_data_prep_stage1"
  version: "1.0"
""".lstrip(),
        encoding="utf-8",
    )
    return cfg_path


def test_unit_universe_projected_area_policy_matches_shared_projected_helper() -> None:
    zones = _toy_geo_zones()
    dists = _toy_geo_districts()

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

    expected_zone = projected_area_series(zones, projected_crs="EPSG:3857", units="sq_km")
    expected_dist = projected_area_series(dists, projected_crs="EPSG:3857", units="sq_km")

    assert df.loc[df["unit_type"] == "zone", "area_sqkm"].tolist() == pytest.approx(
        expected_zone.tolist()
    )
    assert df.loc[df["unit_type"] == "district", "area_sqkm"].tolist() == pytest.approx(
        expected_dist.tolist()
    )
    assert df.loc[df["unit_type"] == "zone", "unit_code"].tolist() == ["Z1", "Z2"]
    assert df.loc[df["unit_type"] == "zone", "parent_code"].tolist() == ["", ""]
    assert df.loc[df["unit_type"] == "district", "unit_code"].tolist() == ["", ""]
    assert df.loc[df["unit_type"] == "district", "parent_code"].tolist() == ["Z1", "Z2"]


def test_unit_universe_geodesic_area_policy_matches_shared_geodesic_helper() -> None:
    zones = _toy_geo_zones()
    dists = _toy_geo_districts()

    df = build_unit_universe_dataframe(
        zones,
        dists,
        zone_level_label="acz",
        district_level_label="district",
        district_area_policy="compute",
        area_method="geodesic",
        area_geodesic_ellipsoid="WGS84",
        area_units="sq_km",
    )

    expected_zone = geodesic_area_series(zones, ellipsoid="WGS84", units="sq_km")
    expected_dist = geodesic_area_series(dists, ellipsoid="WGS84", units="sq_km")

    assert df.loc[df["unit_type"] == "zone", "area_sqkm"].tolist() == pytest.approx(
        expected_zone.tolist()
    )
    assert df.loc[df["unit_type"] == "district", "area_sqkm"].tolist() == pytest.approx(
        expected_dist.tolist()
    )
    assert df.loc[df["unit_type"] == "district", "parent_code"].tolist() == ["Z1", "Z2"]


def test_unit_universe_fails_fast_when_policy_method_both_cannot_fit_fixed_schema() -> None:
    zones = _toy_geo_zones()
    dists = _toy_geo_districts()

    with pytest.raises(UniverseExportError) as excinfo:
        build_unit_universe_dataframe(
            zones,
            dists,
            zone_level_label="acz",
            district_level_label="district",
            district_area_policy="compute",
            area_method="both",
            area_projected_crs="EPSG:3857",
            area_units="sq_km",
        )

    assert "method='both'" in str(excinfo.value)
    assert "unit_universe.csv schema" in str(excinfo.value)


@pytest.mark.parametrize(
    ("area_method", "area_units", "expected_fragment"),
    [
        ("both", "sq_km", "method='both'"),
        ("projected", "sq_m", "units='sq_m'"),
    ],
)
def test_runtime_fails_fast_when_declared_area_policy_cannot_be_represented(
    tmp_path: Path,
    area_method: str,
    area_units: str,
    expected_fragment: str,
) -> None:
    cfg_path = _write_toy_repo(tmp_path, area_method=area_method, area_units=area_units)

    with pytest.raises(RunError) as excinfo:
        run_from_config(cfg_path, run_id="bad_area_policy")

    msg = str(excinfo.value)
    assert expected_fragment in msg
    assert "unit_universe.csv schema" in msg
