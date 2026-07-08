"""Servo tester board: the first automation-routed PCBSmith board.

Builds the netlist from the exporter's pin-net tables, lets
``route_board`` produce every trace from the coarse placements, and
asserts the virtual DRC is clean plus the design checks pass. Mutation
cases lock in the machinery this board bought: rect-pad corner coverage
in the router's obstacle model, per-physical-pad connectivity (switch
footprints carry duplicate pad numbers), and the silkscreen text-height
and board-edge checks.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.servo555 import compose_servo555
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardNet,
    BoardNetlist,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.export_servo555 import INSTANCES
from pcbsmith.kicad.servo555_board import (
    BOARD_H,
    BOARD_W,
    compute_servo555_board_layout,
)
from pcbsmith.kicad.virtual_drc import _collect_items, run_virtual_drc

REQUEST = (
    "Design a compact PCB for a 555-timer-based RC servo driver tester "
    "with forward and reverse buttons"
)


def _netlist() -> BoardNetlist:
    intent = classify_circuit_intent(REQUEST)
    design = compose_servo555(intent, select_topology(intent))
    footprints = {
        component.reference: component.footprint
        for component in design.components
    }
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for reference, _lib, _x, pin_nets in INSTANCES:
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


def test_router_layout_is_virtually_clean_and_passes_design_checks() -> None:
    netlist = _netlist()
    layout = compute_servo555_board_layout(netlist)

    assert layout.width_mm == BOARD_W and layout.height_mm == BOARD_H
    assert layout.segments, "route_board produced no copper"
    assert run_virtual_drc(layout, netlist) == ()

    review = run_design_checks(
        layout,
        netlist,
        DesignChecksSpec(
            net_currents=(("/VCC", 1.0), ("/GND", 1.0)),
            component_cards=(("U1", "NE555"),),
            tie_nets=(("GND", "/GND"), ("VCC", "/VCC")),
        ),
    )
    assert review.status == "passed", review


def test_power_nets_carry_the_forty_mil_width() -> None:
    netlist = _netlist()
    layout = compute_servo555_board_layout(netlist)
    for segment in layout.segments:
        if segment.net_name in ("/VCC", "/GND"):
            assert segment.width_mm >= 1.0, segment


def test_every_physical_switch_pad_gets_copper() -> None:
    # SW_PUSH carries two pads per number; KiCad's ratsnest wants copper
    # to each. Stripping one switch net's copper must trip the
    # pad-connectivity check (this exact miss escaped to kicad-cli once).
    netlist = _netlist()
    layout = compute_servo555_board_layout(netlist)
    stripped = replace(
        layout,
        segments=tuple(
            s for s in layout.segments if s.net_name != "/FWDM"
        ),
        vias=tuple(v for v in layout.vias if v.net_name != "/FWDM"),
    )
    findings = run_virtual_drc(stripped, netlist)
    assert any(f.check == "pad_connectivity" for f in findings)


def test_rect_pad_corners_are_covered_for_the_router() -> None:
    # Q1's pin-1 pad is a rect; the stadium underestimates its corners
    # unless the router's obstacle mode inflates it (kicad-cli caught
    # corner-cutting routes live).
    netlist = _netlist()
    layout = compute_servo555_board_layout(netlist)
    plain = {
        (i.label, i.layer): i.radius
        for i in _collect_items(layout, netlist)
        if i.label.startswith("pad Q1.1")
    }
    covered = {
        (i.label, i.layer): i.radius
        for i in _collect_items(layout, netlist, cover_rect_pads=True)
        if i.label.startswith("pad Q1.1")
    }
    assert covered and all(
        covered[key] > plain[key] for key in plain
    )


def test_silk_text_height_and_edge_containment_are_checked() -> None:
    from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM
    from pcbsmith.kicad.shaped_board import silk_text

    netlist = _netlist()
    layout = compute_servo555_board_layout(netlist)
    mutated = replace(
        layout,
        graphics=(
            *layout.graphics,
            # Below the 0.8 mm board minimum.
            silk_text("tiny", (28.0, 2.5), BOARD_SHEET_ORIGIN_MM, size=0.6),
            # Clipped by the west board edge.
            silk_text("edge", (-0.5, 2.5), BOARD_SHEET_ORIGIN_MM, size=1.0),
        ),
    )
    checks = {f.check for f in run_virtual_drc(mutated, netlist)}
    assert "silk_text_height" in checks
    assert "silk_edge_clearance" in checks
