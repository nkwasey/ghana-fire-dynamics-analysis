from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def test_public_docs_distinguish_normal_use_from_complete_source_qualification() -> None:
    sub = (ROOT / "README.md").read_text(encoding="utf-8")
    top = (REPO / "README.md").read_text(encoding="utf-8")
    assert "Normal analysis use" in sub
    assert "Complete source qualification" in sub
    for text in (sub, top):
        assert "rp1_analysis" in text
        assert "rp1_mv_firms_panels" in text
        assert "geo_data_prep" in text
        assert "tools/qualify_source_checkout.py" in text


def test_source_qualifier_uses_governed_projection_authority_and_full_estate() -> None:
    path = REPO / "tools/qualify_source_checkout.py"
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    assert "load_qualification_contract" in source
    assert "inventory_governed_source" in source
    assert "project_governed_source" in source
    assert "projected_import_environment" in source
    assert "probe_projected_imports" in source
    assert "verify_projected_inventory" in source
    assert "remove_generated_artifacts_from_projection" in source
    assert "origin.is_relative_to" in source
    assert "RP_RUN_NATIVE_PLOT_SMOKE" in source
    assert "example_acz" in source
    assert source.count('"-m", "pytest"') == 1
    assert 'cwd=projection_root' in source
    assert "clean_generated_outputs" not in source
