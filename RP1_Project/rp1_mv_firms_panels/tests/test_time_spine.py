# file: tests/test_time_spine.py
from __future__ import annotations

import pandas as pd
import pytest
from mv_firms_panels.core.time_spine import (
    acq_datetime_utc_from_date_time,
    build_monthly_time_spine,
    yyyymm_from_acq_date_series,
)


def test_build_monthly_time_spine_inclusive() -> None:
    df = build_monthly_time_spine(202001, 202003)
    assert df["yyyymm"].tolist() == [202001, 202002, 202003]
    assert df["year"].tolist() == [2020, 2020, 2020]
    assert df["month"].tolist() == [1, 2, 3]


def test_yyyymm_from_acq_date_series_deterministic() -> None:
    s = pd.Series(["2020-02-29", "2020-03-01"])
    out = yyyymm_from_acq_date_series(s, strict=True)
    assert out.tolist() == [202002, 202003]


def test_acq_datetime_parsing_hhmm_padding_and_validation() -> None:
    acq_date = pd.Series(["2020-01-01", "2020-01-01", "2020-01-01"])
    acq_time = pd.Series([5, "45", "2345"])
    out = acq_datetime_utc_from_date_time(acq_date, acq_time, strict=True)
    assert out.dt.hour.tolist() == [0, 0, 23]
    assert out.dt.minute.tolist() == [5, 45, 45]

    with pytest.raises(ValueError):
        _ = acq_datetime_utc_from_date_time(
            pd.Series(["2020-01-01"]), pd.Series(["2360"]), strict=True
        )
