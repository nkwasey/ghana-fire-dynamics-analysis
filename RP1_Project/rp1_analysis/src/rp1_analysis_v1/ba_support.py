"""Mandatory c3 evidence validation for the compact analytical panels."""
from __future__ import annotations

import csv
import hashlib
import hmac
import re
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd
from rp1_ba_contracts.c3 import FIELDS as FIELDS69, METHOD, POLICY, SCHEMA, parse_filename, validate_row, observation_windows


class BAObservationSupportError(ValueError):
    """Raised when declared c3 evidence cannot be trusted."""


KEY = ["level", "unit_id", "yyyymm", "family"]
SOURCE_META_FIELDS = ["family", "source_path", "source_sha256", "source_row"]
BASE = list(FIELDS69) + SOURCE_META_FIELDS
QA = [name for name in FIELDS69 if name.startswith("ba_")]
EVIDENCE_SCHEMA = "rp1-ba-c3-evidence-v1"
USABLE_STATUSES = {"ADMITTED", "ZERO_UNION_DENOMINATOR"}
PRIMARY_FIELDS = (
    "modis_ba_km2", "modis_burned_pixel_count", "modis_ba_any",
    "modis_burnable_km2_union", "modis_burnable_km2_annual",
    "modis_burned_frac_union", "modis_burned_frac_annual",
    "modis_aoi_area_land_km2", "modis_zero_union_den_flag",
    "modis_zero_annual_den_flag",
)
PROFILE_OUTPUTS = {
    "fire_panel_acz": "fire_panel_acz_monthly_consolidated_2001_2024.csv",
    "fire_panel_district": "fire_panel_district_monthly_consolidated_2001_2024.csv",
    "key_audit": "fire_panel_key_audit.csv",
    "merge_summary": "fire_panel_merge_summary.json",
    "ba_observation_support": "ba_observation_support.csv",
}


def _fail(message: str) -> None:
    raise BAObservationSupportError(message)


def validate_c3_manifest(manifest: dict[str, Any]) -> None:
    """Require the admitted c3 source policy and its evidence."""
    meta, profile = manifest.get("ba_observation_support"), manifest.get("profile_contract")
    if not isinstance(meta, dict):
        _fail("c3 evidence declaration missing from panel manifest")
    if manifest.get("profile_id") != "c3" or not isinstance(profile, dict):
        _fail("Only the c3 burned-area profile is supported")
    if (profile.get("source_label") != "c3" or profile.get("quality_policy") != POLICY
            or profile.get("source_schema_version") != SCHEMA or profile.get("method_version") != METHOD):
        _fail("Panel profile does not declare the current c3 source, policy and method")
    if (meta.get("schema_version") != EVIDENCE_SCHEMA or meta.get("profile_id") != "c3"
            or meta.get('source_schema_version') != SCHEMA
            or meta.get("quality_policy") != POLICY or meta.get("method_version") != METHOD
            or meta.get("sidecar_output") != "ba_observation_support.csv"
            or meta.get("source_values_preserved") is not True):
        _fail("Invalid c3 evidence schema, policy, method or preservation declaration")


def profile_output_filenames(manifest: dict[str, Any]) -> dict[str, str]:
    """Resolve semantic output roles without date-based filename assumptions."""
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        _fail("Profile output manifest mapping is missing")
    result = {}
    for role in PROFILE_OUTPUTS:
        record = outputs.get(role)
        if not isinstance(record, dict):
            _fail(f"Profile output manifest record missing: {role}")
        staged = record.get("staged_path")
        if not isinstance(staged, str) or not staged or "\\" in staged:
            _fail(f"Invalid profile output path: {role}")
        filename = Path(staged).name
        if not filename or filename in {".", ".."} or ":" in filename:
            _fail(f"Invalid profile output filename: {role}")
        result[role] = filename
    if len(set(result.values())) != len(result):
        _fail("Profile output roles alias the same filename")
    return result


def validate_profile_output_hashes(root: Path, manifest: dict[str, Any]) -> None:
    """Verify immutable staged bytes, including AF columns and the companion."""
    outputs = manifest.get("outputs", {})
    for role, filename in profile_output_filenames(manifest).items():
        record = outputs[role]
        sha = record.get("sha256")
        if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
            _fail(f"Invalid profile output SHA-256: {role}")
        path = (root / "data/raw" / filename).resolve()
        if not path.is_relative_to(root.resolve()):
            _fail(f"Profile output path escapes the analysis subproject: {role}")
        if not path.is_file():
            _fail(f"Profile output file is missing: {role}")
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            raise BAObservationSupportError(
                f"Cannot read profile output {role} at {path}: {exc}. Verification stopped."
            ) from exc
        if not hmac.compare_digest(digest.hexdigest(), sha):
            _fail(f"Profile output hash does not match manifest: {role}")


def load_observation_support(root: Path, manifest: dict[str, Any]) -> pd.DataFrame:
    """Read all original source fields as text, preserving blank cells."""
    validate_c3_manifest(manifest)
    record = manifest.get("outputs", {}).get("ba_observation_support")
    if not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
        _fail("Missing c3 evidence output hash")
    if Path(str(record.get("staged_path", ""))).name != "ba_observation_support.csv":
        _fail("Invalid c3 evidence staged filename")
    path = (root / "data/raw/ba_observation_support.csv").resolve()
    if not path.is_relative_to(root.resolve()):
        _fail('c3 evidence path escapes the analysis subproject')
    if not path.is_file():
        _fail("Manifest-declared c3 evidence companion is missing")
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            _fail("c3 evidence companion hash does not match manifest")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            extended_header = list(FIELDS69) + ['ba_annual_lc_source_index'] + SOURCE_META_FIELDS
            if len(header) != len(set(header)) or header not in (BASE, extended_header):
                _fail("c3 evidence header must contain all 69 source fields and exact provenance fields in order")
            if any(len(row) != len(header) for row in reader):
                _fail("Invalid c3 evidence CSV row width")
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except BAObservationSupportError:
        raise
    except (OSError, ValueError, StopIteration, csv.Error, pd.errors.ParserError) as exc:
        raise BAObservationSupportError(f"Unable to read c3 evidence: {exc}") from exc


def _numeric(frame: pd.DataFrame, name: str, *, nullable: bool = False) -> pd.Series:
    try:
        values = pd.to_numeric(frame[name].replace("", np.nan), errors="raise").astype(float)
    except (KeyError, ValueError, TypeError) as exc:
        raise BAObservationSupportError(f"Invalid numeric c3 evidence field {name}: {exc}") from exc
    if np.isinf(values).any() or (not nullable and values.isna().any()):
        _fail(f"Missing or nonfinite c3 evidence field {name}")
    return values


def _same(actual: pd.Series, expected: pd.Series, field: str) -> None:
    x = pd.to_numeric(actual, errors="coerce").astype(float)
    y = pd.to_numeric(expected, errors="coerce").astype(float)
    good = (x.isna() & y.isna()) | (x.notna() & y.notna() & np.isclose(x, y, rtol=1e-10, atol=1e-8))
    if not good.all():
        _fail(f"c3 source values/nulls disagree with analytical panel: {field}")


def _source_records(manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    records = {}
    for family in manifest.get("families", []):
        if not isinstance(family, dict):
            _fail('Invalid c3 source family inventory')
        if family.get("source_kind") not in {"ba2001", "ba2012"}:
            continue
        for record in family.get("files", []):
            if not isinstance(record, dict):
                _fail('Invalid c3 source file inventory record')
            name = record.get("filename") or PurePosixPath(str(record.get("source_path") or record.get("origin_path") or record.get("path", ""))).name
            if isinstance(record.get("sha256"), str) and name:
                key = (str(family["source_kind"]), str(name))
                if key in records:
                    _fail("Duplicate c3 source file identity in merger inventory")
                records[key] = record
    return records


def validate_observation_support(
    sidecar: pd.DataFrame | None, manifest: dict[str, Any],
    acz: pd.DataFrame, district: pd.DataFrame,
) -> None:
    """Validate source semantics and exact source-to-panel primary projections."""
    validate_c3_manifest(manifest)
    declaration = manifest.get('study', {'start_yyyymm': 200101, 'end_yyyymm': 202412})
    windows = observation_windows(int(declaration['start_yyyymm'])//100, int(declaration['end_yyyymm'])//100)
    if sidecar is None or set(BASE).difference(sidecar.columns):
        _fail("Mandatory c3 evidence fields are missing")
    frame = sidecar.copy()
    if frame.empty:
        _fail("c3 evidence companion is empty")
    months = _numeric(frame, "yyyymm")
    if not months.mod(1).eq(0).all():
        _fail("c3 evidence months must be integers")
    frame["yyyymm"] = months.astype("int64")
    if frame.duplicated(KEY).any():
        _fail("Duplicate c3 evidence key")
    if not frame["level"].isin(["acz", "district"]).all() or not frame["family"].isin(["ba2001", "ba2012"]).all():
        _fail("Unexpected c3 evidence level or family")
    if not frame["ba_domain"].eq(frame["family"].str.upper()).all():
        _fail("c3 source domain disagrees with canonical family")
    monthly_identity = ['ba_source_index', 'ba_source_count', 'ba_product', 'ba_grid_crs', 'ba_grid_transform', 'ba_reducer']
    if frame.groupby(['family','yyyymm'], observed=True)[monthly_identity].nunique(dropna=False).gt(1).any().any():
        _fail('c3 monthly source/grid identity disagrees across levels or zones')
    if frame.groupby('family', observed=True)['ba_lc_source_indexes'].nunique(dropna=False).gt(1).any():
        _fail('c3 full-reference land-cover source identity changes within a domain')
    if frame.groupby('level', observed=True)['ba_boundary_asset'].nunique(dropna=False).gt(1).any() or frame.ba_ghana_asset.nunique(dropna=False) != 1:
        _fail('c3 boundary asset identity changes within the selected delivery')
    rows = _numeric(frame, "source_row")
    if not rows.ge(1).all() or not rows.mod(1).eq(0).all():
        _fail("c3 source_row must be the original 1-based CSV data-row index")
    if frame.duplicated(["source_path", "source_row"]).any():
        _fail("Duplicate c3 original source row identity")
    for path, group in frame.groupby('source_path', observed=True):
        indices = sorted(pd.to_numeric(group.source_row, errors='raise').astype(int).tolist())
        if indices != list(range(1, len(indices) + 1)):
            _fail(f'c3 original data-row indexes are incomplete: {path}')
    source_records = _source_records(manifest)
    if not source_records:
        _fail("c3 source file inventory missing from merger manifest")
    observed_files = {(str(family), PurePosixPath(str(path)).name) for family, path in zip(frame.family, frame.source_path)}
    if observed_files != set(source_records):
        _fail('c3 evidence does not cover the exact merger source file inventory')
    for (family, path), group in frame.groupby(['family','source_path'], observed=True):
        identity = parse_filename(PurePosixPath(path).name, observation_windows=windows)
        bound = source_records[(family, PurePosixPath(path).name)]
        for field in ('family','domain','level','partition','year'):
            if field in bound and str(bound[field]) != str(identity[field]):
                _fail(f'c3 source inventory filename disagrees with {field}')
        size = bound.get('row_count', bound.get('rows'))
        if size is not None and int(size) != len(group):
            _fail('c3 evidence source row count disagrees with merger inventory')
        run_ids = bound.get('run_ids')
        if run_ids is None and bound.get('run_id') is not None:
            run_ids = [bound['run_id']]
        if run_ids is not None and set(group.run_id.astype(str)) != set(map(str, run_ids)):
            _fail('c3 original source run identities disagree with merger inventory')
    for record in frame.to_dict(orient="records"):
        path = record["source_path"]
        if (not isinstance(path, str) or not path or "\\" in path
                or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts):
            _fail("Invalid c3 source provenance path")
        sha = record["source_sha256"]
        if re.fullmatch(r"[0-9a-f]{64}", str(sha)) is None:
            _fail("Invalid c3 source SHA-256")
        bound = source_records.get((record["family"], PurePosixPath(path).name))
        if bound is None or bound.get("sha256") != sha:
            _fail("c3 evidence source file identity disagrees with merger inventory")
        if path != bound.get('source_path', 'sources/' + PurePosixPath(path).name):
            _fail('c3 evidence source path disagrees with merger inventory')
        raw = {name: (None if pd.isna(record[name]) else record[name]) for name in FIELDS69}
        if 'ba_annual_lc_source_index' in record:
            raw['ba_annual_lc_source_index'] = record['ba_annual_lc_source_index']
        try:
            validate_row(raw, identity=parse_filename(PurePosixPath(path).name, observation_windows=windows),
                         observation_windows=windows)
        except ValueError as exc:
            raise BAObservationSupportError(f"Invalid c3 evidence at {path}:{record['source_row']}: {exc}") from exc
    expected = []
    for level, panel in (("acz", acz), ("district", district)):
        for family in ("ba2001", "ba2012"):
            subset = panel if family == "ba2001" else panel.loc[panel["ba2012_supported_flag"].eq(1)]
            part = subset[["unit_id", "yyyymm"]].copy()
            part["level"], part["family"] = level, family
            expected.append(part[KEY])
    spine = pd.concat(expected, ignore_index=True)
    joined = spine.merge(frame, on=KEY, how="outer", validate="one_to_one", indicator=True)
    if len(joined) != len(spine) or not joined["_merge"].eq("both").all():
        _fail("c3 evidence keys do not match supported panel keys")
    for level, panel in (("acz", acz), ("district", district)):
        for family in ("ba2001", "ba2012"):
            part = frame.loc[frame["level"].eq(level) & frame["family"].eq(family)]
            names = [f"{name}_{family}" for name in PRIMARY_FIELDS]
            identity = [name for name in ("unit_code", "unit_name", "parent_level", "parent_id", "parent_code", "parent_name", "year", "month") if name in panel]
            merged = part.merge(panel[["unit_id", "yyyymm", *identity, *names]], on=["unit_id", "yyyymm"], how="left", validate="one_to_one", suffixes=("_source", "_panel"))
            for name in identity:
                left, right = merged[f"{name}_source"], merged[f"{name}_panel"]
                if name in {"year", "month"}:
                    _same(left, right, name)
                elif not left.fillna("").astype(str).eq(right.fillna("").astype(str)).all():
                    _fail(f"c3 source identity disagrees with panel: {name}")
            for source, target in zip(PRIMARY_FIELDS, names):
                _same(merged[target], _numeric(merged, source, nullable=True), target)


def c3_evidence_summary(sidecar: pd.DataFrame) -> pd.DataFrame:
    """Count records by result/evidence state, without claiming area coverage."""
    fields = ["level", "family", "year", "month", "ba_status", "ba_coverage_status"]
    if sidecar is None or set(fields + ["modis_ba_km2", "ba_state_explicit_zero_km2"]).difference(sidecar.columns):
        _fail("c3 evidence summary requires complete companion fields")
    frame = sidecar.copy()
    ba = _numeric(frame, "modis_ba_km2", nullable=True)
    explicit = _numeric(frame, "ba_state_explicit_zero_km2", nullable=True)
    frame["primary_usable_rows"] = frame.ba_status.isin(USABLE_STATUSES).astype(int)
    frame["withheld_rows"] = (~frame.ba_status.isin(USABLE_STATUSES)).astype(int)
    frame["scenario_zero_rows"] = (frame.ba_status.eq("ADMITTED") & ba.eq(0) & explicit.fillna(0).eq(0)).astype(int)
    frame["explicit_zero_evidence_rows"] = explicit.gt(0).astype(int)
    frame["positive_rows"] = ba.gt(0).astype(int)
    frame["rows"] = 1
    values = ["rows", "primary_usable_rows", "withheld_rows", "scenario_zero_rows", "explicit_zero_evidence_rows", "positive_rows"]
    return frame.groupby(fields, as_index=False, dropna=False, observed=True)[values].sum()



C3_DIAGNOSTIC_AREAS = (
    "ba_known_union_area_km2", "ba_known_union_burned_km2",
    "ba_domain_unresolved_km2", "ba_domain_excluded_km2", "ba_annual_unknown_km2",
    "ba_any_lc_missing_year_km2", "ba_any_lw_missing_year_km2",
    "ba_any_lc_invalid_year_km2", "ba_any_lw_invalid_year_km2",
    "ba_state_qa_missing_km2", "ba_state_burndate_masked_km2",
    "ba_state_unsupported_km2", "ba_state_explicit_zero_km2", "ba_state_accepted_km2",
    "ba_supported_area_km2", "ba_shortened_km2", "ba_full_period_only_km2",
    "ba_anomaly_area_km2", "ba_state_closure_km2",
)
C3_DIAGNOSTIC_COUNTS = ("ba_sampled_pixel_count", "ba_anomaly_pixel_count")


def reconcile_c3_evidence(
    sidecar: pd.DataFrame, district_panel: pd.DataFrame, *,
    area_absolute_tolerance: float = 1e-8, area_relative_tolerance: float = 1e-10,
    union_absolute_tolerance: float = 1e-5,
) -> pd.DataFrame:
    """Reconcile available additive diagnostics even when primary BA is withheld.

    Reason areas are intentionally absent: their overlaps are not a partition.
    Counts compare exactly; known-union area uses the existing governed union
    tolerance. Every other area retains the default area reconciliation limits.
    """
    limits = (area_absolute_tolerance, area_relative_tolerance, union_absolute_tolerance)
    if any(not np.isfinite(v) or v < 0 for v in limits):
        _fail("Invalid c3 evidence reconciliation tolerances")
    fields = [*C3_DIAGNOSTIC_AREAS, *C3_DIAGNOSTIC_COUNTS]
    frame = sidecar.copy()
    for name in fields:
        frame[name] = _numeric(frame, name, nullable=True)
    frame["yyyymm"] = _numeric(frame, "yyyymm").astype("int64")
    districts = frame.loc[frame.level.eq("district")].copy()
    zones = frame.loc[frame.level.eq("acz")].copy()
    districts["_zone"] = districts.parent_code
    zones["_zone"] = zones.unit_code
    keys = ["family", "_zone", "yyyymm"]
    if zones.duplicated(keys).any() or districts.duplicated(["family","unit_id","yyyymm"]).any():
        _fail("Duplicate c3 evidence reconciliation key")
    universe = district_panel[["unit_id","parent_code"]].drop_duplicates()
    if universe.unit_id.duplicated().any():
        _fail("Inconsistent district parent in c3 reconciliation universe")
    expected = universe.groupby("parent_code", observed=True).unit_id.nunique()
    grouped = districts.groupby(keys, observed=True)
    sizes = grouped.size()
    counts = grouped[fields].count()
    totals = grouped[fields].sum(min_count=1)
    expected_rows = totals.index.get_level_values("_zone").map(expected)
    if pd.isna(expected_rows).any():
        _fail("Unknown c3 evidence parent in reconciliation")
    missing = sizes.to_numpy() != expected_rows
    for name in fields:
        totals.loc[missing | (counts[name].to_numpy() != expected_rows), name] = np.nan
    summed = totals.reset_index()
    compared = zones[keys + fields].merge(summed, on=keys, how="outer",
        suffixes=("_acz","_district_sum"), indicator=True)
    if not compared["_merge"].eq("both").all():
        _fail("Missing ACZ/district keys in c3 diagnostic reconciliation")
    records = []
    for family in ("ba2001", "ba2012"):
        selected = compared.family.eq(family)
        member_family = totals.index.get_level_values("family") == family
        for name in fields:
            direct = compared.loc[selected, name+"_acz"]
            total = compared.loc[selected, name+"_district_sum"]
            available = direct.notna() & total.notna()
            count_field = name in C3_DIAGNOSTIC_COUNTS
            atol = 0.0 if count_field else union_absolute_tolerance if name == "ba_known_union_area_km2" else area_absolute_tolerance
            rtol = 0.0 if count_field or name == "ba_known_union_area_km2" else area_relative_tolerance
            difference = (direct-total).abs()
            close = np.isclose(direct.loc[available], total.loc[available], atol=atol, rtol=rtol)
            if not close.all():
                bad = available.copy()
                bad.loc[available] = ~close
                example = compared.loc[selected].loc[bad, keys].iloc[0].to_dict()
                _fail(f"c3 diagnostic reconciliation disagreement in {name}: {example}")
            incomplete_members = missing[member_family]
            withheld_members = (counts[name].to_numpy() != expected_rows)[member_family] & ~incomplete_members
            records.append({
                "family":family, "field":name, "rows_compared":int(available.sum()),
                "not_comparable_rows":int((~available).sum()),
                "missing_constituent_rows":int(incomplete_members.sum()),
                "withheld_constituent_rows":int(withheld_members.sum()),
                "withheld_acz_rows":int(direct.isna().sum()),
                "max_absolute_difference":float(difference.loc[available].max()) if available.any() else 0.0,
                "absolute_tolerance":atol, "relative_tolerance":rtol,
                "comparison_status":"COMPLETE" if available.all() else "WITHHELD_DIAGNOSTICS_NOT_COMPARED",
                "passed":True,
            })
    return pd.DataFrame(records)

