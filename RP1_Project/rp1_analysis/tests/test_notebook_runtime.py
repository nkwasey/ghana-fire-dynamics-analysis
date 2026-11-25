"""Real process-exit and loop-ownership regressions for Windows Jupyter."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from rp1_analysis_v1.notebook_runtime import _execute_in_owned_selector_loop


def test_owned_selector_loop_closes_and_preserves_policy_on_error():
    observed = []
    original_policy = asyncio.get_event_loop_policy()

    class Client:
        async def async_execute(self):
            observed.append(asyncio.get_running_loop())
            raise ValueError("kernel failure remains visible")

    with pytest.raises(ValueError, match="kernel failure remains visible"):
        _execute_in_owned_selector_loop(Client())
    assert len(observed) == 1
    assert observed[0].is_closed()
    assert asyncio.get_event_loop_policy() is original_policy


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows Jupyter process-teardown regression")
@pytest.mark.parametrize("caller", ["plain", "installed_loop", "running_loop"])
def test_windows_notebook_process_exits_cleanly_without_policy_changes(tmp_path, caller):
    kernel_dir = tmp_path / "jupyter/kernels/rp1-minimal"
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "kernel.json").write_text(json.dumps({
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "RP1 minimal test kernel", "language": "python",
    }), encoding="utf-8")
    env = os.environ.copy()
    env["JUPYTER_PATH"] = str(tmp_path / "jupyter")
    env["JUPYTER_RUNTIME_DIR"] = str(tmp_path / "runtime")
    env["IPYTHONDIR"] = str(tmp_path / "ipython")
    code = '''
import asyncio
from pathlib import Path
import sys
import nbformat
from nbclient import NotebookClient

policy = asyncio.get_event_loop_policy()
existing = None
if sys.argv[1] == 'installed_loop':
    existing = asyncio.new_event_loop()
    asyncio.set_event_loop(existing)
from rp1_analysis_v1.notebook_runtime import execute_notebook_client
assert asyncio.get_event_loop_policy() is policy

def execute():
    nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell('import sys; print(sys.executable)')])
    result = execute_notebook_client(NotebookClient(nb, kernel_name='rp1-minimal', timeout=30))
    assert result.cells[0].execution_count == 1
    assert Path(result.cells[0].outputs[0].text.strip()).resolve() == Path(sys.executable).resolve()
    assert asyncio.get_event_loop_policy() is policy

if sys.argv[1] == 'running_loop':
    async def caller():
        running = asyncio.get_running_loop()
        execute()
        assert asyncio.get_running_loop() is running
        assert not running.is_closed()
    asyncio.run(caller())
else:
    for _ in range(3):
        execute()
    if existing is not None:
        assert asyncio.get_event_loop() is existing
        assert not existing.is_closed()
        existing.close()
        asyncio.set_event_loop(None)
print('RP1_MINIMAL_NOTEBOOK_PROCESS=PASS', flush=True)
'''
    completed = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code, caller],
                               env=env, cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "RP1_MINIMAL_NOTEBOOK_PROCESS=PASS" in completed.stdout
    assert "Proactor event loop does not implement add_reader" not in completed.stderr
