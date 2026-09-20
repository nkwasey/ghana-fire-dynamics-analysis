from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SUBPROJECT = Path(__file__).resolve().parents[1]
SRC = SUBPROJECT / "src"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_in_subprocess(root: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["RP1_ANALYSIS_V1_ROOT"] = str(root)
    # Keep validation subprocesses isolated from pytest's optional tracing plugin.
    env["DD_TRACE_ENABLED"] = "false"
    code = """
import json
from rp1_analysis_v1.integration import validate_governed_inputs
r = validate_governed_inputs()
print(json.dumps({
    'input_validation_status': r['input_validation_status'],
    'canonical_input_identity': r['canonical_input_identity'],
    'panel_status': r['panel_schema_validation']['status'],
    'geometry_status': r['geometry_summary']['status'],
    'reconciliation_status': r['reconciliation_summary']['status'],
    'changed': [x['staged_path'] for x in r['current_input_identities'] if not x['identity_match']],
}, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _linked_copy(src: Path, dst: Path) -> None:
    def link_or_copy(source: str, target: str) -> str:
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        return target

    shutil.copytree(src, dst, copy_function=link_or_copy)


def _candidate_root(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    root.mkdir()
    shutil.copytree(SUBPROJECT / "config", root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    _linked_copy(SUBPROJECT / "data", root / "data")
    marker = root / "src/rp1_analysis_v1"
    marker.mkdir(parents=True)
    shutil.copy2(SUBPROJECT / "src/rp1_analysis_v1/__init__.py", marker / "__init__.py")
    return root


def _replace_json(path: Path, payload: dict, *, indent: int | None, sort_keys: bool) -> None:
    # The candidate tree may use hard links. Replace the directory entry rather
    # than modifying a linked canonical file in place.
    path.unlink()
    text = json.dumps(payload, indent=indent, sort_keys=sort_keys)
    path.write_text(text + "\n", encoding="utf-8")


def test_provenance_mutation_and_equivalent_serialisation_pass_as_noncanonical(
    tmp_path: Path,
) -> None:
    root = _candidate_root(tmp_path)

    # Case B: provenance-only content mutation that leaves the scientific contract valid.
    merge_path = root / "data/raw/fire_panel_merge_summary.json"
    merge_payload = json.loads(merge_path.read_text(encoding="utf-8"))
    merge_payload["merge_run_id"] = "v12301_runtime_reconstruction"
    _replace_json(merge_path, merge_payload, indent=2, sort_keys=True)

    # Case C: semantically equivalent JSON serialisation with different bytes.
    manifest_path = root / "data/raw/fire_panel_manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _replace_json(manifest_path, manifest_payload, indent=None, sort_keys=False)

    report = _validate_in_subprocess(root)
    assert report["input_validation_status"] == "PASS"
    assert report["canonical_input_identity"] == "DIFFERENT"
    assert set(report["changed"]) == {
        "data/raw/fire_panel_merge_summary.json",
        "data/raw/fire_panel_manifest.json",
    }
    assert report["panel_status"] == "PASS"
    assert report["reconciliation_status"] == "PASS"


def test_canonical_release_bytes_still_match_immutable_inventory() -> None:
    inventory_path = SUBPROJECT / "data/input_sha256.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert inventory["schema_version"] == "rp1-analysis-v1.1"
    assert inventory["provenance_schema_version"] == "rp1-input-provenance-v2"
    assert len(inventory["files"]) == 15
    for item in inventory["files"]:
        path = SUBPROJECT / item["staged_path"]
        assert path.is_file(), item["staged_path"]
        assert path.stat().st_size == item["size_bytes"], item["staged_path"]
        assert _sha256(path) == item["sha256"], item["staged_path"]
