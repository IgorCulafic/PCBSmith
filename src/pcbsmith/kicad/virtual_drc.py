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
# Modelling tolerance: only flag violations deeper than this, so roundrect
# corner radii and float noise never produce a false positive.
TOLERANCE_MM = 0.05
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
    layout: BoardLayout, netlist: BoardNetlist
) -> list[_Stadium]:
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
            if not pad.name:
                # Unnamed paste/thermal pads take the net of the named pad
                # they overlap at embed time; the named pad models them.
                continue
            net = net_of.get(
                (reference, pad.name), f"~nc:{reference}.{pad.name}"
            )
            half_long = (max(pad.width_mm, pad.height_mm) - min(
                pad.width_mm, pad.height_mm
            )) / 2
            radius = min(pad.width_mm, pad.height_mm) / 2
            axis = (half_long, 0.0) if pad.width_mm >= pad.height_mm else (0.0, half_long)
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
        # Zone-net items in a non-main region are stranded.
        for item in items:
            if item.layer != zone_layer or item.net != zone_net:
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
    ]
    return tuple(findings)
