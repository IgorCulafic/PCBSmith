"""Bounded restricted-exact return-adjacency evaluator."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from typing import Any

from pcbsmith.mask_geometry import Compound, OrientedRect, Polygon
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlanarRelation,
    compound_inside_polygon,
    compound_relation,
)
from pcbsmith.return_adjacency_ir import (
    ADVISORY_MODEL_IDS,
    QualifiedReferenceFill,
    ReferenceStitchEvidence,
    ReturnAdjacencyResult,
    ReturnDiscontinuityEvidence,
    ReturnFinding,
    ReturnPathDeclaration,
    ReturnSegmentEvidence,
    ReturnTransitionEvidence,
    TransitionStitchSelection,
)
from pcbsmith.routed_copper_graph_ir import ExactRational, fingerprint
from pcbsmith.semantic_ir import SemanticDisposition
from pcbsmith.sensor_copper_removal_ir import ExactFilledZoneCopper


def _rational(value: Decimal | Fraction) -> ExactRational:
    return ExactRational.build(value if isinstance(value, Fraction) else Fraction(value))


def _rectangle(
    x1: Fraction, y1: Fraction, x2: Fraction, y2: Fraction, width: Fraction
) -> ExactPlanarCompound | None:
    half = width / 2
    if x1 == x2:
        left, right = x1 - half, x1 + half
        bottom, top = min(y1, y2) - half, max(y1, y2) + half
    elif y1 == y2:
        left, right = min(x1, x2) - half, max(x1, x2) + half
        bottom, top = y1 - half, y1 + half
    else:
        return None
    polygon = ExactPlanarPolygon(
        outer=(
            (float(left), float(bottom)),
            (float(right), float(bottom)),
            (float(right), float(top)),
            (float(left), float(top)),
        )
    )
    return ExactPlanarCompound(polygons=(polygon,))


def derive_exact_reference_fill_geometry(
    fill: ExactFilledZoneCopper,
) -> ExactPlanarCompound | None:
    """Convert only graph-retained exact polygonal fill; never reconstruct curves."""

    def polygons(geometry: Any) -> tuple[ExactPlanarPolygon, ...] | None:
        if isinstance(geometry, OrientedRect) and geometry.angle_deg in {
            0.0,
            90.0,
            180.0,
            270.0,
        }:
            cx = Fraction(str(geometry.center.x_mm))
            cy = Fraction(str(geometry.center.y_mm))
            width = Fraction(str(geometry.width_mm))
            height = Fraction(str(geometry.height_mm))
            if geometry.angle_deg in {90.0, 270.0}:
                width, height = height, width
            half_width, half_height = width / 2, height / 2
            return (
                ExactPlanarPolygon(
                    outer=(
                        (float(cx - half_width), float(cy - half_height)),
                        (float(cx + half_width), float(cy - half_height)),
                        (float(cx + half_width), float(cy + half_height)),
                        (float(cx - half_width), float(cy + half_height)),
                    )
                ),
            )
        if isinstance(geometry, Polygon):
            return (
                ExactPlanarPolygon(
                    outer=tuple((item.x_mm, item.y_mm) for item in geometry.vertices)
                ),
            )
        if isinstance(geometry, Compound):
            retained: list[ExactPlanarPolygon] = []
            for part in geometry.parts:
                converted = polygons(part)
                if converted is None:
                    return None
                retained.extend(converted)
            return tuple(retained)
        return None

    converted = polygons(fill.geometry)
    if converted is None:
        return None
    try:
        return ExactPlanarCompound(polygons=converted)
    except ValueError:
        # Touching/overlapping pieces would require an exact polygon-union kernel.
        return None


def _relation(
    signal: ExactPlanarCompound, fills: tuple[QualifiedReferenceFill, ...]
) -> tuple[str, QualifiedReferenceFill | None]:
    # A pass is deliberately limited to containment by one polygon.  Islands are
    # never unioned to manufacture continuity.
    for fill in fills:
        for polygon in fill.exact_geometry.polygons:
            if compound_inside_polygon(signal, polygon):
                return "contained", fill
    relations = tuple(compound_relation(signal, fill.exact_geometry) for fill in fills)
    if fills and all(item is PlanarRelation.DISJOINT for item in relations):
        return "disjoint", None
    return "partial_overlap", None


def _cross(first: tuple[Fraction, Fraction], second: tuple[Fraction, Fraction]) -> Fraction:
    return first[0] * second[1] - first[1] * second[0]


def _boundary_intersection(
    start: tuple[Fraction, Fraction],
    end: tuple[Fraction, Fraction],
    first: tuple[Fraction, Fraction],
    second: tuple[Fraction, Fraction],
) -> tuple[Fraction, Fraction] | None:
    signal = (end[0] - start[0], end[1] - start[1])
    boundary = (second[0] - first[0], second[1] - first[1])
    offset = (first[0] - start[0], first[1] - start[1])
    denominator = _cross(signal, boundary)
    if denominator == 0:
        candidates = tuple(
            point
            for point in (start, end, first, second)
            if _cross((point[0] - start[0], point[1] - start[1]), signal) == 0
            and min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
            and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
            and min(first[0], second[0]) <= point[0] <= max(first[0], second[0])
            and min(first[1], second[1]) <= point[1] <= max(first[1], second[1])
        )
        return min(candidates) if candidates else None
    signal_parameter = _cross(offset, boundary) / denominator
    boundary_parameter = _cross(offset, signal) / denominator
    if not (0 <= signal_parameter <= 1 and 0 <= boundary_parameter <= 1):
        return None
    return (
        start[0] + signal_parameter * signal[0],
        start[1] + signal_parameter * signal[1],
    )


def _partial_location(
    start: tuple[Fraction, Fraction],
    end: tuple[Fraction, Fraction],
    fills: tuple[QualifiedReferenceFill, ...],
) -> tuple[Fraction, Fraction]:
    candidates: set[tuple[Fraction, Fraction]] = set()
    for fill in fills:
        for polygon in fill.exact_geometry.polygons:
            for boundary in (polygon.outer, *polygon.holes):
                rational = tuple((Fraction(str(x)), Fraction(str(y))) for x, y in boundary)
                for index, first in enumerate(rational):
                    point = _boundary_intersection(
                        start, end, first, rational[(index + 1) % len(rational)]
                    )
                    if point is not None:
                        candidates.add(point)
    return min(candidates) if candidates else start


def _validate_inputs(
    declaration: ReturnPathDeclaration,
    reference_fills: Sequence[QualifiedReferenceFill],
    stitch_evidence: Sequence[ReferenceStitchEvidence],
    selections: Sequence[TransitionStitchSelection],
) -> tuple[
    ReturnPathDeclaration,
    tuple[QualifiedReferenceFill, ...],
    tuple[ReferenceStitchEvidence, ...],
    tuple[TransitionStitchSelection, ...],
]:
    retained = ReturnPathDeclaration.model_validate_json(declaration.model_dump_json())
    fills = tuple(sorted(reference_fills, key=lambda item: item.reference_fill_id))
    stitches = tuple(sorted(stitch_evidence, key=lambda item: item.stitch_evidence_id))
    chosen = tuple(sorted(selections, key=lambda item: item.signal_transition_source_id))
    for values, name, attribute in (
        (fills, "reference fill", "reference_fill_id"),
        (stitches, "stitch evidence", "stitch_evidence_id"),
        (chosen, "transition selection", "signal_transition_source_id"),
    ):
        ids = [getattr(item, attribute) for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{name} identities must be unique")
    zone_source_ids = [item.zone_source_id for item in fills]
    if len(zone_source_ids) != len(set(zone_source_ids)):
        raise ValueError("reference-fill zone sources must be unique")
    graph_fill_by_source = {item.zone_source_id: item for item in retained.graph.exact_filled_zones}
    for fill in fills:
        if fill.reference_net_name != retained.reference_net_name:
            raise ValueError("reference fill belongs to another net")
        if (
            fill.provenance.board_layout_snapshot_fingerprint
            != retained.board_layout_snapshot_fingerprint
        ):
            raise ValueError("reference fill is stale for the declared BoardLayout")
        graph_fill = graph_fill_by_source.get(fill.zone_source_id)
        if graph_fill is None:
            raise ValueError("reference fill source is absent from the routed graph authority")
        if (
            graph_fill.zone_net_name != fill.reference_net_name
            or graph_fill.layer != fill.layer
            or graph_fill.reader_id != fill.provenance.reader_id
            or graph_fill.reader_version != fill.provenance.reader_version
            or graph_fill.source_artifact_id != fill.provenance.source_artifact_id
            or graph_fill.source_artifact_sha256 != fill.provenance.source_artifact_sha256
            or graph_fill.final_fill_record_sha256 != fill.routed_graph_final_fill_record_sha256
        ):
            raise ValueError("reference fill provenance differs from routed graph final fill")
        replayed_geometry = derive_exact_reference_fill_geometry(graph_fill)
        if replayed_geometry is None:
            raise ValueError("routed graph final-fill geometry is unsupported by restricted v1")
        if (
            fill.exact_geometry != replayed_geometry
            or fill.exact_geometry.semantic_fingerprint()
            != replayed_geometry.semantic_fingerprint()
        ):
            raise ValueError("caller reference geometry differs from replayed graph final fill")
    edge_by_source = {item.source_id: item for item in retained.graph.edges}
    for stitch in stitches:
        if stitch.reference_net_name != retained.reference_net_name:
            raise ValueError("reference stitch belongs to another net")
        edge = edge_by_source.get(stitch.source_id)
        if edge is None or edge.kind != "via" or edge.net_name != retained.reference_net_name:
            raise ValueError("explicit reference-via source is absent from routed graph authority")
        first = next(item for item in retained.graph.nodes if item.node_id == edge.start_node_id)
        second = next(item for item in retained.graph.nodes if item.node_id == edge.end_node_id)
        if (
            set(stitch.reference_layers) != {first.layer, second.layer}
            or Fraction(stitch.x_mm) != Fraction(first.x_mm)
            or Fraction(stitch.y_mm) != Fraction(first.y_mm)
            or Fraction(first.x_mm) != Fraction(second.x_mm)
            or Fraction(first.y_mm) != Fraction(second.y_mm)
        ):
            raise ValueError("reference-via geometry differs from routed graph authority")
    edge_by_id = {item.edge_id: item for item in retained.graph.edges}
    declared_transition_sources = {
        edge_by_id[edge_id].source_id
        for leg in retained.legs
        for edge_id in leg.complete_selected_path.ordered_edge_ids
        if edge_by_id[edge_id].kind == "via"
    }
    if retained.transition_stitch_requirement is None and chosen:
        raise ValueError("transition selections require an explicit stitch requirement")
    stitch_ids = {item.stitch_evidence_id for item in stitches}
    for selection in chosen:
        if selection.signal_transition_source_id not in declared_transition_sources:
            raise ValueError("transition selection refers to a via outside declared signal legs")
        if selection.stitch_evidence_id not in stitch_ids:
            raise ValueError("transition selection refers to absent retained stitch evidence")
    return retained, fills, stitches, chosen


def rederive_return_adjacency(
    declaration: ReturnPathDeclaration,
    reference_fills: Sequence[QualifiedReferenceFill] = (),
    stitch_evidence: Sequence[ReferenceStitchEvidence] = (),
    stitch_selections: Sequence[TransitionStitchSelection] = (),
) -> dict[str, Any]:
    retained, fills, stitches, selections = _validate_inputs(
        declaration, reference_fills, stitch_evidence, stitch_selections
    )
    graph = retained.graph
    node_map = {item.node_id: item for item in graph.nodes}
    edge_map = {item.edge_id: item for item in graph.edges}
    layer_map = {item.signal_layer: item.reference_layer for item in retained.layer_pairs}
    fill_map = {
        layer: tuple(item for item in fills if item.layer == layer)
        for layer in set(layer_map.values())
    }
    segment_records: list[ReturnSegmentEvidence] = []
    gaps: list[ReturnDiscontinuityEvidence] = []
    transitions: list[ReturnTransitionEvidence] = []
    findings: list[ReturnFinding] = []
    stitch_map = {item.stitch_evidence_id: item for item in stitches}
    selection_map = {item.signal_transition_source_id: item for item in selections}

    for leg in retained.legs:
        path = leg.complete_selected_path
        for index, edge_id in enumerate(path.ordered_edge_ids):
            edge = edge_map[edge_id]
            first = node_map[path.ordered_node_ids[index]]
            second = node_map[path.ordered_node_ids[index + 1]]
            if edge.kind == "via":
                before_layer, after_layer = first.layer, second.layer
                before_reference = layer_map.get(before_layer)
                after_reference = layer_map.get(after_layer)
                selected = selection_map.get(edge.source_id)
                stitch = None if selected is None else stitch_map.get(selected.stitch_evidence_id)
                squared: Fraction | None = None
                state = "not_required"
                requirement = retained.transition_stitch_requirement
                if requirement is not None:
                    if before_reference is None or after_reference is None:
                        state = "unverified"
                    elif stitch is None:
                        state = "unstitched"
                    elif stitch.reference_net_name != retained.reference_net_name or set(
                        stitch.reference_layers
                    ) != {before_reference, after_reference}:
                        state = "unverified"
                    else:
                        dx = Fraction(first.x_mm) - Fraction(stitch.x_mm)
                        dy = Fraction(first.y_mm) - Fraction(stitch.y_mm)
                        squared = dx * dx + dy * dy
                        maximum = Fraction(requirement.maximum_distance_mm)
                        state = "stitched" if squared <= maximum * maximum else "unstitched"
                transitions.append(
                    ReturnTransitionEvidence(
                        leg_id=leg.leg_id,
                        signal_via_source_id=edge.source_id,
                        from_signal_layer=before_layer,
                        to_signal_layer=after_layer,
                        from_reference_layer=before_reference or "undeclared",
                        to_reference_layer=after_reference or "undeclared",
                        stitch_evidence_id=None if stitch is None else stitch.stitch_evidence_id,
                        squared_stitch_distance_mm2=None if squared is None else _rational(squared),
                        stitch_state=state,
                    )
                )
                segment_records.append(
                    ReturnSegmentEvidence(
                        leg_id=leg.leg_id,
                        edge_id=edge.edge_id,
                        signal_source_id=edge.source_id,
                        signal_layer=f"{before_layer}->{after_layer}",
                        reference_layer=f"{before_reference}->{after_reference}",
                        reference_fill_id=None,
                        state="transition",
                        relation="transition",
                    )
                )
                if state in {"unstitched", "unverified"}:
                    disposition = (
                        SemanticDisposition.FAIL
                        if state == "unstitched"
                        else SemanticDisposition.UNVERIFIED
                    )
                    findings.append(
                        ReturnFinding(
                            finding_id=f"finding:transition:{leg.leg_id}:{edge.source_id}",
                            kind="transition_stitch",
                            disposition=disposition,
                            source_ids=(edge.source_id,),
                            message=(
                                "Signal-layer transition lacks the explicitly required "
                                "exact stitch."
                            )
                            if state == "unstitched"
                            else (
                                "Transition reference-layer pairing or stitch authority "
                                "is incomplete."
                            ),
                        )
                    )
                continue

            reference_layer = layer_map.get(first.layer)
            if edge.kind != "track" or edge.width_mm is None or reference_layer is None:
                relation, geometry = "unsupported", None
            else:
                geometry = _rectangle(
                    Fraction(first.x_mm),
                    Fraction(first.y_mm),
                    Fraction(second.x_mm),
                    Fraction(second.y_mm),
                    Fraction(edge.width_mm),
                )
                relation = (
                    "unsupported"
                    if geometry is None
                    else _relation(geometry, fill_map.get(reference_layer, ()))[0]
                )
            matching_fill = None
            if geometry is not None and reference_layer is not None and relation == "contained":
                _, matching_fill = _relation(geometry, fill_map.get(reference_layer, ()))
            length = abs(Fraction(first.x_mm) - Fraction(second.x_mm)) + abs(
                Fraction(first.y_mm) - Fraction(second.y_mm)
            )
            if relation == "contained":
                state = "covered"
            elif relation == "disjoint":
                state = "uncovered"
            else:
                state = "unverified"
            reason = {
                "unsupported": "only exact axis-aligned track rectangles are supported",
                "partial_overlap": (
                    "partial overlap or multiple-fill union needs intersection-length authority"
                ),
            }.get(relation)
            witness = (
                _partial_location(
                    (Fraction(first.x_mm), Fraction(first.y_mm)),
                    (Fraction(second.x_mm), Fraction(second.y_mm)),
                    fill_map.get(reference_layer, ()) if reference_layer is not None else (),
                )
                if relation == "partial_overlap"
                else (Fraction(first.x_mm), Fraction(first.y_mm))
            )
            segment_records.append(
                ReturnSegmentEvidence(
                    leg_id=leg.leg_id,
                    edge_id=edge.edge_id,
                    signal_source_id=edge.source_id,
                    signal_layer=first.layer,
                    reference_layer=reference_layer or "undeclared",
                    reference_fill_id=(
                        None if matching_fill is None else matching_fill.reference_fill_id
                    ),
                    state=state,
                    relation=relation,
                    witness_point_x=_rational(witness[0]),
                    witness_point_y=_rational(witness[1]),
                    exact_length_mm=_rational(length),
                    unknown_reason=reason,
                )
            )
            if state != "covered":
                relevant_fills = (
                    () if reference_layer is None else fill_map.get(reference_layer, ())
                )
                relevant_sources = tuple(item.zone_source_id for item in relevant_fills)
                gaps.append(
                    ReturnDiscontinuityEvidence(
                        discontinuity_id=f"gap:{leg.leg_id}:{edge.source_id}",
                        leg_id=leg.leg_id,
                        signal_source_ids=(edge.source_id,),
                        reference_fill_source_ids=relevant_sources,
                        location_x=_rational(witness[0]),
                        location_y=_rational(witness[1]),
                        exact_length_mm=_rational(length) if state == "uncovered" else None,
                        state=(
                            "wholly_uncovered" if state == "uncovered" else "partial_or_unknown"
                        ),
                    )
                )

    segments = tuple(sorted(segment_records, key=lambda item: (item.leg_id, item.edge_id)))
    discontinuities = tuple(sorted(gaps, key=lambda item: item.discontinuity_id))
    transition_tuple = tuple(
        sorted(transitions, key=lambda item: (item.leg_id, item.signal_via_source_id))
    )
    adjacency_sources = tuple(sorted({item.signal_source_id for item in segments}))
    path_scope_unverified = any(
        item.complete_selected_path.connectivity_state == "unverified" for item in retained.legs
    )
    if retained.adjacency_model_id in ADVISORY_MODEL_IDS:
        findings.append(
            ReturnFinding(
                finding_id=f"finding:advisory:{retained.adjacency_model_id}",
                kind="advisory_model",
                disposition=SemanticDisposition.ADVISORY,
                source_ids=adjacency_sources,
                message="Scoped advisory model retained without hard pass/fail authority.",
            )
        )
    else:
        track_states = {item.state for item in segments if item.state != "transition"}
        disposition = (
            SemanticDisposition.UNVERIFIED
            if path_scope_unverified or "unverified" in track_states or not track_states
            else SemanticDisposition.FAIL
            if "uncovered" in track_states
            else SemanticDisposition.PASS
        )
        findings.append(
            ReturnFinding(
                finding_id=f"finding:adjacency:{retained.declaration_id}",
                kind="adjacency",
                disposition=disposition,
                source_ids=adjacency_sources,
                message={
                    SemanticDisposition.PASS: (
                        "Every supported complete signal segment is contained in one "
                        "exact reference polygon."
                    ),
                    SemanticDisposition.FAIL: (
                        "At least one complete signal segment is exactly disjoint "
                        "from reference fill."
                    ),
                    SemanticDisposition.UNVERIFIED: (
                        "Return adjacency cannot be proved by the restricted exact kernel."
                    ),
                }[disposition],
            )
        )
        for threshold in retained.hard_thresholds:
            if path_scope_unverified:
                threshold_disposition = SemanticDisposition.UNVERIFIED
            elif threshold.kind == "complete_coverage":
                threshold_disposition = disposition
            elif threshold.kind == "maximum_lateral_distance_mm":
                # Containment proves zero set distance.  The restricted kernel does
                # not claim maximum point-to-reference distance for an uncovered
                # rectangle, so that case fails closed instead of using a nearest
                # point or endpoint sample.
                threshold_disposition = (
                    SemanticDisposition.PASS
                    if track_states == {"covered"}
                    else SemanticDisposition.UNVERIFIED
                )
            else:
                if "unverified" in track_states or threshold.value_mm is None:
                    threshold_disposition = SemanticDisposition.UNVERIFIED
                else:
                    maximum_run = Fraction(0)
                    run_by_leg: dict[str, Fraction] = {}
                    for record in segment_records:
                        if record.state == "uncovered" and record.exact_length_mm is not None:
                            run = run_by_leg.get(record.leg_id, Fraction(0))
                            run += record.exact_length_mm.fraction()
                            run_by_leg[record.leg_id] = run
                            maximum_run = max(maximum_run, run)
                        else:
                            run_by_leg[record.leg_id] = Fraction(0)
                    maximum = Fraction(threshold.value_mm)
                    threshold_disposition = (
                        SemanticDisposition.PASS
                        if maximum_run <= maximum
                        else SemanticDisposition.FAIL
                    )
            findings.append(
                ReturnFinding(
                    finding_id=f"finding:threshold:{threshold.threshold_id}",
                    kind=(
                        "discontinuity"
                        if threshold.kind == "maximum_discontinuity_length_mm"
                        else "adjacency"
                    ),
                    disposition=threshold_disposition,
                    source_ids=adjacency_sources,
                    message=(
                        "Hard return threshold evaluated only from exact complete-segment proofs."
                        if threshold_disposition is not SemanticDisposition.UNVERIFIED
                        else (
                            "Hard return threshold cannot be decided by the restricted exact "
                            "kernel."
                        )
                    ),
                )
            )
    return {
        "segment_evidence": segments,
        "discontinuities": discontinuities,
        "transitions": transition_tuple,
        "findings": tuple(sorted(findings, key=lambda item: item.finding_id)),
        "scope_exclusions": (
            "impedance",
            "current",
            "ir_drop",
            "common_impedance",
            "board_mutation",
        ),
        "board_mutation_performed": False,
    }


def evaluate_return_adjacency(
    declaration: ReturnPathDeclaration,
    reference_fills: Sequence[QualifiedReferenceFill] = (),
    stitch_evidence: Sequence[ReferenceStitchEvidence] = (),
    stitch_selections: Sequence[TransitionStitchSelection] = (),
) -> ReturnAdjacencyResult:
    declaration_json = declaration.model_dump_json()
    fill_json = tuple(item.model_dump_json() for item in reference_fills)
    stitch_json = tuple(item.model_dump_json() for item in stitch_evidence)
    selection_json = tuple(item.model_dump_json() for item in stitch_selections)
    retained, fills, stitches, selections = _validate_inputs(
        declaration, reference_fills, stitch_evidence, stitch_selections
    )
    derived = rederive_return_adjacency(retained, fills, stitches, selections)
    fields = {
        "declaration": retained,
        "reference_fills": fills,
        "stitch_evidence": stitches,
        "stitch_selections": selections,
        **derived,
    }
    provisional = ReturnAdjacencyResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    result = ReturnAdjacencyResult(**fields, result_fingerprint=result_fp)
    if declaration.model_dump_json() != declaration_json:
        raise RuntimeError("return-adjacency evaluator mutated caller declaration")
    if tuple(item.model_dump_json() for item in reference_fills) != fill_json:
        raise RuntimeError("return-adjacency evaluator mutated caller reference fills")
    if tuple(item.model_dump_json() for item in stitch_evidence) != stitch_json:
        raise RuntimeError("return-adjacency evaluator mutated caller stitch evidence")
    if tuple(item.model_dump_json() for item in stitch_selections) != selection_json:
        raise RuntimeError("return-adjacency evaluator mutated caller stitch selections")
    return result
