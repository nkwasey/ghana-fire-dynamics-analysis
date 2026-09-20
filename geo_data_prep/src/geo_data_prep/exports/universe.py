"""geo_data_prep.exports.universe

Build the unit universe export (CSV).

The unit universe is a simple, audit-friendly table describing the hierarchical
administrative unit set used by Stage 1 outputs:
- zone units (e.g., ACZ/AEZ)
- district units, each referencing a parent zone

This module is intentionally *pure export logic*:
- It does not attempt to run the full processing pipeline.
- Callers provide GeoDataFrames that already satisfy the Stage 1 column contract.

Contract properties
-------------------
- Preserves ``unit_id`` and ``parent_id`` as the canonical relational keys.
- Adds ``unit_code`` and ``parent_code`` as explicit code-metadata fields in the
  logical ``unit_universe.csv`` contract.
- Zone rows always expose ``unit_code = zone_code`` and a blank ``parent_code``.
- District rows always expose ``parent_code = zone_code``.
- District rows expose ``unit_code = district_code`` only when a district-code
  field exists upstream and the value is present; otherwise ``unit_code`` is blank.
- Preserves the fixed ``area_sqkm`` column and the shared Stage 1 area-policy
  implementation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from geo_data_prep.spatial.area import AreaComputationError, area_series_from_policy

DistrictAreaPolicy = Literal["compute", "blank"]


class UniverseExportError(RuntimeError):
    """Raised when building or writing the unit universe fails."""


def _require_pandas() -> object:
    try:
        import pandas as pd  # type: ignore

        return pd
    except Exception as e:  # pragma: no cover
        raise UniverseExportError("pandas is required for CSV exports") from e


def _require_cols(gdf: object, cols: Sequence[str], *, obj_name: str) -> None:
    missing = [c for c in cols if c not in getattr(gdf, "columns", [])]
    if missing:
        raise UniverseExportError(f"{obj_name} missing required columns: {missing}")


@dataclass(frozen=True)
class UnitUniverseColumns:
    """Logical column names for inputs (not constrained by Shapefile limits)."""

    zone_id: str = "zone_id"
    zone_name: str = "zone_name"
    zone_code: str = "zone_code"

    district_id: str = "district_id"
    district_name: str = "district_name"
    district_code: str = "district_code"


_UNIVERSE_COL_ORDER: tuple[str, ...] = (
    "unit_type",
    "level",
    "unit_id",
    "unit_code",
    "unit_name",
    "parent_level",
    "parent_id",
    "parent_code",
    "parent_name",
    "area_sqkm",
)


def _compute_area_sqkm(
    gdf: object,
    *,
    area_method: str,
    area_projected_crs: str | None,
    area_geodesic_ellipsoid: str,
    area_units: str,
    obj_name: str,
) -> object:
    """Compute Stage 1 unit-universe areas under the declared area policy.

    The canonical CSV schema exposes only ``area_sqkm``. That means we can only
    faithfully represent single-method area outputs reported in square
    kilometres. Unsupported policy combinations must therefore fail fast.
    """

    if area_method == "both":
        raise UniverseExportError(
            f"{obj_name} area policy method='both' cannot be represented in the fixed "
            "unit_universe.csv schema, which exposes only one area_sqkm column"
        )
    if area_units != "sq_km":
        raise UniverseExportError(
            f"{obj_name} area policy units={area_units!r} cannot be represented in the fixed "
            "unit_universe.csv schema, which exposes area_sqkm"
        )

    try:
        return area_series_from_policy(
            gdf,
            method=area_method,
            projected_crs=area_projected_crs,
            geodesic_ellipsoid=area_geodesic_ellipsoid,
            units=area_units,
        )
    except AreaComputationError as e:
        raise UniverseExportError(
            f"Failed to compute {obj_name} area_sqkm from declared area policy: {e}"
        ) from e


def _string_series_or_blank(frame: object, col: str, *, pd: object) -> object:
    """Return a string series for ``col`` or blanks when the column is absent.

    The Stage 1 unit-universe contract allows district ``unit_code`` to be blank
    when no upstream district code exists. Missing values therefore normalise to
    the empty string rather than the literal text ``'nan'``.
    """

    if col not in getattr(frame, "columns", []):
        return pd.Series([""] * len(frame), index=getattr(frame, "index", None), dtype="object")  # type: ignore[attr-defined]

    series = frame[col]
    return series.map(lambda value: "" if pd.isna(value) else str(value))  # type: ignore[attr-defined]


def build_unit_universe_dataframe(
    zones: object,
    districts: object,
    *,
    zone_level_label: str,
    district_level_label: str,
    district_area_policy: DistrictAreaPolicy = "compute",
    cols: UnitUniverseColumns = UnitUniverseColumns(),  # noqa: B008
    area_method: str = "projected",
    area_projected_crs: str | None = None,
    area_geodesic_ellipsoid: str = "WGS84",
    area_units: str = "sq_km",
) -> object:
    """Build the unit universe as a pandas DataFrame (no file I/O)."""

    pd = _require_pandas()

    if not zone_level_label or not isinstance(zone_level_label, str):
        raise UniverseExportError("zone_level_label must be a non-empty string")
    if not district_level_label or not isinstance(district_level_label, str):
        raise UniverseExportError("district_level_label must be a non-empty string")

    _require_cols(zones, [cols.zone_id, cols.zone_name, cols.zone_code], obj_name="zones")
    _require_cols(
        districts, [cols.district_id, cols.district_name, cols.zone_id], obj_name="districts"
    )

    # If districts lack zone_name/zone_code, attach them from zones.
    need_zone_name = cols.zone_name not in getattr(districts, "columns", [])
    need_zone_code = cols.zone_code not in getattr(districts, "columns", [])
    d = districts
    if need_zone_name or need_zone_code:
        z_lu = (
            zones[[cols.zone_id, cols.zone_name, cols.zone_code]]
            .drop_duplicates(subset=[cols.zone_id])
            .copy()
        )
        d = d.merge(z_lu, on=cols.zone_id, how="left")

    # Validate that districts have parent zone resolved.
    if d[cols.zone_name].isna().any() or d[cols.zone_code].isna().any():  # type: ignore[index]
        bad = d.loc[d[cols.zone_name].isna() | d[cols.zone_code].isna(), cols.zone_id].head(5).tolist()  # type: ignore[index]
        raise UniverseExportError(
            "Some districts have missing parent zone fields after merge. "
            f"Example zone_id values: {bad}"
        )

    z_area = _compute_area_sqkm(
        zones,
        area_method=area_method,
        area_projected_crs=area_projected_crs,
        area_geodesic_ellipsoid=area_geodesic_ellipsoid,
        area_units=area_units,
        obj_name="zones",
    )

    if district_area_policy == "compute":
        d_area = _compute_area_sqkm(
            d,
            area_method=area_method,
            area_projected_crs=area_projected_crs,
            area_geodesic_ellipsoid=area_geodesic_ellipsoid,
            area_units=area_units,
            obj_name="districts",
        )
    elif district_area_policy == "blank":
        d_area = pd.Series([float("nan")] * len(d), index=d.index, dtype="float64")  # type: ignore[attr-defined]
    else:  # pragma: no cover
        raise UniverseExportError(f"Unknown district_area_policy: {district_area_policy}")

    z_df = pd.DataFrame(
        {
            "unit_type": "zone",
            "level": zone_level_label,
            "unit_id": zones[cols.zone_id].astype(str),
            "unit_code": zones[cols.zone_code].astype(str),
            "unit_name": zones[cols.zone_name].astype(str),
            "parent_level": "",
            "parent_id": "",
            "parent_code": "",
            "parent_name": "",
            "area_sqkm": z_area,
        }
    )

    d_df = pd.DataFrame(
        {
            "unit_type": "district",
            "level": district_level_label,
            "unit_id": d[cols.district_id].astype(str),
            "unit_code": _string_series_or_blank(d, cols.district_code, pd=pd),
            "unit_name": d[cols.district_name].astype(str),
            "parent_level": zone_level_label,
            "parent_id": d[cols.zone_id].astype(str),
            "parent_code": d[cols.zone_code].astype(str),
            "parent_name": d[cols.zone_name].astype(str),
            "area_sqkm": d_area,
        }
    )

    z_df = z_df.sort_values(["unit_id"], ascending=[True], kind="mergesort").reset_index(drop=True)
    d_df = d_df.sort_values(
        ["parent_id", "unit_id"], ascending=[True, True], kind="mergesort"
    ).reset_index(drop=True)

    out = pd.concat([z_df, d_df], axis=0, ignore_index=True)
    out = out[list(_UNIVERSE_COL_ORDER)]
    return out


def write_unit_universe_csv(
    zones: object,
    districts: object,
    *,
    out_dir: Path,
    zone_level_label: str,
    district_level_label: str,
    district_area_policy: DistrictAreaPolicy = "compute",
    filename: str = "unit_universe.csv",
    cols: UnitUniverseColumns = UnitUniverseColumns(),  # noqa: B008
    area_method: str = "projected",
    area_projected_crs: str | None = None,
    area_geodesic_ellipsoid: str = "WGS84",
    area_units: str = "sq_km",
) -> Path:
    """Write ``unit_universe.csv`` to ``out_dir`` and return the path."""

    pd = _require_pandas()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not filename.endswith(".csv"):
        raise UniverseExportError(f"filename must end with .csv: {filename}")

    df = build_unit_universe_dataframe(
        zones,
        districts,
        zone_level_label=zone_level_label,
        district_level_label=district_level_label,
        district_area_policy=district_area_policy,
        cols=cols,
        area_method=area_method,
        area_projected_crs=area_projected_crs,
        area_geodesic_ellipsoid=area_geodesic_ellipsoid,
        area_units=area_units,
    )

    out_path = out_dir / filename
    try:
        df.to_csv(out_path, index=False, encoding="utf-8", float_format="%.6f")
    except Exception as e:
        raise UniverseExportError(f"Failed to write CSV: {out_path}: {e}") from e

    try:
        read_back = pd.read_csv(out_path)
    except Exception as e:
        raise UniverseExportError(f"CSV written but could not be read back: {out_path}: {e}") from e

    if list(read_back.columns) != list(_UNIVERSE_COL_ORDER):
        raise UniverseExportError(
            "CSV schema mismatch after write/read roundtrip. "
            f"Expected={list(_UNIVERSE_COL_ORDER)}, got={list(read_back.columns)}"
        )

    return out_path
