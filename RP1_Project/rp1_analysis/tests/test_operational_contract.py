from __future__ import annotations

from pathlib import Path
import tomllib

SUBPROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = SUBPROJECT.parents[1]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_user_guides_define_distinct_source_and_distribution_modes() -> None:
    documents = (
        REPOSITORY / "README.md",
        REPOSITORY / "RP1_Project/RP1_README.md",
        SUBPROJECT / "README.md",
        SUBPROJECT / "docs/Reproducibility_Contract.md",
    )
    for path in documents:
        text = _text(path).lower()
        assert "source" in text, path
        assert "distribution" in text, path
        assert "editable" in text, path
        assert "non-edit" in text, path


def test_source_guidance_uses_editable_current_checkout() -> None:
    root_readme = _text(REPOSITORY / "README.md")
    analysis_readme = _text(SUBPROJECT / "README.md")
    reproducibility = _text(SUBPROJECT / "docs/Reproducibility_Contract.md")

    assert "-e ./RP1_Project/rp1_analysis" in root_readme or "environment.yml" in root_readme
    assert "python -m pip install -e ." in analysis_readme
    assert "python -m pip install -e ." in reproducibility
    assert "rp1_analysis_v1.__file__" in root_readme
    assert "rp1_analysis_v1.__file__" in analysis_readme


def test_distribution_guidance_uses_built_wheel_noneditably() -> None:
    documents = (
        REPOSITORY / "README.md",
        SUBPROJECT / "README.md",
        SUBPROJECT / "docs/Reproducibility_Contract.md",
    )
    for path in documents:
        text = _text(path)
        assert "python -m build --wheel" in text, path
        version = tomllib.loads((SUBPROJECT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        assert f"rp1_analysis_v1-{version}-*.whl" in text, path
        assert "non-edit" in text.lower(), path


def test_current_operational_guidance_has_no_python311_or_source_dir_release_install() -> None:
    documents = (
        REPOSITORY / "README.md",
        REPOSITORY / "RP1_Project/RP1_README.md",
        SUBPROJECT / "README.md",
        SUBPROJECT / "docs/Reproducibility_Contract.md",
    )
    for path in documents:
        text = _text(path)
        assert "Python " "3.11" not in text, path
        assert "python" "3.11" not in text, path
        assert "python -m pip install ./RP1_Project/rp1_analysis" not in text, path


def test_durable_tests_do_not_embed_the_active_checkout_or_user_home() -> None:
    active_roots = {str(REPOSITORY.resolve()), str(Path.home().resolve())}
    for path in sorted((SUBPROJECT / "tests").glob("test_*.py")):
        source = _text(path)
        for root in active_roots:
            if len(root) > 1:
                assert root not in source, (path, root)
