from __future__ import annotations

import json
from pathlib import Path
import nbformat

from rp1_analysis_v1 import CanonicalIntegrationResult, validate_canonical_integration

ROOT = Path(__file__).resolve().parents[1]


def _nb_text() -> tuple[str, str]:
    nb = nbformat.read(ROOT / "RP1_Analysis_v1.ipynb", as_version=4)
    code = "\n".join(c.source for c in nb.cells if c.cell_type == "code")
    markdown = "\n".join(c.source for c in nb.cells if c.cell_type == "markdown")
    return code, markdown


def test_canonical_integration_api_is_public() -> None:
    assert CanonicalIntegrationResult.__name__ == "CanonicalIntegrationResult"
    assert callable(validate_canonical_integration)


def test_notebook_uses_package_owned_canonical_validator_and_exact_final_gate() -> None:
    code, _ = _nb_text()
    assert "validate_canonical_integration(" in code
    assert 'final_run_gate = "PASS"' in code
    assert 'publication_gate = integration_validation.status' in code
    assert 'PUBLICATION_RUN = build_publication_run_isolated(' in code
    assert 'if secondary.execution_state == RESULTS_VALIDATED' not in code


def test_notebook_has_final_rq2_rq3_and_probability_authorities() -> None:
    code, _ = _nb_text()
    assert "realised_bandwidth" in code
    assert "permutation_count" in code
    assert "standardised_probability_source" in code
    assert "reference_distribution" in code
    assert "active_days" not in code
    assert "modis_det_primary_any" not in code


def test_publication_contract_is_final_identity() -> None:
    from rp1_analysis_v1.config import load_configuration_bundle
    bundle=load_configuration_bundle(ROOT/"config")
    assert [x.output_id for x in bundle.output.tables if x.role=="manuscript"] == ["T1","T2","T3"]
    assert [x.output_id for x in bundle.output.tables if x.role=="supplementary"] == ["S1","S2","S3","S4","S5","S6"]
    assert [x.figure_id for x in bundle.figure.figures if x.role=="manuscript"] == ["F2","F3","F4","F5","F6"]
    assert [x.figure_id for x in bundle.figure.figures if x.role=="supplementary"] == ["S1"]


def test_public_docs_are_standalone_and_describe_current_contract() -> None:
    public = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    text = "\n".join(path.read_text(encoding="utf-8") for path in public)
    assert "1.2.3" in text
    assert "Romano–Tirlea" in text
    assert "Firth-type penalised GEE" in text
    assert "hierarchical" in text.lower()


def test_required_public_guides_exist() -> None:
    for name in ("Configuration_Guide.md","Variable_Map.md","Output_Guide.md"):
        assert (ROOT/"docs"/name).is_file()
