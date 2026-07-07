"""Flyback board: offline geometry checks without kicad-cli.

Builds the board netlist from the exporter's pin-net tables (the same
source the schematic is generated from), computes the hand-routed
layout, and asserts the virtual DRC and the rule-10.1 isolation barrier
hold - plus that a deliberately smuggled primary trace on the secondary
side trips the barrier check.
"""

from __future__ import annotations

from collections import defaultdict

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.flyback import compose_flyback
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardNet,
    BoardNetlist,
    TrackSegment,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.export_flyback import INSTANCES
from pcbsmith.kicad.flyback_board import (
    BARRIER_X,
    ISOLATION_GAP_MM,
    PRIMARY_NETS,
    SECONDARY_NETS,
    STRADDLE_REFS,
    compute_flyback_board_layout,
)
from pcbsmith.kicad.virtual_drc import run_virtual_drc


def _netlist() -> BoardNetlist:
    intent = classify_circuit_intent("120 VAC to 3.3 V flyback converter")
    design = compose_flyback(intent, select_topology(intent))
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


def _spec() -> DesignChecksSpec:
    return DesignChecksSpec(
        isolation_barrier=(
            BARRIER_X,
            ISOLATION_GAP_MM,
            PRIMARY_NETS,
            SECONDARY_NETS,
            STRADDLE_REFS,
        ),
    )


def test_flyback_layout_is_virtual_drc_clean() -> None:
    netlist = _netlist()
    layout = compute_flyback_board_layout(netlist)
    assert run_virtual_drc(layout, netlist) == ()


def test_flyback_isolation_barrier_passes() -> None:
    netlist = _netlist()
    layout = compute_flyback_board_layout(netlist)
    report = run_design_checks(layout, netlist, _spec())
    assert "isolation_barrier" in report.checks_run
    assert not [f for f in report.findings if f.rule == "10.1"]


def test_flyback_isolation_barrier_catches_smuggled_primary_trace() -> None:
    netlist = _netlist()
    layout = compute_flyback_board_layout(netlist)
    smuggled = TrackSegment(
        x1=70.0, y1=20.0, x2=75.0, y2=20.0,
        layer="F.Cu", net_name="/HVP", width_mm=0.4,
    )
    poisoned = layout.__class__(
        **{
            **{
                field: getattr(layout, field)
                for field in layout.__dataclass_fields__
            },
            "segments": (*layout.segments, smuggled),
        }
    )
    report = run_design_checks(poisoned, netlist, _spec())
    violations = [f for f in report.findings if f.rule == "10.1"]
    assert violations, "a primary trace on the secondary side must trip 10.1"
    assert all(f.severity == "blocker" for f in violations)


def test_earth_clearance_catches_smuggled_earth_trace() -> None:
    from pcbsmith.kicad.flyback_board import PRIMARY_NETS

    netlist = _netlist()
    layout = compute_flyback_board_layout(netlist)
    smuggled = TrackSegment(
        x1=12.0, y1=8.0, x2=12.0, y2=12.0,
        layer="F.Cu", net_name="/EARTH", width_mm=0.4,
    )
    poisoned = layout.__class__(
        **{
            **{
                field: getattr(layout, field)
                for field in layout.__dataclass_fields__
            },
            "segments": (*layout.segments, smuggled),
        }
    )
    spec = DesignChecksSpec(
        net_group_clearances=(
            ("earth-to-primary clearance", ("/EARTH",), PRIMARY_NETS, 3.0,
             ("CY2", "CY3")),
        ),
    )
    report = run_design_checks(poisoned, netlist, spec)
    violations = [f for f in report.findings if f.rule == "10.4"]
    assert violations, "an earth trace beside the mains terminal must trip 10.4"

    clean_report = run_design_checks(layout, netlist, spec)
    assert not [f for f in clean_report.findings if f.rule == "10.4"]
