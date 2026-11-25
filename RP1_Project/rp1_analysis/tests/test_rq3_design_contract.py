from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scientific_input_reference import (model_input_reference, cluster_reference, paired_input_reference, factor_outcome_reference, factor_outcomes_by_key, design_terms_reference)

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.gee import mean_model_column_provenance
from rp1_analysis_v1.observability import (
    RQ3_CLUSTER_OUTCOME_COLUMNS,
    RQ3_DESIGN_METADATA_COLUMNS,
    RQ3_FACTOR_OUTCOME_COLUMNS,
    ObservabilityError,
    build_paired_overlap_panel,
    build_rq3_design_authority,
)
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.validation import AnalyticalMask, validate_data_authorities
from rp1_analysis_v1.variables import resolve_field_role

SUBPROJECT = Path(__file__).resolve().parents[1]
DUMMY_METHODS_HASH = "a" * 64
DUMMY_DATA_HASH = "b" * 64


@pytest.fixture(scope="module")
def bundle():
    return load_configuration_bundle(SUBPROJECT / "config")


@pytest.fixture(scope="module")
def design_authority(bundle):
    paths = ProjectPaths.discover(SUBPROJECT)
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    return build_rq3_design_authority(
        authorities,
        summary,
        bundle,
        methods_spec_sha256=DUMMY_METHODS_HASH,
        data_sha256=DUMMY_DATA_HASH,
    )


def _tiny_paired_frame() -> tuple[pd.DataFrame, AnalyticalMask]:
    periods = pd.period_range("2012-02", "2024-12", freq="M")
    rows = []
    for k, period in enumerate(periods):
        rows.append({
            "unit_id": "d1", "unit_name": "D1", "parent_code": "CZ", "parent_name": "Coastal Zone",
            "yyyymm": period.year * 100 + period.month, "year": period.year, "month": period.month,
            "viirs_supported_flag": 1, "ba2012_supported_flag": 1,
            "modis_ba_any_ba2012": int(k % 3 == 0), "modis_ba_km2_ba2012": float(k % 3 == 0),
            "viirs_det_primary_any": int(k % 2 == 0), "viirs_det_primary": float(1 + k % 4) if k % 2 == 0 else 0.0,
            "viirs_frp_mean_mw": float(2 + k % 5) if k % 2 == 0 else 0.0,
            "modis_burnable_km2_union_ba2012": 10.0,
        })
    mask = AnalyticalMask("paired", pd.DataFrame({"unit_id": ["d1"], "eligible": [True], "exclusion_reasons": [""]}))
    return pd.DataFrame(rows), mask


def test_paired_support_eligibility_and_positive_fixed_area_are_explicit(bundle) -> None:
    frame, mask = _tiny_paired_frame()
    paired = build_paired_overlap_panel(frame, bundle.analysis, bundle.methods, mask, enforce_governed_counts=False)
    assert len(paired) == 155
    assert paired["viirs_supported_flag"].eq(1).all()
    assert paired["ba2012_supported_flag"].eq(1).all()
    assert paired["modis_burnable_km2_union_ba2012"].gt(0).all()

    broken = frame.copy()
    broken.loc[0, "modis_burnable_km2_union_ba2012"] = 0.0
    with pytest.raises(ObservabilityError, match="positive fixed BA-2012"):
        build_paired_overlap_panel(broken, bundle.analysis, bundle.methods, mask, enforce_governed_counts=False)


def test_missing_support_is_not_converted_to_zero(bundle) -> None:
    frame, mask = _tiny_paired_frame()
    frame.loc[0, "viirs_supported_flag"] = np.nan
    with pytest.raises(ObservabilityError, match="incomplete support"):
        build_paired_overlap_panel(frame, bundle.analysis, bundle.methods, mask, enforce_governed_counts=False)


def test_four_state_source_is_exhaustive_and_mutually_exclusive(design_authority) -> None:
    source = design_authority.paired_four_state_source
    assert len(source) == len(paired_input_reference())
    assert source["observation_state"].notna().all()
    assert set(source["observation_state"]) == {
        "both_zero", "mcd64a1_positive_viirs_zero", "viirs_positive_mcd64a1_zero", "both_positive"
    }
    summary = design_authority.four_state_summary
    overall = summary.loc[summary["summary_scope"].eq("overall")]
    assert int(overall["count"].sum()) == len(paired_input_reference())
    assert np.isclose(float(overall["proportion"].sum()), 1.0)
    by_acz = summary.loc[summary["summary_scope"].eq("acz")]
    assert by_acz["parent_code"].nunique() == 5
    for _, group in by_acz.groupby("parent_code", observed=True):
        assert int(group["count"].sum()) == int(group["denominator_n"].iloc[0])


def test_exact_paired_and_viirs_positive_populations(design_authority) -> None:
    assert len(design_authority.paired_four_state_source) == len(paired_input_reference())
    assert design_authority.paired_four_state_source["unit_id"].nunique() == model_input_reference().unit_id.nunique()
    model = design_authority.model_population_source
    assert len(model) == len(model_input_reference())
    assert model["unit_id"].nunique() == model_input_reference().unit_id.nunique()
    reference = model_input_reference().set_index(["unit_id", "yyyymm"]).sort_index()
    actual = model.set_index(["unit_id", "yyyymm"]).sort_index()
    assert actual.index.tolist() == reference.index.tolist()
    np.testing.assert_array_equal(actual.mismatch_y.to_numpy(dtype=int), reference.mismatch_y.to_numpy(dtype=int))


def test_outcome_definition_is_exact(design_authority) -> None:
    model = design_authority.model_population_source
    expected = 1 - model["modis_ba_any_ba2012"].astype(int)
    np.testing.assert_array_equal(model["mismatch_y"].to_numpy(dtype=int), expected.to_numpy(dtype=int))


def test_exact_predictor_identities_roles_and_exclusions(bundle, design_authority) -> None:
    configured = bundle.analysis.research_questions["rq3"]["predictors"]
    assert [(x["field_role"], x["transform"], x["role"]) for x in configured] == [
        ("rq3.viirs_count", "log2_positive", "focal"),
        ("rq3.mean_frp", "log2_positive", "focal"),
        ("rq3.burnable_area", "log2_positive", "adjustment"),
    ]
    metadata = design_authority.design_metadata
    continuous = metadata.loc[metadata["component"].eq("continuous_predictor")]
    assert continuous["reporting_role"].tolist() == ["focal", "focal", "adjustment"]
    terms = set(metadata["term"])
    assert "log2_viirs_days_active_nh" not in terms
    assert "modis_det_primary_any" not in terms


def test_all_log2_sources_are_strictly_positive(design_authority) -> None:
    model = design_authority.model_population_source
    for field in ("viirs_det_primary", "viirs_frp_mean_mw", "modis_burnable_km2_union_ba2012"):
        assert pd.to_numeric(model[field], errors="raise").gt(0).all()


def test_exact_reference_categories(bundle, design_authority) -> None:
    refs = {x["factor_id"]: (x["reference"], x["reference_label"]) for x in bundle.analysis.research_questions["rq3"]["factors"]}
    assert set(refs) == {x["factor_id"] for x in bundle.analysis.research_questions["rq3"]["factors"]}
    terms = set(design_authority.design_metadata["term"])
    assert "month_1" not in terms and "year_2013" not in terms and "acz_CZ" not in terms


def test_configured_term_identity_and_order(design_authority) -> None:
    expected = design_terms_reference()
    assert design_authority.gee_design.term_order == expected
    assert tuple(design_authority.design_metadata.columns) == RQ3_DESIGN_METADATA_COLUMNS
    assert design_authority.design_metadata["term"].tolist() == list(expected)
    assert design_authority.mean_model_design.shape == (len(model_input_reference()), len(design_terms_reference()) + 3)  # unit/time/outcome + 31 design columns


def test_design_is_full_rank(design_authority) -> None:
    X = design_authority.gee_design.design_matrix.to_numpy(dtype=float)
    assert X.shape == (len(model_input_reference()), len(design_terms_reference()))
    assert np.linalg.matrix_rank(X) == len(design_terms_reference())


def test_vif_matches_independent_inverse_correlation_reference(design_authority) -> None:
    terms = [
        "log2_viirs_det_primary", "log2_viirs_frp_mean_mw", "log2_modis_burnable_km2_union_ba2012"
    ]
    X = design_authority.gee_design.design_matrix[terms].to_numpy(dtype=float)
    correlation = np.corrcoef(X, rowvar=False)
    independent_vif = np.diag(np.linalg.inv(correlation))
    actual = design_authority.predictor_vif.set_index("variable").loc[terms, "vif"].to_numpy(dtype=float)
    np.testing.assert_allclose(actual, independent_vif, rtol=1e-10, atol=1e-10)
    raw = model_input_reference()
    reference_predictors = np.log2(raw[["viirs_det_primary", "viirs_frp_mean_mw", "modis_burnable_km2_union_ba2012"]].to_numpy(dtype=float))
    np.testing.assert_allclose(actual, np.diag(np.linalg.inv(np.corrcoef(reference_predictors, rowvar=False))), rtol=1e-10, atol=1e-10)


def test_factor_outcome_table_reports_exact_counts_without_near_threshold(design_authority) -> None:
    table = design_authority.factor_outcome_counts
    assert tuple(table.columns) == RQ3_FACTOR_OUTCOME_COLUMNS
    assert "near_separation" not in table.columns
    reference = factor_outcomes_by_key(factor_outcome_reference())
    actual = factor_outcomes_by_key(table)
    pd.testing.assert_index_equal(actual.index, reference.index)
    for field in ("n", "y1", "y0", "complete_separation"):
        np.testing.assert_array_equal(actual[field].to_numpy(), reference[field].to_numpy())


def test_all_y1_clusters_are_identified_exactly(design_authority) -> None:
    table = design_authority.cluster_outcome_counts
    assert tuple(table.columns) == RQ3_CLUSTER_OUTCOME_COLUMNS
    assert len(table) == model_input_reference().unit_id.nunique()
    reference = cluster_reference()
    assert set(table.loc[table.all_y1, "cluster"]) == set(reference.index[reference["sum"].eq(reference["size"])])
    assert set(table.loc[table.all_y0, "cluster"]) == set(reference.index[reference["sum"].eq(0)])
    assert table.loc[table["all_y1"], "cluster"].is_unique


def test_realised_run_manifest_records_design_references_transforms_and_roles(design_authority) -> None:
    meta = design_authority.realised_run_metadata
    assert meta["realised_sample_sizes"]["rq3_paired_rows"] == len(paired_input_reference())
    assert meta["realised_sample_sizes"]["rq3_model_rows"] == len(model_input_reference())
    assert meta["realised_sample_sizes"]["rq3_model_districts"] == model_input_reference().unit_id.nunique()
    assert len(meta["rq3_design_columns"]) == len(design_terms_reference())
    bundle = load_configuration_bundle(SUBPROJECT / "config")
    assert meta["factor_references"] == {x["factor_id"]: x["reference"] for x in bundle.analysis.research_questions["rq3"]["factors"]}
    assert meta["rq3_transformations"] == {
        "log2_viirs_det_primary": "log2_positive",
        "log2_viirs_frp_mean_mw": "log2_positive",
        "log2_modis_burnable_km2_union_ba2012": "log2_positive",
    }
    assert meta["rq3_reporting_roles"] == {
        "log2_viirs_det_primary": "focal",
        "log2_viirs_frp_mean_mw": "focal",
        "log2_modis_burnable_km2_union_ba2012": "adjustment",
    }


def test_design_construction_is_deterministic(design_authority, bundle) -> None:
    again = mean_model_column_provenance(design_authority.gee_design, bundle.analysis)
    pd.testing.assert_frame_equal(design_authority.design_metadata.reset_index(drop=True), again.reset_index(drop=True))
    left = design_authority.mean_model_design.to_csv(index=False, lineterminator="\n")
    right = design_authority.mean_model_design.copy().to_csv(index=False, lineterminator="\n")
    assert left == right
