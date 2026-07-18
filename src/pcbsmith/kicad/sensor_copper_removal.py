"""Replay-bound KiCad adapter for exact sensor copper-removal checks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypedDict, cast

from pcbsmith.copper_exposure import CopperGeometryVerification, OuterCopperRegion
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.copper_exposure import collect_outer_copper_regions
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.mask_geometry import (
    ApertureRelation,
    MaskSide,
    measure_geometry,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticVerification,
)
from pcbsmith.sensor_copper_removal_ir import (
    CopperRemovalEvaluationResult,
    CopperRemovalPairEvidence,
    CopperRemovalPhysicalSource,
    CopperRemovalRegionDeclaration,
    CopperRemovalSourceEvidence,
    CopperRemovalSourceKind,
    ExactFilledZoneCopper,
    fingerprint,
)
from pcbsmith.sensor_isolation_ir import (
    SensorIsolationEvaluationResult,
    SensorIsolationFeatureKind,
)

_NO_NET = "<no-net>"
_SIDE_TO_LAYER = {MaskSide.FRONT: "F.Cu", MaskSide.BACK: "B.Cu"}


class _Derived(TypedDict):
    isolation_result: SensorIsolationEvaluationResult
    declarations: tuple[CopperRemovalRegionDeclaration, ...]
    exact_filled_zones: tuple[ExactFilledZoneCopper, ...]
    board_layout_fingerprint: str
    board_layout_snapshot_fingerprint: str
    board_netlist_fingerprint: str
    physical_sources: tuple[CopperRemovalPhysicalSource, ...]
    pair_evidence: tuple[CopperRemovalPairEvidence, ...]
    source_evidence: tuple[CopperRemovalSourceEvidence, ...]
    source_geometry_fingerprint: str
    input_fingerprint: str
    findings: tuple[SemanticFinding, ...]
    semantic_result: SemanticLayoutResult


def _source_kind(region: OuterCopperRegion) -> CopperRemovalSourceKind:
    if region.source_id.startswith("track:"):
        return CopperRemovalSourceKind.TRACK
    if region.source_id.startswith("via:"):
        return CopperRemovalSourceKind.VIA_LAND
    if region.source_id.startswith("pad:"):
        return CopperRemovalSourceKind.PAD
    if region.source_id.startswith("zone:"):
        return CopperRemovalSourceKind.ZONE_INTENT
    raise ValueError(f"unrecognized physical copper source identity: {region.source_id}")


def _physical_sources(
    regions: Sequence[OuterCopperRegion],
    fills: Sequence[ExactFilledZoneCopper],
) -> tuple[CopperRemovalPhysicalSource, ...]:
    fill_by_id = {item.zone_source_id: item for item in fills}
    if len(fill_by_id) != len(fills):
        raise ValueError("exact filled-zone source identities must be unique")
    result: list[CopperRemovalPhysicalSource] = []
    seen: set[str] = set()
    resolved: set[str] = set()
    for region in regions:
        if region.source_id in seen:
            raise ValueError(f"duplicate physical copper source identity: {region.source_id}")
        seen.add(region.source_id)
        layer = cast(Literal["F.Cu", "B.Cu"], _SIDE_TO_LAYER[region.side])
        fill = fill_by_id.get(region.source_id)
        if fill is not None:
            if _source_kind(region) is not CopperRemovalSourceKind.ZONE_INTENT:
                raise ValueError("exact final fill may resolve only live zone intent")
            if fill.layer != layer or fill.zone_net_name != region.net_name:
                raise ValueError("exact final fill zone net/layer differs from live zone intent")
            resolved.add(region.source_id)
            result.append(
                CopperRemovalPhysicalSource(
                    source_id=region.source_id,
                    parent_source_id=region.parent_source_id,
                    source_kind=CopperRemovalSourceKind.EXACT_FILLED_ZONE,
                    net_name=region.net_name,
                    layer=fill.layer,
                    geometry=fill.geometry,
                    verification=CopperGeometryVerification.EXACT,
                    final_fill_record_sha256=fill.final_fill_record_sha256,
                )
            )
            continue
        result.append(
            CopperRemovalPhysicalSource(
                source_id=region.source_id,
                parent_source_id=region.parent_source_id,
                source_kind=_source_kind(region),
                net_name=region.net_name,
                layer=layer,
                geometry=region.geometry,
                verification=region.verification,
                unsupported_reason=region.unsupported_reason,
            )
        )
    if resolved != set(fill_by_id):
        raise ValueError("exact filled-zone record does not cover a live zone source")
    return tuple(sorted(result, key=lambda item: item.source_id))


def _declaration_authority(
    declaration: CopperRemovalRegionDeclaration,
    isolation: SensorIsolationEvaluationResult,
) -> bool:
    catalog = isolation.catalog
    if declaration.candidate_id != catalog.candidate.candidate_id:
        return False
    feature = next(
        (
            item
            for item in catalog.candidate.features
            if item.feature_id == declaration.source_feature_id
        ),
        None,
    )
    if feature is None or feature.feature_kind is not SensorIsolationFeatureKind.SLOT:
        return False
    region = next((item for item in catalog.regions if item.region_id == feature.region_id), None)
    limit = next(
        (item for item in catalog.process_profile.limits if item.limit_id == feature.limit_id),
        None,
    )
    evidence = next(
        (item for item in isolation.feature_evidence if item.feature_id == feature.feature_id),
        None,
    )
    if region is None or limit is None or evidence is None:
        return False
    required = tuple(
        sorted(
            {
                *catalog.candidate.source_binding_ids,
                *feature.source_binding_ids,
                *region.source_binding_ids,
                *limit.applicability_binding_ids,
                *limit.minimum.source_binding_ids,
            }
        )
    )
    geometry_binding = declaration.geometry_evidence_binding
    geometry_rule = declaration.geometry_rule
    binding_is_complete = _geometry_binding_complete(geometry_binding)
    retained_binding_ids = {
        item.binding_id for item in isolation.context.semantic_profile.evidence_bindings
    }
    if isolation.context.assembly_profile is not None:
        retained_binding_ids.update(
            item.binding_id for item in isolation.context.assembly_profile.evidence_bindings
        )
    expected_rule_objects = tuple(
        sorted(
            (
                declaration.declaration_id,
                declaration.candidate_id,
                declaration.source_feature_id,
            )
        )
    )
    return (
        declaration.isolation_result_fingerprint == isolation.semantic_fingerprint()
        and declaration.region_id == feature.region_id
        and declaration.evidence_binding_ids == required
        and declaration.applicability_binding_ids == tuple(sorted(limit.applicability_binding_ids))
        and evidence.authority_complete
        and binding_is_complete
        and geometry_binding.geometry_source_fingerprint
        == declaration.geometry.semantic_fingerprint()
        and geometry_binding.binding_id not in declaration.evidence_binding_ids
        and geometry_binding.binding_id not in declaration.applicability_binding_ids
        and geometry_binding.binding_id not in retained_binding_ids
        and geometry_rule.rule_id == declaration.rule_id
        and geometry_rule.authority is SemanticAuthorityClass.HARD_GEOMETRY
        and geometry_rule.process_profile_id is None
        and geometry_rule.qualified_process_record_id is None
        and geometry_rule.validation_requirement_ids == ()
        and geometry_rule.object_ids == expected_rule_objects
        and geometry_rule.geometry_region_ids == (declaration.region_id,)
        and geometry_rule.evidence_binding_ids == (geometry_binding.binding_id,)
    )


def _geometry_binding_complete(binding: EvidenceApplicabilityBinding) -> bool:
    return (
        bool(binding.required_conditions)
        and not binding.unmatched_conditions
        and set(binding.matched_conditions) == set(binding.required_conditions)
        and binding.geometry_source_fingerprint is not None
        and binding.reviewer_record_id is not None
        and all(
            item.source_status == "pinned"
            and item.local_sha256 is not None
            and item.locator_status in {"text_verified", "figure_verified"}
            and item.applicability_status == "confirmed"
            for item in binding.evidence
        )
    )


def _derive_evidence(
    sources: Sequence[CopperRemovalPhysicalSource],
    declarations: Sequence[CopperRemovalRegionDeclaration],
    isolation: SensorIsolationEvaluationResult,
) -> tuple[
    tuple[CopperRemovalPairEvidence, ...],
    tuple[CopperRemovalSourceEvidence, ...],
    tuple[SemanticFinding, ...],
]:
    declarations_by_layer: dict[str, list[CopperRemovalRegionDeclaration]] = {
        "F.Cu": [],
        "B.Cu": [],
    }
    known_bindings = {
        item.binding_id for item in isolation.context.semantic_profile.evidence_bindings
    }
    if isolation.context.assembly_profile is not None:
        known_bindings.update(
            item.binding_id for item in isolation.context.assembly_profile.evidence_bindings
        )
    for declaration in declarations:
        unknown = (
            set(declaration.evidence_binding_ids) | set(declaration.applicability_binding_ids)
        ) - known_bindings
        if unknown:
            raise ValueError(
                "copper-removal declaration cites unknown context evidence: "
                + ", ".join(sorted(unknown))
            )
        declarations_by_layer[declaration.layer].append(declaration)
    pairs: list[CopperRemovalPairEvidence] = []
    source_evidence: list[CopperRemovalSourceEvidence] = []
    findings: list[SemanticFinding] = []
    for source in sources:
        applicable = sorted(
            declarations_by_layer[source.layer], key=lambda item: item.declaration_id
        )
        source_dispositions: list[SemanticDisposition] = []
        for declaration in applicable:
            authority = _declaration_authority(declaration, isolation)
            if source.verification is CopperGeometryVerification.UNSUPPORTED:
                relation = None
                verification = SemanticVerification.UNSUPPORTED
                disposition = SemanticDisposition.UNVERIFIED
                message = "Relevant physical copper geometry or final zone fill is unresolved"
                action = (
                    "Provide exact supported copper geometry or a bound exact final-fill record"
                )
            else:
                assert source.geometry is not None
                relation = measure_geometry(source.geometry, declaration.geometry).relation
                verification = SemanticVerification.EXACT
                if not authority:
                    disposition = SemanticDisposition.UNVERIFIED
                    message = "Selected declaration lacks complete retained geometry authority"
                    action = (
                        "Bind the exact removal geometry to its reviewed hard-geometry rule"
                    )
                elif relation is ApertureRelation.OVERLAP:
                    disposition = SemanticDisposition.FAIL
                    message = "Exact copper has positive-area overlap with the removal interior"
                    action = "Reroute or remove the copper from the declared removal region"
                elif relation is ApertureRelation.TOUCHING:
                    disposition = SemanticDisposition.PASS
                    message = (
                        "Exact copper touches only the removal boundary; deterministic "
                        "non-interior-overlap policy passes boundary contact"
                    )
                    action = "Retain exact boundary geometry and fabrication authority"
                else:
                    disposition = SemanticDisposition.PASS
                    message = "Exact copper is separated from the removal region"
                    action = "Retain the exact separated geometry"
            finding = SemanticFinding(
                rule_id=declaration.rule_id,
                authority=SemanticAuthorityClass.HARD_GEOMETRY,
                disposition=disposition,
                verification=verification,
                object_ids=(
                    declaration.declaration_id,
                    declaration.candidate_id,
                    declaration.source_feature_id,
                    source.source_id,
                ),
                net_refs=() if source.net_name == _NO_NET else (source.net_name,),
                region_ids=(declaration.region_id,),
                evidence_binding_ids=(declaration.geometry_evidence_binding.binding_id,),
                message=message,
                suggested_action=action,
            )
            findings.append(finding)
            pairs.append(
                CopperRemovalPairEvidence(
                    source_id=source.source_id,
                    declaration_id=declaration.declaration_id,
                    rule_id=declaration.rule_id,
                    net_name=source.net_name,
                    layer=source.layer,
                    relation=relation,
                    authority_complete=authority,
                    verification=verification,
                    disposition=disposition,
                    finding_id=finding.finding_id,
                )
            )
            source_dispositions.append(disposition)
        aggregate = (
            SemanticDisposition.NOT_APPLICABLE
            if not applicable
            else SemanticDisposition.FAIL
            if SemanticDisposition.FAIL in source_dispositions
            else SemanticDisposition.UNVERIFIED
            if SemanticDisposition.UNVERIFIED in source_dispositions
            else SemanticDisposition.PASS
        )
        source_evidence.append(
            CopperRemovalSourceEvidence(
                source_id=source.source_id,
                source_kind=source.source_kind,
                net_name=source.net_name,
                layer=source.layer,
                applicable_declaration_ids=tuple(item.declaration_id for item in applicable),
                disposition=aggregate,
            )
        )
    return (
        tuple(sorted(pairs, key=lambda item: (item.source_id, item.declaration_id))),
        tuple(sorted(source_evidence, key=lambda item: item.source_id)),
        tuple(sorted(findings, key=lambda item: item.finding_id)),
    )


def _validate_fills(
    fills: Sequence[ExactFilledZoneCopper],
    layout: BoardLayout,
    layout_fingerprint: str,
) -> tuple[ExactFilledZoneCopper, ...]:
    canonical = tuple(
        sorted(
            (ExactFilledZoneCopper.model_validate_json(item.model_dump_json()) for item in fills),
            key=lambda item: item.zone_source_id,
        )
    )
    if len({item.zone_source_id for item in canonical}) != len(canonical):
        raise ValueError("exact filled-zone source identities must be unique")
    for fill in canonical:
        if fill.board_layout_fingerprint != layout_fingerprint:
            raise ValueError("exact filled-zone record is stale for this BoardLayout")
        if fill.zone_index >= len(layout.zones):
            raise ValueError("exact filled-zone record references an absent zone")
        net_name, layer, _rect = layout.zones[fill.zone_index]
        expected_source_id = f"zone:{fill.zone_index}:copper:{layer}"
        if (
            fill.zone_source_id != expected_source_id
            or fill.zone_net_name != (net_name or _NO_NET)
            or fill.layer != layer
        ):
            raise ValueError("exact filled-zone record has the wrong zone identity/net/layer")
    return canonical


def rederive_copper_removal_result(
    *,
    isolation_result: SensorIsolationEvaluationResult,
    board_layout_snapshot_json: str,
    board_netlist_snapshot_json: str,
    declarations: Sequence[CopperRemovalRegionDeclaration],
    exact_filled_zones: Sequence[ExactFilledZoneCopper],
) -> _Derived:
    isolation = SensorIsolationEvaluationResult.model_validate_json(
        isolation_result.model_dump_json()
    )
    layout = parse_canonical_board_layout_snapshot(board_layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(board_netlist_snapshot_json)
    # Exact round-trip equality proves the parser consumed every retained field.
    if board_layout_snapshot_json != canonical_board_layout_snapshot_json(layout):
        raise ValueError("board layout snapshot did not round-trip exactly")
    if board_netlist_snapshot_json != canonical_board_netlist_snapshot_json(netlist):
        raise ValueError("board netlist snapshot did not round-trip exactly")
    layout_fp = board_layout_fingerprint(layout)
    if isolation.board_layout_fingerprint != layout_fp:
        raise ValueError("accepted sensor-isolation result is bound to another BoardLayout")
    declaration_values = tuple(
        sorted(
            (
                CopperRemovalRegionDeclaration.model_validate_json(item.model_dump_json())
                for item in declarations
            ),
            key=lambda item: item.declaration_id,
        )
    )
    if len({item.declaration_id for item in declaration_values}) != len(declaration_values):
        raise ValueError("copper-removal declaration identities must be unique")
    fills = _validate_fills(exact_filled_zones, layout, layout_fp)
    regions = collect_outer_copper_regions(layout, netlist)
    sources = _physical_sources(regions, fills)
    pairs, source_evidence, findings = _derive_evidence(sources, declaration_values, isolation)
    source_fp = fingerprint([item.model_dump(mode="json") for item in sources])
    layout_snapshot_fp = board_layout_snapshot_fingerprint(board_layout_snapshot_json)
    netlist_fp = board_netlist_snapshot_fingerprint(board_netlist_snapshot_json)
    declarations_fp = fingerprint([item.model_dump(mode="json") for item in declaration_values])
    inputs = {
        "isolation_result_fingerprint": isolation.semantic_fingerprint(),
        "board_layout_fingerprint": layout_fp,
        "board_layout_snapshot_fingerprint": layout_snapshot_fp,
        "board_netlist_fingerprint": netlist_fp,
        "declarations_fingerprint": declarations_fp,
        "exact_filled_zones_fingerprint": fingerprint(
            [item.model_dump(mode="json") for item in fills]
        ),
        "source_geometry_fingerprint": source_fp,
    }
    input_fp = fingerprint(inputs)
    semantic = SemanticLayoutResult.build(
        context_fingerprint=isolation.context.semantic_fingerprint(),
        declarations_fingerprint=declarations_fp,
        geometry_fingerprint=source_fp,
        metrics=(),
        findings=findings,
    )
    if (
        any(
            item.disposition in {SemanticDisposition.FAIL, SemanticDisposition.UNVERIFIED}
            for item in source_evidence
            if item.applicable_declaration_ids
        )
        and semantic.outcome.value == "passed"
    ):
        raise ValueError("aggregate semantic result cannot pass failed/unverified copper")
    return {
        "isolation_result": isolation,
        "declarations": declaration_values,
        "exact_filled_zones": fills,
        "board_layout_fingerprint": layout_fp,
        "board_layout_snapshot_fingerprint": layout_snapshot_fp,
        "board_netlist_fingerprint": netlist_fp,
        "physical_sources": sources,
        "pair_evidence": pairs,
        "source_evidence": source_evidence,
        "source_geometry_fingerprint": source_fp,
        "input_fingerprint": input_fp,
        "findings": findings,
        "semantic_result": semantic,
    }


def evaluate_sensor_copper_removal(
    layout: BoardLayout,
    netlist: BoardNetlist,
    isolation_result: SensorIsolationEvaluationResult,
    declarations: Sequence[CopperRemovalRegionDeclaration],
    *,
    exact_filled_zones: Sequence[ExactFilledZoneCopper] = (),
) -> CopperRemovalEvaluationResult:
    """Evaluate exact positive-area copper overlap with explicit removal regions."""

    layout_snapshot = canonical_board_layout_snapshot_json(layout)
    netlist_snapshot = canonical_board_netlist_snapshot_json(netlist)
    derived = rederive_copper_removal_result(
        isolation_result=isolation_result,
        board_layout_snapshot_json=layout_snapshot,
        board_netlist_snapshot_json=netlist_snapshot,
        declarations=declarations,
        exact_filled_zones=exact_filled_zones,
    )
    return CopperRemovalEvaluationResult(
        isolation_result=derived["isolation_result"],
        board_layout_snapshot_json=layout_snapshot,
        board_netlist_snapshot_json=netlist_snapshot,
        board_layout_fingerprint=derived["board_layout_fingerprint"],
        board_layout_snapshot_fingerprint=derived["board_layout_snapshot_fingerprint"],
        board_netlist_fingerprint=derived["board_netlist_fingerprint"],
        declarations=derived["declarations"],
        exact_filled_zones=derived["exact_filled_zones"],
        physical_sources=derived["physical_sources"],
        pair_evidence=derived["pair_evidence"],
        source_evidence=derived["source_evidence"],
        source_geometry_fingerprint=derived["source_geometry_fingerprint"],
        input_fingerprint=derived["input_fingerprint"],
        findings=derived["findings"],
        semantic_result=derived["semantic_result"],
    )
