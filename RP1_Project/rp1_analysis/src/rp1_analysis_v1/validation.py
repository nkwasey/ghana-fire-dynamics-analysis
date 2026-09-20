"""Fail-closed, data-schema-driven input validation and population authority."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Never

import geopandas as gpd
import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype, is_string_dtype

from .contracts import AnalysisContract, DataFieldSpec, DataSchemaContract
from .data_io import DataAuthorities
from .variables import ensure_declared_fields, resolve_field_role


class DataContractError(ValueError):
    """Raised when a governed input violates the analytical data contract."""


@dataclass(frozen=True, slots=True)
class AnalyticalMask:
    name: str
    units: pd.DataFrame

    @property
    def retained_units(self) -> int:
        return int(self.units["eligible"].sum())

    @property
    def candidate_units(self) -> int:
        return int(len(self.units))

    @property
    def excluded_units(self) -> int:
        return self.candidate_units - self.retained_units


@dataclass(frozen=True, slots=True)
class DataContractSummary:
    acz_count: int
    acz_monthly_rows: int
    district_spatial_universe_count: int
    district_monthly_rows: int
    long_run_eligible_count: int
    long_run_rows: int
    paired_eligible_count: int
    paired_rows: int
    rq3_gee_units: int
    rq3_gee_rows: int
    long_run_start: str
    long_run_end: str
    overlap_start: str
    overlap_end: str
    complete_year_start: int
    complete_year_end: int
    reconciliation_absolute_tolerance: float
    reconciliation_relative_tolerance: float
    reconciliation: pd.DataFrame
    population_authority: pd.DataFrame
    long_run_mask: AnalyticalMask
    paired_mask: AnalyticalMask
    spatial_universe_mask: AnalyticalMask


def _raise(message: str) -> Never:
    raise DataContractError(message)


def _default_schema() -> DataSchemaContract:
    from .config import load_configuration_bundle
    from .paths import ProjectPaths

    paths = ProjectPaths.discover()
    return load_configuration_bundle(paths.root / "config").data_schema


def _schema(value: DataSchemaContract | None) -> DataSchemaContract:
    return value or _default_schema()


def _require_columns(frame: pd.DataFrame, required: Iterable[str], context: str) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        _raise(f"Missing required columns in {context}: {missing!r}")


def _month_range(start: str, end: str) -> np.ndarray:
    periods = pd.period_range(start, end, freq="M")
    return np.asarray([p.year * 100 + p.month for p in periods], dtype=np.int64)


def _yyyymm(value: str) -> int:
    try:
        period = pd.Period(str(value), freq="M")
    except Exception as exc:
        raise DataContractError(f"Invalid monthly support boundary: {value!r}") from exc
    return period.year * 100 + period.month


def _window_yyyymm(window: Any) -> tuple[int, int]:
    try:
        return _yyyymm(str(window["start"])), _yyyymm(str(window["end"]))
    except Exception as exc:
        raise DataContractError(f"Invalid configured monthly window: {window!r}") from exc


def _support_mask(frame: pd.DataFrame, schema: DataSchemaContract, support_id: str) -> pd.Series:
    try:
        support = schema.source_supports[support_id]
    except KeyError as exc:
        raise DataContractError(f"Unknown structural support: {support_id!r}") from exc
    start = _yyyymm(str(support["start"]))
    end = _yyyymm(str(support["end"]))
    return frame["yyyymm"].astype(int).between(start, end)


def _check_exact_schema(frame: pd.DataFrame, manifest: dict[str, Any], context: str, schema: DataSchemaContract) -> None:
    manifest_schema = manifest.get("final_schema_columns")
    if not isinstance(manifest_schema, list) or not all(isinstance(x, str) for x in manifest_schema):
        _raise("Manifest final_schema_columns is missing or invalid")
    expected = list(schema.field_order)
    if manifest_schema != expected:
        _raise("Manifest final_schema_columns disagrees with data_schema_contract.yml")
    if list(frame.columns) != expected:
        missing = sorted(set(expected).difference(frame.columns))
        extra = sorted(set(frame.columns).difference(expected))
        _raise(f"{context} does not match data-schema order; missing={missing!r}, extra={extra!r}")


def _check_dtypes(frame: pd.DataFrame, context: str, schema: DataSchemaContract) -> None:
    wrong: list[str] = []
    for field in schema.fields:
        series = frame[field.name]
        if field.dtype == "string":
            if not is_string_dtype(series.dtype):
                wrong.append(f"{field.name}:expected-string-observed-{series.dtype}")
        elif field.dtype in {"integer", "number"}:
            if not is_numeric_dtype(series.dtype):
                wrong.append(f"{field.name}:expected-{field.dtype}-observed-{series.dtype}")
                continue
            if field.dtype == "integer":
                values = series.dropna().to_numpy(dtype=float)
                if not np.all(np.equal(values, np.floor(values))):
                    wrong.append(f"{field.name}:non-integral-values")
        else:
            wrong.append(f"{field.name}:unsupported-schema-dtype-{field.dtype}")
    if wrong:
        _raise(f"Dtype violations in {context}: {wrong!r}")


def _check_finite_numeric(frame: pd.DataFrame, context: str) -> None:
    bad: list[str] = []
    for col in frame.columns:
        if is_numeric_dtype(frame[col].dtype):
            values = frame[col].to_numpy(dtype=float, na_value=np.nan)
            if np.isinf(values).any():
                bad.append(col)
    if bad:
        _raise(f"Infinite numeric values in {context}: {bad!r}")


def _check_domains_ranges_and_nulls(frame: pd.DataFrame, context: str, schema: DataSchemaContract) -> None:
    for field in schema.fields:
        series = frame[field.name]
        if not field.nullable and series.isna().any():
            _raise(f"{context}.{field.name} contains nulls but nullable=false")
        if field.categorical_domain is not None:
            allowed = set(schema.categorical_domains[field.categorical_domain])
            observed = set(series.dropna().tolist())
            invalid = observed.difference(allowed)
            if invalid:
                _raise(f"{context}.{field.name} contains values outside categorical domain {field.categorical_domain}: {sorted(invalid, key=repr)!r}")
        if field.minimum is not None or field.maximum is not None:
            if not is_numeric_dtype(series.dtype):
                _raise(f"{context}.{field.name} has numeric range constraints but is not numeric")
            values = series.dropna().astype(float)
            if field.minimum is not None and (values < float(field.minimum)).any():
                _raise(f"{context}.{field.name} contains values below minimum {field.minimum}")
            if field.maximum is not None and (values > float(field.maximum)).any():
                _raise(f"{context}.{field.name} contains values above maximum {field.maximum}")


def _check_keys_and_time(frame: pd.DataFrame, panel_id: str, schema: DataSchemaContract) -> None:
    panel = schema.panel(panel_id)
    key = list(panel.primary_key)
    if frame[key].isna().any().any():
        _raise(f"{panel_id} contains missing key values")
    if frame.duplicated(key, keep=False).any():
        dup = int(frame.duplicated(key, keep=False).sum())
        _raise(f"{panel_id} contains {dup} duplicate primary-key rows")
    if set(frame["level"].dropna().astype(str).unique()) != {panel.level_value}:
        _raise(f"{panel_id} contains inconsistent level values")
    if set(frame["schema_version"].dropna().astype(str).unique()) != {schema.panel_schema_version}:
        _raise(f"{panel_id} panel schema_version is not {schema.panel_schema_version}")

    yyyymm = frame["yyyymm"].to_numpy(dtype=np.int64)
    months = yyyymm % 100
    years = yyyymm // 100
    if np.any((months < 1) | (months > 12)):
        _raise(f"{panel_id} contains invalid yyyymm month values")
    if not np.array_equal(years, frame["year"].to_numpy(dtype=np.int64)):
        _raise(f"{panel_id} year disagrees with yyyymm")
    if not np.array_equal(months, frame["month"].to_numpy(dtype=np.int64)):
        _raise(f"{panel_id} month disagrees with yyyymm")

    expected = _month_range(panel.start, panel.end)
    start, end = int(expected[0]), int(expected[-1])
    if int(frame["yyyymm"].min()) != start or int(frame["yyyymm"].max()) != end:
        _raise(f"{panel_id} temporal range does not match the data-schema authority")
    for unit_id, group in frame.groupby("unit_id", sort=False, observed=True):
        observed = group["yyyymm"].to_numpy(dtype=np.int64)
        if not np.all(observed[1:] > observed[:-1]):
            _raise(f"{panel_id} time is not strictly ordered for unit {unit_id!r}")
        if not np.array_equal(observed, expected):
            _raise(f"{panel_id} has an incomplete monthly spine for unit {unit_id!r}")


def _check_dimensions(frame: pd.DataFrame, panel_id: str, merge_summary: dict[str, Any], schema: DataSchemaContract) -> None:
    panel = schema.panel(panel_id)
    level = panel.level_value
    actual = {
        "row_count": len(frame), "column_count": len(frame.columns),
        "unique_units": int(frame["unit_id"].nunique()),
        "yyyymm_min": int(frame["yyyymm"].min()), "yyyymm_max": int(frame["yyyymm"].max()),
    }
    expected_contract = {
        "row_count": panel.expected_rows, "column_count": panel.column_count,
        "unique_units": panel.expected_units, "yyyymm_min": _yyyymm(panel.start), "yyyymm_max": _yyyymm(panel.end),
    }
    for key, value in actual.items():
        if value != expected_contract[key]:
            _raise(f"{panel_id} {key}={value!r} conflicts with data schema {expected_contract[key]!r}")
    summary = merge_summary.get(level)
    if not isinstance(summary, dict):
        _raise(f"Merge summary is missing {level!r} dimensions")
    for key, value in actual.items():
        if summary.get(key) != value:
            _raise(f"{panel_id} {key}={value!r} conflicts with merge summary {summary.get(key)!r}")


def _check_support_definitions(frame: pd.DataFrame, context: str, schema: DataSchemaContract) -> None:
    for support_id, support in schema.source_supports.items():
        expected = _support_mask(frame, schema, support_id).astype(int).to_numpy()
        support_flag = support.get("support_flag")
        if isinstance(support_flag, str):
            if not np.array_equal(frame[support_flag].to_numpy(dtype=int), expected):
                _raise(f"{context}.{support_flag} conflicts with structural support {support_id}")
        source_presence = support.get("source_presence_flag")
        if isinstance(source_presence, str):
            if not np.array_equal(frame[source_presence].to_numpy(dtype=int), expected):
                _raise(f"{context}.{source_presence} conflicts with structural support {support_id}")
        structural_flag = support.get("structural_missing_flag")
        if isinstance(structural_flag, str):
            if not np.array_equal(frame[structural_flag].to_numpy(dtype=int), 1 - expected):
                _raise(f"{context}.{structural_flag} does not complement structural support {support_id}")

    # When both product-specific supports exist, the combined support must be their conjunction.
    if all(c in frame for c in ("full_overlap_supported_flag", "ba2012_supported_flag", "viirs_supported_flag")):
        combined = (frame["ba2012_supported_flag"].astype(int) & frame["viirs_supported_flag"].astype(int)).to_numpy(dtype=int)
        if not np.array_equal(frame["full_overlap_supported_flag"].to_numpy(dtype=int), combined):
            _raise(f"{context}.full_overlap_supported_flag is inconsistent with component supports")

    for field in schema.fields:
        support = _support_mask(frame, schema, field.structural_support)
        if field.required_when_supported and frame.loc[support, field.name].isna().any():
            _raise(f"{context}.{field.name} is missing despite governed source support")
        if field.structural_support != "canonical_spine" and frame.loc[~support, field.name].notna().any():
            _raise(f"{context}.{field.name} is populated outside governed source support")


def _check_validation_rules(frame: pd.DataFrame, context: str, schema: DataSchemaContract) -> None:
    denominators = schema.validation_rules.get("denominators", ())
    for rule in denominators:
        denominator = str(rule["denominator"]); zero_flag = str(rule["zero_flag"])
        support = _support_mask(frame, schema, str(rule["support"]))
        den = frame.loc[support, denominator]
        flag = frame.loc[support, zero_flag]
        if den.isna().any() or flag.isna().any():
            _raise(f"{context}: supported denominator/flag is missing for {denominator}")
        if (den < 0).any():
            _raise(f"{context}: negative denominator in {denominator}")
        expected_flag = den.eq(0).astype(int)
        if not np.array_equal(flag.astype(int).to_numpy(), expected_flag.to_numpy()):
            _raise(f"{context}: {zero_flag} does not match zero state of {denominator}")
        zero = support & frame[denominator].eq(0)
        positive = support & frame[denominator].gt(0)
        for derived in rule["derived_fields"]:
            if frame.loc[zero, derived].notna().any():
                _raise(f"{context}: {derived} must be missing when {denominator} is zero")
            if frame.loc[positive, derived].isna().any():
                _raise(f"{context}: {derived} is missing despite positive {denominator}")

    for rule in schema.validation_rules.get("temporal_consistency", ()):
        field = str(rule["field"]); scope = str(rule["scope"])
        support = _support_mask(frame, schema, str(rule["support"]))
        subset = frame.loc[support]
        if scope == "unit_constant":
            counts = subset.groupby("unit_id", observed=True)[field].nunique(dropna=True)
            if (counts > 1).any():
                bad = counts[counts > 1].index.astype(str).tolist()[:10]
                _raise(f"{context}: fixed field {field} varies within units {bad!r}")
        elif scope == "unit_year_constant":
            counts = subset.groupby(["unit_id", "year"], observed=True)[field].nunique(dropna=True)
            if (counts > 1).any():
                _raise(f"{context}: annual field {field} varies within a unit-year")
        else:
            _raise(f"Unknown temporal consistency scope: {scope!r}")


def _check_identity_consistency(frame: pd.DataFrame, panel_id: str, schema: DataSchemaContract) -> None:
    panel = schema.panel(panel_id)
    if panel_id == "acz_monthly":
        fields = ["unit_name", "unit_code"]
    else:
        fields = ["unit_name", "parent_level", "parent_id", "parent_code", "parent_name"]
    for column in fields:
        counts = frame.groupby("unit_id", observed=True)[column].nunique(dropna=False)
        if (counts > 1).any():
            bad = counts[counts > 1].index.astype(str).tolist()[:10]
            _raise(f"{panel_id} has inconsistent {column} for units {bad!r}")

    if panel_id == "acz_monthly":
        identities = schema.geometry("acz").unit_identities
        if identities is not None:
            observed = {
                str(unit_id): {"unit_code": str(code), "unit_name": str(name)}
                for unit_id, code, name in frame[["unit_id", "unit_code", "unit_name"]].drop_duplicates().itertuples(index=False, name=None)
            }
            expected = {str(k): dict(v) for k, v in identities.items()}
            if observed != expected:
                _raise(f"ACZ identities differ from data-schema authority: {observed!r}")


def validate_manifest(manifest: dict[str, Any], data_schema: DataSchemaContract | None = None) -> None:
    schema = _schema(data_schema)
    if manifest.get("merge_schema_version") != schema.panel_schema_version:
        _raise("Manifest merge_schema_version is unsupported by data schema")
    if manifest.get("final_schema_columns") != list(schema.field_order):
        _raise("Manifest final_schema_columns disagree with data schema")
    families = manifest.get("families")
    if not isinstance(families, list):
        _raise("Manifest families is missing or invalid")
    observed: dict[tuple[str, str], tuple[int, int]] = {}
    for item in families:
        if not isinstance(item, dict):
            _raise("Manifest family entry is invalid")
        source = item.get("source_kind"); level = item.get("level")
        start = item.get("support_start_yyyymm"); end = item.get("support_end_yyyymm")
        if not isinstance(source, str) or level not in {"acz", "district"} or not isinstance(start, int) or not isinstance(end, int):
            _raise("Manifest source family identity/support is invalid")
        observed[(source, str(level))] = (start, end)
    expected: dict[tuple[str, str], tuple[int, int]] = {}
    for support in schema.source_supports.values():
        source = support.get("manifest_source_kind")
        if isinstance(source, str):
            window = (_yyyymm(str(support["start"])), _yyyymm(str(support["end"])))
            for level in ("acz", "district"):
                expected[(source, level)] = window
    if observed != expected:
        _raise(f"Manifest source-family support does not match data-schema authority: {observed!r}")


def validate_key_audit(key_audit: pd.DataFrame, merge_summary: dict[str, Any], data_schema: DataSchemaContract | None = None) -> None:
    schema = _schema(data_schema)
    required = {"level", "expected_rows", "actual_rows", "unique_keys", "duplicate_key_rows", "column_count", "yyyymm_min", "yyyymm_max", "passes_key_audit"}
    _require_columns(key_audit, required, "key audit")
    expected_levels = {p.level_value for p in schema.panels.values()}
    if set(key_audit["level"].astype(str)) != expected_levels:
        _raise(f"Key audit levels are not exactly {sorted(expected_levels)!r}")
    panel_by_level = {p.level_value: p for p in schema.panels.values()}
    for row in key_audit.to_dict(orient="records"):
        level = str(row["level"]); panel = panel_by_level[level]; summary = merge_summary.get(level, {})
        if not bool(row["passes_key_audit"]): _raise(f"Key audit is not passing for {level}")
        if int(row["duplicate_key_rows"]) != 0: _raise(f"Key audit records duplicate keys for {level}")
        expected = {"actual_rows": panel.expected_rows, "expected_rows": panel.expected_rows, "unique_keys": panel.expected_rows,
                    "column_count": panel.column_count, "yyyymm_min": _yyyymm(panel.start), "yyyymm_max": _yyyymm(panel.end)}
        for key, value in expected.items():
            if int(row[key]) != int(value): _raise(f"Key audit {key} conflicts with data schema for {level}")
        for audit_key, summary_key in (("actual_rows","row_count"),("column_count","column_count"),("yyyymm_min","yyyymm_min"),("yyyymm_max","yyyymm_max")):
            if int(row[audit_key]) != int(summary.get(summary_key, -1)):
                _raise(f"Key audit {audit_key} conflicts with merge summary for {level}")


def validate_panel(frame: pd.DataFrame, *, level: str, manifest: dict[str, Any], merge_summary: dict[str, Any], analysis: AnalysisContract | None = None, data_schema: DataSchemaContract | None = None) -> None:
    del analysis  # physical validation belongs to data_schema_contract.yml
    schema = _schema(data_schema)
    panel_id = "acz_monthly" if level == "acz" else "district_monthly" if level == "district" else None
    if panel_id is None: _raise(f"Unsupported panel level: {level!r}")
    context = f"{level} panel"
    _check_exact_schema(frame, manifest, context, schema)
    _check_dtypes(frame, context, schema)
    _check_finite_numeric(frame, context)
    _check_domains_ranges_and_nulls(frame, context, schema)
    _check_keys_and_time(frame, panel_id, schema)
    _check_dimensions(frame, panel_id, merge_summary, schema)
    _check_identity_consistency(frame, panel_id, schema)
    _check_support_definitions(frame, context, schema)
    _check_validation_rules(frame, context, schema)


def validate_geometry(geometry: gpd.GeoDataFrame, *, level: str, data_schema: DataSchemaContract | None = None) -> None:
    schema = _schema(data_schema)
    geometry_id = "acz" if level == "acz" else "district" if level == "district" else None
    if geometry_id is None: _raise(f"Unsupported geometry level: {level!r}")
    spec = schema.geometry(geometry_id)
    _require_columns(geometry, spec.required_columns, f"{level} geometry")
    if len(geometry) != spec.expected_features:
        _raise(f"{level} geometry has {len(geometry)} features, expected {spec.expected_features}")
    key = spec.identifier_field
    if geometry[key].isna().any() or geometry[key].duplicated().any():
        _raise(f"{level} geometry key {key} is missing or non-unique")
    if geometry.crs is None or geometry.crs.to_epsg() != spec.crs_epsg:
        _raise(f"{level} geometry CRS must resolve to EPSG:{spec.crs_epsg}; got {geometry.crs}")
    if geometry.geometry.isna().any() or geometry.geometry.is_empty.any():
        _raise(f"{level} geometry contains null or empty geometries")
    if not bool(geometry.geometry.is_valid.all()): _raise(f"{level} geometry contains invalid geometries")
    if not geometry.geom_type.isin(list(spec.geometry_types)).all():
        _raise(f"{level} geometry contains geometry types outside {spec.geometry_types!r}")
    if spec.unit_identities is not None:
        observed = {
            str(row[spec.identifier_field]): {"unit_code": str(row["zone_code"]), "unit_name": str(row["zone_name"])}
            for _, row in geometry.iterrows()
        }
        expected = {str(k): dict(v) for k, v in spec.unit_identities.items()}
        if observed != expected: _raise("ACZ geometry identities do not match data-schema authority")


def validate_geometry_panel_reconciliation(acz_panel: pd.DataFrame, district_panel: pd.DataFrame, acz_geometry: gpd.GeoDataFrame, district_geometry: gpd.GeoDataFrame, data_schema: DataSchemaContract | None = None) -> None:
    schema = _schema(data_schema)
    objects: dict[str, pd.DataFrame] = {
        "acz_monthly": acz_panel.drop_duplicates("unit_id"),
        "district_monthly": district_panel.drop_duplicates("unit_id"),
        "acz_geometry": acz_geometry,
        "district_geometry": district_geometry,
    }
    # Configured many-to-one / one-to-one relationships are validation authority.
    for rel in schema.relationships:
        source = objects[rel.from_object]; target = objects[rel.to_object]
        _require_columns(source, [rel.from_field], rel.from_object); _require_columns(target, [rel.to_field], rel.to_object)
        source_values = set(source[rel.from_field].dropna().astype(str)); target_values = set(target[rel.to_field].dropna().astype(str))
        missing = source_values.difference(target_values)
        if missing: _raise(f"Relationship {rel.relationship_id} has orphan values: {sorted(missing)!r}")
        if rel.cardinality == "one_to_one" and target[rel.to_field].dropna().duplicated().any():
            _raise(f"Relationship {rel.relationship_id} requires unique target keys")

    for geometry_id, panel_id, frame in (("acz","acz_monthly",acz_panel),("district","district_monthly",district_panel)):
        spec = schema.geometry(geometry_id); identity_map = spec.panel_identity_map
        if identity_map is None: continue
        panel_identity = frame[list(identity_map)].drop_duplicates().rename(columns=dict(identity_map))
        geometry = objects[f"{geometry_id}_geometry"]
        cols = list(identity_map.values())
        merged = panel_identity.merge(geometry[cols], on=spec.identifier_field, how="outer", suffixes=("_panel","_geo"), indicator=True)
        if not merged["_merge"].eq("both").all(): _raise(f"{geometry_id} geometry/panel identity merge is incomplete")
        for col in cols:
            if col == spec.identifier_field: continue
            left = merged[f"{col}_panel"].astype("string"); right = merged[f"{col}_geo"].astype("string")
            if not left.equals(right):
                bad = merged.loc[left.ne(right), spec.identifier_field].astype(str).tolist()[:10]
                _raise(f"{geometry_id} geometry/panel {col} mismatch for {bad!r}")


def spatial_universe_mask(district_panel: pd.DataFrame, district_geometry: gpd.GeoDataFrame, data_schema: DataSchemaContract | None = None) -> AnalyticalMask:
    schema = _schema(data_schema); geo_key = schema.geometry("district").identifier_field
    panel_ids = set(district_panel["unit_id"].astype(str).unique()); geo_ids = set(district_geometry[geo_key].astype(str))
    rows=[]
    for unit_id in sorted(panel_ids | geo_ids):
        reasons=[]
        if unit_id not in panel_ids: reasons.append("missing_from_district_panel")
        if unit_id not in geo_ids: reasons.append("missing_from_district_geometry")
        rows.append({"unit_id":unit_id,"eligible":not reasons,"exclusion_reasons":";".join(reasons)})
    return AnalyticalMask("district_spatial_universe", pd.DataFrame(rows))


def _unit_mask_with_rules(
    district_panel: pd.DataFrame,
    base: AnalyticalMask,
    *,
    start: str,
    end: str,
    support_fields: tuple[str, ...] = (),
    denominator_field: str | None = None,
    name: str,
) -> AnalyticalMask:
    """Apply population rules supplied by the executable analysis contract."""
    start_key = _yyyymm(start); end_key = _yyyymm(end)
    expected_months = len(_month_range(start, end))
    required = ["unit_id", "yyyymm", *support_fields]
    if denominator_field is not None:
        required.append(denominator_field)
    _require_columns(district_panel, required, name)
    by_base = base.units.set_index("unit_id")
    subset = district_panel[district_panel["yyyymm"].between(start_key, end_key)]
    grouped = {str(k): g for k, g in subset.groupby("unit_id", observed=True)}
    rows: list[dict[str, object]] = []
    for unit_id in by_base.index.astype(str):
        reasons = [x for x in str(by_base.loc[unit_id, "exclusion_reasons"]).split(";") if x]
        group = grouped.get(unit_id)
        if group is None or len(group) != expected_months:
            reasons.append("incomplete_temporal_support")
        else:
            for flag in support_fields:
                if not group[flag].eq(1).all():
                    reasons.append(f"incomplete_{flag}")
            if denominator_field is not None:
                den = pd.to_numeric(group[denominator_field], errors="coerce")
                if den.isna().any():
                    reasons.append("primary_denominator_missing")
                elif not den.gt(0).all():
                    reasons.append("primary_denominator_zero_or_nonpositive")
        reasons = list(dict.fromkeys(reasons))
        rows.append({"unit_id": unit_id, "eligible": not reasons, "exclusion_reasons": ";".join(reasons)})
    return AnalyticalMask(name, pd.DataFrame(rows))


def _population(analysis: AnalysisContract, population_id: str) -> Mapping[str, Any]:
    try:
        population = analysis.study["populations"][population_id]
    except KeyError as exc:
        raise DataContractError(f"Unknown configured population {population_id!r}") from exc
    if not isinstance(population, Mapping):
        raise DataContractError(f"Configured population {population_id!r} must be a mapping")
    return population


def long_run_ba_district_mask(
    district_panel: pd.DataFrame,
    district_geometry: gpd.GeoDataFrame,
    analysis: AnalysisContract,
    data_schema: DataSchemaContract | None = None,
) -> AnalyticalMask:
    schema = _schema(data_schema)
    base = spatial_universe_mask(district_panel, district_geometry, schema)
    pop = _population(analysis, "long_run_district")
    denominator = str(resolve_field_role(analysis, str(pop["denominator_role"])))
    return _unit_mask_with_rules(
        district_panel,
        base,
        start=str(pop["start"]),
        end=str(pop["end"]),
        denominator_field=denominator,
        name="long_run_ba_district",
    )


def paired_ba_viirs_district_mask(
    district_panel: pd.DataFrame,
    district_geometry: gpd.GeoDataFrame,
    analysis: AnalysisContract,
    data_schema: DataSchemaContract | None = None,
) -> AnalyticalMask:
    schema = _schema(data_schema)
    base = spatial_universe_mask(district_panel, district_geometry, schema)
    pop = _population(analysis, "paired_overlap")
    support_fields = tuple(str(resolve_field_role(analysis, str(role))) for role in pop.get("support_roles", ()))
    denominator = str(resolve_field_role(analysis, str(pop["denominator_role"])))
    return _unit_mask_with_rules(
        district_panel,
        base,
        start=str(pop["start"]),
        end=str(pop["end"]),
        support_fields=support_fields,
        denominator_field=denominator,
        name="paired_ba_viirs_district",
    )


def long_run_temporal_mask(frame: pd.DataFrame, analysis: AnalysisContract) -> pd.Series:
    start, end = _window_yyyymm(analysis.study["temporal_windows"]["long_run"])
    return frame["yyyymm"].between(start, end)


def overlap_monthly_temporal_mask(frame: pd.DataFrame, analysis: AnalysisContract) -> pd.Series:
    start, end = _window_yyyymm(analysis.study["temporal_windows"]["overlap_monthly"])
    return frame["yyyymm"].between(start, end)


def complete_year_overlap_temporal_mask(frame: pd.DataFrame, analysis: AnalysisContract) -> pd.Series:
    window = analysis.study["temporal_windows"]["overlap_complete_years"]
    return frame["year"].between(int(window["start"]), int(window["end"]))


def _exclusion_reason_counts(mask: AnalyticalMask) -> str:
    counts: dict[str, int] = {}
    for value in mask.units.loc[~mask.units["eligible"], "exclusion_reasons"].astype(str):
        for reason in filter(None, value.split(";")):
            counts[reason] = counts.get(reason, 0) + 1
    return "none" if not counts else ";".join(f"{key}:{counts[key]}" for key in sorted(counts))


def reconcile_district_to_acz(district_panel: pd.DataFrame, acz_panel: pd.DataFrame, *, fields: tuple[str,...] | list[str] | None = None, absolute_tolerance: float | None = None, relative_tolerance: float | None = None, data_schema: DataSchemaContract | None = None) -> pd.DataFrame:
    schema=_schema(data_schema); rule=schema.additive_reconciliation["district_to_acz"]
    governed=tuple(str(x) for x in rule["fields"]); selected=governed if fields is None else tuple(fields)
    ensure_declared_fields(selected, schema.field_names)
    nonadditive=sorted(f for f in selected if not schema.field(f).additive or f not in governed)
    if nonadditive: raise ValueError(f"Non-additive or ungoverned reconciliation fields: {nonadditive!r}")
    atol=float(rule["absolute_tolerance"] if absolute_tolerance is None else absolute_tolerance); rtol=float(rule["relative_tolerance"] if relative_tolerance is None else relative_tolerance)
    parent=str(rule["district_parent_field"]); acz_key=str(rule["acz_key_field"]); time=str(rule["time_field"])
    _require_columns(district_panel,[parent,time,*selected],"district reconciliation input"); _require_columns(acz_panel,[acz_key,time,*selected],"ACZ reconciliation input")
    grouped=district_panel.groupby([parent,time],as_index=False,observed=True)[list(selected)].sum(min_count=1)
    merged=acz_panel[[acz_key,time,*selected]].merge(grouped,left_on=[acz_key,time],right_on=[parent,time],how="outer",suffixes=("_acz","_district_sum"),indicator=True)
    if not merged["_merge"].eq("both").all(): _raise("District-to-ACZ reconciliation keys are incomplete")
    rows=[]
    for field in selected:
        a=merged[f"{field}_acz"].astype(float); b=merged[f"{field}_district_sum"].astype(float); null_mismatch=a.isna()^b.isna(); comparable=a.notna()&b.notna(); abs_diff=(a-b).abs(); scale=np.maximum(np.maximum(a.abs(),b.abs()),1e-15); rel_diff=abs_diff/scale; close=pd.Series(True,index=merged.index)
        close.loc[comparable]=np.isclose(a.loc[comparable],b.loc[comparable],atol=atol,rtol=rtol); passed=not bool(null_mismatch.any()) and bool(close.all())
        rows.append({"field":field,"rows_compared":int(comparable.sum()),"null_state_mismatches":int(null_mismatch.sum()),"max_absolute_difference":float(abs_diff.loc[comparable].max()) if comparable.any() else 0.0,"max_relative_difference":float(rel_diff.loc[comparable].max()) if comparable.any() else 0.0,"absolute_tolerance":atol,"relative_tolerance":rtol,"passed":passed})
    result=pd.DataFrame(rows)
    if not bool(result["passed"].all()): _raise(f"Material district-to-ACZ reconciliation disagreement: {result.loc[~result['passed'],'field'].tolist()!r}")
    return result


def analytical_population_authority(
    acz_panel: pd.DataFrame,
    district_panel: pd.DataFrame,
    acz_geometry: gpd.GeoDataFrame,
    district_geometry: gpd.GeoDataFrame,
    analysis: AnalysisContract,
    data_schema: DataSchemaContract | None = None,
) -> tuple[pd.DataFrame, AnalyticalMask, AnalyticalMask, AnalyticalMask, int, int]:
    schema = _schema(data_schema)
    populations = analysis.study["populations"]
    spatial = spatial_universe_mask(district_panel, district_geometry, schema)
    long_mask = long_run_ba_district_mask(district_panel, district_geometry, analysis, schema)
    paired_mask = paired_ba_viirs_district_mask(district_panel, district_geometry, analysis, schema)
    long_exp = populations["long_run_district"]
    pair_exp = populations["paired_overlap"]
    rq3_exp = populations["rq3_model"]
    acz_count = len(set(acz_panel["unit_id"].astype(str)) & set(acz_geometry[schema.geometry("acz").identifier_field].astype(str)))
    paired_ids = set(paired_mask.units.loc[paired_mask.units["eligible"], "unit_id"].astype(str))
    start = _yyyymm(str(rq3_exp["start"])); end = _yyyymm(str(rq3_exp["end"]))
    positive_field = str(resolve_field_role(analysis, str(rq3_exp["positive_role"])))
    rq3_rows_frame = district_panel[
        district_panel["unit_id"].astype(str).isin(paired_ids)
        & district_panel["yyyymm"].between(start, end)
        & pd.to_numeric(district_panel[positive_field], errors="coerce").gt(0)
    ]
    rq3_rows = len(rq3_rows_frame); rq3_units = int(rq3_rows_frame["unit_id"].nunique())
    long_den = str(resolve_field_role(analysis, str(long_exp["denominator_role"])))
    pair_den = str(resolve_field_role(analysis, str(pair_exp["denominator_role"])))
    rows = [
      {"population_name":"acz_spatial_universe","candidate_units":schema.panel("acz_monthly").expected_units,"retained_units":acz_count,"excluded_units":schema.panel("acz_monthly").expected_units-acz_count,"rows":len(acz_panel),"exclusion_reasons":"none" if acz_count==schema.panel("acz_monthly").expected_units else "geometry_panel_key_mismatch","temporal_start":schema.panel("acz_monthly").start,"temporal_end":schema.panel("acz_monthly").end,"source_family":"governed_spatial_authority","denominator":"not_applicable"},
      {"population_name":spatial.name,"candidate_units":spatial.candidate_units,"retained_units":spatial.retained_units,"excluded_units":spatial.excluded_units,"rows":len(district_panel),"exclusion_reasons":_exclusion_reason_counts(spatial),"temporal_start":schema.panel("district_monthly").start,"temporal_end":schema.panel("district_monthly").end,"source_family":"district_spatial_authority","denominator":"not_applicable"},
      {"population_name":long_mask.name,"candidate_units":long_mask.candidate_units,"retained_units":long_mask.retained_units,"excluded_units":long_mask.excluded_units,"rows":int(long_mask.retained_units*len(_month_range(str(long_exp['start']),str(long_exp['end'])))),"exclusion_reasons":_exclusion_reason_counts(long_mask),"temporal_start":str(long_exp["start"]),"temporal_end":str(long_exp["end"]),"source_family":"BA-2001","denominator":long_den},
      {"population_name":paired_mask.name,"candidate_units":paired_mask.candidate_units,"retained_units":paired_mask.retained_units,"excluded_units":paired_mask.excluded_units,"rows":int(paired_mask.retained_units*len(_month_range(str(pair_exp['start']),str(pair_exp['end'])))),"exclusion_reasons":_exclusion_reason_counts(paired_mask),"temporal_start":str(pair_exp["start"]),"temporal_end":str(pair_exp["end"]),"source_family":"BA-2012 + S-NPP VIIRS","denominator":pair_den},
      {"population_name":"rq3_model","candidate_units":paired_mask.retained_units,"retained_units":rq3_units,"excluded_units":paired_mask.retained_units-rq3_units,"rows":rq3_rows,"exclusion_reasons":"none" if rq3_units==paired_mask.retained_units else "no_viirs_positive_observation","temporal_start":str(rq3_exp["start"]),"temporal_end":str(rq3_exp["end"]),"source_family":"paired VIIRS/MCD64A1","denominator":"not_applicable"},
    ]
    return pd.DataFrame(rows), spatial, long_mask, paired_mask, rq3_units, rq3_rows


def validate_data_authorities(authorities: DataAuthorities, analysis: AnalysisContract, data_schema: DataSchemaContract | None = None) -> DataContractSummary:
    schema = _schema(data_schema)
    validate_manifest(authorities.manifest,schema); validate_key_audit(authorities.key_audit,authorities.merge_summary,schema)
    validate_panel(authorities.acz_panel,level="acz",manifest=authorities.manifest,merge_summary=authorities.merge_summary,analysis=analysis,data_schema=schema)
    validate_panel(authorities.district_panel,level="district",manifest=authorities.manifest,merge_summary=authorities.merge_summary,analysis=analysis,data_schema=schema)
    validate_geometry(authorities.acz_geometry,level="acz",data_schema=schema); validate_geometry(authorities.district_geometry,level="district",data_schema=schema)
    validate_geometry_panel_reconciliation(authorities.acz_panel,authorities.district_panel,authorities.acz_geometry,authorities.district_geometry,schema)
    reconciliation = reconcile_district_to_acz(authorities.district_panel,authorities.acz_panel,data_schema=schema)
    population,spatial,long_mask,paired_mask,rq3_units,rq3_rows = analytical_population_authority(authorities.acz_panel,authorities.district_panel,authorities.acz_geometry,authorities.district_geometry,analysis,schema)
    exp = analysis.study["populations"]
    actuals = {
      "acz_monthly":(int(authorities.acz_panel["unit_id"].nunique()),len(authorities.acz_panel)),
      "district_monthly":(int(authorities.district_panel["unit_id"].nunique()),len(authorities.district_panel)),
      "long_run_district":(long_mask.retained_units,int(population.set_index("population_name").loc["long_run_ba_district","rows"])),
      "paired_overlap":(paired_mask.retained_units,int(population.set_index("population_name").loc["paired_ba_viirs_district","rows"])),
      "rq3_model":(rq3_units,rq3_rows),
    }
    for name,(units,rows) in actuals.items():
        expected=exp[name]
        if units!=int(expected["units"]) or rows!=int(expected["rows"]):
            _raise(f"Analytical population {name} differs from executable analysis authority: observed units={units}, rows={rows}; expected units={expected['units']}, rows={expected['rows']}")
    windows=analysis.study["temporal_windows"]
    rule=schema.additive_reconciliation["district_to_acz"]
    return DataContractSummary(
      acz_count=actuals["acz_monthly"][0],acz_monthly_rows=actuals["acz_monthly"][1],district_spatial_universe_count=spatial.retained_units,district_monthly_rows=actuals["district_monthly"][1],long_run_eligible_count=long_mask.retained_units,long_run_rows=actuals["long_run_district"][1],paired_eligible_count=paired_mask.retained_units,paired_rows=actuals["paired_overlap"][1],rq3_gee_units=rq3_units,rq3_gee_rows=rq3_rows,long_run_start=str(exp["long_run_district"]["start"]),long_run_end=str(exp["long_run_district"]["end"]),overlap_start=str(exp["paired_overlap"]["start"]),overlap_end=str(exp["paired_overlap"]["end"]),complete_year_start=int(windows["overlap_complete_years"]["start"]),complete_year_end=int(windows["overlap_complete_years"]["end"]),reconciliation_absolute_tolerance=float(rule["absolute_tolerance"]),reconciliation_relative_tolerance=float(rule["relative_tolerance"]),reconciliation=reconciliation,population_authority=population,long_run_mask=long_mask,paired_mask=paired_mask,spatial_universe_mask=spatial)


def rq3_mcd64a1_support_audit(
    paired_panel: pd.DataFrame,
    *,
    ba_area_field: str = "modis_ba_km2_ba2012",
    ba_presence_field: str = "modis_ba_any_ba2012",
) -> pd.DataFrame:
    """Audit supported MCD64A1 zeroes separately from structural missingness.

    The caller supplies the already-governed paired population.  This function
    does not recode missing values and fails if a paired row lacks BA support.
    """
    required = {
        "month",
        "ba2012_supported_flag",
        "ba2012_structural_missing_flag",
        ba_area_field,
        ba_presence_field,
    }
    missing = sorted(required.difference(paired_panel.columns))
    if missing:
        _raise(f"RQ3 MCD64A1 support audit is missing fields: {missing!r}")
    if not paired_panel["ba2012_supported_flag"].eq(1).all():
        _raise("RQ3 paired population contains BA2012 rows without support")
    if not paired_panel["ba2012_structural_missing_flag"].eq(0).all():
        _raise("RQ3 paired population contains structurally missing BA2012 rows")
    ba = pd.to_numeric(paired_panel[ba_area_field], errors="coerce")
    presence = pd.to_numeric(paired_panel[ba_presence_field], errors="coerce")
    if ba.isna().any() or presence.isna().any():
        _raise("RQ3 supported MCD64A1 observations contain numerical missing values")
    if not presence.isin([0, 1]).all():
        _raise("RQ3 MCD64A1 presence flag is not binary")
    if not ((ba > 0).astype(int) == presence.astype(int)).all():
        _raise("RQ3 MCD64A1 area/presence semantics disagree")
    rows = []
    for month, group in paired_panel.groupby("month", sort=True, observed=True):
        values = pd.to_numeric(group[ba_area_field], errors="raise")
        rows.append(
            {
                "month": int(month),
                "rows": int(len(group)),
                "supported_rows": int(group["ba2012_supported_flag"].eq(1).sum()),
                "structural_missing_rows": int(group["ba2012_structural_missing_flag"].eq(1).sum()),
                "numeric_missing_rows": int(values.isna().sum()),
                "zero_rows": int(values.eq(0).sum()),
                "positive_rows": int(values.gt(0).sum()),
            }
        )
    return pd.DataFrame(rows)
