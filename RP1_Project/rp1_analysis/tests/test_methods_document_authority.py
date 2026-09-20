from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "data/authorities/methods_document_authority.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_current_methods_document_authority_is_phase_neutral_and_science_preserving() -> None:
    payload = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    assert payload["schema"] == "rp1-methods-document-authority-v1"
    assert payload["document_role"] == "current_methods_authority"
    assert payload["scientific_method_change"] == "NONE"
    assert set(payload["alignment_scope"]) == {
        "scientific_documentation",
        "reference_scope",
        "method_provenance",
        "presentation_outputs",
        "optional_external_result_integration",
    }
    assert payload["docx"]["filename"].endswith(".docx")
    assert payload["pdf"]["filename"].endswith(".pdf")
    assert len(payload["docx"]["sha256"]) == 64
    assert len(payload["pdf"]["sha256"]) == 64
    for key in ("docx", "pdf"):
        document = ROOT / "docs" / payload[key]["filename"]
        assert document.is_file()
        assert document.stat().st_size == payload[key]["size_bytes"]
        assert _sha(document) == payload[key]["sha256"]
    assert "immutable snapshots" in payload["scientific_run_provenance_policy"]


def test_scientific_run_metadata_remain_one_immutable_methods_snapshot() -> None:
    rq1 = json.loads((ROOT / "data/authorities/rq1/realised_run_metadata.json").read_text())
    rq2 = json.loads((ROOT / "data/authorities/rq2/realised_run_metadata.json").read_text())
    rq3 = json.loads((ROOT / "data/authorities/rq3/realised_run_metadata.json").read_text())
    rq3_manifest = json.loads((ROOT / "data/authorities/rq3/source_manifest.json").read_text())
    historical = {
        rq1["methods_spec_sha256"],
        rq2["methods_spec_sha256"],
        rq3["methods_spec_sha256"],
        rq3_manifest["methods_specification_sha256"],
    }
    assert len(historical) == 1
    current = json.loads(AUTHORITY.read_text())["docx"]["sha256"]
    assert next(iter(historical)) != current


def test_methods_document_authority_materialiser_is_deterministic(tmp_path: Path) -> None:
    docx = tmp_path / "methods.docx"
    pdf = tmp_path / "methods.pdf"
    docx.write_bytes(b"docx-test-bytes")
    pdf.write_bytes(b"pdf-test-bytes")
    out1 = tmp_path / "one.json"
    out2 = tmp_path / "two.json"
    script = ROOT / "scripts/materialize_methods_document_authority.py"
    for out in (out1, out2):
        subprocess.run(
            [sys.executable, str(script), "--docx", str(docx), "--pdf", str(pdf), "--output", str(out)],
            check=True,
        )
    assert out1.read_bytes() == out2.read_bytes()
    payload = json.loads(out1.read_text())
    assert payload["docx"]["sha256"] == _sha(docx)
    assert payload["pdf"]["sha256"] == _sha(pdf)
