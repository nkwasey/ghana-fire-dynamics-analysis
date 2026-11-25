import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from rp1_analysis_v1.ba_support import PROFILE_OUTPUTS, BAObservationSupportError
from _c3_analysis_fixture import fixture

spec = importlib.util.spec_from_file_location("prepare_profile_handoff", Path(__file__).resolve().parents[1] / "scripts/prepare_profile_handoff.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_handoff_preserves_manifest_and_checks_each_output(tmp_path):
    source = tmp_path / "run"
    source.mkdir()
    outputs = {}
    for key, name in PROFILE_OUTPUTS.items():
        data = (key + " data").encode()
        (source / name).write_bytes(data)
        outputs[key] = {"origin_path": f"run/{name}", "staged_path": f"run/{name}", "sha256": hashlib.sha256(data).hexdigest()}
    outputs["manifest"] = {"origin_path": "run/fire_panel_manifest.json", "staged_path": "run/fire_panel_manifest.json"}
    _, manifest, _, _ = fixture()
    manifest.update(outputs=outputs, source_roots={"example": "unchanged"})
    original = json.dumps(manifest).encode()
    (source / "fire_panel_manifest.json").write_bytes(original)
    target = tmp_path / "handoff"
    module.prepare(source, target)
    updated = json.loads((target / "fire_panel_manifest.json").read_bytes())
    assert (target / "original_merger_manifest.json").read_bytes() == original
    assert updated["analysis_handoff"]["original_manifest_sha256"] == hashlib.sha256(original).hexdigest()
    assert updated["source_roots"] == manifest["source_roots"]
    assert updated["outputs"]["fire_panel_district"]["origin_path"] == manifest["outputs"]["fire_panel_district"]["origin_path"]
    assert updated["outputs"]["fire_panel_district"]["staged_path"].endswith("data/raw/" + PROFILE_OUTPUTS["fire_panel_district"])
    with pytest.raises(ValueError, match="must not exist"):
        module.prepare(source, target)
    (source / PROFILE_OUTPUTS["fire_panel_district"]).write_text("tampered AF")
    with pytest.raises(BAObservationSupportError, match="hash"):
        module.prepare(source, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
