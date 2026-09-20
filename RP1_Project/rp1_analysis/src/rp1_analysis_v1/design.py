"""Semantic validation for configuration-governed RP1 Analysis design.

The executable scientific design lives in ``analysis_contract.yml``.  This
module validates mathematical legality, cross-contract references and generic
implementation capabilities; it deliberately does not mirror Ghana study
values as Python constants.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .method_authority import (
    FIGURE_DATA_BUILDER_REGISTRY,
    FIGURE_RENDERER_REGISTRY,
    OUTPUT_BUILDER_REGISTRY,
    PRESENTATION_RENDERER_REGISTRY,
    method_is_implemented,
    require_implementation,
)
from .variables import resolve_field_role


class DesignValidationError(ValueError):
    """Raised when configuration is structurally or semantically invalid."""


class PendingDesignError(RuntimeError):
    """Raised when execution is requested for a method not yet implemented."""


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DesignValidationError(f"{context} must be a mapping")
    return value


def _sequence(value: Any, context: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DesignValidationError(f"{context} must be a sequence")
    return value


def _probability(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesignValidationError(f"{context} must be numeric")
    number = float(value)
    if not 0.0 < number < 1.0:
        raise DesignValidationError(f"{context} must lie strictly between 0 and 1")
    return number


def _positive_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DesignValidationError(f"{context} must be a positive integer")
    return value


def _nonnegative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DesignValidationError(f"{context} must be a non-negative integer")
    return value


def _positive_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise DesignValidationError(f"{context} must be positive")
    return float(value)


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    """Reject undeclared keys at an executable scientific-contract boundary.

    The key schema is structural rather than study-value authority: it prevents
    typoed or unsupported parallel settings from being silently ignored while the
    values themselves remain owned by configuration.
    """

    unknown = set(value).difference(allowed)
    if unknown:
        raise DesignValidationError(
            f"Unknown scientific fields in {context}: {sorted(unknown)!r}"
        )


def _method(value: Any, context: str) -> str:
    """Validate only the structural form of a configured method identifier.

    Scientific method identity is owned by ``method_authorities.yml`` and cannot
    be mirrored in Python. Cross-contract validation resolves the identifier
    against the injected method-authority contract.
    """
    if not isinstance(value, str) or not value:
        raise DesignValidationError(f"{context} must be a non-empty method identifier")
    return value


def _months_between(start: str, end: str) -> int:
    try:
        sy, sm = (int(x) for x in start.split("-"))
        ey, em = (int(x) for x in end.split("-"))
    except Exception as exc:
        raise DesignValidationError(f"Invalid monthly window {start!r}..{end!r}") from exc
    if not (1 <= sm <= 12 and 1 <= em <= 12):
        raise DesignValidationError(f"Invalid monthly window {start!r}..{end!r}")
    months = (ey - sy) * 12 + (em - sm) + 1
    if months <= 0:
        raise DesignValidationError(f"Temporal window is reversed: {start!r}..{end!r}")
    return months


def _resolve_source(raw: Mapping[str, Any], source: str, context: str) -> Any:
    current: Any = raw
    for token in source.split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise DesignValidationError(f"{context} references unknown config source {source!r}")
        current = current[token]
    return current


def _validate_reproducibility(raw: Mapping[str, Any]) -> None:
    rep = _mapping(raw.get("reproducibility"), "reproducibility")
    _nonnegative_int(rep.get("primary_seed"), "reproducibility.primary_seed")
    _probability(rep.get("alpha"), "reproducibility.alpha")
    _probability(rep.get("confidence_level"), "reproducibility.confidence_level")


def _validate_windows(study: Mapping[str, Any]) -> None:
    windows = _mapping(study.get("temporal_windows"), "study.temporal_windows")
    if not windows:
        raise DesignValidationError("study.temporal_windows must not be empty")
    for name, raw_window in windows.items():
        window = _mapping(raw_window, f"study.temporal_windows.{name}")
        if "start" not in window or "end" not in window:
            raise DesignValidationError(f"study.temporal_windows.{name} requires start and end")
        start, end = window["start"], window["end"]
        if isinstance(start, int) and isinstance(end, int):
            if end < start:
                raise DesignValidationError(f"Invalid year window: {window!r}")
        else:
            _months_between(str(start), str(end))


def _validate_populations(study: Mapping[str, Any]) -> None:
    populations = _mapping(study.get("populations"), "study.populations")
    if not populations:
        raise DesignValidationError("study.populations must not be empty")
    for name, raw_pop in populations.items():
        pop = _mapping(raw_pop, f"study.populations.{name}")
        _positive_int(pop.get("units"), f"study.populations.{name}.units")
        _positive_int(pop.get("rows"), f"study.populations.{name}.rows")
        if "source_panel" not in pop and "source_population" not in pop:
            raise DesignValidationError(
                f"study.populations.{name} requires source_panel or source_population"
            )
        if "start" in pop or "end" in pop:
            if "start" not in pop or "end" not in pop:
                raise DesignValidationError(f"study.populations.{name} requires both start and end")
            _months_between(str(pop["start"]), str(pop["end"]))
        if not isinstance(pop.get("eligibility"), str) or not pop.get("eligibility"):
            raise DesignValidationError(f"study.populations.{name}.eligibility is required")


def _validate_seed_or_alpha_source(raw: Mapping[str, Any], source: Any, context: str, *, probability: bool = False) -> None:
    if not isinstance(source, str) or not source:
        raise DesignValidationError(f"{context} must be a dotted config source")
    value = _resolve_source(raw, source, context)
    if probability:
        _probability(value, source)
    else:
        _nonnegative_int(value, source)


def _validate_rq1(raw: Mapping[str, Any], rq1: Mapping[str, Any]) -> None:
    _reject_unknown_keys(
        rq1,
        {
            "identity", "population", "supports", "annual_rate", "within_acz",
            "district_departure", "seasonality", "spatial",
            "arbitrary_departure_thresholds_primary_evidence",
        },
        "research_questions.rq1",
    )
    annual = _mapping(rq1.get("annual_rate"), "research_questions.rq1.annual_rate")
    _positive_number(annual.get("scale_per_km2"), "research_questions.rq1.annual_rate.scale_per_km2")
    within = _mapping(rq1.get("within_acz"), "research_questions.rq1.within_acz")
    _method(within.get("concentration_method"), "research_questions.rq1.within_acz.concentration_method")
    summaries = _sequence(within.get("summaries"), "research_questions.rq1.within_acz.summaries")
    if not summaries or len(set(map(str, summaries))) != len(summaries):
        raise DesignValidationError("RQ1 within-ACZ summaries must be unique")
    departure = _mapping(rq1.get("district_departure"), "research_questions.rq1.district_departure")
    _method(departure.get("method"), "research_questions.rq1.district_departure.method")
    seasonality = _mapping(rq1.get("seasonality"), "research_questions.rq1.seasonality")
    _positive_int(seasonality.get("climatology_months"), "research_questions.rq1.seasonality.climatology_months")
    _method(seasonality.get("method"), "research_questions.rq1.seasonality.method")
    spatial = _mapping(rq1.get("spatial"), "research_questions.rq1.spatial")
    weights = _mapping(spatial.get("weights"), "research_questions.rq1.spatial.weights")
    _method(weights.get("method"), "research_questions.rq1.spatial.weights.method")
    global_cfg = _mapping(spatial.get("global"), "research_questions.rq1.spatial.global")
    _method(global_cfg.get("method"), "research_questions.rq1.spatial.global.method")
    _method(global_cfg.get("inference_method"), "research_questions.rq1.spatial.global.inference_method")
    _positive_int(global_cfg.get("permutations"), "research_questions.rq1.spatial.global.permutations")
    _validate_seed_or_alpha_source(raw, global_cfg.get("seed_source"), "research_questions.rq1.spatial.global.seed_source")
    local = _mapping(spatial.get("local"), "research_questions.rq1.spatial.local")
    _method(local.get("method"), "research_questions.rq1.spatial.local.method")
    _method(local.get("multiplicity_method"), "research_questions.rq1.spatial.local.multiplicity_method")
    _positive_int(local.get("permutations"), "research_questions.rq1.spatial.local.permutations")
    _validate_seed_or_alpha_source(raw, local.get("seed_source"), "research_questions.rq1.spatial.local.seed_source")
    for key in (
        "permutation_scheme", "candidate_pool", "standardisation", "statistic",
        "upper_tail_comparison", "tie_allocation", "p_value_method", "classification",
    ):
        if not isinstance(local.get(key), str) or not local.get(key):
            raise DesignValidationError(f"research_questions.rq1.spatial.local.{key} is required")
    if not isinstance(local.get("multiply_smaller_tail_by_two"), bool):
        raise DesignValidationError("RQ1 Local Moran tail multiplier flag must be boolean")


def _validate_rq2(raw: Mapping[str, Any], rq2: Mapping[str, Any]) -> None:
    _reject_unknown_keys(
        rq2,
        {
            "identity", "authority_status", "population", "analysis_unit",
            "expected_series_count", "expected_n_per_series", "rate",
            "effect_estimator", "effect_uncertainty", "inferential_test",
            "multiple_testing",
        },
        "research_questions.rq2",
    )
    # Realised values must remain execution metadata rather than parallel
    # scientific authorities in the executable contract.
    for forbidden_key in ("bandwidth", "realised_bandwidth", "block_length", "resampling"):
        if forbidden_key in rq2:
            raise DesignValidationError(
                f"research_questions.rq2 must not store derived key {forbidden_key!r}"
            )
    _method(rq2.get("effect_estimator"), "research_questions.rq2.effect_estimator")
    test = _mapping(rq2.get("inferential_test"), "research_questions.rq2.inferential_test")
    for forbidden_key in ("bandwidth", "realised_bandwidth", "block_length", "replications"):
        if forbidden_key in test:
            raise DesignValidationError(
                f"RQ2 inferential_test must not duplicate a derived value as {forbidden_key!r}"
            )
    _method(test.get("method"), "research_questions.rq2.inferential_test.method")
    _positive_number(test.get("variance_floor"), "research_questions.rq2.inferential_test.variance_floor")
    _positive_int(test.get("permutations"), "research_questions.rq2.inferential_test.permutations")
    _validate_seed_or_alpha_source(raw, test.get("seed_source"), "research_questions.rq2.inferential_test.seed_source")
    for key in ("empirical_cdf", "bandwidth_rule", "studentisation", "alternative", "p_value_method"):
        if not isinstance(test.get(key), str) or not test.get(key):
            raise DesignValidationError(f"research_questions.rq2.inferential_test.{key} is required")
    multiple = _mapping(rq2.get("multiple_testing"), "research_questions.rq2.multiple_testing")
    _method(multiple.get("method"), "research_questions.rq2.multiple_testing.method")
    _positive_int(multiple.get("family_size"), "research_questions.rq2.multiple_testing.family_size")
    _validate_seed_or_alpha_source(raw, multiple.get("alpha_source"), "research_questions.rq2.multiple_testing.alpha_source", probability=True)


def _validate_rq3(rq3: Mapping[str, Any]) -> None:
    for forbidden_key in (
        "model_family", "mean_model", "working_correlation_candidates",
        "selection_enabled", "cic", "qic", "degrees_of_freedom",
    ):
        if forbidden_key in rq3:
            raise DesignValidationError(
                f"research_questions.rq3 contains unsupported parallel authority {forbidden_key!r}"
            )
    _reject_unknown_keys(
        rq3,
        {
            "identity", "authority_status", "descriptive_population",
            "model_population", "four_state_correspondence", "outcome",
            "estimator", "family", "link", "cluster", "working_correlation",
            "covariance", "reference_distribution", "predictors", "factors",
            "intercept", "diagnostics", "standardised_probabilities",
            "excluded_predictor_roles", "interactions", "stepwise_selection",
            "outcome_driven_tuning", "computational_controls",
        },
        "research_questions.rq3",
    )
    for key in ("estimator", "family", "link", "working_correlation", "covariance", "reference_distribution"):
        _method(rq3.get(key), f"research_questions.rq3.{key}")
    cluster = _mapping(rq3.get("cluster"), "research_questions.rq3.cluster")
    if not isinstance(cluster.get("id_role"), str) or not cluster.get("id_role"):
        raise DesignValidationError("research_questions.rq3.cluster.id_role is required")
    predictors = _sequence(rq3.get("predictors"), "research_questions.rq3.predictors")
    if not predictors:
        raise DesignValidationError("RQ3 requires at least one predictor")
    excluded_roles = {str(x) for x in _sequence(
        rq3.get("excluded_predictor_roles"), "research_questions.rq3.excluded_predictor_roles"
    )}
    if rq3.get("interactions") is not False:
        raise DesignValidationError("RQ3 interactions must remain prospectively disabled")
    if rq3.get("stepwise_selection") is not False:
        raise DesignValidationError("RQ3 stepwise selection must remain disabled")
    if rq3.get("outcome_driven_tuning") is not False:
        raise DesignValidationError("RQ3 outcome-driven tuning must remain disabled")
    ids: set[str] = set(); terms: set[str] = set()
    for idx, item in enumerate(predictors):
        pred = _mapping(item, f"research_questions.rq3.predictors[{idx}]")
        for key in ("predictor_id", "field_role", "transform", "role", "term_name"):
            if not isinstance(pred.get(key), str) or not pred.get(key):
                raise DesignValidationError(f"RQ3 predictor {idx} requires {key}")
        if pred["role"] not in {"focal", "adjustment"}:
            raise DesignValidationError(f"RQ3 predictor {idx} has invalid role")
        if str(pred["field_role"]) in excluded_roles:
            raise DesignValidationError(
                f"RQ3 predictor {idx} uses an explicitly excluded field role {pred['field_role']!r}"
            )
        _method(pred["transform"], f"research_questions.rq3.predictors[{idx}].transform")
        if pred["predictor_id"] in ids or pred["term_name"] in terms:
            raise DesignValidationError("RQ3 predictor IDs and term names must be unique")
        ids.add(str(pred["predictor_id"])); terms.add(str(pred["term_name"]))
    factors = _sequence(rq3.get("factors"), "research_questions.rq3.factors")
    if not factors:
        raise DesignValidationError("RQ3 requires at least one factor")
    factor_ids: set[str] = set()
    for idx, item in enumerate(factors):
        fac = _mapping(item, f"research_questions.rq3.factors[{idx}]")
        for key in ("factor_id", "field_role", "coding", "role", "term_prefix"):
            if not isinstance(fac.get(key), str) or not fac.get(key):
                raise DesignValidationError(f"RQ3 factor {idx} requires {key}")
        _method(fac["coding"], f"research_questions.rq3.factors[{idx}].coding")
        if "reference" not in fac:
            raise DesignValidationError(f"RQ3 factor {idx} requires a configured reference")
        if fac["factor_id"] in factor_ids:
            raise DesignValidationError("RQ3 factor IDs must be unique")
        factor_ids.add(str(fac["factor_id"]))
    diagnostics = _mapping(rq3.get("diagnostics"), "research_questions.rq3.diagnostics")
    vif = _mapping(diagnostics.get("vif"), "research_questions.rq3.diagnostics.vif")
    if not isinstance(vif.get("enabled"), bool) or not isinstance(vif.get("deletion_authority"), bool):
        raise DesignValidationError("RQ3 VIF flags must be boolean")
    std = _mapping(rq3.get("standardised_probabilities"), "research_questions.rq3.standardised_probabilities")
    _method(std.get("method"), "research_questions.rq3.standardised_probabilities.method")
    quantiles = _sequence(std.get("focal_predictor_quantiles"), "research_questions.rq3.standardised_probabilities.focal_predictor_quantiles")
    if not quantiles:
        raise DesignValidationError("RQ3 predictive standardisation requires quantiles")
    for idx, value in enumerate(quantiles):
        _probability(value, f"research_questions.rq3.standardised_probabilities.focal_predictor_quantiles[{idx}]")
    if len(set(float(x) for x in quantiles)) != len(quantiles):
        raise DesignValidationError("RQ3 predictive-standardisation quantiles must be unique")
    controls = _mapping(rq3.get("computational_controls"), "research_questions.rq3.computational_controls")
    _positive_number(controls.get("tolerance"), "research_questions.rq3.computational_controls.tolerance")
    _positive_int(controls.get("max_iterations"), "research_questions.rq3.computational_controls.max_iterations")
    max_halvings = controls.get("max_step_halvings")
    if isinstance(max_halvings, bool) or not isinstance(max_halvings, int) or max_halvings < 0:
        raise DesignValidationError("research_questions.rq3.computational_controls.max_step_halvings must be a non-negative integer")


def _validate_secondary(raw: Mapping[str, Any], secondary: Mapping[str, Any]) -> None:
    external = _mapping(secondary.get("external_execution"), "secondary_analysis.external_execution")
    if not isinstance(external.get("user_defined_random_seed_supported"), bool):
        raise DesignValidationError("secondary RNG support flag must be boolean")
    _validate_seed_or_alpha_source(
        raw, external.get("scientific_seed_source"), "secondary_analysis.external_execution.scientific_seed_source"
    )
    seed_parameter = external.get("user_defined_random_seed_parameter")
    if external["user_defined_random_seed_supported"]:
        if not isinstance(seed_parameter, str) or not seed_parameter.strip():
            raise DesignValidationError("supported SaTScan user seed requires an exact parameter-field name")
    elif seed_parameter is not None:
        raise DesignValidationError("unsupported SaTScan user seed must not define a parameter-field name")
    for key in ("rng_authority", "engine_rng_behaviour"):
        if not isinstance(external.get(key), str) or not external.get(key):
            raise DesignValidationError(f"secondary_analysis.external_execution.{key} is required")
    spatial = _mapping(secondary.get("spatial_support"), "secondary_analysis.spatial_support")
    common = _mapping(secondary.get("common"), "secondary_analysis.common")
    pct = _positive_number(common.get("max_spatial_percent"), "secondary_analysis.common.max_spatial_percent")
    if pct > 100:
        raise DesignValidationError("secondary_analysis.common.max_spatial_percent cannot exceed 100")
    _positive_int(common.get("max_temporal_months"), "secondary_analysis.common.max_temporal_months")
    _positive_int(common.get("monte_carlo_replicates"), "secondary_analysis.common.monte_carlo_replicates")
    _validate_seed_or_alpha_source(raw, common.get("alpha_source"), "secondary_analysis.common.alpha_source", probability=True)
    _method(common.get("reporting_method"), "secondary_analysis.common.reporting_method")
    if not isinstance(common.get("geographical_overlap"), bool):
        raise DesignValidationError("secondary_analysis.common.geographical_overlap must be boolean")
    if not isinstance(common.get("gini_optimised_reporting"), bool):
        raise DesignValidationError("secondary_analysis.common.gini_optimised_reporting must be boolean")
    if common.get("reporting_method") == "hierarchical_non_overlapping" and common["gini_optimised_reporting"]:
        raise DesignValidationError("hierarchical non-overlapping SaTScan reporting forbids Gini optimisation")
    if not isinstance(common.get("report_cluster_rank"), bool):
        raise DesignValidationError("secondary_analysis.common.report_cluster_rank must be boolean")
    for key in ("coordinate_crs", "coordinate_anchor_method", "spatial_window_shape"):
        if not isinstance(spatial.get(key), str) or not spatial.get(key):
            raise DesignValidationError(f"secondary_analysis.spatial_support.{key} is required")
    scenarios = _sequence(secondary.get("scenarios"), "secondary_analysis.scenarios")
    if not scenarios:
        raise DesignValidationError("secondary_analysis.scenarios must not be empty")
    seen: set[str] = set()
    for idx, item in enumerate(scenarios):
        scenario = _mapping(item, f"secondary_analysis.scenarios[{idx}]")
        sid = scenario.get("scenario_id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise DesignValidationError("Secondary scenario IDs must be unique non-empty strings")
        seen.add(sid)
        model = _method(scenario.get("model"), f"secondary_analysis.scenarios[{idx}].model")
        exposure = scenario.get("exposure_role")
        if model == "space_time_permutation" and exposure is not None:
            raise DesignValidationError(f"STP scenario {sid} must not define exposure")
        if model == "discrete_poisson" and (not isinstance(exposure, str) or not exposure):
            raise DesignValidationError(f"Poisson scenario {sid} requires exposure")


def validate_analysis_design(raw: Mapping[str, Any]) -> None:
    """Validate the executable scientific contract without exact-value mirroring."""

    if not isinstance(raw.get("schema_version"), str) or not raw.get("schema_version"):
        raise DesignValidationError("analysis schema_version is required")
    project = _mapping(raw.get("project"), "project")
    for key in ("name", "distribution", "package_namespace", "canonical_notebook", "analysis_schema", "data_schema"):
        if not isinstance(project.get(key), str) or not project.get(key):
            raise DesignValidationError(f"project.{key} is required")
    if "package_version" in project or "version" in project:
        raise DesignValidationError("Release version must not be duplicated in analysis_contract.yml")
    _validate_reproducibility(raw)
    study = _mapping(raw.get("study"), "study")
    _validate_windows(study)
    _validate_populations(study)
    _mapping(raw.get("field_roles"), "field_roles")
    rqs = _mapping(raw.get("research_questions"), "research_questions")
    for name in ("rq1", "rq2", "rq3"):
        if name not in rqs:
            raise DesignValidationError(f"Missing research_questions.{name}")
    _validate_rq1(raw, _mapping(rqs["rq1"], "research_questions.rq1"))
    _validate_rq2(raw, _mapping(rqs["rq2"], "research_questions.rq2"))
    _validate_rq3(_mapping(rqs["rq3"], "research_questions.rq3"))
    _validate_secondary(raw, _mapping(raw.get("secondary_analysis"), "secondary_analysis"))


def _iter_field_refs(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if (key.endswith("_field") or key.endswith("_role")) and isinstance(child, str):
                # Role references are validated separately and should not be treated as physical fields here.
                if key.endswith("_field"):
                    refs.append((path, child))
            refs.extend(_iter_field_refs(child, path))
    elif isinstance(value, (tuple, list)):
        for idx, child in enumerate(value):
            refs.extend(_iter_field_refs(child, f"{prefix}[{idx}]"))
    return refs


def _field_role_values(value: Any, prefix: str = "field_roles") -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            refs.extend(_field_role_values(child, f"{prefix}.{key}"))
    elif isinstance(value, (tuple, list)):
        for idx, child in enumerate(value):
            if isinstance(child, str):
                refs.append((f"{prefix}[{idx}]", child))
    elif isinstance(value, str):
        refs.append((prefix, value))
    return refs


def _iter_method_values(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Return method-authority references from executable analysis paths.

    Path predicates encode contract *shape*, not method identities. This avoids
    misclassifying ordinary strings such as a spatial-weight transform, a
    multiplicity-family label or the district crosswalk assignment method.
    """
    found: list[tuple[str, str]] = []

    def is_method_path(path: str, key: str) -> bool:
        if key in {
            "concentration_method", "inference_method", "multiplicity_method",
            "effect_estimator", "estimator", "working_correlation", "covariance",
            "reference_distribution", "reporting_method",
        }:
            return path.startswith("research_questions.") or path.startswith("secondary_analysis.")
        if key == "method":
            return path.startswith("research_questions.") or path.startswith("secondary_analysis.scenarios[")
        if key in {"family", "link"}:
            return path == f"research_questions.rq3.{key}"
        if key == "transform":
            return path.startswith("research_questions.rq3.predictors[")
        if key == "coding":
            return path.startswith("research_questions.rq3.factors[")
        if key == "model":
            return path.startswith("secondary_analysis.scenarios[")
        return False

    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, str) and is_method_path(path, str(key)):
                found.append((path, child))
            found.extend(_iter_method_values(child, path))
    elif isinstance(value, (tuple, list)):
        for idx, child in enumerate(value):
            found.extend(_iter_method_values(child, f"{prefix}[{idx}]"))
    return found


def validate_configuration_semantics(analysis, data_schema, methods, output, figure) -> None:
    """Validate cross-contract references and generic implementation capabilities."""

    configured_methods = methods.method_ids
    for item in methods.authorities:
        try:
            capability = require_implementation(item.implementation_id)
        except ValueError as exc:
            raise DesignValidationError(str(exc)) from exc
        configured_as_implemented = item.status == "implemented"
        if configured_as_implemented != capability.implemented:
            raise DesignValidationError(
                "Configured method status disagrees with software capability for "
                f"{item.method_id!r}: status={item.status!r}, "
                f"implementation_id={item.implementation_id!r}"
            )
        if item.outcome_tuning_allowed:
            raise DesignValidationError(f"Outcome-driven tuning is prohibited for method {item.method_id!r}")

    selected_refs = _iter_method_values(analysis.to_dict())
    selected = {value for _, value in selected_refs}
    missing_authority = selected.difference(configured_methods)
    if missing_authority:
        paths = {value: path for path, value in selected_refs if value in missing_authority}
        raise DesignValidationError(
            "Study methods missing from method_authorities.yml: "
            f"{sorted(missing_authority)!r}; locations={paths!r}"
        )

    fields = data_schema.field_names
    if analysis.project.get("analysis_schema") != data_schema.schema_version:
        raise DesignValidationError("Analysis/data-schema analysis-schema identities disagree")
    if analysis.project.get("data_schema") != data_schema.data_schema_version:
        raise DesignValidationError("Analysis/data-schema data-schema identities disagree")
    if data_schema.field_count != len(data_schema.fields):
        raise DesignValidationError("Data-schema field_count disagrees with the realised field registry")
    for panel_id, panel in data_schema.panels.items():
        if panel.column_count != data_schema.field_count:
            raise DesignValidationError(f"Panel {panel_id!r} column_count disagrees with field registry")
        unknown = set(panel.primary_key).difference(fields)
        if unknown:
            raise DesignValidationError(f"Panel {panel_id!r} primary key references unknown fields: {sorted(unknown)!r}")

    for path, field in _field_role_values(analysis.field_roles):
        if field not in fields:
            raise DesignValidationError(f"Invalid field reference {field!r} at {path}")
    for path, field in _iter_field_refs(analysis.to_dict()):
        if field not in fields:
            raise DesignValidationError(f"Invalid physical field reference {field!r} at {path}")

    # Analysis population source panels/populations and role references are executable authority.
    populations = analysis.study["populations"]
    for population_id, pop in populations.items():
        source_panel = pop.get("source_panel")
        source_population = pop.get("source_population")
        if source_panel is not None and source_panel not in data_schema.panels:
            raise DesignValidationError(f"Population {population_id!r} references unknown panel {source_panel!r}")
        if source_population is not None and source_population not in populations:
            raise DesignValidationError(f"Population {population_id!r} references unknown population {source_population!r}")
        for key in ("denominator_role", "positive_role"):
            if key in pop:
                try:
                    resolve_field_role(analysis, str(pop[key]))
                except ValueError as exc:
                    raise DesignValidationError(str(exc)) from exc
        for role in pop.get("support_roles", ()):
            try:
                resolve_field_role(analysis, str(role))
            except ValueError as exc:
                raise DesignValidationError(str(exc)) from exc

    # Factor references must belong to the physical schema domains.
    for item in analysis.research_questions["rq3"]["factors"]:
        role_path = str(item["field_role"])
        try:
            field_name = str(resolve_field_role(analysis, role_path))
            field_spec = data_schema.field(field_name)
        except (ValueError, KeyError) as exc:
            raise DesignValidationError(f"Invalid RQ3 factor field role {role_path!r}") from exc
        if field_spec.categorical_domain is None:
            raise DesignValidationError(f"Categorical reference field {field_name!r} has no configured domain")
        domain = data_schema.categorical_domains[field_spec.categorical_domain]
        if item["reference"] not in domain:
            raise DesignValidationError(
                f"Invalid categorical reference {item['reference']!r} for {field_name}; allowed {tuple(domain)!r}"
            )

    # SaTScan case/exposure roles must resolve and obey model semantics.
    for scenario in analysis.secondary_analysis["scenarios"]:
        try:
            resolve_field_role(analysis, str(scenario["case_role"]))
            if scenario.get("exposure_role") is not None:
                resolve_field_role(analysis, str(scenario["exposure_role"]))
        except ValueError as exc:
            raise DesignValidationError(str(exc)) from exc

    object_fields: dict[str, frozenset[str]] = {panel_id: fields for panel_id in data_schema.panels}
    for geometry_id, geometry in data_schema.geometries.items():
        object_fields[f"{geometry_id}_geometry"] = frozenset(geometry.required_columns)
    for relationship in data_schema.relationships:
        if relationship.from_object not in object_fields or relationship.to_object not in object_fields:
            raise DesignValidationError(f"Relationship {relationship.relationship_id!r} references unknown object")
        if relationship.from_field not in object_fields[relationship.from_object]:
            raise DesignValidationError(f"Relationship {relationship.relationship_id!r} has unknown source field")
        if relationship.to_field not in object_fields[relationship.to_object]:
            raise DesignValidationError(f"Relationship {relationship.relationship_id!r} has unknown target field")

    recon = data_schema.additive_reconciliation.get("district_to_acz")
    if not isinstance(recon, Mapping):
        raise DesignValidationError("Missing district_to_acz additive-reconciliation authority")
    for field_name in recon.get("fields", ()):
        if field_name not in fields:
            raise DesignValidationError(f"Invalid additive reconciliation field {field_name!r}: unknown field")
        if not data_schema.field(field_name).additive:
            raise DesignValidationError(f"Additive reconciliation field {field_name!r} is not declared additive")

    roles = {"manuscript", "supplementary", "internal_authority"}
    for table in output.tables:
        if table.builder not in OUTPUT_BUILDER_REGISTRY:
            raise DesignValidationError(f"Unregistered output builder {table.builder!r}")
        if table.role not in roles:
            raise DesignValidationError(f"Invalid output role {table.role!r}")
        if table.role != "internal_authority" and not table.required_columns:
            raise DesignValidationError(f"Publication output {table.output_id} requires a governed schema")
    for item in output.secondary_outputs:
        if item.builder not in OUTPUT_BUILDER_REGISTRY:
            raise DesignValidationError(f"Unregistered secondary output builder {item.builder!r}")
        if item.role != "internal_authority":
            raise DesignValidationError(f"Secondary output {item.output_id} must be internal_authority")

    for item in figure.figures:
        if item.renderer not in FIGURE_RENDERER_REGISTRY:
            raise DesignValidationError(f"Unregistered figure renderer {item.renderer!r}")
        if item.data_builder not in FIGURE_DATA_BUILDER_REGISTRY:
            raise DesignValidationError(f"Unregistered figure data builder {item.data_builder!r}")
        if item.role not in roles:
            raise DesignValidationError(f"Invalid figure role {item.role!r}")
        if item.panel_count <= 0:
            raise DesignValidationError(f"Figure {item.figure_id} panel_count must be positive")
        if item.role != "internal_authority" and not item.required_columns:
            raise DesignValidationError(f"Publication figure {item.figure_id} requires a source-data schema")

    presentation = figure.presentation_export
    if presentation is not None:
        unsupported_renderers = set(presentation.renderer_identities).difference(
            PRESENTATION_RENDERER_REGISTRY
        )
        if unsupported_renderers:
            raise DesignValidationError(
                "Unregistered presentation renderer identities: "
                f"{sorted(unsupported_renderers)!r}"
            )
        configured_scenarios = {
            str(item["scenario_id"]) for item in analysis.secondary_analysis["scenarios"]
        }
        configured_geometries = set(data_schema.geometries)
        for dependency in presentation.geometry_dependencies.values():
            unknown_geometries = set(dependency.geometries).difference(configured_geometries)
            if unknown_geometries:
                raise DesignValidationError(
                    f"Presentation geometry dependency {dependency.dependency_id!r} references "
                    f"unknown geometries: {sorted(unknown_geometries)!r}"
                )
        for item in presentation.exports:
            if item.renderer_identity not in PRESENTATION_RENDERER_REGISTRY:
                raise DesignValidationError(
                    f"Unregistered presentation renderer {item.renderer_identity!r} for {item.export_id}"
                )
            if item.scenario is not None and item.scenario not in configured_scenarios:
                raise DesignValidationError(
                    f"Presentation export {item.export_id!r} references unknown secondary scenario "
                    f"{item.scenario!r}"
                )


def assert_execution_ready(raw: Mapping[str, Any], methods, research_question: str) -> None:
    """Fail closed when an injected configured production method is unavailable.

    The analysis contract supplies the selected method ID; the separate method
    authority contract binds that ID to an implementation capability. Python does
    not own the scientific method mapping.
    """

    validate_analysis_design(raw)
    rqs = _mapping(raw["research_questions"], "research_questions")
    if research_question == "rq1":
        return
    if research_question == "rq2":
        method = str(rqs["rq2"]["inferential_test"]["method"] )
    elif research_question == "rq3":
        method = str(rqs["rq3"]["estimator"] )
    else:
        raise DesignValidationError(f"Unknown research question: {research_question!r}")
    try:
        implemented = method_is_implemented(methods, method)
    except ValueError as exc:
        raise DesignValidationError(str(exc)) from exc
    if not implemented:
        raise PendingDesignError(
            f"{research_question.upper()} method {method!r} is scientifically frozen but not yet production-implemented"
        )
