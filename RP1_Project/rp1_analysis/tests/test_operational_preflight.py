from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

SUBPROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = SUBPROJECT / "scripts"


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location(
        "rp1_analysis_v1_operational_preflight_test",
        SCRIPTS / "_operational_preflight.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with (SUBPROJECT / "pyproject.toml").open("rb") as _handle:
    EXPECTED_ANALYSIS_VERSION = tomllib.load(_handle)["project"]["version"]


class _FakeDistribution:
    def __init__(
        self, *, root: Path, editable: Path | None = None, version: str | None = None
    ) -> None:
        self.version = version or EXPECTED_ANALYSIS_VERSION
        self._root = root
        self._editable = editable

    def read_text(self, name: str) -> str | None:
        if name != "direct_url.json" or self._editable is None:
            return None
        return json.dumps(
            {
                "url": self._editable.resolve().as_uri(),
                "dir_info": {"editable": True},
            }
        )

    def locate_file(self, _name: str) -> Path:
        return self._root


def _patch_package_state(
    monkeypatch: pytest.MonkeyPatch,
    module,
    *,
    origin: Path,
    distribution_root: Path,
    editable: Path | None,
    version: str | None = None,
) -> None:
    distribution = _FakeDistribution(
        root=distribution_root, editable=editable, version=version
    )
    monkeypatch.setattr(module.importlib.metadata, "distribution", lambda _name: distribution)
    monkeypatch.setattr(
        module.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(origin=str(origin)),
    )


@pytest.mark.parametrize(
    ("script_name", "expected_kernel"),
    [
        ("validate_inputs.py", "not-applicable"),
        ("execute_notebook.py", "python3"),
        ("validate_run.py", "not-applicable"),
    ],
)
def test_missing_package_fails_with_source_mode_remediation(
    tmp_path: Path,
    script_name: str,
    expected_kernel: str,
) -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(SCRIPTS / script_name),
            "--help",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""

    stderr = result.stderr
    assert "RP1_ANALYSIS_V1_OPERATIONAL_PREFLIGHT=FAIL" in stderr
    assert "Traceback" not in stderr
    assert "ModuleNotFoundError" not in stderr

    for field in (
        '"installation_mode"',
        '"python_executable"',
        '"python_version"',
        '"python_prefix"',
        '"package_version"',
        '"package_origin"',
        '"project_root"',
        '"source_root"',
        '"configuration_path"',
        '"kernel"',
        '"issues"',
    ):
        assert field in stderr

    assert '"installation_mode": "source"' in stderr
    assert f'"kernel": "{expected_kernel}"' in stderr
    assert "ACTION (source mode):" in stderr
    assert "pip install -e" in stderr
    assert "VERIFY:" in stderr


def test_source_mode_accepts_verified_current_source_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_preflight_module()
    project_root = SUBPROJECT.resolve()
    origin = project_root / "src/rp1_analysis_v1/__init__.py"
    prefix = Path(sys.prefix).resolve()
    _patch_package_state(
        monkeypatch,
        module,
        origin=origin,
        distribution_root=prefix / "lib/python3.13/site-packages",
        editable=project_root,
    )

    diagnostics, issues = module.operational_preflight(
        script_path=SCRIPTS / "validate_inputs.py",
        kernel="not-applicable",
        mode=module.InstallationMode.SOURCE,
    )

    assert issues == []
    assert diagnostics["status"] == "PASS"
    assert diagnostics["installation_mode"] == "source"
    assert Path(str(diagnostics["package_origin"])).is_relative_to(project_root / "src")


def test_source_mode_rejects_installed_distribution_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_preflight_module()
    prefix = Path(sys.prefix).resolve()
    origin = prefix / "lib/python3.13/site-packages/rp1_analysis_v1/__init__.py"
    _patch_package_state(
        monkeypatch,
        module,
        origin=origin,
        distribution_root=prefix / "lib/python3.13/site-packages",
        editable=None,
    )

    diagnostics, issues = module.operational_preflight(
        script_path=SCRIPTS / "validate_inputs.py",
        kernel="not-applicable",
        mode="source",
    )

    assert diagnostics["status"] == "FAIL"
    assert any("verified current source tree" in issue for issue in issues)


def test_distribution_mode_accepts_noneditable_interpreter_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_preflight_module()
    prefix = Path(sys.prefix).resolve()
    origin = prefix / "lib/python3.13/site-packages/rp1_analysis_v1/__init__.py"
    _patch_package_state(
        monkeypatch,
        module,
        origin=origin,
        distribution_root=prefix / "lib/python3.13/site-packages",
        editable=None,
    )

    diagnostics, issues = module.operational_preflight(
        script_path=SCRIPTS / "validate_inputs.py",
        kernel="not-applicable",
        mode=module.InstallationMode.DISTRIBUTION,
    )

    assert issues == []
    assert diagnostics["status"] == "PASS"
    assert diagnostics["installation_mode"] == "distribution"


def test_distribution_mode_rejects_editable_source_install(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_preflight_module()
    project_root = SUBPROJECT.resolve()
    origin = project_root / "src/rp1_analysis_v1/__init__.py"
    prefix = Path(sys.prefix).resolve()
    _patch_package_state(
        monkeypatch,
        module,
        origin=origin,
        distribution_root=prefix / "lib/python3.13/site-packages",
        editable=project_root,
    )

    diagnostics, issues = module.operational_preflight(
        script_path=SCRIPTS / "validate_inputs.py",
        kernel="not-applicable",
        mode="distribution",
    )

    assert diagnostics["status"] == "FAIL"
    assert any("non-editable installation" in issue for issue in issues)
    assert any("must not import" in issue for issue in issues)


def test_unsupported_python_major_minor_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_preflight_module()
    project_root = SUBPROJECT.resolve()
    prefix = Path(sys.prefix).resolve()
    _patch_package_state(
        monkeypatch,
        module,
        origin=project_root / "src/rp1_analysis_v1/__init__.py",
        distribution_root=prefix / "lib/python3.13/site-packages",
        editable=project_root,
    )

    class FakeVersionInfo(tuple):
        @property
        def major(self) -> int:
            return self[0]

        @property
        def minor(self) -> int:
            return self[1]

    monkeypatch.setattr(module.sys, "version_info", FakeVersionInfo((3, 12, 9)))

    diagnostics, issues = module.operational_preflight(
        script_path=SCRIPTS / "validate_inputs.py",
        kernel="not-applicable",
        mode="source",
    )

    assert diagnostics["status"] == "FAIL"
    assert any("expected 3.13, observed 3.12" in issue for issue in issues)


def test_projected_source_context_accepts_actual_projected_origin_despite_stale_editable_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_preflight_module()
    project_root = SUBPROJECT.resolve()
    prefix = Path(sys.prefix).resolve()
    stale_checkout = project_root.parent.parent.parent / "different-operational-checkout"
    _patch_package_state(
        monkeypatch,
        module,
        origin=project_root / "src/rp1_analysis_v1/__init__.py",
        distribution_root=prefix / "lib/python3.13/site-packages",
        editable=stale_checkout,
        version="1.2.1",
    )
    monkeypatch.setenv(module.PROJECTED_IMPORT_MODE_ENV, module.PROJECTED_IMPORT_MODE)
    monkeypatch.setenv(module.PROJECTED_PROJECT_ROOT_ENV, str(project_root))

    diagnostics, issues = module.operational_preflight(
        script_path=SCRIPTS / "validate_inputs.py",
        kernel="not-applicable",
        mode=module.InstallationMode.SOURCE,
    )

    assert issues == []
    assert diagnostics["status"] == "PASS"
    assert diagnostics["projected_source_context"] is True
    assert diagnostics["editable_project_location"] == str(stale_checkout.resolve())
    assert diagnostics["package_version"] == "1.2.1"
    assert Path(str(diagnostics["package_origin"])).is_relative_to(project_root / "src")


def test_projected_source_context_still_rejects_wrong_import_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_preflight_module()
    project_root = SUBPROJECT.resolve()
    prefix = Path(sys.prefix).resolve()
    stale_checkout = project_root.parent.parent.parent / "different-operational-checkout"
    _patch_package_state(
        monkeypatch,
        module,
        origin=stale_checkout / "src/rp1_analysis_v1/__init__.py",
        distribution_root=prefix / "lib/python3.13/site-packages",
        editable=stale_checkout,
    )
    monkeypatch.setenv(module.PROJECTED_IMPORT_MODE_ENV, module.PROJECTED_IMPORT_MODE)
    monkeypatch.setenv(module.PROJECTED_PROJECT_ROOT_ENV, str(project_root))

    diagnostics, issues = module.operational_preflight(
        script_path=SCRIPTS / "validate_inputs.py",
        kernel="not-applicable",
        mode=module.InstallationMode.SOURCE,
    )

    assert diagnostics["status"] == "FAIL"
    assert any("verified current source tree" in issue for issue in issues)


def test_projected_source_context_rejects_declared_project_root_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_preflight_module()
    project_root = SUBPROJECT.resolve()
    prefix = Path(sys.prefix).resolve()
    _patch_package_state(
        monkeypatch,
        module,
        origin=project_root / "src/rp1_analysis_v1/__init__.py",
        distribution_root=prefix / "lib/python3.13/site-packages",
        editable=project_root,
    )
    monkeypatch.setenv(module.PROJECTED_IMPORT_MODE_ENV, module.PROJECTED_IMPORT_MODE)
    monkeypatch.setenv(module.PROJECTED_PROJECT_ROOT_ENV, str(tmp_path / "wrong"))

    diagnostics, issues = module.operational_preflight(
        script_path=SCRIPTS / "validate_inputs.py",
        kernel="not-applicable",
        mode=module.InstallationMode.SOURCE,
    )

    assert diagnostics["status"] == "FAIL"
    assert any("root mismatch" in issue for issue in issues)
