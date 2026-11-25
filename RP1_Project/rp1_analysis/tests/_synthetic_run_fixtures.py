"""Small test-only state authorities; these are not empirical SaTScan results."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def secondary_status(model_count: int = 2) -> dict:
    return {
        "fixture_kind": "SYNTHETIC_TEST_ONLY",
        "external_execution_state": "RESULTS_VALIDATED",
        "model_count": model_count,
        "validated_model_count": model_count,
        "live_satscan_execution": "VALIDATED_EXTERNAL_RESULTS_INGESTED",
    }


def write_secondary_state(run: Path, scenarios) -> None:
    """Exercise state-consumer contracts without claiming any engine execution."""
    section = run / "04_secondary_concentration"
    (section / "tables").mkdir(parents=True)
    (section / "publication_sources").mkdir()
    (section / "secondary_external_execution_status.json").write_text(
        json.dumps(secondary_status(len(scenarios))), encoding="utf-8"
    )
    pd.DataFrame([
        {"model_id": str(item["scenario_id"]), "execution_state": "RESULTS_VALIDATED", "results_validated": True}
        for item in scenarios
    ]).to_csv(section / "tables/secondary_run_registry.csv", index=False)
    (section / "publication_sources/M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json").write_text(
        json.dumps({"fixture_kind": "SYNTHETIC_TEST_ONLY", "external_execution_state": "RESULTS_VALIDATED"}),
        encoding="utf-8",
    )
