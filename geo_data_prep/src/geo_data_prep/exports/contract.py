"""geo_data_prep.exports.contract

Machine-readable Stage 1 contract manifest writer.

The contract manifest documents canonical logical outputs and the governing
configuration semantics without changing the physical Shapefile schemas.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ContractExportError(RuntimeError):
    """Raised when the Stage 1 contract manifest cannot be written."""


@dataclass(frozen=True)
class ContractWriteOutputs:
    manifest_path: Path


def _jsonable(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            return str(value)
    if hasattr(value, "__dict__"):
        return _jsonable(dict(value.__dict__))
    return str(value)


def write_stage1_contract_manifest(
    *,
    out_dir: Path,
    cfg: object,
    zone_level_label: str,
    district_level_label: str,
    zones_basename: str,
    districts_basename: str,
    unit_universe_filename: str = "unit_universe.csv",
    overlap_report_filename: str = "district_zone_overlap.csv",
    manifest_filename: str = "stage1_contract_manifest.json",
    extra_outputs: Mapping[str, object] | None = None,
) -> ContractWriteOutputs:
    """Write a machine-readable Stage 1 contract manifest under ``out_dir/contract/``."""

    cdir = Path(out_dir) / "contract"
    cdir.mkdir(parents=True, exist_ok=True)

    logical_schema = {
        "unit_universe_csv": [
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
        ],
        "zones_shapefile_logical_fields": ["zone_id", "zone_name", "zone_code"],
        "districts_shapefile_logical_fields": [
            "district_id",
            "district_name",
            "district_code",
            "zone_id",
            "zone_name",
            "zone_code",
            "ovl_share",
        ],
        "districts_shapefile_physical_fields": [
            "dist_id",
            "dist_name",
            "dist_code",
            "zone_id",
            "zone_name",
            "zone_code",
            "ovl_share",
        ],
        "overlap_report_csv": None,
    }

    manifest = {
        "contract": {
            "stage": getattr(getattr(cfg, "contract", None), "stage", None),
            "name": getattr(getattr(cfg, "contract", None), "name", None),
            "version": getattr(getattr(cfg, "contract", None), "version", None),
            "canonical_upstream": getattr(
                getattr(cfg, "contract", None), "canonical_upstream", None
            ),
            "downstreams_adapt_later": getattr(
                getattr(cfg, "contract", None), "downstreams_adapt_later", None
            ),
        },
        "schema_version": getattr(cfg, "schema_version", None),
        "levels": {
            "zone": zone_level_label,
            "district": district_level_label,
        },
        "crs": _jsonable(getattr(cfg, "crs", None)),
        "area_policy": _jsonable(getattr(cfg, "area_policy", None)),
        "qa": _jsonable(getattr(cfg, "qa", None)),
        "outputs": {
            "basenames": {
                "zones": zones_basename,
                "districts": districts_basename,
            },
            "logical_outputs": {
                "unit_universe_csv": unit_universe_filename,
                "zones_shapefile": f"boundaries/{zones_basename}.shp",
                "districts_shapefile": f"boundaries/{districts_basename}.shp",
                "overlap_report_csv": f"qa/{overlap_report_filename}",
            },
        },
        "logical_schema": logical_schema,
        "notes": {
            "stage1_is_canonical_upstream_contract": True,
            "legacy_alias_fields_are_not_added_to_canonical_stage1_outputs": True,
            "rich_provenance_and_crosswalks_live_in_sidecars": True,
            "unit_universe_contract_revision": (
                "The logical contract includes unit_code and parent_code in the "
                "unit_universe.csv schema while preserving unit_id and parent_id as the "
                "canonical relational keys."
            ),
            "schema_governance": {
                "unit_universe_and_boundary_schemas_require_contract_versioning_when_changed": True,
                "downstream_revalidation_required_before_schema_change": True,
                "known_stage3_contract_consumers": ["RP1_Project/merge_af_ba_panels.py"],
            },
        },
        "extra_outputs": _jsonable(dict(extra_outputs or {})),
    }

    manifest_path = cdir / manifest_filename
    try:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception as e:
        raise ContractExportError(f"Failed to write contract manifest {manifest_path}: {e}") from e

    return ContractWriteOutputs(manifest_path=manifest_path)
