#!/usr/bin/env bash
set -euo pipefail

CFG="configs/my_project.yaml"
RUN_ALL="ghana_all"

# MODIS 2000–2024
for YEAR in $(seq 2000 2024); do
  python scripts/prepare_year.py --config "$CFG" --sensor modis --year "$YEAR" --run-id "$RUN_ALL"
done

# VIIRS 2014–2024
for YEAR in $(seq 2014 2024); do
  python scripts/prepare_year.py --config "$CFG" --sensor viirs --year "$YEAR" --run-id "$RUN_ALL"
done

# Aggregate per sensor (use their valid ranges)
python scripts/aggregate_level.py --config "$CFG" --sensor modis --run-id "$RUN_ALL" --start-yyyymm 200011 --end-yyyymm 202412
python scripts/aggregate_level.py --config "$CFG" --sensor viirs --run-id "$RUN_ALL" --start-yyyymm 201401 --end-yyyymm 202412

# Combine only for overlap (recommended even with single run)
python scripts/combine_panels.py --config "$CFG" --run-id "$RUN_ALL" --start-yyyymm 201401 --end-yyyymm 202412

echo "Done."
echo "All outputs: out/runs/$RUN_ALL/"