from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from geo_data_prep.exports.contract import write_stage1_contract_manifest


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        schema_version="1.0",
        contract=SimpleNamespace(
            stage="stage_1",
            name="geo_data_prep_stage1",
            version="1.0.0-test",
            canonical_upstream=True,
            downstreams_adapt_later=True,
        ),
        crs=SimpleNamespace(working_crs="EPSG:3857", plot_crs="EPSG:4326"),
        area_policy=SimpleNamespace(
            method="geodesic",
            projected_crs="EPSG:3857",
            geodesic_ellipsoid="WGS84",
            units="sq_km",
            include_method_metadata=True,
        ),
        qa=SimpleNamespace(
            enabled=True,
            thresholds={
                "overlap_share": {"warn_below": 0.95, "fail_below": 0.8},
                "area_relative_difference": {"warn_above": 0.01, "fail_above": 0.05},
                "unassigned_units": {"warn_above": 0, "fail_above": 0},
                "legacy_assignment_disagreement": {"warn_above": 0, "fail_above": 0},
                "invalid_geometries": {"warn_above": 0, "fail_above": 0},
            },
        ),
    )


def test_contract_manifest_freezes_stage1_logical_outputs_and_schema(tmp_path: Path) -> None:
    out = write_stage1_contract_manifest(
        out_dir=tmp_path,
        cfg=_cfg(),
        zone_level_label="acz",
        district_level_label="district",
        zones_basename="zones_stage1_acz",
        districts_basename="districts_stage1",
        extra_outputs={
            "unit_universe_csv": "unit_universe.csv",
            "overlap_report_csv": "qa/district_zone_overlap.csv",
            "combined_zone_shapefile": "boundaries/zones_stage1_acz.shp",
        },
    )

    manifest = json.loads(out.manifest_path.read_text(encoding="utf-8"))

    assert out.manifest_path == tmp_path / "contract" / "stage1_contract_manifest.json"
    assert manifest["contract"] == {
        "canonical_upstream": True,
        "downstreams_adapt_later": True,
        "name": "geo_data_prep_stage1",
        "stage": "stage_1",
        "version": "1.0.0-test",
    }
    assert manifest["schema_version"] == "1.0"
    assert manifest["levels"] == {"zone": "acz", "district": "district"}
    assert manifest["outputs"] == {
        "basenames": {"zones": "zones_stage1_acz", "districts": "districts_stage1"},
        "logical_outputs": {
            "unit_universe_csv": "unit_universe.csv",
            "zones_shapefile": "boundaries/zones_stage1_acz.shp",
            "districts_shapefile": "boundaries/districts_stage1.shp",
            "overlap_report_csv": "qa/district_zone_overlap.csv",
        },
    }
    assert manifest["logical_schema"] == {
        "unit_universe_csv": [
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
        ],
        "zones_shapefile_logical_fields": ["zone_id", "zone_name", "zone_code"],
        "districts_shapefile_logical_fields": [
            "district_id",
            "district_name",
            "district_code",
            "zone_id",
            "zone_name",
            "zone_code",
            "ovl_share",
        ],
        "districts_shapefile_physical_fields": [
            "dist_id",
            "dist_name",
            "dist_code",
            "zone_id",
            "zone_name",
            "zone_code",
            "ovl_share",
        ],
        "overlap_report_csv": None,
    }
    assert manifest["notes"] == {
        "legacy_alias_fields_are_not_added_to_canonical_stage1_outputs": True,
        "rich_provenance_and_crosswalks_live_in_sidecars": True,
        "schema_governance": {
            "downstream_revalidation_required_before_schema_change": True,
            "known_stage3_contract_consumers": ["RP1_Project/merge_af_ba_panels.py"],
            "unit_universe_and_boundary_schemas_require_contract_versioning_when_changed": True,
        },
        "stage1_is_canonical_upstream_contract": True,
        "unit_universe_contract_revision": (
            "The logical contract includes unit_code and parent_code in the "
            "unit_universe.csv schema while preserving unit_id and parent_id as the "
            "canonical relational keys."
        ),
    }
    assert manifest["extra_outputs"] == {
        "combined_zone_shapefile": "boundaries/zones_stage1_acz.shp",
        "overlap_report_csv": "qa/district_zone_overlap.csv",
        "unit_universe_csv": "unit_universe.csv",
    }


def test_contract_manifest_honours_custom_output_filenames(tmp_path: Path) -> None:
    out = write_stage1_contract_manifest(
        out_dir=tmp_path,
        cfg=_cfg(),
        zone_level_label="aez",
        district_level_label="district",
        zones_basename="zones_custom",
        districts_basename="districts_custom",
        unit_universe_filename="unit_universe_custom.csv",
        overlap_report_filename="district_zone_overlap_custom.csv",
        manifest_filename="contract_custom.json",
    )

    manifest = json.loads(out.manifest_path.read_text(encoding="utf-8"))
    assert out.manifest_path.name == "contract_custom.json"
    assert manifest["levels"] == {"zone": "aez", "district": "district"}
    assert manifest["outputs"]["logical_outputs"] == {
        "unit_universe_csv": "unit_universe_custom.csv",
        "zones_shapefile": "boundaries/zones_custom.shp",
        "districts_shapefile": "boundaries/districts_custom.shp",
        "overlap_report_csv": "qa/district_zone_overlap_custom.csv",
    }
    assert manifest["logical_schema"]["unit_universe_csv"] == [
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
