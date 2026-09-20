# file: tests/test_aggregate_monthly_slicing.py
"""Focused tests for aggregate_monthly time-window slicing.

This test asserts that aggregate_monthly:
- accepts explicit start_yyyymm/end_yyyymm parameters,
- filters fires_canonical rows by yyyymm bounds BEFORE aggregation,
- records pre/post filter counts + effective window in the QA summary.

We use an in-memory fires_canonical_df to avoid filesystem dependencies.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.aggregate_monthly import aggregate_monthly


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cfg():
    repo_root = _repo_root()
    loaded = load_config(
        repo_root / "configs" / "example_project.yaml", validate_paths=False, repo_root=repo_root
    )
    return loaded.config, repo_root


def test_aggregate_monthly_explicit_window_filters_months() -> None:
    cfg, repo_root = _load_cfg()

    fires = pd.DataFrame(
        [
            # Jan (outside)
            {
                "run_id": "testrun",
                "source_file": "dummy.csv",
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 202401,
                "date_utc": "2024-01-01",
                "conf_cat": "n",
                "frp_mw": 1.0,
            },
            # Feb (inside)
            {
                "run_id": "testrun",
                "source_file": "dummy.csv",
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 202402,
                "date_utc": "2024-02-01",
                "conf_cat": "h",
                "frp_mw": 2.0,
            },
            {
                "run_id": "testrun",
                "source_file": "dummy.csv",
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U2",
                "yyyymm": 202402,
                "date_utc": "2024-02-02",
                "conf_cat": "l",
                "frp_mw": 0.0,
            },
            # Mar (outside)
            {
                "run_id": "testrun",
                "source_file": "dummy.csv",
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U2",
                "yyyymm": 202403,
                "date_utc": "2024-03-03",
                "conf_cat": "n",
                "frp_mw": 3.0,
            },
        ]
    )

    res = aggregate_monthly(
        cfg=cfg,
        repo_root=repo_root,
        sensor="viirs",
        run_id="testrun",
        fires_canonical_df=fires,
        start_yyyymm=202402,
        end_yyyymm=202402,
        write_outputs=False,
    )

    out = res.panel_sensor_monthly
    assert set(out["yyyymm"].unique().tolist()) == {202402}

    qa = res.qa_summary
    tw = qa["steps"]["time_window_filter"]
    assert tw["source"] == "explicit"
    assert tw["start_yyyymm"] == 202402
    assert tw["end_yyyymm"] == 202402
    assert tw["n_rows_pre"] == 4
    assert tw["n_rows_post"] == 2
