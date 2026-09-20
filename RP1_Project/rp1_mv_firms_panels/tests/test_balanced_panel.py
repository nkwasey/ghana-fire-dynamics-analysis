# file: tests/test_balanced_panel.py
"""Balanced panel guarantees.

This test isolates the balancing logic: given a unit universe and a time spine,
combine_panels must emit every unit×month row even when there are no detections.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.combine_panels import CombinePanelsError, combine_panels


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cfg():
    repo_root = _repo_root()
    loaded = load_config(
        repo_root / "configs" / "example_project.yaml", validate_paths=False, repo_root=repo_root
    )
    return loaded.config, repo_root


def test_balanced_panel_with_no_detections():
    cfg, repo_root = _load_cfg()

    unit_universe = pd.DataFrame(
        [
            {"level": "district", "unit_id": "U1", "unit_name": "Unit 1"},
            {"level": "district", "unit_id": "U2", "unit_name": "Unit 2"},
        ]
    )

    empty_viirs = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])
    empty_modis = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])

    res = combine_panels(
        cfg=cfg,
        repo_root=repo_root,
        run_id="test_run",
        unit_universe_df=unit_universe,
        viirs_monthly_df=empty_viirs,
        modis_monthly_df=empty_modis,
        start_yyyymm=202401,
        end_yyyymm=202402,
        write_outputs=False,
        validate_schema=True,
        write_extended_metrics=False,
    )

    panel = res.panel_monthly
    assert len(panel) == 4  # 2 units × 2 months

    # All counts must be zero; FRP mean must be NA when active_days==0
    for sensor in ["viirs", "modis"]:
        assert (panel[f"{sensor}_det_low"] == 0).all()
        assert (panel[f"{sensor}_det_nominal"] == 0).all()
        assert (panel[f"{sensor}_det_high"] == 0).all()
        assert (panel[f"{sensor}_det_nh"] == 0).all()
        assert (panel[f"{sensor}_frp_active_days"] == 0).all()
        assert (panel[f"{sensor}_frp_sum_daily_max_mw"] == 0.0).all()
        assert panel[f"{sensor}_frp_mean_mw"].isna().all()


def test_combine_panels_missing_unit_universe_reports_access_guidance(tmp_path: Path):
    cfg, repo_root = _load_cfg()
    empty_viirs = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])
    empty_modis = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])

    with pytest.raises(CombinePanelsError) as excinfo:
        combine_panels(
            cfg=cfg,
            repo_root=repo_root,
            run_id="missing_unit_universe",
            unit_universe_path=tmp_path / "missing_unit_universe.csv",
            viirs_monthly_df=empty_viirs,
            modis_monthly_df=empty_modis,
            start_yyyymm=202401,
            end_yyyymm=202402,
            write_outputs=False,
            validate_schema=False,
            write_extended_metrics=False,
        )

    msg = str(excinfo.value)
    assert "Missing required Stage 2 input `unit_universe_csv`" in msg
    assert "docs/data_access.md" in msg
    assert "README.md" in msg
    assert "Required by stage: rp1_mv_firms_panels combine_panels." in msg
