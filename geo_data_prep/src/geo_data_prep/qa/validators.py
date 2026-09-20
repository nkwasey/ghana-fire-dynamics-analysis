"""geo_data_prep.qa.validators

Core validators plus assignment-specific QA checks.

Assignment checks
-----------------
- Assignment-share threshold checks.
- District-vs-overlap area closure checks.
- Missing/invalid assignment checks.
- Legacy-vs-recomputed assignment disagreement checks where relevant.

The original fail-fast helpers remain current public validation entry points.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from geo_data_prep.qa.metrics import (
    area_difference_summary,
    count_exceedance_summary,
    share_metric_summary,
)


class ValidationError(RuntimeError):
    """Raised when a QA validation fails."""


@dataclass(frozen=True)
class ValidationSummary:
    """Lightweight result object for validators."""

    ok: bool
    message: str
    status: str = "pass"
    details: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ShareNormalisationResult:
    """Raw and tolerance-normalised share vectors used by QA validators."""

    raw_shares: object
    normalised_shares: object
    invalid_mask: object
    clamped_low_count: int
    clamped_high_count: int
    bound_tol: float


DEFAULT_SHARE_BOUND_TOL = 1e-12


def _require_pandas() -> tuple[object, object]:
    try:
        import pandas as pd  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ValidationError(f"pandas is required for validation helpers: {e}") from e

    try:
        import geopandas as gpd  # type: ignore
    except Exception:
        gpd = None  # type: ignore[assignment]

    return pd, gpd


def _as_dataframe(table: object, *, obj_name: str):
    pd, _ = _require_pandas()
    try:
        return table if isinstance(table, pd.DataFrame) else pd.DataFrame(table)
    except Exception as e:
        raise ValidationError(f"{obj_name} is not DataFrame-like: {e}") from e


def _require_columns(table: object, columns: Sequence[str], *, obj_name: str) -> None:
    missing = [c for c in columns if c not in getattr(table, "columns", [])]
    if missing:
        raise ValidationError(f"{obj_name} missing required columns: {missing}")


def _validate_status(status: str) -> str:
    allowed = {"pass", "warn", "fail", "na"}
    if status not in allowed:
        raise ValidationError(f"Invalid validator status: {status}")
    return status


def _raise_if_fail(summary: ValidationSummary) -> ValidationSummary:
    if summary.status == "fail":
        raise ValidationError(summary.message)
    return summary


def _coerce_bool_mask(series: object):
    try:
        return series.fillna(False).astype(bool)
    except Exception:
        return series.notna()


def _coerce_numeric_series(series: object, *, obj_name: str):
    pd, _ = _require_pandas()
    try:
        return pd.to_numeric(series, errors="coerce")
    except Exception as e:
        raise ValidationError(f"{obj_name} is not numeric-like: {e}") from e


def normalise_share_series_for_validation(
    shares: object,
    *,
    bound_tol: float = DEFAULT_SHARE_BOUND_TOL,
) -> ShareNormalisationResult:
    """Return a tolerance-normalised view of share values for QA evaluation.

    Raw shares are preserved for audit. The returned ``normalised_shares`` clamp
    values lying within ``bound_tol`` of 0 or 1 into the closed interval
    ``[0, 1]``. Material excursions outside that tolerance remain invalid.
    """

    if float(bound_tol) < 0:
        raise ValidationError("share_bound_tol must be >= 0")

    raw_shares = _coerce_numeric_series(shares, obj_name="share_series").astype(float)
    invalid_mask = (
        raw_shares.isna() | (raw_shares < -float(bound_tol)) | (raw_shares > 1.0 + float(bound_tol))
    )

    normalised = raw_shares.copy()
    clamp_low_mask = (~invalid_mask) & (normalised < 0.0)
    clamp_high_mask = (~invalid_mask) & (normalised > 1.0)

    if int(clamp_low_mask.sum()) > 0:
        normalised.loc[clamp_low_mask] = 0.0
    if int(clamp_high_mask.sum()) > 0:
        normalised.loc[clamp_high_mask] = 1.0

    return ShareNormalisationResult(
        raw_shares=raw_shares,
        normalised_shares=normalised,
        invalid_mask=invalid_mask,
        clamped_low_count=int(clamp_low_mask.sum()),
        clamped_high_count=int(clamp_high_mask.sum()),
        bound_tol=float(bound_tol),
    )


def require_non_null(gdf: object, columns: Sequence[str]) -> ValidationSummary:
    missing = [c for c in columns if c not in getattr(gdf, "columns", [])]
    if missing:
        raise ValidationError(f"Non-null validation failed: missing columns {missing}")

    null_counts = {c: int(gdf[c].isna().sum()) for c in columns}
    bad = {c: n for c, n in null_counts.items() if n > 0}
    if bad:
        raise ValidationError(f"Non-null validation failed: null counts {bad}")
    return ValidationSummary(
        ok=True, message="non-null: ok", status="pass", details={"null_counts": null_counts}
    )


def require_unique(gdf: object, columns: Sequence[str]) -> ValidationSummary:
    missing = [c for c in columns if c not in getattr(gdf, "columns", [])]
    if missing:
        raise ValidationError(f"Uniqueness validation failed: missing columns {missing}")

    if len(columns) == 1:
        col = columns[0]
        dup_n = int(gdf[col].duplicated().sum())
        if dup_n > 0:
            raise ValidationError(f"Uniqueness validation failed: {col} has {dup_n} duplicates")
        return ValidationSummary(
            ok=True, message="unique: ok", status="pass", details={"duplicate_rows": 0}
        )

    dup_n = int(gdf.duplicated(subset=list(columns)).sum())
    if dup_n > 0:
        raise ValidationError(
            f"Uniqueness validation failed: {dup_n} duplicate rows on {list(columns)}"
        )
    return ValidationSummary(
        ok=True, message="unique: ok", status="pass", details={"duplicate_rows": 0}
    )


def require_geometry_valid(gdf: object) -> ValidationSummary:
    geom = getattr(gdf, "geometry", None)
    if geom is None:
        raise ValidationError("Geometry validity check failed: GeoDataFrame has no geometry")

    try:
        invalid_mask = ~geom.is_valid
        invalid_n = int(invalid_mask.sum())
    except Exception as e:  # pragma: no cover
        raise ValidationError(f"Geometry validity check failed: {e}") from e

    if invalid_n > 0:
        raise ValidationError(f"Geometry validity check failed: {invalid_n} invalid geometries")
    return ValidationSummary(
        ok=True, message="geometry-valid: ok", status="pass", details={"invalid_count": 0}
    )


def validate_invalid_geometry_counts(
    *,
    layer_invalid_counts: Mapping[str, object] | None = None,
    warn_above: int = 0,
    fail_above: int = 0,
) -> ValidationSummary:
    """Evaluate emitted invalid-geometry counts from runtime-checked layers.

    This validator is non-blocking only in the sense that it serialises the
    observed count into the shared QA payload. The runtime may still fail fast
    earlier when invalid geometries are detected in canonical Stage 1 layers.
    """

    if layer_invalid_counts is None:
        return ValidationSummary(
            ok=True,
            message="invalid-geometries: not applicable (layer counts not provided)",
            status="na",
            details={"invalid_geometry_count": 0, "layer_invalid_counts": {}},
        )

    clean_counts: dict[str, int] = {}
    total_invalid = 0
    for layer_name, value in dict(layer_invalid_counts).items():
        try:
            count = int(value)
        except Exception as e:
            raise ValidationError(
                f"invalid-geometry counts must be integer-like; layer={layer_name!r}, value={value!r}: {e}"
            ) from e
        if count < 0:
            raise ValidationError(
                f"invalid-geometry counts must be >= 0; layer={layer_name!r}, value={count}"
            )
        clean_counts[str(layer_name)] = count
        total_invalid += count

    metric = count_exceedance_summary(
        count=total_invalid,
        warn_above=warn_above,
        fail_above=fail_above,
        name="invalid_geometries",
    )
    status = _validate_status(metric.status)
    message = (
        "invalid-geometries: "
        f"layers={len(clean_counts)}, invalid_geometry_count={total_invalid}, status={status}"
    )
    return ValidationSummary(
        ok=status != "fail",
        message=message,
        status=status,
        details={
            "invalid_geometry_count": int(total_invalid),
            "layer_invalid_counts": clean_counts,
            "warn_above": int(warn_above),
            "fail_above": int(fail_above),
        },
    )


def validate_assignment_share_thresholds(
    overlap_table: object,
    *,
    district_id_col: str = "district_id",
    share_col: str = "ovl_share",
    is_assigned_col: str = "is_assigned",
    warn_below: float = 0.95,
    fail_below: float = 0.80,
    share_bound_tol: float = DEFAULT_SHARE_BOUND_TOL,
) -> ValidationSummary:
    """Evaluate assigned overlap shares against lower-bound thresholds.

    Shares are evaluated against an explicit machine-precision tolerance at the
    closed interval bounds. Raw shares remain unchanged in the overlap table for
    audit, while the validator clamps only those values that lie within
    ``share_bound_tol`` of 0 or 1 before threshold evaluation.

    Status is:
    - fail: any assigned share is materially invalid or below ``fail_below``
    - warn: none fail, but one or more are below ``warn_below``
    - pass: all assigned shares meet the warning threshold
    - na: no assigned rows were available to evaluate
    """

    df = _as_dataframe(overlap_table, obj_name="overlap_table")
    _require_columns(df, [district_id_col, share_col], obj_name="overlap_table")

    if is_assigned_col in df.columns:
        assigned = df.loc[_coerce_bool_mask(df[is_assigned_col])].copy()
    else:
        assigned = df.copy()

    if assigned.empty:
        return ValidationSummary(
            ok=True,
            message="assignment-share thresholds: no assigned rows to evaluate",
            status="na",
            details={"assigned_rows": 0},
        )

    normalised = normalise_share_series_for_validation(
        assigned[share_col], bound_tol=share_bound_tol
    )
    invalid_count = int(normalised.invalid_mask.sum())
    valid_shares = normalised.normalised_shares.loc[~normalised.invalid_mask].tolist()

    metrics = share_metric_summary(valid_shares, warn_below=warn_below, fail_below=fail_below)
    status = "pass"
    if invalid_count > 0 or metrics.fail_count > 0:
        status = "fail"
    elif metrics.warn_count > 0:
        status = "warn"

    message = (
        "assignment-share thresholds: "
        f"assigned_rows={len(assigned)}, invalid={invalid_count}, "
        f"warn_count={metrics.warn_count}, fail_count={metrics.fail_count}, "
        f"min_share={metrics.min_share}"
    )
    return ValidationSummary(
        ok=status != "fail",
        message=message,
        status=status,
        details={
            "assigned_rows": int(len(assigned)),
            "invalid_share_count": invalid_count,
            "clamped_low_count": int(normalised.clamped_low_count),
            "clamped_high_count": int(normalised.clamped_high_count),
            "share_bound_tol": float(normalised.bound_tol),
            "warn_count": int(metrics.warn_count),
            "fail_count": int(metrics.fail_count),
            "min_share": metrics.min_share,
            "mean_share": metrics.mean_share,
            "max_share": metrics.max_share,
            "raw_min_share": (
                None
                if normalised.raw_shares.loc[~normalised.invalid_mask].empty
                else float(normalised.raw_shares.loc[~normalised.invalid_mask].min())
            ),
            "raw_max_share": (
                None
                if normalised.raw_shares.loc[~normalised.invalid_mask].empty
                else float(normalised.raw_shares.loc[~normalised.invalid_mask].max())
            ),
            "warn_below": float(warn_below),
            "fail_below": float(fail_below),
        },
    )


def require_assignment_share_thresholds(
    overlap_table: object,
    *,
    district_id_col: str = "district_id",
    share_col: str = "ovl_share",
    is_assigned_col: str = "is_assigned",
    warn_below: float = 0.95,
    fail_below: float = 0.80,
    share_bound_tol: float = DEFAULT_SHARE_BOUND_TOL,
) -> ValidationSummary:
    summary = validate_assignment_share_thresholds(
        overlap_table,
        district_id_col=district_id_col,
        share_col=share_col,
        is_assigned_col=is_assigned_col,
        warn_below=warn_below,
        fail_below=fail_below,
        share_bound_tol=share_bound_tol,
    )
    return _raise_if_fail(summary)


def validate_area_consistency(
    overlap_table: object,
    *,
    district_id_col: str = "district_id",
    district_area_col: str = "district_area",
    intersection_area_col: str = "intersection_area",
    warn_above: float = 0.01,
    fail_above: float = 0.05,
) -> ValidationSummary:
    """Evaluate district-vs-overlap area closure consistency.

    For each district, the validator compares the summed positive overlap area
    against the district area used as the share denominator. This is a direct
    check of whether the district×zone overlay closes as expected.
    """

    df = _as_dataframe(overlap_table, obj_name="overlap_table")
    _require_columns(
        df, [district_id_col, district_area_col, intersection_area_col], obj_name="overlap_table"
    )

    if df.empty:
        return ValidationSummary(
            ok=True,
            message="area-consistency: no overlap rows to evaluate",
            status="na",
            details={"districts_evaluated": 0},
        )

    work = df[[district_id_col, district_area_col, intersection_area_col]].copy()
    for col in [district_area_col, intersection_area_col]:
        work[col] = _coerce_numeric_series(work[col], obj_name=col).astype(float)

    invalid_area_rows = int((work[district_area_col].isna() | (work[district_area_col] <= 0)).sum())
    invalid_intersection_rows = int(
        (work[intersection_area_col].isna() | (work[intersection_area_col] < 0)).sum()
    )

    grouped = work.groupby(district_id_col, dropna=False)
    district_area_first = grouped[district_area_col].first()
    district_area_min = grouped[district_area_col].min()
    district_area_max = grouped[district_area_col].max()
    district_area_inconsistent = int((district_area_max - district_area_min > 0).sum())
    intersection_sum = grouped[intersection_area_col].sum()

    rel_diffs: list[float] = []
    worst_examples: list[dict[str, object]] = []
    for district_id, dist_area in district_area_first.items():
        if dist_area is None or float(dist_area) <= 0:
            continue
        total_intersection = float(intersection_sum.loc[district_id])
        rel_diff = abs(total_intersection - float(dist_area)) / float(dist_area)
        rel_diffs.append(rel_diff)
        worst_examples.append(
            {
                district_id_col: district_id,
                "district_area": float(dist_area),
                "intersection_area_sum": total_intersection,
                "relative_difference": rel_diff,
            }
        )

    worst_examples = sorted(
        worst_examples, key=lambda x: float(x["relative_difference"]), reverse=True
    )[:10]
    metrics = area_difference_summary(rel_diffs, warn_above=warn_above, fail_above=fail_above)

    status = "pass"
    if (
        invalid_area_rows > 0
        or invalid_intersection_rows > 0
        or district_area_inconsistent > 0
        or metrics.fail_count > 0
    ):
        status = "fail"
    elif metrics.warn_count > 0:
        status = "warn"

    message = (
        "area-consistency: "
        f"districts={len(district_area_first)}, invalid_area_rows={invalid_area_rows}, "
        f"invalid_intersection_rows={invalid_intersection_rows}, "
        f"district_area_inconsistent={district_area_inconsistent}, "
        f"warn_count={metrics.warn_count}, fail_count={metrics.fail_count}, "
        f"max_abs_rel_diff={metrics.max_abs_rel_diff}"
    )
    return ValidationSummary(
        ok=status != "fail",
        message=message,
        status=status,
        details={
            "districts_evaluated": int(len(district_area_first)),
            "invalid_district_area_rows": invalid_area_rows,
            "invalid_intersection_rows": invalid_intersection_rows,
            "district_area_inconsistent_count": district_area_inconsistent,
            "warn_count": int(metrics.warn_count),
            "fail_count": int(metrics.fail_count),
            "max_abs_rel_diff": metrics.max_abs_rel_diff,
            "mean_abs_rel_diff": metrics.mean_abs_rel_diff,
            "warn_above": float(warn_above),
            "fail_above": float(fail_above),
            "worst_examples": worst_examples,
        },
    )


def require_area_consistency(
    overlap_table: object,
    *,
    district_id_col: str = "district_id",
    district_area_col: str = "district_area",
    intersection_area_col: str = "intersection_area",
    warn_above: float = 0.01,
    fail_above: float = 0.05,
) -> ValidationSummary:
    summary = validate_area_consistency(
        overlap_table,
        district_id_col=district_id_col,
        district_area_col=district_area_col,
        intersection_area_col=intersection_area_col,
        warn_above=warn_above,
        fail_above=fail_above,
    )
    return _raise_if_fail(summary)


def validate_assignment_presence(
    table: object,
    *,
    district_id_col: str = "district_id",
    zone_id_col: str = "zone_id",
    share_col: str = "ovl_share",
    warn_above: int = 0,
    fail_above: int = 0,
) -> ValidationSummary:
    """Evaluate whether assignments are present and numerically valid.

    The input may be either the enriched district table or the overlap table. A
    row is considered invalid when ``zone_id`` is missing, share is null, or
    share is non-positive.
    """

    df = _as_dataframe(table, obj_name="assignment_table")
    _require_columns(df, [district_id_col, zone_id_col, share_col], obj_name="assignment_table")

    share_values = _coerce_numeric_series(df[share_col], obj_name=share_col).astype(float)
    invalid_mask = df[zone_id_col].isna() | share_values.isna() | (share_values <= 0)
    invalid_rows = int(invalid_mask.sum())
    affected_districts = (
        int(df.loc[invalid_mask, district_id_col].nunique()) if invalid_rows > 0 else 0
    )

    metric = count_exceedance_summary(
        count=affected_districts,
        warn_above=warn_above,
        fail_above=fail_above,
        name="assignment_presence",
    )
    status = _validate_status(metric.status)
    message = (
        "assignment-presence: "
        f"affected_districts={affected_districts}, invalid_rows={invalid_rows}, status={status}"
    )
    return ValidationSummary(
        ok=status != "fail",
        message=message,
        status=status,
        details={
            "affected_districts": affected_districts,
            "invalid_rows": invalid_rows,
            "warn_above": int(warn_above),
            "fail_above": int(fail_above),
        },
    )


def require_assignment_presence(
    table: object,
    *,
    district_id_col: str = "district_id",
    zone_id_col: str = "zone_id",
    share_col: str = "ovl_share",
    warn_above: int = 0,
    fail_above: int = 0,
) -> ValidationSummary:
    summary = validate_assignment_presence(
        table,
        district_id_col=district_id_col,
        zone_id_col=zone_id_col,
        share_col=share_col,
        warn_above=warn_above,
        fail_above=fail_above,
    )
    return _raise_if_fail(summary)


def validate_legacy_assignment_agreement(
    table: object,
    *,
    district_id_col: str = "district_id",
    legacy_zone_id_col: str = "legacy_zone_id",
    recomputed_zone_id_col: str = "zone_id",
    legacy_present_col: str = "legacy_assignment_present",
    warn_above: int = 0,
    fail_above: int = 0,
) -> ValidationSummary:
    """Evaluate disagreement between legacy and recomputed assignments when present."""

    df = _as_dataframe(table, obj_name="assignment_table")

    required = [district_id_col, recomputed_zone_id_col]
    if any(c not in df.columns for c in [legacy_zone_id_col, legacy_present_col]):
        return ValidationSummary(
            ok=True,
            message="legacy-assignment agreement: not applicable (legacy columns absent)",
            status="na",
            details={"districts_compared": 0, "disagreement_count": 0},
        )
    _require_columns(
        df, required + [legacy_zone_id_col, legacy_present_col], obj_name="assignment_table"
    )

    present_mask = _coerce_bool_mask(df[legacy_present_col])
    comparable = df.loc[present_mask].copy()
    if comparable.empty:
        return ValidationSummary(
            ok=True,
            message="legacy-assignment agreement: no legacy assignments present",
            status="na",
            details={"districts_compared": 0, "disagreement_count": 0},
        )

    disagreement_mask = comparable[legacy_zone_id_col].astype(str) != comparable[
        recomputed_zone_id_col
    ].astype(str)
    disagreement_count = int(disagreement_mask.sum())

    metric = count_exceedance_summary(
        count=disagreement_count,
        warn_above=warn_above,
        fail_above=fail_above,
        name="legacy_assignment_disagreement",
    )
    status = _validate_status(metric.status)
    examples = comparable.loc[
        disagreement_mask, [district_id_col, legacy_zone_id_col, recomputed_zone_id_col]
    ].head(10)
    message = (
        "legacy-assignment agreement: "
        f"districts_compared={len(comparable)}, disagreement_count={disagreement_count}, status={status}"
    )
    return ValidationSummary(
        ok=status != "fail",
        message=message,
        status=status,
        details={
            "districts_compared": int(len(comparable)),
            "disagreement_count": disagreement_count,
            "warn_above": int(warn_above),
            "fail_above": int(fail_above),
            "examples": examples.to_dict(orient="records"),
        },
    )


def require_legacy_assignment_agreement(
    table: object,
    *,
    district_id_col: str = "district_id",
    legacy_zone_id_col: str = "legacy_zone_id",
    recomputed_zone_id_col: str = "zone_id",
    legacy_present_col: str = "legacy_assignment_present",
    warn_above: int = 0,
    fail_above: int = 0,
) -> ValidationSummary:
    summary = validate_legacy_assignment_agreement(
        table,
        district_id_col=district_id_col,
        legacy_zone_id_col=legacy_zone_id_col,
        recomputed_zone_id_col=recomputed_zone_id_col,
        legacy_present_col=legacy_present_col,
        warn_above=warn_above,
        fail_above=fail_above,
    )
    return _raise_if_fail(summary)


def run_basic_validators(
    gdf: object,
    *,
    non_null: Iterable[str] | None = None,
    unique: Iterable[Sequence[str]] | None = None,
    check_geometry: bool = True,
) -> list[ValidationSummary]:
    """Convenience runner; raises on first failure."""

    out: list[ValidationSummary] = []
    if non_null:
        out.append(require_non_null(gdf, list(non_null)))
    if unique:
        for cols in unique:
            out.append(require_unique(gdf, list(cols)))
    if check_geometry:
        out.append(require_geometry_valid(gdf))
    return out


def run_assignment_validators(
    overlap_table: object,
    *,
    share_warn_below: float = 0.95,
    share_fail_below: float = 0.80,
    share_bound_tol: float = DEFAULT_SHARE_BOUND_TOL,
    area_warn_above: float = 0.01,
    area_fail_above: float = 0.05,
    missing_warn_above: int = 0,
    missing_fail_above: int = 0,
    invalid_geometry_warn_above: int = 0,
    invalid_geometry_fail_above: int = 0,
    invalid_geometry_layer_counts: Mapping[str, object] | None = None,
    legacy_disagreement_warn_above: int = 0,
    legacy_disagreement_fail_above: int = 0,
) -> list[ValidationSummary]:
    """Run the assignment-oriented validators without mutating inputs."""

    out = [
        validate_assignment_share_thresholds(
            overlap_table,
            warn_below=share_warn_below,
            fail_below=share_fail_below,
            share_bound_tol=share_bound_tol,
        ),
        validate_area_consistency(
            overlap_table,
            warn_above=area_warn_above,
            fail_above=area_fail_above,
        ),
        validate_assignment_presence(
            overlap_table,
            warn_above=missing_warn_above,
            fail_above=missing_fail_above,
        ),
        validate_invalid_geometry_counts(
            layer_invalid_counts=invalid_geometry_layer_counts,
            warn_above=invalid_geometry_warn_above,
            fail_above=invalid_geometry_fail_above,
        ),
        validate_legacy_assignment_agreement(
            overlap_table,
            warn_above=legacy_disagreement_warn_above,
            fail_above=legacy_disagreement_fail_above,
        ),
    ]
    return out
