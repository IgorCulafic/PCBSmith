"""Firing fixture 6: copper crossing a declared sensor removal region."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_copper_exposure import (
    _component,
    _install,
    _netlist,
    _pad,
)
from tests.unit.kicad.test_sensor_isolation import _case

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment, ViaSpec
from pcbsmith.kicad.copper_identity import pad_copper_source_id, via_copper_source_id
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.kicad.sensor_copper_removal import evaluate_sensor_copper_removal
from pcbsmith.kicad.sensor_isolation import evaluate_sensor_isolation_fabrication
from pcbsmith.mask_geometry import ApertureRelation, Disc, OrientedRect, Point, Polygon
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticRuleDeclaration,
)
from pcbsmith.sensor_copper_removal_ir import (
    CopperRemovalEvaluationResult,
    CopperRemovalRegionDeclaration,
    ExactFilledZoneCopper,
    ExactFilledZoneReaderPolicy,
    canonical_json,
)


def _isolation(layout: BoardLayout):
    catalog, context, _base, rules = _case()
    return evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )


def _declaration(
    isolation,
    geometry,
    *,
    layer: str = "F.Cu",
    declaration_id: str = "removal:front",
) -> CopperRemovalRegionDeclaration:
    feature = next(
        item for item in isolation.catalog.candidate.features if item.feature_kind.value == "slot"
    )
    region = next(item for item in isolation.catalog.regions if item.region_id == feature.region_id)
    limit = next(
        item
        for item in isolation.catalog.process_profile.limits
        if item.limit_id == feature.limit_id
    )
    evidence = tuple(
        sorted(
            {
                *isolation.catalog.candidate.source_binding_ids,
                *feature.source_binding_ids,
                *region.source_binding_ids,
                *limit.applicability_binding_ids,
                *limit.minimum.source_binding_ids,
            }
        )
    )
    geometry_binding_id = f"binding:{declaration_id}"
    geometry_binding = EvidenceApplicabilityBinding(
        binding_id=geometry_binding_id,
        evidence=(
            EvidenceRef(
                kind="project_design_record",
                title="Reviewed exact copper-removal geometry",
                locator=declaration_id,
                source_id=f"source:{declaration_id}",
                organization_or_author="Fixture reviewer",
                revision="1",
                local_sha256="d" * 64,
                source_status="pinned",
                locator_status="figure_verified",
                applicability_status="confirmed",
                required_conditions=("board=fixture",),
            ),
        ),
        claim_id=f"claim:{declaration_id}",
        applicability_record_id=f"applicability:{declaration_id}",
        required_conditions=("board=fixture",),
        excluded_conditions=(),
        matched_conditions=("board=fixture",),
        unmatched_conditions=(),
        geometry_source_fingerprint=geometry.semantic_fingerprint(),
        reviewer_record_id="review:copper-removal",
    )
    rule_id = f"rule:{declaration_id}"
    return CopperRemovalRegionDeclaration(
        declaration_id=declaration_id,
        candidate_id=isolation.catalog.candidate.candidate_id,
        source_feature_id=feature.feature_id,
        region_id=feature.region_id,
        rule_id=rule_id,
        layer=layer,
        geometry=geometry,
        isolation_result_fingerprint=isolation.semantic_fingerprint(),
        evidence_binding_ids=evidence,
        applicability_binding_ids=limit.applicability_binding_ids,
        geometry_evidence_binding=geometry_binding,
        geometry_rule=SemanticRuleDeclaration(
            rule_id=rule_id,
            authority=SemanticAuthorityClass.HARD_GEOMETRY,
            object_ids=(
                declaration_id,
                isolation.catalog.candidate.candidate_id,
                feature.feature_id,
            ),
            geometry_region_ids=(feature.region_id,),
            evidence_binding_ids=(geometry_binding_id,),
        ),
    )


def _reader_policy(
    *,
    reader_id: str = "kicad-final-fill-reader",
    reader_version: str = "1",
    status: str = "active",
) -> ExactFilledZoneReaderPolicy:
    return ExactFilledZoneReaderPolicy(
        policy_id="policy:fixture-final-fill-reader",
        reader_id=reader_id,
        reader_version=reader_version,
        project_qualification_record_id="qualification:fixture-final-fill-reader",
        project_qualification_artifact_sha256="c" * 64,
        reviewer_record_id="review:fixture-final-fill-reader",
        status=status,
    )


def _base_layout(**changes) -> BoardLayout:
    _catalog, _context, layout, _rules = _case()
    return replace(layout, **changes)


def _empty_netlist() -> BoardNetlist:
    return BoardNetlist(components=(), nets=())


def _evaluate(layout: BoardLayout, geometry, *, netlist: BoardNetlist | None = None):
    isolation = _isolation(layout)
    return evaluate_sensor_copper_removal(
        layout,
        netlist or _empty_netlist(),
        isolation,
        (_declaration(isolation, geometry),),
    )


@pytest.mark.parametrize(
    ("region", "relation", "disposition"),
    (
        (
            OrientedRect(center=Point(x_mm=3.0, y_mm=4.0), width_mm=1.0, height_mm=1.0),
            ApertureRelation.OVERLAP,
            SemanticDisposition.FAIL,
        ),
        (
            OrientedRect(center=Point(x_mm=8.0, y_mm=7.0), width_mm=1.0, height_mm=1.0),
            ApertureRelation.SEPARATED,
            SemanticDisposition.PASS,
        ),
        (
            OrientedRect(center=Point(x_mm=3.0, y_mm=4.5), width_mm=1.0, height_mm=0.6),
            ApertureRelation.TOUCHING,
            SemanticDisposition.PASS,
        ),
    ),
)
def test_track_overlap_separation_and_boundary_touch_policy(
    region: OrientedRect,
    relation: ApertureRelation,
    disposition: SemanticDisposition,
) -> None:
    layout = _base_layout(segments=(TrackSegment(2.0, 4.0, 4.0, 4.0, "F.Cu", "N", 0.4),))
    result = _evaluate(layout, region)

    assert result.pair_evidence[0].relation is relation
    assert result.pair_evidence[0].disposition is disposition
    assert result.source_evidence[0].disposition is disposition
    assert result.findings[0].authority is SemanticAuthorityClass.HARD_GEOMETRY
    assert result.findings[0].process_profile_id is None
    assert result.findings[0].qualified_process_record_id is None
    if relation is ApertureRelation.TOUCHING:
        assert "boundary" in result.findings[0].message


def test_via_lands_are_independent_and_opposite_layer_is_not_applicable() -> None:
    layout = _base_layout(vias=(ViaSpec(x=3.0, y=4.0, net_name="N", size_mm=1.0),))
    result = _evaluate(
        layout,
        Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.25),
    )
    indexed = {item.source_id: item for item in result.source_evidence}

    assert indexed[via_copper_source_id(0, "F.Cu")].disposition is SemanticDisposition.FAIL
    assert (
        indexed[via_copper_source_id(0, "B.Cu")].disposition
        is SemanticDisposition.NOT_APPLICABLE
    )
    assert indexed[via_copper_source_id(0, "B.Cu")].applicable_declaration_ids == ()


def test_back_side_rotated_flipped_pad_fires_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        (_pad("1", "rect", x=2.0, y=-1.0, width=2.0, height=1.0, layers=("F.Cu",)),),
    )
    component = _component()
    layout = _base_layout(
        placements=((component, 8.0),),
        part_y_mm=((component.reference, 6.0),),
        part_rotation=((component.reference, 37.0),),
        part_flip=(component.reference,),
    )
    isolation = _isolation(layout)
    # Collector's mirror/rotation is the authority; a generous exact removal
    # rectangle proves the transformed back-side pad is actually evaluated.
    declaration = _declaration(
        isolation,
        OrientedRect(center=Point(x_mm=6.0, y_mm=7.0), width_mm=8.0, height_mm=8.0),
        layer="B.Cu",
        declaration_id="removal:back",
    )
    result = evaluate_sensor_copper_removal(
        layout,
        _netlist(("U1", "1")),
        isolation,
        (declaration,),
    )

    pad = next(
        item
        for item in result.source_evidence
        if item.source_id == pad_copper_source_id("U1", 0, "B.Cu")
    )
    assert pad.disposition is SemanticDisposition.FAIL


def test_zone_intent_without_exact_final_fill_is_unverified() -> None:
    layout = _base_layout(zones=(("N", "F.Cu", (1.0, 1.0, 5.0, 5.0)),))
    result = _evaluate(
        layout,
        OrientedRect(center=Point(x_mm=3.0, y_mm=3.0), width_mm=1.0, height_mm=1.0),
    )

    assert result.physical_sources[0].source_kind.value == "zone_intent"
    assert result.pair_evidence[0].relation is None
    assert result.source_evidence[0].disposition is SemanticDisposition.UNVERIFIED
    assert result.semantic_result.summary.route_acceptance_blocked is True


def test_exact_filled_zone_overlap_fires_and_record_replays() -> None:
    layout = _base_layout(zones=(("N", "F.Cu", (1.0, 1.0, 5.0, 5.0)),))
    isolation = _isolation(layout)
    fill = ExactFilledZoneCopper.build(
        board_layout_fingerprint=board_layout_fingerprint(layout),
        zone_source_id="zone:0:copper:F.Cu",
        zone_index=0,
        zone_net_name="N",
        layer="F.Cu",
        geometry=OrientedRect(center=Point(x_mm=3.0, y_mm=3.0), width_mm=3.0, height_mm=3.0),
        reader_id="kicad-final-fill-reader",
        reader_version="1",
        reader_policy=_reader_policy(),
        source_artifact_id="fixture:filled-board",
        source_artifact_sha256="a" * 64,
    )
    result = evaluate_sensor_copper_removal(
        layout,
        _empty_netlist(),
        isolation,
        (
            _declaration(
                isolation,
                Disc(center=Point(x_mm=3.0, y_mm=3.0), radius_mm=0.25),
            ),
        ),
        exact_filled_zones=(fill,),
    )

    assert result.physical_sources[0].source_kind.value == "exact_filled_zone"
    assert result.source_evidence[0].disposition is SemanticDisposition.FAIL
    assert CopperRemovalEvaluationResult.model_validate_json(result.model_dump_json()) == result


def test_exact_fill_rejects_unqualified_reader_and_inactive_policy() -> None:
    layout = _base_layout(zones=(("N", "F.Cu", (1.0, 1.0, 5.0, 5.0)),))
    common = {
        "board_layout_fingerprint": board_layout_fingerprint(layout),
        "zone_source_id": "zone:0:copper:F.Cu",
        "zone_index": 0,
        "zone_net_name": "N",
        "layer": "F.Cu",
        "geometry": Disc(center=Point(x_mm=2.0, y_mm=2.0), radius_mm=0.5),
        "reader_version": "1",
        "source_artifact_id": "fixture:filled-board",
        "source_artifact_sha256": "a" * 64,
    }

    with pytest.raises(ValueError, match="differs from its qualified policy"):
        ExactFilledZoneCopper.build(
            **common,
            reader_id="arbitrary-reader",
            reader_policy=_reader_policy(),
        )
    with pytest.raises(ValueError, match="active qualified reader policy"):
        ExactFilledZoneCopper.build(
            **common,
            reader_id="kicad-final-fill-reader",
            reader_policy=_reader_policy(status="suspended"),
        )


@pytest.mark.parametrize(
    "field_name",
    (
        "geometry",
        "source_artifact_sha256",
        "reader_policy",
        "final_fill_record_json",
        "final_fill_record_sha256",
    ),
)
def test_exact_fill_canonical_record_rejects_tamper(field_name: str) -> None:
    layout = _base_layout(zones=(("N", "F.Cu", (1.0, 1.0, 5.0, 5.0)),))
    fill = ExactFilledZoneCopper.build(
        board_layout_fingerprint=board_layout_fingerprint(layout),
        zone_source_id="zone:0:copper:F.Cu",
        zone_index=0,
        zone_net_name="N",
        layer="F.Cu",
        geometry=Disc(center=Point(x_mm=2.0, y_mm=2.0), radius_mm=0.5),
        reader_id="kicad-final-fill-reader",
        reader_version="1",
        reader_policy=_reader_policy(),
        source_artifact_id="fixture:filled-board",
        source_artifact_sha256="a" * 64,
    )
    payload = fill.model_dump(mode="json")
    if field_name == "geometry":
        payload[field_name] = Disc(
            center=Point(x_mm=3.0, y_mm=3.0), radius_mm=0.5
        ).model_dump(mode="json")
    elif field_name == "reader_policy":
        payload[field_name]["project_qualification_artifact_sha256"] = "e" * 64
    elif field_name == "final_fill_record_json":
        parsed_record = json.loads(payload[field_name])
        parsed_record["source_artifact_id"] = "forged"
        payload[field_name] = canonical_json(parsed_record)
    else:
        payload[field_name] = "e" * 64

    with pytest.raises(ValidationError):
        ExactFilledZoneCopper.model_validate(payload)


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"zone_index": 1}, "absent zone"),
        ({"zone_source_id": "zone:9:copper:F.Cu"}, "wrong zone identity"),
        ({"zone_net_name": "OTHER"}, "wrong zone identity"),
        ({"layer": "B.Cu"}, "wrong zone identity"),
        ({"board_layout_fingerprint": "b" * 64}, "stale for this BoardLayout"),
    ),
)
def test_stale_or_wrong_exact_fill_identity_is_rejected(updates: dict, message: str) -> None:
    layout = _base_layout(zones=(("N", "F.Cu", (1.0, 1.0, 5.0, 5.0)),))
    isolation = _isolation(layout)
    fill = ExactFilledZoneCopper.build(
        board_layout_fingerprint=updates.get(
            "board_layout_fingerprint", board_layout_fingerprint(layout)
        ),
        zone_source_id=updates.get("zone_source_id", "zone:0:copper:F.Cu"),
        zone_index=updates.get("zone_index", 0),
        zone_net_name=updates.get("zone_net_name", "N"),
        layer=updates.get("layer", "F.Cu"),
        geometry=Disc(center=Point(x_mm=2.0, y_mm=2.0), radius_mm=0.5),
        reader_id="kicad-final-fill-reader",
        reader_version="1",
        reader_policy=_reader_policy(),
        source_artifact_id="artifact",
        source_artifact_sha256="a" * 64,
    )

    with pytest.raises((ValidationError, ValueError), match=message):
        evaluate_sensor_copper_removal(
            layout,
            _empty_netlist(),
            isolation,
            (_declaration(isolation, Disc(center=Point(x_mm=2.0, y_mm=2.0), radius_mm=0.2)),),
            exact_filled_zones=(fill,),
        )


def test_unsupported_pad_geometry_is_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, (_pad("1", "custom", custom=True),))
    component = _component()
    layout = _base_layout(
        placements=((component, 3.0),),
        part_y_mm=((component.reference, 4.0),),
    )
    result = _evaluate(
        layout,
        OrientedRect(center=Point(x_mm=3.0, y_mm=4.0), width_mm=2.0, height_mm=2.0),
        netlist=_netlist(("U1", "1")),
    )

    assert result.source_evidence[0].disposition is SemanticDisposition.UNVERIFIED
    assert result.pair_evidence[0].verification.value == "unsupported"


def test_wrong_isolation_candidate_or_feature_authority_is_unverified() -> None:
    layout = _base_layout(segments=(TrackSegment(2.0, 4.0, 4.0, 4.0, "F.Cu", "N", 0.4),))
    isolation = _isolation(layout)
    declaration = _declaration(
        isolation,
        Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.2),
    )
    altered = (
        declaration.model_copy(update={"isolation_result_fingerprint": "e" * 64}),
        declaration.model_copy(update={"candidate_id": "candidate:wrong"}),
        declaration.model_copy(update={"source_feature_id": "feature:web"}),
    )

    for item in altered:
        result = evaluate_sensor_copper_removal(
            layout,
            _empty_netlist(),
            isolation,
            (item,),
        )
        assert result.pair_evidence[0].authority_complete is False
        assert result.source_evidence[0].disposition is SemanticDisposition.UNVERIFIED


def test_process_rule_substitution_cannot_authorize_removal_geometry() -> None:
    layout = _base_layout(segments=(TrackSegment(2.0, 4.0, 4.0, 4.0, "F.Cu", "N", 0.4),))
    isolation = _isolation(layout)
    declaration = _declaration(
        isolation,
        Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.2),
    )
    process_rule = SemanticRuleDeclaration(
        rule_id=declaration.rule_id,
        authority=SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
        object_ids=declaration.geometry_rule.object_ids,
        evidence_binding_ids=(declaration.geometry_evidence_binding.binding_id,),
        process_profile_id=isolation.catalog.process_profile.profile_id,
        qualified_process_record_id=(
            isolation.catalog.process_profile.qualified_process_record_id
        ),
    )
    forged = declaration.model_copy(update={"geometry_rule": process_rule})

    result = evaluate_sensor_copper_removal(
        layout,
        _empty_netlist(),
        isolation,
        (forged,),
    )

    assert result.pair_evidence[0].authority_complete is False
    assert result.pair_evidence[0].disposition is SemanticDisposition.UNVERIFIED
    assert result.findings[0].authority is SemanticAuthorityClass.HARD_GEOMETRY
    assert result.findings[0].process_profile_id is None
    assert result.findings[0].qualified_process_record_id is None


def test_incomplete_mismatched_or_wrong_rule_geometry_binding_is_unverified() -> None:
    layout = _base_layout(segments=(TrackSegment(2.0, 4.0, 4.0, 4.0, "F.Cu", "N", 0.4),))
    isolation = _isolation(layout)
    declaration = _declaration(
        isolation,
        Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.2),
    )
    binding = declaration.geometry_evidence_binding
    incomplete = binding.model_copy(
        update={
            "matched_conditions": (),
            "unmatched_conditions": binding.required_conditions,
            "reviewer_record_id": None,
        }
    )
    mismatched = binding.model_copy(update={"geometry_source_fingerprint": "e" * 64})
    wrong_rule = declaration.geometry_rule.model_copy(update={"rule_id": "rule:wrong"})
    wrong_binding_rule = declaration.geometry_rule.model_copy(
        update={"evidence_binding_ids": ("binding:wrong",)}
    )
    altered = (
        declaration.model_copy(update={"geometry_evidence_binding": incomplete}),
        declaration.model_copy(update={"geometry_evidence_binding": mismatched}),
        declaration.model_copy(update={"geometry_rule": wrong_rule}),
        declaration.model_copy(update={"geometry_rule": wrong_binding_rule}),
    )

    for item in altered:
        result = evaluate_sensor_copper_removal(
            layout,
            _empty_netlist(),
            isolation,
            (item,),
        )
        assert result.pair_evidence[0].authority_complete is False
        assert result.pair_evidence[0].disposition is SemanticDisposition.UNVERIFIED


def test_missing_geometry_binding_or_rule_is_rejected() -> None:
    layout = _base_layout()
    isolation = _isolation(layout)
    declaration = _declaration(
        isolation,
        Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.2),
    )
    for field_name in ("geometry_evidence_binding", "geometry_rule"):
        payload = declaration.model_dump(mode="json")
        del payload[field_name]
        with pytest.raises(ValidationError):
            CopperRemovalRegionDeclaration.model_validate(payload)


def test_duplicate_physical_source_ids_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, (_pad("1"),))
    component = _component()
    layout = _base_layout(
        placements=((component, 3.0), (component, 6.0)),
        part_y_mm=((component.reference, 4.0),),
    )
    isolation = _isolation(layout)

    with pytest.raises(ValueError, match="duplicate physical copper source identity"):
        evaluate_sensor_copper_removal(
            layout,
            _netlist(("U1", "1")),
            isolation,
            (_declaration(isolation, Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=1.0)),),
        )


def test_reversed_declarations_are_canonical_and_deterministic() -> None:
    layout = _base_layout(vias=(ViaSpec(x=3.0, y=4.0, net_name="N", size_mm=1.0),))
    isolation = _isolation(layout)
    front = _declaration(
        isolation,
        Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.2),
    )
    back = _declaration(
        isolation,
        Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.2),
        layer="B.Cu",
        declaration_id="removal:back",
    )
    first = evaluate_sensor_copper_removal(layout, _empty_netlist(), isolation, (front, back))
    second = evaluate_sensor_copper_removal(layout, _empty_netlist(), isolation, (back, front))

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_ordered_polygon_geometry_remains_identity_sensitive() -> None:
    layout = _base_layout(segments=(TrackSegment(2.0, 4.0, 4.0, 4.0, "F.Cu", "N", 0.4),))
    isolation = _isolation(layout)
    vertices = (
        Point(x_mm=2.5, y_mm=3.5),
        Point(x_mm=3.5, y_mm=3.5),
        Point(x_mm=3.5, y_mm=4.5),
        Point(x_mm=2.5, y_mm=4.5),
    )
    forward = _declaration(isolation, Polygon(vertices=vertices))
    reverse = _declaration(isolation, Polygon(vertices=tuple(reversed(vertices))))

    first = evaluate_sensor_copper_removal(layout, _empty_netlist(), isolation, (forward,))
    second = evaluate_sensor_copper_removal(layout, _empty_netlist(), isolation, (reverse,))

    assert first.source_evidence == second.source_evidence
    assert first.declarations != second.declarations
    assert first.input_fingerprint != second.input_fingerprint


@pytest.mark.parametrize(
    "field_name",
    (
        "board_layout_snapshot_json",
        "board_netlist_snapshot_json",
        "declarations",
        "physical_sources",
        "pair_evidence",
        "source_evidence",
        "findings",
        "isolation_result",
    ),
)
def test_retained_inputs_and_derived_outputs_reject_tamper(field_name: str) -> None:
    layout = _base_layout(segments=(TrackSegment(2.0, 4.0, 4.0, 4.0, "F.Cu", "N", 0.4),))
    result = _evaluate(
        layout,
        Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.2),
    )
    if field_name.endswith("snapshot_json"):
        parsed = json.loads(getattr(result, field_name))
        if field_name.startswith("board_layout"):
            parsed["width_mm"] += 1.0
        else:
            parsed["nets"].append({"name": "FORGED", "nodes": []})
        forged = canonical_json(parsed)
    elif field_name == "declarations":
        forged = (
            result.declarations[0].model_copy(
                update={"geometry": Disc(center=Point(x_mm=9.0, y_mm=7.0), radius_mm=0.2)}
            ),
        )
    elif field_name == "isolation_result":
        forged = result.isolation_result.model_copy(update={"board_layout_fingerprint": "f" * 64})
    elif field_name == "findings":
        forged = (
            result.findings[0].model_copy(update={"message": "forged message"}),
            *result.findings[1:],
        )
    else:
        values = getattr(result, field_name)
        forged = (values[0].model_copy(update={"source_id": "forged"}), *values[1:])
    with pytest.raises((ValidationError, ValueError)):
        CopperRemovalEvaluationResult.model_validate_json(
            result.model_copy(update={field_name: forged}).model_dump_json()
        )


def test_result_is_detached_from_caller_collections() -> None:
    layout = _base_layout(segments=(TrackSegment(2.0, 4.0, 4.0, 4.0, "F.Cu", "N", 0.4),))
    isolation = _isolation(layout)
    declarations = [
        _declaration(
            isolation,
            Disc(center=Point(x_mm=3.0, y_mm=4.0), radius_mm=0.2),
        )
    ]
    result = evaluate_sensor_copper_removal(layout, _empty_netlist(), isolation, declarations)
    before = result.model_dump_json()

    declarations.clear()
    assert result.model_dump_json() == before
