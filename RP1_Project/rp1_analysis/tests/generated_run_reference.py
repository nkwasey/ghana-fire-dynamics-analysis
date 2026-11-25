"""Require explicit selection and validation of generated-run references.

The production validator checks that recorded source and input identities
match the selected analysis checkout.
"""
from functools import lru_cache
import os
from pathlib import Path
import re

import pytest

SELECTION_REQUIRED = "generated_integration_selection_required"


def selected_run_base(root: Path) -> str:
    requested = os.environ.get("RP1_ANALYSIS_TEST_RUN")
    if requested:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", requested):
            raise ValueError("RP1_ANALYSIS_TEST_RUN must be a portable run base identifier")
        return requested
    return SELECTION_REQUIRED


@lru_cache(maxsize=None)
def _validated_snapshot(root: Path, run_base: str, fingerprint: tuple):
    from rp1_analysis_v1.integration import validate_run_authority
    from rp1_analysis_v1.paths import ProjectPaths

    missing = [run_base + suffix for suffix in ("_pub", "_sec", "_close")
               if not (root / "out/runs" / (run_base + suffix)).is_dir()]
    if missing:
        pytest.fail(f"Selected generated run is incomplete: {missing}", pytrace=False)
    try:
        result = validate_run_authority(paths=ProjectPaths(root), run_id=run_base)
    except Exception as exc:
        pytest.fail(
            f"Selected generated run {run_base!r} failed current-source validation: {exc}. "
            "Preserve historical runs and validate them with their original sources; "
            "select a newly completed run for this checkout.", pytrace=False,
        )
    if fingerprint != _reference_snapshot(root, run_base):
        pytest.fail("Selected reference changed during validation", pytrace=False)
    if result.status != "PASS":
        pytest.fail(f"Selected generated run did not PASS: {result.status}", pytrace=False)
    return result


def _reference_snapshot(root: Path, run_base: str) -> tuple:
    # Cheap freshness keys invalidate the expensive production validation cache.
    # Production validation remains responsible for cryptographic identities.
    directories = [root / name for name in ("src", "config", "data")]
    directories += [root / "out/runs" / (run_base + suffix)
                    for suffix in ("_pub", "_sec", "_close")]
    directories.append(root / "out/publication_sources" / (run_base + "_pub"))
    files = {root / "RP1_Analysis_v1.ipynb", root / "pyproject.toml"}
    for directory in directories:
        if directory.is_dir():
            files.update(p for p in directory.rglob("*")
                         if p.is_file() and "__pycache__" not in p.parts
                         and p.suffix != ".pyc")
    directory_state = tuple((d.relative_to(root).as_posix(), d.is_dir()) for d in directories)
    file_state = tuple((p.relative_to(root).as_posix(), p.stat().st_size,
                        p.stat().st_mtime_ns) for p in sorted(files) if p.is_file())
    return directory_state, file_state


def _validated_reference(root: Path, run_base: str):
    return _validated_snapshot(root, run_base, _reference_snapshot(root, run_base))


def clear_reference_cache() -> None:
    _validated_snapshot.cache_clear()


def require_selected_run(root: Path, run_base: str, *, external: bool = False) -> None:
    if run_base == SELECTION_REQUIRED and not os.environ.get("RP1_ANALYSIS_TEST_RUN"):
        pytest.skip("Generate a current-source run and explicitly set RP1_ANALYSIS_TEST_RUN; no result run is shipped")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", run_base):
        raise ValueError("Selected run must be a portable run base identifier")
    result = _validated_reference(root.resolve(), run_base)
    if external and result.secondary_external_state != "RESULTS_VALIDATED":
        pytest.fail("Selected RQ4 reference requires RESULTS_VALIDATED external results", pytrace=False)


def publication_source_root(root: Path) -> Path:
    run_base = selected_run_base(root)
    require_selected_run(root, run_base)
    return root / "out/publication_sources" / f"{run_base}_pub"


def publication_sources(root: Path):
    from rp1_analysis_v1.paths import ProjectPaths
    from rp1_analysis_v1.publication_sources import load_publication_authorities

    run_base = selected_run_base(root)
    require_selected_run(root, run_base)
    return load_publication_authorities(paths=ProjectPaths(root), primary_run_id=f"{run_base}_pub")
