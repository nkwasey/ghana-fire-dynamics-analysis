from __future__ import annotations

"""Deterministic ID / code derivation helpers.

These utilities are pure functions (no I/O) and implement the Stage 1 binding
derivation rules for:

- zone_id (lower snake_case slug)
- dist_id (TitleCase tokens joined by underscores)
- zone_code (mapping-first; fallback initials; deterministic collision handling)
"""

import re  # noqa: E402
from collections.abc import Iterable, Mapping  # noqa: E402
from typing import Final  # noqa: E402

from .text import normalise_text  # noqa: E402

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]+", flags=re.UNICODE)
_ALPHA_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]+", flags=re.UNICODE)


def _tokens_alnum(label: str) -> list[str]:
    s = normalise_text(label)
    return _TOKEN_RE.findall(s)


def _tokens_alpha(label: str) -> list[str]:
    s = normalise_text(label)
    return _ALPHA_RE.findall(s)


def zone_id_from_label(label: str) -> str:
    """Lower snake_case slug derived from label.

    Tokenisation is on non-alphanumerics; punctuation (including backslash) is removed.
    """
    tokens = _tokens_alnum(label)
    if not tokens:
        raise ValueError(f"zone_id_from_label: no alphanumeric tokens in label: {label!r}")
    return "_".join(t.lower() for t in tokens)


def dist_id_from_label(label: str) -> str:
    """TitleCase tokens joined by underscores (e.g., Awutu_Senya).

    Tokenisation is on non-alphanumerics; punctuation (including backslash) is removed.
    """
    tokens = _tokens_alnum(label)
    if not tokens:
        raise ValueError(f"dist_id_from_label: no alphanumeric tokens in label: {label!r}")

    def _title_token(t: str) -> str:
        if len(t) == 1:
            return t.upper()
        return t[0].upper() + t[1:].lower()

    return "_".join(_title_token(t) for t in tokens)


def derive_zone_code(
    label: str,
    *,
    mapping: Mapping[str, str] | None = None,
    used_codes: Iterable[str] | None = None,
) -> str:
    """Derive a zone_code from a label, deterministically.

    Priority:
    1) mapping-first: `mapping[label] -> code` with both label keys and `label`
       compared after `normalise_text(...).casefold()`.
    2) fallback: initials of the first two *alphabetic* tokens (after normalisation).

    Collision handling (deterministic; depends only on `label` and `used_codes`):
    - If the preferred code is unused, return it.
    - Else try longer initial strings (first 3 tokens, then 4, ...).
    - Else append numeric suffixes starting at 2 (e.g., CS2, CS3, ...).

    Notes:
    - Codes are always returned uppercased.
    """
    used = {str(c).upper() for c in (used_codes or [])}

    # 1) mapping-first (case/whitespace robust, deterministic selection)
    code: str | None = None
    if mapping:
        key = normalise_text(label).casefold()
        matches: set[str] = set()
        for k, v in mapping.items():
            if normalise_text(str(k)).casefold() == key:
                matches.add(normalise_text(str(v)).upper())
        if matches:
            # Deterministic choice if multiple identical keys exist in mapping sources.
            code = sorted(matches)[0]

    # 2) fallback initials (first two alphabetic tokens)
    if code is None:
        toks = _tokens_alpha(label)
        if not toks:
            raise ValueError(f"derive_zone_code: no alphabetic tokens in label: {label!r}")
        initials = [t[0].upper() for t in toks if t]
        code = "".join(initials[:2]) if len(initials) >= 2 else initials[0]

    code = code.upper()

    # Collision handling
    if code not in used:
        return code

    toks = _tokens_alpha(label)
    initials = [t[0].upper() for t in toks if t]

    # Try longer initial strings
    for n in range(3, len(initials) + 1):
        cand = "".join(initials[:n]).upper()
        if cand not in used:
            return cand

    # Fall back to numeric suffix
    i = 2
    while True:
        cand = f"{code}{i}"
        if cand not in used:
            return cand
        i += 1
