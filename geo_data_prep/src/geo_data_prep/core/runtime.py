"""geo_data_prep.core.runtime

End-to-end Stage 1 runtime orchestration.

This module wires the pipeline:
- read inputs (zones, districts, optional AOI)
- optional AOI clipping
- deterministic derivations (IDs/codes/names)
- district→zone assignment by max overlap share
- exports (unit universe CSV, combined boundaries, optional splits)
- optional plots
- QA reports + validators
- audit artefacts: inputs_fingerprint.json + outputs_manifest.json

Runtime properties
------------------
- Wires ``area_policy``, ``qa.thresholds`` and ``contract`` configuration
  into runtime-managed outputs.
- Emits richer QA, provenance, crosswalk, and contract sidecars while keeping
  canonical Stage 1 Shapefile schemas lean.
- Preserves deterministic behaviour and the callable runtime surface.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geo_data_prep import __version__
from geo_data_prep.core.config import (
    AppConfig,
    ConfigError,
    ResolvedPaths,
    load_config,
    resolve_paths,
)
from geo_data_prep.exports.combined import CombinedExportError, write_combined_boundaries
from geo_data_prep.exports.contract import ContractExportError, write_stage1_contract_manifest
from geo_data_prep.exports.crosswalks import CrosswalkExportError, write_crosswalk_exports
from geo_data_prep.exports.splits import SplitExportError, write_zone_splits
from geo_data_prep.exports.universe import UniverseExportError, write_unit_universe_csv
from geo_data_prep.io.read import ReadError, read_shapefile
from geo_data_prep.normalise.ids import derive_zone_code, dist_id_from_label, zone_id_from_label
from geo_data_prep.normalise.text import to_upper_canon
from geo_data_prep.plots.combined import PlotError as CombinedPlotError
from geo_data_prep.plots.combined import plot_combined_zones_districts
from geo_data_prep.plots.per_zone import PlotError as PerZonePlotError
from geo_data_prep.plots.per_zone import plot_per_zone_maps
from geo_data_prep.qa.defensibility import DefensibilityError, run_working_crs_sensitivity_study
from geo_data_prep.qa.reports import (
    ReportError,
    build_assignment_validation_payload,
    write_district_zone_overlap_csv,
)
from geo_data_prep.qa.validators import (
    ValidationError as QAValidationError,
)
from geo_data_prep.qa.validators import (
    run_basic_validators,
)
from geo_data_prep.spatial.clip import ClipError, maybe_clip_to_aoi
from geo_data_prep.spatial.overlay import OverlayError, assign_districts_to_zones_by_max_share


class RunError(RuntimeError):
    """Raised when the end-to-end run pipeline fails."""


@dataclass(frozen=True)
class RunOutputs:
    """Key paths produced by a run."""

    run_id: str
    run_dir: Path
    inputs_fingerprint_path: Path
    outputs_manifest_path: Path


DATA_ACCESS_DOC_REL = "docs/data_access.md"
ROOT_RUNBOOK_REL = "README.md"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_run_id(run_id: str) -> str:
    s = "_".join(str(run_id).strip().split())
    s = s.replace("/", "_").replace("\\", "_")
    if not s:
        raise RunError("run_id must be a non-empty string")
    return s


def _default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()


def _relative_to_run(path: Path, run_dir: Path) -> str:
    return path.resolve().relative_to(run_dir.resolve()).as_posix()


def _stage1_missing_input_message(*, label: str, path: Path, repo_root: Path) -> str:
    repo_rel = _relative_to_repo(path, repo_root)
    return (
        f"Missing required Stage 1 input `{label}`: {repo_rel}. "
        f"See {DATA_ACCESS_DOC_REL} and {ROOT_RUNBOOK_REL} for acquisition and local staging instructions. "
        "Required by stage: geo_data_prep (Stage 1)."
    )


def _shapefile_bundle_files(shp_path: Path) -> list[Path]:
    """Return existing sidecar files for a Shapefile bundle, deterministically."""

    shp_path = Path(shp_path)
    if shp_path.suffix.lower() != ".shp":
        return [shp_path]

    files = sorted(shp_path.parent.glob(shp_path.stem + ".*"), key=lambda p: p.name)
    if shp_path not in files:
        files.insert(0, shp_path)
    return files


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


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(dict(payload)), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _record_files(path: Path, *, run_dir: Path) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for fp in _shapefile_bundle_files(path):
        if not fp.exists() or fp.is_dir():
            continue
        out.append(
            {
                "path": _relative_to_run(fp, run_dir),
                "bytes": int(fp.stat().st_size),
                "sha256": _sha256_file(fp),
            }
        )
    return out


def _overall_status(results: list[dict[str, object]]) -> str:
    if not results:
        return "na"
    order = {"fail": 3, "warn": 2, "pass": 1, "na": 0}
    return str(
        max(results, key=lambda r: order.get(str(r.get("status", "na")), 0)).get("status", "na")
    )


def _assignment_threshold_kwargs(cfg: AppConfig) -> dict[str, object]:
    thr = cfg.qa.thresholds
    return {
        "qa_enabled": bool(cfg.qa.enabled),
        "share_warn_below": float(thr.overlap_share.warn_below),
        "share_fail_below": float(thr.overlap_share.fail_below),
        "area_warn_above": float(thr.area_relative_difference.warn_above),
        "area_fail_above": float(thr.area_relative_difference.fail_above),
        "missing_warn_above": int(thr.unassigned_units.warn_above),
        "missing_fail_above": int(thr.unassigned_units.fail_above),
        "invalid_geometry_warn_above": int(thr.invalid_geometries.warn_above),
        "invalid_geometry_fail_above": int(thr.invalid_geometries.fail_above),
        "legacy_disagreement_warn_above": int(thr.legacy_assignment_disagreement.warn_above),
        "legacy_disagreement_fail_above": int(thr.legacy_assignment_disagreement.fail_above),
    }


def _sliver_diagnostic_kwargs(cfg: AppConfig) -> dict[str, object]:
    return {
        "sliver_enabled": bool(cfg.qa.enabled and cfg.qa.sliver_diagnostics.enabled),
        "sliver_share_cutoffs": [float(v) for v in cfg.qa.sliver_diagnostics.share_cutoffs],
        "sliver_area_sqkm_cutoffs": [float(v) for v in cfg.qa.sliver_diagnostics.area_sqkm_cutoffs],
        "sliver_example_limit": int(cfg.qa.sliver_diagnostics.example_limit),
    }


def _build_runtime_assignment_validations(
    validation_payload: Mapping[str, object],
    *,
    cfg: AppConfig,
) -> dict[str, object]:
    payload = dict(_jsonable(dict(validation_payload)))
    payload["thresholds"] = _jsonable(getattr(cfg.qa, "thresholds", None))
    if not bool(cfg.qa.enabled):
        payload["notes"] = ["Runtime assignment-threshold evaluation disabled by config."]
    return payload


def build_inputs_fingerprint(
    *,
    cfg: AppConfig,
    resolved: ResolvedPaths,
) -> dict[str, Any]:
    """Build an audit-friendly, deterministic fingerprint of run inputs."""

    cfg_hash = _sha256_file(resolved.config_path)

    def _file_record(p: Path) -> dict[str, Any]:
        return {
            "path": _relative_to_repo(p, resolved.repo_root),
            "bytes": int(p.stat().st_size),
            "sha256": _sha256_file(p),
        }

    inputs: dict[str, Any] = {
        "package": {"name": "geo_data_prep", "version": __version__},
        "config": {
            "path": _relative_to_repo(resolved.config_path, resolved.repo_root),
            "sha256": cfg_hash,
        },
        "schema_version": cfg.schema_version,
        "contract": _jsonable(cfg.contract),
        "area_policy": _jsonable(cfg.area_policy),
        "qa": _jsonable(cfg.qa),
        "crs": {"working_crs": cfg.crs.working_crs, "plot_crs": cfg.crs.plot_crs},
        "levels": {"zone": cfg.levels.zone.level, "district": cfg.levels.district.level},
        "outputs": {
            "out_dir": cfg.outputs.out_dir,
            "toggles": _jsonable(cfg.outputs.toggles),
            "basenames": _jsonable(cfg.outputs.basenames),
        },
        "input_bundles": {},
    }

    bundles: dict[str, list[dict[str, Any]]] = {}
    bundles["zones"] = [_file_record(p) for p in _shapefile_bundle_files(resolved.zones_path)]
    bundles["districts"] = [
        _file_record(p) for p in _shapefile_bundle_files(resolved.districts_path)
    ]
    if resolved.aoi_path is not None:
        bundles["aoi"] = [_file_record(p) for p in _shapefile_bundle_files(resolved.aoi_path)]

    for k in sorted(bundles.keys()):
        inputs["input_bundles"][k] = sorted(bundles[k], key=lambda r: str(r["path"]))

    return inputs


def _derive_zones(
    zones_raw: object,
    *,
    zone_label_field: str,
    zone_code_mapping: dict[str, str],
) -> object:
    import geopandas as gpd  # type: ignore
    import pandas as pd  # type: ignore

    if zone_label_field not in zones_raw.columns:
        raise RunError(f"zones missing label_field column: {zone_label_field}")

    z = zones_raw.copy().reset_index(drop=True)
    labels = z[zone_label_field].astype(str).tolist()

    zone_names = [to_upper_canon(x) for x in labels]
    zone_ids = [zone_id_from_label(x) for x in labels]

    if len(set(zone_ids)) != len(zone_ids):
        s = pd.Series(zone_ids)
        dup = s[s.duplicated()].unique().tolist()
        raise RunError(f"Derived zone_id has duplicates (examples): {dup[:5]}")

    used_codes: set[str] = set()
    zone_codes: list[str] = []
    for lab in labels:
        code = derive_zone_code(lab, mapping=zone_code_mapping, used_codes=used_codes)
        if code in used_codes:
            raise RunError(f"Derived zone_code not unique after collision handling: {code}")
        used_codes.add(code)
        zone_codes.append(code)

    out = gpd.GeoDataFrame(
        {
            "zone_id": zone_ids,
            "zone_name": zone_names,
            "zone_code": zone_codes,
        },
        geometry=z.geometry,
        crs=getattr(z, "crs", None),
    )

    try:
        out = out.sort_values(["zone_id"], kind="mergesort").reset_index(drop=True)
    except Exception:
        pass

    return out


def _derive_districts(districts_raw: object, *, district_label_field: str) -> object:
    import geopandas as gpd  # type: ignore
    import pandas as pd  # type: ignore

    if district_label_field not in districts_raw.columns:
        raise RunError(f"districts missing label_field column: {district_label_field}")

    d = districts_raw.copy().reset_index(drop=True)
    labels = d[district_label_field].astype(str).tolist()

    district_names = [to_upper_canon(x) for x in labels]
    district_ids = [dist_id_from_label(x) for x in labels]

    if len(set(district_ids)) != len(district_ids):
        s = pd.Series(district_ids)
        dup = s[s.duplicated()].unique().tolist()
        raise RunError(f"Derived district_id has duplicates (examples): {dup[:5]}")

    cols: dict[str, Any] = {
        "district_id": district_ids,
        "district_name": district_names,
    }
    if "district_code" in getattr(d, "columns", []):
        cols["district_code"] = d["district_code"].astype(str)

    out = gpd.GeoDataFrame(cols, geometry=d.geometry, crs=getattr(d, "crs", None))

    try:
        out = out.sort_values(["district_id"], kind="mergesort").reset_index(drop=True)
    except Exception:
        pass

    return out


def run_pipeline(
    *,
    cfg: AppConfig,
    resolved: ResolvedPaths,
    run_id: str | None = None,
) -> RunOutputs:
    """Execute the full Stage 1 pipeline and write outputs under ``out_dir/run_id/``."""

    rid = _safe_run_id(run_id or _default_run_id())
    run_dir = Path(resolved.out_dir) / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        zones_rr = read_shapefile(
            resolved.zones_path,
            working_crs=cfg.crs.working_crs,
            required_fields=[cfg.inputs.zones.label_field],
        )
        districts_rr = read_shapefile(
            resolved.districts_path,
            working_crs=cfg.crs.working_crs,
            required_fields=[cfg.inputs.districts.label_field],
        )
        aoi_rr = None
        if resolved.aoi_path is not None:
            aoi_rr = read_shapefile(
                resolved.aoi_path,
                working_crs=cfg.crs.working_crs,
                required_fields=None,
            )
    except ReadError as e:
        raise RunError(str(e)) from e

    zones = zones_rr.gdf
    districts = districts_rr.gdf

    try:
        if cfg.inputs.aoi is not None:
            zones = maybe_clip_to_aoi(
                zones,
                aoi=(aoi_rr.gdf if aoi_rr is not None else None),
                enabled=bool(cfg.inputs.aoi.enabled),
                working_crs=cfg.crs.working_crs,
            )
            districts = maybe_clip_to_aoi(
                districts,
                aoi=(aoi_rr.gdf if aoi_rr is not None else None),
                enabled=bool(cfg.inputs.aoi.enabled),
                working_crs=cfg.crs.working_crs,
            )
    except ClipError as e:
        raise RunError(str(e)) from e

    try:
        zones_enriched = _derive_zones(
            zones,
            zone_label_field=cfg.inputs.zones.label_field,
            zone_code_mapping=dict(cfg.derivations.zone_code.mapping),
        )
        districts_std = _derive_districts(
            districts, district_label_field=cfg.inputs.districts.label_field
        )
    except Exception as e:
        raise RunError(f"Derivation failed: {e}") from e

    try:
        assn = assign_districts_to_zones_by_max_share(
            districts_std,
            zones_enriched,
            working_crs=cfg.crs.working_crs,
            district_id_col="district_id",
            zone_id_col="zone_id",
            zone_cols=("zone_name", "zone_code"),
            share_col="ovl_share",
        )
        districts_enriched = assn.districts_enriched
        overlap_table = assn.overlap_table
    except OverlayError as e:
        raise RunError(str(e)) from e

    geometry_invalid_counts: dict[str, int] = {}
    try:
        zone_validations = run_basic_validators(
            zones_enriched,
            non_null=["zone_id", "zone_name", "zone_code"],
            unique=[("zone_id",), ("zone_code",)],
            check_geometry=True,
        )
        district_validations = run_basic_validators(
            districts_enriched,
            non_null=[
                "district_id",
                "district_name",
                "zone_id",
                "zone_name",
                "zone_code",
                "ovl_share",
            ],
            unique=[("district_id",)],
            check_geometry=True,
        )
        geometry_invalid_counts = {
            "zones": int((zone_validations[-1].details or {}).get("invalid_count", 0)),
            "districts": int((district_validations[-1].details or {}).get("invalid_count", 0)),
        }
    except QAValidationError as e:
        raise RunError(str(e)) from e

    outputs_index: dict[str, object] = {}

    try:
        uni_path = write_unit_universe_csv(
            zones_enriched,
            districts_enriched,
            out_dir=run_dir,
            zone_level_label=cfg.levels.zone.level,
            district_level_label=cfg.levels.district.level,
            district_area_policy="compute",
            filename="unit_universe.csv",
            area_method=str(cfg.area_policy.method),
            area_projected_crs=cfg.effective_area_projected_crs,
            area_geodesic_ellipsoid=str(cfg.area_policy.geodesic_ellipsoid),
            area_units=str(cfg.area_policy.units),
        )
        outputs_index["unit_universe_csv"] = _relative_to_run(uni_path, run_dir)

        comb = write_combined_boundaries(
            zones_enriched,
            districts_enriched,
            out_dir=run_dir,
            zones_basename=str(cfg.outputs.basenames.zones),
            districts_basename=str(cfg.outputs.basenames.districts),
        )
        outputs_index["combined_manifest_json"] = _relative_to_run(comb.manifest_path, run_dir)
        outputs_index["combined_zone_shapefile"] = _relative_to_run(comb.zones.shp_path, run_dir)
        outputs_index["combined_district_shapefile"] = _relative_to_run(
            comb.districts.shp_path, run_dir
        )

        split_outputs = None
        if bool(cfg.outputs.toggles.splits):
            split_outputs = write_zone_splits(
                zones_enriched,
                districts_enriched,
                out_dir=run_dir,
                zones_basename=str(cfg.outputs.basenames.zones),
                districts_basename=str(cfg.outputs.basenames.districts),
            )
            outputs_index["splits_manifest_json"] = _relative_to_run(
                split_outputs.manifest_path, run_dir
            )

        crosswalks = write_crosswalk_exports(
            zones_enriched,
            districts_enriched,
            out_dir=run_dir,
        )
        outputs_index["crosswalks_manifest_json"] = _relative_to_run(
            crosswalks.manifest_path, run_dir
        )
        outputs_index["zone_lookup_csv"] = _relative_to_run(crosswalks.zone_lookup_path, run_dir)
        outputs_index["district_zone_crosswalk_csv"] = _relative_to_run(
            crosswalks.district_zone_crosswalk_path, run_dir
        )
        outputs_index["shapefile_field_crosswalk_json"] = _relative_to_run(
            crosswalks.shapefile_field_crosswalk_path, run_dir
        )

    except (UniverseExportError, CombinedExportError, SplitExportError, CrosswalkExportError) as e:
        raise RunError(str(e)) from e

    if bool(cfg.outputs.toggles.plots):
        try:
            title = f"Zones ({cfg.levels.zone.level}) and districts"
            plot_combined_zones_districts(
                zones_enriched,
                districts_enriched,
                out_dir=run_dir,
                title=title,
                plot_crs=cfg.crs.plot_crs,
            )
            plot_per_zone_maps(
                zones_enriched,
                districts_enriched,
                out_dir=run_dir,
                plot_crs=cfg.crs.plot_crs,
            )
        except (CombinedPlotError, PerZonePlotError) as e:
            raise RunError(str(e)) from e

    try:
        qa_dir = run_dir / "qa"
        assignment_validation_payload = build_assignment_validation_payload(
            overlap_table,
            invalid_geometry_layer_counts=geometry_invalid_counts,
            **_assignment_threshold_kwargs(cfg),
        )
        rep = write_district_zone_overlap_csv(
            overlap_table,
            out_csv=qa_dir / "district_zone_overlap.csv",
            validation_payload=assignment_validation_payload,
            invalid_geometry_layer_counts=geometry_invalid_counts,
            **_assignment_threshold_kwargs(cfg),
            **_sliver_diagnostic_kwargs(cfg),
        )
        outputs_index["overlap_report_csv"] = _relative_to_run(rep.path, run_dir)
        for key, p in sorted(rep.sidecars.items()):
            outputs_index[f"overlap_{key}"] = _relative_to_run(Path(p), run_dir)

        runtime_validations_payload = _build_runtime_assignment_validations(
            assignment_validation_payload,
            cfg=cfg,
        )
        runtime_validations_path = _write_json(
            qa_dir / "runtime_assignment_validations.json", runtime_validations_payload
        )
        outputs_index["runtime_assignment_validations_json"] = _relative_to_run(
            runtime_validations_path, run_dir
        )

        scientific_defensibility: dict[str, object] = {}
        if bool(cfg.qa.enabled and cfg.qa.crs_sensitivity.enabled):
            sensitivity = run_working_crs_sensitivity_study(
                districts_std,
                zones_enriched,
                baseline_districts_enriched=districts_enriched,
                working_crs=cfg.crs.working_crs,
                example_limit=int(cfg.qa.crs_sensitivity.example_limit),
            )
            sensitivity_summary_path = _write_json(
                qa_dir / "working_crs_sensitivity_summary.json",
                sensitivity.summary,
            )
            outputs_index["working_crs_sensitivity_summary_json"] = _relative_to_run(
                sensitivity_summary_path,
                run_dir,
            )
            try:
                sensitivity.comparison_table.to_csv(
                    qa_dir / "working_crs_sensitivity_comparison.csv",
                    index=False,
                    encoding="utf-8",
                )
            except Exception as e:
                raise ReportError(f"Failed to write CRS sensitivity comparison CSV: {e}") from e
            outputs_index["working_crs_sensitivity_comparison_csv"] = _relative_to_run(
                qa_dir / "working_crs_sensitivity_comparison.csv",
                run_dir,
            )
            scientific_defensibility = {
                "working_crs_sensitivity_summary_json": _relative_to_run(
                    sensitivity_summary_path, run_dir
                ),
                "working_crs_sensitivity_comparison_csv": _relative_to_run(
                    qa_dir / "working_crs_sensitivity_comparison.csv",
                    run_dir,
                ),
                "assignment_identity_changes_detected": bool(
                    sensitivity.summary.get("assignment_identity_change_count", 0)
                ),
                "max_overlap_rule_retained": (
                    str(sensitivity.summary.get("recommendation")) == "retain_max_overlap_rule"
                ),
            }
        elif "sliver_summary_json" in rep.sidecars:
            scientific_defensibility = {}

        if "sliver_summary_json" in rep.sidecars:
            scientific_defensibility["overlap_sliver_summary_json"] = _relative_to_run(
                Path(rep.sidecars["sliver_summary_json"]),
                run_dir,
            )

        qa_summary_payload = {
            "ok": bool(runtime_validations_payload.get("ok", True)),
            "status": str(runtime_validations_payload.get("status", "na")),
            "overlap_rows": int(rep.rows),
            "qa_enabled": bool(cfg.qa.enabled),
            "thresholds": _jsonable(getattr(cfg.qa, "thresholds", None)),
            "overlap_report_csv": _relative_to_run(rep.path, run_dir),
            "overlap_sidecars": {
                k: _relative_to_run(Path(v), run_dir) for k, v in sorted(rep.sidecars.items())
            },
            "runtime_assignment_validations_json": _relative_to_run(
                runtime_validations_path, run_dir
            ),
        }
        if scientific_defensibility:
            qa_summary_payload["scientific_defensibility"] = scientific_defensibility
        qa_summary_path = _write_json(qa_dir / "qa_summary.json", qa_summary_payload)
        outputs_index["qa_summary_json"] = _relative_to_run(qa_summary_path, run_dir)
    except (ReportError, DefensibilityError) as e:
        raise RunError(str(e)) from e

    try:
        contract = write_stage1_contract_manifest(
            out_dir=run_dir,
            cfg=cfg,
            zone_level_label=cfg.levels.zone.level,
            district_level_label=cfg.levels.district.level,
            zones_basename=str(cfg.outputs.basenames.zones),
            districts_basename=str(cfg.outputs.basenames.districts),
            extra_outputs=outputs_index,
        )
        outputs_index["stage1_contract_manifest_json"] = _relative_to_run(
            contract.manifest_path, run_dir
        )
    except ContractExportError as e:
        raise RunError(str(e)) from e

    inputs_fp = build_inputs_fingerprint(cfg=cfg, resolved=resolved)
    inputs_fp["run_id"] = rid
    inputs_fp["run_dir"] = (Path(cfg.outputs.out_dir) / rid).as_posix()

    inputs_fp_path = _write_json(run_dir / "inputs_fingerprint.json", inputs_fp)

    manifest_path = run_dir / "outputs_manifest.json"
    records: list[dict[str, Any]] = []
    for fp in sorted(run_dir.rglob("*")):
        if fp.is_dir():
            continue
        if fp.resolve() == manifest_path.resolve():
            continue
        records.append(
            {
                "path": fp.relative_to(run_dir).as_posix(),
                "bytes": int(fp.stat().st_size),
                "sha256": _sha256_file(fp),
            }
        )

    outputs_manifest = {
        "run_id": rid,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contract": _jsonable(cfg.contract),
        "area_policy": _jsonable(cfg.area_policy),
        "qa": {
            "enabled": bool(cfg.qa.enabled),
            "thresholds": _jsonable(getattr(cfg.qa, "thresholds", None)),
            "sliver_diagnostics": _jsonable(getattr(cfg.qa, "sliver_diagnostics", None)),
            "crs_sensitivity": _jsonable(getattr(cfg.qa, "crs_sensitivity", None)),
        },
        "index": outputs_index,
        "files": sorted(records, key=lambda r: str(r["path"])),
    }
    _write_json(manifest_path, outputs_manifest)

    return RunOutputs(
        run_id=rid,
        run_dir=run_dir,
        inputs_fingerprint_path=inputs_fp_path,
        outputs_manifest_path=manifest_path,
    )


def run_from_config(config_path: Path, *, run_id: str | None = None) -> RunOutputs:
    """Convenience entry: load config, resolve paths, execute pipeline."""

    cfg = load_config(config_path)
    resolved = resolve_paths(cfg, config_path=config_path)

    if not resolved.zones_path.exists():
        raise ConfigError(
            _stage1_missing_input_message(
                label="zones",
                path=resolved.zones_path,
                repo_root=resolved.repo_root,
            )
        )
    if not resolved.districts_path.exists():
        raise ConfigError(
            _stage1_missing_input_message(
                label="districts",
                path=resolved.districts_path,
                repo_root=resolved.repo_root,
            )
        )
    if cfg.inputs.aoi is not None and cfg.inputs.aoi.enabled:
        if resolved.aoi_path is None or not resolved.aoi_path.exists():
            raise ConfigError(
                _stage1_missing_input_message(
                    label="aoi",
                    path=(
                        resolved.aoi_path
                        if resolved.aoi_path is not None
                        else Path("<missing-aoi-path>")
                    ),
                    repo_root=resolved.repo_root,
                )
            )

    return run_pipeline(cfg=cfg, resolved=resolved, run_id=run_id)
