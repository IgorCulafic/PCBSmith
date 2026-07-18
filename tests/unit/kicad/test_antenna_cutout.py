"""Firing fixture 5 for exact selected antenna-cutout geometry rules."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.antenna_cutout_ir import (
    AntennaCutoutDeclaration,
    AntennaCutoutResult,
    build_selected_board_cutout,
    support_binding_for_declaration,
)
from pcbsmith.antenna_edge_ir import AntennaModuleSupportRegion
from pcbsmith.antenna_ir import (
    AntennaLocalRegion,
    AntennaModuleDeclaration,
    InstalledFootprintKeepoutProvenance,
    antenna_geometry_source_fingerprint,
)
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.antenna_cutout import evaluate_antenna_cutout
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
OUTLINE = (
    (0.0, 0.0),
    (30.0, 0.0),
    (30.0, 30.0),
    (18.0, 30.0),
    (18.0, 24.0),
    (0.0, 24.0),
)
TARGET_CUTOUT = BoardCutoutPolygon(points=((10.0, 8.0), (14.0, 8.0), (14.0, 12.0), (10.0, 12.0)))
OTHER_CUTOUT = BoardCutoutPolygon(points=((20.0, 14.0), (23.0, 14.0), (23.0, 17.0), (20.0, 17.0)))


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
                title="Fixture antenna cutout/support drawing",
                locator="figure:cutout-support",
                source_id="source:fixture-cutout-guide",
                organization_or_author="Fixture Vendor",
                revision="4",
                local_sha256=SOURCE_SHA,
                source_status="pinned",
                locator_status="figure_bound",
                applicability_status="confirmed",
                required_conditions=("module-revision=4",),
            ),
        ),
        claim_id=claim_id,
        applicability_record_id=f"applicability:{claim_id}",
        required_conditions=("module-revision=4",),
        excluded_conditions=(),
        matched_conditions=("module-revision=4",),
        unmatched_conditions=(),
        geometry_source_fingerprint=geometry_fp,
        reviewer_record_id="review:module:4",
    )


def _antenna_declaration(*, strategy: str = "baseboard_cutout") -> AntennaModuleDeclaration:
    antenna = AntennaLocalRegion(
        region_id="region:antenna",
        role="antenna",
        compound=_rect(-1.0, -1.0, 1.0, 1.0),
        layers=("F.Cu",),
    )
    feed = AntennaLocalRegion(
        region_id="region:feed",
        role="feed",
        compound=_rect(-0.2, -0.2, 0.2, 0.2),
        layers=("F.Cu",),
    )
    keepout = InstalledFootprintKeepoutProvenance(
        provenance_id="provenance:keepout",
        region_id="region:keepout",
        selected_footprint_library_id="RF_Module:Fixture_Cutout_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:4",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding_id="binding:module-guidance",
        prohibited_object_rule_id="rule:keepout",
        compound=_rect(-1.5, -1.5, 1.5, 1.5),
        layers=("F.Cu",),
        prohibited_object_kinds=("board_material",),
    )
    geometry_fp = antenna_geometry_source_fingerprint(antenna, feed, (keepout,))
    return AntennaModuleDeclaration(
        antenna_id="antenna:U1",
        module_reference="U1",
        selected_footprint_library_id="RF_Module:Fixture_Cutout_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:4",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding=_binding(
            "binding:module-guidance", "claim:module-geometry", geometry_fp
        ),
        antenna_region=antenna,
        feed_region=feed,
        keepouts=(keepout,),
        placement_strategy=strategy,
        edge_or_cutout_requirement_id="requirement:cutout",
        enclosure_exclusion_requirement_id="requirement:enclosure",
        rf_validation_requirement_id="requirement:rf",
    )


def _placement(
    *,
    anchor: tuple[float, float] = (12.0, 10.0),
    rotation: float = 0.0,
    back: bool = False,
    strategy: str = "baseboard_cutout",
    cutouts: tuple[BoardCutoutPolygon, ...] = (OTHER_CUTOUT, TARGET_CUTOUT),
):
    component = BoardComponent(
        reference="U1",
        value="Fixture Cutout Module",
        footprint="RF_Module:Fixture_Cutout_Antenna",
        uuid_path="uuid:path:U1",
        fields=(("revision", "module-revision:4"),),
    )
    layout = BoardLayout(
        placements=((component, anchor[0]),),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=30.0,
        parts_row_y_mm=anchor[1],
        part_rotation=(("U1", rotation),) if rotation else (),
        part_flip=("U1",) if back else (),
        outline=OUTLINE,
        cutouts=cutouts,
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
        compound=compound or _rect(-5.0, -1.0, -3.0, 1.0),
        layers=("F.Cu", "F.Fab"),
        installed_footprint_id="RF_Module:Fixture_Cutout_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:4",
        source_file_sha256=SOURCE_SHA,
        source_binding_id="binding:support-geometry",
    )


def _cutout_declaration(
    placement,
    *,
    supports: tuple[AntennaModuleSupportRegion, ...] | None = None,
    selected: BoardCutoutPolygon = TARGET_CUTOUT,
    required: tuple[str, ...] = ("region:antenna",),
) -> AntennaCutoutDeclaration:
    regions = supports or (_support(),)
    antenna = placement.declaration
    binding_fp = support_binding_for_declaration(antenna, regions)
    return AntennaCutoutDeclaration(
        cutout_declaration_id="cutout:U1",
        antenna_id=antenna.antenna_id,
        module_reference=antenna.module_reference,
        antenna_declaration_fingerprint=antenna.semantic_fingerprint(),
        source_applicability_binding_id=antenna.module_guidance_binding.binding_id,
        required_cutout_region_ids=required,
        selected_cutout=build_selected_board_cutout(
            selected, placement.board_layout_snapshot_fingerprint
        ),
        support_regions=regions,
        support_geometry_binding=_binding(
            "binding:support-geometry", "claim:support-geometry", binding_fp
        ),
        antenna_inside_cutout_rule_id="rule:antenna-strictly-inside-selected-cutout",
        support_inside_material_rule_id="rule:module-support-inside-material",
    )


@pytest.mark.parametrize("rotation", (0.0, 90.0, 180.0, 270.0))
@pytest.mark.parametrize("back", (False, True))
def test_exact_front_back_quarter_turn_cutout_and_support_pass(rotation: float, back: bool) -> None:
    placement = _placement(rotation=rotation, back=back)

    result = evaluate_antenna_cutout(placement, _cutout_declaration(placement))

    antenna = result.cutout_evidence[0]
    assert antenna.contained_in_selected_cutout_closed is True
    assert antenna.selected_cutout_boundary_squared_clearance is not None
    assert antenna.selected_cutout_boundary_squared_clearance.numerator > 0
    assert antenna.material_relation is PlanarRelation.DISJOINT
    assert antenna.disposition is SemanticDisposition.PASS
    assert result.support_evidence[0].disposition is SemanticDisposition.PASS
    assert result.semantic_result.outcome is SemanticResultOutcome.PASSED


@pytest.mark.parametrize(
    ("anchor_x", "selected", "contained", "clearance_positive", "relation"),
    (
        (
            12.0,
            BoardCutoutPolygon(points=((10.9, 8.0), (14.0, 8.0), (14.0, 12.0), (10.9, 12.0))),
            True,
            True,
            PlanarRelation.DISJOINT,
        ),
        (11.0, TARGET_CUTOUT, True, False, PlanarRelation.BOUNDARY_TOUCH),
        (
            11.0,
            BoardCutoutPolygon(points=((10.1, 8.0), (14.0, 8.0), (14.0, 12.0), (10.1, 12.0))),
            False,
            False,
            PlanarRelation.INTERIOR_OVERLAP,
        ),
        (10.0, TARGET_CUTOUT, False, False, PlanarRelation.INTERIOR_OVERLAP),
    ),
)
def test_tenth_unit_inside_equality_outside_and_partial_material_overlap(
    anchor_x: float,
    selected: BoardCutoutPolygon,
    contained: bool,
    clearance_positive: bool,
    relation: PlanarRelation,
) -> None:
    placement = _placement(anchor=(anchor_x, 10.0), cutouts=(OTHER_CUTOUT, selected))

    result = evaluate_antenna_cutout(placement, _cutout_declaration(placement, selected=selected))

    evidence = result.cutout_evidence[0]
    assert evidence.contained_in_selected_cutout_closed is contained
    assert evidence.selected_cutout_boundary_squared_clearance is not None
    assert (evidence.selected_cutout_boundary_squared_clearance.numerator > 0) is (
        clearance_positive
    )
    assert evidence.material_relation is relation
    expected = (
        SemanticDisposition.PASS if contained and clearance_positive else SemanticDisposition.FAIL
    )
    assert evidence.disposition is expected


def test_explicit_wrong_existing_cutout_fails_rule_without_nearest_inference() -> None:
    placement = _placement()

    result = evaluate_antenna_cutout(
        placement, _cutout_declaration(placement, selected=OTHER_CUTOUT)
    )

    assert result.selected_cutout.cutout_fingerprint == OTHER_CUTOUT.semantic_fingerprint()
    assert result.cutout_evidence[0].contained_in_selected_cutout_closed is False
    assert result.cutout_evidence[0].disposition is SemanticDisposition.FAIL


def test_absent_selected_cutout_and_stale_snapshot_binding_are_rejected() -> None:
    placement = _placement()
    absent = BoardCutoutPolygon(points=((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)))
    with pytest.raises(ValueError, match="absent, wrong, or ambiguous"):
        evaluate_antenna_cutout(placement, _cutout_declaration(placement, selected=absent))

    payload = _cutout_declaration(placement).model_dump(mode="json")
    payload["selected_cutout"] = build_selected_board_cutout(TARGET_CUTOUT, "d" * 64).model_dump(
        mode="json"
    )
    stale = AntennaCutoutDeclaration.model_validate(payload)
    with pytest.raises(ValueError, match="another board layout snapshot"):
        evaluate_antenna_cutout(placement, stale)


@pytest.mark.parametrize(
    ("compound", "expected_relation", "contained"),
    (
        (_rect(-3.0, -1.0, -2.0, 1.0), PlanarRelation.BOUNDARY_TOUCH, True),
        (_rect(-2.5, -1.0, -1.5, 1.0), PlanarRelation.INTERIOR_OVERLAP, True),
        (_rect(-12.0, -1.0, -10.0, 1.0), PlanarRelation.DISJOINT, True),
        (_rect(-13.0, -1.0, -11.0, 1.0), PlanarRelation.DISJOINT, False),
    ),
)
def test_support_cutout_touch_intrusion_outer_equality_and_overhang(
    compound: ExactPlanarCompound,
    expected_relation: PlanarRelation,
    contained: bool,
) -> None:
    placement = _placement()
    declaration = _cutout_declaration(placement, supports=(_support(compound=compound),))

    result = evaluate_antenna_cutout(placement, declaration)

    support = result.support_evidence[0]
    assert support.contained_in_outer is contained
    target_id = result.selected_cutout.cutout_id
    relations = dict(support.cutout_relations)
    assert relations[target_id] is expected_relation
    passes = contained and all(item is PlanarRelation.DISJOINT for item in relations.values())
    assert support.disposition is (SemanticDisposition.PASS if passes else SemanticDisposition.FAIL)


def test_support_intrusion_into_nonselected_cutout_fails_independently() -> None:
    placement = _placement()
    support = _support(compound=_rect(8.0, 4.0, 11.0, 7.0))

    result = evaluate_antenna_cutout(placement, _cutout_declaration(placement, supports=(support,)))

    assert result.cutout_evidence[0].disposition is SemanticDisposition.PASS
    assert (
        PlanarRelation.INTERIOR_OVERLAP
        in dict(result.support_evidence[0].cutout_relations).values()
    )
    assert result.support_evidence[0].disposition is SemanticDisposition.FAIL


def test_concave_outer_and_multiple_cutouts_are_reconstructed_exactly() -> None:
    placement = _placement()
    result = evaluate_antenna_cutout(placement, _cutout_declaration(placement))

    assert result.board_material.outer_polygon.outer == ExactPlanarPolygon(outer=OUTLINE).outer
    assert len(result.board_material.cutout_compounds) == 2
    assert set(result.board_material.material_compound.polygons[0].holes) == {
        ExactPlanarPolygon(outer=TARGET_CUTOUT.points).outer,
        ExactPlanarPolygon(outer=OTHER_CUTOUT.points).outer,
    }
    assert (
        result.selected_cutout.cutout_compound.polygons[0].outer
        == ExactPlanarPolygon(outer=TARGET_CUTOUT.points).outer
    )


def test_arbitrary_angle_makes_cutout_and_support_rules_independently_unverified() -> None:
    placement = _placement(rotation=17.0)

    result = evaluate_antenna_cutout(placement, _cutout_declaration(placement))

    assert result.cutout_evidence[0].verification is SemanticVerification.BOUNDED_APPROXIMATION
    assert result.support_evidence[0].verification is SemanticVerification.BOUNDED_APPROXIMATION
    assert result.cutout_evidence[0].disposition is SemanticDisposition.UNVERIFIED
    assert result.support_evidence[0].disposition is SemanticDisposition.UNVERIFIED
    assert result.semantic_result.outcome is SemanticResultOutcome.HARD_SCOPE_UNVERIFIED
    assert len(result.semantic_result.findings) == 2


def test_wrong_strategy_module_source_and_support_bindings_fail() -> None:
    edge = _placement(strategy="edge_overhang")
    with pytest.raises(ValueError, match="requires baseboard_cutout"):
        evaluate_antenna_cutout(edge, _cutout_declaration(edge))

    placement = _placement()
    payload = _cutout_declaration(placement).model_dump(mode="json")
    payload["module_reference"] = "U404"
    with pytest.raises(ValueError, match="another antenna declaration"):
        evaluate_antenna_cutout(placement, AntennaCutoutDeclaration.model_validate(payload))

    payload = _cutout_declaration(placement).model_dump(mode="json")
    payload["support_regions"][0]["source_file_sha256"] = "d" * 64
    with pytest.raises(ValidationError):
        AntennaCutoutDeclaration.model_validate(payload)

    payload = _cutout_declaration(placement).model_dump(mode="json")
    payload["support_geometry_binding"]["geometry_source_fingerprint"] = "d" * 64
    with pytest.raises(ValidationError, match="support geometry binding fingerprint is stale"):
        AntennaCutoutDeclaration.model_validate(payload)


def test_missing_duplicate_required_support_and_provenance_identities_fail() -> None:
    placement = _placement()
    payload = _cutout_declaration(placement).model_dump(mode="json")
    payload["required_cutout_region_ids"] = []
    with pytest.raises(ValidationError):
        AntennaCutoutDeclaration.model_validate(payload)
    payload = _cutout_declaration(placement).model_dump(mode="json")
    payload["required_cutout_region_ids"] = ["region:antenna", "region:antenna"]
    with pytest.raises(ValidationError, match="unique identities"):
        AntennaCutoutDeclaration.model_validate(payload)
    unknown = _cutout_declaration(placement, required=("region:unknown",))
    with pytest.raises(ValueError, match="omits or invents"):
        evaluate_antenna_cutout(placement, unknown)

    second = _support(support_id="support:pads", provenance_id="provenance:support:pads")
    for field, duplicate_value, match in (
        ("support_region_id", "support:body", "region identities"),
        ("provenance_id", "provenance:support:body", "provenance identities"),
    ):
        duplicate = second.model_copy(update={field: duplicate_value})
        supports = (_support(), duplicate)
        antenna = placement.declaration
        binding = _binding(
            "binding:support-geometry",
            "claim:support-geometry",
            support_binding_for_declaration(antenna, supports),
        )
        payload = _cutout_declaration(placement).model_dump(mode="json")
        payload["support_regions"] = [item.model_dump(mode="json") for item in supports]
        payload["support_geometry_binding"] = binding.model_dump(mode="json")
        with pytest.raises(ValidationError, match=match):
            AntennaCutoutDeclaration.model_validate(payload)


def test_no_component_or_source_approved_exception_input_exists() -> None:
    fields = AntennaCutoutDeclaration.model_fields
    assert "component_reference_exemption" not in fields
    assert "source_approved_exception" not in fields
    assert "nearest_cutout" not in fields


def test_replay_rejects_cutout_material_transform_evidence_finding_and_message_tamper() -> None:
    placement = _placement()
    result = evaluate_antenna_cutout(placement, _cutout_declaration(placement))
    mutations = []

    selected = deepcopy(result.model_dump(mode="json"))
    selected["selected_cutout"]["cutout_compound"]["polygons"][0]["outer"][0][0] -= 0.1
    mutations.append(selected)
    material = deepcopy(result.model_dump(mode="json"))
    material["board_material"]["outer_polygon"]["outer"][0][0] -= 0.1
    mutations.append(material)
    transformed = deepcopy(result.model_dump(mode="json"))
    transformed["transformed_supports"][0]["bounded_transform"]["compound"]["polygons"][0]["outer"][
        0
    ][0] -= 0.1
    mutations.append(transformed)
    evidence = deepcopy(result.model_dump(mode="json"))
    evidence["cutout_evidence"][0]["disposition"] = "fail"
    mutations.append(evidence)
    unsupported = deepcopy(result.model_dump(mode="json"))
    unsupported["cutout_evidence"][0]["verification"] = "unsupported"
    mutations.append(unsupported)
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
            AntennaCutoutResult.model_validate(payload)


def test_support_reversal_repeat_and_json_are_deterministic() -> None:
    placement = _placement()
    reversed_cutout_placement = _placement(cutouts=(TARGET_CUTOUT, OTHER_CUTOUT))
    body = _support()
    pads = _support(
        support_id="support:pads",
        provenance_id="provenance:support:pads",
        compound=_rect(-4.5, -0.5, -3.5, 0.5),
        role="pad_support",
    )
    first = evaluate_antenna_cutout(
        placement, _cutout_declaration(placement, supports=(body, pads))
    )
    reversed_result = evaluate_antenna_cutout(
        placement, _cutout_declaration(placement, supports=(pads, body))
    )
    repeated = evaluate_antenna_cutout(
        placement, _cutout_declaration(placement, supports=(body, pads))
    )
    reversed_cutouts = evaluate_antenna_cutout(
        reversed_cutout_placement,
        _cutout_declaration(reversed_cutout_placement, supports=(pads, body)),
    )

    assert first == reversed_result == repeated == reversed_cutouts
    assert AntennaCutoutResult.model_validate_json(first.model_dump_json()) == first
