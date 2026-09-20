from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from geo_data_prep.qa.reports import write_district_zone_overlap_csv


def _overlap_fixture() -> pd.DataFrame:
    rows = [
        {
            "district_id": "D2",
            "zone_id": "C",
            "zone_name": "Zone C",
            "zone_code": "ZC",
            "district_area": 100.0,
            "intersection_area": 100.0,
            "district_area_sq_m": 100.0,
            "intersection_area_sq_m": 100.0,
            "district_intersection_sum_sq_m": 100.0,
            "district_uncovered_area_sq_m": 0.0,
            "district_uncovered_frac": 0.0,
            "ovl_share": 1.0,
            "rank": 1,
            "is_assigned": True,
            "assigned_share": 1.0,
            "tie_candidate_count": 1,
            "tie_break_applied": False,
            "assignment_method": "max_intersection_share",
            "area_method": "projected",
            "area_units": "sq_m",
            "working_crs": "EPSG:3857",
            "share_basis": "intersection_over_district_area",
            "assignment_status": "assigned",
            "legacy_zone_id": None,
            "legacy_zone_name": None,
            "legacy_zone_code": None,
            "legacy_assignment_present": False,
            "legacy_assignment_match": None,
            "legacy_assignment_disagreement": None,
        },
        {
            "district_id": "D1",
            "zone_id": "B",
            "zone_name": "Zone B",
            "zone_code": "ZB",
            "district_area": 100.0,
            "intersection_area": 10.0,
            "district_area_sq_m": 100.0,
            "intersection_area_sq_m": 10.0,
            "district_intersection_sum_sq_m": 100.0,
            "district_uncovered_area_sq_m": 0.0,
            "district_uncovered_frac": 0.0,
            "ovl_share": 0.10,
            "rank": 2,
            "is_assigned": False,
            "assigned_share": None,
            "tie_candidate_count": 1,
            "tie_break_applied": False,
            "assignment_method": "max_intersection_share",
            "area_method": "projected",
            "area_units": "sq_m",
            "working_crs": "EPSG:3857",
            "share_basis": "intersection_over_district_area",
            "assignment_status": "candidate_not_selected",
            "legacy_zone_id": "B",
            "legacy_zone_name": "Zone B",
            "legacy_zone_code": "ZB",
            "legacy_assignment_present": True,
            "legacy_assignment_match": True,
            "legacy_assignment_disagreement": False,
        },
        {
            "district_id": "D1",
            "zone_id": "A",
            "zone_name": "Zone A",
            "zone_code": "ZA",
            "district_area": 100.0,
            "intersection_area": 90.0,
            "district_area_sq_m": 100.0,
            "intersection_area_sq_m": 90.0,
            "district_intersection_sum_sq_m": 100.0,
            "district_uncovered_area_sq_m": 0.0,
            "district_uncovered_frac": 0.0,
            "ovl_share": 0.90,
            "rank": 1,
            "is_assigned": True,
            "assigned_share": 0.90,
            "tie_candidate_count": 1,
            "tie_break_applied": False,
            "assignment_method": "max_intersection_share",
            "area_method": "projected",
            "area_units": "sq_m",
            "working_crs": "EPSG:3857",
            "share_basis": "intersection_over_district_area",
            "assignment_status": "assigned",
            "legacy_zone_id": "B",
            "legacy_zone_name": "Zone B",
            "legacy_zone_code": "ZB",
            "legacy_assignment_present": True,
            "legacy_assignment_match": False,
            "legacy_assignment_disagreement": True,
        },
    ]
    return pd.DataFrame(rows)


def test_overlap_report_writes_main_csv_and_richer_sidecars_in_stable_order(tmp_path: Path) -> None:
    out_csv = tmp_path / "qa" / "district_zone_overlap.csv"
    result = write_district_zone_overlap_csv(_overlap_fixture(), out_csv=out_csv)

    assert result.path == out_csv
    assert result.rows == 3
    assert set(result.sidecars) == {
        "summary_json",
        "validations_json",
        "issues_csv",
        "metrics_csv",
        "sliver_summary_json",
    }

    main = pd.read_csv(out_csv)
    assert main[["district_id", "rank", "zone_id"]].to_dict(orient="records") == [
        {"district_id": "D1", "rank": 1, "zone_id": "A"},
        {"district_id": "D1", "rank": 2, "zone_id": "B"},
        {"district_id": "D2", "rank": 1, "zone_id": "C"},
    ]

    summary = json.loads(result.sidecars["summary_json"].read_text(encoding="utf-8"))
    validations = json.loads(result.sidecars["validations_json"].read_text(encoding="utf-8"))
    issues = pd.read_csv(result.sidecars["issues_csv"])
    metrics = pd.read_csv(result.sidecars["metrics_csv"])
    sliver = json.loads(result.sidecars["sliver_summary_json"].read_text(encoding="utf-8"))

    assert summary["rows"] == 3
    assert summary["districts"] == 2
    assert summary["assigned_rows"] == 2
    assert summary["assigned_districts"] == 2
    assert summary["tie_break_rows"] == 0
    assert summary["legacy_assignment_disagreement_rows"] == 1
    assert summary["status"] == "fail"
    assert summary["ok"] is False
    assert validations == summary["validations"]

    assert metrics["status"].tolist() == ["warn", "pass", "pass", "na", "fail"]
    assert metrics["ok"].tolist() == [True, True, True, True, False]
    assert len(metrics) == 5
    assert sliver["rows"] == 3
    assert sliver["candidate_only_rows"] == 1
    assert sliver["share_counts_candidate_only"][2] == {"cutoff": 0.001, "count": 0}
    assert sliver["share_counts_candidate_only"][3] == {"cutoff": 0.01, "count": 0}

    assert sorted(issues["issue_type"].unique().tolist()) == [
        "legacy_assignment_disagreement",
        "low_assignment_share",
    ]
    assert set(issues["district_id"].tolist()) == {"D1"}


def test_overlap_report_reuses_provided_validation_payload_for_summary_and_validations(
    tmp_path: Path,
) -> None:
    out_csv = tmp_path / "qa" / "district_zone_overlap.csv"
    payload = {
        "qa_enabled": True,
        "status": "pass",
        "ok": True,
        "results": [
            {
                "message": "precomputed validation payload",
                "ok": True,
                "status": "pass",
                "details": {"source": "unit_test"},
            }
        ],
    }

    result = write_district_zone_overlap_csv(
        _overlap_fixture(),
        out_csv=out_csv,
        validation_payload=payload,
    )

    summary = json.loads(result.sidecars["summary_json"].read_text(encoding="utf-8"))
    validations = json.loads(result.sidecars["validations_json"].read_text(encoding="utf-8"))

    assert summary["status"] == "pass"
    assert summary["ok"] is True
    assert summary["validations"] == payload["results"]
    assert validations == payload["results"]


def test_overlap_report_uses_provided_thresholds_for_summary_and_issue_table(
    tmp_path: Path,
) -> None:
    out_csv = tmp_path / "qa" / "district_zone_overlap.csv"
    result = write_district_zone_overlap_csv(
        _overlap_fixture(),
        out_csv=out_csv,
        share_warn_below=0.85,
        share_fail_below=0.80,
        legacy_disagreement_warn_above=2,
        legacy_disagreement_fail_above=3,
    )

    summary = json.loads(result.sidecars["summary_json"].read_text(encoding="utf-8"))
    issues = pd.read_csv(result.sidecars["issues_csv"])

    assert summary["status"] == "pass"
    assert summary["ok"] is True
    assert [item["status"] for item in summary["validations"]] == [
        "pass",
        "pass",
        "pass",
        "na",
        "pass",
    ]

    assert issues["issue_type"].tolist() == ["legacy_assignment_disagreement"]
    assert issues["district_id"].tolist() == ["D1"]


def test_overlap_report_writes_schema_stable_empty_issue_csv(tmp_path: Path) -> None:
    out_csv = tmp_path / "qa" / "district_zone_overlap.csv"
    clean = pd.DataFrame(
        [
            {
                "district_id": "D0",
                "zone_id": "Z0",
                "zone_name": "Zone 0",
                "zone_code": "ZZ",
                "district_area": 100.0,
                "intersection_area": 100.0,
                "district_area_sq_m": 100.0,
                "intersection_area_sq_m": 100.0,
                "district_intersection_sum_sq_m": 100.0,
                "district_uncovered_area_sq_m": 0.0,
                "district_uncovered_frac": 0.0,
                "ovl_share": 1.0,
                "rank": 1,
                "is_assigned": True,
                "assigned_share": 1.0,
                "tie_candidate_count": 1,
                "tie_break_applied": False,
                "assignment_method": "max_intersection_share",
                "area_method": "projected",
                "area_units": "sq_m",
                "working_crs": "EPSG:3857",
                "share_basis": "intersection_over_district_area",
                "assignment_status": "assigned",
                "legacy_zone_id": None,
                "legacy_zone_name": None,
                "legacy_zone_code": None,
                "legacy_assignment_present": False,
                "legacy_assignment_match": None,
                "legacy_assignment_disagreement": None,
            }
        ]
    )

    result = write_district_zone_overlap_csv(clean, out_csv=out_csv)
    issues = pd.read_csv(result.sidecars["issues_csv"])

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


def test_overlap_report_writes_schema_stable_empty_metrics_csv_when_qa_disabled(
    tmp_path: Path,
) -> None:
    out_csv = tmp_path / "qa" / "district_zone_overlap.csv"
    result = write_district_zone_overlap_csv(_overlap_fixture(), out_csv=out_csv, qa_enabled=False)

    issues = pd.read_csv(result.sidecars["issues_csv"])
    metrics = pd.read_csv(result.sidecars["metrics_csv"])

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
    assert list(metrics.columns) == ["validator", "status", "ok"]
    assert metrics.empty
