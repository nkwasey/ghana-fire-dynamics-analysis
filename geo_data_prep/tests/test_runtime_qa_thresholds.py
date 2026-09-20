from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from geo_data_prep.core.runtime import run_from_config
from shapely.geometry import Polygon


def _square(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _write_threshold_repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        """[project]\nname = "toy_repo"\nversion = "0.0.0"\n""",
        encoding="utf-8",
    )

    zones_dir = tmp_path / "data" / "raw" / "zones"
    dists_dir = tmp_path / "data" / "raw" / "districts"
    zones_dir.mkdir(parents=True, exist_ok=True)
    dists_dir.mkdir(parents=True, exist_ok=True)

    working_crs = "EPSG:3857"
    zones = gpd.GeoDataFrame(
        {"z_label": ["Zone A", "Zone B"]},
        geometry=[_square(0, 0, 90, 10), _square(90, 0, 100, 10)],
        crs=working_crs,
    )
    districts = gpd.GeoDataFrame(
        {"d_label": ["District 1"]},
        geometry=[_square(0, 0, 100, 10)],
        crs=working_crs,
    )

    zones.to_file(zones_dir / "zones.shp", driver="ESRI Shapefile", index=False)
    districts.to_file(dists_dir / "districts.shp", driver="ESRI Shapefile", index=False)

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
    level: "acz"
  district:
    level: "district"
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
  method: "projected"
  projected_crs: "{working_crs}"
  geodesic_ellipsoid: "WGS84"
  units: "sq_km"
qa:
  enabled: true
  thresholds:
    overlap_share:
      warn_below: 0.85
      fail_below: 0.80
    area_relative_difference:
      warn_above: 0.01
      fail_above: 0.05
    unassigned_units:
      warn_above: 0
      fail_above: 0
    legacy_assignment_disagreement:
      warn_above: 2
      fail_above: 3
    invalid_geometries:
      warn_above: 0
      fail_above: 0
contract:
  stage: "stage_1"
  name: "geo_data_prep_stage1"
  version: "1.0.0-thresholds"
  canonical_upstream: true
  downstreams_adapt_later: true
""".lstrip(),
        encoding="utf-8",
    )
    return cfg_path


def test_runtime_qa_sidecars_follow_configured_thresholds(tmp_path: Path) -> None:
    cfg_path = _write_threshold_repo(tmp_path)

    run_from_config(cfg_path, run_id="toy_thresholds")

    run_dir = tmp_path / "out" / "toy_thresholds"
    overlap_summary = json.loads(
        (run_dir / "qa" / "district_zone_overlap_summary.json").read_text(encoding="utf-8")
    )
    runtime_validations = json.loads(
        (run_dir / "qa" / "runtime_assignment_validations.json").read_text(encoding="utf-8")
    )
    issues = pd.read_csv(run_dir / "qa" / "district_zone_overlap_issues.csv")

    assert overlap_summary["status"] == "pass"
    assert overlap_summary["ok"] is True
    assert [item["status"] for item in overlap_summary["validations"]] == [
        "pass",
        "pass",
        "pass",
        "pass",
        "na",
    ]
    assert overlap_summary["validations"][3]["details"]["invalid_geometry_count"] == 0
    assert overlap_summary["validations"][3]["details"]["layer_invalid_counts"] == {
        "districts": 0,
        "zones": 0,
    }

    assert runtime_validations["status"] == "pass"
    assert runtime_validations["ok"] is True
    assert [item["status"] for item in runtime_validations["results"]] == [
        "pass",
        "pass",
        "pass",
        "pass",
        "na",
    ]
    assert overlap_summary["validations"] == runtime_validations["results"]

    assert issues.empty
