from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.integration import IntegrationError, finalise_interactive_run
from rp1_analysis_v1.paths import ProjectPaths

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
FIXTURE_SEC = ROOT / "tests/fixtures/qualified_presentation_run/qualified_presentation_fixture_sec"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): _sha(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _project(
    tmp_path: Path,
    *,
    state: str = "RESULTS_VALIDATED",
    canonical_input_identity: str = "MATCH",
) -> tuple[ProjectPaths, str]:
    root = tmp_path / "rp1"
    root.mkdir(parents=True)
    shutil.copytree(CONFIG, root / "config")
    shutil.copy2(ROOT / "pyproject.toml", root / "pyproject.toml")
    bundle = load_configuration_bundle(root / "config")
    run_id = "interactive_test"
    pub = root / "out/runs" / f"{run_id}_pub"
    sec = root / "out/runs" / f"{run_id}_sec"
    close = root / "out/runs" / f"{run_id}_close"
    pub.mkdir(parents=True)
    shutil.copytree(FIXTURE_SEC, sec)
    (close / "99_closeout").mkdir(parents=True)

    if state == "EXTERNAL_RESULTS_REQUIRED":
        section = sec / "04_secondary_concentration"
        status_path = section / "secondary_external_execution_status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["external_execution_state"] = "EXTERNAL_RESULTS_REQUIRED"
        status["validated_model_count"] = 0
        status["live_satscan_execution"] = "DEFERRED_EXTERNAL_EXECUTION"
        status_path.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n", encoding="utf-8")

        import pandas as pd
        registry_path = section / "tables/secondary_run_registry.csv"
        registry = pd.read_csv(registry_path, keep_default_na=False)
        registry["execution_state"] = "EXTERNAL_RESULTS_REQUIRED"
        if "results_validated" in registry.columns:
            registry["results_validated"] = False
        registry.to_csv(registry_path, index=False)
        # A deferred state has no integrated publication-source authority.
        shutil.rmtree(section / "publication_sources", ignore_errors=True)

    gate = {
        "canonical_notebook": "RP1_Analysis_v1.ipynb",
        "configuration_sha256": bundle.configuration_sha256,
        "input_validation_status": "PASS",
        "canonical_input_identity": canonical_input_identity,
        "scaffold_gate": "PASS",
        "rq1_gate": "PASS",
        "rq2_gate": "PASS",
        "rq3_gate": "PASS",
        "secondary_gate": "PASS",
        "secondary_external_state": state,
        "publication_gate": "PASS",
        "final_run_gate": "PASS",
    }
    (close / "99_closeout/M_CANONICAL_EXECUTION_GATE.json").write_text(
        json.dumps(gate, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    provenance = {
        "schema_version": bundle.analysis.schema_version,
        "run_id": f"{run_id}_close",
        "started_at_utc": "2026-09-10T10:00:00Z",
        "ended_at_utc": "2026-09-10T10:01:00Z",
        "configuration_sha256": bundle.configuration_sha256,
        "input_validation_status": "PASS",
        "canonical_input_identity": canonical_input_identity,
        "inputs": [{"path": "data/raw/example.csv", "sha256": "a" * 64, "size_bytes": 1}],
        "environment": {},
        "determinism_note": "test",
    }
    (close / "99_closeout/M_REPRODUCIBILITY_MANIFEST.json").write_text(
        json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return ProjectPaths(root), run_id


def test_interactive_finalisation_writes_honest_machine_readable_completion(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    pub = paths.root / "out/runs" / f"{run_id}_pub"
    sec = paths.root / "out/runs" / f"{run_id}_sec"
    before = {"pub": _inventory(pub), "sec": _inventory(sec)}
    result = finalise_interactive_run(paths=paths, run_id=run_id)
    assert result.status == "PASS"
    assert result.execution_mode == "interactive_jupyter"
    assert result.deferred_to_controlled_wrapper is False
    assert result.execution_record is not None and result.execution_record.is_file()
    record = json.loads(result.execution_record.read_text(encoding="utf-8"))
    bundle = load_configuration_bundle(paths.root / "config")
    assert record["schema"] == bundle.execution.execution_record_schema
    assert record["execution_mode"] == "interactive_jupyter"
    assert record["run_id"] == run_id
    assert record["package_version"] == bundle.package_version
    assert record["analysis_schema_version"] == bundle.analysis.schema_version
    assert record["data_schema_version"] == bundle.data_schema.data_schema_version
    assert record["configuration_sha256"] == bundle.configuration_sha256
    assert record["operational_configuration_sha256"] == bundle.operational_configuration_sha256
    assert record["final_section_reached"] is True
    assert record["canonical_gate_status"] == "PASS"
    assert record["publication_gate_status"] == "PASS"
    assert record["input_validation_status"] == "PASS"
    assert record["canonical_input_identity"] == "MATCH"
    assert record["secondary_execution_state"] == "RESULTS_VALIDATED"
    assert record["secondary_integration_state"] == "INTEGRATED"
    assert record["secondary_validated_model_count"] == 2
    assert record["satscan_execution_performed"] is False
    assert record["notebook_snapshot_required"] is False
    assert record["notebook_snapshot_available"] is False
    assert record["provenance_limitations"]
    assert not (result.closeout_run_dir / "99_closeout/RP1_Analysis_v1.executed.ipynb").exists()
    assert before == {"pub": _inventory(pub), "sec": _inventory(sec)}


def test_interactive_finalisation_accepts_valid_noncanonical_input_identity(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path, canonical_input_identity="DIFFERENT")
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    result = finalise_interactive_run(paths=paths, run_id=run_id)
    assert result.status == "PASS"
    assert result.execution_record is not None
    record = json.loads(result.execution_record.read_text(encoding="utf-8"))
    assert record["input_validation_status"] == "PASS"
    assert record["canonical_input_identity"] == "DIFFERENT"


def test_interactive_finalisation_supports_external_results_required(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path, state="EXTERNAL_RESULTS_REQUIRED")
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    result = finalise_interactive_run(paths=paths, run_id=run_id)
    record = json.loads(result.execution_record.read_text(encoding="utf-8"))  # type: ignore[union-attr]
    assert record["secondary_execution_state"] == "EXTERNAL_RESULTS_REQUIRED"
    assert record["secondary_integration_state"] == "NOT_INTEGRATED"
    assert record["secondary_validated_model_count"] == 0


def test_interactive_finalisation_is_idempotent_for_identical_state(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    first = finalise_interactive_run(paths=paths, run_id=run_id)
    assert first.execution_record is not None
    first_hash = _sha(first.execution_record)
    second = finalise_interactive_run(paths=paths, run_id=run_id)
    assert second.reused_existing_record is True
    assert second.execution_record is not None
    assert _sha(second.execution_record) == first_hash


def test_interactive_finalisation_rejects_conflicting_existing_record(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    result = finalise_interactive_run(paths=paths, run_id=run_id)
    assert result.execution_record is not None
    record = json.loads(result.execution_record.read_text(encoding="utf-8"))
    record["configuration_sha256"] = "0" * 64
    result.execution_record.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IntegrationError, match="conflicts|invalid"):
        finalise_interactive_run(paths=paths, run_id=run_id)


@pytest.mark.parametrize("field", ["rq1_gate", "publication_gate", "final_run_gate"])
def test_interactive_finalisation_rejects_failed_required_gates(tmp_path: Path, monkeypatch, field: str) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    gate_path = paths.root / "out/runs" / f"{run_id}_close/99_closeout/M_CANONICAL_EXECUTION_GATE.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate[field] = "FAIL"
    gate_path.write_text(json.dumps(gate, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IntegrationError, match="requires every canonical section/publication gate to PASS"):
        finalise_interactive_run(paths=paths, run_id=run_id)


def test_interactive_finalisation_rejects_missing_reproducibility_manifest(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    (paths.root / "out/runs" / f"{run_id}_close/99_closeout/M_REPRODUCIBILITY_MANIFEST.json").unlink()
    with pytest.raises(IntegrationError, match="requires the reproducibility manifest"):
        finalise_interactive_run(paths=paths, run_id=run_id)


def test_interactive_finalisation_rejects_wrong_run_and_configuration_identity(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    provenance_path = paths.root / "out/runs" / f"{run_id}_close/99_closeout/M_REPRODUCIBILITY_MANIFEST.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["run_id"] = "wrong_close"
    provenance_path.write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IntegrationError, match="run identity"):
        finalise_interactive_run(paths=paths, run_id=run_id)

    paths, run_id = _project(tmp_path / "second")
    gate_path = paths.root / "out/runs" / f"{run_id}_close/99_closeout/M_CANONICAL_EXECUTION_GATE.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["configuration_sha256"] = "0" * 64
    gate_path.write_text(json.dumps(gate, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IntegrationError, match="configuration identity"):
        finalise_interactive_run(paths=paths, run_id=run_id)


def test_interactive_finalisation_rejects_malformed_secondary_state(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
    status_path = paths.root / "out/runs" / f"{run_id}_sec/04_secondary_concentration/secondary_external_execution_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["external_execution_state"] = "INPUTS_READY"
    status_path.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IntegrationError, match="Unsupported secondary completion state|inconsistent"):
        finalise_interactive_run(paths=paths, run_id=run_id)


def test_controlled_wrapper_context_defers_interactive_record(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.setenv("RP1_NOTEBOOK_EXECUTION_MODE", "controlled_nbclient")
    result = finalise_interactive_run(paths=paths, run_id=run_id)
    assert result.deferred_to_controlled_wrapper is True
    assert result.execution_record is None
    assert not (paths.root / "out/runs" / f"{run_id}_close/99_closeout/M_NOTEBOOK_EXECUTION.json").exists()


def test_unknown_execution_context_fails_closed(tmp_path: Path, monkeypatch) -> None:
    paths, run_id = _project(tmp_path)
    monkeypatch.setenv("RP1_NOTEBOOK_EXECUTION_MODE", "invented")
    with pytest.raises(IntegrationError, match="Unsupported notebook execution context"):
        finalise_interactive_run(paths=paths, run_id=run_id)
