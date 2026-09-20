# file: src/mv_firms_panels/io/paths.py
"""Deterministic output path builders.

This module contains *only* path-building helpers; it performs no IO by default.

Rules (binding)
---------------
- Use ``pathlib.Path`` for Windows-friendly paths.
- Do not embed absolute paths; callers supply ``repo_root`` and/or output base
  directory strings.
- Build run folders deterministically from ``(outputs_base_dir, run_id)``.

Monthly panel formats
---------------------
Monthly and RP1 export artefacts may be written as either:
- ``.csv.gz`` (default), or
- ``.csv`` (opt-in)

These helpers provide deterministic filenames for both formats.

RP1 AF path design
-------------------------------------
The merger-ready RP1 AF export family keeps sensor specificity in the directory
layout rather than in the canonical CSV schema. File names are built from:
- the logical export family (``rp1_af``)
- the requested level (for example ``acz`` or ``district``)
- the family subtype (base vs ``_ext``)
- a *generic* partition token derived from the Stage 1 hierarchy

The path helpers intentionally do not assume ACZ partitioning. Callers provide a
partition key/value pair such as ``acz_code=CZ`` or another hierarchy-derived
partition token.
"""

from __future__ import annotations

import re
from pathlib import Path

_INVALID_RUNID_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_SUPPORTED_MONTHLY_PANEL_FORMATS = ("csv.gz", "csv")


def sanitise_run_id(run_id: str) -> str:
    """Sanitise a run_id for safe use as a folder name (deterministic)."""
    run_id = run_id.strip()
    run_id = _INVALID_RUNID_CHARS.sub("_", run_id)
    run_id = run_id.strip("._-")
    if not run_id:
        raise ValueError("run_id is empty after sanitisation")
    return run_id


def sanitise_level(level: str) -> str:
    """Sanitise a level token for safe use in filenames (deterministic)."""
    level = str(level).strip()
    level = _INVALID_RUNID_CHARS.sub("_", level)
    level = level.strip("._-")
    if not level:
        raise ValueError("level is empty after sanitisation")
    return level


def sanitise_token(token: str) -> str:
    """Sanitise a generic filename token deterministically."""
    token = str(token).strip()
    token = _INVALID_RUNID_CHARS.sub("_", token)
    token = token.strip("._-")
    if not token:
        raise ValueError("token is empty after sanitisation")
    return token


def build_run_dir(*, repo_root: Path, outputs_base_dir: str, run_id: str) -> Path:
    """Return the run directory path (not created)."""
    run_id_safe = sanitise_run_id(run_id)
    return (repo_root / outputs_base_dir / run_id_safe).resolve()


def logs_dir(run_dir: Path) -> Path:
    return run_dir / "logs"


def run_log_jsonl_path(run_dir: Path) -> Path:
    return logs_dir(run_dir) / "run.jsonl"


def config_snapshot_yaml_path(run_dir: Path) -> Path:
    return run_dir / "config_snapshot.yaml"


def config_snapshot_json_path(run_dir: Path) -> Path:
    return run_dir / "config_snapshot.json"


def _suffix_for_monthly_format(fmt: str) -> str:
    """Return the file suffix for a monthly/export format token."""
    tok = str(fmt).strip().lower()
    if tok == "csv":
        return ".csv"
    if tok == "csv.gz":
        return ".csv.gz"
    raise ValueError(
        f"Unsupported monthly panel format: {fmt!r}. Supported: {list(_SUPPORTED_MONTHLY_PANEL_FORMATS)}"
    )


def _normalise_range_yyyymm(yyyymm: int | str) -> str:
    text = str(yyyymm).strip()
    if not re.fullmatch(r"\d{6}", text):
        raise ValueError(f"Expected YYYYMM as 6 digits, got: {yyyymm!r}")
    mm = int(text[-2:])
    if mm < 1 or mm > 12:
        raise ValueError(f"Expected YYYYMM month 01..12, got: {yyyymm!r}")
    return text


def _range_tag(start_yyyymm: int | str, end_yyyymm: int | str) -> str:
    start = _normalise_range_yyyymm(start_yyyymm)
    end = _normalise_range_yyyymm(end_yyyymm)
    return f"{start}_{end}"


def panel_monthly_dir(run_dir: Path) -> Path:
    return run_dir / "panel_monthly"


def sensor_panel_monthly_path(*, run_dir: Path, sensor: str, fmt: str) -> Path:
    return (
        panel_monthly_dir(run_dir)
        / sensor
        / f"panel_monthly_{sensor}{_suffix_for_monthly_format(fmt)}"
    )


def panel_monthly_wide_path(*, run_dir: Path, fmt: str) -> Path:
    return panel_monthly_dir(run_dir) / f"panel_monthly{_suffix_for_monthly_format(fmt)}"


def panel_monthly_wide_range_path(
    *, run_dir: Path, start_yyyymm: int | str, end_yyyymm: int | str, fmt: str
) -> Path:
    """Additional range-tagged path for the combined monthly panel."""
    return (
        panel_monthly_dir(run_dir)
        / f"panel_monthly_{_range_tag(start_yyyymm, end_yyyymm)}{_suffix_for_monthly_format(fmt)}"
    )


def panel_monthly_wide_level_path(*, run_dir: Path, level: str, fmt: str) -> Path:
    """Wide panel path for a specific level."""
    lvl = sanitise_level(level)
    return panel_monthly_dir(run_dir) / f"panel_monthly_{lvl}{_suffix_for_monthly_format(fmt)}"


def panel_monthly_ext_level_path(*, run_dir: Path, level: str, fmt: str) -> Path:
    """Extended-metrics panel path for a specific level."""
    lvl = sanitise_level(level)
    return panel_monthly_dir(run_dir) / f"panel_monthly_{lvl}_ext{_suffix_for_monthly_format(fmt)}"


def panel_monthly_ext_path(*, run_dir: Path, fmt: str) -> Path:
    return panel_monthly_dir(run_dir) / f"panel_monthly_ext{_suffix_for_monthly_format(fmt)}"


def panel_monthly_ext_range_path(
    *, run_dir: Path, start_yyyymm: int | str, end_yyyymm: int | str, fmt: str
) -> Path:
    """Additional range-tagged path for the extended monthly panel."""
    return (
        panel_monthly_dir(run_dir)
        / f"panel_monthly_ext_{_range_tag(start_yyyymm, end_yyyymm)}{_suffix_for_monthly_format(fmt)}"
    )


def panel_monthly_qc_path(*, run_dir: Path, fmt: str) -> Path:
    """QC sidecar path for the combined monthly panel.

    This artefact is optional and is written only when enabled in config:
      qc.write_panel_monthly_qc_sidecar: true
    """
    return panel_monthly_dir(run_dir) / f"panel_monthly_qc{_suffix_for_monthly_format(fmt)}"


def panel_monthly_qc_range_path(
    *, run_dir: Path, start_yyyymm: int | str, end_yyyymm: int | str, fmt: str
) -> Path:
    """Additional range-tagged path for the QC sidecar."""
    return (
        panel_monthly_dir(run_dir)
        / f"panel_monthly_qc_{_range_tag(start_yyyymm, end_yyyymm)}{_suffix_for_monthly_format(fmt)}"
    )


def rp1_af_dir(run_dir: Path) -> Path:
    """Directory for merger-ready RP1 AF exports."""
    return run_dir / "rp1_af_exports"


def rp1_af_sensor_dir(*, run_dir: Path, level: str, sensor_mode: str) -> Path:
    """Return the sensor-specific directory for a logical RP1 AF level."""
    lvl = sanitise_level(level)
    sensor_tok = sanitise_token(sensor_mode)
    return rp1_af_dir(run_dir) / lvl / sensor_tok


def rp1_af_export_path(
    *,
    run_dir: Path,
    level: str,
    sensor_mode: str,
    partition_key: str,
    partition_value: str,
    fmt: str,
    family: str = "base",
) -> Path:
    """Deterministic path for a merger-ready RP1 AF export file.

    Parameters
    ----------
    level:
        Logical data level carried inside the CSV (for example ``acz`` or
        ``district``).
    sensor_mode:
        Kept in the directory structure rather than in the canonical CSV schema.
    partition_key / partition_value:
        Generic partition token derived from the Stage 1 hierarchy. The helper is
        intentionally agnostic about whether this resolves to ``acz_code`` or
        another configured hierarchy value.
    family:
        Either ``"base"`` or ``"ext"``.
    """
    lvl = sanitise_level(level)
    _sensor_tok = sanitise_token(sensor_mode)
    part_key = sanitise_token(partition_key)
    part_val = sanitise_token(partition_value)

    fam = str(family).strip().lower()
    if fam not in {"base", "ext"}:
        raise ValueError(f"Unsupported RP1 AF family: {family!r}. Supported: ['base', 'ext']")

    stem = f"rp1_af_{lvl}"
    if fam == "ext":
        stem += "_ext"
    stem += f"_{part_key}_{part_val}"
    return (
        rp1_af_sensor_dir(run_dir=run_dir, level=level, sensor_mode=sensor_mode)
        / f"{stem}{_suffix_for_monthly_format(fmt)}"
    )
