"""R6.4 firing fixtures for replay-bound oscillator zones."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.antenna_clearance_ir import QualifiedExactZoneFillProvenance
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.oscillator_zone import evaluate_oscillator_zone
from pcbsmith.oscillator_zone_ir import (
    ExactNetClassMembership,
    IoSeparationRequirement,
    OscillatorPhysicalObject,
    OscillatorUnsupportedReason,
    OscillatorZoneDeclaration,
    OscillatorZoneResult,
    ReferenceGroundCoverageProof,
    ReferenceGroundRequirement,
    StitchViaRequirement,
    StrayCapacitanceRequirement,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticQuantity,
    SemanticRegion,
    SemanticResultOutcome,
    SemanticVerification,
)
from pcbsmith.sensor_copper_removal_ir import ExactFilledZoneReaderPolicy


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _board() -> tuple[BoardLayout, BoardNetlist]:
    refs = ("U1", "Y1", "C1", "C2", "U9", "J1")
    components = tuple(
        BoardComponent(
            reference=ref,
            value="fixture",
            footprint="Fixture:Part",
            uuid_path=f"uuid:{ref}",
        )
        for ref in refs
    )
    return (
        BoardLayout(
            placements=tuple(
                (component, float(index + 1)) for index, component in enumerate(components)
            ),
            segments=(),
            vias=(),
            width_mm=30.0,
            height_mm=20.0,
        ),
        BoardNetlist(
            components=components,
            nets=(
                BoardNet(name="XIN", nodes=(("U1", "1"), ("Y1", "1"))),
                BoardNet(name="XOUT", nodes=(("U1", "2"), ("Y1", "2"))),
                BoardNet(name="GND", nodes=(("C1", "2"), ("C2", "2"))),
                BoardNet(name="SW", nodes=(("U9", "1"),)),
                BoardNet(name="IO", nodes=(("J1", "1"),)),
            ),
        ),
    )


def _binding() -> EvidenceApplicabilityBinding:
    return EvidenceApplicabilityBinding(
        binding_id="binding:fixture",
        evidence=(
            EvidenceRef(
                kind="component_datasheet",
                title="Oscillator layout fixture",
                locator="layout:1",
                source_id="source:fixture",
                organization_or_author="Fixture Vendor",
                revision="1",
                local_sha256="a" * 64,
                source_status="pinned",
                locator_status="text_verified",
                applicability_status="confirmed",
                required_conditions=("oscillator-revision=1",),
            ),
        ),
        claim_id="claim:oscillator-zone",
        applicability_record_id="applicability:fixture",
        required_conditions=("oscillator-revision=1",),
        excluded_conditions=(),
        matched_conditions=("oscillator-revision=1",),
        unmatched_conditions=(),
        geometry_source_fingerprint=_rect(10, 10, 14, 14).semantic_fingerprint(),
        reviewer_record_id="review:fixture",
    )


def _region(
    region_id: str = "zone:osc", geometry: ExactPlanarCompound | None = None
) -> SemanticRegion:
    return SemanticRegion(
        region_id=region_id,
        coordinate_space="board",
        owner_reference=None,
        compound=geometry or _rect(10, 10, 14, 14),
        layers=("F.Cu", "B.Cu"),
        verification=SemanticVerification.EXACT,
        maximum_error_mm=None,
        source_binding_ids=("binding:fixture",),
    )


def _declaration(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    external: bool = True,
    ground: bool = False,
    stitch: bool = False,
    capacitance: bool = False,
    io_authority: SemanticAuthorityClass | None = None,
) -> OscillatorZoneDeclaration:
    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    netlist_fp = board_netlist_snapshot_fingerprint(netlist_json)
    ground_requirement = (
        ReferenceGroundRequirement(
            requirement_id="requirement:ground",
            rule_id="rule:ground",
            ground_net_name="GND",
            required_layers=("F.Cu",),
            minimum_coverage_basis_points=9000,
            authority=SemanticAuthorityClass.HARD_GEOMETRY,
            source_binding_ids=("binding:fixture",),
        )
        if ground
        else None
    )
    stitch_requirement = (
        StitchViaRequirement(
            requirement_id="requirement:stitch",
            count_rule_id="rule:stitch-count",
            placement_rule_id="rule:stitch-placement",
            ground_net_name="GND",
            minimum_count=2,
            required_layers=("F.Cu", "B.Cu"),
            authority=SemanticAuthorityClass.HARD_GEOMETRY,
            source_binding_ids=("binding:fixture",),
        )
        if stitch
        else None
    )
    io_requirement = (
        IoSeparationRequirement(
            requirement_id="requirement:io",
            rule_id="rule:io",
            io_region=_region("zone:io", _rect(15, 10, 16, 11)),
            minimum_separation=SemanticQuantity(
                quantity_id="quantity:io",
                value=5.0,
                unit="mm",
                source_binding_ids=("binding:fixture",),
            ),
            authority=io_authority,
        )
        if io_authority is not None
        else None
    )
    cap_requirement = (
        StrayCapacitanceRequirement(
            requirement_id="requirement:cap",
            rule_id="rule:cap",
            maximum_capacitance=SemanticQuantity(
                quantity_id="quantity:cap",
                value=0.5,
                unit="pF",
                source_binding_ids=("binding:fixture",),
            ),
            authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        )
        if capacitance
        else None
    )
    return OscillatorZoneDeclaration(
        declaration_id="declaration:oscillator",
        board_layout_snapshot_json=layout_json,
        board_netlist_snapshot_json=netlist_json,
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(layout_json),
        board_netlist_snapshot_fingerprint=netlist_fp,
        has_external_discrete_zone=external,
        zone_id="zone:osc",
        zone_region=_region() if external else None,
        oscillator_reference="U1",
        crystal_reference="Y1" if external else None,
        load_capacitor_references=("C1", "C2") if external else (),
        oscillator_net_names=("XIN", "XOUT") if external else (),
        allowed_object_ids=(),
        allowed_component_refs=("U1", "Y1", "C1", "C2") if external else (),
        allowed_net_names=(),
        forbidden_net_class_ids=("class:switching",) if external else (),
        net_class_memberships=(
            ExactNetClassMembership(
                net_class_id="class:switching",
                net_names=("SW",),
                board_netlist_snapshot_fingerprint=netlist_fp,
                source_binding_ids=("binding:fixture",),
            ),
        )
        if external
        else (),
        intrusion_rule_id="rule:intrusion",
        applicability_rule_id="rule:applicability",
        reference_ground_requirement=ground_requirement,
        stitch_via_requirement=stitch_requirement,
        io_separation_requirement=io_requirement,
        stray_capacitance_requirement=cap_requirement,
        evidence_bindings=(_binding(),),
    )


def _object(
    declaration: OscillatorZoneDeclaration,
    object_id: str,
    *,
    kind: str = "copper",
    net: str = "SW",
    component: str | None = "U9",
    geometry: ExactPlanarCompound | None = None,
    layers: tuple[str, ...] = ("F.Cu",),
    unsupported: OscillatorUnsupportedReason | None = None,
) -> OscillatorPhysicalObject:
    is_zone = kind == "filled_zone"
    exact = None if unsupported else geometry or _rect(11, 11, 12, 12)
    source_id = f"source:{object_id}"
    fill_provenance = None
    if is_zone and unsupported is None:
        assert exact is not None
        policy = ExactFilledZoneReaderPolicy(
            policy_id="policy:oscillator-fixture",
            reader_id="reader:oscillator-fixture",
            reader_version="1",
            project_qualification_record_id="qualification:oscillator-fixture",
            project_qualification_artifact_sha256="b" * 64,
            reviewer_record_id="review:fill",
            status="active",
        )
        fill_provenance = QualifiedExactZoneFillProvenance.build(
            fill_provenance_id=f"fill:{object_id}",
            zone_source_provenance_id=source_id,
            board_layout_snapshot_fingerprint=(declaration.board_layout_snapshot_fingerprint),
            exact_geometry_fingerprint=exact.semantic_fingerprint(),
            reader_id=policy.reader_id,
            reader_version=policy.reader_version,
            reader_policy=policy,
            source_artifact_id=f"artifact:{object_id}",
            source_artifact_sha256="c" * 64,
        )
    return OscillatorPhysicalObject(
        object_id=object_id,
        kind=kind,
        source_id=source_id,
        layers=layers,
        owner_component_ref=component,
        owner_net_name=net,
        board_layout_snapshot_fingerprint=declaration.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=declaration.board_netlist_snapshot_fingerprint,
        source_representation=(
            "zone_intent"
            if unsupported and is_zone
            else "exact_final_fill"
            if is_zone
            else "physical_geometry"
        ),
        verification=(
            SemanticVerification.UNSUPPORTED if unsupported else SemanticVerification.EXACT
        ),
        compound=exact,
        unsupported_reason=unsupported,
        exact_final_fill_provenance=fill_provenance,
    )


def _proof(
    declaration: OscillatorZoneDeclaration,
    ground: OscillatorPhysicalObject,
    predicate: str,
) -> ReferenceGroundCoverageProof:
    assert declaration.zone_region is not None and declaration.zone_region.compound is not None
    assert ground.compound is not None
    return ReferenceGroundCoverageProof(
        proof_id="proof:ground:F.Cu",
        calculation_id="calculation:exact-polygon-coverage",
        ground_object_id=ground.object_id,
        ground_source_id=ground.source_id,
        layer="F.Cu",
        zone_geometry_fingerprint=declaration.zone_region.compound.semantic_fingerprint(),
        ground_geometry_fingerprint=ground.compound.semantic_fingerprint(),
        predicate=predicate,
        source_binding_ids=("binding:fixture",),
    )


def test_foreign_switching_copper_fires_while_local_objects_are_exempt() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, ground=True)
    objects = (
        _object(declaration, "object:foreign"),
        _object(declaration, "object:osc", net="XIN", component="Y1"),
        _object(declaration, "object:ground", net="GND", component=None),
    )

    result = evaluate_oscillator_zone(layout, netlist, declaration, objects)

    evidence = {item.object_id: item for item in result.intrusion_evidence}
    assert evidence["object:foreign"].disposition is SemanticDisposition.FAIL
    assert evidence["object:foreign"].forbidden_net_class_ids == ("class:switching",)
    assert evidence["object:osc"].exemption == "component"
    assert evidence["object:ground"].exemption == "local_ground"
    assert evidence["object:osc"].disposition is SemanticDisposition.NOT_APPLICABLE
    assert result.semantic_result.outcome is SemanticResultOutcome.HARD_REJECTED


def test_reference_ground_and_stitch_count_and_placement_fire_independently() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, ground=True, stitch=True)
    ground = _object(
        declaration,
        "object:fill",
        kind="filled_zone",
        net="GND",
        component=None,
        geometry=_rect(20, 16, 21, 17),
    )
    vias = (
        _object(
            declaration,
            "object:via:1",
            kind="via",
            net="GND",
            component=None,
            layers=("F.Cu", "B.Cu"),
        ),
        _object(
            declaration,
            "object:via:2",
            kind="via",
            net="GND",
            component=None,
            layers=("F.Cu", "B.Cu"),
        ),
    )

    low_ground = evaluate_oscillator_zone(
        layout,
        netlist,
        declaration,
        (ground, *vias),
        (_proof(declaration, ground, "exact_sets_disjoint"),),
    )
    low_by_kind = {item.finding_kind: item for item in low_ground.requirement_evidence}
    assert low_by_kind["reference_ground"].disposition is SemanticDisposition.FAIL
    assert low_by_kind["stitch_count"].disposition is SemanticDisposition.PASS
    assert low_by_kind["stitch_placement"].disposition is SemanticDisposition.PASS

    far_via = _object(
        declaration,
        "object:via:far",
        kind="via",
        net="GND",
        component=None,
        geometry=_rect(20, 16, 20.2, 16.2),
        layers=("F.Cu", "B.Cu"),
    )
    full_ground = _object(
        declaration,
        "object:full-fill",
        kind="filled_zone",
        net="GND",
        component=None,
        geometry=_rect(9, 9, 15, 15),
    )
    one_near_one_far = evaluate_oscillator_zone(
        layout,
        netlist,
        declaration,
        (full_ground, vias[0], far_via),
        (_proof(declaration, full_ground, "zone_inside_single_fill_polygon"),),
    )
    separated = {item.finding_kind: item for item in one_near_one_far.requirement_evidence}
    assert separated["reference_ground"].disposition is SemanticDisposition.PASS
    assert separated["stitch_count"].disposition is SemanticDisposition.PASS
    assert separated["stitch_placement"].disposition is SemanticDisposition.FAIL
    assert separated["stitch_placement"].source_ids == (
        "source:object:via:1",
        "source:object:via:far",
    )


def test_unknown_fill_and_missing_capacitance_model_are_unverified() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, ground=True, capacitance=True)
    zone_intent = _object(
        declaration,
        "object:rectangle-zone",
        kind="filled_zone",
        net="GND",
        component=None,
        unsupported=OscillatorUnsupportedReason.RECTANGLE_ONLY_ZONE,
    )

    result = evaluate_oscillator_zone(layout, netlist, declaration, (zone_intent,))
    findings = {item.finding_kind: item for item in result.requirement_evidence}

    assert findings["reference_ground"].disposition is SemanticDisposition.UNVERIFIED
    assert findings["reference_ground"].verification is SemanticVerification.UNSUPPORTED
    assert findings["stray_capacitance"].disposition is SemanticDisposition.UNVERIFIED
    assert findings["stray_capacitance"].measured_value is None


def test_forged_coverage_and_unqualified_final_fill_are_rejected() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, ground=True)
    partial = _object(
        declaration,
        "object:partial-fill",
        kind="filled_zone",
        net="GND",
        component=None,
        geometry=_rect(11, 11, 12, 12),
    )

    partial_result = evaluate_oscillator_zone(layout, netlist, declaration, (partial,))
    assert partial_result.requirement_evidence[0].disposition is SemanticDisposition.UNVERIFIED
    with pytest.raises(ValueError, match="forged/stale predicate"):
        evaluate_oscillator_zone(
            layout,
            netlist,
            declaration,
            (partial,),
            (_proof(declaration, partial, "zone_inside_single_fill_polygon"),),
        )

    payload = partial.model_dump(mode="json")
    payload["exact_final_fill_provenance"] = None
    with pytest.raises(ValidationError, match="requires active reader"):
        OscillatorPhysicalObject.model_validate(payload)


def test_scoped_advisory_io_separation_cannot_hard_fail() -> None:
    layout, netlist = _board()
    declaration = _declaration(
        layout, netlist, io_authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS
    )

    result = evaluate_oscillator_zone(layout, netlist, declaration, ())

    io = result.requirement_evidence[0]
    assert io.finding_kind == "io_separation"
    assert io.measured_value == 1.0
    assert io.disposition is SemanticDisposition.ADVISORY
    assert not result.semantic_result.summary.route_acceptance_blocked


def test_internal_module_oscillator_is_typed_not_applicable_with_empty_evidence() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, external=False)

    result = evaluate_oscillator_zone(layout, netlist, declaration, ())

    assert result.intrusion_evidence == ()
    assert result.requirement_evidence == ()
    assert result.semantic_result.outcome is SemanticResultOutcome.NOT_APPLICABLE
    assert result.semantic_result.findings[0].disposition is SemanticDisposition.NOT_APPLICABLE
    with pytest.raises(ValueError, match="requires empty physical evidence"):
        evaluate_oscillator_zone(
            layout, netlist, declaration, (_object(declaration, "object:invented"),)
        )


def test_stale_snapshot_owner_net_class_and_evidence_are_rejected() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist)
    stale_layout = deepcopy(declaration.model_dump(mode="json"))
    stale_layout["board_layout_snapshot_fingerprint"] = "f" * 64
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        OscillatorZoneDeclaration.model_validate(stale_layout)

    unknown_binding = deepcopy(declaration.model_dump(mode="json"))
    unknown_binding["net_class_memberships"][0]["source_binding_ids"] = ["binding:stale"]
    with pytest.raises(ValidationError, match="unknown evidence"):
        OscillatorZoneDeclaration.model_validate(unknown_binding)

    bad_class = deepcopy(declaration.model_dump(mode="json"))
    bad_class["net_class_memberships"][0]["net_names"] = ["UNKNOWN"]
    with pytest.raises(ValidationError, match="net absent"):
        OscillatorZoneDeclaration.model_validate(bad_class)

    hard_io = _declaration(
        layout, netlist, io_authority=SemanticAuthorityClass.HARD_GEOMETRY
    ).model_dump(mode="json")
    hard_io["evidence_bindings"][0]["evidence"][0]["source_status"] = "unpinned"
    with pytest.raises(ValidationError, match="pinned applicable reviewed evidence"):
        OscillatorZoneDeclaration.model_validate(hard_io)

    unscoped_hard_io = _declaration(
        layout, netlist, io_authority=SemanticAuthorityClass.HARD_GEOMETRY
    ).model_dump(mode="json")
    unscoped_hard_io["evidence_bindings"][0]["required_conditions"] = []
    unscoped_hard_io["evidence_bindings"][0]["matched_conditions"] = []
    with pytest.raises(ValidationError, match="pinned applicable reviewed evidence"):
        OscillatorZoneDeclaration.model_validate(unscoped_hard_io)

    owner = _object(declaration, "object:owner").model_dump(mode="json")
    owner["owner_component_ref"] = "U404"
    with pytest.raises(ValueError, match="owner component is absent"):
        evaluate_oscillator_zone(
            layout, netlist, declaration, (OscillatorPhysicalObject.model_validate(owner),)
        )


def test_replay_json_reversal_tamper_and_caller_immutability() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist)
    first = _object(declaration, "object:a", geometry=_rect(20, 16, 21, 17))
    second = _object(declaration, "object:b")
    layout_before = canonical_board_layout_snapshot_json(layout)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)

    result = evaluate_oscillator_zone(layout, netlist, declaration, (first, second))
    reversed_result = evaluate_oscillator_zone(layout, netlist, declaration, (second, first))

    assert result == reversed_result
    assert OscillatorZoneResult.model_validate_json(result.model_dump_json()) == result
    assert canonical_board_layout_snapshot_json(layout) == layout_before
    assert canonical_board_netlist_snapshot_json(netlist) == netlist_before

    payload = deepcopy(result.model_dump(mode="json"))
    payload["intrusion_evidence"][0]["disposition"] = "fail"
    with pytest.raises(ValidationError):
        OscillatorZoneResult.model_validate(payload)

    payload = deepcopy(result.model_dump(mode="json"))
    payload["semantic_result"]["findings"][0]["message"] = "tampered"
    with pytest.raises(ValidationError):
        OscillatorZoneResult.model_validate(payload)

    payload = deepcopy(result.model_dump(mode="json"))
    payload["result_fingerprint"] = "e" * 64
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        OscillatorZoneResult.model_validate(payload)

    changed_layout = BoardLayout(
        placements=layout.placements,
        segments=layout.segments,
        vias=layout.vias,
        width_mm=31.0,
        height_mm=layout.height_mm,
    )
    with pytest.raises(ValueError, match="differs from the declaration snapshot"):
        evaluate_oscillator_zone(changed_layout, netlist, declaration, ())
