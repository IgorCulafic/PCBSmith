from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardNet,
    BoardNetlist,
    render_board_from_layout,
)
from pcbsmith.kicad.clover_board import (
    BOARD_H,
    BOARD_W,
    clover_outline,
    clover_silk_graphics,
    compute_clover_board_layout,
)
from pcbsmith.kicad.export_clover import U1_PIN_NETS, U2_PIN_NETS

FOOTPRINTS = {
    "P1": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    "U1": "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm",
    "U2": "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    **{f"C{i}": "Capacitor_SMD:C_0603_1608Metric" for i in range(1, 6)},
    **{f"R{i}": "Resistor_SMD:R_0603_1608Metric" for i in range(1, 7)},
    **{f"D{i}": "LED_SMD:LED_0603_1608Metric" for i in range(1, 5)},
}
MOTTO = "Luck be with 'ye"
UUID_PATTERN = re.compile(r'\(uuid\s+"?([0-9a-f-]{36})"?\)')

# (reference, pin-1 net, pin-2 net) for the two-pin parts, mirroring the
# schematic exporter's passives table (LED pin 1 = cathode, rule 8.4).
TWO_PIN_NETS = (
    ("P1", "VDD", "GND"),
    ("C1", "REGOUT", "GND"),
    ("C2", "VDD", "GND"),
    ("C3", "CPOUT", "GND"),
    ("C4", "VDD", "GND"),
    ("C5", "VDD", "GND"),
    ("R1", "VDD", "SDA"),
    ("R2", "VDD", "SCL"),
    ("R3", "LEAF_NE", "LEAF_NE_A"),
    ("R4", "LEAF_NW", "LEAF_NW_A"),
    ("R5", "LEAF_SW", "LEAF_SW_A"),
    ("R6", "LEAF_SE", "LEAF_SE_A"),
    ("D1", "GND", "LEAF_NE_A"),
    ("D2", "GND", "LEAF_NW_A"),
    ("D3", "GND", "LEAF_SW_A"),
    ("D4", "GND", "LEAF_SE_A"),
)


def _netlist() -> BoardNetlist:
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for pin, net in U1_PIN_NETS.items():
        nodes[net].append(("U1", str(pin)))
    for pin, net in U2_PIN_NETS.items():
        nodes[net].append(("U2", str(pin)))
    for reference, net_one, net_two in TWO_PIN_NETS:
        nodes[net_one].append((reference, "1"))
        nodes[net_two].append((reference, "2"))
    return BoardNetlist(
        components=tuple(
            BoardComponent(
                reference=reference,
                value=reference,
                footprint=footprint,
                uuid_path=f"uuid-{reference}",
            )
            for reference, footprint in FOOTPRINTS.items()
        ),
        nets=tuple(
            BoardNet(name=f"/{name}", nodes=tuple(pins))
            for name, pins in sorted(nodes.items())
        ),
    )


def _segments_intersect(
    a: tuple[tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    (ax1, ay1), (ax2, ay2) = a
    (bx1, by1), (bx2, by2) = b

    def orient(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> float:
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    d1 = orient(bx1, by1, bx2, by2, ax1, ay1)
    d2 = orient(bx1, by1, bx2, by2, ax2, ay2)
    d3 = orient(ax1, ay1, ax2, ay2, bx1, by1)
    d4 = orient(ax1, ay1, ax2, ay2, bx2, by2)
    return d1 * d2 < 0 and d3 * d4 < 0


def test_outline_is_closed_simple_and_inside_the_sheet() -> None:
    points = clover_outline()

    assert len(points) > 100  # smooth arc sampling
    assert len(set(points)) == len(points)  # no duplicate vertices
    for x, y in points:
        assert 0.0 <= x <= BOARD_W
        assert 0.0 <= y <= BOARD_H
    # The polygon must be simple: no two non-adjacent edges intersect.
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


def test_silk_art_has_four_leaves_a_stem_and_the_motto() -> None:
    first = clover_silk_graphics(20.0, MOTTO)
    second = clover_silk_graphics(20.0, MOTTO)

    assert first == second
    polys = [graphic for graphic in first if "gr_poly" in graphic]
    assert len(polys) == 12  # 4 leaves x (2 lobes + 1 wedge)
    assert any("gr_line" in graphic for graphic in first)
    assert any(MOTTO in graphic for graphic in first)
    uuids = [UUID_PATTERN.search(graphic).group(1) for graphic in first]
    assert len(uuids) == len(set(uuids))
    assert all(UUID(value).version == 5 for value in uuids)


def test_layout_places_backside_parts_and_routes_every_leaf() -> None:
    layout = compute_clover_board_layout(_netlist(), MOTTO)

    # Sensor and MCU live on the back with the support passives.
    for reference in ("U1", "U2", "C1", "C2", "C3", "C4", "C5", "R1", "R2"):
        assert reference in layout.part_flip
    # LEDs and their resistors stay on the art face.
    for reference in ("D1", "D2", "D3", "D4", "R3", "R4", "R5", "R6"):
        assert reference not in layout.part_flip
    assert set(layout.hide_references) >= {"D1", "D2", "D3", "D4"}

    routed_nets = {segment.net_name for segment in layout.segments}
    for leaf in ("NE", "NW", "SW", "SE"):
        assert f"/LEAF_{leaf}" in routed_nets
        assert f"/LEAF_{leaf}_A" in routed_nets
    for net in ("/SDA", "/SCL", "/INT", "/REGOUT", "/CPOUT", "/VDD", "/GND"):
        assert net in routed_nets

    zone_nets = [net for net, _layer, _rect in layout.zones]
    assert zone_nets.count("/VDD") == 2
    assert zone_nets.count("/GND") == 1
    assert layout.outline == clover_outline()


def test_complete_clover_board_render_is_repeatable_with_unique_uuids() -> None:
    netlist = _netlist()
    first = render_board_from_layout(
        netlist,
        compute_clover_board_layout(netlist, MOTTO),
    )
    second = render_board_from_layout(
        netlist,
        compute_clover_board_layout(netlist, MOTTO),
    )
    uuids = UUID_PATTERN.findall(first)

    assert first == second
    assert uuids
    assert len(uuids) == len(set(uuids))
    assert all(UUID(value).version == 5 for value in uuids)
