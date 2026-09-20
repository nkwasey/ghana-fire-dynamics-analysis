from __future__ import annotations

import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def _yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def _markdown_text() -> str:
    nb = json.loads((ROOT / "RP1_Analysis_v1.ipynb").read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in nb["cells"]
        if cell.get("cell_type") == "markdown"
    )


def test_current_facing_docs_match_generated_figure_and_external_boundary() -> None:
    figures = _yaml("figure_contract.yml")["figures"]
    main = [item["id"] for item in figures if item["role"] == "manuscript"]
    supp = [item["id"] for item in figures if item["role"] == "supplementary"]
    assert main == ["F2", "F3", "F4", "F5", "F6"]
    assert supp == ["S1"]
    docs = [
        REPO / "README.md",
        ROOT / "README.md",
        ROOT / "docs/Figure_Table_Contract.md",
        ROOT / "docs/Output_Guide.md",
        ROOT / "docs/Configuration_Guide.md",
    ]
    combined = "\n".join(p.read_text(encoding="utf-8") for p in docs)
    assert "Figure 1" in combined and "extern" in combined.lower()
    assert "F2–F6" in combined
    assert "20 × 15 cm" in combined
    assert "T3/F6/S6" in combined or "T3, F6 and S6" in combined


def test_notebook_markdown_describes_current_publication_estate() -> None:
    text = _markdown_text()
    assert "external Figure 1" in text
    assert "generated F2–F6" in text
    assert "T1–T3" in text
    assert "S1–S6" in text
    assert "Figure S1" in text
    assert "T3/F6/S6" in text


def test_methods_sha_provenance_is_single_current_identity() -> None:
    rq1 = json.loads((ROOT / "data/authorities/rq1/realised_run_metadata.json").read_text())
    rq2 = json.loads((ROOT / "data/authorities/rq2/realised_run_metadata.json").read_text())
    rq3 = json.loads((ROOT / "data/authorities/rq3/realised_run_metadata.json").read_text())
    rq3_manifest = json.loads((ROOT / "data/authorities/rq3/source_manifest.json").read_text())
    values = {
        rq1["methods_spec_sha256"],
        rq2["methods_spec_sha256"],
        rq3["methods_spec_sha256"],
        rq3_manifest["methods_specification_sha256"],
    }
    assert len(values) == 1
    value = next(iter(values))
    assert re.fullmatch(r"[0-9a-f]{64}", value)


def test_obsolete_vertical_layout_authorities_are_absent() -> None:
    raw = _yaml("figure_contract.yml")
    assert not any(str(k).endswith("_vertical") for k in raw["dimensions_inches"])
    assert not any(str(k).endswith("_vertical") for k in raw["grid_layouts"])
    style = (ROOT / "src/rp1_analysis_v1/style.py").read_text(encoding="utf-8")
    assert "two_panel" + "_vertical" not in style
    assert "three_panel" + "_vertical" not in style
    assert "five_panel" + "_vertical" not in style


def test_public_product_is_phase_neutral_and_has_no_packaging_runtime_dependency() -> None:
    development_identity_patterns = (
        re.compile(r"\bV\d{3,}[-_]\d+\b", flags=re.IGNORECASE),
        re.compile(r"\bLOCAL[-_]\d+\b", flags=re.IGNORECASE),
    )
    archive_pattern = re.compile(r"\.zip(?:$|[\s'\"])", flags=re.IGNORECASE)
    suffixes = {".py", ".md", ".yml", ".yaml", ".json", ".toml", ".txt", ".ipynb"}
    offenders: list[str] = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if (
            any(pattern.search(text) for pattern in development_identity_patterns)
            or archive_pattern.search(text)
        ):
            offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == []


def test_satscan_monthly_boundary_documentation_matches_current_interface_contract() -> None:
    docs = [
        REPO / "README.md",
        ROOT / "README.md",
        ROOT / "docs/Secondary_Analysis_Contract.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in docs).lower()
    assert "first calendar day" in combined
    assert "final calendar day" in combined
    assert "leap-year" in combined
    assert "2001/1/1" in combined and "2024/12/31" in combined
    assert "2012/2/1" in combined
