"""Exact decoupling-loop topology metrics and declarative policy evaluation."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from typing import Any

from pcbsmith.decoupling_loop_ir import (
    DecouplingClosureSegment,
    DecouplingLoopDeclaration,
    DecouplingLoopEvaluationResult,
    DecouplingLoopMetrics,
    DecouplingLoopPolicy,
    DecouplingPathLegMetrics,
    decoupling_loop_context_fingerprint,
)
from pcbsmith.kicad.board_serialization import parse_canonical_board_netlist_snapshot
from pcbsmith.routed_copper_graph_ir import (
    CopperRadicalLengthTerm,
    ExactRational,
    ResolvedCopperPathResult,
    RoutedCopperGraphResult,
    fingerprint,
)
from pcbsmith.semantic_ir import SemanticDisposition, SemanticVerification

Point = tuple[Fraction, Fraction]


def _is_sha256(value: str | None) -> bool:
    return (
        value is not None
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_inputs(
    graph_result: RoutedCopperGraphResult,
    supply_path: ResolvedCopperPathResult,
    return_path: ResolvedCopperPathResult,
    declaration: DecouplingLoopDeclaration,
) -> tuple[
    RoutedCopperGraphResult,
    ResolvedCopperPathResult,
    ResolvedCopperPathResult,
    DecouplingLoopDeclaration,
]:
    graph = RoutedCopperGraphResult.model_validate_json(graph_result.model_dump_json())
    supply = ResolvedCopperPathResult.model_validate_json(supply_path.model_dump_json())
    return_leg = ResolvedCopperPathResult.model_validate_json(return_path.model_dump_json())
    retained = DecouplingLoopDeclaration.model_validate_json(declaration.model_dump_json())
    if supply.graph != graph or return_leg.graph != graph:
        raise ValueError("decoupling paths must retain the exact declared routed graph")
    if (
        retained.graph_fingerprint != graph.graph_fingerprint
        or retained.board_layout_snapshot_fingerprint != graph.board_layout_snapshot_fingerprint
        or retained.board_netlist_snapshot_fingerprint != graph.board_netlist_snapshot_fingerprint
        or retained.supply_path_result_fingerprint != supply.result_fingerprint
        or retained.return_path_result_fingerprint != return_leg.result_fingerprint
    ):
        raise ValueError("decoupling declaration graph/path snapshot authority is stale")
    expected_supply = (
        retained.source_power_anchor_id,
        retained.load_power_anchor_id,
        retained.expected_power_net_name,
    )
    actual_supply = (
        supply.selection.start_anchor_id,
        supply.selection.end_anchor_id,
        supply.selection.net_name,
    )
    expected_return = (
        retained.load_return_anchor_id,
        retained.source_return_anchor_id,
        retained.expected_return_net_name,
    )
    actual_return = (
        return_leg.selection.start_anchor_id,
        return_leg.selection.end_anchor_id,
        return_leg.selection.net_name,
    )
    if actual_supply != expected_supply or actual_return != expected_return:
        raise ValueError("decoupling paths do not follow their declared terminal roles/nets")
    anchors = {item.anchor_id: item for item in graph.terminal_anchors}
    expected_pads = {
        retained.source_power_anchor_id: retained.source_power_pad_source_id,
        retained.load_power_anchor_id: retained.load_power_pad_source_id,
        retained.load_return_anchor_id: retained.load_return_pad_source_id,
        retained.source_return_anchor_id: retained.source_return_pad_source_id,
    }
    if any(
        anchor_id not in anchors or anchors[anchor_id].physical_pad_source_id != pad_source_id
        for anchor_id, pad_source_id in expected_pads.items()
    ):
        raise ValueError("decoupling declaration terminal pad authority is stale")
    inventory = retained.terminal_inventory
    if (
        inventory.graph_fingerprint != graph.graph_fingerprint
        or inventory.power_net_name != retained.expected_power_net_name
        or inventory.return_net_name != retained.expected_return_net_name
    ):
        raise ValueError("decoupling terminal inventory authority is stale")
    netlist = parse_canonical_board_netlist_snapshot(graph.board_netlist_snapshot_json)
    declared_nets = {retained.expected_power_net_name, retained.expected_return_net_name}
    netlist_nodes = {
        node for net in netlist.nets if net.name in declared_nets for node in net.nodes
    }
    graph_relevant = tuple(
        item for item in graph.terminal_anchors if item.net_name in declared_nets
    )
    graph_pad_nodes = tuple((item.component_reference, item.pad_number) for item in graph_relevant)
    if len(set(graph_pad_nodes)) != len(graph_pad_nodes):
        raise ValueError("routed graph has duplicate component/pad anchor aliases")
    if len({item.physical_pad_source_id for item in graph_relevant}) != len(graph_relevant):
        raise ValueError("routed graph has duplicate physical pad source aliases")
    relevant = {item.anchor_id: item for item in graph_relevant}
    entries = {item.anchor_id: item for item in inventory.entries}
    if not set(entries).issubset(relevant):
        raise ValueError("terminal inventory invents anchors outside the two declared nets")
    for anchor_id, entry in entries.items():
        anchor = relevant[anchor_id]
        if (
            entry.physical_pad_source_id != anchor.physical_pad_source_id
            or entry.component_reference != anchor.component_reference
            or entry.pad_number != anchor.pad_number
            or entry.net_name != anchor.net_name
        ):
            raise ValueError("terminal inventory entry differs from retained graph anchor")
        if (entry.component_reference, entry.pad_number) not in netlist_nodes:
            raise ValueError("terminal inventory invents a node outside retained BoardNetlist")
    if inventory.completeness == "complete":
        inventory_nodes = {
            (item.component_reference, item.pad_number) for item in inventory.entries
        }
        if set(graph_pad_nodes) != netlist_nodes or inventory_nodes != netlist_nodes:
            raise ValueError(
                "complete terminal inventory/graph anchors must equal all retained "
                "BoardNetlist nodes"
            )
        if set(entries) != set(relevant):
            raise ValueError("complete terminal inventory omits relevant graph anchors")
    return graph, supply, return_leg, retained


def _edge_layers(graph: RoutedCopperGraphResult, path: ResolvedCopperPathResult) -> tuple[str, ...]:
    nodes = {item.node_id: item for item in graph.nodes}
    result = []
    for index, edge_id in enumerate(path.ordered_edge_ids):
        edge = next(item for item in graph.edges if item.edge_id == edge_id)
        start = nodes[path.ordered_node_ids[index]].layer
        end = nodes[path.ordered_node_ids[index + 1]].layer
        result.append(start if edge.kind != "via" else f"{start}->{end}")
    return tuple(result)


def _leg_metrics(
    leg: str, graph: RoutedCopperGraphResult, path: ResolvedCopperPathResult
) -> DecouplingPathLegMetrics:
    return DecouplingPathLegMetrics(
        leg=leg,
        ordered_node_ids=path.ordered_node_ids,
        ordered_edge_ids=path.ordered_edge_ids,
        ordered_source_ids=path.ordered_source_ids,
        ordered_layer_transitions=_edge_layers(graph, path),
        via_count=path.via_count,
        via_source_ids=path.via_source_ids,
        minimum_track_width_mm=path.minimum_width_mm,
        neck_edge_ids=path.neck_edge_ids,
        radical_length_terms=path.radical_length_terms,
    )


def _point(graph: RoutedCopperGraphResult, node_id: str) -> Point:
    node = next(item for item in graph.nodes if item.node_id == node_id)
    return Fraction(node.x_mm), Fraction(node.y_mm)


def _remove_consecutive_duplicates(
    points: tuple[tuple[str, Point], ...],
) -> tuple[tuple[str, Point], ...]:
    result: list[tuple[str, Point]] = []
    for item in points:
        if not result or result[-1][1] != item[1]:
            result.append(item)
    if len(result) > 1 and result[0][1] == result[-1][1]:
        result.pop()
    return tuple(result)


def _orientation(a: Point, b: Point, c: Point) -> Fraction:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(point: Point, start: Point, end: Point) -> bool:
    return _orientation(start, end, point) == 0 and all(
        min(first, second) <= value <= max(first, second)
        for value, first, second in zip(point, start, end, strict=True)
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    values = (
        _orientation(a, b, c),
        _orientation(a, b, d),
        _orientation(c, d, a),
        _orientation(c, d, b),
    )
    if values[0] * values[1] < 0 and values[2] * values[3] < 0:
        return True
    return any(
        value == 0 and _on_segment(point, start, end)
        for value, point, start, end in (
            (values[0], c, a, b),
            (values[1], d, a, b),
            (values[2], a, c, d),
            (values[3], b, c, d),
        )
    )


def _area_and_closures(
    graph: RoutedCopperGraphResult,
    supply: ResolvedCopperPathResult,
    return_leg: ResolvedCopperPathResult,
) -> tuple[ExactRational | None, tuple[DecouplingClosureSegment, ...], str]:
    supply_points = tuple((node_id, _point(graph, node_id)) for node_id in supply.ordered_node_ids)
    return_points = tuple(
        (node_id, _point(graph, node_id)) for node_id in return_leg.ordered_node_ids
    )
    polygon = _remove_consecutive_duplicates((*supply_points, *return_points))
    load_start, load_end = supply_points[-1], return_points[0]
    source_start, source_end = return_points[-1], supply_points[0]
    closures = (
        DecouplingClosureSegment(
            closure_id="load-endpoint-closure",
            start_node_id=load_start[0],
            end_node_id=load_end[0],
            squared_length_mm2=ExactRational.build(
                (load_start[1][0] - load_end[1][0]) ** 2 + (load_start[1][1] - load_end[1][1]) ** 2
            ),
        ),
        DecouplingClosureSegment(
            closure_id="source-endpoint-closure",
            start_node_id=source_start[0],
            end_node_id=source_end[0],
            squared_length_mm2=ExactRational.build(
                (source_start[1][0] - source_end[1][0]) ** 2
                + (source_start[1][1] - source_end[1][1]) ** 2
            ),
        ),
    )
    points = tuple(item[1] for item in polygon)
    if len(points) < 3 or len(points) != len(set(points)):
        return None, closures, "unverified_non_simple"
    for index in range(len(points)):
        previous = points[index - 1]
        current = points[index]
        following = points[(index + 1) % len(points)]
        if _orientation(previous, current, following) == 0 and (
            _on_segment(following, previous, current) or _on_segment(previous, current, following)
        ):
            return None, closures, "unverified_non_simple"
    edges = tuple(
        (points[index], points[(index + 1) % len(points)]) for index in range(len(points))
    )
    for first_index, (a, b) in enumerate(edges):
        for second_index, (c, d) in enumerate(edges[first_index + 1 :], first_index + 1):
            adjacent = second_index in {first_index + 1, (first_index - 1) % len(edges)} or (
                first_index == 0 and second_index == len(edges) - 1
            )
            if not adjacent and _segments_intersect(a, b, c, d):
                return None, closures, "unverified_non_simple"
    twice_area = sum(first[0] * second[1] - first[1] * second[0] for first, second in edges)
    if twice_area == 0:
        return None, closures, "unverified_non_simple"
    return ExactRational.build(abs(twice_area) / 2), closures, "exact_simple"


def _combine_terms(
    supply: ResolvedCopperPathResult, return_leg: ResolvedCopperPathResult
) -> tuple[CopperRadicalLengthTerm, ...]:
    coefficients: dict[int, Fraction] = defaultdict(Fraction)
    for term in (*supply.radical_length_terms, *return_leg.radical_length_terms):
        coefficients[term.squarefree_radicand] += term.coefficient_mm.fraction()
    return tuple(
        CopperRadicalLengthTerm(
            squarefree_radicand=radicand,
            coefficient_mm=ExactRational.build(coefficient),
        )
        for radicand, coefficient in sorted(coefficients.items())
    )


def _derive_metrics(
    graph: RoutedCopperGraphResult,
    supply: ResolvedCopperPathResult,
    return_leg: ResolvedCopperPathResult,
    declaration: DecouplingLoopDeclaration,
) -> DecouplingLoopMetrics:
    supply_metrics = _leg_metrics("supply", graph, supply)
    return_metrics = _leg_metrics("return", graph, return_leg)
    widths = tuple(
        value
        for value in (supply.minimum_width_mm, return_leg.minimum_width_mm)
        if value is not None
    )
    minimum = min(widths) if widths else None
    necks = (
        tuple(
            sorted(
                edge_id
                for path in (supply, return_leg)
                if path.minimum_width_mm == minimum
                for edge_id in path.neck_edge_ids
            )
        )
        if minimum is not None
        else ()
    )
    area, closures, closure_status = _area_and_closures(graph, supply, return_leg)
    node_by_anchor = {
        anchor_id: node.node_id for node in graph.nodes for anchor_id in node.anchor_ids
    }
    inventory = declaration.terminal_inventory
    interior_nodes = set(supply.ordered_node_ids[1:-1]) | set(return_leg.ordered_node_ids[1:-1])
    interior = tuple(
        sorted(
            item.anchor_id
            for item in inventory.entries
            if node_by_anchor[item.anchor_id] in interior_nodes
        )
    )
    classification = (
        "unverified"
        if inventory.completeness != "complete"
        else "daisy_chain"
        if interior
        else "dedicated"
    )
    return DecouplingLoopMetrics(
        supply=supply_metrics,
        return_leg=return_metrics,
        combined_via_count=supply.via_count + return_leg.via_count,
        combined_via_source_ids=tuple(sorted((*supply.via_source_ids, *return_leg.via_source_ids))),
        combined_minimum_track_width_mm=minimum,
        combined_neck_edge_ids=necks,
        combined_radical_length_terms=_combine_terms(supply, return_leg),
        projected_loop_area_mm2=area,
        closure_segments=closures,
        projected_closure_verification=closure_status,
        terminal_classification=classification,
        interior_anchor_ids=interior,
    )


def _hard_binding_reasons(declaration: DecouplingLoopDeclaration) -> tuple[str, ...]:
    policy = declaration.policy
    binding = policy.applicability_binding
    if binding is None:
        return ("hard_policy_evidence_missing",)
    reasons = []
    if binding.claim_id != policy.policy_id:
        reasons.append("hard_policy_claim_identity_mismatch")
    if (
        not binding.required_conditions
        or binding.unmatched_conditions
        or set(binding.matched_conditions) != set(binding.required_conditions)
        or binding.reviewer_record_id is None
    ):
        reasons.append("hard_policy_applicability_incomplete")
    if binding.geometry_source_fingerprint != decoupling_loop_context_fingerprint(declaration):
        reasons.append("hard_policy_context_fingerprint_mismatch")
    binding_conditions = set(binding.required_conditions)
    if not all(
        bool(item.source_id and item.source_id.strip())
        and bool(item.revision and item.revision.strip())
        and item.source_status == "pinned"
        and _is_sha256(item.local_sha256)
        and item.locator_status in {"text_verified", "figure_verified"}
        and item.applicability_status == "confirmed"
        and item.required_conditions
        and set(item.required_conditions).issubset(binding_conditions)
        for item in binding.evidence
    ):
        reasons.append("hard_policy_evidence_not_revisioned_pinned_verified_applicable")
    return tuple(sorted(reasons))


def _policy_violations(
    metrics: DecouplingLoopMetrics,
    policy: DecouplingLoopPolicy,
) -> tuple[str, ...]:
    violations = []
    if Fraction(metrics.combined_via_count) > policy.maximum_via_count.fraction():
        violations.append("maximum_via_count_exceeded")
    if policy.minimum_track_width_mm is not None:
        if (
            metrics.combined_minimum_track_width_mm is not None
            and metrics.combined_minimum_track_width_mm < policy.minimum_track_width_mm
        ):
            violations.append("minimum_track_width_violated")
    if (
        policy.maximum_projected_loop_area_mm2 is not None
        and metrics.projected_loop_area_mm2 is not None
        and metrics.projected_loop_area_mm2.fraction()
        > policy.maximum_projected_loop_area_mm2.fraction()
    ):
        violations.append("maximum_projected_loop_area_exceeded")
    if policy.require_dedicated and metrics.terminal_classification == "daisy_chain":
        violations.append("dedicated_topology_required")
    return tuple(sorted(violations))


def rederive_decoupling_loop(
    graph_result: RoutedCopperGraphResult,
    supply_path: ResolvedCopperPathResult,
    return_path: ResolvedCopperPathResult,
    declaration: DecouplingLoopDeclaration,
) -> dict[str, Any]:
    graph, supply, return_leg, retained = _validate_inputs(
        graph_result, supply_path, return_path, declaration
    )
    path_reasons = []
    for name, path in (("supply", supply), ("return", return_leg)):
        if (
            path.connectivity_state != "connected"
            or path.verification is not SemanticVerification.EXACT
            or path.unknown_reasons
        ):
            path_reasons.append(f"{name}_path_not_exact_connected")
    metrics = None if path_reasons else _derive_metrics(graph, supply, return_leg, retained)
    unverified = list(path_reasons)
    if metrics is not None:
        policy = retained.policy
        if metrics.projected_closure_verification != "exact_simple":
            unverified.append("projected_loop_area_unverified")
        if metrics.terminal_classification == "unverified":
            unverified.append("terminal_inventory_incomplete")
        if policy.minimum_track_width_mm is not None:
            if metrics.combined_minimum_track_width_mm is None:
                unverified.append("track_width_unavailable")
        if policy.maximum_projected_loop_area_mm2 is not None:
            if metrics.projected_loop_area_mm2 is None:
                unverified.append("projected_loop_area_unverified")
        if policy.mode == "sourced_hard":
            unverified.extend(_hard_binding_reasons(retained))
    violations_tuple = (
        () if metrics is None or unverified else _policy_violations(metrics, retained.policy)
    )
    unverified_tuple = tuple(sorted(set(unverified)))
    disposition = (
        SemanticDisposition.UNVERIFIED
        if unverified_tuple
        else SemanticDisposition.ADVISORY
        if retained.policy.mode == "advisory"
        else SemanticDisposition.FAIL
        if violations_tuple
        else SemanticDisposition.PASS
    )
    input_fp = fingerprint(
        {
            "graph": graph.result_fingerprint,
            "supply": supply.result_fingerprint,
            "return": return_leg.result_fingerprint,
            "declaration": retained.semantic_fingerprint(),
        }
    )
    return {
        "declaration": retained,
        "metrics": metrics,
        "disposition": disposition,
        "violation_ids": violations_tuple,
        "unverified_reasons": unverified_tuple,
        "input_fingerprint": input_fp,
    }


def evaluate_decoupling_loop(
    graph: RoutedCopperGraphResult,
    supply_path: ResolvedCopperPathResult,
    return_path: ResolvedCopperPathResult,
    declaration: DecouplingLoopDeclaration,
) -> DecouplingLoopEvaluationResult:
    derived = rederive_decoupling_loop(graph, supply_path, return_path, declaration)
    fields = {"graph": graph, "supply_path": supply_path, "return_path": return_path, **derived}
    provisional = DecouplingLoopEvaluationResult.model_construct(
        **fields, result_fingerprint="0" * 64
    )
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return DecouplingLoopEvaluationResult(**fields, result_fingerprint=result_fp)
