from __future__ import annotations

import ast
import re
from pathlib import Path

import nbformat

SUBPROJECT = Path(__file__).resolve().parents[1]
NOTEBOOK = SUBPROJECT / "RP1_Analysis_v1.ipynb"

SECTIONS = [
    "SECTION 00 — Scaffold / authority",
    "SECTION 01 — RQ1",
    "SECTION 02 — RQ2",
    "SECTION 03 — RQ3",
    "SECTION 04 — Secondary analysis",
    "SECTION 90 — Integrated publication outputs",
    "SECTION 99 — Reproducibility closeout",
]

STEP_IDS = [
    "00-01", "00-02", "00-03",
    "01-01", "01-02",
    "02-01", "02-02",
    "03-01", "03-02",
    "04-01", "04-02",
    "90-01",
    "99-01", "99-02",
]

METHOD_LABELS = (
    "**Scientific purpose:**",
    "**Theoretical/methodological basis:**",
    "**Inputs:**",
    "**Method:**",
    "**Expected output:**",
    "**Interpretation limits:**",
)


def _nb():
    return nbformat.read(NOTEBOOK, as_version=4)


def _source(cell) -> str:
    return "".join(cell.get("source", ""))


def _all_code() -> str:
    return "\n".join(_source(c) for c in _nb().cells if c.cell_type == "code")


def _all_markdown() -> str:
    return "\n".join(_source(c) for c in _nb().cells if c.cell_type == "markdown")


def _step_ids() -> list[str]:
    pattern = re.compile(r"^###\s+([0-9]{2}-[0-9]{2})\s+—", re.MULTILINE)
    return [m.group(1) for m in pattern.finditer(_all_markdown())]


def test_canonical_filename_and_nbformat_validation() -> None:
    assert NOTEBOOK.name == "RP1_Analysis_v1.ipynb"
    nb = _nb()
    nbformat.validate(nb)
    assert nb.metadata["rp1_analysis"]["canonical"] is True
    assert nb.metadata["rp1_analysis"]["role"] == "thin_orchestrator"


def test_exact_section_order() -> None:
    text = _all_markdown()
    positions = [text.index(f"# {section}") for section in SECTIONS]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(SECTIONS)


def test_exact_step_sequence() -> None:
    assert _step_ids() == STEP_IDS


def test_every_code_cell_is_preceded_by_method_markdown() -> None:
    nb = _nb()
    for index, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        assert index > 0
        prior = nb.cells[index - 1]
        assert prior.cell_type == "markdown"
        text = _source(prior)
        for label in METHOD_LABELS:
            assert label in text, (index, label)


def test_code_cells_are_valid_python() -> None:
    for cell in _nb().cells:
        if cell.cell_type == "code":
            ast.parse(_source(cell))


def test_notebook_defines_no_reusable_functions_or_classes() -> None:
    for cell in _nb().cells:
        if cell.cell_type != "code":
            continue
        tree = ast.parse(_source(cell))
        offenders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        assert not offenders


def test_notebook_run_directories_match_operational_executor_contract() -> None:
    code = _all_code()
    assert '"secondary": f"{run_tag}_sec"' in code
    assert '"publication": f"{run_tag}_pub"' in code
    assert '"closeout": f"{run_tag}_close"' in code
    assert 'f"{run_tag}_secondary"' not in code
    assert 'f"{run_tag}_publication"' not in code
    assert 'f"{run_tag}_closeout"' not in code


def test_notebook_has_no_machine_specific_absolute_paths() -> None:
    text = "\n".join(_source(c) for c in _nb().cells)
    for pattern in (r"/mnt/[A-Za-z0-9_/.-]+", r"/home/[A-Za-z0-9_/.-]+", r"[A-Za-z]:\\\\"):
        assert re.search(pattern, text) is None


def test_notebook_uses_governed_relative_authorities() -> None:
    text = "\n".join(_source(c) for c in _nb().cells)
    assert "configuration_sources" in str(_nb().metadata)
    assert "validate_governed_inputs" in text


def test_notebook_narrative_describes_current_scientific_methods() -> None:
    text = _all_markdown().lower()
    assert "studentized global mann–kendall" in text
    assert "firth-type pgee" in text
    assert "space-time permutation" in text


def test_notebook_loads_all_five_configuration_contracts() -> None:
    sources = _nb().metadata["rp1_analysis"]["configuration_sources"]
    assert sources == [
        "config/analysis_contract.yml",
        "config/data_schema_contract.yml",
        "config/method_authorities.yml",
        "config/output_contract.yml",
        "config/figure_contract.yml",
    ]
    code = _all_code()
    assert "load_configuration_bundle" in code
    assert "contracts.file_hashes" in code
    assert "contracts.configuration_sha256" in code


def test_notebook_delegates_input_admission_to_package_validation() -> None:
    code = _all_code()
    assert "validate_governed_inputs(paths, bundle=contracts)" in code
    assert 'input_validation_status == "PASS"' in code
    assert "canonical_input_identity" in code
    assert "paths.input_hash_inventory" not in code
    assert "input_hash_status" not in code
    assert "load_data_authorities" in code
    assert "validate_data_authorities" in code


def test_notebook_executes_package_owned_rq_builders_in_order() -> None:
    code = _all_code()
    positions = [
        code.index("build_rq1_tables("),
        code.index("build_rq2_tables("),
        code.index("build_rq3_tables("),
        code.index("build_secondary_input_run_isolated("),
        code.index("validate_and_integrate_satscan_results_if_available("),
        code.index("build_publication_run_isolated("),
    ]
    assert positions == sorted(positions)


def test_integrated_publication_remains_package_owned_and_uses_validated_authorities() -> None:
    code = _all_code().replace(" ", "")
    assert "PUBLICATION_RUN=build_publication_run_isolated(" in code
    assert 'rq2_gate="PASS"' in code
    assert "publication_gate=integration_validation.status" in code
    assert 'secondary_run_id=run_ids["secondary"]' in code
    publication_call = code.split("PUBLICATION_RUN=build_publication_run_isolated(", 1)[1].split(")", 1)[0]
    assert "rq1=rq1" not in publication_call
    assert "rq2=rq2" not in publication_call
    assert "rq3=rq3" not in publication_call
    assert "validate_canonical_integration(" in code


def test_notebook_preserves_external_satscan_boundary() -> None:
    text = "\n".join(_source(c) for c in _nb().cells)
    assert "EXTERNAL_RESULTS_REQUIRED" in text
    assert "RESULTS_VALIDATED" in text
    assert "not equivalent to zero significant clusters" in text.lower()
    assert "never create synthetic cluster output" in _all_markdown().lower()
    assert "validate_and_integrate_satscan_results_if_available(" in text
    assert "run-local" in _all_markdown().lower()
    assert "does not execute satscan" in _all_markdown().lower()


def test_notebook_contains_required_scientific_narrative() -> None:
    text = _all_markdown().lower()
    required = (
        "modifiable-areal-unit",
        "gini",
        "circular",
        "queen",
        "local moran",
        "sen’s slope",
        "romano–tirlea",
        "studentized global mann–kendall",
        "benjamini–hochberg",
        "viirs-positive",
        "firth-type pgee",
        "working independence",
        "morel–bokossa–neerchal",
        "standard-normal wald",
        "space-time permutation",
        "ground truth",
    )
    for phrase in required:
        assert phrase in text, phrase


def test_prohibited_scientific_routes_are_not_active_in_code() -> None:
    code = _all_code().lower()
    forbidden = (
        "log1p",
        "fourier",
        "minimum_cic",
        "qic",
        "exchangeable",
        "calendar_gap",
        "three_system",
        "nine_scenario",
        "area_poisson",
        "recurrence_score",
        "stability_score",
    )
    for token in forbidden:
        assert token not in code


def test_no_stale_publication_id_prefixes() -> None:
    text = "\n".join(_source(c) for c in _nb().cells)
    for token in ("F_RQ", "FS_RQ", "T_RQ"):
        assert token not in text


def test_no_manual_assignment_into_governed_dataframes() -> None:
    code = _all_code()
    # The canonical notebook may bind names and create summaries, but it must not
    # mutate source authorities via indexed assignment.
    assert re.search(r"\b(authorities|rq1|rq2|rq3)\.[A-Za-z_]+\s*\[.*\]\s*=", code) is None
    assert re.search(r"\b(authorities|rq1|rq2|rq3)\.[A-Za-z_]+\.(loc|iloc|at|iat)\s*\[.*\]\s*=", code) is None


def test_notebook_uses_atomic_output_and_provenance_services() -> None:
    code = _all_code()
    assert "OutputWriter" in code
    assert "RunProvenance" in code
    assert "export_realised_configuration" in code
    assert "artefact_registry" in code


def test_final_gate_requires_rq2_production_and_preserves_external_secondary_state() -> None:
    code = _all_code().replace(" ", "")
    assert 'scaffold_gate==rq1_gate==rq2_gate==rq3_gate==secondary_gate=="PASS"' in code
    assert 'publication_gate=="PASS"' in code
    assert 'final_run_gate="PASS"' in code
    assert "secondary_integration.execution_statein{EXTERNAL_RESULTS_REQUIRED,RESULTS_VALIDATED}" in code

def test_notebook_starts_clean_without_embedded_outputs() -> None:
    nb = _nb()
    for cell in nb.cells:
        if cell.cell_type == "code":
            assert cell.execution_count is None
            assert cell.outputs == []


def test_optional_satscan_cell_remains_thin_orchestration() -> None:
    nb = _nb()
    cell = next(
        nb.cells[i + 1]
        for i, item in enumerate(nb.cells[:-1])
        if item.cell_type == "markdown" and item.source.startswith("### 04-02")
    )
    code = _source(cell)
    assert cell.cell_type == "code"
    assert "validate_and_integrate_satscan_results_if_available(" in code
    assert len(code.splitlines()) <= 8
    forbidden = ("parse_cluster_file", "parse_membership_file", "sha256_file", "subprocess", "SaTScan.exe", "Program Files")
    assert not any(token in code for token in forbidden)
