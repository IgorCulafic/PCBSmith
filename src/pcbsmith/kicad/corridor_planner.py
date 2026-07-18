"""Conservative KiCad-to-corridor graph construction for R3.2.

This module builds geometry and derived terminal demands only.  It does not
allocate corridor capacity, guide the detailed router, or claim exact
routability.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Mapping, Sequence
from decimal import ROUND_CEILING, Decimal, localcontext
from enum import StrEnum
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.corridor_ir import (
    CorridorCell,
    CorridorGeometryIssue,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPortal,
    CorridorTerminal,
    CorridorViaPolicy,
    CorridorViaPortal,
)
from pcbsmith.kicad.astar_router import _routable_nets
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
)
from pcbsmith.kicad.clearance_domains import (
    ClearanceGroupInput,
    build_route_pairwise_clearance_domains,
    conservative_clearance_for_net,
)
from pcbsmith.kicad.library import PadSpec, rotate_offset
from pcbsmith.kicad.negotiated_resources import PairwiseClearanceDomain
from pcbsmith.kicad.virtual_drc import (
    _collect_items,
    _PhysicalItemKind,
    _PhysicalSourceRole,
    _point_seg_distance,
    _Stadium,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

Point = tuple[float, float]
Bounds = tuple[float, float, float, float]
Layer = Literal["F.Cu", "B.Cu"]
LAYERS: tuple[Layer, ...] = ("F.Cu", "B.Cu")
_EPSILON = 1e-9


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class OpaqueGraphicsPolicy(StrEnum):
    """Explicit treatment of unparsed board graphics.

    The assertion is fingerprinted input, not an inference from the raw text.
    """

    REJECT_OPAQUE = "reject_opaque"
    ASSERT_NON_EDGE_CUTS = "assert_non_edge_cuts"


class CorridorGraphBuildFailure(StrEnum):
    GEOMETRY_BUDGET = "geometry_budget"
    UNSUPPORTED_GEOMETRY = "unsupported_geometry"
    TERMINAL_UNMAPPED = "terminal_unmapped"


class CorridorGraphBuildBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_cells: int = Field(default=200_000, ge=0)
    max_portals: int = Field(default=400_000, ge=0)


DEFAULT_CORRIDOR_GRAPH_BUILD_BUDGET = CorridorGraphBuildBudget()


class CorridorGraphBuildResult(BaseModel):
    """Versioned graph-build outcome; incomplete output is never plannable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-corridor-graph-build"] = "pcbsmith-corridor-graph-build"
    schema_version: Literal[1] = 1
    complete: bool
    planning_supported: bool
    failure_reason: CorridorGraphBuildFailure | None = None
    graph: CorridorGraph
    demands: tuple[CorridorNetDemand, ...] = ()
    unmapped_terminal_ids: tuple[str, ...] = ()
    graphics_policy: OpaqueGraphicsPolicy
    budget: CorridorGraphBuildBudget

    @model_validator(mode="after")
    def state_is_coherent(self) -> Self:
        demands = tuple(sorted(self.demands, key=lambda item: item.demand_id))
        if len({item.net_name for item in demands}) != len(demands):
            raise ValueError("one graph build permits at most one demand per net")
        unmapped = tuple(sorted(set(self.unmapped_terminal_ids)))
        if any(not item for item in unmapped):
            raise ValueError("unmapped terminal identities must be non-empty")
        if self.planning_supported and not self.complete:
            raise ValueError("incomplete graph output cannot support planning")
        if self.graph.geometry_complete is not self.complete:
            raise ValueError("graph geometry_complete must agree with build completeness")
        if self.planning_supported and self.failure_reason is not None:
            raise ValueError("planning-supported graph cannot carry a failure")
        if not self.planning_supported and self.failure_reason is None:
            raise ValueError("non-plannable graph requires a typed failure")
        if unmapped and self.failure_reason is not CorridorGraphBuildFailure.TERMINAL_UNMAPPED:
            raise ValueError("unmapped terminals require terminal_unmapped failure")
        object.__setattr__(self, "demands", demands)
        object.__setattr__(self, "unmapped_terminal_ids", unmapped)
        return self

    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class _ObstacleKind(StrEnum):
    STADIUM = "stadium"
    POLYGON = "polygon"
    RECTANGLE = "rectangle"


class _Obstacle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    layer: Layer
    kind: _ObstacleKind
    stadium_a: Point | None = None
    stadium_b: Point | None = None
    radius_mm: float = 0.0
    polygon: tuple[Point, ...] = ()
    rectangle: Bounds | None = None
    inflation_mm: float = Field(ge=0)


def build_corridor_graph(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    target_nets: Collection[str] | None = None,
    net_widths: Mapping[str, float] | None = None,
    default_width_mm: float = 0.4,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    clearance_groups: Sequence[ClearanceGroupInput] = (),
    coarse_grid_mm: float = 2.0,
    capacity_quantum_mm: float = 0.01,
    graphics_policy: OpaqueGraphicsPolicy = OpaqueGraphicsPolicy.REJECT_OPAQUE,
    budget: CorridorGraphBuildBudget = DEFAULT_CORRIDOR_GRAPH_BUILD_BUDGET,
) -> CorridorGraphBuildResult:
    """Build the complete conservative R3.2 graph and derived AREA demands."""
    _require_positive_finite(default_width_mm, "default_width_mm")
    _require_positive_finite(coarse_grid_mm, "coarse_grid_mm")
    _require_positive_finite(capacity_quantum_mm, "capacity_quantum_mm")
    widths = dict(net_widths or {})
    for name, width in widths.items():
        if not name:
            raise ValueError("net width names must be non-empty")
        _require_positive_finite(width, "net width")

    outline = _canonical_outline(
        layout.outline
        or (
            (0.0, 0.0),
            (layout.width_mm, 0.0),
            (layout.width_mm, layout.height_mm),
            (0.0, layout.height_mm),
        )
    )
    selected = tuple(
        sorted(
            name
            for name in _routable_nets(layout, netlist, profile)
            if target_nets is None or name in set(target_nets)
        )
    )
    selected_set = frozenset(selected)
    issues: list[CorridorGeometryIssue] = []
    if layout.graphics and graphics_policy is OpaqueGraphicsPolicy.REJECT_OPAQUE:
        issues.append(
            CorridorGeometryIssue(
                source_id="layout:opaque-graphics",
                verification=CorridorGeometryVerification.UNSUPPORTED,
                reason="opaque graphics may contain Edge.Cuts",
            )
        )

    obstacles, pad_copper, obstacle_issues = _collect_graph_geometry(
        layout, netlist, selected_set, profile
    )
    issues.extend(obstacle_issues)
    profile_fingerprint = _fingerprint(profile.model_dump(mode="json"))
    geometry_payload = {
        "schema_id": "pcbsmith-corridor-layout-geometry",
        "schema_version": 1,
        "outline": outline,
        "obstacles": [
            item.model_dump(mode="json")
            for item in sorted(
                obstacles, key=lambda value: (value.source_id, value.layer, value.kind.value)
            )
        ],
        "target_nets": selected,
        "graphics": tuple(layout.graphics),
        "graphics_policy": graphics_policy.value,
    }
    if layout.cutouts:
        geometry_payload["cutouts"] = tuple(cutout.points for cutout in layout.cutouts)
    layout_fingerprint = _fingerprint(geometry_payload)

    x_cells = int(math.floor(layout.width_mm / coarse_grid_mm + _EPSILON))
    y_cells = int(math.floor(layout.height_mm / coarse_grid_mm + _EPSILON))
    if 2 * x_cells * y_cells > budget.max_cells:
        graph = CorridorGraph(
            profile_fingerprint=profile_fingerprint,
            layout_geometry_fingerprint=layout_fingerprint,
            coarse_grid_mm=coarse_grid_mm,
            capacity_quantum_mm=capacity_quantum_mm,
            geometry_complete=False,
            issues=tuple(issues),
        )
        return CorridorGraphBuildResult(
            complete=False,
            planning_supported=False,
            failure_reason=CorridorGraphBuildFailure.GEOMETRY_BUDGET,
            graph=graph,
            graphics_policy=graphics_policy,
            budget=budget,
        )

    cell_records: list[CorridorCell] = []
    cell_bounds: dict[tuple[Layer, int, int], Bounds] = {}
    for layer in LAYERS:
        layer_obstacles = tuple(item for item in obstacles if item.layer == layer)
        for ix in range(x_cells):
            for iy in range(y_cells):
                bounds = (
                    ix * coarse_grid_mm,
                    iy * coarse_grid_mm,
                    (ix + 1) * coarse_grid_mm,
                    (iy + 1) * coarse_grid_mm,
                )
                if not _closed_cell_inside_outline(
                    bounds, outline, profile.fab_spacing.minimum_copper_to_edge_mm
                ):
                    continue
                if any(
                    not _closed_cell_outside_cutout(
                        bounds,
                        cutout.points,
                        profile.fab_spacing.minimum_copper_to_edge_mm,
                    )
                    for cutout in layout.cutouts
                ):
                    continue
                if any(_obstacle_intersects_bounds(item, bounds) for item in layer_obstacles):
                    continue
                owners = tuple(
                    sorted(
                        {
                            net
                            for net, _terminal_id, copper in pad_copper
                            if net in selected_set
                            and copper.layer == layer
                            and _pad_intersects_bounds(copper, bounds)
                        }
                    )
                )
                cell_id = _cell_id(layout_fingerprint, profile_fingerprint, layer, ix, iy, bounds)
                cell_records.append(
                    CorridorCell(
                        cell_id=cell_id,
                        layer=layer,
                        ix=ix,
                        iy=iy,
                        bounds_mm=bounds,
                        terminal_owner_net_names=owners,
                    )
                )
                cell_bounds[(layer, ix, iy)] = bounds

    cells_by_key = {(item.layer, item.ix, item.iy): item for item in cell_records}
    portals: list[CorridorPortal] = []
    span_units = int(math.floor(coarse_grid_mm / capacity_quantum_mm + _EPSILON))
    for (layer, ix, iy), cell in sorted(cells_by_key.items()):
        for dx, dy, orientation in (
            (1, 0, "vertical_cut"),
            (0, 1, "horizontal_cut"),
        ):
            other = cells_by_key.get((layer, ix + dx, iy + dy))
            if other is None:
                continue
            low, high = sorted((cell.cell_id, other.cell_id))
            resource_id = "channel:" + _fingerprint(
                {
                    "schema_version": 1,
                    "layer": layer,
                    "cell_low": low,
                    "cell_high": high,
                    "orientation": orientation,
                    "span_mm": coarse_grid_mm,
                    "quantum_mm": capacity_quantum_mm,
                    "profile_fingerprint": profile_fingerprint,
                }
            )
            portals.append(
                CorridorPortal(
                    resource_id=resource_id,
                    layer=layer,
                    cell_low=low,
                    cell_high=high,
                    orientation=orientation,
                    guaranteed_span_units=span_units,
                    possible_span_units=span_units,
                    verification=CorridorGeometryVerification.EXACT,
                )
            )
            if len(portals) > budget.max_portals:
                graph = CorridorGraph(
                    profile_fingerprint=profile_fingerprint,
                    layout_geometry_fingerprint=layout_fingerprint,
                    coarse_grid_mm=coarse_grid_mm,
                    capacity_quantum_mm=capacity_quantum_mm,
                    geometry_complete=False,
                    cells=tuple(cell_records),
                    issues=tuple(issues),
                )
                return CorridorGraphBuildResult(
                    complete=False,
                    planning_supported=False,
                    failure_reason=CorridorGraphBuildFailure.GEOMETRY_BUDGET,
                    graph=graph,
                    graphics_policy=graphics_policy,
                    budget=budget,
                )

    via_portals = _build_via_portals(
        cells_by_key,
        outline,
        tuple(cutout.points for cutout in layout.cutouts),
        obstacles,
        pad_copper,
        profile,
        layout_fingerprint,
        profile_fingerprint,
    )
    graph = CorridorGraph(
        profile_fingerprint=profile_fingerprint,
        layout_geometry_fingerprint=layout_fingerprint,
        coarse_grid_mm=coarse_grid_mm,
        capacity_quantum_mm=capacity_quantum_mm,
        cells=tuple(cell_records),
        portals=tuple(portals),
        via_portals=via_portals,
        issues=tuple(issues),
    )
    pairwise_domains = build_route_pairwise_clearance_domains(profile, clearance_groups)
    demands, unmapped = _derive_demands(
        selected,
        widths,
        default_width_mm,
        capacity_quantum_mm,
        profile,
        pairwise_domains,
        pad_copper,
        tuple(cell_records),
    )
    if unmapped:
        failure = CorridorGraphBuildFailure.TERMINAL_UNMAPPED
    elif any(issue.verification is CorridorGeometryVerification.UNSUPPORTED for issue in issues):
        failure = CorridorGraphBuildFailure.UNSUPPORTED_GEOMETRY
    else:
        failure = None
    return CorridorGraphBuildResult(
        complete=True,
        planning_supported=failure is None,
        failure_reason=failure,
        graph=graph,
        demands=demands,
        unmapped_terminal_ids=unmapped,
        graphics_policy=graphics_policy,
        budget=budget,
    )


def _collect_graph_geometry(
    layout: BoardLayout,
    netlist: BoardNetlist,
    selected: frozenset[str],
    profile: PcbRuleProfile,
) -> tuple[list[_Obstacle], list[tuple[str, str, _Stadium]], list[CorridorGeometryIssue]]:
    items = _collect_items(layout, netlist, profile=profile)
    pad_copper = [
        (item.net, item.parent_source_id or item.source_id, item)
        for item in items
        if item.kind is _PhysicalItemKind.COPPER and item.source_role is _PhysicalSourceRole.PAD
    ]
    pad_shapes = _pad_shape_map(layout)
    obstacles: list[_Obstacle] = []
    issues: list[CorridorGeometryIssue] = []
    seen_holes: set[tuple[str, Layer]] = set()
    for item in items:
        layer = cast(Layer, item.layer)
        if (
            item.kind is _PhysicalItemKind.COPPER
            and item.source_role in {_PhysicalSourceRole.TRACK, _PhysicalSourceRole.VIA}
            and item.net in selected
        ):
            continue
        if item.kind is _PhysicalItemKind.COPPER and item.source_role is _PhysicalSourceRole.PAD:
            if item.net in selected:
                continue
            pad_shape = pad_shapes.get(item.parent_source_id or "")
            if pad_shape is not None and pad_shape[0].shape in {
                "rect",
                "custom",
                "roundrect",
            }:
                pad, polygon = pad_shape
                if pad.shape == "roundrect":
                    maximum_error_mm, unsupported_reason = _roundrect_bbox_error_mm(pad)
                    if unsupported_reason is not None:
                        issues.append(
                            CorridorGeometryIssue(
                                source_id=item.parent_source_id or item.source_id,
                                layer=layer,
                                verification=CorridorGeometryVerification.UNSUPPORTED,
                                reason=unsupported_reason,
                            )
                        )
                    elif maximum_error_mm is not None:
                        issues.append(
                            CorridorGeometryIssue(
                                source_id=item.parent_source_id or item.source_id,
                                layer=layer,
                                verification=(
                                    CorridorGeometryVerification.BOUNDED_APPROXIMATION
                                ),
                                maximum_error_mm=maximum_error_mm,
                                reason=(
                                    "roundrect copper is conservatively blocked by its full "
                                    "source bounding rectangle"
                                ),
                            )
                        )
                elif pad.shape == "custom":
                    issues.append(
                        CorridorGeometryIssue(
                            source_id=item.parent_source_id or item.source_id,
                            layer=layer,
                            verification=CorridorGeometryVerification.UNSUPPORTED,
                            reason=(
                                f"unsupported exact pad shape {pad.shape!r}; "
                                "full rectangle used conservatively"
                            ),
                        )
                    )
                obstacles.append(
                    _Obstacle(
                        source_id=item.source_id,
                        layer=layer,
                        kind=_ObstacleKind.POLYGON,
                        polygon=polygon,
                        inflation_mm=profile.fab_spacing.minimum_copper_clearance_mm,
                    )
                )
                continue
            if pad_shape is not None and pad_shape[0].shape not in {"", "circle", "oval"}:
                pad, polygon = pad_shape
                issues.append(
                    CorridorGeometryIssue(
                        source_id=item.parent_source_id or item.source_id,
                        layer=layer,
                        verification=CorridorGeometryVerification.UNSUPPORTED,
                        reason=(
                            f"unsupported exact pad shape {pad.shape!r}; "
                            "full rectangle used conservatively"
                        ),
                    )
                )
                obstacles.append(
                    _Obstacle(
                        source_id=item.source_id,
                        layer=layer,
                        kind=_ObstacleKind.POLYGON,
                        polygon=polygon,
                        inflation_mm=profile.fab_spacing.minimum_copper_clearance_mm,
                    )
                )
                continue
        if item.is_hole:
            hole_key = (item.parent_source_id or item.source_id, layer)
            if hole_key in seen_holes:
                continue
            seen_holes.add(hole_key)
            inflation = profile.fab_spacing.minimum_hole_to_copper_mm
        else:
            inflation = profile.fab_spacing.minimum_copper_clearance_mm
        obstacles.append(
            _Obstacle(
                source_id=item.source_id,
                layer=layer,
                kind=_ObstacleKind.STADIUM,
                stadium_a=item.a,
                stadium_b=item.b,
                radius_mm=item.radius,
                inflation_mm=inflation,
            )
        )
    for index, (net_name, raw_layer, rectangle) in enumerate(layout.zones):
        if raw_layer not in LAYERS:
            issues.append(
                CorridorGeometryIssue(
                    source_id=f"zone:{index}",
                    verification=CorridorGeometryVerification.UNSUPPORTED,
                    reason=f"unsupported copper zone layer {raw_layer!r}",
                )
            )
            continue
        if net_name in selected:
            issues.append(
                CorridorGeometryIssue(
                    source_id=f"zone:{index}",
                    layer=raw_layer,
                    verification=CorridorGeometryVerification.UNSUPPORTED,
                    reason="target-net zone fill cannot prove terminal connectivity",
                )
            )
        obstacles.append(
            _Obstacle(
                source_id=f"zone:{index}",
                layer=raw_layer,
                kind=_ObstacleKind.RECTANGLE,
                rectangle=_ordered_bounds(rectangle),
                inflation_mm=profile.fab_spacing.minimum_copper_clearance_mm,
            )
        )
    return obstacles, pad_copper, issues


def _roundrect_bbox_error_mm(pad: PadSpec) -> tuple[float | None, str | None]:
    """Return a strict Hausdorff cap for the conservative roundrect bbox.

    The enclosing rectangle differs furthest at each removed corner.  For
    source corner radius ``r`` that distance is exactly ``r * (sqrt(2) - 1)``.
    Decimal source values and an upward-rounded square root keep the retained
    float strictly conservative instead of relying on binary libm rounding.
    """

    if pad.chamfer_ratio is not None or pad.chamfer_positions:
        return None, "chamfered roundrect pad geometry is unsupported"
    anchor = pad.source_anchor
    if anchor is None:
        return None, "roundrect pad is missing its exact source anchor"
    ratio = pad.roundrect_rratio
    dimensions = (
        anchor.width_mm,
        anchor.height_mm,
        pad.width_mm,
        pad.height_mm,
    )
    if (
        ratio is None
        or not math.isfinite(ratio)
        or ratio < 0.0
        or ratio > 0.5
        or any(not math.isfinite(value) or value <= 0.0 for value in dimensions)
    ):
        return None, "roundrect pad has invalid source dimensions or corner-radius ratio"
    if (anchor.width_mm, anchor.height_mm) != (pad.width_mm, pad.height_mm):
        return None, "roundrect routing dimensions differ from its exact source anchor"
    if ratio == 0.0:
        return None, None

    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_CEILING
        root_two = context.sqrt(Decimal(2)).next_plus(context)
        radius = min(
            Decimal(str(anchor.width_mm)),
            Decimal(str(anchor.height_mm)),
        ) * Decimal(str(ratio))
        upper = radius * (root_two - Decimal(1))
    maximum_error_mm = math.nextafter(float(upper), math.inf)
    if not math.isfinite(maximum_error_mm) or maximum_error_mm <= 0.0:
        return None, "roundrect pad error bound could not be represented"
    return maximum_error_mm, None


def _pad_shape_map(layout: BoardLayout) -> dict[str, tuple[PadSpec, tuple[Point, ...]]]:
    result: dict[str, tuple[PadSpec, tuple[Point, ...]]] = {}
    for component, anchor_x in layout.placements:
        reference = component.reference
        anchor = (anchor_x, placement_y(layout, reference))
        rotation = placement_rotation(layout, reference)
        flipped = reference in layout.part_flip
        for index, pad in enumerate(FOOTPRINT_LIBRARY[component.footprint].pads):
            corners = (
                (-pad.width_mm / 2, -pad.height_mm / 2),
                (pad.width_mm / 2, -pad.height_mm / 2),
                (pad.width_mm / 2, pad.height_mm / 2),
                (-pad.width_mm / 2, pad.height_mm / 2),
            )
            polygon: list[Point] = []
            for dx, dy in corners:
                dx, dy = rotate_offset(dx, dy, pad.angle_deg)
                local = (pad.x_mm + dx, pad.y_mm + dy)
                if flipped:
                    px, py = rotate_offset(local[0], local[1], (360.0 - rotation) % 360.0)
                    placed = (anchor[0] - px, anchor[1] + py)
                else:
                    px, py = rotate_offset(local[0], local[1], rotation)
                    placed = (anchor[0] + px, anchor[1] + py)
                polygon.append(placed)
            result[f"pad:{reference}:{index}"] = (pad, tuple(polygon))
    return result


def _derive_demands(
    selected: Sequence[str],
    widths: Mapping[str, float],
    default_width_mm: float,
    quantum_mm: float,
    profile: PcbRuleProfile,
    pairwise_domains: Sequence[PairwiseClearanceDomain],
    pad_copper: Sequence[tuple[str, str, _Stadium]],
    cells: Sequence[CorridorCell],
) -> tuple[tuple[CorridorNetDemand, ...], tuple[str, ...]]:
    by_terminal: dict[tuple[str, str], list[_Stadium]] = {}
    for net, terminal_id, copper in pad_copper:
        if net in selected:
            by_terminal.setdefault((net, terminal_id), []).append(copper)
    terminal_sets: dict[str, tuple[CorridorTerminal, ...]] = {}
    unmapped: list[str] = []
    for net in selected:
        terminals: list[CorridorTerminal] = []
        for (_net, terminal_id), copper_items in sorted(by_terminal.items()):
            if _net != net:
                continue
            candidate_ids = tuple(
                cell.cell_id
                for cell in cells
                if any(
                    item.layer == cell.layer and _pad_intersects_bounds(item, cell.bounds_mm)
                    for item in copper_items
                )
            )
            if not candidate_ids:
                unmapped.append(terminal_id)
            terminals.append(
                CorridorTerminal(
                    terminal_id=terminal_id,
                    candidate_cell_ids=candidate_ids,
                )
            )
        if len(terminals) >= 2:
            terminal_sets[net] = tuple(terminals)

    demands: list[CorridorNetDemand] = []
    active_net_names = frozenset(terminal_sets)
    for net in selected:
        demand_terminals = terminal_sets.get(net)
        if demand_terminals is None:
            continue
        width = widths.get(net, default_width_mm)
        clearance = conservative_clearance_for_net(
            net,
            active_net_names,
            profile.fab_spacing.minimum_copper_clearance_mm,
            pairwise_domains,
        )
        demands.append(
            CorridorNetDemand(
                demand_id="area:" + _fingerprint({"net_name": net}),
                net_name=net,
                width_mm=width,
                allowed_layers=LAYERS,
                via_policy=CorridorViaPolicy.ALLOWED,
                terminals=demand_terminals,
                ordinary_span_units=_conservative_span_units(
                    width,
                    clearance.effective_clearance_mm,
                    quantum_mm,
                ),
                effective_clearance_mm=clearance.effective_clearance_mm,
                pairwise_domain_ids=clearance.pairwise_domain_ids,
            )
        )
    return tuple(demands), tuple(sorted(set(unmapped)))


def _conservative_span_units(width_mm: float, clearance_mm: float, quantum_mm: float) -> int:
    """Round exact decimal input values upward without epsilon under-reservation."""
    ratio = (Decimal(str(width_mm)) + Decimal(str(clearance_mm))) / Decimal(str(quantum_mm))
    return int(ratio.to_integral_value(rounding=ROUND_CEILING))


def _build_via_portals(
    cells: Mapping[tuple[Layer, int, int], CorridorCell],
    outline: tuple[Point, ...],
    cutouts: tuple[tuple[Point, ...], ...],
    obstacles: Sequence[_Obstacle],
    pad_copper: Sequence[tuple[str, str, _Stadium]],
    profile: PcbRuleProfile,
    layout_fingerprint: str,
    profile_fingerprint: str,
) -> tuple[CorridorViaPortal, ...]:
    result: list[CorridorViaPortal] = []
    via_radius = profile.geometry.routing_via_diameter_mm / 2
    for (layer, ix, iy), front in sorted(cells.items()):
        if layer != "F.Cu":
            continue
        back = cells.get(("B.Cu", ix, iy))
        if back is None:
            continue
        min_x, min_y, max_x, max_y = front.bounds_mm
        site = ((min_x + max_x) / 2, (min_y + max_y) / 2)
        if not _point_inside_outline_with_margin(
            site,
            outline,
            profile.fab_spacing.minimum_copper_to_edge_mm + via_radius,
        ):
            continue
        if any(
            not _point_outside_cutout_with_margin(
                site,
                cutout,
                profile.fab_spacing.minimum_copper_to_edge_mm + via_radius,
            )
            for cutout in cutouts
        ):
            continue
        if any(_obstacle_blocks_point(item, site, via_radius) for item in obstacles):
            continue
        if any(
            _point_seg_distance(site, copper.a, copper.b)
            <= copper.radius + via_radius + profile.fab_spacing.minimum_copper_clearance_mm
            for _net, _terminal_id, copper in pad_copper
        ):
            continue
        resource_id = "via-site:" + _fingerprint(
            {
                "schema_version": 1,
                "front_cell_id": front.cell_id,
                "back_cell_id": back.cell_id,
                "site_mm": site,
                "profile_fingerprint": profile_fingerprint,
                "layout_geometry_fingerprint": layout_fingerprint,
            }
        )
        result.append(
            CorridorViaPortal(
                resource_id=resource_id,
                front_cell_id=front.cell_id,
                back_cell_id=back.cell_id,
                guaranteed_site_count=1,
                possible_site_count=1,
                candidate_sites_mm=(site,),
                verification=CorridorGeometryVerification.EXACT,
            )
        )
    return tuple(result)


def _cell_id(
    layout_fingerprint: str,
    profile_fingerprint: str,
    layer: Layer,
    ix: int,
    iy: int,
    bounds: Bounds,
) -> str:
    return "cell:" + _fingerprint(
        {
            "schema_version": 1,
            "layout_geometry_fingerprint": layout_fingerprint,
            "profile_fingerprint": profile_fingerprint,
            "layer": layer,
            "ix": ix,
            "iy": iy,
            "bounds_mm": bounds,
        }
    )


def _require_positive_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _ordered_bounds(bounds: Bounds) -> Bounds:
    x1, y1, x2, y2 = bounds
    if any(not math.isfinite(value) for value in bounds):
        raise ValueError("rectangle coordinates must be finite")
    if x1 == x2 or y1 == y2:
        raise ValueError("rectangle must have positive area")
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def _canonical_outline(raw: Sequence[Point]) -> tuple[Point, ...]:
    points = tuple(raw[:-1] if len(raw) > 1 and raw[0] == raw[-1] else raw)
    if len(points) < 3 or any(not math.isfinite(value) for point in points for value in point):
        raise ValueError("outline requires at least three finite vertices")
    area = sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )
    if abs(area) <= _EPSILON:
        raise ValueError("outline must have non-zero area")
    edges = [(points[index], points[(index + 1) % len(points)]) for index in range(len(points))]
    for first, (a, b) in enumerate(edges):
        for second in range(first + 1, len(edges)):
            if second in {first, (first + 1) % len(edges)} or first == (second + 1) % len(edges):
                continue
            if _segments_intersect(a, b, *edges[second]):
                raise ValueError("outline must be a simple polygon")
    ordered = points if area > 0 else tuple(reversed(points))
    start = min(range(len(ordered)), key=lambda index: ordered[index])
    return ordered[start:] + ordered[:start]


def _closed_cell_inside_outline(
    bounds: Bounds,
    outline: tuple[Point, ...],
    margin: float,
) -> bool:
    center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    return _point_inside_polygon(center, outline) and all(
        _segment_rectangle_distance(a, b, bounds) > margin + _EPSILON
        for a, b in _polygon_edges(outline)
    )


def _closed_cell_outside_cutout(
    bounds: Bounds,
    cutout: tuple[Point, ...],
    margin: float,
) -> bool:
    center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    return not _point_inside_polygon(center, cutout) and all(
        _segment_rectangle_distance(a, b, bounds) > margin + _EPSILON
        for a, b in _polygon_edges(cutout)
    )


def _point_inside_outline_with_margin(
    point: Point,
    outline: tuple[Point, ...],
    margin: float,
) -> bool:
    return _point_inside_polygon(point, outline) and all(
        _point_seg_distance(point, a, b) > margin + _EPSILON for a, b in _polygon_edges(outline)
    )


def _point_outside_cutout_with_margin(
    point: Point,
    cutout: tuple[Point, ...],
    margin: float,
) -> bool:
    return not _point_inside_polygon(point, cutout) and all(
        _point_seg_distance(point, a, b) > margin + _EPSILON for a, b in _polygon_edges(cutout)
    )


def _obstacle_intersects_bounds(obstacle: _Obstacle, bounds: Bounds) -> bool:
    if obstacle.kind is _ObstacleKind.STADIUM:
        assert obstacle.stadium_a is not None and obstacle.stadium_b is not None
        return (
            _segment_rectangle_distance(obstacle.stadium_a, obstacle.stadium_b, bounds)
            <= obstacle.radius_mm + obstacle.inflation_mm + _EPSILON
        )
    if obstacle.kind is _ObstacleKind.RECTANGLE:
        assert obstacle.rectangle is not None
        return _bounds_distance(obstacle.rectangle, bounds) <= obstacle.inflation_mm + _EPSILON
    return _polygon_rectangle_distance(obstacle.polygon, bounds) <= obstacle.inflation_mm + _EPSILON


def _obstacle_blocks_point(obstacle: _Obstacle, point: Point, radius: float) -> bool:
    clearance = obstacle.inflation_mm + radius
    if obstacle.kind is _ObstacleKind.STADIUM:
        assert obstacle.stadium_a is not None and obstacle.stadium_b is not None
        return _point_seg_distance(point, obstacle.stadium_a, obstacle.stadium_b) <= (
            obstacle.radius_mm + clearance + _EPSILON
        )
    if obstacle.kind is _ObstacleKind.RECTANGLE:
        assert obstacle.rectangle is not None
        return _point_bounds_distance(point, obstacle.rectangle) <= clearance + _EPSILON
    return _point_polygon_distance(point, obstacle.polygon) <= clearance + _EPSILON


def _pad_intersects_bounds(item: _Stadium, bounds: Bounds) -> bool:
    return _segment_rectangle_distance(item.a, item.b, bounds) <= item.radius + _EPSILON


def _polygon_edges(polygon: Sequence[Point]) -> tuple[tuple[Point, Point], ...]:
    return tuple(
        (polygon[index], polygon[(index + 1) % len(polygon)]) for index in range(len(polygon))
    )


def _bounds_polygon(bounds: Bounds) -> tuple[Point, ...]:
    return (
        (bounds[0], bounds[1]),
        (bounds[2], bounds[1]),
        (bounds[2], bounds[3]),
        (bounds[0], bounds[3]),
    )


def _segment_rectangle_distance(a: Point, b: Point, bounds: Bounds) -> float:
    if _point_in_closed_bounds(a, bounds) or _point_in_closed_bounds(b, bounds):
        return 0.0
    edges = _polygon_edges(_bounds_polygon(bounds))
    if any(_segments_intersect(a, b, c, d) for c, d in edges):
        return 0.0
    return min(
        *(_point_seg_distance(corner, a, b) for corner in _bounds_polygon(bounds)),
        *(
            _point_seg_distance(endpoint, edge_start, edge_end)
            for endpoint in (a, b)
            for edge_start, edge_end in edges
        ),
    )


def _polygon_rectangle_distance(polygon: Sequence[Point], bounds: Bounds) -> float:
    rectangle = _bounds_polygon(bounds)
    if any(_point_in_closed_bounds(point, bounds) for point in polygon):
        return 0.0
    if any(_point_inside_polygon(point, tuple(polygon)) for point in rectangle):
        return 0.0
    poly_edges = _polygon_edges(polygon)
    rect_edges = _polygon_edges(rectangle)
    if any(_segments_intersect(a, b, c, d) for a, b in poly_edges for c, d in rect_edges):
        return 0.0
    return min(_segment_segment_distance(a, b, c, d) for a, b in poly_edges for c, d in rect_edges)


def _point_polygon_distance(point: Point, polygon: Sequence[Point]) -> float:
    if _point_inside_polygon(point, tuple(polygon)):
        return 0.0
    return min(_point_seg_distance(point, a, b) for a, b in _polygon_edges(polygon))


def _bounds_distance(first: Bounds, second: Bounds) -> float:
    dx = max(first[0] - second[2], second[0] - first[2], 0.0)
    dy = max(first[1] - second[3], second[1] - first[3], 0.0)
    return math.hypot(dx, dy)


def _point_bounds_distance(point: Point, bounds: Bounds) -> float:
    dx = max(bounds[0] - point[0], point[0] - bounds[2], 0.0)
    dy = max(bounds[1] - point[1], point[1] - bounds[3], 0.0)
    return math.hypot(dx, dy)


def _point_in_closed_bounds(point: Point, bounds: Bounds) -> bool:
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def _point_inside_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    if any(_point_seg_distance(point, a, b) <= _EPSILON for a, b in _polygon_edges(polygon)):
        return False
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in _polygon_edges(polygon):
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if crossing > x:
                inside = not inside
    return inside


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orientation(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    values = (
        orientation(a, b, c),
        orientation(a, b, d),
        orientation(c, d, a),
        orientation(c, d, b),
    )
    if values[0] * values[1] < -_EPSILON and values[2] * values[3] < -_EPSILON:
        return True
    return any(
        abs(value) <= _EPSILON and _point_on_segment(point, start, end)
        for value, point, start, end in (
            (values[0], c, a, b),
            (values[1], d, a, b),
            (values[2], a, c, d),
            (values[3], b, c, d),
        )
    )


def _point_on_segment(point: Point, a: Point, b: Point) -> bool:
    return (
        min(a[0], b[0]) - _EPSILON <= point[0] <= max(a[0], b[0]) + _EPSILON
        and min(a[1], b[1]) - _EPSILON <= point[1] <= max(a[1], b[1]) + _EPSILON
    )


def _segment_segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_seg_distance(a, c, d),
        _point_seg_distance(b, c, d),
        _point_seg_distance(c, a, b),
        _point_seg_distance(d, a, b),
    )
