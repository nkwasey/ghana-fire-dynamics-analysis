# file: src/mv_firms_panels/core/schema.py
"""Schema validation helpers for tabular artefacts.

Responsibilities
---------------
1) Enforce an *exact* column set and output column order (determinism contract).
2) Validate DataFrame row records against a JSON Schema (draft 2020-12).

The JSON Schemas in this project describe *row-level* records. We validate by converting
each row to a JSON-compatible dict (NaN -> None) and checking each record.

Performance
-----------
For large tables, callers can supply `sample_n` to validate a deterministic subset
(first N rows after sorting), but for audit-grade runs you should validate all rows.

No shapefiles are required; this module only handles pandas DataFrames.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd
from jsonschema import Draft202012Validator


class SchemaValidationError(ValueError):
    """Raised when a DataFrame fails schema or column-contract validation."""


def load_json_schema(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"Schema must be a JSON object: {path}")
    return obj


def enforce_exact_column_order(
    df: pd.DataFrame,
    expected_columns: Sequence[str],
    *,
    allow_reorder: bool = True,
) -> pd.DataFrame:
    """Ensure df has exactly expected columns, and returns a reordered copy."""
    expected = list(expected_columns)
    got = list(df.columns)

    missing = [c for c in expected if c not in df.columns]
    extra = [c for c in df.columns if c not in expected]

    if missing or extra:
        raise SchemaValidationError(f"Column contract failure. Missing={missing} Extra={extra}")

    if got != expected:
        if not allow_reorder:
            raise SchemaValidationError("Column order differs from expected contract.")
        return df.loc[:, expected].copy()

    return df.copy()


def validate_dataframe_against_schema(
    df: pd.DataFrame,
    schema: dict[str, Any],
    *,
    expected_columns: Sequence[str] | None = None,
    allow_reorder: bool = True,
    sample_n: int | None = None,
) -> pd.DataFrame:
    """Validate DataFrame against schema (and optional exact column order contract)."""
    if expected_columns is not None:
        df = enforce_exact_column_order(df, expected_columns, allow_reorder=allow_reorder)
    else:
        df = df.copy()

    validator = Draft202012Validator(schema)

    if sample_n is not None:
        if sample_n <= 0:
            raise ValueError("sample_n must be positive if provided")
        df_to_check = df.head(sample_n)
    else:
        df_to_check = df

    records = df_to_check.where(pd.notnull(df_to_check), None).to_dict(orient="records")

    errors: list[str] = []
    for i, rec in enumerate(records):
        for err in validator.iter_errors(rec):
            loc = ".".join([str(p) for p in err.path]) if err.path else "<row>"
            errors.append(f"row={i} field={loc}: {err.message}")

    if errors:
        preview = "\n".join(errors[:20])
        more = "" if len(errors) <= 20 else f"\n... ({len(errors) - 20} more)"
        raise SchemaValidationError(
            f"Schema validation failed with {len(errors)} errors:\n{preview}{more}"
        )

    return df
