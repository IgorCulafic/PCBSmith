"""R6.4 firing fixtures for replay-bound connector zoning."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.connector_zone_ir import (
    ConnectorLocalGeometry,
    ConnectorPadGeometry,
    ConnectorRequirement,
    ConnectorRequirementKind,
    ConnectorRequirementModel,
    ConnectorRole,
    ConnectorZoneDeclaration,
    ConnectorZoneResult,
    connector_declaration_context_fingerprint,
    connector_threshold_context_fingerprint,
    fingerprint,
)
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.connector_zone import evaluate_connector_zone, outline_edges
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticQuantity,
    SemanticRegion,
    SemanticVerification,
)

OUTLINE = (
    (0.0, 0.0),
    (20.0, 0.0),
    (20.0, 20.0),
    (12.0, 20.0),
    (12.0, 5.0),
    (8.0, 5.0),
    (8.0, 20.0),
    (0.0, 20.0),
)


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _board(
    *, x: float = 7.0, y: float = 6.0, rotation: float = 0.0, back: bool = False
) -> tuple[BoardLayout, BoardNetlist]:
    component = BoardComponent("J1", "USB", "Connector:Fixture", "uuid:j1")
    return (
        BoardLayout(
            placements=((component, x),),
            segments=(),
            vias=(),
            width_mm=20,
            height_mm=20,
            parts_row_y_mm=y,
            part_rotation=(("J1", rotation),) if rotation else (),
            part_flip=("J1",) if back else (),
            outline=OUTLINE,
        ),
        BoardNetlist(
            components=(component,),
            nets=(BoardNet("GND", (("J1", "1"),)), BoardNet("D+", (("J1", "2"),))),
        ),
    )


def _binding(
    context_fp: str,
    *,
    complete: bool = True,
    binding_id: str = "binding:connector",
) -> EvidenceApplicabilityBinding:
    conditions = ("connector-revision=1",) if complete else ()
    return EvidenceApplicabilityBinding(
        binding_id=binding_id,
        evidence=(
            EvidenceRef(
                kind="component_datasheet",
                title="Connector fixture drawing",
                locator="figure:1",
                source_id="source:connector",
                organization_or_author="Fixture Vendor",
                revision="1",
                local_sha256="a" * 64,
                source_status="pinned",
                locator_status="figure_bound",
                applicability_status="confirmed",
                required_conditions=conditions,
            ),
        ),
        claim_id=f"claim:{binding_id}",
        applicability_record_id=f"applicability:{binding_id}",
        required_conditions=conditions,
        excluded_conditions=(),
        matched_conditions=conditions,
        unmatched_conditions=(),
        geometry_source_fingerprint=context_fp,
        reviewer_record_id="review:connector" if complete else None,
    )


def _geometry() -> ConnectorLocalGeometry:
    fields = {
        "reference": "J1",
        "installed_footprint_id": "Connector:Fixture",
        "component_uuid_path": "uuid:j1",
        "source_file_sha256": "b" * 64,
        "source_binding_id": "binding:connector",
        "body_region_id": "body:J1",
        "body_compound": _rect(-0.5, -0.25, 0.75, 0.5),
        "body_layers": ("F.Fab",),
        "pads": (
            ConnectorPadGeometry(
                pad_id="1", compound=_rect(-0.4, -0.3, -0.1, 0.3), layers=("F.Cu",)
            ),
            ConnectorPadGeometry(pad_id="2", compound=_rect(0.1, -0.3, 0.4, 0.3), layers=("F.Cu",)),
        ),
    }
    provisional = ConnectorLocalGeometry.model_construct(**fields, geometry_fingerprint="0" * 64)
    return ConnectorLocalGeometry(
        **fields,
        geometry_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"geometry_fingerprint"})
        ),
    )


def _region(
    region_id: str,
    compound: ExactPlanarCompound,
    source_binding_ids: tuple[str, ...] = ("binding:connector",),
) -> SemanticRegion:
    return SemanticRegion(
        region_id=region_id,
        coordinate_space="board",
        owner_reference=None,
        compound=compound,
        layers=("F.Cu", "B.Cu"),
        verification=SemanticVerification.EXACT,
        maximum_error_mm=None,
        source_binding_ids=source_binding_ids,
    )


def _requirements() -> tuple[ConnectorRequirement, ...]:
    common = {
        "authority": SemanticAuthorityClass.HARD_GEOMETRY,
        "source_binding_ids": ("binding:connector",),
    }
    return (
        ConnectorRequirement(
            requirement_id="requirement:filter",
            rule_id="rule:filter",
            kind=ConnectorRequirementKind.FILTER_CHAIN,
            expected_component_order=("J1",),
            **common,
        ),
        ConnectorRequirement(
            requirement_id="requirement:ground",
            rule_id="rule:ground",
            kind=ConnectorRequirementKind.GROUND_PIN_SPREAD,
            minimum_ground_pin_count=2,
            minimum_ground_pin_spread=SemanticQuantity(
                quantity_id="quantity:ground-spread",
                value=0.2,
                unit="mm",
                source_binding_ids=("binding:connector",),
            ),
            **common,
        ),
        ConnectorRequirement(
            requirement_id="requirement:oscillator",
            rule_id="rule:oscillator",
            kind=ConnectorRequirementKind.OSCILLATOR_SEPARATION,
            minimum_separation=SemanticQuantity(
                quantity_id="quantity:oscillator-separation",
                value=3,
                unit="mm",
                source_binding_ids=("binding:connector",),
            ),
            **common,
        ),
        ConnectorRequirement(
            requirement_id="requirement:enclosure",
            rule_id="rule:enclosure",
            kind=ConnectorRequirementKind.ENCLOSURE_ACCESS,
            **common,
        ),
    )


def _declaration(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    role: ConnectorRole = ConnectorRole.OFF_BOARD_IO,
    allowed_edge_id: str | None = None,
    zone: ExactPlanarCompound | None = None,
    requirements: bool = False,
    maximum: bool = False,
    complete_binding: bool = True,
) -> ConnectorZoneDeclaration:
    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    layout_fp = board_layout_snapshot_fingerprint(layout_json)
    netlist_fp = board_netlist_snapshot_fingerprint(netlist_json)
    edge_id = allowed_edge_id or outline_edges(layout)[0][0]
    zone_region = _region("zone:io", zone or _rect(5, 4.5, 9, 8))
    optional = _requirements() if requirements else (None,) * 4
    maximum_quantity = (
        SemanticQuantity(
            quantity_id="quantity:edge",
            value=1,
            unit="mm",
            source_binding_ids=("binding:connector",),
        )
        if maximum
        else None
    )
    context_fp = connector_threshold_context_fingerprint(
        layout_fp,
        netlist_fp,
        ("J1",),
        role,
        zone_region.semantic_fingerprint(),
        (edge_id,),
        tuple(
            item
            for item in (
                maximum_quantity.semantic_fingerprint() if maximum_quantity else None,
                *(
                    requirement.semantic_fingerprint()
                    for requirement in optional
                    if requirement is not None
                ),
            )
            if item is not None
        ),
    )
    return ConnectorZoneDeclaration(
        declaration_id="declaration:connector",
        zone_id="zone:io",
        board_layout_snapshot_json=layout_json,
        board_netlist_snapshot_json=netlist_json,
        board_layout_snapshot_fingerprint=layout_fp,
        board_netlist_snapshot_fingerprint=netlist_fp,
        connector_references=("J1",),
        connector_role=role,
        zone_region=zone_region,
        allowed_edge_ids=(edge_id,),
        maximum_body_to_edge_distance=maximum_quantity,
        connector_geometries=(_geometry(),),
        body_zone_rule_id="rule:body-zone",
        pad_zone_rule_id="rule:pad-zone",
        body_material_rule_id="rule:body-material",
        pad_material_rule_id="rule:pad-material",
        edge_rule_id="rule:edge",
        filter_chain_requirement=optional[0],
        ground_pin_spread_requirement=optional[1],
        oscillator_separation_requirement=optional[2],
        enclosure_access_requirement=optional[3],
        evidence_bindings=(_binding(context_fp, complete=complete_binding),),
    )


def _edge_by_points(
    layout: BoardLayout, first: tuple[float, float], second: tuple[float, float]
) -> str:
    wanted = {first, second}
    return next(edge_id for edge_id, start, end in outline_edges(layout) if {start, end} == wanted)


def test_shaped_outline_chooses_disallowed_not_rectangular_bbox_edge() -> None:
    layout, netlist = _board()
    bottom = _edge_by_points(layout, (0, 0), (20, 0))
    notch = _edge_by_points(layout, (8, 5), (8, 20))

    failed = evaluate_connector_zone(
        layout, netlist, _declaration(layout, netlist, allowed_edge_id=bottom)
    )
    passed = evaluate_connector_zone(
        layout, netlist, _declaration(layout, netlist, allowed_edge_id=notch)
    )

    failed_edge = next(item for item in failed.geometry_evidence if item.kind == "edge_access")
    passed_edge = next(item for item in passed.geometry_evidence if item.kind == "edge_access")
    assert failed_edge.edge_id == notch
    assert failed_edge.disposition is SemanticDisposition.FAIL
    assert passed_edge.disposition is SemanticDisposition.PASS


@pytest.mark.parametrize(
    ("rotation", "back", "expected"),
    [
        (90, False, ((6.75, 5.25), (7.5, 5.25), (7.5, 6.5), (6.75, 6.5))),
        (90, True, ((6.75, 5.5), (7.5, 5.5), (7.5, 6.75), (6.75, 6.75))),
    ],
)
def test_exact_front_and_back_rotated_transforms(
    rotation: float, back: bool, expected: tuple[tuple[float, float], ...]
) -> None:
    layout, netlist = _board(rotation=rotation, back=back)
    result = evaluate_connector_zone(layout, netlist, _declaration(layout, netlist))
    assert set(result.placed_geometries[0].body_transform.compound.polygons[0].outer) == set(
        expected
    )


def test_on_board_module_is_not_subject_to_off_board_zone_or_edge_rules() -> None:
    layout, netlist = _board(x=3, y=3)
    result = evaluate_connector_zone(
        layout,
        netlist,
        _declaration(
            layout, netlist, role=ConnectorRole.ON_BOARD_MODULE, zone=_rect(10, 10, 11, 11)
        ),
    )
    by_kind = {item.kind: item.disposition for item in result.geometry_evidence}
    assert by_kind["body_zone"] is SemanticDisposition.NOT_APPLICABLE
    assert by_kind["pad_zone"] is SemanticDisposition.NOT_APPLICABLE
    assert by_kind["edge_access"] is SemanticDisposition.NOT_APPLICABLE
    assert by_kind["body_material"] is SemanticDisposition.PASS


def test_body_zone_containment_is_independent_from_allowed_edge_access() -> None:
    layout, netlist = _board()
    notch = _edge_by_points(layout, (8, 5), (8, 20))
    result = evaluate_connector_zone(
        layout,
        netlist,
        _declaration(layout, netlist, allowed_edge_id=notch, zone=_rect(1, 1, 2, 2)),
    )
    by_kind = {item.kind: item.disposition for item in result.geometry_evidence}
    assert by_kind["body_zone"] is SemanticDisposition.FAIL
    assert by_kind["edge_access"] is SemanticDisposition.PASS


def test_four_optional_requirements_stay_distinct_and_missing_models_are_unverified() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, requirements=True)
    missing = evaluate_connector_zone(layout, netlist, declaration)
    assert {item.requirement_id for item in missing.requirement_evidence} == {
        "requirement:filter",
        "requirement:ground",
        "requirement:oscillator",
        "requirement:enclosure",
    }
    assert all(
        item.disposition is SemanticDisposition.UNVERIFIED for item in missing.requirement_evidence
    )
    common = {
        "board_layout_snapshot_fingerprint": declaration.board_layout_snapshot_fingerprint,
        "board_netlist_snapshot_fingerprint": declaration.board_netlist_snapshot_fingerprint,
        "source_binding_ids": ("binding:connector",),
    }
    models = (
        ConnectorRequirementModel(
            model_id="model:filter",
            requirement_id="requirement:filter",
            kind=ConnectorRequirementKind.FILTER_CHAIN,
            ordered_component_refs=("J1",),
            **common,
        ),
        ConnectorRequirementModel(
            model_id="model:ground",
            requirement_id="requirement:ground",
            kind=ConnectorRequirementKind.GROUND_PIN_SPREAD,
            ground_pad_ids=("J1:1",),
            **common,
        ),
        ConnectorRequirementModel(
            model_id="model:osc",
            requirement_id="requirement:oscillator",
            kind=ConnectorRequirementKind.OSCILLATOR_SEPARATION,
            exact_region=_region("region:osc", _rect(11, 5, 12, 6)),
            **common,
        ),
        ConnectorRequirementModel(
            model_id="model:enclosure",
            requirement_id="requirement:enclosure",
            kind=ConnectorRequirementKind.ENCLOSURE_ACCESS,
            exact_region=_region("region:access", _rect(6.8, 5.8, 7.2, 6.2)),
            **common,
        ),
    )
    result = evaluate_connector_zone(layout, netlist, declaration, reversed(models))
    assert result == evaluate_connector_zone(layout, netlist, declaration, models)
    by_id = {item.requirement_id: item for item in result.requirement_evidence}
    assert by_id["requirement:filter"].disposition is SemanticDisposition.PASS
    assert by_id["requirement:ground"].disposition is SemanticDisposition.FAIL
    assert by_id["requirement:oscillator"].disposition is SemanticDisposition.PASS
    assert by_id["requirement:enclosure"].disposition is SemanticDisposition.PASS
    assert len({item.rule_id for item in result.requirement_evidence}) == 4


def test_hard_model_effective_sources_are_known_reviewed_current_and_emitted() -> None:
    layout, netlist = _board()
    base = _declaration(layout, netlist, requirements=True)
    context_fp = connector_declaration_context_fingerprint(base)
    common = {
        "board_layout_snapshot_fingerprint": base.board_layout_snapshot_fingerprint,
        "board_netlist_snapshot_fingerprint": base.board_netlist_snapshot_fingerprint,
    }

    def with_binding(binding: EvidenceApplicabilityBinding) -> ConnectorZoneDeclaration:
        payload = base.model_dump(mode="json")
        payload["evidence_bindings"].append(binding.model_dump(mode="json"))
        return ConnectorZoneDeclaration.model_validate(payload)

    unreviewed = with_binding(
        _binding(context_fp, complete=False, binding_id="binding:model-unreviewed")
    )
    unreviewed_model = ConnectorRequirementModel(
        model_id="model:filter:unreviewed",
        requirement_id="requirement:filter",
        kind=ConnectorRequirementKind.FILTER_CHAIN,
        source_binding_ids=("binding:model-unreviewed",),
        ordered_component_refs=("J1",),
        **common,
    )
    with pytest.raises(ValueError, match="pinned applicable reviewed"):
        evaluate_connector_zone(layout, netlist, unreviewed, (unreviewed_model,))

    stale = with_binding(_binding("f" * 64, binding_id="binding:model-stale"))
    stale_model = ConnectorRequirementModel(
        model_id="model:enclosure:stale-region-source",
        requirement_id="requirement:enclosure",
        kind=ConnectorRequirementKind.ENCLOSURE_ACCESS,
        source_binding_ids=("binding:connector",),
        exact_region=_region(
            "region:access:stale",
            _rect(6.8, 5.8, 7.2, 6.2),
            ("binding:model-stale",),
        ),
        **common,
    )
    with pytest.raises(ValueError, match="model evidence has stale context"):
        evaluate_connector_zone(layout, netlist, stale, (stale_model,))

    escaped_region = ConnectorRequirementModel(
        model_id="model:enclosure:unknown-region-source",
        requirement_id="requirement:enclosure",
        kind=ConnectorRequirementKind.ENCLOSURE_ACCESS,
        source_binding_ids=("binding:connector",),
        exact_region=_region(
            "region:access:unknown",
            _rect(6.8, 5.8, 7.2, 6.2),
            ("binding:unknown-region-source",),
        ),
        **common,
    )
    with pytest.raises(ValueError, match="references unknown evidence"):
        evaluate_connector_zone(layout, netlist, base, (escaped_region,))

    current = with_binding(_binding(context_fp, binding_id="binding:model-current"))
    current_model = ConnectorRequirementModel(
        model_id="model:filter:current",
        requirement_id="requirement:filter",
        kind=ConnectorRequirementKind.FILTER_CHAIN,
        source_binding_ids=("binding:model-current",),
        ordered_component_refs=("J1",),
        **common,
    )
    result = evaluate_connector_zone(layout, netlist, current, (current_model,))
    finding = next(
        item for item in result.semantic_result.findings if item.rule_id == "rule:filter"
    )
    assert finding.evidence_binding_ids == (
        "binding:connector",
        "binding:model-current",
    )


def test_hard_threshold_rejects_missing_conditions_and_stale_context() -> None:
    layout, netlist = _board()
    with pytest.raises(ValidationError, match="pinned applicable reviewed"):
        _declaration(layout, netlist, maximum=True, complete_binding=False)
    declaration = _declaration(layout, netlist, maximum=True)
    payload = declaration.model_dump(mode="json")
    payload["evidence_bindings"][0]["geometry_source_fingerprint"] = "f" * 64
    with pytest.raises(ValidationError, match="stale or inexact context"):
        ConnectorZoneDeclaration.model_validate(payload)
    stale_threshold = declaration.model_dump(mode="json")
    stale_threshold["maximum_body_to_edge_distance"]["value"] = 2
    with pytest.raises(ValidationError, match="stale or inexact context"):
        ConnectorZoneDeclaration.model_validate(stale_threshold)


def test_hard_filter_and_enclosure_changes_invalidate_exact_context() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, requirements=True)

    stale_filter = declaration.model_dump(mode="json")
    stale_filter["filter_chain_requirement"]["expected_component_order"] = ["J1", "F1"]
    with pytest.raises(ValidationError, match="stale or inexact context"):
        ConnectorZoneDeclaration.model_validate(stale_filter)

    stale_enclosure = declaration.model_dump(mode="json")
    stale_enclosure["enclosure_access_requirement"]["rule_id"] = "rule:enclosure:changed"
    with pytest.raises(ValidationError, match="stale or inexact context"):
        ConnectorZoneDeclaration.model_validate(stale_enclosure)


def test_json_order_tamper_and_caller_immutability() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, requirements=True)
    before_layout = canonical_board_layout_snapshot_json(layout)
    before_netlist = canonical_board_netlist_snapshot_json(netlist)
    result = evaluate_connector_zone(layout, netlist, declaration)
    assert ConnectorZoneResult.model_validate_json(result.model_dump_json()) == result
    assert canonical_board_layout_snapshot_json(layout) == before_layout
    assert canonical_board_netlist_snapshot_json(netlist) == before_netlist
    tampered = deepcopy(result.model_dump(mode="json"))
    tampered["geometry_evidence"][0]["disposition"] = "fail"
    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        ConnectorZoneResult.model_validate(tampered)


def test_snapshot_source_edge_and_transform_tamper_are_rejected() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist)
    payload = declaration.model_dump(mode="json")

    stale_snapshot = deepcopy(payload)
    stale_snapshot["board_layout_snapshot_fingerprint"] = "f" * 64
    with pytest.raises(ValidationError, match="snapshot fingerprint is stale"):
        ConnectorZoneDeclaration.model_validate(stale_snapshot)

    stale_source = deepcopy(payload)
    stale_source["connector_geometries"][0]["source_file_sha256"] = "c" * 64
    with pytest.raises(ValidationError, match="local geometry fingerprint is stale"):
        ConnectorZoneDeclaration.model_validate(stale_source)

    stale_edge = deepcopy(payload)
    stale_edge["allowed_edge_ids"] = ["outline-edge:" + "f" * 64]
    with pytest.raises(ValidationError, match="absent from the actual shaped outline"):
        ConnectorZoneDeclaration.model_validate(stale_edge)

    result = evaluate_connector_zone(layout, netlist, declaration)
    stale_transform = deepcopy(result.model_dump(mode="json"))
    polygon = stale_transform["placed_geometries"][0]["body_transform"]["compound"]["polygons"][0][
        "outer"
    ]
    polygon[0][0] += 0.1
    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        ConnectorZoneResult.model_validate(stale_transform)
