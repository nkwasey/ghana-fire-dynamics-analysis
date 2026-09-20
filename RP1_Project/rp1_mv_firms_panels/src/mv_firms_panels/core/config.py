# file: src/mv_firms_panels/core/config.py
"""Configuration loading and strict validation.

This module provides:
- YAML loading (safe) and strict schema validation using Pydantic.
- A single validated `AppConfig` object used across the pipeline.
- Optional existence checks for referenced files (disabled by default so tests do not require shapefiles).

Design goals (binding)
----------------------
- Deterministic: config -> canonical dict representation is stable (sorted JSON for hashing).
- Strict: unknown keys are rejected (extra='forbid').
- Explicit scientific assumptions: confidence mapping, dedup keys, FRP aggregation settings.

Output-format helpers
---------------------
Stages that write/read monthly panels use `outputs.write_formats.monthly_panels` as a
preference order (e.g. ["csv.gz","csv"]). This module provides small helper
functions to validate and interpret those tokens.

Important: these helpers are *used by stages*; the config loader itself remains permissive
so that future formats can be introduced without breaking YAML parsing. Unsupported
formats are rejected when a stage attempts to use them.

Optional QA export configuration
--------------------------------
`prepare_year` can optionally export QA artefacts (cleaned/dedup points; optional outside-land points and plots)
under `outputs.prepare_year_qa_exports`. These exports are OFF by default and must not affect contracted
`fires_canonical` outputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SensorName = Literal["viirs", "modis"]

# Predicates used in different parts of the pipeline.
SpatialPredicate = Literal["intersects", "within", "contains"]
LandMaskPredicate = Literal["intersects", "within"]

# Supported RP1 export sensor modes and locked sensor-specific export windows.
#
# These windows define the formal merger-ready RP1 export contract. They are
# intentionally kept separate from the broader processing/sensor coverage ranges,
# because the pipeline may process a wider span than the analysis-ready RP1
# export family is allowed to emit.
SUPPORTED_RP1_EXPORT_SENSOR_MODES: tuple[str, ...] = ("viirs", "modis")
LOCKED_RP1_EXPORT_WINDOWS: dict[str, tuple[int, int]] = {
    "viirs": (201201, 202412),
    "modis": (200101, 202412),
}
DATA_ACCESS_DOC_REL = "docs/data_access.md"
ROOT_RUNBOOK_REL = "README.md"


# -----------------------------------------------------------------------------
# Helpers for output format preference lists
# -----------------------------------------------------------------------------

SUPPORTED_MONTHLY_PANEL_FORMATS: tuple[str, ...] = ("csv.gz", "csv")


def _normalise_format_token(token: str) -> str:
    return str(token).strip().lower()


def _dedupe_preserve_order(items: Sequence[str]) -> list[str]:
    out: list[str] = []
    for x in items:
        x = str(x)
        if x not in out:
            out.append(x)
    return out


def choose_preferred_format(
    preference_order: Sequence[str],
    *,
    supported: Sequence[str] = SUPPORTED_MONTHLY_PANEL_FORMATS,
    context: str = "outputs.write_formats.monthly_panels",
) -> str:
    """Return the first preferred supported format, raising on unsupported tokens."""
    toks = [_normalise_format_token(t) for t in preference_order]
    toks = [t for t in toks if t]
    toks = _dedupe_preserve_order(toks)
    if not toks:
        raise ValueError(
            f"{context} must contain at least one format; supported: {list(supported)}"
        )
    bad = [t for t in toks if t not in supported]
    if bad:
        raise ValueError(f"Unsupported format(s) in {context}: {bad}. Supported: {list(supported)}")
    return toks[0]


def candidate_format_order(
    preference_order: Sequence[str],
    *,
    supported: Sequence[str] = SUPPORTED_MONTHLY_PANEL_FORMATS,
    context: str = "outputs.write_formats.monthly_panels",
) -> list[str]:
    """Return preference order followed by remaining supported formats."""
    toks = [_normalise_format_token(t) for t in preference_order]
    toks = [t for t in toks if t]
    toks = _dedupe_preserve_order(toks)
    if not toks:
        toks = list(supported)
    bad = [t for t in toks if t not in supported]
    if bad:
        raise ValueError(f"Unsupported format(s) in {context}: {bad}. Supported: {list(supported)}")
    tail = [t for t in supported if t not in toks]
    return toks + tail


# -----------------------------------------------------------------------------
# Pydantic config models
# -----------------------------------------------------------------------------


class RunIdStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["config_hash8"] = "config_hash8"
    timestamp_utc: bool = True


class ProjectSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = "0.0.0"
    run_id_strategy: RunIdStrategy


class FirmsSensorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_glob: str
    # canonical -> source column name mapping
    column_map: dict[str, str] = Field(default_factory=dict)


class PolygonLevel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str
    path: str
    unit_id_field: str
    unit_name_field: str
    boundary_vintage_field: str | None = None


class IOInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_universe_csv: str
    land_mask: str | None = None
    polygons: list[PolygonLevel]
    firms_points: dict[SensorName, FirmsSensorInput]


class IOSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: IOInputs


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_yyyymm: int | None = None
    end_yyyymm: int | None = None
    timezone: Literal["UTC"] = "UTC"

    @field_validator("start_yyyymm", "end_yyyymm")
    @classmethod
    def _yyyymm_format(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 190001 or v > 220012:
            raise ValueError("yyyymm outside expected range (190001..220012)")
        mm = v % 100
        if mm < 1 or mm > 12:
            raise ValueError("yyyymm month must be 01..12")
        return v


class ConfidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Mapping from raw confidence label (case-insensitive) to conf_cat {l,n,h}.
    viirs_map: dict[str, Literal["l", "n", "h"]]
    # MODIS confidence thresholds in percent (0..100), with explicit keys.
    modis_thresholds_pct: dict[str, int]
    include_low: bool = True

    @model_validator(mode="after")
    def _validate_modis_thresholds(self) -> ConfidenceModel:
        low_lt = self.modis_thresholds_pct.get("low_lt")
        high_ge = self.modis_thresholds_pct.get("high_ge")
        if low_lt is None or high_ge is None:
            raise ValueError("modis_thresholds_pct must include keys low_lt and high_ge")
        if not (0 <= low_lt <= 100 and 0 <= high_ge <= 100):
            raise ValueError("modis thresholds must be within 0..100")
        if low_lt >= high_ge:
            raise ValueError("modis thresholds require low_lt < high_ge")
        return self


class Deduplication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latlon_round_decimals: int = 6
    include_satellite_in_key: bool = True
    tie_break: list[str] = Field(
        default_factory=lambda: ["max_frp_mw", "max_conf_cat_rank", "stable_first"]
    )


class LandMaskPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # When True, `prepare_year` applies land masking if `io.inputs.land_mask` is provided
    # (or if a land_mask_gdf is passed explicitly in tests).
    enabled_if_path_provided: bool = True

    # Spatial predicate for land masking (see mv_firms_panels.geo.masks).
    spatial_predicate: LandMaskPredicate = "intersects"

    # If True, points outside the land mask are dropped from fires_canonical.
    # If False, points are retained but outside-land counts are still recorded for QA.
    require_land_intersection: bool = True

    outside_land_warn_threshold_fraction: float = 0.0001
    outside_land_warn_threshold_abs_km2: float = 0.0


class FrpPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_frp_mw: float = 0.0
    daily_stat: Literal["max"] = "max"
    monthly_mean_denominator: Literal["frp_active_days"] = "frp_active_days"


class ProcessingSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensors_enabled: list[SensorName] = Field(default_factory=lambda: ["viirs", "modis"])
    time_range: TimeRange

    # Sensor-specific windows
    #
    # These are optional and do not modify the existing `time_range` behaviour. Stages
    # may use them to drive per-sensor processing windows and to encode sensor coverage
    # for structural missingness (e.g., VIIRS months before 201201).
    sensor_time_ranges: dict[SensorName, TimeRange] | None = None
    sensor_coverage: dict[SensorName, TimeRange] | None = None

    confidence_model: ConfidenceModel
    deduplication: Deduplication
    land_mask_policy: LandMaskPolicy
    frp_policy: FrpPolicy

    @field_validator("sensors_enabled")
    @classmethod
    def _dedupe_sensors(cls, v: list[SensorName]) -> list[SensorName]:
        out: list[SensorName] = []
        for s in v:
            if s not in out:
                out.append(s)
        if not out:
            raise ValueError(
                "sensors_enabled must include at least one sensor (viirs and/or modis)"
            )
        return out

    @field_validator("sensor_time_ranges", "sensor_coverage", mode="before")
    @classmethod
    def _validate_sensor_range_keys(cls, v: object, info) -> object:  # type: ignore[no-untyped-def]
        """Fail fast with clear errors for unsupported sensor keys.

        Pydantic will also validate keys via the Literal["viirs","modis"] type, but
        the default error can be hard to interpret. We pre-validate the raw mapping
        to provide a targeted message.
        """
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError(f"processing.{info.field_name} must be a mapping of sensor->TimeRange")
        allowed = {"viirs", "modis"}
        bad = [k for k in v.keys() if str(k) not in allowed]
        if bad:
            raise ValueError(
                f"Invalid sensor key(s) in processing.{info.field_name}: {bad}. Allowed: ['viirs', 'modis']"
            )
        return v

    @model_validator(mode="after")
    def _validate_sensor_ranges(self) -> ProcessingSection:
        """Validate optional sensor-specific ranges without changing time_range semantics."""

        def _require_bounded(tr: TimeRange, *, ctx: str) -> None:
            if tr.start_yyyymm is None or tr.end_yyyymm is None:
                raise ValueError(f"{ctx} requires both start_yyyymm and end_yyyymm")
            if tr.start_yyyymm > tr.end_yyyymm:
                raise ValueError(f"{ctx} requires start_yyyymm <= end_yyyymm")

        def _require_start(tr: TimeRange, *, ctx: str) -> None:
            if tr.start_yyyymm is None:
                if tr.end_yyyymm is None:
                    raise ValueError(f"{ctx} requires start_yyyymm")
                raise ValueError(f"{ctx} requires start_yyyymm when end_yyyymm is set")
            if tr.end_yyyymm is not None and tr.start_yyyymm > tr.end_yyyymm:
                raise ValueError(f"{ctx} requires start_yyyymm <= end_yyyymm")

        if self.sensor_time_ranges:
            for s, tr in self.sensor_time_ranges.items():
                _require_bounded(tr, ctx=f"processing.sensor_time_ranges.{s}")

        if self.sensor_coverage:
            for s, tr in self.sensor_coverage.items():
                _require_start(tr, ctx=f"processing.sensor_coverage.{s}")

        return self


class PrepareYearQAExports(BaseModel):
    """Optional prepare_year QA exports (off by default).

    Intent
    ------
    Provide additional diagnostics without affecting contracted fires_canonical outputs.

    Notes
    -----
    - These exports are best-effort: if the geopandas/GDAL stack cannot write the requested
      formats, the stage continues and records the failure in QA summary/manifest.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False

    # When enabled, write cleaned/dedup points as GeoPackage (unless disabled explicitly).
    write_geopackage: bool = True

    # Optionally also write a Shapefile (multi-file; written next to the .shp).
    also_write_shapefile: bool = False

    # If land-masking is active, optionally also export outside-land points.
    export_outside_land_points: bool = False

    # Optional outside-land plot exports.
    plot_outside_land_points_png: bool = False
    plot_outside_land_points_pdf: bool = False

    # Hard cap for plotted points (deterministic downsample when exceeded).
    plot_max_points: int = 50_000

    @field_validator("plot_max_points")
    @classmethod
    def _plot_max_points_positive(cls, v: int) -> int:
        if int(v) <= 0:
            raise ValueError("plot_max_points must be positive")
        return int(v)


class RP1ExportSchemaPaths(BaseModel):
    """Schema paths for one sensor-specific RP1 export contract."""

    model_config = ConfigDict(extra="forbid")

    base: str
    ext: str

    @field_validator("base", "ext")
    @classmethod
    def _non_empty_schema_path(cls, v: str) -> str:
        v = str(v).strip()
        if not v:
            raise ValueError("RP1 export schema paths must be non-empty strings")
        return v


class RP1ExportSensorContract(BaseModel):
    """Formal RP1 export contract for a single supported sensor."""

    model_config = ConfigDict(extra="forbid")

    window: TimeRange
    schemas: RP1ExportSchemaPaths


class RP1ExportsSection(BaseModel):
    """Explicit merger-ready RP1 export contract configuration.

    Purpose
    -------
    Make the RP1 export family fully explicit in configuration rather than
    relying on exporter-internal constants. This section defines:
    - the fixed export family name,
    - the supported sensor modes,
    - the locked sensor-specific RP1 export windows, and
    - the sensor-specific base/_ext schema paths.

    Notes
    -----
    - Sensor identity remains in folder paths and manifests, not in CSV bodies.
    - Both supported sensors must be declared here even if a particular run only
      enables one of them upstream.
    """

    model_config = ConfigDict(extra="forbid")

    family_name: Literal["rp1_af_exports"] = "rp1_af_exports"
    sensors: dict[SensorName, RP1ExportSensorContract]

    @field_validator("sensors", mode="before")
    @classmethod
    def _validate_sensor_keys(cls, v: object) -> object:
        if not isinstance(v, dict):
            raise ValueError("outputs.rp1_exports.sensors must be a mapping of sensor->contract")
        bad = [str(k) for k in v.keys() if str(k) not in SUPPORTED_RP1_EXPORT_SENSOR_MODES]
        if bad:
            raise ValueError(
                "Invalid sensor key(s) in outputs.rp1_exports.sensors: "
                f"{bad}. Allowed: {list(SUPPORTED_RP1_EXPORT_SENSOR_MODES)}"
            )
        return v

    @model_validator(mode="after")
    def _validate_sensor_contracts(self) -> RP1ExportsSection:
        missing = [s for s in SUPPORTED_RP1_EXPORT_SENSOR_MODES if s not in self.sensors]
        if missing:
            raise ValueError(
                "outputs.rp1_exports.sensors must define contracts for all supported sensors: "
                f"missing {missing}"
            )

        for sensor_mode, expected_window in LOCKED_RP1_EXPORT_WINDOWS.items():
            contract = self.sensors[sensor_mode]
            tr = contract.window
            if tr.start_yyyymm is None or tr.end_yyyymm is None:
                raise ValueError(
                    f"outputs.rp1_exports.sensors.{sensor_mode}.window requires both "
                    "start_yyyymm and end_yyyymm"
                )
            if tr.start_yyyymm > tr.end_yyyymm:
                raise ValueError(
                    f"outputs.rp1_exports.sensors.{sensor_mode}.window requires "
                    "start_yyyymm <= end_yyyymm"
                )
            actual_window = (tr.start_yyyymm, tr.end_yyyymm)
            if actual_window != expected_window:
                raise ValueError(
                    f"outputs.rp1_exports.sensors.{sensor_mode}.window must equal the locked "
                    f"RP1 export window {expected_window[0]}..{expected_window[1]} "
                    f"(got {tr.start_yyyymm}..{tr.end_yyyymm})"
                )
        return self


class OutputsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_dir: str = "out/runs"
    write_formats: dict[str, list[str]]
    schemas: dict[str, str]
    rp1_exports: RP1ExportsSection

    # When true, also write per-level panel_monthly_<level>.* subsets.
    split_panels_by_level: bool = False

    # When true, also write additive range-tagged combined panel artefacts.
    write_range_tagged_panels: bool = False

    # Optional prepare_year QA exports (off by default).
    prepare_year_qa_exports: PrepareYearQAExports = Field(default_factory=PrepareYearQAExports)

    @model_validator(mode="after")
    def _validate_schema_contracts(self) -> OutputsSection:
        required_schema_keys = {
            "fires_canonical",
            "panel_monthly",
            "rp1_af_monthly_base",
            "rp1_af_monthly_ext",
        }
        missing = sorted(required_schema_keys.difference(self.schemas.keys()))
        if missing:
            raise ValueError(f"outputs.schemas is missing required key(s): {missing}")

        viirs_contract = self.rp1_exports.sensors["viirs"]
        if self.schemas["rp1_af_monthly_base"] != viirs_contract.schemas.base:
            raise ValueError(
                "outputs.schemas.rp1_af_monthly_base must match "
                "outputs.rp1_exports.sensors.viirs.schemas.base during the transition "
                "to dual-sensor RP1 export execution"
            )
        if self.schemas["rp1_af_monthly_ext"] != viirs_contract.schemas.ext:
            raise ValueError(
                "outputs.schemas.rp1_af_monthly_ext must match "
                "outputs.rp1_exports.sensors.viirs.schemas.ext during the transition "
                "to dual-sensor RP1 export execution"
            )
        return self

    def rp1_schema_path(
        self, *, sensor_mode: SensorName, export_kind: Literal["base", "ext"]
    ) -> str:
        """Return the configured RP1 schema path for a specific sensor/kind pair."""
        contract = self.rp1_exports.sensors[sensor_mode]
        return contract.schemas.base if export_kind == "base" else contract.schemas.ext


class DeterminismSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stable_sort_before_write: bool = True
    fixed_column_order_enforced: bool = True
    sort_keys: dict[str, list[str]]
    column_order: dict[str, list[str]]


class MissingnessSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counts_zero_when_no_detections: bool = True
    frp_sum_zero_when_no_detections: bool = True
    frp_mean_null_when_no_active_days: bool = True


class QCPerSensor(BaseModel):
    """QC thresholds for a specific sensor.

    Notes
    -----
    These thresholds are used *only* for the optional panel_monthly QC sidecar
    They do not modify the contracted panel_monthly schema.
    """

    model_config = ConfigDict(extra="forbid")

    # Flag months with fewer than this many detections as "low information".
    # Detections are computed as det_low + det_nominal + det_high for the sensor.
    low_information_min_detections: int = 5

    # FRP "OK" requires at least this many active days in the month.
    frp_ok_min_active_days: int = 1

    # FRP "OK" also requires the FRP sum over daily maxima to be at least this value.
    # Keep this at 0.0 to treat any positive number of active days as "OK" provided the
    # FRP mean is consistent with sum/active_days.
    frp_ok_min_sum_daily_max_mw: float = 0.0

    @field_validator("low_information_min_detections", "frp_ok_min_active_days")
    @classmethod
    def _non_negative_int(cls, v: int) -> int:
        v = int(v)
        if v < 0:
            raise ValueError("QC thresholds must be non-negative")
        return v

    @field_validator("frp_ok_min_sum_daily_max_mw")
    @classmethod
    def _non_negative_float(cls, v: float) -> float:
        v = float(v)
        if v < 0:
            raise ValueError("QC thresholds must be non-negative")
        return v


def _default_qc_sensors() -> dict[SensorName, QCPerSensor]:
    return {"viirs": QCPerSensor(), "modis": QCPerSensor()}


class QCSection(BaseModel):
    """Optional QC settings for sidecar outputs.

    Intent
    ------
    Provide opt-in QC flags in a separate artefact to avoid bloating the
    contracted panel_monthly table.

    When enabled, combine_panels writes:
      out/runs/<run_id>/panel_monthly/panel_monthly_qc.<fmt>
    where <fmt> is the selected monthly panel format (csv.gz or csv).
    """

    model_config = ConfigDict(extra="forbid")

    write_panel_monthly_qc_sidecar: bool = False

    # Per-sensor thresholds used to compute flags in the QC sidecar.
    sensors: dict[SensorName, QCPerSensor] = Field(default_factory=_default_qc_sensors)


class AppConfig(BaseModel):
    """Top-level validated configuration."""

    model_config = ConfigDict(extra="forbid")

    project: ProjectSection
    io: IOSection
    processing: ProcessingSection
    outputs: OutputsSection
    determinism: DeterminismSection
    missingness_semantics: MissingnessSemantics

    qc: QCSection = Field(default_factory=QCSection)

    def to_canonical_dict(self) -> dict[str, Any]:
        """Return a stable, JSON-serialisable dict (no Path objects)."""
        return self.model_dump(mode="json", by_alias=False, exclude_none=False)


@dataclass(frozen=True)
class LoadedConfig:
    """A validated config with provenance."""

    config: AppConfig
    config_path: Path


def _repo_relative_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()


def _stage2_missing_input_message(*, label: str, path: Path, repo_root: Path) -> str:
    repo_rel = _repo_relative_path(path, repo_root=repo_root)
    return (
        f"Missing required Stage 2 input `{label}`: {repo_rel}. "
        f"See {DATA_ACCESS_DOC_REL} and {ROOT_RUNBOOK_REL} for acquisition and local staging instructions. "
        "Required by stage: rp1_mv_firms_panels (Stage 2)."
    )


def _load_yaml(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        obj = yaml.safe_load(f)
    if not isinstance(obj, dict):
        raise ValueError("Top-level YAML must be a mapping/object")
    return obj


def _validate_paths(cfg: AppConfig, *, repo_root: Path) -> None:
    """Optional validation: fail fast if referenced files do not exist.

    Note: tests call load_config(..., validate_paths=False), so this is opt-in.
    """
    uu = repo_root / cfg.io.inputs.unit_universe_csv
    if not uu.exists():
        raise FileNotFoundError(
            _stage2_missing_input_message(
                label="unit_universe_csv",
                path=uu,
                repo_root=repo_root,
            )
        )

    if cfg.io.inputs.land_mask:
        lm = repo_root / cfg.io.inputs.land_mask
        if not lm.exists():
            raise FileNotFoundError(
                _stage2_missing_input_message(
                    label="land_mask",
                    path=lm,
                    repo_root=repo_root,
                )
            )

    for poly in cfg.io.inputs.polygons:
        p = repo_root / poly.path
        if not p.exists():
            raise FileNotFoundError(
                _stage2_missing_input_message(
                    label=f"polygon:{poly.level}",
                    path=p,
                    repo_root=repo_root,
                )
            )

    schema_paths = set(cfg.outputs.schemas.values())
    for sensor_mode in SUPPORTED_RP1_EXPORT_SENSOR_MODES:
        contract = cfg.outputs.rp1_exports.sensors[sensor_mode]
        schema_paths.add(contract.schemas.base)
        schema_paths.add(contract.schemas.ext)

    for rel_path in sorted(schema_paths):
        schema_path = repo_root / rel_path
        if not schema_path.exists():
            raise FileNotFoundError(f"schema file not found: {schema_path}")


def load_config(
    path: Path, *, validate_paths: bool = True, repo_root: Path | None = None
) -> LoadedConfig:
    """Load YAML config and return validated `AppConfig`."""
    path = Path(path)
    if repo_root is None:
        repo_root = path.resolve().parents[1]

    raw = _load_yaml(path)

    try:
        cfg = AppConfig.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"Config validation error for {path}: {e}") from e

    if validate_paths:
        _validate_paths(cfg, repo_root=Path(repo_root))

    return LoadedConfig(config=cfg, config_path=path)
