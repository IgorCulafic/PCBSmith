"""Metal detector paddle: the exposed spiral trace IS the sensing inductor.

Board = a circular coil head plus a handle tab carrying a common-base
Colpitts oscillator. The tank inductor is a 20-turn archimedean spiral of
front-copper traces, exposed through a soldermask opening (the user's
"exposed traces as the detector"). Metal near the coil lowers its
inductance via eddy currents and shifts the oscillation frequency at FOUT.

Electrical topology of the coil: the whole spiral, its centre via, and the
back return trace are ONE conductor on the collector net; a net-tie
footprint (L1) joins the return end to VCC, which is how KiCad represents
a component that physically exists only as copper.

Layout rule (recorded in docs/pcb-design-rules.md 9.1): no copper pour or
plane under the coil - only the single thin return trace crosses it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import uuid4

from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    export_kicad_netlist_xml,
    parse_board_netlist,
    render_board_from_layout,
    rotate_offset,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.clover_board import _Router
from pcbsmith.kicad.pear_board import _silk_text

# Coil head and handle (board coords, y down).
COIL_CENTER = (40.0, 50.0)
HEAD_RADIUS = 36.0
HANDLE_HALF_WIDTH = 10.0
HANDLE_END_Y = 3.0
BOARD_W = 80.0
BOARD_H = 90.0

# The sensing spiral: geometry is the single source of truth; the
# composition derives inductance and frequency from these constants.
SPIRAL_OUTER_RADIUS = 31.0
SPIRAL_TURNS = 20
SPIRAL_PITCH = 1.0  # mm per turn: 0.5 trace + 0.5 gap
SPIRAL_TRACE_W = 0.5
MASK_OPENING_RADIUS = 32.2

SIGNAL_W = 0.3
POWER_W = 0.5

P1_AT = (40.0, 5.4)
P1_PIN_NETS = ("VCC", "GND", "FOUT")

# Handle placements (reference: (x, y, rotation)). Front-side rotation 270
# puts pad 1 of a two-pin part on TOP; 90 puts it on the bottom; 180 puts
# it east. Pad positions are always computed from the library, never
# assumed (pear-board lesson).
PLACEMENTS = {
    "P1": (40.0, 5.4, 0.0),
    "Q1": (36.9, 13.6, 0.0),   # B west-top, E west-bottom, C east
    "R1": (34.2, 7.0, 270.0),  # pin1 VCC top, pin2 BASE bottom
    "R2": (34.2, 10.4, 270.0),  # pin1 BASE top, pin2 GND bottom
    "C5": (36.4, 10.4, 270.0),  # base bypass: pin1 BASE top, pin2 GND bottom
    "C1": (42.0, 16.2, 0.0),   # tank: pin1 COL west, pin2 EM east
    "C2": (35.2, 16.2, 180.0),  # tank: pin1 EM east, pin2 GND west
    "R3": (38.6, 16.2, 0.0),   # emitter: pin1 EM west, pin2 GND east
    "C3": (43.0, 13.0, 90.0),  # coupling: pin1 COL bottom, pin2 FO_A top
    "R4": (44.9, 10.4, 90.0),  # series out: pin1 FO_A bottom, pin2 FOUT top
    "C4": (43.4, 5.4, 0.0),    # decouple: pin1 VCC west, pin2 GND east
    "L1": (31.9, 14.6, 270.0),  # net tie: pin1 VCC top, pin2 COL bottom
}


def handle_join_y() -> float:
    return COIL_CENTER[1] - math.sqrt(HEAD_RADIUS**2 - HANDLE_HALF_WIDTH**2)


def detector_outline() -> tuple[tuple[float, float], ...]:
    """Circle head plus the handle tab, spliced like the clover stem."""
    cx, cy = COIL_CENTER
    join_y = handle_join_y()
    points: list[tuple[float, float]] = []
    steps = 240
    for step in range(steps):
        theta = 2 * math.pi * step / steps
        points.append(
            (
                round(cx + HEAD_RADIUS * math.cos(theta), 3),
                round(cy + HEAD_RADIUS * math.sin(theta), 3),
            )
        )
    spliced: list[tuple[float, float]] = []
    handle_done = False
    for point in points:
        in_zone = abs(point[0] - cx) < HANDLE_HALF_WIDTH and point[1] < join_y + 2.0
        if in_zone:
            if not handle_done:
                spliced.extend(
                    (
                        (cx - HANDLE_HALF_WIDTH, join_y),
                        (cx - HANDLE_HALF_WIDTH, HANDLE_END_Y),
                        (cx + HANDLE_HALF_WIDTH, HANDLE_END_Y),
                        (cx + HANDLE_HALF_WIDTH, join_y),
                    )
                )
                handle_done = True
            continue
        spliced.append(point)
    deduped: list[tuple[float, float]] = []
    for point in spliced:
        rounded = (round(point[0], 3), round(point[1], 3))
        if not deduped or rounded != deduped[-1]:
            deduped.append(rounded)
    if deduped[0] == deduped[-1]:
        deduped.pop()
    return tuple(deduped)


def spiral_points(step_deg: float = 2.0) -> list[tuple[float, float]]:
    """Archimedean spiral from the top of the outer turn, winding inward."""
    cx, cy = COIL_CENTER
    total_deg = SPIRAL_TURNS * 360.0
    points: list[tuple[float, float]] = []
    steps = int(total_deg / step_deg)
    for index in range(steps + 1):
        swept = index * step_deg
        radius = SPIRAL_OUTER_RADIUS - SPIRAL_PITCH * swept / 360.0
        theta = math.radians(swept - 90.0)
        points.append(
            (
                round(cx + radius * math.cos(theta), 3),
                round(cy + radius * math.sin(theta), 3),
            )
        )
    return points


def spiral_inner_radius() -> float:
    return SPIRAL_OUTER_RADIUS - SPIRAL_PITCH * SPIRAL_TURNS


def detector_graphics(origin: float) -> tuple[str, ...]:
    graphics: list[str] = []
    # Soldermask opening: the exposed-detector disc over the spiral.
    cx, cy = COIL_CENTER
    rendered = "\n          ".join(
        f"(xy {cx + MASK_OPENING_RADIUS * math.cos(a) + origin:.3f} "
        f"{cy + MASK_OPENING_RADIUS * math.sin(a) + origin:.3f})"
        for a in (2 * math.pi * s / 96 for s in range(96))
    )
    graphics.append(
        f"""  (gr_poly
    (pts
          {rendered}
    )
    (stroke (width 0) (type solid))
    (fill yes)
    (layer "F.Mask")
    (uuid {uuid4()})
  )"""
    )
    # Connector pin labels on the handle.
    for index, label in enumerate(("V", "G", "F")):
        graphics.append(
            _silk_text(label, (P1_AT[0] - 2.1, P1_AT[1] + index * 2.54), origin)
        )
    return tuple(graphics)


def compute_detector_board_layout(netlist: BoardNetlist) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    net_of = {
        (reference, pin): net.name
        for net in netlist.nets
        for reference, pin in net.nodes
    }

    def net(reference: str, pin: str) -> str:
        name = net_of.get((reference, pin))
        if name is None:
            raise BoardGenerationError(f"{reference}.{pin} has no net.")
        return name

    def expect(reference: str, pin: str, expected: str) -> None:
        actual = net(reference, pin)
        if actual != expected:
            raise BoardGenerationError(
                f"{reference}.{pin} is on {actual}, expected {expected}."
            )

    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    part_rotation: list[tuple[str, float]] = []
    for reference, (x, y, rotation) in PLACEMENTS.items():
        if reference not in by_ref:
            raise BoardGenerationError(f"Netlist is missing {reference}.")
        placements.append((by_ref[reference], x))
        part_y.append((reference, y))
        if rotation:
            part_rotation.append((reference, rotation))

    # Pin-net sanity against the schematic before wiring anything.
    for index, pin_net in enumerate(P1_PIN_NETS):
        expect("P1", str(index + 1), f"/{pin_net}")
    expect("Q1", "1", "/BASE")
    expect("Q1", "2", "/EM")
    expect("Q1", "3", "/COL")
    expect("L1", "1", "/VCC")
    expect("L1", "2", "/COL")

    rotations = {ref: rot for ref, (_x, _y, rot) in PLACEMENTS.items()}

    def pad(reference: str, pin: str) -> tuple[float, float]:
        x, y, _rot = PLACEMENTS[reference]
        spec = FOOTPRINT_LIBRARY[by_ref[reference].footprint]
        pad_spec = spec.pads_named(pin)[0]
        dx, dy = rotate_offset(pad_spec.x_mm, pad_spec.y_mm, rotations[reference])
        return (round(x + dx, 4), round(y + dy, 4))

    def pad_for(reference: str, net_name: str) -> tuple[float, float]:
        for pin in ("1", "2"):
            if net(reference, pin) == net_name:
                return pad(reference, pin)
        raise BoardGenerationError(f"{reference} has no pin on {net_name}.")

    router = _Router()

    # --- VCC: header pin 1 across the top, down the west rail. ---
    router.path(
        "/VCC",
        (pad("P1", "1"), (34.2, 5.4), (31.4, 5.4), (31.4, 12.0), pad("L1", "1")),
        layer="F.Cu", width=POWER_W,
    )
    router.path("/VCC", ((34.2, 5.4), pad_for("R1", "/VCC")), layer="F.Cu")
    router.path("/VCC", (pad("P1", "1"), pad_for("C4", "/VCC")), layer="F.Cu")
    # --- GND vias into the handle pour. ---
    for reference, via_at in (
        ("C4", (45.2, 5.4)),
        ("R2", (34.2, 12.2)),
        ("C5", (37.4, 11.4)),
        ("C2", (33.5, 16.2)),
        ("R3", (39.39, 17.3)),
    ):
        router.path("/GND", (pad_for(reference, "/GND"), via_at), layer="F.Cu")
        router.via("/GND", *via_at)
    # --- BASE: bias string plus the bypass, over to the transistor. ---
    router.path(
        "/BASE", (pad_for("R1", "/BASE"), pad_for("R2", "/BASE")), layer="F.Cu"
    )
    router.path(
        "/BASE", (pad_for("R2", "/BASE"), pad_for("C5", "/BASE")), layer="F.Cu"
    )
    router.path(
        "/BASE", ((35.4, 9.61), (35.4, 11.9), pad("Q1", "1")), layer="F.Cu"
    )
    # --- EM: emitter to the tank caps and its resistor. ---
    em_c2 = pad_for("C2", "/EM")
    router.path(
        "/EM", (pad("Q1", "2"), (35.96, 15.9), em_c2), layer="F.Cu"
    )
    # C1's tank-cap EM pad sits east of the COL feed; hop the back layer.
    em_via_a = (36.5, 15.05)
    em_via_b = (43.5, 15.05)
    router.path("/EM", ((35.96, 15.3), em_via_a), layer="F.Cu")
    router.via("/EM", *em_via_a)
    router.path("/EM", (em_via_a, em_via_b), layer="B.Cu")
    router.via("/EM", *em_via_b)
    router.path("/EM", (em_via_b, pad_for("C1", "/EM")), layer="F.Cu")
    router.path("/EM", (em_c2, pad_for("R3", "/EM")), layer="F.Cu")
    # --- COL: collector to the tank cap, the output tap, and the coil. ---
    router.path(
        "/COL",
        (pad("Q1", "3"), (41.6, 13.6), (41.6, 17.6), (40.0, 19.0)),
        layer="F.Cu",
    )
    router.path(
        "/COL", ((41.6, 15.9), pad_for("C1", "/COL")), layer="F.Cu"
    )
    router.path("/COL", ((41.6, 13.6), pad_for("C3", "/COL")), layer="F.Cu")
    # --- FO_A / FOUT: coupling cap through the series resistor. ---
    router.path(
        "/FO_A", (pad_for("C3", "/FO_A"), pad_for("R4", "/FO_A")), layer="F.Cu"
    )
    fout_pad = pad_for("R4", "/FOUT")
    router.path(
        "/FOUT",
        (fout_pad, (fout_pad[0], 9.0), (42.0, 9.0), (42.0, 10.48), pad("P1", "3")),
        layer="F.Cu",
    )

    # --- The coil itself: exposed spiral, centre via, back return. ---
    spiral = spiral_points()
    router.path("/COL", spiral, layer="F.Cu", width=SPIRAL_TRACE_W)
    inner_end = spiral[-1]
    router.via("/COL", *inner_end)
    return_via = (31.9, 18.0)
    router.path("/COL", (inner_end, return_via), layer="B.Cu")
    router.via("/COL", *return_via)
    router.path("/COL", (return_via, pad("L1", "2")), layer="F.Cu")

    return BoardLayout(
        placements=tuple(placements),
        segments=tuple(router.segments),
        vias=tuple(router.vias),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(part_rotation),
        # Ground pour over the HANDLE only: no plane under the coil (9.1).
        zones=(("/GND", "B.Cu", (30.5, 2.0, 49.5, 17.8)),),
        outline=detector_outline(),
        graphics=detector_graphics(BOARD_SHEET_ORIGIN_MM),
        hide_references=(
            "P1", "L1", "Q1", "R1", "R2", "R3", "R4", "C1", "C2", "C3",
            "C4", "C5",
        ),
    )


def generate_detector_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_detector_board_layout(netlist)
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    return netlist, layout
