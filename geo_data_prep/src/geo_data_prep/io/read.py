"""geo_data_prep.io.read

Robust Shapefile reading with strict validation.

Read contract:
- Read Shapefiles with GeoPandas
- Validate existence, CRS presence, polygon geometry, and configured fields
- Reproject to working_crs when needed

Notes:
- This module returns a ReadResult wrapper that retains provenance metadata.
  For ergonomics, ReadResult proxies common GeoDataFrame operations (len, attribute
  access, column selection) to the underlying GeoDataFrame.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd  # noqa: F401


class ReadError(RuntimeError):
    """Raised when reading or validating an input layer fails."""


@dataclass(frozen=True)
class ReadResult:
    """Result of reading a layer, including CRS provenance.

    Attributes
    ----------
    gdf:
        The GeoDataFrame in working CRS (reprojected if needed).
    source_path:
        Path to the source .shp file.
    source_crs:
        The CRS string as read from the source layer.
    working_crs:
        The target/working CRS string requested by the caller.
    """

    gdf: object  # GeoDataFrame (kept as object to avoid hard import at module import time)
    source_path: Path
    source_crs: str
    working_crs: str

    # --- Convenience proxying to behave like the underlying GeoDataFrame ---
    def __len__(self) -> int:
        return len(self.gdf)  # type: ignore[arg-type]

    @overload
    def __getitem__(self, key: str) -> object: ...
    @overload
    def __getitem__(self, key: Sequence[str]) -> object: ...
    def __getitem__(self, key):
        return self.gdf[key]  # type: ignore[index]

    def __iter__(self) -> Iterator:
        return iter(self.gdf)  # type: ignore[arg-type]

    def __getattr__(self, name: str):
        # Only called if normal attribute lookup fails.
        return getattr(self.gdf, name)


def _require_geopandas() -> object:
    try:
        import geopandas as gpd  # type: ignore

        return gpd
    except Exception as e:  # pragma: no cover
        raise ReadError(
            "geopandas is required for IO. Install via conda env (environment.yml) "
            "or add geopandas to your packaging dependencies."
        ) from e


def _require_sidecars_for_read(p: Path) -> None:
    """Fail fast with clear messages when essential Shapefile sidecars are missing.

    We treat .dbf and .shx as required for a valid Shapefile bundle.
    We treat CRS presence as binding; in practice that normally requires .prj.
    """
    required = [".dbf", ".shx"]
    missing = [ext for ext in required if not p.with_suffix(ext).exists()]
    if missing:
        raise ReadError(f"Missing required Shapefile sidecars for {p}: {missing}")

    # CRS is binding; .prj is the normal carrier. If it's missing, error early.
    if not p.with_suffix(".prj").exists():
        raise ReadError(
            f"Missing .prj sidecar for {p}. CRS is required (no-CRS inputs are forbidden)."
        )


def _crs_equal(src_crs: object, working_crs: str) -> bool:
    """Best-effort CRS equality without assuming pyproj is always importable."""
    try:
        from pyproj import CRS  # type: ignore

        return CRS.from_user_input(src_crs) == CRS.from_user_input(working_crs)
    except Exception:
        return str(src_crs) == str(working_crs)


def read_shapefile(
    path: str | Path,
    *,
    working_crs: str,
    required_fields: Sequence[str] | None = None,
    allowed_geom_types: Iterable[str] = ("Polygon", "MultiPolygon"),
) -> ReadResult:
    """Read a Shapefile and validate schema and geometry.

    Parameters
    ----------
    path:
        Path to the .shp file.
    working_crs:
        Target CRS (e.g., "EPSG:32630"). If input differs, the layer is reprojected.
    required_fields:
        Field names that must be present in the layer (e.g., configured label field).
    allowed_geom_types:
        Acceptable geometry types (default: Polygon/MultiPolygon).
    """
    p = Path(path).expanduser()

    # Existence & extension checks
    if not p.exists():
        raise ReadError(f"Input layer not found: {p}")
    if p.is_dir():
        raise ReadError(f"Input layer path is a directory, expected .shp: {p}")
    if p.suffix.lower() != ".shp":
        raise ReadError(f"Input layer must be a .shp file: {p}")

    # Fail fast on essential sidecars
    _require_sidecars_for_read(p)

    gpd = _require_geopandas()

    try:
        gdf = gpd.read_file(p)
    except Exception as e:
        raise ReadError(f"Failed to read Shapefile: {p}: {e}") from e

    # CRS required
    if getattr(gdf, "crs", None) is None:
        raise ReadError(f"CRS is missing on input layer: {p}")
    src_crs = str(gdf.crs)

    # Geometry presence & validity of basic structure
    if not hasattr(gdf, "geometry") or getattr(gdf, "geometry", None) is None:
        raise ReadError(f"Input layer has no geometry column: {p}")
    if len(gdf) == 0:
        raise ReadError(f"Input layer has zero features: {p}")
    try:
        if gdf.geometry.isna().all():  # type: ignore[union-attr]
            raise ReadError(f"Input layer has only null geometries: {p}")
    except ReadError:
        raise
    except Exception as e:
        raise ReadError(f"Failed while checking geometry nulls for {p}: {e}") from e

    # Geometry type gate
    allowed = {str(t) for t in allowed_geom_types}
    try:
        geom_types = {str(x) for x in set(gdf.geom_type.dropna().tolist())}
    except Exception as e:
        raise ReadError(f"Failed while inspecting geometry types for {p}: {e}") from e

    if not geom_types:
        raise ReadError(f"Could not determine geometry types (all null?) for {p}")
    if not geom_types.issubset(allowed):
        raise ReadError(
            f"Invalid geometry types for {p}. Allowed={sorted(allowed)}, found={sorted(geom_types)}"
        )

    # Required field checks
    if required_fields:
        missing = [c for c in required_fields if c not in gdf.columns]
        if missing:
            raise ReadError(f"Missing required fields in {p}: {missing}")

    # Reproject if needed (prefer CRS semantic equality when possible)
    if not _crs_equal(gdf.crs, working_crs):
        try:
            gdf = gdf.to_crs(working_crs)
        except Exception as e:
            raise ReadError(f"Failed to reproject {p} from {src_crs} to {working_crs}: {e}") from e

    return ReadResult(
        gdf=gdf,
        source_path=p,
        source_crs=src_crs,
        working_crs=str(working_crs),
    )
