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
        'This document is generated from `config/data_schema_contract.yml`. The YAML contract is the machine-readable authority; this file is a derived human-readable registry and must not be edited as an independent 111-field authority.', '',
        f'- Analysis schema: `{ds.schema_version}`',
        f'- Data schema: `{ds.data_schema_version}`',
        f'- Panel schema: `{ds.panel_schema_version}`',
        f'- Governed panel fields: **{ds.field_count}**', '',
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
    lines += ['', '## Structural missingness', '', 'A valid numerical zero is permitted only on product-supported unit-months. For fields tied to a structural-support rule, unsupported rows must remain null. Supported rows declared `required_when_supported: true` must be non-null. These semantics are validated from the machine-readable contract rather than from a second Python field list.', '']
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
