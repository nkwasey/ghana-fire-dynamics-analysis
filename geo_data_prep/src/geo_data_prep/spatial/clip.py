"""geo_data_prep.spatial.clip

Optional AOI clipping.

This module performs no I/O. It expects GeoDataFrames already loaded (typically
via geo_data_prep.io.read.read_shapefile) and clips them to an AOI geometry
when enabled by config.
"""

from __future__ import annotations


class ClipError(RuntimeError):
    """Raised when AOI clipping fails."""


def _require_geopandas() -> object:
    try:
        import geopandas as gpd  # type: ignore

        return gpd
    except Exception as e:  # pragma: no cover
        raise ClipError(
            "geopandas is required for clip operations. Install via conda env (environment.yml)."
        ) from e


def _crs_equal(src_crs: object, working_crs: str) -> bool:
    try:
        from pyproj import CRS  # type: ignore

        return CRS.from_user_input(src_crs) == CRS.from_user_input(working_crs)
    except Exception:
        return str(src_crs) == str(working_crs)


def clip_to_aoi(gdf: object, aoi: object, *, working_crs: str) -> object:
    """Clip a GeoDataFrame to an AOI geometry (dissolved to one polygon)."""

    gpd = _require_geopandas()

    if getattr(gdf, "crs", None) is None:
        raise ClipError("gdf CRS is missing")
    if getattr(aoi, "crs", None) is None:
        raise ClipError("aoi CRS is missing")

    gg = gdf
    aa = aoi
    if not _crs_equal(gg.crs, working_crs):
        gg = gg.to_crs(working_crs)
    if not _crs_equal(aa.crs, working_crs):
        aa = aa.to_crs(working_crs)

    try:
        # GeoPandas 1.0+ prefers union_all(); keep a fallback for older stacks.
        if hasattr(aa.geometry, "union_all"):
            geom = aa.geometry.union_all()
        else:  # pragma: no cover
            geom = aa.geometry.unary_union
    except Exception as e:
        raise ClipError(f"Failed to dissolve AOI geometry: {e}") from e

    if geom is None:
        raise ClipError("AOI geometry is empty")

    aoi_one = gpd.GeoDataFrame({"_aoi": [1]}, geometry=[geom], crs=working_crs)

    try:
        out = gpd.clip(gg, aoi_one)
    except Exception as e:
        raise ClipError(f"Clip failed: {e}") from e

    return out


def maybe_clip_to_aoi(
    gdf: object,
    *,
    aoi: object | None,
    enabled: bool,
    working_crs: str,
) -> object:
    """Apply AOI clipping if enabled; otherwise return the input unchanged."""

    if not enabled:
        return gdf
    if aoi is None:
        raise ClipError("AOI clipping enabled but AOI layer is None")
    return clip_to_aoi(gdf, aoi, working_crs=working_crs)
