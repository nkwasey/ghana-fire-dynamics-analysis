from __future__ import annotations

import ast
import hashlib
import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_configuration_bundle

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"
FIVE_CONTRACTS = (
    "analysis_contract.yml",
    "data_schema_contract.yml",
    "method_authorities.yml",
    "output_contract.yml",
    "figure_contract.yml",
)
PUBLICATION_PYTHON = (
    "registers.py", "presentation.py", "publication.py", "figures.py", "mapping.py", "outputs.py"
)


def _copy_project_config(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    shutil.copytree(CONFIG, root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    return root / "config"


def _mutate(path: Path, fn) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def test_exact_five_contracts_load_and_hash() -> None:
    bundle = load_configuration_bundle(CONFIG)
    assert tuple(sorted(bundle.file_hashes)) == tuple(sorted(FIVE_CONTRACTS))
    for name in FIVE_CONTRACTS:
        assert bundle.file_hashes[name] == hashlib.sha256((CONFIG / name).read_bytes()).hexdigest()
    expected = hashlib.sha256(
        json.dumps(dict(sorted(bundle.file_hashes.items())), separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert bundle.configuration_sha256 == expected


def test_bundle_is_deeply_immutable() -> None:
    bundle = load_configuration_bundle(CONFIG)
    with pytest.raises(FrozenInstanceError):
        bundle.package_version = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        bundle.analysis.study["acz_count"] = 999  # type: ignore[index]


def test_unknown_method_and_invalid_field_are_rejected(tmp_path: Path) -> None:
    config = _copy_project_config(tmp_path)
    _mutate(config / "analysis_contract.yml", lambda raw: raw["research_questions"]["rq3"].__setitem__("estimator", "os.system"))
    with pytest.raises(ConfigurationError, match="Study methods missing"):
        load_configuration_bundle(config)

    config = _copy_project_config(tmp_path / "second")
    _mutate(config / "analysis_contract.yml", lambda raw: raw["field_roles"]["rq3"].__setitem__("ba_presence", "field_that_does_not_exist"))
    with pytest.raises(ConfigurationError, match="field_that_does_not_exist"):
        load_configuration_bundle(config)


def test_study_output_ids_are_config_owned_not_literal_python_registry_authority() -> None:
    bundle = load_configuration_bundle(CONFIG)
    configured_ids = {x.output_id for x in bundle.output.tables} | {x.figure_id for x in bundle.figure.figures}
    for name in PUBLICATION_PYTHON:
        path = SUBPROJECT / "src/rp1_analysis_v1" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        literals = {
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        overlap = configured_ids.intersection(literals)
        assert not overlap, (name, sorted(overlap))


def test_valid_output_id_mutation_requires_no_python_change(tmp_path: Path) -> None:
    config = _copy_project_config(tmp_path)
    before = {
        p.relative_to(SUBPROJECT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (SUBPROJECT / "src").rglob("*.py")
    }
    def mutate(raw):
        raw["publication_outputs"]["tables"][0]["id"] = "T1_CONFIG_MUTATION"
        raw["publication_outputs"]["tables"][0]["family_id"] = "T1_CONFIG_MUTATION"
    _mutate(config / "output_contract.yml", mutate)
    bundle = load_configuration_bundle(config)
    assert bundle.output.tables[0].output_id == "T1_CONFIG_MUTATION"
    after = {
        p.relative_to(SUBPROJECT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (SUBPROJECT / "src").rglob("*.py")
    }
    assert before == after


def _constants_in_function(path: Path, function_name: str) -> set[object]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    return {node.value for node in ast.walk(function) if isinstance(node, ast.Constant)}


def test_runtime_validation_does_not_reown_configured_or_realised_study_literals() -> None:
    integration = SUBPROJECT / "src/rp1_analysis_v1/integration.py"
    publication = SUBPROJECT / "src/rp1_analysis_v1/publication.py"

    integration_constants = _constants_in_function(integration, "validate_canonical_integration")
    publication_constants = _constants_in_function(publication, "_registry_authorities")

    # Exact current output identities belong to the output/figure contracts, not the runtime validator.
    assert not {"T1", "T2", "T3", "F2", "F3", "F4", "F5", "F6", "S1", "S2", "S3", "S4", "S5", "S6"}.intersection(integration_constants)
    # The 31-column RQ3 design and 24-year RQ2 length are realised/config-derived quantities.
    assert 31 not in integration_constants
    assert 24 not in publication_constants
