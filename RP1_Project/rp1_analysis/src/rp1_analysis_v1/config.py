"""Single-source, typed and immutable configuration loading for RP1 Analysis."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, cast

import yaml

from .contracts import (
    AnalysisContract,
    ConfigurationBundle,
    ExecutionCloseoutContract,
    ExecutionModeContract,
    RQ1SpatialParameters,
    RQ2TrendParameters,
    RQ3ModelParameters,
    SaTScanParameters,
    RealisedRunMetadata,
    DataFieldSpec,
    DataSchemaContract,
    PanelSpecification,
    GeometrySpecification,
    RelationshipSpecification,
    FigureContract,
    CircularMeanMonthDisplayContract,
    DisplayConventionsContract,
    FigureSpecificationContract,
    GridCellContract,
    GridLayoutContract,
    PublicationCanvasContract,
    PublicationGeometryContract,
    PresentationExportRegistryContract,
    PresentationExportSpecificationContract,
    PresentationGeometryDependencyContract,
    PresentationManifestContract,
    PresentationOutputPolicyContract,
    PresentationRunFamilyContract,
    PresentationSourceContract,
    SemanticStateStyleContract,
    SemanticStylesContract,
    MethodAuthorityContract,
    MethodAuthoritySpec,
    OutputContract,
    OutputSpecification,
    SecondaryOutputSpecification,
    QualificationBuildContract,
    QualificationContract,
    QualificationEvidenceContract,
    QualificationImportContract,
    QualificationPackageContract,
    QualificationProjectionContract,
    QualificationRepositoryContract,
    GeneratedArtifactContract,
    freeze,
    thaw,
)
from .design import DesignValidationError, validate_analysis_design, validate_configuration_semantics
from .variables import resolve_field_role

SCHEMA_VERSION = "rp1-analysis-v1.1"
DATA_SCHEMA_VERSION = "rp1-data-schema-v1.1"
EXECUTION_CONTRACT_FILENAME = "execution_contract.yml"
QUALIFICATION_CONTRACT_FILENAME = "qualification_contract.yml"

CONFIG_FILENAMES = (
    "analysis_contract.yml",
    "data_schema_contract.yml",
    "method_authorities.yml",
    "output_contract.yml",
    "figure_contract.yml",
)
_SUPPORTED_SCHEMAS = {SCHEMA_VERSION}


class ConfigurationError(ValueError):
    """Raised for invalid, incomplete or unsupported configuration."""


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Unable to load YAML configuration {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"Configuration must be a YAML mapping: {path}")
    return cast(dict[str, Any], loaded)


def _validate_schema(raw: Mapping[str, Any], source: Path) -> None:
    schema = raw.get("schema_version")
    if schema is None:
        raise ConfigurationError(f"Missing required field schema_version in {source.name}")
    if schema not in _SUPPORTED_SCHEMAS:
        raise ConfigurationError(
            f"Unsupported schema_version {schema!r} in {source.name}; "
            f"supported: {sorted(_SUPPORTED_SCHEMAS)!r}"
        )


def _require_keys(
    raw: Mapping[str, Any],
    required: set[str],
    context: str,
    *,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required.difference(raw)
    if missing:
        raise ConfigurationError(f"Missing required fields in {context}: {sorted(missing)!r}")
    unknown = set(raw).difference(required | optional)
    if unknown:
        raise ConfigurationError(f"Unknown fields in {context}: {sorted(unknown)!r}")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        thaw(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_realised_configuration(value: Any) -> str:
    """Return deterministic SHA-256 for a realised configuration object."""

    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def configuration_file_hashes(config_dir: str | Path) -> Mapping[str, str]:
    root = Path(config_dir).resolve()
    hashes: dict[str, str] = {}
    for filename in CONFIG_FILENAMES:
        path = root / filename
        if not path.is_file():
            raise ConfigurationError(f"Missing required configuration contract: {path}")
        hashes[filename] = sha256_file(path)
    return MappingProxyType(hashes)


def aggregate_configuration_sha256(file_hashes: Mapping[str, str]) -> str:
    """Hash the ordered filename->raw-file-hash authority."""

    if set(file_hashes) != set(CONFIG_FILENAMES):
        raise ConfigurationError("Aggregate configuration hash requires exactly the five contracts")
    payload = {name: file_hashes[name] for name in CONFIG_FILENAMES}
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def operational_configuration_file_hashes(config_dir: str | Path) -> Mapping[str, str]:
    """Return hashes for non-scientific operational contracts.

    These hashes are deliberately separate from the frozen five-contract
    scientific aggregate so operational completion policy can evolve without
    re-identifying the study design.
    """

    root = Path(config_dir).resolve()
    path = root / EXECUTION_CONTRACT_FILENAME
    if not path.is_file():
        raise ConfigurationError(f"Missing required operational configuration contract: {path}")
    return MappingProxyType({EXECUTION_CONTRACT_FILENAME: sha256_file(path)})


def aggregate_operational_configuration_sha256(file_hashes: Mapping[str, str]) -> str:
    expected = {EXECUTION_CONTRACT_FILENAME}
    if set(file_hashes) != expected:
        raise ConfigurationError("Operational configuration hash requires exactly execution_contract.yml")
    return hashlib.sha256(_canonical_json_bytes(dict(file_hashes))).hexdigest()



def qualification_configuration_file_hashes(config_dir: str | Path) -> Mapping[str, str]:
    """Return the raw-file identity of the source-qualification contract."""

    root = Path(config_dir).resolve()
    path = root / QUALIFICATION_CONTRACT_FILENAME
    if not path.is_file():
        raise ConfigurationError(f"Missing required qualification configuration contract: {path}")
    return MappingProxyType({QUALIFICATION_CONTRACT_FILENAME: sha256_file(path)})


def aggregate_qualification_configuration_sha256(file_hashes: Mapping[str, str]) -> str:
    expected = {QUALIFICATION_CONTRACT_FILENAME}
    if set(file_hashes) != expected:
        raise ConfigurationError(
            "Qualification configuration hash requires exactly qualification_contract.yml"
        )
    return hashlib.sha256(_canonical_json_bytes(dict(file_hashes))).hexdigest()


def _require_unique_strings(value: Any, context: str, *, non_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (non_empty and not value):
        raise ConfigurationError(f"{context} must be {'a non-empty ' if non_empty else ''}list")
    if not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError(f"{context} must contain non-empty strings")
    if len(set(value)) != len(value):
        raise ConfigurationError(f"{context} must not contain duplicates")
    return tuple(value)


def _qualification_relative_path(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{context} must be a non-empty repository-relative path")
    path = Path(value)
    windows_path = PureWindowsPath(value)
    if path.is_absolute() or windows_path.is_absolute() or windows_path.drive or ".." in path.parts or ".." in windows_path.parts:
        raise ConfigurationError(f"{context} must be repository-relative without parent traversal")
    if "\\" in value:
        raise ConfigurationError(f"{context} must use portable repository-relative separators")
    normalised = path.as_posix()
    if normalised in {"", "."}:
        raise ConfigurationError(f"{context} must identify a concrete repository member")
    return normalised


def load_qualification_contract(path: str | Path) -> QualificationContract:
    """Load and strictly validate the operational source-qualification policy."""

    source = Path(path).resolve()
    raw = _load_yaml(source)
    _require_keys(
        raw,
        {
            "schema_version", "contract_id", "repository", "packages",
            "generated_artifacts", "projection", "imports", "evidence", "build",
        },
        source.name,
    )
    if raw["schema_version"] != "rp1-qualification-contract-v1":
        raise ConfigurationError(f"Unsupported qualification contract schema: {raw['schema_version']!r}")
    if raw["contract_id"] != "rp1-source-qualification-v1":
        raise ConfigurationError(f"Unsupported qualification contract identity: {raw['contract_id']!r}")

    repository = raw["repository"]
    if not isinstance(repository, Mapping):
        raise ConfigurationError("qualification.repository must be a mapping")
    _require_keys(
        repository,
        {
            "include_roots", "paths_must_be_repository_relative",
            "forbid_parent_traversal", "forbid_symlinks",
        },
        "qualification.repository",
    )
    include_roots = tuple(
        _qualification_relative_path(item, f"qualification.repository.include_roots[{idx}]")
        for idx, item in enumerate(_require_unique_strings(repository["include_roots"], "qualification.repository.include_roots"))
    )
    for flag in ("paths_must_be_repository_relative", "forbid_parent_traversal", "forbid_symlinks"):
        if repository[flag] is not True:
            raise ConfigurationError(f"qualification.repository.{flag} must be true")

    packages_raw = raw["packages"]
    if not isinstance(packages_raw, list) or not packages_raw:
        raise ConfigurationError("qualification.packages must be a non-empty list")
    packages: list[QualificationPackageContract] = []
    modules: set[str] = set()
    distributions: set[str] = set()
    for idx, item in enumerate(packages_raw):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"qualification.packages[{idx}] must be a mapping")
        _require_keys(item, {"module", "distribution", "project_root", "source_root"}, f"qualification.packages[{idx}]")
        module = item["module"]
        distribution = item["distribution"]
        if not isinstance(module, str) or not module or not isinstance(distribution, str) or not distribution:
            raise ConfigurationError(f"qualification.packages[{idx}] module/distribution must be non-empty strings")
        if module in modules or distribution in distributions:
            raise ConfigurationError("qualification package modules and distributions must be unique")
        modules.add(module)
        distributions.add(distribution)
        project_root = _qualification_relative_path(item["project_root"], f"qualification.packages[{idx}].project_root")
        source_root = _qualification_relative_path(item["source_root"], f"qualification.packages[{idx}].source_root")
        project_path = Path(project_root)
        source_path = Path(source_root)
        try:
            source_path.relative_to(project_path)
        except ValueError as exc:
            raise ConfigurationError(
                f"qualification.packages[{idx}].source_root must lie within project_root"
            ) from exc
        packages.append(QualificationPackageContract(module, distribution, project_root, source_root))

    generated = raw["generated_artifacts"]
    if not isinstance(generated, Mapping):
        raise ConfigurationError("qualification.generated_artifacts must be a mapping")
    _require_keys(
        generated,
        {"directory_names", "directory_suffixes", "file_suffixes", "file_names", "policy"},
        "qualification.generated_artifacts",
    )
    directory_names = _require_unique_strings(generated["directory_names"], "qualification.generated_artifacts.directory_names")
    directory_suffixes = _require_unique_strings(generated["directory_suffixes"], "qualification.generated_artifacts.directory_suffixes")
    file_suffixes = _require_unique_strings(generated["file_suffixes"], "qualification.generated_artifacts.file_suffixes")
    file_names = _require_unique_strings(generated["file_names"], "qualification.generated_artifacts.file_names")
    policy = generated["policy"]
    if not isinstance(policy, str) or not policy:
        raise ConfigurationError("qualification.generated_artifacts.policy must be a non-empty string")

    projection = raw["projection"]
    if not isinstance(projection, Mapping):
        raise ConfigurationError("qualification.projection must be a mapping")
    _require_keys(
        projection,
        {
            "root_policy", "fresh_recreate_each_run", "governed_set", "pre_copy_inventory",
            "post_copy_exact_inventory_comparison", "unexpected_omission", "hash_or_size_mismatch",
            "clean_projection_subdirectory", "allowed_temporary_subdirectories",
        },
        "qualification.projection",
    )
    if projection["root_policy"] != "external_to_repository":
        raise ConfigurationError("qualification.projection.root_policy must be external_to_repository")
    if projection["fresh_recreate_each_run"] is not True or projection["post_copy_exact_inventory_comparison"] is not True:
        raise ConfigurationError("qualification projection must require fresh recreation and exact post-copy comparison")
    if projection["governed_set"] != "all_regular_files_under_include_roots_after_generated_exclusions":
        raise ConfigurationError("Unsupported qualification.projection.governed_set")
    if projection["pre_copy_inventory"] != "sha256_and_size_required":
        raise ConfigurationError("qualification.projection.pre_copy_inventory must require SHA-256 and size")
    if projection["unexpected_omission"] != "FAIL" or projection["hash_or_size_mismatch"] != "FAIL":
        raise ConfigurationError("qualification projection mismatch policies must be FAIL")
    clean_projection_subdirectory = _qualification_relative_path(
        projection["clean_projection_subdirectory"], "qualification.projection.clean_projection_subdirectory"
    )
    if "/" in clean_projection_subdirectory:
        raise ConfigurationError("clean_projection_subdirectory must be a single directory name")
    allowed_temporary_subdirectories = tuple(
        _qualification_relative_path(item, f"qualification.projection.allowed_temporary_subdirectories[{idx}]")
        for idx, item in enumerate(_require_unique_strings(
            projection["allowed_temporary_subdirectories"],
            "qualification.projection.allowed_temporary_subdirectories",
        ))
    )
    if clean_projection_subdirectory not in allowed_temporary_subdirectories:
        raise ConfigurationError("clean projection subdirectory must be in allowed temporary subdirectories")
    if any("/" in item for item in allowed_temporary_subdirectories):
        raise ConfigurationError("allowed temporary subdirectories must be single directory names")

    imports = raw["imports"]
    if not isinstance(imports, Mapping):
        raise ConfigurationError("qualification.imports must be a mapping")
    _require_keys(imports, {"operational_mode", "projected_mode", "isolated_mode", "wrong_origin"}, "qualification.imports")
    expected_imports = {
        "operational_mode": "verify_operational_checkout_source_roots",
        "projected_mode": "explicit_projected_pythonpath_with_origin_probe",
        "isolated_mode": "verify_isolated_install_target",
        "wrong_origin": "FAIL",
    }
    for key, expected in expected_imports.items():
        if imports[key] != expected:
            raise ConfigurationError(f"qualification.imports.{key} must be {expected!r}")

    evidence = raw["evidence"]
    if not isinstance(evidence, Mapping):
        raise ConfigurationError("qualification.evidence must be a mapping")
    _require_keys(
        evidence,
        {"must_be_external_to_operational_repository", "logs_must_be_outside_clean_projection", "stale_runtime_removed_before_run", "evidence_subdirectory"},
        "qualification.evidence",
    )
    for flag in ("must_be_external_to_operational_repository", "logs_must_be_outside_clean_projection", "stale_runtime_removed_before_run"):
        if evidence[flag] is not True:
            raise ConfigurationError(f"qualification.evidence.{flag} must be true")
    evidence_subdirectory = _qualification_relative_path(evidence["evidence_subdirectory"], "qualification.evidence.evidence_subdirectory")
    if "/" in evidence_subdirectory:
        raise ConfigurationError("qualification.evidence.evidence_subdirectory must be a single directory name")

    build = raw["build"]
    if not isinstance(build, Mapping):
        raise ConfigurationError("qualification.build must be a mapping")
    _require_keys(build, {"wheel_sources", "build_isolation_policy", "isolated_install_target"}, "qualification.build")
    expected_build = {
        "wheel_sources": "clean_projected_project_roots",
        "build_isolation_policy": "product_declared_no_stale_wheels",
        "isolated_install_target": "fresh_external_runtime_target",
    }
    for key, expected in expected_build.items():
        if build[key] != expected:
            raise ConfigurationError(f"qualification.build.{key} must be {expected!r}")

    return QualificationContract(
        schema_version=str(raw["schema_version"]),
        contract_id=str(raw["contract_id"]),
        repository=QualificationRepositoryContract(
            include_roots=include_roots,
            paths_must_be_repository_relative=True,
            forbid_parent_traversal=True,
            forbid_symlinks=True,
        ),
        packages=tuple(packages),
        generated_artifacts=GeneratedArtifactContract(
            directory_names=directory_names,
            directory_suffixes=directory_suffixes,
            file_suffixes=file_suffixes,
            file_names=file_names,
            policy=policy,
        ),
        projection=QualificationProjectionContract(
            root_policy=str(projection["root_policy"]),
            fresh_recreate_each_run=True,
            governed_set=str(projection["governed_set"]),
            pre_copy_inventory=str(projection["pre_copy_inventory"]),
            post_copy_exact_inventory_comparison=True,
            unexpected_omission="FAIL",
            hash_or_size_mismatch="FAIL",
            clean_projection_subdirectory=clean_projection_subdirectory,
            allowed_temporary_subdirectories=allowed_temporary_subdirectories,
        ),
        imports=QualificationImportContract(
            operational_mode=str(imports["operational_mode"]),
            projected_mode=str(imports["projected_mode"]),
            isolated_mode=str(imports["isolated_mode"]),
            wrong_origin="FAIL",
        ),
        evidence=QualificationEvidenceContract(
            must_be_external_to_operational_repository=True,
            logs_must_be_outside_clean_projection=True,
            stale_runtime_removed_before_run=True,
            evidence_subdirectory=evidence_subdirectory,
        ),
        build=QualificationBuildContract(
            wheel_sources=str(build["wheel_sources"]),
            build_isolation_policy=str(build["build_isolation_policy"]),
            isolated_install_target=str(build["isolated_install_target"]),
        ),
    )

def load_execution_contract(path: str | Path) -> ExecutionCloseoutContract:
    """Load the package-owned run execution/closeout policy.

    This contract is operational, not scientific: the scientific schema and the
    five-contract scientific configuration hash remain unchanged.
    """

    source = Path(path).resolve()
    raw = _load_yaml(source)
    _require_keys(
        raw,
        {"schema_version", "contract_id", "closeout", "secondary_completion", "validation", "modes"},
        source.name,
    )
    if raw["schema_version"] != "rp1-execution-contract-v1":
        raise ConfigurationError(f"Unsupported execution contract schema: {raw['schema_version']!r}")
    if raw["contract_id"] != "rp1-run-completion-v1":
        raise ConfigurationError(f"Unsupported execution contract identity: {raw['contract_id']!r}")

    closeout = raw["closeout"]
    if not isinstance(closeout, Mapping):
        raise ConfigurationError("execution.closeout must be a mapping")
    _require_keys(closeout, {"section", "artifact_roles", "required_final_gate", "execution_record_schema"}, "execution.closeout")
    section = _validate_relative_config_path(closeout["section"], "execution.closeout.section")
    if "/" in section:
        raise ConfigurationError("execution.closeout.section must be a single governed section name")
    artifact_roles = closeout["artifact_roles"]
    if not isinstance(artifact_roles, Mapping) or not artifact_roles:
        raise ConfigurationError("execution.closeout.artifact_roles must be a non-empty mapping")
    required_roles = {"canonical_gate", "reproducibility_manifest", "execution_record", "executed_notebook"}
    if set(artifact_roles) != required_roles:
        raise ConfigurationError(
            f"execution.closeout.artifact_roles must contain exactly {sorted(required_roles)!r}"
        )
    artifact_names: dict[str, str] = {}
    for role, filename in artifact_roles.items():
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise ConfigurationError(f"execution.closeout.artifact_roles.{role} must be a filename")
        artifact_names[str(role)] = filename
    if len(set(artifact_names.values())) != len(artifact_names):
        raise ConfigurationError("execution closeout artifact filenames must be distinct")
    if closeout["required_final_gate"] != "PASS":
        raise ConfigurationError("execution.closeout.required_final_gate must be PASS")
    if closeout["execution_record_schema"] != "rp1-notebook-execution-v3":
        raise ConfigurationError("execution.closeout.execution_record_schema must be rp1-notebook-execution-v3")

    secondary = raw["secondary_completion"]
    if not isinstance(secondary, Mapping):
        raise ConfigurationError("execution.secondary_completion must be a mapping")
    _require_keys(
        secondary,
        {"allowed_states", "results_validated_required_integration_state"},
        "execution.secondary_completion",
    )
    allowed_states = secondary["allowed_states"]
    if (
        not isinstance(allowed_states, list)
        or not allowed_states
        or not all(isinstance(item, str) and item for item in allowed_states)
        or len(set(allowed_states)) != len(allowed_states)
    ):
        raise ConfigurationError("execution.secondary_completion.allowed_states must be unique strings")
    if set(allowed_states) != {"EXTERNAL_RESULTS_REQUIRED", "RESULTS_VALIDATED"}:
        raise ConfigurationError(
            "execution secondary completion states must be EXTERNAL_RESULTS_REQUIRED and RESULTS_VALIDATED"
        )
    if secondary["results_validated_required_integration_state"] != "INTEGRATED":
        raise ConfigurationError(
            "execution RESULTS_VALIDATED completion must require INTEGRATED secondary state"
        )

    validation = raw["validation"]
    if not isinstance(validation, Mapping):
        raise ConfigurationError("execution.validation must be a mapping")
    _require_keys(validation, {"unknown_mode_policy", "missing_mode_policy"}, "execution.validation")
    for key in ("unknown_mode_policy", "missing_mode_policy"):
        if validation[key] != "fail_closed":
            raise ConfigurationError(f"execution.validation.{key} must be fail_closed")

    modes_raw = raw["modes"]
    if not isinstance(modes_raw, Mapping):
        raise ConfigurationError("execution.modes must be a mapping")
    expected_modes = {"controlled_nbclient", "interactive_jupyter"}
    if set(modes_raw) != expected_modes:
        raise ConfigurationError(f"execution.modes must contain exactly {sorted(expected_modes)!r}")
    modes: dict[str, ExecutionModeContract] = {}
    role_names = set(artifact_names)
    allowed_rules = {"executed_equals_total", "not_required"}
    for mode_id, value in modes_raw.items():
        context = f"execution.modes.{mode_id}"
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"{context} must be a mapping")
        _require_keys(
            value,
            {
                "required_artifact_roles",
                "optional_artifact_roles",
                "required_record_fields",
                "notebook_snapshot_required",
                "notebook_snapshot_sha256_required",
                "code_cell_completion_rule",
            },
            context,
        )
        required_artifact_roles = value["required_artifact_roles"]
        optional_artifact_roles = value["optional_artifact_roles"]
        required_record_fields = value["required_record_fields"]
        for label, items in (
            ("required_artifact_roles", required_artifact_roles),
            ("optional_artifact_roles", optional_artifact_roles),
            ("required_record_fields", required_record_fields),
        ):
            if (
                not isinstance(items, list)
                or not all(isinstance(item, str) and item for item in items)
                or len(set(items)) != len(items)
            ):
                raise ConfigurationError(f"{context}.{label} must be a unique string list")
        if not required_artifact_roles:
            raise ConfigurationError(f"{context}.required_artifact_roles must be non-empty")
        if not set(required_artifact_roles).issubset(role_names):
            raise ConfigurationError(f"{context}.required_artifact_roles contains an unknown role")
        if not set(optional_artifact_roles).issubset(role_names):
            raise ConfigurationError(f"{context}.optional_artifact_roles contains an unknown role")
        if set(required_artifact_roles).intersection(optional_artifact_roles):
            raise ConfigurationError(f"{context} cannot require and optionally declare the same artifact role")
        if "execution_record" not in required_artifact_roles:
            raise ConfigurationError(f"{context} must require execution_record")
        if not {"schema", "status", "run_id", "execution_mode"}.issubset(required_record_fields):
            raise ConfigurationError(f"{context}.required_record_fields lacks base execution fields")
        for flag in ("notebook_snapshot_required", "notebook_snapshot_sha256_required"):
            if not isinstance(value[flag], bool):
                raise ConfigurationError(f"{context}.{flag} must be boolean")
        rule = value["code_cell_completion_rule"]
        if rule not in allowed_rules:
            raise ConfigurationError(f"{context}.code_cell_completion_rule is unsupported: {rule!r}")
        modes[str(mode_id)] = ExecutionModeContract(
            mode_id=str(mode_id),
            required_artifact_roles=tuple(str(x) for x in required_artifact_roles),
            optional_artifact_roles=tuple(str(x) for x in optional_artifact_roles),
            required_record_fields=tuple(str(x) for x in required_record_fields),
            notebook_snapshot_required=bool(value["notebook_snapshot_required"]),
            notebook_snapshot_sha256_required=bool(value["notebook_snapshot_sha256_required"]),
            code_cell_completion_rule=str(rule),
        )

    controlled = modes["controlled_nbclient"]
    interactive = modes["interactive_jupyter"]
    if not controlled.notebook_snapshot_required or not controlled.notebook_snapshot_sha256_required:
        raise ConfigurationError("controlled_nbclient must require an executed-notebook snapshot and SHA-256")
    if controlled.code_cell_completion_rule != "executed_equals_total":
        raise ConfigurationError("controlled_nbclient must require complete code-cell execution")
    if "executed_notebook" not in controlled.required_artifact_roles:
        raise ConfigurationError("controlled_nbclient must require the executed notebook artefact")
    if interactive.notebook_snapshot_required or interactive.notebook_snapshot_sha256_required:
        raise ConfigurationError("interactive_jupyter must not require an executed-notebook snapshot")
    if interactive.code_cell_completion_rule != "not_required":
        raise ConfigurationError("interactive_jupyter must not claim wrapper-observed code-cell completion")
    if "executed_notebook" in interactive.required_artifact_roles:
        raise ConfigurationError("interactive_jupyter must not require the executed notebook artefact")

    return ExecutionCloseoutContract(
        schema_version=str(raw["schema_version"]),
        contract_id=str(raw["contract_id"]),
        closeout_section=section,
        artifact_roles=cast(Mapping[str, str], freeze(artifact_names)),
        required_final_gate="PASS",
        execution_record_schema="rp1-notebook-execution-v3",
        allowed_secondary_completion_states=tuple(str(x) for x in allowed_states),
        results_validated_required_integration_state="INTEGRATED",
        unknown_mode_policy="fail_closed",
        missing_mode_policy="fail_closed",
        modes=MappingProxyType(modes),
    )


def _package_version(project_root: Path) -> str:
    """Read release version from package metadata; YAML/Python do not duplicate it."""

    path = project_root / "pyproject.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        version = raw["project"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"Unable to read package version authority from {path}: {exc}") from exc
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ConfigurationError("project.version must be a semantic x.y.z string")
    return version


def load_analysis_contract(path: str | Path) -> AnalysisContract:
    source = Path(path).resolve()
    raw = _load_yaml(source)
    _validate_schema(raw, source)
    required = {
        "schema_version",
        "project",
        "reproducibility",
        "study",
        "field_roles",
        "product_semantics",
        "research_questions",
        "secondary_analysis",
    }
    _require_keys(raw, required, source.name)
    try:
        validate_analysis_design(raw)
    except DesignValidationError as exc:
        raise ConfigurationError(str(exc)) from exc
    frozen = cast(Mapping[str, Any], freeze(raw))
    return AnalysisContract(
        schema_version=cast(str, frozen["schema_version"]),
        project=cast(Mapping[str, Any], frozen["project"]),
        reproducibility=cast(Mapping[str, Any], frozen["reproducibility"]),
        study=cast(Mapping[str, Any], frozen["study"]),
        field_roles=cast(Mapping[str, Any], frozen["field_roles"]),
        product_semantics=cast(Mapping[str, Any], frozen["product_semantics"]),
        research_questions=cast(Mapping[str, Any], frozen["research_questions"]),
        secondary_analysis=cast(Mapping[str, Any], frozen["secondary_analysis"]),
    )


def load_data_schema_contract(path: str | Path) -> DataSchemaContract:
    """Load the complete physical/semantic input schema authority."""

    source = Path(path).resolve()
    raw = _load_yaml(source)
    _validate_schema(raw, source)
    required = {
        "schema_version", "data_schema_version", "panel_schema_version", "field_count",
        "panels", "auxiliary_inputs", "source_supports", "categorical_domains", "fields",
        "geometries", "relationships", "additive_reconciliation",
        "provenance", "validation_rules",
    }
    _require_keys(raw, required, source.name)
    if raw["data_schema_version"] != DATA_SCHEMA_VERSION:
        raise ConfigurationError(
            f"data_schema_version must be {DATA_SCHEMA_VERSION!r}; got {raw['data_schema_version']!r}"
        )
    if not isinstance(raw["field_count"], int) or raw["field_count"] <= 0:
        raise ConfigurationError("data_schema.field_count must be a positive integer")

    domains_raw = raw["categorical_domains"]
    if not isinstance(domains_raw, Mapping):
        raise ConfigurationError("data_schema.categorical_domains must be a mapping")
    for key, values in domains_raw.items():
        if not isinstance(key, str) or not isinstance(values, list) or not values:
            raise ConfigurationError("Each categorical domain must be a named non-empty list")
    domains = cast(Mapping[str, tuple[Any, ...]], freeze(domains_raw))

    fields_raw = raw["fields"]
    if not isinstance(fields_raw, list) or not fields_raw:
        raise ConfigurationError("data_schema.fields must be a non-empty list")
    fields: list[DataFieldSpec] = []
    names: set[str] = set()
    required_field_keys = {
        "name", "dtype", "semantic_type", "unit", "nullable", "structural_support",
        "required_when_supported", "source_family", "additive",
    }
    optional_field_keys = {"minimum", "maximum", "categorical_domain", "relationship_role"}
    allowed_dtypes = {"string", "integer", "number"}
    supports_raw = raw["source_supports"]
    if not isinstance(supports_raw, Mapping) or not supports_raw:
        raise ConfigurationError("data_schema.source_supports must be a non-empty mapping")
    for index, item in enumerate(fields_raw):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"data_schema.fields[{index}] must be a mapping")
        _require_keys(item, required_field_keys, f"data_schema.fields[{index}]", optional=optional_field_keys)
        name = item["name"]
        if not isinstance(name, str) or not name:
            raise ConfigurationError(f"data_schema.fields[{index}].name must be non-empty")
        if name in names:
            raise ConfigurationError(f"Duplicate data-schema field: {name}")
        names.add(name)
        dtype = item["dtype"]
        if dtype not in allowed_dtypes:
            raise ConfigurationError(f"Unsupported dtype for {name}: {dtype!r}")
        support = item["structural_support"]
        if support not in supports_raw:
            raise ConfigurationError(f"Unknown structural support {support!r} for field {name}")
        domain = item.get("categorical_domain")
        if domain is not None and domain not in domains_raw:
            raise ConfigurationError(f"Unknown categorical domain {domain!r} for field {name}")
        minimum = item.get("minimum")
        maximum = item.get("maximum")
        if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, (int, float))):
            raise ConfigurationError(f"minimum for {name} must be numeric")
        if maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, (int, float))):
            raise ConfigurationError(f"maximum for {name} must be numeric")
        if minimum is not None and maximum is not None and float(maximum) < float(minimum):
            raise ConfigurationError(f"maximum is below minimum for field {name}")
        fields.append(DataFieldSpec(
            name=name,
            dtype=str(dtype), semantic_type=str(item["semantic_type"]), unit=str(item["unit"]),
            nullable=bool(item["nullable"]), structural_support=str(support),
            required_when_supported=bool(item["required_when_supported"]),
            source_family=str(item["source_family"]), additive=bool(item["additive"]),
            minimum=minimum, maximum=maximum,
            categorical_domain=str(domain) if domain is not None else None,
            relationship_role=(str(item["relationship_role"]) if item.get("relationship_role") is not None else None),
        ))
    if len(fields) != int(raw["field_count"]):
        raise ConfigurationError(
            f"data_schema.field_count={raw['field_count']} but {len(fields)} fields are defined"
        )

    panels_raw = raw["panels"]
    if not isinstance(panels_raw, Mapping) or not panels_raw:
        raise ConfigurationError("data_schema.panels must be a non-empty mapping")
    panels: dict[str, PanelSpecification] = {}
    panel_required = {
        "path", "level_value", "primary_key", "expected_rows", "expected_units", "column_count",
        "temporal_frequency", "start", "end",
    }
    for panel_id, item in panels_raw.items():
        if not isinstance(panel_id, str) or not isinstance(item, Mapping):
            raise ConfigurationError("Panel specifications must be named mappings")
        missing = panel_required.difference(item)
        if missing:
            raise ConfigurationError(f"Missing panel fields for {panel_id}: {sorted(missing)!r}")
        primary_key = item["primary_key"]
        if not isinstance(primary_key, list) or not primary_key or not all(isinstance(x, str) for x in primary_key):
            raise ConfigurationError(f"panels.{panel_id}.primary_key must be a non-empty string list")
        for key in primary_key:
            if key not in names:
                raise ConfigurationError(f"panels.{panel_id}.primary_key references unknown field {key!r}")
        for nkey in ("expected_rows", "expected_units", "column_count"):
            if not isinstance(item[nkey], int) or item[nkey] <= 0:
                raise ConfigurationError(f"panels.{panel_id}.{nkey} must be a positive integer")
        metadata = {k: v for k, v in item.items() if k not in panel_required}
        panels[panel_id] = PanelSpecification(
            panel_id=panel_id, path=str(item["path"]), level_value=str(item["level_value"]),
            primary_key=tuple(primary_key), expected_rows=int(item["expected_rows"]),
            expected_units=int(item["expected_units"]), column_count=int(item["column_count"]),
            temporal_frequency=str(item["temporal_frequency"]), start=str(item["start"]), end=str(item["end"]),
            metadata=cast(Mapping[str, Any], freeze(metadata)),
        )

    geometries_raw = raw["geometries"]
    if not isinstance(geometries_raw, Mapping) or not geometries_raw:
        raise ConfigurationError("data_schema.geometries must be a non-empty mapping")
    geometries: dict[str, GeometrySpecification] = {}
    for geometry_id, item in geometries_raw.items():
        if not isinstance(geometry_id, str) or not isinstance(item, Mapping):
            raise ConfigurationError("Geometry specifications must be named mappings")
        required_geometry = {
            "path", "expected_features", "crs_epsg", "geometry_types", "identifier_field",
            "required_columns", "required_members",
        }
        missing = required_geometry.difference(item)
        if missing:
            raise ConfigurationError(f"Missing geometry fields for {geometry_id}: {sorted(missing)!r}")
        geometry_types = item["geometry_types"]
        required_columns = item["required_columns"]
        required_members = item["required_members"]
        if not all(isinstance(v, list) and v and all(isinstance(x, str) for x in v)
                   for v in (geometry_types, required_columns, required_members)):
            raise ConfigurationError(f"Geometry list fields are invalid for {geometry_id}")
        unit_identities = item.get("unit_identities")
        if unit_identities is not None and not isinstance(unit_identities, Mapping):
            raise ConfigurationError(f"geometries.{geometry_id}.unit_identities must be a mapping")
        panel_identity_map = item.get("panel_identity_map")
        if panel_identity_map is not None and (not isinstance(panel_identity_map, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in panel_identity_map.items())):
            raise ConfigurationError(f"geometries.{geometry_id}.panel_identity_map must be a string mapping")
        geometries[geometry_id] = GeometrySpecification(
            geometry_id=geometry_id, path=str(item["path"]), expected_features=int(item["expected_features"]),
            crs_epsg=int(item["crs_epsg"]), geometry_types=tuple(str(x) for x in geometry_types),
            identifier_field=str(item["identifier_field"]), required_columns=tuple(str(x) for x in required_columns),
            required_members=tuple(str(x) for x in required_members),
            parent_field=(str(item["parent_field"]) if item.get("parent_field") is not None else None),
            unit_identities=(cast(Mapping[str, Any], freeze(unit_identities)) if unit_identities is not None else None),
            panel_identity_map=(cast(Mapping[str, str], freeze(panel_identity_map)) if panel_identity_map is not None else None),
        )

    relationships_raw = raw["relationships"]
    if not isinstance(relationships_raw, list) or not relationships_raw:
        raise ConfigurationError("data_schema.relationships must be a non-empty list")
    relationships: list[RelationshipSpecification] = []
    relationship_ids: set[str] = set()
    for index, item in enumerate(relationships_raw):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"relationships[{index}] must be a mapping")
        _require_keys(item, {"relationship_id", "from_object", "from_field", "to_object", "to_field", "cardinality"}, f"relationships[{index}]")
        rid = str(item["relationship_id"])
        if rid in relationship_ids:
            raise ConfigurationError(f"Duplicate relationship_id: {rid}")
        relationship_ids.add(rid)
        if item["cardinality"] not in {"many_to_one", "one_to_one"}:
            raise ConfigurationError(f"Unsupported relationship cardinality: {item['cardinality']!r}")
        relationships.append(RelationshipSpecification(
            relationship_id=rid, from_object=str(item["from_object"]), from_field=str(item["from_field"]),
            to_object=str(item["to_object"]), to_field=str(item["to_field"]), cardinality=str(item["cardinality"]),
        ))

    for section in ("auxiliary_inputs", "additive_reconciliation", "provenance", "validation_rules"):
        if not isinstance(raw[section], Mapping):
            raise ConfigurationError(f"data_schema.{section} must be a mapping")
    return DataSchemaContract(
        schema_version=str(raw["schema_version"]), data_schema_version=str(raw["data_schema_version"]),
        panel_schema_version=str(raw["panel_schema_version"]), field_count=int(raw["field_count"]),
        panels=MappingProxyType(panels),
        auxiliary_inputs=cast(Mapping[str, Mapping[str, Any]], freeze(raw["auxiliary_inputs"])),
        source_supports=cast(Mapping[str, Mapping[str, Any]], freeze(raw["source_supports"])),
        fields=tuple(fields), categorical_domains=domains, geometries=MappingProxyType(geometries),
        relationships=tuple(relationships),
        additive_reconciliation=cast(Mapping[str, Any], freeze(raw["additive_reconciliation"])),
        provenance=cast(Mapping[str, Any], freeze(raw["provenance"])),
        validation_rules=cast(Mapping[str, Any], freeze(raw["validation_rules"])),
    )


def load_method_authorities(path: str | Path) -> MethodAuthorityContract:
    source = Path(path).resolve()
    raw = _load_yaml(source)
    _validate_schema(raw, source)
    _require_keys(raw, {"schema_version", "provenance_classes", "authorities"}, source.name)
    allowed_provenance = {
        "method_defined",
        "study_design_defined",
        "data_defined",
        "computational_reproducibility_only",
    }
    declared = raw["provenance_classes"]
    if not isinstance(declared, list) or set(declared) != allowed_provenance:
        raise ConfigurationError(
            "method_authorities.provenance_classes must contain exactly the four governed classes"
        )
    authorities = raw["authorities"]
    if not isinstance(authorities, list) or not authorities:
        raise ConfigurationError("method_authorities.authorities must be a non-empty list")
    items: list[MethodAuthoritySpec] = []
    seen: set[str] = set()
    required = {
        "method_id", "implementation_id", "family", "status", "qualification_status",
        "authority_scope", "protocol_reference", "authoritative_reference", "doi",
        "governed_variant", "parameter_provenance", "outcome_tuning_allowed",
    }
    for index, item in enumerate(authorities):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"method_authorities[{index}] must be a mapping")
        _require_keys(item, required, f"method_authorities[{index}]")
        method_id = item["method_id"]
        implementation_id = item["implementation_id"]
        if not isinstance(method_id, str) or not method_id:
            raise ConfigurationError("method_id must be a non-empty string")
        if not isinstance(implementation_id, str) or not implementation_id:
            raise ConfigurationError("implementation_id must be a non-empty string")
        if method_id in seen:
            raise ConfigurationError(f"Duplicate method authority: {method_id}")
        seen.add(method_id)
        protocol_ref = item["protocol_reference"]
        authority_ref = item["authoritative_reference"]
        variant = item["governed_variant"]
        if not all(isinstance(x, str) and x.strip() for x in (protocol_ref, authority_ref, variant)):
            raise ConfigurationError(
                f"Method {method_id!r} requires non-empty protocol/reference/variant text"
            )
        doi = item["doi"]
        if doi is not None and (not isinstance(doi, str) or not doi.strip()):
            raise ConfigurationError(f"Method {method_id!r} doi must be a non-empty string or null")
        provenance = item["parameter_provenance"]
        if not isinstance(provenance, Mapping) or not provenance:
            raise ConfigurationError(f"Method {method_id!r} parameter_provenance must be a mapping")
        invalid = sorted(set(provenance.values()).difference(allowed_provenance))
        if invalid:
            raise ConfigurationError(
                f"Method {method_id!r} uses invalid parameter provenance classes: {invalid!r}"
            )
        if item["outcome_tuning_allowed"] is not False:
            raise ConfigurationError(f"Method {method_id!r} must set outcome_tuning_allowed=false")
        items.append(
            MethodAuthoritySpec(
                method_id=method_id,
                implementation_id=implementation_id,
                family=str(item["family"]),
                status=str(item["status"]),
                qualification_status=str(item["qualification_status"]),
                authority_scope=str(item["authority_scope"]),
                protocol_reference=protocol_ref,
                authoritative_reference=authority_ref,
                doi=doi,
                governed_variant=variant,
                parameter_provenance=cast(Mapping[str, str], freeze(provenance)),
                outcome_tuning_allowed=False,
            )
        )
    return MethodAuthorityContract(schema_version=str(raw["schema_version"]), authorities=tuple(items))


def _number(value: Any, context: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{context} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigurationError(f"{context} must be finite")
    if minimum is not None and number < minimum:
        raise ConfigurationError(f"{context} must be >= {minimum}")
    return number


def _grid_cells_overlap(a: GridCellContract, b: GridCellContract) -> bool:
    row_overlap = a.row < b.row + b.row_span and b.row < a.row + a.row_span
    col_overlap = a.column < b.column + b.column_span and b.column < a.column + a.column_span
    return row_overlap and col_overlap


def _load_grid_layouts(raw: Any) -> Mapping[str, GridLayoutContract]:
    if not isinstance(raw, Mapping) or not raw:
        raise ConfigurationError("figure.grid_layouts must be a non-empty mapping")
    layouts: dict[str, GridLayoutContract] = {}
    for layout_id, item in raw.items():
        if not isinstance(layout_id, str) or not layout_id.strip() or not isinstance(item, Mapping):
            raise ConfigurationError("figure.grid_layouts entries require non-empty names and mappings")
        _require_keys(
            item,
            {"size_role", "rows", "columns", "width_ratios", "height_ratios", "cells"},
            f"figure.grid_layouts.{layout_id}",
        )
        size_role = item["size_role"]
        if not isinstance(size_role, str) or not size_role.strip():
            raise ConfigurationError(f"figure.grid_layouts.{layout_id}.size_role must be a non-empty string")
        size_role = size_role.strip()
        rows = int(item["rows"])
        columns = int(item["columns"])
        if rows <= 0 or columns <= 0:
            raise ConfigurationError(f"figure.grid_layouts.{layout_id} rows and columns must be > 0")
        width_ratios_raw = item["width_ratios"]
        height_ratios_raw = item["height_ratios"]
        if not isinstance(width_ratios_raw, (list, tuple)) or len(width_ratios_raw) != columns:
            raise ConfigurationError(
                f"figure.grid_layouts.{layout_id}.width_ratios length must equal columns={columns}"
            )
        if not isinstance(height_ratios_raw, (list, tuple)) or len(height_ratios_raw) != rows:
            raise ConfigurationError(
                f"figure.grid_layouts.{layout_id}.height_ratios length must equal rows={rows}"
            )
        width_ratios = tuple(_number(v, f"figure.grid_layouts.{layout_id}.width_ratios", minimum=0.000001) for v in width_ratios_raw)
        height_ratios = tuple(_number(v, f"figure.grid_layouts.{layout_id}.height_ratios", minimum=0.000001) for v in height_ratios_raw)
        cells_raw = item["cells"]
        if not isinstance(cells_raw, list) or not cells_raw:
            raise ConfigurationError(f"figure.grid_layouts.{layout_id}.cells must be a non-empty list")
        cells: list[GridCellContract] = []
        seen_panel_indices: set[int] = set()
        seen_auxiliary_ids: set[str] = set()
        for idx, cell_raw in enumerate(cells_raw):
            context = f"figure.grid_layouts.{layout_id}.cells[{idx}]"
            if not isinstance(cell_raw, Mapping):
                raise ConfigurationError(f"{context} must be a mapping")
            kind = str(cell_raw.get("kind", ""))
            required_cell = {"kind", "row", "column", "row_span", "column_span"}
            optional_cell = {"panel_index", "auxiliary_id"}
            _require_keys(cell_raw, required_cell, context, optional=optional_cell)
            if kind not in {"data", "auxiliary"}:
                raise ConfigurationError(f"{context}.kind must be 'data' or 'auxiliary'")
            row = int(cell_raw["row"])
            column = int(cell_raw["column"])
            row_span = int(cell_raw["row_span"])
            column_span = int(cell_raw["column_span"])
            if row < 0 or column < 0:
                raise ConfigurationError(f"{context} row and column must be >= 0")
            if row_span <= 0 or column_span <= 0:
                raise ConfigurationError(f"{context} row_span and column_span must be > 0")
            if row + row_span > rows or column + column_span > columns:
                raise ConfigurationError(f"{context} placement extends outside the configured grid")
            panel_index: int | None = None
            auxiliary_id: str | None = None
            if kind == "data":
                if "panel_index" not in cell_raw or "auxiliary_id" in cell_raw:
                    raise ConfigurationError(f"{context} data cells require panel_index and prohibit auxiliary_id")
                panel_index = int(cell_raw["panel_index"])
                if panel_index < 0:
                    raise ConfigurationError(f"{context}.panel_index must be >= 0")
                if panel_index in seen_panel_indices:
                    raise ConfigurationError(f"{context} duplicates data panel_index {panel_index}")
                seen_panel_indices.add(panel_index)
            else:
                auxiliary_id_value = cell_raw.get("auxiliary_id")
                if not isinstance(auxiliary_id_value, str) or not auxiliary_id_value.strip() or "panel_index" in cell_raw:
                    raise ConfigurationError(f"{context} auxiliary cells require auxiliary_id and prohibit panel_index")
                auxiliary_id = auxiliary_id_value.strip()
                if auxiliary_id in seen_auxiliary_ids:
                    raise ConfigurationError(f"{context} duplicates auxiliary_id {auxiliary_id!r}")
                seen_auxiliary_ids.add(auxiliary_id)
            cell = GridCellContract(
                kind=kind,
                row=row,
                column=column,
                row_span=row_span,
                column_span=column_span,
                panel_index=panel_index,
                auxiliary_id=auxiliary_id,
            )
            for earlier in cells:
                if _grid_cells_overlap(earlier, cell):
                    raise ConfigurationError(
                        f"{context} overlaps another configured grid cell; overlapping panels/cells are prohibited"
                    )
            cells.append(cell)
        if seen_panel_indices:
            expected = set(range(len(seen_panel_indices)))
            if seen_panel_indices != expected:
                raise ConfigurationError(
                    f"figure.grid_layouts.{layout_id} data panel indices must be contiguous from 0; "
                    f"got {sorted(seen_panel_indices)!r}"
                )
        layouts[layout_id] = GridLayoutContract(
            layout_id=layout_id,
            size_role=size_role,
            rows=rows,
            columns=columns,
            width_ratios=width_ratios,
            height_ratios=height_ratios,
            cells=tuple(cells),
        )
    return MappingProxyType(layouts)


def _hex_colour(value: Any, context: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None:
        raise ConfigurationError(f"{context} must be a six-digit hexadecimal colour")
    return value.upper()


def _load_semantic_state_style(
    raw: Any,
    context: str,
    *,
    require_hatch: bool = False,
) -> SemanticStateStyleContract:
    if not isinstance(raw, Mapping):
        raise ConfigurationError(f"{context} must be a mapping")
    _require_keys(raw, {"face", "edge"}, context, optional={"hatch"})
    face = _hex_colour(raw["face"], f"{context}.face")
    edge = _hex_colour(raw["edge"], f"{context}.edge")
    hatch = raw.get("hatch", "")
    if not isinstance(hatch, str):
        raise ConfigurationError(f"{context}.hatch must be a string")
    if require_hatch and not hatch.strip():
        raise ConfigurationError(f"{context}.hatch must be non-empty")
    return SemanticStateStyleContract(face=face, edge=edge, hatch=hatch)


def _load_publication_geometry(
    raw: Any,
    *,
    physical_size_roles: Mapping[str, Any],
) -> PublicationGeometryContract:
    if not isinstance(raw, Mapping):
        raise ConfigurationError("figure.publication_geometry must be a mapping")
    _require_keys(
        raw,
        {
            "canvas",
            "outer_margins",
            "spacing",
            "axis_label_padding_pt",
            "panel_label_offset_axes",
            "map_panel",
            "heatmap_colorbar_band_fraction",
            "heatmap_colorbar_gap_fraction",
            "effect_vertical_padding_rows",
        },
        "figure.publication_geometry",
    )
    canvas = raw["canvas"]
    if not isinstance(canvas, Mapping):
        raise ConfigurationError("figure.publication_geometry.canvas must be a mapping")
    _require_keys(canvas, {"width_cm", "height_cm", "orientation"}, "figure.publication_geometry.canvas")
    width_cm = _number(canvas["width_cm"], "figure.publication_geometry.canvas.width_cm", minimum=0.1)
    height_cm = _number(canvas["height_cm"], "figure.publication_geometry.canvas.height_cm", minimum=0.1)
    orientation = canvas["orientation"]
    if orientation != "landscape" or width_cm <= height_cm:
        raise ConfigurationError("figure.publication_geometry.canvas must be landscape")
    if not (abs(width_cm - 20.0) <= 1e-12 and abs(height_cm - 15.0) <= 1e-12):
        raise ConfigurationError("figure.publication_geometry.canvas must remain exactly 20 x 15 cm")
    role = physical_size_roles.get("rectangular_landscape_20x15_cm")
    if not isinstance(role, Mapping):
        raise ConfigurationError("rectangular_landscape_20x15_cm physical size role is required")
    if float(role["width_cm"]) != width_cm or float(role["height_cm"]) != height_cm:
        raise ConfigurationError("publication canvas and rectangular_landscape_20x15_cm size role must agree")

    margins = raw["outer_margins"]
    if not isinstance(margins, Mapping):
        raise ConfigurationError("figure.publication_geometry.outer_margins must be a mapping")
    _require_keys(
        margins,
        {"left_fraction", "right_fraction", "top_fraction", "bottom_fraction"},
        "figure.publication_geometry.outer_margins",
    )
    left = _number(margins["left_fraction"], "figure.publication_geometry.outer_margins.left_fraction", minimum=0.0)
    right = _number(margins["right_fraction"], "figure.publication_geometry.outer_margins.right_fraction", minimum=0.0)
    top = _number(margins["top_fraction"], "figure.publication_geometry.outer_margins.top_fraction", minimum=0.0)
    bottom = _number(margins["bottom_fraction"], "figure.publication_geometry.outer_margins.bottom_fraction", minimum=0.0)
    if any(value >= 0.5 for value in (left, right, top, bottom)) or left + right >= 1 or top + bottom >= 1:
        raise ConfigurationError("figure publication outer margins leave no usable canvas")
    if abs(left - right) > 1e-12:
        raise ConfigurationError("figure publication left/right outer margins must be symmetric")

    spacing = raw["spacing"]
    if not isinstance(spacing, Mapping):
        raise ConfigurationError("figure.publication_geometry.spacing must be a mapping")
    _require_keys(spacing, {"inter_column", "inter_row"}, "figure.publication_geometry.spacing")
    inter_column = _number(spacing["inter_column"], "figure.publication_geometry.spacing.inter_column", minimum=0.0)
    inter_row = _number(spacing["inter_row"], "figure.publication_geometry.spacing.inter_row", minimum=0.0)

    padding = raw["axis_label_padding_pt"]
    if not isinstance(padding, Mapping):
        raise ConfigurationError("figure.publication_geometry.axis_label_padding_pt must be a mapping")
    _require_keys(padding, {"x", "y"}, "figure.publication_geometry.axis_label_padding_pt")
    xlabel_padding = _number(padding["x"], "figure.publication_geometry.axis_label_padding_pt.x", minimum=0.0)
    ylabel_padding = _number(padding["y"], "figure.publication_geometry.axis_label_padding_pt.y", minimum=0.0)

    panel_offset = raw["panel_label_offset_axes"]
    if not isinstance(panel_offset, Mapping):
        raise ConfigurationError("figure.publication_geometry.panel_label_offset_axes must be a mapping")
    _require_keys(panel_offset, {"x", "y"}, "figure.publication_geometry.panel_label_offset_axes")
    offset_x = _number(panel_offset["x"], "figure.publication_geometry.panel_label_offset_axes.x")
    offset_y = _number(panel_offset["y"], "figure.publication_geometry.panel_label_offset_axes.y")
    if not (-0.5 <= offset_x <= 0.5 and -0.5 <= offset_y <= 0.5):
        raise ConfigurationError("figure panel-label offsets must be within +/-0.5 axes units")

    map_panel = raw["map_panel"]
    if not isinstance(map_panel, Mapping):
        raise ConfigurationError("figure.publication_geometry.map_panel must be a mapping")
    _require_keys(
        map_panel,
        {"map_height_ratio", "legend_band_height", "colourbar_band_height", "inter_band_spacing"},
        "figure.publication_geometry.map_panel",
    )
    map_height_ratio = _number(map_panel["map_height_ratio"], "figure.publication_geometry.map_panel.map_height_ratio", minimum=0.000001)
    legend_band_height = _number(map_panel["legend_band_height"], "figure.publication_geometry.map_panel.legend_band_height", minimum=0.000001)
    colourbar_band_height = _number(map_panel["colourbar_band_height"], "figure.publication_geometry.map_panel.colourbar_band_height", minimum=0.000001)
    band_spacing = _number(map_panel["inter_band_spacing"], "figure.publication_geometry.map_panel.inter_band_spacing", minimum=0.0)
    ancillary_map_allocation = legend_band_height + colourbar_band_height + 2.0 * band_spacing
    if ancillary_map_allocation >= map_height_ratio:
        raise ConfigurationError(
            "figure.publication_geometry.map_panel ancillary bands must leave the map viewport dominant"
        )

    heatmap_band = _number(
        raw["heatmap_colorbar_band_fraction"],
        "figure.publication_geometry.heatmap_colorbar_band_fraction",
        minimum=0.000001,
    )
    heatmap_gap = _number(
        raw["heatmap_colorbar_gap_fraction"],
        "figure.publication_geometry.heatmap_colorbar_gap_fraction",
        minimum=0.0,
    )
    if heatmap_band >= 1.0 or heatmap_gap >= 1.0 or heatmap_band + heatmap_gap >= 1.0:
        raise ConfigurationError(
            "figure publication heatmap colourbar band and gap must leave positive plotting area"
        )

    effect_vertical_padding_rows = _number(
        raw["effect_vertical_padding_rows"],
        "figure.publication_geometry.effect_vertical_padding_rows",
        minimum=0.0,
    )
    return PublicationGeometryContract(
        canvas=PublicationCanvasContract(width_cm=width_cm, height_cm=height_cm, orientation=str(orientation)),
        outer_left_fraction=left,
        outer_right_fraction=right,
        outer_top_fraction=top,
        outer_bottom_fraction=bottom,
        inter_column=inter_column,
        inter_row=inter_row,
        xlabel_padding_pt=xlabel_padding,
        ylabel_padding_pt=ylabel_padding,
        panel_label_offset_x=offset_x,
        panel_label_offset_y=offset_y,
        map_height_ratio=map_height_ratio,
        map_legend_band_height=legend_band_height,
        map_colourbar_band_height=colourbar_band_height,
        map_inter_band_spacing=band_spacing,
        heatmap_colorbar_band_fraction=heatmap_band,
        heatmap_colorbar_gap_fraction=heatmap_gap,
        effect_vertical_padding_rows=effect_vertical_padding_rows,
    )


def _load_semantic_styles(raw: Any) -> SemanticStylesContract:
    if not isinstance(raw, Mapping):
        raise ConfigurationError("figure.semantic_styles must be a mapping")
    _require_keys(raw, {"valid_zero", "not_significant", "excluded", "local_moran"}, "figure.semantic_styles")
    valid_zero = _load_semantic_state_style(raw["valid_zero"], "figure.semantic_styles.valid_zero")
    not_significant = _load_semantic_state_style(raw["not_significant"], "figure.semantic_styles.not_significant")
    excluded = _load_semantic_state_style(raw["excluded"], "figure.semantic_styles.excluded", require_hatch=True)
    faces = {valid_zero.face, not_significant.face, excluded.face}
    if len(faces) != 3:
        raise ConfigurationError("valid_zero, not_significant and excluded faces must be visually distinct")
    local_raw = raw["local_moran"]
    if not isinstance(local_raw, Mapping):
        raise ConfigurationError("figure.semantic_styles.local_moran must be a mapping")
    required_classes = {"HH", "LL", "HL", "LH", "NS", "ISLAND"}
    if set(local_raw) != required_classes:
        raise ConfigurationError(
            f"figure.semantic_styles.local_moran requires exactly {sorted(required_classes)!r}"
        )
    local = {
        key: _load_semantic_state_style(local_raw[key], f"figure.semantic_styles.local_moran.{key}")
        for key in ("HH", "LL", "HL", "LH", "NS", "ISLAND")
    }
    if local["NS"].face != not_significant.face:
        raise ConfigurationError("Local Moran NS face must equal the configured not_significant face")
    return SemanticStylesContract(
        valid_zero=valid_zero,
        not_significant=not_significant,
        excluded=excluded,
        local_moran=MappingProxyType(local),
    )


def _load_display_conventions(raw: Any) -> DisplayConventionsContract:
    if not isinstance(raw, Mapping):
        raise ConfigurationError("figure.display_conventions must be a mapping")
    _require_keys(raw, {"circular_mean_month"}, "figure.display_conventions")
    circular = raw["circular_mean_month"]
    if not isinstance(circular, Mapping):
        raise ConfigurationError(
            "figure.display_conventions.circular_mean_month must be a mapping"
        )
    _require_keys(
        circular,
        {"axis_label", "legend_title", "axis_min", "axis_max", "ticks", "tick_labels"},
        "figure.display_conventions.circular_mean_month",
    )
    axis_label = str(circular["axis_label"]).strip()
    legend_title = str(circular["legend_title"]).strip()
    if not axis_label or not legend_title:
        raise ConfigurationError("circular-mean-month display labels must be non-empty")
    axis_min = _number(
        circular["axis_min"], "figure.display_conventions.circular_mean_month.axis_min"
    )
    axis_max = _number(
        circular["axis_max"], "figure.display_conventions.circular_mean_month.axis_max"
    )
    if axis_max <= axis_min:
        raise ConfigurationError("circular-mean-month axis_max must exceed axis_min")
    ticks_raw = circular["ticks"]
    labels_raw = circular["tick_labels"]
    if not isinstance(ticks_raw, list) or not ticks_raw:
        raise ConfigurationError("circular-mean-month ticks must be a non-empty list")
    if not isinstance(labels_raw, list) or len(labels_raw) != len(ticks_raw):
        raise ConfigurationError("circular-mean-month tick_labels must match ticks")
    ticks = tuple(
        _number(value, f"figure.display_conventions.circular_mean_month.ticks[{index}]")
        for index, value in enumerate(ticks_raw)
    )
    if any(value < axis_min or value > axis_max for value in ticks):
        raise ConfigurationError("circular-mean-month ticks must lie within the configured axis")
    tick_labels = tuple(str(value) for value in labels_raw)
    return DisplayConventionsContract(
        circular_mean_month=CircularMeanMonthDisplayContract(
            axis_label=axis_label,
            legend_title=legend_title,
            axis_min=axis_min,
            axis_max=axis_max,
            ticks=ticks,
            tick_labels=tick_labels,
        )
    )


def _validate_presentation_path_pattern(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{context} must be a non-empty relative path pattern")
    value = value.strip()
    unknown_placeholders = set(re.findall(r"\{([^{}]+)\}", value)).difference({"run_base"})
    if unknown_placeholders:
        raise ConfigurationError(
            f"{context} contains unsupported placeholders: {sorted(unknown_placeholders)!r}"
        )
    probe = value.replace("{run_base}", "run_base")
    path = Path(probe)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigurationError(f"{context} must stay within the project/run authority")
    return value


def _validate_presentation_selector(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{context} must be a mapping")
    keys = set(value)
    if keys == {"all_rows"}:
        if value["all_rows"] is not True:
            raise ConfigurationError(f"{context}.all_rows must be true")
    elif keys == {"column", "equals"}:
        column = value["column"]
        if not isinstance(column, str) or not column.strip():
            raise ConfigurationError(f"{context}.column must be a non-empty string")
        equals = value["equals"]
        if equals is None or isinstance(equals, (Mapping, list, tuple, set)):
            raise ConfigurationError(f"{context}.equals must be a scalar value")
    else:
        raise ConfigurationError(
            f"{context} must use exactly all_rows:true or column+equals"
        )
    return cast(Mapping[str, Any], freeze(value))


def _load_presentation_export(
    raw: Any,
    *,
    available_formats: frozenset[str],
    physical_size_roles: Mapping[str, Any],
    resolution_dpi: int,
) -> PresentationExportRegistryContract | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ConfigurationError("figure.presentation_export must be a mapping")
    _require_keys(
        raw,
        {
            "schema",
            "groups",
            "renderer_identities",
            "sources",
            "geometry_dependencies",
            "output",
            "run_family",
            "manifests",
            "semantic_styles",
            "exports",
        },
        "figure.presentation_export",
    )
    schema = str(raw["schema"])
    if schema != "rp1-presentation-export-v1":
        raise ConfigurationError(f"Unsupported figure.presentation_export.schema: {schema!r}")

    groups_raw = raw["groups"]
    if (
        not isinstance(groups_raw, list)
        or not groups_raw
        or not all(isinstance(item, str) and item.strip() for item in groups_raw)
        or len(groups_raw) != len(set(groups_raw))
    ):
        raise ConfigurationError("figure.presentation_export.groups must be unique non-empty strings")
    groups = tuple(str(item) for item in groups_raw)

    renderer_raw = raw["renderer_identities"]
    if (
        not isinstance(renderer_raw, list)
        or not renderer_raw
        or not all(isinstance(item, str) and item.strip() for item in renderer_raw)
        or len(renderer_raw) != len(set(renderer_raw))
    ):
        raise ConfigurationError(
            "figure.presentation_export.renderer_identities must be unique non-empty strings"
        )
    renderer_identities = tuple(str(item) for item in renderer_raw)

    sources_raw = raw["sources"]
    if not isinstance(sources_raw, Mapping) or not sources_raw:
        raise ConfigurationError("figure.presentation_export.sources must be a non-empty mapping")
    sources: dict[str, PresentationSourceContract] = {}
    for source_identity, value in sources_raw.items():
        if not isinstance(source_identity, str) or not source_identity.strip() or not isinstance(value, Mapping):
            raise ConfigurationError("figure.presentation_export.sources entries must be named mappings")
        _require_keys(value, {"path_pattern"}, f"figure.presentation_export.sources.{source_identity}")
        path_pattern = _validate_presentation_path_pattern(
            value["path_pattern"], f"figure.presentation_export.sources.{source_identity}.path_pattern"
        )
        sources[source_identity] = PresentationSourceContract(
            source_identity=source_identity,
            path_pattern=path_pattern,
        )

    dependencies_raw = raw["geometry_dependencies"]
    if not isinstance(dependencies_raw, Mapping) or not dependencies_raw:
        raise ConfigurationError(
            "figure.presentation_export.geometry_dependencies must be a non-empty mapping"
        )
    dependencies: dict[str, PresentationGeometryDependencyContract] = {}
    for dependency_id, value in dependencies_raw.items():
        if not isinstance(dependency_id, str) or not dependency_id.strip() or not isinstance(value, Mapping):
            raise ConfigurationError(
                "figure.presentation_export.geometry_dependencies entries must be named mappings"
            )
        _require_keys(
            value,
            {"geometries"},
            f"figure.presentation_export.geometry_dependencies.{dependency_id}",
        )
        geometries = value["geometries"]
        if (
            not isinstance(geometries, list)
            or not all(isinstance(item, str) and item.strip() for item in geometries)
            or len(geometries) != len(set(geometries))
        ):
            raise ConfigurationError(
                f"figure.presentation_export.geometry_dependencies.{dependency_id}.geometries "
                "must be a unique string list"
            )
        dependencies[dependency_id] = PresentationGeometryDependencyContract(
            dependency_id=dependency_id,
            geometries=tuple(str(item) for item in geometries),
        )

    output_raw = raw["output"]
    if not isinstance(output_raw, Mapping):
        raise ConfigurationError("figure.presentation_export.output must be a mapping")
    _require_keys(
        output_raw,
        {
            "formats",
            "size_role",
            "raster_dpi",
            "collision_policy",
            "deterministic_names",
            "source_run_read_only",
            "staging_policy",
        },
        "figure.presentation_export.output",
    )
    output_formats_raw = output_raw["formats"]
    if (
        not isinstance(output_formats_raw, list)
        or not output_formats_raw
        or not all(isinstance(item, str) and item in available_formats for item in output_formats_raw)
        or len(output_formats_raw) != len(set(output_formats_raw))
    ):
        raise ConfigurationError(
            "figure.presentation_export.output.formats must be unique configured figure formats"
        )
    size_role = str(output_raw["size_role"])
    if size_role not in physical_size_roles:
        raise ConfigurationError(
            f"figure.presentation_export.output.size_role {size_role!r} has no physical-size authority"
        )
    raster_dpi = _number(
        output_raw["raster_dpi"], "figure.presentation_export.output.raster_dpi", minimum=72
    )
    if int(raster_dpi) != raster_dpi or int(raster_dpi) != resolution_dpi:
        raise ConfigurationError(
            "figure.presentation_export.output.raster_dpi must equal figure.resolution_dpi"
        )
    if output_raw["collision_policy"] != "error_if_output_dir_exists":
        raise ConfigurationError("presentation export collision policy must fail on an existing destination")
    if output_raw["deterministic_names"] is not True:
        raise ConfigurationError("presentation export deterministic_names must be true")
    if output_raw["source_run_read_only"] is not True:
        raise ConfigurationError("presentation export source_run_read_only must be true")
    if output_raw["staging_policy"] != "temporary_sibling_then_atomic_promote":
        raise ConfigurationError("presentation export staging policy must use sibling staging and atomic promotion")
    output = PresentationOutputPolicyContract(
        formats=tuple(str(item) for item in output_formats_raw),
        size_role=size_role,
        raster_dpi=int(raster_dpi),
        collision_policy=str(output_raw["collision_policy"]),
        deterministic_names=True,
        source_run_read_only=True,
        staging_policy=str(output_raw["staging_policy"]),
    )

    run_family_raw = raw["run_family"]
    if not isinstance(run_family_raw, Mapping):
        raise ConfigurationError("figure.presentation_export.run_family must be a mapping")
    _require_keys(
        run_family_raw,
        {
            "required_member_suffix",
            "publication_member_suffix",
            "secondary_member_suffix",
            "require_closeout_validation",
        },
        "figure.presentation_export.run_family",
    )
    suffixes = tuple(
        str(run_family_raw[name])
        for name in ("required_member_suffix", "publication_member_suffix", "secondary_member_suffix")
    )
    if any(not item.startswith("_") or len(item) < 2 for item in suffixes) or len(set(suffixes)) != 3:
        raise ConfigurationError("presentation run-family suffixes must be distinct underscore-prefixed strings")
    if not isinstance(run_family_raw["require_closeout_validation"], bool):
        raise ConfigurationError("presentation run_family.require_closeout_validation must be boolean")
    run_family = PresentationRunFamilyContract(
        required_member_suffix=suffixes[0],
        publication_member_suffix=suffixes[1],
        secondary_member_suffix=suffixes[2],
        require_closeout_validation=bool(run_family_raw["require_closeout_validation"]),
    )

    manifests_raw = raw["manifests"]
    if not isinstance(manifests_raw, Mapping):
        raise ConfigurationError("figure.presentation_export.manifests must be a mapping")
    _require_keys(
        manifests_raw,
        {"export_manifest", "source_inventory", "output_inventory"},
        "figure.presentation_export.manifests",
    )
    manifest_names: dict[str, str] = {}
    for key in ("export_manifest", "source_inventory", "output_inventory"):
        value = manifests_raw[key]
        if not isinstance(value, str) or not value.strip() or Path(value).name != value:
            raise ConfigurationError(f"figure.presentation_export.manifests.{key} must be a filename")
        manifest_names[key] = value
    if len(set(manifest_names.values())) != 3:
        raise ConfigurationError("presentation export manifest filenames must be distinct")
    manifests = PresentationManifestContract(**manifest_names)

    styles_raw = raw["semantic_styles"]
    if not isinstance(styles_raw, Mapping) or not styles_raw:
        raise ConfigurationError("figure.presentation_export.semantic_styles must be a non-empty mapping")
    for style_id, mapping in styles_raw.items():
        if not isinstance(style_id, str) or not style_id.strip() or not isinstance(mapping, Mapping) or not mapping:
            raise ConfigurationError("presentation semantic styles must be named non-empty mappings")
        for category, colour in mapping.items():
            if not isinstance(category, str) or not category.strip():
                raise ConfigurationError(f"presentation semantic style {style_id!r} has an invalid category")
            if not isinstance(colour, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", colour) is None:
                raise ConfigurationError(
                    f"presentation semantic style {style_id!r} category {category!r} requires a #RRGGBB colour"
                )

    exports_raw = raw["exports"]
    if not isinstance(exports_raw, list) or not exports_raw:
        raise ConfigurationError("figure.presentation_export.exports must be a non-empty list")
    exports: list[PresentationExportSpecificationContract] = []
    ids: set[str] = set()
    for index, item in enumerate(exports_raw):
        context = f"figure.presentation_export.exports[{index}]"
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"{context} must be a mapping")
        _require_keys(
            item,
            {
                "export_id",
                "group",
                "label",
                "source_identity",
                "source_path_pattern",
                "selector",
                "geometry_dependency",
                "renderer_identity",
                "scenario",
                "required_result_state",
                "output_filename",
                "size_role",
                "formats",
                "raster_dpi",
                "units",
                "category_order",
                "colour_semantic",
                "legend_policy",
                "annotation_policy",
                "interpretation_boundary",
            },
            context,
        )
        export_id = str(item["export_id"])
        if re.fullmatch(r"[a-z][a-z0-9_]*", export_id) is None:
            raise ConfigurationError(f"Invalid presentation export ID: {export_id!r}")
        if export_id in ids:
            raise ConfigurationError(f"Duplicate presentation export ID: {export_id}")
        ids.add(export_id)
        group = str(item["group"])
        if group not in groups:
            raise ConfigurationError(f"Unknown presentation export group {group!r} for {export_id}")
        label = str(item["label"]).strip()
        if not label:
            raise ConfigurationError(f"{export_id}.label must be non-empty")
        source_identity = str(item["source_identity"])
        if source_identity not in sources:
            raise ConfigurationError(f"Unknown presentation source identity {source_identity!r} for {export_id}")
        source_path_pattern = _validate_presentation_path_pattern(
            item["source_path_pattern"], f"{context}.source_path_pattern"
        )
        if source_path_pattern != sources[source_identity].path_pattern:
            raise ConfigurationError(
                f"{export_id}.source_path_pattern conflicts with source registry {source_identity!r}"
            )
        selector = _validate_presentation_selector(item["selector"], f"{context}.selector")
        dependency = str(item["geometry_dependency"])
        if dependency not in dependencies:
            raise ConfigurationError(f"Unknown geometry dependency {dependency!r} for {export_id}")
        renderer_identity = str(item["renderer_identity"])
        if renderer_identity not in renderer_identities:
            raise ConfigurationError(f"Unknown presentation renderer identity {renderer_identity!r} for {export_id}")
        scenario = item["scenario"]
        if scenario is not None and (not isinstance(scenario, str) or not scenario.strip()):
            raise ConfigurationError(f"{export_id}.scenario must be null or a non-empty string")
        required_result_state = str(item["required_result_state"])
        if required_result_state not in {"NONE", "RESULTS_VALIDATED"}:
            raise ConfigurationError(
                f"Unsupported presentation result-state requirement {required_result_state!r} for {export_id}"
            )
        if required_result_state == "RESULTS_VALIDATED" and scenario is None:
            raise ConfigurationError(f"{export_id} requires RESULTS_VALIDATED but has no scenario")
        if scenario is not None and required_result_state != "RESULTS_VALIDATED":
            raise ConfigurationError(f"{export_id} has a scenario without RESULTS_VALIDATED requirement")
        output_filename = str(item["output_filename"])
        if output_filename != f"{export_id}.{{format}}":
            raise ConfigurationError(f"{export_id}.output_filename must be deterministic <export_id>.{{format}}")
        item_size_role = str(item["size_role"])
        if item_size_role not in physical_size_roles or item_size_role != output.size_role:
            raise ConfigurationError(f"{export_id}.size_role must use the configured presentation output size role")
        item_formats = item["formats"]
        if (
            not isinstance(item_formats, list)
            or not item_formats
            or not all(isinstance(fmt, str) and fmt in output.formats for fmt in item_formats)
            or len(item_formats) != len(set(item_formats))
        ):
            raise ConfigurationError(f"{export_id}.formats must be unique supported presentation formats")
        item_dpi = _number(item["raster_dpi"], f"{context}.raster_dpi", minimum=72)
        if int(item_dpi) != item_dpi or int(item_dpi) != output.raster_dpi:
            raise ConfigurationError(f"{export_id}.raster_dpi must use the configured presentation raster DPI")
        units = str(item["units"]).strip()
        if not units:
            raise ConfigurationError(f"{export_id}.units must be non-empty")
        category_order = item["category_order"]
        if not isinstance(category_order, Mapping):
            raise ConfigurationError(f"{export_id}.category_order must be a mapping")
        _require_keys(
            category_order,
            {"mode", "values"},
            f"{context}.category_order",
            optional={"key"},
        )
        mode = str(category_order["mode"])
        if mode not in {"none", "explicit", "deterministic"}:
            raise ConfigurationError(f"Unsupported {export_id}.category_order.mode {mode!r}")
        values = category_order["values"]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ConfigurationError(f"{export_id}.category_order.values must be a string list")
        if mode == "explicit" and not values:
            raise ConfigurationError(f"{export_id} explicit category order cannot be empty")
        if mode == "deterministic":
            key = category_order.get("key")
            if not isinstance(key, str) or not key.strip():
                raise ConfigurationError(f"{export_id} deterministic category order requires key")
        colour_semantic = str(item["colour_semantic"]).strip()
        if not colour_semantic:
            raise ConfigurationError(f"{export_id}.colour_semantic must be non-empty")
        legend_policy = item["legend_policy"]
        if not isinstance(legend_policy, Mapping):
            raise ConfigurationError(f"{export_id}.legend_policy must be a mapping")
        _require_keys(legend_policy, {"show", "position"}, f"{context}.legend_policy")
        if not isinstance(legend_policy["show"], bool):
            raise ConfigurationError(f"{export_id}.legend_policy.show must be boolean")
        position = str(legend_policy["position"])
        if position not in {"none", "below", "renderer_default"}:
            raise ConfigurationError(f"{export_id}.legend_policy.position is unsupported")
        if not legend_policy["show"] and position != "none":
            raise ConfigurationError(f"{export_id} hidden legend must use position='none'")
        annotation_policy = item["annotation_policy"]
        if not isinstance(annotation_policy, list) or not all(
            isinstance(value, str) and value.strip() for value in annotation_policy
        ):
            raise ConfigurationError(f"{export_id}.annotation_policy must be a string list")
        interpretation_boundary = str(item["interpretation_boundary"]).strip()
        if not interpretation_boundary:
            raise ConfigurationError(f"{export_id}.interpretation_boundary must be non-empty")
        exports.append(
            PresentationExportSpecificationContract(
                export_id=export_id,
                group=group,
                label=label,
                source_identity=source_identity,
                source_path_pattern=source_path_pattern,
                selector=selector,
                geometry_dependency=dependency,
                renderer_identity=renderer_identity,
                scenario=cast(str | None, scenario),
                required_result_state=required_result_state,
                output_filename=output_filename,
                size_role=item_size_role,
                formats=tuple(str(fmt) for fmt in item_formats),
                raster_dpi=int(item_dpi),
                units=units,
                category_order=cast(Mapping[str, Any], freeze(category_order)),
                colour_semantic=colour_semantic,
                legend_policy=cast(Mapping[str, Any], freeze(legend_policy)),
                annotation_policy=tuple(str(value) for value in annotation_policy),
                interpretation_boundary=interpretation_boundary,
            )
        )

    return PresentationExportRegistryContract(
        schema=schema,
        groups=groups,
        renderer_identities=renderer_identities,
        sources=MappingProxyType(sources),
        geometry_dependencies=MappingProxyType(dependencies),
        output=output,
        run_family=run_family,
        manifests=manifests,
        semantic_styles=cast(Mapping[str, Any], freeze(styles_raw)),
        exports=tuple(exports),
    )


def load_figure_contract(path: str | Path) -> FigureContract:
    source = Path(path).resolve()
    raw = _load_yaml(source)
    _validate_schema(raw, source)
    required = {
        "schema_version",
        "formats",
        "resolution_dpi",
        "dimensions_inches",
        "physical_size_roles",
        "pixel_rounding",
        "grid_layouts",
        "font_sizes_pt",
        "map_layout",
        "publication_geometry",
        "semantic_styles",
        "display_conventions",
        "panel_layout",
        "panel_labels",
        "source_data_policy",
        "text_policy",
        "figures",
    }
    _require_keys(raw, required, source.name, optional={"presentation_export"})
    dpi = _number(raw["resolution_dpi"], "figure.resolution_dpi", minimum=72)
    if int(dpi) != dpi:
        raise ConfigurationError("figure.resolution_dpi must be an integer")

    physical_size_roles = raw["physical_size_roles"]
    if not isinstance(physical_size_roles, Mapping) or not physical_size_roles:
        raise ConfigurationError("figure.physical_size_roles must be a non-empty mapping")
    for role, value in physical_size_roles.items():
        if not isinstance(role, str) or not role.strip() or not isinstance(value, Mapping):
            raise ConfigurationError("figure.physical_size_roles entries must be named mappings")
        _require_keys(value, {"width_cm", "height_cm"}, f"figure.physical_size_roles.{role}")
        _number(value["width_cm"], f"figure.physical_size_roles.{role}.width_cm", minimum=0.1)
        _number(value["height_cm"], f"figure.physical_size_roles.{role}.height_cm", minimum=0.1)

    publication_geometry = _load_publication_geometry(
        raw["publication_geometry"], physical_size_roles=physical_size_roles
    )
    semantic_styles = _load_semantic_styles(raw["semantic_styles"])
    display_conventions = _load_display_conventions(raw["display_conventions"])

    pixel_rounding = raw["pixel_rounding"]
    if not isinstance(pixel_rounding, Mapping):
        raise ConfigurationError("figure.pixel_rounding must be a mapping")
    _require_keys(pixel_rounding, {"method"}, "figure.pixel_rounding")
    if pixel_rounding.get("method") != "half_up":
        raise ConfigurationError("figure.pixel_rounding.method must be 'half_up'")

    map_layout = raw["map_layout"]
    if not isinstance(map_layout, Mapping):
        raise ConfigurationError("figure.map_layout must be a mapping")
    legend = map_layout.get("legend")
    if not isinstance(legend, Mapping):
        raise ConfigurationError("figure.map_layout.legend must be a mapping")
    if legend.get("position") != "below":
        raise ConfigurationError("figure.map_layout.legend.position must be 'below'")
    colorbar = map_layout.get("colorbar")
    if not isinstance(colorbar, Mapping):
        raise ConfigurationError("figure.map_layout.colorbar must be a mapping")
    if colorbar.get("position") != "below" or colorbar.get("orientation") != "horizontal":
        raise ConfigurationError(
            "figure.map_layout.colorbar requires position='below' and orientation='horizontal'"
        )

    dimensions = raw["dimensions_inches"]
    if not isinstance(dimensions, Mapping) or not dimensions:
        raise ConfigurationError("figure.dimensions_inches must be a non-empty mapping")
    for layout_name, pair in dimensions.items():
        if not isinstance(layout_name, str) or not layout_name.strip():
            raise ConfigurationError("figure dimension layout names must be non-empty strings")
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ConfigurationError(f"figure.dimensions_inches.{layout_name} must contain width and height")
        width = _number(pair[0], f"figure.dimensions_inches.{layout_name}[0]", minimum=0.1)
        height = _number(pair[1], f"figure.dimensions_inches.{layout_name}[1]", minimum=0.1)
        if width <= 0 or height <= 0:
            raise ConfigurationError(f"figure.dimensions_inches.{layout_name} must be positive")

    grid_layouts = _load_grid_layouts(raw["grid_layouts"])
    available_size_roles = set(dimensions) | set(physical_size_roles)
    for layout_id, layout in grid_layouts.items():
        if layout.size_role not in available_size_roles:
            raise ConfigurationError(
                f"figure.grid_layouts.{layout_id}.size_role {layout.size_role!r} has no configured size authority"
            )

    available_formats_raw = raw["formats"]
    if not isinstance(available_formats_raw, Mapping) or not available_formats_raw:
        raise ConfigurationError("figure.formats must be a non-empty mapping")
    available_formats: set[str] = set()
    for family, values in available_formats_raw.items():
        if not isinstance(family, str) or not family.strip() or not isinstance(values, list):
            raise ConfigurationError("figure.formats entries must be named string lists")
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ConfigurationError(f"figure.formats.{family} must contain non-empty strings")
        available_formats.update(str(value) for value in values)
    presentation_export = _load_presentation_export(
        raw.get("presentation_export"),
        available_formats=frozenset(available_formats),
        physical_size_roles=physical_size_roles,
        resolution_dpi=int(dpi),
    )

    figures_raw = raw["figures"]
    if not isinstance(figures_raw, list) or not figures_raw:
        raise ConfigurationError("figure.figures must be a non-empty list")
    figures: list[FigureSpecificationContract] = []
    ids: set[str] = set()
    for index, item in enumerate(figures_raw):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"figure.figures[{index}] must be a mapping")
        required_item = {
            "id",
            "rq",
            "title",
            "role",
            "evidence_class",
            "layout_role",
            "renderer",
            "data_builder",
            "source_attribute",
            "requires_results_validated",
            "data_builder_options",
            "renderer_options",
            "panel_count",
            "required_columns",
        }
        _require_keys(
            item,
            required_item,
            f"figure.figures[{index}]",
            optional={"xlabel", "ylabel", "colorbar_label", "panel_xlabels", "panel_ylabels"},
        )
        figure_id = str(item["id"])
        if figure_id in ids:
            raise ConfigurationError(f"Duplicate figure ID: {figure_id}")
        ids.add(figure_id)
        panel_count = int(item["panel_count"])
        if panel_count < 1:
            raise ConfigurationError("figure.panel_count must be >= 1")
        layout_role = str(item["layout_role"])
        if layout_role not in grid_layouts:
            raise ConfigurationError(f"{figure_id}.layout_role {layout_role!r} has no configured grid layout")
        data_cell_count = len(grid_layouts[layout_role].data_cells)
        if data_cell_count != panel_count:
            raise ConfigurationError(
                f"{figure_id}.layout_role {layout_role!r} provides {data_cell_count} data panels, "
                f"but panel_count is {panel_count}"
            )
        panel_x = tuple(item.get("panel_xlabels", []))
        panel_y = tuple(item.get("panel_ylabels", []))
        if panel_count > 1 and (len(panel_x) != panel_count or len(panel_y) != panel_count):
            raise ConfigurationError(f"{figure_id} panel label arrays must match panel_count")
        required_columns = item["required_columns"]
        if not isinstance(required_columns, list) or not all(isinstance(x, str) for x in required_columns):
            raise ConfigurationError(f"{figure_id}.required_columns must be a string list")
        source_attribute = item["source_attribute"]
        if not isinstance(source_attribute, str) or not source_attribute.strip():
            raise ConfigurationError(f"{figure_id}.source_attribute must be a non-empty string")
        if not isinstance(item["requires_results_validated"], bool):
            raise ConfigurationError(f"{figure_id}.requires_results_validated must be boolean")
        for option_name in ("data_builder_options", "renderer_options"):
            if not isinstance(item[option_name], Mapping):
                raise ConfigurationError(f"{figure_id}.{option_name} must be a mapping")
        figures.append(
            FigureSpecificationContract(
                figure_id=figure_id,
                rq=str(item["rq"]),
                title=str(item["title"]),
                role=str(item["role"]),
                evidence_class=str(item["evidence_class"]),
                layout_role=layout_role,
                renderer=str(item["renderer"]),
                data_builder=str(item["data_builder"]),
                source_attribute=source_attribute,
                requires_results_validated=bool(item["requires_results_validated"]),
                data_builder_options=cast(Mapping[str, Any], freeze(item["data_builder_options"])),
                renderer_options=cast(Mapping[str, Any], freeze(item["renderer_options"])),
                xlabel=cast(str | None, item.get("xlabel")),
                ylabel=cast(str | None, item.get("ylabel")),
                colorbar_label=cast(str | None, item.get("colorbar_label")),
                panel_count=panel_count,
                panel_xlabels=cast(tuple[str | None, ...], panel_x),
                panel_ylabels=cast(tuple[str | None, ...], panel_y),
                required_columns=tuple(required_columns),
            )
        )
    return FigureContract(
        schema_version=str(raw["schema_version"]),
        formats=cast(Mapping[str, Any], freeze(raw["formats"])),
        resolution_dpi=int(dpi),
        dimensions_inches=cast(Mapping[str, Any], freeze(raw["dimensions_inches"])),
        physical_size_roles=cast(Mapping[str, Any], freeze(raw["physical_size_roles"])),
        pixel_rounding=cast(Mapping[str, Any], freeze(raw["pixel_rounding"])),
        grid_layouts=grid_layouts,
        font_sizes_pt=cast(Mapping[str, Any], freeze(raw["font_sizes_pt"])),
        map_layout=cast(Mapping[str, Any], freeze(raw["map_layout"])),
        publication_geometry=publication_geometry,
        semantic_styles=semantic_styles,
        display_conventions=display_conventions,
        panel_layout=cast(Mapping[str, Any], freeze(raw["panel_layout"])),
        panel_labels=cast(Mapping[str, Any], freeze(raw["panel_labels"])),
        source_data_policy=cast(Mapping[str, Any], freeze(raw["source_data_policy"])),
        text_policy=cast(Mapping[str, Any], freeze(raw["text_policy"])),
        figures=tuple(figures),
        presentation_export=presentation_export,
    )

def _validate_relative_config_path(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{context} must be a non-empty relative path")
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        raise ConfigurationError(f"{context} must stay within the subproject")
    return p.as_posix()


def load_output_contract(path: str | Path) -> OutputContract:
    source = Path(path).resolve()
    raw = _load_yaml(source)
    _validate_schema(raw, source)
    required = {
        "schema_version",
        "run_root",
        "latest_run_pointer",
        "sections",
        "output_families",
        "filename_policy",
        "write_policy",
        "hashing",
        "csv_column_orders",
        "publication_outputs",
        "secondary_outputs",
    }
    _require_keys(raw, required, source.name)
    run_root = _validate_relative_config_path(raw["run_root"], "output.run_root")
    latest = _validate_relative_config_path(raw["latest_run_pointer"], "output.latest_run_pointer")
    sections = raw["sections"]
    families = raw["output_families"]
    if not isinstance(sections, list) or not sections or len(sections) != len(set(sections)):
        raise ConfigurationError("output.sections must be a non-empty list of unique names")
    if not isinstance(families, list) or not families or len(families) != len(set(families)):
        raise ConfigurationError("output.output_families must be a non-empty list of unique names")
    publication = raw["publication_outputs"]
    if not isinstance(publication, Mapping):
        raise ConfigurationError("output.publication_outputs must be a mapping")
    _require_keys(publication, {"tables", "figure_formats", "registries"}, "output.publication_outputs")
    table_raw = publication["tables"]
    if not isinstance(table_raw, list) or not table_raw:
        raise ConfigurationError("output.publication_outputs.tables must be a non-empty list")
    tables: list[OutputSpecification] = []
    ids: set[str] = set()
    for index, item in enumerate(table_raw):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"output.tables[{index}] must be a mapping")
        _require_keys(
            item,
            {
                "id", "rq", "title", "role", "family_id", "evidence_class",
                "builder", "source_attribute", "required_columns",
                "requires_results_validated", "builder_options"
            },
            f"output.tables[{index}]",
        )
        output_id = str(item["id"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", output_id):
            raise ConfigurationError(f"Invalid governed output identifier: {output_id!r}")
        if output_id in ids:
            raise ConfigurationError(f"Duplicate output ID: {output_id}")
        ids.add(output_id)
        required_columns = item["required_columns"]
        if not isinstance(required_columns, list) or not all(isinstance(x, str) for x in required_columns):
            raise ConfigurationError(f"{output_id}.required_columns must be a string list")
        source_attribute = item["source_attribute"]
        if source_attribute is not None and not isinstance(source_attribute, str):
            raise ConfigurationError(f"{output_id}.source_attribute must be string or null")
        role = str(item["role"])
        if role not in {"manuscript", "supplementary", "internal_authority"}:
            raise ConfigurationError(f"Invalid output role for {output_id}: {role!r}")
        family_id = str(item["family_id"])
        if not family_id:
            raise ConfigurationError(f"{output_id}.family_id must be non-empty")
        if not isinstance(item["requires_results_validated"], bool):
            raise ConfigurationError(f"{output_id}.requires_results_validated must be boolean")
        if not isinstance(item["builder_options"], Mapping):
            raise ConfigurationError(f"{output_id}.builder_options must be a mapping")
        tables.append(
            OutputSpecification(
                output_id=output_id,
                rq=str(item["rq"]),
                title=str(item["title"]),
                role=role,
                family_id=family_id,
                evidence_class=str(item["evidence_class"]),
                builder=str(item["builder"]),
                source_attribute=source_attribute,
                required_columns=tuple(required_columns),
                requires_results_validated=bool(item["requires_results_validated"]),
                builder_options=cast(Mapping[str, Any], freeze(item["builder_options"])),
            )
        )
    secondary_raw = raw["secondary_outputs"]
    if not isinstance(secondary_raw, list):
        raise ConfigurationError("output.secondary_outputs must be a list")
    secondary_outputs: list[SecondaryOutputSpecification] = []
    secondary_ids: set[str] = set()
    for index, item in enumerate(secondary_raw):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"output.secondary_outputs[{index}] must be a mapping")
        _require_keys(
            item,
            {"id", "output_type", "role", "builder", "source_attribute", "requires_results_validated"},
            f"output.secondary_outputs[{index}]",
        )
        output_id = str(item["id"])
        if output_id in ids or output_id in secondary_ids:
            raise ConfigurationError(f"Duplicate output ID: {output_id}")
        secondary_ids.add(output_id)
        if item["output_type"] not in {"table", "manifest"}:
            raise ConfigurationError(f"Invalid secondary output type for {output_id}")
        if not isinstance(item["requires_results_validated"], bool):
            raise ConfigurationError(f"{output_id}.requires_results_validated must be boolean")
        role = str(item["role"])
        if role != "internal_authority":
            raise ConfigurationError(
                f"Secondary interface output {output_id} must be explicitly internal_authority"
            )
        secondary_outputs.append(
            SecondaryOutputSpecification(
                output_id=output_id,
                output_type=str(item["output_type"]),
                role=role,
                builder=str(item["builder"]),
                source_attribute=str(item["source_attribute"]),
                requires_results_validated=bool(item["requires_results_validated"]),
            )
        )

    figure_formats = publication["figure_formats"]
    registries = publication["registries"]
    if not isinstance(figure_formats, list) or not all(isinstance(x, str) for x in figure_formats):
        raise ConfigurationError("output.figure_formats must be a string list")
    if not isinstance(registries, list) or not all(isinstance(x, str) for x in registries):
        raise ConfigurationError("output.registries must be a string list")
    return OutputContract(
        schema_version=str(raw["schema_version"]),
        run_root=run_root,
        latest_run_pointer=latest,
        sections=tuple(str(x) for x in sections),
        output_families=tuple(str(x) for x in families),
        filename_policy=cast(Mapping[str, Any], freeze(raw["filename_policy"])),
        write_policy=cast(Mapping[str, Any], freeze(raw["write_policy"])),
        hashing=cast(Mapping[str, Any], freeze(raw["hashing"])),
        csv_column_orders=cast(Mapping[str, Any], freeze(raw["csv_column_orders"])),
        tables=tuple(tables),
        secondary_outputs=tuple(secondary_outputs),
        registries=tuple(str(x) for x in registries),
        figure_formats=tuple(str(x) for x in figure_formats),
    )


def load_configuration_bundle(config_dir: str | Path | None = None) -> ConfigurationBundle:
    if config_dir is None:
        from .paths import discover_subproject_root

        project_root = discover_subproject_root()
        config_root = project_root / "config"
    else:
        config_root = Path(config_dir).resolve()
        project_root = config_root.parent
    file_hashes = configuration_file_hashes(config_root)
    operational_file_hashes = operational_configuration_file_hashes(config_root)
    analysis = load_analysis_contract(config_root / "analysis_contract.yml")
    data_schema = load_data_schema_contract(config_root / "data_schema_contract.yml")
    methods = load_method_authorities(config_root / "method_authorities.yml")
    output = load_output_contract(config_root / "output_contract.yml")
    figure = load_figure_contract(config_root / "figure_contract.yml")
    execution = load_execution_contract(config_root / EXECUTION_CONTRACT_FILENAME)
    package_version = _package_version(project_root)
    try:
        validate_configuration_semantics(analysis, data_schema, methods, output, figure)
    except DesignValidationError as exc:
        raise ConfigurationError(str(exc)) from exc
    digest = aggregate_configuration_sha256(file_hashes)
    operational_digest = aggregate_operational_configuration_sha256(operational_file_hashes)
    return ConfigurationBundle(
        analysis=analysis,
        data_schema=data_schema,
        methods=methods,
        output=output,
        figure=figure,
        execution=execution,
        file_hashes=file_hashes,
        configuration_sha256=digest,
        operational_file_hashes=operational_file_hashes,
        operational_configuration_sha256=operational_digest,
        package_version=package_version,
    )


def _resolve_analysis_source(analysis: AnalysisContract, source: str) -> Any:
    """Resolve a dotted reference inside the immutable analysis contract."""

    current: Any = analysis.as_mapping()
    for token in source.split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise ConfigurationError(f"Unknown analysis-contract source reference: {source!r}")
        current = current[token]
    return current


def rq1_spatial_parameters(analysis: AnalysisContract) -> RQ1SpatialParameters:
    spatial = analysis.research_questions["rq1"]["spatial"]
    global_cfg = spatial["global"]
    local = spatial["local"]
    weights = spatial["weights"]
    return RQ1SpatialParameters(
        global_permutations=int(global_cfg["permutations"]),
        local_permutations=int(local["permutations"]),
        random_seed=int(_resolve_analysis_source(analysis, str(global_cfg["seed_source"]))),
        local_p_value_method=str(local["p_value_method"]),
        local_permutation_scheme=str(local["permutation_scheme"]),
        local_upper_tail_comparison=str(local["upper_tail_comparison"]),
        local_tie_allocation=str(local["tie_allocation"]),
        local_multiply_smaller_tail_by_two=bool(local["multiply_smaller_tail_by_two"]),
        multiplicity_method=str(local["multiplicity_method"]),
        alpha=float(analysis.reproducibility["alpha"]),
        weight_method=str(weights["method"]),
        weight_order=str(weights["order"]),
        weight_transform=str(weights["transform"]),
        island_policy=str(weights["island_policy"]),
    )


def rq2_trend_parameters(analysis: AnalysisContract) -> RQ2TrendParameters:
    rq2 = analysis.research_questions["rq2"]
    test = rq2["inferential_test"]
    multiple = rq2["multiple_testing"]
    admissibility = test.get("reference_admissibility")
    if not isinstance(admissibility, Mapping):
        raise ConfigurationError(
            "RQ2 inferential_test.reference_admissibility must be a mapping"
        )
    requires_distinct = admissibility.get("requires_distinct_observations")
    on_ties = admissibility.get("on_ties")
    if not isinstance(requires_distinct, bool):
        raise ConfigurationError(
            "RQ2 reference_admissibility.requires_distinct_observations must be boolean"
        )
    if requires_distinct is not True or on_ties != "fail_closed":
        raise ConfigurationError(
            "RQ2 strict reference admissibility requires distinct observations and on_ties='fail_closed'"
        )
    return RQ2TrendParameters(
        effect_estimator=str(rq2["effect_estimator"]),
        inferential_test=str(test["method"]),
        empirical_cdf=str(test["empirical_cdf"]),
        rank_tie_contribution=str(test["rank_tie_contribution"]),
        requires_distinct_observations=requires_distinct,
        on_ties=str(on_ties),
        bandwidth_rule=str(test["bandwidth_rule"]),
        variance_floor=float(test["variance_floor"]),
        studentisation=str(test["studentisation"]),
        permutations=int(test["permutations"]),
        random_seed=int(_resolve_analysis_source(analysis, str(test["seed_source"]))),
        alternative=str(test["alternative"]),
        p_value_method=str(test["p_value_method"]),
        multiple_testing_method=str(multiple["method"]),
        family_size=int(multiple["family_size"]),
        alpha=float(_resolve_analysis_source(analysis, str(multiple["alpha_source"]))),
    )


def rq3_model_parameters(analysis: AnalysisContract) -> RQ3ModelParameters:
    rq3 = analysis.research_questions["rq3"]
    cluster = rq3["cluster"]
    predictors = tuple(cast(Mapping[str, Any], freeze(x)) for x in rq3["predictors"])
    factors = tuple(cast(Mapping[str, Any], freeze(x)) for x in rq3["factors"])
    std = rq3["standardised_probabilities"]
    vif = rq3["diagnostics"]["vif"]
    controls = rq3["computational_controls"]
    return RQ3ModelParameters(
        estimator=str(rq3["estimator"]),
        family=str(rq3["family"]),
        link=str(rq3["link"]),
        cluster_unit=str(cluster["unit"]),
        cluster_field=str(resolve_field_role(analysis, str(cluster["id_role"]))),
        working_correlation=str(rq3["working_correlation"]),
        covariance=str(rq3["covariance"]),
        reference_distribution=str(rq3["reference_distribution"]),
        predictors=predictors,
        factors=factors,
        vif_enabled=bool(vif["enabled"]),
        predictive_standardisation_method=str(std["method"]),
        predictive_quantiles=tuple(float(x) for x in std["focal_predictor_quantiles"]),
        tolerance=float(controls["tolerance"]),
        max_iterations=int(controls["max_iterations"]),
        max_step_halvings=int(controls["max_step_halvings"]),
    )


def satscan_parameters(analysis: AnalysisContract) -> SaTScanParameters:
    secondary = analysis.secondary_analysis
    external = secondary["external_execution"]
    spatial = secondary["spatial_support"]
    common = secondary["common"]
    return SaTScanParameters(
        engine=str(external["engine"]),
        engine_version_authority=str(external["engine_version_authority"]),
        analysis_type=str(common["analysis_type"]),
        cluster_type=str(common["cluster_type"]),
        max_spatial_percent=float(common["max_spatial_percent"]),
        max_temporal_months=int(common["max_temporal_months"]),
        monte_carlo_replicates=int(common["monte_carlo_replicates"]),
        alpha=float(_resolve_analysis_source(analysis, str(common["alpha_source"]))),
        reporting_method=str(common["reporting_method"]),
        geographical_overlap=bool(common["geographical_overlap"]),
        gini_optimised_reporting=bool(common["gini_optimised_reporting"]),
        coordinate_crs=str(spatial["coordinate_crs"]),
        coordinate_anchor_method=str(spatial["coordinate_anchor_method"]),
        spatial_window_shape=str(spatial["spatial_window_shape"]),
        report_cluster_rank=bool(common["report_cluster_rank"]),
        scientific_seed=int(_resolve_analysis_source(analysis, str(external["scientific_seed_source"]))),
        user_defined_random_seed_supported=bool(external["user_defined_random_seed_supported"]),
        user_defined_random_seed_parameter=(
            None
            if external.get("user_defined_random_seed_parameter") is None
            else str(external["user_defined_random_seed_parameter"])
        ),
        rng_authority=str(external["rng_authority"]),
        engine_rng_behaviour=str(external["engine_rng_behaviour"]),
    )


def build_realised_run_metadata(
    bundle: ConfigurationBundle,
    *,
    methods_spec_sha256: str,
    data_sha256: str,
    realised_sample_sizes: Mapping[str, int] | None = None,
    rq2_realised_bandwidth: int | None = None,
    realised_permutation_counts: Mapping[str, int] | None = None,
    rq3_design_columns: tuple[str, ...] = (),
    factor_references: Mapping[str, Any] | None = None,
    rq3_transformations: Mapping[str, str] | None = None,
    rq3_reporting_roles: Mapping[str, str] | None = None,
    spatial_weight_parameters: Mapping[str, Any] | None = None,
    satscan_parameter_hashes: Mapping[str, str] | None = None,
) -> RealisedRunMetadata:
    """Create immutable run metadata without inventing realised scientific values."""

    for label, digest in (("methods_spec_sha256", methods_spec_sha256), ("data_sha256", data_sha256)):
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ConfigurationError(f"{label} must be a lowercase SHA-256 digest")
    if rq2_realised_bandwidth is not None and rq2_realised_bandwidth <= 0:
        raise ConfigurationError("rq2_realised_bandwidth must be positive when realised")
    return RealisedRunMetadata(
        schema_version="rp1-realised-run-v1",
        config_sha256=bundle.configuration_sha256,
        methods_spec_sha256=methods_spec_sha256,
        data_sha256=data_sha256,
        realised_sample_sizes=cast(Mapping[str, int], freeze(realised_sample_sizes or {})),
        rq2_realised_bandwidth=rq2_realised_bandwidth,
        realised_permutation_counts=cast(Mapping[str, int], freeze(realised_permutation_counts or {})),
        rq3_design_columns=tuple(rq3_design_columns),
        factor_references=cast(Mapping[str, Any], freeze(factor_references or {})),
        rq3_transformations=cast(Mapping[str, str], freeze(rq3_transformations or {})),
        rq3_reporting_roles=cast(Mapping[str, str], freeze(rq3_reporting_roles or {})),
        spatial_weight_parameters=cast(Mapping[str, Any], freeze(spatial_weight_parameters or {})),
        satscan_parameter_hashes=cast(Mapping[str, str], freeze(satscan_parameter_hashes or {})),
    )


def _atomic_create_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise FileExistsError(path) from None
        tmp.unlink()
    finally:
        if tmp.exists():
            tmp.unlink()


def export_realised_configuration(bundle: ConfigurationBundle, run_dir: str | Path) -> Path:
    """Export canonical realised configuration into run-scoped scaffold evidence."""

    destination = Path(run_dir).resolve() / "00_scaffold" / "realised_configuration.json"
    payload = json.dumps(
        bundle.realised_dict(), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
    ) + "\n"
    _atomic_create_text(destination, payload)
    return destination


__all__ = [
    "SCHEMA_VERSION",
    "DATA_SCHEMA_VERSION",
    "CONFIG_FILENAMES",
    "AnalysisContract",
    "DataSchemaContract",
    "MethodAuthorityContract",
    "OutputContract",
    "FigureContract",
    "ConfigurationBundle",
    "EXECUTION_CONTRACT_FILENAME",
    "QUALIFICATION_CONTRACT_FILENAME",
    "ConfigurationError",
    "load_analysis_contract",
    "load_data_schema_contract",
    "load_method_authorities",
    "load_output_contract",
    "load_figure_contract",
    "load_configuration_bundle",
    "load_execution_contract",
    "load_qualification_contract",
    "configuration_file_hashes",
    "qualification_configuration_file_hashes",
    "aggregate_qualification_configuration_sha256",
    "aggregate_configuration_sha256",
    "sha256_realised_configuration",
    "export_realised_configuration",
    "rq1_spatial_parameters",
    "rq2_trend_parameters",
    "rq3_model_parameters",
    "satscan_parameters",
    "build_realised_run_metadata",
]
