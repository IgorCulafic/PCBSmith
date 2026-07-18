"""Firing fixture 7 for source-specific 3-D antenna enclosure exclusion."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest
from pydantic import ValidationError

from pcbsmith.antenna_enclosure_ir import (
    AntennaEnclosureExclusionDeclaration,
    AntennaEnclosureExclusionResult,
    AntennaExclusionPrismDeclaration,
    EnclosureObject,
    EnclosureObjectProfile,
    ExactDecimalInterval,
    exclusion_binding_fingerprint,
)
from pcbsmith.antenna_ir import (
    AntennaLocalRegion,
    AntennaModuleDeclaration,
    InstalledFootprintKeepoutProvenance,
    antenna_geometry_source_fingerprint,
)
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.antenna_enclosure import evaluate_antenna_enclosure_exclusion
from pcbsmith.kicad.antenna_semantics import evaluate_antenna_placement
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNetlist
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticResultOutcome,
    SemanticVerification,
)

SOURCE_SHA = "a" * 64
MODEL_SHA = "b" * 64


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
                title="Fixture module enclosure exclusion",
                locator="figure:enclosure-exclusion",
                source_id="source:fixture-module-guide",
                organization_or_author="Fixture Vendor",
                revision="7",
                local_sha256=SOURCE_SHA,
                source_status="pinned",
                locator_status="figure_verified",
                applicability_status="confirmed",
                required_conditions=("module-revision=7",),
            ),
        ),
        claim_id=claim_id,
        applicability_record_id=f"applicability:{claim_id}",
        required_conditions=("module-revision=7",),
        excluded_conditions=(),
        matched_conditions=("module-revision=7",),
        unmatched_conditions=(),
        geometry_source_fingerprint=geometry_fp,
        reviewer_record_id="review:module:7",
    )


def _antenna_declaration() -> AntennaModuleDeclaration:
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
        selected_footprint_library_id="RF_Module:Fixture_3D_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:7",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding_id="binding:module-guidance",
        prohibited_object_rule_id="rule:pcb-keepout",
        compound=_rect(-2.0, -2.0, 2.0, 2.0),
        layers=("F.Cu",),
        prohibited_object_kinds=("track", "via", "pad", "zone"),
    )
    geometry_fp = antenna_geometry_source_fingerprint(antenna, feed, (keepout,))
    return AntennaModuleDeclaration(
        antenna_id="antenna:U1",
        module_reference="U1",
        selected_footprint_library_id="RF_Module:Fixture_3D_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:7",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding=_binding(
            "binding:module-guidance", "claim:module-geometry", geometry_fp
        ),
        antenna_region=antenna,
        feed_region=feed,
        keepouts=(keepout,),
        placement_strategy="edge_overhang",
        edge_or_cutout_requirement_id="requirement:edge",
        enclosure_exclusion_requirement_id="requirement:enclosure-15mm",
        rf_validation_requirement_id="requirement:rf",
    )


def _placement(*, rotation: float = 0.0, back: bool = False):
    component = BoardComponent(
        reference="U1",
        value="Fixture 3D Module",
        footprint="RF_Module:Fixture_3D_Antenna",
        uuid_path="uuid:path:U1",
        fields=(("revision", "module-revision:7"),),
    )
    layout = BoardLayout(
        placements=((component, 0.0),),
        segments=(),
        vias=(),
        width_mm=40.0,
        height_mm=40.0,
        parts_row_y_mm=0.0,
        part_rotation=(("U1", rotation),) if rotation else (),
        part_flip=("U1",) if back else (),
    )
    return evaluate_antenna_placement(
        layout, BoardNetlist(components=(component,), nets=()), _antenna_declaration()
    )


def _exclusion() -> AntennaExclusionPrismDeclaration:
    return AntennaExclusionPrismDeclaration(
        exclusion_id="exclusion:module-antenna",
        local_xy_compound=_rect(-1.0, -1.0, 1.0, 1.0),
        local_z_interval=ExactDecimalInterval(lower_mm="0", upper_mm="1"),
    )


def _declaration(placement) -> AntennaEnclosureExclusionDeclaration:
    antenna = placement.declaration
    exclusion = _exclusion()
    clearance = Decimal("15")
    geometry_fp = exclusion_binding_fingerprint(
        antenna, exclusion, clearance, ("metal", "plastic")
    )
    return AntennaEnclosureExclusionDeclaration(
        declaration_id="enclosure-exclusion:U1",
        antenna_id=antenna.antenna_id,
        module_reference=antenna.module_reference,
        selected_footprint_library_id=antenna.selected_footprint_library_id,
        component_uuid_path=antenna.component_uuid_path,
        component_revision=antenna.component_revision,
        source_file_sha256=antenna.source_file_sha256,
        antenna_declaration_fingerprint=antenna.semantic_fingerprint(),
        exclusion_requirement_id=antenna.enclosure_exclusion_requirement_id,
        validation_profile_id="validation-profile:enclosure:7",
        exclusion=exclusion,
        required_clearance_mm=clearance,
        prohibited_material_classes=("metal", "plastic"),
        enclosure_profile_id="enclosure-profile:fixture",
        enclosure_id="enclosure:fixture",
        enclosure_revision="enclosure-revision:7",
        model_id="cad-model:fixture",
        model_sha256=MODEL_SHA,
        applicability_binding=_binding(
            "binding:enclosure-exclusion", "claim:enclosure-15mm", geometry_fp
        ),
    )


def _object(
    *,
    object_id: str = "object:wall",
    material: str = "metal",
    xy: ExactPlanarCompound | None = None,
    z: ExactDecimalInterval | None = None,
) -> EnclosureObject:
    return EnclosureObject(
        object_id=object_id,
        enclosure_profile_id="enclosure-profile:fixture",
        enclosure_id="enclosure:fixture",
        enclosure_revision="enclosure-revision:7",
        model_id="cad-model:fixture",
        model_sha256=MODEL_SHA,
        material_class=material,
        planar_compound=xy,
        z_interval=z,
    )


def _profile(
    objects: tuple[EnclosureObject, ...],
    *,
    plane: str = "0",
    completeness: str = "complete",
    expected: tuple[str, ...] | None = None,
    model_geometry_status: str = "available",
) -> EnclosureObjectProfile:
    return EnclosureObjectProfile(
        profile_id="enclosure-profile:fixture",
        enclosure_id="enclosure:fixture",
        enclosure_revision="enclosure-revision:7",
        model_id="cad-model:fixture",
        model_sha256=MODEL_SHA,
        model_geometry_status=model_geometry_status,
        board_plane_z_mm=plane,
        completeness=completeness,
        expected_object_ids=expected or tuple(item.object_id for item in objects),
        objects=objects,
    )


@pytest.mark.parametrize("rotation", (0.0, 90.0, 180.0, 270.0))
@pytest.mark.parametrize("back", (False, True))
def test_front_back_quarter_turns_are_exact_and_reflect_z(rotation: float, back: bool) -> None:
    placement = _placement(rotation=rotation, back=back)
    declaration = _declaration(placement)
    wall = _object(
        xy=_rect(30.0, 30.0, 31.0, 31.0),
        z=ExactDecimalInterval(lower_mm="30", upper_mm="31"),
    )

    result = evaluate_antenna_enclosure_exclusion(
        placement, declaration, _profile((wall,), plane="10")
    )

    assert result.transformed_exclusion is not None
    assert result.transformed_exclusion.verification is SemanticVerification.EXACT
    expected_z = (Decimal("9"), Decimal("10")) if back else (Decimal("10"), Decimal("11"))
    interval = result.transformed_exclusion.exact_z_interval
    assert (interval.lower_mm, interval.upper_mm) == expected_z


@pytest.mark.parametrize(
    ("wall_start", "disposition", "squared"),
    (
        (16.0, SemanticDisposition.PASS, Fraction(225)),
        (15.9, SemanticDisposition.FAIL, Fraction(22201, 100)),
    ),
)
def test_exact_15mm_equality_passes_and_14_9_fails(
    wall_start: float, disposition: SemanticDisposition, squared: Fraction
) -> None:
    placement = _placement()
    wall = _object(
        xy=_rect(wall_start, -1.0, wall_start + 1.0, 1.0),
        z=ExactDecimalInterval(lower_mm="0", upper_mm="1"),
    )

    result = evaluate_antenna_enclosure_exclusion(
        placement, _declaration(placement), _profile((wall,))
    )

    evidence = result.evidence[0]
    assert evidence.disposition is disposition
    assert evidence.total_squared_distance is not None
    assert evidence.total_squared_distance.as_fraction() == squared
    assert evidence.required_squared_clearance.as_fraction() == Fraction(225)


@pytest.mark.parametrize(
    ("xy", "z", "xy_squared", "z_separation"),
    (
        (_rect(16.0, -1.0, 17.0, 1.0), ("0", "1"), Fraction(225), Fraction(0)),
        (_rect(-1.0, -1.0, 1.0, 1.0), ("16", "17"), Fraction(0), Fraction(15)),
        (_rect(10.0, -1.0, 11.0, 1.0), ("13", "14"), Fraction(81), Fraction(12)),
    ),
)
def test_xy_z_and_combined_exact_3d_distance(
    xy: ExactPlanarCompound,
    z: tuple[str, str],
    xy_squared: Fraction,
    z_separation: Fraction,
) -> None:
    placement = _placement()
    wall = _object(
        xy=xy, z=ExactDecimalInterval(lower_mm=z[0], upper_mm=z[1])
    )

    evidence = evaluate_antenna_enclosure_exclusion(
        placement, _declaration(placement), _profile((wall,))
    ).evidence[0]

    assert evidence.xy_squared_distance is not None
    assert evidence.z_separation is not None
    assert evidence.total_squared_distance is not None
    assert evidence.xy_squared_distance.as_fraction() == xy_squared
    assert evidence.z_separation.as_fraction() == z_separation
    assert evidence.total_squared_distance.as_fraction() == Fraction(225)
    assert evidence.disposition is SemanticDisposition.PASS


def test_overlap_and_touch_fail_positive_clearance() -> None:
    placement = _placement()
    for xy in (_rect(-0.5, -0.5, 0.5, 0.5), _rect(1.0, -1.0, 2.0, 1.0)):
        wall = _object(
            xy=xy, z=ExactDecimalInterval(lower_mm="0", upper_mm="1")
        )
        evidence = evaluate_antenna_enclosure_exclusion(
            placement, _declaration(placement), _profile((wall,))
        ).evidence[0]
        assert evidence.total_squared_distance is not None
        assert evidence.total_squared_distance.as_fraction() == 0
        assert evidence.disposition is SemanticDisposition.FAIL


def test_prohibited_and_nonprohibited_materials_are_independent() -> None:
    placement = _placement()
    geometry = _rect(-0.5, -0.5, 0.5, 0.5)
    interval = ExactDecimalInterval(lower_mm="0", upper_mm="1")
    profile = _profile(
        (
            _object(object_id="object:metal", material="metal", xy=geometry, z=interval),
            _object(object_id="object:glass", material="glass", xy=geometry, z=interval),
        )
    )

    result = evaluate_antenna_enclosure_exclusion(
        placement, _declaration(placement), profile
    )

    by_id = {item.object_id: item for item in result.evidence}
    assert by_id["object:metal"].disposition is SemanticDisposition.FAIL
    assert by_id["object:glass"].disposition is SemanticDisposition.NOT_APPLICABLE
    assert result.semantic_result.outcome is SemanticResultOutcome.VALIDATION_FAILED


def test_missing_profile_object_geometry_and_incomplete_inventory_are_pending() -> None:
    placement = _placement()
    declaration = _declaration(placement)

    absent = evaluate_antenna_enclosure_exclusion(placement, declaration, None)
    assert absent.evidence[0].disposition is SemanticDisposition.VALIDATION_PENDING
    assert absent.semantic_result.outcome is SemanticResultOutcome.VALIDATION_PENDING

    missing_model = _profile(
        (),
        completeness="incomplete",
        expected=("object:wall",),
        model_geometry_status="missing",
    )
    result = evaluate_antenna_enclosure_exclusion(
        placement, declaration, missing_model
    )
    assert result.evidence[0].pending_reason == "enclosure_model_geometry_missing"

    missing_geometry = _object(xy=None, z=None)
    result = evaluate_antenna_enclosure_exclusion(
        placement, declaration, _profile((missing_geometry,))
    )
    assert result.evidence[0].pending_reason == "object_geometry_missing"

    incomplete = _profile(
        (), completeness="incomplete", expected=("object:wall",)
    )
    result = evaluate_antenna_enclosure_exclusion(placement, declaration, incomplete)
    assert {item.pending_reason for item in result.evidence} == {
        "enclosure_profile_inventory_incomplete",
        "expected_object_missing",
    }

    incomplete_with_expected_object = _profile(
        (_object(),), completeness="incomplete", expected=("object:wall",)
    )
    result = evaluate_antenna_enclosure_exclusion(
        placement, declaration, incomplete_with_expected_object
    )
    assert any(
        item.pending_reason == "enclosure_profile_inventory_incomplete"
        for item in result.evidence
    )
    assert result.semantic_result.outcome is SemanticResultOutcome.VALIDATION_PENDING


def test_arbitrary_angle_is_validation_pending_not_exact_failure() -> None:
    placement = _placement(rotation=13.0)
    wall = _object(
        xy=_rect(-0.5, -0.5, 0.5, 0.5),
        z=ExactDecimalInterval(lower_mm="0", upper_mm="1"),
    )

    result = evaluate_antenna_enclosure_exclusion(
        placement, _declaration(placement), _profile((wall,))
    )

    assert result.transformed_exclusion is not None
    assert result.transformed_exclusion.verification is SemanticVerification.BOUNDED_APPROXIMATION
    assert result.evidence[0].disposition is SemanticDisposition.VALIDATION_PENDING
    assert result.evidence[0].total_squared_distance is None


def test_3d_evaluation_retains_2d_pcb_geometry_byte_and_value_identically() -> None:
    placement = _placement()
    placement_json = placement.model_dump_json()
    layout_json = placement.board_layout_snapshot_json
    keepouts = placement.declaration.keepouts
    placed = placement.placed_regions
    wall = _object(
        xy=_rect(16.0, -1.0, 17.0, 1.0),
        z=ExactDecimalInterval(lower_mm="0", upper_mm="1"),
    )

    result = evaluate_antenna_enclosure_exclusion(
        placement, _declaration(placement), _profile((wall,))
    )

    assert placement.model_dump_json() == placement_json
    assert result.placement_result.board_layout_snapshot_json == layout_json
    assert result.placement_result.declaration.keepouts == keepouts
    assert result.placement_result.placed_regions == placed
    assert result.pcb_geometry_before_fingerprint == result.pcb_geometry_after_fingerprint


def test_complete_profile_rejects_missing_invented_duplicate_and_stale_objects() -> None:
    wall = _object(
        xy=_rect(16.0, -1.0, 17.0, 1.0),
        z=ExactDecimalInterval(lower_mm="0", upper_mm="1"),
    )
    with pytest.raises(ValidationError, match="exact object inventory"):
        _profile((), expected=("object:wall",))
    with pytest.raises(ValidationError, match="invents objects"):
        _profile((wall,), expected=("object:other",), completeness="incomplete")
    with pytest.raises(ValidationError, match="unique"):
        _profile((wall, wall))
    stale = wall.model_copy(update={"model_sha256": "c" * 64})
    with pytest.raises(ValidationError, match="stale"):
        _profile((stale,))


@pytest.mark.parametrize(
    "field",
    (
        "antenna_id", "module_reference", "selected_footprint_library_id",
        "component_uuid_path", "component_revision", "source_file_sha256",
        "antenna_declaration_fingerprint", "exclusion_requirement_id",
    ),
)
def test_wrong_antenna_module_source_binding_is_rejected(field: str) -> None:
    placement = _placement()
    declaration = _declaration(placement)
    value = "c" * 64 if field.endswith("sha256") or field.endswith("fingerprint") else "wrong"
    stale = declaration.model_copy(update={field: value})

    with pytest.raises(ValueError):
        evaluate_antenna_enclosure_exclusion(placement, stale, None)


def test_changed_clearance_unit_geometry_or_binding_is_rejected() -> None:
    placement = _placement()
    declaration = _declaration(placement)
    for update in (
        {"required_clearance_mm": Decimal("14.9")},
        {"exclusion": declaration.exclusion.model_copy(
            update={"local_z_interval": ExactDecimalInterval(lower_mm="0", upper_mm="2")}
        )},
        {"applicability_binding": declaration.applicability_binding.model_copy(
            update={"geometry_source_fingerprint": "c" * 64}
        )},
    ):
        stale = declaration.model_copy(update=update)
        with pytest.raises(ValueError, match="applicability is stale"):
            evaluate_antenna_enclosure_exclusion(placement, stale, None)
    payload = declaration.model_dump(mode="json")
    payload["clearance_unit"] = "cm"
    with pytest.raises(ValidationError):
        AntennaEnclosureExclusionDeclaration.model_validate(payload)


def test_stale_profile_revision_model_hash_and_profile_id_are_rejected() -> None:
    placement = _placement()
    declaration = _declaration(placement)
    wall = _object(
        xy=_rect(16.0, -1.0, 17.0, 1.0),
        z=ExactDecimalInterval(lower_mm="0", upper_mm="1"),
    )
    profile = _profile((wall,))
    for update in (
        {"profile_id": "wrong"},
        {"enclosure_revision": "wrong"},
        {"model_sha256": "c" * 64},
    ):
        stale = profile.model_copy(update=update)
        with pytest.raises((ValueError, ValidationError), match="stale"):
            evaluate_antenna_enclosure_exclusion(placement, declaration, stale)


def test_json_replay_and_result_message_fingerprint_tamper_rejected() -> None:
    placement = _placement()
    wall = _object(
        xy=_rect(16.0, -1.0, 17.0, 1.0),
        z=ExactDecimalInterval(lower_mm="0", upper_mm="1"),
    )
    result = evaluate_antenna_enclosure_exclusion(
        placement, _declaration(placement), _profile((wall,))
    )
    replay = AntennaEnclosureExclusionResult.model_validate_json(result.model_dump_json())
    assert replay == result

    for mutate in (
        lambda payload: payload["evidence"][0].update({"pending_reason": "tampered"}),
        lambda payload: payload["semantic_result"]["findings"][0].update(
            {"message": "tampered"}
        ),
        lambda payload: payload.update({"evidence_fingerprint": "c" * 64}),
        lambda payload: payload.update({"result_fingerprint": "c" * 64}),
    ):
        payload = deepcopy(result.model_dump(mode="json"))
        mutate(payload)
        with pytest.raises(ValidationError):
            AntennaEnclosureExclusionResult.model_validate(payload)
