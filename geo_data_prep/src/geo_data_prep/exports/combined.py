"""geo_data_prep.exports.combined

Write combined Stage 1 boundary exports.

Outputs (relative to out_dir)
-----------------------------
- boundaries/<zones_basename>.shp
- boundaries/<districts_basename>.shp
- boundaries/combined_manifest.json

Contract properties
-------------------
- Preserves Shapefile-safe physical DBF names for district layers.
- Keeps canonical logical schema in manifests/sidecars rather than inflating DBFs.
- Honours configured output basenames where callers provide them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from geo_data_prep.io.write import WriteResult, write_shapefile


class CombinedExportError(RuntimeError):
    """Raised when combined boundary exports fail."""


def _require_cols(gdf: object, cols: Sequence[str], *, obj_name: str) -> None:
    missing = [c for c in cols if c not in getattr(gdf, "columns", [])]
    if missing:
        raise CombinedExportError(f"{obj_name} missing required columns: {missing}")


def _safe_stem(name: str, *, obj_name: str) -> str:
    s = str(name).strip()
    if not s:
        raise CombinedExportError(f"{obj_name} basename must be a non-empty string")
    s = s.replace("/", "_").replace("\\", "_")
    if s.lower().endswith(".shp"):
        s = s[:-4]
    if not s:
        raise CombinedExportError(f"{obj_name} basename resolved to an empty filename stem")
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
    """Return a Shapefile-safe view of districts with <=10-char field names."""

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


@dataclass(frozen=True)
class CombinedWriteOutputs:
    zones: WriteResult
    districts: WriteResult
    manifest_path: Path


def write_combined_boundaries(
    zones_enriched: object,
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
    zones_basename: str = "zones_enriched",
    districts_basename: str = "districts_enriched",
    manifest_filename: str = "combined_manifest.json",
) -> CombinedWriteOutputs:
    """Write the combined boundaries export under ``out_dir/boundaries/``."""

    out_dir = Path(out_dir)
    bdir = out_dir / "boundaries"
    bdir.mkdir(parents=True, exist_ok=True)

    _require_cols(
        zones_enriched, [zone_id_col, zone_name_col, zone_code_col], obj_name="zones_enriched"
    )
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

    zones_stem = _safe_stem(zones_basename, obj_name="zones")
    districts_stem = _safe_stem(districts_basename, obj_name="districts")

    z_path = bdir / f"{zones_stem}.shp"
    z_view = zones_enriched[[zone_id_col, zone_name_col, zone_code_col, "geometry"]].copy()
    try:
        z_view = z_view.sort_values([zone_id_col], ascending=[True], kind="mergesort")
    except Exception:
        pass
    z_wr = write_shapefile(
        z_view,
        shp_path=z_path,
        required_columns=[zone_id_col, zone_name_col, zone_code_col],
    )

    d_path = bdir / f"{districts_stem}.shp"
    d_view = _districts_shp_view(
        districts_enriched,
        district_id_col=district_id_col,
        district_name_col=district_name_col,
        district_code_col=district_code_col,
        zone_id_col=zone_id_col,
        zone_name_col=zone_name_col,
        zone_code_col=zone_code_col,
        ovl_share_col=ovl_share_col,
    )

    req = ["dist_id", "dist_name", zone_id_col, zone_name_col, zone_code_col, ovl_share_col]
    if "dist_code" in getattr(d_view, "columns", []):
        req.insert(2, "dist_code")

    d_wr = write_shapefile(
        d_view,
        shp_path=d_path,
        required_columns=req,
    )

    def _rel(p: Path) -> str:
        return p.relative_to(out_dir).as_posix()

    field_crosswalk = {
        "zones": {
            "logical_to_physical": {
                zone_id_col: zone_id_col,
                zone_name_col: zone_name_col,
                zone_code_col: zone_code_col,
            },
            "physical_to_logical": {
                zone_id_col: zone_id_col,
                zone_name_col: zone_name_col,
                zone_code_col: zone_code_col,
            },
        },
        "districts": {
            "logical_to_physical": {
                district_id_col: "dist_id",
                district_name_col: "dist_name",
                zone_id_col: zone_id_col,
                zone_name_col: zone_name_col,
                zone_code_col: zone_code_col,
                ovl_share_col: ovl_share_col,
                **({district_code_col: "dist_code"} if district_code_col else {}),
            },
            "physical_to_logical": {
                "dist_id": district_id_col,
                "dist_name": district_name_col,
                zone_id_col: zone_id_col,
                zone_name_col: zone_name_col,
                zone_code_col: zone_code_col,
                ovl_share_col: ovl_share_col,
                **({"dist_code": district_code_col} if district_code_col else {}),
            },
        },
    }

    zones_entry = {
        "basename": zones_stem,
        "shp": _rel(z_wr.shp_path),
        "sidecars": {ext: _rel(fp) for ext, fp in z_wr.sidecars.items()},
    }
    districts_entry = {
        "basename": districts_stem,
        "shp": _rel(d_wr.shp_path),
        "sidecars": {ext: _rel(fp) for ext, fp in d_wr.sidecars.items()},
    }

    manifest = {
        "zones": zones_entry,
        "districts": districts_entry,
        "boundaries": {
            "zones": zones_entry,
            "districts": districts_entry,
        },
        "schema": {
            "logical_fields": {
                "zones": [zone_id_col, zone_name_col, zone_code_col],
                "districts": [
                    district_id_col,
                    district_name_col,
                    *([district_code_col] if district_code_col else []),
                    zone_id_col,
                    zone_name_col,
                    zone_code_col,
                    ovl_share_col,
                ],
            },
            "field_crosswalk": field_crosswalk,
        },
    }

    m_path = bdir / manifest_filename
    try:
        m_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as e:
        raise CombinedExportError(f"Failed to write manifest JSON: {m_path}: {e}") from e

    return CombinedWriteOutputs(zones=z_wr, districts=d_wr, manifest_path=m_path)
