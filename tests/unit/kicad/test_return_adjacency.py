"""Focused restricted-exact R6 return-adjacency firing fixtures."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pcbsmith.antenna_clearance_ir import QualifiedExactZoneFillProvenance
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.kicad.return_adjacency import evaluate_return_adjacency
from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph, resolve_copper_path
from pcbsmith.mask_geometry import Compound, OrientedRect, Point
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.return_adjacency_ir import (
    ADVISORY_3H_MODEL_ID,
    ADVISORY_3W_MODEL_ID,
    ADVISORY_ONE_TRACE_WIDTH_MODEL_ID,
    EXACT_CONTAINMENT_MODEL_ID,
    QualifiedReferenceFill,
    ReferenceStitchEvidence,
    ReturnHardThreshold,
    ReturnLayerPair,
    ReturnPathDeclaration,
    ReturnPathLeg,
    ReturnSignalClass,
    TransitionStitchRequirement,
    TransitionStitchSelection,
    return_requirement_context_fingerprint,
)
from pcbsmith.routed_copper_graph_ir import (
    CopperTerminalAnchorBinding,
    DeclaredCopperPathSelection,
)
from pcbsmith.semantic_ir import EvidenceApplicabilityBinding, SemanticDisposition
from pcbsmith.sensor_copper_removal_ir import ExactFilledZoneCopper, ExactFilledZoneReaderPolicy


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value="fixture",
        footprint="Fixture:Pad",
        uuid_path=f"uuid:{reference}",
    )


def _fixture(*, diagonal: bool = False, fill_kind: str = "full"):
    components = (_component("U1"), _component("U2"), _component("G1"))
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet(name="SIG", nodes=(("U1", "1"), ("U2", "1"))),
            BoardNet(name="GND", nodes=(("G1", "1"),)),
        ),
    )
    end = (10.0, 2.0) if diagonal else (10.0, 0.0)
    layout = BoardLayout(
        placements=tuple((item, float(index)) for index, item in enumerate(components)),
        segments=(TrackSegment(0.0, 0.0, *end, "F.Cu", "SIG", 0.2),),
        vias=(),
        width_mm=12.0,
        height_mm=6.0,
        zones=(("GND", "B.Cu", (-1.0, -2.0, 11.0, 3.0)),),
    )
    policy = ExactFilledZoneReaderPolicy(
        policy_id="policy:return-fill",
        reader_id="reader:return-fill",
        reader_version="1",
        project_qualification_record_id="qualification:return-fill",
        project_qualification_artifact_sha256="a" * 64,
        reviewer_record_id="review:return-fill",
        status="active",
    )
    fill_geometry = {
        "full": OrientedRect(center=Point(x_mm=5.0, y_mm=0.5), width_mm=12.0, height_mm=5.0),
        "far": OrientedRect(center=Point(x_mm=5.0, y_mm=2.0), width_mm=12.0, height_mm=2.0),
        "tight": OrientedRect(center=Point(x_mm=5.0, y_mm=0.0), width_mm=10.0, height_mm=2.0),
        "slot": Compound(
            parts=(
                OrientedRect(center=Point(x_mm=1.5, y_mm=0.5), width_mm=5.0, height_mm=5.0),
                OrientedRect(center=Point(x_mm=8.5, y_mm=0.5), width_mm=5.0, height_mm=5.0),
            )
        ),
    }[fill_kind]
    graph_fill = ExactFilledZoneCopper.build(
        board_layout_fingerprint=board_layout_fingerprint(layout),
        zone_source_id="zone:0:copper:B.Cu",
        zone_index=0,
        zone_net_name="GND",
        layer="B.Cu",
        geometry=fill_geometry,
        reader_id=policy.reader_id,
        reader_version=policy.reader_version,
        reader_policy=policy,
        source_artifact_id="artifact:return-fill",
        source_artifact_sha256="b" * 64,
    )
    anchors = (
        CopperTerminalAnchorBinding(
            anchor_id="start",
            physical_pad_source_id="pad:U1:1",
            component_reference="U1",
            pad_number="1",
            net_name="SIG",
            layer="F.Cu",
            x_mm="0",
            y_mm="0",
        ),
        CopperTerminalAnchorBinding(
            anchor_id="end",
            physical_pad_source_id="pad:U2:1",
            component_reference="U2",
            pad_number="1",
            net_name="SIG",
            layer="F.Cu",
            x_mm=str(end[0]),
            y_mm=str(end[1]),
        ),
    )
    graph = build_routed_copper_graph(layout, netlist, anchors, (graph_fill,))
    path = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:sig",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="SIG",
            start_anchor_id="start",
            end_anchor_id="end",
            ordered_edge_ids=None,
        ),
    )
    declaration = ReturnPathDeclaration(
        declaration_id="return:sig",
        graph=graph,
        board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
        signal_net_names=("SIG",),
        signal_class=ReturnSignalClass.CLOCK,
        exact_net_class_id="netclass:clock",
        reference_net_name="GND",
        layer_pairs=(ReturnLayerPair(signal_layer="F.Cu", reference_layer="B.Cu"),),
        legs=(
            ReturnPathLeg(
                leg_id="leg:sig",
                signal_net_name="SIG",
                complete_selected_path=path,
            ),
        ),
        adjacency_model_id=EXACT_CONTAINMENT_MODEL_ID,
    )
    return layout, policy, graph_fill, declaration


def _reference_fill(
    layout: BoardLayout,
    policy: ExactFilledZoneReaderPolicy,
    graph_fill: ExactFilledZoneCopper,
    *,
    fill_kind: str = "full",
    forged: bool = False,
) -> QualifiedReferenceFill:
    boundaries = {
        "full": (((-1.0, -2.0), (11.0, -2.0), (11.0, 3.0), (-1.0, 3.0)),),
        "far": (((-1.0, 1.0), (11.0, 1.0), (11.0, 3.0), (-1.0, 3.0)),),
        "tight": (((0.0, -1.0), (10.0, -1.0), (10.0, 1.0), (0.0, 1.0)),),
        "slot": (
            ((-1.0, -2.0), (4.0, -2.0), (4.0, 3.0), (-1.0, 3.0)),
            ((6.0, -2.0), (11.0, -2.0), (11.0, 3.0), (6.0, 3.0)),
        ),
    }["far" if forged else fill_kind]
    geometry = ExactPlanarCompound(
        polygons=tuple(ExactPlanarPolygon(outer=boundary) for boundary in boundaries)
    )
    provenance = QualifiedExactZoneFillProvenance.build(
        fill_provenance_id=f"fill:return:{fill_kind}:{'forged' if forged else 'exact'}",
        zone_source_provenance_id="zone:0:copper:B.Cu",
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(
            canonical_board_layout_snapshot_json(layout)
        ),
        exact_geometry_fingerprint=geometry.semantic_fingerprint(),
        reader_id=policy.reader_id,
        reader_version=policy.reader_version,
        reader_policy=policy,
        source_artifact_id="artifact:return-fill",
        source_artifact_sha256="b" * 64,
    )
    return QualifiedReferenceFill(
        reference_fill_id=f"reference:{fill_kind}:{'forged' if forged else 'exact'}",
        zone_source_id="zone:0:copper:B.Cu",
        reference_net_name="GND",
        layer="B.Cu",
        exact_geometry=geometry,
        provenance=provenance,
        routed_graph_final_fill_record_sha256=graph_fill.final_fill_record_sha256,
    )


def test_exact_full_fill_passes_and_graph_true_slot_is_located_unverified() -> None:
    layout, policy, graph_fill, declaration = _fixture()
    full = evaluate_return_adjacency(declaration, (_reference_fill(layout, policy, graph_fill),))
    assert full.findings[-1].disposition is SemanticDisposition.PASS
    assert full.segment_evidence[0].state == "covered"

    slot_layout, slot_policy, slot_graph_fill, slot_declaration = _fixture(fill_kind="slot")
    hole = evaluate_return_adjacency(
        slot_declaration,
        (_reference_fill(slot_layout, slot_policy, slot_graph_fill, fill_kind="slot"),),
    )
    assert hole.findings[-1].disposition is SemanticDisposition.UNVERIFIED
    assert hole.discontinuities[0].state == "partial_or_unknown"
    assert hole.discontinuities[0].reference_fill_source_ids == ("zone:0:copper:B.Cu",)
    assert hole.discontinuities[0].location_x.fraction() == 4
    assert hole.scope_exclusions == (
        "impedance",
        "current",
        "ir_drop",
        "common_impedance",
        "board_mutation",
    )
    assert hole.board_mutation_performed is False


def test_missing_fill_and_diagonal_fail_closed_without_endpoint_sampling() -> None:
    _layout, _policy, _graph_fill, declaration = _fixture()
    missing = evaluate_return_adjacency(declaration)
    assert missing.findings[-1].disposition is SemanticDisposition.UNVERIFIED
    assert missing.segment_evidence[0].relation == "partial_overlap"

    layout, policy, graph_fill, diagonal = _fixture(diagonal=True)
    result = evaluate_return_adjacency(diagonal, (_reference_fill(layout, policy, graph_fill),))
    assert result.findings[-1].disposition is SemanticDisposition.UNVERIFIED
    assert result.segment_evidence[0].relation == "unsupported"


def test_graph_fill_geometry_cannot_be_replaced_and_end_caps_are_conservative() -> None:
    layout, policy, graph_fill, declaration = _fixture()
    forged = _reference_fill(layout, policy, graph_fill, forged=True)
    with pytest.raises(ValueError, match="differs from replayed graph final fill"):
        evaluate_return_adjacency(declaration, (forged,))

    tight_layout, tight_policy, tight_graph_fill, tight_declaration = _fixture(fill_kind="tight")
    end_cap = evaluate_return_adjacency(
        tight_declaration,
        (_reference_fill(tight_layout, tight_policy, tight_graph_fill, fill_kind="tight"),),
    )
    assert end_cap.segment_evidence[0].relation == "partial_overlap"
    assert end_cap.findings[-1].disposition is SemanticDisposition.UNVERIFIED


def test_one_graph_fill_source_cannot_be_aliased_as_multiple_reference_fills() -> None:
    layout, policy, graph_fill, declaration = _fixture()
    fill = _reference_fill(layout, policy, graph_fill)
    alias = fill.model_copy(update={"reference_fill_id": "reference:alias"})
    with pytest.raises(ValueError, match="zone sources must be unique"):
        evaluate_return_adjacency(declaration, (fill, alias))


def test_unknown_adjacency_model_is_rejected() -> None:
    _layout, _policy, _graph_fill, declaration = _fixture()
    payload = declaration.model_dump(mode="python")
    payload["adjacency_model_id"] = "model:caller-invented-hard-pass"
    with pytest.raises(ValidationError, match="unknown return-adjacency model"):
        ReturnPathDeclaration(**payload)


def test_advisory_model_ids_are_distinct_and_never_hard_fail() -> None:
    assert len({ADVISORY_3W_MODEL_ID, ADVISORY_3H_MODEL_ID, ADVISORY_ONE_TRACE_WIDTH_MODEL_ID}) == 3
    layout, policy, graph_fill, declaration = _fixture(fill_kind="slot")
    for model_id in (
        ADVISORY_3W_MODEL_ID,
        ADVISORY_3H_MODEL_ID,
        ADVISORY_ONE_TRACE_WIDTH_MODEL_ID,
    ):
        advisory = declaration.model_copy(update={"adjacency_model_id": model_id})
        result = evaluate_return_adjacency(
            advisory, (_reference_fill(layout, policy, graph_fill, fill_kind="slot"),)
        )
        assert result.findings[-1].disposition is SemanticDisposition.ADVISORY


def _hard_binding(context: str, binding_id: str) -> EvidenceApplicabilityBinding:
    return EvidenceApplicabilityBinding(
        binding_id=binding_id,
        evidence=(
            EvidenceRef(
                kind="datasheet",
                title="Qualified hard return threshold",
                locator="section 2",
                local_sha256="d" * 64,
                source_status="pinned",
                locator_status="text_verified",
                applicability_status="confirmed",
            ),
        ),
        claim_id=f"claim:{binding_id}",
        applicability_record_id=f"applicability:{binding_id}",
        required_conditions=("return-model=fixture",),
        matched_conditions=("return-model=fixture",),
        geometry_source_fingerprint=context,
        reviewer_record_id=f"review:{binding_id}",
    )


def test_hard_discontinuity_threshold_is_context_pinned_and_exact() -> None:
    layout, policy, graph_fill, declaration = _fixture(fill_kind="far")
    context = return_requirement_context_fingerprint(
        declaration_id=declaration.declaration_id,
        graph=declaration.graph,
        signal_net_names=declaration.signal_net_names,
        signal_class=declaration.signal_class,
        exact_net_class_id=declaration.exact_net_class_id,
        reference_net_name=declaration.reference_net_name,
        layer_pairs=declaration.layer_pairs,
        legs=declaration.legs,
        adjacency_model_id=declaration.adjacency_model_id,
        requirement_id="threshold:max-gap",
        requirement_kind="maximum_discontinuity_length_mm",
        requirement_value=Decimal("9"),
    )
    threshold = ReturnHardThreshold(
        threshold_id="threshold:max-gap",
        kind="maximum_discontinuity_length_mm",
        value_mm=Decimal("9"),
        evidence_binding=_hard_binding(context, "binding:max-gap"),
    )
    fields = declaration.model_dump(mode="python")
    fields["hard_thresholds"] = (threshold,)
    hard = ReturnPathDeclaration(**fields)
    result = evaluate_return_adjacency(
        hard, (_reference_fill(layout, policy, graph_fill, fill_kind="far"),)
    )
    threshold_finding = next(
        item for item in result.findings if item.finding_id == "finding:threshold:threshold:max-gap"
    )
    assert threshold_finding.disposition is SemanticDisposition.FAIL

    stale = threshold.model_dump(mode="python")
    stale["value_mm"] = Decimal("10")
    fields["hard_thresholds"] = (ReturnHardThreshold(**stale),)
    with pytest.raises(ValidationError, match="stale for its full context"):
        ReturnPathDeclaration(**fields)


def _transition_fixture():
    components = tuple(_component(item) for item in ("U1", "U2", "G1"))
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet(name="SIG", nodes=(("U1", "1"), ("U2", "1"))),
            BoardNet(name="GND", nodes=(("G1", "1"),)),
        ),
    )
    layout = BoardLayout(
        placements=tuple((item, float(index)) for index, item in enumerate(components)),
        segments=(
            TrackSegment(0.0, 0.0, 5.0, 0.0, "F.Cu", "SIG", 0.2),
            TrackSegment(5.0, 0.0, 10.0, 0.0, "B.Cu", "SIG", 0.2),
        ),
        vias=(ViaSpec(5.0, 0.0, "SIG"), ViaSpec(5.0, 0.0, "GND")),
        width_mm=12.0,
        height_mm=6.0,
    )
    anchors = (
        CopperTerminalAnchorBinding(
            anchor_id="start",
            physical_pad_source_id="pad:U1:1",
            component_reference="U1",
            pad_number="1",
            net_name="SIG",
            layer="F.Cu",
            x_mm="0",
            y_mm="0",
        ),
        CopperTerminalAnchorBinding(
            anchor_id="end",
            physical_pad_source_id="pad:U2:1",
            component_reference="U2",
            pad_number="1",
            net_name="SIG",
            layer="B.Cu",
            x_mm="10",
            y_mm="0",
        ),
    )
    graph = build_routed_copper_graph(layout, netlist, anchors)
    path = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:transition",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="SIG",
            start_anchor_id="start",
            end_anchor_id="end",
            ordered_edge_ids=None,
        ),
    )
    legs = (
        ReturnPathLeg(leg_id="leg:transition", signal_net_name="SIG", complete_selected_path=path),
    )
    pairs = (
        ReturnLayerPair(signal_layer="F.Cu", reference_layer="B.Cu"),
        ReturnLayerPair(signal_layer="B.Cu", reference_layer="F.Cu"),
    )
    context = return_requirement_context_fingerprint(
        declaration_id="return:transition",
        graph=graph,
        signal_net_names=("SIG",),
        signal_class=ReturnSignalClass.CLOCK,
        exact_net_class_id="netclass:clock",
        reference_net_name="GND",
        layer_pairs=pairs,
        legs=legs,
        adjacency_model_id=EXACT_CONTAINMENT_MODEL_ID,
        requirement_id="requirement:stitch",
        requirement_kind="transition_stitch_maximum_distance_mm",
        requirement_value=Decimal("1"),
    )
    binding = EvidenceApplicabilityBinding(
        binding_id="binding:stitch",
        evidence=(
            EvidenceRef(
                kind="datasheet",
                title="Qualified transition fixture",
                locator="section 1",
                local_sha256="c" * 64,
                source_status="pinned",
                locator_status="text_verified",
                applicability_status="confirmed",
            ),
        ),
        claim_id="claim:stitch",
        applicability_record_id="applicability:stitch",
        required_conditions=("return-model=fixture",),
        matched_conditions=("return-model=fixture",),
        geometry_source_fingerprint=context,
        reviewer_record_id="review:stitch",
    )
    declaration = ReturnPathDeclaration(
        declaration_id="return:transition",
        graph=graph,
        board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
        signal_net_names=("SIG",),
        signal_class="clock",
        exact_net_class_id="netclass:clock",
        reference_net_name="GND",
        layer_pairs=pairs,
        legs=legs,
        adjacency_model_id=EXACT_CONTAINMENT_MODEL_ID,
        transition_stitch_requirement=TransitionStitchRequirement(
            requirement_id="requirement:stitch",
            maximum_distance_mm=Decimal("1"),
            evidence_binding=binding,
        ),
    )
    signal_via = next(item for item in graph.edges if item.kind == "via" and item.net_name == "SIG")
    reference_via = next(
        item for item in graph.edges if item.kind == "via" and item.net_name == "GND"
    )
    stitch = ReferenceStitchEvidence.build(
        stitch_evidence_id="stitch:gnd",
        source_id=reference_via.source_id,
        source_kind="reference_via",
        reference_net_name="GND",
        reference_layers=("F.Cu", "B.Cu"),
        x_mm=Decimal("5"),
        y_mm=Decimal("0"),
    )
    selection = TransitionStitchSelection(
        signal_transition_source_id=signal_via.source_id,
        stitch_evidence_id=stitch.stitch_evidence_id,
    )
    return declaration, stitch, selection


def test_unstitched_transition_fires_independently_and_explicit_stitch_passes() -> None:
    declaration, stitch, selection = _transition_fixture()
    missing = evaluate_return_adjacency(declaration)
    assert missing.transitions[0].stitch_state == "unstitched"
    assert any(
        item.kind == "transition_stitch" and item.disposition is SemanticDisposition.FAIL
        for item in missing.findings
    )

    passing = evaluate_return_adjacency(declaration, (), (stitch,), (selection,))
    assert passing.transitions[0].stitch_state == "stitched"
    assert not any(item.kind == "transition_stitch" for item in passing.findings)


def test_transition_selections_are_exhaustively_graph_and_leg_bound() -> None:
    declaration, stitch, selection = _transition_fixture()
    without_requirement_fields = declaration.model_dump(mode="python")
    without_requirement_fields["transition_stitch_requirement"] = None
    without_requirement = ReturnPathDeclaration(**without_requirement_fields)
    with pytest.raises(ValueError, match="require an explicit stitch requirement"):
        evaluate_return_adjacency(without_requirement, (), (stitch,), (selection,))

    dangling = TransitionStitchSelection(
        signal_transition_source_id=selection.signal_transition_source_id,
        stitch_evidence_id="stitch:absent",
    )
    with pytest.raises(ValueError, match="absent retained stitch"):
        evaluate_return_adjacency(declaration, (), (stitch,), (dangling,))

    reference_via_source = stitch.source_id
    foreign = TransitionStitchSelection(
        signal_transition_source_id=reference_via_source,
        stitch_evidence_id=stitch.stitch_evidence_id,
    )
    with pytest.raises(ValueError, match="outside declared signal legs"):
        evaluate_return_adjacency(declaration, (), (stitch,), (foreign,))

    with pytest.raises(ValidationError):
        ReferenceStitchEvidence.build(
            stitch_evidence_id="stitch:capacitor",
            source_id="capacitor:C1",
            source_kind="reference_capacitor",  # type: ignore[arg-type]
            reference_net_name="GND",
            reference_layers=("F.Cu", "B.Cu"),
            x_mm=Decimal("5"),
            y_mm=Decimal("0"),
        )


def test_replay_json_order_immutability_and_tamper_rejection() -> None:
    layout, policy, graph_fill, declaration = _fixture()
    fill = _reference_fill(layout, policy, graph_fill)
    before = (declaration.model_dump_json(), fill.model_dump_json())
    result = evaluate_return_adjacency(declaration, (fill,))
    assert before == (declaration.model_dump_json(), fill.model_dump_json())
    assert type(result).model_validate_json(result.model_dump_json()) == result

    payload = deepcopy(result.model_dump(mode="json"))
    payload["segment_evidence"][0]["state"] = "uncovered"
    with pytest.raises(ValidationError, match="stale|replay"):
        type(result).model_validate(payload)
