from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.registers import result_registry

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]


def _bundle():
    return load_configuration_bundle(ROOT / "config")


def test_current_generated_publication_estate_is_positive_and_complete() -> None:
    bundle = _bundle()
    main_figures = {item.figure_id for item in bundle.figure.figures if item.role == "manuscript"}
    supplementary_figures = {item.figure_id for item in bundle.figure.figures if item.role == "supplementary"}
    manuscript_tables = {item.output_id for item in bundle.output.tables if item.role == "manuscript"}
    supplementary_tables = {item.output_id for item in bundle.output.tables if item.role == "supplementary"}
    secondary_tables = {item.output_id for item in bundle.output.tables if item.rq == "SECONDARY"}
    secondary_figures = {item.figure_id for item in bundle.figure.figures if item.rq == "SECONDARY"}

    assert main_figures == {"F2", "F3", "F4", "F5", "F6"}
    assert supplementary_figures == {"S1"}
    assert manuscript_tables == {"T1", "T2", "T3"}
    assert supplementary_tables == {"S1", "S2", "S3", "S4", "S5", "S6"}
    assert secondary_tables | secondary_figures == {"T3", "F6", "S6"}
    assert "F1" not in {item.figure_id for item in bundle.figure.figures}


def test_current_semantic_presentation_sources_exist() -> None:
    bundle = _bundle()
    sources = {item.source_attribute for item in bundle.figure.figures}
    assert {
        "long_run_spatial_rate_presentation_source",
        "seasonality_spatial_organisation_presentation_source",
        "annual_trend_source",
        "cross_product_observability_presentation_source",
        "cluster_recurrence_source",
        "district_seasonal_diagnostics_source",
    }.issubset(sources)


def test_result_registry_uses_semantic_result_to_presentation_provenance() -> None:
    bundle = _bundle()
    rq1 = pd.DataFrame([
        {
            "specification_role": "primary",
            "morans_i": 0.4,
            "permutation_p": 0.01,
            "n_effective": 240,
        }
    ])
    rq2 = pd.DataFrame([
        {"parent_code": code, "sen_slope": -0.1, "raw_p": 0.02, "bh_q": 0.04, "n": 24}
        for code in ("CZ", "FZ", "GS", "SS", "TZ")
    ])
    rq3 = pd.DataFrame([
        {
            "term": "log2_viirs_det_primary",
            "adjusted_or": 0.9,
            "or_lower_95": 0.8,
            "or_upper_95": 1.0,
            "p": 0.03,
            "n": 22939,
        },
        {
            "term": "log2_viirs_frp_mean_mw",
            "adjusted_or": 1.1,
            "or_lower_95": 1.0,
            "or_upper_95": 1.2,
            "p": 0.04,
            "n": 22939,
        },
    ])

    registry = result_registry(
        rq1,
        rq2,
        rq3,
        output_contract=bundle.output,
        figure_contract=bundle.figure,
    ).set_index("result_id")

    global_moran = registry.loc["RQ1_GLOBAL_MORAN_PRIMARY"]
    assert global_moran["source_table"] == "S3.csv"
    assert global_moran["source_figure"] == ""

    rq2_rows = registry.loc[registry.index.str.startswith("RQ2_TREND_")]
    assert set(rq2_rows["source_table"]) == {"T1.csv"}
    assert set(rq2_rows["source_figure"]) == {"F4"}

    rq3_rows = registry.loc[registry.index.str.startswith("RQ3_PGEE_")]
    assert set(rq3_rows["source_table"]) == {"T2.csv"}
    assert set(rq3_rows["source_figure"]) == {"F5"}


def test_public_product_is_phase_neutral_and_self_contained() -> None:
    development_identity_patterns = (
        re.compile(r"\bv\d{3,}[-_]\d+\b", flags=re.IGNORECASE),
        re.compile(r"\blocal[-_]\d+\b", flags=re.IGNORECASE),
    )
    forbidden_runtime_patterns = (
        re.compile(r"\.zip(?:$|[\s'\"])", flags=re.IGNORECASE),
        re.compile(r"/home/[^/\s]+/", flags=re.IGNORECASE),
        re.compile(r"/mnt/[A-Za-z]/(?:Users|home)/", flags=re.IGNORECASE),
        re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]", flags=re.IGNORECASE),
    )
    suffixes = {".py", ".md", ".yml", ".yaml", ".json", ".toml", ".txt", ".ipynb"}
    offenders: list[str] = []
    for path in REPOSITORY_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if (
            "tests" in path.parts
            or "out" in path.parts
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if (
            any(pattern.search(text) for pattern in development_identity_patterns)
            or any(pattern.search(text) for pattern in forbidden_runtime_patterns)
        ):
            offenders.append(path.relative_to(REPOSITORY_ROOT).as_posix())
    assert offenders == []
