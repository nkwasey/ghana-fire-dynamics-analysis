"""Regression coverage for explicit, run-local generated-publication prerequisites."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

import generated_run_reference as reference
import rp1_analysis_v1.integration as integration
import rp1_analysis_v1.publication_sources as sources


@pytest.fixture(autouse=True)
def isolated_selection(monkeypatch):
    monkeypatch.delenv("RP1_ANALYSIS_TEST_RUN", raising=False)
    reference.clear_reference_cache()
    yield
    reference.clear_reference_cache()


def _family(root, run="chosen"):
    for suffix in ("_pub", "_sec", "_close"):
        (root / "out/runs" / (run + suffix)).mkdir(parents=True)


def _validator(monkeypatch, *, status="PASS", external="RESULTS_VALIDATED"):
    calls = []
    def validate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status=status, secondary_external_state=external)
    monkeypatch.setattr(integration, "validate_run_authority", validate)
    return calls


def test_no_selection_does_not_choose_even_a_single_complete_run(tmp_path):
    _family(tmp_path)
    assert reference.selected_run_base(tmp_path) == reference.SELECTION_REQUIRED
    with pytest.raises(pytest.skip.Exception, match="explicitly set"):
        reference.require_selected_run(tmp_path, reference.selected_run_base(tmp_path))


@pytest.mark.parametrize("value", ["../chosen", "/absolute", "chosen/other", "chosen\\other", " chosen"])
def test_invalid_explicit_selection_is_rejected(tmp_path, monkeypatch, value):
    monkeypatch.setenv("RP1_ANALYSIS_TEST_RUN", value)
    with pytest.raises(ValueError, match="portable"):
        reference.selected_run_base(tmp_path)


def test_explicit_missing_family_fails_instead_of_skipping(tmp_path, monkeypatch):
    monkeypatch.setenv("RP1_ANALYSIS_TEST_RUN", "chosen")
    with pytest.raises(pytest.fail.Exception, match="incomplete"):
        reference.require_selected_run(tmp_path, "chosen")


def test_explicit_incomplete_family_fails(tmp_path, monkeypatch):
    (tmp_path / "out/runs/chosen_pub").mkdir(parents=True)
    calls = _validator(monkeypatch)
    with pytest.raises(pytest.fail.Exception, match="incomplete"):
        reference.require_selected_run(tmp_path, "chosen")
    assert not calls


def test_selected_reference_delegates_to_real_validator_once_per_family(tmp_path, monkeypatch):
    _family(tmp_path)
    calls = _validator(monkeypatch)
    reference.require_selected_run(tmp_path, "chosen")
    reference.require_selected_run(tmp_path, "chosen", external=True)
    assert len(calls) == 1
    assert calls[0]["run_id"] == "chosen"
    assert calls[0]["paths"].root == tmp_path.resolve()


def test_modified_reference_invalidates_cached_validation(tmp_path, monkeypatch):
    _family(tmp_path)
    calls = _validator(monkeypatch)
    reference.require_selected_run(tmp_path, "chosen")
    (tmp_path / "out/runs/chosen_pub/new.csv").write_text("modified")
    reference.require_selected_run(tmp_path, "chosen")
    assert len(calls) == 2


def test_change_during_validation_is_rejected(tmp_path, monkeypatch):
    _family(tmp_path)
    def mutate(**kwargs):
        (tmp_path / "out/runs/chosen_pub/new.csv").write_text("modified")
        return SimpleNamespace(status="PASS", secondary_external_state="RESULTS_VALIDATED")
    monkeypatch.setattr(integration, "validate_run_authority", mutate)
    with pytest.raises(pytest.fail.Exception, match="changed during validation"):
        reference.require_selected_run(tmp_path, "chosen")


def test_removed_empty_required_member_invalidates_cached_validation(tmp_path, monkeypatch):
    _family(tmp_path)
    calls = _validator(monkeypatch)
    reference.require_selected_run(tmp_path, "chosen")
    (tmp_path / "out/runs/chosen_close").rmdir()
    with pytest.raises(pytest.fail.Exception, match="incomplete"):
        reference.require_selected_run(tmp_path, "chosen")
    assert len(calls) == 1


@pytest.mark.parametrize("problem", ["changed code", "source hash mismatch", "configuration mismatch", "missing raw results", "pending marker conflict"])
def test_recorded_pass_never_bypasses_production_validation(tmp_path, monkeypatch, problem):
    _family(tmp_path)
    (tmp_path / "out/runs/chosen_close/PASS.json").write_text('{"status":"PASS"}')
    def reject(**kwargs):
        raise ValueError(problem)
    monkeypatch.setattr(integration, "validate_run_authority", reject)
    with pytest.raises(pytest.fail.Exception, match="failed current-source validation"):
        reference.require_selected_run(tmp_path, "chosen")


def test_nonpassing_validation_is_rejected(tmp_path, monkeypatch):
    _family(tmp_path)
    _validator(monkeypatch, status="FAIL")
    with pytest.raises(pytest.fail.Exception, match="did not PASS"):
        reference.require_selected_run(tmp_path, "chosen")


def test_pending_external_results_are_only_usable_for_non_rq4_references(tmp_path, monkeypatch):
    _family(tmp_path)
    _validator(monkeypatch, external="EXTERNAL_RESULTS_REQUIRED")
    reference.require_selected_run(tmp_path, "chosen")
    with pytest.raises(pytest.fail.Exception, match="requires RESULTS_VALIDATED"):
        reference.require_selected_run(tmp_path, "chosen", external=True)


def _synthetic_sources(tmp_path, monkeypatch):
    """Use the actual manifest/hash/schema reader with synthetic input identity.

    Scientific run validation is tested by delegation above and by the explicit
    real-run qualification campaign, not inferred from this tiny fixture.
    """
    _family(tmp_path)
    monkeypatch.setenv("RP1_ANALYSIS_TEST_RUN", "chosen")
    _validator(monkeypatch)
    minimal_bundle = SimpleNamespace(
        configuration_sha256="configuration",
        output=SimpleNamespace(tables=()),
        figure=SimpleNamespace(figures=(
            SimpleNamespace(source_attribute="annual_trend_source", data_builder_options={}),
        )),
    )
    monkeypatch.setattr(sources, "load_configuration_bundle", lambda _: minimal_bundle)
    identity = {"files": {}, "code": {}, "inventory_sha256": "fixture"}
    monkeypatch.setattr(sources, "_source_input_identity", lambda *a, **kw: identity)
    directory = tmp_path / "out/publication_sources/chosen_pub"
    directory.mkdir(parents=True)
    path = directory / "annual_trend_source.csv"
    path.write_text("year,value\n2001,4.25\n", encoding="utf-8")
    entry = {"path": path.relative_to(tmp_path).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows": 1, "columns": ["year", "value"]}
    manifest = {"schema": "rp1-publication-sources-run-v2", "run_id": "chosen_pub", "configuration_sha256": "configuration", "input_identity": identity, "sources": {"annual_trend_source": entry}}
    (directory / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    return directory, path, manifest


def test_run_local_sources_load_without_any_global_manifest(tmp_path, monkeypatch):
    directory, path, manifest = _synthetic_sources(tmp_path, monkeypatch)
    assert not (tmp_path / "data/authorities").exists()
    assert reference.publication_source_root(tmp_path) == directory
    actual = reference.publication_sources(tmp_path)["annual_trend_source"]
    pd.testing.assert_frame_equal(actual, pd.DataFrame({"year": [2001], "value": [4.25]}))


@pytest.mark.parametrize("corruption", ["hash", "run", "config", "escape", "columns"])
def test_run_local_loader_rejects_corrupt_selected_sources(tmp_path, monkeypatch, corruption):
    directory, path, manifest = _synthetic_sources(tmp_path, monkeypatch)
    entry = manifest["sources"]["annual_trend_source"]
    if corruption == "hash":
        path.write_text("year,value\n2001,8\n")
    elif corruption == "run":
        manifest["run_id"] = "foreign_pub"
    elif corruption == "config":
        manifest["configuration_sha256"] = "foreign"
    elif corruption == "escape":
        entry["path"] = "../foreign.csv"
    else:
        entry["columns"] = ["wrong"]
    (directory / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    with pytest.raises((sources.PublicationSourceError, ValueError)):
        reference.publication_sources(tmp_path)


def test_clean_source_gates_leave_independent_publication_checks_runnable(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    original = Path(__file__).parent
    for name in ("conftest.py", "generated_run_reference.py"):
        shutil.copy2(original / name, tests / name)
    (tests / "test_presentation_export_core.py").write_text(
        "from pathlib import Path\nfrom generated_run_reference import selected_run_base, require_selected_run\n"
        "def test_config_only():\n    assert True\n"
        "def test_generated_data():\n    root=Path(__file__).parents[1]\n    require_selected_run(root, selected_run_base(root))\n"
    )
    report = tmp_path / "result.xml"
    env = os.environ.copy()
    for name in ("RP1_ANALYSIS_TEST_RUN", "PYTEST_ADDOPTS", "PYTEST_DEBUG_TEMPROOT"):
        env.pop(name, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml", str(report), str(tests)], env=env, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    suite = next(ET.parse(report).getroot().iter("testsuite"))
    assert (suite.get("tests"), suite.get("skipped"), suite.get("failures"), suite.get("errors")) == ("2", "1", "0", "0")


@pytest.mark.parametrize(("module_name", "function_name", "export_id"), [
    ("test_presentation_rq2_renderers", "test_end_to_end_single_export_is_read_only_and_manifest_bound", "rq2_coastal_trend"),
    ("test_presentation_rq2_renderers", "test_end_to_end_five_acz_comparison_is_read_only", None),
    ("test_presentation_rq2_renderers", "test_deterministic_repeat_rendering_for_all_six_exports", None),
    ("test_presentation_rq3_renderers", "test_end_to_end_rq3_export_is_read_only_and_manifest_bound", "rq3_focal_effects"),
    ("test_presentation_rq3_renderers", "test_deterministic_repeat_rendering_for_all_four_rq3_exports", None),
])
@pytest.mark.parametrize("selected", [False, True])
def test_real_renderer_entrypoints_check_prerequisites_before_resolving_runs(
    tmp_path, monkeypatch, module_name, function_name, export_id, selected,
):
    import importlib
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    run_base = "chosen" if selected else reference.SELECTION_REQUIRED
    monkeypatch.setattr(module, "RUN_BASE", run_base)
    monkeypatch.setattr(module, "RUN_CLOSE", tmp_path / "out/runs" / (run_base + "_close"))
    calls = _validator(monkeypatch)
    if selected:
        monkeypatch.setenv("RP1_ANALYSIS_TEST_RUN", "chosen")
        _family(tmp_path)
    class ResolutionReached(Exception):
        pass
    def resolve(*args, **kwargs):
        assert selected, "unselected generated test reached run resolution before its prerequisite"
        assert len(calls) == 1, "selected generated test bypassed production run validation"
        raise ResolutionReached()
    monkeypatch.setattr(module.pe, "resolve_run_family", resolve)
    kwargs = {"tmp_path": tmp_path, "monkeypatch": monkeypatch}
    if export_id is not None:
        kwargs["export_id"] = export_id
    expected = ResolutionReached if selected else pytest.skip.Exception
    with pytest.raises(expected):
        getattr(module, function_name)(**kwargs)
    assert len(calls) == int(selected)
