from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml
from mv_firms_panels.core.config import load_config
from mv_firms_panels.io.paths import build_run_dir
from mv_firms_panels.stages import visualise as visualise_stage

RUN_NATIVE_PLOT_SMOKE = os.environ.get("RP_RUN_NATIVE_PLOT_SMOKE") == "1"
NATIVE_PLOT_SKIP_REASON = (
    "Set RP_RUN_NATIVE_PLOT_SMOKE=1 to run native GeoPandas/Matplotlib rendering smoke tests."
)


def _write_minimal_repo(tmp_repo: Path) -> Path:
    tmp_repo.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[1]
    (tmp_repo / "configs" / "schemas").mkdir(parents=True, exist_ok=True)
    (tmp_repo / "data" / "metadata").mkdir(parents=True, exist_ok=True)

    shutil.copy(
        repo_root / "configs" / "example_project.yaml",
        tmp_repo / "configs" / "example_project.yaml",
    )
    shutil.copy(
        repo_root / "configs" / "schemas" / "panel_monthly.schema.json",
        tmp_repo / "configs" / "schemas" / "panel_monthly.schema.json",
    )

    cfg_path = tmp_repo / "configs" / "example_project.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["outputs"]["write_formats"]["monthly_panels"] = ["csv"]
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    uu = pd.DataFrame(
        {"level": ["district", "acz"], "unit_id": ["U1", "A1"], "unit_name": ["Unit 1", "Zone 1"]}
    )
    (tmp_repo / "data" / "metadata" / "unit_universe.csv").write_text(
        uu.to_csv(index=False),
        encoding="utf-8",
    )
    return cfg_path


def _stub_plot_timeseries(
    *,
    df: pd.DataFrame,
    out_dir: Path,
    level: str,
    x: str,
    y_cols,
    title: str,
) -> list[Path]:
    """Write deterministic placeholder artefacts without entering Matplotlib rendering."""
    del df, x, y_cols, title
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"timeseries_{level}".replace("/", "_")
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    png.write_bytes(b"stub-visualise-png")
    pdf.write_bytes(b"stub-visualise-pdf")
    return [png, pdf]


def _run_visualise_summary_plot_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    native_plotting: bool,
):
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    loaded = load_config(cfg_path, validate_paths=False, repo_root=tmp_repo)
    cfg = loaded.config

    panel = pd.DataFrame(
        {
            "run_id": ["test_run"] * 4,
            "level": ["district", "district", "acz", "acz"],
            "unit_id": ["U1", "U1", "A1", "A1"],
            "unit_name": ["Unit 1", "Unit 1", "Zone 1", "Zone 1"],
            "yyyymm": [202401, 202402, 202401, 202402],
            "year": [2024, 2024, 2024, 2024],
            "month": [1, 2, 1, 2],
            "viirs_det_low": [0, 1, 0, 0],
            "viirs_det_nominal": [2, 3, 1, 1],
            "viirs_det_high": [0, 1, 0, 0],
            "viirs_det_nh": [2, 4, 1, 1],
            "viirs_frp_active_days": [1, 1, 1, 1],
            "viirs_frp_sum_daily_max_mw": [10.0, 20.0, 5.0, 6.0],
            "viirs_frp_mean_mw": [10.0, 20.0, 5.0, 6.0],
            "modis_det_low": [0, 0, 0, 0],
            "modis_det_nominal": [1, 1, 1, 1],
            "modis_det_high": [0, 0, 0, 0],
            "modis_det_nh": [1, 1, 1, 1],
            "modis_frp_active_days": [1, 1, 1, 1],
            "modis_frp_sum_daily_max_mw": [5.0, 7.5, 2.0, 2.5],
            "modis_frp_mean_mw": [5.0, 7.5, 2.0, 2.5],
        }
    )

    if not native_plotting:
        monkeypatch.setattr(visualise_stage, "_plot_timeseries", _stub_plot_timeseries)

    res = visualise_stage.visualise(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id="test_run",
        panel_monthly_df=panel,
        write_outputs=True,
        make_plots=True,
    )
    return tmp_repo, cfg, res


def _assert_visualise_plot_contract(tmp_repo: Path, cfg, res) -> None:
    assert res.qa_summary_path is not None
    assert res.manifest_path is not None

    summary = json.loads(res.qa_summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))

    figure_entries = manifest.get("figures", [])
    assert len(figure_entries) == 4
    assert summary["plots"]["requested"] is True
    assert summary["plots"]["written"] == 4
    assert sorted(summary["plots"]["files"]) == sorted(
        [Path(entry["path"]).name for entry in figure_entries]
    )

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id="test_run"
    )
    for entry in figure_entries:
        assert (tmp_repo / entry["path"]).exists()
    assert (run_dir / "summaries" / "panel_monthly_totals_by_level.csv.gz").exists()


def test_visualise_summary_reports_actual_written_plot_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_repo, cfg, res = _run_visualise_summary_plot_smoke(
        tmp_path,
        monkeypatch,
        native_plotting=False,
    )

    _assert_visualise_plot_contract(tmp_repo, cfg, res)


@pytest.mark.native_plot_smoke
@pytest.mark.skipif(not RUN_NATIVE_PLOT_SMOKE, reason=NATIVE_PLOT_SKIP_REASON)
def test_visualise_summary_reports_actual_written_plot_count_native_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_repo, cfg, res = _run_visualise_summary_plot_smoke(
        tmp_path,
        monkeypatch,
        native_plotting=True,
    )

    _assert_visualise_plot_contract(tmp_repo, cfg, res)
