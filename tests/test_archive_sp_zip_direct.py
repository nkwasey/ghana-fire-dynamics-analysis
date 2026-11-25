"""Run-local ZIP intake enforces current file-backed acceptance and coverage."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("zip_direct_intake", ROOT / "tools/import_firms_archive_sp.py")
intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intake)


def archive_case(tmp_path, *, year=2024, empty=False, nested=False, coverage_start=None,
                 coverage_end=None, missing=None, status="available", extra_zip=False,
                 wrong_product=False):
    annual, authority = tmp_path / "annual", tmp_path / "validation"
    authority.mkdir(parents=True)
    evidence = authority / "evidence"
    evidence.mkdir()
    parts, exports, coverage, quality, artifacts = [], [], [], [], []
    original_paths = {}
    for sensor, product in intake.SENSORS.items():
        if sensor == missing:
            continue
        source = product["source"]
        if wrong_product and sensor == "viirs":
            source = "VIIRS_NOAA20_SP"
        stem = product["prefix"] + str(year)
        folder = tmp_path / "components" / sensor
        folder.mkdir(parents=True)
        count = 0 if empty else 1
        row = {"obs_id": ["gfa2:" + "a" * 64], "acq_date": [f"{year}-06-01"],
               "time_utc": ["13:07"], "platform": ["Terra" if sensor == "modis" else "Suomi-NPP"],
               "instrument": [product["instrument"]], "confidence": ["nominal"],
               "conf_raw": ["55" if sensor == "modis" else "n"], "frp_mw": [4.0],
               "bright_k": [300.0], "bright_aux": [280.0], "daynight": ["D"],
               "district": ["unit"], "zone": ["zone"], "scan_km": [1.0], "track_km": [1.0],
               "source": [source], "processing": ["SP"],
               "version": ["6.2" if sensor == "modis" else "2"], "fire_type": ["0"]}
        points = gpd.GeoDataFrame(row, geometry=[Point(-1, 8)], crs=4326)
        if empty:
            points = points.iloc[:0].copy()
        shp = folder / (stem + ".shp")
        points.to_file(shp, driver="ESRI Shapefile", encoding="UTF-8", geometry_type="Point")
        original_paths[sensor] = shp
        zip_relative = ("nested/accepted/" if nested else "") + product["archive_folder"] + "/" + stem + ".zip"
        zipped = annual / zip_relative
        zipped.parent.mkdir(parents=True)
        with zipfile.ZipFile(zipped, "w") as stream:
            for ext in intake.EXTENSIONS:
                stream.write(shp.with_suffix(ext), stem + ext)
            if extra_zip:
                stream.writestr("../unadmitted.txt", "no")
        checked_start = coverage_start or (f"{year}-01-20" if sensor == "viirs" and year == 2012 else f"{year}-01-01")
        checked_end = coverage_end or f"{year}-12-31"
        cov = {"source": source, "year": year, "status": status,
               "checked_start": checked_start, "checked_end": checked_end, "processing_status": "SP"}
        coverage.append(cov)
        part = {"source": source, "year": year, "processing_status": "SP", "record_count": count,
                "coverage_start": checked_start, "coverage_end": checked_end,
                "source_versions": [] if empty else row["version"],
                "path": f"canonical/{source}/{year}.csv", "sha256": "b" * 64,
                "shapefile_sha256": intake.sha(zipped), "coverage": cov}
        parts.append(part)
        export = {"source": source, "year": year, "records": count,
                  "checked_start": checked_start, "checked_end": checked_end,
                  "annual_shapefile_zip": zip_relative, "sha256": intake.sha(zipped),
                  "gee_upload_ready": not empty}
        exports.append(export)
        qfile = evidence / f"Ghana_{source}_{year}_qa.csv"
        qfile.write_text("observation_id,source,year,flags\n", encoding="utf-8")
        quality.append({"source": source, "year": year, "records": count,
                        "canonical_path": part["path"], "canonical_sha256": part["sha256"],
                        "qa_path": qfile.name, "qa_sha256": intake.sha(qfile)})
        members = {stem + ext: {"sha256": intake.sha(shp.with_suffix(ext)),
                               "size_bytes": shp.with_suffix(ext).stat().st_size}
                   for ext in intake.EXTENSIONS}
        artifacts.append({"source": source, "year": year, "zip_sha256": intake.sha(zipped), "members": members})
    research = evidence / "archive-manifest.json"
    research.write_text(json.dumps({"contract": "ghana-firms-research-archive-v1", "processing_status": "SP",
                                   "source_coverage": coverage, "partitions": parts}), encoding="utf-8")
    export_path = annual / "annual-export.json"
    export_path.write_text(json.dumps({"contract": "ghana-firms-gee-annual-export-v1",
                                      "research_manifest_sha256": intake.sha(research),
                                      "source_coverage": coverage, "partitions": exports}), encoding="utf-8")
    shutil.copyfile(export_path, evidence / "annual-export.json")
    qa = evidence / "qa-manifest.json"
    qa.write_text(json.dumps({"contract": "ghana-firms-quality-sidecars-v1",
                              "research_manifest_sha256": intake.sha(research), "partitions": quality}), encoding="utf-8")
    for part, export in zip(parts, exports):
        sensor = "modis" if part["source"] == "MODIS_SP" else "viirs"
        product = intake.SENSORS[sensor]
        stem = product["prefix"] + str(year)
        meta = annual / "metadata" / product["archive_folder"]
        meta.mkdir(parents=True)
        (meta / (stem + "_provenance.json")).write_text(json.dumps({
            "contract": "ghana-firms-gee-annual-v1", "accepted_partition": part, "export": export,
            "research_manifest_sha256": intake.sha(research)}), encoding="utf-8")
        (meta / (stem + "_fields.json")).write_text(json.dumps({key: key for key in
            ("obs_id", "conf_raw", "fire_type", "source", "processing", "time_utc")}), encoding="utf-8")
    identities = []
    for file in sorted(evidence.iterdir()):
        role = {"archive-manifest.json": "research_manifest", "annual-export.json": "annual_export",
                "qa-manifest.json": "qa_manifest"}.get(file.name, "qa_sidecar")
        identities.append({**intake.identity(file, file.relative_to(authority).as_posix()), "role": role})
    study = {"start_yyyymm": year * 100 + 1, "end_yyyymm": year * 100 + 12,
             "viirs_support_start_yyyymm": 201201, "ba2012_support_start_yyyymm": 201201}
    receipt = {"schema": "rp1_archive_sp_validation_acceptance_v1", "status": "PASS", "study": study,
               "validation": {"passed": True}, "validator_identity": {"version": "fixture-current"},
               "generation_code_identity": {}, "selected_coverage": coverage,
               "source_evidence": identities, "selected_artifacts": artifacts}
    for role in ("research_manifest", "annual_export", "qa_manifest"):
        receipt[role] = {k: v for k, v in next(i for i in identities if i["role"] == role).items() if k != "role"}
    acceptance = authority / "acceptance.json"
    acceptance.write_text(json.dumps(receipt), encoding="utf-8")
    return annual, acceptance, study, original_paths


@pytest.mark.parametrize("nested", [False, True])
def test_direct_zip_stage_preserves_every_component_and_copies_acceptance(tmp_path, nested):
    annual, acceptance, study, originals = archive_case(tmp_path, nested=nested)
    bundle = tmp_path / "consumer"
    result = intake.stage_archive(annual, bundle, study, acceptance)
    assert result["families"] == 2 and result["components"] == 10
    assert intake.verify_bundle(bundle, study=study)["records"] == 2
    assert not list(bundle.rglob("*.zip"))
    manifest = json.loads((bundle / intake.AUTHORITY).read_text())
    assert (bundle / manifest["acceptance"]["path"]).read_bytes() == acceptance.read_bytes()
    for family in manifest["families"]:
        for component in family["components"]:
            assert (bundle / component["path"]).read_bytes() == originals[family["sensor"]].with_suffix(Path(component["path"]).suffix).read_bytes()


@pytest.mark.parametrize("kwargs", [{"missing": "viirs"}, {"status": "unavailable"},
                                   {"coverage_start": "2024-02-01"}, {"coverage_end": "2024-11-30"},
                                   {"wrong_product": True}, {"extra_zip": True}])
def test_required_missing_unchecked_partial_wrong_product_and_unsafe_zip_fail(tmp_path, kwargs):
    annual, acceptance, study, _ = archive_case(tmp_path, **kwargs)
    destination = tmp_path / "consumer"
    with pytest.raises(ValueError):
        intake.stage_archive(annual, destination, study, acceptance)
    assert not destination.exists()


def test_snpp_effective_start_is_january_twenty_not_january_one(tmp_path):
    annual, acceptance, study, _ = archive_case(tmp_path, year=2012)
    result = intake.stage_archive(annual, tmp_path / "consumer", study, acceptance)
    assert result["status"] == "PASS"


def test_verified_empty_family_keeps_observed_lineage_empty(tmp_path):
    annual, acceptance, study, _ = archive_case(tmp_path, empty=True)
    bundle = tmp_path / "consumer"
    result = intake.stage_archive(annual, bundle, study, acceptance)
    assert result["records"] == 0
    manifest = json.loads((bundle / intake.AUTHORITY).read_text())
    assert all(row["platforms"] == row["versions"] == [] for row in manifest["families"])
    from mv_firms_panels.core.config import FirmsSensorInput
    from mv_firms_panels.core.input_profiles import adapt_archive_sp, source_profile_evidence
    for family in manifest["families"]:
        sensor = family["sensor"]
        inp = FirmsSensorInput(file_glob=f"consumer/data/raw/{sensor}/*.shp",
                               input_profile=intake.PROFILE, admission_bundle_root="consumer",
                               admission_manifest=intake.AUTHORITY)
        shp = bundle / family["path"]
        points = gpd.read_file(shp)
        view, profile = adapt_archive_sp(points=points, input_config=inp, repo_root=tmp_path,
                                        sensor=sensor, year=2024, points_path=shp)
        assert len(view) == 0 and profile["platform_counts"] == profile["version_counts"] == {}
        evidence = source_profile_evidence(input_config=inp, repo_root=tmp_path, sensor=sensor,
                                           year=2024, points_path=shp)
        assert evidence["study"] == study
        assert all(row["path"].startswith("consumer/") for row in evidence["source_evidence"])


@pytest.mark.parametrize("role", ["research_manifest", "annual_export", "qa_manifest", "qa_sidecar"])
def test_copied_acceptance_evidence_tampering_fails_verification_and_consumer(tmp_path, role):
    annual, acceptance, study, _ = archive_case(tmp_path)
    bundle = tmp_path / "consumer"
    intake.stage_archive(annual, bundle, study, acceptance)
    manifest = json.loads((bundle / intake.AUTHORITY).read_text())
    target = next(row for row in manifest["source_evidence"] if row["role"] == role)
    path = bundle / target["path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="identity differs"):
        intake.verify_bundle(bundle)
    from mv_firms_panels.core.config import FirmsSensorInput
    from mv_firms_panels.core.input_profiles import source_profile_evidence
    inp = FirmsSensorInput(file_glob="consumer/data/raw/modis/*.shp", input_profile=intake.PROFILE,
                           admission_bundle_root="consumer", admission_manifest=intake.AUTHORITY)
    with pytest.raises(ValueError, match="acceptance"):
        source_profile_evidence(input_config=inp, repo_root=tmp_path, sensor="modis", year=2024,
                                points_path=bundle / manifest["families"][0]["path"])


def test_component_manifest_rehash_cannot_override_accepted_zip_members(tmp_path):
    annual, acceptance, study, _ = archive_case(tmp_path)
    bundle = tmp_path / "consumer"
    intake.stage_archive(annual, bundle, study, acceptance)
    manifest_path = bundle / intake.AUTHORITY
    manifest = json.loads(manifest_path.read_text())
    row = manifest["families"][0]["components"][0]
    target = bundle / row["path"]
    target.write_bytes(target.read_bytes() + b"tamper")
    row.update(intake.identity(target, row["path"]))
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="accepted ZIP"):
        intake.verify_bundle(bundle)


def test_stage_failure_is_transactional_and_existing_destination_is_never_replaced(tmp_path, monkeypatch):
    annual, acceptance, study, _ = archive_case(tmp_path)
    destination = tmp_path / "consumer"
    original = intake.shutil.copyfile
    def fail(source, target):
        if str(source).endswith("_fields.json"):
            raise OSError("injected extraction failure")
        return original(source, target)
    monkeypatch.setattr(intake.shutil, "copyfile", fail)
    with pytest.raises(OSError, match="injected"):
        intake.stage_archive(annual, destination, study, acceptance)
    assert not destination.exists()
    assert not list(tmp_path.glob(".consumer.stage-*"))
    destination.mkdir()
    (destination / "preserved").write_text("baseline")
    with pytest.raises(ValueError, match="already exists"):
        intake.stage_archive(annual, destination, study, acceptance)
    assert (destination / "preserved").read_text() == "baseline"
