"""Firing fixture 2 for explicit physical-object antenna keepout checks."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.antenna_clearance_ir import (
    AntennaClearanceResult,
    AntennaPhysicalObject,
    AntennaUnsupportedObjectReason,
    QualifiedExactZoneFillProvenance,
)
from pcbsmith.antenna_ir import (
    AntennaLocalRegion,
    AntennaModuleDeclaration,
    InstalledFootprintKeepoutProvenance,
    antenna_geometry_source_fingerprint,
)
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.antenna_clearance import evaluate_antenna_clearance
from pcbsmith.kicad.antenna_semantics import evaluate_antenna_placement
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon, PlanarRelation
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticResultOutcome,
    SemanticVerification,
)
from pcbsmith.sensor_copper_removal_ir import ExactFilledZoneReaderPolicy

SOURCE_SHA = "a" * 64


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _irregular_zone_fill() -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(
                outer=((10.5, 10.5), (12.8, 10.5), (12.2, 11.3), (12.8, 12.8), (10.5, 12.8))
            ),
        )
    )


def _declaration(
    *,
    prohibited: tuple[str, ...] = (
        "track",
        "via",
        "pad",
        "zone",
        "footprint",
        "board_material",
    ),
    keepout_layers: tuple[str, ...] = ("F.Cu", "B.Cu", "board_material"),
) -> AntennaModuleDeclaration:
    antenna = AntennaLocalRegion(
        region_id="region:antenna",
        role="antenna",
        compound=_rect(0.0, 0.0, 1.0, 1.0),
        layers=("F.Cu",),
    )
    feed = AntennaLocalRegion(
        region_id="region:feed",
        role="feed",
        compound=_rect(-1.0, -0.2, 0.0, 0.2),
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
        prohibited_object_rule_id="rule:antenna-keepout",
        compound=_rect(0.0, 0.0, 2.0, 2.0),
        layers=keepout_layers,
        prohibited_object_kinds=prohibited,
    )
    geometry_fp = antenna_geometry_source_fingerprint(antenna, feed, (keepout,))
    binding = EvidenceApplicabilityBinding(
        binding_id="binding:module-guidance",
        evidence=(
            EvidenceRef(
                kind="module_design_guide",
                title="Fixture antenna guide",
                locator="figure:keepout",
                source_id="source:fixture-guide",
                organization_or_author="Fixture Vendor",
                revision="3",
                local_sha256=SOURCE_SHA,
                source_status="pinned",
                locator_status="figure_bound",
                applicability_status="confirmed",
                required_conditions=("module-revision=3",),
            ),
        ),
        claim_id="claim:antenna-keepout",
        applicability_record_id="applicability:module:3",
        required_conditions=("module-revision=3",),
        excluded_conditions=(),
        matched_conditions=("module-revision=3",),
        unmatched_conditions=(),
        geometry_source_fingerprint=geometry_fp,
        reviewer_record_id="review:module:3",
    )
    return AntennaModuleDeclaration(
        antenna_id="antenna:U1",
        module_reference="U1",
        selected_footprint_library_id="RF_Module:Fixture_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:3",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding=binding,
        antenna_region=antenna,
        feed_region=feed,
        keepouts=(keepout,),
        placement_strategy="edge_overhang",
        edge_or_cutout_requirement_id="requirement:edge",
        enclosure_exclusion_requirement_id="requirement:enclosure",
        rf_validation_requirement_id="requirement:rf",
    )


def _placement(
    *,
    rotation: float = 0.0,
    prohibited: tuple[str, ...] = (
        "track",
        "via",
        "pad",
        "zone",
        "footprint",
        "board_material",
    ),
    keepout_layers: tuple[str, ...] = ("F.Cu", "B.Cu", "board_material"),
):
    component = BoardComponent(
        reference="U1",
        value="Fixture Module",
        footprint="RF_Module:Fixture_Antenna",
        uuid_path="uuid:path:U1",
        fields=(("revision", "module-revision:3"),),
    )
    foreign = BoardComponent(
        reference="U9",
        value="Foreign fixture object",
        footprint="Fixture:Foreign",
        uuid_path="uuid:path:U9",
        fields=(),
    )
    layout = BoardLayout(
        placements=((component, 10.0), (foreign, 20.0)),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=20.0,
        parts_row_y_mm=10.0,
        part_rotation=(("U1", rotation),) if rotation else (),
    )
    return evaluate_antenna_placement(
        layout,
        BoardNetlist(
            components=(component, foreign),
            nets=(BoardNet(name="GND", nodes=(("U9", "1"),)),),
        ),
        _declaration(prohibited=prohibited, keepout_layers=keepout_layers),
    )


def _object(
    placement,
    *,
    object_id: str = "object:track",
    kind: str = "track",
    layers: tuple[str, ...] = ("F.Cu",),
    geometry: ExactPlanarCompound | None = None,
    source_id: str | None = None,
    fill_id: str | None = None,
    unsupported_zone_intent: bool = False,
) -> AntennaPhysicalObject:
    source = source_id or f"source:{object_id}"
    if unsupported_zone_intent:
        return AntennaPhysicalObject(
            object_id=object_id,
            kind="zone",
            physical_layers=layers,
            source_provenance_id=source,
            owner_component_ref=None,
            owner_net_name="GND",
            board_layout_snapshot_fingerprint=placement.board_layout_snapshot_fingerprint,
            source_representation="zone_intent",
            verification=SemanticVerification.UNSUPPORTED,
            compound=None,
            unsupported_reason=(
                AntennaUnsupportedObjectReason.ZONE_INTENT_WITHOUT_FINAL_FILL
            ),
            exact_zone_fill_provenance=None,
        )
    exact = geometry or (
        _irregular_zone_fill() if kind == "zone" else _rect(11.0, 11.0, 13.0, 13.0)
    )
    fill = None
    representation = "physical_geometry"
    if kind == "zone":
        representation = "exact_final_zone_fill"
        reader_policy = ExactFilledZoneReaderPolicy(
            policy_id="policy:fixture",
            reader_id="reader:fixture",
            reader_version="1",
            project_qualification_record_id="qualification:fixture",
            project_qualification_artifact_sha256="b" * 64,
            reviewer_record_id="review:fill",
            status="active",
        )
        fill = QualifiedExactZoneFillProvenance.build(
            fill_provenance_id=fill_id or f"fill:{object_id}",
            zone_source_provenance_id=source,
            board_layout_snapshot_fingerprint=placement.board_layout_snapshot_fingerprint,
            exact_geometry_fingerprint=exact.semantic_fingerprint(),
            reader_id="reader:fixture",
            reader_version="1",
            reader_policy=reader_policy,
            source_artifact_id=f"artifact:{object_id}",
            source_artifact_sha256="c" * 64,
        )
    return AntennaPhysicalObject(
        object_id=object_id,
        kind=kind,
        physical_layers=layers,
        source_provenance_id=source,
        owner_component_ref="U9" if kind in {"pad", "footprint"} else None,
        owner_net_name="GND" if kind in {"track", "via", "pad", "zone"} else None,
        board_layout_snapshot_fingerprint=placement.board_layout_snapshot_fingerprint,
        source_representation=representation,
        verification=SemanticVerification.EXACT,
        compound=exact,
        unsupported_reason=None,
        exact_zone_fill_provenance=fill,
    )


@pytest.mark.parametrize(
    ("kind", "layer"),
    (
        ("track", "F.Cu"),
        ("via", "F.Cu"),
        ("pad", "F.Cu"),
        ("zone", "F.Cu"),
        ("footprint", "F.Cu"),
        ("board_material", "board_material"),
    ),
)
def test_each_declared_physical_kind_fires_independently(kind: str, layer: str) -> None:
    placement = _placement()

    result = evaluate_antenna_clearance(
        placement,
        (_object(placement, object_id=f"object:{kind}", kind=kind, layers=(layer,)),),
    )

    pair = result.pair_evidence[0]
    assert pair.relation is PlanarRelation.INTERIOR_OVERLAP
    assert pair.disposition is SemanticDisposition.FAIL
    assert result.semantic_result.outcome is SemanticResultOutcome.HARD_REJECTED
    assert result.semantic_result.summary.route_acceptance_blocked


def test_same_geometry_wrong_kind_or_layer_is_not_applicable() -> None:
    kind_placement = _placement(prohibited=("track",), keepout_layers=("F.Cu",))
    layer_placement = _placement(prohibited=("track",), keepout_layers=("F.Cu",))

    wrong_kind = evaluate_antenna_clearance(
        kind_placement, (_object(kind_placement, kind="via", object_id="object:via"),)
    )
    wrong_layer = evaluate_antenna_clearance(
        layer_placement,
        (_object(layer_placement, kind="track", layers=("B.Cu",)),),
    )

    assert wrong_kind.pair_evidence[0].disposition is SemanticDisposition.NOT_APPLICABLE
    assert wrong_layer.pair_evidence[0].disposition is SemanticDisposition.NOT_APPLICABLE
    assert not wrong_kind.semantic_result.summary.route_acceptance_blocked
    assert not wrong_layer.semantic_result.summary.route_acceptance_blocked


def test_module_owned_feature_has_no_implicit_exemption() -> None:
    placement = _placement()
    payload = _object(placement, kind="pad", object_id="object:module-pad").model_dump(
        mode="json"
    )
    payload["owner_component_ref"] = "U1"
    module_owned = AntennaPhysicalObject.model_validate(payload)

    result = evaluate_antenna_clearance(placement, (module_owned,))

    assert result.pair_evidence[0].disposition is SemanticDisposition.FAIL


def test_exact_disjoint_passes_and_boundary_touch_fails_conservatively() -> None:
    placement = _placement()
    passed = evaluate_antenna_clearance(
        placement,
        (_object(placement, geometry=_rect(13.0, 13.0, 14.0, 14.0)),),
    )
    touched = evaluate_antenna_clearance(
        placement,
        (_object(placement, geometry=_rect(12.0, 10.5, 13.0, 11.5)),),
    )

    assert passed.pair_evidence[0].relation is PlanarRelation.DISJOINT
    assert passed.pair_evidence[0].disposition is SemanticDisposition.PASS
    assert touched.pair_evidence[0].relation is PlanarRelation.BOUNDARY_TOUCH
    assert touched.pair_evidence[0].disposition is SemanticDisposition.FAIL


def test_bounded_keepout_and_unsupported_zone_intent_are_hard_unverified() -> None:
    bounded_placement = _placement(rotation=17.0)
    exact_placement = _placement()
    bounded = evaluate_antenna_clearance(
        bounded_placement, (_object(bounded_placement),)
    )
    zone_intent = evaluate_antenna_clearance(
        exact_placement,
        (
            _object(
                exact_placement,
                object_id="object:zone-intent",
                kind="zone",
                unsupported_zone_intent=True,
            ),
        ),
    )

    assert bounded.pair_evidence[0].verification is SemanticVerification.BOUNDED_APPROXIMATION
    assert zone_intent.pair_evidence[0].verification is SemanticVerification.UNSUPPORTED
    for result in (bounded, zone_intent):
        assert result.pair_evidence[0].disposition is SemanticDisposition.UNVERIFIED
        assert result.semantic_result.outcome is SemanticResultOutcome.HARD_SCOPE_UNVERIFIED
        assert result.semantic_result.summary.route_acceptance_blocked


def test_favorable_unrelated_pair_cannot_hide_failure() -> None:
    placement = _placement()
    result = evaluate_antenna_clearance(
        placement,
        (
            _object(placement, object_id="object:overlap"),
            _object(
                placement,
                object_id="object:disjoint",
                geometry=_rect(20.0, 15.0, 21.0, 16.0),
            ),
        ),
    )

    assert {item.disposition for item in result.pair_evidence} == {
        SemanticDisposition.FAIL,
        SemanticDisposition.PASS,
    }
    assert result.semantic_result.summary.route_acceptance_blocked


def test_board_binding_and_qualified_fill_tamper_fail_closed() -> None:
    placement = _placement()
    payload = _object(placement).model_dump(mode="json")
    payload["board_layout_snapshot_fingerprint"] = "d" * 64
    stale = AntennaPhysicalObject.model_validate(payload)
    with pytest.raises(ValueError, match="another BoardLayout"):
        evaluate_antenna_clearance(placement, (stale,))

    zone_payload = _object(
        placement, object_id="object:zone", kind="zone"
    ).model_dump(mode="json")
    zone_payload["exact_zone_fill_provenance"]["final_fill_record_sha256"] = "d" * 64
    with pytest.raises(ValidationError, match="checksum is stale"):
        AntennaPhysicalObject.model_validate(zone_payload)
    zone_payload = _object(
        placement, object_id="object:zone", kind="zone"
    ).model_dump(mode="json")
    zone_payload["exact_zone_fill_provenance"]["zone_source_provenance_id"] = "source:stale"
    with pytest.raises(ValidationError, match="record JSON is noncanonical or stale"):
        AntennaPhysicalObject.model_validate(zone_payload)

    owner_payload = _object(placement).model_dump(mode="json")
    owner_payload["owner_component_ref"] = "U404"
    with pytest.raises(ValueError, match="owner component is absent"):
        evaluate_antenna_clearance(
            placement, (AntennaPhysicalObject.model_validate(owner_payload),)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("policy_id", "policy:stale"),
        ("reader_version", "stale"),
        ("status", "suspended"),
        ("project_qualification_artifact_sha256", "d" * 64),
        ("reviewer_record_id", "review:stale"),
    ),
)
def test_nested_exact_fill_reader_policy_tamper_fails(field: str, value: str) -> None:
    placement = _placement()
    payload = _object(
        placement, object_id="object:zone", kind="zone"
    ).model_dump(mode="json")
    payload["exact_zone_fill_provenance"]["reader_policy"][field] = value

    with pytest.raises(ValidationError):
        AntennaPhysicalObject.model_validate(payload)


def test_exact_zone_fill_geometry_fingerprint_is_bound() -> None:
    placement = _placement()
    payload = _object(
        placement, object_id="object:zone", kind="zone"
    ).model_dump(mode="json")
    payload["compound"]["polygons"][0]["outer"][0][0] -= 0.2

    with pytest.raises(ValidationError, match="provenance is stale or incomplete"):
        AntennaPhysicalObject.model_validate(payload)


def test_replay_rejects_object_pair_semantic_message_rule_and_fingerprint_tamper() -> None:
    placement = _placement()
    result = evaluate_antenna_clearance(placement, (_object(placement),))

    mutations = []
    object_geometry = deepcopy(result.model_dump(mode="json"))
    object_geometry["physical_objects"][0]["compound"]["polygons"][0]["outer"][0][0] -= 0.2
    mutations.append(object_geometry)
    source = deepcopy(result.model_dump(mode="json"))
    source["physical_objects"][0]["source_provenance_id"] = "source:stale"
    mutations.append(source)
    pair = deepcopy(result.model_dump(mode="json"))
    pair["pair_evidence"][0]["disposition"] = "pass"
    mutations.append(pair)
    rule = deepcopy(result.model_dump(mode="json"))
    rule["pair_evidence"][0]["prohibited_object_rule_id"] = "rule:stale"
    mutations.append(rule)
    semantic = deepcopy(result.model_dump(mode="json"))
    semantic["semantic_result"]["findings"][0]["disposition"] = "pass"
    mutations.append(semantic)
    message = deepcopy(result.model_dump(mode="json"))
    message["semantic_result"]["findings"][0]["message"] = "Changed but same finding ID."
    mutations.append(message)
    stale_fp = deepcopy(result.model_dump(mode="json"))
    stale_fp["result_fingerprint"] = "e" * 64
    mutations.append(stale_fp)

    for payload in mutations:
        with pytest.raises(ValidationError):
            AntennaClearanceResult.model_validate(payload)

    placed = deepcopy(result.model_dump(mode="json"))
    placed["placement_result"]["transform"]["anchor_x_mm"] += 1.0
    with pytest.raises(ValidationError, match="does not replay"):
        AntennaClearanceResult.model_validate(placed)


def test_duplicate_object_source_and_fill_provenance_ids_fail() -> None:
    placement = _placement()
    duplicate_object = (
        _object(placement, object_id="object:same", source_id="source:one"),
        _object(placement, object_id="object:same", source_id="source:two"),
    )
    duplicate_source = (
        _object(placement, object_id="object:one", source_id="source:same"),
        _object(placement, object_id="object:two", source_id="source:same"),
    )
    duplicate_fill = (
        _object(
            placement,
            object_id="object:zone:one",
            kind="zone",
            source_id="source:zone:one",
            fill_id="fill:same",
        ),
        _object(
            placement,
            object_id="object:zone:two",
            kind="zone",
            source_id="source:zone:two",
            fill_id="fill:same",
        ),
    )

    for objects, match in (
        (duplicate_object, "object identities"),
        (duplicate_source, "source provenance"),
        (duplicate_fill, "final-fill provenance"),
    ):
        with pytest.raises(ValueError, match=match):
            evaluate_antenna_clearance(placement, objects)


def test_reversal_repeat_json_and_complete_pair_matrix_are_deterministic() -> None:
    placement = _placement()
    first_object = _object(placement, object_id="object:a")
    second_object = _object(
        placement, object_id="object:b", geometry=_rect(20.0, 15.0, 21.0, 16.0)
    )

    first = evaluate_antenna_clearance(placement, (first_object, second_object))
    reversed_result = evaluate_antenna_clearance(
        placement, (second_object, first_object)
    )
    repeated = evaluate_antenna_clearance(placement, (first_object, second_object))

    assert first == reversed_result == repeated
    assert len(first.pair_evidence) == len(placement.declaration.keepouts) * 2
    assert AntennaClearanceResult.model_validate_json(first.model_dump_json()) == first
