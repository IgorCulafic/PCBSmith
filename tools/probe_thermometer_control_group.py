"""Bounded negotiated probe for the full thermometer control trunk."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.probe_thermometer_negotiated import build_netlist, result_summary

from pcbsmith.kicad.board import render_board_from_layout
from pcbsmith.kicad.negotiated_board import route_board_negotiated
from pcbsmith.kicad.thermometer_board import _unrouted_layout
from pcbsmith.kicad.virtual_drc import run_virtual_drc

CONTROL_ORDER = ("/OE", "/SER", "/SRCLK", "/RCLK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expansions", type=int, default=600_000)
    args = parser.parse_args()
    netlist = build_netlist()
    result = route_board_negotiated(
        _unrouted_layout(netlist),
        netlist,
        target_nets=CONTROL_ORDER,
        net_widths={net: 0.2 for net in CONTROL_ORDER},
        net_order=CONTROL_ORDER,
        grid_mm=0.2,
        default_width_mm=0.25,
        max_passes=16,
        max_stagnant_passes=8,
        max_expansions=args.expansions,
        max_expansions_per_net=250_000,
    )
    summary = result_summary(result)
    summary["virtual_drc"] = tuple(
        finding.as_dict()
        for finding in run_virtual_drc(result.layout, netlist)
        if finding.check != "pad_connectivity"
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    if result.run_result.success and args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            render_board_from_layout(netlist, result.layout), encoding="utf-8"
        )
    return 0 if result.run_result.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
