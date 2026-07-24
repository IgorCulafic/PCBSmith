"""Evaluate only explicit, exact oscillator-zone authority; never inspect raw KiCad text."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.oscillator_zone_ir import (
    IoSeparationRequirement,
    OscillatorIntrusionEvidence,
    OscillatorObjectKind,
    OscillatorPhysicalObject,
    OscillatorRequirementEvidence,
    OscillatorZoneDeclaration,
    OscillatorZoneResult,
    QualifiedCapacitanceModelResult,
    ReferenceGroundCoverageProof,
    ReferenceGroundRequirement,
    StitchViaRequirement,
    fingerprint,
)
from pcbsmith.placement_geometry import (
    PlanarRelation,
    compound_distance_witness,
    compound_inside_polygon,
    compound_relation,
    diagnostic_distance_mm,
)
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticVerification,
)


def _disposition(authority: SemanticAuthorityClass, *, passed: bool) -> SemanticDisposition:
    if authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS:
        return SemanticDisposition.ADVISORY
    return SemanticDisposition.PASS if passed else SemanticDisposition.FAIL


def _exemption(
    declaration: OscillatorZoneDeclaration, item: OscillatorPhysicalObject
) -> str | None:
    ground_nets = {
        requirement.ground_net_name
        for requirement in (
            declaration.reference_ground_requirement,
            declaration.stitch_via_requirement,
        )
        if requirement is not None
    }
    if item.object_id in declaration.allowed_object_ids:
        return "object"
    if item.owner_component_ref in declaration.allowed_component_refs:
        return "component"
    if item.owner_net_name in declaration.oscillator_net_names:
        return "oscillator_net"
    if item.owner_net_name in declaration.allowed_net_names:
        return "allowed_net"
    if item.owner_net_name in ground_nets:
        return "local_ground"
    return None


def _intrusion(
    declaration: OscillatorZoneDeclaration, item: OscillatorPhysicalObject
) -> OscillatorIntrusionEvidence:
    assert declaration.zone_region is not None
    region = declaration.zone_region
    applicable_layers = tuple(sorted(set(region.layers) & set(item.layers)))
    exemption = _exemption(declaration, item)
    relation: PlanarRelation | None = None
    if not applicable_layers or exemption is not None:
        verification = SemanticVerification.EXACT
        disposition = SemanticDisposition.NOT_APPLICABLE
    elif item.verification is SemanticVerification.UNSUPPORTED:
        verification = SemanticVerification.UNSUPPORTED
        disposition = SemanticDisposition.UNVERIFIED
    else:
        assert region.compound is not None and item.compound is not None
        relation = compound_relation(region.compound, item.compound)
        verification = SemanticVerification.EXACT
        disposition = _disposition(
            declaration.intrusion_authority,
            passed=relation is PlanarRelation.DISJOINT,
        )
    class_ids = tuple(
        membership.net_class_id
        for membership in declaration.net_class_memberships
        if item.owner_net_name in membership.net_names
    )
    return OscillatorIntrusionEvidence(
        object_id=item.object_id,
        source_id=item.source_id,
        layers=item.layers,
        applicable_layers=applicable_layers,
        owner_component_ref=item.owner_component_ref,
        owner_net_name=item.owner_net_name,
        forbidden_net_class_ids=class_ids,
        exemption=exemption,
        relation=relation,
        verification=verification,
        disposition=disposition,
    )


def _ground_evidence(
    declaration: OscillatorZoneDeclaration,
    objects: tuple[OscillatorPhysicalObject, ...],
    proofs: tuple[ReferenceGroundCoverageProof, ...],
    requirement: ReferenceGroundRequirement,
) -> OscillatorRequirementEvidence:
    assert declaration.zone_region is not None and declaration.zone_region.compound is not None
    candidates = tuple(
        item
        for item in objects
        if item.kind is OscillatorObjectKind.FILLED_ZONE
        and item.owner_net_name == requirement.ground_net_name
        and set(item.layers) & set(requirement.required_layers)
    )
    exact_by_id = {
        item.object_id: item
        for item in candidates
        if item.verification is SemanticVerification.EXACT
    }
    for proof in proofs:
        item = exact_by_id.get(proof.ground_object_id)
        if item is None:
            raise ValueError("ground coverage proof does not identify an exact final fill")
        assert item.compound is not None
        inside = any(
            compound_inside_polygon(declaration.zone_region.compound, polygon)
            for polygon in item.compound.polygons
        )
        relation = compound_relation(declaration.zone_region.compound, item.compound)
        expected_predicate = (
            "zone_inside_single_fill_polygon"
            if inside
            else "exact_sets_disjoint"
            if relation is PlanarRelation.DISJOINT
            else None
        )
        if (
            proof.ground_source_id != item.source_id
            or proof.layer not in item.layers
            or proof.layer not in requirement.required_layers
            or proof.zone_geometry_fingerprint
            != declaration.zone_region.compound.semantic_fingerprint()
            or proof.ground_geometry_fingerprint != item.compound.semantic_fingerprint()
            or not set(proof.source_binding_ids).issubset(requirement.source_binding_ids)
            or proof.predicate != expected_predicate
        ):
            raise ValueError(
                "ground coverage proof has a forged/stale predicate, geometry, "
                "source, layer, or evidence"
            )
    coverage_by_layer: dict[str, int | None] = {}
    for layer in requirement.required_layers:
        layer_candidates = tuple(item for item in exact_by_id.values() if layer in item.layers)
        contains = any(
            compound_inside_polygon(declaration.zone_region.compound, polygon)
            for item in layer_candidates
            if item.compound is not None
            for polygon in item.compound.polygons
        )
        has_unknown = any(
            item.verification is SemanticVerification.UNSUPPORTED and layer in item.layers
            for item in candidates
        )
        if contains:
            coverage_by_layer[layer] = 10_000
        elif (
            layer_candidates
            and not has_unknown
            and all(
                compound_relation(declaration.zone_region.compound, item.compound)
                is PlanarRelation.DISJOINT
                for item in layer_candidates
                if item.compound is not None
            )
        ):
            coverage_by_layer[layer] = 0
        else:
            coverage_by_layer[layer] = None
    object_ids = tuple(item.object_id for item in candidates)
    source_ids = tuple(item.source_id for item in candidates)
    if any(value is None for value in coverage_by_layer.values()):
        verification = SemanticVerification.UNSUPPORTED
        disposition = SemanticDisposition.UNVERIFIED
        measured = None
        unit = None
    else:
        measured = float(min(value for value in coverage_by_layer.values() if value is not None))
        unit = "basis_points"
        verification = SemanticVerification.EXACT
        disposition = _disposition(
            requirement.authority,
            passed=measured >= requirement.minimum_coverage_basis_points,
        )
    return OscillatorRequirementEvidence(
        requirement_id=requirement.requirement_id,
        finding_kind="reference_ground",
        object_ids=object_ids,
        source_ids=source_ids,
        layers=requirement.required_layers,
        measured_value=measured,
        measured_unit=unit,
        relation=None,
        verification=verification,
        disposition=disposition,
    )


def _stitch_evidence(
    declaration: OscillatorZoneDeclaration,
    objects: tuple[OscillatorPhysicalObject, ...],
    requirement: StitchViaRequirement,
) -> tuple[OscillatorRequirementEvidence, OscillatorRequirementEvidence]:
    assert declaration.zone_region is not None and declaration.zone_region.compound is not None
    vias = tuple(
        item
        for item in objects
        if item.kind is OscillatorObjectKind.VIA
        and item.owner_net_name == requirement.ground_net_name
        and set(item.layers) & set(requirement.required_layers)
    )
    object_ids = tuple(item.object_id for item in vias)
    source_ids = tuple(item.source_id for item in vias)
    count_disposition = _disposition(
        requirement.authority, passed=len(vias) >= requirement.minimum_count
    )
    count = OscillatorRequirementEvidence(
        requirement_id=requirement.requirement_id,
        finding_kind="stitch_count",
        object_ids=object_ids,
        source_ids=source_ids,
        layers=tuple(sorted({layer for item in vias for layer in item.layers})),
        measured_value=float(len(vias)),
        measured_unit="count",
        relation=None,
        verification=SemanticVerification.EXACT,
        disposition=count_disposition,
    )
    if not requirement.require_touch_or_intersection:
        placed_count = len(vias)
        placement_verification = SemanticVerification.EXACT
        placement_disposition = _disposition(requirement.authority, passed=True)
    elif any(item.verification is SemanticVerification.UNSUPPORTED for item in vias):
        placed_count = None
        placement_verification = SemanticVerification.UNSUPPORTED
        placement_disposition = SemanticDisposition.UNVERIFIED
    else:
        placed_count = sum(
            compound_relation(declaration.zone_region.compound, item.compound)
            is not PlanarRelation.DISJOINT
            for item in vias
            if item.compound is not None
        )
        placement_verification = SemanticVerification.EXACT
        placement_disposition = _disposition(
            requirement.authority, passed=placed_count >= requirement.minimum_count
        )
    placement = OscillatorRequirementEvidence(
        requirement_id=requirement.requirement_id,
        finding_kind="stitch_placement",
        object_ids=object_ids,
        source_ids=source_ids,
        layers=tuple(sorted({layer for item in vias for layer in item.layers})),
        measured_value=None if placed_count is None else float(placed_count),
        measured_unit=None if placed_count is None else "count",
        relation=None,
        verification=placement_verification,
        disposition=placement_disposition,
    )
    return count, placement


def _io_evidence(
    declaration: OscillatorZoneDeclaration, requirement: IoSeparationRequirement
) -> OscillatorRequirementEvidence:
    assert declaration.zone_region is not None
    assert declaration.zone_region.compound is not None
    assert requirement.io_region.compound is not None
    witness = compound_distance_witness(
        declaration.zone_region.compound, requirement.io_region.compound
    )
    required = Fraction(str(requirement.minimum_separation.value))
    disposition = _disposition(
        requirement.authority, passed=witness.squared_distance >= required * required
    )
    return OscillatorRequirementEvidence(
        requirement_id=requirement.requirement_id,
        finding_kind="io_separation",
        object_ids=(),
        source_ids=(),
        layers=tuple(
            sorted(set(declaration.zone_region.layers) & set(requirement.io_region.layers))
        ),
        measured_value=diagnostic_distance_mm(witness.squared_distance),
        measured_unit="mm",
        relation=witness.relation,
        verification=SemanticVerification.EXACT,
        disposition=disposition,
    )


def _capacitance_evidence(
    declaration: OscillatorZoneDeclaration,
    requirement_objects_fp: str,
    model: QualifiedCapacitanceModelResult | None,
) -> OscillatorRequirementEvidence:
    requirement = declaration.stray_capacitance_requirement
    assert requirement is not None and declaration.zone_region is not None
    if model is None:
        return OscillatorRequirementEvidence(
            requirement_id=requirement.requirement_id,
            finding_kind="stray_capacitance",
            verification=SemanticVerification.UNSUPPORTED,
            disposition=SemanticDisposition.UNVERIFIED,
        )
    assert declaration.zone_region.compound is not None
    known_bindings = {item.binding_id for item in declaration.evidence_bindings}
    binding_by_id = {item.binding_id: item for item in declaration.evidence_bindings}
    model_binding_ids = set(model.source_binding_ids) | set(
        model.calculated_capacitance.source_binding_ids
    )
    if (
        model.status != "active"
        or model.board_layout_snapshot_fingerprint != declaration.board_layout_snapshot_fingerprint
        or model.board_netlist_snapshot_fingerprint
        != declaration.board_netlist_snapshot_fingerprint
        or model.zone_geometry_fingerprint
        != declaration.zone_region.compound.semantic_fingerprint()
        or model.physical_objects_fingerprint != requirement_objects_fp
        or not model_binding_ids.issubset(known_bindings)
        or any(
            not _binding_is_complete(binding_by_id[binding_id]) for binding_id in model_binding_ids
        )
    ):
        raise ValueError("capacitance model authority is inactive, stale, or out of scope")
    measured = model.calculated_capacitance.value
    disposition = _disposition(
        requirement.authority,
        passed=measured <= requirement.maximum_capacitance.value,
    )
    return OscillatorRequirementEvidence(
        requirement_id=requirement.requirement_id,
        finding_kind="stray_capacitance",
        measured_value=measured,
        measured_unit="pF",
        verification=SemanticVerification.EXACT,
        disposition=disposition,
    )


def _binding_is_complete(binding: Any) -> bool:
    binding_conditions = set(binding.required_conditions)
    return (
        binding.reviewer_record_id is not None
        and bool(binding.required_conditions)
        and not binding.unmatched_conditions
        and set(binding.matched_conditions) == binding_conditions
        and all(
            bool(evidence.source_id and evidence.source_id.strip())
            and bool(evidence.revision and evidence.revision.strip())
            and evidence.source_status == "pinned"
            and evidence.local_sha256 is not None
            and len(evidence.local_sha256) == 64
            and all(
                character in "0123456789abcdef"
                for character in evidence.local_sha256
            )
            and evidence.locator_status in {"text_verified", "figure_verified"}
            and evidence.applicability_status == "confirmed"
            and bool(evidence.required_conditions)
            and set(evidence.required_conditions).issubset(binding_conditions)
            for evidence in binding.evidence
        )
    )


def _finding_for_intrusion(
    declaration: OscillatorZoneDeclaration,
    evidence: OscillatorIntrusionEvidence,
) -> SemanticFinding:
    messages = {
        SemanticDisposition.NOT_APPLICABLE: (
            "Object is outside layer scope or explicitly local/allowed."
        ),
        SemanticDisposition.UNVERIFIED: "Applicable object geometry is unsupported.",
        SemanticDisposition.ADVISORY: (
            "Exact foreign-object relation is reported as advisory evidence."
        ),
        SemanticDisposition.PASS: "Exact foreign object is disjoint from the oscillator zone.",
        SemanticDisposition.FAIL: "Exact foreign object touches or intersects the oscillator zone.",
    }
    return SemanticFinding(
        rule_id=declaration.intrusion_rule_id,
        authority=declaration.intrusion_authority,
        disposition=evidence.disposition,
        verification=evidence.verification,
        object_ids=(evidence.object_id,),
        component_refs=(evidence.owner_component_ref,) if evidence.owner_component_ref else (),
        net_refs=(evidence.owner_net_name,) if evidence.owner_net_name else (),
        region_ids=(declaration.zone_id,),
        evidence_binding_ids=tuple(item.binding_id for item in declaration.evidence_bindings),
        message=messages[evidence.disposition],
        suggested_action="Retain explicit authority or move/remove the foreign object.",
    )


def _requirement_finding(
    declaration: OscillatorZoneDeclaration, evidence: OscillatorRequirementEvidence
) -> SemanticFinding:
    if evidence.finding_kind == "reference_ground":
        ground = declaration.reference_ground_requirement
        assert ground is not None
        rule_id, authority, bindings = (
            ground.rule_id,
            ground.authority,
            ground.source_binding_ids,
        )
    elif evidence.finding_kind in {"stitch_count", "stitch_placement"}:
        stitch = declaration.stitch_via_requirement
        assert stitch is not None
        rule_id = (
            stitch.count_rule_id
            if evidence.finding_kind == "stitch_count"
            else stitch.placement_rule_id
        )
        authority, bindings = stitch.authority, stitch.source_binding_ids
    elif evidence.finding_kind == "io_separation":
        separation = declaration.io_separation_requirement
        assert separation is not None
        rule_id, authority = separation.rule_id, separation.authority
        bindings = separation.minimum_separation.source_binding_ids
    else:
        capacitance = declaration.stray_capacitance_requirement
        assert capacitance is not None
        rule_id, authority = capacitance.rule_id, capacitance.authority
        bindings = capacitance.maximum_capacitance.source_binding_ids
    return SemanticFinding(
        rule_id=rule_id,
        authority=authority,
        disposition=evidence.disposition,
        verification=evidence.verification,
        object_ids=evidence.object_ids,
        region_ids=(declaration.zone_id,),
        evidence_binding_ids=bindings,
        message=(
            f"Oscillator-zone {evidence.finding_kind.replace('_', ' ')} evaluated independently."
        ),
        suggested_action="Provide exact scoped authority or satisfy the declared requirement.",
    )


def rederive_oscillator_zone(
    declaration: OscillatorZoneDeclaration,
    physical_objects: Sequence[OscillatorPhysicalObject],
    coverage_proofs: Sequence[ReferenceGroundCoverageProof] = (),
    capacitance_model_result: QualifiedCapacitanceModelResult | None = None,
) -> dict[str, Any]:
    declaration = OscillatorZoneDeclaration.model_validate_json(declaration.model_dump_json())
    objects = tuple(
        sorted(
            (
                OscillatorPhysicalObject.model_validate_json(item.model_dump_json())
                for item in physical_objects
            ),
            key=lambda item: item.object_id,
        )
    )
    proofs = tuple(
        sorted(
            (
                ReferenceGroundCoverageProof.model_validate_json(item.model_dump_json())
                for item in coverage_proofs
            ),
            key=lambda item: item.proof_id,
        )
    )
    model = (
        None
        if capacitance_model_result is None
        else QualifiedCapacitanceModelResult.model_validate_json(
            capacitance_model_result.model_dump_json()
        )
    )
    if len({item.object_id for item in objects}) != len(objects):
        raise ValueError("oscillator physical object identities must be unique")
    if len({item.source_id for item in objects}) != len(objects):
        raise ValueError("oscillator physical object source identities must be unique")
    fill_ids = tuple(
        item.exact_final_fill_provenance.fill_provenance_id
        for item in objects
        if item.exact_final_fill_provenance is not None
    )
    if len(fill_ids) != len(set(fill_ids)):
        raise ValueError("oscillator final-fill provenance identities must be unique")
    if len({*(item.source_id for item in objects), *fill_ids}) != len(objects) + len(fill_ids):
        raise ValueError("oscillator source/fill provenance namespaces must not collide")
    if len({item.proof_id for item in proofs}) != len(proofs):
        raise ValueError("ground coverage proof identities must be unique")
    netlist = parse_canonical_board_netlist_snapshot(declaration.board_netlist_snapshot_json)
    refs = {item.reference for item in netlist.components}
    nets = {item.name for item in netlist.nets}
    for item in objects:
        if item.board_layout_snapshot_fingerprint != declaration.board_layout_snapshot_fingerprint:
            raise ValueError("oscillator object is bound to another BoardLayout")
        if (
            item.board_netlist_snapshot_fingerprint
            != declaration.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("oscillator object is bound to another BoardNetlist")
        if item.owner_component_ref is not None and item.owner_component_ref not in refs:
            raise ValueError("oscillator object owner component is absent from BoardNetlist")
        if item.owner_net_name is not None and item.owner_net_name not in nets:
            raise ValueError("oscillator object owner net is absent from BoardNetlist")
    objects_fp = fingerprint([item.model_dump(mode="json") for item in objects])
    proofs_fp = fingerprint([item.model_dump(mode="json") for item in proofs])
    intrusions: tuple[OscillatorIntrusionEvidence, ...] = ()
    requirements: list[OscillatorRequirementEvidence] = []
    if declaration.has_external_discrete_zone:
        intrusions = tuple(_intrusion(declaration, item) for item in objects)
        if declaration.reference_ground_requirement is not None:
            requirements.append(
                _ground_evidence(
                    declaration, objects, proofs, declaration.reference_ground_requirement
                )
            )
        elif proofs:
            raise ValueError("ground coverage proofs require a reference-ground declaration")
        if declaration.stitch_via_requirement is not None:
            requirements.extend(
                _stitch_evidence(declaration, objects, declaration.stitch_via_requirement)
            )
        if declaration.io_separation_requirement is not None:
            requirements.append(_io_evidence(declaration, declaration.io_separation_requirement))
        if declaration.stray_capacitance_requirement is not None:
            requirements.append(_capacitance_evidence(declaration, objects_fp, model))
        elif model is not None:
            raise ValueError("capacitance model result requires a stray-capacitance declaration")
        findings = tuple(_finding_for_intrusion(declaration, item) for item in intrusions) + tuple(
            _requirement_finding(declaration, item) for item in requirements
        )
    else:
        if objects or proofs or model is not None:
            raise ValueError("non-external oscillator declaration requires empty physical evidence")
        findings = (
            SemanticFinding(
                rule_id=declaration.applicability_rule_id,
                authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
                disposition=SemanticDisposition.NOT_APPLICABLE,
                verification=SemanticVerification.EXACT,
                evidence_binding_ids=tuple(
                    item.binding_id for item in declaration.evidence_bindings
                ),
                message="No external discrete-crystal oscillator zone is declared.",
                suggested_action="Do not invent a zone for an internal module oscillator.",
            ),
        )
    requirement_tuple = tuple(requirements)
    evidence_fp = fingerprint(
        {
            "intrusions": [item.model_dump(mode="json") for item in intrusions],
            "requirements": [item.model_dump(mode="json") for item in requirement_tuple],
        }
    )
    evaluation_authority_fp = fingerprint(
        {
            "physical_objects": objects_fp,
            "coverage_proofs": proofs_fp,
            "capacitance_model_result": (None if model is None else model.model_dump(mode="json")),
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
        geometry_fingerprint=evaluation_authority_fp,
        metrics=(),
        findings=findings,
    )
    return {
        "physical_objects": objects,
        "coverage_proofs": proofs,
        "capacitance_model_result": model,
        "intrusion_evidence": intrusions,
        "requirement_evidence": requirement_tuple,
        "physical_objects_fingerprint": objects_fp,
        "coverage_proofs_fingerprint": proofs_fp,
        "evidence_fingerprint": evidence_fp,
        "semantic_result": semantic,
    }


def evaluate_oscillator_zone(
    layout: BoardLayout,
    netlist: BoardNetlist,
    declaration: OscillatorZoneDeclaration,
    physical_objects: Sequence[OscillatorPhysicalObject],
    coverage_proofs: Sequence[ReferenceGroundCoverageProof] = (),
    capacitance_model_result: QualifiedCapacitanceModelResult | None = None,
) -> OscillatorZoneResult:
    """Replay the explicit declaration while proving caller inputs were not mutated."""

    layout_before = canonical_board_layout_snapshot_json(layout)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)
    if layout_before != declaration.board_layout_snapshot_json:
        raise ValueError("caller BoardLayout differs from the declaration snapshot")
    if netlist_before != declaration.board_netlist_snapshot_json:
        raise ValueError("caller BoardNetlist differs from the declaration snapshot")
    derived = rederive_oscillator_zone(
        declaration, physical_objects, coverage_proofs, capacitance_model_result
    )
    if canonical_board_layout_snapshot_json(layout) != layout_before:
        raise RuntimeError("oscillator evaluator mutated caller BoardLayout")
    if canonical_board_netlist_snapshot_json(netlist) != netlist_before:
        raise RuntimeError("oscillator evaluator mutated caller BoardNetlist")
    fields: dict[str, Any] = {"declaration": declaration, **derived}
    provisional = OscillatorZoneResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return OscillatorZoneResult(**fields, result_fingerprint=result_fp)
