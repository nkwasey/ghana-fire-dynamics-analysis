"""Run the governed RQ2 sensitivity analysis from an existing S4 table."""

from __future__ import annotations

import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path

import pandas as pd
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.trend_sensitivity import build_trend_sensitivity, settings_from_primary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s4", required=True, type=Path, help="Governed S4 annual-rate CSV")
    parser.add_argument("--expected-s4-sha256", required=True, help="Verified digest of the S4 CSV")
    parser.add_argument("--output-dir", required=True, type=Path, help="Fresh destination for sensitivity results")
    args = parser.parse_args()

    try:
        destination = args.output_dir.resolve()
        if args.output_dir.is_symlink() or destination.exists():
            raise ValueError(f"The output directory must be fresh: {destination}")
        source = args.s4.read_bytes()
        source_digest = hashlib.sha256(source).hexdigest()
        if source_digest != args.expected_s4_sha256.lower():
            raise ValueError("S4 SHA-256 differs from the supplied digest")
        bundle = load_configuration_bundle(Path(__file__).resolve().parents[1] / "config")
        result = build_trend_sensitivity(
            pd.read_csv(BytesIO(source), float_precision="round_trip"),
            settings=settings_from_primary(bundle.analysis),
        )
        outputs = {
            "intervals.csv": result.intervals.to_csv(index=False).encode("utf-8"),
            "calibration.csv": result.calibration.to_csv(index=False).encode("utf-8"),
            "detectability.csv": result.detectability.to_csv(index=False).encode("utf-8"),
            "detectability_summary.csv": result.detectability_summary.to_csv(index=False).encode("utf-8"),
            "settings.json": (json.dumps(result.settings, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
        }
        manifest = {
            "configuration_sha256": bundle.configuration_sha256,
            "s4_sha256": source_digest,
            "files": {
                name: {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
                for name, payload in outputs.items()
            },
        }
        manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        destination.mkdir(parents=True, exist_ok=False)
        for name, payload in outputs.items():
            with (destination / name).open("xb") as stream:
                stream.write(payload)
        with (destination / "MANIFEST.json").open("x", encoding="utf-8") as stream:
            stream.write(manifest_text)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Trend sensitivity failed: {exc}\n")
    print(f"RP1_TREND_SENSITIVITY=PASS {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
