from __future__ import annotations

import re
from uuid import UUID

import pytest

from pcbsmith.kicad.shaped_board import (
    mask_opening_disc,
    silk_line,
    silk_poly,
    silk_text,
)

UUID_PATTERN = re.compile(r'\(uuid\s+"?([0-9a-f-]{36})"?\)')


def _uuid(graphic: str) -> str:
    match = UUID_PATTERN.search(graphic)
    assert match is not None
    return match.group(1)


def test_shared_graphic_primitives_repeat_with_unique_semantic_ids() -> None:
    polygon = silk_poly(((0.0, 0.0), (2.0, 0.0), (1.0, 1.0)), 20.0)
    line = silk_line((0.0, 0.0), (3.0, 1.0), 20.0, width=0.2)
    text = silk_text("ID", (2.0, 3.0), 20.0, size=0.9)
    mask = mask_opening_disc((4.0, 5.0), 2.0, 20.0)

    assert polygon == silk_poly(
        ((0.0, 0.0), (2.0, 0.0), (1.0, 1.0)),
        20.0,
    )
    assert line == silk_line(
        (0.0, 0.0),
        (3.0, 1.0),
        20.0,
        width=0.2,
    )
    assert text == silk_text("ID", (2.0, 3.0), 20.0, size=0.9)
    assert mask == mask_opening_disc((4.0, 5.0), 2.0, 20.0)

    values = [_uuid(item) for item in (polygon, line, text, mask)]
    assert len(values) == len(set(values))
    assert all(UUID(value).version == 5 for value in values)


def test_line_identity_normalizes_direction_and_supports_duplicates() -> None:
    forward = silk_line((1.0, 2.0), (4.0, 6.0), 20.0)
    reverse = silk_line((4.0, 6.0), (1.0, 2.0), 20.0)
    duplicate = silk_line(
        (1.0, 2.0),
        (4.0, 6.0),
        20.0,
        occurrence=1,
    )

    assert _uuid(forward) == _uuid(reverse)
    assert _uuid(forward) != _uuid(duplicate)
    assert duplicate == silk_line(
        (1.0, 2.0),
        (4.0, 6.0),
        20.0,
        occurrence=1,
    )


def test_graphic_occurrence_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        silk_text("bad", (0.0, 0.0), 20.0, occurrence=-1)
