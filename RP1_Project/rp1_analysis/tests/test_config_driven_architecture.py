from __future__ import annotations

import copy
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import box

from rp1_analysis_v1.config import (
    ConfigurationError,
    build_realised_run_metadata,
    load_configuration_bundle,
    rq1_spatial_parameters,
    rq3_model_parameters,
    satscan_parameters,
)
from rp1_analysis_v1.gee import build_gee_mean_model_design, configured_predictor_metadata
from rp1_analysis_v1.satscan_io import generate_parameter_file
from rp1_analysis_v1.secondary_clusters import load_scan_scenarios
from rp1_analysis_v1.spatial_stats import build_rq1_spatial_association_authorities

SUBPROJECT = Path(__file__).resolve().parents[1]


def _mutated_bundle(tmp_path: Path, mutate):
    root = tmp_path / "fixture"
    shutil.copytree(SUBPROJECT / "config", root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    path = root / "config" / "analysis_contract.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return load_configuration_bundle(root / "config")


def test_synthetic_rq1_permutation_and_seed_mutation_reaches_consumer(tmp_path: Path) -> None:
    def mutate(raw):
        raw["reproducibility"]["primary_seed"] = 17
        raw["research_questions"]["rq1"]["spatial"]["global"]["permutations"] = 199
        raw["research_questions"]["rq1"]["spatial"]["local"]["permutations"] = 199

    bundle = _mutated_bundle(tmp_path, mutate)
    params = rq1_spatial_parameters(bundle.analysis)
    assert params.random_seed == 17
    assert params.global_permutations == params.local_permutations == 199

    ids = ["a", "b", "c", "d"]
    geom = gpd.GeoDataFrame(
        {"dist_id": ids},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(0, 1, 1, 2), box(1, 1, 2, 2)],
        crs="EPSG:32630",
    )
    authority = pd.DataFrame({
        "unit_id": ids,
        "within_acz_absolute_departure": [1.0, -1.0, 2.0, -2.0],
    })
    out = build_rq1_spatial_association_authorities(authority, geom, bundle.analysis)
    assert int(out.global_table.loc[0, "permutations"]) == 199
    assert int(out.global_table.loc[0, "random_seed"]) == 17
    assert set(out.local_table["permutations"].astype(int)) == {199}
    assert set(out.local_table["random_seed"].astype(int)) == {17}


def test_synthetic_satscan_temporal_window_serialises_from_config(tmp_path: Path) -> None:
    def mutate(raw):
        common = raw["secondary_analysis"]["common"]
        common["max_temporal_months"] = 7
        common["max_spatial_percent"] = 23
        common["monte_carlo_replicates"] = 17

    bundle = _mutated_bundle(tmp_path, mutate)
    params = satscan_parameters(bundle.analysis)
    scenarios = load_scan_scenarios(bundle.analysis)
    scenario = next(x for x in scenarios if x.population_field is None)
    text = generate_parameter_file(
        scenario_id=scenario.scenario_id,
        product=scenario.product,
        model=scenario.model,
        reporting=scenario.reporting_rule,
        case_path="case.cas",
        population_path=None,
        coordinate_path="coord.geo",
        results_prefix="result/out",
        start_date="2012/02/01",
        end_date="2024/12/31",
        max_spatial_percent=scenario.max_spatial_percent,
        max_temporal_months=scenario.max_temporal_months,
        monte_carlo_replicates=params.monte_carlo_replicates,
        analysis_type=params.analysis_type,
        cluster_type=params.cluster_type,
        spatial_window_shape=params.spatial_window_shape,
        geographical_overlap=params.geographical_overlap,
        gini_optimised_reporting=params.gini_optimised_reporting,
        report_cluster_rank=params.report_cluster_rank,
        scientific_seed=params.scientific_seed,
        user_defined_random_seed_supported=params.user_defined_random_seed_supported,
        user_defined_random_seed_parameter=params.user_defined_random_seed_parameter,
        rng_authority=params.rng_authority,
        engine_rng_behaviour=params.engine_rng_behaviour,
    )
    assert "MaxTemporalSize=7" in text
    assert "MaxSpatialSizeInPopulationAtRisk=23" in text
    assert "MonteCarloReps=17" in text


def _synthetic_rq3_panel() -> pd.DataFrame:
    return pd.DataFrame({
        "unit_id": ["d1", "d1", "d2", "d2"],
        "yyyymm": [201301, 201402, 201301, 201402],
        "year": [2013, 2014, 2013, 2014],
        "month": [1, 2, 1, 2],
        "parent_code": ["CZ", "FZ", "CZ", "FZ"],
        "viirs_det_primary": [1.0, 2.0, 4.0, 8.0],
        "viirs_frp_mean_mw": [2.0, 4.0, 8.0, 16.0],
        "modis_burnable_km2_union_ba2012": [10.0, 10.0, 20.0, 20.0],
        "modis_ba_any_ba2012": [0, 1, 0, 1],
        "viirs_det_primary_any": [1, 1, 1, 1],
    })


def test_factor_reference_mutation_controls_design_metadata(tmp_path: Path) -> None:
    def mutate(raw):
        for factor in raw["research_questions"]["rq3"]["factors"]:
            if factor["factor_id"] == "year":
                factor["reference"] = 2014
                factor["reference_label"] = "2014"

    bundle = _mutated_bundle(tmp_path, mutate)
    params = rq3_model_parameters(bundle.analysis)
    year = next(x for x in params.factors if x["factor_id"] == "year")
    assert year["reference"] == 2014
    design = build_gee_mean_model_design(_synthetic_rq3_panel(), bundle.analysis, enforce_governed_counts=False)
    assert "year_2014" not in design.term_order
    assert "year_2013" in design.term_order


def test_predictor_role_mutation_changes_reporting_metadata_without_code_change(tmp_path: Path) -> None:
    def mutate(raw):
        predictors = raw["research_questions"]["rq3"]["predictors"]
        predictors[0]["role"] = "adjustment"
        predictors[2]["role"] = "focal"

    original = load_configuration_bundle(SUBPROJECT / "config")
    mutated = _mutated_bundle(tmp_path, mutate)
    before = configured_predictor_metadata(original.analysis).set_index("predictor_id")["predictor_role"].to_dict()
    after = configured_predictor_metadata(mutated.analysis).set_index("predictor_id")["predictor_role"].to_dict()
    assert before != after
    assert after["viirs_detection_count"] == "adjustment"
    assert after["fixed_ba2012_burnable_area"] == "focal"


def test_realised_run_metadata_records_derived_values_without_reowning_them() -> None:
    bundle = load_configuration_bundle(SUBPROJECT / "config")
    digest_a = "a" * 64
    digest_b = "b" * 64
    metadata = build_realised_run_metadata(
        bundle,
        methods_spec_sha256=digest_a,
        data_sha256=digest_b,
        realised_sample_sizes={"synthetic": 3},
        rq2_realised_bandwidth=2,
        realised_permutation_counts={"synthetic": 19},
        rq3_design_columns=("Intercept", "x"),
        factor_references={"year": 2014},
        spatial_weight_parameters={"transform": "row_standardised"},
        satscan_parameter_hashes={"synthetic": digest_a},
    )
    payload = metadata.to_dict()
    assert payload["config_sha256"] == bundle.configuration_sha256
    assert payload["rq2_realised_bandwidth"] == 2
    assert payload["factor_references"]["year"] == 2014
    with pytest.raises(ConfigurationError, match="SHA-256"):
        build_realised_run_metadata(bundle, methods_spec_sha256="bad", data_sha256=digest_b)


@pytest.mark.parametrize("mutation", [
    lambda raw: raw["research_questions"]["rq2"]["inferential_test"].__setitem__("bandwidth", 2),
    lambda raw: raw["research_questions"]["rq3"]["standardised_probabilities"].__setitem__("focal_predictor_quantiles", [0.25, 1.2]),
    lambda raw: raw["research_questions"]["rq3"]["predictors"].append(copy.deepcopy(raw["research_questions"]["rq3"]["predictors"][0])),
    lambda raw: raw["secondary_analysis"]["scenarios"][1].__setitem__("exposure_role", "secondary.fixed_ba2001_exposure"),
    lambda raw: raw["secondary_analysis"]["scenarios"][0].__setitem__("exposure_role", None),
])
def test_malformed_or_parallel_authorities_fail_closed(tmp_path: Path, mutation) -> None:
    with pytest.raises(ConfigurationError):
        _mutated_bundle(tmp_path, mutation)


def test_satscan_gini_reporting_is_explicitly_configured_off() -> None:
    bundle = load_configuration_bundle(SUBPROJECT / "config")
    params = satscan_parameters(bundle.analysis)
    assert params.gini_optimised_reporting is False

