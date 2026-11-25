"""Observed execution identity and separately transferable evidence contracts."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess

import nbformat
import pandas as pd
import pytest

from rp1_analysis_v1 import execution_evidence as evidence, satscan_io
from rp1_analysis_v1.config import load_execution_contract
from rp1_analysis_v1.paths import ProjectPaths

FIXTURES = Path(__file__).parent / "fixtures/reference_methods/satscan"
CONTRACT_PATH = Path(__file__).parents[1] / "config/execution_contract.yml"
MCD = "MCD64A1_POISSON_PRIMARY"
VIIRS = "VIIRS_STP_PRIMARY"
CLOSEOUT_RECORD = "M_NOTEBOOK_EXECUTION.json"
EXECUTED_NOTEBOOK = "RP1_Analysis_v1.executed.ipynb"


def test_satscan_path_discovery_prefers_the_native_batch_executable(tmp_path, monkeypatch):
    suffix = ".exe" if os.name == "nt" else ""
    binary = tmp_path / f"SaTScanBatch64{suffix}"
    for candidate in (binary, tmp_path / f"SaTScanBatch{suffix}", tmp_path / f"SaTScan{suffix}"):
        candidate.write_bytes(b"discovery probe fixture")
        candidate.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert satscan_io.find_satscan_executable() == str(binary.resolve())


@pytest.mark.parametrize("version_output", ["SaTScan 10.3.3  (64-bit)\n", "SaTScan v10.3.3\n", "SaTScan version 10.3.3\n", "10.3.3\n"])
def test_actual_batch_version_output_yields_numeric_authority(tmp_path,monkeypatch,version_output):
    binary=tmp_path/"SaTScanBatch64.exe";binary.write_bytes(b"version probe fixture");binary.chmod(0o755)
    calls=[]
    def probe(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0,stdout=version_output,stderr="")
    monkeypatch.setattr(satscan_io.subprocess,"run",probe)
    observed=satscan_io.executable_provenance(binary)
    assert observed.version=="10.3.3" and observed.sha256==satscan_io.sha256_file(binary)
    assert calls==[[str(binary.resolve()),"--version"]]


def test_batch_version_probe_uses_fallback_after_unrecognized_output(tmp_path, monkeypatch):
    binary = tmp_path / "SaTScanBatch64.exe"
    binary.write_bytes(b"version probe fixture")
    binary.chmod(0o755)
    calls = []

    def probe(command, **kwargs):
        option = command[-1]
        calls.append(option)
        if option == "--version":
            return subprocess.CompletedProcess(command, 2, "", "Unrecognized command option")
        return subprocess.CompletedProcess(command, 0, "SaTScan 10.3.3 (64-bit)", "")

    monkeypatch.setattr(satscan_io.subprocess, "run", probe)
    assert satscan_io.executable_provenance(binary).version == "10.3.3"
    assert calls == ["--version", "-v"]


@pytest.mark.parametrize(
    "probe_result, expected",
    [
        (OSError("[WinError 623] Illegal System DLL Relocation"), "could not launch: [WinError 623]"),
        (OSError(8, "Exec format error"), "could not launch: [Errno 8] Exec format error"),
        (subprocess.TimeoutExpired("SaTScanBatch64.exe", 10), "timed out after 10 seconds"),
        (subprocess.CompletedProcess([], 1, "", "Wrong option"), "exited with code 1 without a recognized SaTScan version"),
    ],
)
def test_batch_version_probe_preserves_failed_attempt_diagnostics(tmp_path, monkeypatch, probe_result, expected):
    binary = tmp_path / "SaTScanBatch64.exe"
    binary.write_bytes(b"version probe fixture")
    binary.chmod(0o755)

    def probe(command, **kwargs):
        if isinstance(probe_result, Exception):
            raise probe_result
        return probe_result

    monkeypatch.setattr(satscan_io.subprocess, "run", probe)
    with pytest.raises(satscan_io.SaTScanIOError) as error:
        satscan_io.executable_provenance(binary)
    assert str(binary) in str(error.value)
    assert f"--version {expected}" in str(error.value)
    assert f"-v {expected}" in str(error.value)


def prepared(root, *, name="one", stp=False, scenario=None):
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "results").mkdir(exist_ok=True)
    paths = {"prm": root/f"inputs/{name}.prm", "case": root/f"inputs/{name}.cas",
             "coordinate": root/f"inputs/{name}.geo", "population": root/f"inputs/{name}.pop"}
    paths["case"].write_text("1 2 2020/1/1\n2 2 2020/1/1\n2 1 2020/5/1\n")
    paths["coordinate"].write_text("1 1 1\n2 2 2\n")
    if not stp: paths["population"].write_text("1 2020/1/1 100\n2 2020/1/1 100\n")
    prefix=f"results/{name}"
    paths["prm"].write_text(f"CaseFile=inputs/{name}.cas\nCoordinatesFile=inputs/{name}.geo\nPopulationFile={'inputs/'+name+'.pop' if not stp else ''}\nResultsFile={prefix}\n")
    row = {"model_id":scenario or name,"scenario_id":scenario or name,"product":"viirs" if stp else "mcd64a1",
        "model":"space_time_permutation" if stp else "discrete_poisson", "temporal_start":"2020-01",
        "temporal_end":"2020-12","max_temporal_months":12,"engine_version_authority":"10.3.3",
        "scientific_seed":20260822,"user_defined_random_seed_supported":False,
        "user_defined_random_seed_parameter":"","rng_authority":"engine_deterministic_internal_seed",
        "engine_rng_behaviour":"same_internal_seed_for_identical_input","results_prefix":prefix}
    for role,key in [("prm","prm"),("case","case"),("coordinate","coordinate"),("population","population")]:
        exists=role!="population" or not stp
        row[key+"_path"]=paths[role].relative_to(root).as_posix() if exists else ""
        row[key+"_sha256"]=satscan_io.sha256_file(paths[role]) if exists else ""
    payloads={prefix:("SaTScan v10.3.3\nRetrospective Space-Time analysis\nusing the "
        + ("Space-Time Permutation" if stp else "Discrete Poisson")
        + " model.\nStudy period: 2020/1/1 to 2020/12/31\nProgram completed\n").encode(),
        prefix+".col.txt":(FIXTURES/("known_good_stp.col.txt" if stp else "known_good.col.txt")).read_bytes(),
        prefix+".gis.txt":(FIXTURES/"known_good.gis.txt").read_bytes()}
    return row,payloads


def patch_engine(monkeypatch,root,payloads,*,mode="success",binary_root=None):
    binary=(binary_root or root)/"engine.exe";binary.write_bytes(b"synthetic executable identity")
    monkeypatch.setattr(satscan_io,"executable_provenance",lambda _:satscan_io.ExecutableProvenance(
        str(binary),satscan_io.sha256_file(binary),"10.3.3"))
    def run(command,**kwargs):
        assert kwargs["cwd"]==str(root)
        if mode=="timeout":raise subprocess.TimeoutExpired(command,1,output=b"partial console",stderr=b"timed out")
        for rel,data in payloads.items():
            (root/rel).write_bytes(data)
            newest=max(p.stat().st_mtime_ns for p in (root/"inputs").iterdir())+5_000_000
            os.utime(root/rel,ns=(newest,newest))
        if mode=="input_change":
            next((root/"inputs").glob("*.cas")).write_text("changed during external process\n")
        if mode=="binary_change":binary.write_bytes(b"changed binary")
        return SimpleNamespace(returncode=2 if mode=="failure" else 0,stdout="observed stdout",stderr="observed stderr")
    monkeypatch.setattr(satscan_io.subprocess,"run",run)
    return binary


@pytest.mark.parametrize("stp",[False,True])
def test_observed_execution_receipt_roundtrip_and_parser_linkage(tmp_path,monkeypatch,stp):
    row,payloads=prepared(tmp_path,stp=stp);binary=patch_engine(monkeypatch,tmp_path,payloads)
    result=evidence.execute_satscan_with_evidence(run_row=row,run_dir=tmp_path,executable_path=binary,alpha=.05)
    assert result["status"]=="PASS" and result["inputs_before"]==result["inputs_after"]
    receipt=tmp_path/result["receipt_path"]
    saved=evidence.validate_satscan_execution_receipt(receipt,run_row=row,run_dir=tmp_path)
    assert saved["command"]==[str(binary),str(tmp_path/row["prm_path"])]
    assert saved["return_code"]==0 and saved["executable"]["version"]=="10.3.3"
    parsed=satscan_io.validate_external_results(row,run_dir=tmp_path,alpha=.05)
    assert parsed.provenance["executable_sha256"]==satscan_io.sha256_file(binary)
    assert parsed.provenance["execution_receipt_sha256"]==satscan_io.sha256_file(receipt)
    with pytest.raises(satscan_io.ExternalResultValidationError,match="existing"):
        evidence.execute_satscan_with_evidence(run_row=row,run_dir=tmp_path,executable_path=binary,alpha=.05)


@pytest.mark.parametrize("target",["results/one.col.txt","results/one.stdout.log","inputs/one.cas"])
def test_receipt_cannot_silently_accept_changed_outputs_logs_or_inputs(tmp_path,monkeypatch,target):
    row,payloads=prepared(tmp_path);binary=patch_engine(monkeypatch,tmp_path,payloads)
    evidence.execute_satscan_with_evidence(run_row=row,run_dir=tmp_path,executable_path=binary,alpha=.05)
    (tmp_path/target).write_bytes(b"changed")
    with pytest.raises(satscan_io.ExternalResultValidationError):
        satscan_io.validate_external_results(row,run_dir=tmp_path,alpha=.05)


@pytest.mark.parametrize("mutation", ["change", "remove", "add", "legacy"])
def test_observed_receipt_binds_optional_monte_carlo_maxima(tmp_path, monkeypatch, mutation):
    row, payloads = prepared(tmp_path)
    relative = row["results_prefix"] + ".llr.txt"
    if mutation != "add":
        payloads[relative] = b"LLR\n5.23\n"
    binary = patch_engine(monkeypatch, tmp_path, payloads)
    observed = evidence.execute_satscan_with_evidence(run_row=row, run_dir=tmp_path, executable_path=binary, alpha=.05)
    receipt = tmp_path / observed["receipt_path"]
    maxima = tmp_path / relative
    assert observed["schema"] == "rp1-satscan-observed-execution-v2"
    assert ("monte_carlo_maxima" in observed["outputs"]) == (mutation != "add")
    if mutation != "add":
        identity = observed["outputs"]["monte_carlo_maxima"]
        assert identity == {"path": relative, "sha256": satscan_io.sha256_file(maxima), "bytes": maxima.stat().st_size}
    if mutation == "legacy":
        saved = json.loads(receipt.read_text())
        saved["schema"] = "rp1-satscan-observed-execution-v1"
        del saved["outputs"]["monte_carlo_maxima"]
        receipt.write_text(json.dumps(saved))
        assert evidence.validate_satscan_execution_receipt(receipt, run_row=row, run_dir=tmp_path) == saved
        return
    if mutation == "remove":
        maxima.unlink()
    else:
        maxima.write_bytes(b"LLR\n5.24\n")
    with pytest.raises(satscan_io.ExternalResultValidationError, match="outputs (membership|hash) mismatch"):
        evidence.validate_satscan_execution_receipt(receipt, run_row=row, run_dir=tmp_path)


def test_observed_receipt_refuses_to_claim_existing_monte_carlo_maxima(tmp_path, monkeypatch):
    row, payloads = prepared(tmp_path)
    maxima = tmp_path / (row["results_prefix"] + ".llr.txt")
    maxima.write_bytes(b"existing auxiliary evidence")
    binary = patch_engine(monkeypatch, tmp_path, payloads)
    with pytest.raises(satscan_io.ExternalResultValidationError, match="existing output/evidence"):
        evidence.execute_satscan_with_evidence(run_row=row, run_dir=tmp_path, executable_path=binary, alpha=.05)
    assert maxima.read_bytes() == b"existing auxiliary evidence"


@pytest.mark.parametrize("mode",["input_change","binary_change","failure","timeout"])
def test_failed_attempt_never_receives_success_attestation(tmp_path,monkeypatch,mode):
    row,payloads=prepared(tmp_path);binary=patch_engine(monkeypatch,tmp_path,payloads,mode=mode)
    with pytest.raises((satscan_io.ExternalResultValidationError,subprocess.TimeoutExpired)):
        evidence.execute_satscan_with_evidence(run_row=row,run_dir=tmp_path,executable_path=binary,alpha=.05)
    assert not (tmp_path/"results/one.execution.json").exists()
    failed=json.loads((tmp_path/"results/one.execution.failed.json").read_text())
    assert failed["status"]=="FAIL" and failed["execution_observed"] is True
    assert not (tmp_path/"results/one.execution.lock").exists()


@pytest.mark.parametrize("suffix", ["", ".llr.txt"])
def test_receipt_rejects_native_bytes_changed_after_engine_validation(tmp_path, monkeypatch, suffix):
    row, payloads = prepared(tmp_path)
    relative = row["results_prefix"] + suffix
    if suffix:
        payloads[relative] = b"LLR\n5.23\n"
    binary = patch_engine(monkeypatch, tmp_path, payloads)
    run = satscan_io.run_satscan

    def change_output(**kwargs):
        result = run(**kwargs)
        (tmp_path / relative).write_bytes(b"unvalidated output")
        return result

    monkeypatch.setattr(satscan_io, "run_satscan", change_output)
    with pytest.raises(satscan_io.ExternalResultValidationError, match="changed after validation"):
        evidence.execute_satscan_with_evidence(run_row=row, run_dir=tmp_path, executable_path=binary, alpha=.05)
    assert not (tmp_path / "results/one.execution.json").exists()
    assert (tmp_path / "results/one.execution.failed.json").is_file()


def test_receipt_failure_in_terminal_validation_leaves_no_pass_marker(tmp_path, monkeypatch):
    row, payloads = prepared(tmp_path)
    binary = patch_engine(monkeypatch, tmp_path, payloads)
    publish = evidence._publish

    def change_output_after_recording_log(path, data):
        publish(path, data)
        if path.name == "one.stdout.log":
            (tmp_path / "results/one").write_bytes(b"unvalidated output")

    monkeypatch.setattr(evidence, "_publish", change_output_after_recording_log)
    with pytest.raises(satscan_io.ExternalResultValidationError, match="outputs hash mismatch"):
        evidence.execute_satscan_with_evidence(run_row=row, run_dir=tmp_path, executable_path=binary, alpha=.05)
    assert not (tmp_path / "results/one.execution.json").exists()
    assert (tmp_path / "results/one.execution.failed.json").is_file()


def test_wrong_version_is_rejected_before_process_and_failure_is_honest(tmp_path,monkeypatch):
    row,payloads=prepared(tmp_path);binary=patch_engine(monkeypatch,tmp_path,payloads)
    monkeypatch.setattr(satscan_io,"executable_provenance",lambda _:satscan_io.ExecutableProvenance(str(binary),satscan_io.sha256_file(binary),"99.1"))
    with pytest.raises(satscan_io.ExternalResultValidationError,match="version"):
        evidence.execute_satscan_with_evidence(run_row=row,run_dir=tmp_path,executable_path=binary,alpha=.05)
    assert not (tmp_path/"results/one").exists()
    failed=json.loads((tmp_path/"results/one.execution.failed.json").read_text())
    assert failed["execution_observed"] is False


def test_receipt_identity_and_paths_cannot_be_relabelled(tmp_path,monkeypatch):
    row,payloads=prepared(tmp_path);binary=patch_engine(monkeypatch,tmp_path,payloads)
    result=evidence.execute_satscan_with_evidence(run_row=row,run_dir=tmp_path,executable_path=binary,alpha=.05)
    receipt=tmp_path/result["receipt_path"];record=json.loads(receipt.read_text())
    record["scenario_id"]="another model";receipt.write_text(json.dumps(record))
    with pytest.raises(satscan_io.ExternalResultValidationError,match="identity mismatch"):
        satscan_io.validate_external_results(row,run_dir=tmp_path,alpha=.05)


@pytest.mark.parametrize("key", ["CaseFile", "CoordinatesFile", "PopulationFile", "ResultsFile"])
def test_observed_execution_rejects_parameter_input_path_substitution(tmp_path,monkeypatch,key):
    row,payloads=prepared(tmp_path);binary=patch_engine(monkeypatch,tmp_path,payloads)
    parameter=tmp_path/row["prm_path"]
    lines=parameter.read_text().splitlines()
    parameter.write_text("\n".join(key+"=inputs/unrecorded" if line.startswith(key+"=") else line for line in lines)+"\n")
    row["prm_sha256"]=satscan_io.sha256_file(parameter)
    with pytest.raises(satscan_io.ExternalResultValidationError,match="Parameter "+key):
        evidence.execute_satscan_with_evidence(run_row=row,run_dir=tmp_path,executable_path=binary,alpha=.05)
    failed=json.loads((tmp_path/"results/one.execution.failed.json").read_text())
    assert failed["execution_observed"] is False and not (tmp_path/"results/one").exists()


def test_in_progress_execution_cannot_be_ingested_and_receipt_command_is_bound(tmp_path,monkeypatch):
    row,payloads=prepared(tmp_path);binary=patch_engine(monkeypatch,tmp_path,payloads)
    result=evidence.execute_satscan_with_evidence(run_row=row,run_dir=tmp_path,executable_path=binary,alpha=.05)
    lock=tmp_path/"results/one.execution.lock";lock.write_text("interrupted")
    with pytest.raises(satscan_io.ExternalResultValidationError,match="in progress or interrupted"):
        satscan_io.validate_external_results(row,run_dir=tmp_path,alpha=.05)
    lock.unlink()
    receipt=tmp_path/result["receipt_path"];record=json.loads(receipt.read_text())
    record["command"][1]=str(tmp_path/"inputs/another.prm");receipt.write_text(json.dumps(record))
    with pytest.raises(satscan_io.ExternalResultValidationError,match="governed parameter file"):
        satscan_io.validate_external_results(row,run_dir=tmp_path,alpha=.05)


def _write_primary_fixture(sec, rows, receipts, external_evidence):
    from rp1_analysis_v1.config import load_analysis_contract, satscan_parameters
    from rp1_analysis_v1.publication_sources import build_satscan_publication_sources
    from rp1_analysis_v1.satscan_integration import RUN_LOCAL_SOURCE_DIR, RUN_LOCAL_SOURCE_MANIFEST
    from rp1_analysis_v1.secondary_clusters import load_scan_scenarios
    from rp1_analysis_v1.validation import AnalyticalMask

    analysis = load_analysis_contract(CONTRACT_PATH.with_name("analysis_contract.yml"))
    parsed = {row["model_id"]: satscan_io.validate_external_results(
        row, run_dir=sec, alpha=satscan_parameters(analysis).alpha, enforce_freshness=False,
    ) for row in rows}
    location = pd.DataFrame({
        "location_id": [1, 2, 3], "unit_id": ["a", "b", "c"],
        "unit_name": ["A district", "B district", "C district"], "parent_code": ["FZ"] * 3,
        "parent_name": ["Forest"] * 3, "x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0],
        "anchor_method": ["polygon_centroid"] * 3,
    })
    location.to_csv(sec / "04_secondary_concentration/tables/secondary_location_authority.csv", index=False)
    units = location[["unit_id"]].assign(eligible=[True, True, False], exclusion_reasons=["", "", "fixture exclusion"])
    sources = build_satscan_publication_sources(
        parsed_by_model=parsed, scenarios=load_scan_scenarios(analysis), location_authority=location,
        data_contract=SimpleNamespace(long_run_mask=AnalyticalMask("long_run", units),
                                      paired_mask=AnalyticalMask("paired", units)),
        run_registry=pd.DataFrame(rows), run_dir=sec,
    )
    source_dir = sec / RUN_LOCAL_SOURCE_DIR
    source_dir.mkdir()
    entries = {}
    for name, frame in sources.items():
        path = source_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        entries[name] = {
            "path": path.relative_to(sec).as_posix(), "sha256": satscan_io.sha256_file(path),
            "size_bytes": path.stat().st_size, "rows": len(frame), "columns": list(frame.columns),
        }
    (source_dir / RUN_LOCAL_SOURCE_MANIFEST).write_text(json.dumps({
        "schema": "rp1-satscan-run-local-publication-sources-v2", "source_policy": "run_local_only",
        "satscan_execution_performed_by_notebook": False, "model_count": len(rows),
        "engine_version_authority": satscan_parameters(analysis).engine_version_authority,
        "secondary_run_id": "example_sec", "external_execution_state": "RESULTS_VALIDATED",
        "external_execution_evidence": external_evidence, "execution_receipts": receipts, "sources": entries,
    }))
    return analysis.to_dict(), sources, f"{RUN_LOCAL_SOURCE_DIR}/{RUN_LOCAL_SOURCE_MANIFEST}"


def _write_publication_fixture(pub, close, analysis, primary_sources, restricted_sources):
    """Supply the same embedded registry structure as a completed publication run."""
    attributes = ("restricted_scan_summary", "restricted_scan_clusters", "restricted_scan_recurrence",
                  "restricted_scan_window_comparison")
    specs, registry = [], []
    sources = {"fixture": pd.DataFrame({"value": [1]})} | primary_sources | restricted_sources
    ids = {"FIXTURE": "fixture", "T3": "table3_satscan_clusters", "S6": "supplement_s6_satscan",
           **dict(zip(("S21", "S22", "S23", "S24"), attributes, strict=True))}
    for table_id, attribute in ids.items():
        restricted_table = attribute in attributes
        primary_table = table_id in {"T3", "S6"}
        columns = list(primary_sources[attribute].columns) if primary_table and primary_sources else [
            "scenario_id" if table_id == "S21" else "value",
        ]
        info = {"rq": "SECONDARY", "title": table_id, "role": "supplementary",
                "family_id": table_id, "evidence_class": "SENSITIVITY"}
        specs.append({"id": table_id, **info, "source_attribute": attribute, "required_columns": columns,
                      "builder_options": {"requires_restricted_scan": restricted_table,
                                          "genuine_external_results_required": primary_table},
                      "requires_results_validated": restricted_table or primary_table or not primary_sources})
        frame = sources.get(attribute)
        identity = {"availability": "RESTRICTED_SCAN_RESULTS_REQUIRED", "path": "", "sha256": "", "size_bytes": 0}
        if primary_table:
            identity["availability"] = "EXTERNAL_RESULTS_REQUIRED"
        if frame is not None:
            relative = f"04_secondary_concentration/tables/{table_id}.csv"
            path = pub / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            frame[columns].to_csv(path, index=False)
            identity = {"availability": "AVAILABLE", "path": relative,
                        "sha256": satscan_io.sha256_file(path), "size_bytes": path.stat().st_size}
        registry.append({"table_id": table_id, **info, **identity})
    registered = pub / "90_integrated"
    registered.mkdir()
    pd.DataFrame(registry).to_csv(registered / "T_TABLE_REGISTRY.csv", index=False)
    recurrence_path = "04_secondary_concentration/figure_data/FD_F6.csv"
    manifest_path = "04_secondary_concentration/manifests/F6.manifest.json"
    figure_data = {"columns": []}
    if primary_sources:
        recurrence = primary_sources["cluster_recurrence_source"]
        (pub / recurrence_path).parent.mkdir()
        recurrence.to_csv(pub / recurrence_path, index=False)
        figure_data = {"path": recurrence_path, "sha256": satscan_io.sha256_file(pub / recurrence_path),
                       "rows": len(recurrence), "size_bytes": (pub / recurrence_path).stat().st_size,
                       "columns": list(recurrence.columns)}
        (pub / manifest_path).parent.mkdir()
        (pub / manifest_path).write_text(json.dumps({
            "configuration_sha256": "a" * 64, "figure_id": "F6", "availability": "AVAILABLE",
            "source_attribute": "cluster_recurrence_source", "figure_data": figure_data,
        }))
        pd.DataFrame([{
            "figure_id": "F6", "rq": "SECONDARY", "title": "Recurrence", "role": "manuscript",
            "evidence_class": "DESCRIPTIVE", "availability": "AVAILABLE", "figure_data_path": recurrence_path,
            "figure_data_sha256": figure_data["sha256"], "png_path": "", "pdf_path": "", "manifest_path": manifest_path,
        }]).to_csv(registered / "T_FIGURE_REGISTRY.csv", index=False)
    artefacts = [{"path": path.relative_to(pub).as_posix(), "sha256": satscan_io.sha256_file(path),
                  "size_bytes": path.stat().st_size} for path in sorted(pub.rglob("*")) if path.is_file()]
    pd.DataFrame(artefacts).to_csv(registered / "T_ARTEFACT_REGISTRY.csv", index=False)
    config = close.parent / "00_scaffold/realised_configuration.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"configuration_sha256": "a"*64, "contracts": {
        "analysis_contract.yml": analysis,
        "output_contract.yml": {"publication_outputs": {"tables": specs}},
        "figure_contract.yml": {"figures": [{"id": "F6", "source_attribute": "cluster_recurrence_source",
                                             "required_columns": figure_data["columns"]}]},
    }}))


def synthetic_run(tmp_path,monkeypatch,*,snapshot=True,receipts=False, restricted=True):
    import rp1_analysis_v1.integration as integration
    import rp1_analysis_v1.config as config
    root=tmp_path/"analysis";root.mkdir();paths=ProjectPaths(root)
    (root/"config").mkdir()
    (root/"config/fixture.yml").write_text("fixture: source-authority\n")
    (root/"pyproject.toml").write_text('[project]\nversion = "1.3.1"\n')
    close=root/"out/runs/example_close/99_closeout";close.mkdir(parents=True)
    sec=root/"out/runs/example_sec";sec.mkdir(parents=True)
    pub=root/"out/runs/example_pub";pub.mkdir(parents=True);(pub/"table.csv").write_text("x\n1\n")
    nb=nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("print(1)")])
    nbformat.write(nb,root/"RP1_Analysis_v1.ipynb")
    nb.cells[0]["execution_count"]=1;nb.cells[0]["outputs"]=[nbformat.v4.new_output("stream",name="stdout",text="1\n")]
    notebook=close/EXECUTED_NOTEBOOK
    if snapshot:nbformat.write(nb,notebook)
    sections = {name: "PASS" for name in ("scaffold", "rq1", "rq2", "rq3", "secondary")}
    gate = close / "M_CANONICAL_EXECUTION_GATE.json"
    provenance = close / "M_REPRODUCIBILITY_MANIFEST.json"
    gate.write_text(json.dumps({**{f"{name}_gate": value for name, value in sections.items()},
        "publication_gate": "PASS", "final_run_gate": "PASS", "input_validation_status": "PASS",
        "canonical_input_identity": "MATCH", "configuration_sha256": "a"*64}))
    provenance.write_text(json.dumps({"run_id": "example_close", "configuration_sha256": "a"*64,
        "ended_at_utc": "2026-11-22T01:00:00Z",
        "input_validation_status": "PASS", "canonical_input_identity": "MATCH",
        "inputs": [{"path": "source.csv", "sha256": "a"*64, "size_bytes": 10}]}))
    record={"secondary_execution_state":"RESULTS_VALIDATED","notebook_snapshot_available":snapshot,
        "execution_mode":"controlled_nbclient" if snapshot else "interactive_jupyter",
        "schema": "rp1-notebook-execution-v3", "run_id": "example", "status": "PASS",
        "canonical_notebook": "RP1_Analysis_v1.ipynb", "canonical_gate_status": "PASS",
        "canonical_gate_sha256": satscan_io.sha256_file(gate), "publication_gate_status": "PASS",
        "reproducibility_manifest_sha256": satscan_io.sha256_file(provenance),
        "canonical_input_identity": "MATCH", "configuration_sha256": "a"*64,
        "operational_configuration_sha256": "b"*64, "analysis_schema_version": "fixture",
        "data_schema_version": "fixture", "package_version": "1.3.1", "final_section_reached": True,
        "input_validation_status": "PASS", "secondary_integration_state": "INTEGRATED",
        "secondary_validated_model_count": 2, "satscan_execution_performed": False,
        "notebook_snapshot_required": snapshot, "completion_timestamp_utc": "2026-11-22T01:00:00Z",
        "section_gates": sections}
    if snapshot:
        record.update(executed_notebook_sha256=satscan_io.sha256_file(notebook), kernel_name="python3",
                      execution_cwd_policy="fixture", code_cells=1, executed_code_cells=1)
    else:
        record["provenance_limitations"] = ["No observed notebook execution fixture"]
    (close/CLOSEOUT_RECORD).write_text(json.dumps(record))
    rows=[]
    integrated_receipts = {}
    for name,stp in [(MCD,False),(VIIRS,True)]:
        row,payloads=prepared(sec,name=name,stp=stp)
        row["execution_state"] = "RESULTS_VALIDATED"
        rows.append(row)
        if receipts:
            binary=patch_engine(monkeypatch,sec,payloads,binary_root=sec.parent)
            observed = evidence.execute_satscan_with_evidence(run_row=row,run_dir=sec,executable_path=binary,alpha=.05)
            integrated_receipts[name] = {
                "execution_receipt_path": observed["receipt_path"], "execution_receipt_sha256": observed["receipt_sha256"],
                **{f"executable_{name}": observed["executable"][name] for name in ("path", "version", "sha256")},
            }
        else:
            for relative, content in payloads.items():
                (sec / relative).write_bytes(content)
    registry=sec/"04_secondary_concentration/tables/secondary_run_registry.csv";registry.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(registry,index=False)
    status = registry.parent.parent / "secondary_external_execution_status.json"
    external_evidence = "RECORDED_EXECUTION" if receipts else "RESULT_FILES_ONLY"
    analysis, primary_sources, source_manifest = _write_primary_fixture(sec, rows, integrated_receipts, external_evidence)
    status.write_text(json.dumps({"external_execution_state": "RESULTS_VALIDATED", "validated_model_count": 2,
        "run_local_publication_source_manifest": source_manifest,
        "external_execution_evidence": external_evidence, "satscan_execution_receipts": integrated_receipts}))
    restricted_sources = {}
    if receipts and restricted:
        from rp1_analysis_v1 import scan_sensitivity
        from rp1_analysis_v1.publication import restricted_scan_publication_sources
        nested = sec / "support_sensitivity"
        nested.mkdir()
        row, payloads = prepared(nested, name="modis_gt50", stp=False, scenario=scan_sensitivity.SCENARIO_ID)
        binary = patch_engine(monkeypatch, nested, payloads, binary_root=sec.parent)
        observed = evidence.execute_satscan_with_evidence(run_row=row, run_dir=nested, executable_path=binary, alpha=.05)
        summary = {"scenario_id": scan_sensitivity.SCENARIO_ID, "excluded_districts_by_acz": {}, "execution_receipt": {
            "path": observed["receipt_path"], "sha256": observed["receipt_sha256"]}}
        summary_path = scan_sensitivity.scan_sensitivity_summary_path(nested)
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text(json.dumps(summary))
        (nested / "modis_gt50_design.json").write_text(json.dumps({
            "scenario_id": scan_sensitivity.SCENARIO_ID, "baseline_secondary_run": "example_sec", "run_authority": row}))
        frames = {name: pd.DataFrame({"value": [number]}) for number, name in
                  enumerate(("clusters", "recurrence", "window_comparison"), start=1)}
        restricted_sources = restricted_scan_publication_sources(summary, **frames)
        monkeypatch.setattr(scan_sensitivity, "validate_scan_sensitivity",
                            lambda **_: SimpleNamespace(summary=summary, **frames))
    _write_publication_fixture(pub, close, analysis, primary_sources, restricted_sources)
    monkeypatch.setattr(integration,"validate_run_authority",lambda **_:SimpleNamespace(status="PASS"))
    monkeypatch.setattr(config,"load_configuration_bundle",lambda _:SimpleNamespace(configuration_sha256="a"*64,
        execution=load_execution_contract(CONTRACT_PATH)))
    return paths,close


def test_strict_export_rejects_missing_execution_claims_without_writing(tmp_path,monkeypatch):
    paths,_=synthetic_run(tmp_path,monkeypatch,snapshot=False)
    destination=tmp_path/"bundle"
    with pytest.raises(satscan_io.ExternalResultValidationError,match="Strict"):
        evidence.export_execution_evidence(paths=paths,run_id="example",output_dir=destination)
    assert not destination.exists()


def test_explicit_limited_export_does_not_upgrade_history_and_is_transfer_verifiable(tmp_path,monkeypatch):
    paths,close=synthetic_run(tmp_path,monkeypatch,snapshot=False)
    before=(close/CLOSEOUT_RECORD).read_bytes()
    destination=tmp_path/"bundle"
    result=evidence.export_execution_evidence(paths=paths,run_id="example",output_dir=destination,allow_declared_limitations=True)
    assert result["status"]=="DECLARED_LIMITATIONS" and len(result["limitations"])==4
    assert (close/CLOSEOUT_RECORD).read_bytes()==before
    assert evidence.validate_execution_evidence_bundle(destination)["status"]=="DECLARED_LIMITATIONS"
    (destination/"publication/table.csv").write_text("changed")
    with pytest.raises(satscan_io.ExternalResultValidationError,match="hash mismatch"):
        evidence.validate_execution_evidence_bundle(destination)


def test_strict_bundle_requires_observed_receipts_and_complete_matching_notebook(tmp_path,monkeypatch):
    paths,close=synthetic_run(tmp_path,monkeypatch,receipts=True)
    destination=tmp_path/"bundle"
    result=evidence.export_execution_evidence(paths=paths,run_id="example",output_dir=destination)
    assert result["status"]=="QUALIFIED_EXECUTION_EVIDENCE"
    manifest=evidence.validate_execution_evidence_bundle(destination)
    assert len(manifest["observed_execution_receipts"])==3
    assert manifest["notebook_identity"]["executed_sha256"]==satscan_io.sha256_file(close/EXECUTED_NOTEBOOK)
    with pytest.raises(satscan_io.ExternalResultValidationError,match="fresh"):
        evidence.export_execution_evidence(paths=paths,run_id="example",output_dir=destination)


@pytest.mark.parametrize("qualified", [False, True])
def test_transfer_relocation_and_expected_manifest_checksum(tmp_path, monkeypatch, qualified):
    paths, _ = synthetic_run(tmp_path, monkeypatch, snapshot=qualified, receipts=qualified)
    initial = tmp_path / "initial"
    result = evidence.export_execution_evidence(
        paths=paths, run_id="example", output_dir=initial, allow_declared_limitations=not qualified,
    )
    relocated = tmp_path / "relocated with spaces"
    initial.rename(relocated)
    paths.root.rename(tmp_path / "source relocated")
    validated = evidence.validate_execution_evidence_bundle(relocated, expected_manifest_sha256=result["manifest_sha256"])
    assert validated["status"] == result["status"]
    with pytest.raises(satscan_io.ExternalResultValidationError, match="manifest hash"):
        evidence.validate_execution_evidence_bundle(relocated, expected_manifest_sha256="0" * 64)


@pytest.mark.parametrize(("table_id", "rehash_registries"), [
    ("FIXTURE", False), ("S21", True), ("S22", True), ("S23", True), ("S24", True),
])
def test_unpinned_transfer_rejects_rehashed_publication_tables(tmp_path, monkeypatch, table_id, rehash_registries):
    paths, _ = synthetic_run(tmp_path, monkeypatch, receipts=True)
    bundle = tmp_path / "bundle"
    evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=bundle)
    manifest_path = bundle / "EXECUTION_EVIDENCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    publication = bundle / "publication"
    relative = f"04_secondary_concentration/tables/{table_id}.csv"
    table = publication / relative
    frame = pd.read_csv(table)
    frame.iloc[0, 0] = "counterfeit" if table_id == "S21" else 700
    frame.to_csv(table, index=False)

    def repin(path):
        identity = {"sha256": satscan_io.sha256_file(path), "bytes": path.stat().st_size}
        manifest["files"][path.relative_to(bundle).as_posix()] = identity
        return [identity["sha256"], str(identity["bytes"])]

    table_identity = repin(table)
    if rehash_registries:
        tab_path = publication / "90_integrated/T_TABLE_REGISTRY.csv"
        tab = pd.read_csv(tab_path, dtype=str, keep_default_na=False)
        tab.loc[tab["table_id"].eq(table_id), ["sha256", "size_bytes"]] = table_identity
        tab.to_csv(tab_path, index=False)
        art_path = publication / "90_integrated/T_ARTEFACT_REGISTRY.csv"
        art = pd.read_csv(art_path, dtype=str, keep_default_na=False)
        art.loc[art["path"].eq(relative), ["sha256", "size_bytes"]] = table_identity
        art.loc[art["path"].eq(tab_path.relative_to(publication).as_posix()), ["sha256", "size_bytes"]] = repin(tab_path)
        art.to_csv(art_path, index=False)
        repin(art_path)
    manifest_path.write_text(json.dumps(manifest))
    match = f"contradicts restricted scan results: {table_id}" if rehash_registries else "artefact registry hash"
    with pytest.raises(satscan_io.ExternalResultValidationError, match=match):
        evidence.validate_execution_evidence_bundle(bundle)


def _refresh_bundle_file(bundle, manifest, path):
    identity = {"sha256": satscan_io.sha256_file(path), "bytes": path.stat().st_size}
    manifest["files"][path.relative_to(bundle).as_posix()] = identity
    return identity


def test_legacy_pending_publication_accepts_present_non_scan_table(tmp_path):
    publication = tmp_path / "publication"
    publication.mkdir()
    closeout = tmp_path / "closeout" / "99_closeout"
    closeout.parent.mkdir()
    _write_publication_fixture(publication, closeout, {}, {}, {})
    record = {"configuration_sha256": "a" * 64, "files": {}}
    for path in publication.rglob("*.csv"):
        _refresh_bundle_file(tmp_path, record, path)
    evidence._validate_transferred_publication(
        tmp_path, record=record, secondary_rows=[], secondary_status={"external_execution_state": "EXTERNAL_RESULTS_REQUIRED"},
        restricted_sources={},
    )


@pytest.mark.parametrize(("field", "value", "match"), [
    ("path", "04_secondary_concentration/publication_sources/table3_satscan_clusters.csv", "path, hash or size"),
    ("size_bytes", 1, "path, hash or size"),
    ("sha256", "a" * 64, "path, hash or size"),
    ("columns", ["unit_id"], "column mismatch"),
    ("rows", 1, "row count mismatch"),
])
def test_portable_bundle_rejects_stale_primary_source_identity(tmp_path, monkeypatch, field, value, match):
    paths, _ = synthetic_run(tmp_path, monkeypatch, snapshot=False)
    bundle = tmp_path / "bundle"
    evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=bundle,
                                       allow_declared_limitations=True)
    manifest_path = bundle / "EXECUTION_EVIDENCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    source_manifest = (bundle / "secondary/04_secondary_concentration/publication_sources/"
                       "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json")
    inner = json.loads(source_manifest.read_text())
    inner["sources"]["cluster_recurrence_source"][field] = value
    source_manifest.write_text(json.dumps(inner))
    _refresh_bundle_file(bundle, manifest, source_manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(satscan_io.ExternalResultValidationError, match=match):
        evidence.validate_execution_evidence_bundle(bundle)


def test_portable_primary_source_values_are_reconstructed_from_native_membership(tmp_path, monkeypatch):
    paths, _ = synthetic_run(tmp_path, monkeypatch, snapshot=False)
    bundle = tmp_path / "bundle"
    evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=bundle,
                                       allow_declared_limitations=True)
    manifest_path = bundle / "EXECUTION_EVIDENCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    secondary = bundle / "secondary"
    source_manifest = (secondary / "04_secondary_concentration/publication_sources/"
                       "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json")
    inner = json.loads(source_manifest.read_text())
    source = inner["sources"]["cluster_membership_source"]
    path = secondary / source["path"]
    frame = pd.read_csv(path)
    frame.loc[0, "cluster_id"] = int(frame.loc[0, "cluster_id"]) + 50
    frame.to_csv(path, index=False)
    _refresh_bundle_file(bundle, manifest, path)
    source.update(sha256=satscan_io.sha256_file(path), size_bytes=path.stat().st_size)
    source_manifest.write_text(json.dumps(inner))
    _refresh_bundle_file(bundle, manifest, source_manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(satscan_io.ExternalResultValidationError,
                       match="Publication source contradicts native SaTScan results: cluster_membership_source"):
        evidence.validate_execution_evidence_bundle(bundle)


@pytest.mark.parametrize("projection", ["T3", "S6", "FD_F6"])
def test_portable_bundle_reconciles_primary_publication_projection(tmp_path, monkeypatch, projection):
    paths, _ = synthetic_run(tmp_path, monkeypatch, snapshot=False)
    bundle = tmp_path / "bundle"
    evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=bundle,
                                       allow_declared_limitations=True)
    manifest_path = bundle / "EXECUTION_EVIDENCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    publication = bundle / "publication"
    artefact_path = publication / "90_integrated/T_ARTEFACT_REGISTRY.csv"
    artefacts = pd.read_csv(artefact_path, dtype=str, keep_default_na=False)

    def refresh_publication_file(path):
        identity = _refresh_bundle_file(bundle, manifest, path)
        selected = artefacts["path"].eq(path.relative_to(publication).as_posix())
        artefacts.loc[selected, ["sha256", "size_bytes"]] = [identity["sha256"], str(identity["bytes"])]
        return identity

    if projection == "FD_F6":
        target = publication / "04_secondary_concentration/figure_data/FD_F6.csv"
        frame = pd.read_csv(target)
        frame.loc[0, "significant_cluster_count"] = int(frame.loc[0, "significant_cluster_count"]) + 1
        frame.to_csv(target, index=False)
        identity = refresh_publication_file(target)
        figure = publication / "04_secondary_concentration/manifests/F6.manifest.json"
        figure_manifest = json.loads(figure.read_text())
        figure_manifest["figure_data"].update(sha256=identity["sha256"], size_bytes=identity["bytes"])
        figure.write_text(json.dumps(figure_manifest))
        refresh_publication_file(figure)
        figure_registry = publication / "90_integrated/T_FIGURE_REGISTRY.csv"
        figures = pd.read_csv(figure_registry, dtype=str, keep_default_na=False)
        figures.loc[figures["figure_id"].eq("F6"), "figure_data_sha256"] = identity["sha256"]
        figures.to_csv(figure_registry, index=False)
        refresh_publication_file(figure_registry)
    else:
        target = publication / f"04_secondary_concentration/tables/{projection}.csv"
        frame = pd.read_csv(target)
        frame.loc[0, "observed"] = float(frame.loc[0, "observed"]) + 1
        frame.to_csv(target, index=False)
        identity = refresh_publication_file(target)
        table_registry = publication / "90_integrated/T_TABLE_REGISTRY.csv"
        tables = pd.read_csv(table_registry, dtype=str, keep_default_na=False)
        tables.loc[tables["table_id"].eq(projection), ["sha256", "size_bytes"]] = [
            identity["sha256"], str(identity["bytes"]),
        ]
        tables.to_csv(table_registry, index=False)
        refresh_publication_file(table_registry)
    artefacts.to_csv(artefact_path, index=False)
    _refresh_bundle_file(bundle, manifest, artefact_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(satscan_io.ExternalResultValidationError, match=f"contradicts primary scan results: {projection}"):
        evidence.validate_execution_evidence_bundle(bundle)


@pytest.mark.parametrize("duplicate_status", [False, True])
def test_transferred_limited_snapshot_cannot_claim_strict_qualification(tmp_path, monkeypatch, duplicate_status):
    paths, _ = synthetic_run(tmp_path, monkeypatch, snapshot=False)
    destination = tmp_path / "bundle"
    evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=destination,
                                       allow_declared_limitations=True)
    manifest_path = destination / "EXECUTION_EVIDENCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    if duplicate_status:
        manifest_path.write_text(json.dumps(manifest)[:-1] + ', "status": "QUALIFIED_EXECUTION_EVIDENCE"}')
        match = "Repeated JSON key"
    else:
        manifest.update(status="QUALIFIED_EXECUTION_EVIDENCE", limitations=[])
        manifest_path.write_text(json.dumps(manifest))
        match = "declared limitations contradict"
    with pytest.raises(satscan_io.ExternalResultValidationError, match=match):
        evidence.validate_execution_evidence_bundle(destination)


@pytest.mark.parametrize("tamper", ["missing_restricted", "duplicate_primary", "relabeled", "receipt_bytes",
                                     "limited_status", "notebook_digest", "notebook_outputs", "notebook_code_count",
                                     "population_identity", "restricted_baseline", "failure_receipt", "execution_lock"])
def test_transfer_rejects_contradictory_rehashed_attestations(tmp_path, monkeypatch, tamper):
    paths, _ = synthetic_run(tmp_path, monkeypatch, receipts=True)
    destination = tmp_path / "bundle"
    evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=destination)
    manifest_path = destination / "EXECUTION_EVIDENCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    claims = manifest["observed_execution_receipts"]

    def repin(file):
        identity = {"sha256": satscan_io.sha256_file(file), "bytes": file.stat().st_size}
        manifest["files"][file.relative_to(destination).as_posix()] = identity
        return identity

    match = "receipt inventory"
    if tamper == "missing_restricted":
        claims.pop()
    elif tamper == "duplicate_primary":
        claims[2] = claims[0]
    elif tamper == "relabeled":
        claims[2]["path"] = claims[0]["path"]
    elif tamper == "receipt_bytes":
        file = destination / "secondary" / claims[0]["path"]
        observed = json.loads(file.read_text())
        observed["scenario_id"] = VIIRS
        file.write_text(json.dumps(observed))
        claims[0].update(repin(file))
        match = "receipt identity mismatch"
    elif tamper in {"failure_receipt", "execution_lock"}:
        receipt = destination / "secondary" / claims[0]["path"]
        suffix = ".failed.json" if tamper == "failure_receipt" else ".lock"
        marker = receipt.with_suffix(suffix)
        marker.write_text("contradictory terminal state", encoding="utf-8")
        repin(marker)
        match = "contradicts a failed or in-progress invocation"
    elif tamper == "limited_status":
        manifest.update(status="DECLARED_LIMITATIONS", limitations=["invented limitation"])
        match = "declared limitations contradict"
    elif tamper == "notebook_digest":
        manifest["notebook_identity"]["source_sha256"] = "0" * 64
        match = "notebook identity contradicts"
    elif tamper in {"notebook_outputs", "notebook_code_count"}:
        notebook_path = destination / "closeout/99_closeout" / EXECUTED_NOTEBOOK
        record_path = destination / "closeout/99_closeout" / CLOSEOUT_RECORD
        record = json.loads(record_path.read_text())
        if tamper == "notebook_outputs":
            notebook = nbformat.read(notebook_path, as_version=4)
            notebook.cells[0].outputs = [nbformat.v4.new_output("error", ename="Error", evalue="failed", traceback=[])]
            nbformat.write(notebook, notebook_path)
            digest = repin(notebook_path)["sha256"]
            record.update(executed_notebook_sha256=digest)
            manifest["notebook_identity"]["executed_sha256"] = digest
        else:
            record.update(code_cells=2, executed_code_cells=2)
        record_path.write_text(json.dumps(record))
        repin(record_path)
        match = "complete-cell evidence"
    elif tamper == "population_identity":
        file = destination / "secondary" / claims[0]["path"]
        observed = json.loads(file.read_text())
        observed["inputs_after"]["population"]["sha256"] = "f" * 64
        file.write_text(json.dumps(observed))
        claims[0].update(repin(file))
        match = "input identities"
    elif tamper == "restricted_baseline":
        file = destination / "secondary/support_sensitivity/modis_gt50_design.json"
        design = json.loads(file.read_text())
        design["baseline_secondary_run"] = "other_sec"
        file.write_text(json.dumps(design))
        repin(file)
        match = "restricted scan scenario or baseline"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(satscan_io.ExternalResultValidationError, match=f"(?i){match}"):
        evidence.validate_execution_evidence_bundle(destination)


def test_bundle_does_not_embed_an_engine_kept_inside_the_run(tmp_path,monkeypatch):
    paths,_=synthetic_run(tmp_path,monkeypatch,receipts=True)
    secondary=paths.root/"out/runs/example_sec"
    binary=secondary/"engine.exe";binary.write_bytes(b"synthetic executable identity")
    receipt=secondary/f"results/{MCD}.execution.json";record=json.loads(receipt.read_text())
    record["executable"]["path"]=str(binary);record["command"][0]=str(binary)
    receipt.write_text(json.dumps(record))
    status_path = secondary / "04_secondary_concentration/secondary_external_execution_status.json"
    status = json.loads(status_path.read_text())
    status["satscan_execution_receipts"][MCD]["executable_path"] = str(binary)
    status["satscan_execution_receipts"][MCD]["execution_receipt_sha256"] = satscan_io.sha256_file(receipt)
    status_path.write_text(json.dumps(status))
    source_manifest_path = secondary / status["run_local_publication_source_manifest"]
    source_manifest = json.loads(source_manifest_path.read_text())
    source_manifest["execution_receipts"] = status["satscan_execution_receipts"]
    source_manifest_path.write_text(json.dumps(source_manifest))
    with pytest.raises(satscan_io.ExternalResultValidationError,match="outside the scientific run"):
        evidence.export_execution_evidence(paths=paths,run_id="example",output_dir=tmp_path/"bundle")
    assert not (tmp_path/"bundle").exists()


def test_strict_bundle_requires_restricted_scan_even_when_primary_runs_have_receipts(tmp_path, monkeypatch):
    paths, _ = synthetic_run(tmp_path, monkeypatch, receipts=True, restricted=False)
    with pytest.raises(satscan_io.ExternalResultValidationError, match="Restricted burned-area Poisson scan"):
        evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=tmp_path/"bundle")


@pytest.mark.parametrize("corruption",["source","execution_count","error"])
def test_snapshot_presence_is_not_sufficient_for_strict_bundle(tmp_path,monkeypatch,corruption):
    paths,close=synthetic_run(tmp_path,monkeypatch,receipts=True)
    notebook=close/EXECUTED_NOTEBOOK;nb=nbformat.read(notebook,as_version=4)
    if corruption=="source":nb.cells[0].source="print(2)"
    elif corruption=="execution_count":nb.cells[0].execution_count=None
    else:nb.cells[0].outputs=[nbformat.v4.new_output("error",ename="Error",evalue="failed",traceback=[])]
    nbformat.write(nb,notebook)
    record=json.loads((close/CLOSEOUT_RECORD).read_text());record["executed_notebook_sha256"]=satscan_io.sha256_file(notebook)
    (close/CLOSEOUT_RECORD).write_text(json.dumps(record))
    with pytest.raises(satscan_io.ExternalResultValidationError,match="notebook"):
        evidence.export_execution_evidence(paths=paths,run_id="example",output_dir=tmp_path/"bundle")


@pytest.mark.parametrize("change", ["publication", "secondary", "closeout", "config", "notebook", "version", "add", "remove", "mtime"])
def test_export_rejects_changes_after_validation_before_copy(tmp_path, monkeypatch, change):
    """A newly captured post-validation state must never replace the pinned one."""
    import rp1_analysis_v1.integration as integration
    paths, _ = synthetic_run(tmp_path, monkeypatch, receipts=True)
    publication = paths.root / "out/runs/example_pub/table.csv"
    selected = {
        "publication": publication,
        "secondary": paths.root / f"out/runs/example_sec/results/{MCD}.stdout.log",
        "closeout": paths.root / f"out/runs/example_close/99_closeout/{CLOSEOUT_RECORD}",
        "config": paths.root / "config/fixture.yml",
        "notebook": paths.root / "RP1_Analysis_v1.ipynb",
        "version": paths.root / "pyproject.toml",
    }
    def edit_after_validation(**kwargs):
        if change == "add":
            publication.with_name("new.csv").write_text("new member\n")
        elif change == "remove":
            publication.unlink()
        elif change == "mtime":
            metadata = publication.stat()
            os.utime(publication, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 10_000_000))
        else:
            selected[change].write_bytes(selected[change].read_bytes() + b"\n")
        return SimpleNamespace(status="PASS")
    monkeypatch.setattr(integration, "validate_run_authority", edit_after_validation)
    destination = tmp_path / "bundle"
    with pytest.raises(satscan_io.ExternalResultValidationError, match="snapshot"):
        evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=destination)
    assert not destination.exists()


@pytest.mark.parametrize("point", ["copy", "later_family", "before_seal", "staged_member", "target_member"])
def test_export_binds_copy_and_terminal_publication_to_one_snapshot(tmp_path, monkeypatch, point):
    paths, _ = synthetic_run(tmp_path, monkeypatch, receipts=True)
    destination = tmp_path / "bundle"
    table = paths.root / "out/runs/example_pub/table.csv"
    original_copy = evidence.shutil.copyfile
    original_move = evidence.shutil.move
    changed = False
    def copy(source, target, *args, **kwargs):
        nonlocal changed
        result = original_copy(source, target, *args, **kwargs)
        if not changed:
            if point == "copy":
                Path(source).write_bytes(Path(source).read_bytes() + b"\n")
            elif point == "later_family":
                p = paths.root / f"out/runs/example_close/99_closeout/{CLOSEOUT_RECORD}"
                p.write_bytes(p.read_bytes() + b"\n")
            elif point == "staged_member":
                Path(target).with_name("unvalidated.csv").write_text("unexpected\n")
            else:
                return result
            changed = True
        return result
    def move(source, target, *args, **kwargs):
        nonlocal changed
        result = original_move(source, target, *args, **kwargs)
        if not changed:
            if point == "before_seal":
                table.write_bytes(table.read_bytes() + b"\n")
            elif point == "target_member":
                (destination / "unvalidated.csv").write_text("unexpected\n")
            else:
                return result
            changed = True
        return result
    monkeypatch.setattr(evidence.shutil, "copyfile", copy)
    monkeypatch.setattr(evidence.shutil, "move", move)
    with pytest.raises(satscan_io.ExternalResultValidationError, match="changed|snapshot"):
        evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=destination)
    assert changed
    assert not (destination / "EXECUTION_EVIDENCE_MANIFEST.json").exists()
    if destination.exists():
        assert (destination / "BUNDLE_INCOMPLETE.txt").is_file()


@pytest.mark.parametrize("location", ["config", "run"])
def test_initial_export_snapshot_rejects_linked_entries(tmp_path, monkeypatch, location):
    paths, _ = synthetic_run(tmp_path, monkeypatch, receipts=True)
    outside = tmp_path / "outside.txt";outside.write_text("not a governed member\n")
    parent = paths.root / "config" if location == "config" else paths.root / "out/runs/example_pub"
    link = parent / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit creating a symlink")
    with pytest.raises(satscan_io.ExternalResultValidationError, match="symlink|Linked"):
        evidence.export_execution_evidence(paths=paths, run_id="example", output_dir=tmp_path / "bundle")
