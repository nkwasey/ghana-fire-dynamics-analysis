"""Regression tests for bounded-memory annual-partition aggregation.

The production Ghana run writes one fires_canonical CSV per sensor-year.  The
streaming path must be scientifically identical to the legacy in-memory path
while avoiding concatenation of every annual detection row at once.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pandas.testing as pdt
from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.aggregate_monthly import aggregate_monthly


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cfg():
    root = _repo_root()
    loaded = load_config(
        root / "configs" / "example_project.yaml",
        validate_paths=False,
        repo_root=root,
    )
    return loaded.config, root


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # 2023: repeated day tests daily-max FRP and confidence counts.
            {"level": "district", "unit_id": "U1", "yyyymm": 202312, "date_utc": "2023-12-01", "conf_cat": "n", "frp_mw": 2.0},
            {"level": "district", "unit_id": "U1", "yyyymm": 202312, "date_utc": "2023-12-01", "conf_cat": "h", "frp_mw": 9.0},
            {"level": "district", "unit_id": "U1", "yyyymm": 202312, "date_utc": "2023-12-02", "conf_cat": "n", "frp_mw": 4.0},
            {"level": "acz", "unit_id": "A1", "yyyymm": 202312, "date_utc": "2023-12-02", "conf_cat": "l", "frp_mw": 1.0},
            # 2024: consecutive NH days test persistence.
            {"level": "district", "unit_id": "U1", "yyyymm": 202401, "date_utc": "2024-01-01", "conf_cat": "h", "frp_mw": 8.0},
            {"level": "district", "unit_id": "U1", "yyyymm": 202401, "date_utc": "2024-01-02", "conf_cat": "n", "frp_mw": 6.0},
            {"level": "district", "unit_id": "U2", "yyyymm": 202402, "date_utc": "2024-02-05", "conf_cat": "l", "frp_mw": 3.0},
            {"level": "acz", "unit_id": "A1", "yyyymm": 202402, "date_utc": "2024-02-05", "conf_cat": "h", "frp_mw": 7.0},
        ]
    )


def test_annual_partition_streaming_matches_in_memory_exactly(tmp_path: Path) -> None:
    cfg, root = _cfg()
    all_rows = _rows()
    paths = []
    for year in (2023, 2024):
        p = tmp_path / f"fires_canonical_viirs_{year}.csv"
        all_rows.loc[(all_rows["yyyymm"] // 100) == year].to_csv(p, index=False)
        paths.append(p)

    streamed = aggregate_monthly(
        cfg=cfg,
        repo_root=root,
        sensor="viirs",
        run_id="streamed",
        fires_canonical_paths=paths,
        start_yyyymm=202312,
        end_yyyymm=202402,
        write_outputs=False,
    )
    legacy = aggregate_monthly(
        cfg=cfg,
        repo_root=root,
        sensor="viirs",
        run_id="streamed",
        fires_canonical_df=all_rows,
        start_yyyymm=202312,
        end_yyyymm=202402,
        write_outputs=False,
    )

    pdt.assert_frame_equal(
        streamed.panel_sensor_monthly.reset_index(drop=True),
        legacy.panel_sensor_monthly.reset_index(drop=True),
        check_dtype=True,
        check_exact=True,
    )
    read_step = streamed.qa_summary["steps"]["read_fires_canonical"]
    assert read_step["strategy"] == "annual_partition_streaming"
    assert read_step["n_files"] == 2
    assert read_step["n_rows"] == len(all_rows)
    tw = streamed.qa_summary["steps"]["time_window_filter"]
    assert tw["n_rows_pre"] == len(all_rows)
    assert tw["n_rows_post"] == len(all_rows)
    assert tw["n_distinct_yyyymm_post"] == 3


def test_annual_partition_streaming_respects_partial_window(tmp_path: Path) -> None:
    cfg, root = _cfg()
    all_rows = _rows()
    paths = []
    for year in (2023, 2024):
        p = tmp_path / f"fires_canonical_viirs_{year}.csv"
        all_rows.loc[(all_rows["yyyymm"] // 100) == year].to_csv(p, index=False)
        paths.append(p)

    res = aggregate_monthly(
        cfg=cfg,
        repo_root=root,
        sensor="viirs",
        run_id="streamed",
        fires_canonical_paths=paths,
        start_yyyymm=202401,
        end_yyyymm=202401,
        write_outputs=False,
    )
    assert set(res.panel_sensor_monthly["yyyymm"].tolist()) == {202401}
    tw = res.qa_summary["steps"]["time_window_filter"]
    assert tw["n_rows_pre"] == len(all_rows)
    assert tw["n_rows_post"] == 2
    assert tw["n_distinct_yyyymm_post"] == 1
