from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.core.board import Board, FootprintInstance, Layer, Trace, Via
from pcbsmith.core.geom import Point


def test_board_keeps_footprints_and_traces_separate_from_symbols() -> None:
    board = Board(
        id="main",
        footprints=[
            FootprintInstance(
                reference="R1",
                footprint_id="stdlib:R_0603",
                position=Point(x=0, y=0),
            )
        ],
        traces=[
            Trace(
                net_name="OUT",
                layer=Layer.F_CU,
                points=[Point(x=0, y=0), Point(x=10, y=0)],
                width=150_000,
            )
        ],
        vias=[Via(net_name="OUT", position=Point(x=5, y=0), drill=300_000, diameter=600_000)],
    )
    assert board.footprints[0].reference == "R1"
    assert board.traces[0].layer == Layer.F_CU


def test_trace_rejects_zero_width() -> None:
    with pytest.raises(ValidationError):
        Trace(
            net_name="OUT",
            layer=Layer.F_CU,
            points=[Point(x=0, y=0), Point(x=10, y=0)],
            width=0,
        )


def test_via_rejects_zero_drill() -> None:
    with pytest.raises(ValidationError):
        Via(net_name="OUT", position=Point(x=5, y=0), drill=0, diameter=600_000)


def test_via_rejects_diameter_smaller_than_drill() -> None:
    with pytest.raises(ValidationError):
        Via(net_name="OUT", position=Point(x=5, y=0), drill=600_000, diameter=300_000)


def test_board_round_trips_json_collections_as_tuples() -> None:
    board = Board(
        id="main",
        traces=[
            Trace(
                net_name="OUT",
                layer=Layer.F_CU,
                points=[Point(x=0, y=0), Point(x=10, y=0)],
                width=150_000,
            )
        ],
        vias=[Via(net_name="OUT", position=Point(x=5, y=0), drill=300_000, diameter=600_000)],
    )

    restored = Board.model_validate_json(board.model_dump_json())

    assert restored == board
    assert isinstance(restored.traces, tuple)
    assert isinstance(restored.traces[0].points, tuple)
    assert isinstance(restored.vias, tuple)


def test_board_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Board.model_validate({"id": "main", "footprintz": []})
