from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

import rp1_analysis_v1.satscan_io as satscan_io

from rp1_analysis_v1.config import load_configuration_bundle, satscan_parameters
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.satscan_io import (
    MODEL_DISCRETE_POISSON,
    MODEL_SPACE_TIME_PERMUTATION,
    REPORTING_HIERARCHICAL,
    ExternalResultValidationError,
    ExternalResultsRequired,
    SaTScanIOError,
    generate_parameter_file as generate_prm,
    parse_cluster_file,
    parse_membership_file,
    run_satscan,
    sha256_file,
    validate_external_results,
)
from rp1_analysis_v1.secondary_clusters import (
    EXTERNAL_RESULTS_REQUIRED,
    SecondaryClusterError,
    _scenario_support_panel,
    _window_bounds,
    build_location_authority,
    build_secondary_input_run,
    generate_parameter_file as generate_governed_prm,
    load_scan_scenarios,
    prepare_case_input,
    prepare_location_input,
    prepare_population_input,
    prepare_time_input,
    validate_case_population_location_keys,
)
from rp1_analysis_v1.validation import validate_data_authorities

SUBPROJECT = Path(__file__).resolve().parents[1]
FIXTURE = SUBPROJECT / "tests/fixtures/reference_methods/satscan"
EXPECTED_FALLBACK_IDS = {
    "Awutu_Senya_East",
    "Mfantseman_Municipal",
    "Fanteakwa_South",
    "Asutifi_South",
}


@pytest.fixture(scope="module")
def governed():
    paths = ProjectPaths(SUBPROJECT)
    bundle = load_configuration_bundle(paths.root / "config")
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    params = satscan_parameters(bundle.analysis)
    location = build_location_authority(
        authorities.district_geometry,
        coordinate_crs=params.coordinate_crs,
        anchor_method=params.coordinate_anchor_method,
    )
    scenarios = {s.scenario_id: s for s in load_scan_scenarios(bundle.analysis)}
    return paths, bundle, authorities, summary, location, scenarios, params


def _seed_kwargs() -> dict[str, object]:
    return {
        "report_cluster_rank": True,
        "scientific_seed": 20260822,
        "user_defined_random_seed_supported": False,
        "user_defined_random_seed_parameter": None,
        "rng_authority": "engine_deterministic_internal_seed",
        "engine_rng_behaviour": "same_internal_seed_for_identical_input",
    }


def test_exact_two_scan_specifications_and_model_exposure_semantics(governed) -> None:
    _, _, _, _, _, scenarios, params = governed
    assert set(scenarios) == {"MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"}
    mcd = scenarios["MCD64A1_POISSON_PRIMARY"]
    viirs = scenarios["VIIRS_STP_PRIMARY"]
    assert mcd.model == MODEL_DISCRETE_POISSON and mcd.population_field is not None
    assert viirs.model == MODEL_SPACE_TIME_PERMUTATION and viirs.population_field is None
    assert mcd.reporting_rule == viirs.reporting_rule == params.reporting_method == REPORTING_HIERARCHICAL


def test_scan_parameters_are_projected_from_analysis_contract(governed) -> None:
    _, bundle, _, _, _, scenarios, params = governed
    common = bundle.analysis.secondary_analysis["common"]
    external = bundle.analysis.secondary_analysis["external_execution"]
    assert params.max_spatial_percent == float(common["max_spatial_percent"]) == 50.0
    assert params.max_temporal_months == int(common["max_temporal_months"]) == 12
    assert params.monte_carlo_replicates == int(common["monte_carlo_replicates"]) == 999
    assert params.report_cluster_rank is True
    assert all(s.max_spatial_percent == params.max_spatial_percent for s in scenarios.values())
    assert all(s.max_temporal_months == params.max_temporal_months for s in scenarios.values())
    assert params.scientific_seed == int(bundle.analysis.reproducibility["primary_seed"]) == 20260822
    assert params.user_defined_random_seed_supported is False
    assert params.user_defined_random_seed_parameter is None
    assert params.rng_authority == str(external["rng_authority"])
    assert params.engine_rng_behaviour == str(external["engine_rng_behaviour"])


def test_governed_coordinate_authority_is_deterministic_and_spatially_valid(governed) -> None:
    _, _, authorities, _, location, _, params = governed
    assert len(location) == 260
    assert location.location_id.tolist() == list(range(1, 261))
    assert location.unit_id.is_unique and location.location_id.is_unique
    assert location.crs.eq(params.coordinate_crs).all()
    assert set(location.anchor_method).issubset({"polygon_centroid", "point_on_surface"})
    assert location.anchor_rule.eq(params.coordinate_anchor_method).all()
    assert location.anchor_covered_by_geometry.all()
    assert np.isfinite(location[["x", "y"]].to_numpy(dtype=float)).all()

    geometry = authorities.district_geometry.set_index(authorities.district_geometry["dist_id"].astype(str))
    for row in location.itertuples(index=False):
        assert geometry.loc[row.unit_id].geometry.covers(Point(float(row.x), float(row.y)))


def test_known_centroid_fallback_regressions_are_generic_rule_outputs(governed) -> None:
    _, _, authorities, _, location, _, _ = governed
    observed = set(location.loc[location["anchor_method"].eq("point_on_surface"), "unit_id"].astype(str))
    assert observed == EXPECTED_FALLBACK_IDS
    geometry = authorities.district_geometry.set_index(authorities.district_geometry["dist_id"].astype(str))
    for unit_id in EXPECTED_FALLBACK_IDS:
        geom = geometry.loc[unit_id].geometry
        assert not geom.covers(geom.centroid)


def test_exact_secondary_populations_and_temporal_support(governed) -> None:
    _, bundle, authorities, _, _, scenarios, _ = governed
    mcd, mcd_ids, _ = _scenario_support_panel(scenarios["MCD64A1_POISSON_PRIMARY"], authorities, bundle.analysis)
    stp, stp_ids, _ = _scenario_support_panel(scenarios["VIIRS_STP_PRIMARY"], authorities, bundle.analysis)
    assert len(mcd_ids) == 250 and len(mcd) == 250 * 288
    assert len(stp_ids) == 249 and len(stp) == 249 * 155
    assert (mcd.yyyymm.min(), mcd.yyyymm.max()) == (200101, 202412)
    assert (stp.yyyymm.min(), stp.yyyymm.max()) == (201202, 202412)


def test_mcd_case_and_fixed_exposure_files_match_governed_source(governed) -> None:
    _, bundle, authorities, _, location, scenarios, _ = governed
    scenario = scenarios["MCD64A1_POISSON_PRIMARY"]
    support, ids, _ = _scenario_support_panel(scenario, authorities, bundle.analysis)
    cases = prepare_case_input(scenario, support, location)
    population = prepare_population_input(scenario, support, location)
    coords = prepare_location_input(location, ids)
    times = prepare_time_input(bundle.analysis, scenario.temporal_window)
    validate_case_population_location_keys(scenario, cases, population, coords, times)
    assert len(population) == 250 * 288
    assert len(coords) == 250
    assert (cases["cases"] > 0).all()
    assert np.equal(cases["cases"], np.rint(cases["cases"])).all()
    assert int(cases["cases"].sum()) == int(pd.to_numeric(support[scenario.case_field], errors="raise").sum())
    assert population.groupby("location_id", observed=True)["population"].nunique().max() == 1


def test_viirs_case_file_has_no_exposure_and_matches_governed_source(governed) -> None:
    _, bundle, authorities, _, location, scenarios, _ = governed
    scenario = scenarios["VIIRS_STP_PRIMARY"]
    support, ids, _ = _scenario_support_panel(scenario, authorities, bundle.analysis)
    cases = prepare_case_input(scenario, support, location)
    coords = prepare_location_input(location, ids)
    times = prepare_time_input(bundle.analysis, scenario.temporal_window)
    validate_case_population_location_keys(scenario, cases, None, coords, times)
    assert len(coords) == 249
    assert (cases["cases"] > 0).all()
    assert int(cases["cases"].sum()) == int(pd.to_numeric(support[scenario.case_field], errors="raise").sum())
    with pytest.raises(SecondaryClusterError, match="must not receive"):
        prepare_population_input(scenario, support, location)


@pytest.mark.parametrize(
    ("end_month", "expected_end"),
    [
        ("2023-01", "2023/1/31"),
        ("2023-02", "2023/2/28"),
        ("2024-02", "2024/2/29"),
        ("2024-04", "2024/4/30"),
        ("2024-12", "2024/12/31"),
    ],
)
def test_production_wrapper_serialises_calendar_aware_month_end(
    governed, end_month: str, expected_end: str
) -> None:
    _, _, _, _, _, scenarios, params = governed
    scenario = scenarios["VIIRS_STP_PRIMARY"]
    end = pd.Period(end_month, freq="M")
    start = pd.Period(year=end.year, month=end.month, freq="M")
    text = generate_governed_prm(
        scenario,
        case_path="x.cas",
        population_path=None,
        location_path="x.geo",
        results_prefix="x",
        start=start,
        end=end,
        params=params,
    )
    assert f"StartDate={end.year}/{end.month}/1" in text
    assert f"EndDate={expected_end}" in text


def test_production_wrapper_projects_current_configured_study_bounds(governed) -> None:
    _, bundle, _, _, _, scenarios, params = governed
    expected = {
        "MCD64A1_POISSON_PRIMARY": ("2001/1/1", "2024/12/31"),
        "VIIRS_STP_PRIMARY": ("2012/2/1", "2024/12/31"),
    }
    for scenario_id, (expected_start, expected_end) in expected.items():
        scenario = scenarios[scenario_id]
        start, end = _window_bounds(bundle.analysis, scenario.temporal_window)
        text = generate_governed_prm(
            scenario,
            case_path="x.cas",
            population_path="x.pop" if scenario.requires_population else None,
            location_path="x.geo",
            results_prefix="x",
            start=start,
            end=end,
            params=params,
        )
        assert f"StartDate={expected_start}" in text
        assert f"EndDate={expected_end}" in text


def test_low_level_parameter_generator_rejects_non_month_end_end_date() -> None:
    with pytest.raises(SaTScanIOError, match="final calendar day"):
        generate_prm(
            scenario_id="SYN",
            product="viirs",
            model=MODEL_SPACE_TIME_PERMUTATION,
            reporting=REPORTING_HIERARCHICAL,
            case_path="x.cas",
            population_path=None,
            coordinate_path="x.geo",
            results_prefix="x",
            start_date="2024/1/1",
            end_date="2024/12/1",
            max_spatial_percent=50,
            max_temporal_months=12,
            monte_carlo_replicates=999,
            analysis_type="retrospective",
            cluster_type="high_only",
            spatial_window_shape="circular",
            geographical_overlap=False,
            gini_optimised_reporting=False,
            **_seed_kwargs(),
        )


def test_low_level_parameter_generator_serialises_injected_values_not_internal_literals() -> None:
    text = generate_prm(
        scenario_id="SYN",
        product="viirs",
        model=MODEL_SPACE_TIME_PERMUTATION,
        reporting=REPORTING_HIERARCHICAL,
        case_path="x.cas",
        population_path=None,
        coordinate_path="x.geo",
        results_prefix="x",
        start_date="2020/1/1",
        end_date="2021/12/31",
        max_spatial_percent=23,
        max_temporal_months=7,
        monte_carlo_replicates=199,
        analysis_type="retrospective",
        cluster_type="high_only",
        spatial_window_shape="circular",
        geographical_overlap=False,
        gini_optimised_reporting=False,
        **_seed_kwargs(),
    )
    assert "MaxSpatialSizeInPopulationAtRisk=23" in text
    assert "MaxTemporalSize=7" in text
    assert "MonteCarloReps=199" in text
    assert "ReportHierarchicalClusters=y" in text
    assert "CriteriaForReportingSecondaryClusters=0" in text
    assert "ReportGiniClusters=n" in text
    assert "ReportClusterRank=y" in text
    assert "IncludeRelativeRisksCensusAreasASCII=n" in text
    assert "; scientific_seed=20260822" in text
    assert "RandomSeed=" not in text


def test_parameter_generator_enforces_model_structural_legality() -> None:
    base = dict(
        scenario_id="SYN",
        product="viirs",
        reporting=REPORTING_HIERARCHICAL,
        case_path="x.cas",
        coordinate_path="x.geo",
        results_prefix="x",
        start_date="2020/1/1",
        end_date="2021/12/31",
        max_spatial_percent=30,
        max_temporal_months=6,
        monte_carlo_replicates=99,
        analysis_type="retrospective",
        cluster_type="high_only",
        spatial_window_shape="circular",
        geographical_overlap=False,
        gini_optimised_reporting=False,
        **_seed_kwargs(),
    )
    with pytest.raises(SaTScanIOError, match="requires a population"):
        generate_prm(model=MODEL_DISCRETE_POISSON, population_path=None, **base)
    with pytest.raises(SaTScanIOError, match="must not receive exposure"):
        generate_prm(model=MODEL_SPACE_TIME_PERMUTATION, population_path="bad.pop", **base)


def test_parameter_generator_rejects_gini_for_frozen_hierarchical_reporting() -> None:
    with pytest.raises(SaTScanIOError, match="forbids Gini optimisation"):
        generate_prm(
            scenario_id="SYN",
            product="mcd64a1",
            model=MODEL_DISCRETE_POISSON,
            reporting=REPORTING_HIERARCHICAL,
            case_path="x.cas",
            population_path="x.pop",
            coordinate_path="x.geo",
            results_prefix="x",
            start_date="2020/1/1",
            end_date="2021/1/31",
            max_spatial_percent=50,
            max_temporal_months=12,
            monte_carlo_replicates=999,
            analysis_type="retrospective",
            cluster_type="high_only",
            spatial_window_shape="circular",
            geographical_overlap=False,
            gini_optimised_reporting=True,
            **_seed_kwargs(),
        )


def test_parameter_generator_does_not_invent_seed_field_when_unsupported() -> None:
    bad = _seed_kwargs()
    bad["user_defined_random_seed_parameter"] = "RandomSeed"
    with pytest.raises(SaTScanIOError, match="must not define"):
        generate_prm(
            scenario_id="SYN",
            product="viirs",
            model=MODEL_SPACE_TIME_PERMUTATION,
            reporting=REPORTING_HIERARCHICAL,
            case_path="x.cas",
            population_path=None,
            coordinate_path="x.geo",
            results_prefix="x",
            start_date="2020/1/1",
            end_date="2021/1/31",
            max_spatial_percent=50,
            max_temporal_months=12,
            monte_carlo_replicates=999,
            analysis_type="retrospective",
            cluster_type="high_only",
            spatial_window_shape="circular",
            geographical_overlap=False,
            gini_optimised_reporting=False,
            **bad,
        )


def test_known_good_parser_fixtures() -> None:
    clusters = parse_cluster_file(FIXTURE / "known_good.col.txt", alpha=0.05)
    membership = parse_membership_file(FIXTURE / "known_good.gis.txt", alpha=0.05)
    expected = json.loads((FIXTURE / "expected_parser.json").read_text(encoding="utf-8"))
    assert clusters.cluster_id.tolist() == expected["significant_cluster_ids"]
    assert clusters.cluster_rank.tolist() == expected["significant_cluster_ids"]
    assert membership.location_id.tolist() == expected["membership"]["1"]


def _external_fixture(tmp_path: Path, *, model: str = MODEL_DISCRETE_POISSON) -> dict[str, object]:
    inp = tmp_path / "inputs"
    res = tmp_path / "results"
    inp.mkdir()
    res.mkdir()
    prm = inp / "x.prm"
    case = inp / "x.cas"
    geo = inp / "x.geo"
    pop = inp / "x.pop"
    case.write_text("1 1 2020/1/1\n2 1 2020/1/1\n", encoding="utf-8")
    geo.write_text("1 1 1\n2 2 2\n", encoding="utf-8")
    population_rel = "inputs/x.pop" if model == MODEL_DISCRETE_POISSON else ""
    if model == MODEL_DISCRETE_POISSON:
        pop.write_text("1 2020/1/1 100\n2 2020/1/1 100\n", encoding="utf-8")
    prm.write_text(
        f"PopulationFile={population_rel}\nResultsFile=results/x\n",
        encoding="utf-8",
    )

    model_label = "Discrete Poisson" if model == MODEL_DISCRETE_POISSON else "Space-Time Permutation"
    report = res / "x"
    col = res / "x.col.txt"
    gis = res / "x.gis.txt"
    report.write_text(
        "SaTScan v10.3.3\n"
        "Retrospective Space-Time analysis\n"
        f"using the {model_label} model.\n"
        "Study period.......................: 2020/1/1 to 2020/12/31\n"
        "Program completed\n",
        encoding="utf-8",
    )
    col.write_bytes((FIXTURE / "known_good.col.txt").read_bytes())
    gis.write_bytes((FIXTURE / "known_good.gis.txt").read_bytes())
    now = max(prm.stat().st_mtime_ns, case.stat().st_mtime_ns, geo.stat().st_mtime_ns) + 5_000_000
    if model == MODEL_DISCRETE_POISSON:
        now = max(now, pop.stat().st_mtime_ns + 5_000_000)
    for path in (report, col, gis):
        os.utime(path, ns=(now, now))

    population_hash = sha256_file(pop) if model == MODEL_DISCRETE_POISSON else ""
    product = "mcd64a1" if model == MODEL_DISCRETE_POISSON else "viirs"
    return {
        "scenario_id": "SYN",
        "model_id": "SYN",
        "product": product,
        "model": model,
        "temporal_start": "2020-01",
        "temporal_end": "2020-12",
        "max_temporal_months": 12,
        "engine_version_authority": "10.3.3",
        "scientific_seed": 20260822,
        "user_defined_random_seed_supported": False,
        "user_defined_random_seed_parameter": None,
        "rng_authority": "engine_deterministic_internal_seed",
        "engine_rng_behaviour": "same_internal_seed_for_identical_input",
        "satscan_executable_sha256": "",
        "prm_path": "inputs/x.prm",
        "prm_sha256": sha256_file(prm),
        "case_path": "inputs/x.cas",
        "case_sha256": sha256_file(case),
        "coordinate_path": "inputs/x.geo",
        "coordinate_sha256": sha256_file(geo),
        "population_path": population_rel,
        "population_sha256": population_hash,
        "results_prefix": "results/x",
        "required_report_path": "results/x",
        "required_cluster_path": "results/x.col.txt",
        "required_membership_path": "results/x.gis.txt",
    }


def test_validated_parser_round_trip_without_external_provenance(tmp_path: Path) -> None:
    row = _external_fixture(tmp_path)
    parsed = validate_external_results(row, run_dir=tmp_path, alpha=0.05)
    assert parsed.scenario_id == "SYN"
    assert parsed.clusters.cluster_rank.tolist() == [1]
    assert parsed.membership.location_id.tolist() == ["1", "2"]
    assert parsed.provenance["external_provenance_sidecar_required"] is False
    assert parsed.provenance["executable_version"] == "10.3.3"
    assert not (tmp_path / "results/x.provenance.json").exists()
    assert not (tmp_path / "results/x.txt").exists()


def test_stp_parser_neutralises_relative_risk(tmp_path: Path) -> None:
    row = _external_fixture(tmp_path, model=MODEL_SPACE_TIME_PERMUTATION)
    parsed = validate_external_results(row, run_dir=tmp_path, alpha=0.05)
    assert parsed.model == MODEL_SPACE_TIME_PERMUTATION
    assert parsed.clusters["relative_risk"].isna().all()


def test_external_results_missing_core_member_is_required_at_low_level(tmp_path: Path) -> None:
    row = _external_fixture(tmp_path)
    (tmp_path / "results/x.gis.txt").unlink()
    with pytest.raises(ExternalResultsRequired):
        validate_external_results(row, run_dir=tmp_path, alpha=0.05)


def test_external_results_reject_wrong_version_model_and_period(tmp_path: Path) -> None:
    for mode, expected in (
        ("version", "version mismatch"),
        ("model", "model identity"),
        ("period", "study period"),
    ):
        other = tmp_path / mode
        other.mkdir()
        row = _external_fixture(other)
        report = other / "results/x"
        content = report.read_text(encoding="utf-8")
        if mode == "version":
            content = content.replace("SaTScan v10.3.3", "SaTScan v10.3.2")
        elif mode == "model":
            content = content.replace("Discrete Poisson", "Space-Time Permutation")
        else:
            content = content.replace("2020/12/31", "2020/11/30")
        report.write_text(content, encoding="utf-8")
        newest = max((other / "inputs/x.prm").stat().st_mtime_ns, (other / "inputs/x.cas").stat().st_mtime_ns, (other / "inputs/x.geo").stat().st_mtime_ns, (other / "inputs/x.pop").stat().st_mtime_ns) + 5_000_000
        os.utime(report, ns=(newest, newest))
        with pytest.raises(ExternalResultValidationError, match=expected):
            validate_external_results(row, run_dir=other, alpha=0.05)


def test_external_parser_rejects_malformed_cluster_output(tmp_path: Path) -> None:
    row = _external_fixture(tmp_path)
    col = tmp_path / "results/x.col.txt"
    col.write_text("Cluster Location X\n1 1 2\n", encoding="utf-8")
    newest = max((tmp_path / "inputs/x.prm").stat().st_mtime_ns, (tmp_path / "inputs/x.cas").stat().st_mtime_ns, (tmp_path / "inputs/x.geo").stat().st_mtime_ns, (tmp_path / "inputs/x.pop").stat().st_mtime_ns) + 5_000_000
    os.utime(col, ns=(newest, newest))
    with pytest.raises(ExternalResultValidationError, match="fewer than 11 fields"):
        validate_external_results(row, run_dir=tmp_path, alpha=0.05)


def test_python_side_secondary_build_records_external_deferral_and_exact_hashes(governed) -> None:
    paths, bundle, authorities, *_ = governed
    run_ids = ["pytest_secondary_repeatability_a", "pytest_secondary_repeatability_b"]
    targets = [paths.resolve_inside(bundle.output.run_root) / run_id for run_id in run_ids]
    for target in targets:
        if target.exists():
            shutil.rmtree(target)
    try:
        runs = [
            build_secondary_input_run(paths=paths, bundle=bundle, authorities=authorities, run_id=run_id)
            for run_id in run_ids
        ]
        for run in runs:
            assert run.execution_state == EXTERNAL_RESULTS_REQUIRED
            assert len(run.scan_specification_registry) == 2
            assert set(run.secondary_run_registry.model) == {MODEL_DISCRETE_POISSON, MODEL_SPACE_TIME_PERMUTATION}
            viirs = run.secondary_run_registry.loc[run.secondary_run_registry.model.eq(MODEL_SPACE_TIME_PERMUTATION)].iloc[0]
            assert viirs.population_path == "" and viirs.population_sha256 == ""
            assert "required_provenance_path" not in run.secondary_run_registry.columns
            for row in run.secondary_run_registry.itertuples(index=False):
                assert row.required_report_path == row.results_prefix
                assert row.required_cluster_path == f"{row.results_prefix}.col.txt"
                assert row.required_membership_path == f"{row.results_prefix}.gis.txt"
                prm = run.run_dir / row.prm_path
                text = prm.read_text(encoding="utf-8")
                assert f"ResultsFile={row.results_prefix}" in text
                assert "MaxSpatialSizeInPopulationAtRisk=50" in text
                assert "MaxTemporalSize=12" in text
                assert "MonteCarloReps=999" in text
                assert "ReportGiniClusters=n" in text
                assert "CriteriaForReportingSecondaryClusters=0" in text
                assert "ReportClusterRank=y" in text
                assert "RandomSeed=" not in text
        cols = ["model_id", "prm_sha256", "case_sha256", "coordinate_sha256", "population_sha256"]
        pd.testing.assert_frame_equal(
            runs[0].secondary_run_registry[cols].reset_index(drop=True),
            runs[1].secondary_run_registry[cols].reset_index(drop=True),
            check_dtype=False,
        )
    finally:
        for target in targets:
            if target.exists():
                shutil.rmtree(target)


def test_method_authority_contains_hierarchical_no_gini_and_product_specific_models(governed) -> None:
    _, bundle, *_ = governed
    methods = {item.method_id: item for item in bundle.methods.authorities}
    assert methods["discrete_poisson"].status == "implemented"
    assert methods["space_time_permutation"].status == "implemented"
    hierarchical = methods["hierarchical_non_overlapping"]
    assert "no Gini" in hierarchical.governed_variant
    assert hierarchical.outcome_tuning_allowed is False



def _run_satscan_fixture_kwargs(tmp_path: Path, row: dict[str, object]) -> dict[str, object]:
    return {
        "executable_path": tmp_path / "SaTScanBatch64.exe",
        "parameter_path": tmp_path / str(row["prm_path"]),
        "case_path": tmp_path / str(row["case_path"]),
        "coordinate_path": tmp_path / str(row["coordinate_path"]),
        "population_path": (
            None if not str(row.get("population_path", "") or "")
            else tmp_path / str(row["population_path"])
        ),
        "scenario_id": str(row["scenario_id"]),
        "product": str(row["product"]),
        "model": str(row["model"]),
        "temporal_start": str(row["temporal_start"]),
        "temporal_end": str(row["temporal_end"]),
        "results_prefix": str(row["results_prefix"]),
        "cwd": tmp_path,
        "engine_version_authority": str(row["engine_version_authority"]),
        "scientific_seed": 20260822,
        "user_defined_random_seed_supported": False,
        "user_defined_random_seed_parameter": None,
        "rng_authority": "engine_deterministic_internal_seed",
        "engine_rng_behaviour": "same_internal_seed_for_identical_input",
        "alpha": 0.05,
        "max_temporal_months": 12,
    }


def _patch_satscan_execution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> None:
    monkeypatch.setattr(
        satscan_io,
        "executable_provenance",
        lambda _path: satscan_io.ExecutableProvenance(
            path="SaTScanBatch64.exe",
            sha256="e9905236b64971e9cf5d23e4474c1bfd9655fa352882ae78868ad3a5c4e91477",
            version="10.3.3",
        ),
    )

    class _Completed:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(satscan_io.subprocess, "run", lambda *args, **kwargs: _Completed())


def test_run_satscan_rejects_observed_zero_returncode_invalid_parameter_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _external_fixture(tmp_path)
    (tmp_path / "results/x").write_bytes(b"")
    (tmp_path / "results/x.col.txt").unlink()
    (tmp_path / "results/x.gis.txt").unlink()
    _patch_satscan_execution(
        monkeypatch,
        returncode=0,
        stderr=(
            "Invalid Parameter Setting\n"
            "The parameter settings prevent SaTScan from continuing.\n"
        ),
    )
    with pytest.raises(ExternalResultValidationError, match="fatal SaTScan diagnostic"):
        run_satscan(**_run_satscan_fixture_kwargs(tmp_path, row))


def test_run_satscan_rejects_nonzero_returncode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _external_fixture(tmp_path)
    _patch_satscan_execution(monkeypatch, returncode=2)
    with pytest.raises(ExternalResultValidationError, match="return code 2"):
        run_satscan(**_run_satscan_fixture_kwargs(tmp_path, row))


def test_run_satscan_accepts_zero_returncode_only_with_validated_complete_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _external_fixture(tmp_path)
    _patch_satscan_execution(monkeypatch, returncode=0, stdout="SaTScan batch calculation finished")
    result = run_satscan(**_run_satscan_fixture_kwargs(tmp_path, row))
    assert result["return_code"] == 0
    assert result["fatal_execution_diagnostic_detected"] is False
    assert result["result_family_validated"] is True
    assert result["validated_report_sha256"] == sha256_file(tmp_path / "results/x")


def test_run_satscan_rejects_zero_returncode_with_empty_main_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _external_fixture(tmp_path)
    report = tmp_path / "results/x"
    report.write_bytes(b"")
    newest = max(
        (tmp_path / "inputs/x.prm").stat().st_mtime_ns,
        (tmp_path / "inputs/x.cas").stat().st_mtime_ns,
        (tmp_path / "inputs/x.geo").stat().st_mtime_ns,
        (tmp_path / "inputs/x.pop").stat().st_mtime_ns,
    ) + 5_000_000
    os.utime(report, ns=(newest, newest))
    _patch_satscan_execution(monkeypatch, returncode=0)
    with pytest.raises(ExternalResultValidationError, match="main report is empty"):
        run_satscan(**_run_satscan_fixture_kwargs(tmp_path, row))


@pytest.mark.parametrize(
    ("missing_name", "expected"),
    [
        ("x.col.txt", "incomplete result family"),
        ("x.gis.txt", "incomplete result family"),
    ],
)
def test_run_satscan_rejects_zero_returncode_with_missing_companion(
    missing_name: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _external_fixture(tmp_path)
    (tmp_path / "results" / missing_name).unlink()
    _patch_satscan_execution(monkeypatch, returncode=0)
    with pytest.raises(ExternalResultValidationError, match=expected):
        run_satscan(**_run_satscan_fixture_kwargs(tmp_path, row))


def test_run_satscan_rejects_zero_returncode_with_semantic_fatal_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _external_fixture(tmp_path)
    _patch_satscan_execution(
        monkeypatch,
        returncode=0,
        stdout="Invalid Parameter Setting: parameter settings prevent SaTScan from continuing",
    )
    with pytest.raises(ExternalResultValidationError, match="fatal SaTScan diagnostic"):
        run_satscan(**_run_satscan_fixture_kwargs(tmp_path, row))


def test_canonical_result_validator_rejects_fatal_diagnostic_in_main_report(tmp_path: Path) -> None:
    row = _external_fixture(tmp_path)
    report = tmp_path / "results/x"
    report.write_text(
        report.read_text(encoding="utf-8")
        + "Invalid Parameter Setting\nThe parameter settings prevent SaTScan from continuing.\n",
        encoding="utf-8",
    )
    newest = max(
        (tmp_path / "inputs/x.prm").stat().st_mtime_ns,
        (tmp_path / "inputs/x.cas").stat().st_mtime_ns,
        (tmp_path / "inputs/x.geo").stat().st_mtime_ns,
        (tmp_path / "inputs/x.pop").stat().st_mtime_ns,
    ) + 5_000_000
    os.utime(report, ns=(newest, newest))
    with pytest.raises(ExternalResultValidationError, match="fatal SaTScan diagnostic"):
        validate_external_results(row, run_dir=tmp_path, alpha=0.05)
