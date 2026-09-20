# file: src/mv_firms_panels/stages/prepare_year.py
"""
Stage: prepare_year (annual points → fires_canonical per-detection table).

This stage processes one sensor-year of FIRMS-like active fire points into the project’s
contracted detection table (`fires_canonical_*`). The processing pipeline is:

1) Resolve and read a single annual points file (unless points_gdf is supplied).
2) Standardise raw columns into the internal working schema:
   - latitude/longitude, FRP, and TYPE are coerced to numeric
   - confidence is mapped to conf_cat ∈ {"l","n","h"} using sensor-specific rules
   - acquisition date/time are normalised to *strings* for schema compliance:
        acq_date, date_utc: "YYYY-MM-DD"
        acq_datetime_utc:  "YYYY-MM-DDTHH:MM:SSZ"  (UTC; RFC3339 with 'Z')
     and yyyymm is derived deterministically from acq_date.
3) Filter canonical TYPE == 0 detections before land masking and deduplication.
4) Optionally apply a land mask (if enabled and available):
   - points are split into inside-land vs outside-land using a configurable predicate
   - if require_land_intersection is True, outside-land points are dropped from
     the contracted output, but counts are still recorded in QA.
4) Deterministically deduplicate points using a configurable key (rounded lat/lon) and
   tie-break strategy.
5) Join points to one or more polygon boundary levels (e.g., district, ACZ). Points that
   do not intersect any unit polygon for a given level are dropped for that level
   (unit_id is required by the fires_canonical schema).
6) Enforce deterministic sort and exact column order, then (optionally) validate the
   DataFrame against the JSON schema.

Contractual bindings (CP)
-------------------------
- Sensors: viirs and modis.
- Confidence: conf_cat ∈ {"l","n","h"} (strict mapping; errors on unknown values).
- Determinism:
  * Stable sorting (mergesort) for reproducible row order.
  * Exact column order from cfg.determinism.column_order["fires_canonical"].
- Output contract:
  * fires_canonical validates against cfg.outputs.schemas["fires_canonical"].
  * TYPE is retained in fires_canonical and only TYPE == 0 detections are allowed through.
  * One row per (deduplicated detection × polygon level), after dropping unmatched points.

Optional QA exports – best-effort, behind toggles
------------------------------------------------------------
If cfg.outputs.prepare_year_qa_exports.enabled is True, additional diagnostics are written
under the run’s QA directory, without changing the contracted fires_canonical output:

- Cleaned/deduplicated points as GeoPackage (and optionally as Shapefile).
- Outside-land points as GeoPackage/Shapefile (only when a land mask split occurs).
- An outside-land plot (PNG, optional PDF) named:
    prepare_year_outside_land_<sensor>_<year>.png/.pdf

Outside-land plot specification (your requested visual update)
--------------------------------------------------------------
When the plot is enabled and a land mask split occurs, the plot shows:
1) All fires (for that sensor-year) as red points.
2) The land-mask polygon boundary as the outline (map context).
3) Outside-land fires highlighted in blue (plotted on top of red).
4) A legend in the top-right.
5) A latitude/longitude grid.
6) A descriptive title: "Ghana <SENSOR> fire (FIRMS active fire points) - <YEAR>"
7) A second title line with counts:
      inside: <n_inside> | outside: <n_outside> | Total: <n_points>

If the number of points exceeds plot_max_points, points are downsampled deterministically
(random_state=0) and this is recorded in the QA plot status.

Notes
-----
- All paths written to manifests/QA JSON are repo-relative where possible (no absolute paths).
- QA exports are best-effort: failures to write geospatial files or plots are recorded in the
  QA summary/manifest, but do not fail the stage.
"""


from __future__ import annotations

import glob
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from mv_firms_panels.core.config import AppConfig, SensorName
from mv_firms_panels.core.hashing import sha256_file, sha256_text, short_hash8, stable_json_dumps
from mv_firms_panels.core.schema import (
    enforce_exact_column_order,
    load_json_schema,
    validate_dataframe_against_schema,
)
from mv_firms_panels.core.time_spine import (
    acq_datetime_utc_from_date_time,
    parse_acq_date_series,
    yyyymm_from_acq_date_series,
)
from mv_firms_panels.geo.joins import join_points_to_units
from mv_firms_panels.geo.masks import split_points_by_land_mask
from mv_firms_panels.io.paths import build_run_dir
from mv_firms_panels.io.readers import read_points, read_polygons
from mv_firms_panels.io.writers import (
    WriteError,
    stable_sort_df,
    write_dataframe_csv,
    write_geofile,
    write_json,
)


class PrepareYearError(ValueError):
    """Raised when prepare_year cannot complete under the current configuration."""


@dataclass(frozen=True)
class PrepareYearResult:
    """Outputs and QA from prepare_year."""

    fires_canonical: pd.DataFrame
    qa_summary: dict[str, object]
    fires_canonical_path: Path | None = None
    qa_summary_path: Path | None = None
    manifest_path: Path | None = None


DATA_ACCESS_DOC_REL = "docs/data_access.md"
ROOT_RUNBOOK_REL = "README.md"


def _repo_relative_text(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()


def _stage2_prepare_year_missing_input_message(
    *,
    label: str,
    detail: str,
    access_hint: str,
) -> str:
    return (
        f"Missing required Stage 2 input `{label}`: {detail}. "
        f"See {DATA_ACCESS_DOC_REL} and {ROOT_RUNBOOK_REL} for {access_hint}. "
        "Required by stage: rp1_mv_firms_panels prepare_year."
    )


# -----------------------------------------------------------------------------
# Path resolution (annual points)
# -----------------------------------------------------------------------------


def resolve_annual_points_path(
    *, repo_root: Path, file_glob: str, sensor: SensorName, year: int
) -> Path:
    """
    Resolve a single annual points file for (sensor, year) from a glob pattern.

    Determinism:
    - Candidate paths are sorted lexicographically.
    - Ambiguity (multiple matches for the year) is an error.

    Year matching is conservative: the 4-digit year must appear as a standalone
    numeric token in the filename stem (regex: (?<!\\d)YYYY(?!\\d)).
    """
    pattern = (repo_root / file_glob).as_posix()
    candidates = sorted([Path(p) for p in glob.glob(pattern)])
    if not candidates:
        raise PrepareYearError(
            _stage2_prepare_year_missing_input_message(
                label=f"firms_points[{sensor}]",
                detail=f"sensor={sensor} year={year} file_glob={file_glob!r}",
                access_hint="FIRMS download, rename, and local staging instructions",
            )
        )

    year_s = str(int(year))
    rx = re.compile(rf"(?<!\d){re.escape(year_s)}(?!\d)")

    year_hits = [p for p in candidates if rx.search(p.stem)]
    if len(year_hits) == 1:
        return year_hits[0]
    if len(year_hits) == 0:
        raise PrepareYearError(
            _stage2_prepare_year_missing_input_message(
                label=f"firms_points[{sensor}]",
                detail=(
                    f"matched {len(candidates)} file(s) under file_glob={file_glob!r}, "
                    f"but none matched year token {year_s}"
                ),
                access_hint="FIRMS rename-convention and local staging instructions",
            )
        )
    raise PrepareYearError(
        f"Ambiguous annual file resolution for {sensor=} {year=}. Year-token candidates: "
        f"{[p.as_posix() for p in year_hits]}"
    )


def _rel_source_file(repo_root: Path, src_path: Path) -> str:
    """Return a deterministic, repo-relative source_file string when possible."""
    try:
        return src_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return src_path.name


# -----------------------------------------------------------------------------
# Normalisation helpers
# -----------------------------------------------------------------------------


def _ensure_points_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.geometry.name not in gdf.columns:
        raise PrepareYearError("Input points GeoDataFrame has no active geometry column")
    if len(gdf) > 0:
        g0 = gdf.geometry.iloc[0]
        if g0 is not None and getattr(g0, "geom_type", None) != "Point":
            raise PrepareYearError(
                f"Expected Point geometries; got {getattr(g0, 'geom_type', None)!r}"
            )
    if gdf.crs is None:
        # FIRMS points are lon/lat by convention; treat missing CRS as EPSG:4326.
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    return gdf


def _normalise_hhmm(series: pd.Series, *, strict: bool = True) -> pd.Series:
    """Normalise FIRMS HHMM (string/int/float) to zero-padded 4-char strings."""

    def _one(x: object) -> str | None:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        try:
            n = int(str(x).strip())
        except Exception:
            return None
        if n < 0 or n > 2359:
            return None
        hh = n // 100
        mm = n % 100
        if hh > 23 or mm > 59:
            return None
        return f"{hh:02d}{mm:02d}"

    out = series.apply(_one).astype("object")
    if strict and out.isna().any():
        raise PrepareYearError(
            f"acq_time contains {int(out.isna().sum())} invalid/missing values under strict=True"
        )
    return out


def _coerce_type_code(type_series: pd.Series, *, strict: bool = True) -> pd.Series:
    """Coerce FIRMS TYPE to canonical integer codes under strict validation."""

    type_num = pd.to_numeric(type_series, errors="coerce")
    out = pd.Series(pd.NA, index=type_series.index, dtype="Int64")

    valid = type_num.notna()
    whole = valid & (type_num % 1 == 0)
    non_negative = valid & (type_num >= 0)
    keep = whole & non_negative
    out.loc[keep] = type_num.loc[keep].astype("int64")

    if strict:
        if (~valid).any():
            raise PrepareYearError("type contains missing or non-numeric values under strict=True")
        if (~whole).any():
            raise PrepareYearError("type contains non-integer values under strict=True")
        if (~non_negative).any():
            raise PrepareYearError("type contains negative values under strict=True (invalid)")

    return out


def _map_conf_cat(
    *, sensor: SensorName, confidence: pd.Series, cfg: AppConfig, strict: bool = True
) -> pd.Series:
    if sensor == "viirs":
        from mv_firms_panels.sensors.viirs import viirs_conf_cat_from_confidence

        return viirs_conf_cat_from_confidence(
            confidence, viirs_map=cfg.processing.confidence_model.viirs_map, strict=strict
        )

    if sensor == "modis":
        from mv_firms_panels.sensors.modis import modis_conf_cat_from_confidence

        return modis_conf_cat_from_confidence(
            confidence,
            thresholds_pct=cfg.processing.confidence_model.modis_thresholds_pct,
            strict=strict,
        )

    raise PrepareYearError(f"Unsupported sensor: {sensor!r}")


def _standardise_points(
    *, points: gpd.GeoDataFrame, sensor: SensorName, cfg: AppConfig, strict: bool = True
) -> gpd.GeoDataFrame:
    """Rename + type-coerce raw points into the internal canonical working set."""
    points = _ensure_points_geometry(points)

    colmap = cfg.io.inputs.firms_points[sensor].column_map  # canonical -> source
    required_keys = ["latitude", "longitude", "acq_date", "acq_time", "confidence", "frp", "type"]

    missing: list[str] = []
    for k in required_keys:
        src = colmap.get(k)
        if src is None:
            missing.append(f"<missing mapping:{k}>")
        elif src not in points.columns:
            missing.append(src)

    if strict and missing:
        raise PrepareYearError(f"Missing required source columns for {sensor}: {missing}")

    inv = {v: k for k, v in colmap.items() if v in points.columns}  # source -> canonical
    keep_src = [v for v in colmap.values() if v in points.columns]

    work = points.loc[:, keep_src + [points.geometry.name]].rename(columns=inv).copy()

    # Optional fields (present in schema properties)
    for opt in ["daynight", "satellite"]:
        if opt not in work.columns:
            work[opt] = pd.NA

    # Numeric coercion
    work["latitude"] = pd.to_numeric(work["latitude"], errors="coerce")
    work["longitude"] = pd.to_numeric(work["longitude"], errors="coerce")
    work["frp"] = pd.to_numeric(work["frp"], errors="coerce")
    work["type"] = _coerce_type_code(work["type"], strict=strict)

    if strict:
        if work["latitude"].isna().any() or work["longitude"].isna().any():
            raise PrepareYearError(
                "latitude/longitude contain non-numeric or missing values under strict=True"
            )
        if work["frp"].isna().any():
            raise PrepareYearError("frp contains non-numeric or missing values under strict=True")
        if (work["frp"] < 0).any():
            raise PrepareYearError("frp contains negative values under strict=True (invalid)")

    # Date/time normalisation
    dt_date = parse_acq_date_series(work["acq_date"], strict=strict)
    acq_date_str = dt_date.dt.strftime("%Y-%m-%d")
    acq_time_str = _normalise_hhmm(work["acq_time"], strict=strict)

    dt_ts = acq_datetime_utc_from_date_time(acq_date_str, acq_time_str, strict=strict)
    acq_datetime_str = dt_ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    yyyymm = yyyymm_from_acq_date_series(acq_date_str, strict=strict).astype("int64")

    conf_cat = _map_conf_cat(sensor=sensor, confidence=work["confidence"], cfg=cfg, strict=strict)

    # Optional policy: drop low confidence detections
    if not cfg.processing.confidence_model.include_low:
        keep = conf_cat != "l"
        work = work.loc[keep].copy()
        acq_date_str = acq_date_str.loc[keep]
        acq_time_str = acq_time_str.loc[keep]
        acq_datetime_str = acq_datetime_str.loc[keep]
        yyyymm = yyyymm.loc[keep]
        conf_cat = conf_cat.loc[keep]

    # Promote canonical working fields used downstream
    work["acq_date"] = acq_date_str
    work["acq_time_utc"] = acq_time_str
    work["acq_datetime_utc"] = acq_datetime_str
    work["yyyymm"] = yyyymm
    work["date_utc"] = acq_date_str
    work["conf_cat"] = conf_cat
    work["frp_mw"] = work["frp"].astype(float)

    for c in ["daynight", "satellite", "conf_cat"]:
        work[c] = work[c].astype("object")
    work["type"] = work["type"].astype("int64")

    return work


# -----------------------------------------------------------------------------
# Deduplication
# -----------------------------------------------------------------------------


def _conf_rank(conf_cat: pd.Series) -> pd.Series:
    return conf_cat.map({"l": 0, "n": 1, "h": 2}).astype("float").fillna(-1.0)


def _format_round(series: pd.Series, decimals: int) -> pd.Series:
    r = series.round(decimals)
    fmt = f"{{0:.{decimals}f}}"
    return r.map(lambda x: fmt.format(float(x)) if pd.notna(x) else "")


def _build_dedup_key(
    *,
    sensor: SensorName,
    acq_date: pd.Series,
    acq_time_utc: pd.Series,
    lat: pd.Series,
    lon: pd.Series,
    satellite: pd.Series,
    decimals: int,
    include_satellite: bool,
) -> pd.Series:
    lat_s = _format_round(lat, decimals)
    lon_s = _format_round(lon, decimals)

    if include_satellite:
        sat_s = satellite.fillna("").astype("object").map(lambda x: str(x).strip())
    else:
        sat_s = pd.Series([""] * len(acq_date), index=acq_date.index, dtype="object")

    sensor_s = pd.Series([sensor] * len(acq_date), index=acq_date.index, dtype="object")

    # Deterministic vectorised concatenation
    out = sensor_s.astype("string")
    for p in [sat_s, acq_date.astype("object"), acq_time_utc.astype("object"), lat_s, lon_s]:
        out = out + "|" + p.astype("string")
    return out.astype("object")


def deduplicate_points(
    *, points: gpd.GeoDataFrame, sensor: SensorName, cfg: AppConfig
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    """Deduplicate points deterministically and return (kept_points, QA stats)."""
    if len(points) == 0:
        pts = points.copy()
        pts["dedup_key"] = pd.Series([], dtype="object")
        pts["was_dedup_kept"] = pd.Series([], dtype="bool")
        return pts, {"n_in": 0, "n_kept": 0, "n_dropped": 0}

    dcfg = cfg.processing.deduplication
    pts = points.copy()

    pts["dedup_key"] = _build_dedup_key(
        sensor=sensor,
        acq_date=pts["acq_date"],
        acq_time_utc=pts["acq_time_utc"],
        lat=pts["latitude"],
        lon=pts["longitude"],
        satellite=pts["satellite"],
        decimals=int(dcfg.latlon_round_decimals),
        include_satellite=bool(dcfg.include_satellite_in_key),
    )

    tie_break = list(dcfg.tie_break)
    work = pts.copy()

    # Add tie-break helper columns deterministically.
    if "max_conf_cat_rank" in tie_break:
        work["_conf_rank"] = _conf_rank(work["conf_cat"])

    # Stable row order to make 'stable_first' explicit even if index is arbitrary.
    work["_row_order"] = pd.Series(range(len(work)), index=work.index, dtype="int64")

    sort_cols: list[str] = ["dedup_key"]
    ascending: list[bool] = [True]

    for tb in tie_break:
        if tb == "max_frp_mw":
            sort_cols.append("frp_mw")
            ascending.append(False)
        elif tb == "max_conf_cat_rank":
            sort_cols.append("_conf_rank")
            ascending.append(False)
        elif tb == "stable_first":
            sort_cols.append("_row_order")
            ascending.append(True)
        else:
            raise PrepareYearError(f"Unknown tie_break option: {tb!r}")

    work = work.sort_values(sort_cols, ascending=ascending, kind="mergesort")

    kept_flags = ~work["dedup_key"].duplicated(keep="first")
    work["was_dedup_kept"] = kept_flags.astype(bool)

    kept = work.loc[kept_flags].copy()
    kept = kept.drop(columns=["_conf_rank", "_row_order"], errors="ignore")

    stats = {
        "n_in": int(len(points)),
        "n_kept": int(len(kept)),
        "n_dropped": int(len(points) - len(kept)),
        "latlon_round_decimals": int(dcfg.latlon_round_decimals),
        "include_satellite_in_key": bool(dcfg.include_satellite_in_key),
        "tie_break": list(dcfg.tie_break),
    }
    return kept, stats


# -----------------------------------------------------------------------------
# Run-id derivation (optional)
# -----------------------------------------------------------------------------


def _derive_run_id(cfg: AppConfig, *, now_utc: datetime | None = None) -> str:
    """Derive run_id from a stable hash of the config snapshot."""
    if now_utc is None:
        now_utc = datetime.now(UTC)
    canon_json = stable_json_dumps(cfg.to_canonical_dict())
    h8 = short_hash8(sha256_text(canon_json))
    base = f"{cfg.project.name}_{h8}"
    if cfg.project.run_id_strategy.timestamp_utc:
        return f"{base}_{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
    return base


# -----------------------------------------------------------------------------
# QA exports
# -----------------------------------------------------------------------------


def _maybe_plot_outside_land(
    *,
    all_points: gpd.GeoDataFrame,
    outside_points: gpd.GeoDataFrame,
    land_mask: gpd.GeoDataFrame,
    land_stats: dict[str, float],
    sensor: SensorName,
    year: int,
    out_png: Path | None,
    out_pdf: Path | None,
    max_points: int,
) -> dict[str, object]:
    """Best-effort outside-land plot matching the project QA specification.

    This is a QA-only artefact. It MUST NOT influence contracted fires_canonical outputs.

    Plot contents
    -------------
    - All fires (sensor-year) in red.
    - Land-mask outline (boundary) as map context.
    - Outside-land fires highlighted in blue (plotted on top of red).
    - Legend (top-right), lat/lon grid, descriptive title + counts line.

    Performance / determinism
    -------------------------
    - If point counts exceed max_points, points are downsampled deterministically
      (random_state=0). Counts shown in the title always come from land_stats
      computed on the full point set.
    """
    status: dict[str, object] = {
        "status": "SKIPPED",
        "error": None,
        "png": None,
        "pdf": None,
        "n_points_total": int(round(float(land_stats.get("n_points", float(len(all_points)))))),
        "n_inside": int(round(float(land_stats.get("n_inside", 0.0)))),
        "n_outside": int(round(float(land_stats.get("n_outside", float(len(outside_points)))))),
        "max_points": int(max_points),
        "sampled_red": False,
        "sampled_blue": False,
        "n_plotted_red": None,
        "n_plotted_blue": None,
    }

    if out_png is None and out_pdf is None:
        status["status"] = "SKIPPED_DISABLED"
        return status

    if len(all_points) == 0:
        status["status"] = "SKIPPED_EMPTY"
        return status

    # Lazy import: keep pipeline usable even if matplotlib is not available.
    try:
        import matplotlib  # type: ignore

        matplotlib.use("Agg", force=True)  # headless-safe
        import matplotlib.pyplot as plt  # type: ignore
        from matplotlib.lines import Line2D  # type: ignore
    except Exception as e:
        status["status"] = "FAILED"
        status["error"] = f"matplotlib unavailable: {e!s}"
        return status

    def _to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Convert to EPSG:4326 when possible (for lat/lon axes and grid)."""
        gg = gdf.copy()
        if gg.crs is None:
            return gg.set_crs("EPSG:4326", allow_override=True)
        try:
            if str(gg.crs).upper() == "EPSG:4326":
                return gg
            return gg.to_crs("EPSG:4326")
        except Exception:
            # Fall back to whatever CRS we have; axes will still be labelled lon/lat,
            # but values may not be degrees if CRS conversion is not possible.
            return gg

    def _xy(gdf: gpd.GeoDataFrame):
        if gdf.geometry is not None:
            return gdf.geometry.x.astype(float), gdf.geometry.y.astype(float)
        if "longitude" in gdf.columns and "latitude" in gdf.columns:
            return gdf["longitude"].astype(float), gdf["latitude"].astype(float)
        raise PrepareYearError(
            "Cannot plot points: missing geometry and longitude/latitude columns"
        )

    pts_all = _to_wgs84(all_points)
    pts_out = _to_wgs84(outside_points)
    lm = _to_wgs84(land_mask)

    # Deterministic ordering for stable over-plotting.
    sort_cols = [
        c
        for c in ["acq_datetime_utc", "latitude", "longitude", "conf_cat", "frp_mw"]
        if c in pts_all.columns
    ]
    if sort_cols:
        pts_all = pts_all.sort_values(sort_cols, kind="mergesort")

    sort_cols_out = [
        c for c in ["acq_datetime_utc", "latitude", "longitude"] if c in pts_out.columns
    ]
    if sort_cols_out:
        pts_out = pts_out.sort_values(sort_cols_out, kind="mergesort")

    # Deterministic downsampling (QA-only)
    pts_all_plot = pts_all
    if len(pts_all_plot) > max_points:
        pts_all_plot = pts_all_plot.sample(n=max_points, random_state=0)
        status["sampled_red"] = True

    pts_out_plot = pts_out
    if len(pts_out_plot) > max_points:
        pts_out_plot = pts_out_plot.sample(n=max_points, random_state=0)
        status["sampled_blue"] = True

    status["n_plotted_red"] = int(len(pts_all_plot))
    status["n_plotted_blue"] = int(len(pts_out_plot))

    # Title + counts line (counts are from full land_stats, not from samples)
    sensor_label = str(sensor).upper()
    sensor_type = "FIRMS active fire points"
    title = f"Ghana {sensor_label} fire ({sensor_type}) - {int(year)}"
    counts = f"inside: {status['n_inside']} | outside: {status['n_outside']} | Total: {status['n_points_total']}"

    try:
        fig, ax = plt.subplots(figsize=(8.5, 8.5), dpi=160)

        # Land mask outline (boundary only)
        try:
            lm.boundary.plot(ax=ax, linewidth=1.0, color="black")
        except Exception:
            # Continue with points-only plot if boundary fails.
            pass

        x_all, y_all = _xy(pts_all_plot)
        ax.scatter(x_all, y_all, s=2, alpha=0.45, c="red")

        if len(pts_out_plot) > 0:
            x_out, y_out = _xy(pts_out_plot)
            ax.scatter(x_out, y_out, s=10, alpha=0.90, c="blue")

        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(True)

        # Keep view roughly centred on the land mask when possible.
        try:
            minx, miny, maxx, maxy = lm.total_bounds
            dx = max(maxx - minx, 1e-9)
            dy = max(maxy - miny, 1e-9)
            pad_x = max(0.05 * dx, 0.1)
            pad_y = max(0.05 * dy, 0.1)
            ax.set_xlim(minx - pad_x, maxx + pad_x)
            ax.set_ylim(miny - pad_y, maxy + pad_y)
        except Exception:
            pass

        ax.set_title(f"{title}\n{counts}")

        # Legend (top-right) using proxies for crisp labelling.
        handles = [
            Line2D([0], [0], color="black", linewidth=1.0, label="Land mask outline"),
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                markerfacecolor="red",
                markeredgecolor="red",
                markersize=6,
                label="All fires",
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                markerfacecolor="blue",
                markeredgecolor="blue",
                markersize=6,
                label="Outside mask",
            ),
        ]
        ax.legend(handles=handles, loc="upper right")

        fig.tight_layout()

        if out_png is not None:
            out_png.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out_png, dpi=160, bbox_inches="tight")
            status["png"] = out_png

        if out_pdf is not None:
            out_pdf.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out_pdf, bbox_inches="tight")
            status["pdf"] = out_pdf

        plt.close(fig)
        status["status"] = "WRITTEN"
        return status
    except Exception as e:
        status["status"] = "FAILED"
        status["error"] = str(e)
        try:
            plt.close("all")
        except Exception:
            pass
        return status


def _write_prepare_year_qa_exports(
    *,
    cfg: AppConfig,
    repo_root: Path,
    run_dir: Path,
    sensor: SensorName,
    year: int,
    cleaned_points: gpd.GeoDataFrame,
    outside_land_points: gpd.GeoDataFrame | None,
    all_points_for_plot: gpd.GeoDataFrame | None,
    land_mask_for_plot: gpd.GeoDataFrame | None,
    land_stats_for_plot: dict[str, float] | None,
) -> tuple[dict[str, object], dict[str, dict[str, str]]]:
    """Write optional QA exports and return (qa_exports_status, manifest_additions).

    manifest_additions maps a deterministic key -> {path, sha256} for successfully written files.
    """
    exp_cfg = cfg.outputs.prepare_year_qa_exports

    qa_exports: dict[str, object] = {
        "enabled": bool(exp_cfg.enabled),
        "write_geopackage": bool(exp_cfg.write_geopackage),
        "also_write_shapefile": bool(exp_cfg.also_write_shapefile),
        "export_outside_land_points": bool(exp_cfg.export_outside_land_points),
        "plot_outside_land_points_png": bool(exp_cfg.plot_outside_land_points_png),
        "plot_outside_land_points_pdf": bool(exp_cfg.plot_outside_land_points_pdf),
        "plot_max_points": int(exp_cfg.plot_max_points),
        "cleaned_points": {"n_points": int(len(cleaned_points)), "files": []},
        "outside_land": {
            "n_points": int(len(outside_land_points)) if outside_land_points is not None else None,
            "files": [],
            "plot": None,
        },
    }

    manifest_add: dict[str, dict[str, str]] = {}

    if not exp_cfg.enabled:
        return qa_exports, manifest_add

    out_dir = (run_dir / "qa" / "prepare_year_exports" / sensor).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    def _rel(p: Path) -> str:
        return p.relative_to(repo_root).as_posix()

    def _record_written(key: str, path: Path) -> None:
        manifest_add[key] = {"path": _rel(path), "sha256": sha256_file(path)}

    # 1) Cleaned points (dedup + land-only if land-masking required)
    base = f"prepare_year_points_clean_{sensor}_{int(year)}"

    if exp_cfg.write_geopackage:
        gpkg_path = out_dir / f"{base}.gpkg"
        try:
            p = write_geofile(
                gdf=cleaned_points, path=gpkg_path, driver="GPKG", layer="clean_points"
            )
            qa_exports["cleaned_points"]["files"].append({"kind": "gpkg", "path": _rel(p)})
            _record_written("qa_clean_points_gpkg", p)
        except WriteError as e:
            qa_exports["cleaned_points"]["files"].append(
                {"kind": "gpkg", "status": "FAILED", "error": str(e)}
            )

    if exp_cfg.also_write_shapefile:
        shp_path = out_dir / f"{base}.shp"
        try:
            p = write_geofile(gdf=cleaned_points, path=shp_path, driver="ESRI Shapefile")
            qa_exports["cleaned_points"]["files"].append({"kind": "shp", "path": _rel(p)})
            _record_written("qa_clean_points_shp", p)
        except WriteError as e:
            qa_exports["cleaned_points"]["files"].append(
                {"kind": "shp", "status": "FAILED", "error": str(e)}
            )

    # 2) Outside-land points (only meaningful when land masking is active)
    outside = outside_land_points
    if exp_cfg.export_outside_land_points:
        if outside is None:
            qa_exports["outside_land"]["files"].append(
                {"status": "SKIPPED", "reason": "no_land_mask"}
            )
        elif len(outside) == 0:
            qa_exports["outside_land"]["files"].append({"status": "SKIPPED", "reason": "empty"})
        else:
            base2 = f"prepare_year_points_outside_land_{sensor}_{int(year)}"
            if exp_cfg.write_geopackage:
                gpkg2 = out_dir / f"{base2}.gpkg"
                try:
                    p = write_geofile(gdf=outside, path=gpkg2, driver="GPKG", layer="outside_land")
                    qa_exports["outside_land"]["files"].append({"kind": "gpkg", "path": _rel(p)})
                    _record_written("qa_outside_land_gpkg", p)
                except WriteError as e:
                    qa_exports["outside_land"]["files"].append(
                        {"kind": "gpkg", "status": "FAILED", "error": str(e)}
                    )

            if exp_cfg.also_write_shapefile:
                shp2 = out_dir / f"{base2}.shp"
                try:
                    p = write_geofile(gdf=outside, path=shp2, driver="ESRI Shapefile")
                    qa_exports["outside_land"]["files"].append({"kind": "shp", "path": _rel(p)})
                    _record_written("qa_outside_land_shp", p)
                except WriteError as e:
                    qa_exports["outside_land"]["files"].append(
                        {"kind": "shp", "status": "FAILED", "error": str(e)}
                    )

    # 3) Outside-land plot (PNG required; PDF optional)
    want_png = bool(exp_cfg.plot_outside_land_points_png)
    want_pdf = bool(exp_cfg.plot_outside_land_points_pdf)

    if want_png or want_pdf:
        if outside is None:
            qa_exports["outside_land"]["plot"] = {"status": "SKIPPED", "reason": "no_land_mask"}
        elif (
            all_points_for_plot is None or land_mask_for_plot is None or land_stats_for_plot is None
        ):
            qa_exports["outside_land"]["plot"] = {
                "status": "SKIPPED",
                "reason": "missing_plot_inputs",
            }
        else:
            out_png = (
                out_dir / f"prepare_year_outside_land_{sensor}_{int(year)}.png"
                if want_png
                else None
            )
            out_pdf = (
                out_dir / f"prepare_year_outside_land_{sensor}_{int(year)}.pdf"
                if want_pdf
                else None
            )
            plot_status = _maybe_plot_outside_land(
                all_points=all_points_for_plot,
                outside_points=outside,
                land_mask=land_mask_for_plot,
                land_stats=land_stats_for_plot,
                sensor=sensor,
                year=int(year),
                out_png=out_png,
                out_pdf=out_pdf,
                max_points=int(exp_cfg.plot_max_points),
            )

            # Convert Paths to repo-relative strings for JSON serialisation.
            if isinstance(plot_status.get("png"), Path):
                p = plot_status["png"]
                plot_status["png"] = _rel(p)
                _record_written("qa_outside_land_plot_png", Path(repo_root / plot_status["png"]))

            if isinstance(plot_status.get("pdf"), Path):
                p = plot_status["pdf"]
                plot_status["pdf"] = _rel(p)
                _record_written("qa_outside_land_plot_pdf", Path(repo_root / plot_status["pdf"]))

            qa_exports["outside_land"]["plot"] = plot_status

    return qa_exports, manifest_add


# -----------------------------------------------------------------------------
# Main entrypoint
# -----------------------------------------------------------------------------


def prepare_year(
    *,
    cfg: AppConfig,
    repo_root: Path,
    sensor: SensorName,
    year: int,
    run_id: str | None = None,
    points_path: Path | None = None,
    points_gdf: gpd.GeoDataFrame | None = None,
    polygons_by_level: Mapping[str, gpd.GeoDataFrame] | None = None,
    land_mask_gdf: gpd.GeoDataFrame | None = None,
    write_outputs: bool = True,
    validate_schema: bool = True,
) -> PrepareYearResult:
    """Prepare one sensor-year into fires_canonical (joined to configured polygon levels)."""
    repo_root = Path(repo_root)

    if run_id is None:
        run_id = _derive_run_id(cfg)

    qa: dict[str, object] = {
        "sensor": sensor,
        "year": int(year),
        "run_id": run_id,
        "steps": {},
    }

    # Read points
    if points_gdf is None:
        if points_path is None:
            fin = cfg.io.inputs.firms_points[sensor]
            points_path = resolve_annual_points_path(
                repo_root=repo_root, file_glob=fin.file_glob, sensor=sensor, year=year
            )
        if not points_path.exists():
            raise PrepareYearError(
                _stage2_prepare_year_missing_input_message(
                    label=f"firms_points[{sensor}]",
                    detail=_repo_relative_text(repo_root, Path(points_path)),
                    access_hint="FIRMS download, rename, and local staging instructions",
                )
            )
        points_gdf = read_points(points_path)
    else:
        points_path = points_path or Path("<in-memory>")

    qa["source_file"] = _rel_source_file(repo_root, Path(points_path))

    # Standardise (strict)
    pts = _standardise_points(points=points_gdf, sensor=sensor, cfg=cfg, strict=True)
    qa["steps"]["standardise"] = {"n_points": int(len(pts))}

    # Binding policy: retain only FIRMS TYPE == 0 before land masking and deduplication.
    type_counts = pts["type"].value_counts(dropna=False).sort_index()
    pts = pts.loc[pts["type"] == 0].copy()
    qa["steps"]["type_filter"] = {
        "field": "type",
        "keep_value": 0,
        "applied_before_land_mask": True,
        "applied_before_dedup": True,
        "n_in": int(type_counts.sum()),
        "n_kept": int(len(pts)),
        "n_dropped_nonzero": int(type_counts.sum() - len(pts)),
        "value_counts_before_filter": {str(int(k)): int(v) for k, v in type_counts.items()},
        "value_counts_after_filter": {"0": int(len(pts))},
    }

    # Optional land mask
    outside_land_points: gpd.GeoDataFrame | None = None
    # Inputs for optional outside-land plot (QA only; kept separate from contracted flow)
    all_points_for_plot: gpd.GeoDataFrame | None = None
    land_mask_for_plot: gpd.GeoDataFrame | None = None
    land_stats_for_plot: dict[str, float] | None = None

    lmp = cfg.processing.land_mask_policy
    land_mask_enabled = bool(lmp.enabled_if_path_provided)

    if land_mask_gdf is None and cfg.io.inputs.land_mask and land_mask_enabled:
        land_mask_path = (repo_root / cfg.io.inputs.land_mask).resolve()
        if not land_mask_path.exists():
            raise PrepareYearError(
                _stage2_prepare_year_missing_input_message(
                    label="land_mask",
                    detail=_repo_relative_text(repo_root, land_mask_path),
                    access_hint="data acquisition and local staging instructions",
                )
            )
        land_mask_gdf = read_polygons(land_mask_path)

    if land_mask_gdf is not None and land_mask_enabled:
        lm = land_mask_gdf.copy()
        if lm.crs is None:
            lm = lm.set_crs(pts.crs, allow_override=True)
        elif lm.crs != pts.crs:
            lm = lm.to_crs(pts.crs)

        inside, outside, land_stats = split_points_by_land_mask(
            points=pts, land_mask=lm, predicate=lmp.spatial_predicate
        )
        outside_land_points = outside

        # For QA plotting we keep the full sensor-year point set (inside + outside),
        # the land mask used for the split, and the full-count statistics.
        land_mask_for_plot = lm
        land_stats_for_plot = land_stats
        try:
            all_points_for_plot = gpd.GeoDataFrame(
                pd.concat([inside, outside], ignore_index=True),
                geometry=inside.geometry.name,
                crs=inside.crs,
            )
        except Exception:
            all_points_for_plot = None

        if lmp.require_land_intersection:
            pts = inside
            n_dropped = int(len(outside))
        else:
            # Retain all points but still report outside-land counts.
            n_dropped = 0

        qa["steps"]["land_mask"] = {
            "enabled": True,
            "predicate": str(lmp.spatial_predicate),
            "require_land_intersection": bool(lmp.require_land_intersection),
            "n_inside": int(len(inside)),
            "n_outside": int(len(outside)),
            "n_outside_dropped": int(n_dropped),
            **{k: float(v) for k, v in land_stats.items()},
        }
    else:
        qa["steps"]["land_mask"] = {
            "enabled": False,
            "reason": (
                "no_land_mask"
                if cfg.io.inputs.land_mask is None and land_mask_gdf is None
                else "disabled"
            ),
        }

    # Dedup (on whichever point set is flowing into fires_canonical)
    pts_dedup, dedup_stats = deduplicate_points(points=pts, sensor=sensor, cfg=cfg)
    qa["steps"]["dedup"] = dedup_stats

    # Join to polygons (1+ levels)
    out_frames: list[pd.DataFrame] = []
    dropped_unmatched_by_level: dict[str, int] = {}

    for lvl in cfg.io.inputs.polygons:
        level = lvl.level

        if polygons_by_level is not None and level in polygons_by_level:
            polys = polygons_by_level[level].copy()
        else:
            polygon_path = (repo_root / lvl.path).resolve()
            if not polygon_path.exists():
                raise PrepareYearError(
                    _stage2_prepare_year_missing_input_message(
                        label=f"polygon:{level}",
                        detail=_repo_relative_text(repo_root, polygon_path),
                        access_hint="data acquisition and local staging instructions",
                    )
                )
            polys = read_polygons(polygon_path, columns=[lvl.unit_id_field, lvl.unit_name_field])

        if polys.crs is None:
            polys = polys.set_crs(pts_dedup.crs, allow_override=True)
        elif polys.crs != pts_dedup.crs:
            polys = polys.to_crs(pts_dedup.crs)

        joined = join_points_to_units(
            points=pts_dedup,
            polygons=polys,
            level=level,
            unit_id_field=lvl.unit_id_field,
            unit_name_field=lvl.unit_name_field,
            predicate="intersects",
        )

        # Drop unmatched points (unit_id required by schema)
        unit_id = joined["unit_id"].astype("object")
        keep = unit_id.notna() & (unit_id.astype(str).str.len() > 0)
        dropped_unmatched_by_level[level] = int((~keep).sum())
        joined = joined.loc[keep].copy()

        # Canonical row record (schema properties; no extras)
        df = pd.DataFrame(
            {
                "run_id": run_id,
                "source_file": qa["source_file"],
                "sensor": sensor,
                "level": level,
                "unit_id": joined["unit_id"].astype(str),
                "acq_datetime_utc": joined["acq_datetime_utc"].astype("object"),
                "acq_date": joined["acq_date"].astype("object"),
                "acq_time_utc": joined["acq_time_utc"].astype("object"),
                "yyyymm": joined["yyyymm"].astype("int64"),
                "date_utc": joined["date_utc"].astype("object"),
                "latitude": joined["latitude"].astype(float),
                "longitude": joined["longitude"].astype(float),
                "conf_cat": joined["conf_cat"].astype("object"),
                "frp_mw": joined["frp_mw"].astype(float),
                "daynight": joined.get(
                    "daynight", pd.Series([pd.NA] * len(joined), index=joined.index)
                ).astype("object"),
                "satellite": joined.get(
                    "satellite", pd.Series([pd.NA] * len(joined), index=joined.index)
                ).astype("object"),
                "type": joined["type"].astype("int64"),
                "dedup_key": joined["dedup_key"].astype("object"),
                "was_dedup_kept": joined["was_dedup_kept"].astype(bool),
            }
        )
        out_frames.append(df)

    if not out_frames:
        raise PrepareYearError("No polygon levels configured (io.inputs.polygons is empty).")

    fires = pd.concat(out_frames, ignore_index=True)

    qa["steps"]["polygon_join"] = {
        "levels": [lvl.level for lvl in cfg.io.inputs.polygons],
        "n_rows_total": int(len(fires)),
        "dropped_unmatched_by_level": dropped_unmatched_by_level,
    }

    # Deterministic ordering + exact columns
    sort_keys: Sequence[str] = cfg.determinism.sort_keys.get("fires_canonical", [])
    if sort_keys:
        fires = stable_sort_df(fires, sort_keys)

    col_order = cfg.determinism.column_order.get("fires_canonical")
    if col_order is None:
        raise PrepareYearError("Config missing determinism.column_order.fires_canonical")
    fires = enforce_exact_column_order(fires, col_order, allow_reorder=True)

    # Schema validation
    if validate_schema:
        schema_rel = cfg.outputs.schemas.get("fires_canonical")
        if not schema_rel:
            raise PrepareYearError("Config missing outputs.schemas.fires_canonical")
        schema_path = (repo_root / schema_rel).resolve()
        schema_obj = load_json_schema(schema_path)
        fires = validate_dataframe_against_schema(
            df=fires, schema=schema_obj, expected_columns=col_order, allow_reorder=True
        )
        qa["steps"]["schema_validation"] = {"status": "PASS", "schema": schema_rel}
    else:
        qa["steps"]["schema_validation"] = {"status": "SKIPPED"}

    # Writes: CSV + QA + manifest (+ optional QA exports)
    fires_path: Path | None = None
    qa_path: Path | None = None
    manifest_path: Path | None = None

    if write_outputs:
        run_dir = build_run_dir(
            repo_root=repo_root, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
        )
        out_dir = run_dir / "fires_canonical" / sensor
        fires_path = out_dir / f"fires_canonical_{sensor}_{int(year)}.csv"

        write_dataframe_csv(df=fires, path=fires_path, sort_keys=sort_keys, column_order=col_order)

        # Optional QA exports (best-effort, must not affect fires_canonical)
        qa_exports_status, manifest_additions = _write_prepare_year_qa_exports(
            cfg=cfg,
            repo_root=repo_root,
            run_dir=run_dir,
            sensor=sensor,
            year=int(year),
            cleaned_points=pts_dedup,
            outside_land_points=outside_land_points,
            all_points_for_plot=all_points_for_plot,
            land_mask_for_plot=land_mask_for_plot,
            land_stats_for_plot=land_stats_for_plot,
        )
        qa_exports_status["type_filter"] = qa["steps"]["type_filter"]
        qa["qa_exports"] = qa_exports_status

        qa_dir = run_dir / "qa"
        qa_path = qa_dir / f"prepare_year_{sensor}_{int(year)}_summary.json"
        write_json(obj=qa, path=qa_path)

        manifest: dict[str, object] = {
            "fires_canonical_csv": {
                "path": fires_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(fires_path),
            },
            "qa_summary_json": {
                "path": qa_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(qa_path),
            },
        }

        # Optional additions are only for successfully written files.
        if manifest_additions:
            manifest["qa_exports"] = manifest_additions

        manifest_path = qa_dir / f"prepare_year_{sensor}_{int(year)}_manifest.json"
        write_json(obj=manifest, path=manifest_path)

    return PrepareYearResult(
        fires_canonical=fires,
        qa_summary=qa,
        fires_canonical_path=fires_path,
        qa_summary_path=qa_path,
        manifest_path=manifest_path,
    )
