from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import shutil
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
    if failures:
        raise SystemExit("Import-origin qualification failed:\n" + "\n".join(failures))
    return observed


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _qualify_projected_source(repository_root: Path, evidence_root: Path) -> None:
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
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"],
        cwd=projection_root,
        env=env,
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
        help="Only verify that all three imports resolve inside this operational checkout.",
    )
    parser.add_argument(
        "--evidence-dir",
        help="Optional external disposable root for the clean projection.",
    )
    args = parser.parse_args()

    verify_import_origins(ROOT)
    if args.origins_only:
        return 0

    if args.evidence_dir:
        evidence_root = Path(args.evidence_dir).resolve()
        if evidence_root == ROOT.resolve() or evidence_root.is_relative_to(ROOT.resolve()) or ROOT.resolve().is_relative_to(evidence_root):
            raise SystemExit("source-qualification evidence root must be external and non-overlapping")
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True)
        _qualify_projected_source(ROOT, evidence_root)
    else:
        with tempfile.TemporaryDirectory(prefix="rp1-source-qualification-") as temporary:
            _qualify_projected_source(ROOT, Path(temporary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
