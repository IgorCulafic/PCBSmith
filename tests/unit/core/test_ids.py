from __future__ import annotations

from pcbsmith.core.ids import make_id


def test_make_id_uses_prefix_and_slug() -> None:
    assert make_id("sym", "Resistor 10k") == "sym:resistor-10k"


def test_make_id_strips_repeated_separators() -> None:
    assert make_id("fp", "  SOIC--8 / Wide  ") == "fp:soic-8-wide"


def test_make_id_rejects_empty_slug() -> None:
    try:
        make_id("net", " -- / ")
    except ValueError as error:
        assert str(error) == "Cannot create an id from empty text"
    else:
        raise AssertionError("Expected ValueError")
