from __future__ import annotations

import json
import re
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

ACTIVE_DOCS = [
    REPO / "README.md",
    ROOT / "README.md",
    ROOT / "docs/Analysis_Methods_Contract.md",
    ROOT / "docs/Method_Authority_Register.md",
    ROOT / "docs/Reference_Method_Validation.md",
    ROOT / "docs/Configuration_Guide.md",
    ROOT / "docs/Data_Contract.md",
    ROOT / "docs/Reproducibility_Contract.md",
]


def _combined() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in ACTIVE_DOCS)


def _docx_text(path: Path) -> str:
    with ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return " ".join(node.text or "" for node in root.findall(".//w:t", ns))


def test_rq2_current_documentation_separates_effect_from_inferential_null() -> None:
    text = _combined().lower()
    assert "sen's slope" in text or "sen’s slope" in text
    assert "strict stationarity" in text
    assert "h0: sen slope = 0" not in text
    assert "non-rejection" in text
    assert "not causal" in text or "not interpreted causally" in text


def test_rq2_tie_reference_scope_and_fail_closed_policy_are_explicit() -> None:
    text = _combined().lower()
    assert "tie-free" in text
    assert "fail closed" in text or "fail_closed" in text
    assert "pairwise" in text and "inferential qualification" in text
    assert "all five ghana" in text and "tie-free" in text
    analysis = yaml.safe_load((ROOT / "config/analysis_contract.yml").read_text(encoding="utf-8"))
    rule = analysis["research_questions"]["rq2"]["inferential_test"]["reference_admissibility"]
    assert rule == {"requires_distinct_observations": True, "on_ties": "fail_closed"}


def test_rq2_parameter_provenance_is_not_overattributed_to_reference_theorem() -> None:
    text = _combined().lower()
    assert "study/computational choices" in text or "study or computational choices" in text
    assert "not uniquely" in text and "theorem" in text
    methods = yaml.safe_load((ROOT / "config/method_authorities.yml").read_text(encoding="utf-8"))
    rq2 = next(a for a in methods["authorities"] if a["method_id"] == "studentized_global_mann_kendall_permutation")
    assert rq2["parameter_provenance"]["bandwidth_rule"] == "study_design_defined"
    assert rq2["parameter_provenance"]["p_value_construction"] == "study_design_defined"


def test_obsolete_rq2_and_transition_claims_are_absent() -> None:
    text = _combined().lower()
    for token in (
        "block-bootstrap mk", "residual-bootstrap sen", "annual-denominator sensitivity",
        "hamed–rao production", "yue–wang production", "ordinary-mk fallback", "prewhitening",
        "transition significant decline", "transition zone significant decline",
    ):
        assert token not in text
    assert "none has bh-fdr-supported evidence of monotonic decline" in text


def test_circular_month_documentation_uses_cyclic_coordinate() -> None:
    text = _combined().lower()
    assert "0 is equivalent to 12" in text or "0 ≡ 12" in text
    assert "strictly [1,12]" not in text and "strictly [1, 12]" not in text


def test_current_methods_docx_carries_same_scientific_scope() -> None:
    authority = json.loads((ROOT / "data/authorities/methods_document_authority.json").read_text(encoding="utf-8"))
    docx = ROOT / "docs" / authority["docx"]["filename"]
    text = _docx_text(docx).lower()
    for phrase in (
        "strict stationarity", "tie-free", "fail closed", "sen slope", "plus-one monte carlo",
        "0 is equivalent to 12", "external execution boundary", "results_validated",
        "scientific method change: none",
    ):
        assert phrase in text
    assert "h0: sen slope = 0" not in text
    assert "none has bh-fdr-supported evidence of monotonic decline" in text


def test_active_documentation_is_phase_neutral_and_machine_neutral() -> None:
    text = _combined()
    development_identity_pattern = re.compile(r"\bV\d{3,}[-_]\d+\b", flags=re.IGNORECASE)
    assert not development_identity_pattern.search(text)
    lowered = text.lower()
    assert ".zip" not in lowered
    machine_path_patterns = (
        re.compile(r"/home/[^/\s]+/", flags=re.IGNORECASE),
        re.compile(r"/mnt/[A-Za-z]/(?:Users|home)/", flags=re.IGNORECASE),
        re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]", flags=re.IGNORECASE),
    )
    assert not any(pattern.search(text) for pattern in machine_path_patterns)
