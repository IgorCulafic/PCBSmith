"""Exact board-material checks for the R6.2 antenna edge-overhang strategy."""

from __future__ import annotations

from typing import Any

from pcbsmith.antenna_edge_ir import (
    AntennaBoardMaterialAuthority,
    AntennaEdgeOverhangDeclaration,
    AntennaEdgeOverhangResult,
    AntennaOutsideMaterialEvidence,
    AntennaSupportMaterialEvidence,
    AntennaTransformedSupport,
    fingerprint,
    support_geometry_binding_fingerprint,
)
from pcbsmith.antenna_ir import AntennaPlacementResult
from pcbsmith.kicad.board_serialization import parse_canonical_board_layout_snapshot
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacementTransformAuthority,
    PlanarRelation,
    compound_inside_polygon,
    compound_relation,
    transform_compound,
    transform_compound_bounded,
)
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticVerification,
)


def _board_material(placement: AntennaPlacementResult) -> AntennaBoardMaterialAuthority:
    layout = parse_canonical_board_layout_snapshot(placement.board_layout_snapshot_json)
    outline = layout.outline or (
        (0.0, 0.0),
        (layout.width_mm, 0.0),
        (layout.width_mm, layout.height_mm),
        (0.0, layout.height_mm),
    )
    outer_polygon = ExactPlanarPolygon(outer=outline)
    outer_compound = ExactPlanarCompound(polygons=(outer_polygon,))
    cutouts = tuple(
        sorted(
            (
                ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=item.points),))
                for item in layout.cutouts
            ),
            key=lambda item: item.semantic_json(),
        )
    )
    material = ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(
                outer=outer_polygon.outer,
                holes=tuple(item.polygons[0].outer for item in cutouts),
            ),
        )
    )
    payload = {
        "schema_id": "pcbsmith-antenna-board-material-authority",
        "schema_version": 1,
        "board_layout_snapshot_fingerprint": placement.board_layout_snapshot_fingerprint,
        "outer_polygon": outer_polygon.model_dump(mode="json"),
        "outer_compound": outer_compound.model_dump(mode="json"),
        "cutout_compounds": [item.model_dump(mode="json") for item in cutouts],
        "material_compound": material.model_dump(mode="json"),
    }
    material_fp = fingerprint(payload)
    return AntennaBoardMaterialAuthority(
        board_layout_snapshot_fingerprint=placement.board_layout_snapshot_fingerprint,
        outer_polygon=outer_polygon,
        outer_compound=outer_compound,
        cutout_compounds=cutouts,
        material_compound=material,
        board_material_fingerprint=material_fp,
    )


def _validate_declaration(
    placement: AntennaPlacementResult, declaration: AntennaEdgeOverhangDeclaration
) -> AntennaEdgeOverhangDeclaration:
    retained = AntennaEdgeOverhangDeclaration.model_validate_json(declaration.model_dump_json())
    antenna = placement.declaration
    if antenna.placement_strategy != "edge_overhang":
        raise ValueError("antenna edge evaluator requires edge_overhang placement strategy")
    if (
        retained.antenna_id != antenna.antenna_id
        or retained.module_reference != antenna.module_reference
        or retained.antenna_declaration_fingerprint != antenna.semantic_fingerprint()
        or retained.source_applicability_binding_id != antenna.module_guidance_binding.binding_id
    ):
        raise ValueError("antenna edge companion is bound to another antenna declaration")
    expected_outside = (antenna.antenna_region.region_id,)
    if retained.required_outside_region_ids != expected_outside:
        raise ValueError("antenna edge companion omits or invents required antenna regions")
    if retained.support_geometry_binding.geometry_source_fingerprint != (
        support_geometry_binding_fingerprint(antenna, retained.support_regions)
    ):
        raise ValueError("antenna support geometry fingerprint is stale")
    for support in retained.support_regions:
        if (
            support.installed_footprint_id != antenna.selected_footprint_library_id
            or support.component_uuid_path != antenna.component_uuid_path
            or support.component_revision != antenna.component_revision
            or support.source_file_sha256 != antenna.source_file_sha256
        ):
            raise ValueError("antenna support source/module identity is stale")
    return retained


def _transformed_supports(
    placement: AntennaPlacementResult,
    declaration: AntennaEdgeOverhangDeclaration,
) -> tuple[AntennaTransformedSupport, ...]:
    transformed: list[AntennaTransformedSupport] = []
    for support in declaration.support_regions:
        bounded = transform_compound_bounded(support.compound, placement.transform)
        exact = None
        verification = SemanticVerification.BOUNDED_APPROXIMATION
        if bounded.authority is PlacementTransformAuthority.EXACT:
            exact = transform_compound(support.compound, placement.transform)
            if exact != bounded.compound:
                raise ValueError("shared exact and bounded support transform kernels disagree")
            verification = SemanticVerification.EXACT
        transformed.append(
            AntennaTransformedSupport(
                support_region=support,
                bounded_transform=bounded,
                exact_transformed_compound=exact,
                verification=verification,
            )
        )
    return tuple(sorted(transformed, key=lambda item: item.support_region.support_region_id))


def _outside_evidence(
    placement: AntennaPlacementResult,
    declaration: AntennaEdgeOverhangDeclaration,
    material: AntennaBoardMaterialAuthority,
) -> tuple[AntennaOutsideMaterialEvidence, ...]:
    placed_by_id = {item.region_id: item for item in placement.placed_regions}
    evidence: list[AntennaOutsideMaterialEvidence] = []
    for region_id in declaration.required_outside_region_ids:
        placed = placed_by_id[region_id]
        if placed.bounded_transform.authority is PlacementTransformAuthority.BOUNDED_APPROXIMATION:
            relation = None
            verification = SemanticVerification.BOUNDED_APPROXIMATION
            disposition = SemanticDisposition.UNVERIFIED
        else:
            if placed.exact_transformed_compound is None:
                raise ValueError("exact antenna outside rule is missing exact geometry")
            relation = compound_relation(
                placed.exact_transformed_compound, material.material_compound
            )
            verification = SemanticVerification.EXACT
            disposition = (
                SemanticDisposition.PASS
                if relation is PlanarRelation.DISJOINT
                else SemanticDisposition.FAIL
            )
        evidence.append(
            AntennaOutsideMaterialEvidence(
                region_id=region_id,
                rule_id=declaration.antenna_outside_rule_id,
                evidence_binding_ids=(declaration.source_applicability_binding_id,),
                material_relation=relation,
                verification=verification,
                disposition=disposition,
            )
        )
    return tuple(sorted(evidence, key=lambda item: item.region_id))


def _support_evidence(
    transformed: tuple[AntennaTransformedSupport, ...],
    declaration: AntennaEdgeOverhangDeclaration,
    material: AntennaBoardMaterialAuthority,
) -> tuple[AntennaSupportMaterialEvidence, ...]:
    evidence: list[AntennaSupportMaterialEvidence] = []
    for item in transformed:
        if item.verification is SemanticVerification.BOUNDED_APPROXIMATION:
            contained = None
            cutout_relations: tuple[tuple[str, PlanarRelation], ...] = ()
            disposition = SemanticDisposition.UNVERIFIED
        else:
            if item.exact_transformed_compound is None:
                raise ValueError("exact support rule is missing exact geometry")
            contained = compound_inside_polygon(
                item.exact_transformed_compound, material.outer_polygon
            )
            cutout_relations = tuple(
                (
                    f"cutout:{index}:{cutout.semantic_fingerprint()}",
                    compound_relation(item.exact_transformed_compound, cutout),
                )
                for index, cutout in enumerate(material.cutout_compounds)
            )
            passes = contained and all(
                relation is PlanarRelation.DISJOINT for _, relation in cutout_relations
            )
            disposition = SemanticDisposition.PASS if passes else SemanticDisposition.FAIL
        evidence.append(
            AntennaSupportMaterialEvidence(
                support_region_id=item.support_region.support_region_id,
                rule_id=declaration.support_inside_rule_id,
                evidence_binding_ids=(declaration.support_geometry_binding.binding_id,),
                contained_in_outer=contained,
                cutout_relations=cutout_relations,
                verification=item.verification,
                disposition=disposition,
            )
        )
    return tuple(sorted(evidence, key=lambda item: item.support_region_id))


def _findings(
    outside: tuple[AntennaOutsideMaterialEvidence, ...],
    supports: tuple[AntennaSupportMaterialEvidence, ...],
) -> tuple[SemanticFinding, ...]:
    findings: list[SemanticFinding] = []
    for outside_item in outside:
        findings.append(
            SemanticFinding(
                rule_id=outside_item.rule_id,
                authority=SemanticAuthorityClass.HARD_GEOMETRY,
                disposition=outside_item.disposition,
                verification=outside_item.verification,
                region_ids=(outside_item.region_id,),
                evidence_binding_ids=outside_item.evidence_binding_ids,
                message={
                    SemanticDisposition.PASS: (
                        "Required antenna region is strictly outside board material."
                    ),
                    SemanticDisposition.FAIL: (
                        "Required antenna region touches or overlaps board material."
                    ),
                    SemanticDisposition.UNVERIFIED: (
                        "Antenna outside-material relation is not exact."
                    ),
                }[outside_item.disposition],
                suggested_action={
                    SemanticDisposition.PASS: "Retain the exact placed antenna geometry.",
                    SemanticDisposition.FAIL: (
                        "Move the module to make the required antenna region disjoint."
                    ),
                    SemanticDisposition.UNVERIFIED: (
                        "Provide an exact orthogonal placement transform."
                    ),
                }[outside_item.disposition],
            )
        )
    for support_item in supports:
        findings.append(
            SemanticFinding(
                rule_id=support_item.rule_id,
                authority=SemanticAuthorityClass.HARD_GEOMETRY,
                disposition=support_item.disposition,
                verification=support_item.verification,
                region_ids=(support_item.support_region_id,),
                evidence_binding_ids=support_item.evidence_binding_ids,
                message={
                    SemanticDisposition.PASS: "Declared module support lies in board material.",
                    SemanticDisposition.FAIL: (
                        "Declared module support overhangs or touches a cutout."
                    ),
                    SemanticDisposition.UNVERIFIED: "Module support containment is not exact.",
                }[support_item.disposition],
                suggested_action={
                    SemanticDisposition.PASS: "Retain the exact support geometry authority.",
                    SemanticDisposition.FAIL: (
                        "Move the module so every support region remains supported."
                    ),
                    SemanticDisposition.UNVERIFIED: (
                        "Provide an exact orthogonal placement transform."
                    ),
                }[support_item.disposition],
            )
        )
    return tuple(findings)


def rederive_antenna_edge_overhang(
    placement_result: AntennaPlacementResult,
    declaration: AntennaEdgeOverhangDeclaration,
) -> dict[str, Any]:
    placement = AntennaPlacementResult.model_validate_json(placement_result.model_dump_json())
    retained = _validate_declaration(placement, declaration)
    material = _board_material(placement)
    transformed = _transformed_supports(placement, retained)
    outside = _outside_evidence(placement, retained, material)
    supports = _support_evidence(transformed, retained, material)
    evidence_fp = fingerprint(
        {
            "board_material": material.model_dump(mode="json"),
            "transformed_supports": [item.model_dump(mode="json") for item in transformed],
            "outside_evidence": [item.model_dump(mode="json") for item in outside],
            "support_evidence": [item.model_dump(mode="json") for item in supports],
        }
    )
    semantic = SemanticLayoutResult.build(
        context_fingerprint=placement.declaration.module_guidance_binding.semantic_fingerprint(),
        declarations_fingerprint=retained.semantic_fingerprint(),
        geometry_fingerprint=material.board_material_fingerprint,
        placement_candidate_fingerprint=placement.result_fingerprint,
        metrics=(),
        findings=_findings(outside, supports),
    )
    return {
        "declaration": retained,
        "board_material": material,
        "transformed_supports": transformed,
        "outside_evidence": outside,
        "support_evidence": supports,
        "evidence_fingerprint": evidence_fp,
        "semantic_result": semantic,
    }


def evaluate_antenna_edge_overhang(
    placement_result: AntennaPlacementResult,
    declaration: AntennaEdgeOverhangDeclaration,
) -> AntennaEdgeOverhangResult:
    """Evaluate only edge-overhang antenna/support material rules."""

    derived = rederive_antenna_edge_overhang(placement_result, declaration)
    fields = {"placement_result": placement_result, **derived}
    provisional = AntennaEdgeOverhangResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return AntennaEdgeOverhangResult(**fields, result_fingerprint=result_fp)
