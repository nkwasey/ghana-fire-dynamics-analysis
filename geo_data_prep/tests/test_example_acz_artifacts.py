from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

EXAMPLE_RUN_ID = "example_acz"


def _example_run_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "out" / EXAMPLE_RUN_ID


def test_real_example_acz_regenerated_qa_outcome_is_stable() -> None:
    run_dir = _example_run_dir()
    qa_dir = run_dir / "qa"
    contract_dir = run_dir / "contract"

    if not run_dir.exists():
        pytest.skip(
            "Optional regenerated Stage 1 example_acz run is not shipped in the clean repository; "
            "generate it explicitly to qualify the external Stage 1 integration artefacts."
        )

    qa_summary = json.loads((qa_dir / "qa_summary.json").read_text(encoding="utf-8"))
    overlap_summary = json.loads(
        (qa_dir / "district_zone_overlap_summary.json").read_text(encoding="utf-8")
    )
    runtime_validations = json.loads(
        (qa_dir / "runtime_assignment_validations.json").read_text(encoding="utf-8")
    )
    sensitivity_summary = json.loads(
        (qa_dir / "working_crs_sensitivity_summary.json").read_text(encoding="utf-8")
    )
    contract_manifest = json.loads(
        (contract_dir / "stage1_contract_manifest.json").read_text(encoding="utf-8")
    )
    issues = pd.read_csv(qa_dir / "district_zone_overlap_issues.csv")
    unit_universe = pd.read_csv(run_dir / "unit_universe.csv")

    assert qa_summary["status"] == "pass"
    assert qa_summary["ok"] is True
    assert qa_summary["scientific_defensibility"]["assignment_identity_changes_detected"] is False
    assert qa_summary["scientific_defensibility"]["max_overlap_rule_retained"] is True
    assert qa_summary["thresholds"] == {
        "area_relative_difference": {"fail_above": 0.05, "warn_above": 0.01},
        "invalid_geometries": {"fail_above": 0, "warn_above": 0},
        "legacy_assignment_disagreement": {"fail_above": 0, "warn_above": 0},
        "overlap_share": {"fail_below": 0.8, "warn_below": 0.95},
        "unassigned_units": {"fail_above": 0, "warn_above": 0},
    }

    assert overlap_summary["status"] == "pass"
    assert overlap_summary["assigned_districts"] == 260
    assert overlap_summary["assigned_rows"] == 260
    assert overlap_summary["legacy_assignment_disagreement_rows"] == 0
    assert [item["status"] for item in overlap_summary["validations"]] == [
        "pass",
        "pass",
        "pass",
        "pass",
        "na",
    ]
    assert overlap_summary["validations"][0]["details"]["invalid_share_count"] == 0
    # Stage 1 normalises tolerance-level floating-point share overshoot at source, so the
    # regenerated QA contract must not depend on GEOS/PROJ-specific ulp behaviour.
    assert overlap_summary["validations"][0]["details"]["clamped_high_count"] == 0
    assert overlap_summary["validations"][3]["details"] == {
        "fail_above": 0,
        "invalid_geometry_count": 0,
        "layer_invalid_counts": {"districts": 0, "zones": 0},
        "warn_above": 0,
    }

    assert runtime_validations["status"] == "pass"
    assert runtime_validations["ok"] is True
    assert runtime_validations["results"] == overlap_summary["validations"]

    assert sensitivity_summary["assignment_identity_change_count"] == 0
    assert sensitivity_summary["recommendation"] == "retain_max_overlap_rule"

    assert list(unit_universe.columns) == [
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
    assert contract_manifest["notes"]["schema_governance"] == {
        "downstream_revalidation_required_before_schema_change": True,
        "known_stage3_contract_consumers": ["RP1_Project/merge_af_ba_panels.py"],
        "unit_universe_and_boundary_schemas_require_contract_versioning_when_changed": True,
    }

    assert list(issues.columns) == [
        "district_id",
        "zone_id",
        "zone_name",
        "legacy_zone_id",
        "legacy_zone_name",
        "ovl_share",
        "district_uncovered_frac",
        "issue_type",
    ]
    assert issues.empty
