"""Exact shaped-outline and placed-geometry evaluation for R6 connector zones."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from itertools import combinations
from typing import Any

from pcbsmith.connector_zone_ir import (
    ConnectorGeometryEvidence,
    ConnectorPlacedGeometry,
    ConnectorRequirement,
    ConnectorRequirementEvidence,
    ConnectorRequirementKind,
    ConnectorRequirementModel,
    ConnectorRole,
    ConnectorZoneDeclaration,
    ConnectorZoneResult,
    connector_declaration_context_fingerprint,
    evidence_binding_is_complete,
    fingerprint,
    outline_edge_id,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
)
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacementTransform,
    PlacementTransformAuthority,
    PlanarRelation,
    compound_distance_witness,
    compound_inside_polygon,
    compound_relation,
    compound_to_segment_distance_witness,
    diagnostic_distance_mm,
    transform_compound_bounded,
)
from pcbsmith.placement_pose_authority import derive_exact_placement_poses
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticVerification,
)


def outline_edges(
    layout: BoardLayout,
) -> tuple[tuple[str, tuple[float, float], tuple[float, float]], ...]:
    """Canonical actual shaped-outline segments and their stable identities."""

    points = layout.outline or (
        (0.0, 0.0),
        (layout.width_mm, 0.0),
        (layout.width_mm, layout.height_mm),
        (0.0, layout.height_mm),
    )
    return tuple(
        sorted(
            (
                outline_edge_id(points[index], points[(index + 1) % len(points)]),
                points[index],
                points[(index + 1) % len(points)],
            )
            for index in range(len(points))
        )
    )


def _inside_compound(subject: ExactPlanarCompound, allowed: ExactPlanarCompound) -> bool:
    return all(
        any(
            compound_inside_polygon(ExactPlanarCompound(polygons=(polygon,)), container)
            for container in allowed.polygons
        )
        for polygon in subject.polygons
    )


def _inside_material(
    subject: ExactPlanarCompound,
    outer: ExactPlanarPolygon,
    cutouts: tuple[ExactPlanarCompound, ...],
) -> bool:
    return compound_inside_polygon(subject, outer) and all(
        compound_relation(subject, cutout) is PlanarRelation.DISJOINT for cutout in cutouts
    )


def _disposition(authority: SemanticAuthorityClass, passed: bool) -> SemanticDisposition:
    if authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS:
        return SemanticDisposition.ADVISORY
    return SemanticDisposition.PASS if passed else SemanticDisposition.FAIL


def _placed(
    declaration: ConnectorZoneDeclaration, layout: BoardLayout
) -> tuple[ConnectorPlacedGeometry, ...]:
    poses = {item.reference: item for item in derive_exact_placement_poses(layout)}
    result: list[ConnectorPlacedGeometry] = []
    for geometry in declaration.connector_geometries:
        pose = poses[geometry.reference]
        transform = PlacementTransform(
            anchor_x_mm=pose.x_mm,
            anchor_y_mm=pose.y_mm,
            rotation_deg=pose.rotation_deg,
            side="back" if pose.flipped else "front",
        )
        body = transform_compound_bounded(geometry.body_compound, transform)
        pads = tuple(
            (pad.pad_id, transform_compound_bounded(pad.compound, transform))
            for pad in geometry.pads
        )
        result.append(
            ConnectorPlacedGeometry(
                source_geometry=geometry,
                body_transform=body,
                pad_transforms=pads,
            )
        )
    return tuple(result)


def _geometry_evidence(
    declaration: ConnectorZoneDeclaration,
    layout: BoardLayout,
    placed: tuple[ConnectorPlacedGeometry, ...],
) -> tuple[ConnectorGeometryEvidence, ...]:
    assert declaration.zone_region.compound is not None
    points = layout.outline or (
        (0.0, 0.0),
        (layout.width_mm, 0.0),
        (layout.width_mm, layout.height_mm),
        (0.0, layout.height_mm),
    )
    outer = ExactPlanarPolygon(outer=points)
    cutouts = tuple(
        ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=item.points),))
        for item in layout.cutouts
    )
    edges = outline_edges(layout)
    evidence: list[ConnectorGeometryEvidence] = []
    off_board = declaration.connector_role is not ConnectorRole.ON_BOARD_MODULE
    for item in placed:
        reference = item.source_geometry.reference
        exact = item.body_transform.authority is PlacementTransformAuthority.EXACT and all(
            transform.authority is PlacementTransformAuthority.EXACT
            for _, transform in item.pad_transforms
        )
        pad_compounds = tuple(transform.compound for _, transform in item.pad_transforms)
        specifications = (
            ("body_zone", declaration.body_zone_rule_id),
            ("pad_zone", declaration.pad_zone_rule_id),
            ("body_material", declaration.body_material_rule_id),
            ("pad_material", declaration.pad_material_rule_id),
        )
        if not exact:
            for kind, rule_id in specifications:
                evidence.append(
                    ConnectorGeometryEvidence(
                        evidence_id=f"connector:{reference}:{kind}",
                        reference=reference,
                        kind=kind,
                        rule_id=rule_id,
                        verification=SemanticVerification.BOUNDED_APPROXIMATION,
                        disposition=SemanticDisposition.UNVERIFIED,
                    )
                )
        else:
            zone_body = _inside_compound(
                item.body_transform.compound, declaration.zone_region.compound
            )
            zone_pads = all(
                _inside_compound(compound, declaration.zone_region.compound)
                for compound in pad_compounds
            )
            material_body = _inside_material(item.body_transform.compound, outer, cutouts)
            material_pads = all(
                _inside_material(compound, outer, cutouts) for compound in pad_compounds
            )
            values = (zone_body, zone_pads, material_body, material_pads)
            for (kind, rule_id), passed in zip(specifications, values, strict=True):
                not_applicable = not off_board and kind in {"body_zone", "pad_zone"}
                evidence.append(
                    ConnectorGeometryEvidence(
                        evidence_id=f"connector:{reference}:{kind}",
                        reference=reference,
                        kind=kind,
                        rule_id=rule_id,
                        verification=SemanticVerification.EXACT,
                        disposition=(
                            SemanticDisposition.NOT_APPLICABLE
                            if not_applicable
                            else (SemanticDisposition.PASS if passed else SemanticDisposition.FAIL)
                        ),
                    )
                )
        if not off_board:
            evidence.append(
                ConnectorGeometryEvidence(
                    evidence_id=f"connector:{reference}:edge_access",
                    reference=reference,
                    kind="edge_access",
                    rule_id=declaration.edge_rule_id,
                    verification=SemanticVerification.EXACT,
                    disposition=SemanticDisposition.NOT_APPLICABLE,
                )
            )
        elif item.body_transform.authority is not PlacementTransformAuthority.EXACT:
            evidence.append(
                ConnectorGeometryEvidence(
                    evidence_id=f"connector:{reference}:edge_access",
                    reference=reference,
                    kind="edge_access",
                    rule_id=declaration.edge_rule_id,
                    verification=SemanticVerification.BOUNDED_APPROXIMATION,
                    disposition=SemanticDisposition.UNVERIFIED,
                )
            )
        else:
            candidates = tuple(
                (
                    compound_to_segment_distance_witness(item.body_transform.compound, start, end),
                    edge_id,
                )
                for edge_id, start, end in edges
            )
            witness, edge_id = min(candidates, key=lambda pair: (pair[0].squared_distance, pair[1]))
            passed = edge_id in declaration.allowed_edge_ids
            maximum = declaration.maximum_body_to_edge_distance
            if maximum is not None:
                threshold = Fraction(str(maximum.value))
                passed = passed and witness.squared_distance <= threshold * threshold
            evidence.append(
                ConnectorGeometryEvidence(
                    evidence_id=f"connector:{reference}:edge_access",
                    reference=reference,
                    kind="edge_access",
                    rule_id=declaration.edge_rule_id,
                    edge_id=edge_id,
                    squared_distance_numerator=witness.squared_distance.numerator,
                    squared_distance_denominator=witness.squared_distance.denominator,
                    body_witness=tuple(str(value) for value in witness.compound_point),
                    edge_witness=tuple(str(value) for value in witness.segment_point),
                    verification=SemanticVerification.EXACT,
                    disposition=_disposition(declaration.maximum_edge_authority, passed),
                )
            )
    return tuple(sorted(evidence, key=lambda item: item.evidence_id))


def _requirements(declaration: ConnectorZoneDeclaration) -> tuple[ConnectorRequirement, ...]:
    return tuple(
        item
        for item in (
            declaration.filter_chain_requirement,
            declaration.ground_pin_spread_requirement,
            declaration.oscillator_separation_requirement,
            declaration.enclosure_access_requirement,
        )
        if item is not None
    )


def _requirement_evidence(
    declaration: ConnectorZoneDeclaration,
    placed: tuple[ConnectorPlacedGeometry, ...],
    models: tuple[ConnectorRequirementModel, ...],
) -> tuple[ConnectorRequirementEvidence, ...]:
    by_id = {item.requirement_id: item for item in models}
    result: list[ConnectorRequirementEvidence] = []
    pad_ids = {
        f"{item.source_geometry.reference}:{pad_id}"
        for item in placed
        for pad_id, _ in item.pad_transforms
    }
    pad_compounds = {
        f"{item.source_geometry.reference}:{pad_id}": transform.compound
        for item in placed
        for pad_id, transform in item.pad_transforms
    }
    for requirement in _requirements(declaration):
        model = by_id.get(requirement.requirement_id)
        effective_binding_ids = (
            requirement.source_binding_ids
            if model is None
            else tuple(
                sorted(
                    {
                        *model.source_binding_ids,
                        *(
                            model.exact_region.source_binding_ids
                            if model.exact_region is not None
                            else ()
                        ),
                    }
                )
            )
        )
        if declaration.connector_role is ConnectorRole.ON_BOARD_MODULE:
            result.append(
                ConnectorRequirementEvidence(
                    requirement_id=requirement.requirement_id,
                    rule_id=requirement.rule_id,
                    kind=requirement.kind,
                    effective_binding_ids=effective_binding_ids,
                    verification=SemanticVerification.EXACT,
                    disposition=SemanticDisposition.NOT_APPLICABLE,
                )
            )
            continue
        if model is None:
            result.append(
                ConnectorRequirementEvidence(
                    requirement_id=requirement.requirement_id,
                    rule_id=requirement.rule_id,
                    kind=requirement.kind,
                    effective_binding_ids=effective_binding_ids,
                    verification=SemanticVerification.UNSUPPORTED,
                    disposition=SemanticDisposition.UNVERIFIED,
                )
            )
            continue
        measured: float | None = None
        unit: str | None = None
        if requirement.kind is ConnectorRequirementKind.FILTER_CHAIN:
            passed = model.ordered_component_refs == requirement.expected_component_order
        elif requirement.kind is ConnectorRequirementKind.GROUND_PIN_SPREAD:
            if not set(model.ground_pad_ids).issubset(pad_ids):
                raise ValueError("ground-pin topology references absent connector pad geometry")
            maximum_squared = max(
                (
                    compound_distance_witness(
                        pad_compounds[first], pad_compounds[second]
                    ).squared_distance
                    for first, second in combinations(model.ground_pad_ids, 2)
                ),
                default=Fraction(0),
            )
            measured, unit = diagnostic_distance_mm(maximum_squared), "mm"
            assert requirement.minimum_ground_pin_count is not None
            assert requirement.minimum_ground_pin_spread is not None
            threshold = Fraction(str(requirement.minimum_ground_pin_spread.value))
            passed = (
                len(model.ground_pad_ids) >= requirement.minimum_ground_pin_count
                and maximum_squared >= threshold * threshold
            )
        elif requirement.kind is ConnectorRequirementKind.OSCILLATOR_SEPARATION:
            assert model.exact_region is not None and model.exact_region.compound is not None
            if any(
                item.body_transform.authority is not PlacementTransformAuthority.EXACT
                for item in placed
            ):
                result.append(
                    ConnectorRequirementEvidence(
                        requirement_id=requirement.requirement_id,
                        rule_id=requirement.rule_id,
                        kind=requirement.kind,
                        model_id=model.model_id,
                        effective_binding_ids=effective_binding_ids,
                        verification=SemanticVerification.BOUNDED_APPROXIMATION,
                        disposition=SemanticDisposition.UNVERIFIED,
                    )
                )
                continue
            witness = min(
                (
                    compound_distance_witness(
                        item.body_transform.compound, model.exact_region.compound
                    )
                    for item in placed
                ),
                key=lambda item: (item.squared_distance, item.first_point, item.second_point),
            )
            measured, unit = diagnostic_distance_mm(witness.squared_distance), "mm"
            assert requirement.minimum_separation is not None
            threshold = Fraction(str(requirement.minimum_separation.value))
            passed = witness.squared_distance >= threshold * threshold
        else:
            assert model.exact_region is not None and model.exact_region.compound is not None
            if any(
                item.body_transform.authority is not PlacementTransformAuthority.EXACT
                for item in placed
            ):
                result.append(
                    ConnectorRequirementEvidence(
                        requirement_id=requirement.requirement_id,
                        rule_id=requirement.rule_id,
                        kind=requirement.kind,
                        model_id=model.model_id,
                        effective_binding_ids=effective_binding_ids,
                        verification=SemanticVerification.BOUNDED_APPROXIMATION,
                        disposition=SemanticDisposition.UNVERIFIED,
                    )
                )
                continue
            passed = any(
                compound_relation(item.body_transform.compound, model.exact_region.compound)
                is not PlanarRelation.DISJOINT
                for item in placed
            )
        result.append(
            ConnectorRequirementEvidence(
                requirement_id=requirement.requirement_id,
                rule_id=requirement.rule_id,
                kind=requirement.kind,
                model_id=model.model_id,
                effective_binding_ids=effective_binding_ids,
                measured_value=measured,
                measured_unit=unit,
                verification=SemanticVerification.EXACT,
                disposition=_disposition(requirement.authority, passed),
            )
        )
    return tuple(sorted(result, key=lambda item: item.requirement_id))


def _findings(
    declaration: ConnectorZoneDeclaration,
    geometry: tuple[ConnectorGeometryEvidence, ...],
    requirements: tuple[ConnectorRequirementEvidence, ...],
) -> tuple[SemanticFinding, ...]:
    geometry_bindings = tuple(
        sorted(
            {
                *declaration.zone_region.source_binding_ids,
                *(item.source_binding_id for item in declaration.connector_geometries),
            }
        )
    )
    findings = [
        SemanticFinding(
            rule_id=item.rule_id,
            authority=(
                declaration.maximum_edge_authority
                if item.kind == "edge_access"
                else SemanticAuthorityClass.HARD_GEOMETRY
            ),
            disposition=item.disposition,
            verification=item.verification,
            object_ids=(item.evidence_id,),
            component_refs=(item.reference,),
            region_ids=(declaration.zone_id,),
            evidence_binding_ids=geometry_bindings,
            message=f"Connector {item.kind.replace('_', ' ')} evaluated independently.",
            suggested_action="Retain exact supplied geometry or satisfy this distinct rule.",
        )
        for item in geometry
    ]
    requirement_by_id = {item.requirement_id: item for item in _requirements(declaration)}
    for item in requirements:
        requirement = requirement_by_id[item.requirement_id]
        findings.append(
            SemanticFinding(
                rule_id=item.rule_id,
                authority=requirement.authority,
                disposition=item.disposition,
                verification=item.verification,
                object_ids=((item.model_id,) if item.model_id else ()),
                region_ids=(declaration.zone_id,),
                evidence_binding_ids=tuple(
                    sorted(
                        {
                            *requirement.source_binding_ids,
                            *item.effective_binding_ids,
                        }
                    )
                ),
                message=(
                    f"Connector {item.kind.value.replace('_', ' ')} evaluated as a "
                    "distinct requirement."
                ),
                suggested_action=(
                    "Provide exact scoped topology/model authority or satisfy this requirement."
                ),
            )
        )
    return tuple(findings)


def rederive_connector_zone(
    declaration: ConnectorZoneDeclaration,
    requirement_models: Sequence[ConnectorRequirementModel] = (),
) -> dict[str, Any]:
    declaration = ConnectorZoneDeclaration.model_validate_json(declaration.model_dump_json())
    models = tuple(
        sorted(
            (
                ConnectorRequirementModel.model_validate_json(item.model_dump_json())
                for item in requirement_models
            ),
            key=lambda item: item.requirement_id,
        )
    )
    if len({item.requirement_id for item in models}) != len(models):
        raise ValueError("connector requirement model identities must be unique")
    requirements = {item.requirement_id: item for item in _requirements(declaration)}
    binding_by_id = {item.binding_id: item for item in declaration.evidence_bindings}
    known_bindings = set(binding_by_id)
    context_fp = connector_declaration_context_fingerprint(declaration)
    for model in models:
        requirement = requirements.get(model.requirement_id)
        if requirement is None or model.kind is not requirement.kind:
            raise ValueError("connector model is absent from or mistyped for the declaration")
        if (
            model.board_layout_snapshot_fingerprint != declaration.board_layout_snapshot_fingerprint
            or model.board_netlist_snapshot_fingerprint
            != declaration.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("connector requirement model is bound to stale board snapshots")
        effective_binding_ids = {
            *model.source_binding_ids,
            *(model.exact_region.source_binding_ids if model.exact_region is not None else ()),
        }
        if not effective_binding_ids.issubset(known_bindings):
            raise ValueError("connector requirement model references unknown evidence")
        if requirement.authority is SemanticAuthorityClass.HARD_GEOMETRY:
            if any(
                not evidence_binding_is_complete(binding_by_id[binding_id])
                for binding_id in effective_binding_ids
            ):
                raise ValueError(
                    "hard connector requirement model requires pinned applicable reviewed evidence"
                )
            if any(
                binding_by_id[binding_id].geometry_source_fingerprint != context_fp
                for binding_id in effective_binding_ids
            ):
                raise ValueError("hard connector requirement model evidence has stale context")
    layout = parse_canonical_board_layout_snapshot(declaration.board_layout_snapshot_json)
    placed = _placed(declaration, layout)
    geometry = _geometry_evidence(declaration, layout, placed)
    requirement_evidence = _requirement_evidence(declaration, placed, models)
    evidence_fp = fingerprint(
        {
            "placed": [item.model_dump(mode="json") for item in placed],
            "geometry": [item.model_dump(mode="json") for item in geometry],
            "requirements": [item.model_dump(mode="json") for item in requirement_evidence],
        }
    )
    semantic = SemanticLayoutResult.build(
        context_fingerprint=fingerprint(
            {
                "layout": declaration.board_layout_snapshot_fingerprint,
                "netlist": declaration.board_netlist_snapshot_fingerprint,
            }
        ),
        declarations_fingerprint=declaration.semantic_fingerprint(),
        geometry_fingerprint=evidence_fp,
        metrics=(),
        findings=_findings(declaration, geometry, requirement_evidence),
    )
    return {
        "requirement_models": models,
        "placed_geometries": placed,
        "geometry_evidence": geometry,
        "requirement_evidence": requirement_evidence,
        "evidence_fingerprint": evidence_fp,
        "semantic_result": semantic,
    }


def evaluate_connector_zone(
    layout: BoardLayout,
    netlist: BoardNetlist,
    declaration: ConnectorZoneDeclaration,
    requirement_models: Sequence[ConnectorRequirementModel] = (),
) -> ConnectorZoneResult:
    """Evaluate only supplied connector geometry/topology without broader completeness claims."""

    layout_before = canonical_board_layout_snapshot_json(layout)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)
    if layout_before != declaration.board_layout_snapshot_json:
        raise ValueError("caller BoardLayout differs from the declaration snapshot")
    if netlist_before != declaration.board_netlist_snapshot_json:
        raise ValueError("caller BoardNetlist differs from the declaration snapshot")
    derived = rederive_connector_zone(declaration, requirement_models)
    if canonical_board_layout_snapshot_json(layout) != layout_before:
        raise RuntimeError("connector evaluator mutated caller BoardLayout")
    if canonical_board_netlist_snapshot_json(netlist) != netlist_before:
        raise RuntimeError("connector evaluator mutated caller BoardNetlist")
    fields: dict[str, Any] = {"declaration": declaration, **derived}
    provisional = ConnectorZoneResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return ConnectorZoneResult(**fields, result_fingerprint=result_fp)
