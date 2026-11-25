#!/usr/bin/env python3
"""Render the publication-neutral data-schema registry from the realised contract."""
from __future__ import annotations
import argparse
from pathlib import Path
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.paths import ProjectPaths


def _text(value):
    if value is None: return "—"
    if isinstance(value, bool): return "yes" if value else "no"
    return str(value).replace("|", "\\|")


def render(root: Path) -> str:
    bundle=load_configuration_bundle(root/'config')
    ds=bundle.data_schema
    lines=[
        '# Data Schema Contract', '',
        f'This document is generated from `config/data_schema_contract.yml`. The YAML contract is the machine-readable authority; this file is a derived registry and must not be edited as an independent {ds.field_count}-field authority.', '',
        f'- Analysis schema: `{ds.schema_version}`',
        f'- Data schema: `{ds.data_schema_version}`',
        f'- Panel schema: `{ds.panel_schema_version}`',
        f'- Governed panel fields: **{ds.field_count}**', '',
        'The `modis_burned_frac_annual_*` headers denote nonnegative ratios: their numerator is restricted to the family union mask, whereas their denominator is the year-specific burnable area. They are not fractions of the annual mask and may exceed one. The union-denominator fractions remain bounded by one.', '',
        '## Panel authorities', '',
        '| Panel | Path | Primary key | Rows | Units | Frequency | Start | End |',
        '|---|---|---|---:|---:|---|---|---|',
    ]
    for key,spec in ds.panels.items():
        lines.append(f'| `{key}` | `{spec.path}` | `{", ".join(spec.primary_key)}` | {spec.expected_rows} | {spec.expected_units} | {spec.temporal_frequency} | {spec.start} | {spec.end} |')
    lines += ['', '## Analytical-population validation authorities', '', 'Scientific analysis-population choices are owned by `config/analysis_contract.yml`; the data schema owns only field and support semantics.', '', '| Population | Units | Rows | Start | End | Eligibility rule |', '|---|---:|---:|---|---|---|']
    for key,e in bundle.analysis.study["populations"].items():
        lines.append(f'| `{key}` | {e["units"]} | {e["rows"]} | {e["start"]} | {e["end"]} | `{e["eligibility"]}` |')
    lines += ['', '## Geometry authorities', '', '| Geometry | Path | Features | CRS | Identifier | Parent field | Required members |', '|---|---|---:|---|---|---|---:|']
    for key,g in ds.geometries.items():
        lines.append(f'| `{key}` | `{g.path}` | {g.expected_features} | EPSG:{g.crs_epsg} | `{g.identifier_field}` | `{g.parent_field or "—"}` | {len(g.required_members)} |')
    lines += ['', '## Relationships', '', '| ID | From | To | Cardinality |', '|---|---|---|---|']
    for r in ds.relationships:
        lines.append(f'| `{r.relationship_id}` | `{r.from_object}.{r.from_field}` | `{r.to_object}.{r.to_field}` | `{r.cardinality}` |')
    lines += ['', '## Field registry', '', '| # | Field | Dtype | Semantic type | Unit | Nullable | Structural support | Source family | Additive | Min | Max | Domain | Relationship role |', '|---:|---|---|---|---|---|---|---|---|---:|---:|---|---|']
    for i,f in enumerate(ds.fields,1):
        lines.append('| ' + ' | '.join([
            str(i), f'`{f.name}`', _text(f.dtype), _text(f.semantic_type), _text(f.unit), _text(f.nullable),
            f'`{f.structural_support}`', _text(f.source_family), _text(f.additive), _text(f.minimum), _text(f.maximum),
            _text(f.categorical_domain), _text(f.relationship_role)
        ]) + ' |')
    lines += ['', '## Additive reconciliation', '', 'District-to-ACZ reconciliation is governed by the YAML contract. The configured additive fields are:', '']
    for field in ds.additive_fields: lines.append(f'- `{field}`')
    lines += ['', '## Mandatory c3 evidence', '',
        'The companion `ba_observation_support.csv` uses `rp1-ba-c3-evidence-v1`: all 69 original `rp1_ba_c3_extended_v2` fields plus `family`, `source_path`, `source_sha256` and 1-based data-record `source_row`. Original `run_id` remains the source task identity. The c3 policy is `c3_preserve_admission_v1`, pinned to `c3_methods_v1_schema_v2`.', '',
        '## Auxiliary authorities', '', '| Role | Path |', '|---|---|']
    for key,spec in ds.auxiliary_inputs.items():
        lines.append(f'| `{key}` | `{spec["path"]}` |')
    lines += ['', '## Structural missingness and result admission', '',
        'Temporal flags describe calendar/domain membership. Outside that support, fields remain structurally null. Within support, c3 primary fields can be withheld by their own result guards; exact values/nulls must match the mandatory evidence companion. Positive annual denominator alone does not make a withheld primary numerator usable.', '',
        'Admitted scenario zeros, including `NO_SUPPORTED_EVIDENCE`, are retained and are not physical absence observations. A resolved zero union has zero numerator/denominator and undefined union fraction/rate. Fixed denominators are never filled from known-union diagnostics. Complete-window analytical eligibility excludes withheld primary inputs without changing estimators.', '',
        '`ba_supported_fraction` is accepted-positive divided by accepted-positive plus qualifying explicit-zero evidence, not geographic observation coverage. Five exclusive evidence-state areas form the known-union partition; reason areas overlap. District reconciliation never sums around missing constituent values.', '']
    return '\n'.join(lines)


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--check',action='store_true'); args=ap.parse_args()
    paths=ProjectPaths.discover(Path(__file__).resolve()); dest=paths.root/'docs/Data_Schema_Contract.md'; content=render(paths.root)
    if args.check:
        if not dest.is_file() or dest.read_text(encoding='utf-8') != content:
            raise SystemExit('Data_Schema_Contract.md is not synchronised with data_schema_contract.yml')
    else:
        dest.write_text(content,encoding='utf-8',newline='\n')
    print(f'DATA_SCHEMA_DOCUMENTATION_FIELDS={len(load_configuration_bundle(paths.root/"config").data_schema.fields)}')
    print('RP1_DATA_SCHEMA_DOCUMENTATION=PASS')
    return 0
if __name__=='__main__': raise SystemExit(main())
