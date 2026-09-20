"""Config-driven RQ3 cross-product observability authorities.

The analysis contract owns population restrictions, variables, predictor roles,
transforms, factors and inferential method IDs.  This module supplies generic
construction and diagnostics.  No predictor may be added, removed or reclassified
by a Python literal or a diagnostic result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .contracts import AnalysisContract, ConfigurationBundle, MethodAuthorityContract, OutputContract
from .config import build_realised_run_metadata
from .data_io import DataAuthorities
from .design import assert_execution_ready
from .gee import (
    GEEMeanModelDesign,
    RQ3PGEEProductionResult,
    build_gee_mean_model_design,
    mean_model_column_provenance,
    mean_model_design_authority,
    run_current_rq3_pgee_production,
)
from .pgee import SeparationDiagnostics, separation_diagnostics
from .validation import AnalyticalMask, DataContractSummary
from .variables import resolve_field_role


class ObservabilityError(ValueError):
    """Raised when RQ3 construction violates the injected scientific contract."""


OBSERVATION_STATES: tuple[str, ...] = (
    "both_zero",
    "mcd64a1_positive_viirs_zero",
    "viirs_positive_mcd64a1_zero",
    "both_positive",
)

FOUR_STATE_SUMMARY_COLUMNS: tuple[str, ...] = (
    "summary_scope", "parent_code", "parent_name", "state", "count", "denominator_n", "percentage"
)
CONTINUOUS_MODEL_SUMMARY_COLUMNS: tuple[str, ...] = (
    "term", "predictor_role", "beta", "corrected_se", "z", "p", "adjusted_or",
    "or_lower_95", "or_upper_95", "n", "districts", "estimator", "working_structure",
    "covariance_method", "reference_distribution",
)
PREDICTOR_DIAGNOSTICS_COLUMNS: tuple[str, ...] = (
    "record_type", "variable", "comparison_variable", "n", "mean", "sd", "min", "q25",
    "median", "q75", "max", "correlation", "vif", "interpretation",
)
FIT_DIAGNOSTICS_COLUMNS: tuple[str, ...] = (
    "observations", "districts", "outcome_y1", "outcome_y0", "outcome_prevalence_y1",
    "model_columns", "model_rank", "complete_separation_levels",
    "all_y1_clusters", "all_y0_clusters", "cluster_size_min", "cluster_size_median",
    "cluster_size_mean", "cluster_size_max", "estimator", "working_structure",
    "covariance_estimator", "reference_distribution", "convergence",
    "finite_coefficient_status", "finite_covariance_status",
)
FULL_COEFFICIENT_COLUMNS: tuple[str, ...] = (
    "term_order", "term", "term_role", "source_id", "coding", "reference_level",
    "is_focal_predictor", "beta", "corrected_se", "z", "p", "adjusted_or",
    "or_lower_95", "or_upper_95", "n", "districts", "estimator", "working_structure",
    "covariance_method", "reference_distribution",
)
DISTRICT_MISMATCH_COLUMNS: tuple[str, ...] = (
    "unit_id", "unit_name", "parent_code", "parent_name", "paired_months",
    "viirs_positive_months", "viirs_only_months", "viirs_only_share",
)
FOCAL_EFFECT_COLUMNS: tuple[str, ...] = (
    "display_order", "term", "adjusted_or", "or_lower_95", "or_upper_95", "p", "n", "districts"
)
STANDARDISED_PROBABILITY_COLUMNS: tuple[str, ...] = (
    "predictor_id", "term", "predictor_role", "quantile", "raw_quantile_value",
    "transformed_quantile_value", "standardised_probability", "n", "districts",
    "model_spec_sha256", "design_matrix_sha256", "configuration_sha256",
    "standardisation_method", "averaging_distribution",
)
FULL_MODEL_AUTHORITY_COLUMNS: tuple[str, ...] = (
    "record_type", "term", "term_role", "estimate", "standard_error", "test_statistic",
    "p_value", "confidence_low", "confidence_high", "diagnostic_name", "diagnostic_value",
    "standardisation_predictor", "standardisation_quantile", "standardised_probability",
)

RQ3_DESIGN_METADATA_COLUMNS: tuple[str, ...] = (
    "column_order", "term", "component", "source_field", "field_role",
    "transform_or_coding", "reporting_role", "factor_id", "factor_level",
    "reference_level", "design_dimension",
)
RQ3_FACTOR_OUTCOME_COLUMNS: tuple[str, ...] = (
    "factor", "level", "n", "y1", "y0", "prevalence_y1", "complete_separation",
)
RQ3_CLUSTER_OUTCOME_COLUMNS: tuple[str, ...] = (
    "cluster", "n", "y1", "y0", "all_y1", "all_y0",
)


@dataclass(frozen=True, slots=True)
class PredictorDiagnostics:
    correlation: pd.DataFrame
    vif: pd.DataFrame


@dataclass(frozen=True, slots=True)
class RQ3DesignAuthority:
    paired_four_state_source: pd.DataFrame
    four_state_summary: pd.DataFrame
    model_population_source: pd.DataFrame
    mean_model_design: pd.DataFrame
    design_metadata: pd.DataFrame
    predictor_correlation: pd.DataFrame
    predictor_vif: pd.DataFrame
    factor_outcome_counts: pd.DataFrame
    cluster_outcome_counts: pd.DataFrame
    gee_design: GEEMeanModelDesign
    realised_run_metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class RQ3ProductionPGEE:
    separation: SeparationDiagnostics
    production: RQ3PGEEProductionResult


@dataclass(frozen=True, slots=True)
class RQ3Tables:
    correspondence: pd.DataFrame
    district_mismatch_authority: pd.DataFrame
    model_population: pd.DataFrame
    mean_model_design: pd.DataFrame
    paired_panel: pd.DataFrame
    predictor_diagnostics: PredictorDiagnostics
    gee_design: GEEMeanModelDesign
    separation_diagnostics: pd.DataFrame
    production_pgee: RQ3ProductionPGEE
    four_state_summary_source: pd.DataFrame
    continuous_model_summary_source: pd.DataFrame
    predictor_diagnostics_source: pd.DataFrame
    fit_diagnostics_source: pd.DataFrame
    full_coefficient_source: pd.DataFrame
    standardised_probability_source: pd.DataFrame
    full_model_authority: pd.DataFrame
    district_mismatch_source: pd.DataFrame
    focal_effect_source: pd.DataFrame




def _field(analysis: AnalysisContract, role: str) -> str:
    value = resolve_field_role(analysis, role)
    if not isinstance(value, str):
        raise ObservabilityError(f"RQ3 role must resolve to one field: {role!r}")
    return value


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], context: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ObservabilityError(f"Missing required columns in {context}: {missing!r}")


def _retained_ids(mask: AnalyticalMask) -> set[str]:
    return set(mask.units.loc[mask.units["eligible"].astype(bool), "unit_id"].astype(str))


def _overlap_yyyymm(analysis: AnalysisContract) -> list[int]:
    window = analysis.study["temporal_windows"]["overlap_monthly"]
    periods = pd.period_range(str(window["start"]), str(window["end"]), freq="M")
    return [int(p.year * 100 + p.month) for p in periods]


def classify_observation_states(frame: pd.DataFrame, analysis: AnalysisContract) -> pd.Series:
    rq3 = analysis.research_questions["rq3"]
    states = tuple(str(x) for x in rq3["four_state_correspondence"]["states"])
    if len(states) != 4 or len(set(states)) != 4:
        raise ObservabilityError("Four-state correspondence requires four unique configured state IDs")
    ba_field = _field(analysis, str(rq3["outcome"]["burned_area_presence_role"]))
    viirs_field = _field(analysis, "rq3.viirs_presence")
    _require_columns(frame, [ba_field, viirs_field], "four-state input")
    ba = pd.to_numeric(frame[ba_field], errors="coerce")
    viirs = pd.to_numeric(frame[viirs_field], errors="coerce")
    if ba.isna().any() or viirs.isna().any() or not ba.isin([0, 1]).all() or not viirs.isin([0, 1]).all():
        raise ObservabilityError("Four-state classification requires supported non-missing binary flags")
    # Map by semantic condition, not by outcome frequencies.
    semantic = {
        "both_zero": ba.eq(0) & viirs.eq(0),
        "mcd64a1_positive_viirs_zero": ba.eq(1) & viirs.eq(0),
        "viirs_positive_mcd64a1_zero": ba.eq(0) & viirs.eq(1),
        "both_positive": ba.eq(1) & viirs.eq(1),
    }
    if set(states) != set(semantic):
        raise ObservabilityError("Configured four-state IDs are not recognised by the implementation")
    values = np.select([semantic[state] for state in states], states, default="invalid")
    result = pd.Series(values, index=frame.index, dtype="string")
    if result.eq("invalid").any():
        raise ObservabilityError("Four-state classification was not exhaustive")
    return result


def build_paired_overlap_panel(
    district_panel: pd.DataFrame,
    analysis: AnalysisContract,
    methods: MethodAuthorityContract,
    paired_mask: AnalyticalMask,
    *,
    enforce_governed_counts: bool = True,
) -> pd.DataFrame:
    """Build the configured paired-overlap population from field roles and support semantics."""
    assert_execution_ready(analysis.to_dict(), methods, "rq3")
    rq3 = analysis.research_questions["rq3"]
    pop = analysis.study["populations"][str(rq3["descriptive_population"])]
    unit = _field(analysis, "keys.unit_id")
    unit_name = _field(analysis, "keys.unit_name")
    parent_code = _field(analysis, "keys.parent_code")
    parent_name = _field(analysis, "keys.parent_name")
    yyyymm = _field(analysis, "keys.yyyymm")
    required_roles = [
        "keys.year", "keys.month", "rq3.ba_presence", "rq3.ba_area", "rq3.viirs_presence",
        "rq3.viirs_count", "rq3.mean_frp", "rq3.burnable_area",
    ]
    required = [unit, unit_name, parent_code, parent_name, yyyymm]
    required.extend(_field(analysis, role) for role in required_roles)
    support_fields = [_field(analysis, str(role)) for role in pop.get("support_roles", ())]
    required.extend(support_fields)
    _require_columns(district_panel, required, "district panel")

    ids = _retained_ids(paired_mask)
    months = _overlap_yyyymm(analysis)
    selected = district_panel.loc[
        district_panel[unit].astype(str).isin(ids) & district_panel[yyyymm].isin(months)
    ].copy().sort_values([unit, yyyymm]).reset_index(drop=True)
    if enforce_governed_counts:
        if len(selected) != int(pop["rows"]):
            raise ObservabilityError(f"Paired overlap has {len(selected)} rows; expected {int(pop['rows'])}")
        if int(selected[unit].nunique()) != int(pop["units"]):
            raise ObservabilityError("Paired overlap unit count disagrees with configured population authority")
    if selected[[unit, yyyymm]].duplicated().any():
        raise ObservabilityError("Paired overlap contains duplicate unit-month keys")
    for flag in support_fields:
        values = pd.to_numeric(selected[str(flag)], errors="coerce")
        if values.isna().any() or not values.eq(1).all():
            raise ObservabilityError(f"Paired analytical row has incomplete support flag {flag}")
    denominator_role = pop.get("denominator_role")
    if denominator_role:
        denominator_field = _field(analysis, str(denominator_role))
        denominator = pd.to_numeric(selected[denominator_field], errors="coerce")
        if denominator.isna().any() or not denominator.gt(0).all():
            raise ObservabilityError(
                "Paired analytical population requires non-missing positive fixed BA-2012 burnable area"
            )

    selected["observation_state"] = classify_observation_states(selected, analysis)
    viirs_count = _field(analysis, "rq3.viirs_count")
    selected["viirs_positive"] = pd.to_numeric(selected[viirs_count], errors="raise").gt(0).astype(int)
    selected["mismatch_y"] = pd.array([pd.NA] * len(selected), dtype="Int64")
    ba_field = _field(analysis, str(rq3["outcome"]["burned_area_presence_role"]))
    positive = selected["viirs_positive"].eq(1)
    selected.loc[positive, "mismatch_y"] = (
        1 - pd.to_numeric(selected.loc[positive, ba_field], errors="raise").astype(int)
    ).astype("Int64")
    return selected


def summarise_correspondence(panel: pd.DataFrame, analysis: AnalysisContract | None = None) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if analysis is None:
        code_field, name_field = "parent_code", "parent_name"
        states = OBSERVATION_STATES
    else:
        code_field, name_field = _field(analysis, "keys.parent_code"), _field(analysis, "keys.parent_name")
        states = tuple(str(x) for x in analysis.research_questions["rq3"]["four_state_correspondence"]["states"])
    groups: list[tuple[str, str | None, str | None, pd.DataFrame]] = [("overall", None, "Overall", panel)]
    for code, group in panel.groupby(code_field, sort=True, observed=True):
        groups.append(("acz", str(code), str(group[name_field].iloc[0]), group))
    for scope, code, parent_name, group in groups:
        n = len(group)
        for state in states:
            count = int(group["observation_state"].eq(state).sum())
            rows.append({
                "summary_scope": scope, "parent_code": code, "parent_name": parent_name,
                "state": state, "count": count, "denominator_n": n,
                "proportion": count / n if n else np.nan,
            })
    rank = {state: i for i, state in enumerate(states)}
    result = pd.DataFrame(rows)
    result["_state_order"] = result["state"].map(rank)
    return result.sort_values(["summary_scope", "parent_code", "_state_order"], na_position="first").drop(columns="_state_order").reset_index(drop=True)


def summarise_district_mismatch(panel: pd.DataFrame, analysis: AnalysisContract | None = None) -> pd.DataFrame:
    if analysis is None:
        unit, unit_name, parent_code, parent_name = "unit_id", "unit_name", "parent_code", "parent_name"
    else:
        unit = _field(analysis, "keys.unit_id"); unit_name = _field(analysis, "keys.unit_name")
        parent_code = _field(analysis, "keys.parent_code"); parent_name = _field(analysis, "keys.parent_name")
    rows: list[dict[str, object]] = []
    for unit_id, group in panel.groupby(unit, sort=True, observed=True):
        vp = group.loc[group["viirs_positive"].eq(1)]
        mismatch = int(vp["mismatch_y"].astype(int).sum()) if len(vp) else 0
        rows.append({
            "unit_id": str(unit_id), "unit_name": str(group[unit_name].iloc[0]),
            "parent_code": str(group[parent_code].iloc[0]), "parent_name": str(group[parent_name].iloc[0]),
            "paired_months": int(len(group)), "viirs_positive_months": int(len(vp)),
            "viirs_only_months": mismatch,
            "viirs_only_share_among_viirs_positive": mismatch / len(vp) if len(vp) else np.nan,
        })
    return pd.DataFrame(rows).sort_values("unit_id").reset_index(drop=True)


def _continuous_predictor_terms(analysis: AnalysisContract) -> list[str]:
    return [
        str(item["term_name"])
        for item in analysis.research_questions["rq3"]["predictors"]
        if str(item["transform"]) in {"log2_positive", "identity"}
    ]


def _variance_inflation_factors(frame: pd.DataFrame) -> pd.DataFrame:
    """Compute ordinary VIF values for continuous columns, without selection authority."""
    values = frame.to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    for j, name in enumerate(frame.columns):
        y = values[:, j]
        others = np.delete(values, j, axis=1)
        if others.shape[1] == 0:
            vif = 1.0
        else:
            X = np.column_stack([np.ones(len(y)), others])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            fitted = X @ coef
            ss_res = float(np.square(y - fitted).sum())
            ss_tot = float(np.square(y - y.mean()).sum())
            r2 = 0.0 if ss_tot == 0.0 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
            vif = float("inf") if r2 >= 1.0 else 1.0 / (1.0 - r2)
        rows.append({"variable": str(name), "vif": vif})
    return pd.DataFrame(rows)


def predictor_diagnostics(design: GEEMeanModelDesign, analysis: AnalysisContract) -> PredictorDiagnostics:
    terms = _continuous_predictor_terms(analysis)
    corr = design.design_matrix[terms].corr(method="pearson")
    corr.index.name = "term"
    vif = _variance_inflation_factors(design.design_matrix[terms])
    return PredictorDiagnostics(correlation=corr.reset_index(), vif=vif)


def _run_production(
    design: GEEMeanModelDesign, analysis: AnalysisContract, methods: MethodAuthorityContract,
    *, configuration_sha256: str | None = None,
) -> RQ3ProductionPGEE:
    diagnostic = separation_diagnostics(design.frame, design.design_matrix, design.outcome, design.clusters)
    if diagnostic.outcome_n != design.n_observations or diagnostic.design_columns != len(design.term_order):
        raise ObservabilityError("Pre-fit diagnostic does not cover the configured RQ3 design")
    if diagnostic.design_rank != diagnostic.design_columns:
        raise ObservabilityError("Configured RQ3 design is not full rank")
    return RQ3ProductionPGEE(
        diagnostic,
        run_current_rq3_pgee_production(
            design, analysis, methods, configuration_sha256=configuration_sha256
        ),
    )


def _build_four_state_summary(correspondence: pd.DataFrame) -> pd.DataFrame:
    result = correspondence[["summary_scope", "parent_code", "parent_name", "state", "count", "denominator_n", "proportion"]].copy()
    result["percentage"] = result.pop("proportion") * 100.0
    return result.loc[:, FOUR_STATE_SUMMARY_COLUMNS]


def _build_full_coefficient_source(production: RQ3PGEEProductionResult) -> pd.DataFrame:
    a = production.production.coefficient_authority.copy()
    result = pd.DataFrame({
        "term_order": a["term_order"].astype(int), "term": a["term"].astype(str),
        "term_role": a["term_role"].astype(str), "source_id": a["source_id"].astype(str),
        "coding": a["coding"].astype(str), "reference_level": a["reference_level"],
        "is_focal_predictor": a["is_focal_predictor"].astype(bool), "beta": a["coefficient"].astype(float),
        "corrected_se": a["corrected_se"].astype(float), "z": a["wald_z"].astype(float),
        "p": a["standard_normal_p"].astype(float), "adjusted_or": a["adjusted_or"],
        "or_lower_95": a["adjusted_or_ci_low"], "or_upper_95": a["adjusted_or_ci_high"],
        "n": a["n_observations"].astype(int), "districts": a["n_clusters"].astype(int),
        "estimator": a["estimator"].astype(str), "working_structure": a["working_structure"].astype(str),
        "covariance_method": a["covariance_method"].astype(str),
        "reference_distribution": a["reference_distribution"].astype(str),
    })
    return result.sort_values("term_order").reset_index(drop=True).loc[:, FULL_COEFFICIENT_COLUMNS]


def _build_continuous_model_summary(full_coefficients: pd.DataFrame) -> pd.DataFrame:
    # Main association table uses all configured continuous predictor rows; the
    # contract determines which are focal versus adjustment.
    rows = full_coefficients.loc[full_coefficients["term_role"].astype(str).str.endswith("_predictor")].copy()
    return pd.DataFrame({
        "term": rows["term"], "predictor_role": rows["term_role"].str.removesuffix("_predictor"),
        "beta": rows["beta"], "corrected_se": rows["corrected_se"], "z": rows["z"], "p": rows["p"],
        "adjusted_or": rows["adjusted_or"], "or_lower_95": rows["or_lower_95"],
        "or_upper_95": rows["or_upper_95"], "n": rows["n"], "districts": rows["districts"],
        "estimator": rows["estimator"], "working_structure": rows["working_structure"],
        "covariance_method": rows["covariance_method"], "reference_distribution": rows["reference_distribution"],
    }).reset_index(drop=True).loc[:, CONTINUOUS_MODEL_SUMMARY_COLUMNS]


def _build_predictor_diagnostics(design: GEEMeanModelDesign, analysis: AnalysisContract) -> pd.DataFrame:
    rq3 = analysis.research_questions["rq3"]
    terms = _continuous_predictor_terms(analysis)
    rows: list[dict[str, object]] = []
    vifs = _variance_inflation_factors(design.design_matrix[terms]).set_index("variable")["vif"]
    for item in rq3["predictors"]:
        term = str(item["term_name"])
        values = pd.to_numeric(design.design_matrix[term], errors="raise").astype(float)
        rows.append({
            "record_type": "distribution", "variable": term, "comparison_variable": None,
            "n": int(values.size), "mean": float(values.mean()), "sd": float(values.std(ddof=1)),
            "min": float(values.min()), "q25": float(values.quantile(.25)), "median": float(values.median()),
            "q75": float(values.quantile(.75)), "max": float(values.max()), "correlation": None,
            "vif": float(vifs.loc[term]), "interpretation": f"descriptive_{item['role']}_predictor",
        })
    corr = design.design_matrix[terms].corr(method="pearson")
    for left in terms:
        for right in terms:
            rows.append({
                "record_type": "correlation", "variable": left, "comparison_variable": right,
                "n": int(design.n_observations), "mean": None, "sd": None, "min": None, "q25": None,
                "median": None, "q75": None, "max": None, "correlation": float(corr.loc[left, right]),
                "vif": None, "interpretation": "descriptive_correlation_only",
            })
    return pd.DataFrame(rows).loc[:, PREDICTOR_DIAGNOSTICS_COLUMNS]


def _build_fit_diagnostics(production: RQ3ProductionPGEE, analysis: AnalysisContract) -> pd.DataFrame:
    d, fit = production.separation, production.production.fit
    rq3 = analysis.research_questions["rq3"]
    return pd.DataFrame([{
        "observations": int(d.outcome_n), "districts": int(fit.n_clusters), "outcome_y1": int(d.outcome_y1),
        "outcome_y0": int(d.outcome_y0), "outcome_prevalence_y1": float(d.outcome_prevalence_y1),
        "model_columns": int(d.design_columns), "model_rank": int(d.design_rank),
        "complete_separation_levels": "|".join(d.complete_separation_levels),
        "all_y1_clusters": int(d.all_y1_clusters), "all_y0_clusters": int(d.all_y0_clusters),
        "cluster_size_min": int(d.cluster_size_min), "cluster_size_median": float(d.cluster_size_median),
        "cluster_size_mean": float(d.cluster_size_mean), "cluster_size_max": int(d.cluster_size_max),
        "estimator": str(rq3["estimator"]), "working_structure": str(rq3["working_correlation"]),
        "covariance_estimator": str(rq3["covariance"]), "reference_distribution": str(rq3["reference_distribution"]),
        "convergence": "PASS" if fit.converged else "FAIL",
        "finite_coefficient_status": "PASS" if fit.coefficients_finite else "FAIL",
        "finite_covariance_status": "PASS" if fit.covariance_finite else "FAIL",
    }]).loc[:, FIT_DIAGNOSTICS_COLUMNS]


def _build_full_model_authority(
    production: RQ3ProductionPGEE,
    predictor_diagnostics_source: pd.DataFrame,
    fit_diagnostics_source: pd.DataFrame,
) -> pd.DataFrame:
    """Build the governed long-form supplementary RQ3 model authority."""
    coeff = production.production.coefficient_authority
    rows: list[dict[str, object]] = []
    for _, item in coeff.iterrows():
        rows.append({
            "record_type": "coefficient",
            "term": str(item["term"]),
            "term_role": str(item["term_role"]),
            "estimate": float(item["coefficient"]),
            "standard_error": float(item["corrected_se"]),
            "test_statistic": float(item["wald_z"]),
            "p_value": float(item["standard_normal_p"]),
            "confidence_low": float(item["ci_low"]),
            "confidence_high": float(item["ci_high"]),
            "diagnostic_name": None, "diagnostic_value": None,
            "standardisation_predictor": None, "standardisation_quantile": None,
            "standardised_probability": None,
        })

    distributions = predictor_diagnostics_source.loc[predictor_diagnostics_source["record_type"].eq("distribution")].copy()
    for _, item in distributions.iterrows():
        rows.append({
            "record_type": "diagnostic", "term": str(item["variable"]),
            "term_role": "continuous_predictor", "estimate": None, "standard_error": None,
            "test_statistic": None, "p_value": None, "confidence_low": None,
            "confidence_high": None, "diagnostic_name": "vif",
            "diagnostic_value": float(item["vif"]), "standardisation_predictor": None,
            "standardisation_quantile": None, "standardised_probability": None,
        })
    correlations = predictor_diagnostics_source.loc[predictor_diagnostics_source["record_type"].eq("correlation")].copy()
    for _, item in correlations.iterrows():
        rows.append({
            "record_type": "diagnostic", "term": str(item["variable"]),
            "term_role": "continuous_predictor", "estimate": None, "standard_error": None,
            "test_statistic": None, "p_value": None, "confidence_low": None,
            "confidence_high": None,
            "diagnostic_name": f"correlation_with:{item['comparison_variable']}",
            "diagnostic_value": float(item["correlation"]), "standardisation_predictor": None,
            "standardisation_quantile": None, "standardised_probability": None,
        })

    summary = fit_diagnostics_source.iloc[0]
    for name in (
        "observations", "districts", "outcome_y1", "outcome_y0", "model_columns", "model_rank",
        "all_y1_clusters", "all_y0_clusters", "cluster_size_min", "cluster_size_max",
    ):
        rows.append({
            "record_type": "diagnostic", "term": None, "term_role": None, "estimate": None,
            "standard_error": None, "test_statistic": None, "p_value": None,
            "confidence_low": None, "confidence_high": None, "diagnostic_name": name,
            "diagnostic_value": float(summary[name]), "standardisation_predictor": None,
            "standardisation_quantile": None, "standardised_probability": None,
        })
    for name in ("convergence", "finite_coefficient_status", "finite_covariance_status"):
        rows.append({
            "record_type": "diagnostic", "term": None, "term_role": None, "estimate": None,
            "standard_error": None, "test_statistic": None, "p_value": None,
            "confidence_low": None, "confidence_high": None, "diagnostic_name": name,
            "diagnostic_value": 1.0 if str(summary[name]) == "PASS" else 0.0,
            "standardisation_predictor": None, "standardisation_quantile": None,
            "standardised_probability": None,
        })

    std = production.production.standardised_probability_authority
    for _, item in std.iterrows():
        rows.append({
            "record_type": "standardised_probability", "term": str(item["term"]),
            "term_role": "focal_predictor", "estimate": None, "standard_error": None,
            "test_statistic": None, "p_value": None, "confidence_low": None,
            "confidence_high": None, "diagnostic_name": None, "diagnostic_value": None,
            "standardisation_predictor": str(item["predictor_id"]),
            "standardisation_quantile": float(item["quantile"]),
            "standardised_probability": float(item["standardised_probability"]),
        })
    return pd.DataFrame(rows).loc[:, FULL_MODEL_AUTHORITY_COLUMNS]


def _build_district_mismatch_source(district_mismatch: pd.DataFrame) -> pd.DataFrame:
    return district_mismatch.rename(columns={"viirs_only_share_among_viirs_positive": "viirs_only_share"}).loc[:, DISTRICT_MISMATCH_COLUMNS].sort_values("unit_id").reset_index(drop=True)


def _build_focal_effect_source(continuous_model_summary: pd.DataFrame) -> pd.DataFrame:
    focal = continuous_model_summary.loc[continuous_model_summary["predictor_role"].eq("focal")].reset_index(drop=True)
    result = pd.DataFrame({
        "display_order": np.arange(1, len(focal) + 1, dtype=int), "term": focal["term"],
        "adjusted_or": focal["adjusted_or"], "or_lower_95": focal["or_lower_95"],
        "or_upper_95": focal["or_upper_95"], "p": focal["p"], "n": focal["n"], "districts": focal["districts"],
    })
    return result.loc[:, FOCAL_EFFECT_COLUMNS]


def build_rq3_design_authority(
    authorities: DataAuthorities,
    data_contract: DataContractSummary,
    bundle: ConfigurationBundle,
    *,
    methods_spec_sha256: str,
    data_sha256: str,
) -> RQ3DesignAuthority:
    """Build the frozen RQ3 population, exact design, and diagnostics without fitting PGEE.

    This design authority deliberately stops before estimator
    execution: the existing PGEE implementation is not changed or used to define
    population/design membership.
    """
    analysis, methods = bundle.analysis, bundle.methods
    paired = build_paired_overlap_panel(
        authorities.district_panel, analysis, methods, data_contract.paired_mask,
        enforce_governed_counts=True,
    )
    correspondence = summarise_correspondence(paired, analysis)
    design = build_gee_mean_model_design(paired, analysis, enforce_governed_counts=True)
    provenance = mean_model_column_provenance(design, analysis)
    diagnostics = predictor_diagnostics(design, analysis)
    separation = separation_diagnostics(
        design.frame, design.design_matrix, design.outcome, design.clusters
    )

    factor_counts = separation.level_table.loc[:, RQ3_FACTOR_OUTCOME_COLUMNS].copy()
    cluster_counts = separation.cluster_table.loc[:, RQ3_CLUSTER_OUTCOME_COLUMNS].copy()

    rq3 = analysis.research_questions["rq3"]
    predictor_transforms = {
        str(item["term_name"]): str(item["transform"]) for item in rq3["predictors"]
    }
    reporting_roles = {
        str(item["term_name"]): str(item["role"]) for item in rq3["predictors"]
    }
    factor_refs = {str(item["factor_id"]): item["reference"] for item in rq3["factors"]}
    metadata = build_realised_run_metadata(
        bundle,
        methods_spec_sha256=methods_spec_sha256,
        data_sha256=data_sha256,
        realised_sample_sizes={
            "rq3_paired_rows": int(len(paired)),
            "rq3_paired_districts": int(paired[_field(analysis, "keys.unit_id")].nunique()),
            "rq3_model_rows": int(design.n_observations),
            "rq3_model_districts": int(design.n_clusters),
            "rq3_outcome_y1": int(design.outcome.sum()),
            "rq3_outcome_y0": int(len(design.outcome) - design.outcome.sum()),
        },
        rq3_design_columns=design.term_order,
        factor_references=factor_refs,
        rq3_transformations=predictor_transforms,
        rq3_reporting_roles=reporting_roles,
    ).to_dict()

    paired_source_columns = [
        _field(analysis, "keys.unit_id"), _field(analysis, "keys.unit_name"),
        _field(analysis, "keys.parent_code"), _field(analysis, "keys.parent_name"),
        _field(analysis, "keys.yyyymm"), _field(analysis, "keys.year"),
        _field(analysis, "keys.month"), _field(analysis, "rq3.viirs_support"),
        _field(analysis, "rq3.ba2012_support"), _field(analysis, "rq3.viirs_count"),
        _field(analysis, "rq3.ba_presence"), "observation_state", "viirs_positive", "mismatch_y",
    ]
    paired_source = paired.loc[:, paired_source_columns].copy()

    model_fields = [
        _field(analysis, "keys.unit_id"), _field(analysis, "keys.unit_name"),
        _field(analysis, "keys.parent_code"), _field(analysis, "keys.parent_name"),
        _field(analysis, "keys.yyyymm"), _field(analysis, "keys.year"), _field(analysis, "keys.month"),
        _field(analysis, str(rq3["outcome"]["burned_area_presence_role"])),
    ]
    model_fields.extend(_field(analysis, str(item["field_role"])) for item in rq3["predictors"])
    model_fields = list(dict.fromkeys(model_fields)) + ["mismatch_y"]
    model_source = design.frame.loc[:, model_fields].copy()

    return RQ3DesignAuthority(
        paired_four_state_source=paired_source,
        four_state_summary=correspondence,
        model_population_source=model_source,
        mean_model_design=mean_model_design_authority(design, analysis),
        design_metadata=provenance.loc[:, RQ3_DESIGN_METADATA_COLUMNS].copy(),
        predictor_correlation=diagnostics.correlation.copy(),
        predictor_vif=diagnostics.vif.copy(),
        factor_outcome_counts=factor_counts,
        cluster_outcome_counts=cluster_counts,
        gee_design=design,
        realised_run_metadata=metadata,
    )


def build_rq3_tables(
    authorities: DataAuthorities,
    data_contract: DataContractSummary,
    analysis: AnalysisContract,
    methods: MethodAuthorityContract,
    *,
    configuration_sha256: str | None = None,
) -> RQ3Tables:
    paired = build_paired_overlap_panel(authorities.district_panel, analysis, methods, data_contract.paired_mask)
    design = build_gee_mean_model_design(paired, analysis, enforce_governed_counts=True)
    correspondence = summarise_correspondence(paired, analysis)
    district_mismatch = summarise_district_mismatch(paired, analysis)
    production = _run_production(
        design, analysis, methods, configuration_sha256=configuration_sha256
    )
    full_coefficients = _build_full_coefficient_source(production)
    continuous_model_summary = _build_continuous_model_summary(full_coefficients)
    predictor_diagnostic_source = _build_predictor_diagnostics(design, analysis)
    fit_diagnostic_source = _build_fit_diagnostics(production, analysis)
    standardised = production.production.standardised_probability_authority.loc[:, STANDARDISED_PROBABILITY_COLUMNS].copy()
    full_model = _build_full_model_authority(production, predictor_diagnostic_source, fit_diagnostic_source)
    return RQ3Tables(
        correspondence=correspondence, district_mismatch_authority=district_mismatch,
        model_population=design.frame.copy(), mean_model_design=mean_model_design_authority(design, analysis),
        paired_panel=paired, predictor_diagnostics=predictor_diagnostics(design, analysis), gee_design=design,
        separation_diagnostics=production.separation.level_table, production_pgee=production,
        four_state_summary_source=_build_four_state_summary(correspondence),
        continuous_model_summary_source=continuous_model_summary,
        predictor_diagnostics_source=predictor_diagnostic_source,
        fit_diagnostics_source=fit_diagnostic_source,
        full_coefficient_source=full_coefficients, standardised_probability_source=standardised,
        full_model_authority=full_model, district_mismatch_source=_build_district_mismatch_source(district_mismatch),
        focal_effect_source=_build_focal_effect_source(continuous_model_summary),
    )


def run_rq3_pgee_production(tables: RQ3Tables, analysis: AnalysisContract) -> RQ3ProductionPGEE:
    design, production = tables.gee_design, tables.production_pgee
    fit = production.production.fit
    if fit.n_observations != design.n_observations or fit.n_clusters != design.n_clusters:
        raise ObservabilityError("Integrated PGEE does not match configured RQ3 population")
    if fit.design_dimension != len(design.term_order):
        raise ObservabilityError("Integrated PGEE does not match configured RQ3 design")
    if str(analysis.research_questions["rq3"]["working_correlation"]) != "independence":
        raise ObservabilityError("Configured RQ3 working structure is not supported by current dispatcher")
    return production

