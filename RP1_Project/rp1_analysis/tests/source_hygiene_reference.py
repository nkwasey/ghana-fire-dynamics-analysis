"""Distinguish runtime input dependencies from local archive output handling."""
import ast
import json
import os
from pathlib import Path
import re
import yaml


ARCHIVE_COMPONENT = "RP1_Project/rp1_firms_archive/"
LOCAL_ARCHIVE_COMPONENT_CODE = {
    ARCHIVE_COMPONENT + "src/ghana_fire_archive/api.py",
    ARCHIVE_COMPONENT + "src/ghana_fire_archive/cli.py",
    ARCHIVE_COMPONENT + "src/ghana_fire_archive/core.py",
    ARCHIVE_COMPONENT + "src/ghana_fire_archive/exports.py",
    ARCHIVE_COMPONENT + "tools/package_source.py",
    ARCHIVE_COMPONENT + "tools/package_annual.py",
}
LOCAL_ARCHIVE_COMPONENT_DOCUMENTATION = {
    ARCHIVE_COMPONENT + "README.md", ARCHIVE_COMPONENT + "GEE_UPLOAD.md",
}
LOCAL_ARCHIVE_PRODUCERS = {"tools/stage_gee_handoff.py", "tools/package_clean_source.py",
                           "tools/firms_archive_workflow.py"} | LOCAL_ARCHIVE_COMPONENT_CODE
LOCAL_ARCHIVE_INTAKE_TOOLS = {"tools/import_firms_archive_sp.py"}
# Exact reviewed code/document paths, never an exemption for the component tree.
# Producer code also has an explicit output-literal check in its hygiene tests.
LOCAL_ARCHIVE_IO_TOOLS = (LOCAL_ARCHIVE_PRODUCERS | LOCAL_ARCHIVE_INTAKE_TOOLS
                          | LOCAL_ARCHIVE_COMPONENT_DOCUMENTATION)
_NON_SOURCE_DIRECTORIES = {"tests", "out", "downloads", "__pycache__", ".pytest_cache"}
GENERATED_PRESENTATION_ROOTS = {
    "RP1_Project/rp1_analysis/presentation_all",
    "RP1_Project/rp1_analysis/presentation_one",
    "RP1_Project/rp1_analysis/presentation_rq3",
}
_PROVENANCE_ROOT = "RP1_Project/rp1_mv_firms_panels/data/raw/source_provenance/"
_ARCHIVE_SOURCES = {"MODIS_SP": ("MODIS", "Ghana_MODIS_SP_"),
                    "VIIRS_SNPP_SP": ("VIIRS", "Ghana_VIIRS_SNPP_SP_"),
                    "VIIRS_NOAA20_SP": ("NOAA20", "Ghana_VIIRS_NOAA20_SP_"),
                    "VIIRS_NOAA21_SP": ("NOAA21", "Ghana_VIIRS_NOAA21_SP_")}


def _archive_reference(row: object) -> str | None:
    """Recognise a hash-bearing annual export identity, never an arbitrary ZIP path."""
    if not isinstance(row, dict) or row.get("source") not in _ARCHIVE_SOURCES:
        return None
    if type(row.get("year")) is not int or not 1900 <= row["year"] <= 2200:
        return None
    folder, prefix = _ARCHIVE_SOURCES[row["source"]]
    expected = f"{folder}/{prefix}{row['year']}.zip"
    if (row.get("annual_shapefile_zip") != expected
            or re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))) is None):
        return None
    return expected


def archive_provenance_scan_text(relative: str, text: str) -> str:
    """Mask only declared archival identity slots in specific governed data schemas.

    Data authorities retain descriptive source ZIP names and their hashes. Unknown
    schemas, paths, fields and runtime-input keys remain visible to the scanner.
    This projection never changes the source file or removes it from inventories.
    """
    if not relative.startswith(_PROVENANCE_ROOT) or not relative.endswith(".json"):
        return text
    name = relative[len(_PROVENANCE_ROOT):]
    known_path = (name in {"annual-export.json", "archive_sp_intake.json"}
                  or re.fullmatch(r"(?:modis/Ghana_MODIS_SP_|viirs/Ghana_VIIRS_SNPP_SP_)\d{4}_provenance\.json", name))
    if not known_path:
        return text
    payload = json.loads(text)
    if not isinstance(payload, dict):
        return text
    if name == "annual-export.json" and payload.get("contract") == "ghana-firms-gee-annual-export-v1":
        for row in payload.get("partitions", []):
            if _archive_reference(row):
                row["annual_shapefile_zip"] = "hash_bound_annual_source_archive"
    elif name == "archive_sp_intake.json" and payload.get("schema") == "rp1_firms_archive_sp_intake_v1":
        if payload.get("input_profile") != "ghana_firms_archive_sp_v1":
            return text
        for family in payload.get("families", []):
            if not isinstance(family, dict):
                continue
            archive = family.get("archive_zip")
            if not isinstance(archive, dict):
                continue
            row = {"source": family.get("source"), "year": family.get("year"),
                   "annual_shapefile_zip": archive.get("path"), "sha256": archive.get("sha256")}
            if _archive_reference(row):
                archive["path"] = "hash_bound_annual_source_archive"
    elif payload.get("contract") == "ghana-firms-gee-annual-v1" and name.endswith("_provenance.json"):
        exported = payload.get("export")
        reference = _archive_reference(exported)
        accepted = payload.get("accepted_partition")
        if reference and isinstance(accepted, dict):
            source, year = exported["source"], exported["year"]
            sensor = "modis" if source == "MODIS_SP" else "viirs" if source == "VIIRS_SNPP_SP" else None
            basename = reference.split("/", 1)[1]
            if (sensor and name == f"{sensor}/{basename[:-4]}_provenance.json"
                    and accepted.get("source") == source and accepted.get("year") == year
                    and accepted.get("shapefile_sha256") == exported["sha256"]):
                folder = reference.split("/", 1)[0]
                pattern = rf"artifacts/{folder}/{year}/[0-9a-f]{{8,64}}/{re.escape(basename)}"
                if re.fullmatch(pattern, str(accepted.get("shapefile_path", ""))):
                    accepted["shapefile_path"] = "hash_bound_canonical_archive_export"
                exported["annual_shapefile_zip"] = "hash_bound_annual_source_archive"
    return json.dumps(payload)


def runtime_source_files(repository: Path):
    """Walk source only, without traversing generated or test directories."""
    def fail(exc: OSError) -> None:
        raise exc
    for directory, dirs, files in os.walk(repository, topdown=True, onerror=fail, followlinks=False):
        dirs[:] = [name for name in dirs if name not in _NON_SOURCE_DIRECTORIES
                   and (Path(directory) / name).relative_to(repository).as_posix() not in GENERATED_PRESENTATION_ROOTS]
        for name in files:
            yield Path(directory) / name


def runtime_scan_text(path: Path, repository: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = archive_provenance_scan_text(path.relative_to(repository).as_posix(), text)
    if path.relative_to(repository).as_posix() == ARCHIVE_COMPONENT + "data/reference/geography/geography-manifest.json":
        payload = json.loads(text)
        source = payload.get("source", {}) if isinstance(payload, dict) else {}
        safety = source.get("archive_safety", {}) if isinstance(source, dict) else {}
        name = source.get("archive_name")
        identity = source.get("archive_sha256")
        if (isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+\.zip", name)
                and re.fullmatch(r"[0-9a-f]{64}", str(identity))
                and isinstance(safety, dict) and safety.get("safe") is True
                and safety.get("archive_name") == name and safety.get("archive_sha256") == identity):
            # Pinned reference-origin descriptions cannot hide runtime-input keys.
            source["archive_name"] = "hash_bound_reference_source_archive"
            safety["archive_name"] = "hash_bound_reference_source_archive"
            text = json.dumps(payload)
    if path.relative_to(repository).as_posix() == "configs/clean_source_package.json":
        policy = json.loads(text)
        if policy.get("schema") == "rp1-clean-source-package-v1":
            # Exclusion globs describe files omitted from a locally produced ZIP.
            text = json.dumps({key: value for key, value in policy.items()
                               if key != "exclude_file_patterns"})
    elif path.relative_to(repository).as_posix() == "RP1_Project/rp1_analysis/config/qualification_contract.yml":
        policy = yaml.safe_load(text)
        if isinstance(policy, dict) and policy.get("schema_version") == "rp1-qualification-contract-v1":
            generated = policy.get("generated_artifacts")
            if isinstance(generated, dict):
                # These suffixes identify artifacts to omit, not inputs to load.
                generated.pop("file_suffixes", None)
                text = json.dumps(policy)
    return re.sub(r"out/releases/[a-z0-9_.-]+\.zip", "local_release_output", text, flags=re.IGNORECASE)


def archive_input_literals(source: str) -> list[str]:
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value.strip()
        if len(value) <= 4 or not value.casefold().endswith(".zip"):
            continue
        parent = parents.get(node)
        # Regex patterns inspect documentation/source text; they do not load an archive.
        if (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
                and isinstance(parent.func.value, ast.Name) and parent.func.value.id == "re"):
            continue
        result.append(value)
    return result

