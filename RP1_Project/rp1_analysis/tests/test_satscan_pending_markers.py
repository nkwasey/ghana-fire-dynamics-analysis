"""Pending-result marker lifecycle, independent of generated Ghana panels.

The small files below are integration-control fixtures, not engine output or
scientific validation. Parser and scientific projection are replaced so this
contract also runs in a clean source release with no prepared data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from rp1_analysis_v1 import satscan_integration as integration
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.satscan_io import ExternalResultValidationError
from rp1_analysis_v1.secondary_clusters import (
    EXTERNAL_RESULTS_REQUIRED,
    RESULTS_VALIDATED,
    SECONDARY_SECTION,
)


MODEL_IDS = ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY")
MARKER_NAME = "EXTERNAL_RESULTS_REQUIRED.txt"


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*") if p.is_file()
    }


@pytest.fixture
def marker_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Use actual registry paths, hashes and state files with two model roots."""
    project = tmp_path / "project"
    run_id = "marker_contract"
    run = project / "out" / "runs" / run_id
    section = run / SECONDARY_SECTION
    tables = section / "tables"
    tables.mkdir(parents=True)
    rows = []
    markers = []
    result_files = []
    for model_id in MODEL_IDS:
        model = "discrete_poisson" if model_id.startswith("MCD") else "space_time_permutation"
        model_root = section / "satscan" / model_id
        result_root = model_root / "results"
        result_root.mkdir(parents=True)
        prefix = (result_root / model_id).relative_to(run).as_posix()
        row = {"model_id": model_id, "scenario_id": model_id, "model": model,
               "results_prefix": prefix, "required_report_path": prefix,
               "required_cluster_path": prefix + ".col.txt",
               "required_membership_path": prefix + ".gis.txt",
               "population_path": "", "population_sha256": "",
               "execution_state": EXTERNAL_RESULTS_REQUIRED,
               "parameter_linkage_validated": False, "live_execution_deferred": True}
        for role, suffix in (("case", ".cas"), ("coordinate", ".geo")):
            p = model_root / (model_id + suffix)
            p.write_text("fixture interface\n", encoding="utf-8")
            row[role + "_path"] = p.relative_to(run).as_posix()
            row[role + "_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        if model == "discrete_poisson":
            population = model_root / (model_id + ".pop")
            population.write_text("fixture exposure\n", encoding="utf-8")
            row["population_path"] = population.relative_to(run).as_posix()
            row["population_sha256"] = hashlib.sha256(population.read_bytes()).hexdigest()
        prm = model_root / (model_id + ".prm")
        prm.write_text(
            f"ResultsFile={prefix}\nPopulationFile={row['population_path']}\n",
            encoding="utf-8",
        )
        row["prm_path"] = prm.relative_to(run).as_posix()
        row["prm_sha256"] = hashlib.sha256(prm.read_bytes()).hexdigest()
        marker = result_root / MARKER_NAME
        marker.write_text(EXTERNAL_RESULTS_REQUIRED + "\nPending fixture results\n", encoding="utf-8")
        markers.append(marker)
        result_files.append(tuple(run / row[k] for k in (
            "required_report_path", "required_cluster_path", "required_membership_path")))
        rows.append(row)
    pd.DataFrame(rows).to_csv(tables / "secondary_run_registry.csv", index=False)
    location = pd.DataFrame({"unit_id": ["fixture_district"], "x": [1], "y": [2]})
    location.to_csv(tables / "secondary_location_authority.csv", index=False)
    config_digest = "a" * 64
    snapshot = run / "00_scaffold/realised_configuration.json"
    snapshot.parent.mkdir()
    snapshot.write_text(json.dumps({"configuration_sha256": config_digest}), encoding="utf-8")
    (section / "secondary_external_execution_status.json").write_text(
        json.dumps({
            "external_execution_state": EXTERNAL_RESULTS_REQUIRED,
            "configuration_sha256": config_digest,
        }),
        encoding="utf-8",
    )
    sources = {
        "table3_satscan_clusters": pd.DataFrame({"product": ["mcd64a1", "viirs"], "cluster_rank": [1, 1]}),
        "cluster_membership_source": pd.DataFrame({"product": ["mcd64a1", "viirs"], "unit_id": ["A", "A"]}),
        "cluster_recurrence_source": pd.DataFrame({"product": ["mcd64a1", "viirs"], "count": [1, 1]}),
        "supplement_s6_satscan": pd.DataFrame({"record_type": ["fixture"]}),
    }
    bundle = SimpleNamespace(
        analysis=object(), data_schema=object(),
        execution=SimpleNamespace(allowed_secondary_completion_states=(EXTERNAL_RESULTS_REQUIRED, RESULTS_VALIDATED)),
        output=SimpleNamespace(secondary_outputs=[SimpleNamespace(
            output_id="T3", source_attribute="table3_satscan_clusters",
            output_type="table", requires_results_validated=True)]),
    )
    monkeypatch.setattr(integration, "load_configuration_bundle", lambda _: bundle)
    monkeypatch.setattr(integration, "validate_secondary_configuration", lambda *_: {
        "decision": "EXACT",
        "prepared_configuration_sha256": config_digest,
        "current_configuration_sha256": config_digest,
        "changed_contract_files": [],
    })
    monkeypatch.setattr(integration, "load_scan_scenarios", lambda _: [SimpleNamespace(scenario_id=x) for x in MODEL_IDS])
    monkeypatch.setattr(integration, "satscan_parameters", lambda _: SimpleNamespace(
        alpha=.05, coordinate_crs="EPSG:32630", coordinate_anchor_method="fixture", engine_version_authority="10.3.3"))
    monkeypatch.setattr(integration, "validate_external_results", lambda row, **_: SimpleNamespace(
        provenance={"scenario_id": row["model_id"], "executable_version": "fixture", "native_reconciliation": {}}))
    monkeypatch.setattr(integration, "load_data_authorities", lambda *_: SimpleNamespace(district_geometry=object()))
    monkeypatch.setattr(integration, "validate_data_authorities", lambda *_: object())
    monkeypatch.setattr(integration, "build_location_authority", lambda *_, **__: location.copy())
    monkeypatch.setattr(integration, "build_satscan_publication_sources", lambda **_: {k: v.copy() for k, v in sources.items()})
    unrelated = section / "satscan" / "UNCONFIGURED_MODEL" / "results" / MARKER_NAME
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("Unrelated pending model\n", encoding="utf-8")
    outside = project / "out" / "runs" / "another_pending_run" / MARKER_NAME
    outside.parent.mkdir(parents=True)
    outside.write_text("Another pending run\n", encoding="utf-8")
    return SimpleNamespace(paths=ProjectPaths(project), run_id=run_id, run=run,
                           markers=tuple(markers), result_files=tuple(result_files),
                           unrelated=unrelated, outside=outside)


def _stage_results(case, models=MODEL_IDS):
    for model_id, family in zip(MODEL_IDS, case.result_files):
        if model_id in models:
            for p in family:
                p.write_text("fixture result\n", encoding="utf-8")


def _integrate(case):
    return integration.validate_and_integrate_satscan_results_if_available(
        paths=case.paths, secondary_run_id=case.run_id)


def test_success_removes_only_configured_pending_markers_after_validation(marker_run):
    case = marker_run
    _stage_results(case)
    raw_before = {p: p.read_bytes() for family in case.result_files for p in family}
    unrelated_before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (case.unrelated, case.outside)}
    result = _integrate(case)
    assert result.external_execution_state == RESULTS_VALIDATED
    assert result.validated_model_count == len(MODEL_IDS)
    assert all(not p.exists() for p in case.markers)
    assert all(p.read_bytes() == content for p, content in raw_before.items())
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == info for p, info in unrelated_before.items())


@pytest.mark.parametrize("missing", [0, 1, 2])
def test_success_tolerates_already_absent_pending_markers(marker_run, missing):
    _stage_results(marker_run)
    for marker in marker_run.markers[:missing]:
        marker.unlink()
    result = _integrate(marker_run)
    assert result.external_execution_state == RESULTS_VALIDATED
    assert all(not p.exists() for p in marker_run.markers)


def test_marker_only_pending_run_remains_unchanged(marker_run):
    before = _snapshot(marker_run.run)
    result = _integrate(marker_run)
    inspection = integration.inspect_satscan_results(paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert result.external_execution_state == EXTERNAL_RESULTS_REQUIRED
    assert inspection.external_execution_state == EXTERNAL_RESULTS_REQUIRED
    assert _snapshot(marker_run.run) == before


def test_ready_result_inspection_preserves_markers_until_integration(marker_run):
    _stage_results(marker_run)
    before = _snapshot(marker_run.run)
    inspection = integration.inspect_satscan_results(
        paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert inspection.external_execution_state == RESULTS_VALIDATED
    assert inspection.integration_state == "VALIDATED_READY_FOR_INTEGRATION"
    assert _snapshot(marker_run.run) == before


@pytest.mark.parametrize("mode", ["only_first_family", "missing_companion"])
def test_partial_results_preserve_both_pending_markers(marker_run, mode):
    _stage_results(marker_run, MODEL_IDS[:1] if mode == "only_first_family" else MODEL_IDS)
    if mode == "missing_companion":
        marker_run.result_files[1][-1].unlink()
    before = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="Partial SaTScan"):
        _integrate(marker_run)
    assert _snapshot(marker_run.run) == before


def test_invalid_second_model_does_not_resolve_first_model_marker(marker_run, monkeypatch):
    _stage_results(marker_run)
    validated = []
    def reject_second(row, **_):
        validated.append(row["model_id"])
        if row["model_id"] == MODEL_IDS[1]:
            raise ExternalResultValidationError("invalid second fixture model")
        return SimpleNamespace(provenance={})
    monkeypatch.setattr(integration, "validate_external_results", reject_second)
    before = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="invalid second"):
        _integrate(marker_run)
    assert validated == list(MODEL_IDS)
    assert _snapshot(marker_run.run) == before


def test_publication_projection_failure_keeps_pending_markers(marker_run, monkeypatch):
    _stage_results(marker_run)
    def fail_projection(**_):
        raise ValueError("fixture projection failure")
    monkeypatch.setattr(integration, "build_satscan_publication_sources", fail_projection)
    before = _snapshot(marker_run.run)
    with pytest.raises(ValueError, match="fixture projection failure"):
        _integrate(marker_run)
    assert _snapshot(marker_run.run) == before


@pytest.mark.parametrize("failed_name", [
    "cluster_membership_source.csv", "secondary_run_registry.csv", "secondary_output_registry.csv",
    "secondary_external_execution_status.json", integration.RUN_LOCAL_SOURCE_MANIFEST,
])
def test_any_integration_write_failure_keeps_all_pending_markers(marker_run, monkeypatch, failed_name):
    _stage_results(marker_run)
    marker_before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in marker_run.markers}
    original = integration._atomic_text
    def fail_write(path, text):
        if path.name == failed_name:
            raise OSError("fixture write failure")
        original(path, text)
    monkeypatch.setattr(integration, "_atomic_text", fail_write)
    with pytest.raises(OSError, match="fixture write failure"):
        _integrate(marker_run)
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == content for p, content in marker_before.items())


def test_validated_reuse_and_inspection_reject_historical_markers_without_repair(marker_run):
    """Preserving sealed history does not permit accepting its state conflict."""
    _stage_results(marker_run)
    _integrate(marker_run)
    for marker in marker_run.markers:
        marker.write_text("Historical stale pending marker\n", encoding="utf-8")
    before = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="conflicts with pending"):
        _integrate(marker_run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="conflicts with pending"):
        integration.inspect_satscan_results(paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert _snapshot(marker_run.run) == before


@pytest.mark.parametrize("fail_index", [0, 1])
def test_marker_unlink_failure_restores_complete_state_and_retry(marker_run, monkeypatch, fail_index):
    _stage_results(marker_run)
    before = _snapshot(marker_run.run)
    marker_before = {p: p.read_bytes() for p in marker_run.markers}
    original = Path.unlink
    removed = []
    def fail_second_marker(path, *args, **kwargs):
        if path in marker_before:
            if len(removed) == fail_index:
                raise OSError("fixture second-marker unlink failure")
            removed.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_second_marker)
    with pytest.raises((OSError, integration.OptionalSaTScanIntegrationError), match="marker|unlink"):
        _integrate(marker_run)
    assert len(removed) == fail_index
    assert _snapshot(marker_run.run) == before
    monkeypatch.setattr(Path, "unlink", original)
    result = _integrate(marker_run)
    assert result.external_execution_state == RESULTS_VALIDATED
    assert all(not p.exists() for p in marker_run.markers)
    inspected = integration.inspect_satscan_results(paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert inspected.integration_state == "INTEGRATED"


def test_nonfile_second_marker_preflight_does_not_remove_first_marker(marker_run):
    _stage_results(marker_run)
    first, second = marker_run.markers
    before = (first.read_bytes(), first.stat().st_mtime_ns)
    second.unlink()
    second.mkdir()
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="regular file"):
        _integrate(marker_run)
    assert (first.read_bytes(), first.stat().st_mtime_ns) == before
    assert second.is_dir()


@pytest.mark.parametrize("failed_name", [
    "table3_satscan_clusters.csv", "cluster_membership_source.csv",
    "secondary_run_registry.csv", "secondary_output_registry.csv",
    "secondary_external_execution_status.json", integration.RUN_LOCAL_SOURCE_MANIFEST,
])
def test_published_write_failure_rolls_back_all_authorities_and_allows_retry(marker_run, monkeypatch, failed_name):
    _stage_results(marker_run)
    before = _snapshot(marker_run.run)
    original = integration._atomic_text
    def fail_publication(path, text):
        if path.name == failed_name and integration._TRANSITION_DIRECTORY not in path.parts:
            raise OSError("published authority write failure")
        original(path, text)
    monkeypatch.setattr(integration, "_atomic_text", fail_publication)
    with pytest.raises(OSError, match="published authority"):
        _integrate(marker_run)
    assert _snapshot(marker_run.run) == before
    monkeypatch.setattr(integration, "_atomic_text", original)
    assert _integrate(marker_run).external_execution_state == RESULTS_VALIDATED
    assert all(not p.exists() for p in marker_run.markers)


def test_clean_validated_reuse_is_read_only_and_idempotent(marker_run):
    _stage_results(marker_run)
    _integrate(marker_run)
    before = _snapshot(marker_run.run)
    for _ in range(2):
        assert _integrate(marker_run).external_execution_state == RESULTS_VALIDATED
        assert integration.inspect_satscan_results(
            paths=marker_run.paths, secondary_run_id=marker_run.run_id).integration_state == "INTEGRATED"
    assert _snapshot(marker_run.run) == before


@pytest.mark.parametrize("interrupted_authority", ["secondary_run_registry.csv", "secondary_external_execution_status.json"])
def test_interrupted_publication_is_rejected_until_explicit_rollback(marker_run, monkeypatch, interrupted_authority):
    _stage_results(marker_run)
    before = _snapshot(marker_run.run)
    original = integration._atomic_text
    def interrupt_after_registry(path, text):
        original(path, text)
        if path.name == interrupted_authority and integration._TRANSITION_DIRECTORY not in path.parts:
            raise KeyboardInterrupt("simulated process interruption")
    monkeypatch.setattr(integration, "_atomic_text", interrupt_after_registry)
    with pytest.raises(KeyboardInterrupt):
        _integrate(marker_run)
    monkeypatch.setattr(integration, "_atomic_text", original)
    interrupted = _snapshot(marker_run.run)
    for action in (_integrate, lambda case: integration.inspect_satscan_results(
        paths=case.paths, secondary_run_id=case.run_id)):
        with pytest.raises(integration.OptionalSaTScanIntegrationError, match="recovery required"):
            action(marker_run)
    assert _snapshot(marker_run.run) == interrupted
    outcome = integration.recover_satscan_integration_transition(
        paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert outcome["status"] == "ROLLED_BACK"
    assert _snapshot(marker_run.run) == before
    assert _integrate(marker_run).external_execution_state == RESULTS_VALIDATED


def test_incomplete_rollback_remains_blocked_and_recoverable(marker_run, monkeypatch):
    _stage_results(marker_run)
    before = _snapshot(marker_run.run)
    write = integration._atomic_text
    rollback = integration._rollback_transition
    def fail_status(path, text):
        if path.name == "secondary_external_execution_status.json" and integration._TRANSITION_DIRECTORY not in path.parts:
            raise OSError("status publication failure")
        write(path, text)
    def fail_rollback(*args, **kwargs):
        raise OSError("rollback storage unavailable")
    monkeypatch.setattr(integration, "_atomic_text", fail_status)
    monkeypatch.setattr(integration, "_rollback_transition", fail_rollback)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="rollback was incomplete"):
        _integrate(marker_run)
    monkeypatch.setattr(integration, "_atomic_text", write)
    monkeypatch.setattr(integration, "_rollback_transition", rollback)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="recovery required"):
        _integrate(marker_run)
    integration.recover_satscan_integration_transition(paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert _snapshot(marker_run.run) == before


def test_recovery_refuses_changed_authorities_and_preserves_evidence(marker_run, monkeypatch):
    _stage_results(marker_run)
    original = integration._atomic_text
    def interrupt(path, text):
        original(path, text)
        if path.name == "secondary_run_registry.csv" and integration._TRANSITION_DIRECTORY not in path.parts:
            raise KeyboardInterrupt()
    monkeypatch.setattr(integration, "_atomic_text", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _integrate(marker_run)
    monkeypatch.setattr(integration, "_atomic_text", original)
    authority = marker_run.run / SECONDARY_SECTION / "tables/secondary_run_registry.csv"
    authority.write_text("operator changed this authority", encoding="utf-8")
    before = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="changed outside"):
        integration.recover_satscan_integration_transition(paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert _snapshot(marker_run.run) == before


def test_terminal_seal_failure_restores_complete_pending_state(marker_run, monkeypatch):
    _stage_results(marker_run)
    before = _snapshot(marker_run.run)
    original = integration.os.rename
    def fail_seal(source, target):
        raise OSError("terminal directory seal failure")
    monkeypatch.setattr(integration.os, "rename", fail_seal)
    with pytest.raises(OSError, match="terminal directory seal"):
        _integrate(marker_run)
    assert _snapshot(marker_run.run) == before
    monkeypatch.setattr(integration.os, "rename", original)
    assert _integrate(marker_run).external_execution_state == RESULTS_VALIDATED


@pytest.mark.parametrize("receipt_count,expected", [(0, "RESULT_FILES_ONLY"), (1, "PARTIAL_RECORDED_EXECUTION"), (2, "RECORDED_EXECUTION")])
def test_execution_receipts_are_preserved_without_inventing_historical_attestation(marker_run, monkeypatch, receipt_count, expected):
    _stage_results(marker_run)
    def parsed(row, **_):
        provenance = {"scenario_id": row["model_id"], "native_reconciliation": {}}
        if row["model_id"] in MODEL_IDS[:receipt_count]:
            provenance.update(execution_receipt_path=f"receipt_{row['model_id']}.json",
                execution_receipt_sha256="a" * 64, executable_path="recorded-engine",
                executable_version="10.3.3", executable_sha256="b" * 64)
        return SimpleNamespace(provenance=provenance)
    monkeypatch.setattr(integration, "validate_external_results", parsed)
    _integrate(marker_run)
    section = marker_run.run / SECONDARY_SECTION
    status = json.loads((section / "secondary_external_execution_status.json").read_text())
    manifest = json.loads((section / "publication_sources" / integration.RUN_LOCAL_SOURCE_MANIFEST).read_text())
    assert status["external_execution_evidence"] == expected
    assert status["satscan_executable_detected"] is (receipt_count == 2)
    assert len(status["satscan_execution_receipts"]) == receipt_count
    assert manifest["execution_receipts"] == status["satscan_execution_receipts"]
    assert manifest["satscan_execution_performed_by_notebook"] is False
    assert _integrate(marker_run).external_execution_state == RESULTS_VALIDATED


def test_validated_reuse_rejects_changed_observed_execution_receipt(marker_run, monkeypatch):
    _stage_results(marker_run)
    digest = ["a" * 64]
    def parsed(row, **_):
        return SimpleNamespace(provenance={"scenario_id": row["model_id"], "native_reconciliation": {},
            "execution_receipt_path": f"receipt_{row['model_id']}.json",
            "execution_receipt_sha256": digest[0], "executable_path": "engine",
            "executable_version": "10.3.3", "executable_sha256": "b" * 64})
    monkeypatch.setattr(integration, "validate_external_results", parsed)
    _integrate(marker_run)
    digest[0] = "c" * 64
    before = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="execution-receipt identity"):
        _integrate(marker_run)
    assert _snapshot(marker_run.run) == before


@pytest.mark.parametrize("corruption", ["registry_executable", "status_detection"])
def test_validated_reuse_rejects_false_executable_attestation(marker_run, monkeypatch, corruption):
    _stage_results(marker_run)
    monkeypatch.setattr(integration, "validate_external_results", lambda row, **_: SimpleNamespace(provenance={
        "scenario_id": row["model_id"], "native_reconciliation": {},
        "execution_receipt_path": f"receipt_{row['model_id']}.json",
        "execution_receipt_sha256": "a" * 64, "executable_path": "engine",
        "executable_version": "10.3.3", "executable_sha256": "b" * 64}))
    _integrate(marker_run)
    section = marker_run.run / SECONDARY_SECTION
    if corruption == "registry_executable":
        target = section / "tables/secondary_run_registry.csv"
        registry = pd.read_csv(target, keep_default_na=False)
        registry.loc[0, "satscan_executable_sha256"] = "c" * 64
        registry.to_csv(target, index=False)
    else:
        target = section / "secondary_external_execution_status.json"
        status = json.loads(target.read_text())
        status["satscan_executable_detected"] = False
        target.write_text(json.dumps(status))
    before = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="executable attestation"):
        _integrate(marker_run)
    assert _snapshot(marker_run.run) == before


def _interrupt_transition(case, monkeypatch, authority="secondary_run_registry.csv"):
    _stage_results(case)
    before = _snapshot(case.run)
    original = integration._atomic_text
    def interrupt(path, text):
        original(path, text)
        if path.name == authority and integration._TRANSITION_DIRECTORY not in path.parts:
            raise KeyboardInterrupt("stopped integration writer")
    monkeypatch.setattr(integration, "_atomic_text", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _integrate(case)
    monkeypatch.setattr(integration, "_atomic_text", original)
    directory = integration._transition_path(case.run)
    journal_path = directory / integration._TRANSITION_JOURNAL
    return before, directory, journal_path, json.loads(journal_path.read_text())


@pytest.mark.parametrize("corruption", [
    "empty_entries", "dropped_entry", "duplicate_entry", "non_mapping_entry",
    "missing_existed", "non_boolean_existed", "wrong_before_hash", "wrong_after_hash",
    "missing_metadata", "invalid_mode", "invalid_timestamp", "invalid_backup_path",
    "false_mandatory_registry", "unrelated_created_directory", "duplicate_created_directory",
    "unknown_entry_field", "unknown_header_field", "unknown_phase", "non_string_phase", "non_mapping_journal",
])
def test_corrupt_recovery_journal_is_rejected_before_any_authority_write(marker_run, monkeypatch, corruption):
    """REC-1: malformed recovery metadata cannot erase a file or its safety gate."""
    _, directory, journal_path, journal = _interrupt_transition(marker_run, monkeypatch)
    relative = f"{SECONDARY_SECTION}/tables/secondary_run_registry.csv"
    entry = next(item for item in journal["entries"] if item["path"] == relative)
    if corruption == "empty_entries":
        journal["entries"] = []
    elif corruption == "dropped_entry":
        journal["entries"].pop()
    elif corruption == "duplicate_entry":
        journal["entries"].append(dict(journal["entries"][0]))
    elif corruption == "non_mapping_entry":
        journal["entries"][0] = None
    elif corruption == "missing_existed":
        entry.pop("existed")
    elif corruption == "non_boolean_existed":
        entry["existed"] = 1
    elif corruption == "wrong_before_hash":
        entry["before_sha256"] = "not-a-sha256"
    elif corruption == "wrong_after_hash":
        entry["after_sha256"] = None
    elif corruption == "missing_metadata":
        entry.pop("mtime_ns")
    elif corruption == "invalid_mode":
        entry["mode"] = -1
    elif corruption == "invalid_timestamp":
        entry["mtime_ns"] = "123"
    elif corruption == "invalid_backup_path":
        entry["backup"] = "../outside.bin"
    elif corruption == "false_mandatory_registry":
        entry["existed"] = False
        entry["before_sha256"] = None
        for key in ("backup", "atime_ns", "mtime_ns", "mode"):
            entry.pop(key)
    elif corruption == "unrelated_created_directory":
        unrelated = marker_run.run / "unrelated_empty_directory"
        unrelated.mkdir()
        journal["created_directories"].append("unrelated_empty_directory")
    elif corruption == "duplicate_created_directory":
        journal["created_directories"] *= 2
    elif corruption == "unknown_entry_field":
        entry["unrecognised"] = True
    elif corruption == "unknown_header_field":
        journal["unrecognised"] = True
    elif corruption == "unknown_phase":
        journal["phase"] = "RECOVERED"
    elif corruption == "non_string_phase":
        journal["phase"] = []
    else:
        journal = []
    journal_path.write_text(json.dumps(journal))
    before_recovery = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="recovery|journal"):
        integration.recover_satscan_integration_transition(
            paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert _snapshot(marker_run.run) == before_recovery
    assert directory.is_dir()
    assert (marker_run.run / relative).is_file()


@pytest.mark.parametrize("material", ["missing_backup", "corrupt_backup", "missing_staged", "corrupt_staged", "unrecognised_file", "unrecognised_directory"])
def test_missing_or_corrupt_transition_material_preserves_all_recovery_evidence(marker_run, monkeypatch, material):
    _, directory, _, journal = _interrupt_transition(marker_run, monkeypatch)
    if material == "unrecognised_file":
        (directory / "operator_note.txt").write_text("preserve me")
    elif material == "unrecognised_directory":
        (directory / "operator_directory").mkdir()
    else:
        index, entry = next((i, item) for i, item in enumerate(journal["entries"]) if item["existed"] and item["after_sha256"])
        path = directory / (entry["backup"] if material.endswith("backup") else f"staged/{index:03d}.txt")
        if material.startswith("missing"):
            path.unlink()
        else:
            path.write_bytes(b"corrupt transition material")
    before_recovery = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="recovery"):
        integration.recover_satscan_integration_transition(
            paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert _snapshot(marker_run.run) == before_recovery
    assert directory.is_dir()


@pytest.mark.parametrize("stop_point", ["initial_journal", "first_staged_authority"])
def test_initial_and_partial_preparing_crashes_can_be_cleared_without_authority_changes(marker_run, monkeypatch, stop_point):
    _stage_results(marker_run)
    before = _snapshot(marker_run.run)
    original = integration._atomic_bytes
    text_write = integration._atomic_text
    def interrupt_staging(path, data):
        original(path, data)
        if path.parent.name == "staged":
            raise KeyboardInterrupt("stopped before authoritative publication")
    monkeypatch.setattr(integration, "_atomic_bytes", interrupt_staging)
    if stop_point == "initial_journal":
        def interrupt_initial_journal(path, text):
            text_write(path, text)
            if path.name == integration._TRANSITION_JOURNAL:
                raise KeyboardInterrupt("stopped after initial journal publication")
        monkeypatch.setattr(integration, "_atomic_text", interrupt_initial_journal)
    with pytest.raises(KeyboardInterrupt):
        _integrate(marker_run)
    monkeypatch.setattr(integration, "_atomic_bytes", original)
    monkeypatch.setattr(integration, "_atomic_text", text_write)
    outcome = integration.recover_satscan_integration_transition(
        paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert outcome["previous_phase"] == "PREPARING"
    assert outcome["status"] == "ROLLED_BACK"
    assert _snapshot(marker_run.run) == before
    assert _integrate(marker_run).external_execution_state == RESULTS_VALIDATED


def test_non_directory_recovery_parent_is_rejected_before_restoration(marker_run, monkeypatch):
    _, directory, _, _ = _interrupt_transition(marker_run, monkeypatch)
    source = marker_run.run / integration.RUN_LOCAL_SOURCE_DIR
    for path in source.iterdir():
        path.unlink()
    source.rmdir()
    source.write_text("operator-owned file occupying the parent path")
    before_recovery = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="parent is not a directory"):
        integration.recover_satscan_integration_transition(
            paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert _snapshot(marker_run.run) == before_recovery
    assert directory.is_dir()


@pytest.mark.parametrize("location", ["journal", "extra"])
def test_nonregular_transition_evidence_is_rejected_without_reading_or_cleanup(marker_run, monkeypatch, location):
    if not hasattr(integration.os, "mkfifo"):
        pytest.skip("POSIX FIFO regression")
    _, directory, journal_path, _ = _interrupt_transition(marker_run, monkeypatch)
    path = journal_path if location == "journal" else directory / "operator_fifo"
    if path.exists():
        path.unlink()
    integration.os.mkfifo(path)
    # Do not read the FIFO in the test's file snapshot either.
    ordinary = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in marker_run.run.rglob("*") if p.is_file()}
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="regular|nonregular"):
        integration.recover_satscan_integration_transition(
            paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in ordinary.items())
    assert path.exists() and directory.is_dir()


@pytest.mark.parametrize("authority", ["table3_satscan_clusters.csv", "secondary_run_registry.csv", "secondary_external_execution_status.json"])
def test_changed_authorities_cannot_be_hidden_by_relabelling_journal_preparing(marker_run, monkeypatch, authority):
    _, directory, journal_path, journal = _interrupt_transition(marker_run, monkeypatch, authority)
    journal.update(phase="PREPARING", entries=[], created_directories=[])
    journal_path.write_text(json.dumps(journal))
    before_recovery = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError):
        integration.recover_satscan_integration_transition(
            paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert _snapshot(marker_run.run) == before_recovery
    assert directory.is_dir()


def test_recovery_verifies_restored_pre_state_before_clearing_transition(marker_run, monkeypatch):
    before, directory, _, _ = _interrupt_transition(marker_run, monkeypatch)
    registry = marker_run.run / SECONDARY_SECTION / "tables/secondary_run_registry.csv"
    original = integration._atomic_bytes
    def lose_one_restoration(path, data):
        if path != registry:
            original(path, data)
    monkeypatch.setattr(integration, "_atomic_bytes", lose_one_restoration)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="complete pre-state"):
        integration.recover_satscan_integration_transition(
            paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert directory.is_dir()
    monkeypatch.setattr(integration, "_atomic_bytes", original)
    assert integration.recover_satscan_integration_transition(
        paths=marker_run.paths, secondary_run_id=marker_run.run_id)["status"] == "ROLLED_BACK"
    assert _snapshot(marker_run.run) == before


@pytest.mark.parametrize("historical_marker", [False, True])
def test_validated_run_with_absent_raw_families_is_a_read_only_conflict(marker_run, historical_marker):
    """REC-2: absence cannot silently downgrade recorded validated history."""
    _stage_results(marker_run)
    _integrate(marker_run)
    for family in marker_run.result_files:
        for path in family:
            path.unlink()
    if historical_marker:
        marker_run.markers[0].write_text("Historical contradictory pending marker\n")
    before = _snapshot(marker_run.run)
    for action in (_integrate, lambda case: integration.inspect_satscan_results(
            paths=case.paths, secondary_run_id=case.run_id)):
        with pytest.raises(integration.OptionalSaTScanIntegrationError, match="missing its governed"):
            action(marker_run)
    assert _snapshot(marker_run.run) == before


@pytest.mark.parametrize("result_material", ["absent", "complete"])
@pytest.mark.parametrize("status", [None, "invalid-json", [], {}, {"external_execution_state": "UNKNOWN"}])
def test_inspection_rejects_missing_or_malformed_recorded_state_read_only(marker_run, result_material, status):
    if result_material == "complete":
        _stage_results(marker_run)
    path = marker_run.run / SECONDARY_SECTION / "secondary_external_execution_status.json"
    if status is None:
        path.unlink()
    elif status == "invalid-json":
        path.write_text("{ invalid json")
    else:
        path.write_text(json.dumps(status))
    before = _snapshot(marker_run.run)
    with pytest.raises(integration.OptionalSaTScanIntegrationError, match="execution-status|Unsupported secondary"):
        integration.inspect_satscan_results(paths=marker_run.paths, secondary_run_id=marker_run.run_id)
    assert _snapshot(marker_run.run) == before
