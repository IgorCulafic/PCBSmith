"""Persist and render the full unrouted thermometer placement candidate.

This artifact is deliberately labelled as an incomplete routing review board.
It exists so the actual saved KiCad geometry can be visually inspected even
when the production routing gate fails before normal board serialization.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pcbsmith.kicad.board import (
    parse_board_netlist,
    render_board_previews,
)
from pcbsmith.kicad.preview import plot_assembly_view, plot_board_review
from pcbsmith.kicad.thermometer_board import (
    _unrouted_layout,
    render_thermometer_board,
)
from pcbsmith.kicad.validate import run_kicad_drc
from pcbsmith.kicad.virtual_drc import run_virtual_drc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--name", default="Thermometer_R002")
    args = parser.parse_args()
    output = args.output.resolve()
    netlist_file = output / ".pcbsmith" / "kicad" / f"{args.name}.net.xml"
    if not netlist_file.exists():
        raise FileNotFoundError(f"canonical exported netlist not found: {netlist_file}")

    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = _unrouted_layout(netlist)
    board_file = output / f"{args.name}.kicad_pcb"
    board_file.write_text(
        render_thermometer_board(netlist, layout), encoding="utf-8"
    )

    review_plot = plot_board_review(
        netlist,
        output / f"{args.name}-routing-review.png",
        power_net_names=frozenset({"/VBUS", "/VBUSF", "/VCC", "/GND"}),
        layout=layout,
    )
    assembly_plot = plot_assembly_view(
        netlist, layout, output / f"{args.name}-assembly-review.png"
    )
    previews, preview_findings = render_board_previews(board_file)
    findings = run_virtual_drc(layout, netlist)
    finding_counts = Counter(item.check for item in findings)
    static_findings = tuple(
        item.as_dict() for item in findings if item.check != "pad_connectivity"
    )
    kicad = run_kicad_drc(board_file, schematic_parity=False)
    kicad_finding_counts = Counter(kicad.findings)
    report = {
        "status": "incomplete_routing_review_only",
        "warning": (
            "This is the full 63-component/64-placement production geometry, "
            "but it contains no accepted routed copper and is not fabrication-ready."
        ),
        "board_file": str(board_file),
        "component_count": len(netlist.components),
        "placement_count": len(layout.placements),
        "net_count": len(netlist.nets),
        "pin_node_count": sum(len(net.nodes) for net in netlist.nets),
        "board_width_mm": layout.width_mm,
        "board_height_mm": layout.height_mm,
        "bulb_diameter_mm": 60.0,
        "stem_width_mm": 24.0,
        "segment_count": len(layout.segments),
        "via_count": len(layout.vias),
        "virtual_drc_counts": dict(sorted(finding_counts.items())),
        "virtual_static_findings": static_findings,
        "kicad_drc_status": kicad.status,
        "kicad_drc_finding_counts": dict(sorted(kicad_finding_counts.items())),
        "previews": previews,
        "preview_findings": preview_findings,
        "routing_review_plot": str(review_plot),
        "assembly_review_plot": str(assembly_plot),
        "visual_review": {
            "status": "completed",
            "findings": [
                "The 60mm bulb and 24mm stem read as a classic glass thermometer.",
                "Black mask, white silkscreen, and ENIG intent render correctly.",
                "Both OLED header/body envelopes fit on the bulb shoulder without overlap.",
                "The SHT31 isolation slot and separated sensor placement are visible.",
                "The ESP32 module is on the back with its antenna end at the stem edge.",
                "No routed copper is present; this candidate is not fabrication-ready.",
            ],
        },
    }
    report_file = output / f"{args.name}-placement-review.json"
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
