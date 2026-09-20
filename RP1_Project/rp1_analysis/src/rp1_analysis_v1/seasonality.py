"""Circular month-of-year and seasonality utilities for RP1 Analysis v1.

The RQ1 authority treats calendar month as circular.  December and January are
adjacent, so timing summaries are based on the circular mean direction and mean
resultant length rather than on linear month arithmetic.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np


class SeasonalityError(ValueError):
    """Raised when a seasonal summary cannot be constructed defensibly."""


def _validate_month(month: int) -> int:
    if not isinstance(month, (int, np.integer)) or isinstance(month, bool):
        raise SeasonalityError(f"month must be an integer in 1..12; got {month!r}")
    value = int(month)
    if value < 1 or value > 12:
        raise SeasonalityError(f"month must be in 1..12; got {month!r}")
    return value


def month_angle(month: int) -> float:
    """Return the governed month angle ``theta_m = 2*pi*(m-1)/12``."""

    m = _validate_month(month)
    return 2.0 * math.pi * (m - 1) / 12.0


def circular_month_distance(month1: int, month2: int) -> int:
    """Return the shortest integer month distance on the annual cycle."""

    m1 = _validate_month(month1)
    m2 = _validate_month(month2)
    delta = abs(m1 - m2)
    return min(delta, 12 - delta)


def _as_finite_1d(values: Iterable[float], *, name: str) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    if arr.ndim != 1:
        raise SeasonalityError(f"{name} must be one-dimensional")
    if arr.size == 0:
        raise SeasonalityError(f"{name} must not be empty")
    if not np.isfinite(arr).all():
        raise SeasonalityError(f"{name} contains missing or non-finite values")
    return arr


def monthly_climatology(values: Iterable[float], months: Iterable[int]) -> tuple[float, ...]:
    """Return the arithmetic mean for each calendar month, January through December.

    Every month must be represented. Missing values are rejected rather than silently
    removed because support decisions belong to the governed data-contract layer.
    """

    data = _as_finite_1d(values, name="values")
    month_values = np.asarray([_validate_month(m) for m in months], dtype=np.int64)
    if month_values.ndim != 1 or len(month_values) != len(data):
        raise SeasonalityError("months and values must be one-dimensional with equal length")
    result: list[float] = []
    for month in range(1, 13):
        selected = data[month_values == month]
        if selected.size == 0:
            raise SeasonalityError(f"monthly climatology is missing calendar month {month}")
        result.append(float(np.mean(selected)))
    return tuple(result)


def monthly_shares(climatology: Sequence[float]) -> tuple[float, ...] | None:
    """Convert 12 non-negative climatological values to annual contribution shares.

    An all-zero climatology is scientifically undefined for circular timing and returns
    ``None``.  No equal-share or zero-vector replacement is invented.
    """

    values = _as_finite_1d(climatology, name="climatology")
    if values.size != 12:
        raise SeasonalityError("climatology must contain exactly 12 monthly values")
    if np.any(values < 0):
        raise SeasonalityError("climatology must be non-negative for contribution shares")
    total = float(np.sum(values))
    if total == 0.0:
        return None
    shares = values / total
    return tuple(float(x) for x in shares)


def peak_month(climatology: Sequence[float]) -> int | None:
    """Return the earliest month attaining the maximum, or ``None`` for all-zero input.

    This is a descriptive display statistic only; RQ1 timing authority is circular.
    """

    values = _as_finite_1d(climatology, name="climatology")
    if values.size != 12:
        raise SeasonalityError("climatology must contain exactly 12 monthly values")
    if np.any(values < 0):
        raise SeasonalityError("climatology must be non-negative")
    if float(np.sum(values)) == 0.0:
        return None
    return int(np.argmax(values)) + 1


@dataclass(frozen=True, slots=True)
class CircularStatisticsResult:
    mean_direction_radians: float | None
    mean_month: float | None
    resultant_length: float | None
    status: str


def circular_mean_resultant(shares: Sequence[float] | None) -> CircularStatisticsResult:
    """Return circular mean direction/month and mean resultant length.

    ``shares`` must contain 12 non-negative values summing to one.  ``None`` is the
    explicit fail-closed representation of a zero-total annual distribution.  A
    perfectly balanced circular vector has a defined resultant length of zero but no
    scientifically defined mean direction/month.
    """

    if shares is None:
        return CircularStatisticsResult(None, None, None, "undefined_zero_total")
    p = _as_finite_1d(shares, name="monthly shares")
    if p.size != 12:
        raise SeasonalityError("monthly shares must contain exactly 12 values")
    if np.any(p < 0):
        raise SeasonalityError("monthly shares must be non-negative")
    total = float(np.sum(p))
    if not math.isclose(total, 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise SeasonalityError(f"monthly shares must sum to 1; got {total!r}")
    angles = np.asarray([month_angle(m) for m in range(1, 13)], dtype=float)
    c = float(np.sum(p * np.cos(angles)))
    s = float(np.sum(p * np.sin(angles)))
    r = min(1.0, max(0.0, math.hypot(c, s)))
    if r <= 1e-15:
        return CircularStatisticsResult(None, None, r, "undefined_mean_direction")
    angle = math.atan2(s, c) % (2.0 * math.pi)
    mean_month = 1.0 + 12.0 * angle / (2.0 * math.pi)
    if mean_month > 12.0:
        mean_month -= 12.0
    return CircularStatisticsResult(float(angle), float(mean_month), float(r), "ok")


def circular_mean_direction(shares: Sequence[float] | None) -> float | None:
    """Return the governed circular mean direction in radians, or ``None`` if undefined."""

    return circular_mean_resultant(shares).mean_direction_radians


def circular_mean_month(shares: Sequence[float] | None) -> float | None:
    """Return the governed continuous circular mean month on the annual cycle.

    The publication coordinate is cyclic: the December/January boundary is represented
    continuously with ``0 ≡ 12``. The value is ``None`` for a zero-total or
    zero-resultant distribution; no linear month average is substituted.
    """

    return circular_mean_resultant(shares).mean_month


def mean_resultant_length(shares: Sequence[float] | None) -> float | None:
    """Return circular mean resultant length on ``[0, 1]``, or ``None`` for zero total."""

    return circular_mean_resultant(shares).resultant_length



@dataclass(frozen=True, slots=True)
class SeasonalitySummary:
    monthly_climatology: tuple[float, ...]
    monthly_shares: tuple[float, ...] | None
    peak_month: int | None
    circular_mean_direction_radians: float | None
    circular_mean_month: float | None
    mean_resultant_length: float | None
    total_climatology: float
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "monthly_climatology": list(self.monthly_climatology),
            "monthly_shares": None if self.monthly_shares is None else list(self.monthly_shares),
            "peak_month": self.peak_month,
            "circular_mean_direction_radians": self.circular_mean_direction_radians,
            "circular_mean_month": self.circular_mean_month,
            "mean_resultant_length": self.mean_resultant_length,
            "total_climatology": self.total_climatology,
            "status": self.status,
        }


def summarise_seasonality(values: Iterable[float], months: Iterable[int]) -> SeasonalitySummary:
    """Build one fail-closed 12-month seasonality authority."""

    climatology = monthly_climatology(values, months)
    shares = monthly_shares(climatology)
    total = float(sum(climatology))
    if shares is None:
        return SeasonalitySummary(
            monthly_climatology=climatology,
            monthly_shares=None,
            peak_month=None,
            circular_mean_direction_radians=None,
            circular_mean_month=None,
            mean_resultant_length=None,
            total_climatology=total,
            status="zero_total",
        )
    circular = circular_mean_resultant(shares)
    status = "ok" if circular.status == "ok" else circular.status
    return SeasonalitySummary(
        monthly_climatology=climatology,
        monthly_shares=shares,
        peak_month=peak_month(climatology),
        circular_mean_direction_radians=circular.mean_direction_radians,
        circular_mean_month=circular.mean_month,
        mean_resultant_length=circular.resultant_length,
        total_climatology=total,
        status=status,
    )
