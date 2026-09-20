from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from geo_data_prep.core.runtime import run_from_config
from shapely.geometry import Polygon

_EXPECTED_UNIT_UNIVERSE_COLUMNS = [
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


def _square(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _write_toy_repo(tmp_path: Path) -> Path:
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
    splits: true
    plots: false
  basenames:
    zones: "zones_stage1_acz"
    districts: "districts_stage1"
derivations:
  zone_code:
    mapping: {{}}
    fallback:
      method: "initials"
      collision: "suffix"
area_policy:
  method: "geodesic"
  projected_crs: "{working_crs}"
  geodesic_ellipsoid: "WGS84"
  units: "sq_km"
qa:
  enabled: true
  thresholds:
    overlap_share:
      warn_below: 0.95
      fail_below: 0.80
    area_relative_difference:
      warn_above: 0.01
      fail_above: 0.05
    unassigned_units:
      warn_above: 0
      fail_above: 0
    legacy_assignment_disagreement:
      warn_above: 0
      fail_above: 0
    invalid_geometries:
      warn_above: 0
      fail_above: 0
contract:
  stage: "stage_1"
  name: "geo_data_prep_stage1"
  version: "1.0.0-smoke"
  canonical_upstream: true
  downstreams_adapt_later: true
""".lstrip(),
        encoding="utf-8",
    )
    return cfg_path


def test_run_pipeline_smoke_toy_repo_freezes_batch2_unit_universe_contract(tmp_path: Path) -> None:
    cfg_path = _write_toy_repo(tmp_path)
    outs = run_from_config(cfg_path, run_id="toy_run")

    run_dir = tmp_path / "out" / "toy_run"
    assert outs.run_dir.resolve() == run_dir.resolve()
    assert outs.inputs_fingerprint_path == run_dir / "inputs_fingerprint.json"
    assert outs.outputs_manifest_path == run_dir / "outputs_manifest.json"

    expected_paths = [
        run_dir / "inputs_fingerprint.json",
        run_dir / "outputs_manifest.json",
        run_dir / "unit_universe.csv",
        run_dir / "boundaries" / "combined_manifest.json",
        run_dir / "boundaries" / "zones_stage1_acz.shp",
        run_dir / "boundaries" / "districts_stage1.shp",
        run_dir / "splits" / "splits_manifest.json",
        run_dir / "crosswalks" / "crosswalks_manifest.json",
        run_dir / "crosswalks" / "zone_lookup.csv",
        run_dir / "crosswalks" / "district_zone_crosswalk.csv",
        run_dir / "crosswalks" / "shapefile_field_crosswalk.json",
        run_dir / "qa" / "district_zone_overlap.csv",
        run_dir / "qa" / "district_zone_overlap_summary.json",
        run_dir / "qa" / "district_zone_overlap_validations.json",
        run_dir / "qa" / "district_zone_overlap_issues.csv",
        run_dir / "qa" / "district_zone_overlap_metrics.csv",
        run_dir / "qa" / "district_zone_overlap_sliver_summary.json",
        run_dir / "qa" / "runtime_assignment_validations.json",
        run_dir / "qa" / "working_crs_sensitivity_summary.json",
        run_dir / "qa" / "working_crs_sensitivity_comparison.csv",
        run_dir / "qa" / "qa_summary.json",
        run_dir / "contract" / "stage1_contract_manifest.json",
    ]
    for path in expected_paths:
        assert path.exists(), f"missing expected runtime artefact: {path.relative_to(run_dir)}"

    assert not (run_dir / "plots").exists()

    outputs_manifest = json.loads((run_dir / "outputs_manifest.json").read_text(encoding="utf-8"))
    inputs_fingerprint = json.loads(
        (run_dir / "inputs_fingerprint.json").read_text(encoding="utf-8")
    )
    qa_summary = json.loads((run_dir / "qa" / "qa_summary.json").read_text(encoding="utf-8"))
    contract_manifest = json.loads(
        (run_dir / "contract" / "stage1_contract_manifest.json").read_text(encoding="utf-8")
    )
    unit_universe = pd.read_csv(run_dir / "unit_universe.csv")

    assert outputs_manifest["run_id"] == "toy_run"
    assert outputs_manifest["contract"]["version"] == "1.0.0-smoke"
    assert outputs_manifest["area_policy"] == {
        "geodesic_ellipsoid": "WGS84",
        "include_method_metadata": True,
        "method": "geodesic",
        "projected_crs": "EPSG:3857",
        "units": "sq_km",
    }
    assert set(outputs_manifest["index"].keys()) == {
        "combined_district_shapefile",
        "combined_manifest_json",
        "combined_zone_shapefile",
        "crosswalks_manifest_json",
        "district_zone_crosswalk_csv",
        "overlap_issues_csv",
        "overlap_metrics_csv",
        "overlap_report_csv",
        "overlap_sliver_summary_json",
        "overlap_summary_json",
        "overlap_validations_json",
        "qa_summary_json",
        "runtime_assignment_validations_json",
        "shapefile_field_crosswalk_json",
        "splits_manifest_json",
        "stage1_contract_manifest_json",
        "unit_universe_csv",
        "working_crs_sensitivity_comparison_csv",
        "working_crs_sensitivity_summary_json",
        "zone_lookup_csv",
    }
    assert outputs_manifest["index"] == {
        "combined_district_shapefile": "boundaries/districts_stage1.shp",
        "combined_manifest_json": "boundaries/combined_manifest.json",
        "combined_zone_shapefile": "boundaries/zones_stage1_acz.shp",
        "crosswalks_manifest_json": "crosswalks/crosswalks_manifest.json",
        "district_zone_crosswalk_csv": "crosswalks/district_zone_crosswalk.csv",
        "overlap_issues_csv": "qa/district_zone_overlap_issues.csv",
        "overlap_metrics_csv": "qa/district_zone_overlap_metrics.csv",
        "overlap_report_csv": "qa/district_zone_overlap.csv",
        "overlap_sliver_summary_json": "qa/district_zone_overlap_sliver_summary.json",
        "overlap_summary_json": "qa/district_zone_overlap_summary.json",
        "overlap_validations_json": "qa/district_zone_overlap_validations.json",
        "qa_summary_json": "qa/qa_summary.json",
        "runtime_assignment_validations_json": "qa/runtime_assignment_validations.json",
        "shapefile_field_crosswalk_json": "crosswalks/shapefile_field_crosswalk.json",
        "splits_manifest_json": "splits/splits_manifest.json",
        "stage1_contract_manifest_json": "contract/stage1_contract_manifest.json",
        "unit_universe_csv": "unit_universe.csv",
        "working_crs_sensitivity_comparison_csv": "qa/working_crs_sensitivity_comparison.csv",
        "working_crs_sensitivity_summary_json": "qa/working_crs_sensitivity_summary.json",
        "zone_lookup_csv": "crosswalks/zone_lookup.csv",
    }
    file_paths = [row["path"] for row in outputs_manifest["files"]]
    assert file_paths == sorted(file_paths)
    assert "contract/stage1_contract_manifest.json" in file_paths
    assert "qa/qa_summary.json" in file_paths
    assert "crosswalks/zone_lookup.csv" in file_paths

    assert inputs_fingerprint["run_id"] == "toy_run"
    assert inputs_fingerprint["run_dir"] == "out/toy_run"
    assert inputs_fingerprint["area_policy"]["method"] == "geodesic"
    assert inputs_fingerprint["contract"]["version"] == "1.0.0-smoke"

    assert qa_summary["ok"] is True
    assert qa_summary["status"] == "pass"
    assert qa_summary["overlap_report_csv"] == "qa/district_zone_overlap.csv"
    assert qa_summary["overlap_rows"] == 2
    assert qa_summary["qa_enabled"] is True
    assert (
        qa_summary["runtime_assignment_validations_json"]
        == "qa/runtime_assignment_validations.json"
    )
    assert qa_summary["overlap_sidecars"] == {
        "issues_csv": "qa/district_zone_overlap_issues.csv",
        "metrics_csv": "qa/district_zone_overlap_metrics.csv",
        "sliver_summary_json": "qa/district_zone_overlap_sliver_summary.json",
        "summary_json": "qa/district_zone_overlap_summary.json",
        "validations_json": "qa/district_zone_overlap_validations.json",
    }
    assert qa_summary["thresholds"] == {
        "area_relative_difference": {"fail_above": 0.05, "warn_above": 0.01},
        "invalid_geometries": {"fail_above": 0, "warn_above": 0},
        "legacy_assignment_disagreement": {"fail_above": 0, "warn_above": 0},
        "overlap_share": {"fail_below": 0.8, "warn_below": 0.95},
        "unassigned_units": {"fail_above": 0, "warn_above": 0},
    }
    assert qa_summary["scientific_defensibility"]["overlap_sliver_summary_json"] == (
        "qa/district_zone_overlap_sliver_summary.json"
    )
    assert qa_summary["scientific_defensibility"]["working_crs_sensitivity_summary_json"] == (
        "qa/working_crs_sensitivity_summary.json"
    )
    assert qa_summary["scientific_defensibility"]["working_crs_sensitivity_comparison_csv"] == (
        "qa/working_crs_sensitivity_comparison.csv"
    )
    assert qa_summary["scientific_defensibility"]["assignment_identity_changes_detected"] is False
    assert qa_summary["scientific_defensibility"]["max_overlap_rule_retained"] is True

    assert contract_manifest["contract"]["version"] == "1.0.0-smoke"
    assert contract_manifest["area_policy"]["method"] == "geodesic"
    assert contract_manifest["outputs"]["basenames"] == {
        "zones": "zones_stage1_acz",
        "districts": "districts_stage1",
    }
    assert contract_manifest["outputs"]["logical_outputs"] == {
        "unit_universe_csv": "unit_universe.csv",
        "zones_shapefile": "boundaries/zones_stage1_acz.shp",
        "districts_shapefile": "boundaries/districts_stage1.shp",
        "overlap_report_csv": "qa/district_zone_overlap.csv",
    }
    assert (
        contract_manifest["logical_schema"]["unit_universe_csv"] == _EXPECTED_UNIT_UNIVERSE_COLUMNS
    )
    assert "stage1_contract_manifest_json" not in contract_manifest["extra_outputs"]
    assert contract_manifest["extra_outputs"]["unit_universe_csv"] == "unit_universe.csv"
    assert (
        contract_manifest["extra_outputs"]["crosswalks_manifest_json"]
        == "crosswalks/crosswalks_manifest.json"
    )

    assert list(unit_universe.columns) == _EXPECTED_UNIT_UNIVERSE_COLUMNS
    assert unit_universe["unit_type"].tolist() == ["zone", "zone", "district", "district"]
    assert unit_universe["level"].tolist() == ["acz", "acz", "district", "district"]

    zone_rows = unit_universe.loc[unit_universe["unit_type"] == "zone"].reset_index(drop=True)
    district_rows = unit_universe.loc[unit_universe["unit_type"] == "district"].reset_index(
        drop=True
    )

    assert zone_rows["unit_id"].tolist() == ["zone_a", "zone_b"]
    assert zone_rows["unit_code"].tolist() == ["ZA", "ZB"]
    assert zone_rows["unit_name"].tolist() == ["ZONE A", "ZONE B"]
    assert zone_rows["parent_level"].isna().all()
    assert zone_rows["parent_id"].isna().all()
    assert zone_rows["parent_code"].isna().all()
    assert zone_rows["parent_name"].isna().all()
    assert zone_rows["area_sqkm"].gt(0).all()

    assert district_rows["unit_id"].tolist() == ["District_1", "District_2"]
    assert district_rows["unit_code"].isna().all()
    assert district_rows["unit_name"].tolist() == ["DISTRICT 1", "DISTRICT 2"]
    assert district_rows["parent_level"].tolist() == ["acz", "acz"]
    assert district_rows["parent_id"].tolist() == ["zone_a", "zone_b"]
    assert district_rows["parent_code"].tolist() == ["ZA", "ZB"]
    assert district_rows["parent_name"].tolist() == ["ZONE A", "ZONE B"]
    assert district_rows["area_sqkm"].gt(0).all()
