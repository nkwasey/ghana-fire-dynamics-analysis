"""Generic schema utilities for RP1 Analysis.

Study-specific field identities, supports and reconciliation sets are owned by
``data_schema_contract.yml`` and scientific roles by ``analysis_contract.yml``.
"""

from __future__ import annotations

from collections.abc import Iterable


def resolve_field_role(analysis: object, role_path: str) -> str | tuple[str, ...]:
    """Resolve a dotted scientific field role from an AnalysisContract-like object."""

    current = getattr(analysis, "field_roles", None)
    if current is None:
        raise ValueError("analysis object does not expose field_roles")
    for token in role_path.split("."):
        if not hasattr(current, "__getitem__"):
            raise ValueError(f"Field-role path is not a mapping at {token!r}: {role_path!r}")
        try:
            current = current[token]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Unknown scientific field role: {role_path!r}") from exc
    if isinstance(current, str):
        return current
    if isinstance(current, tuple) and all(isinstance(x, str) for x in current):
        return current
    raise ValueError(f"Scientific field role does not resolve to field identity/identities: {role_path!r}")


def ensure_declared_fields(fields: Iterable[str], declared: Iterable[str]) -> None:
    """Reject field identities not declared by a supplied schema authority."""

    declared_set = set(declared)
    unsupported = sorted(set(fields).difference(declared_set))
    if unsupported:
        raise ValueError(f"Fields are not declared by the data schema: {unsupported!r}")
