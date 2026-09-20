# file: src/mv_firms_panels/stages/combine_panels.py
"""Stage: combine_panels (sensor-monthly → wide balanced panel_monthly).

Role in pipeline
----------------
- Input: per-sensor monthly tables from aggregate_monthly (VIIRS and/or MODIS).
- Output: a *wide* monthly panel containing both sensors' metrics, balanced to the
  full unit×month spine defined by unit_universe × configured time window.

Binding semantics
----------------
- Balanced panel: every unit_id in the unit universe must appear for every month
  in the time spine (no missing unit-month rows).
- Missingness semantics (binding):
  For unit-month with no detections (per sensor):
    * *_det_* = 0
    * *_frp_active_days = 0
    * *_frp_sum_daily_max_mw = 0.0
    * *_frp_mean_mw = null (NA)  [never 0]
- Determinism:
  * Stable sort by cfg.determinism.sort_keys.panel_monthly
  * Exact column set and column order enforced by cfg.determinism.column_order.panel_monthly
  * Output validates against configs/schemas/panel_monthly.schema.json

Extended metrics
----------------
The extended output includes pct_high_conf, NH persistence metrics
(days_active_nh, streak_max_nh) and FRP p95. These are intentionally outside
the contracted panel_monthly base schema and fixed column order.

To preserve schema validation while still producing the requested metrics, this
stage optionally writes a second artefact:
  - panel_monthly_ext.csv.gz (or .csv)
which contains the base schema columns plus the extended metrics (deterministic
order defined in-code).

Output formats
--------------
The wide and per-sensor monthly panels may be written as either:
- ``.csv.gz`` (default), or
- ``.csv`` (opt-in),
controlled by `outputs.write_formats.monthly_panels` preference order.

Readers/discovery accept either ``.csv.gz`` or ``.csv``.

Optional per-level splits
-------------------------
Optional per-level split outputs controlled by `outputs.split_panels_by_level`:
- panel_monthly_{level}.csv[.gz]
- panel_monthly_{level}_ext.csv[.gz] (if ext artefact is written)
These files are exact row subsets of the combined panel written under the same
deterministic sort and column rules.

Optional QC sidecar
-------------------
Optional QC sidecar output (opt-in; does not modify the contracted panel_monthly schema):
- out/runs/<run_id>/panel_monthly/panel_monthly_qc.<fmt>

Enabled via config:
- qc.write_panel_monthly_qc_sidecar: true

The QC sidecar contains per-unit-month flags derived from the contracted panel:
- {sensor}_has_any: any detections in that month for that sensor.
- {sensor}_in_coverage_flag: month is inside the configured sensor coverage window.
- {sensor}_structural_missing_flag: month is outside sensor coverage; metrics are structurally unavailable.
- {sensor}_low_information_month_flag: total detections below a per-sensor threshold, evaluated only inside coverage.
- {sensor}_frp_ok_flag: FRP consistency and minimum-support thresholds.

Thresholds are defined under config.qc.sensors.<sensor>.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from mv_firms_panels.core.config import AppConfig, candidate_format_order, choose_preferred_format
from mv_firms_panels.core.hashing import sha256_file, sha256_text, short_hash8, stable_json_dumps
from mv_firms_panels.core.schema import (
    enforce_exact_column_order,
    load_json_schema,
    validate_dataframe_against_schema,
)
from mv_firms_panels.core.time_spine import build_monthly_time_spine
from mv_firms_panels.io.paths import (
    build_run_dir,
    panel_monthly_ext_level_path,
    panel_monthly_ext_path,
    panel_monthly_ext_range_path,
    panel_monthly_qc_path,
    panel_monthly_qc_range_path,
    panel_monthly_wide_level_path,
    panel_monthly_wide_path,
    panel_monthly_wide_range_path,
    sensor_panel_monthly_path,
)
from mv_firms_panels.io.writers import stable_sort_df, write_dataframe_csv, write_json
from mv_firms_panels.stages.af_exports import write_rp1_af_exports


class CombinePanelsError(ValueError):
    """Raised when combine_panels fails."""


@dataclass(frozen=True)
class CombinePanelsResult:
    panel_monthly: pd.DataFrame
    qa_summary: dict[str, object]
    panel_path: Path | None = None
    panel_ext_path: Path | None = None
    qa_summary_path: Path | None = None
    manifest_path: Path | None = None


DATA_ACCESS_DOC_REL = "docs/data_access.md"
ROOT_RUNBOOK_REL = "README.md"


def _repo_relative_text(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()


def _stage2_combine_missing_input_message(*, label: str, detail: str, access_hint: str) -> str:
    return (
        f"Missing required Stage 2 input `{label}`: {detail}. "
        f"See {DATA_ACCESS_DOC_REL} and {ROOT_RUNBOOK_REL} for {access_hint}. "
        "Required by stage: rp1_mv_firms_panels combine_panels."
    )


def _derive_run_id(cfg: AppConfig, *, now_utc: datetime | None = None) -> str:
    if now_utc is None:
        now_utc = datetime.now(UTC)
    canon_json = stable_json_dumps(cfg.to_canonical_dict())
    h8 = short_hash8(sha256_text(canon_json))
    base = f"{cfg.project.name}_{h8}"
    if cfg.project.run_id_strategy.timestamp_utc:
        return f"{base}_{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
    return base


def _read_sensor_monthly_if_exists(
    run_dir: Path, *, cfg: AppConfig, sensor: str
) -> tuple[pd.DataFrame, Path | None]:
    """Read per-sensor monthly panel if present, accepting .csv.gz or .csv."""
    pref = cfg.outputs.write_formats.get("monthly_panels", ["csv.gz", "csv"])
    candidates = candidate_format_order(pref, context="outputs.write_formats.monthly_panels")
    for fmt in candidates:
        p = sensor_panel_monthly_path(run_dir=run_dir, sensor=sensor, fmt=fmt)
        if p.exists():
            return pd.read_csv(p), p
    return pd.DataFrame(), None


def _load_unit_universe(
    *,
    repo_root: Path,
    cfg: AppConfig,
    unit_universe_path: Path | None,
    unit_universe_df: pd.DataFrame | None,
) -> pd.DataFrame:
    if unit_universe_df is not None:
        uu = unit_universe_df.copy()
    else:
        path = unit_universe_path or (repo_root / cfg.io.inputs.unit_universe_csv)
        if not Path(path).exists():
            raise CombinePanelsError(
                _stage2_combine_missing_input_message(
                    label="unit_universe_csv",
                    detail=_repo_relative_text(repo_root, Path(path)),
                    access_hint="data acquisition, Stage 1 promotion, and local staging instructions",
                )
            )
        uu = pd.read_csv(path)

    if "unit_id" not in uu.columns:
        raise CombinePanelsError("unit_universe must include column 'unit_id'")
    if "unit_name" not in uu.columns:
        uu["unit_name"] = uu["unit_id"].astype(str)
    if "level" not in uu.columns:
        raise CombinePanelsError("unit_universe must include column 'level'")
    uu["unit_id"] = uu["unit_id"].astype(str)
    uu["unit_name"] = uu["unit_name"].astype("object")
    uu["level"] = uu["level"].astype("object")
    return uu


def _infer_time_window(
    *,
    cfg: AppConfig,
    viirs_monthly: pd.DataFrame,
    modis_monthly: pd.DataFrame,
    start_yyyymm: int | None,
    end_yyyymm: int | None,
) -> tuple[int, int]:
    if start_yyyymm is not None and end_yyyymm is not None:
        return int(start_yyyymm), int(end_yyyymm)

    cfg_start = getattr(cfg.processing.time_range, "start_yyyymm", None)
    cfg_end = getattr(cfg.processing.time_range, "end_yyyymm", None)
    if cfg_start is not None and cfg_end is not None:
        return int(cfg_start), int(cfg_end)

    candidates: list[int] = []
    for df in [viirs_monthly, modis_monthly]:
        if df is None or len(df) == 0:
            continue
        if "yyyymm" in df.columns:
            vals = pd.to_numeric(df["yyyymm"], errors="coerce").dropna().astype(int).tolist()
            candidates.extend(vals)

    if not candidates:
        raise CombinePanelsError(
            "Cannot infer time window: provide start_yyyymm/end_yyyymm or set processing.time_range"
        )

    return int(min(candidates)), int(max(candidates))


def _ensure_sensor_contract_columns(df: pd.DataFrame, *, sensor: str) -> pd.DataFrame:
    base = [
        f"{sensor}_det_low",
        f"{sensor}_det_nominal",
        f"{sensor}_det_high",
        f"{sensor}_det_nh",
        f"{sensor}_frp_active_days",
        f"{sensor}_frp_sum_daily_max_mw",
        f"{sensor}_frp_mean_mw",
    ]
    out = df.copy()
    for c in base:
        if c not in out.columns:
            out[c] = pd.NA
    return out


def _apply_sensor_coverage_mask(
    df: pd.DataFrame, *, cfg: AppConfig, sensor: str
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Apply structural missingness for months outside sensor coverage.

    Binding rule: if cfg.processing.sensor_coverage defines a
    coverage window for a sensor, then for unit-months outside that window all
    metric columns for that sensor must be NA/null (not zero-filled).

    This is applied *after* normal in-coverage fill semantics so that:
    - in-coverage missing unit-months become 0 for counts/sums (mean may be NA)
    - out-of-coverage unit-months remain NA across all sensor metric columns
    """

    cov = getattr(cfg.processing, "sensor_coverage", None)
    if not cov or sensor not in cov:
        return df, {
            "status": "SKIPPED",
            "sensor": sensor,
            "reason": "no_processing.sensor_coverage",
        }

    tr = cov.get(sensor)
    start = getattr(tr, "start_yyyymm", None)
    end = getattr(tr, "end_yyyymm", None)
    if start is None:
        # Config model validator should prevent this, but keep this safe.
        return df, {"status": "SKIPPED", "sensor": sensor, "reason": "coverage_missing_start"}

    start_i = int(start)
    end_i = int(end) if end is not None else None

    out = df.copy()
    if "yyyymm" not in out.columns:
        return out, {"status": "SKIPPED", "sensor": sensor, "reason": "missing_yyyymm"}

    yyyymm = pd.to_numeric(out["yyyymm"], errors="coerce")
    in_cov = yyyymm >= start_i
    if end_i is not None:
        in_cov = in_cov & (yyyymm <= end_i)
    out_cov = ~in_cov

    metric_cols = [c for c in out.columns if c.startswith(f"{sensor}_")]
    if not metric_cols:
        return out, {"status": "SKIPPED", "sensor": sensor, "reason": "no_metric_columns"}

    n_out = int(out_cov.sum())
    out.loc[out_cov, metric_cols] = pd.NA

    return out, {
        "status": "APPLIED",
        "sensor": sensor,
        "coverage_start_yyyymm": start_i,
        "coverage_end_yyyymm": end_i,
        "n_rows_outside_coverage": n_out,
    }


def _sensor_coverage_mask(panel: pd.DataFrame, *, cfg: AppConfig, sensor: str) -> pd.Series:
    """Return a boolean mask indicating whether each row is inside sensor coverage."""
    in_cov = pd.Series([True] * len(panel), index=panel.index, dtype="boolean")

    cov = getattr(cfg.processing, "sensor_coverage", None)
    if not cov or sensor not in cov or "yyyymm" not in panel.columns:
        return in_cov

    tr = cov.get(sensor)
    start = getattr(tr, "start_yyyymm", None)
    end = getattr(tr, "end_yyyymm", None)
    if start is None:
        return in_cov

    yyyymm = pd.to_numeric(panel["yyyymm"], errors="coerce")
    in_cov = yyyymm >= int(start)
    if end is not None:
        in_cov = in_cov & (yyyymm <= int(end))
    return in_cov.astype("boolean")


def _build_panel_monthly_qc_sidecar(*, panel: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    """Build the optional QC sidecar for panel_monthly.

    The QC sidecar is derived *only* from the contracted panel columns.
    It is intentionally separate to avoid expanding the panel_monthly schema.

    Semantics:
    - *_in_coverage_flag is True where the month is inside the sensor coverage window.
    - *_structural_missing_flag is True where the sensor is not available for that month.
    - *_low_information_month_flag is evaluated only inside coverage; outside coverage it is NA.
    """
    required_base = ["run_id", "level", "unit_id", "yyyymm", "year", "month"]
    missing = [c for c in required_base if c not in panel.columns]
    if missing:
        raise CombinePanelsError(
            f"Cannot build QC sidecar; missing columns in panel_monthly: {missing}"
        )

    out = panel.loc[:, required_base].copy()

    def _zero_int_series() -> pd.Series:
        return pd.Series([0] * len(panel), index=panel.index)

    def _zero_float_series() -> pd.Series:
        return pd.Series([0.0] * len(panel), index=panel.index)

    def _as_int(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce").fillna(0).astype("int64")

    def _as_float(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce").fillna(0.0).astype("float64")

    for sensor in ["viirs", "modis"]:
        in_cov = _sensor_coverage_mask(panel, cfg=cfg, sensor=sensor)
        structural_missing = (~in_cov.fillna(False)).astype("boolean")

        det_low = _as_int(panel.get(f"{sensor}_det_low", _zero_int_series()))
        det_nom = _as_int(panel.get(f"{sensor}_det_nominal", _zero_int_series()))
        det_high = _as_int(panel.get(f"{sensor}_det_high", _zero_int_series()))
        det_total = det_low + det_nom + det_high

        out[f"{sensor}_has_any"] = (det_total > 0).astype("boolean")
        out[f"{sensor}_in_coverage_flag"] = in_cov.astype("boolean")
        out[f"{sensor}_structural_missing_flag"] = structural_missing

        thr = None
        if getattr(cfg, "qc", None) is not None:
            thr = cfg.qc.sensors.get(sensor)

        low_info_min = (
            int(getattr(thr, "low_information_min_detections", 0)) if thr is not None else 0
        )
        low_info = pd.Series(pd.NA, index=panel.index, dtype="boolean")
        low_info.loc[in_cov.fillna(False)] = (
            det_total.loc[in_cov.fillna(False)] < low_info_min
        ).astype(bool)
        out[f"{sensor}_low_information_month_flag"] = low_info

        ad = _as_int(panel.get(f"{sensor}_frp_active_days", _zero_int_series()))
        ssum = _as_float(panel.get(f"{sensor}_frp_sum_daily_max_mw", _zero_float_series()))
        mean_raw = pd.to_numeric(
            panel.get(f"{sensor}_frp_mean_mw", pd.Series([pd.NA] * len(panel), index=panel.index)),
            errors="coerce",
        )

        # Consistency checks (binding semantics + arithmetic identity).
        # If active_days == 0: sum must be 0 and mean must be NA.
        is_zero = ad == 0
        mean_is_na = mean_raw.isna()
        consistent_zero = is_zero & (ssum == 0.0) & mean_is_na

        # If active_days > 0: mean must be finite and approximately equal to sum/active_days.
        denom = ad.where(ad > 0, 1)
        expected = ssum / denom
        tol = 1e-9
        consistent_pos = (~is_zero) & (~mean_is_na) & ((mean_raw - expected).abs() <= tol)

        consistent = consistent_zero | consistent_pos

        min_ad = int(getattr(thr, "frp_ok_min_active_days", 0)) if thr is not None else 0
        min_sum = (
            float(getattr(thr, "frp_ok_min_sum_daily_max_mw", 0.0)) if thr is not None else 0.0
        )
        enough_support = (ad >= min_ad) & (ssum >= min_sum)

        out[f"{sensor}_frp_ok_flag"] = (consistent & enough_support).astype("boolean")

    cols = list(required_base)
    for sensor in ["viirs", "modis"]:
        cols.extend(
            [
                f"{sensor}_has_any",
                f"{sensor}_in_coverage_flag",
                f"{sensor}_structural_missing_flag",
                f"{sensor}_low_information_month_flag",
                f"{sensor}_frp_ok_flag",
            ]
        )
    return out.loc[:, cols].copy()


def _build_panel_monthly_ext_frame(
    *, spine_rows: pd.DataFrame, base_column_order: Sequence[str]
) -> pd.DataFrame:
    """Build the richer monthly AF source frame used by RP1 AF exports.

    The AF export contract is bound to ``panel_monthly_ext`` plus the QC sidecar
    inputs. This helper therefore materialises the extended monthly frame in
    memory even when the standalone ``panel_monthly_ext`` artefact is not being
    written to disk.

    Scientific meaning is unchanged: the helper simply selects the already-
    computed richer metrics from the balanced ``spine_rows`` table and adds
    missing extension columns as ``NA`` where an upstream monthly source did not
    provide them.
    """
    ext_cols: list[str] = list(base_column_order)
    extensions = [
        "viirs_pct_high_conf",
        "viirs_days_active_nh",
        "viirs_streak_max_nh",
        "viirs_frp_p95_daily_max_mw",
        "modis_pct_high_conf",
        "modis_days_active_nh",
        "modis_streak_max_nh",
        "modis_frp_p95_daily_max_mw",
    ]
    merged = spine_rows.copy()
    for c in extensions:
        if c not in merged.columns:
            merged[c] = pd.NA
    ext_cols.extend(extensions)
    return merged.loc[:, ext_cols].copy()


def combine_panels(
    *,
    cfg: AppConfig,
    repo_root: Path,
    run_id: str | None = None,
    unit_universe_path: Path | None = None,
    unit_universe_df: pd.DataFrame | None = None,
    viirs_monthly_df: pd.DataFrame | None = None,
    modis_monthly_df: pd.DataFrame | None = None,
    start_yyyymm: int | None = None,
    end_yyyymm: int | None = None,
    write_outputs: bool = True,
    validate_schema: bool = True,
    write_extended_metrics: bool = True,
) -> CombinePanelsResult:
    repo_root = Path(repo_root)

    if run_id is None:
        run_id = _derive_run_id(cfg)

    qa: dict[str, object] = {
        "stage": "combine_panels",
        "run_id": run_id,
        "steps": {},
    }

    run_dir = build_run_dir(
        repo_root=repo_root, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
    )

    uu = _load_unit_universe(
        repo_root=repo_root,
        cfg=cfg,
        unit_universe_path=unit_universe_path,
        unit_universe_df=unit_universe_df,
    )
    qa["steps"]["unit_universe"] = {"n_rows": int(len(uu)), "n_levels": int(uu["level"].nunique())}

    viirs_path: Path | None = None
    modis_path: Path | None = None
    if viirs_monthly_df is not None:
        viirs = viirs_monthly_df.copy()
    else:
        viirs, viirs_path = _read_sensor_monthly_if_exists(run_dir, cfg=cfg, sensor="viirs")
    if modis_monthly_df is not None:
        modis = modis_monthly_df.copy()
    else:
        modis, modis_path = _read_sensor_monthly_if_exists(run_dir, cfg=cfg, sensor="modis")
    qa["steps"]["read_sensor_panels"] = {
        "viirs_rows": int(len(viirs)),
        "modis_rows": int(len(modis)),
    }

    sensor_panel_candidates = {
        "viirs": [
            _repo_relative_text(
                repo_root, sensor_panel_monthly_path(run_dir=run_dir, sensor="viirs", fmt="csv.gz")
            ),
            _repo_relative_text(
                repo_root, sensor_panel_monthly_path(run_dir=run_dir, sensor="viirs", fmt="csv")
            ),
        ],
        "modis": [
            _repo_relative_text(
                repo_root, sensor_panel_monthly_path(run_dir=run_dir, sensor="modis", fmt="csv.gz")
            ),
            _repo_relative_text(
                repo_root, sensor_panel_monthly_path(run_dir=run_dir, sensor="modis", fmt="csv")
            ),
        ],
    }
    if (
        viirs_monthly_df is None
        and "viirs" in cfg.processing.sensors_enabled
        and viirs_path is None
    ):
        raise CombinePanelsError(
            _stage2_combine_missing_input_message(
                label="sensor_panel_monthly:viirs",
                detail=f"checked {sensor_panel_candidates['viirs']}",
                access_hint="Stage 2 aggregate_monthly outputs or rerun instructions",
            )
        )
    if (
        modis_monthly_df is None
        and "modis" in cfg.processing.sensors_enabled
        and modis_path is None
    ):
        raise CombinePanelsError(
            _stage2_combine_missing_input_message(
                label="sensor_panel_monthly:modis",
                detail=f"checked {sensor_panel_candidates['modis']}",
                access_hint="Stage 2 aggregate_monthly outputs or rerun instructions",
            )
        )

    viirs = _ensure_sensor_contract_columns(viirs, sensor="viirs")
    modis = _ensure_sensor_contract_columns(modis, sensor="modis")

    s_ym, e_ym = _infer_time_window(
        cfg=cfg,
        viirs_monthly=viirs,
        modis_monthly=modis,
        start_yyyymm=start_yyyymm,
        end_yyyymm=end_yyyymm,
    )
    spine = build_monthly_time_spine(int(s_ym), int(e_ym))
    qa["steps"]["time_spine"] = {
        "start_yyyymm": int(s_ym),
        "end_yyyymm": int(e_ym),
        "n_months": int(len(spine)),
    }

    spine_rows = (
        uu.loc[:, ["level", "unit_id", "unit_name"]].drop_duplicates().merge(spine, how="cross")
    )

    key = ["level", "unit_id", "yyyymm"]
    if len(viirs) > 0:
        viirs_keyed = viirs.copy()
        for k in key:
            if k in viirs_keyed.columns:
                viirs_keyed[k] = viirs_keyed[k].astype(
                    "object" if k == "level" else ("int64" if k == "yyyymm" else str)
                )
        use_cols = key + [c for c in viirs_keyed.columns if c.startswith("viirs_")]
        spine_rows = spine_rows.merge(
            viirs_keyed.loc[:, list(dict.fromkeys(use_cols))], on=key, how="left"
        )
    else:
        for c in [c for c in viirs.columns if c.startswith("viirs_")]:
            spine_rows[c] = pd.NA

    if len(modis) > 0:
        modis_keyed = modis.copy()
        for k in key:
            if k in modis_keyed.columns:
                modis_keyed[k] = modis_keyed[k].astype(
                    "object" if k == "level" else ("int64" if k == "yyyymm" else str)
                )
        use_cols = key + [c for c in modis_keyed.columns if c.startswith("modis_")]
        spine_rows = spine_rows.merge(
            modis_keyed.loc[:, list(dict.fromkeys(use_cols))], on=key, how="left"
        )
    else:
        for c in [c for c in modis.columns if c.startswith("modis_")]:
            spine_rows[c] = pd.NA

    def _apply_sensor_fill(df: pd.DataFrame, sensor: str) -> pd.DataFrame:
        out = df.copy()

        for c in [
            f"{sensor}_det_low",
            f"{sensor}_det_nominal",
            f"{sensor}_det_high",
            f"{sensor}_det_nh",
        ]:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype("Int64")

        ad = f"{sensor}_frp_active_days"
        ssum = f"{sensor}_frp_sum_daily_max_mw"
        mean = f"{sensor}_frp_mean_mw"

        out[ad] = pd.to_numeric(out[ad], errors="coerce").fillna(0).astype("Int64")
        out[ssum] = pd.to_numeric(out[ssum], errors="coerce").fillna(0.0).astype("Float64")

        out[mean] = pd.to_numeric(out[mean], errors="coerce").astype("Float64")
        zero = out[ad] == 0
        out.loc[zero, mean] = pd.NA
        need_calc = (~zero) & out[mean].isna()
        out.loc[need_calc, mean] = out.loc[need_calc, ssum] / out.loc[need_calc, ad]
        out[mean] = out[mean].astype("Float64")
        return out

    spine_rows = _apply_sensor_fill(spine_rows, "viirs")
    spine_rows = _apply_sensor_fill(spine_rows, "modis")

    # Apply structural missingness outside sensor coverage windows.
    # This must run *after* in-coverage fill semantics so that out-of-coverage
    # months are not zero-filled.
    cov_steps: dict[str, object] = {}
    spine_rows, cov_steps["viirs"] = _apply_sensor_coverage_mask(
        spine_rows, cfg=cfg, sensor="viirs"
    )
    spine_rows, cov_steps["modis"] = _apply_sensor_coverage_mask(
        spine_rows, cfg=cfg, sensor="modis"
    )
    qa["steps"]["sensor_coverage"] = cov_steps

    spine_rows.insert(0, "run_id", run_id)

    sort_keys: Sequence[str] = cfg.determinism.sort_keys.get("panel_monthly", [])
    if sort_keys:
        spine_rows = stable_sort_df(spine_rows, sort_keys)

    col_order = cfg.determinism.column_order.get("panel_monthly")
    if col_order is None:
        raise CombinePanelsError("Config missing determinism.column_order.panel_monthly")

    panel = enforce_exact_column_order(
        spine_rows.loc[:, list(col_order)], col_order, allow_reorder=True
    )

    if validate_schema:
        schema_rel = cfg.outputs.schemas.get("panel_monthly")
        if not schema_rel:
            raise CombinePanelsError("Config missing outputs.schemas.panel_monthly")
        schema_path = (repo_root / schema_rel).resolve()
        schema_obj = load_json_schema(schema_path)
        panel = validate_dataframe_against_schema(
            df=panel, schema=schema_obj, expected_columns=col_order, allow_reorder=True
        )
        qa["steps"]["schema_validation"] = {"status": "PASS", "schema": schema_rel}
    else:
        qa["steps"]["schema_validation"] = {"status": "SKIPPED"}

    # Build the richer extended frame in memory regardless of whether the
    # standalone panel_monthly_ext artefact will also be written. The RP1 AF
    # exporter is locked to panel_monthly_ext semantics and therefore must not
    # depend on the optional write-to-disk toggle.
    panel_ext_for_af = _build_panel_monthly_ext_frame(
        spine_rows=spine_rows, base_column_order=col_order
    )

    panel_ext: pd.DataFrame | None = None
    if write_extended_metrics:
        panel_ext = panel_ext_for_af.copy()

    panel_path: Path | None = None
    panel_ext_path: Path | None = None
    qa_path: Path | None = None
    manifest_path: Path | None = None

    if write_outputs:
        pref = cfg.outputs.write_formats.get("monthly_panels", ["csv.gz", "csv"])
        fmt = choose_preferred_format(pref, context="outputs.write_formats.monthly_panels")

        qc_sidecar_path: Path | None = None
        panel_range_path: Path | None = None
        panel_ext_range_path: Path | None = None
        qc_sidecar_range_path: Path | None = None
        af_exports_manifest: dict[str, object] | None = None
        panel_qc_df: pd.DataFrame | None = None
        write_range_tagged = bool(getattr(cfg.outputs, "write_range_tagged_panels", False))

        panel_path = panel_monthly_wide_path(run_dir=run_dir, fmt=fmt)
        write_dataframe_csv(df=panel, path=panel_path, sort_keys=sort_keys, column_order=col_order)
        if write_range_tagged:
            panel_range_path = panel_monthly_wide_range_path(
                run_dir=run_dir,
                start_yyyymm=s_ym,
                end_yyyymm=e_ym,
                fmt=fmt,
            )
            write_dataframe_csv(
                df=panel, path=panel_range_path, sort_keys=sort_keys, column_order=col_order
            )

        if panel_ext is not None:
            panel_ext_path = panel_monthly_ext_path(run_dir=run_dir, fmt=fmt)
            write_dataframe_csv(
                df=panel_ext, path=panel_ext_path, sort_keys=sort_keys, column_order=None
            )
            if write_range_tagged:
                panel_ext_range_path = panel_monthly_ext_range_path(
                    run_dir=run_dir,
                    start_yyyymm=s_ym,
                    end_yyyymm=e_ym,
                    fmt=fmt,
                )
                write_dataframe_csv(
                    df=panel_ext, path=panel_ext_range_path, sort_keys=sort_keys, column_order=None
                )

        # Optional per-level split outputs
        split_by_level_manifest = None
        split_ext_by_level_manifest = None
        if bool(getattr(cfg.outputs, "split_panels_by_level", False)):
            levels = panel["level"].dropna().astype(str).unique().tolist()
            levels = sorted(levels)
            split_by_level_manifest = {}
            split_ext_by_level_manifest = {}
            for lvl in levels:
                mask = panel["level"].astype(str) == str(lvl)
                panel_lvl = panel.loc[mask].copy()
                lvl_path = panel_monthly_wide_level_path(run_dir=run_dir, level=lvl, fmt=fmt)
                write_dataframe_csv(
                    df=panel_lvl, path=lvl_path, sort_keys=sort_keys, column_order=col_order
                )
                split_by_level_manifest[str(lvl)] = {
                    "path": lvl_path.relative_to(repo_root).as_posix(),
                    "sha256": sha256_file(lvl_path),
                }
                if panel_ext is not None:
                    panel_ext_lvl = panel_ext.loc[mask].copy()
                    lvl_ext_path = panel_monthly_ext_level_path(run_dir=run_dir, level=lvl, fmt=fmt)
                    write_dataframe_csv(
                        df=panel_ext_lvl, path=lvl_ext_path, sort_keys=sort_keys, column_order=None
                    )
                    split_ext_by_level_manifest[str(lvl)] = {
                        "path": lvl_ext_path.relative_to(repo_root).as_posix(),
                        "sha256": sha256_file(lvl_ext_path),
                    }
            qa["steps"]["split_panels_by_level"] = {
                "status": "PASS",
                "enabled": True,
                "levels": levels,
            }
        else:
            qa["steps"]["split_panels_by_level"] = {"status": "SKIPPED", "enabled": False}

        # Build QC flags in-memory for AF _ext lineage regardless of whether the
        # separate panel_monthly_qc sidecar is materialised as its own artefact.
        panel_qc_df = _build_panel_monthly_qc_sidecar(panel=panel, cfg=cfg)

        # Additive RP1 AF merger-ready exports from the balanced combined outputs.
        af_exports = write_rp1_af_exports(
            panel_ext_df=panel_ext_for_af,
            unit_universe_df=uu,
            qc_df=panel_qc_df,
            cfg=cfg,
            repo_root=repo_root,
            run_dir=run_dir,
            fmt=fmt,
            sort_keys=sort_keys,
            validate_schema=validate_schema,
        )
        af_exports_manifest = af_exports.manifest
        qa["steps"]["rp1_af_exports"] = {
            "status": "PASS",
            "source": ["panel_monthly_ext", "panel_monthly_qc", "unit_universe"],
            "families": ["base", "ext"],
            "n_files": int(len(af_exports.paths)),
        }

        # Optional QC sidecar output (opt-in; separate artefact)
        if bool(getattr(cfg, "qc", None)) and bool(
            getattr(cfg.qc, "write_panel_monthly_qc_sidecar", False)
        ):
            qc_sidecar_path = panel_monthly_qc_path(run_dir=run_dir, fmt=fmt)
            write_dataframe_csv(
                df=panel_qc_df,
                path=qc_sidecar_path,
                sort_keys=sort_keys,
                column_order=list(panel_qc_df.columns),
            )
            if write_range_tagged:
                qc_sidecar_range_path = panel_monthly_qc_range_path(
                    run_dir=run_dir,
                    start_yyyymm=s_ym,
                    end_yyyymm=e_ym,
                    fmt=fmt,
                )
                write_dataframe_csv(
                    df=panel_qc_df,
                    path=qc_sidecar_range_path,
                    sort_keys=sort_keys,
                    column_order=list(panel_qc_df.columns),
                )
            qa["steps"]["panel_monthly_qc_sidecar"] = {
                "status": "PASS",
                "enabled": True,
                "path": qc_sidecar_path.relative_to(repo_root).as_posix(),
            }
        else:
            qa["steps"]["panel_monthly_qc_sidecar"] = {"status": "SKIPPED", "enabled": False}

        qa_dir = run_dir / "qa"
        qa_path = qa_dir / "combine_panels_summary.json"
        write_json(obj=qa, path=qa_path)

        manifest = {
            "panel_monthly": {
                "format": fmt,
                "path": panel_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(panel_path),
            },
            "qa_summary_json": {
                "path": qa_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(qa_path),
            },
        }

        if qc_sidecar_path is not None:
            manifest["panel_monthly_qc"] = {
                "format": fmt,
                "path": qc_sidecar_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(qc_sidecar_path),
            }
        if panel_ext_path is not None:
            manifest["panel_monthly_ext"] = {
                "format": fmt,
                "path": panel_ext_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(panel_ext_path),
            }
        if write_range_tagged:
            range_manifest = {
                "range": {"start_yyyymm": int(s_ym), "end_yyyymm": int(e_ym)},
                "panel_monthly": {
                    "format": fmt,
                    "path": (
                        panel_range_path.relative_to(repo_root).as_posix()
                        if panel_range_path is not None
                        else None
                    ),
                    "sha256": (
                        sha256_file(panel_range_path) if panel_range_path is not None else None
                    ),
                },
            }
            if panel_ext_range_path is not None:
                range_manifest["panel_monthly_ext"] = {
                    "format": fmt,
                    "path": panel_ext_range_path.relative_to(repo_root).as_posix(),
                    "sha256": sha256_file(panel_ext_range_path),
                }
            if qc_sidecar_range_path is not None:
                range_manifest["panel_monthly_qc"] = {
                    "format": fmt,
                    "path": qc_sidecar_range_path.relative_to(repo_root).as_posix(),
                    "sha256": sha256_file(qc_sidecar_range_path),
                }
            manifest["range_tagged_outputs"] = range_manifest
        if split_by_level_manifest is not None:
            manifest["panel_monthly_by_level"] = {"format": fmt, "levels": split_by_level_manifest}
        if split_ext_by_level_manifest is not None and len(split_ext_by_level_manifest) > 0:
            manifest["panel_monthly_ext_by_level"] = {
                "format": fmt,
                "levels": split_ext_by_level_manifest,
            }
        if af_exports_manifest is not None:
            manifest["rp1_af_exports"] = af_exports_manifest
        manifest_path = qa_dir / "combine_panels_manifest.json"
        write_json(obj=manifest, path=manifest_path)

    return CombinePanelsResult(
        panel_monthly=panel,
        qa_summary=qa,
        panel_path=panel_path,
        panel_ext_path=panel_ext_path,
        qa_summary_path=qa_path,
        manifest_path=manifest_path,
    )
