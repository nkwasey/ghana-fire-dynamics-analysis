# file: tests/test_combine_sensor_coverage_nulling.py
"""Coverage-aware combine.

When combining sensors on a MODIS-anchored monthly spine, VIIRS metrics must be
structurally missing (NA/null) for months prior to the VIIRS coverage start.

Within the coverage window, missing unit-month rows represent "no detections"
and must follow the existing semantics: counts/sums = 0; mean may be NA.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.combine_panels import combine_panels


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_example_cfg_dict() -> dict:
    p = _repo_root() / "configs" / "example_project.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_combine_panels_applies_sensor_coverage_nulling(tmp_path: Path) -> None:
    cfg_dict = _load_example_cfg_dict()

    cfg_dict.setdefault("processing", {})
    cfg_dict["processing"].setdefault("time_range", {})
    cfg_dict["processing"]["time_range"]["start_yyyymm"] = 200001
    cfg_dict["processing"]["time_range"]["end_yyyymm"] = 201301
    cfg_dict["processing"]["time_range"]["timezone"] = "UTC"

    # Coverage windows (structural missingness).
    cfg_dict["processing"]["sensor_coverage"] = {
        "modis": {"start_yyyymm": 200001, "end_yyyymm": None, "timezone": "UTC"},
        "viirs": {"start_yyyymm": 201201, "end_yyyymm": None, "timezone": "UTC"},
    }

    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg_dict, sort_keys=False), encoding="utf-8")

    repo_root = _repo_root()
    loaded = load_config(p, validate_paths=False, repo_root=repo_root)
    cfg = loaded.config

    unit_universe = pd.DataFrame(
        [
            {"level": "district", "unit_id": "U1", "unit_name": "Unit 1"},
        ]
    )

    # Provide a single VIIRS row at the first in-coverage month.
    viirs_monthly = pd.DataFrame(
        [
            {
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 201201,
                "viirs_det_low": 1,
                "viirs_det_nominal": 0,
                "viirs_det_high": 0,
                "viirs_det_nh": 0,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 5.0,
                # omit mean to test internal recomputation
            }
        ]
    )

    empty_modis = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])

    res = combine_panels(
        cfg=cfg,
        repo_root=repo_root,
        run_id="test_run",
        unit_universe_df=unit_universe,
        viirs_monthly_df=viirs_monthly,
        modis_monthly_df=empty_modis,
        start_yyyymm=200001,
        end_yyyymm=201301,
        write_outputs=False,
        validate_schema=True,
        write_extended_metrics=False,
    )

    panel = res.panel_monthly
    assert list(panel.columns) == list(cfg.determinism.column_order["panel_monthly"])

    viirs_cols = [
        "viirs_det_low",
        "viirs_det_nominal",
        "viirs_det_high",
        "viirs_det_nh",
        "viirs_frp_active_days",
        "viirs_frp_sum_daily_max_mw",
        "viirs_frp_mean_mw",
    ]

    # Pre-coverage months must be NA for *all* VIIRS metric columns.
    pre_cov = panel.loc[panel["yyyymm"] < 201201, viirs_cols]
    assert len(pre_cov) > 0
    for c in viirs_cols:
        assert pre_cov[c].isna().all()

    # First in-coverage month: values preserved / mean computed.
    r_201201 = panel.loc[panel["yyyymm"] == 201201].iloc[0]
    assert r_201201["viirs_det_low"] == 1
    assert r_201201["viirs_frp_active_days"] == 1
    assert r_201201["viirs_frp_sum_daily_max_mw"] == 5.0
    assert r_201201["viirs_frp_mean_mw"] == 5.0

    # In-coverage month with no VIIRS input row: counts/sums must be 0; mean stays NA.
    r_201202 = panel.loc[panel["yyyymm"] == 201202].iloc[0]
    assert r_201202["viirs_det_low"] == 0
    assert r_201202["viirs_det_nominal"] == 0
    assert r_201202["viirs_det_high"] == 0
    assert r_201202["viirs_det_nh"] == 0
    assert r_201202["viirs_frp_active_days"] == 0
    assert r_201202["viirs_frp_sum_daily_max_mw"] == 0.0
    assert pd.isna(r_201202["viirs_frp_mean_mw"])
