"""Guard the repository README against known text-encoding corruption."""
from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"
MOJIBAKE = ("\u00e2\u20ac", "\u00c2\u00b2", "\ufffd")


def corrupted_lines(text: str) -> list[int]:
    return [
        number
        for number, line in enumerate(text.splitlines(), 1)
        if any(marker in line for marker in MOJIBAKE)
    ]


def test_readme_is_utf8_without_known_mojibake() -> None:
    assert corrupted_lines(README.read_text(encoding="utf-8")) == []


def test_guard_detects_corruption_without_rejecting_valid_characters() -> None:
    assert corrupted_lines("2001\u20132024; km\u00b2; caf\u00e9") == []
    assert corrupted_lines("2001\u00e2\u20ac\u201c2024\nkm\u00c2\u00b2\n\ufffd") == [1, 2, 3]
