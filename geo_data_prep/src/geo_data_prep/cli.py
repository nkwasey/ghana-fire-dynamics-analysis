"""Command-line interface for configuration validation and geography generation."""
import argparse
import json
import sys
from .pipeline import PrepError, run, validate


def main(argv=None):
    parser = argparse.ArgumentParser(prog="geo-prep", description="Assign whole districts and construct reporting zones.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True)
        if name == "run":
            command.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            print(json.dumps(validate(args.config), indent=2, sort_keys=True))
        else:
            print(run(args.config, args.run_id))
        return 0
    except (PrepError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
