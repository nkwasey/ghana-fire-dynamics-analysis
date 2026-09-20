from __future__ import annotations

import ast
import re
from pathlib import Path

SUBPROJECT = Path(__file__).resolve().parents[1]
DOMAIN_MODULES = (
    "observability.py",
    "spatial_scale.py",
    "trend_robustness.py",
    "seasonality.py",
    "spatial_stats.py",
    "gee.py",
)
NUMBERED_SOURCE = re.compile(r"^[tfs]\d+_source$")
NUMBERED_BUILDER = re.compile(r"^_build_[tfs]\d+(?:_|$)")
NUMBERED_COLUMNS = re.compile(r"^[TFS]\d+_COLUMNS$")
NUMBERED_DOMAIN_PREFIX = re.compile(r"^[tfs]\d+_")


def _defined_identifiers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_scientific_domain_modules_do_not_expose_publication_numbered_identities() -> None:
    violations: list[str] = []
    source_root = SUBPROJECT / "src" / "rp1_analysis_v1"
    for module in DOMAIN_MODULES:
        path = source_root / module
        for name in sorted(_defined_identifiers(path)):
            if (
                NUMBERED_SOURCE.fullmatch(name)
                or NUMBERED_BUILDER.match(name)
                or NUMBERED_COLUMNS.fullmatch(name)
                or NUMBERED_DOMAIN_PREFIX.match(name)
            ):
                violations.append(f"{module}:{name}")
    assert violations == []


def test_removed_compatibility_shims_are_not_reintroduced() -> None:
    source_root = SUBPROJECT / "src" / "rp1_analysis_v1"
    combined = "\n".join((source_root / module).read_text(encoding="utf-8") for module in DOMAIN_MODULES)
    for obsolete in (
        "circular_seasonal_concentration",
        "build_rq1_spatial_autocorrelation_table",
        "Compatibility accessor",
        "Compatibility entry point",
        "Backward-compatible alias",
        "Kept for compatibility",
    ):
        assert obsolete not in combined


def test_publication_numbering_remains_confined_to_presentation_contracts() -> None:
    # T/F/S display identities are intentionally present in the publication contracts.
    output_text = (SUBPROJECT / "config" / "output_contract.yml").read_text(encoding="utf-8")
    figure_text = (SUBPROJECT / "config" / "figure_contract.yml").read_text(encoding="utf-8")
    for publication_id in ("T1", "T2", "T3", "S1", "S2", "S3", "S4", "S5", "S6"):
        assert publication_id in output_text
    for figure_id in ("F2", "F3", "F4", "F5", "F6"):
        assert figure_id in figure_text


def test_domain_authority_filenames_are_publication_number_neutral() -> None:
    authority_root = SUBPROJECT / "data" / "authorities"
    numbered_file = re.compile(r"^(?:table|figure|supplement|[tfs]\d+).*_source\.csv$", re.IGNORECASE)
    violations: list[str] = []
    for domain in ("rq1", "rq2", "rq3"):
        domain_root = authority_root / domain
        for path in domain_root.iterdir():
            if path.is_file() and numbered_file.match(path.name):
                violations.append(path.relative_to(SUBPROJECT).as_posix())
        manifest = domain_root / "source_manifest.json"
        if manifest.exists():
            for match in re.findall(r'"path"\s*:\s*"([^"]+)"', manifest.read_text(encoding="utf-8")):
                if numbered_file.match(Path(match).name):
                    violations.append(f"{manifest.relative_to(SUBPROJECT).as_posix()}:{match}")
    assert violations == []
