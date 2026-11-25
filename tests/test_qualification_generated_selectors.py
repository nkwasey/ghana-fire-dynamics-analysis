"""Clean qualification projections must not inherit generated-run selections."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SELECTORS = (
    "RP1_ANALYSIS_TEST_RUN",
    "RP1_EXPORT_REGRESSION_ANALYSIS_ROOT",
    "RP1_EXPORT_REGRESSION_RUN_ID",
)


def qualifier():
    spec = importlib.util.spec_from_file_location(
        "qualification_generated_selectors_test", ROOT / "tools/qualify_environment.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("present", [(), SELECTORS[:1], SELECTORS[1:], SELECTORS])
def test_clean_test_environment_removes_only_selectors_without_mutating_input(present):
    q = qualifier()
    source = {"ordinary": "preserve", "RP1_NOTEBOOK_RUN_ID": "operational", **{key: "selected" for key in present}}
    original = source.copy()
    result = q._projected_test_environment(source)
    assert source == original
    assert result is not source
    assert all(key not in result for key in SELECTORS)
    assert result == {key: value for key, value in source.items() if key not in SELECTORS}


@pytest.mark.parametrize("source_only", [False, True])
def test_actual_qualifier_sanitizes_collection_and_full_tests_only(tmp_path, monkeypatch, source_only):
    """Exercise qualify's real wiring, stopping before any actual test/build command.

    Runtime/package operations are bounded synthetic stand-ins. Assertions inspect
    the actual run_step arguments emitted by qualify, including parent retention.
    """
    q = qualifier()
    source = tmp_path / "source"
    source.mkdir()
    proof = tmp_path / "proof"
    for key in SELECTORS:
        monkeypatch.setenv(key, "operator-selected-reference")
    monkeypatch.setenv("RP1_NOTEBOOK_RUN_ID", "retain-operational-identity")
    parent = dict(os.environ)
    monkeypatch.setattr(q, "_environment_identity", lambda **kwargs: {"status": "PASS"})
    monkeypatch.setattr(q, "_bootstrap_package_specs", lambda *_: ({"fixture": "package"},))
    monkeypatch.setattr(q, "operational_package_state", lambda *_: {"fixture": {"status": "PASS"}})
    directories = {name: proof / name for name in ("logs", "runtime", "wheels", "isolated_install", "clean_projection")}
    def workspace(*_):
        for directory in directories.values():
            directory.mkdir(parents=True)
        return directories
    monkeypatch.setattr(q, "_prepare_external_workspace", workspace)
    inventory = SimpleNamespace(entries=(), exclusions=(), inventory_sha256="fixture-inventory")
    captured = {}
    def projected_environment(*args, base_environment):
        captured["common"] = base_environment
        captured["projected"] = dict(base_environment, PROJECTED_FIXTURE="retained")
        return captured["projected"]
    runtime = {
        "contract": SimpleNamespace(schema_version="fixture", contract_id="fixture"),
        "qualification_config_hashes": {}, "qualification_config_sha256": "fixture",
        "inventory_governed_source": lambda *a: inventory,
        "project_governed_source": lambda *a, **kw: SimpleNamespace(),
        "verify_projected_inventory": lambda *a: inventory,
        "probe_projected_imports": lambda *a, **kw: {"status": "PASS"},
        "write_projection_evidence": lambda *a: None,
        "projected_import_environment": projected_environment,
        "remove_generated_artifacts_from_projection": lambda *a: (),
    }
    monkeypatch.setattr(q, "_load_runtime_authorities", lambda *_: runtime)
    monkeypatch.setattr(q, "_c3_source_checks", lambda *a: {})
    commands = {}
    class BoundaryReached(Exception):
        pass
    def step(name, command, logs, *, cwd, env):
        commands[name] = {"env": env, "command": command, "cwd": cwd}
        if name == "full_pytest":
            raise BoundaryReached()
        return {"status": "PASS"}
    monkeypatch.setattr(q, "run_step", step)
    with pytest.raises(BoundaryReached):
        q.qualify(repository_root=source, evidence_dir=proof, source_only=source_only,
                  pytest_base_temp=tmp_path / "fresh-pytest")
    assert dict(os.environ) == parent
    for kind in ("common", "projected"):
        assert all(captured[kind][key] == parent[key] for key in SELECTORS)
    for name in ("pytest_collect", "full_pytest"):
        env = commands[name]["env"]
        assert env is not captured["projected"] and env is not captured["common"]
        assert all(key not in env for key in SELECTORS)
        assert env["PROJECTED_FIXTURE"] == "retained"
        assert env["RP1_NOTEBOOK_RUN_ID"] == parent["RP1_NOTEBOOK_RUN_ID"]
        assert commands[name]["cwd"] == directories["clean_projection"]
    assert commands["pytest_collect"]["env"] is commands["full_pytest"]["env"]
    assert "--collect-only" in commands["pytest_collect"]["command"]
    assert "--collect-only" not in commands["full_pytest"]["command"]
    assert commands["pip_check"]["env"] is captured["common"]
    for name in ("compileall", "stage1_example_regeneration"):
        assert commands[name]["env"] is captured["projected"]
        assert all(key in commands[name]["env"] for key in SELECTORS)
