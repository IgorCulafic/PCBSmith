"""Generate a bunny-shaped addressable-LED art-board prototype.

The source silhouette becomes Edge.Cuts. WS2812B-2020 LEDs follow an inward
perimeter and draw the eyes, nose, and mouth. Each LED has a back-side 100 nF
capacitor; +5 V and GND use opposite-side pours. The board is intentionally a
prototype artifact rather than a registered PCBSmith topology.
"""

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

import cv2
from shapely.geometry import MultiPolygon, Polygon
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

LED_FOOTPRINT = "LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm"
CAP_FOOTPRINT = "Capacitor_SMD:C_0805_2012Metric"
CONNECTOR_FOOTPRINT = "Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal"
BOARD_WIDTH_MM = 100.0
IMAGE_MARGIN_MM = 3.0
PERIMETER_INSET_MM = 5.5
PERIMETER_PITCH_MM = 11.5
SIGNAL_WIDTH_MM = 0.20
POWER_STUB_WIDTH_MM = 0.30
VIA_ESCAPE_MM = 0.60
CAP_INSET_MM = 2.8
Point = tuple[float, float]


@dataclass(frozen=True)
class LedSite:
    point: Point
    rotation: float
    group: str


@dataclass(frozen=True)
class BunnyGeometry:
    outline: tuple[Point, ...]
    polygon: Polygon
    width_mm: float
    height_mm: float
    groups: tuple[tuple[str, tuple[Point, ...], bool], ...]


def _largest_polygon(shape: Polygon | MultiPolygon) -> Polygon:
    if isinstance(shape, Polygon):
        return shape
    if not shape.geoms:
        raise ValueError("The silhouette did not produce a usable polygon.")
    return max(shape.geoms, key=lambda item: item.area)


def _ellipse(center: Point, rx: float, ry: float, count: int) -> tuple[Point, ...]:
    return tuple(
        (
            center[0] + rx * math.cos(2 * math.pi * index / count),
            center[1] + ry * math.sin(2 * math.pi * index / count),
        )
        for index in range(count)
    )


def _quadratic_bezier(a: Point, control: Point, b: Point, count: int) -> list[Point]:
    result: list[Point] = []
    for index in range(count):
        t = index / (count - 1)
        u = 1.0 - t
        result.append(
            (
                u * u * a[0] + 2 * u * t * control[0] + t * t * b[0],
                u * u * a[1] + 2 * u * t * control[1] + t * t * b[1],
            )
        )
    return result


def extract_bunny_geometry(image_path: Path) -> BunnyGeometry:
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(image_path)
    _threshold, mask = cv2.threshold(image, 127, 255, cv2.THRESH_BINARY_INV)
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError(f"No silhouette found in {image_path}.")
    contour = max(contours, key=cv2.contourArea)
    raw = [(float(point[0][0]), float(point[0][1])) for point in contour]
    source = _largest_polygon(Polygon(raw).buffer(0))
    min_x, min_y, max_x, _max_y = source.bounds
    scale = (BOARD_WIDTH_MM - 2 * IMAGE_MARGIN_MM) / (max_x - min_x)
    scaled = Polygon(
        [
            (
                (x - min_x) * scale + IMAGE_MARGIN_MM,
                (y - min_y) * scale + IMAGE_MARGIN_MM,
            )
            for x, y in source.exterior.coords
        ]
    ).simplify(0.12, preserve_topology=True)
    scaled = _largest_polygon(scaled.buffer(0))
    height_mm = float(math.ceil(scaled.bounds[3] + IMAGE_MARGIN_MM))
    outline = tuple((round(x, 3), round(y, 3)) for x, y in list(scaled.exterior.coords)[:-1])

    inner = _largest_polygon(scaled.buffer(-PERIMETER_INSET_MM, join_style=1))
    ring = inner.exterior
    count = max(24, round(ring.length / PERIMETER_PITCH_MM))
    perimeter = [
        (point.x, point.y)
        for point in (
            ring.interpolate((index + 0.5) * ring.length / count) for index in range(count)
        )
    ]
    start = min(
        range(len(perimeter)),
        key=lambda index: math.dist(
            perimeter[index], (BOARD_WIDTH_MM / 2, height_mm - PERIMETER_INSET_MM)
        ),
    )
    perimeter = perimeter[start:] + perimeter[:start]
    if perimeter[1][0] > perimeter[0][0]:
        perimeter = [perimeter[0], *reversed(perimeter[1:])]

    head_y = height_mm * 0.72
    left_eye = _ellipse((34.0, head_y - 3.0), 8.0, 5.5, 8)
    right_eye = _ellipse((66.0, head_y - 3.0), 8.0, 5.5, 8)
    nose = ((50.0, head_y + 6.0), (45.5, head_y + 11.0), (54.5, head_y + 11.0))
    mouth = tuple(
        _quadratic_bezier(
            (38.0, head_y + 19.0),
            (44.0, head_y + 25.0),
            (50.0, head_y + 18.0),
            4,
        )[:-1]
        + _quadratic_bezier(
            (50.0, head_y + 18.0),
            (56.0, head_y + 25.0),
            (62.0, head_y + 19.0),
            4,
        )
    )
    groups = (
        ("perimeter", tuple(perimeter), True),
        ("mouth", mouth, False),
        ("nose", nose, True),
        ("left_eye", left_eye, True),
        ("right_eye", right_eye, True),
    )
    safe = scaled.buffer(-1.5)
    for name, points, _closed in groups:
        if any(not safe.covers(ShapePoint(point)) for point in points):
            raise ValueError(f"The {name} LED pattern does not fit inside the board.")
    return BunnyGeometry(outline, scaled, BOARD_WIDTH_MM, height_mm, groups)


def _unit(vector: Point) -> Point:
    length = math.hypot(*vector)
    return (0.0, 0.0) if length == 0 else (vector[0] / length, vector[1] / length)


def _rotation_for_tangent(tangent: Point) -> float:
    tx, ty = -tangent[0], -tangent[1]
    return round((-math.degrees(math.atan2(ty, tx))) % 360.0, 2)


def led_sites(geometry: BunnyGeometry) -> tuple[LedSite, ...]:
    sites: list[LedSite] = []
    for group_name, points, closed in geometry.groups:
        for index, point in enumerate(points):
            if closed:
                previous = points[(index - 1) % len(points)]
                following = points[(index + 1) % len(points)]
            elif index == 0:
                previous, following = point, points[1]
            elif index == len(points) - 1:
                previous, following = points[-2], point
            else:
                previous, following = points[index - 1], points[index + 1]
            tangent = _unit((following[0] - previous[0], following[1] - previous[1]))
            sites.append(
                LedSite(
                    (round(point[0], 4), round(point[1], 4)),
                    _rotation_for_tangent(tangent),
                    group_name,
                )
            )
    return tuple(sites)


def build_netlist(site_count: int) -> BoardNetlist:
    components = [
        BoardComponent(
            "J1",
            "JST-SH 5V/GND/DIN/DOUT",
            CONNECTOR_FOOTPRINT,
            str(uuid5(NAMESPACE_URL, "pcbsmith:bunny:J1")),
        ),
        BoardComponent(
            "C1",
            "10u bulk",
            CAP_FOOTPRINT,
            str(uuid5(NAMESPACE_URL, "pcbsmith:bunny:C1")),
        ),
    ]
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for name, pin in (("+5V", "1"), ("GND", "2"), ("DIN", "3"), ("DOUT", "4")):
        nodes[name].append(("J1", pin))
    nodes["+5V"].append(("C1", "1"))
    nodes["GND"].append(("C1", "2"))
    for index in range(1, site_count + 1):
        reference = f"D{index}"
        components.append(
            BoardComponent(
                reference,
                "WS2812B-2020",
                LED_FOOTPRINT,
                str(uuid5(NAMESPACE_URL, f"pcbsmith:bunny:{reference}")),
            )
        )
        nodes["+5V"].append((reference, "4"))
        nodes["GND"].append((reference, "2"))
        if index == 1:
            nodes["DIN"].append(("D1", "3"))
        else:
            nodes[f"DATA_{index - 1:03d}"].extend(((f"D{index - 1}", "1"), (reference, "3")))
        if index == site_count:
            nodes["DOUT"].append((reference, "1"))
    return BoardNetlist(
        tuple(components),
        tuple(BoardNet(f"/{name}", tuple(net_nodes)) for name, net_nodes in sorted(nodes.items())),
    )


def _move_toward(point: Point, target: Point, distance: float) -> Point:
    direction = _unit((target[0] - point[0], target[1] - point[1]))
    return (point[0] + direction[0] * distance, point[1] + direction[1] * distance)


def _escape_from(anchor: Point, pad: Point, distance: float) -> Point:
    direction = _unit((pad[0] - anchor[0], pad[1] - anchor[1]))
    return (pad[0] + direction[0] * distance, pad[1] + direction[1] * distance)


def _back_silk_text(text: str, at: Point, size: float = 0.8) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    return f"""  (gr_text \"{text}\"
    (at {at[0] + origin:.3f} {at[1] + origin:.3f} 0)
    (layer \"B.SilkS\")
    (uuid {uuid4()})
    (effects
      (font (size {size} {size}) (thickness {size * 0.18:.2f}))
      (justify mirror)
    )
  )"""


def compute_layout(
    geometry: BunnyGeometry, sites: tuple[LedSite, ...], netlist: BoardNetlist
) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    rotations: list[tuple[str, float]] = []
    flipped: list[str] = []
    hidden: list[str] = []
    router = Router()

    def place(reference: str, point: Point, rotation: float, *, back: bool = False) -> None:
        placements.append((by_ref[reference], round(point[0], 4)))
        part_y.append((reference, round(point[1], 4)))
        if rotation:
            rotations.append((reference, rotation))
        if back:
            flipped.append(reference)
        hidden.append(reference)

    for index, site in enumerate(sites, start=1):
        place(f"D{index}", site.point, site.rotation)

    bulk_cap_anchor = (50.0, geometry.height_mm - 12.0)
    place("C1", bulk_cap_anchor, 0.0, back=True)
    connector_anchor = (50.0, geometry.height_mm - 7.0)
    place("J1", connector_anchor, 180.0, back=True)

    for site in sites:
        gnd_pad = placed_pad(LED_FOOTPRINT, "2", anchor=site.point, rotation=site.rotation)
        vdd_pad = placed_pad(LED_FOOTPRINT, "4", anchor=site.point, rotation=site.rotation)
        ground_normal = _unit((gnd_pad[0] - vdd_pad[0], gnd_pad[1] - vdd_pad[1]))
        gnd_via = (
            gnd_pad[0] + ground_normal[0] * VIA_ESCAPE_MM,
            gnd_pad[1] + ground_normal[1] * VIA_ESCAPE_MM,
        )
        router.path("/GND", (gnd_pad, gnd_via), layer="F.Cu", width=POWER_STUB_WIDTH_MM)
        router.via("/GND", *gnd_via)
    connector_pads = {
        pin: placed_pad(
            CONNECTOR_FOOTPRINT,
            pin,
            anchor=connector_anchor,
            rotation=180.0,
            flipped=True,
        )
        for pin in ("1", "2", "3", "4")
    }
    connector_gnd_via = (
        connector_pads["2"][0],
        connector_pads["2"][1] - 1.5,
    )
    router.path(
        "/GND",
        (connector_pads["2"], connector_gnd_via),
        layer="B.Cu",
        width=0.5,
    )
    router.via("/GND", *connector_gnd_via)
    graphics = (
        silk_text(
            "BUNNY LIGHT",
            (geometry.width_mm / 2, geometry.height_mm * 0.59),
            BOARD_SHEET_ORIGIN_MM,
            1.1,
        ),
        _back_silk_text(
            "J1: 1 +5V   2 GND   3 DIN   4 DOUT",
            (geometry.width_mm / 2, geometry.height_mm - 18.0),
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
        zones=(
            (
                "/GND",
                "F.Cu",
                (1.0, 1.0, geometry.width_mm - 1.0, geometry.height_mm - 1.0),
            ),
            (
                "/GND",
                "B.Cu",
                (1.0, 1.0, geometry.width_mm - 1.0, geometry.height_mm - 1.0),
            ),
        ),
        outline=geometry.outline,
        graphics=graphics,
        part_flip=tuple(flipped),
        hide_references=tuple(hidden),
    )
    routed = route_board(
        base_layout,
        netlist,
        default_width_mm=SIGNAL_WIDTH_MM,
        net_widths={"/+5V": 0.3},
        net_order=("/+5V",),
        skip_nets=("/GND",),
        max_restarts=12,
        grid_mm=0.2,
    )
    if routed.failed:
        raise BoardGenerationError("Bunny data routing failed on: " + ", ".join(routed.failed))
    return routed.layout


def _write_bom(output_dir: Path, site_count: int) -> None:
    with (output_dir / "BOM.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("Quantity", "References", "Value", "Footprint", "Notes"))
        writer.writerow(
            (
                site_count,
                f"D1-D{site_count}",
                "WS2812B-2020",
                LED_FOOTPRINT,
                "DO/GND/DI/VDD = pins 1/2/3/4",
            )
        )
        writer.writerow((1, "C1", "10u bulk", CAP_FOOTPRINT, "Back-side input bulk capacitor"))
        writer.writerow(
            (
                1,
                "J1",
                "JST-SH 1x04",
                CONNECTOR_FOOTPRINT,
                "1:+5V 2:GND 3:DIN 4:DOUT; back side",
            )
        )


def generate(image_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    geometry = extract_bunny_geometry(image_path)
    sites = led_sites(geometry)
    netlist = build_netlist(len(sites))
    layout = compute_layout(geometry, sites, netlist)
    board_file = output_dir / "bunny-led.kicad_pcb"
    project_file = output_dir / "bunny-led.kicad_pro"
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    project_file.write_text(_render_project(), encoding="utf-8")
    plot_board_review(
        netlist,
        output_dir / "bunny-led-review.png",
        power_net_names=frozenset({"+5V", "GND"}),
        layout=layout,
    )
    _write_bom(output_dir, len(sites))

    virtual = run_virtual_drc(layout, netlist)
    review = run_design_checks(
        layout,
        netlist,
        DesignChecksSpec(allowed_unconnected_pins=(("J1", "MP"),)),
    )
    authority = run_kicad_drc(board_file, schematic_parity=False)
    status: dict[str, Any] = {
        "board": str(board_file),
        "source_image": str(image_path),
        "board_width_mm": geometry.width_mm,
        "board_height_mm": geometry.height_mm,
        "outline_vertices": len(geometry.outline),
        "led_count": len(sites),
        "capacitor_count": 1,
        "perimeter_led_count": sum(site.group == "perimeter" for site in sites),
        "face_led_count": sum(site.group != "perimeter" for site in sites),
        "estimated_full_white_current_a": round(len(sites) * 0.012, 3),
        "virtual_drc": [finding.as_dict() for finding in virtual],
        "design_check_status": review.status,
        "design_check_findings": [finding.model_dump() for finding in review.findings],
        "kicad_drc_status": authority.status,
        "kicad_drc_findings": list(authority.findings),
        "notes": [
            "Board-only prototype: no schematic/ERC or schematic-parity gate is included.",
            "Use a regulated 5 V supply.",
            "Only bulk decoupling is fitted; add local LED decouplers before production.",
            "Black solder mask and white silkscreen are recommended.",
            "Human review remains required before fabrication.",
        ],
    }
    (output_dir / "verification.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image", type=Path, default=root / "demo-assets" / "bunny-head-source.png"
    )
    parser.add_argument("--output", type=Path, default=root / "outputs" / "bunny-led-pcb-r001")
    args = parser.parse_args()
    status = generate(args.image.resolve(), args.output.resolve())
    print(json.dumps(status, indent=2))
    return 0 if status["kicad_drc_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
