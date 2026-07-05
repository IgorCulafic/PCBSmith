"""Four-leaf-clover tilt-indicator board: shaped outline, art, two sides.

Everything here is parametric geometry around the clover centre:

- the OUTLINE is the union boundary of four leaf circles plus a stem,
  emitted as a dense Edge.Cuts polygon;
- the FRONT carries a green LED at each leaf tip, its series resistor on the
  arm, curved arm traces (the traces are part of the art), a VDD copper
  plane in the centre, and the silkscreen clover with its motto;
- the BACK carries the MPU-6050 (rotated so its I2C pins face the MCU), the
  ATtiny84A, the support passives, and a full GND pour that connects every
  ground pad without explicit routing.

Power distribution is planar (front VDD zone + back GND pour); only the
signals are routed, as explicit waypoint paths tuned against live KiCad DRC.
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
    TrackSegment,
    ViaSpec,
    _side_escapes,
    export_kicad_netlist_xml,
    parse_board_netlist,
    render_board_from_layout,
    rotate_offset,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli

CX = 21.0
CY = 19.5
LEAF_RADIUS = 9.5
LEAF_DISTANCE = 9.5
STEM_HALF_WIDTH = 4.5
STEM_END_Y = CY + 22.5
BOARD_W = 42.0
BOARD_H = 46.0

# Leaf compass directions as unit vectors in board coordinates (y down).
LEAVES = {
    "NE": (math.sqrt(0.5), -math.sqrt(0.5)),
    "SE": (math.sqrt(0.5), math.sqrt(0.5)),
    "SW": (-math.sqrt(0.5), math.sqrt(0.5)),
    "NW": (-math.sqrt(0.5), -math.sqrt(0.5)),
}
LED_RADIAL = 16.4
RESISTOR_RADIAL = 10.2

SIGNAL_W = 0.3
POWER_W = 0.5

U1_AT = (21.0, 16.0)
U1_ROT = 180.0  # I2C pins face the MCU below
U2_AT = (21.0, 28.2)
U2_ROT = 180.0  # SDA lands top-west, right under the sensor's SDA exit

BACK_PARTS = {"U1", "U2", "C1", "C2", "C3", "C4", "C5", "R1", "R2"}
BACK_POSITIONS = {
    "U1": U1_AT,
    "U2": U2_AT,
    "C1": (14.2, 12.0),   # REGOUT filter
    "C2": (25.0, 9.8),    # MPU VDD bypass
    "C3": (27.6, 20.0),   # CPOUT charge pump
    "C4": (19.5, 10.2),   # VLOGIC bypass
    "C5": (26.9, 33.5),   # MCU VCC bypass
    "R1": (16.1, 23.9),   # SDA pullup, inline tap under the SDA column
    "R2": (28.4, 26.6),   # SCL pullup, inline tap on the east corridor
}
# 270 on the mirrored back puts pin 2 (the signal pad) on TOP.
BACK_ROTATIONS = {
    "U1": U1_ROT, "U2": U2_ROT, "C2": 90.0, "C3": 90.0,
    "R1": 270.0, "R2": 270.0,
}
LEAF_PARTS = {
    "NE": ("R3", "D1"),
    "NW": ("R4", "D2"),
    "SW": ("R5", "D3"),
    "SE": ("R6", "D4"),
}
# The flipped+rotated SOIC puts PA0..PA3 on its EAST column (pins 13..10
# top to bottom); the geometry below routes each to its leaf.
LEAF_MCU_PINS = {"NE": "10", "SE": "11", "SW": "12", "NW": "13"}

P1_AT = (21.0, 37.5)


def _radial(direction: tuple[float, float], distance: float) -> tuple[float, float]:
    return (CX + direction[0] * distance, CY + direction[1] * distance)


# ---------------------------------------------------------------------------
# Outline: four circle arcs joined at their intersection cusps, plus a stem.


def clover_outline() -> tuple[tuple[float, float], ...]:
    centers = {
        name: _radial(direction, LEAF_DISTANCE) for name, direction in LEAVES.items()
    }
    order = ("NE", "SE", "SW", "NW")  # clockwise in board coords

    def cusp(a: str, b: str) -> tuple[float, float]:
        (ax, ay), (bx, by) = centers[a], centers[b]
        mx, my = ((ax + bx) / 2, (ay + by) / 2)
        half = math.dist((ax, ay), (bx, by)) / 2
        height = math.sqrt(LEAF_RADIUS**2 - half**2)
        # Perpendicular direction pointing away from the clover centre.
        px, py = (-(by - ay), bx - ax)
        norm = math.hypot(px, py)
        px, py = px / norm * height, py / norm * height
        candidate1 = (mx + px, my + py)
        candidate2 = (mx - px, my - py)
        return max(
            (candidate1, candidate2), key=lambda p: math.dist(p, (CX, CY))
        )

    points: list[tuple[float, float]] = []
    for index, name in enumerate(order):
        previous = order[index - 1]
        following = order[(index + 1) % len(order)]
        center = centers[name]
        start = cusp(previous, name)
        end = cusp(name, following)
        a0 = math.atan2(start[1] - center[1], start[0] - center[0])
        a1 = math.atan2(end[1] - center[1], end[0] - center[0])
        while a1 <= a0:
            a1 += 2 * math.pi
        # Keep whichever sweep bulges AWAY from the clover centre; the wrong
        # choice self-intersects the polygon (live DRC: invalid_outline).
        mid = a0 + (a1 - a0) / 2
        mid_point = (
            center[0] + LEAF_RADIUS * math.cos(mid),
            center[1] + LEAF_RADIUS * math.sin(mid),
        )
        if math.dist(mid_point, (CX, CY)) < LEAF_DISTANCE:
            a0, a1 = a1, a0 + 2 * math.pi
        steps = 40
        for step in range(steps):
            angle = a0 + (a1 - a0) * step / steps
            points.append(
                (
                    center[0] + LEAF_RADIUS * math.cos(angle),
                    center[1] + LEAF_RADIUS * math.sin(angle),
                )
            )
        points.append(end)

    # Splice the stem between the two bottom leaves. The leaf arcs dip BELOW
    # their cusp, so the stem must join at the arcs' crossings with its side
    # walls (x = CX +/- STEM_HALF_WIDTH), not at the cusp itself: replace the
    # whole contiguous run of points inside the stem zone with the stem.
    bottom = cusp("SE", "SW")
    se_center = centers["SE"]
    join_y = se_center[1] + math.sqrt(
        LEAF_RADIUS**2 - (CX + STEM_HALF_WIDTH - se_center[0]) ** 2
    )
    spliced: list[tuple[float, float]] = []
    in_zone_done = False
    for point in points:
        in_zone = abs(point[0] - CX) < STEM_HALF_WIDTH and point[1] > bottom[1] - 2.0
        if in_zone:
            if not in_zone_done:
                spliced.extend(
                    (
                        (CX + STEM_HALF_WIDTH, join_y),
                        (CX + STEM_HALF_WIDTH, STEM_END_Y),
                        (CX - STEM_HALF_WIDTH, STEM_END_Y),
                        (CX - STEM_HALF_WIDTH, join_y),
                    )
                )
                in_zone_done = True
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


# ---------------------------------------------------------------------------
# Silkscreen art: a little clover of four filled hearts plus the motto.


def _circle_points(
    center: tuple[float, float], radius: float, steps: int = 24
) -> list[tuple[float, float]]:
    return [
        (
            center[0] + radius * math.cos(2 * math.pi * step / steps),
            center[1] + radius * math.sin(2 * math.pi * step / steps),
        )
        for step in range(steps)
    ]


def _silk_poly(points: Sequence[tuple[float, float]], origin: float) -> str:
    rendered = "\n          ".join(
        f"(xy {x + origin:.3f} {y + origin:.3f})" for x, y in points
    )
    return f"""  (gr_poly
    (pts
          {rendered}
    )
    (stroke (width 0.12) (type solid))
    (fill yes)
    (layer "F.SilkS")
    (uuid {uuid4()})
  )"""


def clover_silk_graphics(origin: float, motto: str) -> tuple[str, ...]:
    graphics: list[str] = []
    art_center = (CX, CY - 0.3)
    for direction in LEAVES.values():
        # Each art leaf: two lobes plus a wedge back to the centre. Leaves
        # sit far enough apart that a cross-shaped gap separates them.
        lobe_base = (
            art_center[0] + direction[0] * 3.5,
            art_center[1] + direction[1] * 3.5,
        )
        perp = (-direction[1], direction[0])
        for sign in (1.0, -1.0):
            lobe = (
                lobe_base[0] + perp[0] * 0.95 * sign,
                lobe_base[1] + perp[1] * 0.95 * sign,
            )
            graphics.append(_silk_poly(_circle_points(lobe, 1.25), origin))
        wedge = (
            (
                art_center[0] + direction[0] * 0.9 + perp[0] * 0.75,
                art_center[1] + direction[1] * 0.9 + perp[1] * 0.75,
            ),
            (
                art_center[0] + direction[0] * 0.9 - perp[0] * 0.75,
                art_center[1] + direction[1] * 0.9 - perp[1] * 0.75,
            ),
            (lobe_base[0] + direction[0] * 1.1, lobe_base[1] + direction[1] * 1.1),
        )
        graphics.append(_silk_poly(wedge, origin))
    # Stem flourish: a short curved line below the art.
    stem = [
        (art_center[0] + 0.3 * math.sin(t * 2.2), art_center[1] + 3.4 + t * 2.4)
        for t in (0.0, 0.35, 0.7, 1.0)
    ]
    graphics.append(
        f"""  (gr_line
    (start {stem[0][0] + origin:.3f} {stem[0][1] + origin:.3f})
    (end {stem[-1][0] + origin:.3f} {stem[-1][1] + origin:.3f})
    (stroke (width 0.4) (type solid))
    (layer "F.SilkS")
    (uuid {uuid4()})
  )"""
    )
    escaped = motto.replace("\\", "\\\\").replace('"', '\\"')
    graphics.append(
        f"""  (gr_text "{escaped}"
    (at {CX + origin:.3f} {CY + 11.0 + origin:.3f} 0)
    (layer "F.SilkS")
    (uuid {uuid4()})
    (effects
      (font
        (size 1.3 1.3)
        (thickness 0.22)
        (italic yes)
      )
    )
  )"""
    )
    return tuple(graphics)


# ---------------------------------------------------------------------------
# Placement and routing.


def _front_pad(
    spec_ref: tuple[float, float], rotation: float, pad_offset: tuple[float, float]
) -> tuple[float, float]:
    dx, dy = rotate_offset(pad_offset[0], pad_offset[1], rotation)
    return (spec_ref[0] + dx, spec_ref[1] + dy)


def _back_pad(
    anchor: tuple[float, float], rotation: float, pad_offset: tuple[float, float]
) -> tuple[float, float]:
    # KiCad rotations act clockwise on the mirrored back side, so the
    # physical pad position uses the INVERSE angle before mirroring.
    dx, dy = rotate_offset(pad_offset[0], pad_offset[1], (360.0 - rotation) % 360.0)
    return (anchor[0] - dx, anchor[1] + dy)


def _pad_offset(footprint: str, pin: str) -> tuple[float, float]:
    pad = FOOTPRINT_LIBRARY[footprint].pads_named(pin)[0]
    return (pad.x_mm, pad.y_mm)


def _bezier(
    start: tuple[float, float],
    end: tuple[float, float],
    bulge: float,
    steps: int = 10,
) -> list[tuple[float, float]]:
    """Quadratic bezier sampled as a polyline; bulge is the perpendicular
    offset of the control point (the arm traces are part of the artwork)."""
    mx, my = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    dx, dy = (end[0] - start[0], end[1] - start[1])
    norm = math.hypot(dx, dy) or 1.0
    ctrl = (mx - dy / norm * bulge, my + dx / norm * bulge)
    points = []
    for step in range(steps + 1):
        t = step / steps
        x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * ctrl[0] + t**2 * end[0]
        y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * ctrl[1] + t**2 * end[1]
        points.append((x, y))
    return points


def _bezier_toward(
    start: tuple[float, float],
    end: tuple[float, float],
    magnitude: float,
    center: tuple[float, float],
) -> list[tuple[float, float]]:
    """Bezier polyline whose bow points toward the given centre."""
    candidates = (
        _bezier(start, end, magnitude),
        _bezier(start, end, -magnitude),
    )
    return min(
        candidates,
        key=lambda pts: math.dist(pts[len(pts) // 2], center),
    )


class _Router:
    def __init__(self) -> None:
        self.segments: list[TrackSegment] = []
        self.vias: list[ViaSpec] = []

    def path(
        self,
        net: str,
        points: Sequence[tuple[float, float]],
        *,
        layer: str,
        width: float = SIGNAL_W,
    ) -> None:
        for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
            self.segments.append(
                TrackSegment(
                    x1=round(x1, 4), y1=round(y1, 4),
                    x2=round(x2, 4), y2=round(y2, 4),
                    layer=layer, net_name=net, width_mm=width,
                )
            )

    def via(self, net: str, x: float, y: float) -> None:
        self.vias.append(ViaSpec(x=round(x, 4), y=round(y, 4), net_name=net))


def compute_clover_board_layout(netlist: BoardNetlist, motto: str) -> BoardLayout:
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

    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    part_rotation: list[tuple[str, float]] = []

    def place(reference: str, x: float, y: float, rotation: float = 0.0) -> None:
        if reference not in by_ref:
            raise BoardGenerationError(f"Netlist is missing {reference}.")
        placements.append((by_ref[reference], x))
        part_y.append((reference, y))
        if rotation:
            part_rotation.append((reference, rotation))

    for reference, position in BACK_POSITIONS.items():
        place(reference, *position, BACK_ROTATIONS.get(reference, 0.0))
    place("P1", *P1_AT)

    led_rotations = {"NE": 180.0, "SE": 180.0, "NW": 0.0, "SW": 0.0}
    resistor_rotations = {"NE": 0.0, "SE": 0.0, "NW": 180.0, "SW": 180.0}
    for leaf, (resistor, led) in LEAF_PARTS.items():
        direction = LEAVES[leaf]
        place(resistor, *_radial(direction, RESISTOR_RADIAL), resistor_rotations[leaf])
        place(led, *_radial(direction, LED_RADIAL), led_rotations[leaf])
    rotations = dict(part_rotation)

    router = _Router()
    u1_spec = FOOTPRINT_LIBRARY[by_ref["U1"].footprint]

    def back_pad(reference: str, pin: str) -> tuple[float, float]:
        return _back_pad(
            BACK_POSITIONS[reference],
            rotations.get(reference, 0.0),
            _pad_offset(by_ref[reference].footprint, pin),
        )

    def front_pad(reference: str, pin: str) -> tuple[float, float]:
        leaf = next(
            key for key, refs in LEAF_PARTS.items() if reference in refs
        )
        radial = RESISTOR_RADIAL if reference.startswith("R") else LED_RADIAL
        return _front_pad(
            _radial(LEAVES[leaf], radial),
            rotations.get(reference, 0.0),
            _pad_offset(by_ref[reference].footprint, pin),
        )

    def pad_net_via(reference: str, pin: str, via_at: tuple[float, float]) -> None:
        pad = back_pad(reference, pin)
        router.path(net(reference, pin), (pad, via_at), layer="B.Cu", width=POWER_W)
        router.via(net(reference, pin), *via_at)

    # --- Sensor fanout (mirrored nested elbows on the back). ---
    plan = _side_escapes(u1_spec, U1_ROT)
    exits: dict[str, tuple[float, float]] = {}
    for pin in ("1", "8", "10", "12", "13", "18", "20", "23", "24"):
        side, target, rank = plan[pin]
        px, py = _back_pad(U1_AT, U1_ROT, _pad_offset(by_ref["U1"].footprint, pin))
        pin_net = net("U1", pin)
        if side in ("north", "south"):
            pad = u1_spec.pads_named(pin)[0]
            reach = max(pad.width_mm, pad.height_mm) / 2 + 0.45 + rank * 0.55
            jog_y = py - reach if side == "north" else py + reach
            spread_x = U1_AT[0] - target
            router.path(pin_net, ((px, py), (px, jog_y)), layer="B.Cu", width=0.25)
            if abs(spread_x - px) > 0.01:
                router.path(
                    pin_net, ((px, jog_y), (spread_x, jog_y)), layer="B.Cu", width=0.25
                )
            exits[pin] = (spread_x, jog_y)
        else:
            escape_x = U1_AT[0] - target
            router.path(pin_net, ((px, py), (escape_x, py)), layer="B.Cu", width=0.25)
            exits[pin] = (escape_x, py)

    # CLKIN's ground escape sits in a cell walled by the INT loop; bridge it
    # over the free front to the centre ground via.
    e1 = exits["1"]
    router.path("/GND", (e1, (16.8, e1[1])), layer="B.Cu", width=0.25)
    router.via("/GND", 16.8, e1[1])
    router.path(
        "/GND", ((16.8, e1[1]), (19.4, 16.4), (21.0, 15.6)), layer="F.Cu",
        width=0.25,
    )

    # AD0 (9) and FSYNC (11) tie to ground along the inside of the pad row,
    # joining CLKIN's pad (pin 1) whose west escape reaches the open pour;
    # their own north exits would be sealed inside the fanout comb.
    pad9 = _back_pad(U1_AT, U1_ROT, _pad_offset(by_ref["U1"].footprint, "9"))
    pad11 = _back_pad(U1_AT, U1_ROT, _pad_offset(by_ref["U1"].footprint, "11"))
    pad1 = _back_pad(U1_AT, U1_ROT, _pad_offset(by_ref["U1"].footprint, "1"))
    router.path(
        "/GND",
        (pad11, (pad11[0], 14.9), (pad9[0], 14.9)),
        layer="B.Cu",
        width=0.2,
    )
    router.path(
        "/GND",
        (pad9, (pad9[0], 14.9), (21.0, 14.9), (21.0, 15.6)),
        layer="B.Cu",
        width=0.2,
    )
    router.via("/GND", 21.0, 15.6)
    router.path("/GND", ((21.0, 15.6), (21.0, 7.4)), layer="F.Cu", width=0.25)
    router.via("/GND", 21.0, 7.4)
    del pad1  # pin 1 reaches the pour through its own west escape

    # --- SDA: straight column into the MCU; the pullup taps the column. ---
    e24 = exits["24"]
    u2_sda = back_pad("U2", "7")
    r1_sda = back_pad("R1", "2")
    router.path(
        "/SDA", (e24, (e24[0], u2_sda[1]), u2_sda), layer="B.Cu"
    )
    router.path(
        "/SDA",
        ((e24[0], 22.8), (r1_sda[0], 22.8), r1_sda),
        layer="B.Cu",
    )
    pad_net_via("R1", "1", (15.0, 24.69))

    # --- SCL: east corridor around the MCU; the pullup taps the corridor. ---
    e23 = exits["23"]
    u2_scl = back_pad("U2", "9")
    router.path(
        "/SCL",
        (e23, (e23[0], 20.6), (26.7, 20.6), (26.7, u2_scl[1]), u2_scl),
        layer="B.Cu",
    )
    r2_scl = back_pad("R2", "2")
    router.path(
        "/SCL", ((26.7, 25.66), (26.7, r2_scl[1]), r2_scl), layer="B.Cu"
    )
    pad_net_via("R2", "1", (28.4, 28.5))

    # --- INT: west loop into the MCU's west-column PA7. ---
    e12 = exits["12"]
    u2_int = back_pad("U2", "6")
    router.path(
        "/INT",
        (
            e12,
            (e12[0], 11.1),
            (11.4, 11.1),
            (11.4, 26.6),
            (17.05, 26.6),
            (17.05, u2_int[1]),
            u2_int,
        ),
        layer="B.Cu",
    )

    # --- REGOUT / CPOUT capacitors. ---
    e10 = exits["10"]
    c1_sig = back_pad("C1", "1")
    router.path(
        "/REGOUT",
        (e10, (e10[0], 11.7), (c1_sig[0], 11.7), c1_sig),
        layer="B.Cu",
    )
    e20 = exits["20"]
    c3_sig = back_pad("C3", "1") if net("C3", "1") == "/CPOUT" else back_pad("C3", "2")
    router.path(
        "/CPOUT",
        (e20, (28.9, e20[1]), (28.9, c3_sig[1]), c3_sig),
        layer="B.Cu",
    )

    # --- VDD plane taps. ---
    e8 = exits["8"]
    router.path("/VDD", (e8, (17.6, 13.3)), layer="B.Cu", width=POWER_W)
    router.via("/VDD", 17.6, 13.3)
    e13 = exits["13"]
    router.path("/VDD", (e13, (e13[0] + 0.9, e13[1])), layer="B.Cu", width=POWER_W)
    router.via("/VDD", e13[0] + 0.9, e13[1])
    c2_vdd = back_pad("C2", "2") if net("C2", "2") == "/VDD" else back_pad("C2", "1")
    router.path("/VDD", (c2_vdd, (c2_vdd[0], 8.2)), layer="B.Cu", width=POWER_W)
    router.via("/VDD", c2_vdd[0], 8.2)
    c4_vdd = back_pad("C4", "2") if net("C4", "2") == "/VDD" else back_pad("C4", "1")
    router.path("/VDD", (c4_vdd, (22.3, c4_vdd[1])), layer="B.Cu", width=POWER_W)
    router.via("/VDD", 22.3, c4_vdd[1])
    # MCU VCC and its bypass feed from the connector pad on the back.
    u2_vcc = back_pad("U2", "1")
    router.path("/VDD", (u2_vcc, (17.2, 32.01)), layer="B.Cu", width=POWER_W)
    router.via("/VDD", 17.2, 32.01)
    c5_vdd = back_pad("C5", "1") if net("C5", "1") == "/VDD" else back_pad("C5", "2")
    router.path("/VDD", (c5_vdd, (27.2, 34.4)), layer="B.Cu", width=POWER_W)
    router.via("/VDD", 27.2, 34.4)

    # --- Leaf feeds: MCU east column -> vias -> front runs to the arms. ---
    inner_pads = {
        leaf: front_pad(LEAF_PARTS[leaf][0], "1") for leaf in LEAF_PARTS
    }
    for leaf in ("NE", "SE", "SW", "NW"):
        pin = LEAF_MCU_PINS[leaf]
        leaf_net = net("U2", pin)
        start = back_pad("U2", pin)
        inner = inner_pads[leaf]
        if leaf == "SE":
            # Short back hop to a via beside the SE arm.
            via_at = (26.1, inner[1])
            router.path(
                leaf_net, (start, (via_at[0], start[1]), via_at), layer="B.Cu"
            )
            router.via(leaf_net, *via_at)
            router.path(leaf_net, (via_at, inner), layer="F.Cu")
            continue
        if leaf == "SW":
            # Thread the back mid-band between the MCU's pad rows, then a
            # via right below the resistor pad.
            sw_via = (inner[0], 28.5)
            router.path(
                leaf_net,
                (start, (24.6, start[1]), (24.6, 28.84), (inner[0], 28.84), sw_via),
                layer="B.Cu",
                width=0.25,
            )
            router.via(leaf_net, *sw_via)
            router.path(leaf_net, (sw_via, inner), layer="F.Cu")
            continue
        via_at = (25.1, start[1])
        router.path(leaf_net, (start, via_at), layer="B.Cu")
        router.via(leaf_net, *via_at)
        if leaf == "NE":
            waypoints = (
                via_at, (26.2, 25.2), (28.6, 23.6), (30.4, 20.0),
                (30.4, 13.9), (27.41, 13.9), inner,
            )
        else:  # NW: the diagonal freed by the inline pullups
            waypoints = (
                via_at, (19.5, 29.6), (14.4, 25.2), (12.4, 22.0),
                (12.4, 15.5), (14.58, 13.9), inner,
            )
        router.path(leaf_net, waypoints, layer="F.Cu")

    # --- Leaf arms: resistor -> curved trace -> LED; cathode -> pour via. ---
    for leaf, (resistor, led) in LEAF_PARTS.items():
        direction = LEAVES[leaf]
        arm_net = net(led, "2")
        outer = front_pad(resistor, "2")
        anode = front_pad(led, "2")
        router.path(
            arm_net, _bezier_toward(outer, anode, 1.6, (CX, CY)), layer="F.Cu"
        )
        cathode = front_pad(led, "1")
        perpendicular = (-direction[1], direction[0])
        gnd_via = (
            cathode[0] + perpendicular[0] * 1.7,
            cathode[1] + perpendicular[1] * 1.7,
        )
        router.path("/GND", (cathode, gnd_via), layer="F.Cu")
        router.via("/GND", *gnd_via)

    zones = (
        ("/VDD", "F.Cu", (12.2, 7.8, 30.4, 27.5)),
        ("/VDD", "F.Cu", (14.5, 26.0, 29.4, 40.0)),
        ("/GND", "B.Cu", (2.0, 2.0, BOARD_W - 2.0, BOARD_H - 2.0)),
    )

    return BoardLayout(
        placements=tuple(placements),
        segments=tuple(router.segments),
        vias=tuple(router.vias),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        parts_row_y_mm=CY,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(part_rotation),
        zones=zones,
        outline=clover_outline(),
        graphics=clover_silk_graphics(BOARD_SHEET_ORIGIN_MM, motto),
        part_flip=tuple(sorted(BACK_PARTS)),
        hide_references=("D1", "D2", "D3", "D4", "R1", "R2"),
    )


def generate_clover_board(
    *,
    schematic_file: Path,
    board_file: Path,
    motto: str,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_clover_board_layout(netlist, motto)
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    return netlist, layout
