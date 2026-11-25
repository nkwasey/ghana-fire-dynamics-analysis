"""Independent expected input membership from the reviewed configuration."""
from pathlib import Path

import yaml


def configured_input_paths(root: Path) -> set[str]:
    schema = yaml.safe_load((root / "config/data_schema_contract.yml").read_text(encoding="utf-8"))
    paths = {record["path"] for record in schema["panels"].values()}
    paths.update(record["path"] for record in schema["auxiliary_inputs"].values())
    for geometry in schema["geometries"].values():
        paths.update(geometry["required_members"])
    return paths
