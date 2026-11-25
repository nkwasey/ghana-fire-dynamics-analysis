from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from rp1_analysis_v1.config import load_qualification_contract
from rp1_analysis_v1.source_projection import (
    inventory_governed_source,
    probe_projected_imports,
    project_governed_source,
    projected_import_environment,
    remove_generated_artifacts_from_projection,
    verify_projected_inventory,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "RP1_Project/rp1_analysis/config/qualification_contract.yml"
CONTRACT = load_qualification_contract(CONTRACT_PATH)
C3_ROOT = Path('RP1_Project/rp1_gee_ba_scripts/c3')


def _environment_qualifier():
    """Load the sibling qualification helpers from this checkout."""
    path = Path(__file__).with_name("qualify_environment.py")
    spec = importlib.util.spec_from_file_location("_rp1_environment_qualifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract_import_probe(source_root: Path) -> str:
    return (
        'import pathlib,rp1_ba_contracts.c3 as c3;'
        f'expected=pathlib.Path({str(source_root)!r}).resolve();'
        'origin=pathlib.Path(c3.__file__).resolve();print(origin);'
        'raise SystemExit(0 if origin.is_relative_to(expected) else 2)'
    )


def verify_import_origins(repository_root: Path = ROOT) -> dict[str, str]:
    failures: list[str] = []
    observed: dict[str, str] = {}
    for package in CONTRACT.packages:
        module = importlib.import_module(package.module)
        if module.__file__ is None:
            failures.append(f"{package.module}: missing filesystem origin")
            continue
        origin = Path(module.__file__).resolve()
        expected_root = (repository_root / package.source_root).resolve()
        observed[package.module] = str(origin)
        if not origin.is_relative_to(expected_root):
            failures.append(
                f"{package.module}: {origin} (expected under {expected_root})"
            )
        else:
            print(f"PASS operational import origin {package.module}: {origin}")
    shared = importlib.import_module('rp1_ba_contracts.c3')
    shared_origin = Path(shared.__file__).resolve()
    shared_root = (repository_root / 'RP1_Project/rp1_analysis/src').resolve()
    observed['rp1_ba_contracts.c3'] = str(shared_origin)
    if not shared_origin.is_relative_to(shared_root):
        failures.append(f'rp1_ba_contracts.c3: {shared_origin} (expected under {shared_root})')
    if failures:
        raise SystemExit("Import-origin qualification failed:\n" + "\n".join(failures))
    return observed


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _qualify_projected_source(
    repository_root: Path, evidence_root: Path, *, pytest_base_temp: Path | None = None,
) -> None:
    qualifier = _environment_qualifier()
    pytest_base = qualifier._select_pytest_base(repository_root, evidence_root, pytest_base_temp)
    pytest_argument = str(
        qualifier._native_path(pytest_base)
        if os.name == "nt" and pytest_base_temp is not None and str(pytest_base_temp).startswith("\\\\?\\")
        else pytest_base
    )
    projection_root = evidence_root / CONTRACT.projection.clean_projection_subdirectory
    expected = inventory_governed_source(repository_root, CONTRACT)
    project_governed_source(
        repository_root,
        projection_root,
        CONTRACT,
        expected_inventory=expected,
    )
    probe_projected_imports(projection_root, CONTRACT, cwd=projection_root)
    env = projected_import_environment(projection_root, CONTRACT)
    env.update(
        {
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "RP_RUN_NATIVE_PLOT_SMOKE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(evidence_root / "pycache"),
            "MPLCONFIGDIR": str(evidence_root / "mplconfig"),
        }
    )
    (evidence_root / "pycache").mkdir(parents=True, exist_ok=True)
    (evidence_root / "mplconfig").mkdir(parents=True, exist_ok=True)

    run([sys.executable, '-c', contract_import_probe(projection_root / 'RP1_Project/rp1_analysis/src')],
        cwd=projection_root, env=env)
    run(['node', '--version'], cwd=projection_root, env=env)
    run([sys.executable, 'tests/run_offline.py'], cwd=projection_root / C3_ROOT, env=env)
    remove_generated_artifacts_from_projection(projection_root, CONTRACT)
    verify_projected_inventory(projection_root, expected)

    # Stage-1 regeneration remains part of complete source qualification, but
    # its generated out/ tree is removed from the disposable projection before
    # the strict release-hygiene/full-test gate runs.
    run(
        ["geo-prep", "run", "--config", "configs/example_acz.yaml", "--run-id", "example_acz"],
        cwd=projection_root / "geo_data_prep",
        env=env,
    )
    remove_generated_artifacts_from_projection(projection_root, CONTRACT)
    verify_projected_inventory(projection_root, expected)

    run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--release-tree-checks",
         "--basetemp", pytest_argument],
        cwd=projection_root,
        env=qualifier._projected_test_environment({
            name: value for name, value in env.items() if name not in qualifier.UNCONTROLLED_PYTEST_ENVIRONMENT
        }),
    )
    remove_generated_artifacts_from_projection(projection_root, CONTRACT)
    verify_projected_inventory(projection_root, expected)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qualify all local source projects through the governed clean-source authority."
    )
    parser.add_argument(
        "--origins-only",
        action="store_true",
        help="Verify all four project imports and the shared c3 contract resolve inside this checkout.",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Optional fresh external directory for the clean projection.",
    )
    parser.add_argument(
        "--pytest-base-temp", type=Path,
        help="Optional fresh external pytest directory, disjoint from the repository and evidence.",
    )
    args = parser.parse_args()

    verify_import_origins(ROOT)
    if args.origins_only:
        return 0

    if args.evidence_dir:
        requested = args.evidence_dir
        if requested.is_symlink() or requested.is_junction():
            raise SystemExit("source-qualification evidence directory may not be linked")
        evidence_root = requested.resolve()
        repository = ROOT.resolve()
        if evidence_root.is_relative_to(repository) or repository.is_relative_to(evidence_root):
            raise SystemExit("source-qualification evidence root must be external and non-overlapping")
        try:
            evidence_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise SystemExit("source-qualification evidence directory must be fresh") from exc
        _qualify_projected_source(ROOT, evidence_root, pytest_base_temp=args.pytest_base_temp)
    else:
        with tempfile.TemporaryDirectory(prefix="rp1-source-qualification-") as temporary:
            _qualify_projected_source(ROOT, Path(temporary), pytest_base_temp=args.pytest_base_temp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
