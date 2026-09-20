#!/usr/bin/env python3
"""Materialise deterministic RQ3 population/design authorities.

This script stops before PGEE estimation.  It writes only analytical population,
mean-model design, exact outcome-support diagnostics, predictor diagnostics and
realised design metadata from the governed configuration and data authorities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.observability import build_rq3_design_authority
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.validation import validate_data_authorities


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.write_text(frame.to_csv(index=False, lineterminator="\n"), encoding="utf-8", newline="")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--methods-spec", type=Path, required=True)
    parser.add_argument("--data-archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    root = args.project_root.resolve()
    output = (args.output_dir or (root / "data" / "authorities" / "rq3")).resolve()
    output.mkdir(parents=True, exist_ok=True)

    bundle = load_configuration_bundle(root / "config")
    paths = ProjectPaths.discover(root)
    authorities = load_data_authorities(paths, bundle.data_schema)
    data_summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    design = build_rq3_design_authority(
        authorities,
        data_summary,
        bundle,
        methods_spec_sha256=sha256(args.methods_spec.resolve()),
        data_sha256=sha256(args.data_archive.resolve()),
    )

    outputs: dict[str, pd.DataFrame] = {
        "paired_four_state_source.csv": design.paired_four_state_source,
        "four_state_summary.csv": design.four_state_summary,
        "model_population_source.csv": design.model_population_source,
        "mean_model_design.csv": design.mean_model_design,
        "design_metadata.csv": design.design_metadata,
        "predictor_correlation.csv": design.predictor_correlation,
        "predictor_vif.csv": design.predictor_vif,
        "factor_outcome_counts.csv": design.factor_outcome_counts,
        "cluster_outcome_counts.csv": design.cluster_outcome_counts,
    }
    for filename, frame in outputs.items():
        write_csv(output / filename, frame)

    metadata_path = output / "realised_run_metadata.json"
    metadata_path.write_text(
        json.dumps(design.realised_run_metadata, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    records = []
    for path in sorted(output.iterdir(), key=lambda p: p.name):
        if not path.is_file() or path.name == "source_manifest.json":
            continue
        records.append({"file": path.name, "sha256": sha256(path), "size_bytes": path.stat().st_size})
    manifest = {
        "schema": "rp1-rq3-design-authority-manifest-v1",
        "authority_scope": "population_design_diagnostics_only_no_pgee_estimation",
        "configuration_sha256": bundle.configuration_sha256,
        "methods_specification_sha256": sha256(args.methods_spec.resolve()),
        "governed_data_archive_sha256": sha256(args.data_archive.resolve()),
        "files": records,
    }
    (output / "source_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
