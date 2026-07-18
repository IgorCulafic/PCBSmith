"""Flyback board r003: offline geometry checks without kicad-cli.

Builds the board netlist from the exporter's pin-net tables (the same
source the schematic is generated from), computes the automation-routed
dual-side layout, and asserts the virtual DRC and the rule-10.1
isolation barrier hold - plus that a deliberately smuggled primary
trace on the secondary side trips the barrier check. Routing takes
~20 s, so the routed layout is computed once per module.
"""

from __future__ import annotations

from collections import defaultdict
from functools import cache

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.flyback import compose_flyback
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.export_flyback import INSTANCES
from pcbsmith.kicad.flyback_board import compute_flyback_board_layout
from pcbsmith.kicad.virtual_drc import run_virtual_drc


@cache
def _routed() -> tuple[BoardNetlist, BoardLayout]:
    netlist = _netlist()
    return netlist, compute_flyback_board_layout(netlist)


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
    # THE spec: the same declaration the router keepouts and the CLI
    # authority use (flyback_board.flyback_checks_spec).
    from pcbsmith.kicad.flyback_board import flyback_checks_spec

    return flyback_checks_spec()


def test_flyback_layout_is_virtual_drc_clean() -> None:
    netlist, layout = _routed()
    assert run_virtual_drc(layout, netlist) == ()


def test_flyback_project_gap_and_barrier_side_review_pass() -> None:
    netlist, layout = _routed()
    report = run_design_checks(layout, netlist, _spec())
    assert "barrier_side_review" in report.checks_run
    assert not [
        finding
        for finding in report.findings
        if finding.rule in {"geometry.barrier_side", "10.4"}
    ]


def test_flyback_isolation_barrier_catches_smuggled_primary_trace() -> None:
    netlist, layout = _routed()
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
    side_reviews = [
        finding
        for finding in report.findings
        if finding.rule == "geometry.barrier_side"
    ]
    ordinary_violations = [
        finding for finding in report.findings if finding.rule == "10.4"
    ]
    assert side_reviews, "a primary trace on the right must trip side review"
    assert all(finding.severity == "warning" for finding in side_reviews)
    assert ordinary_violations, "the declared project gap remains enforced"
    assert all(finding.severity == "blocker" for finding in ordinary_violations)


def test_earth_clearance_catches_smuggled_earth_trace() -> None:
    from pcbsmith.kicad.flyback_board import PRIMARY_NETS

    netlist, layout = _routed()
    # Beside J1's mains pads (J1 sits at x=4.5 on the r003 floor plan).
    smuggled = TrackSegment(
        x1=7.5, y1=8.0, x2=7.5, y2=12.0,
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
