"""Source qualification leaves existing destinations intact."""
import importlib.util
from pathlib import Path
import sys

import pytest


def qualifier():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("qualify_source_checkout", root / "tools/qualify_source_checkout.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checkout_qualifier_preserves_occupied_external_evidence(tmp_path, monkeypatch):
    module = qualifier()
    occupied = tmp_path / "evidence"
    occupied.mkdir()
    proof = occupied / "prior.json"
    proof.write_bytes(b"retain this evidence")
    monkeypatch.setattr(sys, "argv", ["qualify_source_checkout.py", "--evidence-dir", str(occupied)])
    monkeypatch.setattr(module, "verify_import_origins", lambda _: None)
    with pytest.raises(SystemExit, match="evidence directory must be fresh"):
        module.main()
    assert proof.read_bytes() == b"retain this evidence"


def test_source_qualification_uses_fresh_base_and_ignores_inherited_pytest_options(tmp_path, monkeypatch):
    module = qualifier()
    source, evidence_root, pytest_base = (tmp_path / name for name in ("source", "evidence", "pytest"))
    source.mkdir()
    inherited = {"PYTEST_ADDOPTS": "--collect-only", "PYTEST_DEBUG_TEMPROOT": "hidden",
                 "RP1_ANALYSIS_TEST_RUN": "other_checkout", "RP1_EXPORT_REGRESSION_RUN_ID": "other_run",
                 "RP1_EXPORT_REGRESSION_ANALYSIS_ROOT": "other_root", "RP1_NOTEBOOK_RUN_ID": "operator_run"}
    for name in ("inventory_governed_source", "project_governed_source", "probe_projected_imports",
                 "remove_generated_artifacts_from_projection", "verify_projected_inventory"):
        monkeypatch.setattr(module, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "projected_import_environment", lambda *_: inherited.copy())
    commands = []
    monkeypatch.setattr(module, "run", lambda command, *, cwd, env: commands.append((command, env)))

    module._qualify_projected_source(source, evidence_root, pytest_base_temp=pytest_base)

    command, env = commands[-1]
    assert command[-2:] == ["--basetemp", str(pytest_base)]
    assert set(env).intersection(inherited) == {"RP1_NOTEBOOK_RUN_ID"}
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert inherited["PYTEST_ADDOPTS"] == "--collect-only"
