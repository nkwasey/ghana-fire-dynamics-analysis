from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _legacy_tokens() -> tuple[str, ...]:
    return (
        "s" + "7" + "_run_registry",
        "build_" + "t" + "6" + "_source",
        "build_" + "s" + "7" + "_membership_source",
        "build_" + "f" + "7" + "_source",
        "t" + "6" + "_source",
        "s" + "7" + "_membership",
        "Table" + " 6",
        "Figure" + " 7",
        "S" + "7 run registry",
    )

def _scannable_files() -> list[Path]:
    roots = [ROOT / "src", ROOT / "config", ROOT / "tests", ROOT / "docs"]
    files: list[Path] = [ROOT / "RP1_Analysis_v1.ipynb"]
    for root in roots:
        files.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".py", ".yml", ".yaml", ".md", ".ipynb"})
    return sorted(set(files))

def test_secondary_analysis_uses_publication_number_neutral_internal_identities() -> None:
    hits: list[str] = []
    for path in _scannable_files():
        text = path.read_text(encoding="utf-8")
        for token in _legacy_tokens():
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}: {token}")
    assert hits == []

def test_neutral_secondary_identifiers_are_wired_through_code_config_and_notebook() -> None:
    secondary = (ROOT / "src/rp1_analysis_v1/secondary_clusters.py").read_text(encoding="utf-8")
    integration = (ROOT / "src/rp1_analysis_v1/integration.py").read_text(encoding="utf-8")
    publication = (ROOT / "src/rp1_analysis_v1/publication_sources.py").read_text(encoding="utf-8")
    output_contract = (ROOT / "config/output_contract.yml").read_text(encoding="utf-8")
    notebook = (ROOT / "RP1_Analysis_v1.ipynb").read_text(encoding="utf-8")
    assert "secondary_run_registry" in secondary
    assert "secondary_run_registry" in integration
    assert "source_attribute: secondary_run_registry" in output_contract
    assert "secondary.secondary_run_registry" in notebook
    assert "build_cluster_summary_source" in secondary and "build_cluster_summary_source" in publication
    assert "build_cluster_membership_source" in secondary and "build_cluster_membership_source" in publication
    assert "build_cluster_map_source" in secondary
