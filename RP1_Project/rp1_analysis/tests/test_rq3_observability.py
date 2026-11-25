from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scientific_input_reference import (model_input_reference, cluster_reference, paired_input_reference, factor_outcome_reference, factor_outcomes_by_key, design_terms_reference)

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.gee import GEEDesignError, build_gee_mean_model_design, build_gee_population
from rp1_analysis_v1.observability import (
    ObservabilityError,
    build_paired_overlap_panel,
    build_rq3_tables,
    classify_observation_states,
    run_rq3_pgee_production,
)
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.validation import AnalyticalMask, validate_data_authorities
from rp1_analysis_v1.variables import resolve_field_role

SUBPROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bundle():
    return load_configuration_bundle(SUBPROJECT / "config")


@pytest.fixture(scope="module")
def real_rq3(bundle):
    paths = ProjectPaths.discover(SUBPROJECT)
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    return build_rq3_tables(authorities, summary, bundle.analysis, bundle.methods)


@pytest.fixture(scope="module")
def real_rq3_production(real_rq3, bundle):
    return run_rq3_pgee_production(real_rq3, bundle.analysis)


def _paired_synthetic() -> tuple[pd.DataFrame, AnalyticalMask]:
    rows = []
    ids = ["d1", "d2"]
    periods = pd.period_range("2012-02", "2024-12", freq="M")
    for ui, unit in enumerate(ids):
        for k, p in enumerate(periods):
            viirs = int((k + ui) % 3 != 0)
            ba = int((k + 2 * ui) % 4 == 0)
            rows.append({
                "unit_id": unit,
                "unit_name": unit.upper(),
                "parent_code": "CZ" if ui == 0 else "FZ",
                "parent_name": "ZONE",
                "yyyymm": p.year * 100 + p.month,
                "year": p.year,
                "month": p.month,
                "full_overlap_supported_flag": 1,
                "ba2012_supported_flag": 1,
                "viirs_supported_flag": 1,
                "ba2012_structural_missing_flag": 0,
                "viirs_structural_missing_flag": 0,
                "modis_ba_any_ba2012": ba,
                "modis_ba_km2_ba2012": float(ba),
                "viirs_det_primary_any": viirs,
                "viirs_det_primary": float(1 + k % 7) if viirs else 0.0,
                # Deliberately retained in the source panel to prove excluded fields do not enter the model.
                "viirs_days_active_nh": float(1 + k % 5) if viirs else 0.0,
                "viirs_frp_mean_mw": float(2 + k % 8) if viirs else 0.0,
                "modis_det_primary_any": int((k + ui) % 5 != 0),
                "modis_burnable_km2_union_ba2012": 100.0 + ui,
            })
    mask = AnalyticalMask(
        "paired",
        pd.DataFrame({"unit_id": ids, "eligible": [True, True], "exclusion_reasons": ["", ""]}),
    )
    return pd.DataFrame(rows), mask


def _configured_predictor_terms(bundle) -> tuple[str, ...]:
    return tuple(str(x["term_name"]) for x in bundle.analysis.research_questions["rq3"]["predictors"])


def test_real_governed_population_counts(real_rq3):
    assert real_rq3.paired_panel["unit_id"].nunique() == model_input_reference().unit_id.nunique()
    assert len(real_rq3.paired_panel) == len(paired_input_reference())
    assert real_rq3.gee_design.n_clusters == model_input_reference().unit_id.nunique()
    assert real_rq3.gee_design.n_observations == len(model_input_reference())


def test_four_state_construction_is_config_ordered(bundle):
    frame = pd.DataFrame({
        "modis_ba_any_ba2012": [0, 1, 0, 1],
        "viirs_det_primary_any": [0, 0, 1, 1],
    })
    configured = list(bundle.analysis.research_questions["rq3"]["four_state_correspondence"]["states"])
    assert classify_observation_states(frame, bundle.analysis).tolist() == configured


def test_four_state_missing_fails_closed(bundle):
    frame = pd.DataFrame({"modis_ba_any_ba2012": [0, np.nan], "viirs_det_primary_any": [1, 0]})
    with pytest.raises(ObservabilityError, match="supported non-missing"):
        classify_observation_states(frame, bundle.analysis)


def test_paired_support_and_viirs_positive_restriction(bundle):
    frame, mask = _paired_synthetic()
    paired = build_paired_overlap_panel(frame, bundle.analysis, bundle.methods, mask, enforce_governed_counts=False)
    assert len(paired) == 310
    model = build_gee_population(paired, bundle.analysis, enforce_governed_counts=False)
    assert len(model) == int(paired["viirs_positive"].sum())
    assert model["viirs_det_primary_any"].eq(1).all()
    assert model["mismatch_y"].isin([0, 1]).all()


def test_recovered_frp_with_zero_count_and_missing_required_predictor(bundle):
    frame, mask = _paired_synthetic()
    zero_index = frame.index[frame["viirs_det_primary"].eq(0)][0]
    frame.loc[zero_index, "viirs_frp_mean_mw"] = 4.0
    paired = build_paired_overlap_panel(frame, bundle.analysis, bundle.methods, mask, enforce_governed_counts=False)
    key = (frame.loc[zero_index, "unit_id"], frame.loc[zero_index, "yyyymm"])
    model = build_gee_population(paired, bundle.analysis, enforce_governed_counts=False)
    assert key not in set(zip(model["unit_id"], model["yyyymm"]))
    positive_index = paired.index[paired["viirs_det_primary"].gt(0)][0]
    paired.loc[positive_index, "viirs_frp_mean_mw"] = float("nan")
    with pytest.raises(GEEDesignError, match="missing"):
        build_gee_population(paired, bundle.analysis, enforce_governed_counts=False)


def test_unsupported_paired_row_fails_closed(bundle):
    frame, mask = _paired_synthetic()
    frame.loc[0, "viirs_supported_flag"] = 0
    with pytest.raises(ObservabilityError, match="incomplete support"):
        build_paired_overlap_panel(frame, bundle.analysis, bundle.methods, mask, enforce_governed_counts=False)


def test_all_configured_log2_inputs_strictly_positive(real_rq3, bundle):
    frame = real_rq3.gee_design.frame
    for item in bundle.analysis.research_questions["rq3"]["predictors"]:
        if item["transform"] != "log2_positive":
            continue
        field = str(resolve_field_role(bundle.analysis, str(item["field_role"])))
        assert pd.to_numeric(frame[field]).gt(0).all(), field


def test_nonpositive_configured_log2_input_fails_closed(bundle):
    frame, mask = _paired_synthetic()
    paired = build_paired_overlap_panel(frame, bundle.analysis, bundle.methods, mask, enforce_governed_counts=False)
    predictor = bundle.analysis.research_questions["rq3"]["predictors"][1]
    field = str(resolve_field_role(bundle.analysis, str(predictor["field_role"])))
    idx = paired.index[paired["viirs_positive"].eq(1)][0]
    paired.loc[idx, field] = 0.0
    with pytest.raises(GEEDesignError, match="non-positive"):
        build_gee_mean_model_design(paired, bundle.analysis, enforce_governed_counts=False)


def test_fixed_mean_model_transforms_and_references(real_rq3, bundle):
    design = real_rq3.gee_design
    terms = design.term_order
    configured_predictors = _configured_predictor_terms(bundle)
    assert terms[0] == "Intercept"
    assert terms[1 : 1 + len(configured_predictors)] == configured_predictors
    for factor in bundle.analysis.research_questions["rq3"]["factors"]:
        prefix = str(factor["term_prefix"])
        reference = factor["reference"]
        assert f"{prefix}_{reference}" not in terms
    assert design.model_family == "binomial"
    assert design.link == "logit"
    assert design.covariance == "morel_bokossa_neerchal"
    assert design.working_correlation_status == "independence"
    assert design.reference_distribution == "standard_normal_wald"


def test_design_matrix_is_deterministic(real_rq3, bundle):
    paired = real_rq3.paired_panel
    a = build_gee_mean_model_design(paired, bundle.analysis)
    b = build_gee_mean_model_design(paired.sample(frac=1.0, random_state=17), bundle.analysis)
    assert a.term_order == b.term_order
    pd.testing.assert_frame_equal(a.design_matrix, b.design_matrix)
    pd.testing.assert_series_equal(a.outcome, b.outcome)
    pd.testing.assert_series_equal(a.clusters, b.clusters)


def test_no_result_driven_selection_and_vif_has_no_deletion_authority(bundle):
    rq3 = bundle.analysis.research_questions["rq3"]
    assert rq3["interactions"] is False
    assert rq3["stepwise_selection"] is False
    assert rq3["outcome_driven_tuning"] is False
    assert rq3["diagnostics"]["vif"]["enabled"] is True
    assert rq3["diagnostics"]["vif"]["deletion_authority"] is False
    text = (SUBPROJECT / "src/rp1_analysis_v1/observability.py").read_text(encoding="utf-8").casefold()
    gee = (SUBPROJECT / "src/rp1_analysis_v1/gee.py").read_text(encoding="utf-8").casefold()
    for forbidden in ("audit_frp_candidates", "select_frp_metrics", "stepwise", "log1p", "cyclic_fourier"):
        assert forbidden not in text
        assert forbidden not in gee


def test_mean_model_design_interface_does_not_fit_or_select_correlation():
    source = inspect.getsource(build_gee_mean_model_design).lower()
    assert ".fit(" not in source
    assert "exchangeable" not in source
    assert "ar1" not in source
    assert "cic" not in source


def test_paired_each_district_has_configured_months(real_rq3):
    sizes = real_rq3.paired_panel.groupby("unit_id", observed=True).size()
    assert len(sizes) == model_input_reference().unit_id.nunique()
    expected = paired_input_reference().groupby("unit_id").size().sort_index()
    sizes.index = sizes.index.astype(str)
    expected.index = expected.index.astype(str)
    pd.testing.assert_series_equal(sizes.sort_index(), expected.sort_index(), check_names=False)


def test_model_population_and_outcome_match_frozen_authority(real_rq3):
    model = real_rq3.model_population
    assert model["unit_id"].nunique() == model_input_reference().unit_id.nunique()
    assert len(model) == len(model_input_reference())
    expected = 1 - model["modis_ba_any_ba2012"].astype(int)
    pd.testing.assert_series_equal(
        model["mismatch_y"].astype(int).reset_index(drop=True),
        expected.reset_index(drop=True),
        check_names=False,
    )


def test_configured_predictor_transforms_are_exact(real_rq3, bundle):
    design = real_rq3.gee_design
    for item in bundle.analysis.research_questions["rq3"]["predictors"]:
        term = str(item["term_name"])
        field = str(resolve_field_role(bundle.analysis, str(item["field_role"])))
        source = pd.to_numeric(design.frame[field], errors="raise").astype(float)
        if item["transform"] == "log2_positive":
            expected = np.log2(source)
        elif item["transform"] == "identity":
            expected = source
        else:
            raise AssertionError(f"Unexpected configured transform in test: {item['transform']}")
        np.testing.assert_allclose(design.design_matrix[term], expected)


def test_active_days_and_modis_active_fire_are_excluded(real_rq3):
    terms = set(real_rq3.gee_design.term_order)
    assert "log2_viirs_days_active_nh" not in terms
    assert "modis_det_primary_any" not in terms


def test_configured_factor_references_control_design(real_rq3, bundle):
    terms = set(real_rq3.gee_design.term_order)
    for factor in bundle.analysis.research_questions["rq3"]["factors"]:
        prefix = str(factor["term_prefix"])
        field = str(resolve_field_role(bundle.analysis, str(factor["field_role"])))
        reference = factor["reference"]
        levels = set(real_rq3.gee_design.frame[field].tolist())
        assert f"{prefix}_{reference}" not in terms
        assert {f"{prefix}_{level}" for level in levels if level != reference}.issubset(terms)


def test_design_contains_exact_configured_predictors_once(real_rq3, bundle):
    terms = real_rq3.gee_design.term_order
    expected = _configured_predictor_terms(bundle)
    assert all(terms.count(term) == 1 for term in expected)
    configured_prefixes = tuple(str(x["term_prefix"]) + "_" for x in bundle.analysis.research_questions["rq3"]["factors"])
    continuous = [t for t in terms if t != "Intercept" and not t.startswith(configured_prefixes)]
    assert tuple(continuous) == expected


def test_design_has_configured_columns(real_rq3):
    # Dimensions follow the configured terms and levels present in current inputs.
    assert len(real_rq3.gee_design.term_order) == len(design_terms_reference())
    assert real_rq3.gee_design.design_matrix.shape == (len(model_input_reference()), len(design_terms_reference()))
    assert np.isfinite(real_rq3.gee_design.design_matrix.to_numpy(dtype=float)).all()


def test_real_separation_authority_regenerated(real_rq3):
    table = real_rq3.separation_diagnostics
    reference = factor_outcomes_by_key(factor_outcome_reference())
    actual = factor_outcomes_by_key(table)
    pd.testing.assert_index_equal(actual.index, reference.index)
    for field in ("n", "y1", "y0", "complete_separation"):
        np.testing.assert_array_equal(actual[field].to_numpy(), reference[field].to_numpy())


def test_real_cluster_separation_structure(real_rq3):
    model = real_rq3.gee_design.frame
    grouped = model.groupby("unit_id")["mismatch_y"].agg(["size", "sum"])
    y0 = grouped["size"] - grouped["sum"]
    reference = cluster_reference()
    assert set(y0.index[y0.eq(0)]) == set(reference.index[reference["sum"].eq(reference["size"])])
    assert set(grouped.index[grouped["sum"].eq(0)]) == set(reference.index[reference["sum"].eq(0)])
    assert int(grouped["size"].min()) == int(cluster_reference()["size"].min())
    assert int(grouped["size"].max()) == int(cluster_reference()["size"].max())


def test_production_pgee_preserves_full_configured_design(real_rq3_production, real_rq3):
    fit = real_rq3_production.production.fit
    assert fit.n_observations == len(model_input_reference())
    assert fit.n_clusters == model_input_reference().unit_id.nunique()
    assert fit.design_dimension == len(design_terms_reference())
    assert len(real_rq3_production.production.coefficient_authority) == len(design_terms_reference())
    assert tuple(real_rq3_production.production.coefficient_authority["term"]) == real_rq3.gee_design.term_order


def test_production_prefit_separation_diagnostics_are_complete(real_rq3_production):
    diagnostic = real_rq3_production.separation
    assert diagnostic.outcome_n == len(model_input_reference())
    reference = model_input_reference()
    assert diagnostic.outcome_y1 == int(reference.mismatch_y.sum())
    assert diagnostic.outcome_y0 == int(reference.mismatch_y.eq(0).sum())
    assert diagnostic.design_rank == len(design_terms_reference())
    assert diagnostic.design_columns == len(design_terms_reference())
    separated = factor_outcome_reference().loc[lambda x: x.complete_separation]
    assert set(diagnostic.complete_separation_levels) == set(separated.factor + "=" + separated.level)
    clusters = cluster_reference()
    assert diagnostic.all_y1_clusters == int(clusters["sum"].eq(clusters["size"]).sum())
    assert diagnostic.all_y0_clusters == int(clusters["sum"].eq(0).sum())


def test_production_pgee_uses_standard_normal_wald_and_is_finite(real_rq3_production):
    fit = real_rq3_production.production.fit
    assert fit.converged
    assert fit.iterations > 0
    assert fit.score_max_abs < 1e-6
    assert not hasattr(fit, "degrees_of_freedom")
    for values in (
        fit.coefficients,
        fit.standard_errors,
        fit.wald_z,
        fit.standard_normal_p,
        fit.standard_normal_ci_low,
        fit.standard_normal_ci_high,
        fit.covariance,
    ):
        assert np.isfinite(values).all()
    assert np.allclose(fit.covariance, fit.covariance.T, rtol=0.0, atol=1e-12)
    assert np.linalg.eigvalsh(fit.covariance).min() > 0.0


def test_production_authority_or_transform_and_focal_roles(real_rq3_production, bundle):
    authority = real_rq3_production.production.coefficient_authority
    non_intercept = authority.loc[authority["term_role"].ne("intercept")].copy()
    focal = authority.loc[authority["is_focal_predictor"]].copy()
    configured_focal = sum(str(x["role"]) == "focal" for x in bundle.analysis.research_questions["rq3"]["predictors"])
    assert len(focal) == configured_focal == 2
    assert authority["reference_distribution"].eq("standard_normal_wald").all()
    assert "degrees_of_freedom" not in authority.columns
    assert authority["statistic_name"].eq("wald_z").all()
    np.testing.assert_allclose(authority["wald_z"], authority["coefficient"] / authority["corrected_se"])
    assert non_intercept["adjusted_or"].notna().all()
    np.testing.assert_allclose(non_intercept["adjusted_or"], np.exp(non_intercept["coefficient"]))
    np.testing.assert_allclose(non_intercept["adjusted_or_ci_low"], np.exp(non_intercept["ci_low"]))
    np.testing.assert_allclose(non_intercept["adjusted_or_ci_high"], np.exp(non_intercept["ci_high"]))
    assert authority.loc[authority["term"].eq("Intercept"), "adjusted_or"].isna().all()
    assert focal.loc[focal["coding"].eq("log2_positive"), "interpretation"].eq("adjusted_or_per_doubling").all()


def test_production_covariance_authority_is_complete(real_rq3_production):
    covariance = real_rq3_production.production.covariance_authority
    assert len(covariance) == len(design_terms_reference()) ** 2
    assert covariance["row_term"].nunique() == len(design_terms_reference())
    assert covariance["column_term"].nunique() == len(design_terms_reference())
    assert np.isfinite(covariance["covariance"].to_numpy(dtype=float)).all()


def test_production_pgee_deterministic_repeatability(real_rq3, bundle, real_rq3_production):
    second = run_rq3_pgee_production(real_rq3, bundle.analysis)
    first_fit = real_rq3_production.production.fit
    second_fit = second.production.fit
    np.testing.assert_array_equal(first_fit.coefficients, second_fit.coefficients)
    np.testing.assert_array_equal(first_fit.covariance, second_fit.covariance)
    pd.testing.assert_frame_equal(
        real_rq3_production.production.coefficient_authority,
        second.production.coefficient_authority,
    )
    pd.testing.assert_frame_equal(
        real_rq3_production.production.standardised_probability_authority,
        second.production.standardised_probability_authority,
    )


def test_production_authority_contains_no_silent_row_or_term_deletion(real_rq3, real_rq3_production):
    authority = real_rq3_production.production.coefficient_authority
    assert int(authority["n_observations"].iloc[0]) == len(real_rq3.model_population)
    assert int(authority["design_dimension"].iloc[0]) == len(real_rq3.gee_design.term_order)
    assert set(authority["term"]) == set(real_rq3.gee_design.term_order)
