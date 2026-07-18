"""Exact, explicit physical-object checks against placed antenna keepouts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pcbsmith.antenna_clearance_ir import (
    AntennaClearancePairEvidence,
    AntennaClearanceResult,
    AntennaPhysicalObject,
    fingerprint,
)
from pcbsmith.antenna_ir import AntennaPlacementResult, InstalledFootprintKeepoutProvenance
from pcbsmith.kicad.board_serialization import parse_canonical_board_netlist_snapshot
from pcbsmith.placement_geometry import (
    PlacementTransformAuthority,
    PlanarRelation,
    compound_relation,
)
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticVerification,
)


def _pair_id(keepout_id: str, object_id: str) -> str:
    return f"antenna-clearance:{fingerprint({'keepout': keepout_id, 'object': object_id})}"


def _pair(
    placement: AntennaPlacementResult,
    keepout: InstalledFootprintKeepoutProvenance,
    physical_object: AntennaPhysicalObject,
) -> AntennaClearancePairEvidence:
    placed = next(item for item in placement.placed_regions if item.region_id == keepout.region_id)
    kind_applicable = physical_object.kind in keepout.prohibited_object_kinds
    applicable_layers = tuple(sorted(set(keepout.layers) & set(physical_object.physical_layers)))
    layer_applicable = bool(applicable_layers)
    relation: PlanarRelation | None = None
    if not kind_applicable or not layer_applicable:
        verification = SemanticVerification.EXACT
        disposition = SemanticDisposition.NOT_APPLICABLE
    elif placed.bounded_transform.authority is PlacementTransformAuthority.BOUNDED_APPROXIMATION:
        verification = SemanticVerification.BOUNDED_APPROXIMATION
        disposition = SemanticDisposition.UNVERIFIED
    elif physical_object.verification is SemanticVerification.UNSUPPORTED:
        verification = SemanticVerification.UNSUPPORTED
        disposition = SemanticDisposition.UNVERIFIED
    else:
        if placed.exact_transformed_compound is None or physical_object.compound is None:
            raise ValueError("exact clearance pair is missing exact geometry authority")
        relation = compound_relation(placed.exact_transformed_compound, physical_object.compound)
        verification = SemanticVerification.EXACT
        disposition = (
            SemanticDisposition.PASS
            if relation is PlanarRelation.DISJOINT
            else SemanticDisposition.FAIL
        )
    return AntennaClearancePairEvidence(
        pair_id=_pair_id(keepout.provenance_id, physical_object.object_id),
        keepout_provenance_id=keepout.provenance_id,
        keepout_region_id=keepout.region_id,
        prohibited_object_rule_id=keepout.prohibited_object_rule_id,
        evidence_binding_ids=(keepout.module_guidance_binding_id,),
        object_id=physical_object.object_id,
        object_kind=physical_object.kind,
        keepout_layers=keepout.layers,
        object_layers=physical_object.physical_layers,
        applicable_layers=applicable_layers,
        kind_applicable=kind_applicable,
        layer_applicable=layer_applicable,
        relation=relation,
        verification=verification,
        disposition=disposition,
    )


def _finding(
    pair: AntennaClearancePairEvidence, physical_object: AntennaPhysicalObject
) -> SemanticFinding:
    messages = {
        SemanticDisposition.NOT_APPLICABLE: (
            "Object kind or physical layer is outside this keepout rule."
        ),
        SemanticDisposition.UNVERIFIED: "Applicable keepout clearance cannot be verified exactly.",
        SemanticDisposition.PASS: "Exact physical object is disjoint from the placed keepout.",
        SemanticDisposition.FAIL: "Exact physical object touches or overlaps the placed keepout.",
    }
    actions = {
        SemanticDisposition.NOT_APPLICABLE: "No action for this rule/object pair.",
        SemanticDisposition.UNVERIFIED: (
            "Provide exact placed and physical-object geometry authority."
        ),
        SemanticDisposition.PASS: "Retain the exact geometry and provenance record.",
        SemanticDisposition.FAIL: (
            "Move or remove the object, or add a later source-approved exception."
        ),
    }
    return SemanticFinding(
        rule_id=pair.prohibited_object_rule_id,
        authority=SemanticAuthorityClass.HARD_GEOMETRY,
        disposition=pair.disposition,
        verification=pair.verification,
        object_ids=(pair.object_id,),
        component_refs=(
            (physical_object.owner_component_ref,)
            if physical_object.owner_component_ref is not None
            else ()
        ),
        net_refs=(
            (physical_object.owner_net_name,) if physical_object.owner_net_name is not None else ()
        ),
        region_ids=(pair.keepout_region_id,),
        evidence_binding_ids=pair.evidence_binding_ids,
        message=messages[pair.disposition],
        suggested_action=actions[pair.disposition],
    )


def rederive_antenna_clearance(
    placement_result: AntennaPlacementResult,
    physical_objects: Sequence[AntennaPhysicalObject],
) -> dict[str, Any]:
    placement = AntennaPlacementResult.model_validate_json(placement_result.model_dump_json())
    objects = tuple(
        sorted(
            (
                AntennaPhysicalObject.model_validate_json(item.model_dump_json())
                for item in physical_objects
            ),
            key=lambda item: item.object_id,
        )
    )
    if len({item.object_id for item in objects}) != len(objects):
        raise ValueError("antenna physical object identities must be unique")
    source_ids = tuple(item.source_provenance_id for item in objects)
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("antenna physical-object source provenance identities must be unique")
    fill_ids = tuple(
        item.exact_zone_fill_provenance.fill_provenance_id
        for item in objects
        if item.exact_zone_fill_provenance is not None
    )
    if len(fill_ids) != len(set(fill_ids)):
        raise ValueError("antenna final-fill provenance identities must be unique")
    all_provenance_ids = (*source_ids, *fill_ids)
    if len(all_provenance_ids) != len(set(all_provenance_ids)):
        raise ValueError("antenna source/fill provenance namespaces must be collision-free")
    expected_layout_fp = placement.board_layout_snapshot_fingerprint
    if any(item.board_layout_snapshot_fingerprint != expected_layout_fp for item in objects):
        raise ValueError("antenna physical object is bound to another BoardLayout snapshot")
    netlist = parse_canonical_board_netlist_snapshot(placement.board_netlist_snapshot_json)
    component_refs = {item.reference for item in netlist.components}
    net_names = {item.name for item in netlist.nets}
    if any(
        item.owner_component_ref is not None and item.owner_component_ref not in component_refs
        for item in objects
    ):
        raise ValueError("antenna physical object owner component is absent from BoardNetlist")
    if any(
        item.owner_net_name is not None and item.owner_net_name not in net_names
        for item in objects
    ):
        raise ValueError("antenna physical object owner net is absent from BoardNetlist")
    pairs = tuple(
        _pair(placement, keepout, item)
        for keepout in placement.declaration.keepouts
        for item in objects
    )
    findings = (
        tuple(_finding(pair, objects_by_id[pair.object_id]) for pair in pairs)
        if (objects_by_id := {item.object_id: item for item in objects})
        else ()
    )
    objects_fp = fingerprint([item.model_dump(mode="json") for item in objects])
    pairs_fp = fingerprint([item.model_dump(mode="json") for item in pairs])
    semantic = SemanticLayoutResult.build(
        context_fingerprint=placement.declaration.module_guidance_binding.semantic_fingerprint(),
        declarations_fingerprint=placement.declaration.semantic_fingerprint(),
        geometry_fingerprint=objects_fp,
        placement_candidate_fingerprint=placement.result_fingerprint,
        metrics=(),
        findings=findings,
    )
    return {
        "physical_objects": objects,
        "pair_evidence": pairs,
        "physical_objects_fingerprint": objects_fp,
        "pair_evidence_fingerprint": pairs_fp,
        "semantic_result": semantic,
    }


def evaluate_antenna_clearance(
    placement_result: AntennaPlacementResult,
    physical_objects: Sequence[AntennaPhysicalObject],
) -> AntennaClearanceResult:
    """Check only explicit object authority; do not ingest raw board objects."""

    derived = rederive_antenna_clearance(placement_result, physical_objects)
    fields = {
        "placement_result": placement_result,
        **derived,
    }
    provisional = AntennaClearanceResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return AntennaClearanceResult(**fields, result_fingerprint=result_fp)
