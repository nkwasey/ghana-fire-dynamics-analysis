# file: src/mv_firms_panels/stages/aggregate_monthly.py
"""Stage: aggregate_monthly (fires_canonical → per-sensor monthly metrics).

Role in pipeline
----------------
- Input: canonical per-detection table produced by `prepare_year` (stacked across levels).
- Output: sensor-specific monthly metrics at (level, unit_id, yyyymm).

This stage is intentionally *sensor-specific* so that:
- Each sensor can be processed independently,
- Later stages (combine_panels) can merge sensors into a wide, balanced panel.

Scientific outputs
------------------------------------
Per sensor, this stage computes and outputs:
- det_low, det_nominal, det_high, det_nh, pct_high_conf
- FRP (gated): daily max → monthly sum / p95 / mean; mean is NA when active_days=0
- Persistence on NH sample: days_active_nh, streak_max_nh

Schema contract note (important)
--------------------------------
The project panel_monthly JSON schema in configs/schemas/panel_monthly.schema.json
currently covers only counts and FRP mean/sum/active_days for both sensors (no
pct_high_conf or persistence). Therefore:
- The *sensor* monthly output from this stage is not validated against panel_monthly schema.
- The *combined* wide panel produced by combine_panels is validated against the schema.
- Extended metrics can be written by combine_panels to a separate artefact.

Determinism
-----------
- Stable sort by (level, unit_id, yyyymm) before returning/writing.
- Fixed column order for the *final combined* panel is enforced in combine_panels
  using cfg.determinism.column_order.panel_monthly.

Output-format behaviour
--------------------------
Per-sensor monthly outputs may be written as either:
- ``.csv.gz`` (default), or
- ``.csv`` (opt-in)
controlled by `outputs.write_formats.monthly_panels` preference order.

Time-window behaviour
--------------------------
Aggregation must respect a requested time window and must not “aggregate everything
in the run folder” unless explicitly requested.

- New optional start_yyyymm/end_yyyymm parameters.
- If not provided, deterministic fallback:
    (a) cfg.processing.sensor_time_ranges[sensor] if present and bounded
    (b) else cfg.processing.time_range if bounded
    (c) else no slicing
- Records effective window and rows pre/post filter in QA summary JSON.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

import pandas as pd
from mv_firms_panels.core.config import AppConfig, SensorName, choose_preferred_format
from mv_firms_panels.core.hashing import sha256_file, sha256_text, short_hash8, stable_json_dumps
from mv_firms_panels.core.time_spine import validate_yyyymm
from mv_firms_panels.io.paths import build_run_dir, sensor_panel_monthly_path
from mv_firms_panels.io.writers import stable_sort_df, write_dataframe_csv, write_json
from mv_firms_panels.metrics.detections import compute_monthly_detection_metrics
from mv_firms_panels.metrics.frp import (
    compute_daily_max_frp,
    compute_monthly_frp_metrics_from_daily,
)
from mv_firms_panels.metrics.persistence import compute_monthly_persistence_metrics_nh


class AggregateMonthlyError(ValueError):
    """Raised when aggregate_monthly fails."""


@dataclass(frozen=True)
class AggregateMonthlyResult:
    """Outputs and QA from aggregate_monthly."""

    panel_sensor_monthly: pd.DataFrame
    qa_summary: dict[str, object]
    panel_path: Path | None = None
    qa_summary_path: Path | None = None
    manifest_path: Path | None = None


def _derive_run_id(cfg: AppConfig, *, now_utc: datetime | None = None) -> str:
    if now_utc is None:
        now_utc = datetime.now(UTC)
    canon_json = stable_json_dumps(cfg.to_canonical_dict())
    h8 = short_hash8(sha256_text(canon_json))
    base = f"{cfg.project.name}_{h8}"
    if cfg.project.run_id_strategy.timestamp_utc:
        return f"{base}_{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
    return base


def _discover_fires_canonical_csvs(run_dir: Path, *, sensor: SensorName) -> list[Path]:
    d = run_dir / "fires_canonical" / sensor
    if not d.exists():
        return []
    return sorted(d.glob(f"fires_canonical_{sensor}_*.csv"))


def _read_many_csv(paths: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for p in paths:
        frames.append(pd.read_csv(p))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)



_ANNUAL_CANONICAL_RE = re.compile(r"^fires_canonical_(viirs|modis)_(\d{4})\.csv$")
_REQUIRED_AGG_COLUMNS: tuple[str, ...] = (
    "level",
    "unit_id",
    "yyyymm",
    "date_utc",
    "conf_cat",
    "frp_mw",
)


def _annual_partition_paths(
    paths: Sequence[Path], *, sensor: SensorName
) -> list[tuple[int, Path]] | None:
    """Return validated annual canonical partitions or ``None``.

    The production ``prepare-year`` stage emits exactly one canonical CSV per
    sensor-year.  Those files have disjoint calendar-month support, so they can
    be aggregated independently and concatenated without changing any monthly
    statistic.  Restricting the bounded-memory path to this naming contract
    preserves the legacy behaviour for arbitrary caller-supplied path lists.
    """
    out: list[tuple[int, Path]] = []
    seen: set[int] = set()
    for raw in paths:
        path = Path(raw)
        m = _ANNUAL_CANONICAL_RE.fullmatch(path.name)
        if m is None or m.group(1) != sensor:
            return None
        year = int(m.group(2))
        if year in seen:
            raise AggregateMonthlyError(
                f"Duplicate annual fires_canonical partition for sensor={sensor}, year={year}"
            )
        seen.add(year)
        out.append((year, path))
    return sorted(out, key=lambda item: item[0])


def _read_partition_required_columns(path: Path) -> pd.DataFrame:
    """Read only columns required by monthly aggregation.

    This materially reduces peak memory while preserving the exact scientific
    inputs used by the aggregation functions.
    """
    try:
        return pd.read_csv(path, usecols=list(_REQUIRED_AGG_COLUMNS))
    except ValueError as exc:
        raise AggregateMonthlyError(
            f"fires_canonical missing required columns for aggregation in {path}: {exc}"
        ) from exc


def _normalise_and_filter_partition(
    fires: pd.DataFrame,
    *,
    eff_start: int | None,
    eff_end: int | None,
) -> tuple[pd.DataFrame, int, int, set[int], set[int]]:
    """Apply the same type coercion and time filtering as the legacy path."""
    missing = [c for c in _REQUIRED_AGG_COLUMNS if c not in fires.columns]
    if missing:
        raise AggregateMonthlyError(
            f"fires_canonical missing required columns for aggregation: {missing}"
        )

    work = fires.copy()
    work["level"] = work["level"].astype("object")
    work["unit_id"] = work["unit_id"].astype(str)
    work["yyyymm"] = pd.to_numeric(work["yyyymm"], errors="coerce").astype("Int64")
    work = work.loc[work["yyyymm"].notna()].copy()
    work["yyyymm"] = work["yyyymm"].astype("int64")

    n_pre = int(len(work))
    months_pre = set(int(x) for x in work["yyyymm"].unique().tolist())
    if eff_start is not None:
        work = work.loc[work["yyyymm"] >= int(eff_start)].copy()
    if eff_end is not None:
        work = work.loc[work["yyyymm"] <= int(eff_end)].copy()
    n_post = int(len(work))
    months_post = set(int(x) for x in work["yyyymm"].unique().tolist()) if n_post else set()
    return work, n_pre, n_post, months_pre, months_post


def _aggregate_partition_frame(
    fires: pd.DataFrame,
    *,
    cfg: AppConfig,
    sensor: SensorName,
) -> tuple[pd.DataFrame, dict[str, int | float]]:
    """Aggregate one disjoint annual partition with production algorithms."""
    group_cols = ["level", "unit_id", "yyyymm"]

    det = compute_monthly_detection_metrics(fires, sensor=sensor, group_cols=group_cols)

    min_frp_mw = float(getattr(cfg.processing.frp_policy, "min_frp_mw", 0.0))
    daily = compute_daily_max_frp(
        fires,
        id_cols=["level", "unit_id"],
        min_frp_mw=min_frp_mw,
    )
    frp = compute_monthly_frp_metrics_from_daily(
        daily, sensor=sensor, id_cols=["level", "unit_id"]
    )

    pers_raw = compute_monthly_persistence_metrics_nh(fires, group_cols=group_cols)
    pers = pers_raw.loc[:, group_cols].copy()
    pers[f"{sensor}_days_active_nh"] = pers_raw["days_active_nh"].astype("int64")
    pers[f"{sensor}_streak_max_nh"] = pers_raw["streak_max_nh"].astype("int64")

    out = det.merge(frp, on=group_cols, how="outer").merge(pers, on=group_cols, how="outer")
    stats: dict[str, int | float] = {
        "det_groups": int(len(det)),
        "min_frp_mw": min_frp_mw,
        "frp_unit_days": int(len(daily)),
        "frp_groups": int(len(frp)),
        "persistence_groups": int(len(pers)),
    }
    return out, stats


def _finalise_sensor_monthly_output(
    out: pd.DataFrame, *, sensor: SensorName, run_id: str
) -> pd.DataFrame:
    """Apply the canonical post-aggregation typing and deterministic ordering."""
    if len(out) == 0:
        raise AggregateMonthlyError("fires_canonical is empty after aggregation")

    out = out.copy()
    out["year"] = (out["yyyymm"] // 100).astype("int64")
    out["month"] = (out["yyyymm"] % 100).astype("int64")
    out.insert(0, "run_id", run_id)

    for c in [
        f"{sensor}_det_low",
        f"{sensor}_det_nominal",
        f"{sensor}_det_high",
        f"{sensor}_det_nh",
    ]:
        if c in out.columns:
            out[c] = out[c].fillna(0).astype("int64")
    if f"{sensor}_pct_high_conf" in out.columns:
        out[f"{sensor}_pct_high_conf"] = (
            out[f"{sensor}_pct_high_conf"].fillna(0.0).astype("float64")
        )

    if f"{sensor}_days_active_nh" in out.columns:
        out[f"{sensor}_days_active_nh"] = out[f"{sensor}_days_active_nh"].fillna(0).astype("int64")
    if f"{sensor}_streak_max_nh" in out.columns:
        out[f"{sensor}_streak_max_nh"] = out[f"{sensor}_streak_max_nh"].fillna(0).astype("int64")

    ad = f"{sensor}_frp_active_days"
    ssum = f"{sensor}_frp_sum_daily_max_mw"
    mean = f"{sensor}_frp_mean_mw"
    p95 = f"{sensor}_frp_p95_daily_max_mw"

    if ad in out.columns:
        out[ad] = out[ad].fillna(0).astype("int64")
    if ssum in out.columns:
        out[ssum] = out[ssum].fillna(0.0).astype("float64")
    if mean in out.columns:
        out[mean] = out[mean].astype("Float64")
        zero = out[ad] == 0
        out.loc[zero, mean] = pd.NA
        need_calc = (~zero) & out[mean].isna()
        out.loc[need_calc, mean] = out.loc[need_calc, ssum] / out.loc[need_calc, ad]
    if p95 in out.columns:
        out[p95] = out[p95].astype("Float64")

    return stable_sort_df(out, ["level", "unit_id", "yyyymm"])


def _write_aggregate_outputs(
    *,
    cfg: AppConfig,
    repo_root: Path,
    run_id: str,
    sensor: SensorName,
    out: pd.DataFrame,
    qa: dict[str, object],
) -> tuple[Path, Path, Path]:
    run_dir = build_run_dir(
        repo_root=repo_root, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
    )
    pref = cfg.outputs.write_formats.get("monthly_panels", ["csv.gz", "csv"])
    fmt = choose_preferred_format(pref, context="outputs.write_formats.monthly_panels")
    panel_path = sensor_panel_monthly_path(run_dir=run_dir, sensor=sensor, fmt=fmt)
    write_dataframe_csv(
        df=out, path=panel_path, sort_keys=["level", "unit_id", "yyyymm"], column_order=None
    )

    qa_dir = run_dir / "qa"
    qa_path = qa_dir / f"aggregate_monthly_{sensor}_summary.json"
    write_json(obj=qa, path=qa_path)
    manifest = {
        "panel_sensor_monthly": {
            "format": fmt,
            "path": panel_path.relative_to(repo_root).as_posix(),
            "sha256": sha256_file(panel_path),
        },
        "qa_summary_json": {
            "path": qa_path.relative_to(repo_root).as_posix(),
            "sha256": sha256_file(qa_path),
        },
    }
    manifest_path = qa_dir / f"aggregate_monthly_{sensor}_manifest.json"
    write_json(obj=manifest, path=manifest_path)
    return panel_path, qa_path, manifest_path


def _aggregate_annual_partitions(
    *,
    cfg: AppConfig,
    repo_root: Path,
    sensor: SensorName,
    run_id: str,
    annual_paths: Sequence[tuple[int, Path]],
    start_yyyymm: int | None,
    end_yyyymm: int | None,
    write_outputs: bool,
) -> AggregateMonthlyResult:
    """Memory-bounded exact aggregation for disjoint prepare-year outputs."""
    eff_start, eff_end, window_source = _resolve_time_window(
        cfg, sensor=sensor, start_yyyymm=start_yyyymm, end_yyyymm=end_yyyymm
    )
    _validate_window(eff_start, eff_end)

    qa: dict[str, object] = {
        "stage": "aggregate_monthly",
        "sensor": sensor,
        "run_id": run_id,
        "steps": {},
    }
    parts: list[pd.DataFrame] = []
    n_rows_pre = 0
    n_rows_post = 0
    months_pre: set[int] = set()
    months_post: set[int] = set()
    det_groups = 0
    frp_unit_days = 0
    frp_groups = 0
    persistence_groups = 0
    min_frp_mw = float(getattr(cfg.processing.frp_policy, "min_frp_mw", 0.0))
    partition_rows: list[dict[str, object]] = []

    for year, path in annual_paths:
        raw = _read_partition_required_columns(path)
        filtered, n_pre, n_post, m_pre, m_post = _normalise_and_filter_partition(
            raw, eff_start=eff_start, eff_end=eff_end
        )
        source_years = {int(m) // 100 for m in m_pre}
        if source_years and source_years != {int(year)}:
            raise AggregateMonthlyError(
                "Canonical annual partition contains month keys outside its filename year: "
                f"path={path}, filename_year={year}, observed_years={sorted(source_years)}"
            )
        del raw
        n_rows_pre += n_pre
        n_rows_post += n_post
        months_pre.update(m_pre)
        months_post.update(m_post)
        partition_rows.append(
            {
                "year": int(year),
                "path": path.relative_to(repo_root).as_posix()
                if path.is_relative_to(repo_root)
                else path.as_posix(),
                "n_rows_pre": n_pre,
                "n_rows_post": n_post,
            }
        )
        if n_post == 0:
            continue
        part, stats = _aggregate_partition_frame(filtered, cfg=cfg, sensor=sensor)
        del filtered
        parts.append(part)
        det_groups += int(stats["det_groups"])
        frp_unit_days += int(stats["frp_unit_days"])
        frp_groups += int(stats["frp_groups"])
        persistence_groups += int(stats["persistence_groups"])

    qa["steps"]["read_fires_canonical"] = {
        "strategy": "annual_partition_streaming",
        "n_files": int(len(annual_paths)),
        "n_rows": int(n_rows_pre),
        "partitions": partition_rows,
    }
    qa["steps"]["time_window_filter"] = {
        "source": window_source,
        "start_yyyymm": None if eff_start is None else int(eff_start),
        "end_yyyymm": None if eff_end is None else int(eff_end),
        "n_rows_pre": int(n_rows_pre),
        "n_rows_post": int(n_rows_post),
        "n_distinct_yyyymm_pre": int(len(months_pre)),
        "n_distinct_yyyymm_post": int(len(months_post)),
    }
    qa["effective_time_window"] = {
        "source": window_source,
        "start_yyyymm": None if eff_start is None else int(eff_start),
        "end_yyyymm": None if eff_end is None else int(eff_end),
    }
    if n_rows_post == 0 or not parts:
        raise AggregateMonthlyError(
            "fires_canonical has 0 rows after applying time window filter "
            f"(start_yyyymm={eff_start}, end_yyyymm={eff_end}, source={window_source})"
        )

    qa["steps"]["detections"] = {"n_groups": int(det_groups)}
    qa["steps"]["frp"] = {
        "min_frp_mw": min_frp_mw,
        "n_unit_days": int(frp_unit_days),
        "n_groups": int(frp_groups),
    }
    qa["steps"]["persistence"] = {"n_groups": int(persistence_groups)}

    out = pd.concat(parts, ignore_index=True)
    # Annual prepare-year outputs are disjoint in yyyymm.  Assert that invariant
    # before finalising so a future upstream partitioning change fails closed.
    key_cols = ["level", "unit_id", "yyyymm"]
    if out.duplicated(key_cols).any():
        dup = out.loc[out.duplicated(key_cols, keep=False), key_cols].head(10)
        raise AggregateMonthlyError(
            "Annual fires_canonical partitions produced overlapping monthly groups; "
            f"bounded-memory aggregation cannot safely concatenate them. Examples: {dup.to_dict('records')}"
        )
    out = _finalise_sensor_monthly_output(out, sensor=sensor, run_id=run_id)

    panel_path: Path | None = None
    qa_path: Path | None = None
    manifest_path: Path | None = None
    if write_outputs:
        panel_path, qa_path, manifest_path = _write_aggregate_outputs(
            cfg=cfg,
            repo_root=repo_root,
            run_id=run_id,
            sensor=sensor,
            out=out,
            qa=qa,
        )
    return AggregateMonthlyResult(
        panel_sensor_monthly=out,
        qa_summary=qa,
        panel_path=panel_path,
        qa_summary_path=qa_path,
        manifest_path=manifest_path,
    )


def _resolve_time_window(
    cfg: AppConfig,
    *,
    sensor: SensorName,
    start_yyyymm: int | None,
    end_yyyymm: int | None,
) -> tuple[int | None, int | None, str]:
    """Resolve the effective (start_yyyymm, end_yyyymm) window for aggregation.

    Precedence (binding):
      1) Explicit args if either bound is provided.
      2) cfg.processing.sensor_time_ranges[sensor] if present and bounded.
      3) cfg.processing.time_range if bounded.
      4) No slicing.
    """
    if start_yyyymm is not None or end_yyyymm is not None:
        return start_yyyymm, end_yyyymm, "explicit"

    tr_map = getattr(getattr(cfg, "processing", object()), "sensor_time_ranges", None)
    if isinstance(tr_map, dict) and sensor in tr_map:
        tr = tr_map[sensor]
        st = getattr(tr, "start_yyyymm", None)
        en = getattr(tr, "end_yyyymm", None)
        if st is not None or en is not None:
            return st, en, "cfg.processing.sensor_time_ranges"

    tr = getattr(getattr(cfg, "processing", object()), "time_range", None)
    if tr is not None:
        st = getattr(tr, "start_yyyymm", None)
        en = getattr(tr, "end_yyyymm", None)
        if st is not None or en is not None:
            return st, en, "cfg.processing.time_range"

    return None, None, "none"


def _validate_window(start_yyyymm: int | None, end_yyyymm: int | None) -> None:
    if start_yyyymm is not None:
        validate_yyyymm(int(start_yyyymm))
    if end_yyyymm is not None:
        validate_yyyymm(int(end_yyyymm))
    if start_yyyymm is not None and end_yyyymm is not None:
        if int(start_yyyymm) > int(end_yyyymm):
            raise AggregateMonthlyError(
                f"start_yyyymm ({start_yyyymm}) must be <= end_yyyymm ({end_yyyymm})"
            )


def aggregate_monthly(
    *,
    cfg: AppConfig,
    repo_root: Path,
    sensor: SensorName,
    run_id: str | None = None,
    start_yyyymm: int | None = None,
    end_yyyymm: int | None = None,
    fires_canonical_paths: Sequence[Path] | None = None,
    fires_canonical_df: pd.DataFrame | None = None,
    write_outputs: bool = True,
) -> AggregateMonthlyResult:
    """Aggregate canonical detections into sensor-specific monthly metrics."""
    repo_root = Path(repo_root)

    if run_id is None:
        run_id = _derive_run_id(cfg)

    qa: dict[str, object] = {
        "stage": "aggregate_monthly",
        "sensor": sensor,
        "run_id": run_id,
        "steps": {},
    }

    if fires_canonical_df is None:
        run_dir = build_run_dir(
            repo_root=repo_root, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
        )
        candidate_paths = (
            list(fires_canonical_paths)
            if fires_canonical_paths is not None
            else _discover_fires_canonical_csvs(run_dir, sensor=sensor)
        )
        if not candidate_paths:
            raise AggregateMonthlyError(
                f"No fires_canonical CSVs found for sensor={sensor} under run_id={run_id}"
            )
        annual_paths = _annual_partition_paths(candidate_paths, sensor=sensor)
        if annual_paths is not None:
            return _aggregate_annual_partitions(
                cfg=cfg,
                repo_root=repo_root,
                sensor=sensor,
                run_id=run_id,
                annual_paths=annual_paths,
                start_yyyymm=start_yyyymm,
                end_yyyymm=end_yyyymm,
                write_outputs=write_outputs,
            )
        fires_canonical_paths = candidate_paths

    if fires_canonical_df is None:
        run_dir = build_run_dir(
            repo_root=repo_root, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
        )
        if fires_canonical_paths is None:
            fires_canonical_paths = _discover_fires_canonical_csvs(run_dir, sensor=sensor)
        if not fires_canonical_paths:
            raise AggregateMonthlyError(
                f"No fires_canonical CSVs found for sensor={sensor} under run_id={run_id}"
            )
        fires = _read_many_csv(fires_canonical_paths)
        qa["steps"]["read_fires_canonical"] = {
            "n_files": int(len(list(fires_canonical_paths))),
            "n_rows": int(len(fires)),
        }
    else:
        fires = fires_canonical_df.copy()
        qa["steps"]["read_fires_canonical"] = {"source": "in-memory", "n_rows": int(len(fires))}

    if len(fires) == 0:
        raise AggregateMonthlyError("fires_canonical is empty; cannot aggregate.")

    required = ["level", "unit_id", "yyyymm", "date_utc", "conf_cat", "frp_mw"]
    missing = [c for c in required if c not in fires.columns]
    if missing:
        raise AggregateMonthlyError(
            f"fires_canonical missing required columns for aggregation: {missing}"
        )

    fires = fires.copy()
    fires["level"] = fires["level"].astype("object")
    fires["unit_id"] = fires["unit_id"].astype(str)
    fires["yyyymm"] = pd.to_numeric(fires["yyyymm"], errors="coerce").astype("Int64")
    fires = fires.loc[fires["yyyymm"].notna()].copy()
    fires["yyyymm"] = fires["yyyymm"].astype("int64")

    eff_start, eff_end, window_source = _resolve_time_window(
        cfg, sensor=sensor, start_yyyymm=start_yyyymm, end_yyyymm=end_yyyymm
    )
    _validate_window(eff_start, eff_end)

    n_rows_pre = int(len(fires))
    months_pre = int(fires["yyyymm"].nunique(dropna=True))

    if eff_start is not None:
        fires = fires.loc[fires["yyyymm"] >= int(eff_start)].copy()
    if eff_end is not None:
        fires = fires.loc[fires["yyyymm"] <= int(eff_end)].copy()

    n_rows_post = int(len(fires))
    months_post = int(fires["yyyymm"].nunique(dropna=True)) if n_rows_post > 0 else 0

    qa["steps"]["time_window_filter"] = {
        "source": window_source,
        "start_yyyymm": None if eff_start is None else int(eff_start),
        "end_yyyymm": None if eff_end is None else int(eff_end),
        "n_rows_pre": n_rows_pre,
        "n_rows_post": n_rows_post,
        "n_distinct_yyyymm_pre": months_pre,
        "n_distinct_yyyymm_post": months_post,
    }
    qa["effective_time_window"] = {
        "source": window_source,
        "start_yyyymm": None if eff_start is None else int(eff_start),
        "end_yyyymm": None if eff_end is None else int(eff_end),
    }

    if n_rows_post == 0:
        raise AggregateMonthlyError(
            "fires_canonical has 0 rows after applying time window filter "
            f"(start_yyyymm={eff_start}, end_yyyymm={eff_end}, source={window_source})"
        )

    fires["year"] = (fires["yyyymm"] // 100).astype("int64")
    fires["month"] = (fires["yyyymm"] % 100).astype("int64")

    group_cols = ["level", "unit_id", "yyyymm"]

    det = compute_monthly_detection_metrics(fires, sensor=sensor, group_cols=group_cols)
    qa["steps"]["detections"] = {"n_groups": int(len(det))}

    min_frp_mw = float(getattr(cfg.processing.frp_policy, "min_frp_mw", 0.0))
    daily = compute_daily_max_frp(
        fires,
        id_cols=["level", "unit_id"],
        min_frp_mw=min_frp_mw,
    )
    frp = compute_monthly_frp_metrics_from_daily(daily, sensor=sensor, id_cols=["level", "unit_id"])
    qa["steps"]["frp"] = {
        "min_frp_mw": min_frp_mw,
        "n_unit_days": int(len(daily)),
        "n_groups": int(len(frp)),
    }

    pers_raw = compute_monthly_persistence_metrics_nh(fires, group_cols=group_cols)
    pers = pers_raw.loc[:, group_cols].copy()
    pers[f"{sensor}_days_active_nh"] = pers_raw["days_active_nh"].astype("int64")
    pers[f"{sensor}_streak_max_nh"] = pers_raw["streak_max_nh"].astype("int64")
    qa["steps"]["persistence"] = {"n_groups": int(len(pers))}

    out = det.merge(frp, on=group_cols, how="outer").merge(pers, on=group_cols, how="outer")

    out["year"] = (out["yyyymm"] // 100).astype("int64")
    out["month"] = (out["yyyymm"] % 100).astype("int64")
    out.insert(0, "run_id", run_id)

    for c in [
        f"{sensor}_det_low",
        f"{sensor}_det_nominal",
        f"{sensor}_det_high",
        f"{sensor}_det_nh",
    ]:
        if c in out.columns:
            out[c] = out[c].fillna(0).astype("int64")
    if f"{sensor}_pct_high_conf" in out.columns:
        out[f"{sensor}_pct_high_conf"] = (
            out[f"{sensor}_pct_high_conf"].fillna(0.0).astype("float64")
        )

    if f"{sensor}_days_active_nh" in out.columns:
        out[f"{sensor}_days_active_nh"] = out[f"{sensor}_days_active_nh"].fillna(0).astype("int64")
    if f"{sensor}_streak_max_nh" in out.columns:
        out[f"{sensor}_streak_max_nh"] = out[f"{sensor}_streak_max_nh"].fillna(0).astype("int64")

    ad = f"{sensor}_frp_active_days"
    ssum = f"{sensor}_frp_sum_daily_max_mw"
    mean = f"{sensor}_frp_mean_mw"
    p95 = f"{sensor}_frp_p95_daily_max_mw"

    if ad in out.columns:
        out[ad] = out[ad].fillna(0).astype("int64")
    if ssum in out.columns:
        out[ssum] = out[ssum].fillna(0.0).astype("float64")
    if mean in out.columns:
        out[mean] = out[mean].astype("Float64")
        zero = out[ad] == 0
        out.loc[zero, mean] = pd.NA
        need_calc = (~zero) & out[mean].isna()
        out.loc[need_calc, mean] = out.loc[need_calc, ssum] / out.loc[need_calc, ad]
    if p95 in out.columns:
        out[p95] = out[p95].astype("Float64")

    out = stable_sort_df(out, ["level", "unit_id", "yyyymm"])

    panel_path: Path | None = None
    qa_path: Path | None = None
    manifest_path: Path | None = None

    if write_outputs:
        run_dir = build_run_dir(
            repo_root=repo_root, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
        )

        pref = cfg.outputs.write_formats.get("monthly_panels", ["csv.gz", "csv"])
        fmt = choose_preferred_format(pref, context="outputs.write_formats.monthly_panels")

        panel_path = sensor_panel_monthly_path(run_dir=run_dir, sensor=sensor, fmt=fmt)
        write_dataframe_csv(
            df=out, path=panel_path, sort_keys=["level", "unit_id", "yyyymm"], column_order=None
        )

        qa_dir = run_dir / "qa"
        qa_path = qa_dir / f"aggregate_monthly_{sensor}_summary.json"
        write_json(obj=qa, path=qa_path)

        manifest = {
            "panel_sensor_monthly": {
                "format": fmt,
                "path": panel_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(panel_path),
            },
            "qa_summary_json": {
                "path": qa_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(qa_path),
            },
        }
        manifest_path = qa_dir / f"aggregate_monthly_{sensor}_manifest.json"
        write_json(obj=manifest, path=manifest_path)

    return AggregateMonthlyResult(
        panel_sensor_monthly=out,
        qa_summary=qa,
        panel_path=panel_path,
        qa_summary_path=qa_path,
        manifest_path=manifest_path,
    )
