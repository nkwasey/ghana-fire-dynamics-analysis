"""Shared preparation identity checks for governed count and FRP partitions.

Reusing an output is an admission decision: its source family, current input
selection, configuration, geography and output bytes must still agree with the
preparation receipt. Native explicit-path computational calls remain supported;
CLI reuse always checks the currently configured annual selection.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from mv_firms_panels.core.config import AppConfig, SensorName
from mv_firms_panels.core.hashing import sha256_file, sha256_text, stable_json_dumps
from mv_firms_panels.core.schema import load_json_schema, validate_dataframe_against_schema


class PreparationEvidenceError(ValueError):
    """An annual preparation no longer has valid current-input evidence."""


def _family(path: Path) -> list[Path]:
    if path.suffix.lower() == ".shp":
        return sorted(p for p in path.parent.glob(path.stem + ".*") if p.is_file())
    return [path] if path.is_file() else []


def _relative(root: Path, path: Path) -> str:
    return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()


def _identities(root: Path, paths: list[Path]) -> dict[str, str]:
    return {_relative(root, path): sha256_file(path) for path in paths}


def _recorded_identities(root: Path, entries: object, *, label: str) -> dict[str, str]:
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{label} identity missing")
    result: dict[str, str] = {}
    for entry in entries:
        path = (root / entry["path"]).resolve()
        key = _relative(root, path)
        if key in result or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"{label} input identity changed or duplicated")
        result[key] = entry["sha256"]
    return result


def validate_preparation_partition(
    *, repo_root: Path, cfg: AppConfig, run_dir: Path, run_id: str,
    sensor: SensorName, year: int, count_path: Path, frp_path: Path | None = None,
    require_file_inputs: bool = True, require_configured_source: bool = False,
) -> dict[str, object]:
    """Validate one annual receipt and return its bound preparation QA.

    VIIRS callers must supply its independently prepared FRP partition. A native
    preparation made with in-memory inputs can be inspected for calculations
    only when ``require_file_inputs`` is false; it cannot qualify CLI reuse or
    governed output production.
    """
    repo_root = Path(repo_root).resolve()
    try:
        receipt_path = run_dir / "qa" / f"prepare_year_{sensor}_{year}_manifest.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        config_hash = sha256_text(stable_json_dumps(cfg.to_canonical_dict()))
        expected = {"method_version": "viirs_frp_dual_stream_v1", "sensor": sensor,
                    "year": year, "run_id": run_id, "config_sha256": config_hash}
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise ValueError("method, sensor, year, run or configuration mismatch")
        qa_entry = receipt["qa_summary_json"]
        qa_path = repo_root / qa_entry["path"]
        if sha256_file(qa_path) != qa_entry["sha256"]:
            raise ValueError("preparation QA hash mismatch")
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        if any(qa.get(key) != value for key, value in expected.items()):
            raise ValueError("preparation QA identity mismatch")
        if require_file_inputs and qa.get("in_memory_inputs") is not False:
            raise ValueError("governed preparation requires file-backed inputs")

        source_name = qa.get("source_file")
        source = (repo_root / source_name).resolve() if source_name else None
        file_backed = qa.get("in_memory_inputs") is False
        profile = getattr(cfg.io.inputs.firms_points[sensor], "input_profile", "native_firms_v1")
        is_archive = profile == "ghana_firms_archive_sp_v1"
        recorded_source = (
            _recorded_identities(repo_root, qa.get("source_file_identity"), label="source")
            if file_backed or is_archive or qa.get("source_file_identity") else {}
        )
        if file_backed:
            if source is None or not source.is_file():
                raise ValueError("preparation source path missing")
            if _identities(repo_root, _family(source)) != recorded_source:
                raise ValueError("source family changed or component identity incomplete")
            if require_configured_source or is_archive or qa.get("source_selection") == "configured_glob":
                from mv_firms_panels.stages.prepare_year import resolve_annual_points_path
                selected = resolve_annual_points_path(repo_root=repo_root,
                    file_glob=cfg.io.inputs.firms_points[sensor].file_glob, sensor=sensor, year=year)
                if selected.resolve() != source:
                    raise ValueError("configured annual source selection changed")

            current_geography: list[Path] = []
            if cfg.io.inputs.land_mask and cfg.processing.land_mask_policy.enabled_if_path_provided:
                current_geography.extend(_family(repo_root / cfg.io.inputs.land_mask))
            for polygon in cfg.io.inputs.polygons:
                current_geography.extend(_family(repo_root / polygon.path))
            recorded_geography = _recorded_identities(repo_root, qa.get("geography_file_identity"), label="geography")
            if _identities(repo_root, current_geography) != recorded_geography:
                raise ValueError("geography family selection changed or component identity incomplete")
        else:
            for entry in qa.get("geography_file_identity", []):
                if sha256_file(repo_root / entry["path"]) != entry["sha256"]:
                    raise ValueError("geography input identity changed")

        if is_archive or qa.get("input_profile_evidence"):
            from mv_firms_panels.core.input_profiles import source_profile_evidence
            if source is None:
                raise ValueError("source profile requires a source path")
            evidence = source_profile_evidence(input_config=cfg.io.inputs.firms_points[sensor],
                repo_root=repo_root, sensor=sensor, year=year, points_path=source)
            if qa.get("input_profile_evidence") != evidence or receipt.get("input_profile_evidence") != evidence:
                raise ValueError("source profile or admission identity changed")
        if is_archive and (not file_backed or qa.get("steps", {}).get("schema_validation", {}).get("status") != "PASS"):
            raise ValueError("Archive preparation requires file-backed schema-validated outputs")
        if is_archive:
            trace = qa.get("source_observation_trace_csv")
            if (not isinstance(trace, dict) or receipt.get("source_observation_trace_csv") != trace or
                sha256_file(repo_root / trace["path"]) != trace["sha256"]):
                raise ValueError("Archive source-observation trace identity changed or missing")
        schema_identities = qa.get("schema_file_identity", [])
        if is_archive and not schema_identities:
            raise ValueError("Archive schema identity missing")
        if schema_identities:
            actual_schemas = [repo_root / cfg.outputs.schemas["fires_canonical"]]
            if sensor == "viirs":
                actual_schemas.append(repo_root / cfg.outputs.schemas["fires_frp_canonical"])
            recorded_schemas = _recorded_identities(repo_root, schema_identities, label="schema")
            if _identities(repo_root, actual_schemas) != recorded_schemas:
                raise ValueError("schema input identity incomplete or selection changed")

        outputs = [("fires_canonical_csv", Path(count_path), "fires_canonical")]
        if sensor == "viirs":
            if frp_path is None:
                raise ValueError("VIIRS independent FRP partition missing")
            outputs.append(("fires_frp_canonical_csv", Path(frp_path), "fires_frp_canonical"))
            policy = qa.get("steps", {}).get("frp_dedup", {})
            if (policy.get("finite_frp_first") is not True or
                policy.get("tie_break") != list(cfg.processing.deduplication.tie_break) or
                policy.get("latlon_round_decimals") != cfg.processing.deduplication.latlon_round_decimals or
                policy.get("include_satellite_in_key") != cfg.processing.deduplication.include_satellite_in_key):
                raise ValueError("FRP deduplication policy mismatch")

        for output_key, actual, schema_key in outputs:
            entry = receipt[output_key]
            if (repo_root / entry["path"]).resolve() != actual.resolve() or entry["sha256"] != sha256_file(actual):
                raise ValueError(f"{output_key} path or hash mismatch")
            columns = cfg.determinism.column_order.get(schema_key)
            if not columns:
                raise ValueError(f"{output_key} column contract missing")
            schema = None
            # Receipts that bind schema bytes and a validated output hash
            # require only the current row-contract checks. Native receipts
            # without schema-byte identity also require schema validation.
            if (qa.get("steps", {}).get("schema_validation", {}).get("status") == "PASS"
                    and not schema_identities):
                schema = load_json_schema(repo_root / cfg.outputs.schemas[schema_key])
            strings = {key: "string" for key in columns if key not in
                       {"yyyymm", "latitude", "longitude", "frp_mw", "type", "was_dedup_kept"}}
            rows = 0
            seen_keys: set[tuple[str, str]] = set()
            observed_sources: set[str] = set()
            with pd.read_csv(actual, chunksize=100_000, dtype=strings) as reader:
                if list(reader.read(0).columns) != list(columns):
                    raise ValueError(f"{output_key} column contract mismatch")
                for frame in reader:
                    rows += len(frame)
                    observed_sources.update(frame["source_file"].dropna().astype(str))
                    dates = pd.to_datetime(frame["date_utc"], errors="coerce")
                    months = pd.to_numeric(frame["yyyymm"], errors="coerce")
                    if (not frame["sensor"].eq(sensor).all() or not frame["run_id"].eq(run_id).all() or
                        not (months // 100).eq(year).all() or
                        frame[["source_file", "level", "unit_id", "dedup_key"]].isna().any().any() or
                        dates.isna().any() or not (dates.dt.year * 100 + dates.dt.month).eq(months).all() or
                        not frame["conf_cat"].isin(("l", "n", "h")).all() or
                        not pd.to_numeric(frame["type"], errors="coerce").eq(0).all() or
                        not frame["was_dedup_kept"].astype(str).str.lower().eq("true").all()):
                        raise ValueError(f"{output_key} row identity or canonical contract mismatch")
                    keys = list(zip(frame["level"].astype(str), frame["dedup_key"].astype(str)))
                    if len(keys) != len(set(keys)) or seen_keys.intersection(keys):
                        raise ValueError(f"{output_key} duplicate keys")
                    seen_keys.update(keys)
                    if schema_key == "fires_frp_canonical" and not frame["conf_cat"].isin(("n", "h")).all():
                        raise ValueError("FRP population mismatch")
                    if schema is not None:
                        validate_dataframe_against_schema(
                            df=frame, schema=schema, expected_columns=columns, allow_reorder=False,
                        )
            if observed_sources and observed_sources != {source_name}:
                raise ValueError("partition source identity mismatch")
            if "rows" in entry and entry["rows"] != rows:
                raise ValueError(f"{output_key} row count mismatch")
        return qa
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PreparationEvidenceError(f"Invalid {sensor.upper()} preparation evidence for {year}: {exc}") from exc
