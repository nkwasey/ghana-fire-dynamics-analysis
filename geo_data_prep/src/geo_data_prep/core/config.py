"""Config schema, loader, and validation.

This module defines the Stage 1 runtime configuration contract, including
contract metadata, QA thresholds, reported-area policy and fail-fast validation
for paths, thresholds and CRS-like strings.

Configuration defaults
----------------------
- Optional policy fields have explicit deterministic defaults in the current schema.
- ``crs.working_crs`` remains the binding runtime field consumed by the current
  pipeline.
- Optional sections are additive and defaulted conservatively.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic.types import StrictBool, StrictFloat, StrictInt, StrictStr


class ConfigError(RuntimeError):
    """Raised when a YAML config cannot be parsed or validated."""


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _find_repo_root(start: Path) -> Path:
    """Best-effort geo_data_prep project root discovery."""

    start = start.resolve()
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd().resolve()


def _is_relative_path_str(p: str) -> bool:
    # Reject obvious absolute paths across platforms.
    if p.startswith(("~", "/", "\\\\")):  # ~, POSIX absolute, UNC paths
        return False
    # Windows drive letters, e.g. C:\...
    if len(p) >= 2 and p[1] == ":":
        return False
    return not Path(p).is_absolute()


def _require_relative_path(p: str, *, field_name: str) -> str:
    if not p or not isinstance(p, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    if not _is_relative_path_str(p):
        raise ValueError(f"{field_name} must be a relative path (relative to repo root)")
    return p


def _non_empty_str(v: str, *, field_name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return v.strip()


def _validate_crs_like(v: str, *, field_name: str) -> str:
    v = _non_empty_str(v, field_name=field_name)
    try:
        from pyproj import CRS  # type: ignore

        CRS.from_user_input(v)
    except Exception:
        # Keep validation robust even in minimal environments where pyproj is
        # absent or partially unavailable. We still require a non-empty string.
        pass
    return v


def _positive_sorted_float_list(values: list[float], *, field_name: str) -> list[float]:
    if not values:
        raise ValueError(f"{field_name} must contain at least one value")
    clean = sorted({float(v) for v in values})
    if any(v <= 0 for v in clean):
        raise ValueError(f"{field_name} values must all be > 0")
    return clean


def _format_validation_error(err: ValidationError) -> str:
    lines: list[str] = []
    for e in err.errors():
        loc = ".".join(str(x) for x in e.get("loc", []))
        msg = e.get("msg", "Invalid value")
        typ = e.get("type", "validation_error")
        if loc:
            lines.append(f"- {loc}: {msg} ({typ})")
        else:
            lines.append(f"- {msg} ({typ})")
    return "\n".join(lines) if lines else "- <unknown>: validation_error"


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# ---------------------------------------------------------------------------
# Input / output / derivation schema
# ---------------------------------------------------------------------------


class InputLayerConfig(_StrictBaseModel):
    path: StrictStr = Field(
        ..., min_length=1, description="Relative path to input layer (e.g., Shapefile)."
    )
    label_field: StrictStr = Field(
        ..., min_length=1, description="Field name used as the source label."
    )

    @field_validator("path")
    @classmethod
    def _v_path_relative(cls, v: str) -> str:
        return _require_relative_path(v, field_name="inputs.<layer>.path")

    @field_validator("label_field")
    @classmethod
    def _v_label_field_nonempty(cls, v: str) -> str:
        return _non_empty_str(v, field_name="inputs.<layer>.label_field")


class AOIConfig(_StrictBaseModel):
    enabled: StrictBool = Field(False, description="Whether to apply an AOI clip/mask.")
    path: StrictStr | None = Field(
        None, description="Relative path to AOI layer. Required when enabled=true."
    )

    @model_validator(mode="after")
    def _v_enabled_requires_path(self) -> AOIConfig:
        if self.enabled:
            if self.path is None or str(self.path).strip() == "":
                raise ValueError("inputs.aoi.path is required when inputs.aoi.enabled=true")
            _require_relative_path(str(self.path), field_name="inputs.aoi.path")
        return self


class InputsConfig(_StrictBaseModel):
    zones: InputLayerConfig
    districts: InputLayerConfig
    aoi: AOIConfig | None = None


class LevelConfig(_StrictBaseModel):
    level: StrictStr = Field(
        ..., min_length=1, description="Short level name used in outputs (e.g., acz)."
    )

    @field_validator("level")
    @classmethod
    def _v_level_nonempty(cls, v: str) -> str:
        return _non_empty_str(v, field_name="levels.<level>.level")


class LevelsConfig(_StrictBaseModel):
    zone: LevelConfig
    district: LevelConfig


class CRSConfig(_StrictBaseModel):
    working_crs: StrictStr = Field(
        ..., min_length=1, description="Projected working/overlay CRS for spatial operations."
    )
    plot_crs: StrictStr = Field(..., min_length=1, description="CRS for plotting / display.")

    @field_validator("working_crs")
    @classmethod
    def _v_working_crs(cls, v: str) -> str:
        return _validate_crs_like(v, field_name="crs.working_crs")

    @field_validator("plot_crs")
    @classmethod
    def _v_plot_crs(cls, v: str) -> str:
        return _validate_crs_like(v, field_name="crs.plot_crs")

    @property
    def overlay_crs(self) -> str:
        """Alias for callers that use overlay terminology.

        The runtime binds spatial operations to ``working_crs``.
        """

        return self.working_crs


class OutputToggles(_StrictBaseModel):
    splits: StrictBool = Field(False, description="Whether to split outputs by level subfolders.")
    plots: StrictBool = Field(False, description="Whether to export QA/plot artefacts.")


class OutputBasenames(_StrictBaseModel):
    zones: StrictStr = Field(..., min_length=1, description="Basename for zones output layer.")
    districts: StrictStr = Field(
        ..., min_length=1, description="Basename for districts output layer."
    )

    @field_validator("zones")
    @classmethod
    def _v_zones_basename(cls, v: str) -> str:
        return _non_empty_str(v, field_name="outputs.basenames.zones")

    @field_validator("districts")
    @classmethod
    def _v_districts_basename(cls, v: str) -> str:
        return _non_empty_str(v, field_name="outputs.basenames.districts")


class OutputsConfig(_StrictBaseModel):
    out_dir: StrictStr = Field(..., min_length=1, description="Relative output root directory.")
    toggles: OutputToggles
    basenames: OutputBasenames

    @field_validator("out_dir")
    @classmethod
    def _v_outdir_relative(cls, v: str) -> str:
        return _require_relative_path(v, field_name="outputs.out_dir")


class ZoneCodeFallback(_StrictBaseModel):
    method: StrictStr = Field(
        "initials", min_length=1, description="Fallback method for zone_code when mapping missing."
    )
    collision: StrictStr = Field(
        "suffix", min_length=1, description="Collision handling strategy for derived zone_code."
    )

    @field_validator("method")
    @classmethod
    def _v_method(cls, v: str) -> str:
        v = _non_empty_str(v, field_name="derivations.zone_code.fallback.method")
        allowed = {"initials"}
        if v not in allowed:
            raise ValueError(
                f"derivations.zone_code.fallback.method must be one of {sorted(allowed)}"
            )
        return v

    @field_validator("collision")
    @classmethod
    def _v_collision(cls, v: str) -> str:
        v = _non_empty_str(v, field_name="derivations.zone_code.fallback.collision")
        allowed = {"suffix"}
        if v not in allowed:
            raise ValueError(
                f"derivations.zone_code.fallback.collision must be one of {sorted(allowed)}"
            )
        return v


class ZoneCodeDerivation(_StrictBaseModel):
    mapping: dict[StrictStr, StrictStr] = Field(
        default_factory=dict, description="Mapping-first zone_code overrides: label -> code."
    )
    fallback: ZoneCodeFallback

    @field_validator("mapping")
    @classmethod
    def _v_mapping_nonempty_keys_values(cls, v: dict[str, str]) -> dict[str, str]:
        clean: dict[str, str] = {}
        for k, val in v.items():
            kk = _non_empty_str(str(k), field_name="derivations.zone_code.mapping.<key>")
            vv = _non_empty_str(str(val), field_name=f"derivations.zone_code.mapping.{kk}")
            clean[kk] = vv
        return clean


class DerivationsConfig(_StrictBaseModel):
    zone_code: ZoneCodeDerivation


# ---------------------------------------------------------------------------
# Area policy / contract / QA thresholds
# ---------------------------------------------------------------------------


class AreaPolicyConfig(_StrictBaseModel):
    method: StrictStr = Field(
        "projected",
        description=(
            "Reported area methodology. 'projected' reports areas in a projected CRS; "
            "'geodesic' reports geodesic areas; 'both' denotes a comparison policy for "
            "parallel projected/geodesic diagnostics."
        ),
    )
    projected_crs: StrictStr | None = Field(
        None,
        description=(
            "Projected CRS used for reported area calculations when method is 'projected' or 'both'. "
            "Defaults to crs.working_crs under the current configuration contract."
        ),
    )
    geodesic_ellipsoid: StrictStr = Field(
        "WGS84", description="Reference ellipsoid for geodesic area calculations."
    )
    units: StrictStr = Field("sq_km", description="Reported area units.")
    include_method_metadata: StrictBool = Field(
        True,
        description="Whether outputs should include explicit area-method metadata.",
    )

    @field_validator("method")
    @classmethod
    def _v_method(cls, v: str) -> str:
        v = _non_empty_str(v, field_name="area_policy.method")
        allowed = {"projected", "geodesic", "both"}
        if v not in allowed:
            raise ValueError(f"area_policy.method must be one of {sorted(allowed)}")
        return v

    @field_validator("projected_crs")
    @classmethod
    def _v_projected_crs(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_crs_like(v, field_name="area_policy.projected_crs")

    @field_validator("geodesic_ellipsoid")
    @classmethod
    def _v_geodesic_ellipsoid(cls, v: str) -> str:
        return _non_empty_str(v, field_name="area_policy.geodesic_ellipsoid")

    @field_validator("units")
    @classmethod
    def _v_units(cls, v: str) -> str:
        v = _non_empty_str(v, field_name="area_policy.units")
        allowed = {"sq_km", "sq_m"}
        if v not in allowed:
            raise ValueError(f"area_policy.units must be one of {sorted(allowed)}")
        return v


class ContractConfig(_StrictBaseModel):
    stage: StrictStr = Field("stage_1", description="Pipeline stage identifier.")
    name: StrictStr = Field("geo_data_prep_stage1", description="Canonical Stage 1 contract name.")
    version: StrictStr | None = Field(
        None,
        description=(
            "Stage 1 upstream contract version. Defaults to schema_version when omitted so "
            "the established configuration surface remains valid."
        ),
    )
    canonical_upstream: StrictBool = Field(
        True,
        description="Whether Stage 1 is treated as the canonical upstream contract.",
    )
    downstreams_adapt_later: StrictBool = Field(
        True,
        description="Whether downstream consumers are expected to adapt later rather than forcing retrofits here.",
    )

    @field_validator("stage")
    @classmethod
    def _v_stage(cls, v: str) -> str:
        return _non_empty_str(v, field_name="contract.stage")

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return _non_empty_str(v, field_name="contract.name")

    @field_validator("version")
    @classmethod
    def _v_version(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _non_empty_str(v, field_name="contract.version")


class LowerBoundThreshold(_StrictBaseModel):
    warn_below: StrictFloat = Field(..., description="Warn when value falls below this threshold.")
    fail_below: StrictFloat = Field(..., description="Fail when value falls below this threshold.")

    @model_validator(mode="after")
    def _v_bounds(self) -> LowerBoundThreshold:
        if self.warn_below < 0 or self.warn_below > 1:
            raise ValueError("warn_below must lie in [0, 1]")
        if self.fail_below < 0 or self.fail_below > 1:
            raise ValueError("fail_below must lie in [0, 1]")
        if self.fail_below > self.warn_below:
            raise ValueError("fail_below must be <= warn_below")
        return self


class UpperBoundThreshold(_StrictBaseModel):
    warn_above: StrictFloat = Field(..., description="Warn when value rises above this threshold.")
    fail_above: StrictFloat = Field(..., description="Fail when value rises above this threshold.")

    @model_validator(mode="after")
    def _v_bounds(self) -> UpperBoundThreshold:
        if self.warn_above < 0:
            raise ValueError("warn_above must be >= 0")
        if self.fail_above < 0:
            raise ValueError("fail_above must be >= 0")
        if self.fail_above < self.warn_above:
            raise ValueError("fail_above must be >= warn_above")
        return self


class CountUpperBoundThreshold(_StrictBaseModel):
    warn_above: StrictInt = Field(..., description="Warn when a count rises above this threshold.")
    fail_above: StrictInt = Field(..., description="Fail when a count rises above this threshold.")

    @model_validator(mode="after")
    def _v_bounds(self) -> CountUpperBoundThreshold:
        if self.warn_above < 0:
            raise ValueError("warn_above must be >= 0")
        if self.fail_above < 0:
            raise ValueError("fail_above must be >= 0")
        if self.fail_above < self.warn_above:
            raise ValueError("fail_above must be >= warn_above")
        return self


class QAThresholdsConfig(_StrictBaseModel):
    overlap_share: LowerBoundThreshold = Field(
        default_factory=lambda: LowerBoundThreshold(warn_below=0.95, fail_below=0.80),
        description="Thresholds for district-to-zone overlap share diagnostics.",
    )
    area_relative_difference: UpperBoundThreshold = Field(
        default_factory=lambda: UpperBoundThreshold(warn_above=0.01, fail_above=0.05),
        description="Thresholds for relative differences between alternative area calculations.",
    )
    unassigned_units: CountUpperBoundThreshold = Field(
        default_factory=lambda: CountUpperBoundThreshold(warn_above=0, fail_above=0),
        description="Thresholds for units that fail assignment.",
    )
    legacy_assignment_disagreement: CountUpperBoundThreshold = Field(
        default_factory=lambda: CountUpperBoundThreshold(warn_above=0, fail_above=0),
        description="Thresholds for disagreement between legacy and recomputed district assignments.",
    )
    invalid_geometries: CountUpperBoundThreshold = Field(
        default_factory=lambda: CountUpperBoundThreshold(warn_above=0, fail_above=0),
        description="Thresholds for invalid geometries detected during QA.",
    )


class SliverDiagnosticsConfig(_StrictBaseModel):
    enabled: StrictBool = Field(
        True,
        description="Whether to emit descriptive diagnostics for very small overlap candidates.",
    )
    share_cutoffs: list[StrictFloat] = Field(
        default_factory=lambda: [1e-6, 1e-4, 1e-3, 1e-2],
        description="Positive overlap-share cutoffs used to summarise very small candidate overlaps.",
    )
    area_sqkm_cutoffs: list[StrictFloat] = Field(
        default_factory=lambda: [0.001, 0.01, 0.1, 1.0],
        description="Positive overlap-area cutoffs in square kilometres used to summarise small candidate overlaps.",
    )
    example_limit: StrictInt = Field(
        10,
        description="Maximum number of example sliver rows to record in the sidecar output.",
    )

    @field_validator("share_cutoffs")
    @classmethod
    def _v_share_cutoffs(cls, values: list[float]) -> list[float]:
        return _positive_sorted_float_list(values, field_name="qa.sliver_diagnostics.share_cutoffs")

    @field_validator("area_sqkm_cutoffs")
    @classmethod
    def _v_area_sqkm_cutoffs(cls, values: list[float]) -> list[float]:
        return _positive_sorted_float_list(
            values, field_name="qa.sliver_diagnostics.area_sqkm_cutoffs"
        )

    @field_validator("example_limit")
    @classmethod
    def _v_example_limit(cls, value: int) -> int:
        if int(value) <= 0:
            raise ValueError("qa.sliver_diagnostics.example_limit must be > 0")
        return int(value)


class CRSSensitivityConfig(_StrictBaseModel):
    enabled: StrictBool = Field(
        True,
        description="Whether to rerun assignment under an alternative equal-area CRS for sensitivity review.",
    )
    example_limit: StrictInt = Field(
        10,
        description="Maximum number of changed-district examples to record in the sensitivity sidecar output.",
    )

    @field_validator("example_limit")
    @classmethod
    def _v_example_limit(cls, value: int) -> int:
        if int(value) <= 0:
            raise ValueError("qa.crs_sensitivity.example_limit must be > 0")
        return int(value)


class QAConfig(_StrictBaseModel):
    enabled: StrictBool = Field(
        True, description="Whether QA metrics/threshold evaluation is enabled."
    )
    thresholds: QAThresholdsConfig = Field(default_factory=QAThresholdsConfig)
    sliver_diagnostics: SliverDiagnosticsConfig = Field(default_factory=SliverDiagnosticsConfig)
    crs_sensitivity: CRSSensitivityConfig = Field(default_factory=CRSSensitivityConfig)


# ---------------------------------------------------------------------------
# Top-level app config
# ---------------------------------------------------------------------------


class AppConfig(_StrictBaseModel):
    schema_version: StrictStr = Field(
        ..., min_length=1, description="Config schema version (e.g., 1.0)."
    )
    inputs: InputsConfig
    levels: LevelsConfig
    crs: CRSConfig
    outputs: OutputsConfig
    derivations: DerivationsConfig
    area_policy: AreaPolicyConfig = Field(default_factory=AreaPolicyConfig)
    qa: QAConfig = Field(default_factory=QAConfig)
    contract: ContractConfig = Field(default_factory=ContractConfig)

    @field_validator("schema_version")
    @classmethod
    def _v_schema_version(cls, v: str) -> str:
        return _non_empty_str(v, field_name="schema_version")

    @model_validator(mode="after")
    def _v_cross_section_defaults(self) -> AppConfig:
        # Current area-policy default: reported projected area uses
        # the same projected working/overlay CRS unless a distinct projected CRS is configured.
        if self.area_policy.projected_crs is None and self.area_policy.method in {
            "projected",
            "both",
        }:
            self.area_policy = self.area_policy.model_copy(
                update={"projected_crs": self.crs.working_crs}
            )

        # Contract default: if omitted, tie the contract version to the config schema version.
        if self.contract.version is None:
            self.contract = self.contract.model_copy(update={"version": self.schema_version})

        return self

    @property
    def contract_version(self) -> str:
        return str(self.contract.version)

    @property
    def effective_area_projected_crs(self) -> str | None:
        return self.area_policy.projected_crs


@dataclass(frozen=True)
class ResolvedPaths:
    repo_root: Path
    config_path: Path
    zones_path: Path
    districts_path: Path
    aoi_path: Path | None
    out_dir: Path


def resolve_paths(
    cfg: AppConfig, *, config_path: Path, repo_root: Path | None = None
) -> ResolvedPaths:
    rr = repo_root or _find_repo_root(config_path.parent)
    zones_p = (rr / cfg.inputs.zones.path).resolve()
    dists_p = (rr / cfg.inputs.districts.path).resolve()
    aoi_p = None
    if cfg.inputs.aoi is not None and cfg.inputs.aoi.enabled:
        aoi_p = (rr / str(cfg.inputs.aoi.path)).resolve()
    out_p = (rr / cfg.outputs.out_dir).resolve()
    return ResolvedPaths(
        repo_root=rr,
        config_path=config_path.resolve(),
        zones_path=zones_p,
        districts_path=dists_p,
        aoi_path=aoi_p,
        out_dir=out_p,
    )


def load_config(path: Path) -> AppConfig:
    """Load a YAML config and validate it against the strict schema.

    Notes
    -----
    - The YAML must be a mapping (top-level dict).
    - Unknown keys are forbidden at all levels (no guessing).
    - Paths in the config must be relative to repo root.
    - The runtime binds spatial operations to ``crs.working_crs``; area and QA
      policy sections are additive configuration surfaces.
    """

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:  # YAML parsing errors vary by version
        raise ConfigError(f"Config parse failed for {path}: {e}") from e

    if raw is None:
        raise ConfigError(f"Config is empty: {path}")
    if not isinstance(raw, dict):
        raise ConfigError(f"Config must be a YAML mapping (dict) at top level: {path}")

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(
            f"Config validation failed for {path}:\n" + _format_validation_error(e)
        ) from e
