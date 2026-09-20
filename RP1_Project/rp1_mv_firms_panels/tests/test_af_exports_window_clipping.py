# file: tests/test_af_exports_window_clipping.py
"""Window-clipping tests for the dedicated RP1 AF export family."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.core.config import load_config
from mv_firms_panels.io.paths import build_run_dir, rp1_af_export_path
from mv_firms_panels.stages.combine_panels import combine_panels


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cfg(tmp_repo: Path):
    src_repo = _repo_root()
    (tmp_repo / "configs" / "schemas").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        src_repo / "configs" / "example_project.yaml", tmp_repo / "configs" / "example_project.yaml"
    )
    for name in [
        "panel_monthly.schema.json",
        "rp1_af_monthly_base_viirs.schema.json",
        "rp1_af_monthly_ext_viirs.schema.json",
        "rp1_af_monthly_base_modis.schema.json",
        "rp1_af_monthly_ext_modis.schema.json",
    ]:
        shutil.copy(
            src_repo / "configs" / "schemas" / name, tmp_repo / "configs" / "schemas" / name
        )

    cfg_path = tmp_repo / "configs" / "example_project.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    raw["outputs"]["base_dir"] = "out/runs"
    raw["outputs"]["write_formats"]["monthly_panels"] = ["csv"]
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config(cfg_path, validate_paths=False, repo_root=tmp_repo).config


def test_rp1_af_exports_are_clipped_to_sensor_specific_windows(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir(parents=True, exist_ok=True)
    cfg = _load_cfg(tmp_repo)

    unit_universe = pd.DataFrame(
        [
            {
                "level": "acz",
                "unit_id": "zone_1",
                "unit_code": "Z1",
                "unit_name": "Zone 1",
                "parent_level": pd.NA,
                "parent_id": pd.NA,
                "parent_code": pd.NA,
                "parent_name": pd.NA,
            }
        ]
    )
    viirs = pd.DataFrame(
        [
            {
                "level": "acz",
                "unit_id": "zone_1",
                "yyyymm": 201112,
                "viirs_det_low": 1,
                "viirs_det_nominal": 0,
                "viirs_det_high": 0,
                "viirs_det_nh": 0,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 2.0,
                "viirs_frp_mean_mw": 2.0,
                "viirs_pct_high_conf": 0.0,
                "viirs_days_active_nh": 0,
                "viirs_streak_max_nh": 0,
                "viirs_frp_p95_daily_max_mw": 2.0,
            },
            {
                "level": "acz",
                "unit_id": "zone_1",
                "yyyymm": 201201,
                "viirs_det_low": 2,
                "viirs_det_nominal": 1,
                "viirs_det_high": 0,
                "viirs_det_nh": 1,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 4.0,
                "viirs_frp_mean_mw": 4.0,
                "viirs_pct_high_conf": 0.0,
                "viirs_days_active_nh": 1,
                "viirs_streak_max_nh": 1,
                "viirs_frp_p95_daily_max_mw": 4.0,
            },
            {
                "level": "acz",
                "unit_id": "zone_1",
                "yyyymm": 202412,
                "viirs_det_low": 1,
                "viirs_det_nominal": 1,
                "viirs_det_high": 1,
                "viirs_det_nh": 2,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 5.0,
                "viirs_frp_mean_mw": 5.0,
                "viirs_pct_high_conf": 33.3,
                "viirs_days_active_nh": 1,
                "viirs_streak_max_nh": 1,
                "viirs_frp_p95_daily_max_mw": 5.0,
            },
            {
                "level": "acz",
                "unit_id": "zone_1",
                "yyyymm": 202501,
                "viirs_det_low": 1,
                "viirs_det_nominal": 0,
                "viirs_det_high": 0,
                "viirs_det_nh": 0,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 1.0,
                "viirs_frp_mean_mw": 1.0,
                "viirs_pct_high_conf": 0.0,
                "viirs_days_active_nh": 0,
                "viirs_streak_max_nh": 0,
                "viirs_frp_p95_daily_max_mw": 1.0,
            },
        ]
    )
    modis = pd.DataFrame(
        [
            {
                "level": "acz",
                "unit_id": "zone_1",
                "yyyymm": 200012,
                "modis_det_low": 1,
                "modis_det_nominal": 0,
                "modis_det_high": 0,
                "modis_det_nh": 0,
                "modis_frp_active_days": 1,
                "modis_frp_sum_daily_max_mw": 2.0,
                "modis_frp_mean_mw": 2.0,
                "modis_pct_high_conf": 0.0,
                "modis_days_active_nh": 0,
                "modis_streak_max_nh": 0,
                "modis_frp_p95_daily_max_mw": 2.0,
            },
            {
                "level": "acz",
                "unit_id": "zone_1",
                "yyyymm": 200101,
                "modis_det_low": 2,
                "modis_det_nominal": 1,
                "modis_det_high": 0,
                "modis_det_nh": 1,
                "modis_frp_active_days": 1,
                "modis_frp_sum_daily_max_mw": 4.0,
                "modis_frp_mean_mw": 4.0,
                "modis_pct_high_conf": 0.0,
                "modis_days_active_nh": 1,
                "modis_streak_max_nh": 1,
                "modis_frp_p95_daily_max_mw": 4.0,
            },
            {
                "level": "acz",
                "unit_id": "zone_1",
                "yyyymm": 202412,
                "modis_det_low": 1,
                "modis_det_nominal": 1,
                "modis_det_high": 1,
                "modis_det_nh": 2,
                "modis_frp_active_days": 1,
                "modis_frp_sum_daily_max_mw": 5.0,
                "modis_frp_mean_mw": 5.0,
                "modis_pct_high_conf": 33.3,
                "modis_days_active_nh": 1,
                "modis_streak_max_nh": 1,
                "modis_frp_p95_daily_max_mw": 5.0,
            },
            {
                "level": "acz",
                "unit_id": "zone_1",
                "yyyymm": 202501,
                "modis_det_low": 1,
                "modis_det_nominal": 0,
                "modis_det_high": 0,
                "modis_det_nh": 0,
                "modis_frp_active_days": 1,
                "modis_frp_sum_daily_max_mw": 1.0,
                "modis_frp_mean_mw": 1.0,
                "modis_pct_high_conf": 0.0,
                "modis_days_active_nh": 0,
                "modis_streak_max_nh": 0,
                "modis_frp_p95_daily_max_mw": 1.0,
            },
        ]
    )

    combine_panels(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id="clip_window",
        unit_universe_df=unit_universe,
        viirs_monthly_df=viirs,
        modis_monthly_df=modis,
        start_yyyymm=200012,
        end_yyyymm=202501,
        write_outputs=True,
        validate_schema=True,
        write_extended_metrics=True,
    )

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id="clip_window"
    )

    viirs_base_path = rp1_af_export_path(
        run_dir=run_dir,
        level="acz",
        sensor_mode="viirs",
        partition_key="acz_code",
        partition_value="Z1",
        fmt="csv",
        family="base",
    )
    viirs_ext_path = rp1_af_export_path(
        run_dir=run_dir,
        level="acz",
        sensor_mode="viirs",
        partition_key="acz_code",
        partition_value="Z1",
        fmt="csv",
        family="ext",
    )
    modis_base_path = rp1_af_export_path(
        run_dir=run_dir,
        level="acz",
        sensor_mode="modis",
        partition_key="acz_code",
        partition_value="Z1",
        fmt="csv",
        family="base",
    )
    modis_ext_path = rp1_af_export_path(
        run_dir=run_dir,
        level="acz",
        sensor_mode="modis",
        partition_key="acz_code",
        partition_value="Z1",
        fmt="csv",
        family="ext",
    )

    viirs_base_df = pd.read_csv(viirs_base_path)
    viirs_ext_df = pd.read_csv(viirs_ext_path)
    modis_base_df = pd.read_csv(modis_base_path)
    modis_ext_df = pd.read_csv(modis_ext_path)

    assert viirs_base_df["yyyymm"].min() == 201201
    assert viirs_base_df["yyyymm"].max() == 202412
    assert viirs_ext_df["yyyymm"].min() == 201201
    assert viirs_ext_df["yyyymm"].max() == 202412
    assert 201112 not in set(viirs_base_df["yyyymm"].tolist())
    assert 202501 not in set(viirs_base_df["yyyymm"].tolist())

    assert modis_base_df["yyyymm"].min() == 200101
    assert modis_base_df["yyyymm"].max() == 202412
    assert modis_ext_df["yyyymm"].min() == 200101
    assert modis_ext_df["yyyymm"].max() == 202412
    assert 200012 not in set(modis_base_df["yyyymm"].tolist())
    assert 202501 not in set(modis_base_df["yyyymm"].tolist())
