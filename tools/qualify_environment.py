from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any, Iterable, Mapping
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PYTHON = (3, 13)
EXPECTED_ENVIRONMENT = "rp_ghana_fire"
QUALIFICATION_CONTRACT = Path("RP1_Project/rp1_analysis/config/qualification_contract.yml")
ROOT_EVIDENCE_FILES = ("qualification_report.json", "projection_evidence.json")


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return _is_within(left, right) or _is_within(right, left)


def _safe_relative_path(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty repository-relative path")
    token = value.replace("\\", "/")
    candidate = Path(token)
    if candidate.is_absolute() or ".." in candidate.parts or token.startswith("//"):
        raise ValueError(f"{field} must be a repository-relative path: {value!r}")
    if len(token) >= 2 and token[1] == ":":
        raise ValueError(f"{field} must be a repository-relative path: {value!r}")
    return candidate.as_posix()


def _bootstrap_package_specs(repository_root: Path) -> tuple[dict[str, str], ...]:
    """Read only the package/source mapping needed before project imports are trusted.

    The full typed contract is loaded after operational import-origin checks.  This
    small bootstrap reader does not define a second policy: every value comes from
    the canonical qualification contract and is subsequently revalidated by the
    production configuration loader.
    """

    path = repository_root / QUALIFICATION_CONTRACT
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or not isinstance(raw.get("packages"), list):
        raise ValueError("qualification contract does not define a packages list")
    specs: list[dict[str, str]] = []
    seen_modules: set[str] = set()
    seen_distributions: set[str] = set()
    for index, item in enumerate(raw["packages"]):
        if not isinstance(item, Mapping):
            raise ValueError(f"qualification packages[{index}] must be a mapping")
        required = {"module", "distribution", "project_root", "source_root"}
        if set(item) != required:
            raise ValueError(
                f"qualification packages[{index}] must contain exactly {sorted(required)!r}"
            )
        module = item["module"]
        distribution = item["distribution"]
        if not isinstance(module, str) or not module or not isinstance(distribution, str) or not distribution:
            raise ValueError(f"qualification packages[{index}] module/distribution must be non-empty strings")
        if module in seen_modules or distribution in seen_distributions:
            raise ValueError("qualification package modules/distributions must be unique")
        seen_modules.add(module)
        seen_distributions.add(distribution)
        project_root = _safe_relative_path(str(item["project_root"]), field=f"packages[{index}].project_root")
        source_root = _safe_relative_path(str(item["source_root"]), field=f"packages[{index}].source_root")
        try:
            Path(source_root).relative_to(Path(project_root))
        except ValueError as exc:
            raise ValueError(f"packages[{index}].source_root must lie within project_root") from exc
        specs.append(
            {
                "module": module,
                "distribution": distribution,
                "project_root": project_root,
                "source_root": source_root,
            }
        )
    if not specs:
        raise ValueError("qualification packages list is empty")
    return tuple(specs)


def _project_version(pyproject: Path) -> str:
    with pyproject.open("rb") as handle:
        raw = tomllib.load(handle)
    project = raw["project"]
    if "version" in project:
        return str(project["version"])
    dynamic = raw.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version", {})
    attr = dynamic.get("attr")
    if attr == "mv_firms_panels.version.__version__":
        version_file = pyproject.parent / "src/mv_firms_panels/version.py"
        namespace: dict[str, Any] = {}
        exec(compile(version_file.read_text(encoding="utf-8"), str(version_file), "exec"), namespace)
        return str(namespace["__version__"])
    raise ValueError(f"Cannot determine project version from {pyproject}")


def expected_package_versions(
    repository_root: Path,
    specs: Iterable[Mapping[str, str]],
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for item in specs:
        project_root = repository_root / item["project_root"]
        result[item["module"]] = (
            item["distribution"],
            _project_version(project_root / "pyproject.toml"),
        )
    return result


def operational_package_state(
    repository_root: Path,
    specs: Iterable[Mapping[str, str]],
) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for item in specs:
        module_name = item["module"]
        distribution = item["distribution"]
        project_root = repository_root / item["project_root"]
        expected_source_root = (repository_root / item["source_root"]).resolve()
        version = _project_version(project_root / "pyproject.toml")
        module = importlib.import_module(module_name)
        if module.__file__ is None:
            raise RuntimeError(f"{module_name} has no filesystem import origin")
        origin = Path(module.__file__).resolve()
        observed = importlib.metadata.version(distribution)
        origin_ok = origin.is_relative_to(expected_source_root)
        version_ok = observed == version
        state[module_name] = {
            "authority": "operational_checkout",
            "distribution": distribution,
            "expected_version": version,
            "observed_version": observed,
            "expected_source_root": str(expected_source_root),
            "origin": str(origin),
            "origin_in_intended_operational_checkout": origin_ok,
            "status": "PASS" if origin_ok and version_ok else "FAIL",
        }
    return state


def _package_states_pass(states: Mapping[str, Any]) -> bool:
    return bool(states) and all(
        isinstance(value, Mapping) and value.get("status") == "PASS"
        for value in states.values()
    )


def _environment_identity(*, defer_native_environment: bool) -> dict[str, Any]:
    actual_env = os.environ.get("CONDA_DEFAULT_ENV")
    python_ok = sys.version_info[:2] == EXPECTED_PYTHON
    env_ok = actual_env == EXPECTED_ENVIRONMENT
    if not python_ok:
        status = "FAIL"
        reason = "Canonical qualification requires Python 3.13; this check is not deferrable."
    elif env_ok:
        status = "PASS"
        reason = None
    elif defer_native_environment:
        status = "DEFERRED"
        reason = (
            "Native canonical Conda identity is unavailable in this hosted run; "
            "the underlying lifecycle is still exercised without falsifying CONDA_DEFAULT_ENV."
        )
    else:
        status = "FAIL"
        reason = "Canonical qualification requires the expected Conda environment and Python 3.13."
    return {
        "expected_conda_env": EXPECTED_ENVIRONMENT,
        "actual_conda_env": actual_env,
        "expected_python": "3.13",
        "actual_python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_identity_ok": python_ok,
        "conda_identity_ok": env_ok,
        "status": status,
        "reason": reason,
    }


def _apply_pip_check_policy(
    step: Mapping[str, Any],
    *,
    environment_identity: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Classify ``pip check`` without falsely qualifying a non-canonical host.

    Dependency closure is a hard gate in the canonical environment.  When the
    canonical Conda identity is explicitly deferred for hosted testing, a
    host-level ``pip check`` failure is preserved as evidence but is itself
    deferred rather than misrepresented as a product failure.  Python 3.13 is
    still non-deferrable through :func:`_environment_identity`.
    """

    state = dict(step)
    if state.get("status") == "PASS":
        return state, False
    if environment_identity.get("status") == "DEFERRED":
        state["raw_status"] = state.get("status")
        state["status"] = "DEFERRED"
        state["reason"] = (
            "pip check was executed in a non-canonical hosted environment. "
            "Its dependency-closure result is retained, but canonical dependency "
            "closure must be rerun in the native rp_ghana_fire environment."
        )
        return state, True
    return state, False


def run_step(
    name: str,
    command: list[str],
    logs_dir: Path,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    duration = time.monotonic() - started
    logs_dir.mkdir(parents=True, exist_ok=True)
    log = logs_dir / f"{name}.log"
    log.write_text(result.stdout, encoding="utf-8", newline="\n")
    return {
        "command": command,
        "cwd": str(cwd.resolve()),
        "returncode": result.returncode,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "duration_seconds": round(duration, 6),
        "log": str(log),
    }


def _isolated_import_command(
    target: Path,
    expected: Mapping[str, tuple[str, str]],
) -> str:
    values = [(module, distribution, version) for module, (distribution, version) in expected.items()]
    return (
        "import importlib,importlib.metadata,json,pathlib;"
        f"target=pathlib.Path({str(target)!r}).resolve();"
        f"expected={values!r};"
        "out={};fail=[];"
        "\nfor module_name,distribution,version in expected:\n"
        " m=importlib.import_module(module_name); p=pathlib.Path(m.__file__).resolve(); "
        "v=importlib.metadata.version(distribution); "
        "out[module_name]={'distribution':distribution,'version':v,'origin':str(p)}; "
        "fail.append(module_name) if (v!=version or not p.is_relative_to(target)) else None\n"
        "print(json.dumps(out,sort_keys=True));"
        "raise SystemExit(0 if not fail else 2)"
    )


def _isolated_version_command(
    target: Path,
    *,
    expected_version: str,
    expected_analysis_schema: str,
    expected_data_schema: str,
) -> str:
    """Return a wheel-only version/schema probe that needs no source checkout.

    The ordinary ``rp1-analysis version`` command is source-product aware and
    may legitimately need the extracted governed configuration.  Isolated wheel
    qualification instead verifies package/distribution version, schema
    constants and import origin directly from the installed artefact.
    """

    return (
        "import importlib.metadata,json,pathlib;"
        "import rp1_analysis_v1 as package;"
        "from rp1_analysis_v1.config import SCHEMA_VERSION,DATA_SCHEMA_VERSION;"
        f"target=pathlib.Path({str(target)!r}).resolve();"
        "origin=pathlib.Path(package.__file__).resolve();"
        "metadata_version=importlib.metadata.version('rp1-analysis-v1');"
        f"expected_version={expected_version!r};"
        f"expected_analysis_schema={expected_analysis_schema!r};"
        f"expected_data_schema={expected_data_schema!r};"
        "payload={'package_version':package.__version__,'distribution_version':metadata_version,"
        "'analysis_schema':SCHEMA_VERSION,'data_schema':DATA_SCHEMA_VERSION,'origin':str(origin)};"
        "print(json.dumps(payload,sort_keys=True));"
        "ok=(origin.is_relative_to(target) and package.__version__==expected_version and "
        "metadata_version==expected_version and SCHEMA_VERSION==expected_analysis_schema and "
        "DATA_SCHEMA_VERSION==expected_data_schema);"
        "raise SystemExit(0 if ok else 2)"
    )


def _load_runtime_authorities(repository_root: Path) -> dict[str, Any]:
    """Load the typed qualification contract only after operational origins pass."""

    config_module = importlib.import_module("rp1_analysis_v1.config")
    projection_module = importlib.import_module("rp1_analysis_v1.source_projection")
    contract_path = repository_root / QUALIFICATION_CONTRACT
    contract = config_module.load_qualification_contract(contract_path)
    raw_hashes = config_module.qualification_configuration_file_hashes(contract_path.parent)
    hashes = dict(raw_hashes)
    return {
        "contract": contract,
        "qualification_config_hashes": hashes,
        "qualification_config_sha256": config_module.aggregate_qualification_configuration_sha256(hashes),
        "analysis_schema": config_module.SCHEMA_VERSION,
        "data_schema": config_module.DATA_SCHEMA_VERSION,
        "inventory_governed_source": projection_module.inventory_governed_source,
        "project_governed_source": projection_module.project_governed_source,
        "verify_projected_inventory": projection_module.verify_projected_inventory,
        "probe_projected_imports": projection_module.probe_projected_imports,
        "projected_import_environment": projection_module.projected_import_environment,
        "remove_generated_artifacts_from_projection": projection_module.remove_generated_artifacts_from_projection,
        "write_projection_evidence": projection_module.write_projection_evidence,
    }


def _clear_stale_root_evidence(repository_root: Path, evidence_dir: Path) -> tuple[str, ...]:
    """Remove only qualifier-owned root evidence before starting a new run.

    Runtime/build/install directories are recreated later from the fully validated
    qualification contract.  These two root-level files are also qualifier-owned,
    so a failed or interrupted prior run must not leave them looking current.
    """

    repository_root = repository_root.resolve()
    evidence_dir = evidence_dir.resolve()
    if _paths_overlap(repository_root, evidence_dir):
        raise ValueError("evidence directory must be external to and non-overlapping with the repository")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    removed: list[str] = []
    for name in ROOT_EVIDENCE_FILES:
        path = evidence_dir / name
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(name)
    return tuple(removed)


def _prepare_external_workspace(
    repository_root: Path,
    evidence_dir: Path,
    contract: Any,
) -> dict[str, Path]:
    if _paths_overlap(repository_root, evidence_dir):
        raise ValueError("evidence directory must be external to and non-overlapping with the repository")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    allowed = set(contract.projection.allowed_temporary_subdirectories)
    required = {"clean_projection", "wheels", "isolated_install", "logs", "runtime"}
    missing = required.difference(allowed)
    if missing:
        raise ValueError(f"qualification contract does not authorise required external roots: {sorted(missing)!r}")

    paths = {name: evidence_dir / name for name in required}
    for path in paths.values():
        if path.exists() or path.is_symlink():
            if path.is_symlink():
                raise ValueError(f"qualification external root may not be a symlink: {path}")
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=False)
    return paths


def _base_environment(runtime_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "RP_RUN_NATIVE_PLOT_SMOKE": "1",
            "MPLCONFIGDIR": str(runtime_dir / "mplconfig"),
            "PYTHONPYCACHEPREFIX": str(runtime_dir / "pycache"),
            "PIP_CACHE_DIR": str(runtime_dir / "pip_cache"),
        }
    )
    for name in ("mplconfig", "pycache", "pip_cache"):
        (runtime_dir / name).mkdir(parents=True, exist_ok=True)
    return env


def _parse_pytest_summary(log_path: Path) -> dict[str, int | None]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    import re

    result: dict[str, int | None] = {"collected": None, "passed": None, "failed": None, "skipped": None, "warnings": None}
    collection = re.search(r"(\d+) tests? collected", text)
    if collection:
        result["collected"] = int(collection.group(1))
    for key in ("passed", "failed", "skipped", "warnings"):
        matches = re.findall(rf"(\d+) {key}", text)
        if matches:
            result[key] = int(matches[-1])
    if result["collected"] is None:
        totals = [value for key, value in result.items() if key in {"passed", "failed", "skipped"} and isinstance(value, int)]
        if totals:
            result["collected"] = sum(totals)
    return result



def _wheel_build_command(
    project_root: Path,
    wheel_dir: Path,
    *,
    allow_hosted_fallback: bool,
) -> tuple[list[str], str]:
    """Return the canonical build command, or an explicit hosted-only fallback.

    The canonical environment declares ``python-build`` and therefore uses
    ``python -m build``.  Some hosted qualification environments are network
    isolated and do not provide that module.  When native environment identity
    is explicitly deferred, ``pip wheel --no-build-isolation`` exercises the
    same project build backend from the same clean projected source without
    pretending that the canonical build frontend was available.
    """

    if importlib.util.find_spec("build") is not None:
        return (
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(wheel_dir),
                str(project_root),
            ],
            "python-build",
        )
    if not allow_hosted_fallback:
        return (
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(wheel_dir),
                str(project_root),
            ],
            "python-build-unavailable",
        )
    return (
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(project_root),
        ],
        "hosted-pip-wheel-fallback",
    )

def qualify(
    *,
    repository_root: Path,
    evidence_dir: Path,
    defer_native_environment: bool = False,
) -> tuple[dict[str, Any], int]:
    repository_root = repository_root.resolve()
    evidence_dir = evidence_dir.resolve()
    if not repository_root.is_dir():
        raise ValueError(f"repository root does not exist: {repository_root}")
    if _paths_overlap(repository_root, evidence_dir):
        raise ValueError("evidence directory must be external to and non-overlapping with the repository")

    stale_root_evidence_removed = _clear_stale_root_evidence(repository_root, evidence_dir)
    report: dict[str, Any] = {
        "schema": "rp1-analysis-v1-qualification-lifecycle-v3",
        "qualification_run_id": uuid.uuid4().hex,
        "stale_root_evidence_removed": list(stale_root_evidence_removed),
        "repository_root": str(repository_root),
        "evidence_root": str(evidence_dir),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "conda_default_env": os.environ.get("CONDA_DEFAULT_ENV"),
        "policy": {
            "pytest": "HARD_GATE",
            "black": "DEVELOPMENT_ONLY_NOT_EXECUTED",
            "ruff": "DEVELOPMENT_ONLY_NOT_EXECUTED",
            "mypy": "DEVELOPMENT_ONLY_NOT_EXECUTED",
        },
        "operational_checks": {},
        "projection_checks": {},
        "source_checks": {},
        "build_checks": {},
        "isolated_install_checks": {},
        "deferred_checks": [],
        "hard_failures": [],
    }

    environment_identity = _environment_identity(defer_native_environment=defer_native_environment)
    report["operational_checks"]["environment_identity"] = environment_identity
    if environment_identity["status"] == "DEFERRED":
        report["deferred_checks"].append(
            {
                "id": "native_canonical_conda_end_to_end",
                "reason": environment_identity["reason"],
                "required_stage": "final local L01",
            }
        )
    elif environment_identity["status"] != "PASS":
        report["hard_failures"].append("operational:environment_identity")

    try:
        specs = _bootstrap_package_specs(repository_root)
        package_state = operational_package_state(repository_root, specs)
        report["operational_checks"]["packages"] = package_state
        if not _package_states_pass(package_state):
            report["hard_failures"].append("operational:package_origins_or_versions")
    except Exception as exc:
        specs = ()
        report["operational_checks"]["packages"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }
        report["hard_failures"].append("operational:package_origins_or_versions")

    if report["hard_failures"] and not specs:
        report["status"] = "FAIL"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "qualification_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        return report, 1

    if not _package_states_pass(report["operational_checks"].get("packages", {})):
        report["status"] = "FAIL"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "qualification_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        return report, 1

    try:
        runtime = _load_runtime_authorities(repository_root)
        contract = runtime["contract"]
        report["operational_checks"]["qualification_contract"] = {
            "path": str((repository_root / QUALIFICATION_CONTRACT).resolve()),
            "schema_version": contract.schema_version,
            "contract_id": contract.contract_id,
            "file_hashes": runtime["qualification_config_hashes"],
            "aggregate_sha256": runtime["qualification_config_sha256"],
            "status": "PASS",
        }
    except Exception as exc:
        report["operational_checks"]["qualification_contract"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }
        report["hard_failures"].append("operational:qualification_contract")
        report["status"] = "FAIL"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "qualification_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        return report, 1

    try:
        external = _prepare_external_workspace(repository_root, evidence_dir, contract)
    except Exception as exc:
        report["hard_failures"].append("external_workspace")
        report["external_workspace_error"] = f"{type(exc).__name__}: {exc}"
        report["status"] = "FAIL"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "qualification_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        return report, 1

    logs_dir = external["logs"]
    runtime_dir = external["runtime"]
    wheel_dir = external["wheels"]
    install_target = external["isolated_install"]
    projection_root = external["clean_projection"]
    common_env = _base_environment(runtime_dir)

    operational_step = run_step(
        "pip_check",
        [sys.executable, "-m", "pip", "check"],
        logs_dir,
        cwd=repository_root,
        env=common_env,
    )
    operational_step, pip_check_deferred = _apply_pip_check_policy(
        operational_step,
        environment_identity=environment_identity,
    )
    report["operational_checks"]["pip_check"] = operational_step
    if pip_check_deferred:
        report["deferred_checks"].append(
            {
                "id": "native_canonical_pip_check",
                "reason": operational_step["reason"],
                "required_stage": "final local L01",
            }
        )
    elif operational_step["status"] != "PASS":
        report["hard_failures"].append("operational:pip_check")

    # Projection is constructed from a frozen path/size/SHA-256 source inventory.
    try:
        expected_inventory = runtime["inventory_governed_source"](repository_root, contract)
        projection_result = runtime["project_governed_source"](
            repository_root,
            projection_root,
            contract,
            expected_inventory=expected_inventory,
        )
        projected_inventory = runtime["verify_projected_inventory"](
            projection_root, expected_inventory
        )
        import_probe = runtime["probe_projected_imports"](
            projection_root,
            contract,
            python_executable=sys.executable,
            cwd=projection_root,
        )
        runtime["write_projection_evidence"](
            projection_result, evidence_dir / "projection_evidence.json"
        )
        report["projection_checks"] = {
            "status": "PASS",
            "source_file_count": len(expected_inventory.entries),
            "source_inventory_sha256": expected_inventory.inventory_sha256,
            "projected_file_count": len(projected_inventory.entries),
            "projected_inventory_sha256": projected_inventory.inventory_sha256,
            "excluded_generated_artifacts": [item.to_dict() for item in expected_inventory.exclusions],
            "import_probe": import_probe,
            "projection_root": str(projection_root),
        }
    except Exception as exc:
        report["projection_checks"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "projection_root": str(projection_root),
        }
        report["hard_failures"].append("projection")
        report["status"] = "FAIL"
        (evidence_dir / "qualification_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        return report, 1

    projected_env = runtime["projected_import_environment"](
        projection_root,
        contract,
        base_environment=common_env,
    )

    source_steps: dict[str, Any] = {}
    source_steps["compileall"] = run_step(
        "compileall",
        [sys.executable, "-m", "compileall", "-q", "."],
        logs_dir,
        cwd=projection_root,
        env=projected_env,
    )
    source_steps["stage1_example_regeneration"] = run_step(
        "stage1_example_regeneration",
        ["geo-prep", "run", "--config", "configs/example_acz.yaml", "--run-id", "example_acz"],
        logs_dir,
        cwd=projection_root / "geo_data_prep",
        env=projected_env,
    )
    try:
        source_steps["post_stage1_cleanup"] = {
            "status": "PASS",
            "removed": list(runtime["remove_generated_artifacts_from_projection"](projection_root, contract)),
        }
        runtime["verify_projected_inventory"](projection_root, expected_inventory)
        source_steps["post_stage1_inventory"] = {"status": "PASS"}
    except Exception as exc:
        source_steps["post_stage1_inventory"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }

    source_steps["pytest_collect"] = run_step(
        "pytest_collect",
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-p", "no:cacheprovider", "--collect-only", "-q"],
        logs_dir,
        cwd=projection_root,
        env=projected_env,
    )
    source_steps["full_pytest"] = run_step(
        "full_pytest",
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-p", "no:cacheprovider", "-q"],
        logs_dir,
        cwd=projection_root,
        env=projected_env,
    )
    source_steps["full_pytest"]["summary"] = _parse_pytest_summary(logs_dir / "full_pytest.log")

    try:
        source_steps["post_pytest_cleanup"] = {
            "status": "PASS",
            "removed": list(runtime["remove_generated_artifacts_from_projection"](projection_root, contract)),
        }
        runtime["verify_projected_inventory"](projection_root, expected_inventory)
        source_steps["post_pytest_inventory"] = {"status": "PASS"}
    except Exception as exc:
        source_steps["post_pytest_inventory"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }

    source_steps["validate_inputs"] = run_step(
        "validate_inputs",
        [sys.executable, "RP1_Project/rp1_analysis/scripts/validate_inputs.py"],
        logs_dir,
        cwd=projection_root,
        env=projected_env,
    )
    source_steps["reference_methods"] = run_step(
        "reference_methods",
        [sys.executable, "RP1_Project/rp1_analysis/scripts/qualify_reference_methods.py"],
        logs_dir,
        cwd=projection_root,
        env=projected_env,
    )
    source_steps["version_smoke"] = run_step(
        "version_smoke",
        [sys.executable, "-m", "rp1_analysis_v1.cli", "version"],
        logs_dir,
        cwd=projection_root,
        env=projected_env,
    )
    source_steps["help_smoke"] = run_step(
        "help_smoke",
        [sys.executable, "-m", "rp1_analysis_v1.cli", "--help"],
        logs_dir,
        cwd=projection_root,
        env=projected_env,
    )
    try:
        source_steps["prebuild_cleanup"] = {
            "status": "PASS",
            "removed": list(runtime["remove_generated_artifacts_from_projection"](projection_root, contract)),
        }
        runtime["verify_projected_inventory"](projection_root, expected_inventory)
        source_steps["prebuild_inventory"] = {"status": "PASS"}
    except Exception as exc:
        source_steps["prebuild_inventory"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }

    report["source_checks"] = source_steps
    for name, state in source_steps.items():
        if isinstance(state, Mapping) and state.get("status") != "PASS":
            report["hard_failures"].append(f"source:{name}")

    build_steps: dict[str, Any] = {}
    expected_versions = expected_package_versions(repository_root, specs)
    if not any(item.startswith("source:") for item in report["hard_failures"]):
        for item in contract.packages:
            key = item.module
            project_root = (projection_root / item.project_root).resolve()
            if not project_root.is_relative_to(projection_root):
                build_steps[f"build_{key}_wheel"] = {
                    "status": "FAIL",
                    "reason": "project root escaped clean projection",
                }
                continue
            build_command, build_frontend = _wheel_build_command(
                project_root,
                wheel_dir,
                allow_hosted_fallback=defer_native_environment,
            )
            build_steps[f"build_{key}_wheel"] = run_step(
                f"build_{key}_wheel",
                build_command,
                logs_dir,
                cwd=projection_root,
                env=projected_env,
            )
            build_steps[f"build_{key}_wheel"]["build_frontend"] = build_frontend

        try:
            build_steps["post_build_cleanup"] = {
                "status": "PASS",
                "removed": list(runtime["remove_generated_artifacts_from_projection"](projection_root, contract)),
            }
            runtime["verify_projected_inventory"](projection_root, expected_inventory)
            build_steps["post_build_inventory"] = {"status": "PASS"}
        except Exception as exc:
            build_steps["post_build_inventory"] = {
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
    else:
        build_steps["wheel_builds"] = {
            "status": "FAIL",
            "reason": "source qualification hard gate failed; wheel build not authoritative",
        }

    wheels = sorted(wheel_dir.glob("*.whl"))
    build_steps["wheel_inventory"] = {
        "status": "PASS" if len(wheels) == len(contract.packages) else "FAIL",
        "expected_count": len(contract.packages),
        "observed_count": len(wheels),
        "wheels": [path.name for path in wheels],
        "source_authority": "clean_projection",
    }
    report["build_checks"] = build_steps
    for name, state in build_steps.items():
        if isinstance(state, Mapping) and state.get("status") != "PASS":
            report["hard_failures"].append(f"build:{name}")

    isolated_steps: dict[str, Any] = {}
    if build_steps["wheel_inventory"]["status"] == "PASS" and not any(
        item.startswith("build:") for item in report["hard_failures"]
    ):
        # The install target was already recreated by _prepare_external_workspace.
        isolated_steps["isolated_install"] = run_step(
            "isolated_install",
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-cache-dir",
                "--target",
                str(install_target),
                *[str(path) for path in wheels],
            ],
            logs_dir,
            cwd=evidence_dir,
            env=common_env,
        )
        isolated_env = common_env.copy()
        isolated_env["PYTHONPATH"] = str(install_target)
        isolated_env["PYTHONNOUSERSITE"] = "1"
        isolated_env.pop("RP1_QUALIFICATION_IMPORT_MODE", None)
        isolated_env.pop("RP1_QUALIFICATION_PROJECT_ROOT", None)
        with tempfile.TemporaryDirectory(prefix="rp1-isolated-import-", dir=str(runtime_dir)) as temp_cwd:
            isolated_steps["isolated_import"] = run_step(
                "isolated_import",
                [sys.executable, "-c", _isolated_import_command(install_target, expected_versions)],
                logs_dir,
                cwd=Path(temp_cwd),
                env=isolated_env,
            )
            isolated_steps["isolated_version_smoke"] = run_step(
                "isolated_version_smoke",
                [
                    sys.executable,
                    "-c",
                    _isolated_version_command(
                        install_target,
                        expected_version=expected_versions["rp1_analysis_v1"][1],
                        expected_analysis_schema=runtime["analysis_schema"],
                        expected_data_schema=runtime["data_schema"],
                    ),
                ],
                logs_dir,
                cwd=Path(temp_cwd),
                env=isolated_env,
            )
            isolated_steps["isolated_help_smoke"] = run_step(
                "isolated_help_smoke",
                [sys.executable, "-m", "rp1_analysis_v1.cli", "--help"],
                logs_dir,
                cwd=Path(temp_cwd),
                env=isolated_env,
            )
    else:
        isolated_steps["isolated_install"] = {
            "status": "FAIL",
            "reason": "clean wheel authority unavailable",
        }
        isolated_steps["isolated_import"] = {
            "status": "FAIL",
            "reason": "isolated installation unavailable",
        }
    report["isolated_install_checks"] = isolated_steps
    for name, state in isolated_steps.items():
        if isinstance(state, Mapping) and state.get("status") != "PASS":
            report["hard_failures"].append(f"isolated:{name}")

    # De-duplicate failures while preserving lifecycle order.
    report["hard_failures"] = list(dict.fromkeys(report["hard_failures"]))
    report["status"] = "PASS" if not report["hard_failures"] else "FAIL"
    report["native_environment_deferred"] = environment_identity["status"] == "DEFERRED"
    report_path = evidence_dir / "qualification_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report, 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Qualify the canonical RP1 operational environment, clean governed source projection, "
            "and isolated wheel installation."
        )
    )
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument(
        "--defer-native-environment",
        action="store_true",
        help=(
            "Hosted-test mode only: record a non-canonical Conda identity as DEFERRED rather than PASS. "
            "Normal local qualification must omit this flag."
        ),
    )
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir).resolve()
    try:
        report, returncode = qualify(
            repository_root=ROOT,
            evidence_dir=evidence_dir,
            defer_native_environment=bool(args.defer_native_environment),
        )
    except Exception as exc:
        print(f"RP1_ANALYSIS_V1_LOCAL_QUALIFICATION=FAIL\n{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"QUALIFICATION_REPORT={evidence_dir / 'qualification_report.json'}")
    if report.get("status") == "PASS" and report.get("native_environment_deferred"):
        print("RP1_ANALYSIS_V1_LOCAL_QUALIFICATION=PASS_WITH_NATIVE_ENVIRONMENT_DEFERRED")
    else:
        print(f"RP1_ANALYSIS_V1_LOCAL_QUALIFICATION={report.get('status')}")
    for failure in report.get("hard_failures", []):
        print(f"HARD_FAILURE={failure}")
    for deferred in report.get("deferred_checks", []):
        print(f"DEFERRED_CHECK={deferred.get('id')}")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
