from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import sys
import tomllib
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

EXPECTED_DISTRIBUTION = "rp1-analysis-v1"
EXPECTED_PYTHON = (3, 13)
CANONICAL_CONDA_ENV = "rp_ghana_fire"
PROJECTED_IMPORT_MODE_ENV = "RP1_QUALIFICATION_IMPORT_MODE"
PROJECTED_PROJECT_ROOT_ENV = "RP1_QUALIFICATION_PROJECT_ROOT"
PROJECTED_IMPORT_MODE = "projected_source"


class InstallationMode(StrEnum):
    """Operational package-origin contract for a qualification context."""

    SOURCE = "source"
    DISTRIBUTION = "distribution"


def requested_kernel(argv: Sequence[str], *, default: str) -> str:
    """Return the requested Jupyter kernel without importing project code."""

    args = list(argv)
    for index, argument in enumerate(args):
        if argument == "--kernel" and index + 1 < len(args):
            return args[index + 1]
        if argument.startswith("--kernel="):
            value = argument.split("=", 1)[1]
            return value or default
    return default


def _project_root(script_path: Path) -> Path:
    anchor = script_path.expanduser().resolve()
    for candidate in (anchor.parent, *anchor.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "config" / "analysis_contract.yml").is_file()
            and (candidate / "src" / "rp1_analysis_v1").is_dir()
        ):
            return candidate
    raise RuntimeError(
        "Unable to identify the RP1 Analysis v1 project root " f"from script path: {anchor}"
    )


def _expected_version(project_root: Path) -> str:
    with (project_root / "pyproject.toml").open("rb") as handle:
        raw = tomllib.load(handle)
    return str(raw["project"]["version"])


def _editable_project_location(
    distribution: importlib.metadata.Distribution,
) -> Path | None:
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    directory_info = payload.get("dir_info")
    if not isinstance(directory_info, dict) or directory_info.get("editable") is not True:
        return None

    url = payload.get("url")
    if not isinstance(url, str):
        return None

    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None

    return Path(url2pathname(unquote(parsed.path))).expanduser().resolve()


def _distribution_root(distribution: importlib.metadata.Distribution) -> Path | None:
    try:
        return Path(distribution.locate_file("")).expanduser().resolve()
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _normalise_mode(mode: InstallationMode | str) -> InstallationMode:
    try:
        return InstallationMode(mode)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in InstallationMode)
        raise ValueError(
            f"Unsupported installation mode {mode!r}; expected one of: {allowed}"
        ) from exc


def _remediation_action(*, mode: InstallationMode, project_root: Path) -> str:
    if mode is InstallationMode.SOURCE:
        return (
            "use the verified source tree with Python 3.13 and install the analysis package "
            f"editable from {project_root} (python -m pip install -e {project_root}), then "
            "verify that rp1_analysis_v1 imports from this source tree"
        )
    version = _expected_version(project_root)
    return (
        f"use a clean Python 3.13 environment and install the built rp1-analysis-v1=={version} "
        "distribution non-editably, then verify that rp1_analysis_v1 imports from the "
        "environment's installed distribution rather than a source checkout"
    )


def _projected_source_context(project_root: Path) -> tuple[bool, list[str]]:
    """Validate an explicitly requested clean-projection source context.

    In projected qualification the active interpreter may still contain
    editable distribution metadata for the operational checkout.  That
    metadata is not an import authority.  The explicit context is accepted
    only when its declared project root exactly matches the project root
    discovered from the executing script; actual module origin checks remain
    mandatory.
    """

    raw_mode = os.environ.get(PROJECTED_IMPORT_MODE_ENV)
    if raw_mode != PROJECTED_IMPORT_MODE:
        return False, []

    raw_root = os.environ.get(PROJECTED_PROJECT_ROOT_ENV)
    if not raw_root:
        return True, [
            f"{PROJECTED_PROJECT_ROOT_ENV} is required when "
            f"{PROJECTED_IMPORT_MODE_ENV}={PROJECTED_IMPORT_MODE!r}"
        ]
    try:
        declared_root = Path(raw_root).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return True, [
            f"invalid {PROJECTED_PROJECT_ROOT_ENV}: {type(exc).__name__}: {exc}"
        ]
    if declared_root != project_root:
        return True, [
            "projected-source qualification root mismatch: "
            f"declared {declared_root}, executing project {project_root}"
        ]
    return True, []


def operational_preflight(
    *,
    script_path: Path,
    kernel: str,
    mode: InstallationMode | str = InstallationMode.SOURCE,
) -> tuple[dict[str, object], list[str]]:
    """Collect import-safe runtime diagnostics for an operational script."""

    installation_mode = _normalise_mode(mode)
    project_root = _project_root(script_path)
    configuration_path = project_root / "config" / "analysis_contract.yml"
    expected_version = _expected_version(project_root)
    current_source = (project_root / "src").resolve()
    interpreter_prefix = Path(sys.prefix).resolve()
    # Projected-source markers are authoritative only for source qualification.
    # An explicit distribution-mode check must remain independent of inherited
    # source-qualification environment variables (for example when a test or
    # wrapper deliberately validates both modes in the same process).
    if installation_mode is InstallationMode.SOURCE:
        projected_source_context, projected_context_issues = _projected_source_context(
            project_root
        )
    else:
        projected_source_context, projected_context_issues = False, []

    issues: list[str] = list(projected_context_issues)

    package_version: str | None = None
    package_origin: str | None = None
    editable_project_location: str | None = None
    distribution_root: str | None = None

    distribution: importlib.metadata.Distribution | None = None

    try:
        distribution = importlib.metadata.distribution(EXPECTED_DISTRIBUTION)
        package_version = distribution.version
    except importlib.metadata.PackageNotFoundError:
        if not projected_source_context:
            issues.append(f"{EXPECTED_DISTRIBUTION} is not installed for this Python interpreter")

    if (
        package_version is not None
        and package_version != expected_version
        and not projected_source_context
    ):
        issues.append(
            f"{EXPECTED_DISTRIBUTION} version mismatch: "
            f"expected {expected_version}, observed {package_version}"
        )

    editable: Path | None = None
    if distribution is not None:
        editable = _editable_project_location(distribution)
        if editable is not None:
            editable_project_location = str(editable)
        observed_distribution_root = _distribution_root(distribution)
        if observed_distribution_root is not None:
            distribution_root = str(observed_distribution_root)

    try:
        spec = importlib.util.find_spec("rp1_analysis_v1")
    except (ImportError, AttributeError, ValueError) as exc:
        issues.append(
            "unable to resolve rp1_analysis_v1 import specification: "
            f"{type(exc).__name__}: {exc}"
        )
        spec = None

    origin: Path | None = None
    if spec is None or spec.origin is None:
        issues.append("rp1_analysis_v1 is not importable by this Python interpreter")
    else:
        origin = Path(spec.origin).expanduser().resolve()
        package_origin = str(origin)

    if installation_mode is InstallationMode.SOURCE:
        if (
            editable is not None
            and editable != project_root
            and not projected_source_context
        ):
            issues.append(
                "source qualification found an editable installation from a different project "
                f"checkout: {editable}"
            )
        if origin is not None and not origin.is_relative_to(current_source):
            issues.append(
                "source qualification requires rp1_analysis_v1 to import from the verified "
                f"current source tree {current_source}; observed {origin}"
            )
    else:
        if editable is not None:
            issues.append(
                "distribution qualification requires a non-editable installation; observed "
                f"editable project location {editable}"
            )
        if origin is not None:
            if origin.is_relative_to(current_source):
                issues.append(
                    "distribution qualification must not import rp1_analysis_v1 from the source "
                    f"checkout: {origin}"
                )
            if not origin.is_relative_to(interpreter_prefix):
                issues.append(
                    "distribution qualification requires rp1_analysis_v1 to import from the "
                    f"executing interpreter prefix {interpreter_prefix}; observed {origin}"
                )

    if sys.version_info[:2] != EXPECTED_PYTHON:
        issues.append(
            "unsupported Python version: "
            f"expected {EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]}, "
            f"observed {sys.version_info.major}.{sys.version_info.minor}"
        )

    diagnostics: dict[str, object] = {
        "status": "PASS" if not issues else "FAIL",
        "installation_mode": installation_mode.value,
        "projected_source_context": projected_source_context,
        "projected_source_declared_root": os.environ.get(PROJECTED_PROJECT_ROOT_ENV),
        "script": str(script_path.expanduser().resolve()),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "python_prefix": str(interpreter_prefix),
        "conda_default_env": os.environ.get("CONDA_DEFAULT_ENV"),
        "expected_conda_env": CANONICAL_CONDA_ENV,
        "package_distribution": EXPECTED_DISTRIBUTION,
        "package_expected_version": expected_version,
        "package_version": package_version,
        "package_origin": package_origin,
        "package_distribution_root": distribution_root,
        "editable_project_location": editable_project_location,
        "project_root": str(project_root),
        "source_root": str(current_source),
        "configuration_path": str(configuration_path),
        "kernel": kernel,
        "issues": issues,
    }

    return diagnostics, issues


def require_operational_preflight(
    *,
    script_path: Path,
    kernel: str,
    mode: InstallationMode | str = InstallationMode.SOURCE,
) -> dict[str, object]:
    """Fail cleanly and actionably before importing project packages."""

    installation_mode = _normalise_mode(mode)
    project_root: Path | None = None
    try:
        project_root = _project_root(script_path)
        diagnostics, issues = operational_preflight(
            script_path=script_path,
            kernel=kernel,
            mode=installation_mode,
        )
    except Exception as exc:
        diagnostics = {
            "status": "FAIL",
            "installation_mode": installation_mode.value,
            "script": str(script_path.expanduser().resolve()),
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "python_prefix": str(Path(sys.prefix).resolve()),
            "conda_default_env": os.environ.get("CONDA_DEFAULT_ENV"),
            "expected_conda_env": CANONICAL_CONDA_ENV,
            "package_distribution": EXPECTED_DISTRIBUTION,
            "package_expected_version": (
                _expected_version(project_root) if project_root is not None else None
            ),
            "package_version": None,
            "package_origin": None,
            "package_distribution_root": None,
            "editable_project_location": None,
            "project_root": str(project_root) if project_root is not None else None,
            "source_root": str((project_root / "src").resolve()) if project_root else None,
            "configuration_path": (
                str((project_root / "config" / "analysis_contract.yml").resolve())
                if project_root
                else None
            ),
            "kernel": kernel,
            "issues": [f"{type(exc).__name__}: {exc}"],
        }
        issues = list(diagnostics["issues"])

    if issues:
        print("RP1_ANALYSIS_V1_OPERATIONAL_PREFLIGHT=FAIL", file=sys.stderr)
        print(
            json.dumps(
                diagnostics,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        action_root = project_root or script_path.expanduser().resolve().parent
        print(
            f"ACTION ({installation_mode.value} mode): "
            f"{_remediation_action(mode=installation_mode, project_root=action_root)}.",
            file=sys.stderr,
        )
        print(
            'VERIFY: python -c "import rp1_analysis_v1; '
            'print(rp1_analysis_v1.__version__); print(rp1_analysis_v1.__file__)"',
            file=sys.stderr,
        )
        raise SystemExit(2)

    return diagnostics
