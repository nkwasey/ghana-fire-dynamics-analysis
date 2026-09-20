# file: src/mv_firms_panels/stages/visualise.py
"""Stage: visualise (panel_monthly → human-readable summaries + plots).

Role in pipeline
----------------
- Input: wide balanced monthly panel produced by `combine_panels`.
- Output: lightweight, deterministic summaries and (optionally) plots.

Why this exists
---------------
The contracted pipeline outputs (`fires_canonical`, `panel_monthly`) are intended
for analysis and downstream modelling. Stakeholders usually also want quick
sanity checks and simple visual products (time-series totals, sensor
comparisons, and per-level summaries). This stage provides those in a
non-opinionated, reproducible way.

Determinism (binding)
---------------------
- Stable sort before writing summary tables.
- Fixed filenames under the run directory.
- Manifest includes SHA-256 hashes of written artefacts.

Scientific notes
----------------
- This stage does not change contracted scientific definitions.
- It operates on already-balanced `panel_monthly`, therefore “missing” unit-month
  rows are a pipeline failure upstream.

Output contract
----------------
This stage discovers `panel_monthly` as either ``.csv.gz`` or ``.csv``
(preference order from outputs.write_formats.monthly_panels).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from mv_firms_panels.core.config import AppConfig, candidate_format_order
from mv_firms_panels.core.hashing import sha256_file
from mv_firms_panels.io.paths import build_run_dir, panel_monthly_wide_path
from mv_firms_panels.io.writers import stable_sort_df, write_dataframe_csv, write_json


class VisualiseError(ValueError):
    """Raised when visualise fails."""


@dataclass(frozen=True)
class VisualiseResult:
    summaries_monthly: pd.DataFrame
    qa_summary: dict[str, object]
    summaries_monthly_path: Path | None = None
    figures_dir: Path | None = None
    qa_summary_path: Path | None = None
    manifest_path: Path | None = None


def _discover_panel_path(run_dir: Path, *, cfg: AppConfig) -> Path:
    pref = cfg.outputs.write_formats.get("monthly_panels", ["csv.gz", "csv"])
    candidates = candidate_format_order(pref, context="outputs.write_formats.monthly_panels")
    for fmt in candidates:
        p = panel_monthly_wide_path(run_dir=run_dir, fmt=fmt)
        if p.exists():
            return p
    return panel_monthly_wide_path(run_dir=run_dir, fmt=candidates[0] if candidates else "csv.gz")


def _safe_import_matplotlib():
    try:
        import matplotlib.pyplot as plt  # type: ignore

        return plt
    except Exception:
        return None


def _plot_timeseries(
    *,
    df: pd.DataFrame,
    out_dir: Path,
    level: str,
    x: str,
    y_cols: Sequence[str],
    title: str,
) -> list[Path]:
    """Create a deterministic time-series plot; returns written paths."""
    plt = _safe_import_matplotlib()
    if plt is None:
        return []

    plot_df = stable_sort_df(df, [x]).copy()

    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)

    for col in y_cols:
        if col in plot_df.columns:
            ax.plot(plot_df[x].astype(int), plot_df[col].astype(float))

    ax.set_title(title)
    ax.set_xlabel(x)
    ax.set_ylabel("value")

    ax.legend([c for c in y_cols if c in plot_df.columns], loc="best")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"timeseries_{level}".replace("/", "_")
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    fig.tight_layout()
    fig.savefig(png, dpi=150)
    fig.savefig(pdf)
    plt.close(fig)
    return [png, pdf]


def visualise(
    *,
    cfg: AppConfig,
    repo_root: Path,
    run_id: str,
    panel_monthly_path: Path | None = None,
    panel_monthly_df: pd.DataFrame | None = None,
    write_outputs: bool = True,
    make_plots: bool = True,
) -> VisualiseResult:
    """Produce deterministic summaries (and optional plots) from panel_monthly."""

    repo_root = Path(repo_root)
    run_dir = build_run_dir(
        repo_root=repo_root, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
    )

    qa: dict[str, object] = {
        "stage": "visualise",
        "run_id": run_id,
        "ts_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "steps": {},
        "plots": {"requested": bool(make_plots), "written": 0},
    }

    if panel_monthly_df is None:
        p = panel_monthly_path or _discover_panel_path(run_dir, cfg=cfg)
        if not p.exists():
            raise VisualiseError(f"panel_monthly not found: {p}")
        panel = pd.read_csv(p)
        qa["steps"]["read_panel_monthly"] = {
            "path": p.relative_to(repo_root).as_posix(),
            "n_rows": int(len(panel)),
        }
    else:
        panel = panel_monthly_df.copy()
        qa["steps"]["read_panel_monthly"] = {"source": "in-memory", "n_rows": int(len(panel))}

    required = ["level", "unit_id", "yyyymm", "year", "month"]
    missing = [c for c in required if c not in panel.columns]
    if missing:
        raise VisualiseError(f"panel_monthly missing required columns: {missing}")

    metric_cols = [
        "viirs_det_low",
        "viirs_det_nominal",
        "viirs_det_high",
        "viirs_det_nh",
        "viirs_frp_active_days",
        "viirs_frp_sum_daily_max_mw",
        "modis_det_low",
        "modis_det_nominal",
        "modis_det_high",
        "modis_det_nh",
        "modis_frp_active_days",
        "modis_frp_sum_daily_max_mw",
    ]
    metric_cols = [c for c in metric_cols if c in panel.columns]

    group = ["level", "yyyymm", "year", "month"]
    sums = panel.groupby(group, dropna=False)[metric_cols].sum(numeric_only=True).reset_index()
    sums = stable_sort_df(sums, ["level", "yyyymm"])

    qa["steps"]["monthly_totals"] = {
        "n_groups": int(len(sums)),
        "levels": sorted([str(x) for x in sums["level"].dropna().unique().tolist()]),
        "metric_cols": metric_cols,
    }

    summaries_monthly_path: Path | None = None
    figures_dir: Path | None = None
    qa_path: Path | None = None
    manifest_path: Path | None = None

    written_plots: list[Path] = []
    if write_outputs:
        out_dir = run_dir / "summaries"
        summaries_monthly_path = out_dir / "panel_monthly_totals_by_level.csv.gz"
        write_dataframe_csv(
            df=sums, path=summaries_monthly_path, sort_keys=["level", "yyyymm"], column_order=None
        )

        if make_plots:
            figures_dir = run_dir / "figures"
            y_cols = [c for c in ["viirs_det_nh", "modis_det_nh"] if c in sums.columns]
            for level in sorted([str(x) for x in sums["level"].dropna().unique().tolist()]):
                sub = sums.loc[sums["level"].astype(str) == level].copy()
                title = f"Detections (NH) per month — {level}"
                written_plots.extend(
                    _plot_timeseries(
                        df=sub,
                        out_dir=figures_dir,
                        level=level,
                        x="yyyymm",
                        y_cols=y_cols,
                        title=title,
                    )
                )

        qa["plots"]["written"] = int(len(written_plots))
        qa["plots"]["files"] = [p.name for p in sorted(written_plots)]

        qa_dir = run_dir / "qa"
        qa_path = qa_dir / "visualise_summary.json"
        write_json(obj=qa, path=qa_path)

        manifest: dict[str, object] = {
            "summaries_monthly_csv_gz": {
                "path": summaries_monthly_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(summaries_monthly_path),
            },
            "qa_summary_json": {
                "path": qa_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(qa_path),
            },
        }
        if written_plots:
            manifest["figures"] = [
                {"path": p.relative_to(repo_root).as_posix(), "sha256": sha256_file(p)}
                for p in sorted(written_plots)
            ]

        manifest_path = run_dir / "qa" / "visualise_manifest.json"
        write_json(obj=manifest, path=manifest_path)

    return VisualiseResult(
        summaries_monthly=sums,
        qa_summary=qa,
        summaries_monthly_path=summaries_monthly_path,
        figures_dir=figures_dir,
        qa_summary_path=qa_path,
        manifest_path=manifest_path,
    )
