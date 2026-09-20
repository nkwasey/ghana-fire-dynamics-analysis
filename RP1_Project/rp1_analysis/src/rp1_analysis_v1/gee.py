"""Configuration-driven RQ3 marginal mean-model design and estimator dispatch.

Scientific choices are owned by ``analysis_contract.yml``.  This module contains
only generic design construction, structural validation and closed dispatch to
registered implementation capabilities.  It does not freeze Ghana-specific
predictors, factor references, stochastic settings or inferential thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit

from .contracts import AnalysisContract, MethodAuthorityContract
from .pgee import PGEEResult
from .variables import resolve_field_role


class GEEDesignError(ValueError):
    """Raised when a configured RQ3 population/design is inadmissible."""


@dataclass(frozen=True, slots=True)
class GEEMeanModelDesign:
    frame: pd.DataFrame
    design_matrix: pd.DataFrame
    outcome: pd.Series
    clusters: pd.Series
    time_index: pd.Series
    term_order: tuple[str, ...]
    model_family: str
    link: str
    covariance: str
    working_correlation_status: str
    reference_distribution: str

    @property
    def n_observations(self) -> int:
        return len(self.frame)

    @property
    def n_clusters(self) -> int:
        return int(self.clusters.nunique())


@dataclass(frozen=True, slots=True)
class RQ3PGEEProductionResult:
    fit: PGEEResult
    coefficient_authority: pd.DataFrame
    covariance_authority: pd.DataFrame
    standardised_probability_authority: pd.DataFrame
    model_spec_sha256: str
    design_matrix_sha256: str
    configuration_sha256: str


def _role(analysis: AnalysisContract, path: str) -> str:
    value = resolve_field_role(analysis, path)
    if not isinstance(value, str):
        raise GEEDesignError(f"Field role must resolve to one field: {path!r}")
    return value


def _population_spec(analysis: AnalysisContract, rq3: dict[str, Any]) -> dict[str, Any]:
    pop_id = str(rq3["model_population"])
    try:
        return analysis.study["populations"][pop_id]
    except KeyError as exc:
        raise GEEDesignError(f"RQ3 model population {pop_id!r} is not configured") from exc


def _required_columns(analysis: AnalysisContract) -> tuple[str, ...]:
    rq3 = analysis.research_questions["rq3"]
    pop = _population_spec(analysis, rq3)
    fields = [
        _role(analysis, str(pop["positive_role"])),
        _role(analysis, str(rq3["outcome"]["burned_area_presence_role"])),
        _role(analysis, str(rq3["cluster"]["id_role"])),
        _role(analysis, "keys.yyyymm"),
    ]
    fields.extend(_role(analysis, str(x["field_role"])) for x in rq3["predictors"])
    fields.extend(_role(analysis, str(x["field_role"])) for x in rq3["factors"])
    return tuple(dict.fromkeys(fields))


def build_gee_population(
    paired_panel: pd.DataFrame,
    analysis: AnalysisContract,
    *,
    enforce_governed_counts: bool = True,
) -> pd.DataFrame:
    """Create the configured VIIRS-positive population without embedding study values."""

    rq3 = analysis.research_questions["rq3"]
    pop = _population_spec(analysis, rq3)
    missing = sorted(set(_required_columns(analysis)).difference(paired_panel.columns))
    if missing:
        raise GEEDesignError(f"RQ3 mean model is missing required fields: {missing!r}")

    positive_field = _role(analysis, str(pop["positive_role"]))
    ba_field = _role(analysis, str(rq3["outcome"]["burned_area_presence_role"]))
    cluster_field = _role(analysis, str(rq3["cluster"]["id_role"]))
    yyyymm_field = _role(analysis, "keys.yyyymm")

    positive = pd.to_numeric(paired_panel[positive_field], errors="coerce")
    if positive.isna().any():
        raise GEEDesignError("RQ3 population-restriction field contains missing/non-numeric values")
    model = paired_panel.loc[positive.gt(0)].copy()
    model = model.sort_values([cluster_field, yyyymm_field]).reset_index(drop=True)

    ba = pd.to_numeric(model[ba_field], errors="coerce")
    if ba.isna().any() or not ba.isin([0, 1]).all():
        raise GEEDesignError("MCD64A1 presence must be supported binary data in the RQ3 population")
    model["mismatch_y"] = (1 - ba.astype(int)).astype(int)

    for item in rq3["predictors"]:
        field = _role(analysis, str(item["field_role"]))
        transform = str(item["transform"])
        values = pd.to_numeric(model[field], errors="coerce")
        if values.isna().any():
            raise GEEDesignError(f"Required RQ3 predictor {field!r} contains missing values")
        if transform == "log2_positive" and not values.gt(0).all():
            raise GEEDesignError(
                f"log2-positive predictor {field!r} contains {int((~values.gt(0)).sum())} "
                "non-positive observations"
            )
        if transform not in {"log2_positive", "identity"}:
            raise GEEDesignError(f"Unsupported configured predictor transform {transform!r}")

    for item in rq3["factors"]:
        field = _role(analysis, str(item["field_role"]))
        if model[field].isna().any():
            raise GEEDesignError(f"Categorical factor {field!r} contains missing values")
        if item["reference"] not in set(model[field].tolist()):
            raise GEEDesignError(
                f"Configured reference {item['reference']!r} is absent from factor {field!r}"
            )

    if model[[cluster_field, yyyymm_field]].duplicated().any():
        raise GEEDesignError("RQ3 model population contains duplicate cluster-time keys")

    if enforce_governed_counts:
        expected_rows = int(pop["rows"])
        expected_units = int(pop["units"])
        if len(model) != expected_rows:
            raise GEEDesignError(f"RQ3 model population has {len(model)} rows; expected {expected_rows}")
        units = int(model[cluster_field].nunique())
        if units != expected_units:
            raise GEEDesignError(f"RQ3 model population has {units} clusters; expected {expected_units}")
    return model


def _sorted_levels(series: pd.Series) -> list[Any]:
    values = list(pd.unique(series))
    try:
        return sorted(values)
    except TypeError:
        return sorted(values, key=lambda x: str(x))


def apply_predictor_transform(values: np.ndarray, transform: str) -> np.ndarray:
    """Apply the same configured continuous-predictor transform used in production design."""
    raw = np.asarray(values, dtype=float)
    if not np.isfinite(raw).all():
        raise GEEDesignError("RQ3 predictor transform received non-finite values")
    if transform == "log2_positive":
        if np.any(raw <= 0.0):
            raise GEEDesignError("log2-positive predictor transform received non-positive values")
        return np.log2(raw)
    if transform == "identity":
        return raw.copy()
    raise GEEDesignError(f"Unsupported RQ3 predictor transform {transform!r}")


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frame_sha256(frame: pd.DataFrame) -> str:
    payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def average_counterfactual_probability(
    design_matrix: np.ndarray,
    coefficients: np.ndarray,
    *,
    term_index: int,
    transformed_value: float,
) -> float:
    """Average fitted probabilities after replacing one design column for every row."""
    X = np.asarray(design_matrix, dtype=float)
    beta = np.asarray(coefficients, dtype=float)
    if X.ndim != 2 or beta.shape != (X.shape[1],):
        raise GEEDesignError("Counterfactual design and coefficient dimensions do not align")
    if not (0 <= int(term_index) < X.shape[1]):
        raise GEEDesignError("Counterfactual term index is outside the design matrix")
    if not np.isfinite(X).all() or not np.isfinite(beta).all() or not np.isfinite(transformed_value):
        raise GEEDesignError("Counterfactual prediction input contains non-finite values")
    counterfactual = X.copy()
    counterfactual[:, int(term_index)] = float(transformed_value)
    probabilities = expit(counterfactual @ beta)
    if not np.isfinite(probabilities).all():
        raise GEEDesignError("Counterfactual prediction produced non-finite probabilities")
    value = float(probabilities.mean())
    if not 0.0 <= value <= 1.0:
        raise GEEDesignError("Standardised probability lies outside [0, 1]")
    return value


def build_gee_mean_model_design(
    paired_panel: pd.DataFrame,
    analysis: AnalysisContract,
    *,
    enforce_governed_counts: bool = True,
) -> GEEMeanModelDesign:
    """Build a deterministic design entirely from the injected analysis contract."""

    rq3 = analysis.research_questions["rq3"]
    model = build_gee_population(
        paired_panel, analysis, enforce_governed_counts=enforce_governed_counts
    )
    cluster_field = _role(analysis, str(rq3["cluster"]["id_role"]))
    yyyymm_field = _role(analysis, "keys.yyyymm")

    columns: dict[str, np.ndarray] = {}
    if bool(rq3.get("intercept", True)):
        columns["Intercept"] = np.ones(len(model), dtype=float)

    for item in rq3["predictors"]:
        field = _role(analysis, str(item["field_role"]))
        term = str(item["term_name"])
        values = pd.to_numeric(model[field], errors="raise").to_numpy(dtype=float)
        transform = str(item["transform"])
        columns[term] = apply_predictor_transform(values, transform)

    for item in rq3["factors"]:
        if str(item["coding"]) != "categorical":
            raise GEEDesignError(f"Unsupported RQ3 factor coding {item['coding']!r}")
        field = _role(analysis, str(item["field_role"]))
        reference = item["reference"]
        prefix = str(item["term_prefix"])
        for level in _sorted_levels(model[field]):
            if level == reference:
                continue
            columns[f"{prefix}_{level}"] = model[field].eq(level).astype(float).to_numpy()

    X = pd.DataFrame(columns, index=model.index)
    if X.columns.duplicated().any():
        raise GEEDesignError("Configured RQ3 design produced duplicate terms")
    if not np.isfinite(X.to_numpy(dtype=float)).all():
        raise GEEDesignError("RQ3 design matrix contains non-finite values")

    return GEEMeanModelDesign(
        frame=model,
        design_matrix=X,
        outcome=model["mismatch_y"].astype(int).copy(),
        clusters=model[cluster_field].astype(str).copy(),
        time_index=model[yyyymm_field].astype(int).copy(),
        term_order=tuple(str(x) for x in X.columns),
        model_family=str(rq3["family"]),
        link=str(rq3["link"]),
        covariance=str(rq3["covariance"]),
        working_correlation_status=str(rq3["working_correlation"]),
        reference_distribution=str(rq3["reference_distribution"]),
    )


def mean_model_design_authority(
    design: GEEMeanModelDesign, analysis: AnalysisContract
) -> pd.DataFrame:
    """Return deterministic row-level design authority from an explicit analysis contract."""
    rq3 = analysis.research_questions["rq3"]
    cluster_field = _role(analysis, str(rq3["cluster"]["id_role"]))
    time_field = _role(analysis, "keys.yyyymm")
    base = design.frame[[cluster_field, time_field, "mismatch_y"]].copy()
    for term in design.term_order:
        base[term] = design.design_matrix[term].to_numpy()
    return base



def mean_model_column_provenance(
    design: GEEMeanModelDesign, analysis: AnalysisContract
) -> pd.DataFrame:
    """Return exact ordered column provenance for the configured RQ3 design.

    The rows are reconstructed from configuration and then required to match the
    realised design term-for-term.  This prevents a matrix with the correct
    width but incorrect scientific terms from qualifying.
    """
    rq3 = analysis.research_questions["rq3"]
    rows: list[dict[str, object]] = []

    if bool(rq3.get("intercept", True)):
        rows.append({
            "term": "Intercept", "component": "intercept", "source_field": None,
            "field_role": None, "transform_or_coding": "intercept",
            "reporting_role": "intercept", "factor_id": None,
            "factor_level": None, "reference_level": None,
        })

    for item in rq3["predictors"]:
        rows.append({
            "term": str(item["term_name"]),
            "component": "continuous_predictor",
            "source_field": _role(analysis, str(item["field_role"])),
            "field_role": str(item["field_role"]),
            "transform_or_coding": str(item["transform"]),
            "reporting_role": str(item["role"]),
            "factor_id": None,
            "factor_level": None,
            "reference_level": None,
        })

    for item in rq3["factors"]:
        field = _role(analysis, str(item["field_role"]))
        reference = item["reference"]
        prefix = str(item["term_prefix"])
        for level in _sorted_levels(design.frame[field]):
            if level == reference:
                continue
            rows.append({
                "term": f"{prefix}_{level}",
                "component": "categorical_indicator",
                "source_field": field,
                "field_role": str(item["field_role"]),
                "transform_or_coding": str(item["coding"]),
                "reporting_role": str(item.get("role", "adjustment")),
                "factor_id": str(item["factor_id"]),
                "factor_level": level,
                "reference_level": reference,
            })

    realised = tuple(str(x) for x in design.term_order)
    expected = tuple(str(row["term"]) for row in rows)
    if expected != realised:
        raise GEEDesignError(
            "Realised RQ3 term identity/order differs from the configuration-derived design contract"
        )
    result = pd.DataFrame(rows)
    result.insert(0, "column_order", np.arange(len(result), dtype=int))
    result["design_dimension"] = len(result)
    return result

def fit_current_rq3_estimator(
    design: GEEMeanModelDesign,
    analysis: AnalysisContract,
    methods: MethodAuthorityContract,
    *,
    alpha: float | None = None,
) -> PGEEResult:
    """Closed dispatch from configured method IDs to registered implementation capabilities."""
    from .method_authority import require_method_authority
    from .pgee import fit_pgee_with_morel_standard_normal_inference

    rq3 = analysis.research_questions["rq3"]
    controls = rq3["computational_controls"]
    method_ids = (
        str(rq3["estimator"]),
        str(rq3["family"]),
        str(rq3["link"]),
        str(rq3["working_correlation"]),
        str(rq3["covariance"]),
        str(rq3["reference_distribution"]),
    )
    implementation_ids = tuple(require_method_authority(methods, method).implementation_id for method in method_ids)

    # This tuple is an implementation-capability signature, not the study design.
    # The selected method IDs come solely from the injected scientific contract.
    supported_implementation = (
        "gee.firth_penalized_independence.v1",
        "family.binomial.v1",
        "link.logit.v1",
        "gee.working_independence.v1",
        "covariance.mbn2003.v1",
        "inference.standard_normal_wald.v1",
    )
    if implementation_ids != supported_implementation:
        raise GEEDesignError(
            "No registered RQ3 estimator dispatcher is available for the configured implementation tuple "
            f"{implementation_ids!r}"
        )
    if alpha is None:
        alpha = float(analysis.reproducibility["alpha"])
    if not (0.0 < float(alpha) < 1.0):
        raise GEEDesignError("alpha must lie strictly between zero and one")
    return fit_pgee_with_morel_standard_normal_inference(
        design.design_matrix.to_numpy(dtype=float),
        design.outcome.to_numpy(dtype=float),
        design.clusters.to_numpy(dtype=object),
        alpha=float(alpha),
        tolerance=float(controls["tolerance"]),
        max_iterations=int(controls["max_iterations"]),
        max_step_halvings=int(controls["max_step_halvings"]),
    )


def configured_predictor_metadata(analysis: AnalysisContract) -> pd.DataFrame:
    """Project predictor identity/role metadata from the injected scientific contract."""
    rows = []
    for item in analysis.research_questions["rq3"]["predictors"]:
        rows.append({
            "predictor_id": str(item["predictor_id"]),
            "term": str(item["term_name"]),
            "predictor_role": str(item["role"]),
            "reporting_role": str(item["role"]),
            "transform": str(item["transform"]),
            "field_role": str(item["field_role"]),
        })
    return pd.DataFrame(
        rows,
        columns=["predictor_id", "term", "predictor_role", "reporting_role", "transform", "field_role"],
    )


def _term_metadata(
    analysis: AnalysisContract, term_order: tuple[str, ...]
) -> dict[str, dict[str, object]]:
    rq3 = analysis.research_questions["rq3"]
    metadata: dict[str, dict[str, object]] = {}
    if bool(rq3.get("intercept", True)):
        metadata["Intercept"] = {
            "term_role": "intercept",
            "source_id": "intercept",
            "coding": "intercept",
            "reference": None,
            "interpretation": "baseline_odds",
            "is_focal_predictor": False,
        }
    for item in rq3["predictors"]:
        term = str(item["term_name"])
        transform = str(item["transform"])
        role = str(item["role"])
        interpretation = (
            "adjusted_or_per_doubling" if transform == "log2_positive" else "adjusted_or_per_unit"
        )
        metadata[term] = {
            "term_role": f"{role}_predictor",
            "source_id": str(item["predictor_id"]),
            "coding": transform,
            "reference": None,
            "interpretation": interpretation,
            "is_focal_predictor": role == "focal",
        }
    for item in rq3["factors"]:
        prefix = str(item["term_prefix"])
        factor_id = str(item["factor_id"])
        reference = item["reference"]
        for term in term_order:
            if term.startswith(prefix + "_"):
                metadata[term] = {
                    "term_role": f"{item.get('role', 'adjustment')}_factor",
                    "source_id": factor_id,
                    "coding": "categorical_indicator",
                    "reference": reference,
                    "interpretation": f"adjusted_or_vs_reference_{reference}",
                    "is_focal_predictor": False,
                }
    missing = [term for term in term_order if term not in metadata]
    if missing:
        raise GEEDesignError(f"No configured semantic metadata for RQ3 terms: {missing!r}")
    return metadata


def build_pgee_coefficient_authority(
    design: GEEMeanModelDesign,
    fit: PGEEResult,
    analysis: AnalysisContract,
    methods: MethodAuthorityContract,
) -> pd.DataFrame:
    """Build machine-readable coefficient inference using configured reference semantics."""
    terms = design.term_order
    p = len(terms)
    if fit.n_observations != design.n_observations or fit.n_clusters != design.n_clusters:
        raise GEEDesignError("PGEE result population dimensions differ from the configured design")
    if fit.design_dimension != p or design.design_matrix.shape[1] != p:
        raise GEEDesignError("PGEE result design dimension differs from configured term order")
    arrays = (
        fit.coefficients,
        fit.standard_errors,
        fit.wald_z,
        fit.standard_normal_p,
        fit.standard_normal_ci_low,
        fit.standard_normal_ci_high,
    )
    if any(np.asarray(a).shape != (p,) for a in arrays):
        raise GEEDesignError("PGEE inference arrays do not match configured design")
    if fit.covariance.shape != (p, p):
        raise GEEDesignError("PGEE covariance dimension does not match configured design")
    if not np.allclose(fit.covariance, fit.covariance.T, rtol=0.0, atol=1e-12):
        raise GEEDesignError("PGEE corrected covariance is not symmetric")
    if not fit.converged:
        raise GEEDesignError("PGEE estimator did not converge")
    if not all(np.isfinite(np.asarray(a, dtype=float)).all() for a in (*arrays, fit.covariance)):
        raise GEEDesignError("PGEE inference contains non-finite values")

    from .method_authority import require_method_authority

    rq3 = analysis.research_questions["rq3"]
    reference = str(rq3["reference_distribution"])
    reference_impl = require_method_authority(methods, reference).implementation_id
    if reference_impl == "inference.standard_normal_wald.v1":
        statistic_name = "wald_z"
    else:
        raise GEEDesignError(
            "No coefficient-authority builder is available for configured implementation "
            f"{reference_impl!r}"
        )

    with np.errstate(over="raise", invalid="raise"):
        try:
            exp_beta = np.exp(fit.coefficients)
            exp_low = np.exp(fit.standard_normal_ci_low)
            exp_high = np.exp(fit.standard_normal_ci_high)
        except FloatingPointError as exc:
            raise GEEDesignError("PGEE exponentiated effect estimate is not finite") from exc

    meta = _term_metadata(analysis, terms)
    rows: list[dict[str, object]] = []
    for index, term in enumerate(terms):
        item = meta[term]
        is_intercept = item["term_role"] == "intercept"
        row = {
            "term_order": index,
            "term": term,
            "term_role": item["term_role"],
            "source_id": item["source_id"],
            "coding": item["coding"],
            "reference_level": item["reference"],
            "is_focal_predictor": bool(item["is_focal_predictor"]),
            "interpretation": item["interpretation"],
            "coefficient": float(fit.coefficients[index]),
            "corrected_se": float(fit.standard_errors[index]),
            "wald_z": float(fit.wald_z[index]),
            "statistic_name": statistic_name,
            "standard_normal_p": float(fit.standard_normal_p[index]),
            "ci_low": float(fit.standard_normal_ci_low[index]),
            "ci_high": float(fit.standard_normal_ci_high[index]),
            "exp_coefficient": float(exp_beta[index]),
            "exp_ci_low": float(exp_low[index]),
            "exp_ci_high": float(exp_high[index]),
            "adjusted_or": None if is_intercept else float(exp_beta[index]),
            "adjusted_or_ci_low": None if is_intercept else float(exp_low[index]),
            "adjusted_or_ci_high": None if is_intercept else float(exp_high[index]),
            "n_observations": int(fit.n_observations),
            "n_clusters": int(fit.n_clusters),
            "design_dimension": int(fit.design_dimension),
            "estimator": str(rq3["estimator"]),
            "family": str(rq3["family"]),
            "link": str(rq3["link"]),
            "working_structure": str(rq3["working_correlation"]),
            "covariance_method": str(rq3["covariance"]),
            "reference_distribution": reference,
            "converged": bool(fit.converged),
            "iterations": int(fit.iterations),
            "score_max_abs": float(fit.score_max_abs),
            "solver_tolerance": float(fit.solver_tolerance),
            "solver_max_iterations": int(fit.solver_max_iterations),
            "solver_max_step_halvings": int(fit.solver_max_step_halvings),
            "step_halvings_total": int(fit.step_halvings_total),
            "step_halvings_max_used": int(fit.step_halvings_max_used),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def build_pgee_covariance_authority(
    design: GEEMeanModelDesign, fit: PGEEResult
) -> pd.DataFrame:
    terms = design.term_order
    if fit.covariance.shape != (len(terms), len(terms)):
        raise GEEDesignError("PGEE covariance authority dimension mismatch")
    return pd.DataFrame(
        [
            {
                "row_term_order": i,
                "row_term": row_term,
                "column_term_order": j,
                "column_term": column_term,
                "covariance": float(fit.covariance[i, j]),
            }
            for i, row_term in enumerate(terms)
            for j, column_term in enumerate(terms)
        ]
    )


def build_standardised_probability_authority(
    design: GEEMeanModelDesign,
    fit: PGEEResult,
    analysis: AnalysisContract,
    methods: MethodAuthorityContract,
    *,
    configuration_sha256: str,
) -> tuple[pd.DataFrame, str, str]:
    """Predictively standardise focal RQ3 predictors over observed remaining covariates."""
    from .method_authority import method_is_implemented, require_method_authority

    rq3 = analysis.research_questions["rq3"]
    std = rq3["standardised_probabilities"]
    method_id = str(std["method"])
    authority = require_method_authority(methods, method_id)
    if authority.implementation_id != "prediction.observed_covariate_standardisation.v1":
        raise GEEDesignError("Configured predictive-standardisation implementation is unsupported")
    if not method_is_implemented(methods, method_id):
        raise GEEDesignError("Configured predictive standardisation is not production implemented")
    if str(std.get("averaging_distribution")) != "observed_remaining_covariates":
        raise GEEDesignError("RQ3 standardisation must average over observed remaining covariates")

    rq3_plain = analysis.to_dict()["research_questions"]["rq3"]
    model_payload = {
        "family": rq3_plain["family"], "link": rq3_plain["link"],
        "estimator": rq3_plain["estimator"],
        "working_correlation": rq3_plain["working_correlation"],
        "covariance": rq3_plain["covariance"],
        "reference_distribution": rq3_plain["reference_distribution"],
        "predictors": rq3_plain["predictors"], "factors": rq3_plain["factors"],
        "intercept": rq3_plain["intercept"], "term_order": list(design.term_order),
    }
    model_spec_sha256 = _canonical_sha256(model_payload)
    design_authority = mean_model_design_authority(design, analysis)
    design_matrix_sha256 = _frame_sha256(design_authority)

    X = design.design_matrix.to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    focal = [item for item in rq3["predictors"] if str(item["role"]) == "focal"]
    quantiles = [float(q) for q in std["focal_predictor_quantiles"]]
    for item in focal:
        predictor_id = str(item["predictor_id"])
        term = str(item["term_name"])
        field = _role(analysis, str(item["field_role"]))
        transform = str(item["transform"])
        raw = pd.to_numeric(design.frame[field], errors="raise").astype(float)
        term_index = design.term_order.index(term)
        for q in quantiles:
            raw_value = float(raw.quantile(q))
            transformed_value = float(apply_predictor_transform(np.asarray([raw_value]), transform)[0])
            probability = average_counterfactual_probability(
                X, fit.coefficients, term_index=term_index, transformed_value=transformed_value
            )
            rows.append({
                "predictor_id": predictor_id, "term": term, "predictor_role": "focal",
                "quantile": q, "raw_quantile_value": raw_value,
                "transformed_quantile_value": transformed_value,
                "standardised_probability": probability,
                "n": int(design.n_observations), "districts": int(design.n_clusters),
                "model_spec_sha256": model_spec_sha256,
                "design_matrix_sha256": design_matrix_sha256,
                "configuration_sha256": str(configuration_sha256),
                "standardisation_method": method_id,
                "averaging_distribution": str(std["averaging_distribution"]),
            })
    result = pd.DataFrame(rows)
    if len(result) != len(focal) * len(quantiles):
        raise GEEDesignError("Predictive-standardisation output cardinality is incorrect")
    if set(result["predictor_role"]) != {"focal"}:
        raise GEEDesignError("Predictive standardisation produced a non-focal predictor output")
    if not result["standardised_probability"].between(0.0, 1.0, inclusive="both").all():
        raise GEEDesignError("Predictive-standardisation probability lies outside [0,1]")
    return result, model_spec_sha256, design_matrix_sha256


def run_current_rq3_pgee_production(
    design: GEEMeanModelDesign,
    analysis: AnalysisContract,
    methods: MethodAuthorityContract,
    *,
    alpha: float | None = None,
    configuration_sha256: str | None = None,
) -> RQ3PGEEProductionResult:
    fit = fit_current_rq3_estimator(design, analysis, methods, alpha=alpha)
    if configuration_sha256 is None:
        configuration_sha256 = _canonical_sha256({
            "analysis_contract": analysis.to_dict(),
            "method_authorities": methods.to_dict(),
        })
    standardised, model_hash, design_hash = build_standardised_probability_authority(
        design, fit, analysis, methods, configuration_sha256=configuration_sha256
    )
    return RQ3PGEEProductionResult(
        fit=fit,
        coefficient_authority=build_pgee_coefficient_authority(design, fit, analysis, methods),
        covariance_authority=build_pgee_covariance_authority(design, fit),
        standardised_probability_authority=standardised,
        model_spec_sha256=model_hash,
        design_matrix_sha256=design_hash,
        configuration_sha256=str(configuration_sha256),
    )

