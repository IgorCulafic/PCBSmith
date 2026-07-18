"""Generate the bunny-shaped board using only discrete LEDs and resistors."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from generate_bunny_board import BunnyGeometry, extract_bunny_geometry
from shapely.geometry import Point as ShapePoint

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

LED_FOOTPRINT = "LED_SMD:LED_0603_1608Metric"
RESISTOR_FOOTPRINT = "Resistor_SMD:R_0603_1608Metric"
POWER_PAD_FOOTPRINT = "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm"
RESISTOR_VALUE = "330R"
PAIR_SPACING_MM = 3.0
POWER_ESCAPE_MM = 0.7
TRACK_WIDTH_MM = 0.25
Point = tuple[float, float]


@dataclass(frozen=True)
class PairSite:
    led: Point
    resistor: Point
    rotation: float
    direction: Point
    group: str


def _unit(vector: Point) -> Point:
    length = math.hypot(*vector)
    if length == 0:
        return (0.0, 1.0)
    return (vector[0] / length, vector[1] / length)


def _rotation(direction: Point) -> float:
    return round((-math.degrees(math.atan2(direction[1], direction[0]))) % 360.0, 2)


def pair_sites(geometry: BunnyGeometry) -> tuple[PairSite, ...]:
    sites: list[PairSite] = []
    board_center = (geometry.width_mm / 2, geometry.height_mm * 0.70)
    safe = geometry.polygon.buffer(-1.0)
    for group, points, _closed in geometry.groups:
        cx = sum(point[0] for point in points) / len(points)
        cy = sum(point[1] for point in points) / len(points)
        for point in points:
            if group == "perimeter":
                direction = _unit((board_center[0] - point[0], board_center[1] - point[1]))
            elif group in {"left_eye", "right_eye", "nose"}:
                direction = _unit((point[0] - cx, point[1] - cy))
            else:
                direction = (0.0, 1.0)
            resistor = (
                point[0] + direction[0] * PAIR_SPACING_MM,
                point[1] + direction[1] * PAIR_SPACING_MM,
            )
            escape = (
                resistor[0] + direction[0] * POWER_ESCAPE_MM,
                resistor[1] + direction[1] * POWER_ESCAPE_MM,
            )
            if not safe.covers(ShapePoint(resistor)) or not safe.covers(ShapePoint(escape)):
                direction = (-direction[0], -direction[1])
                resistor = (
                    point[0] + direction[0] * PAIR_SPACING_MM,
                    point[1] + direction[1] * PAIR_SPACING_MM,
                )
            sites.append(PairSite(point, resistor, _rotation(direction), direction, group))
    return tuple(sites)


def build_netlist(count: int) -> BoardNetlist:
    components: list[BoardComponent] = []
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for reference, value, net in (("P1", "+5V solder pad", "+5V"), ("P2", "GND solder pad", "GND")):
        components.append(
            BoardComponent(
                reference,
                value,
                POWER_PAD_FOOTPRINT,
                str(uuid5(NAMESPACE_URL, f"pcbsmith:bunny-simple:{reference}")),
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
                    str(uuid5(NAMESPACE_URL, f"pcbsmith:bunny-simple:{led}")),
                ),
                BoardComponent(
                    resistor,
                    RESISTOR_VALUE,
                    RESISTOR_FOOTPRINT,
                    str(uuid5(NAMESPACE_URL, f"pcbsmith:bunny-simple:{resistor}")),
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


def _back_text(text: str, at: Point, size: float = 0.9) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    return f'''  (gr_text "{text}"
    (at {at[0] + origin:.3f} {at[1] + origin:.3f} 0)
    (layer "B.SilkS")
    (uuid {uuid4()})
    (effects (font (size {size} {size}) (thickness 0.15)) (justify mirror))
  )'''


def compute_layout(
    geometry: BunnyGeometry, sites: tuple[PairSite, ...], netlist: BoardNetlist
) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    rotations: list[tuple[str, float]] = []
    hidden: list[str] = []
    router = Router()

    def place(reference: str, point: Point, rotation: float = 0.0) -> None:
        placements.append((by_ref[reference], round(point[0], 4)))
        part_y.append((reference, round(point[1], 4)))
        if rotation:
            rotations.append((reference, rotation))
        hidden.append(reference)

    for index, site in enumerate(sites, start=1):
        place(f"D{index}", site.led, site.rotation)
        place(f"R{index}", site.resistor, site.rotation)
        led_anode = placed_pad(LED_FOOTPRINT, "2", anchor=site.led, rotation=site.rotation)
        resistor_led = placed_pad(
            RESISTOR_FOOTPRINT, "1", anchor=site.resistor, rotation=site.rotation
        )
        router.path(
            f"/LED_{index:03d}", (led_anode, resistor_led), layer="F.Cu", width=TRACK_WIDTH_MM
        )

    pad_y = geometry.height_mm - 6.0
    place("P1", (43.0, pad_y))
    place("P2", (57.0, pad_y))
    graphics = (
        silk_text(
            "BUNNY LIGHT",
            (geometry.width_mm / 2, geometry.height_mm * 0.585),
            BOARD_SHEET_ORIGIN_MM,
            1.2,
        ),
        silk_text("+5V", (45.0, pad_y - 4.0), BOARD_SHEET_ORIGIN_MM, 1.0),
        silk_text("GND", (55.0, pad_y - 4.0), BOARD_SHEET_ORIGIN_MM, 1.0),
        _back_text(
            "P1 +5V   P2 GND   DISCRETE LED + RESISTOR ARRAY",
            (geometry.width_mm / 2, geometry.height_mm - 12.0),
        ),
    )
    base_layout = BoardLayout(
        placements=tuple(placements),
        segments=tuple(router.segments),
        vias=tuple(router.vias),
        width_mm=geometry.width_mm,
        height_mm=geometry.height_mm,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(rotations),
        zones=(),
        outline=geometry.outline,
        graphics=graphics,
        hide_references=tuple(hidden),
    )
    routed = route_board(
        base_layout,
        netlist,
        default_width_mm=0.3,
        net_widths={"/+5V": 0.5, "/GND": 0.5},
        net_order=("/+5V", "/GND"),
        skip_nets=tuple(f"/LED_{index:03d}" for index in range(1, len(sites) + 1)),
        max_restarts=16,
        grid_mm=0.2,
    )
    if routed.failed:
        raise BoardGenerationError("Explicit power routing failed: " + ", ".join(routed.failed))
    return routed.layout


def _write_bom(output_dir: Path, count: int) -> None:
    with (output_dir / "BOM.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("Quantity", "References", "Value", "Footprint"))
        writer.writerow((count, f"D1-D{count}", "LED", LED_FOOTPRINT))
        writer.writerow((count, f"R1-R{count}", RESISTOR_VALUE, RESISTOR_FOOTPRINT))


def generate(image_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    geometry = extract_bunny_geometry(image_path)
    sites = pair_sites(geometry)
    netlist = build_netlist(len(sites))
    layout = compute_layout(geometry, sites, netlist)
    board_file = output_dir / "bunny-led-resistor.kicad_pcb"
    project_file = output_dir / "bunny-led-resistor.kicad_pro"
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    project_file.write_text(_render_project(), encoding="utf-8")
    plot_board_review(
        netlist,
        output_dir / "bunny-led-resistor-review.png",
        power_net_names=frozenset({"+5V", "GND"}),
        layout=layout,
    )
    _write_bom(output_dir, len(sites))
    virtual = run_virtual_drc(layout, netlist)
    checks = run_design_checks(layout, netlist, DesignChecksSpec())
    authority = run_kicad_drc(board_file, schematic_parity=False)
    status: dict[str, Any] = {
        "board": str(board_file),
        "source_image": str(image_path),
        "board_width_mm": geometry.width_mm,
        "board_height_mm": geometry.height_mm,
        "led_count": len(sites),
        "resistor_count": len(sites),
        "populated_component_types": ["LED", "resistor"],
        "power_entry": "P1 +5V and P2 GND are bare PCB solder pads, not populated components",
        "perimeter_led_count": sum(site.group == "perimeter" for site in sites),
        "face_led_count": sum(site.group != "perimeter" for site in sites),
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
    parser.add_argument(
        "--image", type=Path, default=root / "demo-assets" / "bunny-head-source.png"
    )
    parser.add_argument(
        "--output", type=Path, default=root / "outputs" / "bunny-led-pcb-r002-simple"
    )
    args = parser.parse_args()
    status = generate(args.image.resolve(), args.output.resolve())
    print(json.dumps(status, indent=2))
    return 0 if status["kicad_drc_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
