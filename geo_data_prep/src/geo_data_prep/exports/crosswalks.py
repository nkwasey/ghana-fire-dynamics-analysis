"""geo_data_prep.exports.crosswalks

Crosswalk and provenance sidecars for Stage 1 exports.

These artefacts deliberately live in CSV/JSON sidecars rather than canonical
Shapefile schemas.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class CrosswalkExportError(RuntimeError):
    """Raised when crosswalk exports fail."""


def _require_pandas() -> object:
    try:
        import pandas as pd  # type: ignore

        return pd
    except Exception as e:  # pragma: no cover
        raise CrosswalkExportError("pandas is required for crosswalk exports") from e


def _require_cols(gdf: object, cols: Sequence[str], *, obj_name: str) -> None:
    missing = [c for c in cols if c not in getattr(gdf, "columns", [])]
    if missing:
        raise CrosswalkExportError(f"{obj_name} missing required columns: {missing}")


@dataclass(frozen=True)
class CrosswalkWriteOutputs:
    zone_lookup_path: Path
    district_zone_crosswalk_path: Path
    shapefile_field_crosswalk_path: Path
    manifest_path: Path


def write_crosswalk_exports(
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
    zone_lookup_filename: str = "zone_lookup.csv",
    district_zone_crosswalk_filename: str = "district_zone_crosswalk.csv",
    shapefile_field_crosswalk_filename: str = "shapefile_field_crosswalk.json",
    manifest_filename: str = "crosswalks_manifest.json",
) -> CrosswalkWriteOutputs:
    """Write Stage 1 crosswalk/provenance sidecars under ``out_dir/crosswalks/``."""

    _pd = _require_pandas()

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

    cw_dir = Path(out_dir) / "crosswalks"
    cw_dir.mkdir(parents=True, exist_ok=True)

    zone_lookup = (
        zones_enriched[[zone_id_col, zone_name_col, zone_code_col]]
        .drop_duplicates(subset=[zone_id_col])
        .sort_values([zone_id_col], kind="mergesort")
        .reset_index(drop=True)
    )

    district_cols = [district_id_col, district_name_col]
    if district_code_col and district_code_col in getattr(districts_enriched, "columns", []):
        district_cols.append(district_code_col)
    district_cols.extend([zone_id_col, zone_name_col, zone_code_col, ovl_share_col])

    district_crosswalk = (
        districts_enriched[district_cols]
        .drop_duplicates(subset=[district_id_col])
        .sort_values([zone_id_col, district_id_col], kind="mergesort")
        .reset_index(drop=True)
    )

    zone_lookup_path = cw_dir / zone_lookup_filename
    district_zone_crosswalk_path = cw_dir / district_zone_crosswalk_filename
    try:
        zone_lookup.to_csv(zone_lookup_path, index=False, encoding="utf-8")
        district_crosswalk.to_csv(district_zone_crosswalk_path, index=False, encoding="utf-8")
    except Exception as e:
        raise CrosswalkExportError(f"Failed to write crosswalk CSVs: {e}") from e

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

    shapefile_field_crosswalk_path = cw_dir / shapefile_field_crosswalk_filename
    try:
        shapefile_field_crosswalk_path.write_text(
            json.dumps(field_crosswalk, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as e:
        raise CrosswalkExportError(
            f"Failed to write field crosswalk JSON {shapefile_field_crosswalk_path}: {e}"
        ) from e

    manifest = {
        "zone_lookup_csv": zone_lookup_path.relative_to(out_dir).as_posix(),
        "district_zone_crosswalk_csv": district_zone_crosswalk_path.relative_to(out_dir).as_posix(),
        "shapefile_field_crosswalk_json": shapefile_field_crosswalk_path.relative_to(
            out_dir
        ).as_posix(),
        "zone_rows": int(len(zone_lookup)),
        "district_rows": int(len(district_crosswalk)),
    }

    manifest_path = cw_dir / manifest_filename
    try:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception as e:
        raise CrosswalkExportError(
            f"Failed to write crosswalk manifest {manifest_path}: {e}"
        ) from e

    return CrosswalkWriteOutputs(
        zone_lookup_path=zone_lookup_path,
        district_zone_crosswalk_path=district_zone_crosswalk_path,
        shapefile_field_crosswalk_path=shapefile_field_crosswalk_path,
        manifest_path=manifest_path,
    )
