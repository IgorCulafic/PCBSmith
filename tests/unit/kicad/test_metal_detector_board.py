from __future__ import annotations

import math
from collections import defaultdict

from tests.unit.kicad.test_clover_board import _segments_intersect

from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist
from pcbsmith.kicad.metal_detector_board import (
    BOARD_H,
    BOARD_W,
    COIL_CENTER,
    MASK_OPENING_RADIUS,
    P1_PIN_NETS,
    PLACEMENTS,
    SPIRAL_OUTER_RADIUS,
    SPIRAL_PITCH,
    SPIRAL_TRACE_W,
    SPIRAL_TURNS,
    compute_detector_board_layout,
    detector_outline,
    spiral_inner_radius,
    spiral_points,
)

FOOTPRINTS = {
    "P1": "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
    "Q1": "Package_TO_SOT_SMD:SOT-23",
    "L1": "NetTie:NetTie-2_SMD_Pad2.0mm",
    **{f"R{i}": "Resistor_SMD:R_0603_1608Metric" for i in range(1, 5)},
    **{f"C{i}": "Capacitor_SMD:C_0603_1608Metric" for i in range(1, 6)},
}
TWO_PIN_NETS = (
    ("R1", "VCC", "BASE"),
    ("R2", "BASE", "GND"),
    ("C5", "BASE", "GND"),
    ("L1", "VCC", "COL"),
    ("C1", "COL", "EM"),
    ("C2", "EM", "GND"),
    ("R3", "EM", "GND"),
    ("C4", "VCC", "GND"),
    ("C3", "COL", "FO_A"),
    ("R4", "FO_A", "FOUT"),
)


def _netlist() -> BoardNetlist:
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for index, net in enumerate(P1_PIN_NETS):
        nodes[net].append(("P1", str(index + 1)))
    for pin, net in ((1, "BASE"), (2, "EM"), (3, "COL")):
        nodes[net].append(("Q1", str(pin)))
    for reference, net_one, net_two in TWO_PIN_NETS:
        nodes[net_one].append((reference, "1"))
        nodes[net_two].append((reference, "2"))
    return BoardNetlist(
        components=tuple(
            BoardComponent(
                reference=reference, value=reference,
                footprint=footprint, uuid_path=f"uuid-{reference}",
            )
            for reference, footprint in FOOTPRINTS.items()
        ),
        nets=tuple(
            BoardNet(name=f"/{name}", nodes=tuple(pins))
            for name, pins in sorted(nodes.items())
        ),
    )


def test_outline_is_closed_simple_and_inside_the_sheet() -> None:
    points = detector_outline()

    for x, y in points:
        assert 0.0 <= x <= BOARD_W
        assert 0.0 <= y <= BOARD_H
    edges = [
        (points[i], points[(i + 1) % len(points)]) for i in range(len(points))
    ]
    crossings = [
        (i, j)
        for i in range(len(edges))
        for j in range(i + 2, len(edges))
        if not (i == 0 and j == len(edges) - 1)
        and _segments_intersect(edges[i], edges[j])
    ]
    assert crossings == []


def test_spiral_geometry_keeps_its_pitch_and_stays_on_the_board() -> None:
    points = spiral_points()

    for x, y in points:
        radius = math.dist((x, y), COIL_CENTER)
        assert spiral_inner_radius() - 0.01 <= radius <= SPIRAL_OUTER_RADIUS + 0.01
        # The whole spiral stays under the mask opening and off the edge.
        assert radius <= MASK_OPENING_RADIUS
    # Adjacent turns are one pitch apart: the copper gap never collapses.
    gap = SPIRAL_PITCH - SPIRAL_TRACE_W
    assert gap >= 0.5
    # Sample a radial: distances between consecutive crossings of the +x
    # axis differ by exactly the pitch.
    crossings = [
        math.dist(point, COIL_CENTER)
        for point, following in zip(points, points[1:], strict=False)
        if point[1] < COIL_CENTER[1] <= following[1]
        and point[0] > COIL_CENTER[0]
    ]
    for first, second in zip(crossings, crossings[1:], strict=False):
        assert math.isclose(first - second, SPIRAL_PITCH, abs_tol=0.05)


def test_layout_wires_the_oscillator_and_keeps_the_coil_area_clean() -> None:
    layout = compute_detector_board_layout(_netlist())

    routed = defaultdict(int)
    for segment in layout.segments:
        routed[segment.net_name] += 1
    for net in ("/VCC", "/GND", "/BASE", "/EM", "/COL", "/FO_A", "/FOUT"):
        assert routed[net] >= 1
    # The spiral is a single conductor: hundreds of COL segments.
    assert routed["/COL"] > 1000

    # Rule 9.1: the only back-layer copper under the coil is the return.
    inner_limit = 20.0
    for segment in layout.segments:
        if segment.layer != "B.Cu":
            continue
        for point in ((segment.x1, segment.y1), (segment.x2, segment.y2)):
            if math.dist(point, COIL_CENTER) < inner_limit:
                assert segment.net_name == "/COL"
    zone_net, zone_layer, zone_rect = layout.zones[0]
    assert (zone_net, zone_layer) == ("/GND", "B.Cu")
    assert zone_rect[3] < COIL_CENTER[1] - SPIRAL_OUTER_RADIUS + 0.5

    # The mask-opening graphic exists on F.Mask.
    assert any('(layer "F.Mask")' in graphic for graphic in layout.graphics)
    assert layout.outline == detector_outline()
    # Everything on the handle hides its reference (art-face style).
    assert set(PLACEMENTS) == set(layout.hide_references)


def test_spiral_turn_count_matches_the_advertised_inductor() -> None:
    # ~180 samples per turn at the default step.
    assert len(spiral_points()) == SPIRAL_TURNS * 180 + 1
