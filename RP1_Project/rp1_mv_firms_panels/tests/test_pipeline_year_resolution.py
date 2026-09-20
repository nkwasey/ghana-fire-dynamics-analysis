# file: tests/test_pipeline_year_resolution.py
"""Pipeline year-resolution regressions.

These tests lock in the command-layer behaviour that matters for the combined
panel time spine:
- global years are clamped by per-sensor coverage starts;
- resolved per-sensor aggregate bounds are surfaced in the dry-run plan; and
- the combine stage receives explicit start/end bounds derived from the sensor
  aggregate bounds, rather than silently falling back to cfg.processing.time_range.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.cli.commands import cmd_pipeline


def _write_minimal_repo(tmp_repo: Path) -> Path:
    """Create a minimal repo layout and return config path."""
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

    cfg.setdefault("processing", {})
    cfg["processing"]["sensors_enabled"] = ["viirs", "modis"]

    # Keep the project-level time_range narrow so the test will fail if combine
    # ever falls back to cfg.processing.time_range instead of explicit bounds.
    cfg["processing"]["time_range"] = {
        "start_yyyymm": 202501,
        "end_yyyymm": 202502,
        "timezone": "UTC",
    }

    cfg["processing"]["sensor_time_ranges"] = {
        "modis": {"start_yyyymm": 200001, "end_yyyymm": 202512, "timezone": "UTC"},
        "viirs": {"start_yyyymm": 201201, "end_yyyymm": 202512, "timezone": "UTC"},
    }
    cfg["processing"]["sensor_coverage"] = {
        "modis": {"start_yyyymm": 200001, "end_yyyymm": None, "timezone": "UTC"},
        "viirs": {"start_yyyymm": 201201, "end_yyyymm": None, "timezone": "UTC"},
    }

    uu = pd.DataFrame({"level": ["district"], "unit_id": ["U1"], "unit_name": ["Unit 1"]})
    (tmp_repo / "data" / "metadata" / "unit_universe.csv").write_text(
        uu.to_csv(index=False), encoding="utf-8"
    )

    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return cfg_path


def test_pipeline_year_resolution_clamps_global_years_and_sets_combine_bounds(
    tmp_path: Path, capsys
) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)

    rc = cmd_pipeline(
        repo_root=tmp_repo,
        config_path=cfg_path,
        run_id="test_run",
        years="2000-2025",
        years_viirs=None,
        years_modis=None,
        dry_run=True,
        make_plots=False,
        zip_sha256=None,
        log_level="INFO",
        skip_existing=False,
        force=False,
    )
    assert rc == 0

    plan = json.loads(capsys.readouterr().out.strip())

    years_by_sensor = plan["years_by_sensor"]
    assert years_by_sensor["modis"][0] == 2000
    assert years_by_sensor["modis"][-1] == 2025
    assert years_by_sensor["viirs"][0] == 2012
    assert years_by_sensor["viirs"][-1] == 2025

    bounds = plan["aggregate_bounds_by_sensor"]
    assert bounds["modis"] == [200001, 202512]
    assert bounds["viirs"] == [201201, 202512]

    # Regression: combine must use the union of resolved sensor bounds, not the
    # narrow cfg.processing.time_range smoke window.
    assert plan["combine_bounds"] == [200001, 202512]

    combine_stage = next(stage for stage in plan["stages"] if stage["stage"] == "combine")
    assert combine_stage["start_yyyymm"] == 200001
    assert combine_stage["end_yyyymm"] == 202512


def test_pipeline_stage_plan_uses_sensor_specific_cli_years_for_combine_bounds(
    tmp_path: Path, capsys
) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)

    rc = cmd_pipeline(
        repo_root=tmp_repo,
        config_path=cfg_path,
        run_id="test_run",
        years=None,
        years_viirs="2012-2024",
        years_modis="2000-2025",
        dry_run=True,
        make_plots=False,
        zip_sha256=None,
        log_level="INFO",
        skip_existing=False,
        force=False,
    )
    assert rc == 0

    plan = json.loads(capsys.readouterr().out.strip())

    bounds = plan["aggregate_bounds_by_sensor"]
    assert bounds["modis"] == [200001, 202512]
    assert bounds["viirs"] == [201201, 202412]
    assert plan["combine_bounds"] == [200001, 202512]

    combine_stage = next(stage for stage in plan["stages"] if stage["stage"] == "combine")
    assert combine_stage == {"stage": "combine", "start_yyyymm": 200001, "end_yyyymm": 202512}
