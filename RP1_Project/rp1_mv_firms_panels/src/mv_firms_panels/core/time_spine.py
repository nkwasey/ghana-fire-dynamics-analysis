# file: src/mv_firms_panels/core/time_spine.py
"""Deterministic time helpers (UTC month boundaries) and monthly time spine.

Binding requirements
------------------------------
- Deterministic yyyymm derivation from acq_date.
- Month boundaries are UTC (per configs/example_project.yaml).
- Helpers must operate on pandas objects for unit tests.

Definitions
-----------
- yyyymm is an integer YYYYMM (e.g., 201401).
- acq_date is expected to be parseable as YYYY-MM-DD (string/date-like).
- acq_time is FIRMS HHMM (string/int convertible), interpreted in UTC.

Notes
-----
This module intentionally does not infer time ranges from files; that belongs to
pipeline orchestration stages.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd


def validate_yyyymm(yyyymm: int) -> None:
    """Validate yyyymm integer format."""
    if not isinstance(yyyymm, int):
        raise TypeError("yyyymm must be int")
    if yyyymm < 190001 or yyyymm > 220012:
        raise ValueError("yyyymm outside expected range (190001..220012)")
    mm = yyyymm % 100
    if mm < 1 or mm > 12:
        raise ValueError("yyyymm month must be 01..12")


def _next_month(yyyymm: int) -> int:
    validate_yyyymm(yyyymm)
    y = yyyymm // 100
    m = yyyymm % 100
    if m == 12:
        return (y + 1) * 100 + 1
    return y * 100 + (m + 1)


def iter_months_inclusive(start_yyyymm: int, end_yyyymm: int) -> Iterator[int]:
    """Yield yyyymm values from start to end inclusive."""
    validate_yyyymm(start_yyyymm)
    validate_yyyymm(end_yyyymm)
    if start_yyyymm > end_yyyymm:
        raise ValueError("start_yyyymm must be <= end_yyyymm")

    cur = start_yyyymm
    while True:
        yield cur
        if cur == end_yyyymm:
            break
        cur = _next_month(cur)


def build_monthly_time_spine(start_yyyymm: int, end_yyyymm: int) -> pd.DataFrame:
    """Create a deterministic monthly time spine DataFrame.

    Columns: yyyymm (int), year (int), month (int).
    """
    months = list(iter_months_inclusive(start_yyyymm, end_yyyymm))
    years = [m // 100 for m in months]
    mos = [m % 100 for m in months]
    return pd.DataFrame({"yyyymm": months, "year": years, "month": mos}).astype(
        {"yyyymm": "int64", "year": "int64", "month": "int64"}
    )


def parse_acq_date_series(acq_date: pd.Series, *, strict: bool = True) -> pd.Series:
    """Parse acquisition date to pandas datetime (UTC midnight)."""
    dt = pd.to_datetime(acq_date, errors="coerce", utc=True)
    if strict and dt.isna().any():
        raise ValueError("acq_date contains unparseable values under strict=True")
    return dt.dt.floor("D")


def _hhmm_to_hours_minutes(hhmm: object) -> tuple[int, int]:
    """Parse FIRMS HHMM (string/int) into (hour, minute)."""
    if hhmm is None or (isinstance(hhmm, float) and pd.isna(hhmm)):  # type: ignore[arg-type]
        raise ValueError("acq_time is missing")
    s = str(int(hhmm)) if isinstance(hhmm, (int,)) else str(hhmm).strip()
    if s == "":
        raise ValueError("acq_time is empty")
    if not s.isdigit():
        raise ValueError(f"acq_time must be digits (HHMM). Got: {hhmm!r}")
    if len(s) > 4:
        raise ValueError(f"acq_time must be <=4 digits (HHMM). Got: {hhmm!r}")
    s = s.zfill(4)
    hh = int(s[:2])
    mm = int(s[2:])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"acq_time outside 00:00..23:59. Got: {s}")
    return hh, mm


def parse_acq_time_to_timedelta(acq_time: pd.Series, *, strict: bool = True) -> pd.Series:
    """Parse FIRMS HHMM into pandas Timedelta (UTC offset from midnight)."""
    out = []
    for v in acq_time.tolist():
        try:
            hh, mm = _hhmm_to_hours_minutes(v)
            out.append(pd.Timedelta(hours=hh, minutes=mm))
        except Exception:
            if strict:
                raise
            out.append(pd.NaT)
    return pd.Series(out, index=acq_time.index)


def acq_datetime_utc_from_date_time(
    acq_date: pd.Series, acq_time: pd.Series, *, strict: bool = True
) -> pd.Series:
    """Combine acq_date and acq_time into UTC timezone-aware timestamps."""
    d0 = parse_acq_date_series(acq_date, strict=strict)
    td = parse_acq_time_to_timedelta(acq_time, strict=strict)
    if strict and td.isna().any():
        raise ValueError("acq_time contains invalid values under strict=True")
    return d0 + td


def yyyymm_from_acq_date_series(acq_date: pd.Series, *, strict: bool = True) -> pd.Series:
    """Derive yyyymm integer from acq_date deterministically."""
    d0 = parse_acq_date_series(acq_date, strict=strict)
    y = d0.dt.year
    m = d0.dt.month
    yyyymm = (y * 100 + m).astype("Int64")
    if strict and yyyymm.isna().any():
        raise ValueError("Failed to derive yyyymm under strict=True")
    return yyyymm
