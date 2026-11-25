"""Opt-in integration regression using a copied, genuinely validated run family.

The clean source ZIP contains no generated scientific run. Set the two documented
environment variables to an original governed run to exercise this regression;
the original is only read and all edits occur in pytest's disposable copy.
"""
from pathlib import Path
import os
import shutil

import pytest

from rp1_analysis_v1 import execution_evidence, integration
from rp1_analysis_v1.paths import ProjectPaths


def test_export_refuses_table_edit_after_actual_run_validation(tmp_path, monkeypatch):
    token = os.environ.get("RP1_EXPORT_REGRESSION_ANALYSIS_ROOT")
    run_id = os.environ.get("RP1_EXPORT_REGRESSION_RUN_ID")
    if not token or not run_id:
        pytest.skip("Requires an explicitly selected generated analysis run; see EXECUTION_EVIDENCE.md")
    original_root = Path(token).resolve()
    original_paths = ProjectPaths(original_root)
    actual_validate = integration.validate_run_authority
    monkeypatch.setenv("RP1_ANALYSIS_V1_ROOT", str(original_root))
    assert actual_validate(paths=original_paths, run_id=run_id).status == "PASS"

    root = tmp_path / "analysis"
    root.mkdir()
    for folder in ("config", "data"):
        shutil.copytree(original_root / folder, root / folder, copy_function=shutil.copy2)
    for name in ("pyproject.toml", "RP1_Analysis_v1.ipynb"):
        shutil.copy2(original_root / name, root / name)
    for suffix in ("pub", "sec", "close"):
        relative = Path("out/runs") / f"{run_id}_{suffix}"
        shutil.copytree(original_root / relative, root / relative, copy_function=shutil.copy2)
    # The input acknowledgement's original lineage remains read-only. Its bytes
    # are not changed or falsely attributed to the disposable run-family copy.
    paths = ProjectPaths(root)
    assert actual_validate(paths=paths, run_id=run_id).status == "PASS"
    table = next((root / f"out/runs/{run_id}_pub").rglob("T1.csv"))
    before = table.read_bytes()
    calls = []
    def edit_after_actual_validation(**kwargs):
        validated = actual_validate(**kwargs)
        calls.append(validated.status)
        table.write_bytes(before + b"\n")
        return validated
    monkeypatch.setattr(integration, "validate_run_authority", edit_after_actual_validation)
    target = tmp_path / "exported"
    with pytest.raises(execution_evidence.ExternalResultValidationError, match="snapshot"):
        execution_evidence.export_execution_evidence(paths=paths, run_id=run_id, output_dir=target)
    assert calls == ["PASS"]
    assert not (target / "EXECUTION_EVIDENCE_MANIFEST.json").exists()
    assert actual_validate(paths=original_paths, run_id=run_id).status == "PASS"
