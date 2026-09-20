from __future__ import annotations

import shutil
import subprocess
import sys


def test_python_module_help() -> None:
    """
    Robust CLI help test that does not depend on console script discovery.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "geo_data_prep", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    out = proc.stdout + proc.stderr
    assert "geo-prep" in out
    # Ensure the end-to-end pipeline command is discoverable.
    assert "run" in out


def test_console_script_help_if_available() -> None:
    """
    If the editable install exposes the console script, verify it too.
    On some environments, PATH resolution can vary; this test is conditional.
    """
    exe = shutil.which("geo-prep")
    if exe is None:
        return

    proc = subprocess.run(
        [exe, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "geo-prep" in (proc.stdout + proc.stderr)
