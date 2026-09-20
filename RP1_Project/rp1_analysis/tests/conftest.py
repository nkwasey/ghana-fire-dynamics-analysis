from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "qualified_presentation_run"
RUN_ROOT = ROOT / "out" / "runs"
FIXTURE_RUN_BASE = "qualified_presentation_fixture"


@pytest.fixture(scope="session", autouse=True)
def materialise_presentation_regression_run() -> None:
    """Materialise the repository-owned exporter fixture only for the test session."""
    if not FIXTURE_ROOT.is_dir():
        yield
        return
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    targets: list[Path] = []
    for suffix in ("pub", "sec", "close"):
        source = FIXTURE_ROOT / f"{FIXTURE_RUN_BASE}_{suffix}"
        target = RUN_ROOT / source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, copy_function=shutil.copy2)
        targets.append(target)
    try:
        yield
    finally:
        for target in targets:
            shutil.rmtree(target, ignore_errors=True)
        try:
            RUN_ROOT.rmdir()
            (ROOT / "out").rmdir()
        except OSError:
            pass
