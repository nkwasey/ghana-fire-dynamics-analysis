# file: src/mv_firms_panels/cli/commands.py
"""CLI command implementations.

Safety flags
------------
Adds two safety flags used across commands:

- --skip-existing (default off)
    Safe resume: a stage may be skipped ONLY when:
      (1) sentinel exists,
      (2) outputs exist,
      (3) contracted outputs pass fast schema + column-contract checks.

- --force
    Overwrite: rerun stage even if outputs/sentinels exist or are inconsistent.

Fail-fast rule (binding)
------------------------
If outputs exist but sentinel is missing -> FAIL unless --force.
This prevents silently reusing “unknown provenance” artefacts.

Pipeline year-resolution behaviour
----------------------------------
Pipeline planning supports per-sensor year overrides:
- --years-viirs
- --years-modis
and clamps global --years by sensor coverage windows, failing fast on empty.

The pipeline also propagates the resolved aggregate bounds into `combine`, so the
final balanced panel matches the effective sensor windows rather than silently
falling back to cfg.processing.time_range.

Visualise stage gating uses visualise-owned artefacts only. Upstream combined
panel files are inputs to visualise, not visualise outputs.

Dual-sensor RP1 completeness
------------------------------
`combine --skip-existing` validates the full configured RP1 AF export
contract per sensor. The CLI resolves base and `_ext` schemas from
`outputs.rp1_exports.sensors.<sensor>.schemas` and requires every configured
sensor branch to be present in the combine manifest.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from mv_firms_panels.core.config import LoadedConfig, SensorName, load_config
from mv_firms_panels.core.hashing import sha256_text, short_hash8, stable_json_dumps
from mv_firms_panels.core.logging import initialise_run
from mv_firms_panels.core.schema import load_json_schema, validate_dataframe_against_schema
from mv_firms_panels.io.paths import (
    panel_monthly_ext_path,
    panel_monthly_wide_path,
    rp1_af_dir,
    sensor_panel_monthly_path,
)
from mv_firms_panels.stages.aggregate_monthly import aggregate_monthly
from mv_firms_panels.stages.combine_panels import combine_panels
from mv_firms_panels.stages.prepare_year import prepare_year
from mv_firms_panels.stages.visualise import visualise

LOG = logging.getLogger("mv_firms_panels.cli")


class CliError(RuntimeError):
    """Raised for user-facing CLI failures."""


def derive_run_id(
    loaded_cfg: LoadedConfig,
    *,
    explicit_run_id: str | None,
) -> str:
    if explicit_run_id:
        return explicit_run_id
    cfg = loaded_cfg.config
    canon_json = stable_json_dumps(cfg.to_canonical_dict())
    h8 = short_hash8(sha256_text(canon_json))
    base = f"{cfg.project.name}_{h8}"
    if cfg.project.run_id_strategy.timestamp_utc:
        now = datetime.now(UTC)
        return f"{base}_{now.strftime('%Y%m%dT%H%M%SZ')}"
    return base


def _repo_root_default(config_path: Path) -> Path:
    return Path(config_path).resolve().parents[1]


def _resolve_repo_root(*, repo_root: Path | None, config_path: Path) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    return _repo_root_default(config_path)


def _load_cfg(config_path: Path, *, repo_root: Path) -> LoadedConfig:
    try:
        return load_config(config_path, validate_paths=False, repo_root=repo_root)
    except Exception as e:
        raise CliError(f"Failed to load config: {e}") from e


def _initialise_run(
    loaded: LoadedConfig,
    *,
    repo_root: Path,
    run_id: str,
    zip_sha256: str | None = None,
    log_level: str = "INFO",
):
    try:
        return initialise_run(
            loaded,
            run_id=run_id,
            repo_root=repo_root,
            outputs_base_dir=loaded.config.outputs.base_dir,
            log_level=log_level,
            zip_sha256=zip_sha256,
        )
    except Exception as e:
        raise CliError(f"Failed to initialise run directory: {e}") from e


def _schema_string_columns(schema: dict[str, object]) -> list[str]:
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        return []
    out: list[str] = []
    for col, spec in props.items():
        if not isinstance(spec, dict):
            continue
        t = spec.get("type")
        if t == "string":
            out.append(str(col))
        elif (
            isinstance(t, list)
            and "string" in t
            and not any(x in t for x in ("number", "integer", "boolean", "object", "array"))
        ):
            out.append(str(col))
    return out


def _resolve_schema_rel_path(
    *,
    cfg: object,
    schema_key: str,
    sensor_mode: str | None = None,
) -> str | None:
    """Resolve a schema path from config for one logical artefact.

    Behaviour
    ---------
    - Contracted non-RP1 artefacts are still resolved from ``outputs.schemas``.
    - RP1 AF base / ``_ext`` artefacts are resolved from the explicit
      sensor-aware contract under ``outputs.rp1_exports.sensors`` when a
      ``sensor_mode`` is supplied.

    The helper deliberately does *not* guess a sensor-specific RP1 contract when
    ``sensor_mode`` is omitted.
    """
    outputs = getattr(cfg, "outputs", None)
    if outputs is None:
        return None

    schema_key = str(schema_key)
    if sensor_mode is not None and schema_key in {"rp1_af_monthly_base", "rp1_af_monthly_ext"}:
        export_kind = "base" if schema_key.endswith("_base") else "ext"
        rp1_schema_path = getattr(outputs, "rp1_schema_path", None)
        if callable(rp1_schema_path):
            return str(rp1_schema_path(sensor_mode=str(sensor_mode), export_kind=export_kind))

    schema_map = getattr(outputs, "schemas", {}) or {}
    schema_rel = schema_map.get(schema_key)
    return str(schema_rel) if schema_rel else None


def _fast_schema_check_csv(
    *,
    repo_root: Path,
    cfg: object,
    schema_key: str | None,
    csv_rel_path: str,
    sensor_mode: str | None = None,
    schema_rel_path: str | None = None,
) -> None:
    """Fast schema check with schema-aware dtype hints for string columns.

    Parameters
    ----------
    schema_key:
        Logical schema key such as ``panel_monthly`` or ``rp1_af_monthly_base``.
        Required unless ``schema_rel_path`` is supplied directly.
    sensor_mode:
        Used only for RP1 AF exports so the validator can route to the correct
        sensor-specific schema.
    schema_rel_path:
        Optional explicit repo-relative schema path. When supplied it takes
        precedence over ``schema_key`` lookup.
    """
    schema_rel: str | None = None
    if schema_rel_path is not None and str(schema_rel_path).strip():
        schema_rel = str(schema_rel_path)
    elif schema_key is not None:
        schema_rel = _resolve_schema_rel_path(
            cfg=cfg, schema_key=schema_key, sensor_mode=sensor_mode
        )

    if not schema_rel:
        return  # no configured schema for this artefact

    schema_path = (repo_root / str(schema_rel)).resolve()
    if not schema_path.exists():
        detail = f" key={schema_key!r}" if schema_key is not None else ""
        raise CliError(f"Schema file missing for{detail}: {schema_path}")

    abs_csv = (repo_root / csv_rel_path).resolve()
    if not abs_csv.exists():
        raise CliError(f"Contracted output missing for schema check: {csv_rel_path}")

    schema = load_json_schema(schema_path)
    string_cols = set(_schema_string_columns(schema))
    dtype = {c: "string" for c in string_cols}

    df = pd.read_csv(abs_csv, nrows=200, dtype=dtype)
    # Normalise pandas NA/NaN values to plain None before schema validation so
    # nullable integer/boolean fields written through CSV round-trips do not
    # fail fast validation merely because pandas re-read them as float NaN.
    df = df.astype(object).where(pd.notnull(df), None)
    validate_dataframe_against_schema(df, schema)

    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    expected_order = list(props.keys())
    if expected_order and list(df.columns) != expected_order:
        raise CliError(
            f"Column order mismatch for {csv_rel_path}\n"
            f"Expected: {expected_order}\n"
            f"Actual:   {list(df.columns)}"
        )


def _gate_stage_execution(
    *,
    stage: str,
    repo_root: Path,
    cfg,
    sentinel_path: Path,
    output_candidates: Sequence[Path],
    contracted_schema_checks: Sequence[tuple[str, str]],
    skip_existing: bool,
    force: bool,
) -> tuple[bool, str]:
    """Return (should_run, reason).

    Notes (why this shape):
    - Tests require that 'outputs exist but sentinel missing' raises even when skip_existing=False.
    - Some outputs are format-alternatives (csv.gz vs csv). Contract checks must not fail if an
      alternative format is absent but another exists.
    """
    if force:
        return True, "force"

    outputs_exist = any(p.exists() for p in output_candidates)
    sentinel_exists = sentinel_path.exists()

    # Binding: fail fast if outputs exist but sentinel is missing (regardless of skip_existing).
    if outputs_exist and not sentinel_exists:
        raise CliError(
            f"{stage}: outputs exist but sentinel is missing; refusing to proceed without --force.\n"
            f"Missing sentinel: {sentinel_path}"
        )

    if not skip_existing:
        return True, "skip_existing off"

    if not sentinel_exists:
        return True, "no sentinel"

    if not outputs_exist:
        return True, "no outputs"

    # Only validate contracted schema checks for files that exist.
    for schema_key, csv_rel_path in contracted_schema_checks:
        abs_p = (repo_root / csv_rel_path).resolve()
        if not abs_p.exists():
            continue
        _fast_schema_check_csv(
            repo_root=repo_root, cfg=cfg, schema_key=schema_key, csv_rel_path=csv_rel_path
        )

    return False, "sentinel + outputs + contracts ok"


def _load_json_object(*, path: Path, context: str) -> dict[str, object]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise CliError(f"{context}: failed to read JSON: {path}: {e}") from e
    if not isinstance(obj, dict):
        raise CliError(f"{context}: expected a JSON object at {path}")
    return obj


def _validate_manifest_path_entry(*, repo_root: Path, entry: object, context: str) -> None:
    if not isinstance(entry, dict):
        raise CliError(f"{context}: expected object with path")
    rel_path = entry.get("path")
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise CliError(f"{context}: missing non-empty path")
    abs_path = (repo_root / rel_path).resolve()
    if not abs_path.exists():
        raise CliError(f"{context}: referenced path missing: {rel_path}")


def _validate_rp1_af_exports_manifest(*, repo_root: Path, manifest: object, cfg) -> None:
    """Validate the RP1 AF manifest against the configured dual-sensor contract.

    The command layer deliberately validates only contract-relevant structure:
    - RP1 AF family metadata and merge keys
    - presence of every configured sensor branch
    - per-sensor windows and schema paths recorded in the manifest
    - generic per-level partition dictionaries
    - on-disk existence and fast schema validation of every referenced CSV

    It intentionally does *not* re-impose any ACZ-specific partition naming rules.
    """
    context = "combine_panels manifest rp1_af_exports"
    if not isinstance(manifest, dict):
        raise CliError(f"{context}: missing or invalid object")

    family_name = manifest.get("family_name")
    expected_family_name = getattr(
        getattr(cfg, "outputs", object()), "rp1_exports", object()
    ).family_name
    if family_name != expected_family_name:
        raise CliError(
            f"{context}: expected family_name={expected_family_name!r}, got {family_name!r}"
        )

    source = manifest.get("source")
    if source != ["panel_monthly_ext", "panel_monthly_qc", "unit_universe"]:
        raise CliError(
            f"{context}: expected source=['panel_monthly_ext', 'panel_monthly_qc', 'unit_universe'], got {source!r}"
        )

    families = manifest.get("families")
    if list(map(str, families or [])) != ["base", "ext"]:
        raise CliError(f"{context}: expected families ['base', 'ext']")

    merge_keys = manifest.get("merge_keys")
    if list(map(str, merge_keys or [])) != ["level", "unit_id", "yyyymm"]:
        raise CliError(f"{context}: expected merge_keys ['level', 'unit_id', 'yyyymm']")

    schema_version = manifest.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise CliError(f"{context}: missing non-empty schema_version")

    sensor_modes = manifest.get("sensor_modes")
    if not isinstance(sensor_modes, dict) or not sensor_modes:
        raise CliError(f"{context}: missing sensor_modes")

    configured_sensor_contracts = (
        getattr(getattr(cfg.outputs, "rp1_exports", object()), "sensors", {}) or {}
    )
    configured_sensor_modes = list(map(str, configured_sensor_contracts.keys()))
    missing_sensors = [sensor for sensor in configured_sensor_modes if sensor not in sensor_modes]
    extra_sensors = [
        sensor for sensor in sensor_modes.keys() if sensor not in configured_sensor_modes
    ]
    if missing_sensors:
        raise CliError(f"{context}: missing configured sensor_modes {missing_sensors}")
    if extra_sensors:
        raise CliError(f"{context}: unexpected sensor_modes {extra_sensors}")

    seen_partition_paths = 0
    for sensor_mode in configured_sensor_modes:
        sensor_manifest = sensor_modes.get(sensor_mode)
        if not isinstance(sensor_manifest, dict):
            raise CliError(f"{context}: sensor manifest for {sensor_mode!r} must be an object")
        if sensor_manifest.get("partition_basis") != "top_level_ancestor":
            raise CliError(
                f"{context}: sensor_mode={sensor_mode!r} expected partition_basis='top_level_ancestor'"
            )

        contract = configured_sensor_contracts[sensor_mode]
        expected_window = {
            "start_yyyymm": int(contract.window.start_yyyymm),
            "end_yyyymm": int(contract.window.end_yyyymm),
        }
        window = sensor_manifest.get("window")
        if window != expected_window:
            raise CliError(
                f"{context}: sensor_mode={sensor_mode!r} expected window {expected_window!r}, got {window!r}"
            )

        expected_schemas = {
            "base": str(contract.schemas.base),
            "ext": str(contract.schemas.ext),
        }
        schemas = sensor_manifest.get("schemas")
        if schemas != expected_schemas:
            raise CliError(
                f"{context}: sensor_mode={sensor_mode!r} expected schemas {expected_schemas!r}, got {schemas!r}"
            )

        levels = sensor_manifest.get("levels")
        if not isinstance(levels, dict) or not levels:
            raise CliError(
                f"{context}: sensor_mode={sensor_mode!r} missing non-empty levels mapping"
            )

        sensor_partition_paths = 0
        for level, level_manifest in levels.items():
            if not isinstance(level_manifest, dict):
                raise CliError(
                    f"{context}: sensor_mode={sensor_mode!r} level={level!r} must be an object"
                )

            base_partitions = level_manifest.get("base_partitions")
            ext_partitions = level_manifest.get("ext_partitions")
            if not isinstance(base_partitions, dict) or not base_partitions:
                raise CliError(
                    f"{context}: sensor_mode={sensor_mode!r} level={level!r} missing base_partitions"
                )
            if not isinstance(ext_partitions, dict) or not ext_partitions:
                raise CliError(
                    f"{context}: sensor_mode={sensor_mode!r} level={level!r} missing ext_partitions"
                )
            if set(base_partitions.keys()) != set(ext_partitions.keys()):
                raise CliError(
                    f"{context}: sensor_mode={sensor_mode!r} level={level!r} base/ext partition labels differ"
                )

            for family_name, partitions, schema_key in [
                ("base", base_partitions, "rp1_af_monthly_base"),
                ("ext", ext_partitions, "rp1_af_monthly_ext"),
            ]:
                expected_schema_rel = expected_schemas[family_name]
                for partition_label, entry in partitions.items():
                    if not isinstance(entry, dict):
                        raise CliError(
                            f"{context}: sensor_mode={sensor_mode!r} level={level!r} family={family_name!r} partition={partition_label!r} must be an object"
                        )
                    for req in [
                        "partition_key",
                        "partition_value",
                        "partition_level",
                        "path",
                        "sha256",
                        "n_rows",
                    ]:
                        if req not in entry:
                            raise CliError(
                                f"{context}: sensor_mode={sensor_mode!r} level={level!r} family={family_name!r} partition={partition_label!r} missing {req!r}"
                            )
                    _validate_manifest_path_entry(
                        repo_root=repo_root,
                        entry=entry,
                        context=(
                            f"{context}: sensor_mode={sensor_mode!r} level={level!r} family={family_name!r} partition={partition_label!r}"
                        ),
                    )
                    rel_path = str(entry["path"])
                    expected_fragment = f"rp1_af_exports/{level}/{sensor_mode}/"
                    if expected_fragment not in rel_path.replace("\\", "/"):
                        raise CliError(
                            f"{context}: sensor_mode={sensor_mode!r} level={level!r} family={family_name!r} path does not contain expected fragment {expected_fragment!r}: {rel_path!r}"
                        )
                    _fast_schema_check_csv(
                        repo_root=repo_root,
                        cfg=cfg,
                        schema_key=schema_key,
                        csv_rel_path=rel_path,
                        sensor_mode=sensor_mode,
                        schema_rel_path=expected_schema_rel,
                    )
                    sensor_partition_paths += 1
                    seen_partition_paths += 1

        if sensor_partition_paths <= 0:
            raise CliError(
                f"{context}: sensor_mode={sensor_mode!r} expected at least one RP1 AF export path"
            )

    if seen_partition_paths <= 0:
        raise CliError(f"{context}: expected at least one RP1 AF export path in manifest")


def _validate_combine_skip_existing_contract(*, repo_root: Path, manifest_path: Path, cfg) -> None:
    manifest = _load_json_object(path=manifest_path, context="combine_panels manifest")

    for key in ("panel_monthly", "qa_summary_json"):
        if key not in manifest:
            raise CliError(f"combine_panels manifest: missing required key {key!r}")
        _validate_manifest_path_entry(
            repo_root=repo_root, entry=manifest[key], context=f"combine_panels manifest {key}"
        )

    panel_ext = manifest.get("panel_monthly_ext")
    if panel_ext is not None:
        _validate_manifest_path_entry(
            repo_root=repo_root,
            entry=panel_ext,
            context="combine_panels manifest panel_monthly_ext",
        )

    _validate_rp1_af_exports_manifest(
        repo_root=repo_root, manifest=manifest.get("rp1_af_exports"), cfg=cfg
    )


def _visualise_output_candidates(*, run_dir: Path, make_plots: bool) -> list[Path]:
    """Return artefacts owned by the visualise stage.

    Important:
    - `panel_monthly.csv[.gz]` is an *input* to visualise and must not be used for
      stage-output gating.
    - The visualise stage always writes a QA summary JSON and a monthly totals CSV.
    - Plots are optional; when requested, the figures directory is also a legitimate
      owned artefact for gating / provenance checks.
    """
    candidates = [
        run_dir / "qa" / "visualise_summary.json",
        run_dir / "summaries" / "panel_monthly_totals_by_level.csv.gz",
    ]
    if make_plots:
        candidates.append(run_dir / "figures")
    return candidates


def cmd_prepare_year(
    *,
    repo_root: Path | None,
    config_path: Path,
    sensor: SensorName,
    year: int,
    run_id: str | None = None,
    zip_sha256: str | None = None,
    log_level: str = "INFO",
    skip_existing: bool = False,
    force: bool = False,
) -> int:
    repo_root = _resolve_repo_root(repo_root=repo_root, config_path=config_path)
    loaded = _load_cfg(config_path, repo_root=repo_root)
    rid = derive_run_id(loaded, explicit_run_id=run_id)
    run_ctx = _initialise_run(
        loaded, repo_root=repo_root, run_id=rid, zip_sha256=zip_sha256, log_level=log_level
    )
    run_dir = run_ctx.run_dir

    sentinel_path = run_dir / "qa" / f"prepare_year_{sensor}_{year}_manifest.json"
    qa_out = run_dir / "qa" / f"prepare_year_{sensor}_{year}_summary.json"
    fires_out = run_dir / "fires_canonical" / sensor / f"fires_canonical_{sensor}_{year}.csv"

    should_run, _ = _gate_stage_execution(
        stage=f"prepare_year({sensor},{year})",
        repo_root=repo_root,
        cfg=loaded.config,
        sentinel_path=sentinel_path,
        output_candidates=[qa_out, fires_out],
        contracted_schema_checks=[],
        skip_existing=bool(skip_existing),
        force=bool(force),
    )
    if not should_run:
        return 0

    try:
        prepare_year(
            cfg=loaded.config,
            repo_root=repo_root,
            sensor=sensor,
            year=year,
            run_id=rid,
            write_outputs=True,
        )
        return 0
    except Exception as e:
        LOG.exception("prepare-year failed")
        raise CliError(str(e)) from e


def cmd_aggregate(
    *,
    repo_root: Path | None,
    config_path: Path,
    sensor: SensorName,
    run_id: str | None = None,
    start_yyyymm: int | None = None,
    end_yyyymm: int | None = None,
    zip_sha256: str | None = None,
    log_level: str = "INFO",
    skip_existing: bool = False,
    force: bool = False,
) -> int:
    repo_root = _resolve_repo_root(repo_root=repo_root, config_path=config_path)
    loaded = _load_cfg(config_path, repo_root=repo_root)
    rid = derive_run_id(loaded, explicit_run_id=run_id)
    run_ctx = _initialise_run(
        loaded, repo_root=repo_root, run_id=rid, zip_sha256=zip_sha256, log_level=log_level
    )
    run_dir = run_ctx.run_dir

    sentinel_path = run_dir / "qa" / f"aggregate_monthly_{sensor}_manifest.json"
    qa_out = run_dir / "qa" / f"aggregate_monthly_{sensor}_summary.json"
    panel_candidates = [
        sensor_panel_monthly_path(run_dir=run_dir, sensor=sensor, fmt="csv.gz"),
        sensor_panel_monthly_path(run_dir=run_dir, sensor=sensor, fmt="csv"),
    ]

    should_run, _ = _gate_stage_execution(
        stage="aggregate_monthly",
        repo_root=repo_root,
        cfg=loaded.config,
        sentinel_path=sentinel_path,
        output_candidates=[qa_out, *panel_candidates],
        contracted_schema_checks=[],
        skip_existing=bool(skip_existing),
        force=bool(force),
    )
    if not should_run:
        return 0

    try:
        aggregate_monthly(
            cfg=loaded.config,
            repo_root=repo_root,
            sensor=sensor,
            run_id=rid,
            start_yyyymm=start_yyyymm,
            end_yyyymm=end_yyyymm,
            write_outputs=True,
        )
        return 0
    except Exception as e:
        LOG.exception("aggregate failed")
        raise CliError(str(e)) from e


def cmd_combine(
    *,
    repo_root: Path | None,
    config_path: Path,
    run_id: str | None = None,
    start_yyyymm: int | None = None,
    end_yyyymm: int | None = None,
    zip_sha256: str | None = None,
    log_level: str = "INFO",
    skip_existing: bool = False,
    force: bool = False,
) -> int:
    repo_root = _resolve_repo_root(repo_root=repo_root, config_path=config_path)
    loaded = _load_cfg(config_path, repo_root=repo_root)
    rid = derive_run_id(loaded, explicit_run_id=run_id)
    run_ctx = _initialise_run(
        loaded, repo_root=repo_root, run_id=rid, zip_sha256=zip_sha256, log_level=log_level
    )
    run_dir = run_ctx.run_dir

    sentinel_path = run_dir / "qa" / "combine_panels_manifest.json"
    qa_out = run_dir / "qa" / "combine_panels_summary.json"
    panel_candidates = [
        panel_monthly_wide_path(run_dir=run_dir, fmt="csv.gz"),
        panel_monthly_wide_path(run_dir=run_dir, fmt="csv"),
        panel_monthly_ext_path(run_dir=run_dir, fmt="csv.gz"),
        panel_monthly_ext_path(run_dir=run_dir, fmt="csv"),
        rp1_af_dir(run_dir),
    ]

    should_run, _ = _gate_stage_execution(
        stage="combine_panels",
        repo_root=repo_root,
        cfg=loaded.config,
        sentinel_path=sentinel_path,
        output_candidates=[qa_out, *panel_candidates],
        contracted_schema_checks=[
            (
                "panel_monthly",
                panel_monthly_wide_path(run_dir=run_dir, fmt="csv.gz")
                .relative_to(repo_root)
                .as_posix(),
            ),
            (
                "panel_monthly",
                panel_monthly_wide_path(run_dir=run_dir, fmt="csv")
                .relative_to(repo_root)
                .as_posix(),
            ),
        ],
        skip_existing=bool(skip_existing),
        force=bool(force),
    )
    if not should_run:
        try:
            _validate_combine_skip_existing_contract(
                repo_root=repo_root, manifest_path=sentinel_path, cfg=loaded.config
            )
        except CliError:
            should_run = True
        else:
            return 0

    try:
        combine_panels(
            cfg=loaded.config,
            repo_root=repo_root,
            run_id=rid,
            start_yyyymm=start_yyyymm,
            end_yyyymm=end_yyyymm,
            write_outputs=True,
        )
        return 0
    except Exception as e:
        LOG.exception("combine failed")
        raise CliError(str(e)) from e


def cmd_visualise(
    *,
    repo_root: Path | None,
    config_path: Path,
    run_id: str | None = None,
    make_plots: bool = True,
    zip_sha256: str | None = None,
    log_level: str = "INFO",
    skip_existing: bool = False,
    force: bool = False,
) -> int:
    repo_root = _resolve_repo_root(repo_root=repo_root, config_path=config_path)
    loaded = _load_cfg(config_path, repo_root=repo_root)
    rid = derive_run_id(loaded, explicit_run_id=run_id)
    run_ctx = _initialise_run(
        loaded, repo_root=repo_root, run_id=rid, zip_sha256=zip_sha256, log_level=log_level
    )
    run_dir = run_ctx.run_dir

    sentinel_path = run_dir / "qa" / "visualise_manifest.json"

    should_run, _ = _gate_stage_execution(
        stage="visualise",
        repo_root=repo_root,
        cfg=loaded.config,
        sentinel_path=sentinel_path,
        output_candidates=_visualise_output_candidates(
            run_dir=run_dir, make_plots=bool(make_plots)
        ),
        contracted_schema_checks=[],
        skip_existing=bool(skip_existing),
        force=bool(force),
    )
    if not should_run:
        return 0

    try:
        visualise(
            cfg=loaded.config,
            repo_root=repo_root,
            run_id=rid,
            make_plots=bool(make_plots),
            write_outputs=True,
        )
        return 0
    except Exception as e:
        LOG.exception("visualise failed")
        raise CliError(str(e)) from e


def _parse_years(years: str | None) -> list[int] | None:
    if years is None:
        return None
    years = years.strip()
    if not years:
        return None
    if re.fullmatch(r"\d{4}-\d{4}", years):
        a, b = years.split("-")
        start = int(a)
        end = int(b)
        if start > end:
            raise CliError("years range start must be <= end")
        return list(range(start, end + 1))
    parts = [p.strip() for p in years.split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        if not re.fullmatch(r"\d{4}", p):
            raise CliError(f"Invalid year token: {p}")
        out.append(int(p))
    return out


def _discover_years_from_inputs(run_dir: Path, *, sensor: SensorName) -> list[int]:
    d = run_dir / "fires_canonical" / sensor
    if not d.exists():
        return []
    years: list[int] = []
    for p in d.glob(f"fires_canonical_{sensor}_*.csv"):
        m = re.search(rf"fires_canonical_{sensor}_(\d{{4}})\.csv$", p.name)
        if m:
            years.append(int(m.group(1)))
    return sorted(set(years))


_DEFAULT_SENSOR_COVERAGE_START_YYYYMM: dict[SensorName, int] = {"viirs": 201201, "modis": 200001}


def _sensor_clamp_window_for_years(
    loaded: LoadedConfig, *, sensor: SensorName
) -> tuple[int | None, int | None]:
    proc = loaded.config.processing

    start_yyyymm: int | None = None
    end_yyyymm: int | None = None

    if proc.sensor_time_ranges and sensor in proc.sensor_time_ranges:
        tr = proc.sensor_time_ranges[sensor]
        start_yyyymm = tr.start_yyyymm
        end_yyyymm = tr.end_yyyymm

    if proc.sensor_coverage and sensor in proc.sensor_coverage:
        cov = proc.sensor_coverage[sensor]
        if cov.start_yyyymm is not None:
            start_yyyymm = (
                cov.start_yyyymm if start_yyyymm is None else max(start_yyyymm, cov.start_yyyymm)
            )
        if cov.end_yyyymm is not None:
            end_yyyymm = cov.end_yyyymm if end_yyyymm is None else min(end_yyyymm, cov.end_yyyymm)

    default_start = _DEFAULT_SENSOR_COVERAGE_START_YYYYMM.get(sensor)
    if default_start is not None:
        start_yyyymm = default_start if start_yyyymm is None else max(start_yyyymm, default_start)

    if start_yyyymm is not None and end_yyyymm is not None and start_yyyymm > end_yyyymm:
        raise CliError(
            f"Invalid sensor window for {sensor}: start_yyyymm {start_yyyymm} > end_yyyymm {end_yyyymm}"
        )

    return start_yyyymm, end_yyyymm


def _clamp_years_to_window(
    years: list[int], *, start_yyyymm: int | None, end_yyyymm: int | None
) -> list[int]:
    if not years:
        return []
    start_year = (start_yyyymm // 100) if start_yyyymm is not None else None
    end_year = (end_yyyymm // 100) if end_yyyymm is not None else None
    return [
        y
        for y in years
        if (start_year is None or y >= start_year) and (end_year is None or y <= end_year)
    ]


def _bounds_for_years(
    years: list[int], *, clamp_start_yyyymm: int | None, clamp_end_yyyymm: int | None
) -> tuple[int, int]:
    if not years:
        raise CliError("Cannot resolve aggregate bounds from an empty year list")
    start_yyyymm = min(years) * 100 + 1
    end_yyyymm = max(years) * 100 + 12
    if clamp_start_yyyymm is not None:
        start_yyyymm = max(start_yyyymm, clamp_start_yyyymm)
    if clamp_end_yyyymm is not None:
        end_yyyymm = min(end_yyyymm, clamp_end_yyyymm)
    if start_yyyymm > end_yyyymm:
        raise CliError(
            f"Resolved yyyymm bounds invalid: start_yyyymm {start_yyyymm} > end_yyyymm {end_yyyymm}"
        )
    return start_yyyymm, end_yyyymm


def _default_aggregate_bounds_for_sensor(
    loaded: LoadedConfig,
    *,
    sensor: SensorName,
    discovered_years: Sequence[int],
) -> tuple[tuple[int, int] | None, str]:
    """Resolve default aggregate bounds for pipeline planning when CLI years are absent.

    This mirrors aggregate_monthly precedence as closely as possible while producing
    explicit two-sided bounds for downstream combine planning when feasible.

    Precedence:
      1) cfg.processing.sensor_time_ranges[sensor] (filling one-sided bounds from discovered inputs)
      2) cfg.processing.time_range (filling one-sided bounds from discovered inputs)
      3) discovered input years only
      4) no bounds available
    """
    inferred_from_inputs: tuple[int, int] | None = None
    if discovered_years:
        inferred_from_inputs = _bounds_for_years(
            list(discovered_years), clamp_start_yyyymm=None, clamp_end_yyyymm=None
        )

    tr_map = getattr(loaded.config.processing, "sensor_time_ranges", None)
    if tr_map and sensor in tr_map:
        tr = tr_map[sensor]
        start = tr.start_yyyymm
        end = tr.end_yyyymm
        if start is not None or end is not None:
            if inferred_from_inputs is not None:
                start = inferred_from_inputs[0] if start is None else int(start)
                end = inferred_from_inputs[1] if end is None else int(end)
            if start is not None and end is not None:
                if int(start) > int(end):
                    raise CliError(
                        f"Invalid default aggregate bounds for {sensor} from processing.sensor_time_ranges: "
                        f"start_yyyymm {start} > end_yyyymm {end}"
                    )
                return (int(start), int(end)), "cfg.processing.sensor_time_ranges"

    tr = getattr(loaded.config.processing, "time_range", None)
    if tr is not None:
        start = getattr(tr, "start_yyyymm", None)
        end = getattr(tr, "end_yyyymm", None)
        if start is not None or end is not None:
            if inferred_from_inputs is not None:
                start = inferred_from_inputs[0] if start is None else int(start)
                end = inferred_from_inputs[1] if end is None else int(end)
            if start is not None and end is not None:
                if int(start) > int(end):
                    raise CliError(
                        f"Invalid default aggregate bounds for {sensor} from processing.time_range: "
                        f"start_yyyymm {start} > end_yyyymm {end}"
                    )
                return (int(start), int(end)), "cfg.processing.time_range"

    if inferred_from_inputs is not None:
        return inferred_from_inputs, "discovered_inputs"

    return None, "none"


def _combine_bounds_from_sensor_bounds(
    aggregate_bounds_by_sensor: dict[str, tuple[int, int]],
) -> tuple[int, int] | None:
    if not aggregate_bounds_by_sensor:
        return None
    starts = [int(v[0]) for v in aggregate_bounds_by_sensor.values()]
    ends = [int(v[1]) for v in aggregate_bounds_by_sensor.values()]
    if not starts or not ends:
        return None
    start_yyyymm = min(starts)
    end_yyyymm = max(ends)
    if start_yyyymm > end_yyyymm:
        raise CliError(
            f"Resolved combine bounds invalid: start_yyyymm {start_yyyymm} > end_yyyymm {end_yyyymm}"
        )
    return start_yyyymm, end_yyyymm


def cmd_pipeline(
    *,
    repo_root: Path | None,
    config_path: Path,
    run_id: str | None = None,
    years: str | None = None,
    years_viirs: str | None = None,
    years_modis: str | None = None,
    dry_run: bool = False,
    make_plots: bool = True,
    zip_sha256: str | None = None,
    log_level: str = "INFO",
    skip_existing: bool = False,
    force: bool = False,
) -> int:
    repo_root = _resolve_repo_root(repo_root=repo_root, config_path=config_path)
    loaded = _load_cfg(config_path, repo_root=repo_root)
    rid = derive_run_id(loaded, explicit_run_id=run_id)
    run_ctx = _initialise_run(
        loaded, repo_root=repo_root, run_id=rid, zip_sha256=zip_sha256, log_level=log_level
    )
    run_dir = run_ctx.run_dir

    plan: dict[str, object] = {
        "run_id": rid,
        "repo_root": str(repo_root),
        "config": str(config_path),
        "stages": [],
    }

    years_list_global = _parse_years(years)
    years_list_viirs = _parse_years(years_viirs)
    years_list_modis = _parse_years(years_modis)

    years_by_sensor: dict[str, list[int]] = {}
    aggregate_bounds_by_sensor: dict[str, tuple[int, int]] = {}
    aggregate_bounds_source_by_sensor: dict[str, str] = {}

    for sensor in loaded.config.processing.sensors_enabled:
        clamp_start, clamp_end = _sensor_clamp_window_for_years(loaded, sensor=sensor)

        requested: list[int] | None = None
        requested_source: str = "auto"

        if sensor == "viirs" and years_list_viirs is not None:
            requested = years_list_viirs
            requested_source = "sensor"
        elif sensor == "modis" and years_list_modis is not None:
            requested = years_list_modis
            requested_source = "sensor"
        elif years_list_global is not None:
            requested = years_list_global
            requested_source = "global"

        if requested is None:
            resolved_years = _discover_years_from_inputs(run_dir, sensor=sensor)
            years_by_sensor[sensor] = resolved_years
            default_bounds, default_source = _default_aggregate_bounds_for_sensor(
                loaded, sensor=sensor, discovered_years=resolved_years
            )
            if default_bounds is not None:
                aggregate_bounds_by_sensor[sensor] = default_bounds
                aggregate_bounds_source_by_sensor[sensor] = default_source
            continue

        clamped = _clamp_years_to_window(requested, start_yyyymm=clamp_start, end_yyyymm=clamp_end)

        if requested_source == "sensor" and clamped != requested:
            raise CliError(
                f"Requested {sensor} years include values outside the {sensor} window: requested={requested} "
                f"window_start_yyyymm={clamp_start} window_end_yyyymm={clamp_end}"
            )

        if not clamped:
            raise CliError(
                f"No years remain for sensor={sensor} after resolving CLI years "
                f"(source={requested_source}, requested={requested}) with window_start_yyyymm={clamp_start} "
                f"window_end_yyyymm={clamp_end}"
            )

        years_by_sensor[sensor] = clamped
        aggregate_bounds_by_sensor[sensor] = _bounds_for_years(
            clamped, clamp_start_yyyymm=clamp_start, clamp_end_yyyymm=clamp_end
        )
        aggregate_bounds_source_by_sensor[sensor] = f"cli:{requested_source}"

    plan["years_by_sensor"] = years_by_sensor
    if aggregate_bounds_by_sensor:
        plan["aggregate_bounds_by_sensor"] = {
            k: [v[0], v[1]] for k, v in aggregate_bounds_by_sensor.items()
        }
        plan["aggregate_bounds_source_by_sensor"] = aggregate_bounds_source_by_sensor

    combine_bounds = _combine_bounds_from_sensor_bounds(aggregate_bounds_by_sensor)
    if combine_bounds is not None:
        plan["combine_bounds"] = [combine_bounds[0], combine_bounds[1]]

    for sensor in loaded.config.processing.sensors_enabled:
        for y in years_by_sensor.get(sensor, []):
            plan["stages"].append({"stage": "prepare-year", "sensor": sensor, "year": y})

        b = aggregate_bounds_by_sensor.get(sensor)
        if b is None:
            plan["stages"].append({"stage": "aggregate", "sensor": sensor})
        else:
            plan["stages"].append(
                {"stage": "aggregate", "sensor": sensor, "start_yyyymm": b[0], "end_yyyymm": b[1]}
            )

    combine_stage: dict[str, object] = {"stage": "combine"}
    if combine_bounds is not None:
        combine_stage["start_yyyymm"] = combine_bounds[0]
        combine_stage["end_yyyymm"] = combine_bounds[1]
    plan["stages"].append(combine_stage)
    plan["stages"].append({"stage": "visualise", "plots": bool(make_plots)})

    if dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    for sensor in loaded.config.processing.sensors_enabled:
        for y in years_by_sensor.get(sensor, []):
            cmd_prepare_year(
                repo_root=repo_root,
                config_path=config_path,
                sensor=sensor,
                year=int(y),
                run_id=rid,
                zip_sha256=zip_sha256,
                log_level=log_level,
                skip_existing=skip_existing,
                force=force,
            )

        b = aggregate_bounds_by_sensor.get(sensor)
        cmd_aggregate(
            repo_root=repo_root,
            config_path=config_path,
            sensor=sensor,
            run_id=rid,
            start_yyyymm=(b[0] if b is not None else None),
            end_yyyymm=(b[1] if b is not None else None),
            zip_sha256=zip_sha256,
            log_level=log_level,
            skip_existing=skip_existing,
            force=force,
        )

    cmd_combine(
        repo_root=repo_root,
        config_path=config_path,
        run_id=rid,
        start_yyyymm=(combine_bounds[0] if combine_bounds is not None else None),
        end_yyyymm=(combine_bounds[1] if combine_bounds is not None else None),
        zip_sha256=zip_sha256,
        log_level=log_level,
        skip_existing=skip_existing,
        force=force,
    )

    cmd_visualise(
        repo_root=repo_root,
        config_path=config_path,
        run_id=rid,
        make_plots=bool(make_plots),
        zip_sha256=zip_sha256,
        log_level=log_level,
        skip_existing=skip_existing,
        force=force,
    )

    return 0
