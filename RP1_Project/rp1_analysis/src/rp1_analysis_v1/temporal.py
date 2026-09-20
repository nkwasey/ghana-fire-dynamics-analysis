"""Deterministic temporal semantics for Ghana Fire RP1 Analysis v1.

This module provides generic calendar helpers only.  It does not implement any
research-question-specific inference.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd


class TemporalContractError(ValueError):
    """Raised when a temporal input violates the governed calendar contract."""


@dataclass(frozen=True, order=True, slots=True)
class YearMonth:
    """Validated Gregorian year-month value."""

    year: int
    month: int

    def __post_init__(self) -> None:
        if not isinstance(self.year, int) or isinstance(self.year, bool):
            raise TemporalContractError("year must be an integer")
        if not isinstance(self.month, int) or isinstance(self.month, bool):
            raise TemporalContractError("month must be an integer")
        if self.year < 1 or self.year > 9999:
            raise TemporalContractError(f"invalid Gregorian year: {self.year!r}")
        if self.month < 1 or self.month > 12:
            raise TemporalContractError(f"invalid Gregorian month: {self.month!r}")

    @property
    def yyyymm(self) -> int:
        return self.year * 100 + self.month

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def ordinal(self) -> int:
        """Return a zero-based absolute month ordinal on the proleptic calendar."""

        return self.year * 12 + (self.month - 1)

    def add_months(self, offset: int) -> YearMonth:
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise TemporalContractError("month offset must be an integer")
        ordinal = self.ordinal + offset
        if ordinal < 12:
            raise TemporalContractError("month offset precedes Gregorian year 1")
        year, month0 = divmod(ordinal, 12)
        return YearMonth(year, month0 + 1)


def parse_yyyymm(value: int | str | YearMonth) -> YearMonth:
    """Parse ``YYYYMM`` or ``YYYY-MM`` without coercing malformed values."""

    if isinstance(value, YearMonth):
        return value
    if isinstance(value, bool):
        raise TemporalContractError("yyyymm must not be boolean")
    if isinstance(value, int):
        year, month = divmod(value, 100)
        return YearMonth(year, month)
    if not isinstance(value, str):
        raise TemporalContractError(f"yyyymm must be int or str, got {type(value).__name__}")
    text = value.strip()
    if len(text) == 6 and text.isdigit():
        return YearMonth(int(text[:4]), int(text[4:]))
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
        return YearMonth(int(text[:4]), int(text[5:]))
    raise TemporalContractError(f"invalid yyyymm representation: {value!r}")


def yyyymm_to_year_month(value: int | str | YearMonth) -> tuple[int, int]:
    ym = parse_yyyymm(value)
    return ym.year, ym.month


def month_ordinal(value: int | str | YearMonth) -> int:
    return parse_yyyymm(value).ordinal


def month_range(start: int | str | YearMonth, end: int | str | YearMonth) -> tuple[YearMonth, ...]:
    first = parse_yyyymm(start)
    last = parse_yyyymm(end)
    if last < first:
        raise TemporalContractError(f"temporal end {last.label} precedes start {first.label}")
    return tuple(first.add_months(i) for i in range(last.ordinal - first.ordinal + 1))


def validate_month_sequence(
    values: Iterable[int | str | YearMonth],
    *,
    require_sorted: bool = True,
    require_complete: bool = True,
    expected_start: int | str | YearMonth | None = None,
    expected_end: int | str | YearMonth | None = None,
) -> tuple[YearMonth, ...]:
    """Validate uniqueness, ordering, contiguity and optional exact endpoints."""

    parsed = tuple(parse_yyyymm(v) for v in values)
    if not parsed:
        raise TemporalContractError("month sequence is empty")
    if len(set(parsed)) != len(parsed):
        raise TemporalContractError("month sequence contains duplicate months")
    if require_sorted and any(a >= b for a, b in zip(parsed, parsed[1:], strict=False)):
        raise TemporalContractError("month sequence is not strictly chronological")
    ordered = parsed if require_sorted else tuple(sorted(parsed))
    if require_complete:
        expected = month_range(ordered[0], ordered[-1])
        if ordered != expected:
            missing = sorted(set(expected).difference(ordered))
            labels = ", ".join(x.label for x in missing[:8])
            suffix = "..." if len(missing) > 8 else ""
            raise TemporalContractError(f"incomplete monthly spine; missing: {labels}{suffix}")
    if expected_start is not None and ordered[0] != parse_yyyymm(expected_start):
        raise TemporalContractError(
            f"unexpected temporal start {ordered[0].label}; expected {parse_yyyymm(expected_start).label}"
        )
    if expected_end is not None and ordered[-1] != parse_yyyymm(expected_end):
        raise TemporalContractError(
            f"unexpected temporal end {ordered[-1].label}; expected {parse_yyyymm(expected_end).label}"
        )
    return ordered


def add_year_month_columns(
    frame: pd.DataFrame,
    *,
    yyyymm_col: str = "yyyymm",
    year_col: str = "year",
    month_col: str = "month",
    ordinal_col: str = "month_ordinal",
) -> pd.DataFrame:
    """Return a copy with deterministic calendar columns validated from ``yyyymm``."""

    if yyyymm_col not in frame.columns:
        raise TemporalContractError(f"missing temporal key column: {yyyymm_col}")
    out = frame.copy()
    parsed = [parse_yyyymm(v) for v in out[yyyymm_col].tolist()]
    years = np.fromiter((x.year for x in parsed), dtype=np.int64, count=len(parsed))
    months = np.fromiter((x.month for x in parsed), dtype=np.int64, count=len(parsed))
    ordinals = np.fromiter((x.ordinal for x in parsed), dtype=np.int64, count=len(parsed))
    for target, values in ((year_col, years), (month_col, months), (ordinal_col, ordinals)):
        if target in out.columns:
            existing = pd.to_numeric(out[target], errors="coerce").to_numpy()
            if (
                len(existing) != len(values)
                or np.any(~np.isfinite(existing))
                or not np.array_equal(existing.astype(np.int64), values)
            ):
                raise TemporalContractError(f"existing {target} conflicts with {yyyymm_col}")
        else:
            out[target] = values
    return out


def assert_complete_temporal_spine(
    frame: pd.DataFrame,
    *,
    unit_col: str,
    yyyymm_col: str = "yyyymm",
    start: int | str | YearMonth,
    end: int | str | YearMonth,
) -> None:
    """Require every governed unit to have exactly one row for every expected month."""

    if unit_col not in frame.columns or yyyymm_col not in frame.columns:
        raise TemporalContractError(f"required columns missing: {unit_col}, {yyyymm_col}")
    if frame[[unit_col, yyyymm_col]].isna().any().any():
        raise TemporalContractError("temporal spine keys contain missing values")
    if frame.duplicated([unit_col, yyyymm_col]).any():
        raise TemporalContractError("temporal spine contains duplicate unit-month keys")
    expected = tuple(x.yyyymm for x in month_range(start, end))
    expected_set = set(expected)
    errors: list[str] = []
    for unit, group in frame.groupby(unit_col, sort=True, dropna=False):
        observed = tuple(parse_yyyymm(v).yyyymm for v in group[yyyymm_col].tolist())
        observed_set = set(observed)
        if observed_set != expected_set:
            missing = sorted(expected_set - observed_set)
            extra = sorted(observed_set - expected_set)
            errors.append(f"{unit}: missing={missing[:6]!r}, extra={extra[:6]!r}")
            continue
        ordered = tuple(sorted(observed))
        if ordered != expected:
            errors.append(f"{unit}: incomplete or non-canonical monthly spine")
    if errors:
        raise TemporalContractError("incomplete temporal spine: " + "; ".join(errors[:8]))


def construct_grouped_annual_series(
    frame: pd.DataFrame,
    *,
    value_col: str,
    group_cols: Sequence[str],
    yyyymm_col: str = "yyyymm",
    support_col: str | None = None,
    aggregation: str = "sum",
    require_complete_years: bool = True,
) -> pd.DataFrame:
    """Construct annual values while preserving source support explicitly.

    If ``support_col`` is supplied, annual values are emitted only when all 12
    months are source-supported.  Unsupported years retain a row with ``value``
    set to NaN and ``annual_supported`` false; they are never silently treated as
    zero.  A complete-year requirement applies to the calendar spine, not to fire
    occurrence.
    """

    if aggregation not in {"sum", "mean"}:
        raise TemporalContractError("aggregation must be 'sum' or 'mean'")
    required = set(group_cols) | {value_col, yyyymm_col}
    if support_col is not None:
        required.add(support_col)
    missing = required.difference(frame.columns)
    if missing:
        raise TemporalContractError(f"missing annualisation columns: {sorted(missing)!r}")
    if not group_cols:
        raise TemporalContractError("group_cols must not be empty")

    prepared = add_year_month_columns(frame, yyyymm_col=yyyymm_col)
    numeric = pd.to_numeric(prepared[value_col], errors="coerce")
    if prepared[value_col].notna().sum() != numeric.notna().sum():
        raise TemporalContractError(f"{value_col} contains non-numeric values")
    prepared = prepared.copy()
    prepared[value_col] = numeric.astype(float)

    if support_col is not None:
        support = pd.to_numeric(prepared[support_col], errors="coerce")
        if support.isna().any() or not set(support.unique()).issubset({0, 1}):
            raise TemporalContractError(f"{support_col} must contain only 0/1 support flags")
        prepared[support_col] = support.astype(np.int8)
        invalid_supported = prepared[support_col].eq(1) & prepared[value_col].isna()
        invalid_unsupported = prepared[support_col].eq(0) & prepared[value_col].notna()
        if invalid_supported.any():
            raise TemporalContractError(f"{value_col} is missing in source-supported months")
        if invalid_unsupported.any():
            raise TemporalContractError(f"{value_col} is observed in source-unsupported months")
    elif prepared[value_col].isna().any():
        raise TemporalContractError(
            f"{value_col} contains missing values without an explicit support flag"
        )

    keys = [*group_cols, "year"]
    rows: list[dict[str, object]] = []
    for key, group in prepared.groupby(keys, sort=True, dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        months = sorted(group["month"].astype(int).tolist())
        if len(months) != len(set(months)):
            raise TemporalContractError(f"duplicate monthly rows within annual group {key_tuple!r}")
        complete = months == list(range(1, 13))
        if require_complete_years and not complete:
            raise TemporalContractError(
                f"incomplete calendar year for group {key_tuple!r}: months={months!r}"
            )
        supported_months = len(group) if support_col is None else int(group[support_col].sum())
        annual_supported = complete and supported_months == 12
        if annual_supported:
            values = group[value_col].to_numpy(dtype=float)
            annual_value = float(np.sum(values) if aggregation == "sum" else np.mean(values))
        else:
            annual_value = float("nan")
        row = {column: value for column, value in zip(keys, key_tuple, strict=True)}
        row.update(
            {
                value_col: annual_value,
                "n_months": int(len(group)),
                "supported_months": int(supported_months),
                "complete_year": bool(complete),
                "annual_supported": bool(annual_supported),
            }
        )
        rows.append(row)
    columns = [
        *keys,
        value_col,
        "n_months",
        "supported_months",
        "complete_year",
        "annual_supported",
    ]
    return pd.DataFrame(rows, columns=columns)
