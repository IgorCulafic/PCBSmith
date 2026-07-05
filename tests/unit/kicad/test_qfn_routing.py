from __future__ import annotations

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardNet,
    BoardNetlist,
    _side_escapes,
    compute_board_layout,
)

QFN = "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm"


def test_qfn_fanout_plan_covers_all_four_sides() -> None:
    plan = _side_escapes(FOOTPRINT_LIBRARY[QFN], 0.0)

    sides = {side for side, _, _ in plan.values()}
    assert sides == {"north", "south", "east", "west"}
    # South pins 7-12 spread onto a 1 mm grid.
    south_targets = sorted(
        target for side, target, _ in plan.values() if side == "south"
    )
    assert len(south_targets) == 6
    assert all(
        abs((b - a) - 1.0) < 1e-6
        for a, b in zip(south_targets, south_targets[1:], strict=False)
    )
    # Nested elbows: outermost pads jog shallowest (rank 0).
    south_ranks = [
        (target, rank) for side, target, rank in plan.values() if side == "south"
    ]
    south_ranks.sort()
    assert [rank for _, rank in south_ranks] == [0, 1, 2, 2, 1, 0]


def test_two_pin_parts_get_no_fanout() -> None:
    assert _side_escapes(FOOTPRINT_LIBRARY["Diode_SMD:D_SMA"], 0.0) == {}
    assert (
        _side_escapes(
            FOOTPRINT_LIBRARY["Package_TO_SOT_SMD:TO-263-5_TabPin3"], 90.0
        )
        == {}
    )


def test_north_pads_route_into_the_top_channel() -> None:
    netlist = BoardNetlist(
        components=(
            BoardComponent(
                reference="U1", value="MPU-6050", footprint=QFN, uuid_path="u1"
            ),
            BoardComponent(
                reference="R1",
                value="4.7k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                uuid_path="r1",
            ),
        ),
        nets=(
            # Pin 24 (SDA) is on the QFN north side; R1 sits in the row.
            BoardNet(name="/SDA", nodes=(("U1", "24"), ("R1", "2"))),
            BoardNet(name="/VDD", nodes=(("U1", "13"), ("R1", "1"))),
        ),
    )

    layout = compute_board_layout(netlist, frozenset({"VDD"}))

    above = [
        segment
        for segment in layout.segments
        if segment.net_name == "/SDA"
        and segment.layer == "B.Cu"
        and segment.y1 < layout.parts_row_y_mm
    ]
    assert above, "SDA must get a top-channel lane above the parts row"
    # The join drops from the top lane through R1's pad column.
    joins = [
        segment
        for segment in layout.segments
        if segment.net_name == "/SDA"
        and segment.layer == "F.Cu"
        and segment.y2 < layout.parts_row_y_mm <= segment.y1
    ]
    assert joins, "SDA needs a cross-channel join through its row pad"
