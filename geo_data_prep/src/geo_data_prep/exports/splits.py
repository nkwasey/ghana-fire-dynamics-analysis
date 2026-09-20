"""geo_data_prep.exports.splits

Per-zone Shapefile splits.

Outputs (relative to out_dir)
-----------------------------
- splits/zones_split/<zone-split-filename>.shp
- splits/zone_districts/<district-split-filename>.shp
- splits/splits_manifest.json

District Shapefile field names must obey the Stage 1 Shapefile integrity rules
(<=10 chars). The Stage 1 logical district fields (e.g., ``district_id``) are
therefore written using Shapefile-safe aliases:
- district_id   -> dist_id
- district_name -> dist_name
- district_code -> dist_code (if present)

Contract properties
-------------------
- Uses the configured default filenames when no explicit basenames are supplied.
- Honours configured basenames when callers provide them.
- Emits a split manifest rather than bloating Shapefile schemas.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from geo_data_prep.io.write import WriteResult, write_shapefile


class SplitExportError(RuntimeError):
    """Raised when per-zone split exports fail."""


def _require_cols(gdf: object, cols: Sequence[str], *, obj_name: str) -> None:
    missing = [c for c in cols if c not in getattr(gdf, "columns", [])]
    if missing:
        raise SplitExportError(f"{obj_name} missing required columns: {missing}")


def _safe_filename_part(s: str) -> str:
    return str(s).replace("/", "_").replace("\\", "_")


def _safe_stem(name: str | None) -> str | None:
    if name is None:
        return None
    s = str(name).strip()
    if not s:
        raise SplitExportError("split basename must be a non-empty string when provided")
    s = s.replace("/", "_").replace("\\", "_")
    if s.lower().endswith(".shp"):
        s = s[:-4]
    return s


def _districts_shp_view(
    districts: object,
    *,
    district_id_col: str,
    district_name_col: str,
    district_code_col: str | None,
    zone_id_col: str,
    zone_name_col: str,
    zone_code_col: str,
    ovl_share_col: str,
) -> object:
    keep: list[str] = [
        district_id_col,
        district_name_col,
        zone_id_col,
        zone_name_col,
        zone_code_col,
        ovl_share_col,
        "geometry",
    ]
    if district_code_col and district_code_col in getattr(districts, "columns", []):
        keep.insert(2, district_code_col)

    d = districts[keep].copy()

    rename = {
        district_id_col: "dist_id",
        district_name_col: "dist_name",
        zone_id_col: zone_id_col,
        zone_name_col: zone_name_col,
        zone_code_col: zone_code_col,
        ovl_share_col: ovl_share_col,
    }
    if district_code_col and district_code_col in d.columns:
        rename[district_code_col] = "dist_code"

    d = d.rename(columns=rename)

    sort_cols = [zone_id_col, "dist_id"] if zone_id_col in d.columns else ["dist_id"]
    try:
        d = d.sort_values(sort_cols, ascending=[True] * len(sort_cols), kind="mergesort")
    except Exception:
        pass

    return d


def _zone_split_filename(zone_id: str, *, zones_basename: str | None) -> str:
    zid_safe = _safe_filename_part(zone_id)
    stem = _safe_stem(zones_basename)
    if stem is None:
        return f"zone_{zid_safe}.shp"
    return f"{stem}__zone_{zid_safe}.shp"


def _district_split_filename(zone_id: str, *, districts_basename: str | None) -> str:
    zid_safe = _safe_filename_part(zone_id)
    stem = _safe_stem(districts_basename)
    if stem is None:
        return f"zone_{zid_safe}_districts.shp"
    return f"{stem}__zone_{zid_safe}.shp"


@dataclass(frozen=True)
class SplitWriteOutputs:
    zones_written: list[WriteResult]
    districts_written: list[WriteResult]
    manifest_path: Path


def write_zone_splits(
    zones: object,
    districts_enriched: object,
    *,
    out_dir: Path,
    zone_id_col: str = "zone_id",
    zone_name_col: str = "zone_name",
    zone_code_col: str = "zone_code",
    district_id_col: str = "district_id",
    district_name_col: str = "district_name",
    district_code_col: str | None = "district_code",
    ovl_share_col: str = "ovl_share",
    zones_basename: str | None = None,
    districts_basename: str | None = None,
    manifest_filename: str = "splits_manifest.json",
) -> SplitWriteOutputs:
    """Write per-zone split Shapefiles under ``out_dir/splits/``."""

    out_dir = Path(out_dir)

    _require_cols(zones, [zone_id_col, zone_name_col, zone_code_col], obj_name="zones")
    _require_cols(
        districts_enriched,
        [
            district_id_col,
            district_name_col,
            zone_id_col,
            zone_name_col,
            zone_code_col,
            ovl_share_col,
        ],
        obj_name="districts_enriched",
    )

    try:
        if zones[zone_id_col].duplicated().any():  # type: ignore[index]
            raise SplitExportError(f"zones have duplicate {zone_id_col} values")
    except SplitExportError:
        raise
    except Exception as e:
        raise SplitExportError(f"Failed while checking zone uniqueness: {e}") from e

    zones_dir = out_dir / "splits" / "zones_split"
    dists_dir = out_dir / "splits" / "zone_districts"
    zones_dir.mkdir(parents=True, exist_ok=True)
    dists_dir.mkdir(parents=True, exist_ok=True)

    zones_written: list[WriteResult] = []
    districts_written: list[WriteResult] = []
    manifest_rows: list[dict[str, object]] = []

    try:
        zone_ids: Iterable[str] = sorted(zones[zone_id_col].astype(str).tolist())  # type: ignore[index]
    except Exception as e:
        raise SplitExportError(f"Failed to enumerate zone_ids: {e}") from e

    for zid in zone_ids:
        z_sub = zones.loc[zones[zone_id_col].astype(str) == str(zid)].copy()  # type: ignore[index]
        if len(z_sub) != 1:
            raise SplitExportError(
                f"Expected exactly 1 zone feature for zone_id={zid}, got {len(z_sub)}"
            )

        z_view = z_sub[[zone_id_col, zone_name_col, zone_code_col, "geometry"]].copy()
        z_filename = _zone_split_filename(zid, zones_basename=zones_basename)
        z_path = zones_dir / z_filename
        z_wr = write_shapefile(
            z_view,
            shp_path=z_path,
            required_columns=[zone_id_col, zone_name_col, zone_code_col],
        )
        zones_written.append(z_wr)

        d_sub = districts_enriched.loc[districts_enriched[zone_id_col].astype(str) == str(zid)].copy()  # type: ignore[index]
        if len(d_sub) == 0:
            raise SplitExportError(f"No districts found for zone_id={zid}; cannot write split")

        d_view = _districts_shp_view(
            d_sub,
            district_id_col=district_id_col,
            district_name_col=district_name_col,
            district_code_col=district_code_col,
            zone_id_col=zone_id_col,
            zone_name_col=zone_name_col,
            zone_code_col=zone_code_col,
            ovl_share_col=ovl_share_col,
        )

        d_filename = _district_split_filename(zid, districts_basename=districts_basename)
        d_path = dists_dir / d_filename
        req = ["dist_id", "dist_name", zone_id_col, zone_name_col, zone_code_col, ovl_share_col]
        if "dist_code" in getattr(d_view, "columns", []):
            req.insert(2, "dist_code")

        d_wr = write_shapefile(
            d_view,
            shp_path=d_path,
            required_columns=req,
        )
        districts_written.append(d_wr)

        manifest_rows.append(
            {
                "zone_id": str(zid),
                "zone_name": str(z_sub.iloc[0][zone_name_col]),
                "zone_code": str(z_sub.iloc[0][zone_code_col]),
                "zone_layer": (Path("splits") / "zones_split" / z_filename).as_posix(),
                "district_layer": (Path("splits") / "zone_districts" / d_filename).as_posix(),
                "district_count": int(len(d_sub)),
            }
        )

    manifest = {
        "zones_basename": _safe_stem(zones_basename),
        "districts_basename": _safe_stem(districts_basename),
        "rows": sorted(manifest_rows, key=lambda r: str(r["zone_id"])),
    }

    manifest_path = out_dir / "splits" / manifest_filename
    try:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception as e:
        raise SplitExportError(f"Failed to write split manifest {manifest_path}: {e}") from e

    return SplitWriteOutputs(
        zones_written=zones_written,
        districts_written=districts_written,
        manifest_path=manifest_path,
    )
