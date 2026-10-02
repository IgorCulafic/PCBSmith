"""Topology-derived placement seeds for fixed two-layer routing evaluations.

This module does not claim universal placement authority.  It translates
explicit benchmark relations into a deterministic candidate-zero pose map:

* local decouplers are placed from the exact IC power/return terminal pair;
* series elements are placed from their declared source terminal;
* switched-load components are kept as local gate/device/connector clusters;
* legal quarter-turns are evaluated instead of silently fixing every part at
  zero degrees.

The resulting seed still has to pass R5 legalization/routability and the exact
KiCad review path before it may be routed or called acceptable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from statistics import mean
from typing import Protocol

from pcbsmith.kicad.astar_router import RoutingError, route_net_pad_subset, with_route
from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment, ViaSpec
from pcbsmith.kicad.library import FootprintSpec, load_footprint, rotate_offset
from pcbsmith.kicad.virtual_drc import run_virtual_drc

Pose = tuple[float, float, float]


class PlacementLike(Protocol):
    reference: str
    footprint: str
    x_mm: float
    y_mm: float
    rotation_deg: float


class NetLike(Protocol):
    name: str
    nodes: tuple[tuple[str, str], ...]
    width_mm: float


class RoutingCaseLike(Protocol):
    board_width_mm: float
    board_height_mm: float
    placements: tuple[PlacementLike, ...]
    nets: tuple[NetLike, ...]


@dataclass(frozen=True)
class TwoLayerTopologyPlacementEvidence:
    schema: str
    layer_count: int
    four_layer_escalation_allowed: bool
    reference_net: str
    reference_layer: str
    rotation_candidates_deg: tuple[float, ...]
    selected_u1_rotation_deg: float
    initial_decoupling_loop_span_mm: tuple[float, float]
    proposed_decoupling_loop_span_mm: tuple[float, float]
    initial_mean_series_source_distance_mm: float
    proposed_mean_series_source_distance_mm: float
    initial_mean_gate_distance_mm: float
    proposed_mean_gate_distance_mm: float
    relations_applied: tuple[str, ...]
    qualification_boundary: str


@dataclass(frozen=True)
class TwoLayerTopologyPlacementProposal:
    poses: dict[str, Pose]
    evidence: TwoLayerTopologyPlacementEvidence
    ground_zone: tuple[str, str, tuple[float, float, float, float]]


@dataclass(frozen=True)
class TwoLayerSeriesEscapeAttempt:
    net_name: str
    source_terminal: str
    series_terminal: str
    status: str
    reason: str
    track_width_mm: float
    grid_mm: float
    segment_count: int
    via_count: int
    route_length_mm: float
    expansion_count: int


@dataclass(frozen=True)
class TwoLayerSeriesEscapeEvidence:
    schema: str
    layer_count: int
    four_layer_escalation_allowed: bool
    candidate_scope: str
    requested_count: int
    accepted_count: int
    rejected_count: int
    attempts: tuple[TwoLayerSeriesEscapeAttempt, ...]
    qualification_boundary: str


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _pad_position(
    placements: dict[str, PlacementLike],
    poses: dict[str, Pose],
    reference: str,
    pad_name: str,
) -> tuple[float, float]:
    placement = placements[reference]
    pad = load_footprint(placement.footprint).spec.pads_named(pad_name)[0]
    x_mm, y_mm, rotation = poses[reference]
    dx, dy = rotate_offset(pad.x_mm, pad.y_mm, rotation)
    return x_mm + dx, y_mm + dy


def _rotated_bounds(spec: FootprintSpec, pose: Pose) -> tuple[float, float, float, float]:
    x_mm, y_mm, rotation = pose
    corners = tuple(
        rotate_offset(x, y, rotation)
        for x in (spec.x_min, spec.x_max)
        for y in (spec.y_min, spec.y_max)
    )
    return (
        x_mm + min(point[0] for point in corners),
        y_mm + min(point[1] for point in corners),
        x_mm + max(point[0] for point in corners),
        y_mm + max(point[1] for point in corners),
    )


def _overlaps(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    clearance_mm: float = 0.25,
) -> bool:
    return not (
        first[2] + clearance_mm <= second[0]
        or second[2] + clearance_mm <= first[0]
        or first[3] + clearance_mm <= second[1]
        or second[3] + clearance_mm <= first[1]
    )


def _inside_board(
    bounds: tuple[float, float, float, float], width_mm: float, height_mm: float
) -> bool:
    margin = 0.75
    return (
        bounds[0] >= margin
        and bounds[1] >= margin
        and bounds[2] <= width_mm - margin
        and bounds[3] <= height_mm - margin
    )


def _numeric_suffix(reference: str, prefix: str) -> int:
    return int(reference[len(prefix) :])


def _u1_ground_pad(case: RoutingCaseLike) -> str:
    ground = next(net for net in case.nets if net.name == "GND")
    return next(pad for reference, pad in ground.nodes if reference == "U1")


def _decoupling_spans(
    case: RoutingCaseLike,
    placements: dict[str, PlacementLike],
    poses: dict[str, Pose],
) -> tuple[float, float]:
    ground_pad = _u1_ground_pad(case)
    supply = _pad_position(placements, poses, "U1", "1")
    ground = _pad_position(placements, poses, "U1", ground_pad)
    return tuple(
        _distance(supply, _pad_position(placements, poses, reference, "1"))
        + _distance(ground, _pad_position(placements, poses, reference, "2"))
        for reference in ("C1", "C2")
    )  # type: ignore[return-value]


def _node_net_map(case: RoutingCaseLike) -> dict[tuple[str, str], NetLike]:
    return {node: net for net in case.nets for node in net.nodes}


def _series_source_distances(
    case: RoutingCaseLike,
    placements: dict[str, PlacementLike],
    poses: dict[str, Pose],
) -> tuple[float, ...]:
    node_nets = _node_net_map(case)
    references = sorted(
        (reference for reference in poses if re.fullmatch(r"R\d+", reference)),
        key=lambda reference: _numeric_suffix(reference, "R"),
    )
    distances: list[float] = []
    for reference in references:
        input_net = node_nets[(reference, "1")]
        source = next(node for node in input_net.nodes if node[0] == "U1")
        distances.append(
            _distance(
                _pad_position(placements, poses, *source),
                _pad_position(placements, poses, reference, "1"),
            )
        )
    return tuple(distances)


def _gate_distances(
    placements: dict[str, PlacementLike], poses: dict[str, Pose]
) -> tuple[float, ...]:
    references = sorted(
        (reference for reference in poses if reference.startswith("RG")),
        key=lambda reference: _numeric_suffix(reference, "RG"),
    )
    return tuple(
        _distance(
            _pad_position(placements, poses, reference, "2"),
            _pad_position(
                placements,
                poses,
                f"Q{_numeric_suffix(reference, 'RG')}",
                "1",
            ),
        )
        for reference in references
    )


def _mean_or_zero(values: tuple[float, ...]) -> float:
    return mean(values) if values else 0.0


def _connector_endpoint(
    case: RoutingCaseLike, node_nets: dict[tuple[str, str], NetLike], reference: str
) -> tuple[str, str]:
    output_net = node_nets[(reference, "2")]
    return next(node for node in output_net.nodes if node[0].startswith("J"))


def _choose_u1_rotation(
    case: RoutingCaseLike,
    placements: dict[str, PlacementLike],
    poses: dict[str, Pose],
) -> float:
    _node_net_map(case)
    scored: list[tuple[float, float]] = []
    for rotation in (0.0, 90.0, 180.0, 270.0):
        candidate = dict(poses)
        x_mm, y_mm, _old = candidate["U1"]
        candidate["U1"] = (x_mm, y_mm, rotation)
        score = 0.0
        for net in case.nets:
            u1_nodes = tuple(node for node in net.nodes if node[0] == "U1")
            connector_nodes = tuple(
                node for node in net.nodes if node[0].startswith("J") and node[0] != "J1"
            )
            if u1_nodes and connector_nodes:
                score += min(
                    _distance(
                        _pad_position(placements, candidate, *source),
                        _pad_position(placements, candidate, *sink),
                    )
                    for source in u1_nodes
                    for sink in connector_nodes
                )
        score += 1.5 * sum(_decoupling_spans(case, placements, candidate))
        scored.append((score, rotation))
    return min(scored)[1]


def _place_decouplers(
    case: RoutingCaseLike,
    placements: dict[str, PlacementLike],
    poses: dict[str, Pose],
    occupied: list[tuple[float, float, float, float]],
) -> None:
    u1_supply = _pad_position(placements, poses, "U1", "1")
    u1_ground = _pad_position(placements, poses, "U1", _u1_ground_pad(case))
    u1_x, u1_y, _rotation = poses["U1"]
    midpoint = ((u1_supply[0] + u1_ground[0]) / 2, (u1_supply[1] + u1_ground[1]) / 2)
    outward = (midpoint[0] - u1_x, midpoint[1] - u1_y)
    magnitude = max(math.hypot(*outward), 1e-9)
    normal = (outward[0] / magnitude, outward[1] / magnitude)
    tangent = (-normal[1], normal[0])

    for cap_index, reference in enumerate(("C1", "C2")):
        spec = load_footprint(placements[reference].footprint).spec
        candidates: list[tuple[float, Pose, tuple[float, float, float, float]]] = []
        for distance_mm in (1.6, 2.1, 2.7, 3.4, 4.2, 5.0):
            for tangent_offset in (0.0, -1.0, 1.0, -2.0, 2.0, -3.0, 3.0):
                for rotation in (0.0, 90.0, 180.0, 270.0):
                    pose = (
                        midpoint[0] + normal[0] * distance_mm + tangent[0] * tangent_offset,
                        midpoint[1] + normal[1] * distance_mm + tangent[1] * tangent_offset,
                        rotation,
                    )
                    bounds = _rotated_bounds(spec, pose)
                    if not _inside_board(bounds, case.board_width_mm, case.board_height_mm):
                        continue
                    if any(_overlaps(bounds, existing) for existing in occupied):
                        continue
                    trial = dict(poses)
                    trial[reference] = pose
                    loop_span = _distance(
                        u1_supply, _pad_position(placements, trial, reference, "1")
                    ) + _distance(u1_ground, _pad_position(placements, trial, reference, "2"))
                    candidates.append((loop_span + cap_index * distance_mm * 0.05, pose, bounds))
        if not candidates:
            raise ValueError(f"no legal local decoupler placement found for {reference}")
        _score, pose, bounds = min(candidates, key=lambda item: item[0])
        poses[reference] = pose
        occupied.append(bounds)


def _nearest_u1_side(
    u1_bounds: tuple[float, float, float, float], point: tuple[float, float]
) -> tuple[float, float]:
    distances = (
        (abs(point[0] - u1_bounds[0]), (-1.0, 0.0)),
        (abs(point[0] - u1_bounds[2]), (1.0, 0.0)),
        (abs(point[1] - u1_bounds[1]), (0.0, -1.0)),
        (abs(point[1] - u1_bounds[3]), (0.0, 1.0)),
    )
    return min(distances, key=lambda item: item[0])[1]


def _series_rotation(normal: tuple[float, float]) -> tuple[float, float]:
    return (0.0, 180.0) if normal[0] else (90.0, 270.0)


def _place_source_series_elements(
    case: RoutingCaseLike,
    placements: dict[str, PlacementLike],
    poses: dict[str, Pose],
    occupied: list[tuple[float, float, float, float]],
) -> None:
    node_nets = _node_net_map(case)
    u1_spec = load_footprint(placements["U1"].footprint).spec
    u1_bounds = _rotated_bounds(u1_spec, poses["U1"])
    references = sorted(
        (reference for reference in poses if re.fullmatch(r"R\d+", reference)),
        key=lambda reference: _numeric_suffix(reference, "R"),
    )
    for reference in references:
        input_net = node_nets[(reference, "1")]
        source_node = next(node for node in input_net.nodes if node[0] == "U1")
        source = _pad_position(placements, poses, *source_node)
        normal = _nearest_u1_side(u1_bounds, source)
        tangent = (-normal[1], normal[0])
        spec = load_footprint(placements[reference].footprint).spec
        candidates: list[tuple[float, Pose, tuple[float, float, float, float]]] = []
        for row in range(10):
            radial = 1.7 + row * 1.55
            for tangent_offset in (
                0.0,
                -0.8,
                0.8,
                -1.6,
                1.6,
                -2.4,
                2.4,
                -3.2,
                3.2,
                -4.0,
                4.0,
            ):
                for rotation in _series_rotation(normal):
                    pose = (
                        source[0] + normal[0] * radial + tangent[0] * tangent_offset,
                        source[1] + normal[1] * radial + tangent[1] * tangent_offset,
                        rotation,
                    )
                    bounds = _rotated_bounds(spec, pose)
                    if not _inside_board(bounds, case.board_width_mm, case.board_height_mm):
                        continue
                    if any(_overlaps(bounds, existing) for existing in occupied):
                        continue
                    trial = dict(poses)
                    trial[reference] = pose
                    source_distance = _distance(
                        source, _pad_position(placements, trial, reference, "1")
                    )
                    sink = _connector_endpoint(case, node_nets, reference)
                    sink_distance = _distance(
                        _pad_position(placements, trial, reference, "2"),
                        _pad_position(placements, trial, *sink),
                    )
                    candidates.append((source_distance * 4.0 + sink_distance * 0.02, pose, bounds))
        if not candidates:
            raise ValueError(f"no legal source-series placement found for {reference}")
        _score, pose, bounds = min(candidates, key=lambda item: item[0])
        poses[reference] = pose
        occupied.append(bounds)


def _place_output_clusters(
    case: RoutingCaseLike,
    placements: dict[str, PlacementLike],
    poses: dict[str, Pose],
) -> None:
    q_references = sorted(
        (reference for reference in poses if re.fullmatch(r"Q\d+", reference)),
        key=lambda reference: _numeric_suffix(reference, "Q"),
    )
    if not q_references:
        return
    # Keep the switched-load bank out of the tall right-edge signal-header
    # corridor. The terminal blocks are rotated so their LOAD pad faces the
    # device, while the gate resistor sits beside (rather than on top of) the
    # SOT-23 gate pad. These spacings follow exact footprint bounds.
    left = 18.0
    right = case.board_width_mm - 25.0
    step = (right - left) / max(len(q_references) - 1, 1)
    for index, q_reference in enumerate(q_references):
        channel = _numeric_suffix(q_reference, "Q")
        x_mm = (left + right) / 2 if len(q_references) == 1 else left + index * step
        jout_reference = f"JOUT{channel}"
        rg_reference = f"RG{channel}"
        poses[jout_reference] = (x_mm + 4.0, case.board_height_mm - 5.0, 180.0)
        poses[q_reference] = (x_mm, case.board_height_mm - 13.0, 0.0)

        gate = _pad_position(placements, poses, q_reference, "1")
        rg_spec = load_footprint(placements[rg_reference].footprint).spec
        q_bounds = _rotated_bounds(
            load_footprint(placements[q_reference].footprint).spec,
            poses[q_reference],
        )
        rg_candidates: list[tuple[float, Pose]] = []
        for distance_mm in (3.7, 4.2, 4.7, 5.2):
            for y_offset in (0.0, -1.2, 1.2, -2.4, 2.4):
                for direction in (-1.0, 1.0):
                    pose = (
                        poses[q_reference][0] + direction * distance_mm,
                        gate[1] + y_offset,
                        0.0 if direction < 0 else 180.0,
                    )
                    bounds = _rotated_bounds(rg_spec, pose)
                    if not _inside_board(bounds, case.board_width_mm, case.board_height_mm):
                        continue
                    if _overlaps(bounds, q_bounds):
                        continue
                    trial = dict(poses)
                    trial[rg_reference] = pose
                    rg_candidates.append(
                        (
                            _distance(_pad_position(placements, trial, rg_reference, "2"), gate),
                            pose,
                        )
                    )
        if not rg_candidates:
            raise ValueError(f"no local gate-series placement found for {rg_reference}")
        poses[rg_reference] = min(rg_candidates)[1]


def build_two_layer_critical_preroutes(
    case: RoutingCaseLike,
    proposal: TwoLayerTopologyPlacementProposal,
) -> tuple[tuple[TrackSegment, ...], tuple[ViaSpec, ...]]:
    """Reserve short terminal escapes before the bulk autorouter runs.

    The 0.30-0.50 mm local neck-down is derived from the IC pad pitch and limited to the 0603
    capacitor/IC escape. The external router still receives the declared bulk
    VIN/GND width and the width read-back records every narrower segment.
    Ground escapes terminate in large, home-drillable vias onto the reserved
    B.Cu reference zone.
    """

    placements = {placement.reference: placement for placement in case.placements}
    poses = proposal.poses
    u1_x, u1_y, _rotation = poses["U1"]
    supply = _pad_position(placements, poses, "U1", "1")
    ground = _pad_position(placements, poses, "U1", _u1_ground_pad(case))

    def outward_via(point: tuple[float, float], distance_mm: float) -> tuple[float, float]:
        vector = (point[0] - u1_x, point[1] - u1_y)
        magnitude = max(math.hypot(*vector), 1e-9)
        return (
            point[0] + vector[0] / magnitude * distance_mm,
            point[1] + vector[1] / magnitude * distance_mm,
        )

    pitch_match = re.search(r"P(\d+(?:\.\d+)?)mm", placements["U1"].footprint)
    pitch_mm = float(pitch_match.group(1)) if pitch_match else 1.0
    local_escape_width_mm = 0.30 if pitch_mm <= 0.50 else 0.50
    segments: list[TrackSegment] = []
    vias: list[ViaSpec] = []
    for reference in ("C1", "C2"):
        cap_supply = _pad_position(placements, poses, reference, "1")
        cap_ground = _pad_position(placements, poses, reference, "2")
        segments.append(TrackSegment(*supply, *cap_supply, "F.Cu", "VIN", local_escape_width_mm))
        cap_via = outward_via(cap_ground, 1.10)
        segments.append(TrackSegment(*cap_ground, *cap_via, "F.Cu", "GND", local_escape_width_mm))
        vias.append(ViaSpec(*cap_via, "GND", size_mm=1.40, drill_mm=0.60))

    u1_bounds = _rotated_bounds(load_footprint(placements["U1"].footprint).spec, poses["U1"])
    supply_segments = tuple(segment for segment in segments if segment.net_name == "VIN")
    cap_supply_points = tuple(
        _pad_position(placements, poses, reference, "1") for reference in ("C1", "C2")
    )

    def point_segment_distance(point: tuple[float, float], segment: TrackSegment) -> float:
        dx = segment.x2 - segment.x1
        dy = segment.y2 - segment.y1
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            return _distance(point, (segment.x1, segment.y1))
        projection = max(
            0.0,
            min(
                1.0,
                ((point[0] - segment.x1) * dx + (point[1] - segment.y1) * dy) / length_squared,
            ),
        )
        nearest = (segment.x1 + projection * dx, segment.y1 + projection * dy)
        return _distance(point, nearest)

    via_candidates: list[tuple[float, tuple[float, float]]] = []
    diagonal = math.sqrt(0.5)
    for dx, dy in (
        (-1.0, 0.0),
        (1.0, 0.0),
        (0.0, -1.0),
        (0.0, 1.0),
        (-diagonal, -diagonal),
        (-diagonal, diagonal),
        (diagonal, -diagonal),
        (diagonal, diagonal),
    ):
        candidate = (ground[0] + dx * 1.55, ground[1] + dy * 1.55)
        if not (0.9 <= candidate[0] <= case.board_width_mm - 0.9):
            continue
        if not (0.9 <= candidate[1] <= case.board_height_mm - 0.9):
            continue
        outside_u1 = (
            candidate[0] < u1_bounds[0] - 0.20
            or candidate[0] > u1_bounds[2] + 0.20
            or candidate[1] < u1_bounds[1] - 0.20
            or candidate[1] > u1_bounds[3] + 0.20
        )
        if not outside_u1:
            continue
        clearance_score = min(
            *(_distance(candidate, point) for point in cap_supply_points),
            *(point_segment_distance(candidate, segment) for segment in supply_segments),
        )
        via_candidates.append((clearance_score, candidate))
    if not via_candidates:
        raise ValueError("no legal U1 ground-via escape candidate")
    _score, u1_ground_via = max(via_candidates, key=lambda item: item[0])
    segments.append(TrackSegment(*ground, *u1_ground_via, "F.Cu", "GND", local_escape_width_mm))
    vias.append(ViaSpec(*u1_ground_via, "GND", size_mm=1.40, drill_mm=0.60))
    return tuple(segments), tuple(vias)


def _blocking_virtual_drc_signatures(
    layout: BoardLayout,
    netlist: BoardNetlist,
) -> frozenset[tuple[str, str, float, float]]:
    """Geometry findings that a committed local escape may not increase."""

    return frozenset(
        (finding.check, finding.message, round(finding.x_mm, 4), round(finding.y_mm, 4))
        for finding in run_virtual_drc(layout, netlist)
        if finding.check != "pad_connectivity" and not finding.check.startswith("silk")
    )


def build_two_layer_series_escape_preroutes(
    case: RoutingCaseLike,
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    target_net_names: frozenset[str] | None = None,
    max_expansions_per_escape: int = 500_000,
    maximum_route_length_mm: float = 8.1,
) -> tuple[tuple[TrackSegment, ...], TwoLayerSeriesEscapeEvidence]:
    """Commit legal, local U1-to-series-element fanout before bulk routing.

    Each candidate is routed against the already accepted copper using the
    virtual-DRC obstacle model.  It is committed only when it stays on F.Cu,
    uses no via, remains within the local length budget, and introduces no new
    non-silkscreen geometry finding.  A rejection leaves the layout unchanged
    so the external router can still attempt the net.
    """

    if max_expansions_per_escape < 1:
        raise ValueError("max_expansions_per_escape must be positive")
    if maximum_route_length_mm <= 0:
        raise ValueError("maximum_route_length_mm must be positive")

    placements = {placement.reference: placement for placement in case.placements}
    node_nets = _node_net_map(case)
    u1_footprint = placements["U1"].footprint
    pitch_match = re.search(r"P(\d+(?:\.\d+)?)mm", u1_footprint)
    pitch_mm = float(pitch_match.group(1)) if pitch_match else 1.0
    grid_mm = 0.05 if pitch_mm <= 0.50 else 0.10

    requests: list[tuple[str, NetLike, tuple[str, str]]] = []
    for reference in sorted(
        (item for item in placements if re.fullmatch(r"R\d+", item)),
        key=lambda item: _numeric_suffix(item, "R"),
    ):
        net = node_nets.get((reference, "1"))
        if net is None or (target_net_names is not None and net.name not in target_net_names):
            continue
        source = next((node for node in net.nodes if node[0] == "U1"), None)
        if source is not None:
            requests.append((reference, net, source))

    poses = {
        reference: (placement.x_mm, placement.y_mm, placement.rotation_deg)
        for reference, placement in placements.items()
    }
    requests.sort(
        key=lambda item: (
            -_distance(
                _pad_position(placements, poses, *item[2]),
                _pad_position(placements, poses, item[0], "1"),
            ),
            _numeric_suffix(item[0], "R"),
        )
    )

    current = layout
    attempts: list[TwoLayerSeriesEscapeAttempt] = []
    for reference, net, source in requests:
        width_mm = 0.20 if pitch_mm <= 0.50 else min(max(float(net.width_mm), 0.20), 0.40)
        before = _blocking_virtual_drc_signatures(current, netlist)
        try:
            result = route_net_pad_subset(
                current,
                netlist,
                net.name,
                {"U1", reference},
                track_width_mm=width_mm,
                grid_mm=grid_mm,
                max_expansions=max_expansions_per_escape,
            )
        except RoutingError as exc:
            attempts.append(
                TwoLayerSeriesEscapeAttempt(
                    net_name=net.name,
                    source_terminal=f"{source[0]}.{source[1]}",
                    series_terminal=f"{reference}.1",
                    status="rejected",
                    reason=f"routing_error:{exc.reason.value}",
                    track_width_mm=width_mm,
                    grid_mm=grid_mm,
                    segment_count=0,
                    via_count=0,
                    route_length_mm=0.0,
                    expansion_count=exc.expansion_count,
                )
            )
            continue

        reason = "accepted"
        if result.vias:
            reason = "cross_layer_via_forbidden_for_local_escape"
        elif any(segment.layer != "F.Cu" for segment in result.segments):
            reason = "back_copper_local_escape_forbidden"
        elif result.length_mm > maximum_route_length_mm:
            reason = "local_route_length_budget_exceeded"
        candidate = with_route(current, result)
        if reason == "accepted":
            new_findings = _blocking_virtual_drc_signatures(candidate, netlist) - before
            if new_findings:
                reason = "new_virtual_drc_geometry_finding"
        accepted = reason == "accepted"
        if accepted:
            current = candidate
        attempts.append(
            TwoLayerSeriesEscapeAttempt(
                net_name=net.name,
                source_terminal=f"{source[0]}.{source[1]}",
                series_terminal=f"{reference}.1",
                status="accepted" if accepted else "rejected",
                reason=reason,
                track_width_mm=width_mm,
                grid_mm=grid_mm,
                segment_count=len(result.segments),
                via_count=len(result.vias),
                route_length_mm=result.length_mm,
                expansion_count=result.expansion_count,
            )
        )

    accepted_count = sum(attempt.status == "accepted" for attempt in attempts)
    evidence = TwoLayerSeriesEscapeEvidence(
        schema="pcbsmith-two-layer-series-escape-evidence-v1",
        layer_count=2,
        four_layer_escalation_allowed=False,
        candidate_scope=(
            "Feedback-selected, constrained-first U1 source terminal to first pad of "
            "numeric series resistor"
        ),
        requested_count=len(attempts),
        accepted_count=accepted_count,
        rejected_count=len(attempts) - accepted_count,
        attempts=tuple(attempts),
        qualification_boundary=(
            "Accepted routes prove only bounded local two-layer geometry against the "
            "virtual DRC model; exact KiCad DRC, bulk routing, reference continuity, "
            "SI, EMC, ampacity, thermal, and release acceptance remain separate gates."
        ),
    )
    return current.segments[len(layout.segments) :], evidence


def propose_two_layer_topology_placement(
    case: RoutingCaseLike,
) -> TwoLayerTopologyPlacementProposal:
    """Create one deterministic topology-derived seed for later R5 evaluation."""

    placements = {placement.reference: placement for placement in case.placements}
    initial = {
        reference: (placement.x_mm, placement.y_mm, placement.rotation_deg)
        for reference, placement in placements.items()
    }
    poses = dict(initial)

    u1_x, u1_y, _rotation = poses["U1"]
    poses["U1"] = (u1_x, u1_y, _choose_u1_rotation(case, placements, poses))

    occupied = [_rotated_bounds(load_footprint(placements["U1"].footprint).spec, poses["U1"])]
    _place_decouplers(case, placements, poses, occupied)
    _place_source_series_elements(case, placements, poses, occupied)
    _place_output_clusters(case, placements, poses)

    initial_series = _series_source_distances(case, placements, initial)
    proposed_series = _series_source_distances(case, placements, poses)
    initial_gate = _gate_distances(placements, initial)
    proposed_gate = _gate_distances(placements, poses)
    evidence = TwoLayerTopologyPlacementEvidence(
        schema="pcbsmith-two-layer-topology-placement-evidence-v1",
        layer_count=2,
        four_layer_escalation_allowed=False,
        reference_net="GND",
        reference_layer="B.Cu",
        rotation_candidates_deg=(0.0, 90.0, 180.0, 270.0),
        selected_u1_rotation_deg=poses["U1"][2],
        initial_decoupling_loop_span_mm=_decoupling_spans(case, placements, initial),
        proposed_decoupling_loop_span_mm=_decoupling_spans(case, placements, poses),
        initial_mean_series_source_distance_mm=_mean_or_zero(initial_series),
        proposed_mean_series_source_distance_mm=_mean_or_zero(proposed_series),
        initial_mean_gate_distance_mm=_mean_or_zero(initial_gate),
        proposed_mean_gate_distance_mm=_mean_or_zero(proposed_gate),
        relations_applied=(
            "exact-u1-power-return-to-c1-local-decoupler",
            "exact-u1-power-return-to-c2-local-rail-capacitor",
            "declared-u1-source-to-series-element",
            "gate-series-device-load-functional-cluster",
            "bottom-copper-ground-reference-reservation",
        ),
        qualification_boundary=(
            "This is a two-layer benchmark placement proposal and comparative evidence, "
            "not universal distance, EMC, SI, thermal, ampacity, or release qualification."
        ),
    )
    return TwoLayerTopologyPlacementProposal(
        poses=poses,
        evidence=evidence,
        ground_zone=(
            "GND",
            "B.Cu",
            (0.75, 0.75, case.board_width_mm - 0.75, case.board_height_mm - 0.75),
        ),
    )


__all__ = [
    "TwoLayerSeriesEscapeAttempt",
    "TwoLayerSeriesEscapeEvidence",
    "TwoLayerTopologyPlacementEvidence",
    "TwoLayerTopologyPlacementProposal",
    "build_two_layer_critical_preroutes",
    "build_two_layer_series_escape_preroutes",
    "propose_two_layer_topology_placement",
]
