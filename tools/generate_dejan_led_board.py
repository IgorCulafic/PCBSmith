"""Generate a two-sided LED sign spelling Dejan."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pcbsmith.kicad.astar_router import route_board
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    render_board_from_layout,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.export_divider_highpass_led import _render_project
from pcbsmith.kicad.preview import plot_board_review
from pcbsmith.kicad.shaped_board import Router, placed_pad, silk_text
from pcbsmith.kicad.validate import run_kicad_drc
from pcbsmith.kicad.virtual_drc import run_virtual_drc

LED_FOOTPRINT = "LED_SMD:LED_0805_2012Metric"
RESISTOR_FOOTPRINT = "Resistor_SMD:R_0603_1608Metric"
POWER_PAD_FOOTPRINT = "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm"
RESISTOR_VALUE = "330R"
BOARD_WIDTH_MM = 125.0
BOARD_HEIGHT_MM = 40.0
GRID_PITCH_MM = 4.0
GRID_ORIGIN = (6.5, 6.0)
SERIES_VIA_OFFSET_MM = 1.75
TRACK_WIDTH_MM = 0.25
POWER_WIDTH_MM = 0.5

LETTER_ROWS = (
    "11110.00000.00010.00000.00000",
    "10001.00000.00000.00000.00000",
    "10001.01110.00010.01110.11110",
    "10001.10001.00010.00001.10001",
    "10001.11111.00010.01111.10001",
    "10001.10000.00010.10001.10001",
    "11110.01111.10010.01111.10001",
    "00000.00000.01100.00000.00000",
)
Point = tuple[float, float]


def led_points() -> tuple[Point, ...]:
    points: list[Point] = []
    for row, pattern in enumerate(LETTER_ROWS):
        column = 0
        for character in pattern:
            if character == ".":
                continue
            if character == "1":
                points.append(
                    (
                        GRID_ORIGIN[0] + column * GRID_PITCH_MM,
                        GRID_ORIGIN[1] + row * GRID_PITCH_MM,
                    )
                )
            column += 1
    return tuple(points)


def build_netlist(count: int) -> BoardNetlist:
    components: list[BoardComponent] = []
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for reference, value, net in (
        ("P1", "+5V solder pad", "+5V"),
        ("P2", "GND solder pad", "GND"),
    ):
        components.append(
            BoardComponent(
                reference,
                value,
                POWER_PAD_FOOTPRINT,
                str(uuid5(NAMESPACE_URL, f"pcbsmith:dejan:{reference}")),
            )
        )
        nodes[net].append((reference, "1"))
    for index in range(1, count + 1):
        led = f"D{index}"
        resistor = f"R{index}"
        series = f"LED_{index:03d}"
        components.extend(
            (
                BoardComponent(
                    led,
                    "LED",
                    LED_FOOTPRINT,
                    str(uuid5(NAMESPACE_URL, f"pcbsmith:dejan:{led}")),
                ),
                BoardComponent(
                    resistor,
                    RESISTOR_VALUE,
                    RESISTOR_FOOTPRINT,
                    str(uuid5(NAMESPACE_URL, f"pcbsmith:dejan:{resistor}")),
                ),
            )
        )
        nodes["GND"].append((led, "1"))
        nodes[series].extend(((led, "2"), (resistor, "1")))
        nodes["+5V"].append((resistor, "2"))
    return BoardNetlist(
        tuple(components),
        tuple(BoardNet(f"/{name}", tuple(net_nodes)) for name, net_nodes in sorted(nodes.items())),
    )


def compute_layout(points: tuple[Point, ...], netlist: BoardNetlist) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    flipped: list[str] = []
    hidden: list[str] = []
    router = Router()

    def place(reference: str, point: Point, *, back: bool = False) -> None:
        placements.append((by_ref[reference], point[0]))
        part_y.append((reference, point[1]))
        hidden.append(reference)
        if back:
            flipped.append(reference)

    for index, point in enumerate(points, start=1):
        led_ref = f"D{index}"
        resistor_ref = f"R{index}"
        place(led_ref, point)
        place(resistor_ref, point, back=True)
        led_anode = placed_pad(LED_FOOTPRINT, "2", anchor=point)
        resistor_series = placed_pad(RESISTOR_FOOTPRINT, "1", anchor=point, flipped=True)
        via = (point[0] + SERIES_VIA_OFFSET_MM, point[1])
        net = f"/LED_{index:03d}"
        router.path(net, (led_anode, via), layer="F.Cu", width=TRACK_WIDTH_MM)
        router.path(net, (resistor_series, via), layer="B.Cu", width=TRACK_WIDTH_MM)
        router.via(net, *via)

    place("P1", (2.5, 13.5))
    place("P2", (2.5, 26.5))
    graphics = (
        silk_text("+5V", (2.5, 9.5), BOARD_SHEET_ORIGIN_MM, 0.8),
        silk_text("GND", (2.5, 30.5), BOARD_SHEET_ORIGIN_MM, 0.8),
        silk_text(
            "DEJAN", (BOARD_WIDTH_MM - 9.0, BOARD_HEIGHT_MM - 3.0), BOARD_SHEET_ORIGIN_MM, 0.8
        ),
    )
    base_layout = BoardLayout(
        placements=tuple(placements),
        segments=tuple(router.segments),
        vias=tuple(router.vias),
        width_mm=BOARD_WIDTH_MM,
        height_mm=BOARD_HEIGHT_MM,
        part_y_mm=tuple(part_y),
        zones=(),
        graphics=graphics,
        part_flip=tuple(flipped),
        hide_references=tuple(hidden),
    )
    routed = route_board(
        base_layout,
        netlist,
        default_width_mm=0.3,
        net_widths={"/+5V": POWER_WIDTH_MM, "/GND": POWER_WIDTH_MM},
        net_order=("/+5V", "/GND"),
        skip_nets=tuple(f"/LED_{index:03d}" for index in range(1, len(points) + 1)),
        max_restarts=20,
        grid_mm=0.2,
    )
    if routed.failed:
        raise BoardGenerationError("Dejan power routing failed: " + ", ".join(routed.failed))
    return routed.layout


def _write_bom(output_dir: Path, count: int) -> None:
    with (output_dir / "BOM.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("Quantity", "References", "Value", "Footprint", "Side"))
        writer.writerow((count, f"D1-D{count}", "LED", LED_FOOTPRINT, "Front"))
        writer.writerow((count, f"R1-R{count}", RESISTOR_VALUE, RESISTOR_FOOTPRINT, "Back"))


def generate(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    points = led_points()
    netlist = build_netlist(len(points))
    layout = compute_layout(points, netlist)
    board_file = output_dir / "dejan-led.kicad_pcb"
    project_file = output_dir / "dejan-led.kicad_pro"
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    project_file.write_text(_render_project(), encoding="utf-8")
    plot_board_review(
        netlist,
        output_dir / "dejan-led-review.png",
        power_net_names=frozenset({"+5V", "GND"}),
        layout=layout,
    )
    _write_bom(output_dir, len(points))
    virtual = run_virtual_drc(layout, netlist)
    checks = run_design_checks(layout, netlist, DesignChecksSpec())
    authority = run_kicad_drc(board_file, schematic_parity=False)
    status: dict[str, Any] = {
        "board": str(board_file),
        "board_width_mm": BOARD_WIDTH_MM,
        "board_height_mm": BOARD_HEIGHT_MM,
        "text": "Dejan",
        "led_count": len(points),
        "front_led_count": len(points),
        "resistor_count": len(points),
        "back_resistor_count": len(points),
        "copper_zones": 0,
        "virtual_drc": [finding.as_dict() for finding in virtual],
        "design_check_status": checks.status,
        "design_check_findings": [finding.model_dump() for finding in checks.findings],
        "kicad_drc_status": authority.status,
        "kicad_drc_findings": list(authority.findings),
    }
    (output_dir / "verification.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=root / "outputs" / "dejan-led-pcb-r001")
    args = parser.parse_args()
    status = generate(args.output.resolve())
    print(json.dumps(status, indent=2))
    return 0 if status["kicad_drc_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
