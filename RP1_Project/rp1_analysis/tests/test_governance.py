from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml
from rp1_analysis_v1.config import (
    ConfigurationError,
    export_realised_configuration,
    load_analysis_contract,
    load_configuration_bundle,
    load_output_contract,
)
from rp1_analysis_v1.design import assert_execution_ready
from rp1_analysis_v1.outputs import OutputPolicyError, OutputWriter, stable_filename
from rp1_analysis_v1.paths import PathIsolationError, ProjectPaths, discover_subproject_root
from rp1_analysis_v1.provenance import RunProvenance, sha256_file
from rp1_analysis_v1.variables import resolve_field_role

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"
DISTRICT_PANEL = SUBPROJECT / "data/raw/fire_panel_district_monthly_consolidated_2001_2024.csv"


def _copy_configs(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "config"
    shutil.copytree(CONFIG, target)
    shutil.copy2(SUBPROJECT / "pyproject.toml", destination / "pyproject.toml")
    return target


def _mutate_yaml(path: Path, mutate) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _temp_run(tmp_path: Path):
    config_dir = _copy_configs(tmp_path / "root")
    contract = load_output_contract(config_dir / "output_contract.yml")
    run = tmp_path / "run"
    run.mkdir()
    for section in contract.sections:
        (run / section).mkdir()
    return run, contract


def test_valid_configuration_bundle_loads() -> None:
    bundle = load_configuration_bundle(CONFIG)
    assert bundle.analysis.schema_version == "rp1-analysis-v1.1"
    assert bundle.data_schema.data_schema_version == "rp1-data-schema-v1.1"
    assert len(bundle.file_hashes) == 5
    assert len(bundle.configuration_sha256) == 64


def test_invalid_schema_is_rejected(tmp_path: Path) -> None:
    config_dir = _copy_configs(tmp_path)
    _mutate_yaml(
        config_dir / "analysis_contract.yml",
        lambda raw: raw.__setitem__("schema_version", "rp1-analysis-v9"),
    )
    with pytest.raises(ConfigurationError, match="Unsupported schema_version"):
        load_analysis_contract(config_dir / "analysis_contract.yml")


def test_unknown_method_is_rejected(tmp_path: Path) -> None:
    config_dir = _copy_configs(tmp_path)

    def mutate(raw):
        raw["research_questions"]["rq3"]["estimator"] = "arbitrary_python_function"

    _mutate_yaml(config_dir / "analysis_contract.yml", mutate)
    with pytest.raises(ConfigurationError, match="Study methods missing|prohibited"):
        load_configuration_bundle(config_dir)


def test_unregistered_rq2_method_mutation_is_rejected(tmp_path: Path) -> None:
    config_dir = _copy_configs(tmp_path)

    def mutate(raw):
        raw["research_questions"]["rq2"]["inferential_test"]["method"] = "unregistered_rq2_method"

    _mutate_yaml(config_dir / "analysis_contract.yml", mutate)
    with pytest.raises(ConfigurationError, match="Study methods missing|prohibited"):
        load_configuration_bundle(config_dir)


def test_configuration_hash_is_deterministic_and_byte_sensitive(tmp_path: Path) -> None:
    original_a = load_configuration_bundle(CONFIG)
    original_b = load_configuration_bundle(CONFIG)
    assert original_a.configuration_sha256 == original_b.configuration_sha256
    copied = _copy_configs(tmp_path)
    _mutate_yaml(
        copied / "analysis_contract.yml",
        lambda raw: raw["research_questions"]["rq1"]["spatial"]["global"].__setitem__(
            "permutations", int(raw["research_questions"]["rq1"]["spatial"]["global"]["permutations"]) + 2
        ),
    )
    mutated = load_configuration_bundle(copied)
    assert mutated.configuration_sha256 != original_a.configuration_sha256
    assert mutated.file_hashes["analysis_contract.yml"] != original_a.file_hashes["analysis_contract.yml"]


def test_configuration_is_immutable() -> None:
    bundle = load_configuration_bundle(CONFIG)
    with pytest.raises(TypeError):
        bundle.analysis.study["acz_count"] = 4  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        bundle.analysis.schema_version = "other"  # type: ignore[misc]
    assert isinstance(bundle.analysis.research_questions["rq3"]["predictors"], tuple)


def test_governed_execution_parameters_are_semantically_ready() -> None:
    bundle = load_configuration_bundle(CONFIG)
    analysis = bundle.analysis.to_dict()
    assert_execution_ready(analysis, bundle.methods, "rq1")
    assert_execution_ready(analysis, bundle.methods, "rq2")
    assert_execution_ready(analysis, bundle.methods, "rq3")


def test_rq3_governed_fields_exist_in_district_panel() -> None:
    contract = load_configuration_bundle(CONFIG).analysis
    rq3 = contract.research_questions["rq3"]
    with DISTRICT_PANEL.open(newline="", encoding="utf-8-sig") as handle:
        header = set(next(csv.reader(handle)))
    required = {
        str(resolve_field_role(contract, contract.study["populations"]["rq3_model"]["positive_role"])),
        str(resolve_field_role(contract, rq3["outcome"]["burned_area_presence_role"])),
        str(resolve_field_role(contract, rq3["cluster"]["id_role"])),
    }
    for item in (*rq3["predictors"], *rq3["factors"]):
        required.add(str(resolve_field_role(contract, item["field_role"])))
    assert required.issubset(header)


def test_root_discovery_from_package_location_ignores_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("RP1_ANALYSIS_V1_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert discover_subproject_root() == SUBPROJECT.resolve()


def test_root_discovery_works_at_arbitrary_extraction_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RP1_ANALYSIS_V1_ROOT", raising=False)
    root = tmp_path / "a folder" / "deep" / "rp1_analysis_v1"
    (root / "config").mkdir(parents=True)
    (root / "src/rp1_analysis_v1").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    for name in (
        "analysis_contract.yml",
        "data_schema_contract.yml",
        "method_authorities.yml",
        "output_contract.yml",
        "figure_contract.yml",
        "execution_contract.yml",
        "qualification_contract.yml",
    ):
        (root / "config" / name).write_text("x: 1\n", encoding="utf-8")
    (root / "src/rp1_analysis_v1/__init__.py").write_text("", encoding="utf-8")
    nested = root / "data" / "raw"
    nested.mkdir(parents=True)
    assert discover_subproject_root(nested) == root.resolve()


def test_environment_root_override_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RP1_ANALYSIS_V1_ROOT", str(tmp_path))
    with pytest.raises(PathIsolationError, match="does not identify"):
        discover_subproject_root()


def test_path_escape_and_absolute_path_are_rejected() -> None:
    paths = ProjectPaths(SUBPROJECT.resolve())
    with pytest.raises(PathIsolationError):
        paths.resolve_inside("../escape.txt")
    with pytest.raises(PathIsolationError):
        paths.resolve_inside(Path("/tmp/escape.txt"))


def test_create_run_builds_governed_sections_and_latest_pointer(tmp_path: Path) -> None:
    root = tmp_path / "portable_root"
    root.mkdir()
    shutil.copytree(CONFIG, root / "config")
    paths = ProjectPaths(root)
    run = paths.create_run("test_run_001")
    contract = load_output_contract(root / "config/output_contract.yml")
    assert sorted(p.name for p in run.iterdir() if p.is_dir()) == sorted(contract.sections)
    assert paths.read_latest_run() == run.resolve()
    assert (root / "out/latest_run").read_text(encoding="utf-8") == "out/runs/test_run_001\n"
    with pytest.raises(FileExistsError):
        paths.create_run("test_run_001")


def test_invalid_run_id_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(CONFIG, root / "config")
    with pytest.raises(PathIsolationError, match="Invalid run_id"):
        ProjectPaths(root).create_run("../escape")


def test_stable_output_filename_is_deterministic() -> None:
    assert stable_filename("rq1_table_01.csv") == "rq1_table_01.csv"
    assert stable_filename("rq1_table_01.csv") == "rq1_table_01.csv"
    for bad in ("../x.csv", "a b.csv", "", "/tmp/x.csv"):
        with pytest.raises(OutputPolicyError):
            stable_filename(bad)


def test_atomic_text_and_json_writes_leave_no_temp_files(tmp_path: Path) -> None:
    run, contract = _temp_run(tmp_path)
    writer = OutputWriter(run, contract)
    text_record = writer.write_text("00_scaffold/note.txt", "a\r\nb\r\n")
    json_record = writer.write_json("00_scaffold/value.json", {"b": 2, "a": 1})
    assert (run / text_record.path).read_bytes() == b"a\nb\n"
    assert (run / json_record.path).read_text(encoding="utf-8").startswith('{\n  "a": 1,')
    assert not list(run.rglob("*.tmp"))


def test_output_collision_is_protected(tmp_path: Path) -> None:
    run, contract = _temp_run(tmp_path)
    writer = OutputWriter(run, contract)
    writer.write_text("00_scaffold/collision.txt", "first\n")
    with pytest.raises(FileExistsError):
        writer.write_text("00_scaffold/collision.txt", "second\n")
    assert (run / "00_scaffold/collision.txt").read_text(encoding="utf-8") == "first\n"


def test_outputs_cannot_escape_or_bypass_governed_sections(tmp_path: Path) -> None:
    run, contract = _temp_run(tmp_path)
    writer = OutputWriter(run, contract)
    with pytest.raises(OutputPolicyError):
        writer.write_text("../escape.txt", "x")
    with pytest.raises(OutputPolicyError, match="governed run section"):
        writer.write_text("rogue/file.txt", "x")


def test_csv_contract_column_order_and_hash_are_deterministic(tmp_path: Path) -> None:
    run, contract = _temp_run(tmp_path)
    writer = OutputWriter(run, contract)
    rows = [{"size_bytes": 2, "path": "b", "mtime_ns": 4, "sha256": "c"}]
    first = writer.write_csv(
        "00_scaffold/input_inventory.csv",
        rows,
        contract_column_order="provenance_input_inventory",
    )
    text = (run / first.path).read_text(encoding="utf-8")
    assert text.splitlines()[0] == "path,sha256,size_bytes,mtime_ns"
    second_run = tmp_path / "run2"
    second_run.mkdir()
    for section in contract.sections:
        (second_run / section).mkdir()
    second = OutputWriter(second_run, contract).write_csv(
        "00_scaffold/input_inventory.csv",
        rows,
        contract_column_order="provenance_input_inventory",
    )
    assert first.sha256 == second.sha256
    assert (run / first.path).read_bytes() == (second_run / second.path).read_bytes()


def test_provenance_manifest_contains_required_content(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    shutil.copytree(CONFIG, root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    input_file = root / "input.txt"
    input_file.write_text("input\n", encoding="utf-8")
    provenance = RunProvenance(
        run_id="run_001",
        project_root=root,
        configuration_sha256="a" * 64,
        input_paths=[input_file],
    )
    provenance.finish()
    manifest = provenance.manifest()
    assert manifest["configuration_sha256"] == "a" * 64
    assert manifest["inputs"][0]["sha256"] == sha256_file(input_file)
    assert {"python", "platform", "packages", "git_commit"}.issubset(manifest["environment"])
    assert manifest["started_at_utc"].endswith("Z")
    assert manifest["ended_at_utc"].endswith("Z")
    out = provenance.write_manifest(root / "manifest.json")
    assert json.loads(out.read_text(encoding="utf-8"))["run_id"] == "run_001"


def test_realised_configuration_export_is_run_scoped_and_hash_matches(tmp_path: Path) -> None:
    bundle = load_configuration_bundle(CONFIG)
    run, _ = _temp_run(tmp_path)
    exported = export_realised_configuration(bundle, run)
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert exported.parent.name == "00_scaffold"
    assert payload["configuration_sha256"] == bundle.configuration_sha256
    with pytest.raises(FileExistsError):
        export_realised_configuration(bundle, run)


def test_scientific_csv_bytes_do_not_depend_on_provenance_timestamps(tmp_path: Path) -> None:
    run, contract = _temp_run(tmp_path)
    rows = [{"unit": "A", "estimate": 1.25}]
    first = OutputWriter(run, contract).write_csv(
        "01_rq1_spatial_scale/result.csv", rows, columns=("unit", "estimate")
    )
    other = tmp_path / "other"
    other.mkdir()
    for section in contract.sections:
        (other / section).mkdir()
    second = OutputWriter(other, contract).write_csv(
        "01_rq1_spatial_scale/result.csv", rows, columns=("unit", "estimate")
    )
    assert first.sha256 == second.sha256
    assert hashlib.sha256((run / first.path).read_bytes()).hexdigest() == first.sha256


def test_all_hashed_inputs_are_exposed_and_stay_within_root() -> None:
    paths = ProjectPaths(SUBPROJECT.resolve())
    governed = paths.all_hashed_inputs
    assert len(governed) == 15
    assert all(path.is_file() for path in governed)
    assert all(path.is_relative_to(SUBPROJECT.resolve()) for path in governed)


def test_unknown_scientific_field_is_rejected(tmp_path: Path) -> None:
    config_dir = _copy_configs(tmp_path)

    def mutate(raw):
        raw["research_questions"]["rq1"]["invented_setting"] = True

    _mutate_yaml(config_dir / "analysis_contract.yml", mutate)
    with pytest.raises(ConfigurationError, match="Unknown scientific fields"):
        load_analysis_contract(config_dir / "analysis_contract.yml")


def test_invalid_figure_enum_is_rejected(tmp_path: Path) -> None:
    config_dir = _copy_configs(tmp_path)
    _mutate_yaml(
        config_dir / "figure_contract.yml",
        lambda raw: raw["map_layout"]["legend"].__setitem__("position", "inside"),
    )
    with pytest.raises(ConfigurationError, match="legend.position"):
        load_configuration_bundle(config_dir)


def test_output_contract_path_traversal_is_rejected(tmp_path: Path) -> None:
    config_dir = _copy_configs(tmp_path)
    _mutate_yaml(
        config_dir / "output_contract.yml",
        lambda raw: raw.__setitem__("run_root", "../outside"),
    )
    with pytest.raises(ConfigurationError, match="stay within"):
        load_output_contract(config_dir / "output_contract.yml")
