"""Record-only R6.2 antenna RF campaign evaluator."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pcbsmith.antenna_enclosure_ir import AntennaEnclosureExclusionResult
from pcbsmith.antenna_rf_validation_ir import (
    AntennaRfCampaignRecord,
    AntennaRfCampaignRequirement,
    AntennaRfMetricEvidence,
    AntennaRfValidationResult,
    fingerprint,
    metric_requirement_passed,
)
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticResultOutcome,
    SemanticVerification,
)


def _decimal_float(value: float) -> Decimal:
    return Decimal(str(value))


def _validate_requirement(
    enclosure: AntennaEnclosureExclusionResult,
    requirement: AntennaRfCampaignRequirement,
) -> AntennaRfCampaignRequirement:
    retained = AntennaRfCampaignRequirement.model_validate_json(requirement.model_dump_json())
    placement = enclosure.placement_result
    antenna = placement.declaration
    enclosure_declaration = enclosure.declaration
    context = retained.context
    expected = (
        context.antenna_id == antenna.antenna_id
        and context.module_reference == antenna.module_reference
        and context.selected_footprint_library_id == antenna.selected_footprint_library_id
        and context.component_uuid_path == antenna.component_uuid_path
        and context.component_revision == antenna.component_revision
        and context.module_source_sha256 == antenna.source_file_sha256
        and context.placement_result_fingerprint == placement.result_fingerprint
        and context.anchor_x_mm == _decimal_float(placement.transform.anchor_x_mm)
        and context.anchor_y_mm == _decimal_float(placement.transform.anchor_y_mm)
        and context.rotation_deg == _decimal_float(placement.transform.rotation_deg)
        and context.side == placement.transform.side
        and context.board_layout_snapshot_fingerprint
        == placement.board_layout_snapshot_fingerprint
        and context.enclosure_profile_id == enclosure_declaration.enclosure_profile_id
        and context.enclosure_id == enclosure_declaration.enclosure_id
        and context.enclosure_revision == enclosure_declaration.enclosure_revision
        and context.enclosure_model_sha256 == enclosure_declaration.model_sha256
    )
    if not expected:
        raise ValueError("RF requirement is bound to another module/placement/enclosure authority")
    return retained


def _validate_campaign(
    requirement: AntennaRfCampaignRequirement,
    record: AntennaRfCampaignRecord | None,
) -> AntennaRfCampaignRecord | None:
    if record is None:
        return None
    retained = AntennaRfCampaignRecord.model_validate_json(record.model_dump_json())
    if (
        retained.requirement_id != requirement.requirement_id
        or retained.validation_profile_id != requirement.validation_profile_id
        or retained.requirement_fingerprint != requirement.semantic_fingerprint()
        or retained.context != requirement.context
    ):
        raise ValueError("RF campaign record conditions are stale or belong to another requirement")
    required_ids = {item.metric_id for item in requirement.metrics}
    measured_ids = {item.metric_id for item in retained.measurements}
    if not measured_ids.issubset(required_ids):
        raise ValueError("RF campaign record contains unrequested metric identities")
    if retained.availability == "complete" and measured_ids != required_ids:
        raise ValueError("complete RF campaign omits required metrics")
    return retained


def _geometry_finding(
    enclosure: AntennaEnclosureExclusionResult,
    requirement: AntennaRfCampaignRequirement,
) -> SemanticFinding:
    outcome = enclosure.semantic_result.outcome
    if outcome is SemanticResultOutcome.PASSED:
        disposition = SemanticDisposition.PASS
        message = "Retained enclosure prerequisite passed before RF campaign evaluation."
        action = "Retain the replay-valid enclosure prerequisite result."
    elif outcome in {
        SemanticResultOutcome.VALIDATION_FAILED,
        SemanticResultOutcome.HARD_REJECTED,
    }:
        disposition = SemanticDisposition.FAIL
        message = "Retained enclosure prerequisite failed and blocks RF validation acceptance."
        action = "Correct and revalidate the enclosure prerequisite before RF acceptance."
    else:
        disposition = SemanticDisposition.VALIDATION_PENDING
        message = "Retained enclosure prerequisite is pending and blocks RF acceptance."
        action = "Complete the exact enclosure prerequisite before RF acceptance."
    return SemanticFinding(
        rule_id=f"{requirement.requirement_id}:geometry-prerequisite",
        authority=SemanticAuthorityClass.VALIDATION_REQUIRED,
        disposition=disposition,
        verification=SemanticVerification.EXACT,
        object_ids=(enclosure.declaration.declaration_id,),
        component_refs=(requirement.context.module_reference,),
        region_ids=(enclosure.declaration.exclusion.exclusion_id,),
        evidence_binding_ids=(requirement.applicability_binding.binding_id,),
        validation_profile_id=(
            requirement.validation_profile_id
            if disposition in {SemanticDisposition.PASS, SemanticDisposition.FAIL}
            else None
        ),
        validation_requirement_ids=(requirement.requirement_id,),
        message=message,
        suggested_action=action,
    )


def _metric_evidence(
    requirement: AntennaRfCampaignRequirement,
    record: AntennaRfCampaignRecord | None,
) -> tuple[AntennaRfMetricEvidence, ...]:
    complete = record is not None and record.availability == "complete"
    by_id = {} if record is None else {item.metric_id: item for item in record.measurements}
    evidence = []
    for metric in requirement.metrics:
        measured = by_id.get(metric.metric_id) if complete else None
        if measured is None:
            reason = (
                "campaign_record_missing"
                if record is None
                else f"campaign_record_{record.availability}"
            )
            evidence.append(
                AntennaRfMetricEvidence(
                    requirement=metric,
                    measured=None,
                    campaign_record_id=None,
                    disposition=SemanticDisposition.VALIDATION_PENDING,
                    verification=SemanticVerification.EXACT,
                    pending_reason=reason,
                )
            )
            continue
        if measured.unit != metric.unit:
            raise ValueError(f"RF metric {metric.metric_id} unit differs from requirement")
        passed = metric_requirement_passed(metric, measured.value)
        assert record is not None
        evidence.append(
            AntennaRfMetricEvidence(
                requirement=metric,
                measured=measured,
                campaign_record_id=record.record_id,
                disposition=(SemanticDisposition.PASS if passed else SemanticDisposition.FAIL),
                verification=SemanticVerification.EXACT,
                pending_reason=None,
            )
        )
    return tuple(evidence)


def _campaign_findings(
    requirement: AntennaRfCampaignRequirement,
    evidence: tuple[AntennaRfMetricEvidence, ...],
) -> tuple[SemanticFinding, ...]:
    findings = []
    for item in evidence:
        disposition = item.disposition
        findings.append(
            SemanticFinding(
                rule_id=f"{requirement.requirement_id}:metric:{item.requirement.metric_id}",
                authority=SemanticAuthorityClass.VALIDATION_REQUIRED,
                disposition=disposition,
                verification=item.verification,
                object_ids=(item.campaign_record_id,) if item.campaign_record_id else (),
                component_refs=(requirement.context.module_reference,),
                evidence_binding_ids=(requirement.applicability_binding.binding_id,),
                validation_profile_id=(
                    requirement.validation_profile_id
                    if disposition in {SemanticDisposition.PASS, SemanticDisposition.FAIL}
                    else None
                ),
                validation_requirement_ids=(requirement.requirement_id,),
                message={
                    SemanticDisposition.PASS: "Exact RF campaign metric meets its reviewed target.",
                    SemanticDisposition.FAIL: "Exact RF campaign metric fails its reviewed target.",
                    SemanticDisposition.VALIDATION_PENDING: (
                        "No complete exact RF campaign measurement is available."
                    ),
                }[disposition],
                suggested_action={
                    SemanticDisposition.PASS: "Retain the exact raw campaign authority.",
                    SemanticDisposition.FAIL: (
                        "Correct the design or test context and repeat RF validation."
                    ),
                    SemanticDisposition.VALIDATION_PENDING: (
                        "Attach a complete campaign matching every declared condition."
                    ),
                }[disposition],
            )
        )
    return tuple(sorted(findings, key=lambda item: item.finding_id))


def _pcb_geometry_fingerprint(enclosure: AntennaEnclosureExclusionResult) -> str:
    placement = enclosure.placement_result
    return fingerprint(
        {
            "board_layout_snapshot_json": placement.board_layout_snapshot_json,
            "board_layout_snapshot_fingerprint": placement.board_layout_snapshot_fingerprint,
            "keepouts": [item.model_dump(mode="json") for item in placement.declaration.keepouts],
            "placed_regions": [item.model_dump(mode="json") for item in placement.placed_regions],
            "enclosure_pcb_geometry_before": enclosure.pcb_geometry_before_fingerprint,
            "enclosure_pcb_geometry_after": enclosure.pcb_geometry_after_fingerprint,
        }
    )


def rederive_antenna_rf_validation(
    enclosure_result: AntennaEnclosureExclusionResult,
    requirement: AntennaRfCampaignRequirement,
    campaign_record: AntennaRfCampaignRecord | None,
) -> dict[str, Any]:
    enclosure = AntennaEnclosureExclusionResult.model_validate_json(
        enclosure_result.model_dump_json()
    )
    retained_requirement = _validate_requirement(enclosure, requirement)
    retained_record = _validate_campaign(retained_requirement, campaign_record)
    before = _pcb_geometry_fingerprint(enclosure)
    geometry = _geometry_finding(enclosure, retained_requirement)
    evidence = _metric_evidence(retained_requirement, retained_record)
    campaign_findings = _campaign_findings(retained_requirement, evidence)
    after = _pcb_geometry_fingerprint(enclosure)
    if before != after:
        raise ValueError("RF campaign evaluation changed retained PCB geometry")
    evidence_fp = fingerprint(
        {
            "geometry_finding": geometry.model_dump(mode="json"),
            "metric_evidence": [item.model_dump(mode="json") for item in evidence],
            "campaign_findings": [item.model_dump(mode="json") for item in campaign_findings],
        }
    )
    semantic = SemanticLayoutResult.build(
        context_fingerprint=retained_requirement.context.semantic_fingerprint(),
        declarations_fingerprint=retained_requirement.semantic_fingerprint(),
        geometry_fingerprint=enclosure.semantic_fingerprint(),
        placement_candidate_fingerprint=enclosure.placement_result.result_fingerprint,
        findings=(geometry, *campaign_findings),
    )
    return {
        "requirement": retained_requirement,
        "campaign_record": retained_record,
        "geometry_finding": geometry,
        "metric_evidence": evidence,
        "campaign_findings": campaign_findings,
        "pcb_geometry_before_fingerprint": before,
        "pcb_geometry_after_fingerprint": after,
        "evidence_fingerprint": evidence_fp,
        "semantic_result": semantic,
    }


def evaluate_antenna_rf_validation(
    enclosure_result: AntennaEnclosureExclusionResult,
    requirement: AntennaRfCampaignRequirement,
    campaign_record: AntennaRfCampaignRecord | None,
) -> AntennaRfValidationResult:
    """Evaluate only exact campaign records; never infer RF performance from geometry."""

    derived = rederive_antenna_rf_validation(enclosure_result, requirement, campaign_record)
    fields = {"enclosure_result": enclosure_result, **derived}
    provisional = AntennaRfValidationResult.model_construct(
        **fields, result_fingerprint="0" * 64
    )
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return AntennaRfValidationResult(**fields, result_fingerprint=result_fp)
