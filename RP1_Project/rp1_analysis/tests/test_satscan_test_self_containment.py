from __future__ import annotations

import ast
import re
from pathlib import Path

SUBPROJECT = Path(__file__).resolve().parents[1]
TEST_ROOT = SUBPROJECT / "tests"
SATSCAN_TESTS = (
    TEST_ROOT / "test_secondary_clusters.py",
    TEST_ROOT / "test_optional_satscan_integration.py",
    TEST_ROOT / "test_satscan_publication_fixture.py",
    TEST_ROOT / "test_satscan_test_self_containment.py",
    TEST_ROOT / "reference_methods/test_satscan_reference.py",
    TEST_ROOT / "reference_methods/satscan_reference_implementations.py",
)


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_satscan_regression_estate_has_no_external_archive_dependency() -> None:
    development_identity_patterns = (
        re.compile(r"\bV\d{3,}[-_]\d+\b", flags=re.IGNORECASE),
        re.compile(r"\bLOCAL[-_]\d+\b", flags=re.IGNORECASE),
        re.compile(r"\bRP1_ANALYSIS_V1_V\d{3,}[-_]\d+\b", flags=re.IGNORECASE),
    )
    external_archive_patterns = (
        re.compile(r"\.zip(?:$|[\s'\"])", flags=re.IGNORECASE),
    )
    offenders: list[tuple[str, str]] = []
    guard_file = Path(__file__).resolve()
    for path in SATSCAN_TESTS:
        assert path.is_file()
        if path.resolve() == guard_file:
            continue
        for value in _string_literals(path):
            if any(pattern.search(value) for pattern in development_identity_patterns + external_archive_patterns):
                offenders.append((path.relative_to(TEST_ROOT).as_posix(), value))
    assert offenders == []


def test_satscan_regression_estate_has_no_user_specific_absolute_path_literal() -> None:
    patterns = (
        re.compile(r"^/home/[^/]+/"), re.compile(r"^/mnt/[A-Za-z]/"),
        re.compile(r"^[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]"),
    )
    offenders: list[tuple[str, str]] = []
    for path in SATSCAN_TESTS:
        for value in _string_literals(path):
            if any(pattern.search(value) for pattern in patterns):
                offenders.append((path.relative_to(TEST_ROOT).as_posix(), value))
    assert offenders == []


def test_satscan_regression_fixture_roots_are_repository_local() -> None:
    repository_root = SUBPROJECT.parents[1].resolve()
    for path in SATSCAN_TESTS:
        assert path.resolve().is_relative_to(repository_root)
    fixture_root = (TEST_ROOT / "fixtures/reference_methods/satscan").resolve()
    assert fixture_root.is_dir()
    assert fixture_root.is_relative_to(repository_root)
