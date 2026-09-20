from __future__ import annotations

"""Deterministic text normalisation helpers.

These utilities implement the *binding* Stage 1 text normalisation rules:

- Unicode normalisation: NFKC
- Strip leading/trailing whitespace
- Collapse any internal whitespace runs to a single ASCII space

They are pure functions (no I/O).
"""

import re  # noqa: E402
import unicodedata  # noqa: E402
from typing import Final  # noqa: E402

_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+", flags=re.UNICODE)


def normalise_text(value: str) -> str:
    """Apply NFKC, strip, and collapse whitespace to single spaces."""
    if not isinstance(value, str):
        raise TypeError(f"normalise_text expects str, got {type(value).__name__}")
    # NFKC can change compatibility forms (e.g., half-width, ligatures) deterministically.
    s = unicodedata.normalize("NFKC", value)
    s = s.strip()
    s = _WS_RE.sub(" ", s)
    return s


def to_lower_name(label: str) -> str:
    """Derive the lower-case 'name' form from a raw label (punctuation preserved)."""
    return normalise_text(label).lower()


def to_upper_canon(label: str) -> str:
    """Derive the upper-case 'canon' form from a raw label (punctuation preserved)."""
    return normalise_text(label).upper()
