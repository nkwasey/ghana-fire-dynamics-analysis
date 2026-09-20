"""Descriptive scientific-defensibility diagnostics for Stage 1 assignment QA.

This module adds two non-blocking audit layers:

- sliver diagnostics over the district x zone overlap candidates
- a short CRS sensitivity study that reruns max-overlap assignment under an
  alternative equal-area projection and compares district assignments

Neither diagnostic changes the assignment rule. They exist to document whether
the current max-overlap implementation appears numerically stable and
scientifically defensible for a given run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class DefensibilityError(RuntimeError):
    """Raised when scientific-defensibility diagnostics cannot be computed."""


@dataclass(frozen=True)
class SensitivityStudyResult:
    """JSON summary plus district-level comparison table for a sensitivity study."""

    summary: Mapping[str, object]
    comparison_table: object


def _coerce_dataframe(table: object):
    try:
        import pandas as pd  # type: ignore
    except Exception as e:  # pragma: no cover
        raise DefensibilityError(f"pandas is required for defensibility diagnostics: {e}") from e

    try:
        df = table if isinstance(table, pd.DataFrame) else pd.DataFrame(table)
    except Exception as e:
        raise DefensibilityError(f"Expected DataFrame-like input: {e}") from e
    return pd, df


def _bool_mask(series: object):
    try:
        return series.astype("boolean").fillna(False)
    except Exception:
        try:
            return series.notna()
        except Exception:
            return series


def _coerce_numeric_series(pd: object, series: object, *, field_name: str):
    try:
        return pd.to_numeric(series, errors="coerce")
    except Exception as e:
        raise DefensibilityError(f"{field_name} must be numeric-like: {e}") from e


def _require_columns(df: object, columns: Sequence[str], *, obj_name: str) -> None:
    missing = [c for c in columns if c not in getattr(df, "columns", [])]
    if missing:
        raise DefensibilityError(f"{obj_name} missing required columns: {missing}")


def _require_geospatial_deps() -> tuple[object, object]:
    try:
        import geopandas as gpd  # type: ignore
    except Exception as e:  # pragma: no cover
        raise DefensibilityError(
            f"geopandas is required for CRS sensitivity diagnostics: {e}"
        ) from e

    try:
        from pyproj import CRS  # type: ignore
    except Exception as e:  # pragma: no cover
        raise DefensibilityError(f"pyproj is required for CRS sensitivity diagnostics: {e}") from e

    return gpd, CRS


def _crs_equal(src_crs: object, dst_crs: str) -> bool:
    _, CRS = _require_geospatial_deps()
    try:
        return CRS.from_user_input(src_crs) == CRS.from_user_input(dst_crs)
    except Exception:
        return str(src_crs) == str(dst_crs)


def _normalise_positive_cutoffs(values: Sequence[float], *, field_name: str) -> list[float]:
    clean = sorted({float(v) for v in values})
    if not clean:
        raise DefensibilityError(f"{field_name} must contain at least one cutoff")
    if any(v <= 0 for v in clean):
        raise DefensibilityError(f"{field_name} cutoffs must all be > 0")
    return clean


def _count_at_or_below(values: object, cutoffs: Sequence[float]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for cutoff in cutoffs:
        count = int((values <= float(cutoff)).fillna(False).sum())
        out.append({"cutoff": float(cutoff), "count": count})
    return out


def build_sliver_diagnostics(
    overlap_table: object,
    *,
    share_cutoffs: Sequence[float] = (1e-6, 1e-4, 1e-3, 1e-2),
    area_sqkm_cutoffs: Sequence[float] = (0.001, 0.01, 0.1, 1.0),
    example_limit: int = 10,
) -> dict[str, object]:
    """Summarise very small overlap candidates without imposing pass/fail logic."""

    if int(example_limit) <= 0:
        raise DefensibilityError("example_limit must be > 0")

    pd, df = _coerce_dataframe(overlap_table)
    share_cutoffs = _normalise_positive_cutoffs(share_cutoffs, field_name="share_cutoffs")
    area_sqkm_cutoffs = _normalise_positive_cutoffs(
        area_sqkm_cutoffs, field_name="area_sqkm_cutoffs"
    )

    if df.empty:
        return {
            "rows": 0,
            "districts": 0,
            "assigned_rows": 0,
            "candidate_only_rows": 0,
            "share_cutoffs": share_cutoffs,
            "area_sqkm_cutoffs": area_sqkm_cutoffs,
            "share_counts_all_rows": _count_at_or_below(pd.Series(dtype=float), share_cutoffs),
            "share_counts_candidate_only": _count_at_or_below(
                pd.Series(dtype=float), share_cutoffs
            ),
            "area_sqkm_counts_all_rows": _count_at_or_below(
                pd.Series(dtype=float), area_sqkm_cutoffs
            ),
            "area_sqkm_counts_candidate_only": _count_at_or_below(
                pd.Series(dtype=float), area_sqkm_cutoffs
            ),
            "small_overlap_examples": [],
            "notes": [
                "No overlap rows were available, so the sliver diagnostics are informationally empty.",
            ],
        }

    area_col = (
        "intersection_area_sq_m" if "intersection_area_sq_m" in df.columns else "intersection_area"
    )
    _require_columns(
        df, ["district_id", "zone_id", "ovl_share", area_col], obj_name="overlap_table"
    )

    work = df.copy()
    work["ovl_share"] = _coerce_numeric_series(
        pd, work["ovl_share"], field_name="ovl_share"
    ).astype(float)
    work["_intersection_area_sq_m"] = _coerce_numeric_series(
        pd, work[area_col], field_name=area_col
    ).astype(float)
    work["_intersection_area_sqkm"] = work["_intersection_area_sq_m"] / 1_000_000.0
    assigned_mask = (
        _bool_mask(work["is_assigned"])
        if "is_assigned" in work.columns
        else pd.Series(False, index=work.index)
    )
    candidate_only = work.loc[~assigned_mask].copy()

    keep = [
        c
        for c in [
            "district_id",
            "zone_id",
            "zone_name",
            "ovl_share",
            "is_assigned",
            "rank",
            "working_crs",
        ]
        if c in work.columns
    ]
    examples = (
        work.loc[
            work["ovl_share"].notna() & work["_intersection_area_sqkm"].notna(),
            keep + ["_intersection_area_sqkm"],
        ]
        .sort_values(
            by=["ovl_share", "_intersection_area_sqkm", "district_id", "zone_id"],
            ascending=[True, True, True, True],
            kind="mergesort",
        )
        .head(int(example_limit))
        .rename(columns={"_intersection_area_sqkm": "intersection_area_sqkm"})
    )

    return {
        "rows": int(len(work)),
        "districts": int(work["district_id"].nunique()),
        "assigned_rows": int(assigned_mask.sum()),
        "candidate_only_rows": int(len(candidate_only)),
        "share_cutoffs": share_cutoffs,
        "area_sqkm_cutoffs": area_sqkm_cutoffs,
        "share_counts_all_rows": _count_at_or_below(work["ovl_share"], share_cutoffs),
        "share_counts_candidate_only": _count_at_or_below(
            candidate_only["ovl_share"], share_cutoffs
        ),
        "area_sqkm_counts_all_rows": _count_at_or_below(
            work["_intersection_area_sqkm"], area_sqkm_cutoffs
        ),
        "area_sqkm_counts_candidate_only": _count_at_or_below(
            candidate_only["_intersection_area_sqkm"], area_sqkm_cutoffs
        ),
        "small_overlap_examples": examples.to_dict(orient="records"),
        "notes": [
            "These counts are descriptive sliver diagnostics only; no sliver-specific pass/fail threshold is applied.",
            "Candidate-only rows are usually the most relevant screen for overlay slivers because assigned rows represent the selected parent zone.",
        ],
    }


def _resolve_alternative_equal_area_crs(
    districts: object,
    zones: object,
    *,
    working_crs: str,
) -> tuple[str, dict[str, object]]:
    _, CRS = _require_geospatial_deps()

    bounds: list[tuple[float, float, float, float]] = []
    for label, layer in [("districts", districts), ("zones", zones)]:
        if getattr(layer, "crs", None) is None:
            raise DefensibilityError(f"{label} CRS is missing")
        try:
            geographic = layer if _crs_equal(layer.crs, "EPSG:4326") else layer.to_crs("EPSG:4326")
        except Exception as e:
            raise DefensibilityError(
                f"Failed to reproject {label} to EPSG:4326 for sensitivity-study setup: {e}"
            ) from e
        minx, miny, maxx, maxy = geographic.total_bounds
        bounds.append((float(minx), float(miny), float(maxx), float(maxy)))

    west = min(b[0] for b in bounds)
    south = min(b[1] for b in bounds)
    east = max(b[2] for b in bounds)
    north = max(b[3] for b in bounds)
    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0

    laea_crs = (
        f"+proj=laea +lat_0={center_lat:.8f} +lon_0={center_lon:.8f} "
        "+datum=WGS84 +units=m +no_defs +type=crs"
    )
    if _crs_equal(working_crs, laea_crs):
        return (
            "EPSG:6933",
            {
                "name": "epsg_6933_global_equal_area_fallback",
                "selection_basis": "working_crs already matches the auto-derived local equal-area CRS",
                "area_preserving": True,
                "geographic_extent": {
                    "west": west,
                    "south": south,
                    "east": east,
                    "north": north,
                    "center_lon": center_lon,
                    "center_lat": center_lat,
                },
            },
        )

    # Validate the generated CRS string so failures happen here rather than later.
    try:
        CRS.from_user_input(laea_crs)
    except Exception as e:
        raise DefensibilityError(
            f"Failed to construct a local equal-area CRS for sensitivity testing: {e}"
        ) from e

    return (
        laea_crs,
        {
            "name": "auto_laea_equal_area",
            "selection_basis": "Lambert azimuthal equal-area projection centred on the study extent",
            "area_preserving": True,
            "geographic_extent": {
                "west": west,
                "south": south,
                "east": east,
                "north": north,
                "center_lon": center_lon,
                "center_lat": center_lat,
            },
        },
    )


def _assignment_lookup_from_districts(
    districts_enriched: object,
    *,
    district_id_col: str,
    zone_id_col: str,
    share_col: str,
):
    pd, df = _coerce_dataframe(districts_enriched)
    _require_columns(df, [district_id_col, zone_id_col, share_col], obj_name="districts_enriched")
    keep = [
        c
        for c in [
            district_id_col,
            zone_id_col,
            "zone_name",
            "zone_code",
            share_col,
            "assignment_status",
        ]
        if c in df.columns
    ]
    out = df[keep].copy()
    out = out.rename(
        columns={
            zone_id_col: "zone_id",
            share_col: "assigned_share",
        }
    )
    out["zone_id"] = out["zone_id"].where(out["zone_id"].notna(), None)
    out["assigned_share"] = _coerce_numeric_series(
        pd, out["assigned_share"], field_name="assigned_share"
    ).astype(float)
    return out


def run_working_crs_sensitivity_study(
    districts: object,
    zones: object,
    *,
    baseline_districts_enriched: object,
    working_crs: str,
    district_id_col: str = "district_id",
    zone_id_col: str = "zone_id",
    share_col: str = "ovl_share",
    example_limit: int = 10,
) -> SensitivityStudyResult:
    """Rerun assignment under an alternative equal-area CRS and compare results."""

    if int(example_limit) <= 0:
        raise DefensibilityError("example_limit must be > 0")

    from geo_data_prep.spatial.overlay import assign_districts_to_zones_by_max_share

    alternative_crs, alternative_meta = _resolve_alternative_equal_area_crs(
        districts,
        zones,
        working_crs=working_crs,
    )

    try:
        alternative_assignment = assign_districts_to_zones_by_max_share(
            districts,
            zones,
            working_crs=alternative_crs,
            district_id_col=district_id_col,
            zone_id_col=zone_id_col,
            zone_cols=("zone_name", "zone_code"),
            share_col=share_col,
        )
    except Exception as e:
        raise DefensibilityError(
            f"Working-CRS sensitivity study failed while rerunning assignment: {e}"
        ) from e

    pd, baseline = _coerce_dataframe(
        _assignment_lookup_from_districts(
            baseline_districts_enriched,
            district_id_col=district_id_col,
            zone_id_col=zone_id_col,
            share_col=share_col,
        )
    )
    _, alternative = _coerce_dataframe(
        _assignment_lookup_from_districts(
            alternative_assignment.districts_enriched,
            district_id_col=district_id_col,
            zone_id_col=zone_id_col,
            share_col=share_col,
        )
    )

    baseline = baseline.rename(
        columns={
            "zone_id": "baseline_zone_id",
            "zone_name": "baseline_zone_name",
            "zone_code": "baseline_zone_code",
            "assigned_share": "baseline_assigned_share",
            "assignment_status": "baseline_assignment_status",
        }
    )
    alternative = alternative.rename(
        columns={
            "zone_id": "alternative_zone_id",
            "zone_name": "alternative_zone_name",
            "zone_code": "alternative_zone_code",
            "assigned_share": "alternative_assigned_share",
            "assignment_status": "alternative_assignment_status",
        }
    )

    comparison = baseline.merge(alternative, on=district_id_col, how="outer")
    comparison["assignment_identity_changed"] = comparison["baseline_zone_id"].fillna(
        "<NA>"
    ).astype(str) != comparison["alternative_zone_id"].fillna("<NA>").astype(str)
    comparison["assigned_share_abs_diff"] = (
        comparison["baseline_assigned_share"] - comparison["alternative_assigned_share"]
    ).abs()
    comparison = comparison.sort_values(by=[district_id_col], kind="mergesort").reset_index(
        drop=True
    )

    changed = comparison.loc[comparison["assignment_identity_changed"]].copy()
    changed_examples = changed.head(int(example_limit)).to_dict(orient="records")
    change_count = int(len(changed))

    summary = {
        "status": "pass" if change_count == 0 else "warn",
        "ok": change_count == 0,
        "working_crs": str(working_crs),
        "alternative_equal_area_crs": {
            **alternative_meta,
            "crs": str(alternative_crs),
        },
        "assignment_method": "max_intersection_share",
        "districts_compared": int(len(comparison)),
        "assignment_identity_change_count": change_count,
        "assignment_identity_change_examples": changed_examples,
        "share_difference_summary": {
            "max_abs_diff": (
                None
                if comparison["assigned_share_abs_diff"].dropna().empty
                else float(comparison["assigned_share_abs_diff"].max())
            ),
            "mean_abs_diff": (
                None
                if comparison["assigned_share_abs_diff"].dropna().empty
                else float(comparison["assigned_share_abs_diff"].mean())
            ),
        },
        "recommendation": (
            "retain_max_overlap_rule"
            if change_count == 0
            else "review_assignment_rule_under_projection_sensitivity"
        ),
        "notes": [
            "The alternative CRS is area-preserving and is used only as a sensitivity check; it does not replace the configured working_crs.",
            "The max-overlap assignment rule should be retained unless district assignment identities change under the alternative equal-area projection.",
        ],
    }
    return SensitivityStudyResult(summary=summary, comparison_table=comparison)
