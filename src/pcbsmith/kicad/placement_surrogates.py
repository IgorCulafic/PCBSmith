"""Deterministic exact-authority placement surrogates for R5.3."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from itertools import combinations

from pcbsmith.kicad.clearance_domains import (
    ClearanceGroupInput,
    build_route_pairwise_clearance_domains,
)
from pcbsmith.kicad.placement_routability import PlacementProbe
from pcbsmith.placement_candidate_ir import PlacementSurrogateEvidence
from pcbsmith.placement_geometry import compound_minimum_squared_distance
from pcbsmith.placement_ir import PlacementLegalizationResult
from pcbsmith.placement_surrogate_ir import (
    BusBoundaryOrderObservation,
    BusOrderEvidence,
    CallerClearanceGroup,
    EscapeObstacle,
    EscapeRay,
    NetHpwlEvidence,
    PinEscapeEvidence,
    PlacedTerminalCopper,
    PlacementCorridorEvidence,
    PlacementSurrogatePolicy,
    PlacementSurrogateResult,
    SketchIntersectionEvidence,
    SketchIntersectionKind,
    SketchSegment,
    TerminalClearanceEvidence,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


def _fp(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _um(value: float) -> int:
    return int((Decimal(str(value)) * 1000).to_integral_value(rounding=ROUND_HALF_EVEN))


def _ceil_um(value: float) -> int:
    return int((Decimal(str(value)) * 1000).to_integral_value(rounding=ROUND_CEILING))


def _catalog_fp(terminals: tuple[PlacedTerminalCopper, ...]) -> str:
    return _fp(
        {
            "schema_id": "pcbsmith-placed-terminal-catalog",
            "schema_version": 1,
            "terminals": [x.model_dump(mode="json") for x in terminals],
        }
    )


def _profile_fp(profile: PcbRuleProfile) -> str:
    return _fp(
        {
            "schema_id": "pcbsmith-placement-surrogate-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


def _clearance(
    terminals: tuple[PlacedTerminalCopper, ...],
    profile: PcbRuleProfile,
    groups: tuple[CallerClearanceGroup, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[TerminalClearanceEvidence, ...]]:
    inputs: tuple[ClearanceGroupInput, ...] = tuple(
        (g.nets_a, g.nets_b, g.minimum_clearance_mm, g.exempt_component_refs) for g in groups
    )
    domains = build_route_pairwise_clearance_domains(profile, inputs)
    evidence = []
    for first, second in combinations(terminals, 2):
        if first.layer != second.layer or first.net_name == second.net_name:
            continue
        pair = tuple(sorted((first.net_name, second.net_name)))
        applicable = tuple(
            d
            for d in domains
            if d.net_names == pair
            and first.component_reference not in d.exempt_component_refs
            and second.component_reference not in d.exempt_component_refs
        )
        required = max(
            (
                profile.fab_spacing.minimum_copper_clearance_mm,
                *(d.minimum_clearance_mm for d in applicable),
            )
        )
        squared = compound_minimum_squared_distance(first.copper, second.copper)
        floor_um = math.isqrt((squared.numerator * 1_000_000) // squared.denominator)
        required_um = _ceil_um(required)
        evidence.append(
            TerminalClearanceEvidence(
                source_ids=tuple(sorted((first.source_id, second.source_id))),
                net_names=pair,
                layer=first.layer,
                exact_squared_distance_numerator=squared.numerator,
                exact_squared_distance_denominator=squared.denominator,
                distance_floor_um=floor_um,
                required_clearance_mm=required,
                required_clearance_um=required_um,
                margin_floor_um=floor_um - required_um,
                exact_violation=squared < Fraction(str(required)) ** 2,
                contributing_domain_ids=tuple(d.domain_id for d in applicable),
            )
        )
    return (
        tuple(d.domain_id for d in domains),
        tuple(sorted({d.requirement_id for d in domains})),
        tuple(sorted(evidence, key=lambda x: x.semantic_json())),
    )


def _physical_centers(
    terminals: tuple[PlacedTerminalCopper, ...],
) -> dict[str, tuple[str, tuple[int, int]]]:
    out: dict[str, tuple[str, tuple[int, int]]] = {}
    for item in terminals:
        value = (item.net_name, (_um(item.center_mm[0]), _um(item.center_mm[1])))
        if item.terminal_id in out and out[item.terminal_id] != value:
            raise ValueError("terminal copies disagree on net or center")
        out[item.terminal_id] = value
    return out


def _mst_segments(
    items: tuple[tuple[str, tuple[int, int]], ...], net: str, layer: str
) -> tuple[SketchSegment, ...]:
    if len(items) < 2:
        return ()
    parent = {sid: sid for sid, _ in items}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    edges: list[tuple[int, str, str, tuple[int, int], tuple[int, int]]] = []
    for (sa, a), (sb, b) in combinations(items, 2):
        edges.append((abs(a[0] - b[0]) + abs(a[1] - b[1]), sa, sb, a, b))
    chosen: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for _dist, sa, sb, a, b in sorted(edges):
        ra, rb = find(sa), find(sb)
        if ra == rb:
            continue
        parent[rb] = ra
        chosen.append((a, b))
        if len(chosen) == len(items) - 1:
            break
    result: list[SketchSegment] = []
    for a, b in chosen:
        corner1 = (b[0], a[1])
        corner2 = (a[0], b[1])
        alternatives: list[tuple[SketchSegment, ...]] = []
        for corner in (corner1, corner2):
            segs = []
            for p, q in ((a, corner), (corner, b)):
                if p != q:
                    segs.append(SketchSegment(net_name=net, layer=layer, start_um=p, end_um=q))
            alternatives.append(tuple(sorted(segs, key=lambda x: x.semantic_json())))
        result.extend(min(alternatives, key=lambda seq: tuple(x.semantic_json() for x in seq)))
    return tuple(sorted(set(result), key=lambda x: x.semantic_json()))


def _sketches(terminals: tuple[PlacedTerminalCopper, ...]) -> tuple[SketchSegment, ...]:
    result: list[SketchSegment] = []
    for layer in ("F.Cu", "B.Cu"):
        by_net: dict[str, dict[str, tuple[int, int]]] = {}
        for t in terminals:
            if t.layer == layer:
                by_net.setdefault(t.net_name, {})[t.terminal_id] = (
                    _um(t.center_mm[0]),
                    _um(t.center_mm[1]),
                )
        for net, values in sorted(by_net.items()):
            result.extend(_mst_segments(tuple(sorted(values.items())), net, layer))
    return tuple(sorted(result, key=lambda x: x.semantic_json()))


def _intersections(segments: tuple[SketchSegment, ...]) -> tuple[SketchIntersectionEvidence, ...]:
    out = []
    for a, b in combinations(segments, 2):
        if a.layer != b.layer or a.net_name == b.net_name:
            continue
        ah = a.start_um[1] == a.end_um[1]
        bh = b.start_um[1] == b.end_um[1]
        kind = None
        if ah != bh:
            h, v = (a, b) if ah else (b, a)
            p = (v.start_um[0], h.start_um[1])
            if h.start_um[0] < p[0] < h.end_um[0] and v.start_um[1] < p[1] < v.end_um[1]:
                kind = SketchIntersectionKind.PROPER
        elif (
            ah
            and a.start_um[1] == b.start_um[1]
            and max(a.start_um[0], b.start_um[0]) < min(a.end_um[0], b.end_um[0])
        ):
            kind = SketchIntersectionKind.COLLINEAR_AMBIGUITY
        elif (
            not ah
            and a.start_um[0] == b.start_um[0]
            and max(a.start_um[1], b.start_um[1]) < min(a.end_um[1], b.end_um[1])
        ):
            kind = SketchIntersectionKind.COLLINEAR_AMBIGUITY
        if kind is not None:
            out.append(
                SketchIntersectionEvidence(
                    kind=kind,
                    net_names=tuple(sorted((a.net_name, b.net_name))),
                    layer=a.layer,
                    first_segment=min((a, b), key=lambda x: x.semantic_json()),
                    second_segment=max((a, b), key=lambda x: x.semantic_json()),
                )
            )
    return tuple(sorted(out, key=lambda x: x.semantic_json()))


def _hpwl(terminals: tuple[PlacedTerminalCopper, ...]) -> tuple[NetHpwlEvidence, ...]:
    by: dict[str, dict[str, tuple[int, int]]] = {}
    for t in terminals:
        by.setdefault(t.net_name, {})[t.terminal_id] = (_um(t.center_mm[0]), _um(t.center_mm[1]))
    return tuple(
        NetHpwlEvidence(
            net_name=n,
            hpwl_um=(
                max(p[0] for p in v.values())
                - min(p[0] for p in v.values())
                + max(p[1] for p in v.values())
                - min(p[1] for p in v.values())
            ),
        )
        for n, v in sorted(by.items())
    )


def _bus(items: tuple[BusBoundaryOrderObservation, ...]) -> tuple[BusOrderEvidence, ...]:
    out = []
    for x in sorted(items, key=lambda v: (v.bus_id, v.boundary_id)):
        if x.observed_member_ids == x.declared_member_ids:
            accepted = "declared"
        elif x.allow_whole_bundle_reversal and x.observed_member_ids == tuple(
            reversed(x.declared_member_ids)
        ):
            accepted = "whole_reversal"
        elif x.observed_member_ids in x.allowed_member_permutations:
            accepted = "allowed_permutation"
        else:
            accepted = "conflict"
        out.append(
            BusOrderEvidence(
                bus_id=x.bus_id,
                boundary_id=x.boundary_id,
                observed_member_ids=x.observed_member_ids,
                conflict=accepted == "conflict",
                accepted_as=accepted,
            )
        )
    return tuple(out)


def _q(p: tuple[float, float]) -> tuple[Fraction, Fraction]:
    return Fraction(str(p[0])), Fraction(str(p[1]))


def _orient(
    a: tuple[Fraction, Fraction], b: tuple[Fraction, Fraction], c: tuple[Fraction, Fraction]
) -> Fraction:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on(
    p: tuple[Fraction, Fraction], a: tuple[Fraction, Fraction], b: tuple[Fraction, Fraction]
) -> bool:
    return (
        _orient(a, b, p) == 0
        and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def _ring_location(
    point: tuple[Fraction, Fraction], ring: tuple[tuple[Fraction, Fraction], ...]
) -> int:
    inside = False
    for index, first in enumerate(ring):
        second = ring[(index + 1) % len(ring)]
        if _on(point, first, second):
            return 0
        if (first[1] > point[1]) != (second[1] > point[1]):
            crossing_x = first[0] + (point[1] - first[1]) * (second[0] - first[0]) / (
                second[1] - first[1]
            )
            if crossing_x > point[0]:
                inside = not inside
    return 1 if inside else -1


def _filled(point: tuple[Fraction, Fraction], obstacle: EscapeObstacle) -> bool:
    for polygon in obstacle.compound.polygons:
        outer = tuple(_q(item) for item in polygon.outer)
        outer_location = _ring_location(point, outer)
        if outer_location == 0:
            return True
        if outer_location < 0:
            continue
        in_hole = False
        for hole in polygon.holes:
            location = _ring_location(point, tuple(_q(item) for item in hole))
            if location == 0:
                return True
            if location > 0:
                in_hole = True
        if not in_hole:
            return True
    return False


def _hit(a: tuple[float, float], b: tuple[float, float], obs: EscapeObstacle) -> bool:
    qa, qb = _q(a), _q(b)
    if _filled(qa, obs) or _filled(qb, obs):
        return True
    for poly in obs.compound.polygons:
        for raw_ring in (poly.outer, *poly.holes):
            points = tuple(_q(point) for point in raw_ring)
            for index, c in enumerate(points):
                d = points[(index + 1) % len(points)]
                o1, o2 = _orient(qa, qb, c), _orient(qa, qb, d)
                o3, o4 = _orient(c, d, qa), _orient(c, d, qb)
                if (
                    (o1 == 0 and _on(c, qa, qb))
                    or (o2 == 0 and _on(d, qa, qb))
                    or (o3 == 0 and _on(qa, c, d))
                    or (o4 == 0 and _on(qb, c, d))
                    or ((o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0))
                ):
                    return True
    return False


def _escape(
    terminals: tuple[PlacedTerminalCopper, ...],
    obstacles: tuple[EscapeObstacle, ...],
    policy: PlacementSurrogatePolicy,
) -> tuple[PinEscapeEvidence, ...]:
    by: dict[str, PlacedTerminalCopper] = {}
    for t in terminals:
        by.setdefault(t.terminal_id, t)
    out: list[PinEscapeEvidence] = []
    for t in sorted(by.values(), key=lambda x: x.terminal_id):
        legal: list[EscapeRay] = []
        blocked: set[str] = set()
        for ray in t.escape_rays:
            end = (
                t.center_mm[0] + ray.dx * t.escape_length_mm,
                t.center_mm[1] + ray.dy * t.escape_length_mm,
            )
            hits = [
                o.obstacle_id
                for o in obstacles
                if o.layer == t.layer
                and t.component_reference not in o.exempt_component_refs
                and _hit(t.center_mm, end, o)
            ]
            if hits:
                blocked.update(hits)
            else:
                legal.append(ray)
        grid = Fraction(str(policy.escape_grid_mm))
        x_units = Fraction(str(t.center_mm[0])) / grid
        y_units = Fraction(str(t.center_mm[1])) / grid
        residual_mm = (abs(x_units - round(x_units)) + abs(y_units - round(y_units))) * grid
        residual = (residual_mm.numerator * 1000) // residual_mm.denominator
        out.append(
            PinEscapeEvidence(
                terminal_id=t.terminal_id,
                source_id=t.source_id,
                legal_alternative_count=len(legal),
                unescaped=not legal,
                constrained=any(r.constrained_portal_ids for r in legal),
                minimum_alignment_penalty_units=min(
                    (r.alignment_penalty_units for r in legal), default=0
                ),
                grid_residual_um=residual,
                off_grid_diagnostic=residual > 0,
                ambiguous=not t.escape_rays,
                blocked_obstacle_ids=tuple(sorted(blocked)),
            )
        )
    return tuple(out)


DEFAULT_PLACEMENT_CORRIDOR_EVIDENCE = PlacementCorridorEvidence(state="absent")
DEFAULT_PLACEMENT_SURROGATE_POLICY = PlacementSurrogatePolicy()


def evaluate_placement_surrogates(
    terminals: Sequence[PlacedTerminalCopper],
    *,
    pose_fingerprint: str,
    probe_layout_fingerprint: str,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    clearance_groups: Sequence[CallerClearanceGroup] = (),
    bus_observations: Sequence[BusBoundaryOrderObservation] = (),
    corridor: PlacementCorridorEvidence = DEFAULT_PLACEMENT_CORRIDOR_EVIDENCE,
    escape_obstacles: Sequence[EscapeObstacle] = (),
    policy: PlacementSurrogatePolicy = DEFAULT_PLACEMENT_SURROGATE_POLICY,
) -> PlacementSurrogateResult:
    terms = tuple(sorted(terminals, key=lambda x: (x.source_id, x.layer)))
    groups = tuple(sorted(clearance_groups, key=lambda x: x.semantic_json()))
    if len({item.semantic_fingerprint() for item in groups}) != len(groups):
        raise ValueError("duplicate caller clearance groups are forbidden")
    if not terms or len({(x.source_id, x.layer) for x in terms}) != len(terms):
        raise ValueError("terminal catalog must be non-empty and unique")
    domain_ids, requirement_ids, clearance = _clearance(terms, profile, groups)
    sketches = _sketches(terms)
    intersections = _intersections(sketches)
    hpwl = _hpwl(terms)
    observations = tuple(sorted(bus_observations, key=lambda x: (x.bus_id, x.boundary_id)))
    if len({(item.bus_id, item.boundary_id) for item in observations}) != len(observations):
        raise ValueError("duplicate bus boundary observations are forbidden")
    bus = _bus(observations)
    obstacles = tuple(sorted(escape_obstacles, key=lambda x: (x.layer, x.obstacle_id)))
    if len({item.obstacle_id for item in obstacles}) != len(obstacles):
        raise ValueError("duplicate escape obstacles are forbidden")
    escape = _escape(terms, obstacles, policy)
    terminal_catalog_fingerprint = _catalog_fp(terms)
    profile_fingerprint = _profile_fp(profile)
    policy_fingerprint = policy.semantic_fingerprint()
    clearance_groups_fingerprint = _fp([item.model_dump(mode="json") for item in groups])
    bus_observations_fingerprint = _fp([item.model_dump(mode="json") for item in observations])
    corridor_fingerprint = corridor.semantic_fingerprint()
    escape_obstacles_fingerprint = _fp([item.model_dump(mode="json") for item in obstacles])
    input_fields = {
        "pose_fingerprint": pose_fingerprint,
        "probe_layout_fingerprint": probe_layout_fingerprint,
        "terminal_catalog_fingerprint": terminal_catalog_fingerprint,
        "profile_fingerprint": profile_fingerprint,
        "policy_fingerprint": policy_fingerprint,
        "clearance_groups_fingerprint": clearance_groups_fingerprint,
        "bus_observations_fingerprint": bus_observations_fingerprint,
        "corridor_fingerprint": corridor_fingerprint,
        "escape_obstacles_fingerprint": escape_obstacles_fingerprint,
    }
    input_fingerprint = _fp(
        {"schema_id": "pcbsmith-placement-surrogate-input", "schema_version": 1, **input_fields}
    )
    margins = tuple(x.margin_floor_um for x in clearance)
    bands = tuple((b, sum(m < b for m in margins)) for b in policy.clearance_review_bands_um)
    return PlacementSurrogateResult(
        pose_fingerprint=pose_fingerprint,
        probe_layout_fingerprint=probe_layout_fingerprint,
        terminal_catalog_fingerprint=terminal_catalog_fingerprint,
        profile_fingerprint=profile_fingerprint,
        policy_fingerprint=policy_fingerprint,
        clearance_groups_fingerprint=clearance_groups_fingerprint,
        bus_observations_fingerprint=bus_observations_fingerprint,
        corridor_fingerprint=corridor_fingerprint,
        escape_obstacles_fingerprint=escape_obstacles_fingerprint,
        input_fingerprint=input_fingerprint,
        clearance_domain_ids=domain_ids,
        clearance_requirement_ids=requirement_ids,
        clearance_evidence=clearance,
        minimum_terminal_margin_um=min(margins, default=None),
        terminal_clearance_violation_count=sum(x.exact_violation for x in clearance),
        clearance_review_band_counts=bands,
        sketch_segments=sketches,
        sketch_intersections=intersections,
        geometric_crossing_count=sum(
            x.kind is SketchIntersectionKind.PROPER for x in intersections
        ),
        collinear_ambiguity_count=sum(
            x.kind is SketchIntersectionKind.COLLINEAR_AMBIGUITY for x in intersections
        ),
        hpwl_by_net=hpwl,
        total_hpwl_um=sum(x.hpwl_um for x in hpwl),
        maximum_net_hpwl_um=max((x.hpwl_um for x in hpwl), default=0),
        bus_order_evidence=bus,
        declared_order_conflict_count=sum(x.conflict for x in bus),
        corridor=corridor,
        pin_escape_evidence=escape,
        unescaped_terminal_count=sum(x.unescaped for x in escape),
        constrained_escape_count=sum(x.constrained for x in escape),
        alignment_penalty_units=sum(x.minimum_alignment_penalty_units for x in escape),
        grid_residual_units=sum(x.grid_residual_um for x in escape),
        ambiguous_escape_count=sum(x.ambiguous for x in escape),
    )


@dataclass(frozen=True)
class PlacementSurrogateInput:
    pose_fingerprint: str
    probe_layout_fingerprint: str
    terminals: tuple[PlacedTerminalCopper, ...]
    clearance_groups: tuple[CallerClearanceGroup, ...] = ()
    bus_observations: tuple[BusBoundaryOrderObservation, ...] = ()
    corridor: PlacementCorridorEvidence = DEFAULT_PLACEMENT_CORRIDOR_EVIDENCE
    escape_obstacles: tuple[EscapeObstacle, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.pose_fingerprint, self.probe_layout_fingerprint):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("surrogate input pose/probe fingerprints must be SHA-256")


class DeterministicPlacementSurrogateEvaluator:
    def __init__(
        self,
        inputs_by_pose_fingerprint: Mapping[str, PlacementSurrogateInput],
        *,
        profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
        policy: PlacementSurrogatePolicy = DEFAULT_PLACEMENT_SURROGATE_POLICY,
    ) -> None:
        self._inputs = dict(inputs_by_pose_fingerprint)
        if any(key != item.pose_fingerprint for key, item in self._inputs.items()):
            raise ValueError("surrogate input key must equal its pose fingerprint")
        self._profile = profile
        self._policy = policy
        self.results: dict[str, PlacementSurrogateResult] = {}

    def __call__(
        self, probe: PlacementProbe, legalization_result: PlacementLegalizationResult
    ) -> PlacementSurrogateEvidence:
        pose = probe.result.telemetry.pose_fingerprint
        if legalization_result.telemetry.pose_fingerprint != pose:
            raise ValueError("surrogate probe/legalization pose mismatch")
        source = self._inputs.get(pose)
        if source is None:
            raise ValueError("no typed R5.3 input for placement pose")
        if source.probe_layout_fingerprint != probe.result.telemetry.probe_layout_fingerprint:
            raise ValueError("typed R5.3 input is stale for the probe layout")
        result = evaluate_placement_surrogates(
            source.terminals,
            pose_fingerprint=source.pose_fingerprint,
            probe_layout_fingerprint=source.probe_layout_fingerprint,
            profile=self._profile,
            clearance_groups=source.clearance_groups,
            bus_observations=source.bus_observations,
            corridor=source.corridor,
            escape_obstacles=source.escape_obstacles,
            policy=self._policy,
        )
        self.results[pose] = result
        return PlacementSurrogateEvidence(
            evaluator_id="deterministic-placement-surrogates-v1",
            evidence_fingerprint=result.semantic_fingerprint(),
        )
