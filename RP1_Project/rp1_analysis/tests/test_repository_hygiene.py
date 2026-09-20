from __future__ import annotations

import ast
import importlib
import pkgutil
import re
import tomllib
from pathlib import Path

import yaml

import rp1_analysis_v1
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.method_authority import require_implementation

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
DOCS = [
    WORKSPACE / "README.md",
    ROOT.parent / "RP1_README.md",
    ROOT / "README.md",
    ROOT / "docs/Analysis_Methods_Contract.md",
    ROOT / "docs/Data_Contract.md",
    ROOT / "docs/Data_Schema_Contract.md",
    ROOT / "docs/Method_Authority_Register.md",
    ROOT / "docs/Reference_Method_Validation.md",
    ROOT / "docs/Figure_Table_Contract.md",
    ROOT / "docs/RP1_Analysis_v1_Cell_Contract.md",
    ROOT / "docs/Reproducibility_Contract.md",
    ROOT / "docs/Secondary_Analysis_Contract.md",
]
CURRENT_METHOD_IDS = {
    "within_acz_rate_difference", "median_iqr", "gini_coefficient", "circular_mean_resultant",
    "queen_contiguity", "global_morans_i", "local_morans_i", "permutation", "sens_slope",
    "studentized_global_mann_kendall_permutation", "benjamini_hochberg", "firth_penalized_gee",
    "binomial", "logit", "independence", "morel_bokossa_neerchal", "standard_normal_wald",
    "log2_positive", "categorical", "variance_inflation_factor",
    "observed_covariate_predictive_standardisation", "discrete_poisson", "space_time_permutation",
    "hierarchical_non_overlapping",
}


def _collection_time_release_contaminants() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Snapshot persistent release contaminants before test execution starts."""
    forbidden_dirs = {"build", "dist", ".ipynb_checkpoints"}
    contaminants: list[str] = []
    for path in ROOT.rglob("*"):
        if path.is_dir() and (path.name in forbidden_dirs or path.name.endswith(".egg-info")):
            contaminants.append(path.relative_to(ROOT).as_posix())
        elif path.is_file() and (path.suffix.lower() == ".zip" or path.name.endswith("~")):
            contaminants.append(path.relative_to(ROOT).as_posix())
    out = ROOT / "out"
    out_files = (
        tuple(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
        if out.exists()
        else ()
    )
    return tuple(sorted(contaminants)), tuple(sorted(out_files))


COLLECTION_TIME_CONTAMINANTS, COLLECTION_TIME_OUT_FILES = _collection_time_release_contaminants()



def _yaml(name: str):
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def test_final_documentation_set_exists_and_describes_current_product() -> None:
    for path in DOCS:
        assert path.is_file(), path
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)
    assert "1.2.3" in combined
    assert "Romano–Tirlea" in combined
    assert "Firth-type penalised GEE" in combined
    assert "space-time permutation" in combined.lower()


def test_configuration_and_documentation_share_current_schema_identities() -> None:
    bundle = load_configuration_bundle(ROOT / "config")
    assert bundle.analysis.schema_version == "rp1-analysis-v1.1"
    assert bundle.data_schema.data_schema_version == "rp1-data-schema-v1.1"
    for name in ("analysis_contract.yml", "data_schema_contract.yml", "method_authorities.yml", "output_contract.yml", "figure_contract.yml"):
        assert _yaml(name)["schema_version"] == "rp1-analysis-v1.1"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)
    assert "rp1-analysis-v1.1" in combined
    assert "rp1-data-schema-v1.1" in combined


def test_package_version_is_single_and_consistent() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["name"] == "rp1-analysis-v1"
    assert project["version"] == "1.2.3"
    assert rp1_analysis_v1.__version__ == "1.2.3"
    assert "Ghana Fire RP1 Analysis v1.2.3" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "version `1.2.3`" in (WORKSPACE / "README.md").read_text(encoding="utf-8")
    assert "rp1-analysis-v1==1.2.3" in (ROOT.parent / "RP1_README.md").read_text(encoding="utf-8")


def test_method_authority_contains_exact_current_methods() -> None:
    raw = _yaml("method_authorities.yml")
    ids = {item["method_id"] for item in raw["authorities"]}
    assert ids == CURRENT_METHOD_IDS
    allowed_status = {"implemented", "scientifically_frozen_implementation_pending"}
    assert all(item["status"] in allowed_status for item in raw["authorities"])
    assert all(item["authority_scope"] == "scientific_contract" for item in raw["authorities"])
    for item in raw["authorities"]:
        capability = require_implementation(item["implementation_id"])
        if item["status"] == "implemented":
            assert capability.implemented, item["method_id"]
        else:
            assert not capability.implemented, item["method_id"]


def test_current_method_implementations_are_registered() -> None:
    bundle = load_configuration_bundle(ROOT / "config")
    for item in bundle.methods.authorities:
        require_implementation(item.implementation_id)


def test_runtime_and_operational_scripts_use_repository_relative_inputs() -> None:
    paths = list((ROOT / "src/rp1_analysis_v1").glob("*.py")) + list((ROOT / "scripts").glob("*.py"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "/home/" not in text
    assert "/mnt/" not in text
    assert ":\\Users\\" not in text


def test_operational_scripts_do_not_duplicate_release_version_literal() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "scripts").glob("*.py"))
    assert '"1.2.3"' not in text
    assert "'1.2.3'" not in text
    assert "future_qualification_slots" not in text


def test_all_package_modules_import_from_current_source_tree() -> None:
    names = sorted(module.name for module in pkgutil.iter_modules(rp1_analysis_v1.__path__))
    expected = sorted(path.stem for path in (ROOT / "src/rp1_analysis_v1").glob("*.py") if path.name != "__init__.py")
    assert names == expected
    for name in names:
        module = importlib.import_module(f"rp1_analysis_v1.{name}")
        assert Path(module.__file__).resolve().is_relative_to((ROOT / "src/rp1_analysis_v1").resolve())


def test_notebook_uses_repository_relative_inputs() -> None:
    text = (ROOT / "RP1_Analysis_v1.ipynb").read_text(encoding="utf-8")
    assert "/home/" not in text
    assert "/mnt/" not in text
    assert ":\\Users\\" not in text


def test_test_filenames_and_reference_fixtures_are_product_scoped() -> None:
    names = [path.name.lower() for path in (ROOT / "tests").glob("test_*.py")]
    assert not any(re.search(r"v[0-9]{3}", name) for name in names)
    assert not (ROOT / "tests/fixtures/reference_methods/future_qualification_slots.json").exists()


def test_repository_inventory_contains_no_persistent_release_contaminants() -> None:
    # Test workflows can create run output after collection.  The product-hygiene
    # assertion therefore evaluates the release tree as it existed at collection
    # time, while final packaging independently repeats the filesystem scan.
    assert COLLECTION_TIME_CONTAMINANTS == ()
    assert COLLECTION_TIME_OUT_FILES in ((), (".gitkeep",))


def test_python_files_are_parseable_without_generated_bytecode() -> None:
    for root in (ROOT / "src", ROOT / "scripts", ROOT / "tests"):
        for path in root.rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
