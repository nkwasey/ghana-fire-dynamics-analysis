from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from rp1_analysis_v1 import integration
from rp1_analysis_v1 import publication as publication_module
from rp1_analysis_v1.config import load_output_contract


@pytest.fixture
def output_contract():
    return load_output_contract(Path(__file__).resolve().parents[1] / "config/output_contract.yml")


@pytest.fixture
def linked_publication(tmp_path, output_contract):
    publication = tmp_path/'pub'
    secondary = tmp_path/'sec'
    (publication/'90_integrated').mkdir(parents=True)
    (secondary/'04_secondary_concentration/publication_sources').mkdir(parents=True)
    source_dir = secondary/'04_secondary_concentration/publication_sources'
    sources = {}
    for name in ('table3_satscan_clusters', 'supplement_s6_satscan', 'cluster_recurrence_source'):
        path = source_dir/f'{name}.csv'
        path.write_text('product,value\nviirs,3\n')
        sources[name] = {'path': path.relative_to(secondary).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (source_dir/'M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json').write_text(json.dumps({'secondary_run_id':'sec','sources':sources}))
    for name in ('T3', 'S6', 'F6'):
        (publication/f'{name}.csv').write_text('product,value\nviirs,3\n')
    (publication/'F6.json').write_text(json.dumps({'figure_data': {'path':'F6.csv'}}))
    rows = [{'table_id':name, 'availability':'AVAILABLE', 'path':f'{name}.csv'} for name in ('T3', 'S6')]
    rows.extend(
        {'table_id': spec.output_id, 'availability': 'RESTRICTED_SCAN_RESULTS_REQUIRED', 'path': ''}
        for spec in output_contract.tables if spec.builder_options.get("requires_restricted_scan")
    )
    pd.DataFrame(rows).to_csv(publication/'90_integrated/T_TABLE_REGISTRY.csv', index=False)
    pd.DataFrame([{'figure_id':'F6', 'availability':'AVAILABLE', 'manifest_path':'F6.json'}]).to_csv(publication/'90_integrated/T_FIGURE_REGISTRY.csv', index=False)
    return publication, secondary


@pytest.mark.parametrize('name', ['T3', 'S6', 'F6'])
def test_publication_values_are_bound_to_selected_secondary_sources(linked_publication, output_contract, name):
    publication, secondary = linked_publication
    integration._validate_publication_secondary_sources(publication, secondary, 'RESULTS_VALIDATED', output=output_contract)
    (publication/f'{name}.csv').write_text('product,value\nviirs,4\n')
    with pytest.raises(integration.IntegrationError, match='Publication values differ'):
        integration._validate_publication_secondary_sources(publication, secondary, 'RESULTS_VALIDATED', output=output_contract)


def test_publication_rejects_changed_secondary_state_and_identity(linked_publication, output_contract):
    publication, secondary = linked_publication
    with pytest.raises(integration.IntegrationError, match='availability differs'):
        integration._validate_publication_secondary_sources(publication, secondary, 'EXTERNAL_RESULTS_REQUIRED', output=output_contract)
    path = secondary/'04_secondary_concentration/publication_sources/M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json'
    manifest = json.loads(path.read_text())
    manifest['secondary_run_id'] = 'other'
    path.write_text(json.dumps(manifest))
    with pytest.raises(integration.IntegrationError, match='identity mismatch'):
        integration._validate_publication_secondary_sources(publication, secondary, 'RESULTS_VALIDATED', output=output_contract)


def test_publication_restricted_pending_registry_is_complete(linked_publication, output_contract):
    publication, secondary = linked_publication
    registry = publication / "90_integrated/T_TABLE_REGISTRY.csv"
    tables = pd.read_csv(registry)
    tables.loc[tables["table_id"].eq("S24"), "availability"] = "AVAILABLE"
    tables.to_csv(registry, index=False)
    with pytest.raises(integration.IntegrationError, match="S24 lacks selected-run evidence"):
        integration._validate_publication_secondary_sources(
            publication, secondary, "RESULTS_VALIDATED", output=output_contract
        )
    tables.loc[~tables["table_id"].eq("S24")].to_csv(registry, index=False)
    with pytest.raises(integration.IntegrationError, match="Missing restricted scan table registry entry: S24"):
        integration._validate_publication_secondary_sources(
            publication, secondary, "RESULTS_VALIDATED", output=output_contract
        )


def test_publication_restricted_values_are_bound_to_selected_run(
    linked_publication, output_contract, monkeypatch
):
    publication, secondary = linked_publication
    registry = publication / "90_integrated/T_TABLE_REGISTRY.csv"
    tables = pd.read_csv(registry)
    sources = {}
    for spec in output_contract.tables:
        if spec.builder_options.get("requires_restricted_scan"):
            frame = pd.DataFrame([{field: 1 for field in spec.required_columns}])
            sources[spec.source_attribute] = frame
            filename = f"{spec.output_id}.csv"
            frame.to_csv(publication / filename, index=False)
            tables.loc[tables["table_id"].eq(spec.output_id), ["availability", "path"]] = "AVAILABLE", filename
    tables.to_csv(registry, index=False)
    monkeypatch.setattr(publication_module, "load_restricted_scan_sources", lambda _: sources)
    integration._validate_publication_secondary_sources(
        publication, secondary, "RESULTS_VALIDATED", output=output_contract
    )
    path = publication / "S24.csv"
    changed = pd.read_csv(path)
    changed.loc[0, "restricted_observed"] = 2
    changed.to_csv(path, index=False)
    with pytest.raises(integration.IntegrationError, match="S24 disagrees"):
        integration._validate_publication_secondary_sources(
            publication, secondary, "RESULTS_VALIDATED", output=output_contract
        )


@pytest.mark.parametrize("table_id", ["T3", "S6"])
def test_resume_rejects_hash_valid_legacy_header_and_accepts_current_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table_id: str,
) -> None:
    # This synthetic fixture checks SaTScan header semantics only. The explicit
    # assertion here does not qualify any real RQ3 input or publication run.
    monkeypatch.setattr(integration, "require_rq3_inputs_acknowledged", lambda: None)
    # The incompatible bytes are deliberately recorded with their correct hash:
    # byte integrity alone cannot establish that O/E was not labelled as RR.
    run = tmp_path / "project" / "out" / "runs" / "run"
    (run / "90_integrated").mkdir(parents=True)
    (run / "90_integrated/T_ARTEFACT_REGISTRY.csv").write_text("", encoding="utf-8")
    table = run / f"{table_id}.csv"
    spec = SimpleNamespace(
        output_id=table_id,
        required_columns=("record_type", "model", "expected", "conditional_expected", "observed_expected_ratio", "relative_risk", "log_likelihood_ratio", "test_statistic", "test_statistic_type"),
        requires_results_validated=True,
    )
    bundle = SimpleNamespace(
        output=SimpleNamespace(tables=[spec]),
        figure=SimpleNamespace(figures=[]),
    )
    monkeypatch.setattr(integration, "load_configuration_bundle", lambda _: bundle)
    monkeypatch.setattr(integration, "table_specs", lambda _: [(table_id,)])
    monkeypatch.setattr(integration, "figure_specs", lambda _: [])

    def run_validation(content: str):
        table.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(table.read_bytes()).hexdigest()
        registries = {
            "table registry": pd.DataFrame([{
                "table_id": table_id, "availability": "AVAILABLE",
                "path": table.name, "sha256": digest, "size_bytes": table.stat().st_size,
            }]),
            "figure registry": pd.DataFrame(columns=["figure_id"]),
            "result registry": pd.DataFrame(columns=["result_id", "evidence_class"]),
            "artefact registry": pd.DataFrame([{
                "path": table.name, "sha256": digest, "size_bytes": table.stat().st_size,
            }]),
        }
        monkeypatch.setattr(integration, "_read_csv", lambda _path, label: registries[label])
        return integration._validate_publication_run(run)

    with pytest.raises(integration.IntegrationError, match="header differs"):
        run_validation("observed,relative_risk\n4,2\n")

    count, figures, _ = run_validation(
        "record_type,model,expected,conditional_expected,observed_expected_ratio,relative_risk,log_likelihood_ratio,test_statistic,test_statistic_type\n"
        "cluster,discrete_poisson,2,,2,2.5,1,1,LLR\n"
    )
    assert (count, figures) == (1, 0)
    # A stale semantic error must fail even with matching fresh file hashes.
    with pytest.raises(integration.IntegrationError, match="STP must not report"):
        run_validation(
            "record_type,model,expected,conditional_expected,observed_expected_ratio,relative_risk,log_likelihood_ratio,test_statistic,test_statistic_type\n"
            "cluster,space_time_permutation,,2,2,2.5,,1,TEST_STAT\n"
        )


@pytest.mark.parametrize("table_id", ["T3", "S6"])
@pytest.mark.parametrize("field", ["expected", "relative_risk", "log_likelihood_ratio"])
def test_stp_cluster_forbids_poisson_fields_even_if_hash_would_match(
    tmp_path: Path, table_id: str, field: str,
) -> None:
    path = tmp_path / "source.csv"
    columns = ("record_type", "model", "expected", "conditional_expected",
               "observed_expected_ratio", "relative_risk", "log_likelihood_ratio",
               "test_statistic", "test_statistic_type")
    row = dict.fromkeys(columns, "")
    row.update(record_type="cluster", model="space_time_permutation",
               conditional_expected="10", observed_expected_ratio="2",
               test_statistic="5", test_statistic_type="TEST_STAT")
    row[field] = "1.5"
    import csv
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerow(row)
    with pytest.raises(integration.IntegrationError, match="STP must not report"):
        integration._validate_satscan_table_model_fields(path, table_id)


def test_s6_ignores_noncluster_rows_and_accepts_empty_table(tmp_path: Path) -> None:
    path = tmp_path / "s6.csv"
    path.write_text("record_type,model,expected,conditional_expected,observed_expected_ratio,relative_risk,log_likelihood_ratio,test_statistic,test_statistic_type\n"
                    "membership,,,,,,,,\n")
    integration._validate_satscan_table_model_fields(path, "S6")
    path.write_text(path.read_text().splitlines()[0] + "\n")
    integration._validate_satscan_table_model_fields(path, "S6")


def test_poisson_rejects_stp_conditional_expectation(tmp_path: Path) -> None:
    path = tmp_path / "t3.csv"
    path.write_text("model,expected,conditional_expected,observed_expected_ratio,relative_risk,log_likelihood_ratio,test_statistic,test_statistic_type\n"
                    "discrete_poisson,2,2,2,2.5,1,1,LLR\n")
    with pytest.raises(integration.IntegrationError, match="Poisson must not report"):
        integration._validate_satscan_table_model_fields(path, "T3")


def test_s6_rejects_unknown_record_type_or_hidden_noncluster_rr(tmp_path: Path) -> None:
    path = tmp_path / "s6.csv"
    header = "record_type,model,expected,conditional_expected,observed_expected_ratio,relative_risk,log_likelihood_ratio,test_statistic,test_statistic_type\n"
    path.write_text(header + "not-a-type,,,,,,,,\n")
    with pytest.raises(integration.IntegrationError, match="unknown record type"):
        integration._validate_satscan_table_model_fields(path, "S6")
    path.write_text(header + "membership,space_time_permutation,,,,1,,,\n")
    with pytest.raises(integration.IntegrationError, match="non-cluster row reports"):
        integration._validate_satscan_table_model_fields(path, "S6")
