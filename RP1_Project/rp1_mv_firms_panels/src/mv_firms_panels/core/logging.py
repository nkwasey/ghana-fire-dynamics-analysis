# file: src/mv_firms_panels/core/logging.py
"""Run folder creation, config snapshotting, and structured logging.

This module centralises run-level IO concerns:
- create a deterministic run directory under the configured outputs base directory
- snapshot the validated configuration into the run folder (YAML + canonical JSON)
- configure project logging with a console stream handler and a per-run JSONL log

Design notes
------------
The logger configuration must be safe across repeated test runs and repeated CLI
invocations within the same Python process. In particular, pytest may replace and
close its temporary stderr capture streams between tests. If a stale stream handler
is retained across runs, later log writes can raise ``ValueError: I/O operation on
closed file``.

To avoid that failure mode, this module tags and rebuilds only the handlers owned
by ``mv_firms_panels`` on every run initialisation. Handlers installed by pytest
or other libraries are left untouched.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mv_firms_panels.core.config import LoadedConfig
from mv_firms_panels.core.hashing import sha256_file
from mv_firms_panels.io.paths import (
    build_run_dir,
    config_snapshot_json_path,
    config_snapshot_yaml_path,
    logs_dir,
    run_log_jsonl_path,
)

_HANDLER_MARKER = "_mv_firms_panels_handler"


class JsonLineFormatter(logging.Formatter):
    """Minimal JSONL formatter for structured logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts_utc": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        for key, value in record.__dict__.items():
            if key.startswith("_"):
                continue
            if key in payload:
                continue
            if key in {"args", "msg", "exc_info", "exc_text", "stack_info"}:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except TypeError:
                payload[key] = str(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


@dataclass(frozen=True)
class RunContext:
    """Run-level context returned by :func:`initialise_run`."""

    run_id: str
    run_dir: Path
    config_yaml: Path
    config_json: Path
    config_sha256: str
    zip_sha256: str | None = None


def initialise_run(
    loaded_cfg: LoadedConfig,
    *,
    run_id: str,
    repo_root: Path,
    outputs_base_dir: str,
    log_level: str = "INFO",
    zip_sha256: str | None = None,
) -> RunContext:
    """Create run directory, snapshot config, and configure structured logging."""
    run_dir = build_run_dir(repo_root=repo_root, outputs_base_dir=outputs_base_dir, run_id=run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    logs_dir(run_dir).mkdir(parents=True, exist_ok=True)

    cfg_dict = loaded_cfg.config.to_canonical_dict()
    yaml_path = config_snapshot_yaml_path(run_dir)
    json_path = config_snapshot_json_path(run_dir)

    with yaml_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(cfg_dict, handle, sort_keys=False)

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(cfg_dict, handle, ensure_ascii=False, indent=2, sort_keys=True)

    config_sha = sha256_file(json_path)

    _configure_logging(run_dir=run_dir, level=log_level)

    logger = logging.getLogger("mv_firms_panels")
    logger.info(
        "Initialised run",
        extra={
            "run_id": run_id,
            "run_dir": str(run_dir),
            "config_snapshot_yaml": str(yaml_path),
            "config_snapshot_json": str(json_path),
            "config_sha256": config_sha,
            "repo_root": str(repo_root),
            "zip_sha256": zip_sha256,
        },
    )

    return RunContext(
        run_id=run_id,
        run_dir=run_dir,
        config_yaml=yaml_path,
        config_json=json_path,
        config_sha256=config_sha,
        zip_sha256=zip_sha256,
    )


def _iter_project_handlers(logger: logging.Logger) -> list[logging.Handler]:
    """Return handlers owned by ``mv_firms_panels``.

    Only handlers tagged with the private marker are managed here. This allows
    pytest capture handlers and any external logging hooks to remain attached.
    """
    return [handler for handler in logger.handlers if getattr(handler, _HANDLER_MARKER, False)]


def _tag_handler(handler: logging.Handler) -> logging.Handler:
    """Mark a handler as owned by ``mv_firms_panels`` and return it."""
    setattr(handler, _HANDLER_MARKER, True)
    return handler


def _remove_project_handlers(logger: logging.Logger) -> None:
    """Detach and close only the handlers owned by this module."""
    for handler in _iter_project_handlers(logger):
        logger.removeHandler(handler)
        try:
            handler.flush()
        except Exception:
            pass
        try:
            handler.close()
        except Exception:
            pass


def _configure_logging(*, run_dir: Path, level: str) -> None:
    """Configure project logging for the current run.

    The configuration is refreshed on every call so the console stream handler is
    rebound to the current stderr capture object under pytest and the JSONL file
    handler always points at the active run directory.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))

    project_logger = logging.getLogger("mv_firms_panels")
    project_logger.setLevel(root.level)
    project_logger.propagate = True

    _remove_project_handlers(root)

    stream_handler = _tag_handler(logging.StreamHandler())
    stream_handler.setLevel(root.level)
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    root.addHandler(stream_handler)

    file_handler = _tag_handler(logging.FileHandler(run_log_jsonl_path(run_dir), encoding="utf-8"))
    file_handler.setLevel(root.level)
    file_handler.setFormatter(JsonLineFormatter())
    root.addHandler(file_handler)
