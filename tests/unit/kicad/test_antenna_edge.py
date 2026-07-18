"""Firing fixture 4 for exact antenna edge-overhang board-material rules."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.antenna_edge_ir import (
    AntennaEdgeOverhangDeclaration,
    AntennaEdgeOverhangResult,
    AntennaModuleSupportRegion,
    support_geometry_binding_fingerprint,
)
from pcbsmith.antenna_ir import (
    AntennaLocalRegion,
    AntennaModuleDeclaration,
    InstalledFootprintKeepoutProvenance,
    antenna_geometry_source_fingerprint,
)
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.antenna_edge import evaluate_antenna_edge_overhang
from pcbsmith.kicad.antenna_semantics import evaluate_antenna_placement
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNetlist
from pcbsmith.kicad.board_region import BoardCutoutPolygon
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon, PlanarRelation
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticResultOutcome,
    SemanticVerification,
)

SOURCE_SHA = "a" * 64
OUTLINE = ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (12.0, 20.0), (12.0, 12.0), (0.0, 12.0))
CUTOUT = BoardCutoutPolygon(points=((5.0, 4.0), (7.0, 4.0), (7.0, 6.0), (5.0, 6.0)))


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _binding(binding_id: str, claim_id: str, geometry_fp: str) -> EvidenceApplicabilityBinding:
    return EvidenceApplicabilityBinding(
        binding_id=binding_id,
        evidence=(
            EvidenceRef(
                kind="module_design_guide",
                title="Fixture antenna edge/support drawing",
                locator="figure:edge-support",
                source_id="source:fixture-edge-guide",
                organization_or_author="Fixture Vendor",
                revision="3",
                local_sha256=SOURCE_SHA,
                source_status="pinned",
                locator_status="figure_bound",
                applicability_status="confirmed",
                required_conditions=("module-revision=3",),
            ),
        ),
        claim_id=claim_id,
        applicability_record_id=f"applicability:{claim_id}",
        required_conditions=("module-revision=3",),
        excluded_conditions=(),
        matched_conditions=("module-revision=3",),
        unmatched_conditions=(),
        geometry_source_fingerprint=geometry_fp,
        reviewer_record_id="review:module:3",
    )


def _antenna_declaration(*, strategy: str = "edge_overhang") -> AntennaModuleDeclaration:
    antenna = AntennaLocalRegion(
        region_id="region:antenna",
        role="antenna",
        compound=_rect(1.0, -1.0, 3.0, 1.0),
        layers=("F.Cu",),
    )
    feed = AntennaLocalRegion(
        region_id="region:feed",
        role="feed",
        compound=_rect(0.2, -0.2, 0.8, 0.2),
        layers=("F.Cu",),
    )
    keepout = InstalledFootprintKeepoutProvenance(
        provenance_id="provenance:keepout",
        region_id="region:keepout",
        selected_footprint_library_id="RF_Module:Fixture_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:3",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding_id="binding:module-guidance",
        prohibited_object_rule_id="rule:keepout",
        compound=_rect(-2.0, -1.0, 3.0, 1.0),
        layers=("F.Cu",),
        prohibited_object_kinds=("board_material",),
    )
    geometry_fp = antenna_geometry_source_fingerprint(antenna, feed, (keepout,))
    return AntennaModuleDeclaration(
        antenna_id="antenna:U1",
        module_reference="U1",
        selected_footprint_library_id="RF_Module:Fixture_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:3",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding=_binding(
            "binding:module-guidance", "claim:module-geometry", geometry_fp
        ),
        antenna_region=antenna,
        feed_region=feed,
        keepouts=(keepout,),
        placement_strategy=strategy,
        edge_or_cutout_requirement_id="requirement:edge",
        enclosure_exclusion_requirement_id="requirement:enclosure",
        rf_validation_requirement_id="requirement:rf",
    )


def _placement(
    *,
    anchor: tuple[float, float] = (20.0, 8.0),
    rotation: float = 0.0,
    back: bool = False,
    strategy: str = "edge_overhang",
):
    component = BoardComponent(
        reference="U1",
        value="Fixture Module",
        footprint="RF_Module:Fixture_Antenna",
        uuid_path="uuid:path:U1",
        fields=(("revision", "module-revision:3"),),
    )
    layout = BoardLayout(
        placements=((component, anchor[0]),),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=20.0,
        parts_row_y_mm=anchor[1],
        part_rotation=(("U1", rotation),) if rotation else (),
        part_flip=("U1",) if back else (),
        outline=OUTLINE,
        cutouts=(CUTOUT,),
    )
    return evaluate_antenna_placement(
        layout,
        BoardNetlist(components=(component,), nets=()),
        _antenna_declaration(strategy=strategy),
    )


def _support(
    *,
    support_id: str = "support:body",
    provenance_id: str = "provenance:support:body",
    compound: ExactPlanarCompound | None = None,
    role: str = "body_support",
) -> AntennaModuleSupportRegion:
    return AntennaModuleSupportRegion(
        support_region_id=support_id,
        provenance_id=provenance_id,
        role=role,
        compound=compound or _rect(-2.0, -1.0, 0.0, 1.0),
        layers=("F.Cu", "F.Fab"),
        installed_footprint_id="RF_Module:Fixture_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:3",
        source_file_sha256=SOURCE_SHA,
        source_binding_id="binding:support-geometry",
    )


def _edge_declaration(
    placement,
    *,
    supports: tuple[AntennaModuleSupportRegion, ...] | None = None,
    required: tuple[str, ...] = ("region:antenna",),
) -> AntennaEdgeOverhangDeclaration:
    regions = supports or (_support(),)
    antenna = placement.declaration
    binding_fp = support_geometry_binding_fingerprint(antenna, regions)
    return AntennaEdgeOverhangDeclaration(
        edge_declaration_id="edge:U1",
        antenna_id=antenna.antenna_id,
        module_reference=antenna.module_reference,
        antenna_declaration_fingerprint=antenna.semantic_fingerprint(),
        source_applicability_binding_id=antenna.module_guidance_binding.binding_id,
        required_outside_region_ids=required,
        support_regions=regions,
        support_geometry_binding=_binding(
            "binding:support-geometry", "claim:support-geometry", binding_fp
        ),
        antenna_outside_rule_id="rule:antenna-strictly-outside",
        support_inside_rule_id="rule:module-support-inside",
    )


EXACT_POSES = (
    (0.0, False, (20.0, 8.0)),
    (90.0, False, (15.0, 0.0)),
    (180.0, False, (0.0, 8.0)),
    (270.0, False, (9.0, 12.0)),
    (0.0, True, (0.0, 8.0)),
    (90.0, True, (9.0, 12.0)),
    (180.0, True, (20.0, 8.0)),
    (270.0, True, (15.0, 0.0)),
)


@pytest.mark.parametrize(("rotation", "back", "anchor"), EXACT_POSES)
def test_exact_front_back_quarter_turn_overhang_and_support_pass(
    rotation: float, back: bool, anchor: tuple[float, float]
) -> None:
    placement = _placement(anchor=anchor, rotation=rotation, back=back)

    result = evaluate_antenna_edge_overhang(placement, _edge_declaration(placement))

    assert result.outside_evidence[0].material_relation is PlanarRelation.DISJOINT
    assert result.outside_evidence[0].disposition is SemanticDisposition.PASS
    assert result.support_evidence[0].contained_in_outer is True
    assert all(
        relation is PlanarRelation.DISJOINT
        for _, relation in result.support_evidence[0].cutout_relations
    )
    assert result.support_evidence[0].disposition is SemanticDisposition.PASS
    assert result.semantic_result.outcome is SemanticResultOutcome.PASSED


@pytest.mark.parametrize(
    ("anchor", "relation"),
    (((18.0, 8.0), PlanarRelation.INTERIOR_OVERLAP), ((19.0, 8.0), PlanarRelation.BOUNDARY_TOUCH)),
)
def test_antenna_partial_overlap_and_boundary_touch_fail_with_support_passing(
    anchor: tuple[float, float], relation: PlanarRelation
) -> None:
    placement = _placement(anchor=anchor)

    result = evaluate_antenna_edge_overhang(placement, _edge_declaration(placement))

    assert result.outside_evidence[0].material_relation is relation
    assert result.outside_evidence[0].disposition is SemanticDisposition.FAIL
    assert result.support_evidence[0].disposition is SemanticDisposition.PASS
    assert result.semantic_result.summary.route_acceptance_blocked


@pytest.mark.parametrize(
    ("compound", "expected_cutout_relation"),
    (
        (_rect(0.0, -1.0, 2.0, 1.0), None),
        (_rect(-15.5, -3.5, -13.5, -1.5), PlanarRelation.INTERIOR_OVERLAP),
        (_rect(-13.0, -4.0, -12.0, -2.0), PlanarRelation.BOUNDARY_TOUCH),
    ),
)
def test_support_external_overhang_cutout_intrusion_and_touch_fail_independently(
    compound: ExactPlanarCompound, expected_cutout_relation: PlanarRelation | None
) -> None:
    placement = _placement()
    declaration = _edge_declaration(placement, supports=(_support(compound=compound),))

    result = evaluate_antenna_edge_overhang(placement, declaration)

    assert result.outside_evidence[0].disposition is SemanticDisposition.PASS
    support = result.support_evidence[0]
    assert support.disposition is SemanticDisposition.FAIL
    if expected_cutout_relation is None:
        assert support.contained_in_outer is False
    else:
        assert expected_cutout_relation in {relation for _, relation in support.cutout_relations}
    assert result.semantic_result.summary.route_acceptance_blocked


def test_arbitrary_angle_makes_both_hard_rules_unverified() -> None:
    placement = _placement(rotation=17.0)

    result = evaluate_antenna_edge_overhang(placement, _edge_declaration(placement))

    assert result.outside_evidence[0].verification is SemanticVerification.BOUNDED_APPROXIMATION
    assert result.support_evidence[0].verification is SemanticVerification.BOUNDED_APPROXIMATION
    assert result.outside_evidence[0].disposition is SemanticDisposition.UNVERIFIED
    assert result.support_evidence[0].disposition is SemanticDisposition.UNVERIFIED
    assert result.semantic_result.outcome is SemanticResultOutcome.HARD_SCOPE_UNVERIFIED
    assert result.semantic_result.summary.route_acceptance_blocked


def test_concave_outline_and_cutout_build_exact_board_material() -> None:
    placement = _placement()
    result = evaluate_antenna_edge_overhang(placement, _edge_declaration(placement))
    material = result.board_material

    assert material.outer_polygon.outer == ExactPlanarPolygon(outer=OUTLINE).outer
    assert len(material.cutout_compounds) == 1
    assert material.cutout_compounds[0].polygons[0].outer == ExactPlanarPolygon(
        outer=CUTOUT.points
    ).outer
    assert material.material_compound.polygons[0].holes == (
        material.cutout_compounds[0].polygons[0].outer,
    )


def test_wrong_strategy_module_binding_and_source_identity_fail() -> None:
    cutout_strategy = _placement(strategy="baseboard_cutout")
    with pytest.raises(ValueError, match="requires edge_overhang"):
        evaluate_antenna_edge_overhang(
            cutout_strategy, _edge_declaration(cutout_strategy)
        )

    placement = _placement()
    payload = _edge_declaration(placement).model_dump(mode="json")
    payload["module_reference"] = "U404"
    with pytest.raises(ValueError, match="another antenna declaration"):
        evaluate_antenna_edge_overhang(
            placement, AntennaEdgeOverhangDeclaration.model_validate(payload)
        )
    payload = _edge_declaration(placement).model_dump(mode="json")
    payload["source_applicability_binding_id"] = "binding:stale"
    with pytest.raises(ValueError, match="another antenna declaration"):
        evaluate_antenna_edge_overhang(
            placement, AntennaEdgeOverhangDeclaration.model_validate(payload)
        )
    payload = _edge_declaration(placement).model_dump(mode="json")
    payload["support_regions"][0]["source_file_sha256"] = "d" * 64
    with pytest.raises(ValidationError):
        AntennaEdgeOverhangDeclaration.model_validate(payload)


def test_wrong_antenna_or_support_binding_fingerprint_fails() -> None:
    placement = _placement()
    payload = _edge_declaration(placement).model_dump(mode="json")
    payload["antenna_declaration_fingerprint"] = "d" * 64
    with pytest.raises(ValidationError, match="support geometry binding fingerprint is stale"):
        AntennaEdgeOverhangDeclaration.model_validate(payload)

    payload = _edge_declaration(placement).model_dump(mode="json")
    payload["support_geometry_binding"]["geometry_source_fingerprint"] = "d" * 64
    with pytest.raises(ValidationError, match="support geometry binding fingerprint is stale"):
        AntennaEdgeOverhangDeclaration.model_validate(payload)


def test_missing_duplicate_required_support_and_provenance_fail() -> None:
    placement = _placement()
    payload = _edge_declaration(placement).model_dump(mode="json")
    payload["required_outside_region_ids"] = []
    with pytest.raises(ValidationError):
        AntennaEdgeOverhangDeclaration.model_validate(payload)
    payload = _edge_declaration(placement).model_dump(mode="json")
    payload["required_outside_region_ids"] = ["region:antenna", "region:antenna"]
    with pytest.raises(ValidationError, match="unique identities"):
        AntennaEdgeOverhangDeclaration.model_validate(payload)
    unknown = _edge_declaration(placement, required=("region:unknown",))
    with pytest.raises(ValueError, match="omits or invents"):
        evaluate_antenna_edge_overhang(placement, unknown)

    second = _support(support_id="support:pads", provenance_id="provenance:support:pads")
    for field, value, match in (
        ("support_region_id", "support:body", "region identities"),
        ("provenance_id", "provenance:support:body", "provenance identities"),
    ):
        duplicate = second.model_copy(update={field: value})
        supports = (_support(), duplicate)
        antenna = placement.declaration
        binding = _binding(
            "binding:support-geometry",
            "claim:support-geometry",
            support_geometry_binding_fingerprint(antenna, supports),
        )
        payload = _edge_declaration(placement).model_dump(mode="json")
        payload["support_regions"] = [item.model_dump(mode="json") for item in supports]
        payload["support_geometry_binding"] = binding.model_dump(mode="json")
        with pytest.raises(ValidationError, match=match):
            AntennaEdgeOverhangDeclaration.model_validate(payload)


def test_no_component_reference_exemption_input_exists() -> None:
    assert "component_reference_exemption" not in AntennaEdgeOverhangDeclaration.model_fields
    assert "body_edge_exception" not in AntennaEdgeOverhangDeclaration.model_fields


def test_replay_rejects_material_snapshot_evidence_finding_message_and_fingerprint_tamper() -> None:
    placement = _placement()
    result = evaluate_antenna_edge_overhang(placement, _edge_declaration(placement))
    mutations = []

    material = deepcopy(result.model_dump(mode="json"))
    material["board_material"]["outer_polygon"]["outer"][0][0] -= 0.1
    mutations.append(material)
    cutout = deepcopy(result.model_dump(mode="json"))
    cutout["board_material"]["cutout_compounds"][0]["polygons"][0]["outer"][0][0] -= 0.1
    mutations.append(cutout)
    outside = deepcopy(result.model_dump(mode="json"))
    outside["outside_evidence"][0]["disposition"] = "fail"
    mutations.append(outside)
    support = deepcopy(result.model_dump(mode="json"))
    support["support_evidence"][0]["disposition"] = "fail"
    mutations.append(support)
    finding = deepcopy(result.model_dump(mode="json"))
    finding["semantic_result"]["findings"][0]["disposition"] = "fail"
    mutations.append(finding)
    message = deepcopy(result.model_dump(mode="json"))
    message["semantic_result"]["findings"][0]["message"] = "Changed message."
    mutations.append(message)
    stale_fp = deepcopy(result.model_dump(mode="json"))
    stale_fp["result_fingerprint"] = "d" * 64
    mutations.append(stale_fp)

    for payload in mutations:
        with pytest.raises(ValidationError):
            AntennaEdgeOverhangResult.model_validate(payload)

    snapshot = deepcopy(result.model_dump(mode="json"))
    snapshot["placement_result"]["board_layout_snapshot_fingerprint"] = "d" * 64
    with pytest.raises(ValidationError):
        AntennaEdgeOverhangResult.model_validate(snapshot)


def test_support_reversal_repeat_and_json_are_deterministic() -> None:
    placement = _placement()
    first_support = _support()
    second_support = _support(
        support_id="support:pads",
        provenance_id="provenance:support:pads",
        compound=_rect(-1.5, -0.5, -0.5, 0.5),
        role="pad_support",
    )
    first = evaluate_antenna_edge_overhang(
        placement, _edge_declaration(placement, supports=(first_support, second_support))
    )
    reversed_result = evaluate_antenna_edge_overhang(
        placement, _edge_declaration(placement, supports=(second_support, first_support))
    )
    repeated = evaluate_antenna_edge_overhang(
        placement, _edge_declaration(placement, supports=(first_support, second_support))
    )

    assert first == reversed_result == repeated
    assert AntennaEdgeOverhangResult.model_validate_json(first.model_dump_json()) == first
