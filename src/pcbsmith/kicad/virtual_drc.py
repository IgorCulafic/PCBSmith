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
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from enum import StrEnum

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
    rotate_offset,
)
from pcbsmith.kicad.copper_exposure import exposure_index
from pcbsmith.kicad.copper_identity import (
    pad_copper_source_id,
    track_copper_source_id,
    via_copper_source_id,
)
from pcbsmith.kicad.library import PadSpec
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    CopperRole,
    OrdinaryClearanceRequirement,
    OuterCopperMaskState,
    PcbRuleProfile,
    qualified_insulation_clearance_groups,
)

CLEARANCE_MM = DEFAULT_PCB_RULE_PROFILE.fab_spacing.minimum_copper_clearance_mm
EDGE_CLEARANCE_MM = DEFAULT_PCB_RULE_PROFILE.fab_spacing.minimum_copper_to_edge_mm
VIA_RADIUS_MM = DEFAULT_PCB_RULE_PROFILE.geometry.routing_via_diameter_mm / 2


# Modelling tolerance: only flag violations deeper than this, so roundrect
# corner radii and float noise never produce a false positive.
TOLERANCE_MM = 0.05
# KiCad board-setup constraint written by render_board_from_layout:
# silkscreen text below this height fails kicad-cli DRC (text_height).
MIN_SILK_TEXT_SIZE_MM = 0.8
_GRID_CELL_MM = 4.0

Point = tuple[float, float]


class _PhysicalItemKind(StrEnum):
    """Physical role of a stadium in the virtual-DRC geometry model."""

    COPPER = "copper"
    HOLE = "hole"
    BARE_HOLE = "bare_hole"
    GEOMETRY_PROXY = "geometry_proxy"


class _PhysicalSourceRole(StrEnum):
    """Semantic source of an item, independent of diagnostic wording."""

    UNKNOWN = "unknown"
    PAD = "pad"
    TRACK = "track"
    VIA = "via"
    BOARD_GRAPHIC = "board_graphic"


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
    """A physical item: segment (a == b for circles) plus a radius."""

    a: Point
    b: Point
    radius: float
    net: str
    layer: str  # "F.Cu" | "B.Cu"
    owner: str  # footprint reference for pads, "" for tracks/vias
    label: str
    kind: _PhysicalItemKind = _PhysicalItemKind.COPPER
    source_role: _PhysicalSourceRole = _PhysicalSourceRole.UNKNOWN
    mask_state: OuterCopperMaskState | None = "unknown"
    role: CopperRole | None = "unknown"
    unresolved_aperture_source_ids: tuple[str, ...] = ()
    exposure_reason: str | None = None
    source_id: str = ""
    parent_source_id: str | None = None

    @property
    def is_hole(self) -> bool:
        return self.kind in {
            _PhysicalItemKind.HOLE,
            _PhysicalItemKind.BARE_HOLE,
        }


_PhysicalHoleKey = tuple[str, Point, Point, float, str]


def _physical_hole_key(item: _Stadium) -> _PhysicalHoleKey:
    """Stable layer-independent identity for one manufactured hole."""
    if not item.is_hole:
        raise ValueError("physical-hole key requested for a copper item")
    first, second = sorted((item.a, item.b))
    return (
        item.parent_source_id or item.source_id,
        first,
        second,
        item.radius,
        item.owner,
    )


def _iter_physical_holes(items: Iterable[_Stadium]) -> Iterator[_Stadium]:
    """Yield each physical hole once despite its per-copper-layer copies."""
    seen: set[_PhysicalHoleKey] = set()
    for item in items:
        if not item.is_hole:
            continue
        key = _physical_hole_key(item)
        if key in seen:
            continue
        seen.add(key)
        yield item


# ---------------------------------------------------------------------------
# Scalar geometry.


def _seg_seg_distance(a1: Point, a2: Point, b1: Point, b2: Point) -> float:
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
            projections_one = [axis[0] * x + axis[1] * y for x, y in polygon_one]
            projections_two = [axis[0] * x + axis[1] * y for x, y in polygon_two]
            if max(projections_one) <= min(projections_two) or max(projections_two) <= min(
                projections_one
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


def _placed(anchor: Point, rotation: float, local: Point, flipped: bool) -> Point:
    if flipped:
        dx, dy = _back_offset(local, rotation)
    else:
        dx, dy = rotate_offset(local[0], local[1], rotation)
    return (anchor[0] + dx, anchor[1] + dy)


def _hole_item(
    pad: PadSpec,
    *,
    anchor: Point,
    footprint_rotation: float,
    flipped: bool,
    net: str,
    layer: str,
    owner: str,
    label: str,
    kind: _PhysicalItemKind,
    source_id: str,
    parent_source_id: str,
) -> _Stadium:
    """Place a PadSpec hole as its exact round/oval stadium."""
    hole = pad.hole
    if hole is None:
        raise ValueError("hole item requested for a pad without hole geometry")
    offset = rotate_offset(
        hole.offset_x_mm,
        hole.offset_y_mm,
        hole.rotation_deg,
    )
    center = (pad.x_mm + offset[0], pad.y_mm + offset[1])
    half_long = (hole.major_mm - hole.minor_mm) / 2
    axis = (half_long, 0.0) if hole.width_mm >= hole.height_mm else (0.0, half_long)
    axis = rotate_offset(axis[0], axis[1], hole.rotation_deg)
    ends_local = (
        (center[0] - axis[0], center[1] - axis[1]),
        (center[0] + axis[0], center[1] + axis[1]),
    )
    return _Stadium(
        a=_placed(anchor, footprint_rotation, ends_local[0], flipped),
        b=_placed(anchor, footprint_rotation, ends_local[1], flipped),
        radius=hole.minor_mm / 2,
        net=net,
        layer=layer,
        owner=owner,
        label=label,
        kind=kind,
        source_role=_PhysicalSourceRole.PAD,
        mask_state=None,
        role=None,
        source_id=source_id,
        parent_source_id=parent_source_id,
    )


def _collect_items(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    cover_rect_pads: bool = False,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> list[_Stadium]:
    """Model copper and physical holes as distinct typed stadiums.

    Pad copper retains the established underestimating/covering modes. Hole
    items preserve the parsed drill axes, offset, pad rotation, placement
    rotation, and front/back transform; clearance policy is applied later.
    """
    del profile  # Geometry is nominal; profile distances belong to checks.
    net_of = {(reference, pin): net.name for net in netlist.nets for reference, pin in net.nodes}
    items: list[_Stadium] = []
    for component, anchor_x in layout.placements:
        reference = component.reference
        spec = FOOTPRINT_LIBRARY[component.footprint]
        rotation = placement_rotation(layout, reference)
        anchor = (anchor_x, placement_y(layout, reference))
        flipped = reference in layout.part_flip
        for pad_index, pad in enumerate(spec.pads):
            if not pad.name and pad.hole is None:
                # Unnamed paste/thermal pads take the net of the named pad
                # they overlap at embed time; the named pad models them.
                continue
            parent_source_id = f"pad:{reference}:{pad_index}"
            is_bare_hole = pad.kind == "npth"
            if is_bare_hole:
                net = f"~hole:{reference}"
            else:
                net = net_of.get((reference, pad.name), f"~nc:{reference}.{pad.name}")

            if not is_bare_hole:
                width_mm = pad.width_mm
                height_mm = pad.height_mm
                half_long = (max(width_mm, height_mm) - min(width_mm, height_mm)) / 2
                radius = min(width_mm, height_mm) / 2
                if cover_rect_pads and pad.shape in ("rect", "custom"):
                    radius = min(width_mm, height_mm) / math.sqrt(2)
                elif cover_rect_pads and pad.shape == "roundrect":
                    short = min(width_mm, height_mm)
                    corner = 0.25 * short
                    radius = short / 2 + corner * (math.sqrt(2) - 1)
                axis = (half_long, 0.0) if width_mm >= height_mm else (0.0, half_long)
                axis = rotate_offset(axis[0], axis[1], pad.angle_deg)
                ends_local = (
                    (pad.x_mm - axis[0], pad.y_mm - axis[1]),
                    (pad.x_mm + axis[0], pad.y_mm + axis[1]),
                )
                a = _placed(anchor, rotation, ends_local[0], flipped)
                b = _placed(anchor, rotation, ends_local[1], flipped)
                copper_layers = (
                    ("F.Cu", "B.Cu")
                    if pad.hole is not None
                    else (("B.Cu",) if flipped else ("F.Cu",))
                )
                for layer in copper_layers:
                    items.append(
                        _Stadium(
                            a=a,
                            b=b,
                            radius=radius,
                            net=net,
                            layer=layer,
                            owner=reference,
                            label=f"pad {reference}.{pad.name} [{net}]",
                            kind=_PhysicalItemKind.COPPER,
                            source_role=_PhysicalSourceRole.PAD,
                            mask_state="unknown",
                            role="component_termination",
                            source_id=pad_copper_source_id(reference, pad_index, layer),
                            parent_source_id=parent_source_id,
                        )
                    )

            if pad.hole is not None:
                hole_kind = _PhysicalItemKind.BARE_HOLE if is_bare_hole else _PhysicalItemKind.HOLE
                qualifier = "bare" if is_bare_hole else "plated"
                for layer in ("F.Cu", "B.Cu"):
                    items.append(
                        _hole_item(
                            pad,
                            anchor=anchor,
                            footprint_rotation=rotation,
                            flipped=flipped,
                            net=net,
                            layer=layer,
                            owner=reference,
                            label=(f"{qualifier} hole {reference}.{pad.name} [{net}]"),
                            kind=hole_kind,
                            source_id=f"{parent_source_id}:hole:{layer}",
                            parent_source_id=parent_source_id,
                        )
                    )
    for segment_index, segment in enumerate(layout.segments):
        items.append(
            _Stadium(
                a=(segment.x1, segment.y1),
                b=(segment.x2, segment.y2),
                radius=segment.width_mm / 2,
                net=segment.net_name,
                layer=segment.layer,
                owner="",
                label=f"track [{segment.net_name}] on {segment.layer}",
                kind=_PhysicalItemKind.COPPER,
                source_role=_PhysicalSourceRole.TRACK,
                mask_state="unknown",
                role="routed_conductor",
                source_id=track_copper_source_id(segment_index),
            )
        )
    for via_index, via in enumerate(layout.vias):
        parent_source_id = f"via:{via_index}"
        for layer in ("F.Cu", "B.Cu"):
            items.extend(
                (
                    _Stadium(
                        a=(via.x, via.y),
                        b=(via.x, via.y),
                        radius=via.size_mm / 2,
                        net=via.net_name,
                        layer=layer,
                        owner="",
                        label=f"via [{via.net_name}]",
                        kind=_PhysicalItemKind.COPPER,
                        source_role=_PhysicalSourceRole.VIA,
                        mask_state="unknown",
                        role="via_land",
                        source_id=via_copper_source_id(via_index, layer),
                        parent_source_id=parent_source_id,
                    ),
                    _Stadium(
                        a=(via.x, via.y),
                        b=(via.x, via.y),
                        radius=via.drill_mm / 2,
                        net=via.net_name,
                        layer=layer,
                        owner="",
                        label=f"plated via hole [{via.net_name}]",
                        kind=_PhysicalItemKind.HOLE,
                        source_role=_PhysicalSourceRole.VIA,
                        mask_state=None,
                        role=None,
                        source_id=f"{parent_source_id}:hole:{layer}",
                        parent_source_id=parent_source_id,
                    ),
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
        (cell_x, cell_y) for cell_x in range(x_lo, x_hi + 1) for cell_y in range(y_lo, y_hi + 1)
    ]


# ---------------------------------------------------------------------------
# Checks.


def _check_copper_clearance(
    items: list[_Stadium],
    clearance_mm: float = CLEARANCE_MM,
    hole_clearance_mm: float | None = None,
) -> list[VirtualDrcFinding]:
    """Check copper pairs and physical-hole-to-foreign-copper spacing."""
    hole_clearance = clearance_mm if hole_clearance_mm is None else hole_clearance_mm
    search_clearance = max(clearance_mm, hole_clearance)
    findings: list[VirtualDrcFinding] = []
    grid: dict[tuple[int, int], list[int]] = {}
    for index, item in enumerate(items):
        for cell in _grid_cells(item, search_clearance):
            grid.setdefault(cell, []).append(index)
    seen: set[tuple[int, int]] = set()
    for bucket in grid.values():
        for position, first in enumerate(bucket):
            for second in bucket[position + 1 :]:
                pair = (min(first, second), max(first, second))
                if pair in seen:
                    continue
                seen.add(pair)
                one, two = items[first], items[second]
                if one.layer != two.layer or one.net == two.net:
                    continue
                if (
                    one.kind is _PhysicalItemKind.GEOMETRY_PROXY
                    or two.kind is _PhysicalItemKind.GEOMETRY_PROXY
                    or (one.is_hole and two.is_hole)
                ):
                    continue
                # The copper land and drill belonging to one physical pad
                # are not a clearance pair. Same-footprint pad pairs retain
                # the established net-tie/multi-net-package exemption.
                if (
                    one.parent_source_id is not None
                    and one.parent_source_id == two.parent_source_id
                ):
                    continue
                if one.owner and one.owner == two.owner:
                    continue
                is_hole_pair = one.is_hole or two.is_hole
                pair_clearance = hole_clearance if is_hole_pair else clearance_mm
                required = one.radius + two.radius + pair_clearance
                distance = _seg_seg_distance(one.a, one.b, two.a, two.b)
                if distance < required - TOLERANCE_MM:
                    midpoint = (
                        (one.a[0] + one.b[0] + two.a[0] + two.b[0]) / 4,
                        (one.a[1] + one.b[1] + two.a[1] + two.b[1]) / 4,
                    )
                    if is_hole_pair:
                        violation = (
                            "hole collision"
                            if distance < one.radius + two.radius
                            else "hole clearance"
                        )
                    else:
                        violation = "short" if distance < one.radius + two.radius else "clearance"
                    findings.append(
                        VirtualDrcFinding(
                            check="copper_clearance",
                            message=(
                                f"{violation}: {one.label} vs {two.label}: "
                                f"{distance:.3f}mm (needs {required:.3f}mm)"
                            ),
                            x_mm=midpoint[0],
                            y_mm=midpoint[1],
                        )
                    )
    return findings


def _check_group_clearances(
    items: list[_Stadium],
    groups: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...], float, tuple[str, ...]],
        ...,
    ],
    *,
    check: str,
) -> list[VirtualDrcFinding]:
    findings: list[VirtualDrcFinding] = []
    for requirement_id, nets_a, nets_b, minimum_mm, exemptions in groups:
        group_a = set(nets_a)
        group_b = set(nets_b)
        exempt = set(exemptions)
        for index, one in enumerate(items):
            if one.owner in exempt:
                continue
            for two in items[index + 1 :]:
                if two.owner in exempt or one.layer != two.layer:
                    continue
                if (
                    one.kind is not _PhysicalItemKind.COPPER
                    or two.kind is not _PhysicalItemKind.COPPER
                ):
                    continue
                paired = (one.net in group_a and two.net in group_b) or (
                    one.net in group_b and two.net in group_a
                )
                if not paired:
                    continue
                required = one.radius + two.radius + minimum_mm
                distance = _seg_seg_distance(one.a, one.b, two.a, two.b)
                if distance >= required - TOLERANCE_MM:
                    continue
                midpoint = (
                    (one.a[0] + one.b[0] + two.a[0] + two.b[0]) / 4,
                    (one.a[1] + one.b[1] + two.a[1] + two.b[1]) / 4,
                )
                findings.append(
                    VirtualDrcFinding(
                        check=check,
                        message=(
                            f"{requirement_id}: {one.label} vs {two.label}: "
                            f"{distance:.3f}mm (needs {required:.3f}mm)"
                        ),
                        x_mm=midpoint[0],
                        y_mm=midpoint[1],
                    )
                )
    return findings


def _unresolved_scope_description(direction: str, item: _Stadium) -> str:
    apertures = ", ".join(item.unresolved_aperture_source_ids) or "none"
    reason = item.exposure_reason or "exposure classification unavailable"
    return (
        f"{direction} {item.source_id or '<missing>'} ({item.layer}) "
        f"unresolved apertures [{apertures}], reason={reason}"
    )


def _check_pairwise_clearance(
    items: list[_Stadium],
    requirements: tuple[OrdinaryClearanceRequirement, ...],
) -> list[VirtualDrcFinding]:
    """Check directional ordinary net spacing and its declared surface scope."""
    findings: list[VirtualDrcFinding] = []
    for requirement in requirements:
        group_a = set(requirement.nets_a)
        group_b = set(requirement.nets_b)
        exempt = set(requirement.exempt_component_refs)
        for index, one in enumerate(items):
            if one.owner in exempt:
                continue
            for two in items[index + 1 :]:
                if two.owner in exempt or one.layer != two.layer:
                    continue
                if (
                    one.kind is not _PhysicalItemKind.COPPER
                    or two.kind is not _PhysicalItemKind.COPPER
                ):
                    continue
                if one.net in group_a and two.net in group_b:
                    item_a, item_b = one, two
                elif one.net in group_b and two.net in group_a:
                    item_a, item_b = two, one
                else:
                    continue

                required = one.radius + two.radius + requirement.minimum_clearance_mm
                distance = _seg_seg_distance(one.a, one.b, two.a, two.b)
                if distance >= required - TOLERANCE_MM:
                    continue
                midpoint = (
                    (one.a[0] + one.b[0] + two.a[0] + two.b[0]) / 4,
                    (one.a[1] + one.b[1] + two.a[1] + two.b[1]) / 4,
                )

                if (requirement.roles_a and item_a.role not in requirement.roles_a) or (
                    requirement.roles_b and item_b.role not in requirement.roles_b
                ):
                    continue

                unresolved: list[tuple[str, _Stadium]] = []
                mask_mismatch = False
                for direction, item, selectors in (
                    ("A", item_a, requirement.mask_states_a),
                    ("B", item_b, requirement.mask_states_b),
                ):
                    if not selectors:
                        continue
                    state = item.mask_state or "unknown"
                    if state == "unknown" and "unknown" not in selectors:
                        unresolved.append((direction, item))
                    elif state not in selectors:
                        mask_mismatch = True
                if mask_mismatch:
                    continue
                if unresolved:
                    pair_description = (
                        f"A {item_a.source_id or '<missing>'} ({item_a.layer}) "
                        f"vs B {item_b.source_id or '<missing>'} ({item_b.layer})"
                    )
                    unresolved_description = "; ".join(
                        _unresolved_scope_description(direction, item)
                        for direction, item in unresolved
                    )
                    findings.append(
                        VirtualDrcFinding(
                            check=("ordinary_pairwise_clearance_scope_unverified"),
                            message=(
                                f"{requirement.requirement_id}: "
                                f"{pair_description}; {unresolved_description}"
                            ),
                            x_mm=midpoint[0],
                            y_mm=midpoint[1],
                        )
                    )
                    continue

                findings.append(
                    VirtualDrcFinding(
                        check="ordinary_pairwise_clearance",
                        message=(
                            f"{requirement.requirement_id}: "
                            f"{one.label} vs {two.label}: "
                            f"{distance:.3f}mm (needs {required:.3f}mm)"
                        ),
                        x_mm=midpoint[0],
                        y_mm=midpoint[1],
                    )
                )
    return findings


def _check_qualified_insulation_clearance(
    items: list[_Stadium], profile: PcbRuleProfile
) -> list[VirtualDrcFinding]:
    """Check reviewed air-clearance results; creepage needs path geometry."""
    groups = qualified_insulation_clearance_groups(profile)
    return _check_group_clearances(items, groups, check="insulation_clearance")


def _courtyard_polygon(layout: BoardLayout, reference: str, anchor: Point) -> list[Point] | None:
    component = next(
        component for component, _x in layout.placements if component.reference == reference
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
        return [_placed(anchor, rotation, corner, flipped) for corner in pulled]
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
            polys.append((reference, reference in layout.part_flip, polygon))
    for index, (ref_one, flip_one, poly_one) in enumerate(polys):
        for ref_two, flip_two, poly_two in polys[index + 1 :]:
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
    items: list[_Stadium],
    layout: BoardLayout,
    edge_clearance_mm: float = EDGE_CLEARANCE_MM,
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
    edges = [(outline[index], outline[(index + 1) % len(outline)]) for index in range(len(outline))]
    edge_grid: dict[tuple[int, int], list[int]] = {}
    for index, (a, b) in enumerate(edges):
        fake = _Stadium(
            a=a,
            b=b,
            radius=0.0,
            net="",
            layer="",
            owner="",
            label="",
            kind=_PhysicalItemKind.GEOMETRY_PROXY,
            mask_state=None,
            role=None,
        )
        for cell in _grid_cells(fake, edge_clearance_mm + 1.0):
            edge_grid.setdefault(cell, []).append(index)
    findings: list[VirtualDrcFinding] = []
    reported: set[str] = set()
    for item in items:
        if item.is_hole:
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
        for cell in _grid_cells(item, edge_clearance_mm):
            candidates.update(edge_grid.get(cell, ()))
        required = item.radius + edge_clearance_mm
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


def _check_pour_connectivity(items: list[_Stadium], layout: BoardLayout) -> list[VirtualDrcFinding]:
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
        blockers = [item for item in items if item.layer == zone_layer and item.net != zone_net]
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
                            0 <= nr < rows
                            and 0 <= nc < columns
                            and not blocked[nr][nc]
                            and region[nr][nc] == -1
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
            item
            for item in items
            if (item.kind is _PhysicalItemKind.COPPER and item.net == zone_net and not item.owner)
        ]
        segments_only = [t for t in tracks if t.a != t.b]
        trace_connected = {
            (item.label, item.a)
            for item in items
            if item.kind is _PhysicalItemKind.COPPER
            and item.net == zone_net
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
            if (
                item.kind is not _PhysicalItemKind.COPPER
                or item.layer != zone_layer
                or item.net != zone_net
            ):
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


def _check_pad_connectivity(items: list[_Stadium], layout: BoardLayout) -> list[VirtualDrcFinding]:
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
        if item.kind is not _PhysicalItemKind.COPPER or item.net.startswith("~"):
            continue
        copper.setdefault((item.net, item.layer), []).append(item)

    pad_counts: dict[str, set[str]] = {}
    for item in items:
        if (
            item.kind is _PhysicalItemKind.COPPER
            and item.source_role is _PhysicalSourceRole.PAD
            and not item.net.startswith("~")
        ):
            pad_counts.setdefault(item.net, set()).add(item.parent_source_id or item.source_id)

    def _pad_connected(pad: _Stadium) -> bool:
        for rect in zone_rects.get((pad.net, pad.layer), ()):
            if rect[0] <= pad.a[0] <= rect[2] and rect[1] <= pad.a[1] <= rect[3]:
                return True
        for other in copper.get((pad.net, pad.layer), ()):
            if other is pad:
                continue
            if other.parent_source_id == pad.parent_source_id and pad.parent_source_id is not None:
                continue  # the THT twin is the same physical pad
            distance = _seg_seg_distance(pad.a, pad.b, other.a, other.b)
            if distance <= pad.radius + other.radius + TOLERANCE_MM:
                return True
        return False

    findings: list[VirtualDrcFinding] = []
    # Group the per-layer copies of each physical pad: connected on any
    # layer is connected.
    by_pad: dict[str, list[_Stadium]] = {}
    for item in items:
        if (
            item.kind is _PhysicalItemKind.COPPER
            and item.source_role is _PhysicalSourceRole.PAD
            and not item.net.startswith("~")
        ):
            pad_id = item.parent_source_id or item.source_id
            by_pad.setdefault(pad_id, []).append(item)
    for _pad_id, copies in sorted(by_pad.items()):
        net = copies[0].net
        label = copies[0].label
        anchor = copies[0].a
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

_TEXT_CHAR_HALF_W = 0.4  # per character, x font size (KiCad advance ~1.0)
_TEXT_HALF_H = 0.55  # x font size
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


def _text_box(center: Point, text: str, size: float, upright_swap: bool) -> _Rect:
    half_w = max(len(text), 1) * size * _TEXT_CHAR_HALF_W
    half_h = size * _TEXT_HALF_H
    if upright_swap:
        half_w, half_h = half_h, half_w
    return (
        center[0] - half_w,
        center[1] - half_h,
        center[0] + half_w,
        center[1] + half_h,
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
        (rect[0], rect[1]),
        (rect[2], rect[1]),
        (rect[2], rect[3]),
        (rect[0], rect[3]),
    )
    return min(
        _seg_seg_distance(a, b, corners[index], corners[(index + 1) % 4]) for index in range(4)
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
            size = spec.reference_label[2] if spec.reference_label else _DEFAULT_REF_SIZE
        elif spec.reference_label is not None:
            local = (spec.reference_label[0], spec.reference_label[1])
            total_angle = rotation
            size = spec.reference_label[2]
        else:
            continue
        center = _placed(
            (anchor_x, placement_y(layout, reference)),
            rotation,
            local,
            flipped,
        )
        texts.append(
            _SilkText(
                box=_text_box(
                    center,
                    reference,
                    size,
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
                [_placed(anchor, rotation, point, flipped) for point in local_points],
            )
        )
    return polys


def _rect_poly_overlap_depth(rect: _Rect, poly: list[Point]) -> float:
    """Positive when the rect penetrates the convex polygon; measured as
    the deepest rect corner/edge inside, approximated via SAT margins."""
    corners = [
        (rect[0], rect[1]),
        (rect[2], rect[1]),
        (rect[2], rect[3]),
        (rect[0], rect[3]),
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
        _seg_seg_distance(a, b, poly[index], poly[(index + 1) % count]) for index in range(count)
    )


def _check_silkscreen(layout: BoardLayout, items: list[_Stadium]) -> list[VirtualDrcFinding]:
    texts = _collect_silk_texts(layout)
    lines = _collect_silk_lines(layout)
    bodies = _body_polys(layout)
    # Bare-hole items carry no copper/mask aperture in the model - keep
    # the silk checks strictly underestimating.
    pads = [item for item in items if item.owner and item.kind is _PhysicalItemKind.COPPER]
    findings: list[VirtualDrcFinding] = []

    def report(check: str, message: str, at: Point) -> None:
        findings.append(VirtualDrcFinding(check=check, message=message, x_mm=at[0], y_mm=at[1]))

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
        for other in texts[index + 1 :]:
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
            if _seg_poly_distance(line.a, line.b, poly) < line.half_width - TOLERANCE_MM:
                report(
                    "silk_overlap",
                    f"{line.label} crosses the body of {reference}",
                    line.a,
                )
        for text in texts:
            if text.side != line.side:
                continue
            if _seg_rect_distance(line.a, line.b, text.box) < line.half_width - TOLERANCE_MM:
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
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> tuple[VirtualDrcFinding, ...]:
    """Run all virtual checks; returns findings (empty = clean)."""
    items = _collect_items(layout, netlist, profile=profile)
    pairwise_requirements = profile.fab_spacing.pairwise_clearances
    if any(
        requirement.mask_states_a or requirement.mask_states_b
        for requirement in pairwise_requirements
    ):
        indexed_exposure = exposure_index(layout, netlist, profile)
        annotated_items: list[_Stadium] = []
        for item in items:
            if item.kind is not _PhysicalItemKind.COPPER:
                annotated_items.append(item)
                continue
            result = indexed_exposure.get(item.source_id)
            if result is None:
                annotated_items.append(
                    replace(
                        item,
                        exposure_reason="copper source has no exposure result",
                    )
                )
                continue
            annotated_items.append(
                replace(
                    item,
                    mask_state=result.state,
                    role=result.role,
                    unresolved_aperture_source_ids=(result.unresolved_aperture_source_ids),
                    exposure_reason=result.reason,
                )
            )
        items = annotated_items
    findings = [
        *_check_copper_clearance(
            items,
            profile.fab_spacing.minimum_copper_clearance_mm,
            profile.fab_spacing.minimum_hole_to_copper_mm,
        ),
        *_check_pairwise_clearance(items, pairwise_requirements),
        *_check_qualified_insulation_clearance(items, profile),
        *_check_courtyards(layout),
        *_check_edge_clearance(items, layout, profile.fab_spacing.minimum_copper_to_edge_mm),
        *_check_pour_connectivity(items, layout),
        *_check_pad_connectivity(items, layout),
        *_check_silkscreen(layout, items),
    ]
    return tuple(findings)
