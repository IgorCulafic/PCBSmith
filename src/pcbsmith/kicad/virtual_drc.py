"""Virtual DRC: fast geometric pre-checks over a BoardLayout.

Covers the failure classes that consumed most live-DRC iterations on the
challenge boards: courtyard overlap, cross-net copper clearance (which
subsumes track crossings at distance zero), and copper-to-edge clearance.

Modelling choice: every copper item is a THICK SEGMENT (a stadium - a
segment with a radius). Tracks map exactly; vias are zero-length stadia;
pads are stadia along their long axis with radius min(w, h)/2, which
UNDERESTIMATES rectangular pad corners by up to (sqrt(2)-1)*min/2. That
bias is deliberate: the pre-filter must never block a board kicad-cli
would pass. kicad-cli DRC remains the authority; this module exists so
iteration failures surface in milliseconds instead of a full KiCad round
trip, and so fixes can eventually be machine-proposed (hardening plan
2.1). Zones are not modelled (they clip themselves against everything).

Everything here is a narrow, JSON-serializable tool surface by design
(plan Track 5): `run_virtual_drc(layout, netlist) -> findings`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
    rotate_offset,
)

CLEARANCE_MM = 0.2
EDGE_CLEARANCE_MM = 0.5
VIA_RADIUS_MM = 0.3
# KiCad's hole-to-copper rule is 0.25mm - 0.05 wider than the copper
# clearance. Net-less hole obstacles carry the excess in their radius
# so the ordinary clearance machinery enforces the stricter rule.
HOLE_EXTRA_MM = 0.25 - CLEARANCE_MM
# Modelling tolerance: only flag violations deeper than this, so roundrect
# corner radii and float noise never produce a false positive.
TOLERANCE_MM = 0.05
# KiCad board-setup constraint written by render_board_from_layout:
# silkscreen text below this height fails kicad-cli DRC (text_height).
MIN_SILK_TEXT_SIZE_MM = 0.8
_GRID_CELL_MM = 4.0

Point = tuple[float, float]


@dataclass(frozen=True)
class VirtualDrcFinding:
    check: str  # courtyard_overlap | copper_clearance | edge_clearance
    message: str
    x_mm: float
    y_mm: float

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "message": self.message,
            "x_mm": round(self.x_mm, 3),
            "y_mm": round(self.y_mm, 3),
        }


@dataclass(frozen=True)
class _Stadium:
    """A copper item: segment (a == b for circles) plus a radius."""

    a: Point
    b: Point
    radius: float
    net: str
    layer: str  # "F.Cu" | "B.Cu"
    owner: str  # footprint reference for pads, "" for tracks/vias
    label: str


# ---------------------------------------------------------------------------
# Scalar geometry.


def _seg_seg_distance(
    a1: Point, a2: Point, b1: Point, b2: Point
) -> float:
    if _segments_cross(a1, a2, b1, b2):
        return 0.0
    return min(
        _point_seg_distance(a1, b1, b2),
        _point_seg_distance(a2, b1, b2),
        _point_seg_distance(b1, a1, a2),
        _point_seg_distance(b2, a1, a2),
    )


def _point_seg_distance(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _segments_cross(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1 = orient(b1, b2, a1)
    d2 = orient(b1, b2, a2)
    d3 = orient(a1, a2, b1)
    d4 = orient(a1, a2, b2)
    return d1 * d2 < 0 and d3 * d4 < 0


def _polygons_overlap(poly_a: list[Point], poly_b: list[Point]) -> bool:
    """Separating-axis test for convex polygons."""
    for polygon_one, polygon_two in ((poly_a, poly_b), (poly_b, poly_a)):
        count = len(polygon_one)
        for index in range(count):
            x1, y1 = polygon_one[index]
            x2, y2 = polygon_one[(index + 1) % count]
            axis = (y1 - y2, x2 - x1)
            projections_one = [
                axis[0] * x + axis[1] * y for x, y in polygon_one
            ]
            projections_two = [
                axis[0] * x + axis[1] * y for x, y in polygon_two
            ]
            if (
                max(projections_one) <= min(projections_two)
                or max(projections_two) <= min(projections_one)
            ):
                return False
    return True


def _point_in_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    x, y = point
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x_cross > x:
                inside = not inside
    return inside


def _back_offset(local: Point, rotation: float) -> Point:
    """Back-side placement: inverse angle, then x-mirror (clover lesson)."""
    dx, dy = rotate_offset(local[0], local[1], (360.0 - rotation) % 360.0)
    return (-dx, dy)


# ---------------------------------------------------------------------------
# Item collection.


def _placed(
    anchor: Point, rotation: float, local: Point, flipped: bool
) -> Point:
    if flipped:
        dx, dy = _back_offset(local, rotation)
    else:
        dx, dy = rotate_offset(local[0], local[1], rotation)
    return (anchor[0] + dx, anchor[1] + dy)


def _collect_items(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    cover_rect_pads: bool = False,
) -> list[_Stadium]:
    """Model the board's copper as stadiums.

    Default radii UNDERESTIMATE rect-family pads (their corners stick
    out past the stadium), keeping the virtual DRC free of false
    positives against KiCad's exact shapes. ``cover_rect_pads=True``
    inflates rect/roundrect radii to min_dim/sqrt(2) so the corners are
    fully covered - the router uses this for FOREIGN obstacles, after
    kicad-cli caught corner-cutting routes the honest model allowed.
    """
    net_of = {
        (reference, pin): net.name
        for net in netlist.nets
        for reference, pin in net.nodes
    }
    items: list[_Stadium] = []
    for component, anchor_x in layout.placements:
        reference = component.reference
        spec = FOOTPRINT_LIBRARY[component.footprint]
        rotation = placement_rotation(layout, reference)
        anchor = (anchor_x, placement_y(layout, reference))
        flipped = reference in layout.part_flip
        for pad in spec.pads:
            if not pad.name and pad.drill_mm <= 0:
                # Unnamed paste/thermal pads take the net of the named pad
                # they overlap at embed time; the named pad models them.
                # Unnamed DRILLED pads (USB-C shell alignment holes) fall
                # through: the hole is a physical obstacle even without
                # copper - kicad-cli caught tracks routed across them.
                continue
            if pad.kind == "npth" or not pad.name:
                net = f"~hole:{reference}"
            else:
                net = net_of.get(
                    (reference, pad.name), f"~nc:{reference}.{pad.name}"
                )
            width_mm = pad.width_mm
            height_mm = pad.height_mm
            if net.startswith("~hole:"):
                # The obstacle is the HOLE (plus slot copper if any),
                # inflated so plain clearance math enforces KiCad's
                # 0.25mm hole-to-copper rule.
                width_mm = max(width_mm, pad.drill_mm) + 2 * HOLE_EXTRA_MM
                height_mm = max(height_mm, pad.drill_mm) + 2 * HOLE_EXTRA_MM
            half_long = (max(width_mm, height_mm) - min(
                width_mm, height_mm
            )) / 2
            radius = min(width_mm, height_mm) / 2
            # Custom pads carry primitive-bbox extents (library.py);
            # official-library customs are solid EP polygons, so the
            # stadium stays inside the copper like a plain rect.
            if cover_rect_pads and pad.shape in ("rect", "custom"):
                radius = min(width_mm, height_mm) / math.sqrt(2)
            elif cover_rect_pads and pad.shape == "roundrect":
                # A roundrect's corners are pulled in by the corner
                # radius (KiCad default ratio 0.25 of the short side):
                # exact extent = min/2 + rr*(sqrt(2)-1). The blanket
                # rect formula over-covered by ~17% and walled the ONLY
                # legal entry into 0.5mm-pitch USB-C data pads
                # (measured on the thermometer board).
                short = min(width_mm, height_mm)
                corner = 0.25 * short
                radius = short / 2 + corner * (math.sqrt(2) - 1)
            axis = (half_long, 0.0) if width_mm >= height_mm else (0.0, half_long)
            # The pad's own angle rotates its body within the footprint.
            axis = rotate_offset(axis[0], axis[1], pad.angle_deg)
            ends_local = (
                (pad.x_mm - axis[0], pad.y_mm - axis[1]),
                (pad.x_mm + axis[0], pad.y_mm + axis[1]),
            )
            a = _placed(anchor, rotation, ends_local[0], flipped)
            b = _placed(anchor, rotation, ends_local[1], flipped)
            layers: tuple[str, ...]
            if pad.drill_mm > 0:
                layers = ("F.Cu", "B.Cu")
            else:
                layers = ("B.Cu",) if flipped else ("F.Cu",)
            for layer in layers:
                items.append(
                    _Stadium(
                        a=a, b=b, radius=radius, net=net, layer=layer,
                        owner=reference,
                        label=f"pad {reference}.{pad.name} [{net}]",
                    )
                )
    for segment in layout.segments:
        items.append(
            _Stadium(
                a=(segment.x1, segment.y1),
                b=(segment.x2, segment.y2),
                radius=segment.width_mm / 2,
                net=segment.net_name,
                layer=segment.layer,
                owner="",
                label=f"track [{segment.net_name}] on {segment.layer}",
            )
        )
    for via in layout.vias:
        for layer in ("F.Cu", "B.Cu"):
            items.append(
                _Stadium(
                    a=(via.x, via.y), b=(via.x, via.y),
                    radius=VIA_RADIUS_MM, net=via.net_name, layer=layer,
                    owner="",
                    label=f"via [{via.net_name}]",
                )
            )
    return items


def _grid_key(x: float, y: float) -> tuple[int, int]:
    return (int(x // _GRID_CELL_MM), int(y // _GRID_CELL_MM))


def _grid_cells(item: _Stadium, inflate: float) -> list[tuple[int, int]]:
    x_min = min(item.a[0], item.b[0]) - item.radius - inflate
    x_max = max(item.a[0], item.b[0]) + item.radius + inflate
    y_min = min(item.a[1], item.b[1]) - item.radius - inflate
    y_max = max(item.a[1], item.b[1]) + item.radius + inflate
    x_lo, y_lo = _grid_key(x_min, y_min)
    x_hi, y_hi = _grid_key(x_max, y_max)
    return [
        (cell_x, cell_y)
        for cell_x in range(x_lo, x_hi + 1)
        for cell_y in range(y_lo, y_hi + 1)
    ]


# ---------------------------------------------------------------------------
# Checks.


def _check_copper_clearance(items: list[_Stadium]) -> list[VirtualDrcFinding]:
    findings: list[VirtualDrcFinding] = []
    grid: dict[tuple[int, int], list[int]] = {}
    for index, item in enumerate(items):
        for cell in _grid_cells(item, CLEARANCE_MM):
            grid.setdefault(cell, []).append(index)
    seen: set[tuple[int, int]] = set()
    for bucket in grid.values():
        for position, first in enumerate(bucket):
            for second in bucket[position + 1:]:
                pair = (min(first, second), max(first, second))
                if pair in seen:
                    continue
                seen.add(pair)
                one, two = items[first], items[second]
                if one.layer != two.layer or one.net == two.net:
                    continue
                # KiCad does not check pad pairs within one footprint
                # (net ties and multi-net packages are legal).
                if one.owner and one.owner == two.owner:
                    continue
                required = one.radius + two.radius + CLEARANCE_MM
                distance = _seg_seg_distance(one.a, one.b, two.a, two.b)
                if distance < required - TOLERANCE_MM:
                    midpoint = (
                        (one.a[0] + one.b[0] + two.a[0] + two.b[0]) / 4,
                        (one.a[1] + one.b[1] + two.a[1] + two.b[1]) / 4,
                    )
                    kind = "short" if distance < one.radius + two.radius else "clearance"
                    findings.append(
                        VirtualDrcFinding(
                            check="copper_clearance",
                            message=(
                                f"{kind}: {one.label} vs {two.label}: "
                                f"{distance:.3f}mm (needs {required:.3f}mm)"
                            ),
                            x_mm=midpoint[0],
                            y_mm=midpoint[1],
                        )
                    )
    return findings


def _courtyard_polygon(
    layout: BoardLayout, reference: str, anchor: Point
) -> list[Point] | None:
    component = next(
        component
        for component, _x in layout.placements
        if component.reference == reference
    )
    spec = FOOTPRINT_LIBRARY[component.footprint]
    rotation = placement_rotation(layout, reference)
    flipped = reference in layout.part_flip
    if spec.courtyard_hull is not None:
        # The exact F.CrtYd convex hull, pulled toward its centroid by a
        # hair so float noise on a deliberate edge-to-edge placement does
        # not false-positive (kicad-cli remains the authority).
        hull = spec.courtyard_hull
        cx = sum(x for x, _ in hull) / len(hull)
        cy = sum(y for _, y in hull) / len(hull)
        shrink = 0.02
        pulled = []
        for x, y in hull:
            distance = math.hypot(x - cx, y - cy)
            factor = max(0.0, 1.0 - shrink / distance) if distance else 0.0
            pulled.append((cx + (x - cx) * factor, cy + (y - cy) * factor))
        return [
            _placed(anchor, rotation, corner, flipped) for corner in pulled
        ]
    # No courtyard drawn: FAB body plus the standard 0.25mm margin. The
    # measured bounds would include silk overhangs and false-positive;
    # underestimating is the pre-filter contract.
    x1, y1, x2, y2 = spec.fab_rect
    margin = 0.25
    corners = (
        (x1 - margin, y1 - margin),
        (x2 + margin, y1 - margin),
        (x2 + margin, y2 + margin),
        (x1 - margin, y2 + margin),
    )
    return [_placed(anchor, rotation, corner, flipped) for corner in corners]


def _check_courtyards(layout: BoardLayout) -> list[VirtualDrcFinding]:
    findings: list[VirtualDrcFinding] = []
    polys: list[tuple[str, bool, list[Point]]] = []
    for component, anchor_x in layout.placements:
        reference = component.reference
        anchor = (anchor_x, placement_y(layout, reference))
        polygon = _courtyard_polygon(layout, reference, anchor)
        if polygon is not None:
            polys.append(
                (reference, reference in layout.part_flip, polygon)
            )
    for index, (ref_one, flip_one, poly_one) in enumerate(polys):
        for ref_two, flip_two, poly_two in polys[index + 1:]:
            if flip_one != flip_two:
                continue  # courtyards live on per-side layers
            if _polygons_overlap(poly_one, poly_two):
                center = (
                    sum(x for x, _ in poly_one) / len(poly_one),
                    sum(y for _, y in poly_one) / len(poly_one),
                )
                findings.append(
                    VirtualDrcFinding(
                        check="courtyard_overlap",
                        message=f"courtyards of {ref_one} and {ref_two} overlap",
                        x_mm=center[0],
                        y_mm=center[1],
                    )
                )
    return findings


def _check_edge_clearance(
    items: list[_Stadium], layout: BoardLayout
) -> list[VirtualDrcFinding]:
    if layout.outline:
        outline: tuple[Point, ...] = layout.outline
    else:
        outline = (
            (0.0, 0.0),
            (layout.width_mm, 0.0),
            (layout.width_mm, layout.height_mm),
            (0.0, layout.height_mm),
        )
    edges = [
        (outline[index], outline[(index + 1) % len(outline)])
        for index in range(len(outline))
    ]
    edge_grid: dict[tuple[int, int], list[int]] = {}
    for index, (a, b) in enumerate(edges):
        fake = _Stadium(a=a, b=b, radius=0.0, net="", layer="", owner="", label="")
        for cell in _grid_cells(fake, EDGE_CLEARANCE_MM + 1.0):
            edge_grid.setdefault(cell, []).append(index)
    findings: list[VirtualDrcFinding] = []
    reported: set[str] = set()
    for item in items:
        if item.net.startswith("~hole:"):
            # Copper-edge clearance governs COPPER; a bare hole near
            # (or straddling) the outline is the footprint's business.
            continue
        midpoint = (
            (item.a[0] + item.b[0]) / 2,
            (item.a[1] + item.b[1]) / 2,
        )
        if not _point_in_polygon(midpoint, outline):
            key = f"outside:{item.label}:{round(midpoint[0], 1)}"
            if key not in reported:
                reported.add(key)
                findings.append(
                    VirtualDrcFinding(
                        check="edge_clearance",
                        message=f"{item.label} lies outside the board outline",
                        x_mm=midpoint[0],
                        y_mm=midpoint[1],
                    )
                )
            continue
        candidates: set[int] = set()
        for cell in _grid_cells(item, EDGE_CLEARANCE_MM):
            candidates.update(edge_grid.get(cell, ()))
        required = item.radius + EDGE_CLEARANCE_MM
        for edge_index in candidates:
            a, b = edges[edge_index]
            distance = _seg_seg_distance(item.a, item.b, a, b)
            if distance < required - TOLERANCE_MM:
                key = f"edge:{item.label}:{round(midpoint[0], 1)},{round(midpoint[1], 1)}"
                if key not in reported:
                    reported.add(key)
                    findings.append(
                        VirtualDrcFinding(
                            check="edge_clearance",
                            message=(
                                f"{item.label} is {distance:.3f}mm from the "
                                f"board edge (needs {required:.3f}mm)"
                            ),
                            x_mm=midpoint[0],
                            y_mm=midpoint[1],
                        )
                    )
                break
    return findings


def _check_pour_connectivity(
    items: list[_Stadium], layout: BoardLayout
) -> list[VirtualDrcFinding]:
    """The sealed-pour-cell class (most expensive live-DRC lesson): a
    zone region walled off by foreign copper that still contains
    same-net pads/vias fills as an island and strands them.

    Grid flood-fill per zone: cells blocked where foreign copper plus
    zone clearance reaches; regions that hold zone-net items but not the
    largest region are reported. Coarse by design - the 0.35mm margin
    keeps legal narrow channels open so a clean board never flags."""
    ZONE_CLEARANCE = 0.5
    GRID = 0.5
    findings: list[VirtualDrcFinding] = []
    for zone_net, zone_layer, rect in layout.zones:
        x1, y1, x2, y2 = rect
        columns = max(2, int((x2 - x1) / GRID))
        rows = max(2, int((y2 - y1) / GRID))
        blocked = [[False] * columns for _ in range(rows)]
        blockers = [
            item for item in items
            if item.layer == zone_layer and item.net != zone_net
        ]
        for item in blockers:
            reach = item.radius + ZONE_CLEARANCE - 0.35
            min_col = max(0, int((min(item.a[0], item.b[0]) - reach - x1) / GRID))
            max_col = min(columns - 1, int((max(item.a[0], item.b[0]) + reach - x1) / GRID))
            min_row = max(0, int((min(item.a[1], item.b[1]) - reach - y1) / GRID))
            max_row = min(rows - 1, int((max(item.a[1], item.b[1]) + reach - y1) / GRID))
            for row in range(min_row, max_row + 1):
                for col in range(min_col, max_col + 1):
                    center = (x1 + (col + 0.5) * GRID, y1 + (row + 0.5) * GRID)
                    if _point_seg_distance(center, item.a, item.b) < reach:
                        blocked[row][col] = True
        # Flood-fill the free cells into regions.
        region = [[-1] * columns for _ in range(rows)]
        region_count = 0
        sizes: list[int] = []
        for row in range(rows):
            for col in range(columns):
                if blocked[row][col] or region[row][col] != -1:
                    continue
                stack = [(row, col)]
                region[row][col] = region_count
                size = 0
                while stack:
                    r, c = stack.pop()
                    size += 1
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = r + dr, c + dc
                        if (
                            0 <= nr < rows and 0 <= nc < columns
                            and not blocked[nr][nc] and region[nr][nc] == -1
                        ):
                            region[nr][nc] = region_count
                            stack.append((nr, nc))
                sizes.append(size)
                region_count += 1
        if region_count <= 1:
            continue
        main_region = sizes.index(max(sizes))
        # A pad that touches same-net TRACK copper does not depend on
        # the pour; a sealed cell around it is a harmless island KiCad
        # removes. Only pour-dependent items are stranded. THT pads
        # conduct through the barrel, so contact on either layer copy
        # clears the physical pad.
        tracks = [
            item for item in items
            if item.net == zone_net and not item.owner
        ]
        segments_only = [t for t in tracks if t.a != t.b]
        trace_connected = {
            (item.label, item.a)
            for item in items
            if item.net == zone_net
            and (item.owner or item.a == item.b)  # pads and vias
            and any(
                track.layer == item.layer
                and _seg_seg_distance(item.a, item.b, track.a, track.b)
                <= item.radius + track.radius + TOLERANCE_MM
                for track in segments_only
            )
        }

        # Zone-net items in a non-main region are stranded.
        for item in items:
            if item.layer != zone_layer or item.net != zone_net:
                continue
            if (item.label, item.a) in trace_connected:
                continue
            if item.owner == "" and item.a == item.b:
                pass  # vias participate
            elif item.owner == "":
                continue  # tracks bridge cells themselves; pads/vias matter
            mid = ((item.a[0] + item.b[0]) / 2, (item.a[1] + item.b[1]) / 2)
            col = int((mid[0] - x1) / GRID)
            row = int((mid[1] - y1) / GRID)
            if not (0 <= row < rows and 0 <= col < columns):
                continue
            if blocked[row][col] or region[row][col] in (-1, main_region):
                continue
            findings.append(
                VirtualDrcFinding(
                    check="pour_connectivity",
                    message=(
                        f"{item.label} sits in a pour cell of zone "
                        f"[{zone_net}] on {zone_layer} sealed off from the "
                        "main region; add a stitch bridge over the free "
                        "layer or open a channel."
                    ),
                    x_mm=mid[0],
                    y_mm=mid[1],
                )
            )
    return findings


def _check_pad_connectivity(
    items: list[_Stadium], layout: BoardLayout
) -> list[VirtualDrcFinding]:
    """Every physical pad of a multi-pad net must touch same-net copper
    (track, via, abutting pad, or a same-net zone under it).

    KiCad's ratsnest works per physical pad, so duplicate pad numbers
    (SW_PUSH carries two "1" pads) each need copper; a label-level view
    misses the twins - caught live by kicad-cli on the servo board."""
    zone_rects: dict[tuple[str, str], list[_Rect]] = {}
    for zone_net, zone_layer, rect in layout.zones:
        zone_rects.setdefault((zone_net, zone_layer), []).append(rect)

    copper: dict[tuple[str, str], list[_Stadium]] = {}
    for item in items:
        if item.net.startswith("~"):
            continue
        copper.setdefault((item.net, item.layer), []).append(item)

    pad_counts: dict[str, set[tuple[str, Point]]] = {}
    for item in items:
        if item.owner and not item.net.startswith("~"):
            pad_counts.setdefault(item.net, set()).add((item.label, item.a))

    def _pad_connected(pad: _Stadium) -> bool:
        for rect in zone_rects.get((pad.net, pad.layer), ()):
            if rect[0] <= pad.a[0] <= rect[2] and rect[1] <= pad.a[1] <= rect[3]:
                return True
        for other in copper.get((pad.net, pad.layer), ()):
            if other is pad:
                continue
            if other.label == pad.label and other.a == pad.a:
                continue  # the THT twin is the same physical pad
            distance = _seg_seg_distance(pad.a, pad.b, other.a, other.b)
            if distance <= pad.radius + other.radius + TOLERANCE_MM:
                return True
        return False

    findings: list[VirtualDrcFinding] = []
    # Group the per-layer copies of each physical pad: connected on any
    # layer is connected.
    by_pad: dict[tuple[str, Point], list[_Stadium]] = {}
    for item in items:
        if item.owner and not item.net.startswith("~"):
            by_pad.setdefault((item.label, item.a), []).append(item)
    for (label, anchor), copies in sorted(by_pad.items()):
        net = copies[0].net
        if len(pad_counts.get(net, ())) < 2:
            continue  # single-pad nets have nothing to reach
        if any(_pad_connected(copy) for copy in copies):
            continue
        findings.append(
            VirtualDrcFinding(
                check="pad_connectivity",
                message=(
                    f"{label} has no same-net copper touching it; KiCad "
                    "will report a missing connection."
                ),
                x_mm=anchor[0],
                y_mm=anchor[1],
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Silkscreen model. KiCad flags silk-over-copper (pads) and overlapping silk
# items; before this model those only surfaced after a full kicad-cli round
# trip (the flyback burned six of them on reference labels alone). Text
# extents are ESTIMATED (stroke font), so boxes are deliberately shrunk —
# underestimating is the pre-filter contract.

_TEXT_CHAR_HALF_W = 0.4   # per character, x font size (KiCad advance ~1.0)
_TEXT_HALF_H = 0.55       # x font size
_DEFAULT_REF_SIZE = 1.27

_Rect = tuple[float, float, float, float]  # x1, y1, x2, y2


@dataclass(frozen=True)
class _SilkText:
    box: _Rect
    side: str
    owner: str  # footprint reference for labels, "" for board texts
    label: str
    size: float = 1.0


@dataclass(frozen=True)
class _SilkLine:
    a: Point
    b: Point
    half_width: float
    side: str
    label: str


_GR_TEXT_RE = re.compile(
    r'\(gr_text\s+"((?:[^"\\]|\\.)*)"\s*\(at\s+([-\d.]+)\s+([-\d.]+)',
)
_GR_TEXT_SIZE_RE = re.compile(r"\(size\s+([-\d.]+)\s+[-\d.]+\)")
_GR_LINE_RE = re.compile(
    r"\(gr_line\s*\(start\s+([-\d.]+)\s+([-\d.]+)\)\s*"
    r"\(end\s+([-\d.]+)\s+([-\d.]+)\)\s*"
    r"\(stroke\s*\(width\s+([-\d.]+)\)",
)


def _text_box(
    center: Point, text: str, size: float, upright_swap: bool
) -> _Rect:
    half_w = max(len(text), 1) * size * _TEXT_CHAR_HALF_W
    half_h = size * _TEXT_HALF_H
    if upright_swap:
        half_w, half_h = half_h, half_w
    return (
        center[0] - half_w, center[1] - half_h,
        center[0] + half_w, center[1] + half_h,
    )


def _rects_overlap_depth(one: _Rect, two: _Rect) -> float:
    dx = min(one[2], two[2]) - max(one[0], two[0])
    dy = min(one[3], two[3]) - max(one[1], two[1])
    return min(dx, dy)


def _point_rect_distance(point: Point, rect: _Rect) -> float:
    dx = max(rect[0] - point[0], 0.0, point[0] - rect[2])
    dy = max(rect[1] - point[1], 0.0, point[1] - rect[3])
    return math.hypot(dx, dy)


def _seg_rect_distance(a: Point, b: Point, rect: _Rect) -> float:
    if rect[0] <= a[0] <= rect[2] and rect[1] <= a[1] <= rect[3]:
        return 0.0
    if rect[0] <= b[0] <= rect[2] and rect[1] <= b[1] <= rect[3]:
        return 0.0
    corners = (
        (rect[0], rect[1]), (rect[2], rect[1]),
        (rect[2], rect[3]), (rect[0], rect[3]),
    )
    return min(
        _seg_seg_distance(a, b, corners[index], corners[(index + 1) % 4])
        for index in range(4)
    )


def _collect_silk_texts(layout: BoardLayout) -> list[_SilkText]:
    from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM

    texts: list[_SilkText] = []
    overrides = dict(layout.part_reference_at)
    for component, anchor_x in layout.placements:
        reference = component.reference
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if spec.board_only or reference in layout.hide_references:
            continue
        rotation = placement_rotation(layout, reference)
        flipped = reference in layout.part_flip
        override = overrides.get(reference)
        if override is not None:
            local = (override[0], override[1])
            total_angle = override[2]
            size = (
                spec.reference_label[2]
                if spec.reference_label
                else _DEFAULT_REF_SIZE
            )
        elif spec.reference_label is not None:
            local = (spec.reference_label[0], spec.reference_label[1])
            total_angle = rotation
            size = spec.reference_label[2]
        else:
            continue
        center = _placed(
            (anchor_x, placement_y(layout, reference)),
            rotation, local, flipped,
        )
        texts.append(
            _SilkText(
                box=_text_box(
                    center, reference, size,
                    upright_swap=round(total_angle) % 180 == 90,
                ),
                side="B" if flipped else "F",
                owner=reference,
                label=f"reference label {reference}",
                size=size,
            )
        )
    for graphic in layout.graphics:
        if '"F.SilkS"' not in graphic:
            continue
        for match in _GR_TEXT_RE.finditer(graphic):
            text = match.group(1)
            center = (
                float(match.group(2)) - BOARD_SHEET_ORIGIN_MM,
                float(match.group(3)) - BOARD_SHEET_ORIGIN_MM,
            )
            size_match = _GR_TEXT_SIZE_RE.search(graphic, match.end())
            size = float(size_match.group(1)) if size_match else 1.0
            texts.append(
                _SilkText(
                    box=_text_box(center, text, size, upright_swap=False),
                    side="F",
                    owner="",
                    label=f"silk text '{text}'",
                    size=size,
                )
            )
    return texts


def _collect_silk_lines(layout: BoardLayout) -> list[_SilkLine]:
    from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM

    lines: list[_SilkLine] = []
    for graphic in layout.graphics:
        if '"F.SilkS"' not in graphic:
            continue
        for match in _GR_LINE_RE.finditer(graphic):
            lines.append(
                _SilkLine(
                    a=(
                        float(match.group(1)) - BOARD_SHEET_ORIGIN_MM,
                        float(match.group(2)) - BOARD_SHEET_ORIGIN_MM,
                    ),
                    b=(
                        float(match.group(3)) - BOARD_SHEET_ORIGIN_MM,
                        float(match.group(4)) - BOARD_SHEET_ORIGIN_MM,
                    ),
                    half_width=float(match.group(5)) / 2.0,
                    side="F",
                    label="silk line",
                )
            )
    return lines


def _body_polys(layout: BoardLayout) -> list[tuple[str, str, list[Point]]]:
    """(reference, side, placed fab hull) — the fab body underestimates
    the silk outline drawn just outside it. A hull, not a bbox: round
    can bodies would otherwise flag labels near their corners."""
    polys: list[tuple[str, str, list[Point]]] = []
    for component, anchor_x in layout.placements:
        reference = component.reference
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if spec.board_only:
            continue
        rotation = placement_rotation(layout, reference)
        flipped = reference in layout.part_flip
        anchor = (anchor_x, placement_y(layout, reference))
        if spec.fab_hull is not None:
            local_points: tuple[tuple[float, float], ...] = spec.fab_hull
        else:
            x1, y1, x2, y2 = spec.fab_rect
            local_points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        polys.append(
            (
                reference,
                "B" if flipped else "F",
                [
                    _placed(anchor, rotation, point, flipped)
                    for point in local_points
                ],
            )
        )
    return polys


def _rect_poly_overlap_depth(rect: _Rect, poly: list[Point]) -> float:
    """Positive when the rect penetrates the convex polygon; measured as
    the deepest rect corner/edge inside, approximated via SAT margins."""
    corners = [
        (rect[0], rect[1]), (rect[2], rect[1]),
        (rect[2], rect[3]), (rect[0], rect[3]),
    ]
    if not _polygons_overlap(corners, poly):
        return 0.0
    # Depth along the polygon edge normals: the smallest penetration.
    depth = float("inf")
    count = len(poly)
    for index in range(count):
        x1, y1 = poly[index]
        x2, y2 = poly[(index + 1) % count]
        nx, ny = y1 - y2, x2 - x1
        length = math.hypot(nx, ny)
        if length == 0:
            continue
        nx, ny = nx / length, ny / length
        poly_proj = [nx * x + ny * y for x, y in poly]
        rect_proj = [nx * x + ny * y for x, y in corners]
        overlap = min(
            max(poly_proj) - min(rect_proj),
            max(rect_proj) - min(poly_proj),
        )
        depth = min(depth, overlap)
    return depth if depth != float("inf") else 0.0


def _seg_poly_distance(a: Point, b: Point, poly: list[Point]) -> float:
    if _point_in_polygon(a, tuple(poly)) or _point_in_polygon(b, tuple(poly)):
        return 0.0
    count = len(poly)
    return min(
        _seg_seg_distance(a, b, poly[index], poly[(index + 1) % count])
        for index in range(count)
    )


def _check_silkscreen(
    layout: BoardLayout, items: list[_Stadium]
) -> list[VirtualDrcFinding]:
    texts = _collect_silk_texts(layout)
    lines = _collect_silk_lines(layout)
    bodies = _body_polys(layout)
    # ~hole: items carry no copper/mask aperture in the model - keep
    # the silk checks strictly underestimating.
    pads = [
        item for item in items
        if item.owner and not item.net.startswith("~hole:")
    ]
    findings: list[VirtualDrcFinding] = []

    def report(check: str, message: str, at: Point) -> None:
        findings.append(
            VirtualDrcFinding(
                check=check, message=message, x_mm=at[0], y_mm=at[1]
            )
        )

    for text in texts:
        center = (
            (text.box[0] + text.box[2]) / 2,
            (text.box[1] + text.box[3]) / 2,
        )
        # KiCad board-setup constraint: silk text below the minimum
        # height fails DRC outright (caught live on the servo board).
        if text.size < MIN_SILK_TEXT_SIZE_MM - TOLERANCE_MM:
            report(
                "silk_text_height",
                f"{text.label} height {text.size:g}mm is below the "
                f"{MIN_SILK_TEXT_SIZE_MM}mm board minimum",
                center,
            )
        # Silk clipped by the board edge (rotated connector reference
        # labels walk off small boards; caught live by kicad-cli).
        if (
            text.box[0] < -TOLERANCE_MM
            or text.box[1] < -TOLERANCE_MM
            or text.box[2] > layout.width_mm + TOLERANCE_MM
            or text.box[3] > layout.height_mm + TOLERANCE_MM
        ):
            report(
                "silk_edge_clearance",
                f"{text.label} is clipped by the board edge",
                center,
            )
        for reference, side, poly in bodies:
            if side != text.side or reference == text.owner:
                continue
            if _rect_poly_overlap_depth(text.box, poly) > TOLERANCE_MM:
                report(
                    "silk_overlap",
                    f"{text.label} overlaps the body of {reference}",
                    center,
                )
        for pad in pads:
            layer = "B.Cu" if text.side == "B" else "F.Cu"
            if pad.layer != layer or pad.owner == text.owner:
                continue
            distance = min(
                _point_rect_distance(pad.a, text.box),
                _point_rect_distance(pad.b, text.box),
            )
            if distance < pad.radius - TOLERANCE_MM:
                report(
                    "silk_over_pad",
                    f"{text.label} sits on {pad.label}",
                    center,
                )
                break
    for index, text in enumerate(texts):
        for other in texts[index + 1:]:
            if other.side != text.side:
                continue
            if _rects_overlap_depth(text.box, other.box) > TOLERANCE_MM:
                report(
                    "silk_overlap",
                    f"{text.label} overlaps {other.label}",
                    (
                        (text.box[0] + text.box[2]) / 2,
                        (text.box[1] + text.box[3]) / 2,
                    ),
                )
    for line in lines:
        for reference, side, poly in bodies:
            if side != line.side:
                continue
            if (
                _seg_poly_distance(line.a, line.b, poly)
                < line.half_width - TOLERANCE_MM
            ):
                report(
                    "silk_overlap",
                    f"{line.label} crosses the body of {reference}",
                    line.a,
                )
        for text in texts:
            if text.side != line.side:
                continue
            if (
                _seg_rect_distance(line.a, line.b, text.box)
                < line.half_width - TOLERANCE_MM
            ):
                report(
                    "silk_overlap",
                    f"{line.label} crosses {text.label}",
                    line.a,
                )
        for pad in pads:
            layer = "B.Cu" if line.side == "B" else "F.Cu"
            if pad.layer != layer:
                continue
            distance = _seg_seg_distance(line.a, line.b, pad.a, pad.b)
            if distance < pad.radius + line.half_width - TOLERANCE_MM:
                report(
                    "silk_over_pad",
                    f"{line.label} crosses {pad.label}",
                    line.a,
                )
    return findings


def run_virtual_drc(
    layout: BoardLayout, netlist: BoardNetlist
) -> tuple[VirtualDrcFinding, ...]:
    """Run all virtual checks; returns findings (empty = clean)."""
    items = _collect_items(layout, netlist)
    findings = [
        *_check_copper_clearance(items),
        *_check_courtyards(layout),
        *_check_edge_clearance(items, layout),
        *_check_pour_connectivity(items, layout),
        *_check_pad_connectivity(items, layout),
        *_check_silkscreen(layout, items),
    ]
    return tuple(findings)
