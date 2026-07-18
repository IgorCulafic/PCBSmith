from __future__ import annotations

import math
import re
from collections import defaultdict
from uuid import UUID

from tests.unit.kicad.test_clover_board import _segments_intersect

from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist
from pcbsmith.kicad.library import rotate_offset
from pcbsmith.kicad.pear_board import (
    BOARD_H,
    BOARD_W,
    MIN_UNIT_RADIUS,
    P1_PIN_NETS,
    RING_INSETS,
    compute_pear_board_layout,
    pear_outline,
    pear_silk_graphics,
    ring_polyline,
    ring_unit_counts,
    ring_unit_sites,
)

LED_FOOTPRINT = "LED_SMD:LED_0603_1608Metric"
RESISTOR_FOOTPRINT = "Resistor_SMD:R_0603_1608Metric"
UUID_PATTERN = re.compile(r'\(uuid\s+"?([0-9a-f-]{36})"?\)')
CONNECTOR_FOOTPRINT = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"


def _netlist() -> BoardNetlist:
    components = [
        BoardComponent(
            reference="P1", value="12V", footprint=CONNECTOR_FOOTPRINT,
            uuid_path="uuid-P1",
        )
    ]
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for index, net in enumerate(P1_PIN_NETS):
        nodes[net].append(("P1", str(index + 1)))
    unit = 0
    for ring, count in enumerate(ring_unit_counts()):
        for _ in range(count):
            unit += 1
            for reference, footprint in (
                (f"R{unit}", RESISTOR_FOOTPRINT),
                (f"D{unit}", LED_FOOTPRINT),
            ):
                components.append(
                    BoardComponent(
                        reference=reference, value=reference,
                        footprint=footprint, uuid_path=f"uuid-{reference}",
                    )
                )
            nodes[f"L{ring + 1}"].append((f"R{unit}", "1"))
            nodes[f"D{unit}_A"].append((f"R{unit}", "2"))
            nodes[f"D{unit}_A"].append((f"D{unit}", "2"))
            nodes["GND"].append((f"D{unit}", "1"))
    return BoardNetlist(
        components=tuple(components),
        nets=tuple(
            BoardNet(name=f"/{name}", nodes=tuple(pins))
            for name, pins in sorted(nodes.items())
        ),
    )


def test_arbitrary_rotation_offsets() -> None:
    x, y = rotate_offset(1.0, 0.0, 45.0)
    assert math.isclose(x, math.sqrt(0.5), abs_tol=1e-9)
    assert math.isclose(y, -math.sqrt(0.5), abs_tol=1e-9)
    # Right angles keep their exact fast paths.
    assert rotate_offset(1.0, 2.0, 90.0) == (2.0, -1.0)


def test_outline_is_closed_simple_and_inside_the_sheet() -> None:
    points = pear_outline()

    assert len(points) > 100
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


def test_rings_are_parallel_offsets_of_the_outline() -> None:
    outline = pear_outline()

    def distance_to_outline(point: tuple[float, float]) -> float:
        return min(math.dist(point, vertex) for vertex in outline)

    for inset in RING_INSETS:
        ring = ring_polyline(inset)
        for point in ring[:: max(1, len(ring) // 24)]:
            # Vertex sampling overestimates slightly; the ring must never be
            # closer to the edge than its inset.
            distance = distance_to_outline(point)
            assert inset - 0.05 <= distance <= inset + 0.6


def test_unit_sites_avoid_sharp_curvature() -> None:
    counts = ring_unit_counts()
    assert all(count >= 10 for count in counts)
    assert counts[0] > counts[1] > counts[2]
    for ring in range(len(RING_INSETS)):
        for site in ring_unit_sites(ring):
            assert site.piece.radius >= MIN_UNIT_RADIUS


def test_pear_silk_graphics_are_repeatable_with_unique_uuids() -> None:
    first = pear_silk_graphics(20.0)
    second = pear_silk_graphics(20.0)
    matches = [UUID_PATTERN.search(graphic) for graphic in first]

    assert first == second
    assert first
    assert all(match is not None for match in matches)
    uuids = [match.group(1) for match in matches if match is not None]
    assert len(uuids) == len(set(uuids))
    assert all(UUID(value).version == 5 for value in uuids)


def test_layout_routes_every_ring_and_branch() -> None:
    layout = compute_pear_board_layout(_netlist())

    routed = defaultdict(int)
    for segment in layout.segments:
        routed[segment.net_name] += 1
    total = sum(ring_unit_counts())
    for ring in range(1, 4):
        assert routed[f"/L{ring}"] > 50  # bus loop plus taps and the feed
    for unit in range(1, total + 1):
        assert routed[f"/D{unit}_A"] >= 1
    # One ground via per LED plus the ring feeds and the stem stitch pair.
    gnd_vias = [via for via in layout.vias if via.net_name == "/GND"]
    assert len(gnd_vias) == total + 2
    assert len(layout.vias) == total + 2 + 3

    rotations = dict(layout.part_rotation)
    arbitrary = [
        angle for angle in rotations.values() if angle % 90.0 not in (0.0,)
    ]
    assert arbitrary, "tangent-following placements must use arbitrary angles"
    assert layout.zones == (("/GND", "B.Cu", (1.5, 1.5, BOARD_W - 1.5, BOARD_H - 1.5)),)
    assert layout.outline == pear_outline()
    assert "P1" in layout.hide_references
