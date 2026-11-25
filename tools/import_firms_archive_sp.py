#!/usr/bin/env python3
"""Verify, stage and activate an Archive SP input release without overwriting inputs.

Staging binds curated shapefile bytes to an accepted Archive annual export. Activation
preserves the complete previous sensor directories outside the FIRMS project and
restores them if activation fails. Scientific preparation/analysis is a separate run.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIRMS_ROOT = ROOT / "RP1_Project/rp1_mv_firms_panels"
_io_spec = importlib.util.spec_from_file_location("_rp1_intake_local_io", ROOT / "RP1_Project/rp1_local_io.py")
_local_io = importlib.util.module_from_spec(_io_spec)
_io_spec.loader.exec_module(_local_io)
publish_directory_no_replace = _local_io.publish_directory_no_replace
preflight_directory_publication = _local_io.preflight_directory_publication
PROFILE = "ghana_firms_archive_sp_v1"
SCHEMA = "rp1_firms_archive_sp_intake_v1"
SCHEMA_V2 = "rp1_firms_archive_sp_intake_v2"
AUTHORITY = "data/raw/source_provenance/archive_sp_intake.json"
EXTENSIONS = (".shp", ".shx", ".dbf", ".prj", ".cpg")
SENSORS = {
    "modis": {"folder": "MODIS_SP", "archive_folder": "MODIS", "prefix": "Ghana_MODIS_SP_",
              "source": "MODIS_SP", "instrument": "MODIS", "platforms": {"Terra", "Aqua"},
              "versions": {"6.2", "6.03", "61.03"}},
    "viirs": {"folder": "VIIRS_SP", "archive_folder": "VIIRS", "prefix": "Ghana_VIIRS_SNPP_SP_",
              "source": "VIIRS_SNPP_SP", "instrument": "VIIRS", "platforms": {"Suomi-NPP"},
              "versions": {"2"}},
}
_authority_spec = importlib.util.spec_from_file_location(
    "_rp1_archive_authority", FIRMS_ROOT / "src/mv_firms_panels/core/archive_authority.py")
_authority = importlib.util.module_from_spec(_authority_spec)
_authority_spec.loader.exec_module(_authority)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or "\\" in value or ":" in value or path.is_absolute()
            or ".." in path.parts or path.as_posix() != value):
        raise ValueError("Unsafe relative input path: " + str(value))
    return value


def identity(path: Path, relative: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked source file: " + str(path))
    return {"path": relative_path(relative), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def dbf_lineage(path: Path) -> dict:
    """Read record count and lineage without requiring a geospatial environment."""
    wanted = {"source", "processing", "platform", "version", "instrument"}
    values = {name: set() for name in wanted}
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise ValueError("Truncated DBF header: " + str(path))
        count, header_size, record_size = struct.unpack_from("<IHH", header, 4)
        if header_size < 33 or (header_size - 33) % 32 or record_size < 2:
            raise ValueError("Invalid DBF structure: " + str(path))
        fields, offset = {}, 1
        for _ in range((header_size - 33) // 32):
            field = stream.read(32)
            name = field[:11].split(b"\0", 1)[0].decode("ascii")
            size = field[16]
            fields[name] = (offset, offset + size)
            offset += size
        if offset != record_size or stream.read(1) != b"\r" or not wanted.issubset(fields):
            raise ValueError("DBF does not contain the Archive lineage schema: " + str(path))
        for _ in range(count):
            record = stream.read(record_size)
            if len(record) != record_size or record[:1] != b" ":
                raise ValueError("Truncated/deleted DBF record: " + str(path))
            for name in wanted:
                start, end = fields[name]
                values[name].add(record[start:end].decode("utf-8").strip())
    return {"record_count": count, **{key: sorted(value) for key, value in values.items()}}


def inspect_curated(curated: Path, annual: Path) -> dict:
    curated, annual = curated.resolve(), annual.resolve()
    authority = annual / "annual-export.json"
    export = json.loads(authority.read_text(encoding="utf-8"))
    if export.get("contract") != "ghana-firms-gee-annual-export-v1":
        raise ValueError("Unrecognised Archive annual export authority")
    indexes = {}
    for row in export["partitions"]:
        key = (row["source"], int(row["year"]))
        if key in indexes:
            raise ValueError("Duplicate Archive source/year")
        indexes[key] = row
    families = []
    for sensor, spec in SENSORS.items():
        source = curated / spec["folder"]
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Missing/linked curated sensor directory: " + str(source))
        expected = set()
        candidates = sorted(source.glob(spec["prefix"] + "*.shp"))
        if not candidates:
            raise ValueError("No curated annual shapefiles for " + sensor)
        for shp in candidates:
            match = re.fullmatch(re.escape(spec["prefix"]) + r"(\d{4})\.shp", shp.name)
            if not match:
                raise ValueError("Invalid annual basename: " + shp.name)
            year = int(match[1])
            row = indexes.get((spec["source"], year))
            if not row or row.get("gee_upload_ready") is not True:
                raise ValueError("Annual source/year is not admitted by Archive: " + shp.name)
            zip_relative = relative_path(row["annual_shapefile_zip"])
            archive_zip = annual / zip_relative
            if sha(archive_zip) != row["sha256"]:
                raise ValueError("Archive ZIP identity differs: " + zip_relative)
            components = []
            with zipfile.ZipFile(archive_zip) as archive:
                names = [shp.stem + ext for ext in EXTENSIONS]
                if len(archive.namelist()) != len(names) or set(archive.namelist()) != set(names):
                    raise ValueError("ZIP has unexpected or missing shapefile components")
                for ext in EXTENSIONS:
                    component = shp.with_suffix(ext)
                    expected.add(component.name)
                    record = identity(component, f"data/raw/{sensor}/{component.name}")
                    digest = hashlib.sha256()
                    with archive.open(component.name) as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                    if digest.hexdigest() != record["sha256"]:
                        raise ValueError("Curated component differs from Archive: " + component.name)
                    components.append(record)
            lineage = dbf_lineage(shp.with_suffix(".dbf"))
            if (lineage["record_count"] != row["records"] or lineage["source"] != [spec["source"]]
                    or lineage["processing"] != ["SP"] or lineage["instrument"] != [spec["instrument"]]
                    or not set(lineage["platform"]).issubset(spec["platforms"])
                    or not set(lineage["version"]).issubset(spec["versions"])
                    or "" in lineage["platform"] or "" in lineage["version"]):
                raise ValueError("Invalid SP lineage/count: " + shp.name)
            metadata = annual / "metadata" / spec["archive_folder"]
            provenance_file = metadata / (shp.stem + "_provenance.json")
            dictionary_file = metadata / (shp.stem + "_fields.json")
            provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
            accepted = provenance.get("accepted_partition", {})
            if (provenance.get("contract") != "ghana-firms-gee-annual-v1"
                    or provenance.get("export") != row
                    or accepted.get("source") != spec["source"] or accepted.get("year") != year
                    or accepted.get("processing_status") != "SP"
                    or accepted.get("record_count") != lineage["record_count"]
                    or accepted.get("shapefile_sha256") != row["sha256"]
                    or set(accepted.get("source_versions", [])) != set(lineage["version"])):
                raise ValueError("Archive provenance does not bind annual export: " + shp.name)
            dictionary = json.loads(dictionary_file.read_text(encoding="utf-8"))
            if not {"obs_id", "conf_raw", "fire_type", "source", "processing", "time_utc"}.issubset(dictionary):
                raise ValueError("Incomplete Archive field dictionary")
            base = "data/raw/source_provenance/" + sensor + "/"
            families.append({
                "sensor": sensor, "year": year, "path": f"data/raw/{sensor}/{shp.name}",
                "basename": shp.stem, "record_count": lineage["record_count"],
                "source": spec["source"], "processing": "SP", "instrument": spec["instrument"],
                "platforms": lineage["platform"], "versions": lineage["version"],
                "allowed_versions": lineage["version"], "components": components,
                "archive_zip": {"path": zip_relative, "sha256": row["sha256"],
                                "size_bytes": archive_zip.stat().st_size},
                "provenance": identity(provenance_file, base + provenance_file.name),
                "field_dictionary": identity(dictionary_file, base + dictionary_file.name),
                "lineage": {"source_sha256": accepted.get("source_sha256"),
                            "research_manifest_sha256": provenance.get("research_manifest_sha256"),
                            "coverage_start": accepted.get("coverage_start"),
                            "coverage_end": accepted.get("coverage_end"),
                            "archive_preprocessing": "country_filter_validation_measurement_deduplication"},
            })
        actual = {path.name for path in source.iterdir()}
        if actual != expected:
            raise ValueError("Unexpected curated files: " + repr(sorted(actual ^ expected)))
    return {"schema": SCHEMA, "input_profile": PROFILE,
            "archive_export": identity(authority, "data/raw/source_provenance/annual-export.json"),
            "study_selection": {"modis": [2001, 2024], "viirs": [2012, 2024]},
            "families": families}


def verify_bundle(root: Path, *, study: dict | None = None) -> dict:
    root = root.resolve()
    manifest_path = root / AUTHORITY
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") not in {SCHEMA, SCHEMA_V2} or manifest.get("input_profile") != PROFILE:
        raise ValueError("Unrecognised intake authority")
    admission = None
    if manifest["schema"] == SCHEMA_V2:
        admission = _authority.validate_v2_authority(root, manifest, study=study)
    elif study is not None:
        raise ValueError("Study-scoped verification requires validation acceptance v2")
    if not manifest.get("families"):
        raise ValueError("Empty intake authority")
    checked, keys, expected = 0, set(), {sensor: set() for sensor in SENSORS}
    companions = [manifest["archive_export"]]
    for family in manifest["families"]:
        sensor, year = family["sensor"], family["year"]
        if sensor not in SENSORS or (sensor, year) in keys:
            raise ValueError("Unknown or duplicate admitted sensor/year")
        keys.add((sensor, year))
        shp = Path(relative_path(family["path"]))
        if shp.parent.as_posix() != f"data/raw/{sensor}" or shp.suffix != ".shp":
            raise ValueError("Family outside sensor directory")
        names = {shp.with_suffix(ext).as_posix() for ext in EXTENSIONS}
        if len(family["components"]) != 5 or {r["path"] for r in family["components"]} != names:
            raise ValueError("Incomplete admitted shapefile family")
        expected[sensor].update(names)
        companions += [family["provenance"], family["field_dictionary"]]
        for record in family["components"]:
            check_identity(root, record)
            checked += 1
        if admission is not None:
            _verify_archive_family(root, family, admission)
    for record in companions:
        check_identity(root, record)
    for sensor in SENSORS:
        actual = {path.relative_to(root).as_posix() for path in (root / "data/raw" / sensor).iterdir()}
        if actual != expected[sensor]:
            raise ValueError("Unadmitted files in staged sensor directory")
    if admission is not None:
        required = {(next(s for s, p in SENSORS.items() if p["source"] == source), year)
                    for source, year in admission["required"]}
        if keys != required:
            raise ValueError("Admitted sensor/year families differ from selected study")
    return {"status": "PASS", "families": len(keys), "components": checked,
            "records": sum(row["record_count"] for row in manifest["families"]),
            "intake_sha256": sha(manifest_path)}


def check_identity(root: Path, record: dict) -> None:
    path = _authority.child(root, relative_path(record["path"]))
    if identity(path, record["path"]) != record:
        raise ValueError("Input or companion identity differs: " + record["path"])


def _zip_members(path: Path, basename: str) -> dict:
    """Require exactly one safe, unencrypted five-component shapefile family."""
    names = {basename + ext for ext in EXTENSIONS}
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        actual = [entry.filename for entry in members]
        if len(actual) != 5 or len(set(actual)) != 5 or set(actual) != names:
            raise ValueError("ZIP has unexpected or missing shapefile components")
        for entry in members:
            relative_path(entry.filename)
            if (entry.is_dir() or entry.flag_bits & 1
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("ZIP contains linked, encrypted or non-file components")
        if archive.testzip() is not None:
            raise ValueError("ZIP component CRC differs")
        return {entry.filename: {"sha256": hashlib.sha256(archive.read(entry)).hexdigest(),
                                  "size_bytes": entry.file_size} for entry in members}


def _verify_archive_family(root: Path, family: dict, admission: dict) -> None:
    sensor, year = family["sensor"], family["year"]
    spec = SENSORS[sensor]
    key = (spec["source"], year)
    part, row = admission["partitions"].get(key), admission["exports"].get(key)
    if part is None or row is None:
        raise ValueError("Annual family is not selected by validation acceptance")
    basename = spec["prefix"] + str(year)
    if (family.get("basename") != basename or Path(family["path"]).stem != basename
            or family.get("record_count") != part["record_count"]
            or family.get("source") != spec["source"] or family.get("processing") != "SP"
            or family.get("instrument") != spec["instrument"]):
        raise ValueError("Annual family product/count differs from acceptance")
    for role in ("provenance", "field_dictionary"):
        check_identity(root, family[role])
    if (family["archive_zip"]["sha256"] != row["sha256"]
            or family["archive_zip"]["path"] != row["annual_shapefile_zip"]):
        raise ValueError("Annual ZIP differs from accepted export")
    members = admission["artifacts"][key]["members"]
    for component in family["components"]:
        expected = members[Path(component["path"]).name]
        if any(component[k] != expected[k] for k in ("sha256", "size_bytes")):
            raise ValueError("Extracted component differs from accepted ZIP")
    provenance = json.loads((root / family["provenance"]["path"]).read_text(encoding="utf-8"))
    if (provenance.get("contract") != "ghana-firms-gee-annual-v1" or provenance.get("export") != row
            or provenance.get("accepted_partition") != part
            or provenance.get("research_manifest_sha256") != admission["documents"]["annual_export"]["research_manifest_sha256"]):
        raise ValueError("Archive provenance does not bind exact accepted partition/export")
    dictionary = json.loads((root / family["field_dictionary"]["path"]).read_text(encoding="utf-8"))
    if not {"obs_id", "conf_raw", "fire_type", "source", "processing", "time_utc"}.issubset(dictionary):
        raise ValueError("Incomplete Archive field dictionary")
    lineage = dbf_lineage(root / family["path"].replace(".shp", ".dbf"))
    count = lineage["record_count"]
    if count != part["record_count"]:
        raise ValueError("Archive DBF record count differs")
    if count:
        if (lineage["source"] != [spec["source"]] or lineage["processing"] != ["SP"]
                or lineage["instrument"] != [spec["instrument"]]
                or not set(lineage["platform"]) <= spec["platforms"]
                or not set(lineage["version"]) <= spec["versions"]
                or "" in lineage["platform"] or "" in lineage["version"]):
            raise ValueError("Invalid SP lineage/count")
    elif any(lineage[name] for name in ("source", "processing", "instrument", "platform", "version")):
        raise ValueError("Empty Archive family must have empty observed lineage")
    if (family.get("platforms") != lineage["platform"] or family.get("versions") != lineage["version"]
            or set(part.get("source_versions", [])) != set(lineage["version"])
            or family.get("allowed_platforms") != sorted(spec["platforms"])
            or family.get("allowed_versions") != sorted(spec["versions"])):
        raise ValueError("Observed and allowed Archive lineage differs")
    if row.get("gee_upload_ready") is not (count > 0):
        raise ValueError("Archive readiness is inconsistent with verified record count")


def stage_archive(annual: Path, destination: Path, study: dict, acceptance: Path) -> dict:
    """Extract accepted annual ZIPs directly into a fresh run-local source bundle.

    Acceptance evidence is retained unchanged, including QA sidecars. Publication
    happens only after full validation, using the workspace no-replace primitive.
    No live inputs, producer outputs, or previous bundles are modified.
    """
    annual, acceptance = Path(annual).resolve(), Path(acceptance).resolve()
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Staging destination already exists; choose a fresh directory")
    destination = destination.resolve()
    if (destination.is_relative_to(annual) or annual.is_relative_to(destination)
            or destination.is_relative_to(acceptance.parent) or acceptance.parent.is_relative_to(destination)):
        raise ValueError("Staging and Archive acceptance/source directories must be disjoint")
    receipt = json.loads(acceptance.read_text(encoding="utf-8"))
    admission = _authority.validate_acceptance(acceptance.parent, receipt, study=study)
    source_export = annual / "annual-export.json"
    if sha(source_export) != receipt["annual_export"]["sha256"]:
        raise ValueError("Annual directory differs from validation acceptance")
    destination.parent.mkdir(parents=True, exist_ok=True)
    preflight_directory_publication(destination)
    with tempfile.TemporaryDirectory(prefix="." + destination.name + ".stage-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        base = Path("data/raw/source_provenance/validation")
        acceptance_target = staging / base / "acceptance.json"
        acceptance_target.parent.mkdir(parents=True)
        shutil.copyfile(acceptance, acceptance_target)
        evidence = []
        for original in receipt["source_evidence"]:
            source = _authority.check_file(acceptance.parent, original)
            target = _authority.child(acceptance_target.parent, original["path"])
            if target == acceptance_target:
                raise ValueError("Source evidence collides with acceptance receipt")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            evidence.append({**original, "path": target.relative_to(staging).as_posix()})
        export = dict(receipt["annual_export"])
        export["path"] = (base / export["path"]).as_posix()
        manifest = {"schema": SCHEMA_V2, "input_profile": PROFILE, "study": study,
                    "acceptance": identity(acceptance_target, acceptance_target.relative_to(staging).as_posix()),
                    "archive_export": export, "source_evidence": evidence,
                    "selected_coverage": receipt["selected_coverage"], "families": []}
        for (source, year) in sorted(admission["required"]):
            sensor = next(s for s, spec in SENSORS.items() if spec["source"] == source)
            spec, row = SENSORS[sensor], admission["exports"][(source, year)]
            basename = spec["prefix"] + str(year)
            archive = _authority.child(annual, row["annual_shapefile_zip"])
            if not archive.is_file() or sha(archive) != row["sha256"]:
                raise ValueError("Archive ZIP identity differs: " + row["annual_shapefile_zip"])
            if _zip_members(archive, basename) != admission["artifacts"][(source, year)]["members"]:
                raise ValueError("Actual ZIP members differ from validation acceptance")
            components = []
            with zipfile.ZipFile(archive) as zipped:
                for extension in EXTENSIONS:
                    relative = f"data/raw/{sensor}/{basename}{extension}"
                    target = staging / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(basename + extension) as incoming, target.open("xb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                    components.append(identity(target, relative))
            lineage = dbf_lineage(staging / f"data/raw/{sensor}/{basename}.dbf")
            family = {"sensor": sensor, "year": year, "path": f"data/raw/{sensor}/{basename}.shp",
                      "basename": basename, "record_count": lineage["record_count"],
                      "source": source, "processing": "SP", "instrument": spec["instrument"],
                      "platforms": lineage["platform"], "versions": lineage["version"],
                      "allowed_platforms": sorted(spec["platforms"]), "allowed_versions": sorted(spec["versions"]),
                      "components": components,
                      "archive_zip": identity(archive, row["annual_shapefile_zip"]),
                      "archive_origin_path": row["annual_shapefile_zip"]}
            for role, suffix in (("provenance", "_provenance.json"), ("field_dictionary", "_fields.json")):
                original = _authority.child(annual, f"metadata/{spec['archive_folder']}/{basename}{suffix}")
                target = staging / "data/raw/source_provenance" / sensor / original.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, target)
                family[role] = identity(target, target.relative_to(staging).as_posix())
            _verify_archive_family(staging, family, admission)
            manifest["families"].append(family)
        for sensor in SENSORS:
            (staging / "data/raw" / sensor).mkdir(parents=True, exist_ok=True)
        write_json(staging / AUTHORITY, manifest)
        result = verify_bundle(staging, study=study)
        publish_directory_no_replace(staging, destination)
    return {**result, "bundle_root": str(destination), "input_profile": PROFILE,
            "admission_manifest": AUTHORITY}


def stage(curated: Path, annual: Path, destination: Path) -> dict:
    destination = destination.resolve()
    if (destination == curated.resolve() or destination.is_relative_to(curated.resolve())
            or destination == annual.resolve() or destination.is_relative_to(annual.resolve())):
        raise ValueError("Staging must be outside curated and Archive source directories")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Staging destination already exists; choose a fresh directory")
    manifest = inspect_curated(curated, annual)
    destination.mkdir(parents=True)
    for family in manifest["families"]:
        spec = SENSORS[family["sensor"]]
        for record in family["components"]:
            source = curated / spec["folder"] / Path(record["path"]).name
            target = destination / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for role, suffix in (("provenance", "_provenance.json"), ("field_dictionary", "_fields.json")):
            source = annual / "metadata" / spec["archive_folder"] / (family["basename"] + suffix)
            target = destination / family[role]["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    target = destination / manifest["archive_export"]["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(annual / "annual-export.json", target)
    write_json(destination / AUTHORITY, manifest)
    return verify_bundle(destination)


def tree_inventory(path: Path) -> dict:
    result = {}
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError("Linked member in input directory: " + str(item))
        if item.is_file():
            relative = item.relative_to(path).as_posix()
            result[relative] = identity(item, relative)
    return result


def activate(staged: Path, firms_root: Path, backup: Path) -> dict:
    staged, firms_root, backup = staged.resolve(), firms_root.resolve(), backup.resolve()
    result = verify_bundle(staged)
    if not firms_root.is_dir() or backup.is_relative_to(firms_root) or firms_root.is_relative_to(backup):
        raise ValueError("Backup must be outside the existing FIRMS project")
    if backup.exists() or backup.is_symlink():
        raise ValueError("Backup directory already exists; never overwrite a baseline")
    if staged == firms_root or staged.is_relative_to(firms_root) or firms_root.is_relative_to(staged):
        raise ValueError("Staging and active FIRMS roots must be disjoint")
    if backup == staged or backup.is_relative_to(staged) or staged.is_relative_to(backup):
        raise ValueError("Backup and staging roots must be disjoint")
    relative_dirs = ["data/raw/modis", "data/raw/viirs", "data/raw/source_provenance"]
    before = {}
    for relative in relative_dirs:
        path = firms_root / relative
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError("Invalid active directory: " + relative)
        before[relative] = tree_inventory(path) if path.exists() else None
    backup.mkdir(parents=True)
    preflight_directory_publication(backup / "data/raw/modis")
    preflight_directory_publication(firms_root / "data/raw/modis")
    write_json(backup / "activation.json", {"schema": "rp1_firms_sp_activation_v1", "state": "prepared",
               "active_root": str(firms_root), "staged_root": str(staged), "new_intake": result,
               "old_directories": before})
    moved_old, moved_new = [], []
    try:
        for relative in relative_dirs:
            active, saved = firms_root / relative, backup / relative
            if active.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                publish_directory_no_replace(active, saved)
                moved_old.append(relative)
                if tree_inventory(saved) != before[relative]:
                    raise ValueError("Active source changed during activation: " + relative)
        for relative in relative_dirs:
            active, prepared = firms_root / relative, staged / relative
            if active.exists():
                raise ValueError("Active destination reappeared during activation")
            active.parent.mkdir(parents=True, exist_ok=True)
            publish_directory_no_replace(prepared, active)
            moved_new.append(relative)
        verify_bundle(firms_root)
        write_json(backup / "activation_complete.json", {"status": "PASS", "new_intake": result,
                   "old_directories": before, "restore": "Move new directories to a fresh quarantine, then restore saved directories at active_root. Restore source/config/analysis authorities from the matching complete baseline."})
    except BaseException:
        for relative in reversed(moved_new):
            publish_directory_no_replace(firms_root / relative, staged / relative)
        for relative in reversed(moved_old):
            publish_directory_no_replace(backup / relative, firms_root / relative)
        write_json(backup / "activation_failed.json", {"state": "rolled_back", "new_intake": result})
        raise
    return {**result, "backup": str(backup), "active_root": str(firms_root)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "stage"):
        child = commands.add_parser(command)
        child.add_argument("--curated", type=Path, required=True)
        child.add_argument("--archive-annual", type=Path, required=True)
        if command == "stage":
            child.add_argument("--destination", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--staged", type=Path, required=True)
    verify.add_argument("--study", type=Path, help="JSON study selection required by a v2 bundle")
    direct = commands.add_parser("stage-archive")
    direct.add_argument("--archive-annual", type=Path, required=True)
    direct.add_argument("--destination", type=Path, required=True)
    direct.add_argument("--study", type=Path, required=True, help="JSON study selection")
    direct.add_argument("--acceptance", type=Path, required=True)
    apply = commands.add_parser("activate")
    apply.add_argument("--staged", type=Path, required=True)
    apply.add_argument("--firms-root", type=Path, default=FIRMS_ROOT)
    apply.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "plan":
        manifest = inspect_curated(args.curated, args.archive_annual)
        result = {"status": "PASS", "action": "read_only_plan", "families": len(manifest["families"]),
                  "records": sum(row["record_count"] for row in manifest["families"]),
                  "profile": PROFILE, "admission_manifest": AUTHORITY}
    elif args.command == "stage":
        result = stage(args.curated, args.archive_annual, args.destination)
    elif args.command == "stage-archive":
        result = stage_archive(args.archive_annual, args.destination,
                               json.loads(args.study.read_text(encoding="utf-8")), args.acceptance)
    elif args.command == "verify":
        study = json.loads(args.study.read_text(encoding="utf-8")) if args.study else None
        result = verify_bundle(args.staged, study=study)
    else:
        result = activate(args.staged, args.firms_root, args.backup)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
