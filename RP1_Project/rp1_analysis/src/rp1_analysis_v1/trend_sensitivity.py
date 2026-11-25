"""Pointwise Sen slope uncertainty and five-zone trend detectability.

The observed trend test is owned by :mod:`trend_robustness`. This module
calibrates additional slope intervals and evaluates the finite-sample behavior
of the same test rule under explicitly simulated annual burned-area series.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from .config import rq2_trend_parameters
from .contracts import AnalysisContract
from .inference import (
    _bh_adjusted_p_values,
    _rq2_bandwidth,
    _studentized_global_mk_rank_components,
)

_ZONES = ("CZ", "FZ", "GS", "SS", "TZ")
_SLOPE_UNIT = "change in annual mapped km2 per 100 km2 fixed burnable area per year"
_Z_95 = 1.959963984540054
_INDEPENDENT_SIMULATION = "independent_simulated_series"
_INCOMPLETE_FAMILY = "UNAVAILABLE_INCOMPLETE_FIVE_ZONE_FAMILY"
_CROSSING_CANDIDATE = "SCREENING_CROSSING_PENDING_CONFIRMATION"
_UNCONFIRMED_CROSSING = "UNCONFIRMED_SCREENING_CROSSING"
_CALIBRATION_FIELDS = (
    "parent_code", "noise_scenario", "decline_fraction_per_decade", "true_slope", "sample", "replicates",
    "valid_fit_count", "uncalibrated_coverage", "calibrated_coverage", "coverage_lower_95", "coverage_upper_95",
    "coverage_mcse", "slope_bias", "mean_interval_width", "calibration_multiplier",
)
_DETECTABILITY_IDENTIFIERS = ("noise_scenario", "effect_pattern", "target_zone", "parent_code")
_DETECTABILITY_FIELDS = (
    *_DETECTABILITY_IDENTIFIERS, "decline_fraction_per_decade", "injected_slope", "replicates", "raw_rejection_count",
    "raw_rejection", "raw_rejection_lower_95", "raw_rejection_upper_95", "bh_rejection_count", "bh_rejection",
    "bh_rejection_lower_95", "bh_rejection_upper_95", "bh_rejection_mcse", "bh_bank_min", "bh_bank_max",
    "bh_bank_lower_95_min", "family_any_bh_rejection", "family_any_bh_rejection_lower_95",
    "family_any_bh_rejection_upper_95", "family_any_bh_rejection_mcse", "family_fdr", "family_fdr_mcse",
    "variance_floor_fraction",
)
_DETECTABILITY_SUMMARY_FIELDS = (
    *_DETECTABILITY_IDENTIFIERS, "target_power", "status", "sustained_decline_fraction_per_decade", "sustained_slope",
    "maximum_tested_decline_fraction_per_decade", "maximum_tested_decline_slope", "peak_bh_detection", "peak_slope",
    "estimated_nonmonotone",
)


class TrendSensitivityError(ValueError):
    """Input or simulation configuration cannot support the requested diagnostics."""


@dataclass(frozen=True, slots=True)
class TrendSensitivitySettings:
    seed: int = 20260823
    interval_bootstrap_replicates: int = 9999
    calibration_bootstrap_replicates: int = 299
    calibration_replicates: int = 600
    validation_replicates: int = 600
    detectability_replicates: int = 3000
    held_out_interval_replicates: int = 300
    null_confirmation_replicates: int = 4000
    expected_block_length: int = 3
    sensitivity_block_lengths: tuple[int, ...] = (2, 4, 6)
    interval_level: float = 0.95
    calibration_coverage: float = 0.98
    calibration_decline: float = 0.20
    variance_floor: float = 0.001
    bandwidth: int = 2
    permutation_count: int = 9999
    permutation_banks: int = 3
    bh_alpha: float = 0.05
    target_power: float = 0.80
    coverage_review_flag: float = 0.925
    null_rejection_review_flag: float = 0.075
    fitted_lag_shrinkage: float = 0.7
    fitted_lag_limit: float = 0.65
    positive_stress_lag: float = 0.45
    negative_stress_lag: float = -0.40
    cross_zone_diagonal_weight: float = 0.25
    heavy_tail_strength: float = 1.25
    skew_strength: float = 0.6
    decline_grid: tuple[float, ...] = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80)
    years: tuple[int, ...] = tuple(range(2001, 2025))


def _centered_time(n_years: int) -> np.ndarray:
    return np.arange(n_years, dtype=float) - (n_years - 1) / 2


_PRIMARY_SETTINGS = {"variance_floor", "bandwidth", "permutation_count", "bh_alpha", "years"}


def _profile_options(profile: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(profile, Mapping):
        raise TrendSensitivityError("RQ2 trend_sensitivity must be a mapping")
    defaults = asdict(TrendSensitivitySettings())
    keys = set(defaults) - _PRIMARY_SETTINGS
    if set(profile) != keys:
        raise TrendSensitivityError(
            f"RQ2 trend_sensitivity missing {sorted(keys - set(profile))}, "
            f"unexpected {sorted(set(profile) - keys, key=str)}"
        )
    options = {}
    for name, value in profile.items():
        default = defaults[name]
        values = value if isinstance(default, tuple) else [value]
        expected = type(default[0]) if isinstance(default, tuple) else type(default)
        numeric_types = (int,) if expected is int else (int, float)
        if not isinstance(values, (list, tuple)) or any(
            type(item) not in numeric_types or not math.isfinite(item) for item in values
        ):
            raise TrendSensitivityError(f"RQ2 trend_sensitivity setting {name} has an invalid numeric value")
        options[name] = tuple(values) if isinstance(default, tuple) else value
    if options["null_confirmation_replicates"] < 4000:
        raise TrendSensitivityError("RQ2 null confirmation requires at least 4,000 independent families per setting")
    return options


def _compile_settings(*, years, profile=None, **primary) -> TrendSensitivitySettings:
    if len(years) < 6:
        raise TrendSensitivityError("Trend sensitivity requires at least six declared complete calendar years")
    options = _profile_options(profile) if profile is not None else {}
    defaults = TrendSensitivitySettings()
    declared_grid = np.asarray(options.get("decline_grid", defaults.decline_grid), dtype=float)
    if len(declared_grid) < 2 or declared_grid[0] != 0 or not np.all(np.diff(declared_grid) > 0) or declared_grid[-1] >= 1:
        raise TrendSensitivityError("The declared decline grid must increase from zero and stay below one")
    maximum_decline = 10.0 / _centered_time(len(years))[-1]
    feasible_grid = tuple(float(decline) for decline in declared_grid if decline < maximum_decline)
    if len(feasible_grid) == 1:
        feasible_grid = (0.0, maximum_decline / 2)
    calibration_decline = options.get("calibration_decline", defaults.calibration_decline)
    if not 0 < calibration_decline <= declared_grid[-1]:
        raise TrendSensitivityError("The declared calibration decline must be positive and within the decline grid")
    options.update(decline_grid=feasible_grid, calibration_decline=min(calibration_decline, feasible_grid[-1]))
    settings = TrendSensitivitySettings(years=years, **primary, **options)
    _validate_settings(settings)
    return settings


def settings_from_primary(analysis: AnalysisContract) -> TrendSensitivitySettings:
    """Bind the simulation decision rule to the primary RQ2 contract."""
    parameters = rq2_trend_parameters(analysis)
    supported = {
        "effect_estimator": "sens_slope",
        "inferential_test": "studentized_global_mann_kendall_permutation",
        "empirical_cdf": "less_than_or_equal_ecdf",
        "rank_tie_contribution": "zero",
        "bandwidth_rule": "floor_n_power_one_third",
        "studentisation": "recompute_for_each_permutation",
        "alternative": "two_sided_absolute",
        "p_value_method": "monte_carlo_plus_one",
        "multiple_testing_method": "benjamini_hochberg",
        "family_size": len(_ZONES),
    }
    for name, expected in supported.items():
        if getattr(parameters, name) != expected:
            raise TrendSensitivityError(f"Unsupported primary RQ2 setting for the simulation: {name}")
    rq2 = analysis.research_questions["rq2"]
    if (rq2["multiple_testing"]["family"] != "exactly_five_acz_raw_p_values"
            or int(rq2["expected_series_count"]) != len(_ZONES)):
        raise TrendSensitivityError("Trend sensitivity requires the primary family of five ACZ tests")
    if (rq2["rate"]["denominator_support"] != "fixed_ba2001_burnable_union"
            or float(rq2["rate"]["scale_per_km2"]) != 100.0):
        raise TrendSensitivityError("Trend sensitivity requires annual rates per 100 km2 of fixed burnable area")
    window = analysis.study["temporal_windows"]["long_run"]
    start, end = pd.Period(window["start"], freq="M"), pd.Period(window["end"], freq="M")
    years = tuple(range(start.year, end.year + 1))
    if (start.month != 1 or end.month != 12 or len(years) < 6
            or len(years) != int(rq2["expected_n_per_series"])):
        raise TrendSensitivityError("Trend sensitivity requires at least six declared complete calendar years")
    return _compile_settings(
        variance_floor=parameters.variance_floor,
        bandwidth=_rq2_bandwidth(len(years), parameters.bandwidth_rule),
        permutation_count=parameters.permutations,
        bh_alpha=parameters.alpha,
        years=years,
        profile=rq2.get("trend_sensitivity"),
    )


@dataclass(frozen=True, slots=True)
class TrendSensitivityResult:
    intervals: pd.DataFrame
    calibration: pd.DataFrame
    detectability: pd.DataFrame
    detectability_summary: pd.DataFrame
    settings: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Noise:
    name: str
    lag1: np.ndarray
    log_dispersion: np.ndarray
    innovation_correlation: np.ndarray
    transform: str = "gaussian"
    strength: float = 0.0
    independent_zones: bool = False


def _validate_settings(settings: TrendSensitivitySettings) -> None:
    years = settings.years
    if (len(years) < 6 or any(type(year) is not int for year in years)
            or tuple(years) != tuple(range(years[0], years[0] + len(years)))):
        raise TrendSensitivityError("The annual calendar must contain at least six consecutive integer years")
    counts = (
        settings.interval_bootstrap_replicates,
        settings.calibration_bootstrap_replicates,
        settings.calibration_replicates,
        settings.validation_replicates,
        settings.detectability_replicates,
        settings.held_out_interval_replicates,
        settings.null_confirmation_replicates,
        settings.permutation_count,
        settings.permutation_banks,
    )
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 2 for n in counts):
        raise TrendSensitivityError("Replication counts must be integers of at least two")
    if isinstance(settings.seed, bool) or not isinstance(settings.seed, int) or settings.seed < 0:
        raise TrendSensitivityError("The simulation seed must be a nonnegative integer")
    lengths = (settings.expected_block_length, *settings.sensitivity_block_lengths)
    if any(isinstance(n, bool) or not isinstance(n, int) or not 2 <= n <= min(12, len(years)) for n in lengths):
        raise TrendSensitivityError("Expected block lengths must be integers between 2 and 12 within the annual record")
    if len(set(lengths)) != len(lengths):
        raise TrendSensitivityError("Block lengths must be distinct")
    if not 0 < settings.interval_level < settings.calibration_coverage < 1:
        raise TrendSensitivityError("Calibration coverage must exceed the interval level and be below one")
    if not 0 < settings.bh_alpha < 1 or not 0 < settings.target_power < 1:
        raise TrendSensitivityError("BH alpha and target power must lie strictly between zero and one")
    if not 0 < settings.coverage_review_flag <= settings.interval_level or not 0 < settings.null_rejection_review_flag < 1:
        raise TrendSensitivityError("Review flags must be valid proportions within the declared interval settings")
    if not (0 <= settings.fitted_lag_shrinkage <= 1 and 0 < settings.fitted_lag_limit < 1
            and 0 < settings.positive_stress_lag < 1 and -1 < settings.negative_stress_lag < 0
            and 0 < settings.cross_zone_diagonal_weight <= 1
            and 0 < settings.heavy_tail_strength <= 2 and 0 < settings.skew_strength <= 2):
        raise TrendSensitivityError("Noise settings must specify stationary AR(1) and bounded marginal transforms")
    if not math.isfinite(settings.variance_floor) or settings.variance_floor <= 0:
        raise TrendSensitivityError("The variance floor must be positive and finite")
    if isinstance(settings.bandwidth, bool) or not isinstance(settings.bandwidth, int) or not 1 <= settings.bandwidth < len(years):
        raise TrendSensitivityError("The studentization bandwidth is invalid")
    maximum_decline = 10.0 / _centered_time(len(years))[-1]
    if not 0 < settings.calibration_decline < maximum_decline:
        raise TrendSensitivityError("The calibration decline must preserve positive central rates")
    grid = np.asarray(settings.decline_grid, dtype=float)
    if len(grid) < 2 or grid[0] != 0 or not np.all(np.diff(grid) > 0) or not grid[-1] < maximum_decline:
        raise TrendSensitivityError("The decline grid must increase from zero and preserve positive central rates")


def _input_rates(frame: pd.DataFrame, settings: TrendSensitivitySettings) -> np.ndarray:
    columns = {"parent_code", "year", "annual_rate"}
    if not columns.issubset(frame.columns):
        raise TrendSensitivityError(f"Missing annual rate fields: {sorted(columns.difference(frame.columns))}")
    if frame.duplicated(["parent_code", "year"]).any():
        raise TrendSensitivityError("Duplicate zone-year inputs")
    indexed = frame.pivot(index="parent_code", columns="year", values="annual_rate")
    if set(indexed.index) != set(_ZONES) or set(indexed.columns) != set(settings.years):
        raise TrendSensitivityError("Trend sensitivity requires the five ACZs and the complete declared annual calendar")
    rates = indexed.reindex(index=list(_ZONES), columns=settings.years).to_numpy(dtype=float)
    if not np.all(np.isfinite(rates)):
        raise TrendSensitivityError("Complete, finite annual rates are required for each zone")
    positive_rates = rates[(rates > 0).all(axis=-1)]
    if np.any(np.diff(np.sort(positive_rates, axis=-1), axis=-1) == 0):
        raise TrendSensitivityError("Governed trend diagnostics require distinct annual rates within each ACZ")
    if "fixed_burnable_km2" in frame:
        support = frame.groupby("parent_code")["fixed_burnable_km2"].agg(["min", "max"])
        support_values = frame["fixed_burnable_km2"].to_numpy(dtype=float)
        if not np.all(np.isfinite(support_values)) or np.any(support_values <= 0):
            raise TrendSensitivityError("Annual rate support must be positive and finite")
        if not np.allclose(support["min"], support["max"], rtol=1e-12, atol=1e-12):
            raise TrendSensitivityError("The fixed burnable area changed across years")
    for name, expected in (
        ("realised_bandwidth", settings.bandwidth),
        ("variance_floor", settings.variance_floor),
        ("permutation_count", settings.permutation_count),
        ("bh_alpha", settings.bh_alpha),
    ):
        if name in frame and not np.allclose(frame[name], expected, rtol=0, atol=1e-14):
            raise TrendSensitivityError(f"Simulation setting disagrees with the observed trend authority: {name}")
    if "sen_slope" in frame:
        supplied = frame.groupby("parent_code")["sen_slope"].agg(["min", "max"]).reindex(_ZONES)
        if not np.allclose(supplied.to_numpy(), _sen(rates)[:, None], rtol=1e-12, atol=1e-12):
            raise TrendSensitivityError("Supplied Sen slopes disagree with their annual rates")
    return rates


@lru_cache(maxsize=8)
def _sen_pairs(n_years: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    first, last = np.triu_indices(n_years, k=1)
    return first, last, last - first


def _sen(values: np.ndarray) -> np.ndarray:
    first, last, elapsed = _sen_pairs(values.shape[-1])
    pair_slopes = np.subtract(values[..., last], values[..., first])
    pair_slopes /= elapsed
    return np.median(pair_slopes, axis=-1, overwrite_input=True)


def _fit_sen_lines(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    slope = _sen(values)
    time = _centered_time(values.shape[-1])
    center = np.median(values - slope[..., None] * time, axis=-1)
    line = center[..., None] + slope[..., None] * time
    return center, slope, line


def _log_ratios(values: np.ndarray, line: np.ndarray) -> np.ndarray:
    errors = np.log(values / line)
    return errors - np.median(errors, axis=-1, keepdims=True)


def _noise_models(log_ratios: np.ndarray, settings: TrendSensitivitySettings) -> tuple[_Noise, ...]:
    spread = log_ratios.std(axis=-1, ddof=1)
    zones = len(log_ratios)
    empirical_lag = np.array([np.corrcoef(row[:-1], row[1:])[0, 1] for row in log_ratios])
    lag_limit = settings.fitted_lag_limit
    lag = np.clip(np.nan_to_num(empirical_lag) * settings.fitted_lag_shrinkage, -lag_limit, lag_limit)
    residual_correlation = np.atleast_2d(np.corrcoef(log_ratios))
    if not np.all(np.isfinite(residual_correlation)):
        raise TrendSensitivityError("The cross-zone residual correlation is undefined")
    weight = settings.cross_zone_diagonal_weight
    correlation = (1 - weight) * residual_correlation + weight * np.eye(zones)
    return (
        _Noise("fitted_weak_ar1", lag, spread, correlation),
        _Noise("independent_years", np.zeros(zones), spread, correlation),
        _Noise("positive_ar1_stress", np.full(zones, settings.positive_stress_lag), spread, correlation),
        _Noise("negative_ar1_stress", np.full(zones, settings.negative_stress_lag), spread, correlation),
    )


def _held_out_noise_models(fitted: _Noise, settings: TrendSensitivitySettings) -> tuple[_Noise, ...]:
    lag, spread, correlation = fitted.lag1, fitted.log_dispersion, fitted.innovation_correlation
    return (
        _Noise("independent_zones_fitted_ar1", lag, spread, np.eye(len(lag)), independent_zones=True),
        _Noise("held_out_heavy_tail", lag, spread, correlation, "symmetric_tail_stretch", settings.heavy_tail_strength),
        _Noise("held_out_skew", lag, spread, correlation, "positive_half_stretch", settings.skew_strength),
    )


def _stationary_errors(noise: _Noise, n: int, rng: np.random.Generator, n_years: int) -> np.ndarray:
    innovation_scale = np.sqrt(1 - noise.lag1**2)
    zones = len(noise.lag1)
    if noise.independent_zones:
        # Each zone has unit stationary variance. Direct standard-normal draws
        # keep coordinates attached to their zones when fitted lags round.
        errors = rng.standard_normal((n, n_years, zones)) * innovation_scale
        errors[:, 0, :] = rng.standard_normal((n, zones))
    else:
        innovation_covariance = noise.innovation_correlation * np.outer(innovation_scale, innovation_scale)
        stationary_covariance = innovation_covariance / (1 - np.outer(noise.lag1, noise.lag1))
        mean = np.zeros(zones)
        errors = rng.multivariate_normal(mean, innovation_covariance, size=(n, n_years))
        errors[:, 0, :] = rng.multivariate_normal(mean, stationary_covariance, size=n)
    for year in range(1, n_years):
        errors[:, year, :] += errors[:, year - 1, :] * noise.lag1
    strength = noise.strength
    if noise.transform == "symmetric_tail_stretch":
        # For standard Gaussian Z, let H = sign(Z) max(|Z| - 1, 0).
        # Then E[ZH] = 2 P(Z > 1) and E[H²] = 4 P(Z > 1) - 2 phi(1).
        tail = math.erfc(1 / math.sqrt(2)) / 2
        density = math.exp(-0.5) / math.sqrt(2 * math.pi)
        variation = 1 + 4 * strength * tail + strength**2 * (4 * tail - 2 * density)
        errors = (errors + strength * np.sign(errors) * np.maximum(np.abs(errors) - 1, 0)) / math.sqrt(variation)
    elif noise.transform == "positive_half_stretch":
        # Stretch the positive half around the median and normalize variance.
        variation = (1 + (1 + strength)**2) / 2 - strength**2 / (2 * math.pi)
        errors = (errors + strength * np.maximum(errors, 0)) / math.sqrt(variation)
    return errors.transpose(0, 2, 1) * noise.log_dispersion[None, :, None]


def _stationary_indices(
    rng: np.random.Generator, families: int, replicates: int, block_length: int, n_years: int
) -> np.ndarray:
    # The zones share one year-index path per replicate.
    shape = (families, replicates, n_years)
    dtype = np.int16 if n_years < np.iinfo(np.int16).max else np.int32
    starts = rng.integers(n_years, size=shape, dtype=dtype)
    restart = rng.random(shape) < 1 / block_length
    indices = starts.copy()
    for year in range(1, n_years):
        indices[..., year] = np.where(
            restart[..., year], starts[..., year], (indices[..., year - 1] + 1) % n_years
        )
    return indices


def _bootstrap_half_widths(
    values: np.ndarray,
    *,
    replications: int,
    block_length: int,
    interval_level: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    _, slope, line = _fit_sen_lines(values)
    admissible = (line > 0).all(axis=-1)
    safe_line = np.where(admissible[..., None], line, 1.0)
    residuals = _log_ratios(values, safe_line)
    lower_half = np.full(slope.shape, np.nan)
    upper_half = np.full(slope.shape, np.nan)
    tails = ((1.0 - interval_level) / 2.0, (1.0 + interval_level) / 2.0)
    # Restrict the temporary pairwise-slope arrays to a modest memory budget.
    zones, n_years = values.shape[-2:]
    pairs = n_years * (n_years - 1) // 2
    chunk = max(1, min(32, 900_000 // (replications * zones * pairs)))
    for start in range(0, len(values), chunk):
        window = slice(start, min(start + chunk, len(values)))
        indices = _stationary_indices(rng, window.stop - window.start, replications, block_length, n_years)
        residual_draws = np.take_along_axis(residuals[window, None, :, :], indices[:, :, None, :], axis=-1)
        draws = safe_line[window, None, :, :] * np.exp(residual_draws)
        errors = _sen(draws) - slope[window, None, :]
        low, high = np.quantile(errors, tails, axis=1)
        lower_half[window] = np.where(admissible[window], np.maximum(high, 0), np.nan)
        upper_half[window] = np.where(admissible[window], np.maximum(-low, 0), np.nan)
    return slope, lower_half, upper_half, admissible


def _wilson(proportion: np.ndarray | float, n: int) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(proportion, dtype=float)
    inflation = _Z_95**2 / n
    center = (p + inflation / 2) / (1 + inflation)
    delta = _Z_95 * np.sqrt((p * (1 - p) + inflation / 4) / n) / (1 + inflation)
    return np.maximum(0, center - delta), np.minimum(1, center + delta)


def _error_scale(
    estimate: np.ndarray, truth: np.ndarray, low_half: np.ndarray, high_half: np.ndarray, valid: np.ndarray
) -> np.ndarray:
    difference = estimate - truth
    half = np.where(difference >= 0, low_half, high_half)
    ratio = np.divide(np.abs(difference), half, out=np.full_like(estimate, np.inf), where=half > 0)
    return np.where(valid & (difference == 0), 0, ratio)


def _coverage_diagnostics(case, zones, sample, scale, settings) -> list[dict[str, object]]:
    noise, decline, truth, estimate, width, valid, needed = case
    n = len(estimate)
    valid = valid & np.isfinite(scale) & np.isfinite(width) & np.isfinite(estimate)
    covered = valid & (needed <= scale)
    missed = valid & ~covered
    count = covered.sum(axis=0)
    below = (missed & (truth < estimate)).sum(axis=0)
    above = (missed & (truth > estimate)).sum(axis=0)
    lower, upper = _wilson(count / n, n)
    records = []
    for i, zone in enumerate(zones):
        valid_width = width[valid[:, i], i]
        records.append({
            "sample": sample,
            "noise_scenario": noise,
            "decline_fraction_per_decade": decline,
            "parent_code": zone,
            "replicates": n,
            "covered_count": int(count[i]),
            "truth_below_lower_endpoint_count": int(below[i]),
            "truth_above_upper_endpoint_count": int(above[i]),
            "invalid_interval_count": int((~valid[:, i]).sum()),
            "coverage": float(count[i] / n),
            "coverage_lower_95": float(lower[i]),
            "coverage_upper_95": float(upper[i]),
            "coverage_below_review_flag": bool(count[i] / n < settings.coverage_review_flag),
            "nominal_coverage_supported_by_lower_bound": bool(lower[i] >= settings.interval_level),
            "mean_interval_width": float(valid_width.mean() * scale[i]) if len(valid_width) else None,
            "slope_bias": float(estimate[valid[:, i], i].mean() - truth[i]) if len(valid_width) else None,
        })
    return records


def _calibrate_intervals(
    noise_models: tuple[_Noise, ...],
    center: np.ndarray,
    zones: tuple[str, ...],
    settings: TrendSensitivitySettings,
    seed: np.random.SeedSequence,
    independent_seed: np.random.SeedSequence,
) -> tuple[np.ndarray, pd.DataFrame, list[dict[str, object]]]:
    model_seeds = zip(noise_models, seed.spawn(len(noise_models)), independent_seed.spawn(len(noise_models)), strict=True)
    time = _centered_time(len(settings.years))
    calibration_cases = []
    validation_cases = []
    for noise, fit_seed, validation_seed in model_seeds:
        fit_rng, validation_rng = np.random.default_rng(fit_seed), np.random.default_rng(validation_seed)
        fit_errors = np.exp(_stationary_errors(noise, settings.calibration_replicates, fit_rng, len(time)))
        validation_errors = np.exp(_stationary_errors(noise, settings.validation_replicates, validation_rng, len(time)))
        for decline in (0.0, settings.calibration_decline):
            truth = -center * (decline / 10.0)
            line = center[:, None] + truth[:, None] * time
            for errors, rng, destination in (
                (fit_errors, fit_rng, calibration_cases),
                (validation_errors, validation_rng, validation_cases),
            ):
                estimate, low_half, high_half, valid = _bootstrap_half_widths(
                    line * errors,
                    replications=settings.calibration_bootstrap_replicates,
                    block_length=settings.expected_block_length,
                    interval_level=settings.interval_level,
                    rng=rng,
                )
                scale = _error_scale(estimate, truth, low_half, high_half, valid)
                destination.append((noise.name, decline, truth, estimate, low_half + high_half, valid, scale))

    # Use the widest calibration supported across the predeclared cases. An
    # infinite multiplier means that calibration failed, never a valid interval.
    scales = [np.quantile(case[-1], settings.calibration_coverage, axis=0, method="higher") for case in calibration_cases]
    scale = np.maximum(1.0, np.max(scales, axis=0))
    records, diagnostics = [], []
    for sample, cases in (("calibration", calibration_cases), (_INDEPENDENT_SIMULATION, validation_cases)):
        for case in cases:
            noise, decline, truth, estimate, width, valid, needed = case
            diagnostics.extend(_coverage_diagnostics(case, zones, sample, scale, settings))
            n = len(needed)
            covered = (needed <= scale) & np.isfinite(scale)
            rate = covered.mean(axis=0)
            lower, upper = _wilson(rate, n)
            for i, zone in enumerate(zones):
                valid_width = width[valid[:, i], i]
                records.append({
                    "parent_code": zone,
                    "noise_scenario": noise,
                    "decline_fraction_per_decade": decline,
                    "true_slope": truth[i],
                    "sample": sample,
                    "replicates": n,
                    "valid_fit_count": int(valid[:, i].sum()),
                    "uncalibrated_coverage": float((needed[:, i] <= 1).mean()),
                    "calibrated_coverage": rate[i],
                    "coverage_lower_95": lower[i],
                    "coverage_upper_95": upper[i],
                    "coverage_mcse": np.sqrt(rate[i] * (1 - rate[i]) / n),
                    "slope_bias": np.mean(estimate[:, i]) - truth[i],
                    "mean_interval_width": np.mean(valid_width) * scale[i] if len(valid_width) and np.isfinite(scale[i]) else np.nan,
                    "calibration_multiplier": scale[i] if np.isfinite(scale[i]) else np.nan,
                })
    return scale, pd.DataFrame.from_records(records, columns=_CALIBRATION_FIELDS), diagnostics


def _held_out_intervals(noises, center, zones, scale, settings, seed) -> list[dict[str, object]]:
    time = _centered_time(len(settings.years))
    cases = [(noise, decline) for noise in noises for decline in (0.0, settings.calibration_decline)]
    records = []
    for (noise, decline), case_seed in zip(cases, seed.spawn(len(cases)), strict=True):
        error_seed, bootstrap_seed = case_seed.spawn(2)
        errors = np.exp(_stationary_errors(
            noise, settings.held_out_interval_replicates, np.random.default_rng(error_seed), len(time)
        ))
        truth = -center * (decline / 10.0)
        line = center[:, None] + truth[:, None] * time
        estimate, low, high, valid = _bootstrap_half_widths(
            line * errors,
            replications=settings.calibration_bootstrap_replicates,
            block_length=settings.expected_block_length,
            interval_level=settings.interval_level,
            rng=np.random.default_rng(bootstrap_seed),
        )
        needed = _error_scale(estimate, truth, low, high, valid)
        records.extend(_coverage_diagnostics(
            (noise.name, decline, truth, estimate, low + high, valid, needed),
            zones, "held_out_noise_scenario", scale, settings,
        ))
    return records


def _permutation_banks(settings: TrendSensitivitySettings, rng: np.random.Generator) -> np.ndarray:
    banks = []
    n_years = len(settings.years)
    for _ in range(settings.permutation_banks):
        order = np.argsort(rng.random((settings.permutation_count, n_years)), axis=1, kind="stable")
        ranks = order + 1
        _, _, scores = _studentized_global_mk_rank_components(
            ranks,
            bandwidth=settings.bandwidth, variance_floor=settings.variance_floor,
        )
        banks.append(np.sort(np.abs(scores)))
    return np.asarray(banks)


def _rank_statistics(series: np.ndarray, settings: TrendSensitivitySettings) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(series, axis=1, kind="stable")
    ranks = np.argsort(order, axis=1) + 1
    _, variance, signed_t = _studentized_global_mk_rank_components(
        ranks, bandwidth=settings.bandwidth, variance_floor=settings.variance_floor,
    )
    return np.abs(signed_t), variance < settings.variance_floor


def _bank_p_values(values: np.ndarray, banks: np.ndarray, settings: TrendSensitivitySettings) -> tuple[np.ndarray, np.ndarray]:
    """Use independent rank reference draws with chronological observed ranks.

    The reference law is invariant to the observed ranks when there are no
    ties. Its finite draws are separate from the production p-value stream.
    """
    flat = values.reshape(-1, len(settings.years))
    if not np.all(np.isfinite(flat)):
        raise TrendSensitivityError("A simulated series violates the finite-value trend contract")
    all_p = np.empty((len(flat), len(banks)))
    all_floor = np.empty(len(flat), dtype=bool)
    n_draws = banks.shape[1]
    for start in range(0, len(flat), 2000):
        window = slice(start, min(start + 2000, len(flat)))
        series = flat[window]
        if np.any(np.diff(np.sort(series, axis=1), axis=1) == 0):
            raise TrendSensitivityError("A simulated series violates the no-ties trend contract")
        score, floor = _rank_statistics(series, settings)
        for i, bank in enumerate(banks):
            lower = np.searchsorted(bank, score, side="left")
            all_p[window, i] = (n_draws - lower + 1) / (n_draws + 1)
        all_floor[window] = floor
    return all_p.reshape(*values.shape[:-1], len(banks)), all_floor.reshape(values.shape[:-1])


def _bh_rejections(p: np.ndarray, alpha: float) -> np.ndarray:
    families = np.moveaxis(p, 1, -1)
    return np.moveaxis(_bh_adjusted_p_values(families) <= alpha, -1, 1)


def _detectability_case(
    noise: _Noise,
    pattern: str,
    target_zone: str,
    decline: float,
    truth: np.ndarray,
    p_values: np.ndarray,
    floor: np.ndarray,
    settings: TrendSensitivitySettings,
) -> list[dict[str, object]]:
    n = len(p_values)
    rejected = _bh_rejections(p_values, settings.bh_alpha)
    reference = rejected[:, :, 0]
    raw = p_values[:, :, 0] <= settings.bh_alpha
    raw_rate = raw.mean(axis=0)
    raw_low, raw_high = _wilson(raw_rate, n)
    count = reference.sum(axis=1)
    any_rate = np.mean(count > 0)
    any_low, any_high = _wilson(any_rate, n)
    false_count = reference[:, truth == 0].sum(axis=1)
    false_fraction = false_count / np.maximum(count, 1)
    bank_rates = rejected.mean(axis=0)
    main_rate = bank_rates[:, 0]
    low, high = _wilson(main_rate, n)
    bank_lower, _ = _wilson(bank_rates, n)
    return [
        {
            "noise_scenario": noise.name,
            "effect_pattern": pattern,
            "target_zone": target_zone,
            "parent_code": zone,
            "decline_fraction_per_decade": decline,
            "injected_slope": truth[i],
            "replicates": n,
            "raw_rejection_count": int(raw[:, i].sum()),
            "raw_rejection": raw_rate[i],
            "raw_rejection_lower_95": raw_low[i],
            "raw_rejection_upper_95": raw_high[i],
            "bh_rejection_count": int(reference[:, i].sum()),
            "bh_rejection": main_rate[i],
            "bh_rejection_lower_95": low[i],
            "bh_rejection_upper_95": high[i],
            "bh_rejection_mcse": np.sqrt(main_rate[i] * (1 - main_rate[i]) / n),
            "bh_bank_min": min(bank_rates[i]),
            "bh_bank_max": max(bank_rates[i]),
            "bh_bank_lower_95_min": min(bank_lower[i]),
            "family_any_bh_rejection": any_rate,
            "family_any_bh_rejection_lower_95": float(any_low),
            "family_any_bh_rejection_upper_95": float(any_high),
            "family_any_bh_rejection_mcse": np.sqrt(any_rate * (1 - any_rate) / n),
            "family_fdr": false_fraction.mean(),
            "family_fdr_mcse": false_fraction.std(ddof=1) / np.sqrt(n),
            "variance_floor_fraction": floor[:, i].mean(),
        }
        for i, zone in enumerate(_ZONES)
    ]


def _detectability(
    noise_models: tuple[_Noise, ...], center: np.ndarray, settings: TrendSensitivitySettings,
    seed: np.random.SeedSequence, permutation_seed: np.random.SeedSequence
) -> pd.DataFrame:
    banks = _permutation_banks(settings, np.random.default_rng(permutation_seed))
    time = _centered_time(len(settings.years))
    records = []
    for noise, model_seed in zip(noise_models, seed.spawn(len(noise_models)), strict=True):
        noise_factor = np.exp(_stationary_errors(
            noise, settings.detectability_replicates, np.random.default_rng(model_seed), len(time),
        ))
        null_p, null_floor = _bank_p_values(noise_factor * center[:, None], banks, settings)
        zero = np.zeros(len(_ZONES))
        records.extend(_detectability_case(noise, "all_zero", "", 0.0, zero, null_p, null_floor, settings))
        for decline in settings.decline_grid[1:]:
            slopes = -center * (decline / 10.0)
            line = center[:, None] + slopes[:, None] * time
            declining_p, declining_floor = _bank_p_values(noise_factor * line, banks, settings)
            records.extend(_detectability_case(
                noise, "concurrent_decline", "", decline, slopes, declining_p, declining_floor, settings
            ))
            for i, zone in enumerate(_ZONES):
                truth, single_p, single_floor = zero.copy(), null_p.copy(), null_floor.copy()
                truth[i], single_p[:, i, :], single_floor[:, i] = slopes[i], declining_p[:, i, :], declining_floor[:, i]
                records.extend(_detectability_case(
                    noise, "single_zone_decline", zone, decline, truth, single_p, single_floor, settings
                ))
    return pd.DataFrame.from_records(records, columns=_DETECTABILITY_FIELDS)


def _null_confirmation(noises, center, settings, seed) -> list[dict[str, object]]:
    reference_seed, families_seed = seed.spawn(2)
    banks = _permutation_banks(settings, np.random.default_rng(reference_seed))
    records = []
    for noise, noise_seed in zip(noises, families_seed.spawn(len(noises)), strict=True):
        errors = _stationary_errors(
            noise, settings.null_confirmation_replicates, np.random.default_rng(noise_seed), len(settings.years)
        )
        p_values, floor = _bank_p_values(np.exp(errors) * center[:, None], banks, settings)
        rows = _detectability_case(noise, "all_zero", "", 0.0, np.zeros(len(center)), p_values, floor, settings)
        family_fields = [field for field in rows[0] if field.startswith("family_")]
        zone_fields = [field for field in rows[0] if field.startswith(("raw_", "bh_"))]
        any_rates = _bh_rejections(p_values, settings.bh_alpha).any(axis=1).mean(axis=0)
        records.append({
            "noise_scenario": noise.name,
            "replicates": settings.null_confirmation_replicates,
            "family_any_bh_rejection_count": int(round(any_rates[0] * settings.null_confirmation_replicates)),
            **{field: float(rows[0][field]) for field in family_fields},
            "bank_family_any_bh_rejection": any_rates.tolist(),
            "review_flag_exceeded_in_reference_bank": bool(any_rates[0] > settings.null_rejection_review_flag),
            "review_flag_exceeded_in_any_bank": bool(np.any(any_rates > settings.null_rejection_review_flag)),
            "nominal_rejection_exceeded_by_lower_bound": bool(
                rows[0]["family_any_bh_rejection_lower_95"] > settings.bh_alpha
            ),
            "zones": [
                {"parent_code": row["parent_code"], "variance_floor_fraction": float(row["variance_floor_fraction"]),
                 **{field: row[field] for field in zone_fields}}
                for row in rows
            ],
        })
    return records


def _direction_check(noise, center, settings, seed) -> dict[str, object]:
    reference_seed, families_seed = seed.spawn(2)
    banks = _permutation_banks(settings, np.random.default_rng(reference_seed))
    n = settings.null_confirmation_replicates
    time = _centered_time(len(settings.years))
    factor = np.exp(_stationary_errors(noise, n, np.random.default_rng(families_seed), len(time)))
    rates = []
    for sign in (-1, 1):
        slope = sign * center * (settings.calibration_decline / 10.0)
        p_values, _ = _bank_p_values(factor * (center[:, None] + slope[:, None] * time), banks, settings)
        rates.append(_bh_rejections(p_values, settings.bh_alpha)[:, :, 0])
    decline, increase = rates
    difference = increase.astype(float) - decline
    mean = difference.mean(axis=0)
    mcse = difference.std(axis=0, ddof=1) / np.sqrt(n)
    return {
        "noise_scenario": noise.name,
        "absolute_fraction_per_decade": settings.calibration_decline,
        "replicates": n,
        "reported_difference": "paired increase minus decline probability in the reference bank",
        "zones": [
            {
                "parent_code": zone,
                "decline_bh_rejection": float(decline[:, i].mean()),
                "increase_bh_rejection": float(increase[:, i].mean()),
                "difference": float(mean[i]),
                "difference_mcse": float(mcse[i]),
                "difference_lower_95": float(np.clip(mean[i] - _Z_95 * mcse[i], -1, 1)),
                "difference_upper_95": float(np.clip(mean[i] + _Z_95 * mcse[i], -1, 1)),
            }
            for i, zone in enumerate(_ZONES)
        ],
    }


def _confirm_crossings(summary, noises, center, settings, seed) -> list[dict[str, object]]:
    candidates = summary.loc[summary["status"].eq(_CROSSING_CANDIDATE)]
    if candidates.empty:
        return []
    reference_seed, families_seed = seed.spawn(2)
    banks = _permutation_banks(settings, np.random.default_rng(reference_seed))
    time = _centered_time(len(settings.years))
    n = settings.null_confirmation_replicates
    grid = settings.decline_grid
    results = []
    for noise, noise_seed in zip(noises, families_seed.spawn(len(noises)), strict=True):
        cases = candidates.loc[candidates["noise_scenario"].eq(noise.name)]
        if cases.empty:
            continue
        factor = np.exp(_stationary_errors(noise, n, np.random.default_rng(noise_seed), len(time)))
        null_p, _ = _bank_p_values(factor * center[:, None], banks, settings)
        effect_p = {0.0: null_p}
        for case in cases.itertuples():
            index = grid.index(case.sustained_decline_fraction_per_decade)
            zone = _ZONES.index(case.parent_code)
            for decline in grid[index - 1:]:
                if decline not in effect_p:
                    line = center[:, None] * (1 - decline * time / 10)
                    effect_p[decline], _ = _bank_p_values(factor * line, banks, settings)
                p_values = effect_p[decline]
                if case.effect_pattern == "single_zone_decline":
                    p_values = null_p.copy()
                    p_values[:, zone, :] = effect_p[decline][:, zone, :]
                bank_rates = _bh_rejections(p_values, settings.bh_alpha)[:, zone, :].mean(axis=0)
                lower, upper = _wilson(bank_rates, n)
                results.append({
                    "noise_scenario": noise.name,
                    "effect_pattern": case.effect_pattern,
                    "target_zone": case.target_zone,
                    "parent_code": case.parent_code,
                    "replicates": n,
                    "candidate_crossing_fraction": case.sustained_decline_fraction_per_decade,
                    "decline_fraction_per_decade": decline,
                    "injected_slope": float(-center[zone] * (decline / 10.0)),
                    "bank_bh_rejection": bank_rates.tolist(),
                    "bank_wilson_lower_95": lower.tolist(),
                    "bank_wilson_upper_95": upper.tolist(),
                    "target_supported_by_all_bank_lower_bounds": bool(min(lower) >= settings.target_power),
                })
    return results


def _qualify_detectability_crossings(
    summary: pd.DataFrame,
    confirmations: list[dict[str, object]],
    grid: tuple[float, ...],
) -> pd.DataFrame:
    """Require a complete independently supported tail of the screening grid."""
    by_case = {}
    for record in confirmations:
        identity = tuple(record[field] for field in _DETECTABILITY_IDENTIFIERS)
        by_case.setdefault(identity, {})[record["decline_fraction_per_decade"]] = record

    qualified = summary.copy()
    candidates = summary.loc[summary["status"].eq(_CROSSING_CANDIDATE)]
    columns = ["status", "sustained_decline_fraction_per_decade", "sustained_slope"]
    for index, candidate in candidates.iterrows():
        identity = tuple(candidate[field] for field in _DETECTABILITY_IDENTIFIERS)
        study_tail = grid[grid.index(candidate["sustained_decline_fraction_per_decade"]):]
        confirmed = by_case.get(identity, {})
        crossing = None
        for decline in reversed(study_tail):
            if decline not in confirmed or not confirmed[decline]["target_supported_by_all_bank_lower_bounds"]:
                break
            crossing = confirmed[decline]
        qualified.loc[index, columns] = (
            (_UNCONFIRMED_CROSSING, np.nan, np.nan)
            if crossing is None
            else ("ATTAINED_ON_GRID", crossing["decline_fraction_per_decade"], crossing["injected_slope"])
        )
    return qualified


def _summarize_detectability(frame: pd.DataFrame, target: float) -> pd.DataFrame:
    fields = list(_DETECTABILITY_IDENTIFIERS)
    positive_effect = frame.loc[frame["injected_slope"].lt(0)]
    records = []
    for identity, values in positive_effect.groupby(fields, sort=True):
        series = values.sort_values("decline_fraction_per_decade")
        robust = series["bh_bank_lower_95_min"].to_numpy() >= target
        sustained = np.logical_and.accumulate(robust[::-1])[::-1]
        crossing = series.loc[sustained].head(1)
        peak = series.loc[series["bh_rejection"].idxmax()]
        records.append({
            **dict(zip(fields, identity, strict=True)),
            "target_power": target,
            "status": _CROSSING_CANDIDATE if len(crossing) else "NOT_ATTAINED_ON_GRID",
            "sustained_decline_fraction_per_decade": crossing["decline_fraction_per_decade"].iloc[0] if len(crossing) else np.nan,
            "sustained_slope": crossing["injected_slope"].iloc[0] if len(crossing) else np.nan,
            "maximum_tested_decline_fraction_per_decade": series["decline_fraction_per_decade"].iloc[-1],
            "maximum_tested_decline_slope": series["injected_slope"].iloc[-1],
            "peak_bh_detection": peak["bh_rejection"],
            "peak_slope": peak["injected_slope"],
            "estimated_nonmonotone": bool(np.any(np.diff(series["bh_rejection"]) < 0)),
        })
    return pd.DataFrame.from_records(records, columns=_DETECTABILITY_SUMMARY_FIELDS)


def build_trend_sensitivity(
    annual_rates: pd.DataFrame, *, settings: TrendSensitivitySettings | None = None
) -> TrendSensitivityResult:
    """Build uncertainty and detectability from the governed annual rate series.

    ``annual_rates`` accepts the publication-side ``parent_code``, ``year`` and
    ``annual_rate`` fields for the five ACZs over complete consecutive years.
    Interval coverage is pointwise and conditional on the declared simulated
    series. Proportional models require positive rates and fitted paths.
    """
    settings = settings or TrendSensitivitySettings()
    _validate_settings(settings)
    values = _input_rates(annual_rates, settings)
    center, slopes, line = _fit_sen_lines(values)
    availability = np.full(len(_ZONES), "AVAILABLE", dtype=object)
    positive = (values > 0).all(axis=-1)
    admissible_line = (line > 0).all(axis=-1)
    availability[~positive] = "UNAVAILABLE_NONPOSITIVE_RATES"
    availability[positive & ~admissible_line] = "UNAVAILABLE_NONPOSITIVE_FITTED_PATH"
    eligible = np.flatnonzero(positive & admissible_line)
    residuals = _log_ratios(values[eligible], line[eligible])
    dispersed = residuals.std(axis=-1, ddof=1) > 1e-12
    availability[eligible[~dispersed]] = "UNAVAILABLE_DEGENERATE_RESIDUALS"
    active = eligible[dispersed]
    active_zones = tuple(_ZONES[i] for i in active)
    noises = _noise_models(residuals[dispersed], settings) if active_zones else ()
    held_out = _held_out_noise_models(noises[0], settings) if noises else ()
    (interval_seed, calibration_seed, validation_seed, power_seed, permutation_seed,
     stress_seed, null_seed, direction_seed, crossing_seed) = np.random.SeedSequence(settings.seed).spawn(9)
    multiplier = np.full(len(_ZONES), np.nan)
    calibration = pd.DataFrame(columns=_CALIBRATION_FIELDS)
    endpoint_diagnostics, stress_coverage = [], []
    if active_zones:
        scale, calibration, endpoint_diagnostics = _calibrate_intervals(
            noises, center[active], active_zones, settings, calibration_seed, validation_seed,
        )
        multiplier[active] = scale
        stress_coverage = _held_out_intervals(held_out, center[active], active_zones, scale, settings, stress_seed)
    independent = calibration.loc[calibration["sample"].eq(_INDEPENDENT_SIMULATION)]
    minimum_coverage = independent.groupby("parent_code")["calibrated_coverage"].min().reindex(_ZONES).to_numpy()
    minimum_coverage_lower = independent.groupby("parent_code")["coverage_lower_95"].min().reindex(_ZONES).to_numpy()
    interval_records = []
    lengths = (settings.expected_block_length, *settings.sensitivity_block_lengths)
    for length, length_seed in zip(lengths, interval_seed.spawn(len(lengths)), strict=True):
        low_width, high_width = np.full(len(_ZONES), np.nan), np.full(len(_ZONES), np.nan)
        if active_zones:
            _, low, high, _ = _bootstrap_half_widths(
                values[None, active, :],
                replications=settings.interval_bootstrap_replicates,
                block_length=length,
                interval_level=settings.interval_level,
                rng=np.random.default_rng(length_seed),
            )
            low_width[active], high_width[active] = low[0], high[0]
        primary = length == settings.expected_block_length
        factor = np.where(np.isfinite(multiplier), multiplier, np.nan) if primary else np.ones(len(_ZONES))
        for i, zone in enumerate(_ZONES):
            status = availability[i]
            if status == "AVAILABLE" and primary:
                if not np.isfinite(factor[i]):
                    status = "CALIBRATION_FAILED"
                elif minimum_coverage_lower[i] >= settings.interval_level:
                    status = "TARGET_SUPPORTED_ON_INDEPENDENT_SIMULATED_SERIES"
                else:
                    status = "LIMITED_INDEPENDENT_SIMULATION_COVERAGE"
            elif status == "AVAILABLE":
                status = "UNCALIBRATED_BLOCK_LENGTH_SENSITIVITY"
            interval_records.append({
                "parent_code": zone,
                "n_years": len(settings.years),
                "sen_slope": slopes[i],
                "slope_unit": _SLOPE_UNIT,
                "pointwise_interval_level": settings.interval_level,
                "expected_block_length": length,
                "interval_role": "calibrated_primary" if primary else "block_length_sensitivity",
                "bootstrap_replicates": settings.interval_bootstrap_replicates,
                "interval_lower": slopes[i] - low_width[i] * factor[i],
                "interval_upper": slopes[i] + high_width[i] * factor[i],
                "uncalibrated_lower": slopes[i] - low_width[i],
                "uncalibrated_upper": slopes[i] + high_width[i],
                "calibration_multiplier": factor[i] if primary else np.nan,
                "worst_held_out_coverage": minimum_coverage[i] if primary else np.nan,
                "worst_held_out_coverage_lower_95": minimum_coverage_lower[i] if primary else np.nan,
                "status": status,
            })
    all_null, direction, crossings = [], None, []
    if active_zones == _ZONES:
        detectability = _detectability(noises, center, settings, power_seed, permutation_seed)
        detectability_summary = _summarize_detectability(detectability, settings.target_power)
        detectability_status = "AVAILABLE"
        all_null = _null_confirmation((*noises, *held_out), center, settings, null_seed)
        direction = _direction_check(noises[1], center, settings, direction_seed)
        crossings = _confirm_crossings(detectability_summary, noises, center, settings, crossing_seed)
        detectability_summary = _qualify_detectability_crossings(
            detectability_summary, crossings, settings.decline_grid,
        )
    else:
        detectability = pd.DataFrame(columns=_DETECTABILITY_FIELDS)
        detectability_summary = pd.DataFrame.from_records([
            {"parent_code": zone, "noise_scenario": "all_planned_scenarios", "effect_pattern": "declared_five_zone_family",
             "target_zone": "", "target_power": settings.target_power, "status": _INCOMPLETE_FAMILY}
            for zone in _ZONES
        ], columns=_DETECTABILITY_SUMMARY_FIELDS)
        detectability_status = _INCOMPLETE_FAMILY
    metadata = asdict(settings)
    metadata["slope_unit"] = _SLOPE_UNIT
    metadata["interval_method"] = "calibrated_pointwise_sen_stationary_block_bootstrap_log_ratio_residuals"
    metadata["detectability_method"] = "studentized_global_mann_kendall_rank_permutation_five_zone_bh"
    metadata["detectability_reference_stream"] = "independent_sorted_production_reference_rank_banks"
    metadata["detectability_decision_arithmetic"] = {
        "observed": "production_integer_rank_studentization",
        "reference": "production_integer_rank_studentization",
        "extreme_counts": "inclusive_absolute_scores",
        "bh": "production_adjusted_p_less_than_or_equal_to_alpha",
    }
    metadata["detectability_status"] = detectability_status
    metadata["simulation_zone_order"] = list(active_zones)
    metadata["zone_availability"] = dict(zip(_ZONES, availability.tolist(), strict=True))
    metadata["zone_order"] = list(_ZONES)
    metadata["years"] = list(settings.years)
    metadata["central_rates"] = dict(zip(_ZONES, center.tolist(), strict=True))
    metadata["interval_calibration_scope"] = {
        "sample_label": _INDEPENDENT_SIMULATION,
        "sample_basis": "independent random draws from the same fitted or declared noise and effect settings",
        "coverage_fields": (
            "S13 worst_held_out_coverage and worst_held_out_coverage_lower_95 are the minima in independently "
            "seeded repeats of the calibration scenarios. S17 reports the distinct held-out noise mechanisms."
        ),
        "bootstrap_scope": "calibration uses the declared proxy count; the observed intervals use the final count",
        "uncertainty_scope": "conditional pointwise coverage, with no simultaneous or uniform coverage guarantee",
    }
    metadata["interval_coverage_qualification"] = {
        "status": "AVAILABLE" if active_zones else "UNAVAILABLE_NO_ADMISSIBLE_ZONE",
        "scope": "conditional pointwise stress of the fixed multiplier from the Gaussian calibration settings",
        "bootstrap_replicates": settings.calibration_bootstrap_replicates,
        "total_family_denominator_includes_invalid_intervals": True,
        "coverage_review_flag": settings.coverage_review_flag,
        "held_out_seed_spawn_key": list(stress_seed.spawn_key),
        "directional_endpoint_diagnostics": endpoint_diagnostics,
        "held_out_noise_scenarios": stress_coverage,
    }
    metadata["detectability_scope"] = {
        "all_zero_fields": "family_any_bh_rejection and family_fdr diagnose the simulated all-zero rejection rate",
        "noise_scope": "S15 and S16 use the four Gaussian log-error scenarios over the full effect grid",
        "held_out_noise_scope": "additional independent-zone, heavy-tailed and right-skewed checks cover null rejection and interval coverage",
        "bank_uncertainty_scope": (
            "S15 Wilson intervals condition on the reference bank. The bank minimum and maximum show variation "
            "across the finite reference banks."
        ),
        "uncertainty_scope": "rejection and target attainment are conditional on these scenarios and the tested decline grid",
        "all_zero_point_estimate_diagnostic_flag": settings.null_rejection_review_flag,
        "scenarios_above_all_zero_diagnostic_flag": sorted(detectability.loc[
            detectability["effect_pattern"].eq("all_zero")
            & detectability["family_any_bh_rejection"].gt(settings.null_rejection_review_flag), "noise_scenario",
        ].unique()),
    }
    metadata["detectability_qualification"] = {
        "status": detectability_status,
        "scope": "independent simulated families conditional on a separate finite permutation reference stream",
        "null_confirmation_seed_spawn_key": list(null_seed.spawn_key),
        "all_null_confirmation": all_null,
        "direction_check_seed_spawn_key": list(direction_seed.spawn_key),
        "direction_check": direction,
        "target_crossing_seed_spawn_key": list(crossing_seed.spawn_key),
        "target_crossing_rule": (
            "S16 requires every point from the final crossing to the largest tested effect to meet the target "
            "using the smallest bank-wise Wilson lower bound in both the screen and independent confirmation."
        ),
        "target_crossing_confirmation": "AVAILABLE" if crossings else (
            "NOT_TRIGGERED_NO_SUSTAINED_CROSSING" if detectability_status == "AVAILABLE" else _INCOMPLETE_FAMILY
        ),
        "target_crossing_diagnostics": crossings,
    }
    metadata["noise_scenarios"] = {
        noise.name: {"lag1": noise.lag1.tolist(), "log_dispersion": noise.log_dispersion.tolist(),
                     "innovation_correlation": noise.innovation_correlation.tolist()}
        for noise in noises
    }
    metadata["held_out_noise_models"] = {
        noise.name: {
            "latent_lag1": noise.lag1.tolist(),
            "latent_innovation_correlation": noise.innovation_correlation.tolist(),
            "marginal_log_dispersion": noise.log_dispersion.tolist(),
            "median_centered_marginal_transform": noise.transform,
            "transform_strength": noise.strength,
        }
        for noise in held_out
    }
    return TrendSensitivityResult(
        pd.DataFrame.from_records(interval_records), calibration, detectability,
        detectability_summary, metadata,
    )
