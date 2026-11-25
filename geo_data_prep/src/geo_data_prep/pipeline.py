"""Spatial assignment, whole-district construction, QA and reproducible handoffs."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely import get_coordinates, union_all
import yaml

from . import __version__

UNIT_COLUMNS = ["unit_type", "level", "unit_id", "unit_code", "unit_name", "parent_level", "parent_id", "parent_code", "parent_name", "area_sqkm"]


class PrepError(ValueError):
    """Input or output violates the declared geography contract."""


def require(condition, message):
    if not condition:
        raise PrepError(message)


def normalise(value):
    require(isinstance(value, str) and bool(value.strip()), "Names and identifiers must be nonempty strings")
    return " ".join(unicodedata.normalize("NFKC", value).split())


def district_id(name):
    tokens = re.findall(r"[A-Za-z0-9]+", normalise(name))
    require(bool(tokens), f"No identifier tokens in district name: {name!r}")
    return "_".join(t[0].upper() + t[1:].lower() for t in tokens)


def zone_id(name):
    tokens = re.findall(r"[A-Za-z0-9]+", normalise(name))
    require(bool(tokens), f"No identifier tokens in zone name: {name!r}")
    return "_".join(tokens).lower()


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.17g", lineterminator="\n")


def bundle(path):
    """Hash component bytes and a canonical mapping of component names to hashes."""
    path = Path(path)
    parts = {p.name: sha256(p) for p in sorted(path.parent.glob(path.stem + ".*")) if p.is_file()}
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"file": path.name, "parts": parts, "bundle_sha256": digest}


class ConfigLoader(yaml.SafeLoader):
    """Safe YAML reader that rejects ambiguous duplicate mapping keys."""


def _config_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            require(key not in result, f"Duplicate configuration key: {key!r}")
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as error:
            raise PrepError("Configuration mapping keys must be scalar values") from error
    return result


ConfigLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _config_mapping)


def _supported_keys(mapping, allowed, section):
    require(isinstance(mapping, dict), f"{section} must be a mapping")
    require(all(isinstance(key, str) for key in mapping), f"{section} keys must be strings")
    unknown = sorted(set(mapping) - set(allowed))
    require(not unknown, f"Unsupported {section} settings: {', '.join(unknown)}")


def _text(value, setting):
    require(isinstance(value, str) and bool(value.strip()), f"{setting} must be a nonempty string")


def _number(value, setting):
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{setting} must be numeric")
    try:
        value = float(value)
    except OverflowError as error:
        raise PrepError(f"{setting} must be finite") from error
    require(math.isfinite(value), f"{setting} must be finite")
    return value


def _source_path(cfg, role):
    return (cfg["_root"] / cfg["inputs"][role]["path"]).resolve()


def _input_layer(cfg, role):
    try:
        layers = gpd.list_layers(_source_path(cfg, role))
    except Exception as error:
        raise PrepError(f"Cannot list {role} input layers: {error}") from error
    names = [str(name) for name in layers.loc[layers.geometry_type.notna(), "name"]]
    require(bool(names), f"No spatial layers in {role} input")
    selected = cfg["inputs"][role].get("layer")
    if selected is not None:
        require(selected in names, f"Unknown spatial layer for {role}: {selected}")
        return selected
    require(len(names) == 1, f"Multiple spatial layers in {role} input; set inputs.{role}.layer explicitly")
    return names[0]


def _input_identity(cfg, role):
    path = _source_path(cfg, role)
    identity = bundle(path)
    selected = _input_layer(cfg, role)
    require(bundle(path) == identity, f"Input bundle changed while identifying layer: {role}")
    return {**identity, "layer": selected}


def _verify_input_identities(cfg, identities):
    for role in ("districts", "zones", "national"):
        if role in identities:
            require(_input_identity(cfg, role) == identities[role], f"Input bundle changed during processing: {role}")


def load_config(config_path):
    path = Path(config_path).resolve()
    try:
        content = path.read_bytes()
        cfg = yaml.load(content.decode("utf-8"), Loader=ConfigLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise PrepError(f"Cannot read configuration: {error}") from error
    _supported_keys(cfg, {"project_root", "inputs", "outputs", "crs", "assignment", "qa", "expected", "clip_to_aoi"}, "configuration")
    _text(cfg.get("project_root", ".."), "project_root")
    root = (path.parent / cfg.get("project_root", "..")).resolve()
    _supported_keys(cfg.get("inputs"), {"districts", "zones", "national"}, "inputs")
    for role in ("districts", "zones"):
        require(isinstance(cfg["inputs"].get(role), dict), f"Missing input role: {role}")
    for role, spec in cfg["inputs"].items():
        if role == "national" and spec is None:
            continue
        allowed = {"path", "layer"} if role == "national" else {"path", "layer", "name_field", "id_field", "code_field"}
        if role == "zones":
            allowed.add("code_mapping")
        _supported_keys(spec, allowed, f"inputs.{role}")
        _text(spec.get("path"), f"inputs.{role}.path")
        if "layer" in spec:
            _text(spec["layer"], f"inputs.{role}.layer")
        if role != "national":
            _text(spec.get("name_field"), f"inputs.{role}.name_field")
            for field in ("id_field", "code_field"):
                if field in spec:
                    _text(spec[field], f"inputs.{role}.{field}")
        if "code_mapping" in spec:
            require(isinstance(spec["code_mapping"], dict), "inputs.zones.code_mapping must be a mapping")
            for name, code in spec["code_mapping"].items():
                _text(name, "inputs.zones.code_mapping name")
                _text(code, "inputs.zones.code_mapping code")
    settings = {
        "outputs": {"root", "splits", "plots"}, "crs": {"working", "area", "output", "analysis"},
        "assignment": {"tie_tolerance", "warning_share", "warning_margin"},
        "qa": {"area_tolerance_m2"}, "expected": {"districts", "zones"},
    }
    for section, allowed in settings.items():
        _supported_keys(cfg.get(section, {}), allowed, section)
    _text(cfg.get("outputs", {}).get("root", "out"), "outputs.root")
    for key in ("splits", "plots"):
        if key in cfg.get("outputs", {}):
            require(isinstance(cfg["outputs"][key], bool), f"outputs.{key} must be a YAML boolean")
    if "clip_to_aoi" in cfg:
        require(isinstance(cfg["clip_to_aoi"], bool), "clip_to_aoi must be a YAML boolean")
        require(not cfg["clip_to_aoi"], "Whole-district method does not allow AOI clipping")
    for key, value in cfg.get("expected", {}).items():
        require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"expected.{key} must be a positive integer")
    for key in ("working", "area", "analysis"):
        if key == "analysis" and key not in cfg.get("crs", {}):
            continue
        value = cfg.get("crs", {}).get(key, cfg.get("crs", {}).get("working", "EPSG:32630"))
        try:
            require(isinstance(value, (str, int, dict)) and not isinstance(value, bool), f"Invalid crs.{key} value")
            crs = CRS.from_user_input(value)
        except (CRSError, TypeError) as error:
            raise PrepError(f"Invalid crs.{key}: {error}") from error
        require(crs.is_projected and all(abs(a.unit_conversion_factor - 1.0) < 1e-12 for a in crs.axis_info[:2]), f"crs.{key} must be a projected CRS with metre axes")
    if "output" in cfg.get("crs", {}):
        try:
            value = cfg["crs"]["output"]
            require(isinstance(value, (str, int, dict)) and not isinstance(value, bool), "Invalid crs.output value")
            CRS.from_user_input(value)
        except (CRSError, TypeError) as error:
            raise PrepError(f"Invalid crs.output: {error}") from error
    for key, default in (("tie_tolerance", 1e-12), ("warning_share", .5), ("warning_margin", .05)):
        value = _number(cfg.get("assignment", {}).get(key, default), f"assignment.{key}")
        require(0 <= value <= 1, f"assignment.{key} must be finite in [0,1]")
    tolerance = _number(cfg.get("qa", {}).get("area_tolerance_m2", 1e-4), "qa.area_tolerance_m2")
    require(tolerance >= 0, "qa.area_tolerance_m2 must be finite and nonnegative")
    cfg["_config_path"], cfg["_root"] = path, root
    cfg["_config_sha256"] = hashlib.sha256(content).hexdigest()
    output_root = (root / cfg.get("outputs", {}).get("root", "out")).resolve()
    require(not any(output_root == _source_path(cfg, role).parent for role in cfg["inputs"] if cfg["inputs"][role] is not None), "Output root must not be a source directory")
    return cfg


def read_layer(cfg, role):
    spec = cfg["inputs"][role]
    path = (cfg["_root"] / spec["path"]).resolve()
    require(path.is_file(), f"Missing {role} input: {spec['path']}")
    if path.suffix.lower() == ".shp":
        for extension in (".shp", ".shx", ".dbf", ".prj"):
            require(path.with_suffix(extension).is_file(), f"Missing shapefile component: {path.stem}{extension}")
    try:
        frame = gpd.read_file(path, layer=_input_layer(cfg, role))
    except Exception as error:
        raise PrepError(f"Cannot read {role}: {error}") from error
    require(frame.crs is not None, f"Missing CRS for {role}")
    require(len(frame) > 0, f"Empty layer: {role}")
    require(not frame.geometry.isna().any() and not frame.geometry.is_empty.any(), f"Empty geometry in {role}")
    require(frame.geometry.is_valid.all(), f"Invalid geometry in {role}; repair must be explicit before running")
    require(frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all(), f"Nonpolygon geometry in {role}")
    require(all(math.isfinite(float(x)) for x in frame.total_bounds), f"Nonfinite coordinates in {role}")
    return frame, path


def fields(frame, spec, role):
    for key in ("name_field", "id_field", "code_field"):
        if spec.get(key):
            require(spec[key] in frame.columns, f"Missing {role} field: {spec[key]}")
    names = [normalise(x) for x in frame[spec["name_field"]]]
    derive = district_id if role == "districts" else zone_id
    if spec.get("id_field"):
        identifiers = []
        for value in frame[spec["id_field"]]:
            require(not pd.isna(value), f"Missing {role} identifier")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                require(math.isfinite(float(value)), f"Nonfinite {role} identifier")
                value = str(int(value)) if float(value).is_integer() else str(value)
            identifiers.append(normalise(str(value)))
    else:
        identifiers = [derive(x) for x in names]
    require(all(re.fullmatch(r"[A-Za-z0-9_]+", i) for i in identifiers), f"Unsafe {role} identifier; use letters, digits and underscores")
    portable_ids = {}
    for identifier in identifiers:
        folded = identifier.casefold()
        require(folded not in portable_ids or portable_ids[folded] == identifier, f"Case-insensitive {role} identifier collision: {identifier}")
        portable_ids[folded] = identifier
        if role == "zones":
            require(not re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", folded), f"Zone identifier is a reserved Windows filename: {identifier}")
    mapping = {}
    for key, value in spec.get("code_mapping", {}).items():
        key, value = normalise(str(key)).casefold(), normalise(str(value)).upper()
        require(key not in mapping or mapping[key] == value, "Conflicting normalized zone code mappings")
        mapping[key] = value
    generated, used = {}, set(mapping.values())
    if role == "zones" and not spec.get("code_field"):
        for identifier, name in sorted(set(zip(identifiers, names))):
            if identifier in generated:
                continue
            if name.casefold() in mapping:
                generated[identifier] = mapping[name.casefold()]
                continue
            base = "".join(token[0] for token in re.findall(r"[A-Za-z]+", name)).upper() or identifier.upper()
            code, suffix = base, 2
            while code in used:
                code, suffix = base + str(suffix), suffix + 1
            generated[identifier] = code
            used.add(code)
    codes = []
    for identifier, (_, record) in zip(identifiers, frame.iterrows()):
        if spec.get("code_field"):
            value = record[spec["code_field"]]
            code = "" if pd.isna(value) else normalise(str(value))
        elif role == "districts":
            code = ""
        else:
            code = generated[identifier]
        if role == "zones":
            require(bool(code), "Zone codes must not be blank")
        codes.append(code)
    return names, identifiers, codes


def positive_overlaps(frame, tolerance):
    """Report overlapping feature pairs above an area tolerance in the frame CRS."""
    records = []
    for i, geometry in enumerate(frame.geometry):
        for j in frame.sindex.query(geometry, predicate="intersects"):
            if int(j) <= i:
                continue
            area = geometry.intersection(frame.geometry.iloc[int(j)]).area
            if area > tolerance:
                records.append({"first": str(frame.index[i]), "second": str(frame.index[int(j)]), "area_m2": float(area)})
    return records


def project(frame, crs, role):
    try:
        transformed = frame.to_crs(crs)
    except Exception as error:
        raise PrepError(f"Cannot project {role}: {error}") from error
    require(not transformed.geometry.is_empty.any() and transformed.geometry.is_valid.all(), f"Invalid projected geometry in {role}")
    require(all(math.isfinite(float(x)) for x in transformed.total_bounds), f"Nonfinite projected coordinates in {role}")
    require(all(math.isfinite(float(x)) and x > 0 for x in transformed.area), f"Nonfinite or nonpositive projected area in {role}")
    return transformed


def geographic_export(frame, role):
    """Return an admissible WGS84 display layer without repairing geometry."""
    try:
        geographic = frame.to_crs(4326)
    except Exception as error:
        raise PrepError(f"Cannot transform {role} to EPSG:4326: {error}") from error
    require(not geographic.geometry.isna().any() and not geographic.geometry.is_empty.any(),
            f"Missing or empty EPSG:4326 geometry in {role}")
    coordinates = get_coordinates(geographic.geometry.values)
    require(all(math.isfinite(float(value)) for coordinate in coordinates for value in coordinate),
            f"Nonfinite EPSG:4326 coordinates in {role}")
    for geometry in geographic.geometry:
        if geometry.has_z:
            require(all(math.isfinite(float(value)) for coordinate in get_coordinates(geometry, include_z=True) for value in coordinate),
                    f"Nonfinite EPSG:4326 coordinates in {role}")
    require(all(-180 <= coordinate[0] <= 180 and -90 <= coordinate[1] <= 90 for coordinate in coordinates),
            f"EPSG:4326 coordinates outside longitude/latitude range in {role}")
    require(geographic.geometry.is_valid.all(), f"Invalid EPSG:4326 geometry in {role}")
    return geographic


def prepare(config_path):
    cfg = load_config(config_path)
    identities = {"config_sha256": cfg["_config_sha256"]}
    for role in ("districts", "zones", "national"):
        if cfg["inputs"].get(role) is not None:
            source = _source_path(cfg, role)
            require(source.is_file(), f"Missing {role} input: {cfg['inputs'][role]['path']}")
            identities[role] = _input_identity(cfg, role)
    districts, district_path = read_layer(cfg, "districts")
    require(_input_identity(cfg, "districts") == identities["districts"], "Input bundle changed during reading: districts")
    zones, zone_path = read_layer(cfg, "zones")
    require(_input_identity(cfg, "zones") == identities["zones"], "Input bundle changed during reading: zones")
    d_names, d_ids, d_codes = fields(districts, cfg["inputs"]["districts"], "districts")
    require(len(set(d_ids)) == len(d_ids), "Duplicate district IDs")
    z_names, z_ids, z_codes = fields(zones, cfg["inputs"]["zones"], "zones")
    districts = gpd.GeoDataFrame({"dist_id": d_ids, "dist_name": [n.upper() for n in d_names], "dist_code": d_codes}, geometry=districts.geometry.values, crs=districts.crs).sort_values("dist_id").reset_index(drop=True)
    zones = gpd.GeoDataFrame({"zone_id": z_ids, "zone_name": [n.upper() for n in z_names], "zone_code": z_codes}, geometry=zones.geometry.values, crs=zones.crs)
    for identifier, group in zones.groupby("zone_id", sort=True):
        require(group.zone_name.nunique() == 1 and group.zone_code.nunique() == 1, f"Inconsistent metadata for zone {identifier}")
    zones = zones.dissolve(by="zone_id", as_index=False).sort_values("zone_id").reset_index(drop=True)
    require(zones.zone_code.nunique() == len(zones), "Duplicate zone codes")
    crs_cfg = cfg.get("crs", {})
    working = CRS.from_user_input(crs_cfg.get("working", "EPSG:32630"))
    area_crs = CRS.from_user_input(crs_cfg.get("area", working))
    if crs_cfg.get("output"):
        try:
            output_crs = CRS.from_user_input(crs_cfg["output"])
        except CRSError as error:
            raise PrepError(f"Invalid output CRS: {error}") from error
        require(output_crs == CRS(districts.crs), "Output CRS must equal district source CRS to preserve original coordinates")
    d_work, z_work = project(districts, working, "districts"), project(zones, working, "zones")
    geographic_export(districts, "district GeoJSON preflight")
    tolerance = float(cfg.get("qa", {}).get("area_tolerance_m2", 1e-4))
    district_overlaps = positive_overlaps(d_work, tolerance)
    require(not district_overlaps, f"Districts have positive-area overlaps above numerical tolerance: {district_overlaps[:3]}")
    if "analysis" in crs_cfg:
        analysis_crs = CRS.from_user_input(crs_cfg["analysis"])
        if analysis_crs != working:
            # Independently transforming vertex chains can separate shared edges
            # when adjacent districts store different intermediate vertices.
            analysis_districts = project(districts, analysis_crs, "analysis districts preflight")
            analysis_overlaps = positive_overlaps(analysis_districts.set_index("dist_id"), tolerance)
            require(not analysis_overlaps,
                    f"Analysis districts have positive-area overlaps above numerical tolerance: {analysis_overlaps[:3]}")
    zone_overlaps = positive_overlaps(z_work, tolerance)
    warnings = []
    if zone_overlaps:
        warnings.append(f"Reference zones overlap in positive area: {len(zone_overlaps)} pairs")
    tie_tolerance = float(cfg.get("assignment", {}).get("tie_tolerance", 1e-12))
    warn_share = float(cfg.get("assignment", {}).get("warning_share", .5))
    warn_margin = float(cfg.get("assignment", {}).get("warning_margin", .05))
    overlap_rows, chosen_rows, coverage_rows = [], [], []
    reference_union = union_all(z_work.geometry.values)
    for i, row in d_work.iterrows():
        area = float(row.geometry.area)
        candidates = []
        for _, zone in z_work.iterrows():
            intersection = row.geometry.intersection(zone.geometry)
            intersection_area = float(intersection.area)
            if intersection_area > 0:
                share = intersection_area / area
                require(share <= 1 + 1e-9, f"Impossible reference overlap share: {row.dist_id}")
                candidates.append({"district_id": row.dist_id, "zone_id": zone.zone_id, "zone_code": zone.zone_code, "zone_name": zone.zone_name, "original_district_area_sq_km": area / 1e6, "overlap_area_sq_km": intersection_area / 1e6, "overlap_share": min(1.0, share)})
        require(candidates, f"District has no positive-area reference overlap: {row.dist_id}")
        candidates.sort(key=lambda r: (-r["overlap_share"], r["zone_id"], r["zone_name"]))
        highest = candidates[0]["overlap_share"]
        tied = [c for c in candidates if highest - c["overlap_share"] <= tie_tolerance]
        selected = sorted(tied, key=lambda r: (r["zone_id"], r["zone_name"]))[0]
        ranked = sorted(candidates, key=lambda r: (-r["overlap_share"], r["zone_id"], r["zone_name"]))
        other_shares = [c["overlap_share"] for c in candidates if c["zone_id"] != selected["zone_id"]]
        runner_up = max(other_shares, default=0.0)
        margin = selected["overlap_share"] - runner_up
        for rank, candidate in enumerate(ranked, start=1):
            candidate["rank"] = rank
            candidate["is_assigned"] = candidate["zone_id"] == selected["zone_id"]
            overlap_rows.append(candidate)
        chosen_rows.append({"district_id": row.dist_id, "district_name": row.dist_name, "district_code": row.dist_code, "zone_id": selected["zone_id"], "zone_code": selected["zone_code"], "zone_name": selected["zone_name"], "original_district_area_sq_km": area / 1e6, "dominant_overlap_area_sq_km": selected["overlap_area_sq_km"], "dominant_overlap_share": selected["overlap_share"], "assignment_method": "maximum reference-polygon overlap share", "working_crs": working.to_string(), "runner_up_share": runner_up, "assignment_margin": margin, "tie_candidate_count": len(tied), "assignment_status": "assigned_tie_break" if len(tied) > 1 else "assigned_maximum"})
        gap = max(0., area - float(row.geometry.intersection(reference_union).area))
        coverage_rows.append({"district_id": row.dist_id, "reference_coverage_share": max(0., min(1., 1 - gap / area)), "reference_gap_area_m2": gap, "sum_reference_overlap_share": sum(c["overlap_share"] for c in candidates)})
        if len(tied) > 1:
            warnings.append(f"Tie-break applied: {row.dist_id}")
        if selected["overlap_share"] < warn_share:
            warnings.append(f"Low selected reference overlap: {row.dist_id}")
        if other_shares and margin < warn_margin:
            warnings.append(f"Small assignment margin: {row.dist_id}")
        if gap > tolerance:
            warnings.append(f"Reference zones leave uncovered district area: {row.dist_id}")
    crosswalk = pd.DataFrame(chosen_rows).sort_values("district_id").reset_index(drop=True)
    overlaps = pd.DataFrame(overlap_rows).sort_values(["district_id", "rank", "zone_id"]).reset_index(drop=True)
    coverage = pd.DataFrame(coverage_rows).sort_values("district_id").reset_index(drop=True)
    used_zones = set(crosswalk.zone_id)
    unused_zones = sorted(set(zones.zone_id) - used_zones)
    if unused_zones:
        warnings.append("Reference zones with no assigned districts: " + ", ".join(unused_zones))
    for key, actual in (("districts", len(districts)), ("zones", len(used_zones))):
        if key in cfg.get("expected", {}):
            require(int(cfg["expected"][key]) == actual, f"Expected {cfg['expected'][key]} {key}, observed {actual}")
    require(not cfg.get("clip_to_aoi", False), "Whole-district method does not allow AOI clipping")
    national_identity, national_difference = None, None
    if cfg["inputs"].get("national"):
        national, national_path = read_layer(cfg, "national")
        require(_input_identity(cfg, "national") == identities["national"], "Input bundle changed during reading: national")
        national_identity = identities["national"]
        national_union = union_all(project(national, working, "national").geometry.values)
        national_difference = float(union_all(d_work.geometry.values).symmetric_difference(national_union).area)
        require(math.isfinite(national_difference), "Nonfinite national comparison area")
        if national_difference > tolerance:
            warnings.append("District union differs from national reference; no clipping was performed")
    summary = {"status": "WARN" if warnings else "PASS", "district_count": len(districts), "zone_count": len(used_zones), "warnings": warnings, "checks": {"input_geometry_valid": True, "unique_district_ids": True, "complete_assignment": True, "positive_area_district_overlap_pairs": len(district_overlaps), "reference_zone_overlap_pairs": len(zone_overlaps), "unused_reference_zones": unused_zones, "national_symmetric_difference_m2": national_difference, "area_tolerance_m2": tolerance, "whole_district_policy": True}, "zone_district_counts": dict(sorted(Counter(crosswalk.zone_code).items()))}
    _verify_input_identities(cfg, identities)
    require(sha256(cfg["_config_path"]) == cfg["_config_sha256"], "Configuration changed during input validation")
    return cfg, districts, crosswalk, overlaps, coverage, summary, identities, area_crs


def validate(config_path):
    """Read and validate all inputs and spatial assignments without writing files."""
    return prepare(config_path)[5]


def export_layer(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(path, driver="ESRI Shapefile", encoding="UTF-8", index=False)
    stored = gpd.read_file(path)
    require(len(stored) == len(frame), f"Round-trip feature count differs: {path.name}")
    require(CRS(stored.crs) == CRS(frame.crs), f"Round-trip CRS differs: {path.name}")
    require(all(a.equals(b) for a, b in zip(frame.geometry, stored.geometry)), f"Round-trip geometry differs: {path.name}")
    require(all(a.normalize().equals_exact(b.normalize(), tolerance=0) for a, b in zip(frame.geometry, stored.geometry)), f"Round-trip coordinates differ: {path.name}")
    attrs = stored.drop(columns=stored.geometry.name)
    for column in attrs.columns:
        if column in frame:
            expected = frame[column]
            actual = attrs[column]
            if pd.api.types.is_numeric_dtype(expected):
                require(all(math.isclose(float(a), float(b), abs_tol=1e-12, rel_tol=1e-12) for a,b in zip(expected, actual)), f"Round-trip values differ: {path.name}/{column}")
            else:
                require(list(expected.fillna("").astype(str)) == list(actual.fillna("").astype(str)), f"Round-trip attributes differ: {path.name}/{column}")
    write_csv(path.with_name(path.stem + "_attributes.csv"), attrs.fillna(""))
    geographic = geographic_export(stored, path.name)
    try:
        geojson = geographic.to_json(drop_id=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise PrepError(f"Cannot serialize strict GeoJSON for {path.name}: {error}") from error
    path.with_suffix(".geojson").write_text(geojson, encoding="utf-8")
    return stored


def plots(districts, zones, root):
    """Render the overview and individually named district maps."""
    from .plotting import render_plots
    return render_plots(districts, zones, root)


def environment():
    import platform
    import shapely
    import pyproj
    result = {"python": platform.python_version(), "GEOS": shapely.geos_version_string, "PROJ": pyproj.proj_version_str}
    for name in ("geopandas", "pandas", "shapely", "pyproj", "pyogrio", "matplotlib", "PyYAML"):
        result[name] = importlib.metadata.version(name)
    return result


def run(config_path, run_id):
    """Generate a complete isolated run, publishing only after all checks pass."""
    require(isinstance(run_id, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id)) and run_id not in (".", ".."), "Unsafe run ID")
    require(not run_id.endswith(".") and not re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", run_id.split(".", 1)[0].casefold()),
            "Run ID must be portable: no reserved Windows basename or trailing dot")
    cfg = load_config(config_path)
    starting_config_sha256 = cfg["_config_sha256"]
    starting_code_parts = {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    output_root = (cfg["_root"] / cfg.get("outputs", {}).get("root", "out")).resolve()
    target = output_root / run_id
    require(not target.exists(), f"Output already exists: {run_id}; select a new run ID")
    cfg, districts, crosswalk, overlaps, coverage, summary, identities, area_crs = prepare(config_path)
    require(identities["config_sha256"] == starting_config_sha256, "Configuration changed during input validation")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".geo-prep-", dir=output_root))
    try:
        cross_dir = temporary / "crosswalks"
        for name in ("district_zone_crosswalk.csv", "district_to_acz_max_overlap.csv"):
            write_csv(cross_dir / name, crosswalk)
        # The serialized assignment table is the actual input to boundary construction.
        pairing = pd.read_csv(cross_dir / "district_zone_crosswalk.csv", keep_default_na=False, dtype={"district_id": str, "zone_id": str, "zone_code": str, "zone_name": str})
        require(pairing.district_id.is_unique and set(pairing.district_id) == set(districts.dist_id), "Serialized assignment keys differ")
        enriched = districts.merge(pairing[["district_id", "zone_id", "zone_name", "zone_code", "dominant_overlap_share"]], left_on="dist_id", right_on="district_id", validate="one_to_one")
        enriched = enriched.drop(columns="district_id").rename(columns={"dominant_overlap_share": "ovl_share"})
        enriched["cov_share"] = 1.0
        enriched = enriched[["dist_id", "dist_name", "dist_code", "zone_id", "zone_name", "zone_code", "ovl_share", "cov_share", "geometry"]].sort_values("dist_id").reset_index(drop=True)
        stored_districts = export_layer(enriched, temporary / "boundaries/districts_within_acz.shp")
        zone_records = []
        for identifier, group in stored_districts.groupby("zone_id", sort=True):
            geom = union_all(group.geometry.values)
            require(not geom.is_empty and geom.is_valid, f"Invalid dissolved zone: {identifier}")
            zone_records.append({"zone_id": identifier, "zone_name": group.zone_name.iloc[0], "zone_code": group.zone_code.iloc[0], "geometry": geom})
        generated_zones = gpd.GeoDataFrame(zone_records, crs=districts.crs)
        stored_zones = export_layer(generated_zones, temporary / "boundaries/acz.shp")
        hierarchy = []
        for _, zone in stored_zones.iterrows():
            assigned = stored_districts[stored_districts.zone_id == zone.zone_id]
            reconstructed = union_all(assigned.geometry.values)
            require(zone.geometry.equals(reconstructed), f"Zone does not equal assigned district union: {zone.zone_id}")
            require(all(zone.geometry.covers(g) for g in assigned.geometry), f"Zone does not cover district: {zone.zone_id}")
            hierarchy.append({"zone_id": zone.zone_id, "district_count": len(assigned), "exact_union_equal": True, "all_districts_covered": True})
        require(union_all(stored_zones.geometry.values).equals(union_all(stored_districts.geometry.values)), "National reporting union differs")
        analysis_handoff = None
        if "analysis" in cfg.get("crs", {}):
            analysis_crs = CRS.from_user_input(cfg["crs"]["analysis"])
            # Reproject complete districts first; dissolve the serialized projected
            # districts, so parent/child boundaries have the same coordinates.
            projected = project(stored_districts, analysis_crs, "analysis districts")
            analysis_district_path = temporary / "analysis_boundaries/districts_within_acz.shp"
            analysis_zone_path = temporary / "analysis_boundaries/acz.shp"
            analysis_districts = export_layer(projected, analysis_district_path)
            analysis_records = []
            for identifier, group in analysis_districts.groupby("zone_id", sort=True):
                geometry = union_all(group.geometry.values)
                require(not geometry.is_empty and geometry.is_valid, f"Invalid projected dissolved zone: {identifier}")
                analysis_records.append({"zone_id": identifier, "zone_name": group.zone_name.iloc[0],
                                         "zone_code": group.zone_code.iloc[0], "geometry": geometry})
            analysis_zones = export_layer(gpd.GeoDataFrame(analysis_records, crs=analysis_crs), analysis_zone_path)
            analysis_hierarchy = []
            for _, zone in analysis_zones.iterrows():
                assigned = analysis_districts[analysis_districts.zone_id == zone.zone_id]
                reconstructed = union_all(assigned.geometry.values)
                require(zone.geometry.equals(reconstructed), f"Projected zone does not equal assigned district union: {zone.zone_id}")
                require(all(zone.geometry.covers(g) for g in assigned.geometry), f"Projected zone does not cover district: {zone.zone_id}")
                analysis_hierarchy.append({"zone_id": zone.zone_id, "district_count": len(assigned),
                                           "exact_union_equal": True, "all_districts_covered": True})
            require(union_all(analysis_zones.geometry.values).equals(union_all(analysis_districts.geometry.values)), "Projected reporting union differs")
            write_csv(temporary / "qa/analysis_hierarchy.csv", pd.DataFrame(analysis_hierarchy))
            analysis_handoff = {"crs": analysis_crs.to_string(),
                "districts_relative_path": "analysis_boundaries/districts_within_acz.shp",
                "zones_relative_path": "analysis_boundaries/acz.shp",
                "district_source": "boundaries/districts_within_acz.shp",
                "construction": "Reproject native exported districts; serialize; dissolve projected districts by assigned zone",
                "district_bundle": bundle(analysis_district_path), "zone_bundle": bundle(analysis_zone_path),
                "exact_parent_district_union": True}
        area_districts = project(stored_districts, area_crs, "output districts").area / 1e6
        area_zones = project(stored_zones, area_crs, "output zones").area / 1e6
        units = []
        for i, zone in stored_zones.iterrows():
            units.append(["zone", "acz", zone.zone_id, zone.zone_code, zone.zone_name, "", "", "", "", float(area_zones.iloc[i])])
        for i, district in stored_districts.iterrows():
            units.append(["district", "district", district.dist_id, district.dist_code or "", district.dist_name, "acz", district.zone_id, district.zone_code, district.zone_name, float(area_districts.iloc[i])])
        write_csv(temporary / "unit_universe.csv", pd.DataFrame(units, columns=UNIT_COLUMNS))
        write_csv(temporary / "qa/district_zone_overlap.csv", overlaps)
        write_csv(temporary / "qa/reference_coverage.csv", coverage)
        write_csv(temporary / "qa/constructed_hierarchy.csv", pd.DataFrame(hierarchy))
        if cfg.get("outputs", {}).get("splits", True):
            for _, zone in stored_zones.iterrows():
                identifier = zone.zone_id
                selected = stored_districts[stored_districts.zone_id == identifier]
                export_layer(stored_zones[stored_zones.zone_id == identifier], temporary / f"splits/zones_split/acz__zone_{identifier}.shp")
                export_layer(selected, temporary / f"splits/zone_districts/districts_within_acz__zone_{identifier}.shp")
                write_csv(temporary / f"district_lists/{identifier}.csv", selected.drop(columns="geometry").fillna(""))
        if cfg.get("outputs", {}).get("plots", True):
            plots(stored_districts, stored_zones, temporary / "plots")
        code_parts = {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
        implementation_hash = hashlib.sha256(json.dumps(code_parts, sort_keys=True).encode()).hexdigest()
        provenance = {"schema": "district-to-zone-crosswalk-provenance-v1", "crosswalk": {"relative_path": "crosswalks/district_to_acz_max_overlap.csv", "sha256": sha256(cross_dir / "district_to_acz_max_overlap.csv"), "rows": len(crosswalk)}, "analysis_crs": cfg.get("crs", {}).get("working", "EPSG:32630"), "source_district_geometry": identities["districts"], "source_acz_geometry": identities["zones"], "implementation_identity": f"geo_data_prep.pipeline.prepare:{implementation_hash}", "assignment_method": "maximum reference-polygon overlap share", "share_definition": "area(original district intersect reference zone) / area(original district)", "tie_tolerance": float(cfg.get("assignment", {}).get("tie_tolerance", 1e-12)), "tie_break": "lexicographically smallest zone_id then zone_name within tie tolerance"}
        write_json(cross_dir / "district_to_acz_max_overlap.provenance.json", provenance)
        summary["checks"].update({"serialized_geometry_verified": True, "exact_parent_district_union": True, "input_coordinates_preserved": True, "handoff_eligible": True})
        if analysis_handoff:
            summary["checks"].update({"analysis_crs": analysis_handoff["crs"], "analysis_exact_parent_district_union": True})
        summary["eligibility_scope"] = "Structural geography handoff; scientific review and downstream input compatibility are separate"
        summary["reporting_zone_role"] = "RP1 acz level and basenames identify the reporting-zone interface; the configured reference layer defines its scientific meaning"
        summary["environment"] = environment()
        write_json(temporary / "qa/qa_summary.json", summary)
        write_json(temporary / "inputs_fingerprint.json", identities)
        write_json(temporary / "environment.json", environment())
        config_public = {k: v for k, v in cfg.items() if not k.startswith("_")}
        write_json(temporary / "run_configuration.json", config_public)
        write_json(temporary / "contract/stage1_contract_manifest.json", {"name": "geo_data_prep", "version": __version__, "run_id": run_id, "unit_universe_columns": UNIT_COLUMNS, "district_id_field": "dist_id", "zone_id_field": "zone_id", "geometry_crs": CRS(districts.crs).to_string(), "analysis_handoff": analysis_handoff, "area_crs": area_crs.to_string(), "area_units": "sq_km", "ovl_share_definition": "Reference-zone overlap share used for assignment", "cov_share_definition": "Full original district covered by constructed zone", "whole_district_policy": "No clipping, snapping, buffering, simplification or repair", "handoff_eligible": True, "qa_status": summary["status"], "eligibility_scope": summary["eligibility_scope"], "reporting_zone_role": summary["reporting_zone_role"], "implementation_sha256": implementation_hash})
        files = {p.relative_to(temporary).as_posix(): {"sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(temporary.rglob("*")) if p.is_file()}
        write_json(temporary / "outputs_manifest.json", {"schema": "geo-data-output-manifest-v1", "run_id": run_id, "created_utc": datetime.now(timezone.utc).isoformat(), "files": files, "excludes": ["outputs_manifest.json"]})
        require(starting_code_parts == code_parts, "Implementation changed during generation")
        require(sha256(cfg["_config_path"]) == starting_config_sha256, "Configuration changed during generation")
        _verify_input_identities(cfg, identities)
        require(not target.exists(), "Output appeared while run was in progress")
        os.rename(temporary, target)
        return target
    except BaseException:
        # Clean interrupted runs as well as ordinary failures; forced process kills cannot execute cleanup.
        shutil.rmtree(temporary, ignore_errors=True)
        raise
