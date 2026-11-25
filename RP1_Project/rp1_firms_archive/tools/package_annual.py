"""Collect accepted annual GEE upload ZIPs into sensor folders."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ghana_fire_archive.exports import package_collection as package


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.manifest, args.output), indent=2))
