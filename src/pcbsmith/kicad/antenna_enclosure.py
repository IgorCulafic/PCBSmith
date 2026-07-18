"""Exact source-specific 3-D antenna/enclosure exclusion evaluator."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Any

from pcbsmith.antenna_enclosure_ir import (
    AntennaEnclosureDistanceEvidence,
    AntennaEnclosureExclusionDeclaration,
    AntennaEnclosureExclusionResult,
    EnclosureObject,
    EnclosureObjectProfile,
    ExactDecimalInterval,
    ExactRational,
    ExactRationalPoint2,
    TransformedAntennaExclusionPrism,
    exclusion_binding_fingerprint,
    fingerprint,
)
from pcbsmith.antenna_ir import AntennaPlacementResult
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    PlacementTransformAuthority,
    compound_distance_witness,
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


def _validate_declaration(
    placement: AntennaPlacementResult,
    declaration: AntennaEnclosureExclusionDeclaration,
) -> AntennaEnclosureExclusionDeclaration:
    retained = AntennaEnclosureExclusionDeclaration.model_validate_json(
        declaration.model_dump_json()
    )
    antenna = placement.declaration
    identity = (
        retained.antenna_id == antenna.antenna_id
        and retained.module_reference == antenna.module_reference
        and retained.selected_footprint_library_id == antenna.selected_footprint_library_id
        and retained.component_uuid_path == antenna.component_uuid_path
        and retained.component_revision == antenna.component_revision
        and retained.source_file_sha256 == antenna.source_file_sha256
        and retained.antenna_declaration_fingerprint == antenna.semantic_fingerprint()
        and retained.exclusion_requirement_id == antenna.enclosure_exclusion_requirement_id
    )
    if not identity:
        raise ValueError("antenna enclosure declaration is bound to another module authority")
    expected = exclusion_binding_fingerprint(
        antenna,
        retained.exclusion,
        retained.required_clearance_mm,
        retained.prohibited_material_classes,
    )
    if retained.applicability_binding.geometry_source_fingerprint != expected:
        raise ValueError("antenna enclosure exclusion/clearance applicability is stale")
    return retained


def _validate_profile(
    declaration: AntennaEnclosureExclusionDeclaration,
    profile: EnclosureObjectProfile | None,
) -> EnclosureObjectProfile | None:
    if profile is None:
        return None
    retained = EnclosureObjectProfile.model_validate_json(profile.model_dump_json())
    if (
        retained.profile_id != declaration.enclosure_profile_id
        or retained.enclosure_id != declaration.enclosure_id
        or retained.enclosure_revision != declaration.enclosure_revision
        or retained.model_id != declaration.model_id
        or retained.model_sha256 != declaration.model_sha256
    ):
        raise ValueError("enclosure profile/revision/model authority is stale")
    return retained


def _reflect_z(
    interval: ExactDecimalInterval,
    board_plane: Decimal,
    *,
    back: bool,
) -> ExactDecimalInterval:
    if not back:
        return ExactDecimalInterval(
            lower_mm=board_plane + interval.lower_mm,
            upper_mm=board_plane + interval.upper_mm,
        )
    return ExactDecimalInterval(
        lower_mm=board_plane - interval.upper_mm,
        upper_mm=board_plane - interval.lower_mm,
    )


def _transform_exclusion(
    placement: AntennaPlacementResult,
    declaration: AntennaEnclosureExclusionDeclaration,
    profile: EnclosureObjectProfile,
) -> TransformedAntennaExclusionPrism:
    local = declaration.exclusion
    bounded = transform_compound_bounded(local.local_xy_compound, placement.transform)
    exact: ExactPlanarCompound | None = None
    verification = SemanticVerification.BOUNDED_APPROXIMATION
    if bounded.authority is PlacementTransformAuthority.EXACT:
        exact = transform_compound(local.local_xy_compound, placement.transform)
        if exact != bounded.compound:
            raise ValueError("shared exact and bounded enclosure transform kernels disagree")
        verification = SemanticVerification.EXACT
    return TransformedAntennaExclusionPrism(
        exclusion_id=local.exclusion_id,
        bounded_xy_transform=bounded,
        exact_xy_compound=exact,
        exact_z_interval=_reflect_z(
            local.local_z_interval,
            profile.board_plane_z_mm,
            back=placement.transform.side == "back",
        ),
        board_plane_z_mm=profile.board_plane_z_mm,
        verification=verification,
    )


def _rational_point(point: tuple[Fraction, Fraction]) -> ExactRationalPoint2:
    return ExactRationalPoint2(
        x_mm=ExactRational.from_fraction(point[0]),
        y_mm=ExactRational.from_fraction(point[1]),
    )


def _interval_separation(
    first: ExactDecimalInterval, second: ExactDecimalInterval
) -> tuple[Fraction, Fraction, Fraction]:
    first_low = Fraction(first.lower_mm)
    first_high = Fraction(first.upper_mm)
    second_low = Fraction(second.lower_mm)
    second_high = Fraction(second.upper_mm)
    if first_high < second_low:
        return second_low - first_high, first_high, second_low
    if second_high < first_low:
        return first_low - second_high, first_low, second_high
    point = max(first_low, second_low)
    return Fraction(0), point, point


def _exact_evidence(
    declaration: AntennaEnclosureExclusionDeclaration,
    transformed: TransformedAntennaExclusionPrism,
    item: EnclosureObject,
) -> AntennaEnclosureDistanceEvidence:
    required_squared = Fraction(declaration.required_clearance_mm) ** 2
    if item.material_class not in declaration.prohibited_material_classes:
        return AntennaEnclosureDistanceEvidence(
            object_id=item.object_id,
            material_class=item.material_class,
            applicable=False,
            object_geometry_fingerprint=(
                None if item.planar_compound is None else item.semantic_fingerprint()
            ),
            xy_squared_distance=None,
            z_separation=None,
            total_squared_distance=None,
            required_squared_clearance=ExactRational.from_fraction(required_squared),
            exclusion_xy_point=None,
            object_xy_point=None,
            exclusion_z_point=None,
            object_z_point=None,
            verification=SemanticVerification.EXACT,
            disposition=SemanticDisposition.NOT_APPLICABLE,
            pending_reason=None,
        )
    if item.planar_compound is None or item.z_interval is None:
        return _pending_evidence(
            declaration, item.object_id, item.material_class, "object_geometry_missing"
        )
    if transformed.verification is not SemanticVerification.EXACT:
        return _pending_evidence(
            declaration,
            item.object_id,
            item.material_class,
            "placement_transform_not_exact",
            verification=SemanticVerification.BOUNDED_APPROXIMATION,
        )
    if transformed.exact_xy_compound is None:
        raise ValueError("exact transformed exclusion is missing exact XY geometry")
    xy = compound_distance_witness(transformed.exact_xy_compound, item.planar_compound)
    z_separation, antenna_z, object_z = _interval_separation(
        transformed.exact_z_interval, item.z_interval
    )
    total = xy.squared_distance + z_separation * z_separation
    disposition = (
        SemanticDisposition.PASS
        if total >= required_squared
        else SemanticDisposition.FAIL
    )
    return AntennaEnclosureDistanceEvidence(
        object_id=item.object_id,
        material_class=item.material_class,
        applicable=True,
        object_geometry_fingerprint=item.semantic_fingerprint(),
        xy_squared_distance=ExactRational.from_fraction(xy.squared_distance),
        z_separation=ExactRational.from_fraction(z_separation),
        total_squared_distance=ExactRational.from_fraction(total),
        required_squared_clearance=ExactRational.from_fraction(required_squared),
        exclusion_xy_point=_rational_point(xy.first_point),
        object_xy_point=_rational_point(xy.second_point),
        exclusion_z_point=ExactRational.from_fraction(antenna_z),
        object_z_point=ExactRational.from_fraction(object_z),
        verification=SemanticVerification.EXACT,
        disposition=disposition,
        pending_reason=None,
    )


def _pending_evidence(
    declaration: AntennaEnclosureExclusionDeclaration,
    object_id: str,
    material_class: str | None,
    reason: str,
    *,
    verification: SemanticVerification = SemanticVerification.EXACT,
) -> AntennaEnclosureDistanceEvidence:
    return AntennaEnclosureDistanceEvidence(
        object_id=object_id,
        material_class=material_class,
        applicable=None if material_class is None else True,
        object_geometry_fingerprint=None,
        xy_squared_distance=None,
        z_separation=None,
        total_squared_distance=None,
        required_squared_clearance=ExactRational.from_fraction(
            Fraction(declaration.required_clearance_mm) ** 2
        ),
        exclusion_xy_point=None,
        object_xy_point=None,
        exclusion_z_point=None,
        object_z_point=None,
        verification=verification,
        disposition=SemanticDisposition.VALIDATION_PENDING,
        pending_reason=reason,
    )


def _findings(
    declaration: AntennaEnclosureExclusionDeclaration,
    evidence: tuple[AntennaEnclosureDistanceEvidence, ...],
) -> tuple[SemanticFinding, ...]:
    findings = []
    for item in evidence:
        findings.append(
            SemanticFinding(
                rule_id=declaration.exclusion_requirement_id,
                authority=SemanticAuthorityClass.VALIDATION_REQUIRED,
                disposition=item.disposition,
                verification=item.verification,
                object_ids=(item.object_id,),
                component_refs=(declaration.module_reference,),
                region_ids=(declaration.exclusion.exclusion_id,),
                evidence_binding_ids=(declaration.applicability_binding.binding_id,),
                validation_profile_id=(
                    declaration.validation_profile_id
                    if item.disposition in {SemanticDisposition.PASS, SemanticDisposition.FAIL}
                    else None
                ),
                validation_requirement_ids=(declaration.exclusion_requirement_id,),
                message={
                    SemanticDisposition.PASS: (
                        "Exact 3-D enclosure clearance meets the source-specific requirement."
                    ),
                    SemanticDisposition.FAIL: (
                        "Exact 3-D enclosure clearance violates the source-specific requirement."
                    ),
                    SemanticDisposition.NOT_APPLICABLE: (
                        "Enclosure object material is not prohibited by this source-specific rule."
                    ),
                    SemanticDisposition.VALIDATION_PENDING: (
                        "3-D enclosure exclusion cannot be completed from the retained "
                        "model authority."
                    ),
                }[item.disposition],
                suggested_action={
                    SemanticDisposition.PASS: (
                        "Retain the exact enclosure object and module placement authorities."
                    ),
                    SemanticDisposition.FAIL: (
                        "Revise the enclosure or module placement and re-evaluate this 3-D rule."
                    ),
                    SemanticDisposition.NOT_APPLICABLE: (
                        "No action for this nonprohibited material class."
                    ),
                    SemanticDisposition.VALIDATION_PENDING: (
                        "Attach complete exact enclosure geometry and an orthogonal "
                        "module placement."
                    ),
                }[item.disposition],
            )
        )
    return tuple(sorted(findings, key=lambda item: item.finding_id))


def _pcb_geometry_fingerprint(placement: AntennaPlacementResult) -> str:
    return fingerprint(
        {
            "board_layout_snapshot_json": placement.board_layout_snapshot_json,
            "board_layout_snapshot_fingerprint": placement.board_layout_snapshot_fingerprint,
            "declaration_keepouts": [
                item.model_dump(mode="json") for item in placement.declaration.keepouts
            ],
            "placed_regions": [
                item.model_dump(mode="json") for item in placement.placed_regions
            ],
        }
    )


def rederive_antenna_enclosure_exclusion(
    placement_result: AntennaPlacementResult,
    declaration: AntennaEnclosureExclusionDeclaration,
    enclosure_profile: EnclosureObjectProfile | None,
) -> dict[str, Any]:
    placement = AntennaPlacementResult.model_validate_json(placement_result.model_dump_json())
    retained = _validate_declaration(placement, declaration)
    profile = _validate_profile(retained, enclosure_profile)
    before = _pcb_geometry_fingerprint(placement)
    transformed = None if profile is None else _transform_exclusion(placement, retained, profile)
    evidence: list[AntennaEnclosureDistanceEvidence] = []
    if profile is None:
        evidence.append(
            _pending_evidence(
                retained, "enclosure-profile:missing", None, "enclosure_profile_missing"
            )
        )
    elif profile.model_geometry_status == "missing":
        evidence.append(
            _pending_evidence(
                retained, "enclosure-model:missing", None, "enclosure_model_geometry_missing"
            )
        )
    else:
        if profile.completeness == "incomplete":
            evidence.append(
                _pending_evidence(
                    retained,
                    "enclosure-profile:incomplete",
                    None,
                    "enclosure_profile_inventory_incomplete",
                )
            )
        by_id = {item.object_id: item for item in profile.objects}
        for object_id in profile.expected_object_ids:
            item = by_id.get(object_id)
            if item is None:
                evidence.append(
                    _pending_evidence(retained, object_id, None, "expected_object_missing")
                )
            else:
                assert transformed is not None
                evidence.append(_exact_evidence(retained, transformed, item))
    canonical_evidence = tuple(sorted(evidence, key=lambda item: item.object_id))
    after = _pcb_geometry_fingerprint(placement)
    if before != after:
        raise ValueError("3-D enclosure evaluation changed retained 2-D PCB geometry")
    evidence_fp = fingerprint(
        {
            "transformed_exclusion": (
                None if transformed is None else transformed.model_dump(mode="json")
            ),
            "evidence": [item.model_dump(mode="json") for item in canonical_evidence],
        }
    )
    semantic = SemanticLayoutResult.build(
        context_fingerprint=retained.applicability_binding.semantic_fingerprint(),
        declarations_fingerprint=retained.semantic_fingerprint(),
        geometry_fingerprint=evidence_fp,
        placement_candidate_fingerprint=placement.result_fingerprint,
        findings=_findings(retained, canonical_evidence),
    )
    return {
        "declaration": retained,
        "enclosure_profile": profile,
        "transformed_exclusion": transformed,
        "evidence": canonical_evidence,
        "pcb_geometry_before_fingerprint": before,
        "pcb_geometry_after_fingerprint": after,
        "evidence_fingerprint": evidence_fp,
        "semantic_result": semantic,
    }


def evaluate_antenna_enclosure_exclusion(
    placement_result: AntennaPlacementResult,
    declaration: AntennaEnclosureExclusionDeclaration,
    enclosure_profile: EnclosureObjectProfile | None,
) -> AntennaEnclosureExclusionResult:
    """Evaluate only source-bound 3-D enclosure exclusion; retain PCB geometry."""

    derived = rederive_antenna_enclosure_exclusion(
        placement_result, declaration, enclosure_profile
    )
    fields = {"placement_result": placement_result, **derived}
    provisional = AntennaEnclosureExclusionResult.model_construct(
        **fields, result_fingerprint="0" * 64
    )
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return AntennaEnclosureExclusionResult(**fields, result_fingerprint=result_fp)
