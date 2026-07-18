"""Per-net negotiated-congestion candidate search on the legacy KiCad grid.

This R2.2b seam preserves ``GridRouter`` hard geometry while replacing only its
path search cost.  It does not commit the returned claims or orchestrate passes.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, TypeAlias, cast

from pcbsmith.kicad.astar_router import (
    GRID_MM,
    LAYERS,
    GridRouter,
    RouteResult,
    RoutingError,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment, ViaSpec
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_resources import (
    LayerName,
    NetResourceClaims,
    OccupancyLedger,
    PairwiseClearanceDomain,
    RoutingResourceKey,
    build_pairwise_clearance_domains,
    capsule_move_claims,
    capsule_segment_claims,
    symmetric_halo_radius,
    via_claims,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.routing_ir import RoutingFailureReason
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

GridNode: TypeAlias = tuple[str, int, int]
GridTrackTransition: TypeAlias = tuple[GridNode, GridNode]
Direction: TypeAlias = tuple[int, int] | None
LabelKey: TypeAlias = tuple[GridNode, Direction, frozenset[RoutingResourceKey]]
LabelScore: TypeAlias = tuple[int, int, int, int, int, int]


def _require_non_negative_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


@dataclass(frozen=True, order=True)
class GridClaimDomain:
    """One layer-resource domain and the physical halos claimed within it."""

    domain_id: str
    track_halo_radius_mm: float
    via_halo_radius_mm: float

    def __post_init__(self) -> None:
        if not self.domain_id:
            raise ValueError("claim domain_id must be non-empty")
        for field in ("track_halo_radius_mm", "via_halo_radius_mm"):
            value = getattr(self, field)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field} must be finite and non-negative")


@dataclass(frozen=True)
class GridSoftGuide:
    """Optional, non-binding preferred search transitions on one grid."""

    grid_mm: float
    allowed_track_nodes: frozenset[GridNode]
    allowed_track_transitions: frozenset[GridTrackTransition]
    allowed_via_cells: frozenset[tuple[int, int]]
    off_guide_transition_cost_units: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.grid_mm) or self.grid_mm <= 0:
            raise ValueError("grid_mm must be finite and positive")
        _require_non_negative_int(
            self.off_guide_transition_cost_units,
            "off_guide_transition_cost_units",
        )
        if not isinstance(self.allowed_track_nodes, frozenset):
            raise TypeError("allowed_track_nodes must be a frozenset")
        if not isinstance(self.allowed_track_transitions, frozenset):
            raise TypeError("allowed_track_transitions must be a frozenset")
        if not isinstance(self.allowed_via_cells, frozenset):
            raise TypeError("allowed_via_cells must be a frozenset")
        for node in self.allowed_track_nodes:
            if (
                not isinstance(node, tuple)
                or len(node) != 3
                or node[0] not in LAYERS
                or not all(
                    isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in node[1:]
                )
            ):
                raise ValueError(f"invalid allowed track node {node!r}")
        canonical_transitions: set[GridTrackTransition] = set()
        for transition in self.allowed_track_transitions:
            if not isinstance(transition, tuple) or len(transition) != 2:
                raise ValueError(f"invalid allowed track transition {transition!r}")
            start, end = transition
            if start not in self.allowed_track_nodes or end not in self.allowed_track_nodes:
                raise ValueError("allowed track transition endpoints must be allowed track nodes")
            if start[0] != end[0]:
                raise ValueError("allowed track transitions cannot change layers")
            dx = abs(start[1] - end[1])
            dy = abs(start[2] - end[2])
            if max(dx, dy) != 1:
                raise ValueError("allowed track transitions must join adjacent grid nodes")
            canonical_transitions.add((start, end) if start <= end else (end, start))
        object.__setattr__(
            self,
            "allowed_track_transitions",
            frozenset(canonical_transitions),
        )
        for cell in self.allowed_via_cells:
            if (
                not isinstance(cell, tuple)
                or len(cell) != 2
                or not all(
                    isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in cell
                )
            ):
                raise ValueError(f"invalid allowed via cell {cell!r}")


@dataclass(frozen=True)
class NegotiatedGridRoute:
    """One complete emitted route plus its final set-valued resource claim."""

    result: RouteResult
    claims: NetResourceClaims
    base_cost_units: int
    congestion_cost_units: int
    guidance_cost_units: int = 0
    prefix_alternative_id: str | None = None
    prefix_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.result.net_name != self.claims.net_name:
            raise ValueError("route result and claims must name the same net")
        _require_non_negative_int(self.base_cost_units, "base_cost_units")
        _require_non_negative_int(self.congestion_cost_units, "congestion_cost_units")
        _require_non_negative_int(self.guidance_cost_units, "guidance_cost_units")
        if (self.prefix_alternative_id is None) != (self.prefix_fingerprint is None):
            raise ValueError("prefix identity and fingerprint must be present together")
        if self.prefix_alternative_id is not None and not self.prefix_alternative_id:
            raise ValueError("prefix alternative identity must be non-empty")
        if self.prefix_fingerprint is not None and (
            len(self.prefix_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.prefix_fingerprint)
        ):
            raise ValueError("prefix fingerprint must be a lowercase SHA-256")


def ordinary_claim_domain(
    track_width_mm: float,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> GridClaimDomain:
    """Build the universal ordinary-spacing resource domain for one width."""
    clearance = profile.fab_spacing.minimum_copper_clearance_mm
    return GridClaimDomain(
        domain_id="ordinary",
        track_halo_radius_mm=symmetric_halo_radius(track_width_mm, clearance),
        via_halo_radius_mm=symmetric_halo_radius(
            profile.geometry.routing_via_diameter_mm,
            clearance,
        ),
    )


def pairwise_claim_domain(
    domain: PairwiseClearanceDomain,
    net_name: str,
    *,
    track_width_mm: float,
    via_diameter_mm: float,
) -> GridClaimDomain:
    """Conservatively adapt one pairwise domain for a named net.

    R2.2b applies the domain to the complete routed net.  Mask-state, role, and
    component-exemption narrowing are deliberately ignored: route-search copper
    has no sound per-transition selector proof yet, so net-wide claims are the
    conservative behavior.
    """
    if not domain.applies_to(net_name):
        raise ValueError(f"net {net_name!r} is not in pairwise domain")
    return GridClaimDomain(
        domain_id=domain.domain_id,
        track_halo_radius_mm=symmetric_halo_radius(
            track_width_mm,
            domain.minimum_clearance_mm,
        ),
        via_halo_radius_mm=symmetric_halo_radius(
            via_diameter_mm,
            domain.minimum_clearance_mm,
        ),
    )


def pairwise_claim_domains_for_net(
    domains: Iterable[PairwiseClearanceDomain],
    net_name: str,
    *,
    track_width_mm: float,
    via_diameter_mm: float,
) -> tuple[GridClaimDomain, ...]:
    """Return stable, de-duplicated net-wide adapters for applicable domains."""
    adapted: dict[str, GridClaimDomain] = {}
    for domain in sorted(domains):
        if not domain.applies_to(net_name):
            continue
        claim_domain = pairwise_claim_domain(
            domain,
            net_name,
            track_width_mm=track_width_mm,
            via_diameter_mm=via_diameter_mm,
        )
        previous = adapted.get(claim_domain.domain_id)
        if previous is not None and previous != claim_domain:
            raise ValueError(f"conflicting pairwise claim domain {claim_domain.domain_id!r}")
        adapted[claim_domain.domain_id] = claim_domain
    return tuple(sorted(adapted.values()))


def grid_claim_domains_for_net(
    net_name: str,
    track_width_mm: float,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    *,
    pairwise_domains: Iterable[PairwiseClearanceDomain] | None = None,
) -> tuple[GridClaimDomain, ...]:
    """Build ordinary plus conservative pairwise domains for one routed net."""
    source_domains = (
        build_pairwise_clearance_domains(
            profile.profile_id,
            profile.fab_spacing.pairwise_clearances,
        )
        if pairwise_domains is None
        else tuple(pairwise_domains)
    )
    domains = (
        ordinary_claim_domain(track_width_mm, profile),
        *pairwise_claim_domains_for_net(
            source_domains,
            net_name,
            track_width_mm=track_width_mm,
            via_diameter_mm=profile.geometry.routing_via_diameter_mm,
        ),
    )
    by_id: dict[str, GridClaimDomain] = {}
    for domain in domains:
        previous = by_id.get(domain.domain_id)
        if previous is not None and previous != domain:
            raise ValueError(f"conflicting grid claim domain {domain.domain_id!r}")
        by_id[domain.domain_id] = domain
    return tuple(sorted(by_id.values()))


class _NegotiatedGridRouter(GridRouter):
    """Legacy hard geometry with set-valued present/history search costs."""

    def __init__(
        self,
        layout: BoardLayout,
        netlist: BoardNetlist,
        *,
        net_name: str,
        track_width_mm: float,
        grid_mm: float,
        profile: PcbRuleProfile,
        clearance_groups: Sequence[tuple[Collection[str], Collection[str], float, Collection[str]]],
        max_expansions: int | None,
        ledger: OccupancyLedger,
        history: Mapping[RoutingResourceKey, int],
        present_factor_units: int,
        cost_policy: NegotiatedCostPolicy,
        claim_domains: Sequence[GridClaimDomain],
        soft_guide: GridSoftGuide | None,
        route_prefix: GridRoutePrefix | None,
    ) -> None:
        super().__init__(
            layout,
            netlist,
            net_name=net_name,
            track_width_mm=track_width_mm,
            grid_mm=grid_mm,
            profile=profile,
            clearance_groups=clearance_groups,
            max_expansions=max_expansions,
        )
        _require_non_negative_int(present_factor_units, "present_factor_units")
        for resource, value in history.items():
            if not isinstance(resource, RoutingResourceKey):
                raise TypeError("history keys must be RoutingResourceKey values")
            _require_non_negative_int(value, "history resource cost")
        if not claim_domains:
            raise ValueError("at least one grid claim domain is required")
        canonical_domains = tuple(sorted(set(claim_domains)))
        if len({item.domain_id for item in canonical_domains}) != len(canonical_domains):
            raise ValueError("grid claim domain IDs must be unique")
        self._ledger = ledger
        self._history = history
        self._present_factor_units = present_factor_units
        self._cost_policy = cost_policy
        self._claim_domains = canonical_domains
        if soft_guide is not None and not math.isclose(
            soft_guide.grid_mm,
            self.grid,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                f"soft guide grid {soft_guide.grid_mm}mm does not match router grid {self.grid}mm"
            )
        self._soft_guide = soft_guide
        self._candidate_tree_claims: frozenset[RoutingResourceKey] = frozenset()
        self.base_cost_units = 0
        self.congestion_cost_units = 0
        self.guidance_cost_units = 0
        self._route_prefix = route_prefix
        self._prefix_resource_claims: frozenset[RoutingResourceKey] = frozenset()
        if route_prefix is not None:
            self._prepare_route_prefix(route_prefix)

    def _prepare_route_prefix(self, prefix: GridRoutePrefix) -> None:
        if prefix.net_name != self.net_name:
            raise ValueError("route prefix net does not match the candidate net")
        if not math.isclose(prefix.grid_mm, self.grid, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("route prefix grid does not match the candidate grid")
        if any(
            not math.isclose(segment.width_mm, self.width, rel_tol=0.0, abs_tol=1e-12)
            for segment in prefix.segments
        ):
            raise ValueError("route prefix width does not match the candidate width")
        if any(
            not math.isclose(
                via.size_mm,
                self.profile.geometry.routing_via_diameter_mm,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not math.isclose(
                via.drill_mm,
                self.profile.geometry.routing_via_drill_mm,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for via in prefix.vias
        ):
            raise ValueError("route prefix via geometry does not match the candidate profile")

        pads = {pad.parent_source_id or pad.source_id: pad for pad in self._ordered_physical_pads()}
        for source_id, anchor in prefix.covered_pad_anchors:
            pad = pads.get(source_id)
            if pad is None:
                raise ValueError(f"route prefix covers unknown physical pad {source_id!r}")
            if anchor not in self._pad_nodes(pad):
                raise ValueError(
                    f"route prefix anchor for {source_id!r} does not touch its physical pad"
                )

        exit_layer, exit_ix, exit_iy = prefix.exit_node
        if (
            not (0 <= exit_ix < self.cols and 0 <= exit_iy < self.rows)
            or (exit_ix, exit_iy) in self.blocked[exit_layer]
        ):
            raise ValueError("route prefix exit is outside legal candidate copper")
        for segment in prefix.segments:
            self._validate_prefix_segment(segment)
        for via in prefix.vias:
            cell = (self._exact_grid_index(via.x), self._exact_grid_index(via.y))
            if cell in self.via_blocked:
                raise ValueError("route prefix via occupies a blocked candidate site")

        resources = self._geometry_claims(prefix.segments, prefix.vias)
        self._prefix_resource_claims = resources
        self._candidate_tree_claims = resources
        self.congestion_cost_units = self._resource_cost(resources)
        self.base_cost_units = self._prefix_base_cost(prefix)

    def _validate_prefix_segment(self, segment: TrackSegment) -> None:
        start = (
            segment.layer,
            self._exact_grid_index(segment.x1),
            self._exact_grid_index(segment.y1),
        )
        end = (
            segment.layer,
            self._exact_grid_index(segment.x2),
            self._exact_grid_index(segment.y2),
        )
        dx = end[1] - start[1]
        dy = end[2] - start[2]
        if any(
            not (0 <= node[1] < self.cols and 0 <= node[2] < self.rows) for node in (start, end)
        ):
            raise ValueError("route prefix segment lies outside the candidate board grid")
        if dx != 0 and dy != 0 and abs(dx) != abs(dy):
            raise ValueError("route prefix segments must be horizontal, vertical, or 45-degree")
        step_x = (dx > 0) - (dx < 0)
        step_y = (dy > 0) - (dy < 0)
        x, y = start[1], start[2]
        blocked = self.blocked[segment.layer]
        if (x, y) in blocked:
            raise ValueError("route prefix segment occupies blocked candidate copper")
        while (x, y) != end[1:]:
            if step_x and step_y and ((x + step_x, y) in blocked or (x, y + step_y) in blocked):
                raise ValueError("route prefix diagonal cuts a blocked candidate corner")
            x += step_x
            y += step_y
            if (x, y) in blocked:
                raise ValueError("route prefix segment occupies blocked candidate copper")

    def _geometry_claims(
        self,
        segments: Sequence[TrackSegment],
        vias: Sequence[ViaSpec],
    ) -> frozenset[RoutingResourceKey]:
        resources: set[RoutingResourceKey] = set()
        for segment in segments:
            resources.update(
                self._segment_claims(
                    segment.layer,
                    (segment.x1, segment.y1),
                    (segment.x2, segment.y2),
                )
            )
        for via in vias:
            ix = self._exact_grid_index(via.x)
            iy = self._exact_grid_index(via.y)
            for domain in self._claim_domains:
                resources.update(
                    via_claims(
                        domain.domain_id,
                        ix,
                        iy,
                        self.grid,
                        domain.via_halo_radius_mm,
                    )
                )
        return frozenset(resources)

    def _prefix_base_cost(self, prefix: GridRoutePrefix) -> int:
        total = len(prefix.vias) * self._cost_policy.via_cost_units
        for segment in prefix.segments:
            dx = abs(self._exact_grid_index(segment.x2) - self._exact_grid_index(segment.x1))
            dy = abs(self._exact_grid_index(segment.y2) - self._exact_grid_index(segment.y1))
            units = (
                self._cost_policy.diagonal_length_units
                if dx and dy
                else self._cost_policy.length_units_per_grid
            )
            total += max(dx, dy) * units
        return total

    def route_with_prefix(self) -> RouteResult:
        prefix = self._route_prefix
        if prefix is None:
            return self.route()
        covered = {source_id for source_id, _anchor in prefix.covered_pad_anchors}
        remaining = tuple(
            pad
            for pad in self._ordered_physical_pads()
            if (pad.parent_source_id or pad.source_id) not in covered
        )
        result = self._route_from_seed(
            remaining_pads=remaining,
            tree={prefix.exit_node},
            segments=list(prefix.segments),
            vias=list(prefix.vias),
            first_stub_pad=None,
        )
        unique_vias = tuple(dict.fromkeys(result.vias))
        if unique_vias == result.vias:
            return result
        return RouteResult(
            net_name=result.net_name,
            segments=result.segments,
            vias=unique_vias,
            length_mm=result.length_mm,
            expansion_count=result.expansion_count,
        )

    def _smooth(self, path: list[GridNode]) -> list[GridNode]:
        """Keep the searched transitions identical to the emitted grid path."""
        return path

    def _stub(
        self,
        segments: list[TrackSegment],
        node: GridNode,
        anchor: tuple[float, float],
    ) -> float:
        """Emit the legacy pad stub and add its unavoidable final claims once."""
        point = self._point(node[1:])
        length = super()._stub(segments, node, anchor)
        if length == 0.0:
            return length
        resources = self._segment_claims(node[0], point, anchor)
        newly_claimed = resources - self._candidate_tree_claims
        self._candidate_tree_claims |= resources
        self.base_cost_units += round(length / self.grid * self._cost_policy.length_units_per_grid)
        self.congestion_cost_units += self._resource_cost(newly_claimed)
        return length

    def _astar(
        self,
        sources: set[GridNode],
        targets: set[GridNode],
    ) -> list[GridNode]:
        target_cells = {(ix, iy) for _layer, ix, iy in targets}
        minimum_step_cost = min(
            self._cost_policy.length_units_per_grid,
            self._cost_policy.diagonal_length_units,
        )

        def heuristic(node: GridNode) -> int:
            _layer, ix, iy = node
            return min(
                max(abs(ix - tx), abs(iy - ty)) * minimum_step_cost for tx, ty in target_cells
            )

        # score = (total, congestion, guidance, via count, turn count, base)
        initial_score: LabelScore = (0, 0, 0, 0, 0, 0)
        open_heap: list[
            tuple[
                int,
                int,
                int,
                int,
                int,
                int,
                str,
                int,
                int,
                int,
                int,
                tuple[str, ...],
                int,
                LabelKey,
            ]
        ] = []
        scores: dict[LabelKey, LabelScore] = {}
        came: dict[LabelKey, LabelKey] = {}
        counter = 0
        for node in sorted(sources):
            state: LabelKey = (
                node,
                None,
                frozenset[RoutingResourceKey](),
            )
            scores[state] = initial_score
            heapq.heappush(
                open_heap,
                self._heap_entry(
                    node,
                    None,
                    frozenset(),
                    initial_score,
                    heuristic(node),
                    counter,
                    state,
                ),
            )
            counter += 1

        closed: set[LabelKey] = set()
        while open_heap:
            entry = heapq.heappop(open_heap)
            state = entry[-1]
            if state in closed:
                continue
            score = scores[state]
            node, incoming_direction, label_claims = state
            if node in targets:
                self._candidate_tree_claims |= label_claims
                self.base_cost_units += score[5]
                self.congestion_cost_units += score[1]
                self.guidance_cost_units += score[2]
                return self._reconstruct_path(state, came)
            if self.max_expansions is not None and self.expansion_count >= self.max_expansions:
                raise RoutingError(
                    f"Expansion budget exhausted for {self.net_name}.",
                    reason=RoutingFailureReason.EXPANSION_BUDGET,
                    expansion_count=self.expansion_count,
                )
            closed.add(state)
            self.expansion_count += 1

            for neighbour, direction, base_units, is_via in self._neighbours(
                node,
                incoming_direction,
            ):
                transition_claims = self._transition_claims(node, neighbour, is_via)
                newly_claimed = transition_claims - self._candidate_tree_claims - label_claims
                next_claims = label_claims | newly_claimed
                turn = (
                    direction is not None
                    and incoming_direction is not None
                    and direction != incoming_direction
                )
                turn_units = self._cost_policy.turn_cost_units if turn else 0
                next_base = score[5] + base_units + turn_units
                next_congestion = score[1] + self._resource_cost(newly_claimed)
                next_guidance = score[2] + self._guidance_cost(
                    node,
                    neighbour,
                    is_via,
                )
                next_vias = score[3] + int(is_via)
                next_turns = score[4] + int(turn)
                next_score: LabelScore = (
                    next_base + next_congestion + next_guidance,
                    next_congestion,
                    next_guidance,
                    next_vias,
                    next_turns,
                    next_base,
                )
                next_state = (neighbour, direction, next_claims)
                if next_score >= scores.get(
                    next_state,
                    (math.inf, math.inf, math.inf, math.inf, math.inf, math.inf),
                ):
                    continue
                scores[next_state] = next_score
                came[next_state] = state
                heapq.heappush(
                    open_heap,
                    self._heap_entry(
                        neighbour,
                        direction,
                        next_claims,
                        next_score,
                        heuristic(neighbour),
                        counter,
                        next_state,
                    ),
                )
                counter += 1

        raise RoutingError(
            f"No route found for {self.net_name} at grid {self.grid}mm.",
            expansion_count=self.expansion_count,
        )

    def _heap_entry(
        self,
        node: GridNode,
        direction: Direction,
        claims: frozenset[RoutingResourceKey],
        score: LabelScore,
        heuristic_units: int,
        counter: int,
        state: LabelKey,
    ) -> tuple[
        int,
        int,
        int,
        int,
        int,
        int,
        str,
        int,
        int,
        int,
        int,
        tuple[str, ...],
        int,
        LabelKey,
    ]:
        dx, dy = direction or (0, 0)
        return (
            score[0] + heuristic_units,
            score[1],
            score[2],
            score[3],
            score[4],
            score[5],
            node[0],
            node[1],
            node[2],
            dx,
            dy,
            tuple(sorted(resource.resource_id for resource in claims)),
            counter,
            state,
        )

    def _guidance_cost(
        self,
        start: GridNode,
        end: GridNode,
        is_via: bool,
    ) -> int:
        guide = self._soft_guide
        if guide is None or guide.off_guide_transition_cost_units == 0:
            return 0
        if is_via:
            allowed = (
                start in guide.allowed_track_nodes
                and end in guide.allowed_track_nodes
                and start[1:] in guide.allowed_via_cells
            )
        else:
            transition = (start, end) if start <= end else (end, start)
            allowed = transition in guide.allowed_track_transitions
        return 0 if allowed else guide.off_guide_transition_cost_units

    def _neighbours(
        self,
        node: GridNode,
        incoming_direction: Direction,
    ) -> list[tuple[GridNode, Direction, int, bool]]:
        del incoming_direction  # direction affects cost in the caller, not legality.
        layer, ix, iy = node
        neighbours: list[tuple[GridNode, Direction, int, bool]] = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = ix + dx, iy + dy
            if (
                0 <= nx < self.cols
                and 0 <= ny < self.rows
                and (
                    nx,
                    ny,
                )
                not in self.blocked[layer]
            ):
                neighbours.append(
                    (
                        (layer, nx, ny),
                        (dx, dy),
                        self._cost_policy.length_units_per_grid,
                        False,
                    )
                )
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = ix + dx, iy + dy
            if not (0 <= nx < self.cols and 0 <= ny < self.rows):
                continue
            if (
                (nx, ny) in self.blocked[layer]
                or (ix + dx, iy) in self.blocked[layer]
                or (ix, iy + dy) in self.blocked[layer]
            ):
                continue
            neighbours.append(
                (
                    (layer, nx, ny),
                    (dx, dy),
                    self._cost_policy.diagonal_length_units,
                    False,
                )
            )
        other = LAYERS[1] if layer == LAYERS[0] else LAYERS[0]
        if (ix, iy) not in self.via_blocked and (ix, iy) not in self.blocked[other]:
            neighbours.append(
                (
                    (other, ix, iy),
                    None,
                    self._cost_policy.via_cost_units,
                    True,
                )
            )
        return neighbours

    def _transition_claims(
        self,
        start: GridNode,
        end: GridNode,
        is_via: bool,
    ) -> frozenset[RoutingResourceKey]:
        resources: set[RoutingResourceKey] = set()
        for domain in self._claim_domains:
            if is_via:
                resources.update(
                    via_claims(
                        domain.domain_id,
                        start[1],
                        start[2],
                        self.grid,
                        domain.via_halo_radius_mm,
                    )
                )
            else:
                resources.update(
                    capsule_move_claims(
                        domain.domain_id,
                        cast(LayerName, start[0]),
                        start[1:],
                        end[1:],
                        self.grid,
                        domain.track_halo_radius_mm,
                    )
                )
        return frozenset(resources)

    def _segment_claims(
        self,
        layer: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> frozenset[RoutingResourceKey]:
        if layer not in LAYERS:
            raise RoutingError(f"Unsupported emitted copper layer {layer!r}.")
        resources: set[RoutingResourceKey] = set()
        for domain in self._claim_domains:
            resources.update(
                capsule_segment_claims(
                    domain.domain_id,
                    cast(LayerName, layer),
                    start,
                    end,
                    self.grid,
                    domain.track_halo_radius_mm,
                )
            )
        return frozenset(resources)

    def _resource_cost(self, resources: Iterable[RoutingResourceKey]) -> int:
        total = 0
        for resource in sorted(resources):
            other_demand = self._ledger.demand_without(resource, self.net_name)
            projected_overuse = max(
                0,
                other_demand + 1 - self._ledger.capacity,
            )
            total += self._present_factor_units * projected_overuse
            total += self._history.get(resource, 0)
        return total

    @staticmethod
    def _reconstruct_path(
        state: LabelKey,
        came: Mapping[LabelKey, LabelKey],
    ) -> list[GridNode]:
        path = [state[0]]
        while state in came:
            state = came[state]
            if path[-1] != state[0]:
                path.append(state[0])
        path.reverse()
        return path

    def final_claims(self, result: RouteResult) -> NetResourceClaims:
        """Re-rasterize only emitted copper after merge/prune cleanup."""
        return NetResourceClaims(
            self.net_name,
            self._geometry_claims(result.segments, result.vias),
        )

    def _exact_grid_index(self, value_mm: float) -> int:
        coordinate = value_mm / self.grid
        nearest = round(coordinate)
        if abs(coordinate - nearest) > 1e-9:
            raise RoutingError(
                f"Emitted via coordinate {value_mm}mm is not on the {self.grid}mm grid."
            )
        return nearest


def route_net_negotiated_candidate(
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    net_name: str,
    ledger: OccupancyLedger,
    history: Mapping[RoutingResourceKey, int],
    present_factor_units: int,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    *,
    track_width_mm: float = 0.4,
    grid_mm: float = GRID_MM,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    clearance_groups: Sequence[
        tuple[Collection[str], Collection[str], float, Collection[str]]
    ] = (),
    pairwise_domains: Iterable[PairwiseClearanceDomain] | None = None,
    max_expansions: int | None = None,
    soft_guide: GridSoftGuide | None = None,
    route_prefix: GridRoutePrefix | None = None,
) -> NegotiatedGridRoute:
    """Search one complete net against hard static geometry and soft claims.

    ``static_layout`` must already exclude every negotiable target route.  Pads,
    fixed geometry, and non-target copper stay hard through the inherited
    ``GridRouter`` maps.  The caller owns rip-up, commit, restore, and pass-level
    history updates; this function never mutates ``ledger``.
    """
    domains = grid_claim_domains_for_net(
        net_name,
        track_width_mm,
        profile,
        pairwise_domains=pairwise_domains,
    )
    router = _NegotiatedGridRouter(
        static_layout,
        netlist,
        net_name=net_name,
        track_width_mm=track_width_mm,
        grid_mm=grid_mm,
        profile=profile,
        clearance_groups=clearance_groups,
        max_expansions=max_expansions,
        ledger=ledger,
        history=history,
        present_factor_units=present_factor_units,
        cost_policy=cost_policy,
        claim_domains=domains,
        soft_guide=soft_guide,
        route_prefix=route_prefix,
    )
    result = router.route_with_prefix() if route_prefix is not None else router.route()
    claims = router.final_claims(result)
    if route_prefix is not None and not router._prefix_resource_claims.issubset(claims.resources):
        raise RoutingError("Emitted candidate did not preserve all route-prefix copper claims.")
    return NegotiatedGridRoute(
        result=result,
        claims=claims,
        base_cost_units=router.base_cost_units,
        congestion_cost_units=router.congestion_cost_units,
        guidance_cost_units=router.guidance_cost_units,
        prefix_alternative_id=(route_prefix.alternative_id if route_prefix is not None else None),
        prefix_fingerprint=(
            route_prefix.semantic_fingerprint() if route_prefix is not None else None
        ),
    )


def _endpoint_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be a lowercase SHA-256")


def _canonical_endpoint_graph(
    layer: str,
    portal_node: GridNode,
    allowed_track_nodes: Collection[GridNode],
    allowed_track_transitions: Collection[GridTrackTransition],
) -> tuple[frozenset[GridNode], frozenset[GridTrackTransition]]:
    if layer not in LAYERS:
        raise ValueError("certified endpoint graph layer is unsupported")
    nodes = frozenset(allowed_track_nodes)
    if not nodes:
        raise ValueError("certified endpoint graph requires allowed track nodes")
    for node in nodes:
        if (
            not isinstance(node, tuple)
            or len(node) != 3
            or node[0] != layer
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in node[1:]
            )
        ):
            raise ValueError(f"invalid certified endpoint graph node {node!r}")
    if portal_node not in nodes:
        raise ValueError("certified portal node is not in the allowed graph")
    transitions: set[GridTrackTransition] = set()
    for transition in allowed_track_transitions:
        if not isinstance(transition, tuple) or len(transition) != 2:
            raise ValueError(f"invalid certified endpoint graph transition {transition!r}")
        first, second = transition
        if first not in nodes or second not in nodes:
            raise ValueError("certified transition endpoints must be allowed nodes")
        if first == second or max(abs(first[1] - second[1]), abs(first[2] - second[2])) != 1:
            raise ValueError("certified transitions must join adjacent distinct nodes")
        transitions.add((first, second) if first < second else (second, first))
    adjacency: dict[GridNode, set[GridNode]] = {node: set() for node in nodes}
    for first, second in transitions:
        adjacency[first].add(second)
        adjacency[second].add(first)
    reached = {portal_node}
    pending = [portal_node]
    while pending:
        current = pending.pop()
        for neighbour in adjacency[current]:
            if neighbour not in reached:
                reached.add(neighbour)
                pending.append(neighbour)
    if reached != set(nodes):
        raise ValueError("certified endpoint graph must be connected to its portal")
    return nodes, frozenset(transitions)


def certified_endpoint_graph_fingerprint(
    *,
    grid_mm: float,
    layer: str,
    portal_node: GridNode,
    allowed_track_nodes: Collection[GridNode],
    allowed_track_transitions: Collection[GridTrackTransition],
) -> str:
    """Return the canonical identity of one exact same-layer escape graph."""
    if not math.isfinite(grid_mm) or grid_mm <= 0:
        raise ValueError("certified endpoint graph grid must be finite and positive")
    nodes, transitions = _canonical_endpoint_graph(
        layer,
        portal_node,
        allowed_track_nodes,
        allowed_track_transitions,
    )
    return _endpoint_fingerprint(
        {
            "schema_id": "pcbsmith-certified-endpoint-graph",
            "schema_version": 1,
            "grid_mm": grid_mm,
            "layer": layer,
            "portal_node": portal_node,
            "allowed_track_nodes": sorted(nodes),
            "allowed_track_transitions": sorted(transitions),
        }
    )


@dataclass(frozen=True)
class CertifiedEndpointGraph:
    """Exact caller-supplied authority for one same-layer endpoint graph."""

    grid_mm: float
    layer: str
    portal_node: GridNode
    allowed_track_nodes: frozenset[GridNode]
    allowed_track_transitions: frozenset[GridTrackTransition]
    graph_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_track_nodes, frozenset):
            raise TypeError("allowed_track_nodes must be a frozenset")
        if not isinstance(self.allowed_track_transitions, frozenset):
            raise TypeError("allowed_track_transitions must be a frozenset")
        nodes, transitions = _canonical_endpoint_graph(
            self.layer,
            self.portal_node,
            self.allowed_track_nodes,
            self.allowed_track_transitions,
        )
        object.__setattr__(self, "allowed_track_nodes", nodes)
        object.__setattr__(self, "allowed_track_transitions", transitions)
        expected = certified_endpoint_graph_fingerprint(
            grid_mm=self.grid_mm,
            layer=self.layer,
            portal_node=self.portal_node,
            allowed_track_nodes=nodes,
            allowed_track_transitions=transitions,
        )
        _require_sha256(self.graph_fingerprint, "graph_fingerprint")
        if self.graph_fingerprint != expected:
            raise ValueError("certified endpoint graph fingerprint is stale")


@dataclass(frozen=True)
class CertifiedEndpointTerminalSource:
    """Exact physical pad and exact lattice node selected by the caller."""

    component_ref: str
    pad_number: str
    net_name: str
    physical_pad_source_id: str
    source_node: GridNode

    def __post_init__(self) -> None:
        for field in (
            "component_ref",
            "pad_number",
            "net_name",
            "physical_pad_source_id",
        ):
            value = getattr(self, field)
            if not value or value != value.strip():
                raise ValueError(f"terminal {field} must be non-empty and stripped")
        node = self.source_node
        if (
            not isinstance(node, tuple)
            or len(node) != 3
            or node[0] not in LAYERS
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in node[1:]
            )
        ):
            raise ValueError("terminal source_node is invalid")

    def semantic_fingerprint(self) -> str:
        return _endpoint_fingerprint(
            {
                "schema_id": "pcbsmith-certified-endpoint-terminal-source",
                "schema_version": 1,
                "component_ref": self.component_ref,
                "pad_number": self.pad_number,
                "net_name": self.net_name,
                "physical_pad_source_id": self.physical_pad_source_id,
                "source_node": self.source_node,
            }
        )


def _endpoint_static_layout_fingerprint(layout: BoardLayout) -> str:
    canonical = replace(
        layout,
        placements=tuple(
            sorted(
                layout.placements,
                key=lambda item: (
                    item[0].reference,
                    item[0].value,
                    item[0].footprint,
                    item[0].uuid_path,
                    tuple(sorted(item[0].fields)),
                    item[1],
                ),
            )
        ),
        segments=tuple(
            sorted(
                layout.segments,
                key=lambda item: (
                    item.net_name,
                    item.layer,
                    item.width_mm,
                    item.x1,
                    item.y1,
                    item.x2,
                    item.y2,
                ),
            )
        ),
        vias=tuple(
            sorted(
                layout.vias,
                key=lambda item: (
                    item.net_name,
                    item.x,
                    item.y,
                    item.size_mm,
                    item.drill_mm,
                    item.front_mask.value,
                    item.back_mask.value,
                ),
            )
        ),
        part_y_mm=tuple(sorted(layout.part_y_mm)),
        part_rotation=tuple(sorted(layout.part_rotation)),
        zones=tuple(sorted(layout.zones)),
        graphics=tuple(sorted(layout.graphics)),
        part_flip=tuple(sorted(layout.part_flip)),
        hide_references=tuple(sorted(layout.hide_references)),
        part_reference_at=tuple(sorted(layout.part_reference_at)),
        mask_apertures=tuple(
            sorted(layout.mask_apertures, key=lambda item: item.semantic_fingerprint())
        ),
        cutouts=tuple(sorted(layout.cutouts, key=lambda item: item.semantic_fingerprint())),
    )
    return board_layout_fingerprint(canonical)


def _endpoint_netlist_fingerprint(netlist: BoardNetlist) -> str:
    return _endpoint_fingerprint(
        {
            "schema_id": "pcbsmith-certified-endpoint-netlist",
            "schema_version": 1,
            "components": sorted(
                (
                    {
                        "reference": item.reference,
                        "value": item.value,
                        "footprint": item.footprint,
                        "uuid_path": item.uuid_path,
                        "fields": sorted(item.fields),
                    }
                    for item in netlist.components
                ),
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
            "nets": sorted(
                ({"name": item.name, "nodes": sorted(item.nodes)} for item in netlist.nets),
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
        }
    )


def _canonical_endpoint_clearance_groups(
    groups: Sequence[tuple[Collection[str], Collection[str], float, Collection[str]]],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]], ...]:
    normalized: set[tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]]] = set()
    for nets_a, nets_b, gap_mm, exempt in groups:
        if not math.isfinite(gap_mm) or gap_mm < 0:
            raise ValueError("endpoint clearance gap must be finite and non-negative")
        side_a = tuple(sorted(set(nets_a)))
        side_b = tuple(sorted(set(nets_b)))
        exemptions = tuple(sorted(set(exempt)))
        identities = (*side_a, *side_b, *exemptions)
        if not side_a or not side_b or any(not item or item != item.strip() for item in identities):
            raise ValueError("endpoint clearance identities must be non-empty and stripped")
        low, high = sorted((side_a, side_b))
        normalized.add((low, high, gap_mm, exemptions))
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class CertifiedEndpointSearchBinding:
    """Canonical JSON identity of every input that can change endpoint search."""

    canonical_payload_json: str

    def __post_init__(self) -> None:
        try:
            payload = json.loads(self.canonical_payload_json)
        except json.JSONDecodeError as error:
            raise ValueError("endpoint search binding is not valid JSON") from error
        if not isinstance(payload, dict) or payload.get("schema_id") != (
            "pcbsmith-certified-endpoint-search-inputs"
        ):
            raise ValueError("endpoint search binding schema is invalid")
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if canonical != self.canonical_payload_json:
            raise ValueError("endpoint search binding JSON is not canonical")

    def semantic_fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_payload_json.encode("utf-8")).hexdigest()


def _endpoint_search_binding(
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    terminal_source: CertifiedEndpointTerminalSource,
    graph: CertifiedEndpointGraph,
    ledger: OccupancyLedger,
    history: Mapping[RoutingResourceKey, int],
    present_factor_units: int,
    cost_policy: NegotiatedCostPolicy,
    profile: PcbRuleProfile,
    clearance_groups: tuple[tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]], ...],
    claim_domains: tuple[GridClaimDomain, ...],
    forbidden: frozenset[RoutingResourceKey],
    track_width_mm: float,
    max_expansions: int,
) -> CertifiedEndpointSearchBinding:
    payload = {
        "schema_id": "pcbsmith-certified-endpoint-search-inputs",
        "schema_version": 1,
        "static_layout_fingerprint": _endpoint_static_layout_fingerprint(static_layout),
        "netlist_fingerprint": _endpoint_netlist_fingerprint(netlist),
        "ledger_fingerprint": ledger.semantic_fingerprint(),
        "terminal_source_fingerprint": terminal_source.semantic_fingerprint(),
        "graph_fingerprint": graph.graph_fingerprint,
        "history_costs": sorted(
            (resource.resource_id, value) for resource, value in history.items()
        ),
        "present_factor_units": present_factor_units,
        "cost_policy": cost_policy.semantic_payload(),
        "profile": profile.model_dump(mode="json"),
        "clearance_groups": clearance_groups,
        "claim_domains": [
            (item.domain_id, item.track_halo_radius_mm, item.via_halo_radius_mm)
            for item in claim_domains
        ],
        "hard_forbidden_resource_ids": sorted(item.resource_id for item in forbidden),
        "track_width_mm": track_width_mm,
        "grid_mm": graph.grid_mm,
        "max_expansions": max_expansions,
    }
    return CertifiedEndpointSearchBinding(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


@dataclass(frozen=True)
class CertifiedEndpointConnection:
    """Raw unsmoothed endpoint path and its exact emitted resource claims."""

    terminal_source: CertifiedEndpointTerminalSource
    graph: CertifiedEndpointGraph
    path: tuple[GridNode, ...]
    route: NegotiatedGridRoute
    terminal_source_fingerprint: str
    graph_fingerprint: str
    search_binding: CertifiedEndpointSearchBinding
    search_input_fingerprint: str

    def __post_init__(self) -> None:
        _require_sha256(self.terminal_source_fingerprint, "terminal_source_fingerprint")
        _require_sha256(self.graph_fingerprint, "graph_fingerprint")
        _require_sha256(self.search_input_fingerprint, "search_input_fingerprint")
        if self.search_input_fingerprint != self.search_binding.semantic_fingerprint():
            raise ValueError("endpoint search-input fingerprint is stale")
        binding = json.loads(self.search_binding.canonical_payload_json)
        if binding["terminal_source_fingerprint"] != self.terminal_source_fingerprint:
            raise ValueError("endpoint search binding owns the wrong terminal source")
        if binding["graph_fingerprint"] != self.graph_fingerprint:
            raise ValueError("endpoint search binding owns the wrong graph")
        if self.terminal_source_fingerprint != self.terminal_source.semantic_fingerprint():
            raise ValueError("terminal source fingerprint is stale")
        if self.graph_fingerprint != self.graph.graph_fingerprint:
            raise ValueError("endpoint graph fingerprint is stale")
        if not self.path or self.path[0] != self.terminal_source.source_node:
            raise ValueError("endpoint path does not start at its bound terminal node")
        if self.path[-1] != self.graph.portal_node:
            raise ValueError("endpoint path does not end at its certified portal")
        if any(node not in self.graph.allowed_track_nodes for node in self.path):
            raise ValueError("endpoint path leaves its certified allowed nodes")
        path_transitions = {
            (first, second) if first < second else (second, first)
            for first, second in zip(self.path, self.path[1:], strict=False)
        }
        if not path_transitions.issubset(self.graph.allowed_track_transitions):
            raise ValueError("endpoint path leaves its certified transitions")
        result = self.route.result
        if (
            result.net_name != self.terminal_source.net_name
            or self.route.claims.net_name != self.terminal_source.net_name
            or result.vias
        ):
            raise ValueError("endpoint route has stale net ownership or unsupported vias")
        if (
            self.route.guidance_cost_units != 0
            or self.route.prefix_alternative_id is not None
            or self.route.prefix_fingerprint is not None
        ):
            raise ValueError("endpoint route contains unsupported guidance or prefix state")
        if len(self.path) > 1 and not self.route.claims.resources:
            raise ValueError("non-empty endpoint copper must carry exact resource claims")
        if result.expansion_count < 0:
            raise ValueError("endpoint expansion count must be non-negative")
        if len(result.segments) != max(0, len(self.path) - 1):
            raise ValueError("endpoint emitted segments do not match its raw path")
        for segment, (first, second) in zip(
            result.segments,
            zip(self.path, self.path[1:], strict=False),
            strict=True,
        ):
            if (
                segment.layer != first[0]
                or segment.net_name != self.terminal_source.net_name
                or (segment.x1, segment.y1)
                != (first[1] * self.graph.grid_mm, first[2] * self.graph.grid_mm)
                or (segment.x2, segment.y2)
                != (second[1] * self.graph.grid_mm, second[2] * self.graph.grid_mm)
            ):
                raise ValueError("endpoint emitted segment is stale")

    @property
    def expansion_count(self) -> int:
        return self.route.result.expansion_count

    def semantic_fingerprint(self) -> str:
        result = self.route.result
        return _endpoint_fingerprint(
            {
                "schema_id": "pcbsmith-certified-endpoint-connection",
                "schema_version": 2,
                "search_inputs": self.search_input_fingerprint,
                "terminal_source": self.terminal_source_fingerprint,
                "graph": self.graph_fingerprint,
                "path": self.path,
                "segments": [
                    [
                        item.x1,
                        item.y1,
                        item.x2,
                        item.y2,
                        item.layer,
                        item.net_name,
                        item.width_mm,
                    ]
                    for item in result.segments
                ],
                "resource_ids": sorted(item.resource_id for item in self.route.claims.resources),
                "base_cost_units": self.route.base_cost_units,
                "congestion_cost_units": self.route.congestion_cost_units,
                "expansion_count": result.expansion_count,
            }
        )


class _CertifiedEndpointRouter(_NegotiatedGridRouter):
    def connect(
        self,
        source: GridNode,
        graph: CertifiedEndpointGraph,
        hard_forbidden_resources: frozenset[RoutingResourceKey],
    ) -> tuple[GridNode, ...]:
        if source not in graph.allowed_track_nodes:
            raise ValueError("terminal source node is not in the certified graph")
        if source[0] != graph.layer:
            raise ValueError("terminal source layer does not match the certified graph")
        if source[1:] in self.blocked[source[0]]:
            raise RoutingError("Certified terminal source is blocked.", expansion_count=0)
        adjacency: dict[GridNode, list[GridNode]] = {node: [] for node in graph.allowed_track_nodes}
        for first, second in graph.allowed_track_transitions:
            adjacency[first].append(second)
            adjacency[second].append(first)
        minimum_step_cost = min(
            self._cost_policy.length_units_per_grid,
            self._cost_policy.diagonal_length_units,
        )

        def heuristic(node: GridNode) -> int:
            return (
                max(
                    abs(node[1] - graph.portal_node[1]),
                    abs(node[2] - graph.portal_node[2]),
                )
                * minimum_step_cost
            )

        initial_score: LabelScore = (0, 0, 0, 0, 0, 0)
        state: LabelKey = (source, None, frozenset())
        scores = {state: initial_score}
        came: dict[LabelKey, LabelKey] = {}
        open_heap = [
            self._heap_entry(
                source,
                None,
                frozenset(),
                initial_score,
                heuristic(source),
                0,
                state,
            )
        ]
        closed: set[LabelKey] = set()
        counter = 1
        while open_heap:
            current = heapq.heappop(open_heap)[-1]
            if current in closed:
                continue
            score = scores[current]
            node, incoming_direction, label_claims = current
            if node == graph.portal_node:
                self._candidate_tree_claims = label_claims
                self.base_cost_units = score[5]
                self.congestion_cost_units = score[1]
                return tuple(self._reconstruct_path(current, came))
            if self.max_expansions is not None and self.expansion_count >= self.max_expansions:
                raise RoutingError(
                    f"Expansion budget exhausted for {self.net_name}.",
                    reason=RoutingFailureReason.EXPANSION_BUDGET,
                    expansion_count=self.expansion_count,
                )
            closed.add(current)
            self.expansion_count += 1
            for neighbour in sorted(adjacency[node]):
                direction = (neighbour[1] - node[1], neighbour[2] - node[2])
                if not self._certified_transition_is_hard_legal(
                    node,
                    neighbour,
                    graph.allowed_track_nodes,
                ):
                    continue
                transition_claims = self._transition_claims(node, neighbour, False)
                if transition_claims & hard_forbidden_resources:
                    continue
                newly_claimed = transition_claims - label_claims
                next_claims = label_claims | newly_claimed
                turn = incoming_direction is not None and direction != incoming_direction
                base_units = (
                    self._cost_policy.diagonal_length_units
                    if direction[0] and direction[1]
                    else self._cost_policy.length_units_per_grid
                )
                next_base = (
                    score[5] + base_units + (self._cost_policy.turn_cost_units if turn else 0)
                )
                next_congestion = score[1] + self._resource_cost(newly_claimed)
                next_score: LabelScore = (
                    next_base + next_congestion,
                    next_congestion,
                    0,
                    0,
                    score[4] + int(turn),
                    next_base,
                )
                next_state: LabelKey = (neighbour, direction, next_claims)
                if next_score >= scores.get(
                    next_state,
                    (math.inf, math.inf, math.inf, math.inf, math.inf, math.inf),
                ):
                    continue
                scores[next_state] = next_score
                came[next_state] = current
                heapq.heappush(
                    open_heap,
                    self._heap_entry(
                        neighbour,
                        direction,
                        next_claims,
                        next_score,
                        heuristic(neighbour),
                        counter,
                        next_state,
                    ),
                )
                counter += 1
        raise RoutingError(
            f"No certified endpoint route found for {self.net_name}.",
            expansion_count=self.expansion_count,
        )

    def _certified_transition_is_hard_legal(
        self,
        start: GridNode,
        end: GridNode,
        allowed_nodes: frozenset[GridNode],
    ) -> bool:
        if start[1:] in self.blocked[start[0]] or end[1:] in self.blocked[end[0]]:
            return False
        dx, dy = end[1] - start[1], end[2] - start[2]
        if dx and dy:
            sides = (
                (start[0], start[1] + dx, start[2]),
                (start[0], start[1], start[2] + dy),
            )
            if any(
                side not in allowed_nodes or side[1:] in self.blocked[start[0]] for side in sides
            ):
                return False
        return True


def _require_bound_terminal_source(
    router: _CertifiedEndpointRouter,
    layout: BoardLayout,
    netlist: BoardNetlist,
    source: CertifiedEndpointTerminalSource,
) -> None:
    net_nodes = [
        net.name
        for net in netlist.nets
        for node in net.nodes
        if node == (source.component_ref, source.pad_number)
    ]
    if net_nodes != [source.net_name]:
        raise ValueError(
            "terminal board-netlist binding is missing, duplicated, or on the wrong net"
        )
    components = [
        component for component in netlist.components if component.reference == source.component_ref
    ]
    placements = [
        component
        for component, _x in layout.placements
        if component.reference == source.component_ref
    ]
    if len(components) != 1 or len(placements) != 1 or components[0] != placements[0]:
        raise ValueError("terminal component placement is missing, duplicated, or stale")
    from pcbsmith.kicad.board import FOOTPRINT_LIBRARY

    footprint = FOOTPRINT_LIBRARY.get(components[0].footprint)
    if footprint is None:
        raise ValueError("terminal footprint is not available")
    pad_indexes = tuple(
        index
        for index, pad in enumerate(footprint.pads)
        if pad.name == source.pad_number and pad.kind != "npth"
    )
    if len(pad_indexes) != 1:
        raise ValueError("terminal pad number does not identify exactly one physical pad")
    expected_source_id = f"pad:{source.component_ref}:{pad_indexes[0]}"
    if source.physical_pad_source_id != expected_source_id:
        raise ValueError("terminal physical pad source identity is stale")
    physical_pads = tuple(
        pad
        for pad in router.own_items
        if pad.parent_source_id == expected_source_id and pad.net == source.net_name
    )
    if not physical_pads:
        raise ValueError("terminal physical pad source is absent from the board layout")
    legal_nodes = {node for pad in physical_pads for node in router._pad_nodes(pad)}
    if source.source_node not in legal_nodes:
        raise ValueError("terminal source node does not touch its exact physical pad")


def route_certified_endpoint_to_portal(
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    terminal_source: CertifiedEndpointTerminalSource,
    graph: CertifiedEndpointGraph,
    portal_node: GridNode,
    ledger: OccupancyLedger,
    history: Mapping[RoutingResourceKey, int],
    present_factor_units: int,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    *,
    track_width_mm: float = 0.4,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    clearance_groups: Sequence[
        tuple[Collection[str], Collection[str], float, Collection[str]]
    ] = (),
    pairwise_domains: Iterable[PairwiseClearanceDomain] | None = None,
    hard_forbidden_resources: Collection[RoutingResourceKey] = (),
    max_expansions: int,
) -> CertifiedEndpointConnection:
    """Route one exact physical pad node to one exact certified portal.

    Schema v1 is deliberately same-layer only. The certified graph is hard,
    static geometry and caller-forbidden R2 resources are filtered before
    negotiated present/history cost, and the returned path is never smoothed.
    """
    _require_non_negative_int(max_expansions, "max_expansions")
    if portal_node != graph.portal_node:
        raise ValueError("requested portal does not match the certified graph portal")
    if terminal_source.net_name not in {net.name for net in netlist.nets}:
        raise ValueError("terminal source references an unknown net")
    forbidden = frozenset(hard_forbidden_resources)
    if any(not isinstance(item, RoutingResourceKey) for item in forbidden):
        raise TypeError("hard-forbidden resources must be RoutingResourceKey values")
    canonical_clearance_groups = _canonical_endpoint_clearance_groups(clearance_groups)
    domains = grid_claim_domains_for_net(
        terminal_source.net_name,
        track_width_mm,
        profile,
        pairwise_domains=pairwise_domains,
    )
    search_binding = _endpoint_search_binding(
        static_layout,
        netlist,
        terminal_source,
        graph,
        ledger,
        history,
        present_factor_units,
        cost_policy,
        profile,
        canonical_clearance_groups,
        domains,
        forbidden,
        track_width_mm,
        max_expansions,
    )
    router = _CertifiedEndpointRouter(
        static_layout,
        netlist,
        net_name=terminal_source.net_name,
        track_width_mm=track_width_mm,
        grid_mm=graph.grid_mm,
        profile=profile,
        clearance_groups=canonical_clearance_groups,
        max_expansions=max_expansions,
        ledger=ledger,
        history=history,
        present_factor_units=present_factor_units,
        cost_policy=cost_policy,
        claim_domains=domains,
        soft_guide=None,
        route_prefix=None,
    )
    for node in graph.allowed_track_nodes:
        if not (0 <= node[1] < router.cols and 0 <= node[2] < router.rows):
            raise ValueError("certified endpoint graph node lies outside the board grid")
    _require_bound_terminal_source(router, static_layout, netlist, terminal_source)
    path = router.connect(terminal_source.source_node, graph, forbidden)
    segments = tuple(
        router._segment(first, second) for first, second in zip(path, path[1:], strict=False)
    )
    result = RouteResult(
        net_name=terminal_source.net_name,
        segments=segments,
        vias=(),
        length_mm=sum(
            math.dist(router._point(first[1:]), router._point(second[1:]))
            for first, second in zip(path, path[1:], strict=False)
        ),
        expansion_count=router.expansion_count,
    )
    claims = router.final_claims(result)
    if claims.resources != router._candidate_tree_claims:
        raise RuntimeError("certified endpoint emitted claims differ from searched claims")
    route = NegotiatedGridRoute(
        result=result,
        claims=claims,
        base_cost_units=router.base_cost_units,
        congestion_cost_units=router.congestion_cost_units,
    )
    return CertifiedEndpointConnection(
        terminal_source=terminal_source,
        graph=graph,
        path=path,
        route=route,
        terminal_source_fingerprint=terminal_source.semantic_fingerprint(),
        graph_fingerprint=graph.graph_fingerprint,
        search_binding=search_binding,
        search_input_fingerprint=search_binding.semantic_fingerprint(),
    )
