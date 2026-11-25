"""Retired C1 operations cannot enter current c3 production."""
import subprocess
import sys
from pathlib import Path
import pytest
from RP1_Project.rp1_ba_consolidator import c1


def test_retired_c1_functions_stop():
    with pytest.raises(ValueError, match='retired'):
        c1.stage(None)
    with pytest.raises(ValueError, match='cannot satisfy'):
        c1.verify_handoff(None)


def test_retired_wrapper_reports_migration():
    script = Path(__file__).resolve().parents[1] / 'tools/stage_ba.py'
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode == 2 and 'consolidate_ba.py' in result.stderr
