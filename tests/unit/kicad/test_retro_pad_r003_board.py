from __future__ import annotations

from pcbsmith.kicad.board import BoardLayout, TrackSegment, ViaSpec
from pcbsmith.kicad.retro_pad_r003_board import (
    _prune_unused_isp_fanout,
    _seed_isp_fanout,
)


def _empty_layout() -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=145.0,
        height_mm=55.0,
    )


def test_isp_fanout_seed_is_exactly_reversible() -> None:
    seeded = _seed_isp_fanout(_empty_layout())

    assert {segment.net_name for segment in seeded.segments} == {
        "/SCK",
        "/MOSI",
        "/MISO",
    }
    assert {via.net_name for via in seeded.vias} == {
        "/SCK",
        "/MOSI",
        "/MISO",
    }
    assert _prune_unused_isp_fanout(seeded) == _empty_layout()


def test_isp_fanout_prune_preserves_router_created_copper() -> None:
    routed_segment = TrackSegment(
        x1=94.3,
        y1=32.2,
        x2=94.9,
        y2=32.2,
        layer="B.Cu",
        net_name="/SCK",
        width_mm=0.25,
    )
    routed_via = ViaSpec(x=94.9, y=32.2, net_name="/SCK")
    seeded = _seed_isp_fanout(_empty_layout())
    routed = BoardLayout(
        placements=seeded.placements,
        segments=(*seeded.segments, routed_segment),
        vias=(*seeded.vias, routed_via),
        width_mm=seeded.width_mm,
        height_mm=seeded.height_mm,
    )

    pruned = _prune_unused_isp_fanout(routed)

    assert pruned.segments == (routed_segment,)
    assert pruned.vias == (routed_via,)
