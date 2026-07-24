"""Exact caller-declared switching hot-loop path and projected-area evaluator."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from pcbsmith.kicad.board_serialization import parse_canonical_board_netlist_snapshot
from pcbsmith.kicad.decoupling_loop import _on_segment, _orientation, _segments_intersect
from pcbsmith.routed_copper_graph_ir import (
    CopperRadicalLengthTerm,
    ExactRational,
    ResolvedCopperPathResult,
    RoutedCopperGraphResult,
    fingerprint,
)
from pcbsmith.semantic_ir import SemanticDisposition, SemanticVerification
from pcbsmith.switching_hot_loop_ir import (
    SwitchingHotLoopDeclaration,
    SwitchingHotLoopEvaluationResult,
    SwitchingHotLoopLegMetrics,
    SwitchingHotLoopMetrics,
    SwitchingHotLoopTransitionEvidence,
    switching_hot_loop_context_fingerprint,
)

Point = tuple[Fraction, Fraction]


def _validate_inputs(
    graph_result: RoutedCopperGraphResult,
    paths: Sequence[ResolvedCopperPathResult],
    declaration: SwitchingHotLoopDeclaration,
) -> tuple[
    RoutedCopperGraphResult, tuple[ResolvedCopperPathResult, ...], SwitchingHotLoopDeclaration
]:
    graph = RoutedCopperGraphResult.model_validate_json(graph_result.model_dump_json())
    retained_paths = tuple(
        ResolvedCopperPathResult.model_validate_json(item.model_dump_json()) for item in paths
    )
    retained = SwitchingHotLoopDeclaration.model_validate_json(declaration.model_dump_json())
    if len(retained_paths) != len(retained.legs):
        raise ValueError("switching-loop declaration requires one exact path per ordered leg")
    if (
        retained.graph_fingerprint != graph.graph_fingerprint
        or retained.board_layout_snapshot_fingerprint != graph.board_layout_snapshot_fingerprint
        or retained.board_netlist_snapshot_fingerprint != graph.board_netlist_snapshot_fingerprint
    ):
        raise ValueError("switching-loop graph/layout/netlist authority is stale")
    anchors = {item.anchor_id: item for item in graph.terminal_anchors}
    for index, (leg, path) in enumerate(zip(retained.legs, retained_paths, strict=True)):
        if path.graph != graph or path.result_fingerprint != leg.path_result_fingerprint:
            raise ValueError("switching-loop leg path authority is stale")
        if (
            path.selection.start_anchor_id != leg.start_anchor_id
            or path.selection.end_anchor_id != leg.end_anchor_id
            or path.selection.net_name != leg.net_name
        ):
            raise ValueError("switching-loop path differs from declared leg terminals/net")
        if (
            leg.start_anchor_id not in anchors
            or leg.end_anchor_id not in anchors
            or anchors[leg.start_anchor_id].physical_pad_source_id != leg.start_pad_source_id
            or anchors[leg.end_anchor_id].physical_pad_source_id != leg.end_pad_source_id
        ):
            raise ValueError("switching-loop leg physical pad authority is stale")
        transition = retained.transitions[index]
        next_leg = retained.legs[(index + 1) % len(retained.legs)]
        from_anchor = anchors.get(transition.from_anchor_id)
        to_anchor = anchors.get(transition.to_anchor_id)
        if (
            transition.from_anchor_id != leg.end_anchor_id
            or transition.to_anchor_id != next_leg.start_anchor_id
            or from_anchor is None
            or to_anchor is None
            or from_anchor.physical_pad_source_id != transition.from_pad_source_id
            or to_anchor.physical_pad_source_id != transition.to_pad_source_id
            or from_anchor.component_reference != transition.component_reference
            or to_anchor.component_reference != transition.component_reference
        ):
            raise ValueError(
                "adjacent switching-loop legs do not match declared terminal transition"
            )
    return graph, retained_paths, retained


def _point(graph: RoutedCopperGraphResult, node_id: str) -> Point:
    node = next(item for item in graph.nodes if item.node_id == node_id)
    return Fraction(node.x_mm), Fraction(node.y_mm)


def _layers(graph: RoutedCopperGraphResult, path: ResolvedCopperPathResult) -> tuple[str, ...]:
    nodes = {item.node_id: item for item in graph.nodes}
    edge_map = {item.edge_id: item for item in graph.edges}
    values = []
    for index, edge_id in enumerate(path.ordered_edge_ids):
        edge = edge_map[edge_id]
        start = nodes[path.ordered_node_ids[index]].layer
        end = nodes[path.ordered_node_ids[index + 1]].layer
        values.append(start if edge.kind != "via" else f"{start}->{end}")
    return tuple(values)


def _leg_metrics(
    graph: RoutedCopperGraphResult,
    declaration: SwitchingHotLoopDeclaration,
    paths: tuple[ResolvedCopperPathResult, ...],
) -> tuple[SwitchingHotLoopLegMetrics, ...]:
    return tuple(
        SwitchingHotLoopLegMetrics(
            leg_id=leg.leg_id,
            ordered_node_ids=path.ordered_node_ids,
            ordered_edge_ids=path.ordered_edge_ids,
            ordered_source_ids=path.ordered_source_ids,
            ordered_layer_transitions=_layers(graph, path),
            via_count=path.via_count,
            via_source_ids=path.via_source_ids,
            minimum_track_width_mm=path.minimum_width_mm,
            neck_edge_ids=path.neck_edge_ids,
            radical_length_terms=path.radical_length_terms,
        )
        for leg, path in zip(declaration.legs, paths, strict=True)
    )


def _combine_terms(
    paths: tuple[ResolvedCopperPathResult, ...],
) -> tuple[CopperRadicalLengthTerm, ...]:
    values: dict[int, Fraction] = defaultdict(Fraction)
    for path in paths:
        for term in path.radical_length_terms:
            values[term.squarefree_radicand] += term.coefficient_mm.fraction()
    return tuple(
        CopperRadicalLengthTerm(
            squarefree_radicand=radicand,
            coefficient_mm=ExactRational.build(coefficient),
        )
        for radicand, coefficient in sorted(values.items())
    )


def _polygon_area(points: tuple[Point, ...]) -> tuple[Fraction | None, str]:
    compact: list[Point] = []
    for point in points:
        if not compact or compact[-1] != point:
            compact.append(point)
    if len(compact) > 1 and compact[0] == compact[-1]:
        compact.pop()
    values = tuple(compact)
    if len(values) < 3 or len(values) != len(set(values)):
        return None, "unverified_non_simple"
    for index in range(len(values)):
        previous, current, following = (
            values[index - 1],
            values[index],
            values[(index + 1) % len(values)],
        )
        if _orientation(previous, current, following) == 0 and (
            _on_segment(following, previous, current) or _on_segment(previous, current, following)
        ):
            return None, "unverified_non_simple"
    edges = tuple(
        (values[index], values[(index + 1) % len(values)]) for index in range(len(values))
    )
    for first_index, (a, b) in enumerate(edges):
        for second_index, (c, d) in enumerate(edges[first_index + 1 :], first_index + 1):
            adjacent = second_index == first_index + 1 or (
                first_index == 0 and second_index == len(edges) - 1
            )
            if not adjacent and _segments_intersect(a, b, c, d):
                return None, "unverified_non_simple"
    twice_area = sum(a[0] * b[1] - a[1] * b[0] for a, b in edges)
    if twice_area == 0:
        return None, "unverified_non_simple"
    return twice_area / 2, "exact_simple"


def _derive_metrics(
    graph: RoutedCopperGraphResult,
    paths: tuple[ResolvedCopperPathResult, ...],
    declaration: SwitchingHotLoopDeclaration,
) -> SwitchingHotLoopMetrics:
    leg_metrics = _leg_metrics(graph, declaration, paths)
    anchor_nodes = {
        anchor_id: node.node_id for node in graph.nodes for anchor_id in node.anchor_ids
    }
    polygon_points: list[Point] = []
    transitions = []
    for path, transition in zip(paths, declaration.transitions, strict=True):
        polygon_points.extend(_point(graph, item) for item in path.ordered_node_ids)
        first = _point(graph, anchor_nodes[transition.from_anchor_id])
        second = _point(graph, anchor_nodes[transition.to_anchor_id])
        polygon_points.append(second)
        transitions.append(
            SwitchingHotLoopTransitionEvidence(
                transition_id=transition.transition_id,
                from_anchor_id=transition.from_anchor_id,
                to_anchor_id=transition.to_anchor_id,
                squared_projected_length_mm2=ExactRational.build(
                    (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2
                ),
            )
        )
    signed_area, verification = _polygon_area(tuple(polygon_points))
    widths = tuple(path.minimum_width_mm for path in paths if path.minimum_width_mm is not None)
    minimum = min(widths) if widths else None
    necks = (
        tuple(
            sorted(
                edge_id
                for path in paths
                if path.minimum_width_mm == minimum
                for edge_id in path.neck_edge_ids
            )
        )
        if minimum is not None
        else ()
    )
    return SwitchingHotLoopMetrics(
        legs=leg_metrics,
        transitions=tuple(transitions),
        combined_source_ids=tuple(item for path in paths for item in path.ordered_source_ids),
        combined_via_count=sum(path.via_count for path in paths),
        combined_via_source_ids=tuple(
            sorted(item for path in paths for item in path.via_source_ids)
        ),
        combined_minimum_track_width_mm=minimum,
        combined_neck_edge_ids=necks,
        combined_radical_length_terms=_combine_terms(paths),
        projected_signed_area_mm2=(
            None if signed_area is None else ExactRational.build(signed_area)
        ),
        projected_absolute_area_mm2=(
            None if signed_area is None else ExactRational.build(abs(signed_area))
        ),
        projected_polygon_verification=verification,
        transition_component_references=tuple(
            item.component_reference for item in declaration.transitions
        ),
        transition_roles=tuple(item.transition_role for item in declaration.transitions),
        leg_terminal_component_references=tuple(
            (
                leg.leg_id,
                tuple(
                    sorted(
                        {
                            reference
                            for net in parse_canonical_board_netlist_snapshot(
                                graph.board_netlist_snapshot_json
                            ).nets
                            if net.name == leg.net_name
                            for reference, _pad in net.nodes
                        }
                    )
                ),
            )
            for leg in declaration.legs
        ),
    )


def _terminal_inventory_reasons(
    graph: RoutedCopperGraphResult,
    declaration: SwitchingHotLoopDeclaration,
) -> tuple[str, ...]:
    netlist = parse_canonical_board_netlist_snapshot(graph.board_netlist_snapshot_json)
    reasons = []
    for leg in declaration.legs:
        netlist_nodes = {
            node for net in netlist.nets if net.name == leg.net_name for node in net.nodes
        }
        anchors = tuple(item for item in graph.terminal_anchors if item.net_name == leg.net_name)
        anchor_nodes = tuple((item.component_reference, item.pad_number) for item in anchors)
        if (
            len(anchor_nodes) != len(set(anchor_nodes))
            or len({item.physical_pad_source_id for item in anchors}) != len(anchors)
        ):
            reasons.append(f"duplicate_terminal_anchor_alias:{leg.leg_id}")
        if set(anchor_nodes) != netlist_nodes:
            reasons.append(f"terminal_inventory_incomplete:{leg.leg_id}")
    return tuple(sorted(reasons))


def _policy_violations(
    graph: RoutedCopperGraphResult,
    declaration: SwitchingHotLoopDeclaration,
    metrics: SwitchingHotLoopMetrics,
) -> tuple[str, ...]:
    violations = []
    if metrics.transition_roles != declaration.limit.expected_transition_roles:
        violations.append("expected_transition_membership_violated")
    anchors = {item.anchor_id: item for item in graph.terminal_anchors}
    for index, (leg_id, actual_references) in enumerate(
        metrics.leg_terminal_component_references
    ):
        leg = declaration.legs[index]
        expected_references = {
            anchors[leg.start_anchor_id].component_reference,
            anchors[leg.end_anchor_id].component_reference,
            *leg.declared_parallel_component_references,
        }
        if set(actual_references) != expected_references:
            violations.append(f"unexpected_parallel_or_bypass_component:{leg_id}")
    maximum = declaration.limit.maximum_projected_area_mm2
    if maximum is not None and metrics.projected_absolute_area_mm2 is not None:
        if metrics.projected_absolute_area_mm2.fraction() > maximum.fraction():
            violations.append("maximum_projected_area_exceeded")
    return tuple(sorted(violations))


def _hard_binding_reasons(
    graph: RoutedCopperGraphResult,
    declaration: SwitchingHotLoopDeclaration,
) -> tuple[str, ...]:
    limit = declaration.limit
    reasons = []
    if limit.maximum_projected_area_mm2 is None:
        reasons.append("hard_limit_threshold_missing")
    binding = limit.applicability_binding
    if binding is None:
        reasons.append("hard_limit_evidence_missing")
        return tuple(reasons)
    expected_context = switching_hot_loop_context_fingerprint(
        graph_fingerprint=declaration.graph_fingerprint,
        board_layout_snapshot_fingerprint=declaration.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=declaration.board_netlist_snapshot_fingerprint,
        topology_kind=declaration.topology_kind,
        legs=declaration.legs,
        transitions=declaration.transitions,
        limit_id=limit.limit_id,
        mode=limit.mode,
        maximum_projected_area_mm2=limit.maximum_projected_area_mm2,
        intended_consumer=limit.intended_consumer,
        expected_transition_roles=limit.expected_transition_roles,
    )
    if binding.claim_id != limit.limit_id:
        reasons.append("hard_limit_claim_identity_mismatch")
    if (
        not binding.required_conditions
        or binding.unmatched_conditions
        or set(binding.matched_conditions) != set(binding.required_conditions)
        or binding.reviewer_record_id is None
    ):
        reasons.append("hard_limit_applicability_incomplete")
    if binding.geometry_source_fingerprint != expected_context:
        reasons.append("hard_limit_context_fingerprint_mismatch")
    binding_conditions = set(binding.required_conditions)
    if not all(
        bool(item.source_id and item.source_id.strip())
        and bool(item.revision and item.revision.strip())
        and item.source_status == "pinned"
        and item.local_sha256 is not None
        and len(item.local_sha256) == 64
        and all(character in "0123456789abcdef" for character in item.local_sha256)
        and item.locator_status in {"text_verified", "figure_verified"}
        and item.applicability_status == "confirmed"
        and item.required_conditions
        and set(item.required_conditions).issubset(binding_conditions)
        for item in binding.evidence
    ):
        reasons.append("hard_limit_evidence_not_revisioned_pinned_verified_applicable")
    return tuple(sorted(reasons))


def rederive_switching_hot_loop(
    graph_result: RoutedCopperGraphResult,
    path_results: Sequence[ResolvedCopperPathResult],
    declaration: SwitchingHotLoopDeclaration,
) -> dict[str, Any]:
    graph, paths, retained = _validate_inputs(graph_result, path_results, declaration)
    reasons = []
    for leg, path in zip(retained.legs, paths, strict=True):
        if (
            path.connectivity_state != "connected"
            or path.verification is not SemanticVerification.EXACT
            or path.unknown_reasons
        ):
            reasons.append(f"leg_not_exact_connected:{leg.leg_id}")
    metrics = None if reasons else _derive_metrics(graph, paths, retained)
    if metrics is not None and metrics.projected_polygon_verification != "exact_simple":
        reasons.append("projected_polygon_unverified")
    if metrics is not None:
        reasons.extend(_terminal_inventory_reasons(graph, retained))
        if retained.limit.mode == "sourced_hard":
            reasons.extend(_hard_binding_reasons(graph, retained))
    reasons_tuple = tuple(sorted(set(reasons)))
    violations = (
        () if metrics is None or reasons_tuple else _policy_violations(graph, retained, metrics)
    )
    disposition = (
        SemanticDisposition.UNVERIFIED
        if reasons_tuple
        else SemanticDisposition.ADVISORY
        if retained.limit.mode == "advisory"
        else SemanticDisposition.FAIL
        if violations
        else SemanticDisposition.PASS
    )
    input_fp = fingerprint(
        {
            "graph": graph.result_fingerprint,
            "paths": [item.result_fingerprint for item in paths],
            "declaration": retained.semantic_fingerprint(),
        }
    )
    return {
        "paths": paths,
        "declaration": retained,
        "metrics": metrics,
        "disposition": disposition,
        "violation_ids": violations,
        "unverified_reasons": reasons_tuple,
        "input_fingerprint": input_fp,
    }


def evaluate_switching_hot_loop(
    graph: RoutedCopperGraphResult,
    paths: Sequence[ResolvedCopperPathResult],
    declaration: SwitchingHotLoopDeclaration,
) -> SwitchingHotLoopEvaluationResult:
    derived = rederive_switching_hot_loop(graph, paths, declaration)
    fields = {"graph": graph, **derived}
    provisional = SwitchingHotLoopEvaluationResult.model_construct(
        **fields, result_fingerprint="0" * 64
    )
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return SwitchingHotLoopEvaluationResult(**fields, result_fingerprint=result_fp)
