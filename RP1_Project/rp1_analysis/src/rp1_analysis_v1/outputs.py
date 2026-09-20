"""Deterministic, atomic output writing for RP1 Analysis v1."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import OutputContract


class OutputPolicyError(ValueError):
    """Raised when an output path or filename violates the governed policy."""


OUTPUT_ROLES = frozenset({"manuscript", "supplementary", "internal_authority"})


def validate_output_role(role: str) -> str:
    """Validate one governed publication-output role and return it unchanged."""

    if role not in OUTPUT_ROLES:
        raise OutputPolicyError(
            f"Unsupported output role {role!r}; expected one of {sorted(OUTPUT_ROLES)!r}"
        )
    return role


@dataclass(frozen=True, slots=True)
class OutputRecord:
    path: str
    sha256: str
    size_bytes: int


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def stable_filename(name: str, allowed_pattern: str = r"^[A-Za-z0-9][A-Za-z0-9._-]*$") -> str:
    """Validate a stable single-component filename and return it unchanged."""

    if not name or name in {".", ".."} or Path(name).name != name:
        raise OutputPolicyError(f"Filename must be one stable path component: {name!r}")
    if not re.fullmatch(allowed_pattern, name):
        raise OutputPolicyError(f"Filename violates deterministic filename policy: {name!r}")
    return name


def _normalise_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def require_exact_columns(
    actual: Sequence[str], expected: Sequence[str], *, context: str
) -> tuple[str, ...]:
    """Fail closed unless a machine-readable authority has the exact governed schema."""
    actual_tuple = tuple(str(value) for value in actual)
    expected_tuple = tuple(str(value) for value in expected)
    if actual_tuple != expected_tuple:
        raise OutputPolicyError(
            f"{context} columns differ from the governed exact schema; "
            f"actual={actual_tuple!r}, expected={expected_tuple!r}"
        )
    return actual_tuple


def _atomic_write_bytes(destination: Path, payload: bytes, *, overwrite: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
        if overwrite:
            os.replace(tmp, destination)
        else:
            try:
                os.link(tmp, destination)
            except FileExistsError:
                raise FileExistsError(destination) from None
            tmp.unlink()
    finally:
        if tmp.exists():
            tmp.unlink()


class OutputWriter:
    """Write only inside a pre-created run directory under the output contract."""

    def __init__(self, run_dir: str | Path, contract: OutputContract):
        self.run_dir = Path(run_dir).resolve()
        self.contract = contract
        if not self.run_dir.is_dir():
            raise OutputPolicyError(f"Run directory does not exist: {self.run_dir}")
        self._allowed_pattern = str(contract.filename_policy["allowed_pattern"])

    def _resolve(self, relative: str | Path) -> Path:
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise OutputPolicyError(
                f"Output path must be run-relative and traversal-free: {relative}"
            )
        if rel.parts[0] not in self.contract.sections:
            raise OutputPolicyError(
                f"Output must begin with a governed run section; got {rel.parts[0]!r}"
            )
        stable_filename(rel.name, self._allowed_pattern)
        destination = (self.run_dir / rel).resolve()
        try:
            destination.relative_to(self.run_dir)
        except ValueError:
            raise OutputPolicyError(f"Output escapes run directory: {relative}") from None
        return destination

    def _record(self, destination: Path) -> OutputRecord:
        return OutputRecord(
            path=destination.relative_to(self.run_dir).as_posix(),
            sha256=sha256_file(destination),
            size_bytes=destination.stat().st_size,
        )

    def write_bytes(
        self, relative: str | Path, payload: bytes, *, role: str | None = None, overwrite: bool = False
    ) -> OutputRecord:
        """Atomically write binary output inside the governed run directory."""
        if role is not None:
            validate_output_role(role)
        if not isinstance(payload, (bytes, bytearray)):
            raise OutputPolicyError("Binary output payload must be bytes")
        destination = self._resolve(relative)
        _atomic_write_bytes(destination, bytes(payload), overwrite=overwrite)
        return self._record(destination)

    def write_text(
        self, relative: str | Path, text: str, *, role: str | None = None, overwrite: bool = False
    ) -> OutputRecord:
        if role is not None:
            validate_output_role(role)
        destination = self._resolve(relative)
        payload = _normalise_text(text).encode("utf-8")
        _atomic_write_bytes(destination, payload, overwrite=overwrite)
        return self._record(destination)

    def write_json(
        self,
        relative: str | Path,
        value: Any,
        *,
        role: str | None = None,
        overwrite: bool = False,
    ) -> OutputRecord:
        payload = (
            json.dumps(
                value,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
        return self.write_text(relative, payload, role=role, overwrite=overwrite)

    def write_csv(
        self,
        relative: str | Path,
        rows: Iterable[Mapping[str, Any]],
        *,
        columns: Sequence[str] | None = None,
        contract_column_order: str | None = None,
        role: str | None = None,
        overwrite: bool = False,
    ) -> OutputRecord:
        if role is not None:
            validate_output_role(role)
        materialised = [dict(row) for row in rows]
        if columns is not None and contract_column_order is not None:
            raise OutputPolicyError("Specify columns or contract_column_order, not both")
        if contract_column_order is not None:
            configured = self.contract.csv_column_orders.get(contract_column_order)
            if configured is None:
                raise OutputPolicyError(
                    f"Unknown contract CSV column order: {contract_column_order!r}"
                )
            columns = tuple(str(x) for x in configured)
        if columns is None:
            if not materialised:
                raise OutputPolicyError("CSV columns must be supplied when rows are empty")
            columns = tuple(sorted(materialised[0]))
        else:
            columns = tuple(columns)
        if not columns or len(columns) != len(set(columns)):
            raise OutputPolicyError("CSV columns must be unique and non-empty")
        expected = set(columns)
        for index, row in enumerate(materialised):
            keys = set(row)
            if keys != expected:
                missing = sorted(expected - keys)
                extra = sorted(keys - expected)
                raise OutputPolicyError(
                    f"CSV row {index} does not match governed columns; missing={missing}, extra={extra}"
                )
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for row in materialised:
            writer.writerow({column: row[column] for column in columns})
        return self.write_text(relative, buffer.getvalue(), role=role, overwrite=overwrite)
