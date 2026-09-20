# file: tests/test_af_exports_generic_levels.py
"""Generic-level regression tests for RP1 AF exports.

The exporter must not assume that the top level is named `acz`. This test uses
`region` as the top level and confirms that partition naming and parent linkage
are derived generically from Stage 1 hierarchy metadata for both VIIRS and MODIS.
"""

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


def test_rp1_af_exports_support_generic_top_level_partition_names_for_both_sensors(
    tmp_path: Path,
) -> None:
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir(parents=True, exist_ok=True)
    cfg = _load_cfg(tmp_repo)

    unit_universe = pd.DataFrame(
        [
            {
                "level": "region",
                "unit_id": "R1",
                "unit_code": "RG1",
                "unit_name": "Region 1",
                "parent_level": pd.NA,
                "parent_id": pd.NA,
                "parent_code": pd.NA,
                "parent_name": pd.NA,
            },
            {
                "level": "district",
                "unit_id": "D1",
                "unit_code": pd.NA,
                "unit_name": "District 1",
                "parent_level": "region",
                "parent_id": "R1",
                "parent_code": "RG1",
                "parent_name": "Region 1",
            },
        ]
    )
    viirs = pd.DataFrame(
        [
            {
                "level": "district",
                "unit_id": "D1",
                "yyyymm": 202401,
                "viirs_det_low": 1,
                "viirs_det_nominal": 1,
                "viirs_det_high": 0,
                "viirs_det_nh": 1,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 3.0,
                "viirs_frp_mean_mw": 3.0,
                "viirs_pct_high_conf": 0.0,
                "viirs_days_active_nh": 1,
                "viirs_streak_max_nh": 1,
                "viirs_frp_p95_daily_max_mw": 3.0,
            },
            {
                "level": "region",
                "unit_id": "R1",
                "yyyymm": 202401,
                "viirs_det_low": 1,
                "viirs_det_nominal": 1,
                "viirs_det_high": 0,
                "viirs_det_nh": 1,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 3.0,
                "viirs_frp_mean_mw": 3.0,
                "viirs_pct_high_conf": 0.0,
                "viirs_days_active_nh": 1,
                "viirs_streak_max_nh": 1,
                "viirs_frp_p95_daily_max_mw": 3.0,
            },
        ]
    )
    empty_modis = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])

    combine_panels(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id="generic_levels",
        unit_universe_df=unit_universe,
        viirs_monthly_df=viirs,
        modis_monthly_df=empty_modis,
        start_yyyymm=202401,
        end_yyyymm=202401,
        write_outputs=True,
        validate_schema=True,
        write_extended_metrics=True,
    )

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id="generic_levels"
    )
    for sensor_mode in ["viirs", "modis"]:
        region_base = rp1_af_export_path(
            run_dir=run_dir,
            level="region",
            sensor_mode=sensor_mode,
            partition_key="region_code",
            partition_value="RG1",
            fmt="csv",
            family="base",
        )
        district_ext = rp1_af_export_path(
            run_dir=run_dir,
            level="district",
            sensor_mode=sensor_mode,
            partition_key="region_code",
            partition_value="RG1",
            fmt="csv",
            family="ext",
        )
        assert region_base.exists()
        assert district_ext.exists()

        region_df = pd.read_csv(region_base)
        district_df = pd.read_csv(district_ext)
        assert "acz_code" not in region_df.columns
        assert "sensor_mode" not in district_df.columns
        top = region_df.iloc[0]
        assert pd.isna(top["parent_level"])
        assert pd.isna(top["parent_id"])
        child = district_df.iloc[0]
        assert child["parent_level"] == "region"
        assert child["parent_code"] == "RG1"
