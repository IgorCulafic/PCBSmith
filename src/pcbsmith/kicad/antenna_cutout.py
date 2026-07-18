"""Exact selected-cutout checks for the R6.2 baseboard-cutout strategy.

Cutout choice is caller-declared and bound to a retained board snapshot.  This
module never searches for the nearest void and never grants a whole-component
or source-approved geometry exception.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from pcbsmith.antenna_cutout_ir import (
    AntennaCutoutDeclaration,
    AntennaCutoutResult,
    AntennaCutoutSupportEvidence,
    AntennaInsideSelectedCutoutEvidence,
    AntennaSelectedBoardCutout,
    ExactSquaredBoundaryClearance,
    board_cutout_identity,
    fingerprint,
    support_binding_for_declaration,
)
from pcbsmith.antenna_edge_ir import (
    AntennaBoardMaterialAuthority,
    AntennaTransformedSupport,
)
from pcbsmith.antenna_ir import AntennaPlacementResult
from pcbsmith.kicad.board_region import BoardCutoutPolygon
from pcbsmith.kicad.board_serialization import parse_canonical_board_layout_snapshot
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacementTransformAuthority,
    PlanarRelation,
    compound_boundary_minimum_squared_distance,
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
    return AntennaBoardMaterialAuthority(
        board_layout_snapshot_fingerprint=placement.board_layout_snapshot_fingerprint,
        outer_polygon=outer_polygon,
        outer_compound=outer_compound,
        cutout_compounds=cutouts,
        material_compound=material,
        board_material_fingerprint=fingerprint(payload),
    )


def _validate_declaration(
    placement: AntennaPlacementResult, declaration: AntennaCutoutDeclaration
) -> AntennaCutoutDeclaration:
    retained = AntennaCutoutDeclaration.model_validate_json(declaration.model_dump_json())
    antenna = placement.declaration
    if antenna.placement_strategy != "baseboard_cutout":
        raise ValueError("antenna cutout evaluator requires baseboard_cutout placement strategy")
    if (
        retained.antenna_id != antenna.antenna_id
        or retained.module_reference != antenna.module_reference
        or retained.antenna_declaration_fingerprint != antenna.semantic_fingerprint()
        or retained.source_applicability_binding_id != antenna.module_guidance_binding.binding_id
    ):
        raise ValueError("antenna cutout companion is bound to another antenna declaration")
    if retained.required_cutout_region_ids != (antenna.antenna_region.region_id,):
        raise ValueError("antenna cutout companion omits or invents required antenna regions")
    if (
        retained.selected_cutout.board_layout_snapshot_fingerprint
        != placement.board_layout_snapshot_fingerprint
    ):
        raise ValueError("selected cutout is bound to another board layout snapshot")
    if retained.support_geometry_binding.geometry_source_fingerprint != (
        support_binding_for_declaration(antenna, retained.support_regions)
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


def _resolve_selected_cutout(
    placement: AntennaPlacementResult,
    selected: AntennaSelectedBoardCutout,
) -> AntennaSelectedBoardCutout:
    layout = parse_canonical_board_layout_snapshot(placement.board_layout_snapshot_json)
    matches = tuple(
        cutout
        for cutout in layout.cutouts
        if cutout.semantic_fingerprint() == selected.cutout_fingerprint
        and board_cutout_identity(cutout.semantic_fingerprint()) == selected.cutout_id
    )
    if len(matches) != 1:
        raise ValueError("selected board cutout is absent, wrong, or ambiguous")
    expected_compound = ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=matches[0].points),))
    if selected.cutout_compound != expected_compound:
        raise ValueError("selected board cutout geometry is stale")
    return selected


def _transformed_supports(
    placement: AntennaPlacementResult,
    declaration: AntennaCutoutDeclaration,
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


def _squared_clearance(value: Fraction) -> ExactSquaredBoundaryClearance:
    return ExactSquaredBoundaryClearance(numerator=value.numerator, denominator=value.denominator)


def _cutout_evidence(
    placement: AntennaPlacementResult,
    declaration: AntennaCutoutDeclaration,
    selected: AntennaSelectedBoardCutout,
    material: AntennaBoardMaterialAuthority,
) -> tuple[AntennaInsideSelectedCutoutEvidence, ...]:
    placed_by_id = {item.region_id: item for item in placement.placed_regions}
    evidence: list[AntennaInsideSelectedCutoutEvidence] = []
    for region_id in declaration.required_cutout_region_ids:
        placed = placed_by_id[region_id]
        if placed.bounded_transform.authority is PlacementTransformAuthority.BOUNDED_APPROXIMATION:
            contained = None
            clearance = None
            relation = None
            verification = SemanticVerification.BOUNDED_APPROXIMATION
            disposition = SemanticDisposition.UNVERIFIED
        else:
            exact = placed.exact_transformed_compound
            if exact is None:
                raise ValueError("exact antenna cutout rule is missing exact geometry")
            selected_polygon = selected.cutout_compound.polygons[0]
            contained = compound_inside_polygon(exact, selected_polygon)
            clearance = _squared_clearance(
                compound_boundary_minimum_squared_distance(exact, selected.cutout_compound)
            )
            relation = compound_relation(exact, material.material_compound)
            verification = SemanticVerification.EXACT
            passes = contained and clearance.numerator > 0 and relation is PlanarRelation.DISJOINT
            disposition = SemanticDisposition.PASS if passes else SemanticDisposition.FAIL
        evidence.append(
            AntennaInsideSelectedCutoutEvidence(
                region_id=region_id,
                selected_cutout_id=selected.cutout_id,
                selected_cutout_fingerprint=selected.cutout_fingerprint,
                rule_id=declaration.antenna_inside_cutout_rule_id,
                evidence_binding_ids=(declaration.source_applicability_binding_id,),
                contained_in_selected_cutout_closed=contained,
                selected_cutout_boundary_squared_clearance=clearance,
                material_relation=relation,
                verification=verification,
                disposition=disposition,
            )
        )
    return tuple(sorted(evidence, key=lambda item: item.region_id))


def _support_evidence(
    transformed: tuple[AntennaTransformedSupport, ...],
    declaration: AntennaCutoutDeclaration,
    material: AntennaBoardMaterialAuthority,
) -> tuple[AntennaCutoutSupportEvidence, ...]:
    evidence: list[AntennaCutoutSupportEvidence] = []
    cutouts = tuple(
        (
            board_cutout_identity(
                BoardCutoutPolygon(points=cutout.polygons[0].outer).semantic_fingerprint()
            ),
            cutout,
        )
        for cutout in material.cutout_compounds
    )
    for transformed_support in transformed:
        if transformed_support.verification is SemanticVerification.BOUNDED_APPROXIMATION:
            contained = None
            relations: tuple[tuple[str, PlanarRelation], ...] = ()
            disposition = SemanticDisposition.UNVERIFIED
        else:
            exact = transformed_support.exact_transformed_compound
            if exact is None:
                raise ValueError("exact support rule is missing exact geometry")
            contained = compound_inside_polygon(exact, material.outer_polygon)
            relations = tuple(
                sorted(
                    (
                        (cutout_id, compound_relation(exact, cutout))
                        for cutout_id, cutout in cutouts
                    ),
                    key=lambda item: item[0],
                )
            )
            passes = contained and all(
                relation is PlanarRelation.DISJOINT for _, relation in relations
            )
            disposition = SemanticDisposition.PASS if passes else SemanticDisposition.FAIL
        evidence.append(
            AntennaCutoutSupportEvidence(
                support_region_id=transformed_support.support_region.support_region_id,
                rule_id=declaration.support_inside_material_rule_id,
                evidence_binding_ids=(declaration.support_geometry_binding.binding_id,),
                contained_in_outer=contained,
                cutout_relations=relations,
                verification=transformed_support.verification,
                disposition=disposition,
            )
        )
    return tuple(sorted(evidence, key=lambda item: item.support_region_id))


def _findings(
    cutout: tuple[AntennaInsideSelectedCutoutEvidence, ...],
    supports: tuple[AntennaCutoutSupportEvidence, ...],
) -> tuple[SemanticFinding, ...]:
    findings: list[SemanticFinding] = []
    for item in cutout:
        findings.append(
            SemanticFinding(
                rule_id=item.rule_id,
                authority=SemanticAuthorityClass.HARD_GEOMETRY,
                disposition=item.disposition,
                verification=item.verification,
                region_ids=(item.region_id, item.selected_cutout_id),
                evidence_binding_ids=item.evidence_binding_ids,
                message={
                    SemanticDisposition.PASS: (
                        "Required antenna region is strictly inside the selected board cutout."
                    ),
                    SemanticDisposition.FAIL: (
                        "Required antenna region touches or leaves the selected board cutout."
                    ),
                    SemanticDisposition.UNVERIFIED: (
                        "Antenna selected-cutout containment is not exact."
                    ),
                }[item.disposition],
                suggested_action={
                    SemanticDisposition.PASS: "Retain the exact selected-cutout placement.",
                    SemanticDisposition.FAIL: (
                        "Move the module so the antenna region is strictly inside the "
                        "selected cutout."
                    ),
                    SemanticDisposition.UNVERIFIED: (
                        "Provide an exact orthogonal placement transform."
                    ),
                }[item.disposition],
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
                        "Declared module support overhangs or touches a board cutout."
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


def rederive_antenna_cutout(
    placement_result: AntennaPlacementResult,
    declaration: AntennaCutoutDeclaration,
) -> dict[str, Any]:
    placement = AntennaPlacementResult.model_validate_json(placement_result.model_dump_json())
    retained = _validate_declaration(placement, declaration)
    selected = _resolve_selected_cutout(placement, retained.selected_cutout)
    material = _board_material(placement)
    transformed = _transformed_supports(placement, retained)
    cutout_evidence = _cutout_evidence(placement, retained, selected, material)
    support_evidence = _support_evidence(transformed, retained, material)
    evidence_fp = fingerprint(
        {
            "board_material": material.model_dump(mode="json"),
            "selected_cutout": selected.model_dump(mode="json"),
            "transformed_supports": [item.model_dump(mode="json") for item in transformed],
            "cutout_evidence": [item.model_dump(mode="json") for item in cutout_evidence],
            "support_evidence": [item.model_dump(mode="json") for item in support_evidence],
        }
    )
    semantic = SemanticLayoutResult.build(
        context_fingerprint=placement.declaration.module_guidance_binding.semantic_fingerprint(),
        declarations_fingerprint=retained.semantic_fingerprint(),
        geometry_fingerprint=material.board_material_fingerprint,
        placement_candidate_fingerprint=placement.result_fingerprint,
        metrics=(),
        findings=_findings(cutout_evidence, support_evidence),
    )
    return {
        "declaration": retained,
        "board_material": material,
        "selected_cutout": selected,
        "transformed_supports": transformed,
        "cutout_evidence": cutout_evidence,
        "support_evidence": support_evidence,
        "evidence_fingerprint": evidence_fp,
        "semantic_result": semantic,
    }


def evaluate_antenna_cutout(
    placement_result: AntennaPlacementResult,
    declaration: AntennaCutoutDeclaration,
) -> AntennaCutoutResult:
    """Evaluate only explicit baseboard-cutout antenna/support rules."""

    derived = rederive_antenna_cutout(placement_result, declaration)
    fields = {"placement_result": placement_result, **derived}
    provisional = AntennaCutoutResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return AntennaCutoutResult(**fields, result_fingerprint=result_fp)
