"""Governed source admission and lossless Archive SP interface conversion.

The native FIRMS reader remains unchanged. The Archive profile validates its
upstream lineage before presenting native field names to that reader; it never
changes RP1's selection, spatial joins, deduplication or FRP statistics.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS

from mv_firms_panels.core.config import FirmsSensorInput
from mv_firms_panels.core.archive_authority import INTAKE_V2, child, validate_v2_authority
from mv_firms_panels.core.hashing import sha256_file, sha256_text, stable_json_dumps

ARCHIVE_PROFILE = "ghana_firms_archive_sp_v1"
INTAKE_SCHEMA = "rp1_firms_archive_sp_intake_v1"
FAMILY_SUFFIXES = {".shp", ".shx", ".dbf", ".prj", ".cpg"}
EXPECTED = {
    "modis": {
        "source": "MODIS_SP",
        "instrument": "MODIS",
        "platforms": {"Terra", "Aqua"},
        "versions": {"6.2", "6.03", "61.03"},
    },
    "viirs": {
        "source": "VIIRS_SNPP_SP",
        "instrument": "VIIRS",
        "platforms": {"Suomi-NPP"},
        "versions": {"2"},
    },
}
REQUIRED_FIELDS = {
    "obs_id",
    "acq_date",
    "time_utc",
    "platform",
    "instrument",
    "confidence",
    "conf_raw",
    "frp_mw",
    "bright_k",
    "bright_aux",
    "daynight",
    "district",
    "zone",
    "scan_km",
    "track_km",
    "source",
    "processing",
    "version",
    "fire_type",
}


class InputProfileError(ValueError):
    """A source is outside the declared and hash-bound input contract."""


def _inside(root: Path, value: object) -> Path:
    try:
        return child(root, value)
    except ValueError as exc:
        raise InputProfileError(f"Archive authority path escapes the project or is unsafe: {value}") from exc


def _bundle_root(input_config: FirmsSensorInput, repo_root: Path) -> Path:
    project = Path(repo_root).resolve()
    return _inside(project, input_config.admission_bundle_root) if input_config.admission_bundle_root else project


def _verify_file(root: Path, identity: dict, *, label: str) -> Path:
    if not isinstance(identity, dict):
        raise InputProfileError(f"Invalid {label} identity")
    path = _inside(root, identity.get("path"))
    if not path.is_file():
        raise InputProfileError(f"Missing {label}: {identity.get('path')}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(identity.get("sha256", ""))):
        raise InputProfileError(f"Invalid {label} SHA256")
    if sha256_file(path) != identity["sha256"]:
        raise InputProfileError(f"Changed {label}: {identity['path']}")
    if identity.get("size_bytes") != path.stat().st_size:
        raise InputProfileError(f"Changed {label} byte size: {identity['path']}")
    return path


def _admission(
    *, input_config: FirmsSensorInput, repo_root: Path, sensor: str, year: int, points_path: Path
) -> tuple[dict, Path, dict]:
    if sensor not in EXPECTED:
        raise InputProfileError(f"Unsupported Archive SP sensor: {sensor}")
    root = _bundle_root(input_config, repo_root)
    manifest_path = _inside(root, input_config.admission_manifest)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputProfileError(f"Cannot read Archive admission manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") not in {INTAKE_SCHEMA, INTAKE_V2}:
        raise InputProfileError("Unknown Archive admission manifest schema")
    if manifest.get("input_profile") != ARCHIVE_PROFILE:
        raise InputProfileError("Archive admission manifest profile mismatch")
    admission = None
    if manifest["schema"] == INTAKE_V2:
        try:
            admission = validate_v2_authority(root, manifest)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise InputProfileError(f"Archive validation acceptance changed or is invalid: {exc}") from exc
    _verify_file(root, manifest.get("archive_export"), label="Archive annual-export authority")
    families = manifest.get("families")
    if not isinstance(families, list):
        raise InputProfileError("Archive manifest requires families")
    if admission is not None:
        keys = [(entry.get("source"), entry.get("year")) for entry in families if isinstance(entry, dict)]
        if len(keys) != len(families) or len(set(keys)) != len(keys) or set(keys) != set(admission["required"]):
            raise InputProfileError("Archive families differ from accepted study selection")
    selected = [
        entry
        for entry in families
        if isinstance(entry, dict)
        and entry.get("sensor") == sensor
        and entry.get("year") == int(year)
    ]
    if len(selected) != 1:
        raise InputProfileError(f"Expected exactly one admitted {sensor} {year} family")
    family = selected[0]
    declared = _inside(root, family.get("path"))
    if declared != Path(points_path).resolve() or declared.suffix.lower() != ".shp":
        raise InputProfileError("Resolved source differs from the admitted annual shapefile")
    if not re.search(rf"(?<!\d){int(year)}(?!\d)", declared.stem):
        raise InputProfileError("Admitted filename does not identify the selected year")
    count = family.get("record_count")
    if type(count) is not int or count < 0:
        raise InputProfileError("Invalid admitted record_count")
    expected = EXPECTED[sensor]
    if family.get("source") != expected["source"] or family.get("processing") != "SP":
        raise InputProfileError("Archive family product/processing mismatch")
    platforms = family.get("platforms")
    versions = family.get("allowed_versions", family.get("versions"))
    if (
        not isinstance(platforms, list)
        or (not platforms and not (count == 0 and admission is not None))
        or not set(platforms) <= expected["platforms"]
    ):
        raise InputProfileError("Archive family platform admission mismatch")
    if not isinstance(versions, list) or not versions or not set(versions) <= expected["versions"]:
        raise InputProfileError("Archive family version admission mismatch")
    components = family.get("components")
    if not isinstance(components, list) or len(components) != len(FAMILY_SUFFIXES):
        raise InputProfileError("Archive family requires exactly five component identities")
    admitted_paths = []
    for identity in components:
        path = _verify_file(root, identity, label="Archive component")
        if path.parent != declared.parent or path.stem != declared.stem:
            raise InputProfileError("Archive component is outside its annual family")
        admitted_paths.append(path)
        if admission is not None:
            member = admission["artifacts"][(expected["source"], year)]["members"].get(path.name)
            if not member or any(identity.get(k) != member.get(k) for k in ("sha256", "size_bytes")):
                raise InputProfileError("Archive component differs from validation-accepted ZIP member")
    if {p.suffix.lower() for p in admitted_paths} != FAMILY_SUFFIXES:
        raise InputProfileError("Archive family component extensions are incomplete or duplicated")
    actual = {p.resolve() for p in declared.parent.glob(declared.stem + ".*") if p.is_file()}
    if actual != set(admitted_paths):
        raise InputProfileError("Archive family has missing or unadmitted components")
    if declared.with_suffix(".cpg").read_text(encoding="ascii").strip().upper() not in {
        "UTF-8",
        "UTF8",
        "65001",
    }:
        raise InputProfileError("Archive family encoding must be UTF-8")
    for companion in ("provenance", "field_dictionary"):
        _verify_file(root, family.get(companion), label=f"Archive {companion}")
    if admission is not None:
        key = (expected["source"], year)
        part, export = admission["partitions"][key], admission["exports"][key]
        provenance = json.loads(_inside(root, family["provenance"]["path"]).read_text(encoding="utf-8"))
        if (count != part["record_count"] or family.get("instrument") != expected["instrument"]
                or provenance.get("contract") != "ghana-firms-gee-annual-v1"
                or provenance.get("accepted_partition") != part or provenance.get("export") != export
                or provenance.get("research_manifest_sha256") != admission["documents"]["annual_export"]["research_manifest_sha256"]
                or family.get("archive_zip", {}).get("sha256") != export["sha256"]
                or family.get("archive_zip", {}).get("path") != export["annual_shapefile_zip"]):
            raise InputProfileError("Archive family provenance differs from validation acceptance")
        if count == 0 and (family.get("platforms") or family.get("versions") or part.get("source_versions")):
            raise InputProfileError("Empty Archive family must preserve empty observed lineage")
    return family, manifest_path, manifest


def source_profile_evidence(
    *, input_config: FirmsSensorInput, repo_root: Path, sensor: str, year: int, points_path: Path
) -> dict:
    """Recompute file-backed input-profile identity, also used by reuse checks."""
    if input_config.input_profile == "native_firms_v1":
        return {"profile": "native_firms_v1"}
    if input_config.input_profile != ARCHIVE_PROFILE:
        raise InputProfileError(f"Unsupported input profile: {input_config.input_profile}")
    family, manifest_path, manifest = _admission(
        input_config=input_config,
        repo_root=repo_root,
        sensor=sensor,
        year=year,
        points_path=points_path,
    )
    root = _bundle_root(input_config, repo_root)
    evidence_records = [manifest["archive_export"], family["provenance"], family["field_dictionary"]]
    if manifest["schema"] == INTAKE_V2:
        evidence_records += [manifest["acceptance"], *manifest["source_evidence"]]
    source_evidence = []
    for record in evidence_records:
        entry = dict(record)
        entry["path"] = _inside(root, record["path"]).relative_to(Path(repo_root).resolve()).as_posix()
        if entry not in source_evidence:
            source_evidence.append(entry)
    result = {
        "profile": ARCHIVE_PROFILE,
        "admission_manifest": manifest_path.relative_to(Path(repo_root).resolve()).as_posix(),
        "admission_manifest_sha256": sha256_file(manifest_path),
        "family_sha256": sha256_text(stable_json_dumps(family)),
        "archive_export": manifest["archive_export"],
        "family_path": family["path"],
        "sensor": sensor,
        "year": int(year),
        "source_evidence": source_evidence,
    }
    if manifest["schema"] == INTAKE_V2:
        result.update({"study": manifest["study"], "selected_coverage": manifest["selected_coverage"],
                       "validation_acceptance": next(r for r in source_evidence if r["path"].endswith("/acceptance.json"))})
    return result


def adapt_archive_sp(
    *,
    points: gpd.GeoDataFrame,
    input_config: FirmsSensorInput,
    repo_root: Path,
    sensor: str,
    year: int,
    points_path: Path,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Validate every Archive observation and return a native FIRMS field view."""
    family, _, _ = _admission(
        input_config=input_config,
        repo_root=repo_root,
        sensor=sensor,
        year=year,
        points_path=points_path,
    )
    missing = sorted(REQUIRED_FIELDS - set(points.columns))
    if missing:
        raise InputProfileError(f"Missing Archive SP fields: {missing}")
    if len(points) != family["record_count"]:
        raise InputProfileError("Archive record count differs from admitted annual family")
    if not points.index.is_unique:
        raise InputProfileError("Archive observation row index must be unique")
    if points.crs is None or not CRS(points.crs).equals(
        CRS.from_epsg(4326), ignore_axis_order=True
    ):
        raise InputProfileError("Archive points require declared WGS84 EPSG:4326 CRS")
    geometry = points.geometry
    if (
        geometry.isna().any()
        or geometry.is_empty.any()
        or not geometry.geom_type.eq("Point").all()
        or geometry.has_z.any()
    ):
        raise InputProfileError("Archive geometries must all be finite nonempty 2D Points")
    x, y = geometry.x, geometry.y
    if not (
        np.isfinite(x).all()
        and np.isfinite(y).all()
        and x.between(-180, 180).all()
        and y.between(-90, 90).all()
    ):
        raise InputProfileError("Archive coordinate values are nonfinite or outside WGS84 bounds")
    for field, coordinate in (("LATITUDE", y), ("latitude", y), ("LONGITUDE", x), ("longitude", x)):
        if field in points:
            supplied = pd.to_numeric(points[field], errors="coerce")
            if not np.array_equal(supplied.to_numpy(), coordinate.to_numpy()):
                raise InputProfileError(f"Archive {field} conflicts with point geometry")
    for field in REQUIRED_FIELDS - {
        "frp_mw",
        "bright_k",
        "bright_aux",
        "scan_km",
        "track_km",
        "district",
        "zone",
    }:
        if points[field].isna().any() or points[field].astype(str).str.strip().eq("").any():
            raise InputProfileError(f"Archive {field} contains missing/blank values")
    if points["obs_id"].astype(str).duplicated().any():
        raise InputProfileError("Archive obs_id values must be unique")
    dates = points["acq_date"].astype(str)
    if not dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise InputProfileError("Archive acquisition dates require exact ISO dates")
    parsed = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any() or not parsed.dt.year.eq(int(year)).all():
        raise InputProfileError("Archive acquisition date is invalid or outside selected year")
    clock = points["time_utc"].astype(str)
    if not clock.str.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d").all():
        raise InputProfileError("Archive time_utc requires a valid exact HH:MM UTC clock")
    expected = EXPECTED[sensor]
    for field, allowed in (
        ("source", {expected["source"]}),
        ("processing", {"SP"}),
        ("instrument", {expected["instrument"]}),
        ("platform", set(family["platforms"])),
        ("version", set(family.get("allowed_versions", family.get("versions")))),
        ("daynight", {"D", "N"}),
    ):
        if not points[field].astype(str).isin(allowed).all():
            raise InputProfileError(f"Archive {field} is outside admitted source values")
    types = pd.to_numeric(points["fire_type"], errors="coerce")
    if not types.isin([0, 1, 2, 3]).all():
        raise InputProfileError("Archive fire_type requires valid numeric TYPE 0..3")
    frp = pd.to_numeric(points["frp_mw"], errors="coerce")
    if not np.isfinite(frp).all() or (frp < 0).any():
        raise InputProfileError("Archive frp_mw must be finite, nonmissing and nonnegative")
    raw = points["conf_raw"].astype(str)
    if sensor == "modis":
        native = pd.to_numeric(raw, errors="coerce")
        if not np.isfinite(native).all() or not native.between(0, 100).all():
            raise InputProfileError("Archive MODIS conf_raw requires numeric confidence 0..100")
        harmonized = pd.Series(
            np.select([native < 30, native >= 80], ["low", "high"], default="nominal"),
            index=points.index,
        )
    else:
        # Match the producer's case-insensitive aliases while retaining the raw value.
        harmonized = raw.str.strip().str.lower().map({
            "l": "low", "n": "nominal", "h": "high",
            "low": "low", "nominal": "nominal", "high": "high",
        })
        if harmonized.isna().any():
            raise InputProfileError("Archive VIIRS conf_raw requires l/n/h or low/nominal/high")
    if not points["confidence"].astype(str).eq(harmonized).all():
        raise InputProfileError("Archive harmonized confidence disagrees with conf_raw")
    work = points.copy()
    for name, values in {
        "LATITUDE": y,
        "LONGITUDE": x,
        "ACQ_DATE": dates,
        "ACQ_TIME": clock.str.replace(":", "", regex=False),
        "CONFIDENCE": raw,
        "FRP": frp,
        "TYPE": types,
        "DAYNIGHT": points["daynight"],
        "SATELLITE": points["platform"].replace({"Suomi-NPP": "N"}),
    }.items():
        work[name] = values
    profile = {
        "n_points": len(points),
        "source": expected["source"],
        "processing": "SP",
        "platform_counts": points["platform"].value_counts().sort_index().to_dict(),
        "version_counts": points["version"].value_counts().sort_index().to_dict(),
        "upstream_country_filtered": True,
        "upstream_measurement_deduplicated": True,
        "coordinate_origin": "verified_epsg4326_point_geometry",
        "clock_conversion": "HH:MM_to_HHMM_exact",
        "frp_values_preserved": True,
    }
    return work, profile
