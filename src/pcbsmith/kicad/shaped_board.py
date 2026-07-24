"""Art-board toolkit: shared primitives for shaped, artistic boards.

Extracted from the clover, pear, and metal-detector modules (hardening
plan 2.2) so the next shaped board is composed, not authored. Everything
here is stateless geometry or a small stateful builder; behavior is
pinned by the golden regeneration suite and the geometry-hash probes.

Contents:
- ``Router`` - collects track segments and vias from waypoint paths;
- ``Piece`` - an arc or line stretch of a path with exact
  ``(point, tangent, outward-normal)`` at any arc length;
- ``polyline_from_pieces`` / ``pitched_sites`` - sampling and pitch-based
  placement along piece paths;
- ``splice_rect_tab`` - cut a rectangular tab (stem / handle) into a
  closed outline polygon, choosing the wall insertion order from the
  winding automatically;
- silk primitives: filled polys, line, text, occlusion-clipped circle
  outlines, ellipse and circle sampling, mask-opening discs;
- ``placed_pad`` / ``NetLookup`` - the only sanctioned way to reference
  pad positions and pin nets ("no assumed geometry" principle);
- ``stitch_bridge`` - via + opposite-layer path + via, the standard cure
  for sealed pour cells.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardGenerationError,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
    rotate_offset,
)
from pcbsmith.kicad.board_mask import (
    mask_opening_disc_aperture as mask_opening_disc_aperture,
)
from pcbsmith.kicad.board_mask import (
    render_board_mask_aperture,
)
from pcbsmith.kicad.identity import stable_kicad_uuid

Point = tuple[float, float]

DEFAULT_SIGNAL_WIDTH_MM = 0.3


# ---------------------------------------------------------------------------
# Routing.


class Router:
    """Collects explicit waypoint routing into segments and vias."""

    def __init__(self) -> None:
        self.segments: list[TrackSegment] = []
        self.vias: list[ViaSpec] = []

    def path(
        self,
        net: str,
        points: Sequence[Point],
        *,
        layer: str,
        width: float = DEFAULT_SIGNAL_WIDTH_MM,
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

    def stitch_bridge(
        self,
        net: str,
        waypoints: Sequence[Point],
        *,
        layer: str,
        width: float = DEFAULT_SIGNAL_WIDTH_MM,
    ) -> None:
        """Via, path on the given layer, via: bridges a sealed pour cell
        over the opposite (free) layer - the clover/pear/detector cure."""
        self.via(net, *waypoints[0])
        self.path(net, waypoints, layer=layer, width=width)
        self.via(net, *waypoints[-1])


# ---------------------------------------------------------------------------
# Path pieces (from the pear's offset-ring model).


@dataclass(frozen=True)
class Piece:
    """One stretch of a path: an arc or a straight segment."""

    kind: str  # "arc" | "line"
    length: float
    radius: float  # local curvature radius (inf for lines)
    # Arc: (center, theta0, sweep). Line: (start, direction, outward).
    center: Point = (0.0, 0.0)
    theta0: float = 0.0
    sweep: float = 0.0
    start: Point = (0.0, 0.0)
    direction: Point = (0.0, 0.0)
    outward: Point = (0.0, 0.0)

    def at(self, s: float) -> tuple[Point, Point, Point]:
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


def polyline_from_pieces(
    pieces: Sequence[Piece], step_mm: float = 0.6
) -> list[Point]:
    points: list[Point] = []
    for piece in pieces:
        steps = max(2, math.ceil(piece.length / step_mm))
        for index in range(steps):
            point, _tangent, _outward = piece.at(piece.length * index / steps)
            points.append((round(point[0], 3), round(point[1], 3)))
    return points


@dataclass(frozen=True)
class PathSite:
    """A pitch-placed anchor on a piece path."""

    piece: Piece
    s: float


def pitched_sites(
    pieces: Sequence[Piece],
    *,
    pitch_mm: float,
    span_mm: float,
    min_radius_mm: float = 0.0,
) -> tuple[PathSite, ...]:
    """Evenly pitched sites, centred per piece, skipping stretches whose
    curvature radius is below ``min_radius_mm`` (tangential parts bend
    apart on tight arcs - pear lesson)."""
    sites: list[PathSite] = []
    for piece in pieces:
        if piece.radius < min_radius_mm:
            continue
        count = int(piece.length // pitch_mm)
        if count == 0:
            continue
        margin = (piece.length - count * pitch_mm) / 2 + (pitch_mm - span_mm) / 2
        for index in range(count):
            sites.append(PathSite(piece=piece, s=margin + index * pitch_mm))
    return tuple(sites)


# ---------------------------------------------------------------------------
# Outline tab splicing (clover stem / pear stem / detector handle).


def splice_rect_tab(
    points: Sequence[Point],
    *,
    center_x: float,
    half_width: float,
    end_y: float,
    join_y: float,
    zone_y: float | None = None,
    outward_up: bool,
) -> tuple[Point, ...]:
    """Replace the contiguous outline run inside the tab zone with the tab
    rectangle. ``outward_up`` says whether the tab extends toward -y;
    ``zone_y`` is the removal threshold (defaults to 2mm past the join,
    but e.g. the clover's zone starts at the leaf cusp above its join).

    The wall insertion order is chosen from the point BEFORE the zone, so
    the winding stays consistent regardless of traversal direction.
    """
    if zone_y is None:
        zone_y = join_y + 2.0 if outward_up else join_y - 2.0
    spliced: list[Point] = []
    done = False
    previous: Point | None = None
    for point in points:
        if outward_up:
            in_zone = abs(point[0] - center_x) < half_width and point[1] < zone_y
        else:
            in_zone = abs(point[0] - center_x) < half_width and point[1] > zone_y
        if in_zone:
            if not done:
                near_left = previous is not None and previous[0] < center_x
                first_x = center_x - half_width if near_left else center_x + half_width
                second_x = center_x + half_width if near_left else center_x - half_width
                spliced.extend(
                    (
                        (first_x, join_y),
                        (first_x, end_y),
                        (second_x, end_y),
                        (second_x, join_y),
                    )
                )
                done = True
            continue
        spliced.append(point)
        previous = point
    deduped: list[Point] = []
    for point in spliced:
        rounded = (round(point[0], 3), round(point[1], 3))
        if not deduped or rounded != deduped[-1]:
            deduped.append(rounded)
    if deduped and deduped[0] == deduped[-1]:
        deduped.pop()
    return tuple(deduped)


# ---------------------------------------------------------------------------
# Silk and mask primitives.


def circle_points(
    center: Point, radius: float, steps: int = 24
) -> list[Point]:
    return [
        (
            center[0] + radius * math.cos(2 * math.pi * step / steps),
            center[1] + radius * math.sin(2 * math.pi * step / steps),
        )
        for step in range(steps)
    ]


def ellipse_points(
    center: Point, rx: float, ry: float, steps: int = 48
) -> list[Point]:
    return [
        (
            center[0] + rx * math.cos(2 * math.pi * step / steps),
            center[1] + ry * math.sin(2 * math.pi * step / steps),
        )
        for step in range(steps)
    ]


def _absolute_identity_point(point: Point, origin: float) -> tuple[str, str]:
    return (f"{point[0] + origin:.3f}", f"{point[1] + origin:.3f}")


def _identity_number(value: float) -> str:
    return format(value, ".12g")


def _graphic_uuid(
    kind: str,
    identity: tuple[str, ...],
    occurrence: int,
) -> str:
    if occurrence < 0:
        raise ValueError("Graphic occurrence must be non-negative.")
    return stable_kicad_uuid(
        "board-graphic",
        kind,
        *identity,
        str(occurrence),
    )


def silk_poly(
    points: Sequence[Point],
    origin: float,
    *,
    occurrence: int = 0,
) -> str:
    absolute = tuple(_absolute_identity_point(point, origin) for point in points)
    rendered = "\n          ".join(
        f"(xy {x} {y})" for x, y in absolute
    )
    item_uuid = _graphic_uuid(
        "filled-polygon",
        (
            "F.SilkS",
            "stroke:0.12",
            "fill:yes",
            *(f"{x},{y}" for x, y in absolute),
        ),
        occurrence,
    )
    return f"""  (gr_poly
    (pts
          {rendered}
    )
    (stroke (width 0.12) (type solid))
    (fill yes)
    (layer "F.SilkS")
    (uuid {item_uuid})
  )"""


def silk_line(
    a: Point, b: Point, origin: float, width: float = 0.3,
    layer: str = "F.SilkS",
    *,
    occurrence: int = 0,
) -> str:
    rendered_a = _absolute_identity_point(a, origin)
    rendered_b = _absolute_identity_point(b, origin)
    canonical_start, canonical_end = sorted((rendered_a, rendered_b))
    item_uuid = _graphic_uuid(
        "line",
        (
            layer,
            f"stroke:{_identity_number(width)}",
            f"{canonical_start[0]},{canonical_start[1]}",
            f"{canonical_end[0]},{canonical_end[1]}",
        ),
        occurrence,
    )
    return f"""  (gr_line
    (start {rendered_a[0]} {rendered_a[1]})
    (end {rendered_b[0]} {rendered_b[1]})
    (stroke (width {width}) (type solid))
    (layer "{layer}")
    (uuid {item_uuid})
  )"""


def silk_text(
    text: str,
    at: Point,
    origin: float,
    size: float = 0.8,
    *,
    occurrence: int = 0,
    layer: str = "F.SilkS",
) -> str:
    rendered_at = _absolute_identity_point(at, origin)
    thickness = f"{size * 0.18:.2f}"
    justification = "\n      (justify mirror)" if layer.startswith("B.") else ""
    item_uuid = _graphic_uuid(
        "text",
        (
            layer,
            text,
            f"{rendered_at[0]},{rendered_at[1]}",
            f"size:{_identity_number(size)}",
            f"thickness:{thickness}",
        ),
        occurrence,
    )
    return f"""  (gr_text "{text}"
    (at {rendered_at[0]} {rendered_at[1]} 0)
    (layer "{layer}")
    (uuid {item_uuid})
    (effects
      (font
        (size {size} {size})
        (thickness {thickness})
      ){justification}
    )
  )"""


def clipped_circle_outline(
    center: Point,
    radius: float,
    occluders: tuple[tuple[Point, float], ...],
    origin: float,
    width: float = 0.35,
    steps: int = 72,
) -> list[str]:
    """Circle outline as gr_line chains, hiding stretches inside occluder
    discs (the worm's body-segment occlusion)."""
    points = circle_points(center, radius, steps=steps)
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
        lines.append(silk_line(points[index], points[following], origin, width))
    return lines


def mask_opening_disc(
    center: Point,
    radius: float,
    origin: float,
    *,
    occurrence: int = 0,
) -> str:
    """Filled polygon on F.Mask = soldermask opening (rule 9.3)."""
    aperture = mask_opening_disc_aperture(
        center,
        radius,
        occurrence=occurrence,
    )
    return render_board_mask_aperture(
        aperture,
        origin,
        occurrence=occurrence,
    )


# ---------------------------------------------------------------------------
# Pads and nets ("no assumed geometry").


def back_offset(local: Point, rotation: float) -> Point:
    """Back-side placement: INVERSE angle, then x-mirror (clover lesson)."""
    dx, dy = rotate_offset(local[0], local[1], (360.0 - rotation) % 360.0)
    return (-dx, dy)


def placed_pad(
    footprint: str,
    pin: str,
    *,
    anchor: Point,
    rotation: float = 0.0,
    flipped: bool = False,
) -> Point:
    """The physical position of a pad, computed from the library."""
    pad = FOOTPRINT_LIBRARY[footprint].pads_named(pin)[0]
    if flipped:
        dx, dy = back_offset((pad.x_mm, pad.y_mm), rotation)
    else:
        dx, dy = rotate_offset(pad.x_mm, pad.y_mm, rotation)
    return (round(anchor[0] + dx, 4), round(anchor[1] + dy, 4))


class NetLookup:
    """Pin-to-net queries with loud failures (never wire by assumption)."""

    def __init__(self, netlist: BoardNetlist) -> None:
        self._net_of = {
            (reference, pin): net.name
            for net in netlist.nets
            for reference, pin in net.nodes
        }

    def net(self, reference: str, pin: str) -> str:
        name = self._net_of.get((reference, pin))
        if name is None:
            raise BoardGenerationError(f"{reference}.{pin} has no net.")
        return name

    def expect(self, reference: str, pin: str, expected: str) -> None:
        actual = self.net(reference, pin)
        if actual != expected:
            raise BoardGenerationError(
                f"{reference}.{pin} is on {actual}, expected {expected}."
            )

    def pin_on(self, reference: str, net_name: str, pins: Sequence[str] = ("1", "2")) -> str:
        for pin in pins:
            if self._net_of.get((reference, pin)) == net_name:
                return pin
        raise BoardGenerationError(f"{reference} has no pin on {net_name}.")
