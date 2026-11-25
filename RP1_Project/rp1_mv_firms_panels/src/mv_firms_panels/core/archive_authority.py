"""Portable, file-backed validation of run-local Archive SP admission authorities.

This module deliberately uses only the standard library so intake and preparation
can enforce the same acceptance contract without importing the Archive producer.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

INTAKE_V2 = "rp1_firms_archive_sp_intake_v2"
ACCEPTANCE_SCHEMA = "rp1_archive_sp_validation_acceptance_v1"
SOURCES = {"modis": "MODIS_SP", "viirs": "VIIRS_SNPP_SP"}
STARTS = {"modis": date(2000, 11, 1), "viirs": date(2012, 1, 20)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def child(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Unsafe Archive authority relative path")
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or posix.as_posix() != value:
        raise ValueError("Unsafe Archive authority relative path")
    root = root.resolve()
    candidate = root / value
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError("Linked Archive authority path")
        cursor = cursor.parent
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("Archive authority escapes bundle root")
    return candidate


def check_file(root: Path, record: dict) -> Path:
    if not isinstance(record, dict):
        raise ValueError("Missing Archive authority file identity")
    path = child(root, record.get("path"))
    if (not path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
            or type(record.get("size_bytes")) is not int or record["size_bytes"] != path.stat().st_size
            or record["sha256"] != sha256(path)):
        raise ValueError("Archive authority identity differs: " + str(record.get("path")))
    return path


def _indexed(rows: object, label: str) -> dict:
    if not isinstance(rows, list):
        raise ValueError("Missing Archive " + label)
    result = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("year")) is not int:
            raise ValueError("Invalid Archive " + label)
        key = (row.get("source"), row["year"])
        if key in result:
            raise ValueError("Duplicate Archive " + label + " source/year")
        result[key] = row
    return result


def required_intervals(study: dict) -> dict:
    if not isinstance(study, dict):
        raise ValueError("Study selection must be a mapping")
    start, end = study.get("start_yyyymm"), study.get("end_yyyymm")
    if (type(start) is not int or type(end) is not int or start > end
            or not 1 <= start % 100 <= 12 or not 1 <= end % 100 <= 12):
        raise ValueError("Invalid Archive study month interval")
    import calendar
    first = date(start // 100, start % 100, 1)
    last = date(end // 100, end % 100, calendar.monthrange(end // 100, end % 100)[1])
    result = {}
    for sensor, source in SOURCES.items():
        support = study.get("viirs_support_start_yyyymm", 201201) if sensor == "viirs" else 200011
        support_date = date(support // 100, support % 100, 1)
        effective = max(first, STARTS[sensor], support_date)
        for year in range(effective.year, last.year + 1):
            lower, upper = max(effective, date(year, 1, 1)), min(last, date(year, 12, 31))
            if lower <= upper:
                result[(source, year)] = (lower, upper)
    if not result:
        raise ValueError("Archive study has no supported source intervals")
    return result


def validate_acceptance(root: Path, receipt: dict, *, study: dict | None = None) -> dict:
    """Verify the validator receipt and every copied evidence link independently."""
    if (not isinstance(receipt, dict) or receipt.get("schema") != ACCEPTANCE_SCHEMA
            or receipt.get("status") != "PASS"):
        raise ValueError("Archive validation acceptance is missing or failed")
    if study is not None and receipt.get("study") != study:
        raise ValueError("Archive validation acceptance study differs")
    study = receipt.get("study")
    required = required_intervals(study)
    validation = receipt.get("validation")
    if not isinstance(validation, dict) or not (validation.get("passed") is True or validation.get("status") == "PASS"):
        raise ValueError("Archive acceptance requires successful source validation")
    if not isinstance(receipt.get("validator_identity"), dict) or not receipt["validator_identity"]:
        raise ValueError("Archive acceptance requires validator identity")
    if not isinstance(receipt.get("generation_code_identity"), dict):
        raise ValueError("Archive acceptance requires separate generation code identity")
    evidence = receipt.get("source_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Archive acceptance requires source evidence")
    seen = set()
    for entry in evidence:
        if not isinstance(entry.get("role"), str) or entry["path"] in seen:
            raise ValueError("Invalid or repeated Archive source evidence")
        seen.add(entry["path"])
        check_file(root, entry)
    documents = {}
    for role in ("research_manifest", "annual_export", "qa_manifest"):
        entry = receipt.get(role)
        path = check_file(root, entry)
        matching = [r for r in evidence if r.get("role") == role]
        if len(matching) != 1 or any(matching[0].get(k) != entry.get(k) for k in ("path", "sha256", "size_bytes")):
            raise ValueError("Archive named authority does not bind source evidence: " + role)
        documents[role] = json.loads(path.read_text(encoding="utf-8"))
    manifest, export, qa = (documents[k] for k in ("research_manifest", "annual_export", "qa_manifest"))
    research_hash = receipt["research_manifest"]["sha256"]
    if (manifest.get("contract") != "ghana-firms-research-archive-v1"
            or manifest.get("processing_status") != "SP"
            or export.get("contract") != "ghana-firms-gee-annual-export-v1"
            or qa.get("contract") != "ghana-firms-quality-sidecars-v1"
            or export.get("research_manifest_sha256") != research_hash
            or qa.get("research_manifest_sha256") != research_hash):
        raise ValueError("Archive research/export/QA authority links differ")
    coverage = _indexed(receipt.get("selected_coverage"), "selected coverage")
    source_coverage = _indexed(manifest.get("source_coverage"), "research coverage")
    export_coverage = _indexed(export.get("source_coverage"), "export coverage")
    if set(coverage) != set(required):
        raise ValueError("Archive selected coverage does not exactly cover study obligations")
    parts = _indexed(manifest.get("partitions"), "research partitions")
    exports = _indexed(export.get("partitions"), "export partitions")
    quality = _indexed(qa.get("partitions"), "QA partitions")
    artifacts = _indexed(receipt.get("selected_artifacts"), "selected artifacts")
    if set(artifacts) != set(required):
        raise ValueError("Archive selected artifact grid differs from study obligations")
    for key, (lower, upper) in required.items():
        cov = coverage[key]
        if cov != source_coverage.get(key) or cov != export_coverage.get(key):
            raise ValueError("Archive selected coverage differs from source authorities")
        try:
            checked_start, checked_end = date.fromisoformat(cov["checked_start"]), date.fromisoformat(cov["checked_end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Required Archive interval is unchecked") from exc
        if (cov.get("status") != "available" or cov.get("processing_status", "SP") != "SP"
                or checked_start > lower or checked_end < upper
                or checked_start.year != key[1] or checked_end.year != key[1] or checked_start > checked_end
                or checked_start < STARTS[next(s for s, p in SOURCES.items() if p == key[0])]):
            raise ValueError("Required Archive interval is unavailable, unchecked or partial")
        part, row, qrow = parts.get(key), exports.get(key), quality.get(key)
        if not all(isinstance(r, dict) for r in (part, row, qrow)):
            raise ValueError("Required Archive partition or QA is missing")
        count = part.get("record_count")
        if (type(count) is not int or count < 0 or type(row.get("records")) is not int
                or type(qrow.get("records")) is not int or count != row.get("records") or count != qrow.get("records")
                or part.get("processing_status") != "SP"
                or part.get("coverage_start") != cov["checked_start"] or part.get("coverage_end") != cov["checked_end"]
                or row.get("checked_start") != cov["checked_start"] or row.get("checked_end") != cov["checked_end"]
                or qrow.get("canonical_path") != part.get("path") or qrow.get("canonical_sha256") != part.get("sha256")):
            raise ValueError("Archive partition coverage/count/QA links differ")
        candidates = [r for r in evidence if r.get("role") == "qa_sidecar"
                      and r.get("sha256") == qrow.get("qa_sha256")
                      and PurePosixPath(r["path"]).name == PurePosixPath(qrow.get("qa_path", "")).name]
        if len(candidates) != 1:
            raise ValueError("Archive selected QA sidecar is missing or ambiguous")
        artifact = artifacts[key]
        sensor = next(s for s, p in SOURCES.items() if p == key[0])
        stem = ("Ghana_MODIS_SP_" if sensor == "modis" else "Ghana_VIIRS_SNPP_SP_") + str(key[1])
        members = artifact.get("members")
        if (artifact.get("zip_sha256") != row.get("sha256") or not isinstance(members, dict)
                or set(members) != {stem + ext for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg")}):
            raise ValueError("Archive accepted artifact member identities are incomplete")
        for name, member in members.items():
            if (not isinstance(member, dict) or type(member.get("size_bytes")) is not int
                    or member["size_bytes"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", str(member.get("sha256", "")))):
                raise ValueError("Invalid Archive accepted member identity")
    return {"study": study, "required": required, "partitions": parts, "exports": exports,
            "selected_coverage": list(coverage.values()), "documents": documents, "artifacts": artifacts}


def validate_v2_authority(root: Path, manifest: dict, *, study: dict | None = None) -> dict:
    if manifest.get("schema") != INTAKE_V2:
        raise ValueError("Unknown run-local intake schema")
    receipt_path = check_file(root, manifest.get("acceptance"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    # The unchanged receipt keeps evidence paths relative to its own directory.
    result = validate_acceptance(receipt_path.parent, receipt, study=study or manifest.get("study"))
    if manifest.get("study") != receipt.get("study") or manifest.get("selected_coverage") != receipt.get("selected_coverage"):
        raise ValueError("Run-local study or selected coverage differs from acceptance")
    expected = []
    for original in receipt["source_evidence"]:
        local = dict(original)
        local["path"] = (receipt_path.parent / original["path"]).relative_to(root).as_posix()
        expected.append(local)
    if manifest.get("source_evidence") != expected:
        raise ValueError("Run-local source evidence differs from acceptance")
    for entry in expected:
        check_file(root, entry)
    export_local = dict(receipt["annual_export"])
    export_local["path"] = (receipt_path.parent / export_local["path"]).relative_to(root).as_posix()
    if manifest.get("archive_export") != export_local:
        raise ValueError("Run-local export authority differs from acceptance")
    return result
