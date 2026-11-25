#!/usr/bin/env python3
"""Bounded, read-only environment probes before the longer qualification campaign.

No package installation, editable rebinding, remote service call or scientific
pipeline is performed. Probe scratch files and optional JSON evidence stay
outside the source checkout. A passing preflight is not full qualification.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
STATUSES = frozenset({"PASS", "FAIL", "UNAVAILABLE"})
PROBES = ("python", "versions", "origins", "node", "geospatial", "numerics", "event_loop", "kernel")
STRICT_EXECUTION_PROBES = ("event_loop", "kernel", "satscan")
DEPENDENCIES = (
    ("numpy", "numpy"), ("pandas", "pandas"), ("scipy", "scipy"),
    ("matplotlib", "matplotlib"), ("statsmodels", "statsmodels"),
    ("geopandas", "geopandas"), ("shapely", "shapely"),
    ("pyproj", "pyproj"), ("pyogrio", "pyogrio"), ("fiona", "fiona"),
    ("PIL", "Pillow"), ("yaml", "PyYAML"),
    ("markdown_it", "markdown-it-py"), ("build", "build"),
    ("pydantic", "pydantic"), ("requests", "requests"), ("shapefile", "pyshp"),
    ("nbformat", "nbformat"), ("nbclient", "nbclient"),
    ("ipykernel", "ipykernel"), ("jupyter_client", "jupyter_client"),
)


def _result(name: str, status: str, details: Mapping[str, Any] | None = None,
            issues: Sequence[str] = ()) -> dict[str, Any]:
    return {"probe": name, "status": status, "details": dict(details or {}), "issues": list(issues)}


def assess_origins(origins: Mapping[str, str | None], expected: Mapping[str, Path]) -> list[str]:
    issues: list[str] = []
    for name, source in expected.items():
        token = origins.get(name)
        if not token:
            issues.append(f"{name}: missing filesystem origin")
        elif not Path(token).resolve().is_relative_to(source.resolve()):
            issues.append(f"{name}: origin {token} is outside expected source root {source}")
    return issues


def assess_versions(records: Sequence[Mapping[str, Any]]) -> list[str]:
    """Compare actual module versions and discoverable distribution metadata."""
    from packaging.version import InvalidVersion, Version
    issues: list[str] = []
    for record in records:
        name = str(record["distribution"])
        runtime = record.get("runtime_version")
        metadata = record.get("metadata_version")
        if not runtime or not metadata:
            issues.append(f"{name}: runtime or metadata version is unavailable")
            continue
        try:
            if Version(str(runtime)) != Version(str(metadata)):
                issues.append(f"{name}: imported runtime {runtime} differs from metadata {metadata}")
            discovered = {Version(str(v)) for v in record.get("discovered_metadata_versions", [metadata])}
            if len(discovered) > 1:
                issues.append(f"{name}: conflicting distribution metadata versions {sorted(map(str, discovered))}")
        except InvalidVersion:
            issues.append(f"{name}: an unparseable runtime or metadata version was reported")
    return issues


def _native_environment(scratch: Path) -> dict[str, Any]:
    """Configure only this probe process using its actual base interpreter."""
    prefix = Path(sys.base_prefix).resolve()
    paths = [p for p in (prefix / "Library/bin", prefix / "DLLs", prefix) if p.is_dir()]
    original = {key: os.environ.get(key) for key in ("PROJ_DATA", "GDAL_DATA")}
    os.environ["PATH"] = os.pathsep.join([*(str(p) for p in paths), os.environ.get("PATH", "")])
    # Keep handles alive for the lifetime of a Windows worker.
    handles = []
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        handles = [os.add_dll_directory(str(path)) for path in paths]
    _DLL_HANDLES.extend(handles)
    for path in (prefix / "Library/share/proj", prefix / "share/proj",
                 prefix / "Lib/site-packages/pyproj/proj_dir/share/proj"):
        if (path / "proj.db").is_file():
            os.environ["PROJ_DATA"] = str(path)
            break
    for path in (prefix / "Library/share/gdal", prefix / "share/gdal"):
        if path.is_dir():
            os.environ["GDAL_DATA"] = str(path)
            break
    os.environ.update({"PYTHONDONTWRITEBYTECODE": "1", "MPLCONFIGDIR": str(scratch / "mplconfig"),
                       "IPYTHONDIR": str(scratch / "ipython"),
                       "JUPYTER_RUNTIME_DIR": str(scratch / "jupyter_runtime")})
    sys.dont_write_bytecode = True
    return {"base_prefix": str(prefix), "native_search_paths": [str(p) for p in paths],
            "original_data_environment": original,
            "effective_data_environment": {key: os.environ.get(key) for key in original},
            "scope": "probe-process configuration only; no shared environment was changed"}


_DLL_HANDLES: list[Any] = []


def _probe_versions() -> dict[str, Any]:
    def normalized(token: str) -> str:
        return re.sub(r"[-_.]+", "-", token).lower()
    wanted = {normalized(dist) for _, dist in DEPENDENCIES}
    discovered: dict[str, list[dict[str, str]]] = {name: [] for name in wanted}
    for dist in importlib.metadata.distributions():
        name = normalized(str(dist.metadata.get("Name", "")))
        if name in wanted:
            discovered[name].append({"version": str(dist.version), "location": str(dist.locate_file(""))})
    records = []
    for module_name, distribution in DEPENDENCIES:
        module = importlib.import_module(module_name)
        matches = discovered[normalized(distribution)]
        records.append({"module": module_name, "distribution": distribution,
                        "origin": str(getattr(module, "__file__", "")),
                        "runtime_version": getattr(module, "__version__", None),
                        "metadata_version": importlib.metadata.version(distribution),
                        "discovered_metadata_versions": [entry["version"] for entry in matches],
                        "metadata_locations": matches})
    issues = assess_versions(records)
    return _result("versions", "FAIL" if issues else "PASS", {"dependencies": records}, issues)


def _probe_origins(root: Path) -> dict[str, Any]:
    import yaml
    contract_path = root / "RP1_Project/rp1_analysis/config/qualification_contract.yml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    expected = {}
    for package in contract["packages"]:
        source = Path(str(package["source_root"]))
        if source.is_absolute() or ".." in source.parts or ":" in str(source):
            raise ValueError("Qualification contract source roots must be safe repository-relative paths")
        expected[str(package["module"])] = root / source
    expected["rp1_ba_contracts.c3"] = root / "RP1_Project/rp1_analysis/src"
    origins = {name: getattr(importlib.import_module(name), "__file__", None) for name in expected}
    issues = assess_origins(origins, expected)
    return _result("origins", "FAIL" if issues else "PASS",
                   {"origins": origins, "expected_source_roots": {k: str(v) for k, v in expected.items()},
                    "contract": str(contract_path)}, issues)


def _probe_node(command: str, timeout: float) -> dict[str, Any]:
    executable = shutil.which(command)
    if executable is None:
        return _result("node", "UNAVAILABLE", {"requested_command": command}, ["Node.js executable was not found"])
    completed = subprocess.run([executable, "--version"], text=True, encoding="utf-8", errors="replace",
                               capture_output=True, timeout=timeout, check=False)
    version = completed.stdout.strip()
    issues = []
    if completed.returncode != 0 or not re.fullmatch(r"v24\.\d+\.\d+(?:[-+].*)?", version):
        issues.append(f"Node.js 24 is required; observed {version!r}, exit {completed.returncode}")
    return _result("node", "FAIL" if issues else "PASS",
                   {"executable": executable, "version": version, "exit_code": completed.returncode}, issues)


def _probe_geospatial() -> dict[str, Any]:
    import geopandas as gpd
    import fiona
    import pyogrio
    import pyproj
    from shapely.geometry import Point
    frame = gpd.GeoDataFrame({"id": ["probe"]}, geometry=[Point(-1.0, 7.0)], crs="EPSG:4326")
    point = frame.to_crs("EPSG:32630").geometry.iloc[0]
    if not all(math.isfinite(value) for value in (point.x, point.y)):
        raise RuntimeError("Projected coordinates are not finite")
    return _result("geospatial", "PASS", {"from_crs": "EPSG:4326", "to_crs": "EPSG:32630",
                   "coordinates": [point.x, point.y], "proj_data": pyproj.datadir.get_data_dir(),
                   "fiona": fiona.__version__, "pyogrio": pyogrio.__version__,
                   "scope": "local imports and numerical transform; no remote asset or geographic-accuracy claim"})


def _probe_numerics() -> dict[str, Any]:
    import io
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    matrix = np.array([[4.0, 1.0], [2.0, 3.0]])
    inverse = np.linalg.inv(matrix)
    if not np.allclose(matrix @ inverse, np.eye(2), atol=1e-12):
        raise RuntimeError("Native matrix inverse check failed")
    figure = Figure(figsize=(2, 1.5))
    FigureCanvasAgg(figure)
    figure.add_subplot().plot([0, 1], [0, 1])
    output = io.BytesIO()
    figure.canvas.print_png(output)
    size = len(output.getvalue())
    if size < 100:
        raise RuntimeError("Off-screen rendering produced no useful PNG")
    return _result("numerics", "PASS", {"inverse": inverse.tolist(), "agg_png_bytes": size})


def _probe_event_loop() -> dict[str, Any]:
    import asyncio
    import socket
    first, second = socket.socketpair()
    try:
        first.settimeout(2)
        second.settimeout(2)
        first.sendall(b"rp1")
        if second.recv(3) != b"rp1":
            raise RuntimeError("Socket-pair exchange failed")
    finally:
        first.close()
        second.close()
    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.close()
    return _result("event_loop", "PASS", {"socket_pair_exchange": True, "selector_loop_created_and_closed": True,
                   "scope": "independent Python standard-library probe; no project imports"})


def _probe_kernel(scratch: Path, timeout: float) -> dict[str, Any]:
    import queue
    from jupyter_client import KernelManager
    manager = KernelManager(kernel_name="python3", connection_file=str(scratch / "kernel.json"))
    # Use an ephemeral spec bound to this interpreter, without installing or
    # rewriting a user's named kernel specification.
    manager.kernel_spec.argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
    client = None
    started = False
    observed = None
    try:
        manager.start_kernel(cwd=str(scratch))
        started = True
        client = manager.client()
        client.start_channels()
        client.wait_for_ready(timeout=timeout)
        msg_id = client.execute("import sys, json\nprint('RP1_PREFLIGHT_KERNEL=' + json.dumps({'executable': sys.executable}))")
        deadline = time.monotonic() + timeout
        finished = False
        while time.monotonic() < deadline:
            try:
                message = client.get_iopub_msg(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError("Kernel execution did not reach idle") from exc
            if message.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            kind = message.get("msg_type")
            content = message.get("content", {})
            if kind == "error":
                raise RuntimeError(f"Kernel execution failed: {content.get('ename')}: {content.get('evalue')}")
            if kind == "stream":
                for line in str(content.get("text", "")).splitlines():
                    if line.startswith("RP1_PREFLIGHT_KERNEL="):
                        observed = json.loads(line.split("=", 1)[1])["executable"]
            if kind == "status" and content.get("execution_state") == "idle":
                finished = True
                break
        if not finished:
            raise TimeoutError("Kernel execution did not reach idle")
        if not observed or Path(observed).resolve() != Path(sys.executable).resolve():
            raise RuntimeError(f"Kernel interpreter differs from probe interpreter: {observed!r}")
        return _result("kernel", "PASS", {"executable": observed, "ready": True, "code_completed": True,
                       "scope": "ephemeral same-interpreter kernel; no scientific notebook was run"})
    finally:
        if started:
            manager.shutdown_kernel(now=True)
        if client is not None:
            client.stop_channels()
        manager.cleanup_resources()


def _probe_satscan(root: Path, executable: Path) -> dict[str, Any]:
    from rp1_analysis_v1.config import load_configuration_bundle, satscan_parameters
    from rp1_analysis_v1.satscan_io import executable_provenance

    config = root / "RP1_Project/rp1_analysis/config"
    expected_version = satscan_parameters(load_configuration_bundle(config).analysis).engine_version_authority
    observed = executable_provenance(executable)
    details = {"executable": observed.path, "sha256": observed.sha256,
               "version": observed.version, "expected_version": expected_version,
               "scope": "native executable version and identity only"}
    if observed.version != expected_version:
        return _result("satscan", "FAIL", details, [
            f"SaTScan Batch {expected_version} is governed by this study, observed {observed.version}"
        ])
    return _result("satscan", "PASS", details)


def worker(name: str, root: Path, scratch: Path, node: str, timeout: float,
           satscan_executable: Path | None = None) -> dict[str, Any]:
    setup = _native_environment(scratch)
    try:
        if name == "python":
            good = sys.version_info[:2] == (3, 13)
            result = _result(name, "PASS" if good else "FAIL",
                             {"version": sys.version, "executable": sys.executable,
                              "prefix": sys.prefix, "base_prefix": sys.base_prefix},
                             [] if good else ["Python 3.13 is required by the project environment"])
        elif name == "versions":
            result = _probe_versions()
        elif name == "origins":
            result = _probe_origins(root)
        elif name == "node":
            result = _probe_node(node, timeout)
        elif name == "geospatial":
            result = _probe_geospatial()
        elif name == "numerics":
            result = _probe_numerics()
        elif name == "event_loop":
            result = _probe_event_loop()
        elif name == "kernel":
            result = _probe_kernel(scratch, timeout)
        elif name == "satscan" and satscan_executable is not None:
            result = _probe_satscan(root, satscan_executable)
        else:
            raise ValueError(f"Unknown probe {name!r}")
    except (ModuleNotFoundError, importlib.metadata.PackageNotFoundError) as exc:
        result = _result(name, "UNAVAILABLE", issues=[f"{type(exc).__name__}: {exc}"])
    except Exception as exc:
        result = _result(name, "FAIL", issues=[f"{type(exc).__name__}: {exc}"])
    result["native_setup"] = setup
    return result


def descendant_pids(parent_pairs: Sequence[tuple[int, int]], root_pid: int) -> list[int]:
    """Return only observed descendants, ordered from parent to child."""
    selected: list[int] = []
    frontier = [root_pid]
    visited = {root_pid}
    while frontier:
        parent = frontier.pop(0)
        for pid, observed_parent in parent_pairs:
            if observed_parent == parent and pid > 1 and pid not in visited:
                selected.append(pid)
                frontier.append(pid)
                visited.add(pid)
    return selected


def _terminate_owned_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"
        try:
            subprocess.run([str(executable), "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        # Jupyter kernels start their own POSIX session. Enumerate the owned
        # descendants as well as terminating the worker's process group.
        try:
            listing = subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True,
                                     text=True, timeout=2, check=False)
            pairs = [tuple(map(int, line.split())) for line in listing.stdout.splitlines()
                     if re.fullmatch(r"\s*\d+\s+\d+\s*", line)]
            for pid in reversed(descendant_pids(pairs, process.pid)):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


def run_bounded(name: str, command: Sequence[str], *, cwd: Path, env: Mapping[str, str],
                timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    options: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    try:
        process = subprocess.Popen(list(command), cwd=cwd, env=dict(env), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **options)
    except OSError as exc:
        return _result(name, "UNAVAILABLE", issues=[f"Unable to launch probe: {exc}"])
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_owned_process_tree(process)
        stdout, stderr = process.communicate(timeout=5)
        result = _result(name, "FAIL", {"timeout_seconds": timeout},
                         ["Probe exceeded its time limit; its owned process tree was terminated"])
    else:
        try:
            result = json.loads(stdout)
            if not isinstance(result, dict) or result.get("status") not in STATUSES:
                raise ValueError("Unknown or absent probe status")
        except (ValueError, json.JSONDecodeError):
            result = _result(name, "FAIL", {"exit_code": process.returncode, "stdout": stdout[-4000:]},
                             ["Probe did not return a valid structured result"])
        if process.returncode != 0:
            result["status"] = "FAIL"
            result.setdefault("issues", []).append(f"Probe exited with status {process.returncode}")
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["stderr"] = stderr[-4000:]
    return result


def _external_path(path: Path, root: Path, *, directory: bool) -> Path:
    resolved = path.resolve()
    if resolved == root or resolved.is_relative_to(root) or root.is_relative_to(resolved):
        raise ValueError("Preflight evidence/scratch must be external and non-overlapping with the source checkout")
    if not directory and resolved.exists():
        raise ValueError("Use a fresh JSON evidence path; existing evidence is not overwritten")
    return resolved


def run_preflight(root: Path, *, scratch_parent: Path, timeout: float = 20,
                  kernel_timeout: float = 30, node: str = "node",
                  strict_execution: Path | None = None) -> dict[str, Any]:
    scratch_parent.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="rp1-preflight-", dir=scratch_parent) as temporary:
        scratch = Path(temporary).resolve()
        if not scratch.is_relative_to(scratch_parent.resolve()):
            raise RuntimeError("Unexpected preflight scratch location")
        executable = strict_execution.resolve() if strict_execution is not None else None
        selected_probes = PROBES if executable is None else STRICT_EXECUTION_PROBES
        for name in selected_probes:
            work = scratch / name
            work.mkdir()
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            limit = kernel_timeout if name == "kernel" else timeout
            command = [sys.executable, "-B", str(Path(__file__).resolve()), "--probe", name,
                       "--project-root", str(root), "--scratch", str(work), "--node", node,
                       "--timeout-seconds", str(limit)]
            if name == "satscan" and executable is not None:
                command.extend(("--strict-execution", str(executable)))
            results.append(run_bounded(name, command, cwd=work, env=env,
                                       timeout=(limit + 5 if name == "kernel" else limit)))
    status = "FAIL" if any(r["status"] == "FAIL" for r in results) else (
        "UNAVAILABLE" if any(r["status"] == "UNAVAILABLE" for r in results) else "PASS")
    return {"schema": "rp1-environment-preflight-v1", "status": status,
            "project_root": str(root), "interpreter": sys.executable,
            "probe_timeout_seconds": timeout, "kernel_timeout_seconds": kernel_timeout,
            "probes": results, "scope": "bounded local environment preflight; not full source, platform or scientific qualification"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--json-out", type=Path, help="Optional fresh JSON evidence file outside the source checkout")
    parser.add_argument("--work-dir", type=Path, help="External parent for temporary probe files; removed after probes")
    parser.add_argument("--timeout-seconds", type=float, default=20, help="Maximum seconds per ordinary probe")
    parser.add_argument("--kernel-timeout-seconds", type=float, default=30, help="Maximum kernel readiness/execution seconds")
    parser.add_argument("--node", default="node", help="Node.js 24 command or explicit executable path")
    parser.add_argument("--strict-execution", type=Path, metavar="SATSCAN_BATCH",
                        help="Check local sockets, a Jupyter kernel, and this governed SaTScan Batch executable")
    parser.add_argument("--probe", choices=sorted(set(PROBES) | set(STRICT_EXECUTION_PROBES)),
                        help=argparse.SUPPRESS)
    parser.add_argument("--scratch", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    if not all(math.isfinite(v) and v > 0 for v in (args.timeout_seconds, args.kernel_timeout_seconds)):
        parser.error("Probe timeouts must be finite positive numbers")
    try:
        if args.probe:
            if args.scratch is None or not args.scratch.is_dir():
                raise ValueError("An internal probe requires its prepared external scratch directory")
            scratch = _external_path(args.scratch, root, directory=True)
            print(json.dumps(worker(args.probe, root, scratch, args.node, args.timeout_seconds,
                                    args.strict_execution)))
            return 0
        output = _external_path(args.json_out, root, directory=False) if args.json_out else None
        parent = args.work_dir or (output.parent if output else Path(tempfile.gettempdir()))
        scratch_parent = _external_path(parent, root, directory=True)
        report = run_preflight(root, scratch_parent=scratch_parent, timeout=args.timeout_seconds,
                               kernel_timeout=args.kernel_timeout_seconds, node=args.node,
                               strict_execution=args.strict_execution)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation preserves an evidence file created concurrently.
            with output.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
        print(f"RP1_ENVIRONMENT_PREFLIGHT={report['status']}")
        for probe in report["probes"]:
            print(f"{probe['status']} {probe['probe']}: {'; '.join(probe['issues']) or 'completed'}")
        if output:
            print(f"Evidence: {output}")
        else:
            print(json.dumps(report, indent=2))
        return 0 if report["status"] == "PASS" else 1
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
