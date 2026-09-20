"""Generic statistical foundations for Ghana Fire RP1 Analysis v1.

The functions here expose stable project-specific result schemas.  They do not
choose among scientific methods and do not implement final RQ-specific analyses.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from statistics import NormalDist

import numpy as np
from scipy.stats import rankdata, theilslopes


class InferenceInputError(ValueError):
    """Raised when statistical input is missing, invalid, or computationally unsafe."""


class MethodAdmissibilityError(InferenceInputError):
    """Raised when realised input violates a configured method-reference admissibility rule."""


_NORMAL = NormalDist()


def _finite_vector(values: Iterable[float], *, min_n: int, name: str = "series") -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    if arr.ndim != 1:
        raise InferenceInputError(f"{name} must be one-dimensional")
    if arr.size < min_n:
        raise InferenceInputError(f"{name} must contain at least {min_n} observations")
    if not np.isfinite(arr).all():
        raise InferenceInputError(f"{name} contains missing or non-finite values")
    return arr


def _validate_alpha(alpha: float) -> float:
    try:
        value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise InferenceInputError("alpha must be numeric") from exc
    if not math.isfinite(value) or value <= 0.0 or value >= 1.0:
        raise InferenceInputError("alpha must lie strictly between 0 and 1")
    return value


def _validate_confidence_level(level: float) -> float:
    try:
        value = float(level)
    except (TypeError, ValueError) as exc:
        raise InferenceInputError("confidence_level must be numeric") from exc
    if not math.isfinite(value) or value <= 0.0 or value >= 1.0:
        raise InferenceInputError("confidence_level must lie strictly between 0 and 1")
    return value


@dataclass(frozen=True, slots=True)
class SenSlopeResult:
    n: int
    slope: float
    intercept: float
    ci_low: float
    ci_high: float
    confidence_level: float
    method: str
    diagnostic_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def sens_slope(
    values: Iterable[float],
    *,
    x: Iterable[float] | None = None,
    confidence_level: float,
) -> SenSlopeResult:
    """Return Sen/Theil slope and a slope confidence interval via SciPy ``theilslopes``."""

    y = _finite_vector(values, min_n=2)
    level = _validate_confidence_level(confidence_level)
    if x is None:
        x_arr = np.arange(y.size, dtype=float)
    else:
        x_arr = _finite_vector(x, min_n=2, name="x")
        if x_arr.size != y.size:
            raise InferenceInputError("x and series must have equal length")
        if np.any(np.diff(x_arr) <= 0):
            raise InferenceInputError("x must be strictly increasing")
    result = theilslopes(y, x_arr, alpha=level, method="separate")
    status = "constant_series" if np.all(y == y[0]) else "ok"
    return SenSlopeResult(
        n=int(y.size),
        slope=float(result.slope),
        intercept=float(result.intercept),
        ci_low=float(result.low_slope),
        ci_high=float(result.high_slope),
        confidence_level=level,
        method="sens_slope_scipy_theilslopes",
        diagnostic_status=status,
    )




def sen_slope_point_estimate(
    values: Iterable[float],
    *,
    x: Iterable[float] | None = None,
) -> float:
    """Return only Sen's median pairwise slope.

    This point-estimate helper deliberately constructs no confidence interval. It
    is the RQ2 effect-size primitive used when uncertainty is supplied by a
    separate inferential procedure rather than an independence-oriented slope
    interval.
    """

    y = _finite_vector(values, min_n=2)
    if x is None:
        x_arr = np.arange(y.size, dtype=float)
    else:
        x_arr = _finite_vector(x, min_n=2, name="x")
        if x_arr.size != y.size:
            raise InferenceInputError("x and series must have equal length")
        if np.any(np.diff(x_arr) <= 0):
            raise InferenceInputError("x must be strictly increasing")
    i, j = np.triu_indices(y.size, k=1)
    slopes = (y[j] - y[i]) / (x_arr[j] - x_arr[i])
    return float(np.median(slopes))


def _rq2_bandwidth(n: int, rule: str) -> int:
    if rule != "floor_n_power_one_third":
        raise InferenceInputError(f"unsupported bandwidth rule: {rule!r}")
    if n < 2:
        raise InferenceInputError("series must contain at least two observations")
    return int(math.floor(float(n) ** (1.0 / 3.0)))


def _empirical_cdf_at_observations(values: np.ndarray, convention: str) -> np.ndarray:
    if convention != "less_than_or_equal_ecdf":
        raise InferenceInputError(f"unsupported empirical-CDF convention: {convention!r}")
    ordered = np.sort(values)
    # Right-continuous empirical CDF: F_n(x) = n^{-1} sum 1{X_i <= x}.
    return np.searchsorted(ordered, values, side="right").astype(float) / float(values.size)


def _studentized_global_mk_components(
    values: np.ndarray,
    *,
    bandwidth: int,
    variance_floor: float,
    empirical_cdf: str,
) -> tuple[float, float, float, bool]:
    n = int(values.size)
    i, j = np.triu_indices(n, k=1)
    u_n = float(np.sign(values[j] - values[i]).sum() / float(i.size))
    f = _empirical_cdf_at_observations(values, empirical_cdf)
    g = 1.0 - 2.0 * f
    covariance_sum = 0.0
    for lag in range(1, bandwidth + 1):
        covariance_sum += float(np.dot(g[:-lag], g[lag:]))
    sigma2 = float(4.0 / 9.0 + (8.0 / (3.0 * n)) * covariance_sum)
    floor_used = sigma2 < variance_floor
    denominator = math.sqrt(max(sigma2, variance_floor))
    t_n = float(math.sqrt(n) * u_n / denominator)
    return u_n, sigma2, t_n, bool(floor_used)


@dataclass(frozen=True, slots=True)
class StudentizedGlobalMannKendallPermutationResult:
    n: int
    u_n: float
    realised_bandwidth: int
    long_run_variance: float
    variance_floor: float
    variance_floor_used: bool
    t_n: float
    permutation_count: int
    seed: int
    extreme_count: int
    raw_p: float
    method_id: str
    implementation_id: str
    bandwidth_rule: str
    empirical_cdf: str
    studentisation: str
    alternative: str
    p_value_method: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def studentized_global_mann_kendall_permutation(
    series: Iterable[float],
    *,
    bandwidth_rule: str,
    variance_floor: float,
    replications: int,
    alternative: str,
    seed: int,
    p_value_rule: str,
    empirical_cdf: str,
    studentisation: str,
    method_id: str,
    implementation_id: str,
    requires_distinct_observations: bool = False,
    on_ties: str = "allow",
) -> StudentizedGlobalMannKendallPermutationResult:
    """Romano-Tirlea studentized global Mann-Kendall permutation inference.

    The observed statistic and every permutation are studentized independently.
    Monte-Carlo inference uses the configured absolute two-sided extremeness rule
    and the plus-one construction, so a reported p-value can never equal zero.
    """

    y = _finite_vector(series, min_n=2)
    if not isinstance(requires_distinct_observations, bool):
        raise InferenceInputError("requires_distinct_observations must be boolean")
    if on_ties not in {"allow", "fail_closed"}:
        raise InferenceInputError("on_ties must be 'allow' or 'fail_closed'")
    if requires_distinct_observations and on_ties != "fail_closed":
        raise InferenceInputError(
            "requires_distinct_observations=True requires on_ties='fail_closed'"
        )
    if requires_distinct_observations and np.unique(y).size != y.size:
        raise MethodAdmissibilityError(
            "Romano-Tirlea reference admissibility failed: strict configured RQ2 inference "
            "requires tie-free annual observations; realised series contains ties"
        )
    try:
        epsilon = float(variance_floor)
    except (TypeError, ValueError) as exc:
        raise InferenceInputError("variance_floor must be numeric") from exc
    if not math.isfinite(epsilon) or epsilon <= 0.0:
        raise InferenceInputError("variance_floor must be finite and strictly positive")
    if not isinstance(replications, int) or isinstance(replications, bool) or replications < 1:
        raise InferenceInputError("replications must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise InferenceInputError("seed must be a non-negative integer")
    if alternative != "two_sided_absolute":
        raise InferenceInputError("only two_sided_absolute is supported")
    if p_value_rule != "monte_carlo_plus_one":
        raise InferenceInputError("only monte_carlo_plus_one is supported")
    if studentisation != "recompute_for_each_permutation":
        raise InferenceInputError("studentisation must be recompute_for_each_permutation")
    if not isinstance(method_id, str) or not method_id:
        raise InferenceInputError("method_id must be a non-empty configured identifier")
    if not isinstance(implementation_id, str) or not implementation_id:
        raise InferenceInputError("implementation_id must be a non-empty registered identifier")

    n = int(y.size)
    bandwidth = _rq2_bandwidth(n, bandwidth_rule)
    observed_u, observed_sigma2, observed_t, floor_used = _studentized_global_mk_components(
        y,
        bandwidth=bandwidth,
        variance_floor=epsilon,
        empirical_cdf=empirical_cdf,
    )

    # Generate independent uniform permutations for each Monte-Carlo replicate
    # using random-key orderings.  The same integer seed and NumPy Generator
    # semantics therefore reproduce the complete permutation sequence exactly.
    rng = np.random.default_rng(seed)
    order = np.argsort(rng.random((replications, n)), axis=1, kind="stable")
    permuted = y[order]

    pair_i, pair_j = np.triu_indices(n, k=1)
    perm_u = np.sign(permuted[:, pair_j] - permuted[:, pair_i]).sum(axis=1) / float(pair_i.size)

    ecdf_values = _empirical_cdf_at_observations(y, empirical_cdf)
    perm_g = 1.0 - 2.0 * ecdf_values[order]
    covariance_sum = np.zeros(replications, dtype=float)
    for lag in range(1, bandwidth + 1):
        covariance_sum += np.sum(perm_g[:, :-lag] * perm_g[:, lag:], axis=1)
    perm_sigma2 = 4.0 / 9.0 + (8.0 / (3.0 * n)) * covariance_sum
    perm_t = math.sqrt(n) * perm_u / np.sqrt(np.maximum(perm_sigma2, epsilon))

    extreme = int(np.count_nonzero(np.abs(perm_t) >= abs(observed_t)))
    raw_p = float((extreme + 1) / (replications + 1))
    return StudentizedGlobalMannKendallPermutationResult(
        n=n,
        u_n=observed_u,
        realised_bandwidth=bandwidth,
        long_run_variance=observed_sigma2,
        variance_floor=epsilon,
        variance_floor_used=floor_used,
        t_n=observed_t,
        permutation_count=int(replications),
        seed=int(seed),
        extreme_count=extreme,
        raw_p=raw_p,
        method_id=method_id,
        implementation_id=implementation_id,
        bandwidth_rule=bandwidth_rule,
        empirical_cdf=empirical_cdf,
        studentisation=studentisation,
        alternative=alternative,
        p_value_method=p_value_rule,
    )

def _mk_score(y: np.ndarray) -> float:
    score = 0.0
    for i in range(y.size - 1):
        score += float(np.sign(y[i + 1 :] - y[i]).sum())
    return score


def _acf(values: np.ndarray, max_lag: int) -> tuple[float, ...]:
    if not isinstance(max_lag, int) or isinstance(max_lag, bool):
        raise InferenceInputError("max_lag must be an integer")
    if max_lag < 1 or max_lag >= values.size:
        raise InferenceInputError(f"max_lag must lie in 1..{values.size - 1}")
    centered = values - float(np.mean(values))
    denominator = float(np.dot(centered, centered))
    if denominator == 0.0:
        return tuple(0.0 for _ in range(max_lag))
    correlations = []
    for lag in range(1, max_lag + 1):
        correlations.append(float(np.dot(centered[:-lag], centered[lag:]) / denominator))
    return tuple(correlations)


@dataclass(frozen=True, slots=True)
class AutocorrelationDiagnostics:
    n: int
    max_lag: int
    autocorrelations: tuple[float, ...]
    significance_threshold: float
    significant_lags: tuple[int, ...]
    detrending: str
    ranked: bool
    diagnostic_status: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["autocorrelations"] = list(self.autocorrelations)
        payload["significant_lags"] = list(self.significant_lags)
        return payload


def autocorrelation_diagnostics(
    values: Iterable[float],
    *,
    max_lag: int,
    alpha: float,
    detrend: bool = False,
    rank: bool = False,
) -> AutocorrelationDiagnostics:
    """Return deterministic biased ACF diagnostics through a pre-specified maximum lag."""

    y = _finite_vector(values, min_n=3)
    alpha = _validate_alpha(alpha)
    transformed = y.copy()
    detrending = "none"
    if detrend:
        slopes = [
            (float(y[j]) - float(y[i])) / float(j - i)
            for i in range(y.size - 1)
            for j in range(i + 1, y.size)
        ]
        slope = float(np.median(np.asarray(slopes, dtype=float)))
        transformed = transformed - np.arange(1, y.size + 1, dtype=float) * slope
        detrending = "sens_slope"
    if rank:
        transformed = np.asarray(rankdata(transformed, method="average"), dtype=float)
    acf = _acf(transformed, max_lag)
    threshold = float(_NORMAL.inv_cdf(1.0 - alpha / 2.0) / math.sqrt(y.size))
    significant = tuple(i + 1 for i, rho in enumerate(acf) if abs(rho) > threshold)
    status = "constant_series" if np.all(transformed == transformed[0]) else "ok"
    return AutocorrelationDiagnostics(
        n=int(y.size),
        max_lag=max_lag,
        autocorrelations=acf,
        significance_threshold=threshold,
        significant_lags=significant,
        detrending=detrending,
        ranked=bool(rank),
        diagnostic_status=status,
    )


@dataclass(frozen=True, slots=True)
class FDRResult:
    family_name: str
    n_tests: int
    alpha: float
    raw_p_values: tuple[float, ...]
    adjusted_p_values: tuple[float, ...]
    rejected: tuple[bool, ...]
    method: str = "benjamini_hochberg"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["raw_p_values"] = list(self.raw_p_values)
        payload["adjusted_p_values"] = list(self.adjusted_p_values)
        payload["rejected"] = list(self.rejected)
        return payload


def benjamini_hochberg(
    p_values: Iterable[float],
    *,
    family_name: str,
    alpha: float,
) -> FDRResult:
    """Adjust one explicitly named inferential family using BH-FDR."""

    if not isinstance(family_name, str) or not family_name.strip():
        raise InferenceInputError("family_name must be an explicit non-empty string")
    alpha = _validate_alpha(alpha)
    p = _finite_vector(p_values, min_n=1, name="p_values")
    if np.any((p < 0.0) | (p > 1.0)):
        raise InferenceInputError("p-values must lie in [0,1]")
    m = p.size
    order = np.argsort(p, kind="mergesort")
    ordered = p[order]
    raw_adjusted = ordered * m / np.arange(1, m + 1, dtype=float)
    monotone = np.minimum.accumulate(raw_adjusted[::-1])[::-1]
    monotone = np.clip(monotone, 0.0, 1.0)
    adjusted = np.empty_like(monotone)
    adjusted[order] = monotone
    rejected = adjusted <= alpha
    return FDRResult(
        family_name=family_name.strip(),
        n_tests=int(m),
        alpha=alpha,
        raw_p_values=tuple(float(x) for x in p),
        adjusted_p_values=tuple(float(x) for x in adjusted),
        rejected=tuple(bool(x) for x in rejected),
    )


def normal_confidence_interval(
    estimate: float,
    standard_error: float,
    *,
    confidence_level: float,
) -> tuple[float, float]:
    """Return a two-sided normal-approximation confidence interval."""

    level = _validate_confidence_level(confidence_level)
    try:
        estimate = float(estimate)
        standard_error = float(standard_error)
    except (TypeError, ValueError) as exc:
        raise InferenceInputError("estimate and standard_error must be numeric") from exc
    if not math.isfinite(estimate) or not math.isfinite(standard_error):
        raise InferenceInputError("estimate and standard_error must be finite")
    if standard_error < 0.0:
        raise InferenceInputError("standard_error must be non-negative")
    z = _NORMAL.inv_cdf(0.5 + level / 2.0)
    margin = z * standard_error
    return float(estimate - margin), float(estimate + margin)


@dataclass(frozen=True, slots=True)
class OddsRatioResult:
    coefficient: float
    odds_ratio: float
    ci_low: float | None
    ci_high: float | None
    confidence_level: float | None
    method: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _safe_exp(value: float) -> float:
    if not math.isfinite(value):
        raise InferenceInputError("coefficient transform requires a finite value")
    upper = math.log(sys.float_info.max)
    # exp(x) underflows to zero around -745 on IEEE-754 doubles.  Returning zero
    # would falsely imply a known zero odds ratio, so fail closed instead.
    lower = math.log(float.fromhex("0x0.0000000000001p-1022"))
    if value > upper or value < lower:
        raise InferenceInputError("coefficient is outside the safe exponential range")
    result = math.exp(value)
    if result == 0.0 or not math.isfinite(result):
        raise InferenceInputError("coefficient-to-odds-ratio transform is numerically unsafe")
    return float(result)


def coefficient_to_odds_ratio(
    coefficient: float,
    *,
    standard_error: float | None = None,
    confidence_level: float,
) -> OddsRatioResult:
    """Exponentiate a log-odds coefficient with optional normal CI, failing on overflow."""

    try:
        beta = float(coefficient)
    except (TypeError, ValueError) as exc:
        raise InferenceInputError("coefficient must be numeric") from exc
    odds = _safe_exp(beta)
    if standard_error is None:
        return OddsRatioResult(beta, odds, None, None, None, "exp_log_odds")
    low, high = normal_confidence_interval(beta, standard_error, confidence_level=confidence_level)
    return OddsRatioResult(
        coefficient=beta,
        odds_ratio=odds,
        ci_low=_safe_exp(low),
        ci_high=_safe_exp(high),
        confidence_level=float(confidence_level),
        method="exp_log_odds_normal_ci",
    )
