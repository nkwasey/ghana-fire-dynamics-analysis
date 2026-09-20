"""Reusable QA metric and threshold helpers for Stage 1.

The current runtime still performs only the existing validators and report
writing. This module provides a reusable, deterministic place for callers
to compute QA summaries and evaluate them against explicit config thresholds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import mean


class QAMetricsError(RuntimeError):
    """Raised when QA metrics or threshold evaluation cannot be computed."""


@dataclass(frozen=True)
class ThresholdSpec:
    """Generic threshold specification.

    Use either the ``*_below`` fields for lower-bound metrics or the
    ``*_above`` fields for upper-bound metrics.
    """

    warn_below: float | None = None
    fail_below: float | None = None
    warn_above: float | None = None
    fail_above: float | None = None


@dataclass(frozen=True)
class MetricResult:
    """Single metric value and status."""

    name: str
    value: float | None
    status: str
    detail: str


@dataclass(frozen=True)
class NumericSummary:
    """Audit-friendly summary of a numeric vector."""

    count: int
    min_value: float | None
    mean_value: float | None
    max_value: float | None


@dataclass(frozen=True)
class ShareMetricSummary:
    """Specialised summary for [0, 1] share values."""

    count: int
    min_share: float | None
    mean_share: float | None
    max_share: float | None
    warn_count: int
    fail_count: int


@dataclass(frozen=True)
class AreaDifferenceSummary:
    """Summary for a sequence of relative area differences."""

    count: int
    max_abs_rel_diff: float | None
    mean_abs_rel_diff: float | None
    warn_count: int
    fail_count: int


def _coerce_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception as e:
        raise QAMetricsError(f"Value is not numeric: {value!r}: {e}") from e
    return out


def _clean_numeric_iter(values: Iterable[object]) -> list[float]:
    out: list[float] = []
    for v in values:
        vv = _coerce_optional_float(v)
        if vv is None:
            continue
        out.append(vv)
    return out


def _validate_status(status: str) -> str:
    allowed = {"pass", "warn", "fail", "na"}
    if status not in allowed:
        raise QAMetricsError(f"Invalid QA status: {status}")
    return status


def evaluate_threshold(value: object, *, spec: ThresholdSpec) -> MetricResult:
    """Evaluate a single numeric value against a threshold specification."""

    v = _coerce_optional_float(value)
    if v is None:
        return MetricResult(name="metric", value=None, status="na", detail="value is null")

    # Lower-bound logic
    if spec.warn_below is not None or spec.fail_below is not None:
        warn_below = float(spec.warn_below if spec.warn_below is not None else float("-inf"))
        fail_below = float(spec.fail_below if spec.fail_below is not None else float("-inf"))
        if fail_below > warn_below:
            raise QAMetricsError("fail_below must be <= warn_below")
        if v < fail_below:
            return MetricResult(
                name="metric", value=v, status="fail", detail=f"value < {fail_below}"
            )
        if v < warn_below:
            return MetricResult(
                name="metric", value=v, status="warn", detail=f"value < {warn_below}"
            )
        return MetricResult(
            name="metric", value=v, status="pass", detail="within lower-bound tolerance"
        )

    # Upper-bound logic
    if spec.warn_above is not None or spec.fail_above is not None:
        warn_above = float(spec.warn_above if spec.warn_above is not None else float("inf"))
        fail_above = float(spec.fail_above if spec.fail_above is not None else float("inf"))
        if fail_above < warn_above:
            raise QAMetricsError("fail_above must be >= warn_above")
        if v > fail_above:
            return MetricResult(
                name="metric", value=v, status="fail", detail=f"value > {fail_above}"
            )
        if v > warn_above:
            return MetricResult(
                name="metric", value=v, status="warn", detail=f"value > {warn_above}"
            )
        return MetricResult(
            name="metric", value=v, status="pass", detail="within upper-bound tolerance"
        )

    raise QAMetricsError("ThresholdSpec must define either lower-bound or upper-bound thresholds")


def numeric_summary(values: Iterable[object]) -> NumericSummary:
    vals = _clean_numeric_iter(values)
    if not vals:
        return NumericSummary(count=0, min_value=None, mean_value=None, max_value=None)
    return NumericSummary(
        count=len(vals),
        min_value=min(vals),
        mean_value=mean(vals),
        max_value=max(vals),
    )


def share_metric_summary(
    shares: Iterable[object],
    *,
    warn_below: float,
    fail_below: float,
) -> ShareMetricSummary:
    """Summarise overlap-share style metrics that should lie in [0, 1]."""

    if not (0 <= fail_below <= warn_below <= 1):
        raise QAMetricsError("Expected 0 <= fail_below <= warn_below <= 1")

    vals = _clean_numeric_iter(shares)
    for v in vals:
        if v < 0 or v > 1:
            raise QAMetricsError(f"Share value outside [0, 1]: {v}")

    if not vals:
        return ShareMetricSummary(
            count=0,
            min_share=None,
            mean_share=None,
            max_share=None,
            warn_count=0,
            fail_count=0,
        )

    warn_count = sum(1 for v in vals if fail_below <= v < warn_below)
    fail_count = sum(1 for v in vals if v < fail_below)
    return ShareMetricSummary(
        count=len(vals),
        min_share=min(vals),
        mean_share=mean(vals),
        max_share=max(vals),
        warn_count=warn_count,
        fail_count=fail_count,
    )


def area_difference_summary(
    rel_diffs: Iterable[object],
    *,
    warn_above: float,
    fail_above: float,
) -> AreaDifferenceSummary:
    """Summarise absolute relative area-difference metrics."""

    if warn_above < 0 or fail_above < 0 or fail_above < warn_above:
        raise QAMetricsError("Expected 0 <= warn_above <= fail_above")

    vals = [abs(v) for v in _clean_numeric_iter(rel_diffs)]
    if not vals:
        return AreaDifferenceSummary(
            count=0,
            max_abs_rel_diff=None,
            mean_abs_rel_diff=None,
            warn_count=0,
            fail_count=0,
        )

    warn_count = sum(1 for v in vals if warn_above < v <= fail_above)
    fail_count = sum(1 for v in vals if v > fail_above)
    return AreaDifferenceSummary(
        count=len(vals),
        max_abs_rel_diff=max(vals),
        mean_abs_rel_diff=mean(vals),
        warn_count=warn_count,
        fail_count=fail_count,
    )


def count_exceedance_summary(
    *,
    count: object,
    warn_above: int,
    fail_above: int,
    name: str,
) -> MetricResult:
    """Evaluate a count metric against upper-bound thresholds."""

    if warn_above < 0 or fail_above < 0 or fail_above < warn_above:
        raise QAMetricsError("Expected 0 <= warn_above <= fail_above")

    v = _coerce_optional_float(count)
    if v is None:
        return MetricResult(name=name, value=None, status="na", detail="count is null")

    result = evaluate_threshold(
        v, spec=ThresholdSpec(warn_above=float(warn_above), fail_above=float(fail_above))
    )
    return MetricResult(
        name=name, value=result.value, status=_validate_status(result.status), detail=result.detail
    )


def threshold_spec_from_mapping(mapping: Mapping[str, object]) -> ThresholdSpec:
    """Construct a ThresholdSpec from a mapping-like object.

    This is convenient for callers that pass Pydantic model dumps or
    JSON sidecar content into the same evaluation functions.
    """

    return ThresholdSpec(
        warn_below=_coerce_optional_float(mapping.get("warn_below")),
        fail_below=_coerce_optional_float(mapping.get("fail_below")),
        warn_above=_coerce_optional_float(mapping.get("warn_above")),
        fail_above=_coerce_optional_float(mapping.get("fail_above")),
    )
