# file: tests/test_visualise_gating.py
"""Visualise stage gating regressions.

The visualise command consumes panel_monthly as an input. It must not treat
that upstream artefact as if it were a visualise-owned output during sentinel
checks. These tests lock in that behaviour.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.cli.commands import cmd_visualise
from mv_firms_panels.core.hashing import sha256_file
from mv_firms_panels.io.paths import build_run_dir, panel_monthly_wide_path


def _write_minimal_repo(tmp_repo: Path) -> Path:
    tmp_repo.mkdir(parents=True, exist_ok=True)

    here = Path(__file__).resolve()
    repo_root = here.parents[1]

    (tmp_repo / "configs" / "schemas").mkdir(parents=True, exist_ok=True)
    (tmp_repo / "data" / "metadata").mkdir(parents=True, exist_ok=True)

    shutil.copy(
        repo_root / "configs" / "example_project.yaml",
        tmp_repo / "configs" / "example_project.yaml",
    )
    shutil.copy(
        repo_root / "configs" / "schemas" / "fires_canonical.schema.json",
        tmp_repo / "configs" / "schemas" / "fires_canonical.schema.json",
    )
    shutil.copy(
        repo_root / "configs" / "schemas" / "panel_monthly.schema.json",
        tmp_repo / "configs" / "schemas" / "panel_monthly.schema.json",
    )

    cfg_path = tmp_repo / "configs" / "example_project.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("processing", {}).setdefault("time_range", {})
    cfg["processing"]["time_range"] = {
        "start_yyyymm": 202401,
        "end_yyyymm": 202402,
        "timezone": "UTC",
    }
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    uu = pd.DataFrame({"level": ["district"], "unit_id": ["U1"], "unit_name": ["Unit 1"]})
    (tmp_repo / "data" / "metadata" / "unit_universe.csv").write_text(
        uu.to_csv(index=False), encoding="utf-8"
    )
    return cfg_path


def _write_panel_monthly_input(*, tmp_repo: Path, cfg_path: Path, run_id: str) -> Path:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg["outputs"]["base_dir"], run_id=run_id
    )

    panel = pd.DataFrame(
        {
            "level": ["district", "district"],
            "unit_id": ["U1", "U1"],
            "yyyymm": [202401, 202402],
            "year": [2024, 2024],
            "month": [1, 2],
            "viirs_det_low": [0, 1],
            "viirs_det_nominal": [2, 3],
            "viirs_det_high": [0, 1],
            "viirs_det_nh": [2, 4],
            "viirs_frp_active_days": [1, 1],
            "viirs_frp_sum_daily_max_mw": [10.0, 20.0],
            "modis_det_low": [0, 0],
            "modis_det_nominal": [1, 1],
            "modis_det_high": [0, 0],
            "modis_det_nh": [1, 1],
            "modis_frp_active_days": [1, 1],
            "modis_frp_sum_daily_max_mw": [5.0, 7.5],
        }
    )

    panel_path = panel_monthly_wide_path(run_dir=run_dir, fmt="csv.gz")
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(panel_path, index=False, compression="gzip")
    return run_dir


def test_visualise_runs_when_panel_input_exists_and_visualise_sentinel_is_absent(
    tmp_path: Path,
) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    run_id = "testrun"
    run_dir = _write_panel_monthly_input(tmp_repo=tmp_repo, cfg_path=cfg_path, run_id=run_id)

    panel_path = panel_monthly_wide_path(run_dir=run_dir, fmt="csv.gz")
    assert panel_path.exists()
    assert not (run_dir / "qa" / "visualise_manifest.json").exists()

    # Regression: the presence of panel_monthly (an input) must not trigger the
    # "outputs exist but sentinel missing" failure path.
    assert (
        cmd_visualise(
            repo_root=tmp_repo,
            config_path=cfg_path,
            run_id=run_id,
            make_plots=False,
            skip_existing=False,
            force=False,
        )
        == 0
    )

    assert (run_dir / "qa" / "visualise_summary.json").exists()
    assert (run_dir / "qa" / "visualise_manifest.json").exists()
    assert (run_dir / "summaries" / "panel_monthly_totals_by_level.csv.gz").exists()


def test_visualise_skip_existing_uses_visualise_owned_outputs_not_upstream_panel_input(
    tmp_path: Path,
) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    run_id = "testrun"
    run_dir = _write_panel_monthly_input(tmp_repo=tmp_repo, cfg_path=cfg_path, run_id=run_id)

    assert (
        cmd_visualise(
            repo_root=tmp_repo,
            config_path=cfg_path,
            run_id=run_id,
            make_plots=False,
            skip_existing=False,
            force=False,
        )
        == 0
    )

    summary_path = run_dir / "qa" / "visualise_summary.json"
    manifest_path = run_dir / "qa" / "visualise_manifest.json"
    monthly_totals_path = run_dir / "summaries" / "panel_monthly_totals_by_level.csv.gz"

    h_summary_1 = sha256_file(summary_path)
    h_manifest_1 = sha256_file(manifest_path)
    h_totals_1 = sha256_file(monthly_totals_path)

    assert (
        cmd_visualise(
            repo_root=tmp_repo,
            config_path=cfg_path,
            run_id=run_id,
            make_plots=False,
            skip_existing=True,
            force=False,
        )
        == 0
    )

    assert sha256_file(summary_path) == h_summary_1
    assert sha256_file(manifest_path) == h_manifest_1
    assert sha256_file(monthly_totals_path) == h_totals_1
