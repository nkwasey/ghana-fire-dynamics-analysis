from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rp1_environment_preflight", ROOT / "tools/preflight_environment.py")
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_runtime_metadata_and_conflicting_distribution_versions_are_distinct_failures():
    good = {"distribution": "numpy", "runtime_version": "2.5.4", "metadata_version": "2.5.4",
            "discovered_metadata_versions": ["2.5.4"]}
    assert preflight.assess_versions([good]) == []
    mismatch = {**good, "metadata_version": "2.4.6"}
    assert any("imported runtime 2.5.4 differs from metadata 2.4.6" in issue
               for issue in preflight.assess_versions([mismatch]))
    conflict = {**good, "discovered_metadata_versions": ["2.5.4", "2.4.6"]}
    assert any("conflicting distribution metadata" in issue
               for issue in preflight.assess_versions([conflict]))


def test_origin_probe_rejects_sibling_checkout_and_missing_origin(tmp_path):
    selected = tmp_path / "selected/src"
    other = tmp_path / "other/src"
    expected = {"analysis": selected}
    assert preflight.assess_origins({"analysis": str(selected / "analysis/__init__.py")}, expected) == []
    assert "outside expected source root" in preflight.assess_origins(
        {"analysis": str(other / "analysis/__init__.py")}, expected)[0]
    assert "missing filesystem origin" in preflight.assess_origins({"analysis": None}, expected)[0]


def test_hung_probe_is_bounded_and_reported_as_failure(tmp_path):
    result = preflight.run_bounded("hung", [sys.executable, "-c", "import time; time.sleep(15)"],
                                   cwd=tmp_path, env=os.environ, timeout=0.1)
    assert result["status"] == "FAIL"
    assert result["details"]["timeout_seconds"] == 0.1
    assert any("time limit" in issue for issue in result["issues"])
    assert result["elapsed_seconds"] < 10


def test_nonzero_worker_exit_cannot_masquerade_as_pass(tmp_path):
    command = [sys.executable, "-c", "import json; print(json.dumps({'status':'PASS','issues':[]})); raise SystemExit(3)"]
    result = preflight.run_bounded("broken", command, cwd=tmp_path, env=os.environ, timeout=5)
    assert result["status"] == "FAIL"
    assert "Probe exited with status 3" in result["issues"]


def test_evidence_must_be_external_and_existing_evidence_is_preserved(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    with pytest.raises(ValueError, match="external and non-overlapping"):
        preflight._external_path(root / "out/evidence.json", root, directory=False)
    destination = tmp_path / "evidence.json"
    assert preflight._external_path(destination, root, directory=False) == destination
    destination.write_text("original", encoding="utf-8")
    with pytest.raises(ValueError, match="not overwritten"):
        preflight._external_path(destination, root, directory=False)
    assert destination.read_text(encoding="utf-8") == "original"


def test_unavailable_dependency_is_not_reported_as_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "_native_environment", lambda scratch: {"scope": "fixture"})
    def missing():
        raise ModuleNotFoundError("fixture missing dependency")
    monkeypatch.setattr(preflight, "_probe_versions", missing)
    result = preflight.worker("versions", ROOT, tmp_path, "node", 1)
    assert result["status"] == "UNAVAILABLE"
    assert "fixture missing dependency" in result["issues"][0]


@pytest.mark.parametrize("module_name,distribution", [
    ("pydantic", "pydantic"), ("requests", "requests"), ("shapefile", "pyshp"),
    ("nbformat", "nbformat"), ("nbclient", "nbclient"),
    ("ipykernel", "ipykernel"), ("jupyter_client", "jupyter_client"),
    ("markdown_it", "markdown-it-py"), ("build", "build"),
])
def test_declared_core_and_notebook_dependencies_are_actually_probed(
        module_name, distribution, tmp_path, monkeypatch):
    assert (module_name, distribution) in preflight.DEPENDENCIES
    monkeypatch.setattr(preflight, "_native_environment", lambda scratch: {"scope": "fixture"})
    monkeypatch.setattr(preflight.importlib.metadata, "distributions", lambda: [])
    monkeypatch.setattr(preflight.importlib.metadata, "version", lambda name: "1.0")
    def imported(name):
        if name == module_name:
            raise ModuleNotFoundError(f"fixture missing {module_name}")
        return SimpleNamespace(__version__="1.0", __file__=str(tmp_path / name))
    monkeypatch.setattr(preflight.importlib, "import_module", imported)
    result = preflight.worker("versions", ROOT, tmp_path, "node", 1)
    assert result["status"] == "UNAVAILABLE"
    assert f"fixture missing {module_name}" in result["issues"][0]


def test_aggregate_preflight_cannot_count_unavailable_probe_as_success(tmp_path, monkeypatch):
    def run(name, command, **kwargs):
        status = "UNAVAILABLE" if name == "kernel" else "PASS"
        return preflight._result(name, status, issues=["fixture missing kernel"] if status == "UNAVAILABLE" else [])
    monkeypatch.setattr(preflight, "run_bounded", run)
    scratch = tmp_path / "scratch"
    report = preflight.run_preflight(tmp_path / "source", scratch_parent=scratch)
    assert report["status"] == "UNAVAILABLE"
    assert [row["probe"] for row in report["probes"]] == list(preflight.PROBES)
    assert list(scratch.iterdir()) == []


def test_strict_preflight_checks_only_execution_prerequisites(tmp_path, monkeypatch):
    commands = {}
    executable = tmp_path / "SaTScan Batch"

    def run(name, command, **kwargs):
        commands[name] = command
        return preflight._result(name, "FAIL" if name == "satscan" else "PASS")

    monkeypatch.setattr(preflight, "run_bounded", run)
    report = preflight.run_preflight(ROOT, scratch_parent=tmp_path / "scratch",
                                    strict_execution=executable)
    assert report["status"] == "FAIL"
    assert list(commands) == ["event_loop", "kernel", "satscan"]
    assert commands["satscan"][-2:] == ["--strict-execution", str(executable.resolve())]
    assert all("--strict-execution" not in commands[key] for key in ["event_loop", "kernel"])


@pytest.mark.parametrize("version,status", [("10.3.3", "PASS"), ("10.3.2", "FAIL")])
def test_strict_preflight_uses_governed_satscan_version(tmp_path, monkeypatch, version, status):
    from rp1_analysis_v1 import satscan_io

    executable = tmp_path / "SaTScanBatch"
    identity = satscan_io.ExecutableProvenance(str(executable), "a" * 64, version)
    monkeypatch.setattr(satscan_io, "executable_provenance", lambda path: identity)
    result = preflight.worker("satscan", ROOT, tmp_path, "node", 1, executable)
    assert result["status"] == status
    assert result["details"]["expected_version"] == "10.3.3"
    assert result["details"]["version"] == version
    assert result["details"]["sha256"] == "a" * 64


def test_node_major_version_requirement_is_enforced(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda command: "/selected/node")
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="v22.1.0\n"))
    assert preflight._probe_node("node", 1)["status"] == "FAIL"
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="v24.1.0\n"))
    assert preflight._probe_node("node", 1)["status"] == "PASS"


def test_process_tree_selection_excludes_unrelated_processes():
    pairs = [(1, 0), (10, 1), (11, 10), (12, 11), (20, 1), (21, 20)]
    assert preflight.descendant_pids(pairs, 10) == [11, 12]


def test_native_probe_configuration_uses_actual_base_prefix(tmp_path, monkeypatch):
    prefix = tmp_path / "interpreter"
    dll = prefix / "Library/bin"
    proj = prefix / "Library/share/proj"
    gdal = prefix / "Library/share/gdal"
    dll.mkdir(parents=True)
    proj.mkdir(parents=True)
    gdal.mkdir(parents=True)
    (proj / "proj.db").write_bytes(b"fixture")
    monkeypatch.setattr(preflight.sys, "base_prefix", str(prefix))
    for key in ["PATH", "PROJ_DATA", "GDAL_DATA", "MPLCONFIGDIR", "IPYTHONDIR", "JUPYTER_RUNTIME_DIR", "PYTHONDONTWRITEBYTECODE"]:
        monkeypatch.setenv(key, os.environ.get(key, ""))
    monkeypatch.setenv("PROJ_DATA", str(tmp_path / "foreign/proj"))
    before = len(preflight._DLL_HANDLES)
    try:
        result = preflight._native_environment(tmp_path / "scratch")
        assert result["base_prefix"] == str(prefix)
        assert result["effective_data_environment"]["PROJ_DATA"] == str(proj)
        assert result["effective_data_environment"]["GDAL_DATA"] == str(gdal)
        assert all(Path(value).is_relative_to(prefix) for value in result["native_search_paths"])
    finally:
        for handle in preflight._DLL_HANDLES[before:]:
            handle.close()
        del preflight._DLL_HANDLES[before:]


def test_cli_keeps_existing_evidence_and_returns_nonzero_for_incomplete_preflight(tmp_path, monkeypatch, capsys):
    root = tmp_path / "source"
    root.mkdir()
    output = tmp_path / "evidence/preflight.json"
    monkeypatch.setattr(preflight, "run_preflight", lambda *args, **kwargs: {
        "status": "UNAVAILABLE", "probes": [preflight._result("kernel", "UNAVAILABLE", issues=["missing fixture"])]})
    assert preflight.main(["--project-root", str(root), "--json-out", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "UNAVAILABLE"
    original = output.read_bytes()
    with pytest.raises(SystemExit) as error:
        preflight.main(["--project-root", str(root), "--json-out", str(output)])
    assert error.value.code == 2
    assert output.read_bytes() == original
    assert "not overwritten" in capsys.readouterr().err
