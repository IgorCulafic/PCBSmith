"""Bounded deterministic feasibility probe for the full thermometer board.

This developer tool intentionally stops short of claiming authority.  It runs
the production thermometer input through the negotiated router in the same
fine/main grid split as the legacy caller and prints replayable telemetry.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.thermometer import compose_thermometer
from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist, render_board_from_layout
from pcbsmith.kicad.export_thermometer import INSTANCES
from pcbsmith.kicad.negotiated_board import route_board_negotiated
from pcbsmith.kicad.thermometer_board import (
    FINE_PITCH_NETS,
    LED_COUNT,
    SIG_W,
    _unrouted_layout,
)
from pcbsmith.kicad.virtual_drc import run_virtual_drc

REQUEST = "thermometer temperature humidity display pcb"
CONTROL_ORDER = ("/OE", "/SER", "/SRCLK", "/RCLK")


def build_netlist() -> BoardNetlist:
    intent = classify_circuit_intent(REQUEST)
    design = compose_thermometer(intent, select_topology(intent))
    footprints = {item.reference: item.footprint for item in design.components}
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
                uuid_path=f"probe-{reference}",
            )
            for reference, footprint in footprints.items()
        ),
        nets=tuple(
            BoardNet(name=f"/{name}", nodes=tuple(pins))
            for name, pins in sorted(nodes.items())
        ),
    )


def result_summary(result: object) -> dict[str, object]:
    run = result.run_result  # type: ignore[attr-defined]
    return {
        "success": run.success,
        "failure_reason": None if run.failure_reason is None else run.failure_reason.value,
        "unresolved": run.unresolved_net_names,
        "overuse": tuple(
            (item.resource_kind.value, item.resource_id, item.overuse_units)
            for item in run.resource_overuse
        ),
        "pass_count": len(run.passes),
        "expansions": sum(item.expansion_count for item in run.passes),
        "fingerprint": run.semantic_fingerprint(),
        "segments": len(result.layout.segments),  # type: ignore[attr-defined]
        "vias": len(result.layout.vias),  # type: ignore[attr-defined]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fine-expansions", type=int, default=3_000_000)
    parser.add_argument("--main-expansions", type=int, default=6_000_000)
    args = parser.parse_args()

    netlist = build_netlist()
    base = _unrouted_layout(netlist)
    widths = {
        **FINE_PITCH_NETS,
        **{f"/SEG{index}": 0.2 for index in range(1, LED_COUNT + 1)},
        "/SER": 0.2,
        "/SRCLK": 0.2,
        "/RCLK": 0.2,
        "/OE": 0.2,
    }
    # The global rails are fine-pitch at a handful of endpoints but are
    # also the board's two largest multi-terminal trees.  Routing those
    # trees on the 0.1mm graph is needlessly quadratic (and was observed
    # to exhaust memory).  Keep the pad-pinned local signals on the fine
    # graph and route the rails once on the main graph.
    fine_order = tuple(
        net for net in FINE_PITCH_NETS if net not in ("/VCC", "/GND")
    )
    fine = route_board_negotiated(
        base,
        netlist,
        target_nets=fine_order,
        net_widths=widths,
        net_order=fine_order,
        grid_mm=0.1,
        default_width_mm=SIG_W,
        max_passes=16,
        max_stagnant_passes=8,
        max_expansions=args.fine_expansions,
        max_expansions_per_net=1_000_000,
    )
    output: dict[str, object] = {"fine": result_summary(fine)}
    print(json.dumps(output, sort_keys=True), flush=True)
    if not fine.run_result.success:
        return 2

    remaining = tuple(
        name
        for name in (
            *CONTROL_ORDER,
            *(net.name for net in netlist.nets),
        )
        if name not in fine_order
    )
    remaining = tuple(dict.fromkeys(remaining))
    main_result = route_board_negotiated(
        fine.layout,
        netlist,
        target_nets=remaining,
        net_widths=widths,
        net_order=remaining,
        grid_mm=0.2,
        default_width_mm=SIG_W,
        max_passes=24,
        max_stagnant_passes=10,
        max_expansions=args.main_expansions,
        max_expansions_per_net=1_000_000,
    )
    output["main"] = result_summary(main_result)
    if main_result.run_result.success:
        # route_board_negotiated retains pre-existing copper, so the main
        # result already contains the fine stage exactly once.
        final_layout = main_result.layout
        findings = run_virtual_drc(final_layout, netlist)
        output["virtual_drc"] = tuple(item.as_dict() for item in findings)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                render_board_from_layout(netlist, final_layout),
                encoding="utf-8",
            )
    print(json.dumps(output, sort_keys=True), flush=True)
    return 0 if main_result.run_result.success else 3


if __name__ == "__main__":
    raise SystemExit(main())
