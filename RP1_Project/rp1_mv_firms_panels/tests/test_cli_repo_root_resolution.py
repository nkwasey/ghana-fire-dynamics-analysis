"""CLI repo-root inference regressions."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
from mv_firms_panels.cli import commands as cli_commands
from mv_firms_panels.cli.commands import cmd_prepare_year


def _write_nested_project(workspace: Path) -> tuple[Path, Path]:
    here = Path(__file__).resolve()
    source_root = here.parents[1]
    project_root = workspace / "RP1_Project" / "rp1_mv_firms_panels"

    (project_root / "configs" / "schemas").mkdir(parents=True, exist_ok=True)
    (project_root / "data" / "metadata").mkdir(parents=True, exist_ok=True)

    shutil.copy(
        source_root / "configs" / "example_project.yaml",
        project_root / "configs" / "example_project.yaml",
    )
    for name in [
        "fires_canonical.schema.json",
        "panel_monthly.schema.json",
        "rp1_af_monthly_base.schema.json",
        "rp1_af_monthly_ext.schema.json",
        "rp1_af_monthly_base_viirs.schema.json",
        "rp1_af_monthly_base_modis.schema.json",
        "rp1_af_monthly_ext_viirs.schema.json",
        "rp1_af_monthly_ext_modis.schema.json",
    ]:
        shutil.copy(
            source_root / "configs" / "schemas" / name, project_root / "configs" / "schemas" / name
        )

    uu = pd.DataFrame({"level": ["district"], "unit_id": ["U1"], "unit_name": ["Unit 1"]})
    (project_root / "data" / "metadata" / "unit_universe.csv").write_text(
        uu.to_csv(index=False), encoding="utf-8"
    )

    return workspace, project_root


def test_prepare_year_infers_repo_root_from_config_path_when_omitted(
    tmp_path: Path, monkeypatch
) -> None:
    workspace, project_root = _write_nested_project(tmp_path / "workspace")
    config_path = project_root / "configs" / "example_project.yaml"
    captured: dict[str, object] = {}

    def _fake_prepare_year(**kwargs):
        captured["repo_root"] = kwargs["repo_root"]
        captured["sensor"] = kwargs["sensor"]
        captured["year"] = kwargs["year"]
        captured["run_id"] = kwargs["run_id"]
        return None

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli_commands, "prepare_year", _fake_prepare_year)

    rc = cmd_prepare_year(
        repo_root=None,
        config_path=config_path,
        sensor="viirs",
        year=2012,
        run_id="testrun",
        zip_sha256=None,
        log_level="INFO",
        skip_existing=False,
        force=False,
    )

    assert rc == 0
    assert captured["repo_root"] == project_root.resolve()
    assert captured["sensor"] == "viirs"
    assert captured["year"] == 2012
    assert captured["run_id"] == "testrun"
    assert (project_root / "out" / "runs" / "testrun").exists()
