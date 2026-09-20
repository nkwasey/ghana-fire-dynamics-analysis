"""geo_data_prep.spatial.overlay

District->Zone assignment via intersection overlay and maximum area share.

Design goals
------------
- Scientifically defensible: assignment is based on the share of each district's
  area that lies within each zone.
- Deterministic: ties are resolved via a stable, documented tie-break.
- Audit-friendly: return a district×zone overlap table suitable for QA reporting.
- Use the shared area helper rather than duplicating area
  logic, and emit explicit, unit-aware overlap diagnostics.

Notes
-----
This module assumes geometries are polygonal and *valid*. Upstream IO enforces
polygon-only inputs and CRS presence; we still validate geometry validity here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class OverlayError(RuntimeError):
    """Raised when overlay-based assignment fails or is ill-defined."""


AREA_UNITS_SQ_M = "sq_m"
DISTRICT_AREA_EXPLICIT_COL = "district_area_sq_m"
INTERSECTION_AREA_EXPLICIT_COL = "intersection_area_sq_m"
OVERLAP_SUM_COL = "district_intersection_sum_sq_m"
OVERLAP_GAP_COL = "district_uncovered_area_sq_m"
OVERLAP_GAP_FRAC_COL = "district_uncovered_frac"
ASSIGNMENT_METHOD_COL = "assignment_method"
AREA_METHOD_COL = "area_method"
AREA_UNITS_COL = "area_units"
WORKING_CRS_COL = "working_crs"
SHARE_BASIS_COL = "share_basis"
TIE_CANDIDATE_COUNT_COL = "tie_candidate_count"
TIE_BREAK_APPLIED_COL = "tie_break_applied"
LEGACY_ZONE_ID_COL = "legacy_zone_id"
LEGACY_ZONE_NAME_COL = "legacy_zone_name"
LEGACY_ZONE_CODE_COL = "legacy_zone_code"
LEGACY_PRESENT_COL = "legacy_assignment_present"
LEGACY_MATCH_COL = "legacy_assignment_match"
LEGACY_DISAGREEMENT_COL = "legacy_assignment_disagreement"
ASSIGNMENT_STATUS_COL = "assignment_status"
ASSIGNED_SHARE_COL = "assigned_share"


def _require_geopandas() -> object:
    try:
        import geopandas as gpd  # type: ignore

        return gpd
    except Exception as e:  # pragma: no cover
        raise OverlayError(
            "geopandas is required for overlay operations. Install via conda env (environment.yml)."
        ) from e


def _crs_equal(src_crs: object, working_crs: str) -> bool:
    """Best-effort CRS semantic equality (matches geo_data_prep.io.read behaviour)."""

    try:
        from pyproj import CRS  # type: ignore

        return CRS.from_user_input(src_crs) == CRS.from_user_input(working_crs)
    except Exception:
        return str(src_crs) == str(working_crs)


def _require_cols(gdf: object, cols: Sequence[str], *, obj_name: str) -> None:
    missing = [c for c in cols if c not in getattr(gdf, "columns", [])]
    if missing:
        raise OverlayError(f"{obj_name} missing required columns: {missing}")


def _validate_geometry(gdf: object, *, obj_name: str) -> None:
    from geo_data_prep.qa.validators import require_geometry_valid

    try:
        require_geometry_valid(gdf)
    except Exception as e:
        raise OverlayError(f"{obj_name} has invalid geometries: {e}") from e


@dataclass(frozen=True)
class DistrictZoneAssignment:
    """Result bundle for district->zone assignment."""

    districts_enriched: object  # GeoDataFrame
    overlap_table: object  # pandas.DataFrame


@dataclass(frozen=True)
class _LegacyColumnSpec:
    zone_id: str | None
    zone_name: str | None
    zone_code: str | None


@dataclass(frozen=True)
class _NoOverlapResult:
    districts_enriched: object
    overlap_table: object


@dataclass(frozen=True)
class _AreaSpec:
    district_area_col: str
    intersection_area_col: str
    area_units: str
    area_method: str
    share_basis: str
    working_crs: str


def _as_string_key_series(series: object) -> object:
    return series.astype(str)


def _pick_legacy_assignment_columns(
    districts: object,
    *,
    zone_id_col: str,
    zone_cols: Sequence[str],
) -> _LegacyColumnSpec:
    cols = set(getattr(districts, "columns", []))

    legacy_zone_id = zone_id_col if zone_id_col in cols else None

    legacy_zone_name: str | None = None
    legacy_zone_code: str | None = None
    if len(zone_cols) >= 1 and zone_cols[0] in cols:
        legacy_zone_name = zone_cols[0]
    if len(zone_cols) >= 2 and zone_cols[1] in cols:
        legacy_zone_code = zone_cols[1]

    return _LegacyColumnSpec(
        zone_id=legacy_zone_id,
        zone_name=legacy_zone_name,
        zone_code=legacy_zone_code,
    )


def _attach_legacy_assignment_columns(
    districts: object,
    *,
    legacy_spec: _LegacyColumnSpec,
) -> object:
    out = districts.copy()

    if legacy_spec.zone_id is not None:
        out[LEGACY_ZONE_ID_COL] = out[legacy_spec.zone_id]
    else:
        out[LEGACY_ZONE_ID_COL] = None

    if legacy_spec.zone_name is not None:
        out[LEGACY_ZONE_NAME_COL] = out[legacy_spec.zone_name]
    else:
        out[LEGACY_ZONE_NAME_COL] = None

    if legacy_spec.zone_code is not None:
        out[LEGACY_ZONE_CODE_COL] = out[legacy_spec.zone_code]
    else:
        out[LEGACY_ZONE_CODE_COL] = None

    out[LEGACY_PRESENT_COL] = (
        out[[LEGACY_ZONE_ID_COL, LEGACY_ZONE_NAME_COL, LEGACY_ZONE_CODE_COL]].notna().any(axis=1)
    )
    return out


def _make_empty_overlap_table(
    *,
    district_id_col: str,
    zone_id_col: str,
    zone_cols: Sequence[str],
    share_col: str,
    area_spec: _AreaSpec,
):
    import pandas as pd  # type: ignore

    return pd.DataFrame(
        columns=[
            district_id_col,
            zone_id_col,
            *zone_cols,
            "district_area",
            "intersection_area",
            share_col,
            "rank",
            "is_assigned",
            area_spec.district_area_col,
            area_spec.intersection_area_col,
            OVERLAP_SUM_COL,
            OVERLAP_GAP_COL,
            OVERLAP_GAP_FRAC_COL,
            ASSIGNMENT_METHOD_COL,
            AREA_METHOD_COL,
            AREA_UNITS_COL,
            WORKING_CRS_COL,
            SHARE_BASIS_COL,
            TIE_CANDIDATE_COUNT_COL,
            TIE_BREAK_APPLIED_COL,
            ASSIGNMENT_STATUS_COL,
            LEGACY_ZONE_ID_COL,
            LEGACY_ZONE_NAME_COL,
            LEGACY_ZONE_CODE_COL,
            LEGACY_PRESENT_COL,
            LEGACY_MATCH_COL,
            LEGACY_DISAGREEMENT_COL,
        ]
    )


def _no_overlap_assignment(
    districts: object,
    *,
    district_id_col: str,
    zone_id_col: str,
    zone_cols: Sequence[str],
    share_col: str,
    area_spec: _AreaSpec,
    fail_on_unassigned: bool,
    reason: str,
) -> _NoOverlapResult:

    if fail_on_unassigned:
        raise OverlayError(reason)

    d_out = districts.copy()
    for c in [zone_id_col, *zone_cols]:
        if c in d_out.columns:
            d_out = d_out.drop(columns=[c])
        d_out[c] = None

    d_out[share_col] = 0.0
    d_out[ASSIGNED_SHARE_COL] = 0.0
    d_out[ASSIGNMENT_STATUS_COL] = "unassigned_no_overlap"
    d_out[TIE_CANDIDATE_COUNT_COL] = 0
    d_out[TIE_BREAK_APPLIED_COL] = False
    d_out[AREA_METHOD_COL] = area_spec.area_method
    d_out[AREA_UNITS_COL] = area_spec.area_units
    d_out[WORKING_CRS_COL] = area_spec.working_crs
    d_out[SHARE_BASIS_COL] = area_spec.share_basis
    d_out[LEGACY_MATCH_COL] = None
    d_out[LEGACY_DISAGREEMENT_COL] = None

    empty = _make_empty_overlap_table(
        district_id_col=district_id_col,
        zone_id_col=zone_id_col,
        zone_cols=zone_cols,
        share_col=share_col,
        area_spec=area_spec,
    )

    return _NoOverlapResult(districts_enriched=d_out, overlap_table=empty)


def assign_districts_to_zones_by_max_share(
    districts: object,
    zones: object,
    *,
    working_crs: str,
    district_id_col: str = "district_id",
    zone_id_col: str = "zone_id",
    zone_cols: Sequence[str] = ("zone_name", "zone_code"),
    share_col: str = "ovl_share",
    tie_break_cols: Sequence[str] | None = None,
    tie_tol: float = 1e-12,
    fail_on_unassigned: bool = True,
) -> DistrictZoneAssignment:
    """Assign each district to the zone with maximum intersection area share.

    Assignment rule
    ---------------
    - Intersect districts with zones (polygon overlay).
    - Compute ``ovl_share = area(intersection) / area(district)`` in ``working_crs``.
    - Choose the zone with maximum share.
    - Deterministic tie-break (CP binding): smallest ``zone_id``, then smallest
      ``zone_name`` (lexicographic), for shares tied within ``tie_tol``.

    Assignment diagnostics
    -----------------
    - Use the shared Stage 1 projected-area helper for district and intersection areas.
    - Emit explicit unit-aware area columns alongside the existing overlap fields.
    - Record overlap closure diagnostics and, where present, legacy-vs-recomputed
      assignment agreement diagnostics.
    """

    gpd = _require_geopandas()
    import pandas as pd  # type: ignore

    from geo_data_prep.spatial.area import projected_area_series

    if float(tie_tol) < 0:
        raise OverlayError("tie_tol must be >= 0")

    # Default deterministic tie-break aligns with CP bindings.
    if tie_break_cols is None:
        tb: list[str] = [zone_id_col]
        if "zone_name" in zone_cols:
            tb.append("zone_name")
        tie_break_cols = tb
    else:
        tie_break_cols = list(tie_break_cols)

    _require_cols(districts, [district_id_col], obj_name="districts")
    _require_cols(zones, [zone_id_col, *zone_cols], obj_name="zones")

    # IDs must be unique for the assignment to be well-defined.
    try:
        if districts[district_id_col].duplicated().any():  # type: ignore[index]
            raise OverlayError(f"district_id_col has duplicates: {district_id_col}")
        if zones[zone_id_col].duplicated().any():  # type: ignore[index]
            raise OverlayError(f"zone_id_col has duplicates: {zone_id_col}")
    except OverlayError:
        raise
    except Exception as e:
        raise OverlayError(f"Failed while checking ID uniqueness: {e}") from e

    if getattr(districts, "crs", None) is None:
        raise OverlayError("districts CRS is missing")
    if getattr(zones, "crs", None) is None:
        raise OverlayError("zones CRS is missing")

    d = districts
    z = zones
    if not _crs_equal(d.crs, working_crs):
        d = d.to_crs(working_crs)
    if not _crs_equal(z.crs, working_crs):
        z = z.to_crs(working_crs)

    _validate_geometry(d, obj_name="districts")
    _validate_geometry(z, obj_name="zones")

    legacy_spec = _pick_legacy_assignment_columns(d, zone_id_col=zone_id_col, zone_cols=zone_cols)
    d = _attach_legacy_assignment_columns(d, legacy_spec=legacy_spec)

    area_spec = _AreaSpec(
        district_area_col=DISTRICT_AREA_EXPLICIT_COL,
        intersection_area_col=INTERSECTION_AREA_EXPLICIT_COL,
        area_units=AREA_UNITS_SQ_M,
        area_method="projected",
        share_basis="intersection_over_district_area",
        working_crs=str(working_crs),
    )

    try:
        district_area = projected_area_series(d, projected_crs=working_crs, units=AREA_UNITS_SQ_M)
    except Exception as e:
        raise OverlayError(f"Failed to compute district areas via shared area helper: {e}") from e

    if (district_area <= 0).any():
        bad_n = int((district_area <= 0).sum())
        raise OverlayError(f"Found {bad_n} districts with non-positive area")

    d_min_cols = [
        district_id_col,
        LEGACY_ZONE_ID_COL,
        LEGACY_ZONE_NAME_COL,
        LEGACY_ZONE_CODE_COL,
        LEGACY_PRESENT_COL,
        "geometry",
    ]
    d_min = d[d_min_cols].copy()
    z_min = z[[zone_id_col, *zone_cols, "geometry"]].copy()

    try:
        ovl = gpd.overlay(d_min, z_min, how="intersection", keep_geom_type=False)
    except Exception as e:
        raise OverlayError(f"Overlay intersection failed: {e}") from e

    if len(ovl) == 0:
        no_ovl = _no_overlap_assignment(
            d,
            district_id_col=district_id_col,
            zone_id_col=zone_id_col,
            zone_cols=zone_cols,
            share_col=share_col,
            area_spec=area_spec,
            fail_on_unassigned=fail_on_unassigned,
            reason="No intersections produced between districts and zones",
        )
        return DistrictZoneAssignment(
            districts_enriched=no_ovl.districts_enriched,
            overlap_table=no_ovl.overlap_table,
        )

    try:
        ovl[area_spec.intersection_area_col] = projected_area_series(
            ovl,
            projected_crs=working_crs,
            units=area_spec.area_units,
        )
    except Exception as e:
        raise OverlayError(
            f"Failed to compute intersection areas via shared area helper: {e}"
        ) from e

    ovl = ovl.loc[ovl[area_spec.intersection_area_col] > 0].copy()
    if len(ovl) == 0:
        no_ovl = _no_overlap_assignment(
            d,
            district_id_col=district_id_col,
            zone_id_col=zone_id_col,
            zone_cols=zone_cols,
            share_col=share_col,
            area_spec=area_spec,
            fail_on_unassigned=fail_on_unassigned,
            reason="Only zero-area intersections found (boundary touches); no assignable overlaps",
        )
        return DistrictZoneAssignment(
            districts_enriched=no_ovl.districts_enriched,
            overlap_table=no_ovl.overlap_table,
        )

    area_map = {
        k: float(a)
        for k, a in zip(d[district_id_col].tolist(), district_area.tolist(), strict=False)
    }
    ovl[area_spec.district_area_col] = ovl[district_id_col].map(area_map)

    ovl.loc[ovl[area_spec.intersection_area_col] < 0, area_spec.intersection_area_col] = 0.0

    # Polygon overlay and projected-area arithmetic are floating-point operations.
    # Geometries that should cover a district exactly can therefore produce a raw
    # intersection/district ratio a few ulps above 1.0.  Apply the repository's
    # existing governed share-bound tolerance before the share is ranked or
    # serialised, while preserving the raw area columns for audit.  Material
    # excursions remain unmodified and are rejected by downstream QA.
    raw_share = ovl[area_spec.intersection_area_col] / ovl[area_spec.district_area_col]
    from geo_data_prep.qa.validators import normalise_share_series_for_validation

    normalised_share = normalise_share_series_for_validation(raw_share)
    ovl[share_col] = normalised_share.normalised_shares

    # Preserve the current governed field names while adding explicit unit-aware columns.
    ovl["district_area"] = ovl[area_spec.district_area_col]
    ovl["intersection_area"] = ovl[area_spec.intersection_area_col]
    ovl[AREA_METHOD_COL] = area_spec.area_method
    ovl[AREA_UNITS_COL] = area_spec.area_units
    ovl[WORKING_CRS_COL] = area_spec.working_crs
    ovl[SHARE_BASIS_COL] = area_spec.share_basis
    ovl[ASSIGNMENT_METHOD_COL] = "max_intersection_share"

    per_district_overlap = (
        ovl.groupby(district_id_col, dropna=False)[area_spec.intersection_area_col]
        .sum()
        .rename(OVERLAP_SUM_COL)
        .reset_index()
    )
    ovl = ovl.merge(per_district_overlap, on=district_id_col, how="left")
    ovl[OVERLAP_GAP_COL] = ovl[area_spec.district_area_col] - ovl[OVERLAP_SUM_COL]
    ovl.loc[ovl[OVERLAP_GAP_COL] < 0, OVERLAP_GAP_COL] = 0.0
    ovl[OVERLAP_GAP_FRAC_COL] = ovl[OVERLAP_GAP_COL] / ovl[area_spec.district_area_col]

    max_share = ovl.groupby(district_id_col, dropna=False)[share_col].max().rename("_max")
    ovl = ovl.merge(max_share, on=district_id_col, how="left")
    ovl["_is_tied_max"] = (ovl["_max"] - ovl[share_col]).abs() <= float(tie_tol)

    tie_counts = (
        ovl.loc[ovl["_is_tied_max"]]
        .groupby(district_id_col, dropna=False)
        .size()
        .rename(TIE_CANDIDATE_COUNT_COL)
        .reset_index()
    )
    ovl = ovl.merge(tie_counts, on=district_id_col, how="left")
    ovl[TIE_CANDIDATE_COUNT_COL] = ovl[TIE_CANDIDATE_COUNT_COL].fillna(0).astype(int)
    ovl[TIE_BREAK_APPLIED_COL] = ovl[TIE_CANDIDATE_COUNT_COL] > 1

    sort_cols: list[str] = [share_col]
    ascending: list[bool] = [False]
    for c in tie_break_cols:
        if c not in ovl.columns:
            raise OverlayError(f"tie_break column missing from overlay table: {c}")
        ovl[f"_tb_{c}"] = _as_string_key_series(ovl[c])
        sort_cols.append(f"_tb_{c}")
        ascending.append(True)

    candidates = ovl.loc[ovl["_is_tied_max"]].copy()
    candidates = candidates.sort_values(sort_cols, ascending=ascending, kind="mergesort")
    chosen = candidates.drop_duplicates(subset=[district_id_col], keep="first")

    assigned_ids = set(chosen[district_id_col].tolist())
    all_ids = set(d[district_id_col].tolist())
    unassigned = sorted(all_ids - assigned_ids)
    if unassigned and fail_on_unassigned:
        raise OverlayError(
            "Some districts could not be assigned to any zone (no overlap). "
            f"Count={len(unassigned)}. Example IDs={unassigned[:5]}"
        )

    keep_cols = [
        district_id_col,
        zone_id_col,
        *zone_cols,
        share_col,
        area_spec.district_area_col,
        area_spec.intersection_area_col,
        "district_area",
        "intersection_area",
        OVERLAP_SUM_COL,
        OVERLAP_GAP_COL,
        OVERLAP_GAP_FRAC_COL,
        AREA_METHOD_COL,
        AREA_UNITS_COL,
        WORKING_CRS_COL,
        SHARE_BASIS_COL,
        ASSIGNMENT_METHOD_COL,
        TIE_CANDIDATE_COUNT_COL,
        TIE_BREAK_APPLIED_COL,
    ]
    chosen = chosen[keep_cols].copy()
    chosen["is_assigned"] = True
    chosen["rank"] = 1
    chosen[ASSIGNMENT_STATUS_COL] = "assigned"
    chosen[ASSIGNED_SHARE_COL] = chosen[share_col]

    d_out = d.copy()
    for c in [
        zone_id_col,
        *zone_cols,
        share_col,
        ASSIGNED_SHARE_COL,
        ASSIGNMENT_STATUS_COL,
        TIE_CANDIDATE_COUNT_COL,
        TIE_BREAK_APPLIED_COL,
    ]:
        if c in d_out.columns:
            d_out = d_out.drop(columns=[c])
    d_out = d_out.merge(
        chosen[
            [
                district_id_col,
                zone_id_col,
                *zone_cols,
                share_col,
                ASSIGNED_SHARE_COL,
                ASSIGNMENT_STATUS_COL,
                TIE_CANDIDATE_COUNT_COL,
                TIE_BREAK_APPLIED_COL,
                area_spec.district_area_col,
                "district_area",
                AREA_METHOD_COL,
                AREA_UNITS_COL,
                WORKING_CRS_COL,
                SHARE_BASIS_COL,
                ASSIGNMENT_METHOD_COL,
                OVERLAP_SUM_COL,
                OVERLAP_GAP_COL,
                OVERLAP_GAP_FRAC_COL,
            ]
        ],
        on=district_id_col,
        how="left",
    )
    d_out[share_col] = d_out[share_col].fillna(0.0)
    d_out[ASSIGNED_SHARE_COL] = d_out[ASSIGNED_SHARE_COL].fillna(0.0)
    d_out[ASSIGNMENT_STATUS_COL] = d_out[ASSIGNMENT_STATUS_COL].fillna("unassigned_no_overlap")
    d_out[TIE_CANDIDATE_COUNT_COL] = d_out[TIE_CANDIDATE_COUNT_COL].fillna(0).astype(int)
    d_out[TIE_BREAK_APPLIED_COL] = d_out[TIE_BREAK_APPLIED_COL].fillna(False).astype(bool)

    # Legacy-vs-recomputed diagnostics are relevant only when a legacy assignment was supplied.
    d_out[LEGACY_MATCH_COL] = None
    d_out[LEGACY_DISAGREEMENT_COL] = None
    if legacy_spec.zone_id is not None:
        legacy_zone_id = d_out[LEGACY_ZONE_ID_COL].astype(str)
        assigned_zone_id = d_out[zone_id_col].astype(str)
        d_out[LEGACY_MATCH_COL] = (~d_out[LEGACY_PRESENT_COL]) | (
            legacy_zone_id == assigned_zone_id
        )
        d_out[LEGACY_DISAGREEMENT_COL] = d_out[LEGACY_PRESENT_COL] & (~d_out[LEGACY_MATCH_COL])
    elif legacy_spec.zone_name is not None:
        legacy_zone_name = d_out[LEGACY_ZONE_NAME_COL].astype(str)
        assigned_zone_name = d_out[zone_cols[0]].astype(str)
        d_out[LEGACY_MATCH_COL] = (~d_out[LEGACY_PRESENT_COL]) | (
            legacy_zone_name == assigned_zone_name
        )
        d_out[LEGACY_DISAGREEMENT_COL] = d_out[LEGACY_PRESENT_COL] & (~d_out[LEGACY_MATCH_COL])

    overlap_df = ovl.drop(columns=["geometry"], errors="ignore").copy()
    overlap_df["is_assigned"] = False
    key = chosen[[district_id_col, zone_id_col]].copy()
    key["_assigned_marker"] = True
    overlap_df = overlap_df.merge(key, on=[district_id_col, zone_id_col], how="left")
    overlap_df.loc[overlap_df["_assigned_marker"].notna(), "is_assigned"] = True
    overlap_df = overlap_df.drop(columns=["_assigned_marker"], errors="ignore")

    overlap_df["rank"] = (
        overlap_df.groupby(district_id_col, dropna=False)[share_col]
        .rank(method="dense", ascending=False)
        .astype(int)
    )
    overlap_df[ASSIGNMENT_STATUS_COL] = overlap_df["is_assigned"].map(
        {True: "assigned", False: "candidate_not_selected"}
    )
    overlap_df[ASSIGNED_SHARE_COL] = overlap_df[share_col].where(overlap_df["is_assigned"], None)

    overlap_df[LEGACY_MATCH_COL] = None
    overlap_df[LEGACY_DISAGREEMENT_COL] = None
    if LEGACY_PRESENT_COL in overlap_df.columns:
        if legacy_spec.zone_id is not None and zone_id_col in overlap_df.columns:
            overlap_df[LEGACY_MATCH_COL] = (~overlap_df[LEGACY_PRESENT_COL]) | (
                overlap_df[LEGACY_ZONE_ID_COL].astype(str) == overlap_df[zone_id_col].astype(str)
            )
            overlap_df[LEGACY_DISAGREEMENT_COL] = overlap_df[LEGACY_PRESENT_COL] & (
                ~overlap_df[LEGACY_MATCH_COL]
            )
        elif (
            legacy_spec.zone_name is not None
            and len(zone_cols) >= 1
            and zone_cols[0] in overlap_df.columns
        ):
            overlap_df[LEGACY_MATCH_COL] = (~overlap_df[LEGACY_PRESENT_COL]) | (
                overlap_df[LEGACY_ZONE_NAME_COL].astype(str) == overlap_df[zone_cols[0]].astype(str)
            )
            overlap_df[LEGACY_DISAGREEMENT_COL] = overlap_df[LEGACY_PRESENT_COL] & (
                ~overlap_df[LEGACY_MATCH_COL]
            )

    # Deterministic order for reproducible CSVs.
    overlap_df = overlap_df.sort_values(
        by=[district_id_col, "rank", zone_id_col],
        ascending=[True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    drop_helpers = ["_max", "_is_tied_max"] + [f"_tb_{c}" for c in tie_break_cols]
    overlap_df = overlap_df.drop(columns=drop_helpers, errors="ignore")

    numeric_cols = [
        "district_area",
        "intersection_area",
        area_spec.district_area_col,
        area_spec.intersection_area_col,
        OVERLAP_SUM_COL,
        OVERLAP_GAP_COL,
        OVERLAP_GAP_FRAC_COL,
        share_col,
        ASSIGNED_SHARE_COL,
    ]
    for c in numeric_cols:
        if c in overlap_df.columns:
            overlap_df[c] = pd.to_numeric(overlap_df[c], errors="coerce")

    # Ensure assigned rows correspond to the enriched assignment frame.
    chosen_lookup = chosen[[district_id_col, zone_id_col]].copy()
    chosen_lookup["_chosen"] = True
    d_out = d_out.sort_values(by=[district_id_col], kind="mergesort").reset_index(drop=True)
    overlap_df = overlap_df.merge(chosen_lookup, on=[district_id_col, zone_id_col], how="left")
    overlap_df.loc[overlap_df["_chosen"].notna(), "is_assigned"] = True
    overlap_df = overlap_df.drop(columns=["_chosen"], errors="ignore")

    return DistrictZoneAssignment(districts_enriched=d_out, overlap_table=overlap_df)
