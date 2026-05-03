from __future__ import annotations

from pcbsmith.core.ids import make_id


def test_make_id_uses_prefix_and_slug() -> None:
    assert make_id("sym", "Resistor 10k") == "sym:resistor-10k"


def test_make_id_strips_repeated_separators() -> None:
    assert make_id("fp", "  SOIC--8 / Wide  ") == "fp:soic-8-wide"
