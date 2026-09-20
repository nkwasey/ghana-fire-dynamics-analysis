from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

from rp1_analysis_v1.paths import ProjectPaths

SUBPROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = SUBPROJECT.parents[1]
MANIFEST = SUBPROJECT / "data/raw/fire_panel_manifest.json"
INVENTORY = SUBPROJECT / "data/input_sha256.json"
ORIGIN_OUTPUT_PREFIX = "RP1_Project/rp1_analysis/data/raw/"
CANONICAL_OUTPUT_PREFIX = "RP1_Project/rp1_analysis/data/raw/"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_clean_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def test_input_inventory_has_explicit_origin_and_staged_paths() -> None:
    inventory = _load(INVENTORY)
    assert inventory["provenance_schema_version"] == "rp1-input-provenance-v2"
    assert set(inventory["path_semantics"]) == {"origin_path", "staged_path"}
    assert len(inventory["files"]) == 15

    for row in inventory["files"]:
        assert set(row) == {"origin_path", "staged_path", "sha256", "size_bytes"}
        assert _is_clean_relative(row["origin_path"])
        assert _is_clean_relative(row["staged_path"])
        staged = SUBPROJECT / row["staged_path"]
        assert staged.is_file()
        assert _sha256(staged) == row["sha256"]
        assert staged.stat().st_size == row["size_bytes"]


def test_runtime_path_resolution_uses_staged_path_not_origin_path(tmp_path: Path) -> None:
    staged = tmp_path / "data/raw/value.txt"
    staged.parent.mkdir(parents=True)
    staged.write_text("governed\n", encoding="utf-8")
    inventory = {
        "schema_version": "rp1-analysis-v1.0",
        "provenance_schema_version": "rp1-input-provenance-v2",
        "path_semantics": {},
        "files": [
            {
                "origin_path": "historical/location/that/is/not/present.txt",
                "staged_path": "data/raw/value.txt",
                "sha256": _sha256(staged),
                "size_bytes": staged.stat().st_size,
            }
        ],
    }
    (tmp_path / "data/input_sha256.json").write_text(json.dumps(inventory), encoding="utf-8")
    resolved = ProjectPaths(tmp_path).all_hashed_inputs
    assert resolved == (staged.resolve(),)
    assert not (tmp_path / inventory["files"][0]["origin_path"]).exists()


def test_fire_panel_manifest_has_explicit_path_provenance() -> None:
    manifest = _load(MANIFEST)
    assert manifest["provenance_schema_version"] == "rp1-fire-panel-provenance-v2"
    assert set(manifest["path_semantics"]) == {"origin_path", "staged_path"}
    assert manifest["repo_root"] == "."
    assert not {"unit_universe_path", "af_root", "ba2001_root", "ba2012_root"}.intersection(
        manifest
    )

    for root in manifest["source_roots"].values():
        assert set(root) == {"origin_path", "staged_path"}
        assert _is_clean_relative(root["origin_path"])
        if root["staged_path"] is not None:
            assert _is_clean_relative(root["staged_path"])
            assert (REPOSITORY / root["staged_path"]).exists()

    for family in manifest["families"]:
        assert set(family["root"]) == {"origin_path", "staged_path"}
        assert "root_dir" not in family
        for row in family["files"]:
            assert "path" not in row
            assert "origin_path" in row and "staged_path" in row
            assert _is_clean_relative(row["origin_path"])
            if row["staged_path"] is not None:
                assert _is_clean_relative(row["staged_path"])
                staged = REPOSITORY / row["staged_path"]
                assert staged.is_file()
                assert _sha256(staged) == row["sha256"]


def test_manifest_output_origins_preserved_and_staged_paths_resolve() -> None:
    manifest = _load(MANIFEST)
    outputs = manifest["outputs"]
    assert set(outputs) == {
        "fire_panel_acz",
        "fire_panel_district",
        "key_audit",
        "manifest",
        "merge_summary",
    }
    for name, row in outputs.items():
        assert "path" not in row
        assert row["origin_path"].startswith(ORIGIN_OUTPUT_PREFIX)
        assert row["staged_path"].startswith(CANONICAL_OUTPUT_PREFIX)
        staged = REPOSITORY / row["staged_path"]
        assert staged.is_file()
        if name != "manifest":
            assert _sha256(staged) == row["sha256"]
        else:
            assert "sha256" not in row


def test_unshipped_active_fire_intermediates_are_provenance_only() -> None:
    manifest = _load(MANIFEST)
    active_root = manifest["source_roots"]["active_fire"]
    assert active_root["staged_path"] is None
    assert active_root["origin_path"].startswith(
        "RP1_Project/rp1_mv_firms_panels/out/runs/ghana_full/"
    )
    active_rows = [
        row
        for family in manifest["families"]
        if family["source_kind"] in {"modis_af", "viirs_af"}
        for row in family["files"]
    ]
    assert len(active_rows) == 20
    assert all(row["staged_path"] is None for row in active_rows)


def test_staged_paths_are_canonical_and_relative() -> None:
    texts: list[str] = []
    inventory = _load(INVENTORY)
    texts.extend(row["staged_path"] for row in inventory["files"])
    manifest = _load(MANIFEST)
    for root in manifest["source_roots"].values():
        if root["staged_path"] is not None:
            texts.append(root["staged_path"])
    for family in manifest["families"]:
        if family["root"]["staged_path"] is not None:
            texts.append(family["root"]["staged_path"])
        texts.extend(
            row["staged_path"] for row in family["files"] if row["staged_path"] is not None
        )
    texts.extend(row["staged_path"] for row in manifest["outputs"].values())

    assert texts
    for value in texts:
        assert _is_clean_relative(value)
        assert "/home/" not in value
        assert "/mnt/" not in value
        assert ":\\Users\\" not in value


def test_regeneration_script_is_idempotent_check() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SUBPROJECT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(SUBPROJECT / "scripts/regenerate_data_provenance.py"),
            "--check",
        ],
        cwd=SUBPROJECT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "RP1_DATA_PROVENANCE_REGENERATION=PASS" in result.stdout
