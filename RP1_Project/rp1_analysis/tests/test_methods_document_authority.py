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


def test_current_method_configuration_is_self_contained():
    from rp1_analysis_v1.config import load_configuration_bundle
    bundle = load_configuration_bundle(ROOT / "config")
    assert len(bundle.configuration_sha256) == 64
    local = bundle.analysis.research_questions["rq1"]["spatial"]["local"]
    assert local["tie_allocation"] == "both_tails"
    assert local["multiply_smaller_tail_by_two"] is True


def test_configuration_identity_changes_with_method_parameters(tmp_path):
    import shutil
    from rp1_analysis_v1.config import load_configuration_bundle
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copy2(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    first = load_configuration_bundle(tmp_path / "config").configuration_sha256
    path = tmp_path / "config/analysis_contract.yml"
    text = path.read_text()
    text = text.replace("primary_seed: 20260822", "primary_seed: 42")
    path.write_text(text)
    assert load_configuration_bundle(tmp_path / "config").configuration_sha256 != first


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
