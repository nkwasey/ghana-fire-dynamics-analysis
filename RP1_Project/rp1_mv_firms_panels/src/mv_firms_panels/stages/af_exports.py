# file: src/mv_firms_panels/stages/af_exports.py
"""Merger-ready RP1 AF exports aligned to the generic Stage 1 hierarchy contract.

Purpose
-------
This module writes the dedicated RP1 active-fire export family used downstream
for AF/BA merger work. The exporter is sensor-aware and writes the same
merger-ready family for VIIRS and MODIS while preserving the balanced monthly
panel semantics.

Binding design
--------------
- Source the RP1 AF family from three upstream artefacts:
  ``panel_monthly_ext`` for analytical monthly AF fields,
  ``panel_monthly_qc`` for row-level QC / coverage information, and
  ``unit_universe`` for canonical Stage 1 identity metadata.
- Do **not** rebuild RP1 AF exports from raw detections.
- Use the Stage 1 generic identity vocabulary in the canonical CSV schema:
  ``level``, ``unit_id``, ``unit_code``, ``unit_name``,
  ``parent_level``, ``parent_id``, ``parent_code``, ``parent_name``.
- Keep sensor specificity in the path structure and manifest, not as an in-file
  canonical CSV column.
- Clip the dedicated RP1 AF family to the locked *sensor-specific* RP1 analysis
  windows configured under ``outputs.rp1_exports.sensors`` while leaving broader
  monthly panels unchanged.
- Emit a lean merger-ready base export plus an additive ``_ext`` companion. The
  ``_ext`` family always begins with the full base schema in identical order.
- Fail fast if the combine-stage source artefacts do not contain the required
  sensor-specific columns for the requested export contract.

Sensor scope
------------
The implementation is sensor-aware rather than VIIRS-special-cased. The export family name remains ``rp1_af_exports`` for both
sensors. Each sensor gets:
- its own configured RP1 export window,
- its own configured JSON schemas, and
- its own path branch under ``rp1_af_exports/<level>/<sensor>/...``

The export-contract layer preserves the monthly analytical meaning for each sensor.

Schema validation note
----------------------
The preferred schema paths come from ``cfg.outputs.rp1_exports.sensors`` so the
writer validates each sensor against its own base and ``_ext`` schema. The current public configuration API also exposes shared RP1 schema aliases. If a
minimal source fixture supplies those aliases rather than sensor-specific schema
paths, validation resolves the shared schema deterministically. In-code column
ordering remains authoritative, so this resolution path cannot permit column drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from mv_firms_panels.core.config import SUPPORTED_RP1_EXPORT_SENSOR_MODES, AppConfig
from mv_firms_panels.core.hashing import sha256_file
from mv_firms_panels.core.schema import load_json_schema, validate_dataframe_against_schema
from mv_firms_panels.io.paths import rp1_af_export_path
from mv_firms_panels.io.writers import write_dataframe_csv


class AFExportsError(ValueError):
    """Raised when RP1 AF export generation fails."""


@dataclass(frozen=True)
class AFExportsResult:
    manifest: dict[str, object]
    paths: list[Path]


@dataclass(frozen=True)
class SensorExportContract:
    """Deterministic RP1 export contract for one supported sensor."""

    sensor_mode: str
    schema_version: str
    window_start_yyyymm: int
    window_end_yyyymm: int
    analytical_columns: list[str]
    qc_columns: list[str]
    base_columns: list[str]
    ext_columns: list[str]
    panel_ext_required_columns: list[str]
    qc_required_columns: list[str]


VIIRS_SENSOR_MODE = "viirs"
MODIS_SENSOR_MODE = "modis"

RP1_AF_SCHEMA_VERSION = "rp1_af_monthly_v2"
RP1_AF_MERGE_KEYS = ["level", "unit_id", "yyyymm"]

RP1_AF_IDENTITY_COLUMNS = [
    "run_id",
    "schema_version",
    "level",
    "unit_id",
    "unit_code",
    "unit_name",
    "parent_level",
    "parent_id",
    "parent_code",
    "parent_name",
    "yyyymm",
    "year",
    "month",
]

# The analytical and QC blocks are defined once in generic suffix form, then
# sensorised deterministically so VIIRS and MODIS remain perfectly aligned.
_ANALYTICAL_SUFFIXES = [
    "det_low",
    "det_nominal",
    "det_high",
    "det_all",
    "det_nh",
    "pct_high_conf",
    "days_active_nh",
    "streak_max_nh",
    "frp_active_days",
    "frp_sum_daily_max_mw",
    "frp_mean_mw",
    "frp_p95_daily_max_mw",
]

_EXT_QC_SUFFIXES = [
    "has_any",
    "in_coverage_flag",
    "structural_missing_flag",
    "low_information_month_flag",
    "frp_ok_flag",
]

RP1_AF_EXT_PROVENANCE_COLUMNS = [
    "sensor_coverage_start_yyyymm",
    "sensor_coverage_end_yyyymm",
    "year_rows_in_panel",
    "year_rows_in_sensor_coverage",
    "year_rows_structural_missing",
    "year_coverage_complete_flag",
]

_PARTITION_META_COLUMNS = [
    "partition_level",
    "partition_id",
    "partition_code",
    "partition_name",
    "partition_key",
    "partition_value",
    "partition_label",
]

_UNIT_UNIVERSE_MINIMAL_COLUMNS = [
    "level",
    "unit_id",
    "unit_name",
]

_UNIT_UNIVERSE_OPTIONAL_COLUMNS = [
    "unit_code",
    "parent_level",
    "parent_id",
    "parent_code",
    "parent_name",
]

_UNIT_UNIVERSE_REQUIRED_COLUMNS = list(
    _UNIT_UNIVERSE_MINIMAL_COLUMNS + _UNIT_UNIVERSE_OPTIONAL_COLUMNS
)


def _normalise_sensor_mode(sensor_mode: str | None) -> str:
    """Return a supported sensor token, using VIIRS as the current default."""
    if sensor_mode is None:
        return VIIRS_SENSOR_MODE
    token = str(sensor_mode).strip().lower()
    if token not in SUPPORTED_RP1_EXPORT_SENSOR_MODES:
        raise AFExportsError(
            f"Unsupported RP1 AF sensor mode: {sensor_mode!r}. "
            f"Supported: {list(SUPPORTED_RP1_EXPORT_SENSOR_MODES)}"
        )
    return token


def _sensorised_columns(columns: Sequence[str], *, sensor_mode: str) -> list[str]:
    """Swap the canonical VIIRS prefix for the requested sensor prefix.

    The deterministic in-code column contract is defined once against the VIIRS
    prefix. MODIS columns are generated by a stable prefix substitution so the
    two sensor contracts remain structurally identical apart from the prefix.
    """
    sensor = _normalise_sensor_mode(sensor_mode)
    if sensor == VIIRS_SENSOR_MODE:
        return list(columns)

    out: list[str] = []
    for col in columns:
        if col.startswith("viirs_"):
            out.append(f"{sensor}_{col[len('viirs_'):]}")
        else:
            out.append(col)
    return out


def _sensorised_metric_columns(*, sensor_mode: str) -> list[str]:
    return [f"{_normalise_sensor_mode(sensor_mode)}_{suffix}" for suffix in _ANALYTICAL_SUFFIXES]


def _sensorised_qc_columns(*, sensor_mode: str) -> list[str]:
    return [f"{_normalise_sensor_mode(sensor_mode)}_{suffix}" for suffix in _EXT_QC_SUFFIXES]


def _sensor_contract(cfg: AppConfig, *, sensor_mode: str) -> SensorExportContract:
    """Build the explicit sensor-aware RP1 export contract from config."""
    sensor = _normalise_sensor_mode(sensor_mode)
    try:
        rp1_contract = cfg.outputs.rp1_exports.sensors[sensor]
    except KeyError as exc:
        raise AFExportsError(f"Config missing outputs.rp1_exports.sensors.{sensor}") from exc

    start = getattr(rp1_contract.window, "start_yyyymm", None)
    end = getattr(rp1_contract.window, "end_yyyymm", None)
    if start is None or end is None:
        raise AFExportsError(
            f"Config outputs.rp1_exports.sensors.{sensor}.window requires both start_yyyymm and end_yyyymm"
        )

    analytical_columns = _sensorised_metric_columns(sensor_mode=sensor)
    qc_columns = _sensorised_qc_columns(sensor_mode=sensor)
    base_columns = list(RP1_AF_IDENTITY_COLUMNS + analytical_columns)
    ext_columns = list(base_columns + qc_columns + RP1_AF_EXT_PROVENANCE_COLUMNS)

    panel_ext_required_columns = [
        "run_id",
        "level",
        "unit_id",
        "yyyymm",
        "year",
        "month",
        f"{sensor}_det_low",
        f"{sensor}_det_nominal",
        f"{sensor}_det_high",
        f"{sensor}_det_nh",
        f"{sensor}_pct_high_conf",
        f"{sensor}_days_active_nh",
        f"{sensor}_streak_max_nh",
        f"{sensor}_frp_active_days",
        f"{sensor}_frp_sum_daily_max_mw",
        f"{sensor}_frp_mean_mw",
        f"{sensor}_frp_p95_daily_max_mw",
    ]
    qc_required_columns = [
        "level",
        "unit_id",
        "yyyymm",
        f"{sensor}_has_any",
        f"{sensor}_in_coverage_flag",
        f"{sensor}_structural_missing_flag",
        f"{sensor}_low_information_month_flag",
        f"{sensor}_frp_ok_flag",
    ]

    return SensorExportContract(
        sensor_mode=sensor,
        schema_version=RP1_AF_SCHEMA_VERSION,
        window_start_yyyymm=int(start),
        window_end_yyyymm=int(end),
        analytical_columns=analytical_columns,
        qc_columns=qc_columns,
        base_columns=base_columns,
        ext_columns=ext_columns,
        panel_ext_required_columns=panel_ext_required_columns,
        qc_required_columns=qc_required_columns,
    )


def af_base_column_order(sensor_mode: str | None = None) -> list[str]:
    """Return the exact deterministic column order for the RP1 AF base export."""
    sensor = _normalise_sensor_mode(sensor_mode)
    return list(RP1_AF_IDENTITY_COLUMNS + _sensorised_metric_columns(sensor_mode=sensor))


def af_ext_column_order(sensor_mode: str | None = None) -> list[str]:
    """Return the exact deterministic column order for the RP1 AF _ext export."""
    sensor = _normalise_sensor_mode(sensor_mode)
    return list(
        af_base_column_order(sensor)
        + _sensorised_qc_columns(sensor_mode=sensor)
        + RP1_AF_EXT_PROVENANCE_COLUMNS
    )


def _blank_to_na(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    return text if text else pd.NA


def _as_int64_nullable(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _as_float_nullable(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Float64")


def _require_columns(df: pd.DataFrame, *, required: Sequence[str], label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise AFExportsError(f"{label} is missing required columns: {missing}")


def _assert_merge_safe(df: pd.DataFrame, *, label: str) -> None:
    dupes = df.duplicated(subset=RP1_AF_MERGE_KEYS, keep=False)
    if dupes.any():
        raise AFExportsError(f"{label} is not row-unique on merge keys {RP1_AF_MERGE_KEYS}")


def _normalise_unit_universe(unit_universe_df: pd.DataFrame) -> pd.DataFrame:
    """Normalise Stage 1 identity metadata for RP1 AF exports.

    Current minimal-fixture rule:
    - minimal fixtures may contain only ``level``, ``unit_id``, ``unit_name``
    - optional Stage 1 identity columns are created as blank when absent

    This keeps the exporter aligned to the generic Stage 1 contract without
    forcing every internal test fixture to provide a fully populated hierarchy.
    """
    _require_columns(
        unit_universe_df, required=_UNIT_UNIVERSE_MINIMAL_COLUMNS, label="unit_universe"
    )

    uu = unit_universe_df.copy()

    for col in _UNIT_UNIVERSE_OPTIONAL_COLUMNS:
        if col not in uu.columns:
            uu[col] = pd.NA

    uu = uu.loc[:, _UNIT_UNIVERSE_REQUIRED_COLUMNS].copy()

    for col in _UNIT_UNIVERSE_REQUIRED_COLUMNS:
        uu[col] = uu[col].map(_blank_to_na)

    uu["level"] = uu["level"].astype(str)
    uu["unit_id"] = uu["unit_id"].astype(str)
    uu["unit_name"] = uu["unit_name"].astype(str)

    meta = uu.drop_duplicates(subset=["level", "unit_id"], keep="first").reset_index(drop=True)
    dupes = meta.duplicated(subset=["level", "unit_id"], keep=False)
    if dupes.any():
        raise AFExportsError("unit_universe has non-unique level+unit_id rows after normalisation")
    return meta


def _build_identity_and_partition_metadata(unit_universe_df: pd.DataFrame) -> pd.DataFrame:
    """Build canonical Stage 1 identity metadata and generic partition metadata.

    Partitioning is derived *generically* from the hierarchy in ``unit_universe``.
    Each row is assigned to its top-level ancestor. For a top-level row, the row
    partitions to itself. The realised partition token is represented by:
    - ``partition_level``
    - ``partition_key``
    - ``partition_value``

    In the current Ghana repository this resolves to ACZ-derived partitions, but
    the implementation does not hard-code ACZ semantics.
    """
    meta = _normalise_unit_universe(unit_universe_df)
    lookup: dict[tuple[str, str], Mapping[str, object]] = {
        (str(row["level"]), str(row["unit_id"])): row for row in meta.to_dict("records")
    }

    def _resolve_root(
        key: tuple[str, str], trail: Iterable[tuple[str, str]] | None = None
    ) -> Mapping[str, object]:
        visited = set(trail or [])
        if key in visited:
            raise AFExportsError(
                f"Cycle detected in unit_universe hierarchy while resolving partition root for {key!r}"
            )
        visited.add(key)
        row = lookup.get(key)
        if row is None:
            raise AFExportsError(f"unit_universe is missing hierarchy row for {key!r}")

        parent_level = _blank_to_na(row.get("parent_level"))
        parent_id = _blank_to_na(row.get("parent_id"))
        if pd.isna(parent_level) or pd.isna(parent_id):
            return row

        parent_key = (str(parent_level), str(parent_id))
        if parent_key not in lookup:
            raise AFExportsError(
                f"unit_universe parent reference {parent_key!r} not found for child {(row['level'], row['unit_id'])!r}"
            )
        return _resolve_root(parent_key, trail=visited)

    rows: list[dict[str, object]] = []
    for rec in meta.to_dict("records"):
        key = (str(rec["level"]), str(rec["unit_id"]))
        root = _resolve_root(key)

        partition_level = str(root["level"])
        partition_id = str(root["unit_id"])
        partition_code = _blank_to_na(root.get("unit_code"))
        partition_name = str(root["unit_name"])
        if pd.isna(partition_code):
            partition_key = f"{partition_level}_id"
            partition_value = partition_id
        else:
            partition_key = f"{partition_level}_code"
            partition_value = str(partition_code)

        rows.append(
            {
                "level": str(rec["level"]),
                "unit_id": str(rec["unit_id"]),
                "unit_code": _blank_to_na(rec.get("unit_code")),
                "unit_name": str(rec["unit_name"]),
                "parent_level": _blank_to_na(rec.get("parent_level")),
                "parent_id": _blank_to_na(rec.get("parent_id")),
                "parent_code": _blank_to_na(rec.get("parent_code")),
                "parent_name": _blank_to_na(rec.get("parent_name")),
                "partition_level": partition_level,
                "partition_id": partition_id,
                "partition_code": partition_code,
                "partition_name": partition_name,
                "partition_key": partition_key,
                "partition_value": partition_value,
                "partition_label": f"{partition_key}={partition_value}",
            }
        )

    out = pd.DataFrame(rows)
    dupes = out.duplicated(subset=["level", "unit_id"], keep=False)
    if dupes.any():
        raise AFExportsError("Identity/partition metadata is not unique on level+unit_id")
    return out


def _prepare_panel_ext_source(
    panel_ext_df: pd.DataFrame, *, contract: SensorExportContract
) -> pd.DataFrame:
    """Select, coerce, derive, and clip the source monthly analytical frame."""
    sensor = contract.sensor_mode
    _require_columns(
        panel_ext_df,
        required=contract.panel_ext_required_columns,
        label=f"panel_monthly_ext[{sensor}]",
    )

    out = panel_ext_df.loc[:, contract.panel_ext_required_columns].copy()
    out["level"] = out["level"].astype(str)
    out["unit_id"] = out["unit_id"].astype(str)
    out["run_id"] = out["run_id"].astype(str)
    out["yyyymm"] = _as_int64_nullable(out["yyyymm"])
    out["year"] = _as_int64_nullable(out["year"])
    out["month"] = _as_int64_nullable(out["month"])

    int_metric_cols = [
        f"{sensor}_det_low",
        f"{sensor}_det_nominal",
        f"{sensor}_det_high",
        f"{sensor}_det_nh",
        f"{sensor}_days_active_nh",
        f"{sensor}_streak_max_nh",
        f"{sensor}_frp_active_days",
    ]
    float_metric_cols = [
        f"{sensor}_pct_high_conf",
        f"{sensor}_frp_sum_daily_max_mw",
        f"{sensor}_frp_mean_mw",
        f"{sensor}_frp_p95_daily_max_mw",
    ]

    for col in int_metric_cols:
        out[col] = _as_int64_nullable(out[col])

    for col in float_metric_cols:
        out[col] = _as_float_nullable(out[col])

    det_components = out.loc[
        :, [f"{sensor}_det_low", f"{sensor}_det_nominal", f"{sensor}_det_high"]
    ].apply(pd.to_numeric, errors="coerce")
    out[f"{sensor}_det_all"] = det_components.sum(axis=1, min_count=1).astype("Float64")
    out[f"{sensor}_det_all"] = out[f"{sensor}_det_all"].round(0).astype("Int64")

    out = out.loc[
        (out["yyyymm"] >= contract.window_start_yyyymm)
        & (out["yyyymm"] <= contract.window_end_yyyymm)
    ].copy()
    _assert_merge_safe(out, label=f"panel_monthly_ext[{sensor},clipped]")
    return out.reset_index(drop=True)


def _prepare_qc_source(qc_df: pd.DataFrame, *, contract: SensorExportContract) -> pd.DataFrame:
    """Select, coerce, and clip the sensor-specific QC sidecar source."""
    sensor = contract.sensor_mode
    _require_columns(
        qc_df, required=contract.qc_required_columns, label=f"panel_monthly_qc[{sensor}]"
    )

    out = qc_df.loc[:, contract.qc_required_columns].copy()
    out["level"] = out["level"].astype(str)
    out["unit_id"] = out["unit_id"].astype(str)
    out["yyyymm"] = _as_int64_nullable(out["yyyymm"])

    for col in contract.qc_columns:
        out[col] = out[col].astype("boolean")

    out = out.loc[
        (out["yyyymm"] >= contract.window_start_yyyymm)
        & (out["yyyymm"] <= contract.window_end_yyyymm)
    ].copy()
    _assert_merge_safe(out, label=f"panel_monthly_qc[{sensor},clipped]")
    return out.reset_index(drop=True)


def _coverage_window(cfg: AppConfig, *, sensor_mode: str) -> tuple[object, object]:
    """Return the broader structural coverage window recorded in the QC provenance."""
    coverage = getattr(cfg.processing, "sensor_coverage", None)
    if not coverage or sensor_mode not in coverage:
        return pd.NA, pd.NA
    tr = coverage.get(sensor_mode)
    start = getattr(tr, "start_yyyymm", None)
    end = getattr(tr, "end_yyyymm", None)
    return (int(start) if start is not None else pd.NA, int(end) if end is not None else pd.NA)


def _add_year_provenance(ext_df: pd.DataFrame, *, contract: SensorExportContract) -> pd.DataFrame:
    """Append additive year-level provenance counts derived from clipped `_ext` rows."""
    sensor = contract.sensor_mode
    out = ext_df.copy()

    def _count_true(series: pd.Series) -> int:
        return int(series.astype("boolean").fillna(False).astype("int64").sum())

    year_meta = (
        out.groupby(["level", "unit_id", "year"], dropna=False, sort=False)
        .agg(
            year_rows_in_panel=("yyyymm", "size"),
            year_rows_in_sensor_coverage=(f"{sensor}_in_coverage_flag", _count_true),
            year_rows_structural_missing=(f"{sensor}_structural_missing_flag", _count_true),
        )
        .reset_index()
    )
    for col in [
        "year_rows_in_panel",
        "year_rows_in_sensor_coverage",
        "year_rows_structural_missing",
    ]:
        year_meta[col] = pd.to_numeric(year_meta[col], errors="raise").astype("Int64")
    year_meta["year_coverage_complete_flag"] = (
        year_meta["year_rows_in_panel"] == year_meta["year_rows_in_sensor_coverage"]
    ).astype("boolean")
    out = out.merge(year_meta, on=["level", "unit_id", "year"], how="left", validate="many_to_one")
    return out


def _build_base_export_frame(
    *,
    panel_ext_df: pd.DataFrame,
    identity_meta_df: pd.DataFrame,
    contract: SensorExportContract,
) -> pd.DataFrame:
    """Merge clipped monthly analytics with canonical Stage 1 identity metadata."""
    panel_ext = _prepare_panel_ext_source(panel_ext_df, contract=contract)
    out = panel_ext.merge(
        identity_meta_df, on=["level", "unit_id"], how="left", validate="many_to_one"
    )

    missing_identity = (
        out[["unit_name", "partition_level", "partition_key", "partition_value"]].isna().any(axis=1)
    )
    if bool(missing_identity.any()):
        bad = out.loc[missing_identity, ["level", "unit_id"]].drop_duplicates().to_dict("records")
        raise AFExportsError(f"Missing Stage 1 identity/partition metadata after merge: {bad}")

    out.insert(1, "schema_version", contract.schema_version)
    out = out.loc[:, contract.base_columns + _PARTITION_META_COLUMNS].copy()
    _assert_merge_safe(out, label=f"rp1_af_base[{contract.sensor_mode}]")
    return out.reset_index(drop=True)


def _build_ext_export_frame(
    *,
    base_df: pd.DataFrame,
    qc_df: pd.DataFrame,
    cfg: AppConfig,
    contract: SensorExportContract,
) -> pd.DataFrame:
    """Merge base exports with sensor-specific QC/provenance add-ons."""
    sensor = contract.sensor_mode
    qc_norm = _prepare_qc_source(qc_df, contract=contract)
    out = base_df.merge(qc_norm, on=RP1_AF_MERGE_KEYS, how="left", validate="one_to_one")

    missing_qc = out.loc[:, contract.qc_columns].isna().all(axis=1)
    if bool(missing_qc.any()):
        bad = out.loc[missing_qc, ["level", "unit_id", "yyyymm"]].head(5).to_dict("records")
        raise AFExportsError(
            f"QC merge produced all-null {sensor.upper()} QC fields for one or more rows, e.g. {bad}"
        )

    cov_start, cov_end = _coverage_window(cfg, sensor_mode=sensor)
    out["sensor_coverage_start_yyyymm"] = cov_start
    out["sensor_coverage_end_yyyymm"] = cov_end
    out = _add_year_provenance(out, contract=contract)
    out = out.loc[:, contract.ext_columns + _PARTITION_META_COLUMNS].copy()
    _assert_merge_safe(out, label=f"rp1_af_ext[{sensor}]")
    return out.reset_index(drop=True)


def _schema_has_expected_columns(
    schema: Mapping[str, object], expected_columns: Sequence[str]
) -> bool:
    """Return True when the configured JSON schema matches the deterministic export order."""
    props = schema.get("properties")
    if isinstance(props, dict):
        return list(props.keys()) == list(expected_columns)
    return False


def _shared_schema_alias_path(*, family: str) -> str:
    """Return the current shared RP1 schema-alias filename."""
    if family == "base":
        return "configs/schemas/rp1_af_monthly_base.schema.json"
    return "configs/schemas/rp1_af_monthly_ext.schema.json"


def _schema_candidates(
    *,
    cfg: AppConfig,
    contract: SensorExportContract,
    family: str,
) -> list[str]:
    """Return preferred then fallback schema paths for one export family.

    Preferred path
    --------------
    Sensor-specific schema paths are configured under
    ``outputs.rp1_exports.sensors.<sensor>.schemas``.

    Shared-schema resolution
    ------------------------
    The current public configuration API exposes shared RP1 schema aliases named:

    - ``configs/schemas/rp1_af_monthly_base.schema.json``
    - ``configs/schemas/rp1_af_monthly_ext.schema.json``

    Minimal source fixtures may provide those shared aliases. Because the current
    config intentionally aliases ``outputs.schemas.rp1_af_monthly_*`` to the
    VIIRS-specific paths, the shared-schema resolution path must append the conventional
    shared filenames explicitly rather than relying on the aliased config keys.
    """
    export_kind = "base" if family == "base" else "ext"
    preferred = cfg.outputs.rp1_schema_path(
        sensor_mode=contract.sensor_mode, export_kind=export_kind
    )

    out: list[str] = []
    for rel in [preferred, _shared_schema_alias_path(family=family)]:
        rel_norm = str(rel).strip()
        if rel_norm and rel_norm not in out:
            out.append(rel_norm)
    return out


def _resolve_existing_schema_path(
    *,
    repo_root: Path,
    schema_candidates: Sequence[str],
) -> tuple[str, Path]:
    """Resolve the first schema path that actually exists on disk."""
    checked: list[str] = []
    for rel in schema_candidates:
        rel_norm = str(rel).strip()
        if not rel_norm:
            continue
        path = (repo_root / rel_norm).resolve()
        checked.append(path.as_posix())
        if path.exists():
            return rel_norm, path

    if checked:
        raise FileNotFoundError(
            "No RP1 AF export schema file found. Checked: " + ", ".join(checked)
        )
    raise FileNotFoundError("No RP1 AF export schema path candidates were configured.")


def _validate_export_schema(
    *,
    df: pd.DataFrame,
    family: str,
    contract: SensorExportContract,
    cfg: AppConfig,
    repo_root: Path,
) -> pd.DataFrame:
    """Validate a sensor-specific export frame against its configured schema.

    This validator prefers the sensor-specific schema path for the requested
    sensor and falls back to the conventional shared RP1 schema filename when
    that is the only schema staged in a temporary repository fixture.
    """
    _schema_rel, schema_path = _resolve_existing_schema_path(
        repo_root=repo_root,
        schema_candidates=_schema_candidates(cfg=cfg, contract=contract, family=family),
    )
    schema_obj = load_json_schema(schema_path)

    expected_cols = contract.base_columns if family == "base" else contract.ext_columns

    # If the located schema file does not declare exactly the
    # expected deterministic column order, keep enforcing the in-code order and
    # do not let a transitional schema file silently reorder columns.
    if not _schema_has_expected_columns(schema_obj, expected_cols):
        return df.loc[:, expected_cols].copy()

    return validate_dataframe_against_schema(
        df=df,
        schema=schema_obj,
        expected_columns=expected_cols,
        allow_reorder=True,
    )


def write_rp1_af_exports(
    *,
    panel_ext_df: pd.DataFrame,
    unit_universe_df: pd.DataFrame,
    qc_df: pd.DataFrame,
    cfg: AppConfig,
    repo_root: Path,
    run_dir: Path,
    fmt: str,
    sort_keys: Sequence[str],
    validate_schema: bool,
) -> AFExportsResult:
    """Write the merger-ready RP1 AF base and ``_ext`` export families.

    The function operates on already-prepared monthly artefacts rather than raw
    detections. It uses an explicit sensor-aware contract map derived from
    configuration so VIIRS and MODIS can be written from the same combine-stage
    artefacts without changing any upstream scientific logic.
    """
    repo_root = Path(repo_root)
    identity_meta = _build_identity_and_partition_metadata(unit_universe_df)

    manifest: dict[str, object] = {
        "family_name": cfg.outputs.rp1_exports.family_name,
        "format": fmt,
        "source": ["panel_monthly_ext", "panel_monthly_qc", "unit_universe"],
        "merge_keys": list(RP1_AF_MERGE_KEYS),
        "families": ["base", "ext"],
        "schema_version": RP1_AF_SCHEMA_VERSION,
        "sensor_modes": {},
    }
    written: list[Path] = []

    # Use the supported sensor order rather than dict iteration order so write
    # order is deterministic even if config file ordering changes in future.
    for sensor_mode in SUPPORTED_RP1_EXPORT_SENSOR_MODES:
        contract = _sensor_contract(cfg, sensor_mode=sensor_mode)

        base_df = _build_base_export_frame(
            panel_ext_df=panel_ext_df,
            identity_meta_df=identity_meta,
            contract=contract,
        )
        ext_df = _build_ext_export_frame(
            base_df=base_df,
            qc_df=qc_df,
            cfg=cfg,
            contract=contract,
        )

        base_for_write = base_df.loc[:, contract.base_columns].copy()
        ext_for_write = ext_df.loc[:, contract.ext_columns].copy()
        if validate_schema:
            base_for_write = _validate_export_schema(
                df=base_for_write,
                family="base",
                contract=contract,
                cfg=cfg,
                repo_root=repo_root,
            )
            ext_for_write = _validate_export_schema(
                df=ext_for_write,
                family="ext",
                contract=contract,
                cfg=cfg,
                repo_root=repo_root,
            )

        sensor_manifest: dict[str, object] = {
            "partition_basis": "top_level_ancestor",
            "window": {
                "start_yyyymm": contract.window_start_yyyymm,
                "end_yyyymm": contract.window_end_yyyymm,
            },
            "schemas": {
                "base": cfg.outputs.rp1_schema_path(
                    sensor_mode=contract.sensor_mode, export_kind="base"
                ),
                "ext": cfg.outputs.rp1_schema_path(
                    sensor_mode=contract.sensor_mode, export_kind="ext"
                ),
            },
            "levels": {},
        }

        levels = sorted(base_df["level"].astype(str).unique().tolist())
        for level in levels:
            base_level = base_df.loc[base_df["level"].astype(str) == level].copy()
            ext_level = ext_df.loc[ext_df["level"].astype(str) == level].copy()
            base_write_level = base_for_write.loc[
                base_for_write["level"].astype(str) == level
            ].copy()
            ext_write_level = ext_for_write.loc[ext_for_write["level"].astype(str) == level].copy()

            base_partitions: dict[str, object] = {}
            ext_partitions: dict[str, object] = {}

            partition_rows = (
                base_level.loc[
                    :, ["partition_key", "partition_value", "partition_level", "partition_label"]
                ]
                .drop_duplicates()
                .sort_values(["partition_key", "partition_value"], kind="stable")
            )

            for part in partition_rows.to_dict("records"):
                partition_key = str(part["partition_key"])
                partition_value = str(part["partition_value"])
                partition_level = str(part["partition_level"])
                partition_label = str(part["partition_label"])

                base_mask = (base_level["partition_key"].astype(str) == partition_key) & (
                    base_level["partition_value"].astype(str) == partition_value
                )
                ext_mask = (ext_level["partition_key"].astype(str) == partition_key) & (
                    ext_level["partition_value"].astype(str) == partition_value
                )

                base_part = base_write_level.loc[base_mask.to_numpy(), contract.base_columns].copy()
                ext_part = ext_write_level.loc[ext_mask.to_numpy(), contract.ext_columns].copy()

                base_path = rp1_af_export_path(
                    run_dir=run_dir,
                    level=level,
                    sensor_mode=contract.sensor_mode,
                    partition_key=partition_key,
                    partition_value=partition_value,
                    fmt=fmt,
                    family="base",
                )
                write_dataframe_csv(
                    df=base_part,
                    path=base_path,
                    sort_keys=[k for k in sort_keys if k in base_part.columns]
                    or list(RP1_AF_MERGE_KEYS),
                    column_order=contract.base_columns,
                )
                written.append(base_path)
                base_partitions[partition_label] = {
                    "partition_key": partition_key,
                    "partition_value": partition_value,
                    "partition_level": partition_level,
                    "path": base_path.relative_to(repo_root).as_posix(),
                    "sha256": sha256_file(base_path),
                    "n_rows": int(len(base_part)),
                }

                ext_path = rp1_af_export_path(
                    run_dir=run_dir,
                    level=level,
                    sensor_mode=contract.sensor_mode,
                    partition_key=partition_key,
                    partition_value=partition_value,
                    fmt=fmt,
                    family="ext",
                )
                write_dataframe_csv(
                    df=ext_part,
                    path=ext_path,
                    sort_keys=[k for k in sort_keys if k in ext_part.columns]
                    or list(RP1_AF_MERGE_KEYS),
                    column_order=contract.ext_columns,
                )
                written.append(ext_path)
                ext_partitions[partition_label] = {
                    "partition_key": partition_key,
                    "partition_value": partition_value,
                    "partition_level": partition_level,
                    "path": ext_path.relative_to(repo_root).as_posix(),
                    "sha256": sha256_file(ext_path),
                    "n_rows": int(len(ext_part)),
                }

            sensor_manifest["levels"][level] = {
                "base_partitions": base_partitions,
                "ext_partitions": ext_partitions,
            }

        manifest["sensor_modes"][contract.sensor_mode] = sensor_manifest

    return AFExportsResult(manifest=manifest, paths=written)
