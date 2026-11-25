"""Independent regression review of workflow authority and reuse boundaries."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow_module():
    spec = importlib.util.spec_from_file_location("archive_workflow_independent_review", ROOT / "tools/run_workflow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("change", ["rehashed_raw", "missing_component"])
def test_geo_reuse_binds_input_fingerprint_to_original_output_manifest(tmp_path, monkeypatch, change):
    workflow = workflow_module()
    monkeypatch.setattr(workflow, "ROOT", tmp_path)
    source = tmp_path / "geo/out/original"
    source.mkdir(parents=True)
    config = {"project_root": "..", "outputs": {"root": "out"}, "inputs": {}}
    fingerprint = {}
    raw_files = {}
    for role in ("districts", "zones", "national"):
        raw = tmp_path / f"geo/raw/{role}/{role}.shp"
        raw.parent.mkdir(parents=True)
        raw.write_bytes(b"original geometry")
        raw_files[role] = raw
        config["inputs"][role] = {"path": raw.relative_to(tmp_path / "geo").as_posix()}
        fingerprint[role] = {"parts": {raw.name: workflow.sha(raw)}}
    config_path = tmp_path / "geo/configs/geography.yaml"
    config_path.parent.mkdir()
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    fingerprint["config_sha256"] = workflow.sha(config_path)
    write_json(source / "inputs_fingerprint.json", fingerprint)
    write_json(source / "outputs_manifest.json", {"files": {"inputs_fingerprint.json": {
        "sha256": workflow.sha(source / "inputs_fingerprint.json")}}})
    write_json(source / "contract/stage1_contract_manifest.json", {"synthetic": True})
    write_json(tmp_path / "RP1_Project/geo_handoff_manifest.json", {
        "schema": "rp1-geo-handoff-v2", "source_run": {"run_id": "original"}, "files": {},
        "source_output_manifest_sha256": workflow.sha(source / "outputs_manifest.json"),
        "source_contract_sha256": workflow.sha(source / "contract/stage1_contract_manifest.json")})
    state = tmp_path / "state"
    workflow.reuse_geo_handoff(state, {"geo_config": "geo/configs/geography.yaml"})
    # Updating a mutable fingerprint beside changed raw bytes cannot establish
    # that the unchanged staged geometry was generated from those new inputs.
    if change == "rehashed_raw":
        raw_files["national"].write_bytes(b"new source geometry")
        fingerprint["national"]["parts"][raw_files["national"].name] = workflow.sha(raw_files["national"])
        write_json(source / "inputs_fingerprint.json", fingerprint)
    else:
        raw_files["national"].unlink()
    with pytest.raises(ValueError, match="fingerprint|generation|manifest|source bytes"):
        workflow.verified_geo(state)


def test_archive_reverification_requires_requested_source_root(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("archive_stage_independent_review", ROOT / "tools/firms_archive_workflow.py")
    archive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive)
    original, different = tmp_path / "requested/archive-manifest.json", tmp_path / "different/archive-manifest.json"
    write_json(original, {"synthetic": True})
    write_json(different, {"synthetic": True})
    state = tmp_path / "state"
    state.mkdir()
    cfg = {"firms_archive": {"mode": "existing", "manifest": str(original)},
           "study": {"start_yyyymm": 202401, "end_yyyymm": 202412}}
    monkeypatch.setattr(archive, "producer_identity", lambda _: {"version": "test"})
    # The scientific validator can admit identical bytes in either source
    # directory; this regression isolates the workflow's selected-origin bind.
    monkeypatch.setattr(archive, "check_source_inventory", lambda *_: None)
    monkeypatch.setattr(archive, "intake_module", lambda _: SimpleNamespace(
        _authority=SimpleNamespace(validate_acceptance=lambda *_args, **_kwargs: {})))
    request, _ = archive.bind_request(tmp_path, state, cfg, "test", archive.settings(tmp_path, cfg))
    acceptance = state / "validation/acceptance.json"
    write_json(acceptance, {"status": "PASS"})
    write_json(state / "archive.json", {"mode": "existing", "request_sha256": archive.sha(request),
        "origin_archive_manifest": str(different), "source_inventory": [],
        "acceptance_path": acceptance.relative_to(tmp_path).as_posix(), "acceptance_sha256": archive.sha(acceptance)})
    with pytest.raises(ValueError, match="origin|source|request"):
        archive.verify_archive_step(tmp_path, state, cfg, "test")
