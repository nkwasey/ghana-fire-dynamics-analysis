"""Offline request, source-integrity and real ZIP-admission workflow contracts.

Producer scientific validation is substituted only where small fixture IDs do
not represent research observations. Admission, filesystem hashes, coverage,
ZIP extraction, geography comparison and consumer adaptation execute for real.
"""
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import geopandas as gpd
import pytest

from test_archive_sp_zip_direct import archive_case, intake
from mv_firms_panels.core.config import FirmsSensorInput
from mv_firms_panels.core.input_profiles import adapt_archive_sp

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("archive_workflow_contract_tests", ROOT / "tools/firms_archive_workflow.py")
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def project(root):
    producer = root / workflow.ARCHIVE
    (producer / "src/ghana_fire_archive").mkdir(parents=True)
    (producer / "src/ghana_fire_archive/api.py").write_text("# synthetic validator identity\n", encoding="utf-8")
    (producer / "pyproject.toml").write_text('[project]\nname="fixture-archive"\nversion="1.0.2"\n', encoding="utf-8")
    (producer / "configs").mkdir()
    (producer / "configs/rp1.yaml").write_text("sources: [MODIS_SP, VIIRS_SNPP_SP]\n", encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools/run_workflow.py").write_text("# workflow identity\n", encoding="utf-8")
    return root


@pytest.fixture
def skeleton(tmp_path):
    return project(tmp_path)


@pytest.mark.parametrize("settings", [None, [], {"mode": "surprise"}, {"mode": "existing"},
    {"mode": "bundled", "unknown": True}, {"mode": "bundled", "geography_policy": "other"},
    {"mode": "build", "producer_config": "../outside.yaml"},
    {"mode": "build", "producer_config": "/outside.yaml"}])
def test_invalid_or_unsupported_settings_fail(skeleton, settings):
    with pytest.raises(ValueError):
        workflow.settings(skeleton, {"firms_archive": settings})


def test_modes_resolve_selected_paths_and_explicit_override(skeleton):
    manifest = skeleton / "archive/archive-manifest.json"
    save(manifest, {})
    assert workflow.settings(skeleton, {}) == {"mode": "bundled", "geography_policy": workflow.POLICY}
    existing = workflow.settings(skeleton, {"firms_archive": {"mode": "existing", "manifest": "archive/archive-manifest.json"}})
    assert existing["manifest"] == str(manifest.resolve())
    overridden = workflow.settings(skeleton, {}, str(manifest))
    assert overridden == existing
    built = workflow.settings(skeleton, {"firms_archive": {"mode": "build"}})
    assert built["producer_config_sha256"] == workflow.sha(skeleton / built["producer_config"])
    with pytest.raises(ValueError, match="cannot override build"):
        workflow.settings(skeleton, {"firms_archive": {"mode": "build"}}, str(manifest))


@pytest.mark.parametrize("path", ["../foreign", "/absolute", "data\\file", "a//b", "a/./b", "C:/outside"])
def test_authority_paths_reject_escape_and_noncanonical_forms(skeleton, path):
    with pytest.raises(ValueError):
        workflow.relative_child(skeleton, path)


def test_cli_manifest_override_persists_and_cannot_switch_sources(skeleton):
    original, replacement = skeleton / "one.json", skeleton / "two.json"
    save(original, {}); save(replacement, {})
    state = skeleton / "state"
    cfg = {"study": {"start_yyyymm": 202401, "end_yyyymm": 202412}, "firms_archive": {"mode": "bundled"}}
    selected = workflow.resolved_settings(skeleton, state, cfg, str(original))
    request, value = workflow.bind_request(skeleton, state, cfg, "run", selected)
    assert value["manifest_override"] is True
    assert workflow.resolved_settings(skeleton, state, cfg) == selected
    assert workflow.bind_request(skeleton, state, cfg, "run", selected)[0] == request
    changed = workflow.resolved_settings(skeleton, state, cfg, str(replacement))
    with pytest.raises(ValueError, match="request changed"):
        workflow.bind_request(skeleton, state, cfg, "run", changed)
    cfg["firms_archive"] = {"mode": "existing", "manifest": str(original)}
    with pytest.raises(ValueError, match="configuration changed"):
        workflow.resolved_settings(skeleton, state, cfg)


@pytest.mark.parametrize("change", ["study", "run_id", "producer_code", "producer_version", "workflow_code", "producer_config"])
def test_request_is_bound_to_study_run_code_and_producer_configuration(skeleton, change):
    cfg = {"study": {"start_yyyymm": 202401, "end_yyyymm": 202412}, "firms_archive": {"mode": "build"}}
    state = skeleton / "state"
    workflow.bind_request(skeleton, state, cfg, "run", workflow.settings(skeleton, cfg))
    run_id = "run"
    if change == "study": cfg["study"]["end_yyyymm"] = 202411
    elif change == "run_id": run_id = "another"
    elif change == "producer_code": (skeleton / workflow.ARCHIVE / "src/ghana_fire_archive/api.py").write_text("# changed\n")
    elif change == "producer_version": (skeleton / workflow.ARCHIVE / "pyproject.toml").write_text('[project]\nversion="2.0.0"\n')
    elif change == "workflow_code": (skeleton / "tools/run_workflow.py").write_text("# changed\n")
    elif change == "producer_config": (skeleton / workflow.ARCHIVE / "configs/rp1.yaml").write_text("sources: []\n")
    with pytest.raises(ValueError, match="request changed"):
        workflow.bind_request(skeleton, state, cfg, run_id, workflow.settings(skeleton, cfg))


def test_preview_is_idempotent_and_never_acquires_or_imports_producer(skeleton, monkeypatch):
    monkeypatch.setattr(workflow, "archive_api", lambda _: pytest.fail("Preview must not import producer API"))
    monkeypatch.setattr(workflow, "intake_module", lambda _: pytest.fail("Preview must not stage or validate scientific data"))
    cfg = {"study": {"start_yyyymm": 202401, "end_yyyymm": 202412}, "firms_archive": {"mode": "build"}}
    state = skeleton / "state"
    result = workflow.prepare_archive_step(skeleton, state, cfg, "preview", preview=True)
    assert result["network_performed"] is False
    assert result["required_products"] == ["MODIS_SP", "VIIRS_SNPP_SP"]
    assert workflow.prepare_archive_step(skeleton, state, cfg, "preview", preview=True) == result
    assert not (state / "archive.json").exists()
    assert not (skeleton / workflow.ARCHIVE / "out").exists()
    assert not (state / ".archive_workflow.lock").exists()


@pytest.mark.parametrize("schema", [intake.SCHEMA, intake.SCHEMA_V2])
def test_bundled_legacy_and_scoped_authorities_use_correct_verification(skeleton, monkeypatch, schema):
    bundle = skeleton / workflow.FIRMS
    save(bundle / workflow.AUTHORITY, {"schema": schema})
    study = {"start_yyyymm": 202401, "end_yyyymm": 202412}
    calls = []
    def verify(path, **kwargs):
        calls.append((path, kwargs))
        return {"intake_sha256": "a" * 64}
    stub = SimpleNamespace(SCHEMA=intake.SCHEMA, verify_bundle=verify)
    monkeypatch.setattr(workflow, "intake_module", lambda _: stub)
    cfg = {"study": study, "firms_archive": {"mode": "bundled"}}
    state = skeleton / "state"
    workflow.prepare_archive_step(skeleton, state, cfg, "bundled")
    receipt = workflow.admit_archive_step(skeleton, state, cfg, "bundled", "geo-digest")
    workflow.verify_admission(skeleton, state, cfg, "bundled", "geo-digest")
    assert calls and all(path == bundle for path, _ in calls)
    assert all(kwargs == ({} if schema == intake.SCHEMA else {"study": study}) for _, kwargs in calls)
    assert receipt["bundle_root"] == workflow.FIRMS.as_posix()
    assert receipt["geography_compatibility"] is None


@pytest.mark.parametrize("report", [None, {}, {"passed": False}, {"passed": 1}, {"status": "PASS"}])
def test_acceptance_requires_an_explicit_passing_scientific_report(skeleton, report):
    target = skeleton / "validation"
    with pytest.raises(ValueError, match="passing Archive scientific validation"):
        workflow.acceptance_receipt(skeleton, target, skeleton / "missing.json", {}, report)
    assert not target.exists()


def source_case(root, *, empty=False, missing=None):
    """Adapt the ZIP fixture into the producer's complete output layout."""
    annual, accepted, study, _ = archive_case(root / "fixture", empty=empty, missing=missing)
    output = root / "producer"
    shutil.copytree(annual, output / "annual")
    evidence = accepted.parent / "evidence"
    manifest = workflow.read(evidence / "archive-manifest.json")
    exported = workflow.read(output / "annual/annual-export.json")
    quality = workflow.read(evidence / "qa-manifest.json")
    units = output / "geography/units.json"
    country = output / "geography/ghana.geojson"
    save(units, {"districts": [{"district_id": "D1", "zone_id": "Z1"}]})
    save(country, {"type": "FeatureCollection", "features": []})
    manifest["geography"] = {"units": {"path": "geography/units.json", "sha256": workflow.sha(units)},
                             "ghana": {"path": "geography/ghana.geojson", "sha256": workflow.sha(country)}}
    for part, export, qa in zip(manifest["partitions"], exported["partitions"], quality["partitions"]):
        canonical = output / part["path"]
        canonical.parent.mkdir(parents=True)
        canonical.write_text("source,year\n", encoding="utf-8")
        part["sha256"] = workflow.sha(canonical)
        part["shapefile_path"] = "annual/" + export["annual_shapefile_zip"]
        part["preparation_code_sha256"] = {"historic_producer.py": "b" * 64}
        qa["canonical_sha256"] = part["sha256"]
        destination = output / "qa" / qa["qa_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(evidence / qa["qa_path"], destination)
    path = output / "archive-manifest.json"
    save(path, manifest)
    exported["research_manifest_sha256"] = quality["research_manifest_sha256"] = workflow.sha(path)
    save(output / "annual/annual-export.json", exported)
    save(output / "qa/qa-manifest.json", quality)
    (output / "annual-current.csv").write_text("source,year\n", encoding="utf-8")
    for part, export in zip(manifest["partitions"], exported["partitions"]):
        folder = "MODIS" if part["source"] == "MODIS_SP" else "VIIRS"
        provenance = output / "annual/metadata" / folder / (Path(export["annual_shapefile_zip"]).stem + "_provenance.json")
        value = workflow.read(provenance)
        value.update(accepted_partition=part, export=export, research_manifest_sha256=workflow.sha(path))
        save(provenance, value)
    land = root / "inputs/national.shp"
    land.parent.mkdir()
    land.write_bytes(b"fixed country geometry")
    land.with_suffix(".prj").write_bytes(b"fixed country CRS")
    reference = root / workflow.ARCHIVE / "data/reference/geography/geography-manifest.json"
    save(reference, {"generated_files": {Path(item["path"]).name: item["sha256"] for item in manifest["geography"].values()},
        "source": {"members": [{"path": "data/raw/boundaries/gha_admin0" + ext,
                                  "sha256": workflow.sha(land.with_suffix(ext))} for ext in (".shp", ".prj")]},
        "coordinate_precision_decimal_places": 8})
    universe = root / workflow.FIRMS / "data/metadata/unit_universe.csv"
    universe.parent.mkdir(parents=True)
    universe.write_text("level,unit_id,parent_id\ndistrict,D1,Z1\nacz,Z1,\n", encoding="utf-8")
    shared = root / workflow.FIRMS / "data/raw/original.txt"
    shared.parent.mkdir()
    shared.write_text("original shared raw input", encoding="utf-8")
    cfg = {"study": study, "land_mask": "inputs/national.shp",
           "firms_archive": {"mode": "existing", "manifest": str(path)}}
    return path, cfg, shared


def validation_report(manifest):
    return {"passed": True, "manifest_sha256": workflow.sha(manifest),
            "annual_exports": {"passed": True, "annual_manifest_sha256": workflow.sha(manifest.parent / "annual/annual-export.json")},
            "quality_assurance": {"passed": True, "semantics_recomputed": True,
                                  "qa_manifest_sha256": workflow.sha(manifest.parent / "qa/qa-manifest.json")},
            "validator_code_sha256": {"current.py": "a" * 64}}


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_existing_source_acceptance_admission_and_consumer_are_run_local(skeleton, monkeypatch, empty, override):
    manifest, cfg, shared = source_case(skeleton, empty=empty)
    before = workflow.source_inventory(manifest)
    original = shared.read_bytes()
    calls = []
    def validate(path, verify_qa):
        calls.append((path, verify_qa))
        return validation_report(path)
    monkeypatch.setattr(workflow, "archive_api", lambda _: SimpleNamespace(validate_archive=validate))
    monkeypatch.setattr(workflow, "intake_module", lambda _: intake)
    state = skeleton / "state"
    if override: cfg["firms_archive"] = {"mode": "bundled"}
    receipt = workflow.prepare_archive_step(skeleton, state, cfg, "local", str(manifest) if override else None)
    assert calls == [(manifest, True)]
    acceptance = workflow.read(skeleton / receipt["acceptance_path"])
    assert acceptance["validation"]["report"]["passed"] is True
    assert acceptance["generation_code_identity"]["partition_identities"][0]["preparation_code_sha256"] == {"historic_producer.py": "b" * 64}
    admitted = workflow.admit_archive_step(skeleton, state, cfg, "local", "geo-receipt-hash")
    assert admitted["bundle_root"] == (workflow.FIRMS / "out/runs/local/source_inputs").as_posix()
    assert workflow.verify_admission(skeleton, state, cfg, "local", "geo-receipt-hash") == admitted
    runtime = {"io": {"inputs": {"firms_points": {sensor: {"file_glob": "native", "column_map": {}} for sensor in workflow.SOURCES}}}}
    workflow.configure_firms_inputs(runtime, skeleton, admitted)
    firms = skeleton / workflow.FIRMS
    for sensor in workflow.SOURCES:
        inp = FirmsSensorInput(**runtime["io"]["inputs"]["firms_points"][sensor])
        assert inp.admission_bundle_root == "out/runs/local/source_inputs"
        assert inp.file_glob.startswith("out/runs/local/source_inputs/data/raw/")
        shp = next(firms.glob(inp.file_glob))
        view, evidence = adapt_archive_sp(points=gpd.read_file(shp), input_config=inp,
                                          repo_root=firms, sensor=sensor, year=2024, points_path=shp)
        assert len(view) == (0 if empty else 1)
    assert workflow.source_inventory(manifest) == before
    assert shared.read_bytes() == original
    assert not (firms / "data/raw/modis").exists()
    assert not (firms / "data/raw/viirs").exists()
    with pytest.raises(ValueError, match="geography/study binding"):
        workflow.verify_admission(skeleton, state, cfg, "local", "different-geo")
    changed = manifest.parent / "qa/qa-manifest.json"
    changed.write_bytes(changed.read_bytes() + b" ")
    with pytest.raises(ValueError, match="source inventory changed"):
        workflow.verify_archive_step(skeleton, state, cfg, "local")


@pytest.mark.parametrize("preexisting_output", [False, True])
def test_build_routes_only_selected_sp_sources_to_fresh_run_local_output(skeleton, monkeypatch, preexisting_output):
    source, cfg, shared = source_case(skeleton, empty=True)
    cfg["firms_archive"] = {"mode": "build"}
    state = skeleton / "state"
    output = skeleton / workflow.ARCHIVE / "out/runs/build_run"
    original_source = workflow.source_inventory(source)
    original_shared = shared.read_bytes()
    calls = []
    def load(path, *, start, end):
        calls.append("load")
        assert path == skeleton / workflow.ARCHIVE / "configs/rp1.yaml"
        assert (start, end) == (2024, 2024)
        return {"sources": ["VIIRS_NOAA20_SP"], "selected_years": [2024], "output": "unused"}
    def download(config):
        calls.append("download")
        assert config["sources"] == ["MODIS_SP", "VIIRS_SNPP_SP"]
        assert config["selected_years"] == [2024]
        assert config["output"] == str(output)
        return {"fixture": True}
    def prepare(config, plan):
        calls.append("prepare")
        assert plan == {"fixture": True}
        shutil.copytree(source.parent, Path(config["output"]))
    def validate(path, verify_qa):
        calls.append("validate")
        assert path == output / "archive-manifest.json" and verify_qa is True
        return validation_report(path)
    monkeypatch.setattr(workflow, "archive_api", lambda _: SimpleNamespace(
        load_config=load, download=download, prepare_and_export=prepare, validate_archive=validate))
    monkeypatch.setattr(workflow, "intake_module", lambda _: intake)
    if preexisting_output:
        output.mkdir(parents=True)
        (output / "original.txt").write_text("preserved", encoding="utf-8")
        with pytest.raises(ValueError, match="exists without this build request"):
            workflow.prepare_archive_step(skeleton, state, cfg, "build_run")
        assert calls == ["load"]
        assert (output / "original.txt").read_text() == "preserved"
        assert not (state / "archive.json").exists()
    else:
        result = workflow.prepare_archive_step(skeleton, state, cfg, "build_run")
        assert calls == ["load", "download", "prepare", "validate"]
        assert result["origin_archive_manifest"] == str(output / "archive-manifest.json")
        assert result["mode"] == "build"
        assert workflow.prepare_archive_step(skeleton, state, cfg, "build_run") == result
        assert calls == ["load", "download", "prepare", "validate"]
    assert workflow.source_inventory(source) == original_source
    assert shared.read_bytes() == original_shared


@pytest.mark.parametrize("failure", ["failed_validation", "validation_mutates_source", "missing_sensor", "missing_year"])
def test_failed_or_incomplete_scientific_inputs_never_create_success_receipt(skeleton, monkeypatch, failure):
    manifest, cfg, _ = source_case(skeleton, empty=True, missing="viirs" if failure == "missing_sensor" else None)
    if failure == "missing_year": cfg["study"]["start_yyyymm"] = 202301
    def validate(_path, verify_qa):
        assert verify_qa is True
        report = validation_report(_path)
        if failure == "validation_mutates_source":
            target = manifest.parent / "annual-current.csv"
            target.write_text("changed during validation\n", encoding="utf-8")
        report["passed"] = failure != "failed_validation"
        return report
    monkeypatch.setattr(workflow, "archive_api", lambda _: SimpleNamespace(validate_archive=validate))
    monkeypatch.setattr(workflow, "intake_module", lambda _: intake)
    state = skeleton / "state"
    with pytest.raises(ValueError):
        workflow.prepare_archive_step(skeleton, state, cfg, "failure")
    assert not (state / "archive.json").exists()
    assert not (state / ".archive_workflow.lock").exists()
    assert not (skeleton / workflow.FIRMS / "out/runs/failure").exists()


@pytest.mark.parametrize("field", ["manifest", "annual_hash", "qa_hash", "annual_pass", "qa_pass", "semantics", "missing_annual", "missing_qa"])
def test_stale_incomplete_or_failed_validation_report_never_creates_acceptance(skeleton, monkeypatch, field):
    manifest, cfg, _ = source_case(skeleton, empty=True)
    monkeypatch.setattr(workflow, "intake_module", lambda _: intake)
    report = validation_report(manifest)
    if field == "manifest": report["manifest_sha256"] = "a" * 64
    elif field == "annual_hash": report["annual_exports"]["annual_manifest_sha256"] = "a" * 64
    elif field == "qa_hash": report["quality_assurance"]["qa_manifest_sha256"] = "a" * 64
    elif field == "annual_pass": report["annual_exports"]["passed"] = False
    elif field == "qa_pass": report["quality_assurance"]["passed"] = False
    elif field == "semantics": report["quality_assurance"]["semantics_recomputed"] = False
    elif field == "missing_annual": report.pop("annual_exports")
    elif field == "missing_qa": report.pop("quality_assurance")
    target = skeleton / "validation"
    with pytest.raises(ValueError, match="validation identities|annual/QA checks"):
        workflow.acceptance_receipt(skeleton, target, manifest, cfg["study"], report)
    assert not (target / "acceptance.json").exists()


def test_configure_rejects_bundle_outside_firms_project(skeleton):
    with pytest.raises(ValueError, match="inside the FIRMS project"):
        workflow.configure_firms_inputs({}, skeleton, {"bundle_root": "foreign"})
