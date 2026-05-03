from __future__ import annotations

from pcbsmith.core.board import Board, FootprintInstance, Layer, Trace, Via
from pcbsmith.core.geom import Point


def test_board_keeps_footprints_and_traces_separate_from_symbols() -> None:
    board = Board(
        id="main",
        footprints=[
            FootprintInstance(reference="R1", footprint_id="stdlib:R_0603", position=Point(x=0, y=0))
        ],
        traces=[
            Trace(net_name="OUT", layer=Layer.F_CU, points=[Point(x=0, y=0), Point(x=10, y=0)], width=150_000)
        ],
        vias=[Via(net_name="OUT", position=Point(x=5, y=0), drill=300_000, diameter=600_000)],
    )
    assert board.footprints[0].reference == "R1"
    assert board.traces[0].layer == Layer.F_CU
