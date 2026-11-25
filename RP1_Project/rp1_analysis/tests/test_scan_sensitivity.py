import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from rp1_analysis_v1 import scan_sensitivity as scan
from rp1_analysis_v1.satscan_io import MODEL_DISCRETE_POISSON, ParsedSaTScanResults

EXPOSURE = {"1": Decimal("50"), "2": Decimal("50.0000000001"), "3": Decimal("49.9999999999")}


def _inputs(root: Path) -> tuple[Path, Path, Path]:
    cases, coordinates, population = (root / name for name in ("cases", "coordinates", "population"))
    cases.write_text("1 11 2001/1/1\n2 22 2001/1/1\n3 33 2001/1/1\n", encoding="utf-8")
    coordinates.write_text("1 0 0\n2 1 1\n3 2 2\n", encoding="utf-8")
    population.write_text(
        "".join(f"{unit} 2001/{month}/1 50.000000000\n" for unit in EXPOSURE for month in (1, 2)),
        encoding="utf-8",
    )
    return cases, coordinates, population


def test_restricted_scan_uses_strict_cutoff_for_all_three_files(tmp_path):
    exposure, retained, filtered = scan._subsets(*_inputs(tmp_path), 2, EXPOSURE, cutoff_km2=50)
    assert exposure == EXPOSURE
    assert retained == {"2"}
    assert filtered["case_path"] == [["2", "22", "2001/1/1"]]
    assert filtered["coordinate_path"] == [["2", "1", "1"]]
    assert len(filtered["population_path"]) == 2
    assert {row[2] for row in filtered["population_path"]} == {"50.000000000"}


def test_restricted_scan_rejects_missing_month(tmp_path):
    cases, coordinates, population = _inputs(tmp_path)
    rows = population.read_text(encoding="utf-8").splitlines()
    population.write_text("\n".join(rows[:-1]), encoding="utf-8")
    with pytest.raises(ValueError, match="monthly exposure spine"):
        scan._subsets(cases, coordinates, population, 2, EXPOSURE, cutoff_km2=50)


def test_restricted_scan_rejects_an_unproven_roster(tmp_path):
    inputs = _inputs(tmp_path)
    with pytest.raises(ValueError, match="roster IDs"):
        scan._subsets(*inputs, 2, {"1": Decimal("50"), "2": Decimal("50.1")}, cutoff_km2=50)
    with pytest.raises(ValueError, match="does not reproduce"):
        scan._subsets(*inputs, 2, {**EXPOSURE, "2": Decimal("50.1")}, cutoff_km2=50)


def test_restricted_scan_changes_only_requested_parameter_values():
    original = "[Input]\nCaseFile=primary.cas\nMonteCarloReps=999\nResultsFile=primary\n"
    assert scan._retarget_parameter(original, {"CaseFile": "modis_gt50.cas", "ResultsFile": "modis_gt50"}) == (
        "[Input]\nCaseFile=modis_gt50.cas\nMonteCarloReps=999\nResultsFile=modis_gt50\n"
    )
    with pytest.raises(ValueError, match="exactly one"):
        scan._retarget_parameter(original + "CaseFile=duplicate.cas\n", {"CaseFile": "modis_gt50.cas"})


def _native_windows(windows):
    clusters, members = [], []
    for rank, start, end, locations, observed in windows:
        clusters.append({
            "cluster_id": rank, "cluster_rank": rank, "start_date": start, "end_date": end,
            "case_count": observed, "expected_count": 4.0, "observed_expected_ratio": observed / 4.0,
            "relative_risk": 3.0, "log_likelihood_ratio": 10.0, "p_value": 0.01,
        })
        members.extend({"cluster_id": rank, "location_id": location} for location in locations)
    return ParsedSaTScanResults("example", MODEL_DISCRETE_POISSON, pd.DataFrame(clusters), pd.DataFrame(members), {})


def test_window_comparison_pairs_dates_and_shared_footprints_across_ranks():
    primary = _native_windows([
        (1, "2001/1/1", "2001/2/28", {"1", "2", "3"}, 12),
        (2, "2001/1/1", "2001/2/28", {"4"}, 8),
        (3, "2001/3/1", "2001/3/31", {"1", "2"}, 7),
    ])
    restricted = _native_windows([
        (1, "2001/1/1", "2001/2/28", {"4"}, 8),
        (2, "2001/1/1", "2001/2/28", {"1", "2"}, 10),
        (3, "2001/4/1", "2001/4/30", {"1", "2"}, 7),
    ])
    comparison = scan._window_comparison(primary, restricted, {"1", "2", "4"})
    matched = comparison.iloc[0]
    assert matched["match_status"] == "matched_exact_shared_domain"
    assert matched["primary_leading_window"] and not matched["restricted_leading_window"]
    assert matched["rank_change"] == 1
    assert matched["observed_change"] == -2
    assert matched["observed_expected_ratio_change"] == -0.5
    assert matched["primary_duration_months"] == matched["overlap_months"] == 2
    assert matched["primary_full_districts"] == 3
    assert matched["primary_shared_districts"] == matched["shared_district_intersection"] == 2
    assert matched["shared_district_jaccard"] == 1.0
    assert comparison["match_status"].tolist() == [
        "matched_exact_shared_domain", "matched_exact_shared_domain", "primary_only", "restricted_only",
    ]
    assert pd.isna(comparison.iloc[2]["restricted_cluster_id"])
    assert pd.isna(comparison.iloc[3]["primary_cluster_id"])


def test_window_comparison_rejects_ambiguous_keys():
    primary = _native_windows([
        (1, "2001/1/1", "2001/1/31", {"1"}, 12),
        (2, "2001/1/1", "2001/1/31", {"1", "2"}, 8),
    ])
    with pytest.raises(ValueError, match="ambiguous matching identity"):
        scan._window_comparison(primary, primary, {"1"})


def test_window_comparison_preserves_entirely_excluded_footprints():
    primary = _native_windows([
        (1, "2001/1/1", "2001/1/31", {"1"}, 12),
        (2, "2001/1/1", "2001/1/31", {"2"}, 8),
    ])
    restricted = _native_windows([(1, "2001/1/1", "2001/1/31", {"3"}, 8)])
    comparison = scan._window_comparison(primary, restricted, {"3"})
    assert comparison["match_status"].tolist() == ["primary_only", "primary_only", "restricted_only"]
    assert comparison["primary_shared_districts"].dropna().tolist() == [0, 0]


def test_transferred_baseline_requires_selected_original_identity(tmp_path):
    root = tmp_path / "secondary"
    section = root / scan.SECONDARY_PREFIX
    tables = section / "tables"
    tables.mkdir(parents=True)
    for name in (
        "secondary_run_registry.csv", "secondary_scan_specification_registry.csv", "secondary_location_authority.csv",
    ):
        (tables / name).touch()
    configuration = root / "00_scaffold"
    configuration.mkdir()
    (configuration / "realised_configuration.json").touch()
    status = {
        "external_execution_state": "RESULTS_VALIDATED",
        "external_execution_evidence": "RESULT_FILES_ONLY",
        "validated_model_count": 2,
        "run_local_publication_source_manifest": f"{scan.SECONDARY_PREFIX}/manifest.json",
    }
    (section / "secondary_external_execution_status.json").write_text(json.dumps(status), encoding="utf-8")
    (section / "manifest.json").write_text(json.dumps({
        "schema": "rp1-satscan-run-local-publication-sources-v2",
        "secondary_run_id": "stored_sec",
        "external_execution_state": status["external_execution_state"],
        "external_execution_evidence": status["external_execution_evidence"],
        "model_count": status["validated_model_count"],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Stored primary secondary-run identity"):
        scan._load_baseline(root, expected_run_id="different_sec", enforce_freshness=False)


def test_restricted_derived_family_is_atomic_and_retryable(tmp_path, monkeypatch):
    example = pd.DataFrame({"value": [1]})
    result = scan.RestrictedScanResult({"total": 1}, example, example, example, example)
    monkeypatch.setattr(scan, "_read_scan", lambda *args, **kwargs: result)
    write = scan._write_json

    def fail_after_table_writes(path, contents):
        assert {file.name for file in path.parent.iterdir()} == set(scan.RESULT_NAMES.values())
        raise OSError("simulated interrupted summary write")

    arguments = {"baseline_secondary_dir": tmp_path, "run_dir": tmp_path}
    monkeypatch.setattr(scan, "_write_json", fail_after_table_writes)
    with pytest.raises(OSError, match="simulated"):
        scan.integrate_scan_sensitivity(**arguments)
    assert not scan.scan_sensitivity_summary_path(tmp_path).exists()
    assert not list(tmp_path.iterdir())

    monkeypatch.setattr(scan, "_write_json", write)
    assert scan.integrate_scan_sensitivity(**arguments) == result.summary
    assert set(file.name for file in scan.scan_sensitivity_summary_path(tmp_path).parent.iterdir()) == {
        *scan.RESULT_NAMES.values(), scan.SUMMARY_NAME,
    }
    assert scan.integrate_scan_sensitivity(**arguments) == result.summary
    (tmp_path / scan.DERIVED_DIR / scan.RESULT_NAMES["window_comparison"]).write_text("different", encoding="utf-8")
    with pytest.raises(ValueError, match="does not reconcile"):
        scan.integrate_scan_sensitivity(**arguments)
