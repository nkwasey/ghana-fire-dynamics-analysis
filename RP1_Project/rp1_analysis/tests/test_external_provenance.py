from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rp1_analysis_v1.provenance_paths import valid_origin_path


@pytest.mark.parametrize("origin", ["/home/user/results/file.csv", "C:/Users/user/results/file.csv", "project/results/file.csv"])
def test_manifest_preserves_origin_and_checks_staged_bytes(tmp_path, origin):
    script = Path(__file__).resolve().parents[1] / "scripts/regenerate_data_provenance.py"
    spec = importlib.util.spec_from_file_location("regen_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = tmp_path / "RP1_Project/rp1_analysis/data/raw"
    raw.mkdir(parents=True)
    (raw / "file.csv").write_bytes(b"original")
    digest = hashlib.sha256(b"original").hexdigest()
    manifest = {"source_roots": {}, "families": [], "outputs": {"panel": {"origin_path": origin, "sha256": digest}}}
    result = module.normalise_panel_manifest(manifest, repo_root=tmp_path)
    assert result["outputs"]["panel"]["origin_path"] == origin
    assert result["outputs"]["panel"]["sha256"] == digest
    assert result["outputs"]["panel"]["staged_path"] == "RP1_Project/rp1_analysis/data/raw/file.csv"
    (raw / "file.csv").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash changed"):
        module.normalise_panel_manifest(manifest, repo_root=tmp_path)


@pytest.mark.parametrize("path", ["", "/home/user/../secret", "C:relative/file.csv", "relative/../file.csv", "a\\b", "x\nfile"])
def test_invalid_origin_paths_are_rejected(path):
    assert not valid_origin_path(path)


@pytest.mark.parametrize("origin", ["/home/user/output.csv", "C:/Users/user/output.csv"])
def test_runtime_verifies_staged_file_without_accessing_external_origin(tmp_path, monkeypatch, origin):
    from rp1_analysis_v1 import integration
    from rp1_analysis_v1.paths import ProjectPaths

    staged = tmp_path / "data/raw/output.csv"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"data")
    inventory = {"schema_version": "test", "provenance_schema_version": "rp1-input-provenance-v2",
                 "files": [{"origin_path": origin, "staged_path": "data/raw/output.csv",
                            "sha256": hashlib.sha256(b"data").hexdigest(), "size_bytes": 4}]}
    (tmp_path / "data/input_sha256.json").write_text(json.dumps(inventory))
    bundle = SimpleNamespace(analysis=SimpleNamespace(schema_version="test"), configuration_sha256="hash",
                             data_schema=SimpleNamespace(data_schema_version="test", panel_schema_version="test",
                                 panels={"test":SimpleNamespace(path="data/raw/output.csv")},
                                 auxiliary_inputs={}, geometries={}, provenance={"expected_governed_files":1}))
    def stop_after_inventory(*args):
        raise ValueError("reached scientific validation")
    monkeypatch.setattr(integration, "load_data_authorities", stop_after_inventory)
    report = integration.validate_governed_inputs(ProjectPaths(tmp_path), bundle=bundle, raise_on_failure=False)
    assert report["canonical_input_identity"] == "MATCH"
    assert report["hashes"][0]["origin_path"] == origin
    assert report["validation_error"]["message"] == "reached scientific validation"
