from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from rp1_analysis_v1.config import load_configuration_bundle, satscan_parameters
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.satscan_io import (
    MODEL_DISCRETE_POISSON, MODEL_SPACE_TIME_PERMUTATION, REPORTING_HIERARCHICAL,
    SaTScanIOError, generate_parameter_file, parse_cluster_file, parse_membership_file, sha256_text,
)
from rp1_analysis_v1.secondary_clusters import (
    _window_bounds, generate_parameter_file as generate_governed_parameter_file, load_scan_scenarios,
)
from .satscan_reference_implementations import (
    SaTScanReferenceError, expected_frozen_common_assignments_reference,
    expected_model_assignments_reference, monthly_study_bounds_reference,
    parse_parameter_assignments_reference,
)

SUBPROJECT = Path(__file__).resolve().parents[2]
FIXTURE = SUBPROJECT / "tests/fixtures/reference_methods/satscan"


def _rng() -> dict[str, object]:
    return {"report_cluster_rank": True, "scientific_seed": 20260822,
            "user_defined_random_seed_supported": False, "user_defined_random_seed_parameter": None,
            "rng_authority": "engine_deterministic_internal_seed",
            "engine_rng_behaviour": "same_internal_seed_for_identical_input"}


def _raw_analysis() -> dict:
    return yaml.safe_load((SUBPROJECT / "config/analysis_contract.yml").read_text(encoding="utf-8"))


def _production_bundle():
    paths = ProjectPaths(SUBPROJECT)
    bundle = load_configuration_bundle(paths.root / "config")
    scenarios = {item.scenario_id: item for item in load_scan_scenarios(bundle.analysis)}
    return bundle, scenarios, satscan_parameters(bundle.analysis)


def test_satscan_reference_fixture_uses_exact_core_result_family() -> None:
    expected = {"known_good", "known_good.col.txt", "known_good.gis.txt", "expected_parser.json"}
    assert {path.name for path in FIXTURE.iterdir() if path.is_file()} == expected
    assert not (FIXTURE / "known_good.txt").exists()
    assert not (FIXTURE / "known_good.provenance.json").exists()


def test_satscan_reference_parser_fixture_is_stable() -> None:
    clusters = parse_cluster_file(FIXTURE / "known_good.col.txt", alpha=0.05)
    membership = parse_membership_file(FIXTURE / "known_good.gis.txt", alpha=0.05)
    assert clusters.shape == (1, 16)
    assert membership.shape == (2, 4)
    assert clusters.iloc[0]["cluster_id"] == 1
    assert clusters.iloc[0]["cluster_rank"] == 1
    assert membership["location_id"].tolist() == ["1", "2"]


@pytest.mark.parametrize(("month", "expected_end"), [
    ("2023-01", "2023/1/31"), ("2023-02", "2023/2/28"),
    ("2024-02", "2024/2/29"), ("2024-04", "2024/4/30"), ("2024-12", "2024/12/31"),
])
def test_independent_monthly_boundary_reference_covers_calendar_edges(month: str, expected_end: str) -> None:
    start, end = monthly_study_bounds_reference(month, month)
    year, month_number = (int(part) for part in month.split("-"))
    assert start == f"{year}/{month_number}/1"
    assert end == expected_end


def test_independent_monthly_boundary_reference_rejects_reversed_window() -> None:
    with pytest.raises(SaTScanReferenceError, match="reversed"):
        monthly_study_bounds_reference("2024-12", "2024-11")


@pytest.mark.parametrize("end_month", ["2023-01", "2023-02", "2024-02", "2024-04", "2024-12"])
def test_production_wrapper_matches_independent_calendar_reference(end_month: str) -> None:
    _, scenarios, params = _production_bundle()
    scenario = scenarios["VIIRS_STP_PRIMARY"]
    end = pd.Period(end_month, freq="M")
    start = pd.Period(end_month, freq="M")
    expected_start, expected_end = monthly_study_bounds_reference(end_month, end_month)
    text = generate_governed_parameter_file(
        scenario, case_path="case.cas", population_path=None, location_path="districts.geo",
        results_prefix="results/out", start=start, end=end, params=params,
    )
    assignments = parse_parameter_assignments_reference(text)
    assert assignments["StartDate"] == expected_start
    assert assignments["EndDate"] == expected_end


def test_current_production_scenario_bounds_match_independent_config_reference() -> None:
    raw = _raw_analysis()
    bundle, scenarios, params = _production_bundle()
    windows = raw["study"]["temporal_windows"]
    expected_by_scenario = {
        "MCD64A1_POISSON_PRIMARY": monthly_study_bounds_reference(windows["long_run"]["start"], windows["long_run"]["end"]),
        "VIIRS_STP_PRIMARY": monthly_study_bounds_reference(windows["overlap_monthly"]["start"], windows["overlap_monthly"]["end"]),
    }
    assert expected_by_scenario == {
        "MCD64A1_POISSON_PRIMARY": ("2001/1/1", "2024/12/31"),
        "VIIRS_STP_PRIMARY": ("2012/2/1", "2024/12/31"),
    }
    for scenario_id, expected in expected_by_scenario.items():
        scenario = scenarios[scenario_id]
        start, end = _window_bounds(bundle.analysis, scenario.temporal_window)
        text = generate_governed_parameter_file(
            scenario, case_path="case.cas", population_path="population.pop" if scenario.requires_population else None,
            location_path="districts.geo", results_prefix="results/out", start=start, end=end, params=params,
        )
        assignments = parse_parameter_assignments_reference(text)
        assert (assignments["StartDate"], assignments["EndDate"]) == expected


def test_frozen_common_scan_contract_is_projected_to_both_production_scenarios() -> None:
    raw = _raw_analysis()
    common = raw["secondary_analysis"]["common"]
    assert common["max_spatial_percent"] == 50
    assert common["max_temporal_months"] == 12
    assert common["monte_carlo_replicates"] == 999
    assert common["cluster_type"] == "high_only"
    assert common["reporting_method"] == "hierarchical_non_overlapping"
    assert common["geographical_overlap"] is False
    assert common["gini_optimised_reporting"] is False
    bundle, scenarios, params = _production_bundle()
    expected_common = dict(expected_frozen_common_assignments_reference())
    for scenario in scenarios.values():
        start, end = _window_bounds(bundle.analysis, scenario.temporal_window)
        text = generate_governed_parameter_file(
            scenario, case_path="case.cas", population_path="population.pop" if scenario.requires_population else None,
            location_path="districts.geo", results_prefix="results/out", start=start, end=end, params=params,
        )
        assignments = parse_parameter_assignments_reference(text)
        for key, expected in expected_common.items():
            assert assignments[key] == expected, (scenario.scenario_id, key)


def test_poisson_and_stp_parameter_authorities_match_independent_model_reference() -> None:
    common = dict(
        reporting=REPORTING_HIERARCHICAL, case_path="cases.cas", coordinate_path="districts.geo",
        results_prefix="results/out", max_spatial_percent=37, max_temporal_months=8,
        monte_carlo_replicates=149, analysis_type="retrospective", cluster_type="high_only",
        spatial_window_shape="circular", geographical_overlap=False, gini_optimised_reporting=False, **_rng(),
    )
    poisson = generate_parameter_file(
        scenario_id="POISSON_SYNTHETIC", product="mcd64a1", model=MODEL_DISCRETE_POISSON,
        population_path="population.pop", start_date="2020/1/1", end_date="2021/12/31", **common,
    )
    stp = generate_parameter_file(
        scenario_id="STP_SYNTHETIC", product="viirs", model=MODEL_SPACE_TIME_PERMUTATION,
        population_path=None, start_date="2020/1/1", end_date="2021/12/31", **common,
    )
    assert sha256_text(poisson) == sha256_text(poisson)
    assert sha256_text(poisson) != sha256_text(stp)
    for text, model, population in ((poisson, "discrete_poisson", "population.pop"), (stp, "space_time_permutation", None)):
        assignments = parse_parameter_assignments_reference(text)
        expected_model = expected_model_assignments_reference(model=model, population_path=population)
        for key, expected in expected_model.items():
            assert assignments[key] == expected
        assert assignments["ReportHierarchicalClusters"] == "y"
        assert assignments["CriteriaForReportingSecondaryClusters"] == "0"
        assert assignments["ReportGiniClusters"] == "n"
        assert assignments["MaxSpatialSizeInPopulationAtRisk"] == "37"
        assert assignments["MaxTemporalSize"] == "8"
        assert assignments["MonteCarloReps"] == "149"
        assert assignments["ReportClusterRank"] == "y"
        assert "RandomSeed" not in assignments


def test_reference_and_production_reject_same_model_exposure_illegalities() -> None:
    base = dict(
        scenario_id="SYN", product="synthetic", reporting=REPORTING_HIERARCHICAL,
        case_path="case.cas", coordinate_path="district.geo", results_prefix="results/out",
        start_date="2020/1/1", end_date="2021/12/31", max_spatial_percent=50,
        max_temporal_months=12, monte_carlo_replicates=999, analysis_type="retrospective",
        cluster_type="high_only", spatial_window_shape="circular", geographical_overlap=False,
        gini_optimised_reporting=False, **_rng(),
    )
    with pytest.raises(SaTScanReferenceError, match="requires population"):
        expected_model_assignments_reference(model="discrete_poisson", population_path=None)
    with pytest.raises(SaTScanIOError, match="requires a population"):
        generate_parameter_file(model=MODEL_DISCRETE_POISSON, population_path=None, **base)
    with pytest.raises(SaTScanReferenceError, match="forbids population"):
        expected_model_assignments_reference(model="space_time_permutation", population_path="bad.pop")
    with pytest.raises(SaTScanIOError, match="must not receive exposure"):
        generate_parameter_file(model=MODEL_SPACE_TIME_PERMUTATION, population_path="bad.pop", **base)
