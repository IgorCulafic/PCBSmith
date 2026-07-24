"""Thermometer board: shaped outline, scale-locked LEDs, declarations.

The full route (fine-pitch pre-routing + main pass inside the shaped
outline) takes tens of minutes and lives in the golden suite; these
tests pin the FAST invariants the board's correctness rests on: the
outline geometry, the single scale truth shared by copper and silk,
placement containment, and the checks-spec declarations.
"""

from __future__ import annotations

from collections import defaultdict

from pcbsmith.calculators.electronics import thermometer_scale_fraction
from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.thermometer import compose_thermometer
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardNet,
    BoardNetlist,
)
from pcbsmith.kicad.export_thermometer import INSTANCES
from pcbsmith.kicad.thermometer_board import (
    BOARD_H,
    BOARD_W,
    FINE_PITCH_NETS,
    LED_COUNT,
    PLACEMENTS,
    SCALE_Y0,
    SCALE_Y50,
    SENSOR_ISOLATION_CUTOUT,
    STEM_CX,
    _unrouted_layout,
    led_y,
    scale_y,
    thermometer_checks_spec,
    thermometer_outline,
    thermometer_silk_graphics,
)
from pcbsmith.kicad.thermometer_bus import validate_thermometer_bus_groups
from pcbsmith.kicad.virtual_drc import _point_in_polygon, run_virtual_drc

REQUEST = "thermometer temperature humidity display pcb"


def _netlist() -> BoardNetlist:
    intent = classify_circuit_intent(REQUEST)
    design = compose_thermometer(intent, select_topology(intent))
    footprints = {
        component.reference: component.footprint
        for component in design.components
    }
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for reference, _lib, _x, _y, pin_nets in INSTANCES:
        for pin, net in pin_nets.items():
            nodes[net].append((reference, pin))
    return BoardNetlist(
        components=tuple(
            BoardComponent(
                reference=reference,
                value=reference,
                footprint=footprint,
                uuid_path=f"uuid-{reference}",
            )
            for reference, footprint in footprints.items()
        ),
        nets=tuple(
            BoardNet(name=f"/{name}", nodes=tuple(pins))
            for name, pins in sorted(nodes.items())
        ),
    )


def test_outline_is_closed_and_spans_the_board() -> None:
    outline = thermometer_outline()
    assert len(outline) > 40  # tip arc + bulb sweep are real curves
    xs = [x for x, _y in outline]
    ys = [y for _x, y in outline]
    assert min(xs) >= 0 and max(xs) <= BOARD_W
    assert min(ys) >= 0 and max(ys) <= BOARD_H
    # The USB tab reaches the bottom edge; the tip is near the top.
    assert max(ys) == BOARD_H
    assert min(ys) < 10.0


def test_led_column_follows_the_scale_truth() -> None:
    # One scale function drives BOTH the LED copper and the silk
    # graduations: LED k sits exactly at its threshold temperature.
    for index in range(1, LED_COUNT + 1):
        threshold_c = 50.0 * index / LED_COUNT
        fraction = thermometer_scale_fraction(threshold_c)
        expected = SCALE_Y0 + (SCALE_Y50 - SCALE_Y0) * fraction
        assert abs(led_y(index) - expected) < 1e-9
        x, y, _rot = PLACEMENTS[f"D{index}"]
        assert (x, y) == (STEM_CX, led_y(index))
    assert scale_y(0.0) == SCALE_Y0
    assert scale_y(50.0) == SCALE_Y50


def test_placements_sit_inside_the_outline() -> None:
    outline = thermometer_outline()
    for reference, (x, y, _rot) in PLACEMENTS.items():
        assert _point_in_polygon((x, y), outline), (
            f"{reference} anchor ({x}, {y}) is outside the outline"
        )


def test_graduation_silk_marks_every_ten_degrees() -> None:
    graphics = "\n".join(thermometer_silk_graphics(0.0))
    for label in ("0", "10", "20", "30", "40", "50"):
        assert f'"{label}"' in graphics
    assert '"USB-C 5V"' in graphics


def test_checks_spec_declares_the_board_contracts() -> None:
    spec = thermometer_checks_spec()
    assert dict(spec.component_cards) == {
        "U1": "ESP32-C3-WROOM-02",
        "U2": "SN74HC595PW",
        "U3": "SN74HC595PW",
        "U4": "SHT31-DIS",
    }
    # OLED module sockets are on-board carriers, exempt from rule 1.1
    # by declaration.
    assert spec.connector_edge_exempt_refs == ("J2", "J3")
    assert ("J1", "A8") in spec.allowed_unconnected_pins


def test_fine_pitch_declaration_covers_the_sub_grid_pads() -> None:
    # Only the USB-C data/CC row lacks legal 0.2mm entry cells.  The
    # sensor, register cascade, and global rails stay on the main graph.
    assert set(FINE_PITCH_NETS) == {"/DP", "/DM", "/CC1", "/CC2"}
    netlist = _netlist()
    net_names = {net.name for net in netlist.nets}
    assert set(FINE_PITCH_NETS) <= net_names
    assert len(netlist.components) == 63


def test_radio_overhang_and_sensor_island_are_explicit_geometry() -> None:
    assert PLACEMENTS["U1"] == (37.9, 110.0, 270.0)
    assert PLACEMENTS["U4"] == (12.0, 142.05, 0.0)
    layout = _unrouted_layout(_netlist())
    assert layout.cutouts == (SENSOR_ISOLATION_CUTOUT,)
    # All static physical checks are clean; connectivity is intentionally
    # absent before the routing phase.
    assert {
        finding.check
        for finding in run_virtual_drc(layout, _netlist())
        if finding.check != "pad_connectivity"
    } == set()


def test_full_led_and_control_bus_declarations_bind_live_terminals() -> None:
    groups = validate_thermometer_bus_groups(_netlist())
    assert tuple(group.bus_id for group in groups) == (
        "thermometer-segment-drive",
        "thermometer-led-column",
        "thermometer-shift-control",
    )
    assert tuple(len(group.members) for group in groups) == (16, 16, 4)
    assert tuple(member.net_name for member in groups[1].members) == tuple(
        f"/LK{index}" for index in range(1, 17)
    )
