from __future__ import annotations

import hashlib
import re

import pytest

from pcbsmith.kicad.board import (
    BoardCutoutPolygon,
    BoardLayout,
    BoardNetlist,
    render_board_from_layout,
)


def _layout(*cutouts: BoardCutoutPolygon) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=10.0,
        height_mm=8.0,
        cutouts=cutouts,
    )


def _cutout(points: tuple[tuple[float, float], ...]) -> BoardCutoutPolygon:
    return BoardCutoutPolygon(points=points)


def _render(layout: BoardLayout) -> str:
    return render_board_from_layout(BoardNetlist(components=(), nets=()), layout)


def test_empty_default_preserves_named_net_render_bytes() -> None:
    rendered = _render(_layout())

    # The cutout-neutral snapshot follows the accepted KiCad 10 named-net
    # serializer.  It deliberately omits the legacy 13-byte `(net 0 "")`
    # declaration; reinstating that declaration reproduces the superseded
    # 577-byte/93964948... snapshot exactly.
    assert '(net 0 "")' not in rendered
    assert len(rendered.encode()) == 564
    assert hashlib.sha256(rendered.encode()).hexdigest() == (
        "c049413784d46ff4e1ec728c38adcb7c2c19db7a09e952ba118690e6a7dd91ee"
    )


def test_cutout_renders_as_closed_edge_cuts_with_semantic_uuid() -> None:
    cutout = _cutout(((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)))
    rendered = _render(_layout(cutout))
    cutout_section = rendered.split("(gr_poly", 1)[1].split("(gr_rect", 1)[0]

    assert '(layer "Edge.Cuts")' in cutout_section
    assert "(fill none)" in cutout_section
    assert cutout_section.count("(xy ") == 4
    assert re.search(r"\(uuid [0-9a-f-]{36}\)", cutout_section)


def test_cutout_order_winding_and_start_do_not_change_bytes_or_uuid() -> None:
    left = _cutout(((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)))
    left_reversed = _cutout(((4.0, 4.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0)))
    right = _cutout(((6.0, 4.0), (8.0, 4.0), (8.0, 6.0), (6.0, 6.0)))

    first = _render(_layout(left, right))
    second = _render(_layout(right, left_reversed))

    assert first == second
    uuids = re.findall(r"\(uuid ([0-9a-f-]{36})\)", first)
    assert len(uuids) == len(set(uuids)) == 3


def test_board_layout_rejects_cutout_outside_or_touching_rectangle() -> None:
    outside = _cutout(((9.0, 2.0), (11.0, 2.0), (11.0, 4.0), (9.0, 4.0)))
    touching = _cutout(((0.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)))

    with pytest.raises(ValueError, match="strictly inside|touch or cross"):
        _layout(outside)
    with pytest.raises(ValueError, match="strictly inside|touch or cross"):
        _layout(touching)


def test_board_layout_validates_cutouts_against_concave_custom_outline() -> None:
    outline = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 8.0),
        (6.0, 8.0),
        (6.0, 3.0),
        (4.0, 3.0),
        (4.0, 8.0),
        (0.0, 8.0),
    )
    in_notch = _cutout(((4.5, 4.0), (5.5, 4.0), (5.5, 6.0), (4.5, 6.0)))

    with pytest.raises(ValueError, match="strictly inside"):
        BoardLayout(
            placements=(),
            segments=(),
            vias=(),
            width_mm=10.0,
            height_mm=8.0,
            outline=outline,
            cutouts=(in_notch,),
        )
