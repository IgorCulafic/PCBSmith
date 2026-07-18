"""Live BoardLayout evaluator for opt-in, bounded thermal semantics.

The evaluator proves polygonal separation. It does not solve heat flow and only
emits a theta-model temperature estimate when every declared scope field matches.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from typing import Any

from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.placement_geometry import (
    PlacementTransform,
    PlacementTransformAuthority,
    compound_clearance_at_least,
    compound_distance_witness,
    transform_compound_bounded,
)
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticEvaluationContext,
    SemanticFinding,
    SemanticMetric,
    SemanticQuantity,
    SemanticVerification,
)
from pcbsmith.thermal_ir import (
    ThermalDeclarationCatalog,
    ThermalEvaluationResult,
    ThermalOperatingPoint,
    ThermalPlacementBinding,
    ThermalPredictionModel,
    ThermalRationalPoint,
    ThermalResolvedRegion,
    ThermalSensitiveDeclaration,
    ThermalSeparationEvidence,
    ThermalSourceDeclaration,
    compose_thermal_position_error,
    conservative_thermal_distance_mm,
    derive_thermal_unsupported_causes,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _netlist_fingerprint(netlist: BoardNetlist | None) -> str | None:
    if netlist is None:
        return None
    payload = {
        "schema_id": "pcbsmith-thermal-netlist-binding",
        "schema_version": 1,
        "components": [
            {
                "reference": item.reference,
                "value": item.value,
                "footprint": item.footprint,
                "uuid_path": item.uuid_path,
                "fields": sorted([list(field) for field in item.fields]),
            }
            for item in sorted(netlist.components, key=lambda value: value.reference)
        ],
        "nets": [
            {
                "name": item.name,
                "nodes": sorted([list(node) for node in item.nodes]),
            }
            for item in sorted(netlist.nets, key=lambda value: value.name)
        ],
    }
    return _fingerprint(payload)


def _placement_bindings(layout: BoardLayout) -> tuple[ThermalPlacementBinding, ...]:
    if len({component.reference for component, _ in layout.placements}) != len(layout.placements):
        raise ValueError("BoardLayout component references must be unique")
    bindings: list[ThermalPlacementBinding] = []
    for component, anchor_x_mm in layout.placements:
        transform = PlacementTransform(
            anchor_x_mm=anchor_x_mm,
            anchor_y_mm=placement_y(layout, component.reference),
            rotation_deg=placement_rotation(layout, component.reference),
            side="back" if component.reference in layout.part_flip else "front",
        )
        bindings.append(
            ThermalPlacementBinding(
                component_ref=component.reference,
                uuid_path=component.uuid_path,
                footprint=component.footprint,
                anchor_x_mm=transform.anchor_x_mm,
                anchor_y_mm=transform.anchor_y_mm,
                rotation_deg=transform.rotation_deg,
                side=transform.side,
            )
        )
    return tuple(sorted(bindings, key=lambda item: item.component_ref))


def _resolved_regions(
    declarations: ThermalDeclarationCatalog,
    bindings: Sequence[ThermalPlacementBinding],
) -> tuple[ThermalResolvedRegion, ...]:
    binding_by_ref = {item.component_ref: item for item in bindings}
    resolved: list[ThermalResolvedRegion] = []
    for region in declarations.regions:
        source_fingerprint = region.semantic_fingerprint()
        if region.coordinate_space == "board":
            resolved.append(
                ThermalResolvedRegion(
                    region_id=region.region_id,
                    source_region_fingerprint=source_fingerprint,
                    coordinate_space="board",
                    owner_reference=None,
                    placement_binding_fingerprint=None,
                    compound=region.compound,
                    verification=region.verification,
                    maximum_error_mm=region.maximum_error_mm,
                )
            )
            continue
        owner = region.owner_reference
        binding = None if owner is None else binding_by_ref.get(owner)
        binding_fingerprint = None if binding is None else binding.semantic_fingerprint()
        if (
            binding is None
            or region.verification is SemanticVerification.UNSUPPORTED
            or region.compound is None
        ):
            resolved.append(
                ThermalResolvedRegion(
                    region_id=region.region_id,
                    source_region_fingerprint=source_fingerprint,
                    coordinate_space="component_local",
                    owner_reference=owner,
                    placement_binding_fingerprint=binding_fingerprint,
                    compound=None,
                    verification=SemanticVerification.UNSUPPORTED,
                    maximum_error_mm=None,
                )
            )
            continue
        placed = transform_compound_bounded(
            region.compound,
            PlacementTransform(
                anchor_x_mm=binding.anchor_x_mm,
                anchor_y_mm=binding.anchor_y_mm,
                rotation_deg=binding.rotation_deg,
                side=binding.side,
            ),
        )
        source_error = region.maximum_error_mm or 0.0
        transform_error = placed.maximum_error_mm or 0.0
        maximum_error = compose_thermal_position_error(source_error, transform_error)
        verification = (
            SemanticVerification.BOUNDED_APPROXIMATION
            if region.verification is SemanticVerification.BOUNDED_APPROXIMATION
            or placed.authority is PlacementTransformAuthority.BOUNDED_APPROXIMATION
            else SemanticVerification.EXACT
        )
        resolved.append(
            ThermalResolvedRegion(
                region_id=region.region_id,
                source_region_fingerprint=source_fingerprint,
                coordinate_space="component_local",
                owner_reference=owner,
                placement_binding_fingerprint=binding_fingerprint,
                compound=placed.compound,
                verification=verification,
                maximum_error_mm=maximum_error if maximum_error > 0 else None,
            )
        )
    return tuple(sorted(resolved, key=lambda item: item.region_id))


def _binding_issues(
    component_refs: Sequence[str],
    net_refs: Sequence[str],
    *,
    layout_refs: set[str],
    netlist: BoardNetlist | None,
) -> tuple[str, ...]:
    issues = [
        f"component:{reference}:missing-layout"
        for reference in component_refs
        if reference not in layout_refs
    ]
    if netlist is None:
        issues.extend(f"net:{name}:netlist-unavailable" for name in net_refs)
        return tuple(sorted(issues))
    netlist_refs = {item.reference for item in netlist.components}
    net_names = {item.name for item in netlist.nets}
    issues.extend(
        f"component:{reference}:missing-netlist"
        for reference in component_refs
        if reference not in netlist_refs
    )
    issues.extend(f"net:{name}:missing-netlist" for name in net_refs if name not in net_names)
    return tuple(sorted(issues))


def _pair_evidence(
    source: ThermalSourceDeclaration,
    sensitive: ThermalSensitiveDeclaration,
    requirement_evidence: Sequence[str],
    declarations: ThermalDeclarationCatalog,
) -> tuple[str, ...]:
    region_by_id = {item.region_id: item for item in declarations.regions}
    return tuple(
        sorted(
            {
                *source.evidence_binding_ids,
                *sensitive.evidence_binding_ids,
                *requirement_evidence,
                *region_by_id[source.region_id].source_binding_ids,
                *region_by_id[sensitive.region_id].source_binding_ids,
            }
        )
    )


def _unsupported_pair(
    *,
    source: ThermalSourceDeclaration,
    sensitive: ThermalSensitiveDeclaration,
    rule_id: str,
    authority: SemanticAuthorityClass,
    region_ids: tuple[str, str],
    evidence_ids: tuple[str, ...],
    message: str,
) -> tuple[SemanticMetric, SemanticFinding]:
    metric = SemanticMetric(
        metric_id=f"thermal:separation:{source.source_id}:{sensitive.sensitive_id}",
        verification=SemanticVerification.UNSUPPORTED,
        quantity=None,
        object_ids=(source.source_id, sensitive.sensitive_id),
    )
    finding = SemanticFinding(
        rule_id=rule_id,
        authority=authority,
        disposition=SemanticDisposition.UNVERIFIED,
        verification=SemanticVerification.UNSUPPORTED,
        object_ids=(source.source_id, sensitive.sensitive_id),
        component_refs=(*source.component_refs, *sensitive.component_refs),
        net_refs=(*source.net_refs, *sensitive.net_refs),
        region_ids=region_ids,
        metric_ids=(metric.metric_id,),
        evidence_binding_ids=evidence_ids,
        message=message,
        suggested_action="Bind supported geometry and live component/net identities",
    )
    return metric, finding


def _separation_evaluation(
    declarations: ThermalDeclarationCatalog,
    resolved: Sequence[ThermalResolvedRegion],
    *,
    layout_refs: set[str],
    netlist: BoardNetlist | None,
) -> tuple[
    tuple[SemanticMetric, ...],
    tuple[SemanticFinding, ...],
    tuple[ThermalSeparationEvidence, ...],
]:
    source_by_id = {item.source_id: item for item in declarations.sources}
    sensitive_by_id = {item.sensitive_id: item for item in declarations.sensitive_regions}
    resolved_by_id = {item.region_id: item for item in resolved}
    metrics: list[SemanticMetric] = []
    findings: list[SemanticFinding] = []
    evidence_records: list[ThermalSeparationEvidence] = []
    netlist_component_refs = (
        None if netlist is None else tuple(sorted(item.reference for item in netlist.components))
    )
    netlist_net_refs = (
        None if netlist is None else tuple(sorted(item.name for item in netlist.nets))
    )
    for requirement in declarations.separation_requirements:
        source = source_by_id[requirement.source_id]
        sensitive = sensitive_by_id[requirement.sensitive_id]
        source_region = resolved_by_id[source.region_id]
        sensitive_region = resolved_by_id[sensitive.region_id]
        region_ids = (source.region_id, sensitive.region_id)
        evidence_ids = _pair_evidence(
            source,
            sensitive,
            requirement.evidence_binding_ids,
            declarations,
        )
        unsupported_causes = derive_thermal_unsupported_causes(
            source,
            sensitive,
            source_region,
            sensitive_region,
            layout_component_refs=tuple(sorted(layout_refs)),
            netlist_component_refs=netlist_component_refs,
            netlist_net_refs=netlist_net_refs,
        )
        if unsupported_causes:
            metric, finding = _unsupported_pair(
                source=source,
                sensitive=sensitive,
                rule_id=requirement.rule_id,
                authority=requirement.authority,
                region_ids=region_ids,
                evidence_ids=evidence_ids,
                message=(
                    "Thermal separation is unverified: "
                    + ", ".join(item.message_token() for item in unsupported_causes)
                ),
            )
            metrics.append(metric)
            findings.append(finding)
            evidence_records.append(
                ThermalSeparationEvidence(
                    requirement_id=requirement.requirement_id,
                    rule_id=requirement.rule_id,
                    source_id=source.source_id,
                    sensitive_id=sensitive.sensitive_id,
                    source_region_id=source.region_id,
                    sensitive_region_id=sensitive.region_id,
                    authority=requirement.authority,
                    verification=SemanticVerification.UNSUPPORTED,
                    relation=None,
                    nominal_squared_distance_numerator=None,
                    nominal_squared_distance_denominator=None,
                    closest_source_point=None,
                    closest_sensitive_point=None,
                    maximum_error_mm=None,
                    conservative_distance_mm=None,
                    unsupported_causes=unsupported_causes,
                    disposition=SemanticDisposition.UNVERIFIED,
                    metric_ids=(metric.metric_id,),
                    finding_id=finding.finding_id,
                )
            )
            continue
        assert source_region.compound is not None
        assert sensitive_region.compound is not None
        witness = compound_distance_witness(
            source_region.compound,
            sensitive_region.compound,
        )
        squared_distance = witness.squared_distance
        total_error = compose_thermal_position_error(
            source_region.maximum_error_mm or 0.0,
            sensitive_region.maximum_error_mm or 0.0,
        )
        verification = (
            SemanticVerification.BOUNDED_APPROXIMATION
            if total_error > 0
            else SemanticVerification.EXACT
        )
        conservative_distance = conservative_thermal_distance_mm(
            squared_distance,
            total_error,
        )
        distance_metric = SemanticMetric(
            metric_id=f"thermal:separation:{source.source_id}:{sensitive.sensitive_id}",
            verification=verification,
            quantity=SemanticQuantity(
                quantity_id=(
                    f"thermal:minimum-separation:{source.source_id}:{sensitive.sensitive_id}"
                ),
                value=conservative_distance,
                unit="mm",
                source_binding_ids=evidence_ids,
            ),
            object_ids=(source.source_id, sensitive.sensitive_id),
        )
        pair_metrics = [distance_metric]
        if total_error > 0:
            pair_metrics.append(
                SemanticMetric(
                    metric_id=(
                        f"thermal:separation-error:{source.source_id}:{sensitive.sensitive_id}"
                    ),
                    verification=SemanticVerification.EXACT,
                    quantity=SemanticQuantity(
                        quantity_id=(
                            f"thermal:maximum-position-error:{source.source_id}:"
                            f"{sensitive.sensitive_id}"
                        ),
                        value=total_error,
                        unit="mm",
                        source_binding_ids=evidence_ids,
                    ),
                    object_ids=(source.source_id, sensitive.sensitive_id),
                )
            )
        threshold = requirement.minimum_separation_mm
        if requirement.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS:
            disposition = SemanticDisposition.ADVISORY
            message = (
                "Thermal separation metric reported without a hidden threshold"
                if threshold is None
                else "Thermal separation compared as advisory evidence only"
            )
        elif threshold is None:  # rejected by the IR; retained as a fail-closed guard
            disposition = SemanticDisposition.UNVERIFIED
            message = "Hard thermal separation has no explicit threshold"
        elif total_error == 0:
            passed = compound_clearance_at_least(
                source_region.compound,
                sensitive_region.compound,
                threshold,
            )
            disposition = SemanticDisposition.PASS if passed else SemanticDisposition.FAIL
            message = (
                "Exact thermal separation meets the declared threshold"
                if passed
                else "Exact thermal separation is below the declared threshold"
            )
        else:
            required_with_error = math.nextafter(threshold + total_error, math.inf)
            guaranteed = compound_clearance_at_least(
                source_region.compound,
                sensitive_region.compound,
                required_with_error,
            )
            disposition = SemanticDisposition.PASS if guaranteed else SemanticDisposition.UNVERIFIED
            message = (
                "Bounded thermal separation clears the threshold and error envelope"
                if guaranteed
                else "Bounded thermal separation cannot prove the declared threshold"
            )
        finding = SemanticFinding(
            rule_id=requirement.rule_id,
            authority=requirement.authority,
            disposition=disposition,
            verification=verification,
            object_ids=(source.source_id, sensitive.sensitive_id),
            component_refs=(*source.component_refs, *sensitive.component_refs),
            net_refs=(*source.net_refs, *sensitive.net_refs),
            region_ids=region_ids,
            metric_ids=tuple(item.metric_id for item in pair_metrics),
            evidence_binding_ids=evidence_ids,
            message=message,
            suggested_action=(
                "Increase geometric separation or refine bounded region authority"
                if disposition in {SemanticDisposition.FAIL, SemanticDisposition.UNVERIFIED}
                else "Retain the declared operating scope and evidence"
            ),
        )
        metrics.extend(pair_metrics)
        findings.append(finding)
        evidence_records.append(
            ThermalSeparationEvidence(
                requirement_id=requirement.requirement_id,
                rule_id=requirement.rule_id,
                source_id=source.source_id,
                sensitive_id=sensitive.sensitive_id,
                source_region_id=source.region_id,
                sensitive_region_id=sensitive.region_id,
                authority=requirement.authority,
                verification=verification,
                relation=witness.relation,
                nominal_squared_distance_numerator=squared_distance.numerator,
                nominal_squared_distance_denominator=squared_distance.denominator,
                closest_source_point=ThermalRationalPoint.from_point(witness.first_point),
                closest_sensitive_point=ThermalRationalPoint.from_point(witness.second_point),
                maximum_error_mm=total_error if total_error > 0 else None,
                conservative_distance_mm=conservative_distance,
                disposition=disposition,
                metric_ids=tuple(item.metric_id for item in pair_metrics),
                finding_id=finding.finding_id,
            )
        )
    return tuple(metrics), tuple(findings), tuple(evidence_records)


def _prediction_scope_matches(
    model: ThermalPredictionModel,
    operating_point: ThermalOperatingPoint,
    source: ThermalSourceDeclaration,
    context: SemanticEvaluationContext,
) -> bool:
    enclosure = context.enclosure_profile
    if (
        enclosure is None
        or operating_point.enclosure_profile_fingerprint is None
        or not operating_point.enclosure_condition_ids
    ):
        return False
    return (
        source.source_id in model.applicable_source_ids
        and operating_point.pcb_profile_fingerprint == context.pcb_profile_fingerprint
        and operating_point.enclosure_profile_fingerprint == enclosure.semantic_fingerprint()
        and operating_point.enclosure_condition_ids == enclosure.environment_condition_ids
        and model.ambient_temperature_c == operating_point.ambient_temperature_c
        and model.dissipation_w == operating_point.dissipation_w
        and model.duty_cycle == operating_point.duty_cycle
        and model.pcb_profile_fingerprint == operating_point.pcb_profile_fingerprint
        and model.enclosure_profile_fingerprint == operating_point.enclosure_profile_fingerprint
        and model.board_condition_ids == operating_point.board_condition_ids
        and model.air_condition_ids == operating_point.air_condition_ids
        and model.enclosure_condition_ids == operating_point.enclosure_condition_ids
    )


def _prediction_evaluation(
    declarations: ThermalDeclarationCatalog,
    context: SemanticEvaluationContext,
) -> tuple[tuple[SemanticMetric, ...], tuple[SemanticFinding, ...]]:
    operating_points = {item.operating_point_id: item for item in declarations.operating_points}
    models = {item.model_id: item for item in declarations.prediction_models}
    region_by_id = {item.region_id: item for item in declarations.regions}
    metrics: list[SemanticMetric] = []
    findings: list[SemanticFinding] = []
    for source in declarations.sources:
        if not source.prediction_requested:
            continue
        operating_point = operating_points[source.operating_point_id]
        model = (
            None if source.prediction_model_id is None else models.get(source.prediction_model_id)
        )
        evidence_ids = tuple(
            sorted(
                {
                    *source.evidence_binding_ids,
                    *operating_point.evidence_binding_ids,
                    *region_by_id[source.region_id].source_binding_ids,
                    *(() if model is None else model.evidence_binding_ids),
                }
            )
        )
        rule_id = source.prediction_rule_id
        if rule_id is None:  # rejected by the IR; retained as a fail-closed guard
            raise ValueError("requested thermal prediction lost its rule identity")
        if model is None or not _prediction_scope_matches(
            model,
            operating_point,
            source,
            context,
        ):
            findings.append(
                SemanticFinding(
                    rule_id=rule_id,
                    authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
                    disposition=SemanticDisposition.UNVERIFIED,
                    verification=SemanticVerification.UNSUPPORTED,
                    object_ids=(source.source_id,),
                    component_refs=source.component_refs,
                    net_refs=source.net_refs,
                    region_ids=(source.region_id,),
                    metric_ids=(),
                    evidence_binding_ids=evidence_ids,
                    message=(
                        "Temperature estimate withheld: the explicit theta model is "
                        "missing or its ambient/load/board/air/enclosure scope mismatches"
                    ),
                    suggested_action="Provide a scoped model matching the operating context",
                )
            )
            continue
        estimated_temperature = operating_point.ambient_temperature_c + (
            model.theta_c_per_w * operating_point.dissipation_w * operating_point.duty_cycle
        )
        metric = SemanticMetric(
            metric_id=f"thermal:model-estimate:{source.source_id}",
            verification=SemanticVerification.EXACT,
            quantity=SemanticQuantity(
                quantity_id=f"thermal:model-estimate-temperature:{source.source_id}",
                value=estimated_temperature,
                unit="degC",
                source_binding_ids=evidence_ids,
            ),
            object_ids=(source.source_id,),
        )
        metrics.append(metric)
        findings.append(
            SemanticFinding(
                rule_id=rule_id,
                authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
                disposition=SemanticDisposition.ADVISORY,
                verification=SemanticVerification.EXACT,
                object_ids=(source.source_id,),
                component_refs=source.component_refs,
                net_refs=source.net_refs,
                region_ids=(source.region_id,),
                metric_ids=(metric.metric_id,),
                evidence_binding_ids=evidence_ids,
                message=(
                    "Scoped theta-model estimate reported as advisory, not thermal "
                    "simulation or product validation"
                ),
                suggested_action="Validate temperature on representative hardware",
            )
        )
    return tuple(metrics), tuple(findings)


def evaluate_thermal_semantics(
    layout: BoardLayout,
    declarations: ThermalDeclarationCatalog,
    context: SemanticEvaluationContext,
    *,
    netlist: BoardNetlist | None = None,
    placement_candidate_fingerprint: str | None = None,
) -> ThermalEvaluationResult:
    """Evaluate explicitly declared thermal geometry and optional scoped estimates."""

    bindings = _placement_bindings(layout)
    resolved = _resolved_regions(declarations, bindings)
    layout_refs = {item.component_ref for item in bindings}
    (
        separation_metrics,
        separation_findings,
        separation_evidence,
    ) = _separation_evaluation(
        declarations,
        resolved,
        layout_refs=layout_refs,
        netlist=netlist,
    )
    prediction_metrics, prediction_findings = _prediction_evaluation(
        declarations,
        context,
    )
    return ThermalEvaluationResult.build(
        context=context,
        declarations=declarations,
        board_layout_fingerprint=board_layout_fingerprint(layout),
        netlist_fingerprint=_netlist_fingerprint(netlist),
        netlist_component_refs=(
            None if netlist is None else tuple(item.reference for item in netlist.components)
        ),
        netlist_net_refs=(None if netlist is None else tuple(item.name for item in netlist.nets)),
        placement_candidate_fingerprint=placement_candidate_fingerprint,
        placement_bindings=bindings,
        resolved_regions=resolved,
        separation_evidence=separation_evidence,
        metrics=(*separation_metrics, *prediction_metrics),
        findings=(*separation_findings, *prediction_findings),
    )
