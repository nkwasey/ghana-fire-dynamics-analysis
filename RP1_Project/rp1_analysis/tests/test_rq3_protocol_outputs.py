from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.observability import (
    DISTRICT_MISMATCH_COLUMNS,
    FOCAL_EFFECT_COLUMNS,
    PREDICTOR_DIAGNOSTICS_COLUMNS,
    FIT_DIAGNOSTICS_COLUMNS,
    FULL_COEFFICIENT_COLUMNS,
    FULL_MODEL_AUTHORITY_COLUMNS,
    STANDARDISED_PROBABILITY_COLUMNS,
    FOUR_STATE_SUMMARY_COLUMNS,
    CONTINUOUS_MODEL_SUMMARY_COLUMNS,
    build_rq3_tables,
)
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.validation import validate_data_authorities

SUBPROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bundle():
    return load_configuration_bundle(SUBPROJECT / "config")


@pytest.fixture(scope="module")
def rq3(bundle):
    paths = ProjectPaths.discover(SUBPROJECT)
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    return build_rq3_tables(authorities, summary, bundle.analysis, bundle.methods)


def test_output_contract_owns_current_rq3_publication_and_internal_sources(bundle) -> None:
    publication = [item for item in bundle.output.tables if item.rq == "RQ3"]
    assert {item.output_id for item in publication} == {"T2", "S5"}
    t2 = next(item for item in publication if item.output_id == "T2")
    assert t2.source_attribute == "table2_rq3_model"
    assert t2.required_columns == ("term", "predictor_role", "beta", "corrected_se", "adjusted_or", "or_lower_95", "or_upper_95", "p")
    assert t2.builder_options["row_selector"] == "all_configured_continuous_predictors"
    assert t2.builder_options["factor_coefficients_destination"] == "S5"
    internal = [item for item in bundle.output.secondary_outputs if item.source_attribute == "full_coefficient_source"]
    assert len(internal) == 1
    assert internal[0].output_id == "rq3_full_coefficient_authority"
    std = [item for item in bundle.output.secondary_outputs if item.source_attribute == "standardised_probability_source"]
    assert len(std) == 1
    assert std[0].output_id == "rq3_standardised_probability_authority"


def test_four_state_summary_source_is_complete(rq3) -> None:
    frame = rq3.four_state_summary_source
    assert tuple(frame.columns) == FOUR_STATE_SUMMARY_COLUMNS
    assert len(frame) == 24
    assert set(frame["summary_scope"]) == {"overall", "acz"}
    assert frame.loc[frame["summary_scope"].eq("overall"), "denominator_n"].eq(38595).all()
    assert frame.loc[frame["summary_scope"].eq("acz"), "parent_code"].nunique() == 5
    grouped = frame.groupby(["summary_scope", "parent_code"], dropna=False, observed=True)
    assert grouped["count"].sum().equals(grouped["denominator_n"].first())
    np.testing.assert_allclose(grouped["percentage"].sum().to_numpy(), 100.0)


def test_continuous_model_summary_source_has_exact_schema_and_three_rows(rq3, bundle) -> None:
    frame = rq3.continuous_model_summary_source
    assert tuple(frame.columns) == CONTINUOUS_MODEL_SUMMARY_COLUMNS
    assert len(frame) == len(bundle.analysis.research_questions["rq3"]["predictors"]) == 3
    assert frame["predictor_role"].tolist().count("focal") == 2
    assert frame["predictor_role"].tolist().count("adjustment") == 1
    assert frame["n"].eq(22939).all()
    assert frame["districts"].eq(249).all()
    assert frame["estimator"].eq("firth_penalized_gee").all()
    assert frame["working_structure"].eq("independence").all()
    assert frame["covariance_method"].eq("morel_bokossa_neerchal").all()
    assert frame["reference_distribution"].eq("standard_normal_wald").all()


def test_predictor_diagnostics_source_has_exact_schema_correlations_and_vif(rq3, bundle) -> None:
    frame = rq3.predictor_diagnostics_source
    assert tuple(frame.columns) == PREDICTOR_DIAGNOSTICS_COLUMNS
    n_predictors = len(bundle.analysis.research_questions["rq3"]["predictors"])
    assert len(frame) == n_predictors + n_predictors * n_predictors == 12
    distribution = frame.loc[frame["record_type"].eq("distribution")]
    correlation = frame.loc[frame["record_type"].eq("correlation")]
    assert len(distribution) == 3
    assert len(correlation) == 9
    assert distribution["vif"].notna().all()
    assert np.isfinite(distribution["vif"].to_numpy(dtype=float)).all()
    assert correlation["vif"].isna().all()


def test_fit_diagnostics_source_has_exact_schema_and_standard_normal_metadata(rq3) -> None:
    frame = rq3.fit_diagnostics_source
    assert tuple(frame.columns) == FIT_DIAGNOSTICS_COLUMNS
    assert len(frame) == 1
    row = frame.iloc[0]
    assert int(row["observations"]) == 22939
    assert int(row["districts"]) == 249
    assert int(row["outcome_y1"]) == 16811
    assert int(row["outcome_y0"]) == 6128
    assert int(row["model_columns"]) == int(row["model_rank"]) == 31
    assert row["complete_separation_levels"] == "month=7|month=9"
    assert int(row["all_y1_clusters"]) == 29
    assert int(row["all_y0_clusters"]) == 0
    assert int(row["cluster_size_min"]) == 7
    assert int(row["cluster_size_max"]) == 147
    assert row["reference_distribution"] == "standard_normal_wald"
    assert row["convergence"] == "PASS"
    assert row["finite_coefficient_status"] == "PASS"
    assert row["finite_covariance_status"] == "PASS"


def test_full_coefficient_source_has_complete_count_and_configured_references(rq3, bundle) -> None:
    frame = rq3.full_coefficient_source
    assert tuple(frame.columns) == FULL_COEFFICIENT_COLUMNS
    assert len(frame) == 31
    assert frame["term_order"].tolist() == list(range(31))
    terms = set(frame["term"].astype(str))
    assert "Intercept" in terms
    for factor in bundle.analysis.research_questions["rq3"]["factors"]:
        prefix = str(factor["term_prefix"])
        reference = factor["reference"]
        assert f"{prefix}_{reference}" not in terms
    assert "log2_viirs_days_active_nh" not in terms
    assert "modis_det_primary_any" not in terms
    assert frame["beta"].notna().all()
    assert frame["corrected_se"].notna().all()
    assert frame["reference_distribution"].eq("standard_normal_wald").all()


def test_or_calculations_are_exact_across_continuous_and_full_coefficient_sources(rq3) -> None:
    full_coefficients = rq3.full_coefficient_source
    non_intercept = full_coefficients.loc[full_coefficients["term"].ne("Intercept")].copy()
    np.testing.assert_allclose(non_intercept["adjusted_or"], np.exp(non_intercept["beta"]))
    continuous = full_coefficients.loc[full_coefficients["term_role"].astype(str).str.endswith("_predictor")].reset_index(drop=True)
    np.testing.assert_allclose(rq3.continuous_model_summary_source["adjusted_or"], continuous["adjusted_or"])
    np.testing.assert_allclose(rq3.continuous_model_summary_source["or_lower_95"], continuous["or_lower_95"])
    np.testing.assert_allclose(rq3.continuous_model_summary_source["or_upper_95"], continuous["or_upper_95"])


def test_mismatch_and_focal_effect_sources_are_distinct_and_deterministic(rq3) -> None:
    assert tuple(rq3.district_mismatch_source.columns) == DISTRICT_MISMATCH_COLUMNS
    assert tuple(rq3.focal_effect_source.columns) == FOCAL_EFFECT_COLUMNS
    assert len(rq3.district_mismatch_source) == 249
    assert len(rq3.focal_effect_source) == 2
    assert rq3.district_mismatch_source["unit_id"].is_monotonic_increasing
    assert rq3.focal_effect_source["display_order"].tolist() == [1, 2]
    focal = rq3.continuous_model_summary_source.loc[rq3.continuous_model_summary_source["predictor_role"].eq("focal")].reset_index(drop=True)
    assert rq3.focal_effect_source["term"].tolist() == focal["term"].tolist()
    np.testing.assert_allclose(rq3.focal_effect_source["adjusted_or"], focal["adjusted_or"])


def test_machine_readable_rq3_sources_are_byte_repeatable(rq3) -> None:
    for attribute in (
        "four_state_summary_source", "continuous_model_summary_source", "predictor_diagnostics_source", "fit_diagnostics_source", "full_coefficient_source",
        "standardised_probability_source", "full_model_authority", "district_mismatch_source", "focal_effect_source",
    ):
        frame = getattr(rq3, attribute)
        left = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        right = frame.copy().to_csv(index=False, lineterminator="\n").encode("utf-8")
        assert left == right
        assert hashlib.sha256(left).hexdigest() == hashlib.sha256(right).hexdigest()


def test_no_cic_qic_or_feature_selection_active_output_path(bundle) -> None:
    rq3 = bundle.analysis.research_questions["rq3"]
    assert rq3["working_correlation"] == "independence"
    assert rq3["stepwise_selection"] is False
    assert rq3["outcome_driven_tuning"] is False
    active = "\n".join(
        f"{item.output_id} {item.source_attribute}" for item in bundle.output.tables if item.rq == "RQ3"
    ).casefold()
    assert "cic" not in active
    assert "qic" not in active


def test_complete_rq3_integration_uses_one_qualified_fit_for_semantic_sources(rq3) -> None:
    fit = rq3.production_pgee.production.fit
    assert fit.converged and fit.coefficients_finite and fit.covariance_finite
    assert fit.covariance_symmetric
    assert fit.n_observations == 22939
    assert fit.n_clusters == 249
    assert fit.design_dimension == 31
    continuous_coefficients = rq3.full_coefficient_source.loc[rq3.full_coefficient_source["term_role"].astype(str).str.endswith("_predictor")]
    assert rq3.continuous_model_summary_source["term"].tolist() == continuous_coefficients["term"].tolist()
    focal = continuous_coefficients.loc[continuous_coefficients["term_role"].eq("focal_predictor")].reset_index(drop=True)
    assert rq3.focal_effect_source["term"].tolist() == focal["term"].tolist()
    np.testing.assert_allclose(rq3.continuous_model_summary_source["beta"], continuous_coefficients["beta"])


def test_standardised_probability_authority_exact_cardinality_and_schema(rq3) -> None:
    frame = rq3.standardised_probability_source
    assert tuple(frame.columns) == STANDARDISED_PROBABILITY_COLUMNS
    assert len(frame) == 4
    assert set(frame["predictor_role"]) == {"focal"}
    assert set(frame["predictor_id"]) == {"viirs_detection_count", "viirs_mean_frp"}
    assert set(frame["quantile"]) == {0.25, 0.75}
    assert frame["n"].eq(22939).all()
    assert frame["districts"].eq(249).all()
    assert frame["standardised_probability"].between(0.0, 1.0, inclusive="both").all()
    for column in ("model_spec_sha256", "design_matrix_sha256", "configuration_sha256"):
        assert frame[column].astype(str).str.fullmatch(r"[0-9a-f]{64}").all()
    assert frame["standardisation_method"].eq("observed_covariate_predictive_standardisation").all()
    assert frame["averaging_distribution"].eq("observed_remaining_covariates").all()


def test_full_model_authority_contains_coefficients_diagnostics_and_probabilities(rq3) -> None:
    frame = rq3.full_model_authority
    assert tuple(frame.columns) == FULL_MODEL_AUTHORITY_COLUMNS
    assert (frame["record_type"] == "coefficient").sum() == 31
    assert (frame["record_type"] == "standardised_probability").sum() == 4
    assert (frame["record_type"] == "diagnostic").sum() > 0
    probs = frame.loc[frame["record_type"].eq("standardised_probability")]
    assert probs["standardisation_predictor"].nunique() == 2
    assert probs["standardised_probability"].between(0.0, 1.0, inclusive="both").all()
