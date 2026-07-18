from __future__ import annotations

import math
from collections import defaultdict

from tests.unit.kicad.test_clover_board import _segments_intersect

from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist
from pcbsmith.kicad.copper_exposure import exposure_index
from pcbsmith.kicad.copper_identity import track_copper_source_id, via_copper_source_id
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
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

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


def detector_netlist() -> BoardNetlist:
    """Publicly named production fixture while preserving legacy `_netlist` imports."""
    return _netlist()


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

    # The mask opening is typed; raw graphics remain opaque silk strings.
    assert not any('(layer "F.Mask")' in graphic for graphic in layout.graphics)
    assert len(layout.mask_apertures) == 1
    assert layout.mask_apertures[0].geometry is not None
    assert layout.outline == detector_outline()
    # Everything on the handle hides its reference (art-face style).
    assert set(PLACEMENTS) == set(layout.hide_references)


def test_spiral_turn_count_matches_the_advertised_inductor() -> None:
    # ~180 samples per turn at the default step.
    assert len(spiral_points()) == SPIRAL_TURNS * 180 + 1


def test_production_spiral_exposure_is_side_specific_and_conservative() -> None:
    netlist = detector_netlist()
    layout = compute_detector_board_layout(netlist)
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "geometry": DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
                update={"default_pad_solder_mask_expansion_mm": 0.0}
            )
        }
    )
    indexed = exposure_index(layout, netlist, profile)

    spiral_indices = [
        index
        for index, segment in enumerate(layout.segments)
        if segment.net_name == "/COL"
        and segment.layer == "F.Cu"
        and math.isclose(segment.width_mm, SPIRAL_TRACE_W, abs_tol=1e-12)
    ]
    assert spiral_indices
    spiral_results = [indexed[track_copper_source_id(index)] for index in spiral_indices]
    assert all(result.state == "fully_exposed" for result in spiral_results)
    assert all(result.role == "routed_conductor" for result in spiral_results)
    # Full exposure is monotonic: unresolved inherit apertures cannot cover copper
    # that the exact typed front opening already proves fully exposed.
    assert all(result.unresolved_aperture_source_ids for result in spiral_results)

    inner_end = spiral_points()[-1]
    inner_via_indices = [
        index
        for index, via in enumerate(layout.vias)
        if via.net_name == "/COL"
        and math.isclose(via.x, inner_end[0], abs_tol=1e-9)
        and math.isclose(via.y, inner_end[1], abs_tol=1e-9)
    ]
    assert len(inner_via_indices) == 1
    inner_via_index = inner_via_indices[0]
    front_land = indexed[via_copper_source_id(inner_via_index, "F.Cu")]
    back_land = indexed[via_copper_source_id(inner_via_index, "B.Cu")]
    assert front_land.state == "fully_exposed"
    assert front_land.role == "via_land"
    assert front_land.unresolved_aperture_source_ids
    assert back_land.state == "unknown"
    assert back_land.role == "via_land"
    assert back_land.unresolved_aperture_source_ids

    return_indices = [
        index
        for index, segment in enumerate(layout.segments)
        if segment.net_name == "/COL" and segment.layer == "B.Cu"
    ]
    assert return_indices
    return_results = [indexed[track_copper_source_id(index)] for index in return_indices]
    assert all(result.state == "unknown" for result in return_results)
    assert all(result.role == "routed_conductor" for result in return_results)
    assert all(not result.aperture_source_ids for result in return_results)

    zone_results = [
        result for source_id, result in indexed.items() if source_id.startswith("zone:")
    ]
    assert len(zone_results) == 1
    assert zone_results[0].state == "unknown"
    assert zone_results[0].role == "copper_pour"
    assert zone_results[0].reason == "copper geometry is unsupported"
