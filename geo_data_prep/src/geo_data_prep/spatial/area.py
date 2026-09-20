"""Reusable area-calculation helpers for Stage 1 geodata preparation.

This module is small, explicit and deterministic. It provides one shared
implementation for projected and geodesic area calculations without duplicating
logic across the Stage 1 workflow.
"""

from __future__ import annotations

from dataclasses import dataclass


class AreaComputationError(RuntimeError):
    """Raised when an area computation or CRS operation fails."""


@dataclass(frozen=True)
class AreaMethodSummary:
    """Summary of a chosen area-calculation policy."""

    method: str
    units: str
    projected_crs: str | None
    geodesic_ellipsoid: str


@dataclass(frozen=True)
class AreaComparisonSummary:
    """Small, audit-friendly comparison bundle for two area estimates."""

    projected_sq_m: float
    geodesic_sq_m: float
    abs_diff_sq_m: float
    rel_diff: float | None


def _require_geospatial_deps() -> tuple[object, object, object]:
    try:
        import geopandas as gpd  # type: ignore
    except Exception as e:  # pragma: no cover
        raise AreaComputationError(
            "geopandas is required for area calculations. Install via environment.yml."
        ) from e

    try:
        from pyproj import CRS, Geod  # type: ignore
    except Exception as e:  # pragma: no cover
        raise AreaComputationError(
            "pyproj is required for CRS-aware and geodesic area calculations. "
            "Install via environment.yml."
        ) from e

    return gpd, CRS, Geod


def _normalise_method(method: str) -> str:
    m = str(method).strip()
    allowed = {"projected", "geodesic", "both"}
    if m not in allowed:
        raise AreaComputationError(f"area method must be one of {sorted(allowed)}")
    return m


def _normalise_units(units: str) -> str:
    u = str(units).strip()
    allowed = {"sq_m", "sq_km"}
    if u not in allowed:
        raise AreaComputationError(f"area units must be one of {sorted(allowed)}")
    return u


def _crs_equal(src_crs: object, dst_crs: str) -> bool:
    _, CRS, _ = _require_geospatial_deps()
    try:
        return CRS.from_user_input(src_crs) == CRS.from_user_input(dst_crs)
    except Exception:
        return str(src_crs) == str(dst_crs)


def projected_area_series(
    gdf: object,
    *,
    projected_crs: str | None = None,
    units: str = "sq_km",
) -> object:
    """Return a pandas Series of projected polygon areas.

    Parameters
    ----------
    gdf:
        GeoDataFrame-like object with ``geometry`` and ``crs``.
    projected_crs:
        CRS in which area should be computed. If omitted, the current CRS is used
        and must already be projected.
    units:
        ``sq_m`` or ``sq_km``.
    """

    gpd, CRS, _ = _require_geospatial_deps()
    del gpd  # imported only for dependency validation and caller expectations

    units = _normalise_units(units)

    if getattr(gdf, "crs", None) is None:
        raise AreaComputationError("GeoDataFrame CRS is missing")

    working = gdf
    if projected_crs is not None and not _crs_equal(gdf.crs, projected_crs):
        try:
            working = gdf.to_crs(projected_crs)
        except Exception as e:
            raise AreaComputationError(
                f"Failed to reproject geometries to projected area CRS {projected_crs}: {e}"
            ) from e

    try:
        crs_obj = CRS.from_user_input(working.crs)
    except Exception as e:
        raise AreaComputationError(f"Invalid CRS on projected-area input: {e}") from e

    if not bool(getattr(crs_obj, "is_projected", False)):
        raise AreaComputationError(
            "Projected area computation requires a projected CRS; "
            f"got {getattr(working, 'crs', None)}"
        )

    try:
        areas_sq_m = working.geometry.area.astype(float)
    except Exception as e:
        raise AreaComputationError(f"Failed to compute projected geometry areas: {e}") from e

    if units == "sq_m":
        return areas_sq_m
    return areas_sq_m / 1_000_000.0


def geodesic_area_series(
    gdf: object,
    *,
    ellipsoid: str = "WGS84",
    units: str = "sq_km",
) -> object:
    """Return a pandas Series of geodesic polygon areas.

    Areas are computed on the supplied ellipsoid after reprojecting geometries to
    EPSG:4326 when necessary.
    """

    _, _, Geod = _require_geospatial_deps()
    units = _normalise_units(units)

    if getattr(gdf, "crs", None) is None:
        raise AreaComputationError("GeoDataFrame CRS is missing")

    try:
        geo = gdf if _crs_equal(gdf.crs, "EPSG:4326") else gdf.to_crs("EPSG:4326")
    except Exception as e:
        raise AreaComputationError(f"Failed to reproject geometries to EPSG:4326: {e}") from e

    try:
        geod = Geod(ellps=str(ellipsoid))
    except Exception as e:
        raise AreaComputationError(f"Invalid geodesic ellipsoid '{ellipsoid}': {e}") from e

    def _geom_area_sq_m(geom: object) -> float:
        if geom is None:
            return 0.0
        if getattr(geom, "is_empty", False):
            return 0.0
        try:
            area, _ = geod.geometry_area_perimeter(geom)
        except Exception as e:
            raise AreaComputationError(f"Failed geodesic area computation: {e}") from e
        return abs(float(area))

    try:
        out = geo.geometry.apply(_geom_area_sq_m).astype(float)
    except Exception as e:
        if isinstance(e, AreaComputationError):
            raise
        raise AreaComputationError(f"Failed while applying geodesic area calculation: {e}") from e

    if units == "sq_m":
        return out
    return out / 1_000_000.0


def area_series_from_policy(
    gdf: object,
    *,
    method: str,
    projected_crs: str | None = None,
    geodesic_ellipsoid: str = "WGS84",
    units: str = "sq_km",
) -> object:
    """Dispatch area computation according to a policy declaration."""

    method = _normalise_method(method)
    if method == "projected":
        return projected_area_series(gdf, projected_crs=projected_crs, units=units)
    if method == "geodesic":
        return geodesic_area_series(gdf, ellipsoid=geodesic_ellipsoid, units=units)
    raise AreaComputationError(
        "area_series_from_policy supports a single output method only; "
        "use compare_projected_and_geodesic_areas() when you need both."
    )


def add_area_column(
    gdf: object,
    *,
    column_name: str = "area_sqkm",
    method: str = "projected",
    projected_crs: str | None = None,
    geodesic_ellipsoid: str = "WGS84",
    units: str = "sq_km",
) -> object:
    """Return a copy of ``gdf`` with one deterministic area column added."""

    if not isinstance(column_name, str) or not column_name.strip():
        raise AreaComputationError("column_name must be a non-empty string")

    out = gdf.copy()
    out[column_name] = area_series_from_policy(
        out,
        method=method,
        projected_crs=projected_crs,
        geodesic_ellipsoid=geodesic_ellipsoid,
        units=units,
    )
    return out


def compare_projected_and_geodesic_areas(
    gdf: object,
    *,
    projected_crs: str | None = None,
    geodesic_ellipsoid: str = "WGS84",
) -> AreaComparisonSummary:
    """Compare total projected and geodesic areas across a GeoDataFrame."""

    projected = float(projected_area_series(gdf, projected_crs=projected_crs, units="sq_m").sum())
    geodesic = float(geodesic_area_series(gdf, ellipsoid=geodesic_ellipsoid, units="sq_m").sum())
    abs_diff = abs(projected - geodesic)
    rel_diff = None if geodesic <= 0 else abs_diff / geodesic
    return AreaComparisonSummary(
        projected_sq_m=projected,
        geodesic_sq_m=geodesic,
        abs_diff_sq_m=abs_diff,
        rel_diff=rel_diff,
    )


def area_method_summary(
    *,
    method: str,
    units: str,
    projected_crs: str | None,
    geodesic_ellipsoid: str,
) -> AreaMethodSummary:
    """Return a small frozen summary useful for manifests and audit sidecars."""

    return AreaMethodSummary(
        method=_normalise_method(method),
        units=_normalise_units(units),
        projected_crs=projected_crs,
        geodesic_ellipsoid=str(geodesic_ellipsoid),
    )
