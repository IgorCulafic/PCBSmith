"""Pear-shaped board: three LED rings around the edge, worm silkscreen art.

The pear body is the convex hull of two circles (a big bottom bulge and a
smaller top bulge) joined by their external tangent lines, plus a stem tab
that carries the drive connector. The key geometric property used
throughout: the INWARD OFFSET of this hull at depth t is the same hull with
both radii reduced by t, so every LED ring, bus ring and via ring is exactly
parallel to the outline.

Each ring k is an independent drive net L{k}: bus ring (inner) -> series
resistor -> LED -> via -> back GND pour. Units sit tangentially on the ring
path at arbitrary rotation angles; sharply curved stretches (local radius
below MIN_UNIT_RADIUS) carry only the bare ring traces.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
from pcbsmith.kicad.clover_board import _circle_points, _Router, _silk_poly

# Pear body: two circles joined by external tangents (board coords, y down).
TOP_CENTER = (28.0, 28.0)
TOP_RADIUS = 14.0
BOTTOM_CENTER = (28.0, 56.0)
BOTTOM_RADIUS = 26.0
BOARD_W = 56.0
BOARD_H = 86.0

STEM_HALF_WIDTH = 3.4
STEM_END_Y = 3.0

# Ring insets from the outline: LED units on the ring path, bus 1.5 inward,
# ground vias 1.5 outward of the LED cathodes.
RING_INSETS = (3.2, 7.4, 11.6)
BUS_OFFSET = 1.5
VIA_OFFSET = 1.5
UNIT_PITCH = 8.0
LED_R_GAP = 3.6  # anchor spacing: two courtyards plus arc-tilt margin
MIN_UNIT_RADIUS = 6.0

SIGNAL_W = 0.3
BUS_W = 0.5

P1_AT = (28.0, 5.6)
# Pin 1 (top) is GND. The ring pins are ordered by feed bearing so the back
# feeds never cross: L2 exits west, L3 down the middle, L1 east.
P1_PIN_NETS = ("GND", "L2", "L3", "L1")

LED_FOOTPRINT = "LED_SMD:LED_0603_1608Metric"
RESISTOR_FOOTPRINT = "Resistor_SMD:R_0603_1608Metric"


# ---------------------------------------------------------------------------
# Hull geometry.


def _tangent_angle() -> float:
    """Angle between the centre line and the radius to a tangent point."""
    delta = BOTTOM_RADIUS - TOP_RADIUS
    distance = math.dist(TOP_CENTER, BOTTOM_CENTER)
    return math.acos(delta / distance)


@dataclass(frozen=True)
class _Piece:
    """One stretch of a ring path: an arc or a straight tangent segment."""

    kind: str  # "arc" | "line"
    length: float
    radius: float  # local curvature radius (inf for lines)
    # Arc: (center, theta0, sweep). Line: (start, direction, outward).
    center: tuple[float, float] = (0.0, 0.0)
    theta0: float = 0.0
    sweep: float = 0.0
    start: tuple[float, float] = (0.0, 0.0)
    direction: tuple[float, float] = (0.0, 0.0)
    outward: tuple[float, float] = (0.0, 0.0)

    def at(self, s: float) -> tuple[
        tuple[float, float], tuple[float, float], tuple[float, float]
    ]:
        """(point, unit tangent, unit outward normal) at arc length s."""
        if self.kind == "line":
            point = (
                self.start[0] + self.direction[0] * s,
                self.start[1] + self.direction[1] * s,
            )
            return (point, self.direction, self.outward)
        theta = self.theta0 + self.sweep * (s / self.length)
        point = (
            self.center[0] + self.radius * math.cos(theta),
            self.center[1] + self.radius * math.sin(theta),
        )
        tangent = (-math.sin(theta), math.cos(theta))
        return (point, tangent, (math.cos(theta), math.sin(theta)))


def ring_pieces(inset: float) -> tuple[_Piece, ...]:
    """The ring path at the given inset, clockwise from the top-right."""
    top_r = TOP_RADIUS - inset
    bottom_r = BOTTOM_RADIUS - inset
    if top_r <= 0:
        raise BoardGenerationError(f"Ring inset {inset} swallows the top bulge.")
    beta = _tangent_angle()
    sin_b, cos_b = math.sin(beta), math.cos(beta)

    def on_top(direction: tuple[float, float]) -> tuple[float, float]:
        return (
            TOP_CENTER[0] + top_r * direction[0],
            TOP_CENTER[1] + top_r * direction[1],
        )

    def on_bottom(direction: tuple[float, float]) -> tuple[float, float]:
        return (
            BOTTOM_CENTER[0] + bottom_r * direction[0],
            BOTTOM_CENTER[1] + bottom_r * direction[1],
        )

    top_right = on_top((sin_b, -cos_b))
    bottom_right = on_bottom((sin_b, -cos_b))
    bottom_left = on_bottom((-sin_b, -cos_b))
    top_left = on_top((-sin_b, -cos_b))

    right_len = math.dist(top_right, bottom_right)
    right_dir = (
        (bottom_right[0] - top_right[0]) / right_len,
        (bottom_right[1] - top_right[1]) / right_len,
    )
    left_len = math.dist(bottom_left, top_left)
    left_dir = (
        (top_left[0] - bottom_left[0]) / left_len,
        (top_left[1] - bottom_left[1]) / left_len,
    )

    theta_right = beta - math.pi / 2
    bottom_sweep = 2 * math.pi - 2 * beta
    top_sweep = 2 * beta
    return (
        _Piece(
            kind="line", length=right_len, radius=math.inf,
            start=top_right, direction=right_dir, outward=(sin_b, -cos_b),
        ),
        _Piece(
            kind="arc", length=bottom_r * bottom_sweep, radius=bottom_r,
            center=BOTTOM_CENTER, theta0=theta_right, sweep=bottom_sweep,
        ),
        _Piece(
            kind="line", length=left_len, radius=math.inf,
            start=bottom_left, direction=left_dir, outward=(-sin_b, -cos_b),
        ),
        _Piece(
            kind="arc", length=top_r * top_sweep, radius=top_r,
            center=TOP_CENTER, theta0=3 * math.pi / 2 - beta,
            sweep=top_sweep,
        ),
    )


def ring_polyline(inset: float, step_mm: float = 0.6) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for piece in ring_pieces(inset):
        steps = max(2, math.ceil(piece.length / step_mm))
        for index in range(steps):
            point, _tangent, _outward = piece.at(piece.length * index / steps)
            points.append((round(point[0], 3), round(point[1], 3)))
    return points


@dataclass(frozen=True)
class UnitSite:
    """One LED unit anchored on a ring path."""

    ring: int  # 0-based ring index
    piece: _Piece
    s: float  # arc-length of the RESISTOR anchor within the piece


def ring_unit_sites(ring: int) -> tuple[UnitSite, ...]:
    """Evenly pitched unit sites, skipping sharply curved stretches."""
    sites: list[UnitSite] = []
    unit_span = LED_R_GAP + 1.6  # resistor anchor to cathode-stub end
    for piece in ring_pieces(RING_INSETS[ring]):
        if piece.radius < MIN_UNIT_RADIUS:
            continue
        count = int(piece.length // UNIT_PITCH)
        if count == 0:
            continue
        margin = (piece.length - count * UNIT_PITCH) / 2 + (UNIT_PITCH - unit_span) / 2
        for index in range(count):
            sites.append(UnitSite(ring=ring, piece=piece, s=margin + index * UNIT_PITCH))
    return tuple(sites)


def ring_unit_counts() -> tuple[int, ...]:
    return tuple(len(ring_unit_sites(ring)) for ring in range(len(RING_INSETS)))


# ---------------------------------------------------------------------------
# Outline: hull at inset 0 plus the stem splice.


def pear_outline() -> tuple[tuple[float, float], ...]:
    points = ring_polyline(0.0, step_mm=0.8)
    join_y = TOP_CENTER[1] - math.sqrt(TOP_RADIUS**2 - STEM_HALF_WIDTH**2)
    cx = TOP_CENTER[0]
    spliced: list[tuple[float, float]] = []
    stem_done = False
    for point in points:
        in_zone = abs(point[0] - cx) < STEM_HALF_WIDTH and point[1] < join_y + 2.0
        if in_zone:
            if not stem_done:
                spliced.extend(
                    (
                        (cx - STEM_HALF_WIDTH, join_y),
                        (cx - STEM_HALF_WIDTH, STEM_END_Y),
                        (cx + STEM_HALF_WIDTH, STEM_END_Y),
                        (cx + STEM_HALF_WIDTH, join_y),
                    )
                )
                stem_done = True
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
# Silkscreen: the worm coming out of its hole, plus pin labels and a leaf.


def _ellipse_points(
    center: tuple[float, float], rx: float, ry: float, steps: int = 48
) -> list[tuple[float, float]]:
    return [
        (
            center[0] + rx * math.cos(2 * math.pi * step / steps),
            center[1] + ry * math.sin(2 * math.pi * step / steps),
        )
        for step in range(steps)
    ]


def _clipped_circle_outline(
    center: tuple[float, float],
    radius: float,
    occluders: tuple[tuple[tuple[float, float], float], ...],
    origin: float,
    width: float = 0.35,
) -> list[str]:
    """Circle outline as gr_line chains, hiding stretches inside occluders."""
    steps = 72
    points = _circle_points(center, radius, steps=steps)
    visible = [
        all(
            math.dist(point, occ_center) > occ_radius - 0.05
            for occ_center, occ_radius in occluders
        )
        for point in points
    ]
    lines: list[str] = []
    for index in range(steps):
        following = (index + 1) % steps
        if not (visible[index] and visible[following]):
            continue
        (x1, y1), (x2, y2) = points[index], points[following]
        lines.append(
            f"""  (gr_line
    (start {x1 + origin:.3f} {y1 + origin:.3f})
    (end {x2 + origin:.3f} {y2 + origin:.3f})
    (stroke (width {width}) (type solid))
    (layer "F.SilkS")
    (uuid {uuid4()})
  )"""
        )
    return lines


def _silk_line(
    a: tuple[float, float], b: tuple[float, float], origin: float, width: float = 0.3
) -> str:
    return f"""  (gr_line
    (start {a[0] + origin:.3f} {a[1] + origin:.3f})
    (end {b[0] + origin:.3f} {b[1] + origin:.3f})
    (stroke (width {width}) (type solid))
    (layer "F.SilkS")
    (uuid {uuid4()})
  )"""


def _silk_text(
    text: str, at: tuple[float, float], origin: float, size: float = 0.8
) -> str:
    return f"""  (gr_text "{text}"
    (at {at[0] + origin:.3f} {at[1] + origin:.3f} 0)
    (layer "F.SilkS")
    (uuid {uuid4()})
    (effects
      (font
        (size {size} {size})
        (thickness {size * 0.18:.2f})
      )
    )
  )"""


# Worm anatomy in board coordinates. Everything stays within 12.5 mm of the
# bottom-bulge centre so the art clears the innermost ring's copper.
WORM_HOLE = ((24.4, 60.2), 5.2, 2.1)
WORM_SEGMENTS = (
    ((24.8, 57.6), 2.6),
    ((27.4, 55.8), 2.8),
    ((29.9, 53.4), 3.0),
)
WORM_HEAD = ((31.8, 48.8), 4.2)


def pear_silk_graphics(origin: float) -> tuple[str, ...]:
    graphics: list[str] = []

    # The hole: a filled ellipse at the base of the worm.
    hole_center, hole_rx, hole_ry = WORM_HOLE
    graphics.append(
        _silk_poly(_ellipse_points(hole_center, hole_rx, hole_ry), origin)
    )

    # Body segments, each occluded by the next one toward the head.
    chain = (*WORM_SEGMENTS, WORM_HEAD)
    for index, (center, radius) in enumerate(WORM_SEGMENTS):
        occluders = tuple(chain[index + 1:])
        graphics.extend(
            _clipped_circle_outline(center, radius, occluders, origin)
        )
    head_center, head_radius = WORM_HEAD
    graphics.extend(_clipped_circle_outline(head_center, head_radius, (), origin))

    # Face: eyes with filled pupils, eyebrows, and a smile.
    for eye_center in ((30.5, 48.0), (33.1, 48.7)):
        graphics.extend(
            _clipped_circle_outline(eye_center, 1.05, (), origin, width=0.25)
        )
        graphics.append(
            _silk_poly(_circle_points(eye_center, 0.5, steps=16), origin)
        )
    graphics.append(_silk_line((29.8, 45.9), (31.0, 45.7), origin))
    graphics.append(_silk_line((32.7, 46.4), (33.8, 46.7), origin))
    smile = ((30.2, 49.9), (31.0, 50.7), (32.1, 51.0), (33.1, 50.7))
    for a, b in zip(smile, smile[1:], strict=False):
        graphics.append(_silk_line(a, b, origin))

    # Connector pin labels on the stem.
    labels = ("G", "2", "3", "1")
    for index, label in enumerate(labels):
        graphics.append(
            _silk_text(label, (P1_AT[0] - 1.9, P1_AT[1] + index * 2.54), origin)
        )
    return tuple(graphics)


# ---------------------------------------------------------------------------
# Placement and routing.


def _pad_offset(footprint: str, pin: str) -> tuple[float, float]:
    pad = FOOTPRINT_LIBRARY[footprint].pads_named(pin)[0]
    return (pad.x_mm, pad.y_mm)


def _tangent_rotation(tangent: tuple[float, float], *, flip: bool) -> float:
    """Footprint rotation mapping local +x onto the tangent (or its flip)."""
    tx, ty = tangent
    if flip:
        tx, ty = -tx, -ty
    return round((-math.degrees(math.atan2(ty, tx))) % 360.0, 2)


def compute_pear_board_layout(netlist: BoardNetlist) -> BoardLayout:
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
        placements.append((by_ref[reference], round(x, 4)))
        part_y.append((reference, round(y, 4)))
        if rotation:
            part_rotation.append((reference, rotation))

    router = _Router()
    place("P1", *P1_AT)

    # Bus rings: one closed loop per layer.
    for ring in range(len(RING_INSETS)):
        loop = ring_polyline(RING_INSETS[ring] + BUS_OFFSET)
        router.path(f"/L{ring + 1}", (*loop, loop[0]), layer="F.Cu", width=BUS_W)

    resistor_pad = {pin: _pad_offset(RESISTOR_FOOTPRINT, pin) for pin in ("1", "2")}
    led_pad = {pin: _pad_offset(LED_FOOTPRINT, pin) for pin in ("1", "2")}

    unit = 0
    hidden: list[str] = ["P1"]
    for ring in range(len(RING_INSETS)):
        for site in ring_unit_sites(ring):
            unit += 1
            resistor = f"R{unit}"
            led = f"D{unit}"
            piece = site.piece

            r_point, r_tangent, _r_out = piece.at(site.s)
            r_rotation = _tangent_rotation(r_tangent, flip=False)
            place(resistor, *r_point, r_rotation)

            d_s = site.s + LED_R_GAP
            d_point, d_tangent, _d_out = piece.at(d_s)
            # Flipped so the anode (pad 2) faces the resistor.
            d_rotation = _tangent_rotation(d_tangent, flip=True)
            place(led, *d_point, d_rotation)

            def pad_at(
                anchor: tuple[float, float], rotation: float, local: tuple[float, float]
            ) -> tuple[float, float]:
                dx, dy = rotate_offset(local[0], local[1], rotation)
                return (anchor[0] + dx, anchor[1] + dy)

            bus_net = net(resistor, "1")
            branch_net = net(resistor, "2")
            gnd_net = net(led, "1")
            if bus_net != f"/L{ring + 1}":
                raise BoardGenerationError(
                    f"{resistor}.1 is on {bus_net}, expected /L{ring + 1}."
                )
            if net(led, "2") != branch_net or gnd_net != "/GND":
                raise BoardGenerationError(
                    f"Unit {unit} nets are miswired in the schematic."
                )

            # Bus tap: resistor pad 1 straight inward onto the bus ring.
            pad1 = pad_at(r_point, r_rotation, resistor_pad["1"])
            tap_point, _tap_tangent, tap_out = piece.at(max(site.s - 0.79, 0.0))
            tap = (
                tap_point[0] - tap_out[0] * BUS_OFFSET,
                tap_point[1] - tap_out[1] * BUS_OFFSET,
            )
            router.path(bus_net, (pad1, tap), layer="F.Cu")

            # Resistor pad 2 to the LED anode.
            pad2 = pad_at(r_point, r_rotation, resistor_pad["2"])
            anode = pad_at(d_point, d_rotation, led_pad["2"])
            router.path(branch_net, (pad2, anode), layer="F.Cu")

            # Cathode outward to a ground via into the back pour.
            cathode = pad_at(d_point, d_rotation, led_pad["1"])
            via_point, _via_tangent, via_out = piece.at(
                min(d_s + 0.79, piece.length)
            )
            via = (
                via_point[0] + via_out[0] * VIA_OFFSET,
                via_point[1] + via_out[1] * VIA_OFFSET,
            )
            router.path(gnd_net, (cathode, via), layer="F.Cu")
            router.via(gnd_net, *via)
            hidden.extend((resistor, led))

    # Drive feeds on the BACK from the stem connector to each bus ring.
    header_pads = tuple(
        (P1_AT[0], P1_AT[1] + index * 2.54) for index in range(4)
    )
    for index, pin_net in enumerate(P1_PIN_NETS):
        if net("P1", str(index + 1)) != f"/{pin_net}":
            raise BoardGenerationError(
                f"P1.{index + 1} is on {net('P1', str(index + 1))}, "
                f"expected /{pin_net}."
            )
    cx = TOP_CENTER[0]
    top_cy = TOP_CENTER[1]

    def bus_point(ring: int, angle_deg: float) -> tuple[float, float]:
        radius = TOP_RADIUS - (RING_INSETS[ring] + BUS_OFFSET)
        theta = math.radians(angle_deg)
        return (
            cx + radius * math.sin(theta),
            top_cy - radius * math.cos(theta),
        )

    l2_via = bus_point(1, -40.0)
    router.path(
        "/L2",
        (header_pads[1], (25.5, 9.6), (25.5, 17.0), l2_via),
        layer="B.Cu",
    )
    router.via("/L2", *l2_via)
    l3_via = bus_point(2, 0.0)
    router.path(
        "/L3",
        (header_pads[2], (26.7, 11.8), (26.7, 20.9), l3_via),
        layer="B.Cu",
    )
    router.via("/L3", *l3_via)
    # L1 threads between two ground vias of the outer ring's top arc.
    l1_via = bus_point(0, 45.0)
    router.path(
        "/L1",
        (header_pads[3], (29.4, 14.0), (33.9, 18.2), l1_via),
        layer="B.Cu",
    )
    router.via("/L1", *l1_via)
    # P1 pin 1 (GND) is a through-hole pad inside the back pour. That stem
    # pour patch is walled off by the three feeds plus the header pads, so
    # bridge it to the main pour over the empty front, threading between
    # two outer-ring units.
    stitch_a = (29.9, 9.4)
    stitch_b = (28.46, 14.81)
    router.via("/GND", *stitch_a)
    router.path(
        "/GND", (stitch_a, (29.9, 13.9), stitch_b), layer="F.Cu"
    )
    router.via("/GND", *stitch_b)

    return BoardLayout(
        placements=tuple(placements),
        segments=tuple(router.segments),
        vias=tuple(router.vias),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(part_rotation),
        zones=(("/GND", "B.Cu", (1.5, 1.5, BOARD_W - 1.5, BOARD_H - 1.5)),),
        outline=pear_outline(),
        graphics=pear_silk_graphics(BOARD_SHEET_ORIGIN_MM),
        hide_references=tuple(hidden),
    )


def generate_pear_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_pear_board_layout(netlist)
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    return netlist, layout
