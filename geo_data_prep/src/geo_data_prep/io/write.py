"""geo_data_prep.io.write

Robust Shapefile writing with strict post-write validation.

Write contract:
- Write Shapefile outputs explicitly
- Verify sidecars exist after write: .shp/.dbf/.shx/.prj/.cpg
- Enforce the column contract presence and detect field-name collisions
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


class WriteError(RuntimeError):
    """Raised when writing an output layer fails."""


@dataclass(frozen=True)
class WriteResult:
    """Return object for writes."""

    shp_path: Path
    sidecars: dict[str, Path]


_REQUIRED_SIDECARS: tuple[str, ...] = (".shp", ".dbf", ".shx", ".prj", ".cpg")


def _require_geopandas() -> object:
    try:
        import geopandas as gpd  # type: ignore

        return gpd
    except Exception as e:  # pragma: no cover
        raise WriteError(
            "geopandas is required for IO. Install via conda env (environment.yml) or pip extras."
        ) from e


def _check_column_contract(gdf: object, required_columns: Sequence[str]) -> None:
    missing = [c for c in required_columns if c not in getattr(gdf, "columns", [])]
    if missing:
        raise WriteError(f"Missing required contract columns: {missing}")


def _check_field_name_rules(columns: Iterable[str]) -> None:
    """Validate Shapefile field constraints.

    We enforce:
    - non-geometry fields <= 10 chars (to keep names intact)
    - case-insensitive uniqueness
    - no truncation collisions (upper(col[:10]))
    """

    cols = [c for c in columns if c != "geometry"]

    too_long = [c for c in cols if len(c) > 10]
    if too_long:
        raise WriteError(
            "Shapefile field names must be <= 10 characters to remain intact. "
            f"Too long: {too_long}"
        )

    seen_ci: dict[str, list[str]] = {}
    for c in cols:
        key = c.casefold()
        seen_ci.setdefault(key, []).append(c)
    dup_ci = {k: v for k, v in seen_ci.items() if len(v) > 1}
    if dup_ci:
        raise WriteError(f"Duplicate field names (case-insensitive): {dup_ci}")

    # Truncation collisions (defensive; with <=10 chars, this mostly catches case-only differences).
    trunc_map: dict[str, list[str]] = {}
    for c in cols:
        t = c[:10].upper()
        trunc_map.setdefault(t, []).append(c)
    collisions = {k: v for k, v in trunc_map.items() if len(v) > 1}
    if collisions:
        raise WriteError(f"Shapefile field-name collisions under 10-char truncation: {collisions}")


def _ensure_cpg(path: Path, *, encoding: str) -> None:
    # .cpg is a single-line file that declares encoding.
    path.write_text(encoding, encoding="utf-8")


def _ensure_prj(path: Path, *, crs: object) -> None:
    try:
        from pyproj import CRS  # type: ignore

        wkt = CRS.from_user_input(crs).to_wkt()
    except Exception as e:  # pragma: no cover
        raise WriteError(f"Failed to derive WKT for CRS when creating .prj: {e}") from e
    path.write_text(wkt, encoding="utf-8")


def write_shapefile(
    gdf: object,
    *,
    shp_path: Path,
    required_columns: Sequence[str],
    encoding: str = "UTF-8",
) -> WriteResult:
    """Write a GeoDataFrame to an ESRI Shapefile bundle with guaranteed sidecars.

    Parameters
    ----------
    gdf:
        GeoDataFrame.
    shp_path:
        Output .shp path.
    required_columns:
        Contract columns that must be present before writing.
    encoding:
        Encoding to request from driver; also used for .cpg if missing.
    """

    p = Path(shp_path)
    if p.suffix.lower() != ".shp":
        raise WriteError(f"Output path must end with .shp: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)

    if getattr(gdf, "crs", None) is None:
        raise WriteError("GeoDataFrame CRS is missing; cannot write Shapefile with .prj")

    _check_column_contract(gdf, required_columns=required_columns)
    _check_field_name_rules(getattr(gdf, "columns", []))

    _require_geopandas()  # ensures dependency is present before calling to_file
    try:
        # index=False prevents an unwanted index field in the DBF.
        gdf.to_file(p, driver="ESRI Shapefile", encoding=encoding, index=False)
    except Exception as e:
        raise WriteError(f"Failed to write Shapefile: {p}: {e}") from e

    sidecars: dict[str, Path] = {ext: p.with_suffix(ext) for ext in _REQUIRED_SIDECARS}

    # Ensure .cpg and .prj exist even if driver skipped them.
    if not sidecars[".cpg"].exists():
        _ensure_cpg(sidecars[".cpg"], encoding=encoding)
    if not sidecars[".prj"].exists():
        _ensure_prj(sidecars[".prj"], crs=getattr(gdf, "crs", None))

    missing = [ext for ext, fp in sidecars.items() if not fp.exists()]
    if missing:
        raise WriteError(f"Shapefile sidecars missing after write: {missing} (base={p})")

    return WriteResult(shp_path=p, sidecars=sidecars)
