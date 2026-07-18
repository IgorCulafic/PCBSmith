"""Opt-in companion evaluator for sensor thermal/humidity campaigns."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticVerification,
)
from pcbsmith.sensor_bridge_ir import SensorBridgeEvaluationResult
from pcbsmith.sensor_copper_removal_ir import CopperRemovalEvaluationResult
from pcbsmith.sensor_isolation_ir import SensorIsolationEvaluationResult
from pcbsmith.sensor_validation_ir import (
    SensorEnclosureRevisionContext,
    SensorUpstreamIntegrityEvidence,
    SensorValidationCampaignRecord,
    SensorValidationDeclaration,
    SensorValidationEvaluationResult,
    SensorValidationFindingRecord,
    SensorValidationRequirement,
    fingerprint,
)


class _Derived(TypedDict):
    isolation_result: SensorIsolationEvaluationResult
    copper_removal_result: CopperRemovalEvaluationResult | None
    sensor_bridge_result: SensorBridgeEvaluationResult | None
    declaration: SensorValidationDeclaration
    enclosure_context: SensorEnclosureRevisionContext | None
    campaigns: tuple[SensorValidationCampaignRecord, ...]
    upstream_integrity: SensorUpstreamIntegrityEvidence
    findings: tuple[SemanticFinding, ...]
    finding_records: tuple[SensorValidationFindingRecord, ...]
    input_fingerprint: str
    semantic_result: SemanticLayoutResult


def _collection_fingerprint(values: Sequence[Any]) -> str:
    return fingerprint([item.model_dump(mode="json") for item in values])


def _integrity(
    isolation: SensorIsolationEvaluationResult,
    copper: CopperRemovalEvaluationResult | None,
    bridge: SensorBridgeEvaluationResult | None,
) -> SensorUpstreamIntegrityEvidence:
    return SensorUpstreamIntegrityEvidence(
        isolation_result_fingerprint=isolation.semantic_fingerprint(),
        isolation_metrics_fingerprint=_collection_fingerprint(isolation.metrics),
        isolation_findings_fingerprint=_collection_fingerprint(isolation.findings),
        copper_removal_result_fingerprint=(
            None if copper is None else copper.semantic_fingerprint()
        ),
        copper_pair_evidence_fingerprint=(
            None if copper is None else _collection_fingerprint(copper.pair_evidence)
        ),
        copper_source_evidence_fingerprint=(
            None if copper is None else _collection_fingerprint(copper.source_evidence)
        ),
        copper_findings_fingerprint=(
            None if copper is None else _collection_fingerprint(copper.findings)
        ),
        sensor_bridge_result_fingerprint=(
            None if bridge is None else bridge.semantic_fingerprint()
        ),
        bridge_track_fingerprint=(
            None if bridge is None else _collection_fingerprint(bridge.bridge_tracks)
        ),
        bridge_budget_fingerprint=(
            None if bridge is None else _collection_fingerprint(bridge.budget_evidence)
        ),
        bridge_findings_fingerprint=(
            None if bridge is None else _collection_fingerprint(bridge.findings)
        ),
    )


def _campaign_mismatches(
    record: SensorValidationCampaignRecord,
    declaration: SensorValidationDeclaration,
    requirement: SensorValidationRequirement,
) -> tuple[str, ...]:
    checks = (
        (
            "validation_profile_mismatch",
            record.validation_profile_id == declaration.validation_profile_id
            and record.validation_profile_revision
            == declaration.validation_profile_revision,
        ),
        ("requirement_identity_mismatch", record.requirement_id == requirement.requirement_id),
        ("requirement_kind_mismatch", record.kind is requirement.kind),
        ("board_revision_mismatch", record.board_revision == declaration.board_revision),
        ("enclosure_context_mismatch", record.enclosure == declaration.required_enclosure),
        ("firmware_state_mismatch", record.firmware_state_id == declaration.firmware_state_id),
        ("radio_state_mismatch", record.radio_state_id == declaration.radio_state_id),
        ("load_state_mismatch", record.load_state_id == declaration.load_state_id),
        ("target_mismatch", record.target == requirement.target),
    )
    return tuple(sorted(name for name, matched in checks if not matched))


def _project_binding_complete(binding: EvidenceApplicabilityBinding) -> bool:
    return (
        bool(binding.required_conditions)
        and not binding.unmatched_conditions
        and set(binding.matched_conditions) == set(binding.required_conditions)
        and binding.reviewer_record_id is not None
        and all(
            item.source_status == "pinned"
            and item.local_sha256 is not None
            and item.locator_status in {"text_verified", "figure_verified"}
            and item.applicability_status == "confirmed"
            for item in binding.evidence
        )
    )


def _pending_reasons(
    *,
    declaration: SensorValidationDeclaration,
    requirement: SensorValidationRequirement,
    enclosure_context: SensorEnclosureRevisionContext | None,
    campaigns: Sequence[SensorValidationCampaignRecord],
) -> tuple[tuple[str, ...], tuple[SensorValidationCampaignRecord, ...]]:
    base: list[str] = []
    if enclosure_context is None:
        base.append("enclosure_context_absent")
    elif enclosure_context != declaration.required_enclosure:
        base.append("enclosure_context_mismatch")
    exact = tuple(
        item
        for item in campaigns
        if not _campaign_mismatches(item, declaration, requirement)
    )
    if base:
        return tuple(sorted(base)), ()
    if exact:
        return (), exact
    relevant = tuple(
        item for item in campaigns if item.requirement_id == requirement.requirement_id
    )
    if not relevant:
        return ("matching_campaign_absent",), ()
    reasons = {
        reason
        for item in relevant
        for reason in _campaign_mismatches(item, declaration, requirement)
    }
    return tuple(sorted(reasons or {"matching_campaign_absent"})), ()


def _validate_authority_chain(
    isolation: SensorIsolationEvaluationResult,
    declaration: SensorValidationDeclaration,
    copper: CopperRemovalEvaluationResult | None,
    bridge: SensorBridgeEvaluationResult | None,
) -> None:
    candidate = isolation.catalog.candidate
    if declaration.isolation_result_fingerprint != isolation.semantic_fingerprint():
        raise ValueError("validation declaration is bound to another isolation result")
    if (
        declaration.candidate_id != candidate.candidate_id
        or declaration.sensor_reference != candidate.sensor_reference
    ):
        raise ValueError("validation declaration differs from the retained sensor candidate")
    expected_requirements = {
        candidate.validation.thermal_requirement_id: "thermal",
    }
    if candidate.validation.humidity_requirement_id is not None:
        expected_requirements[candidate.validation.humidity_requirement_id] = "humidity"
    actual_requirements = {
        item.requirement_id: item.kind.value for item in declaration.requirements
    }
    if actual_requirements != expected_requirements:
        raise ValueError("validation requirements differ from the retained candidate identities")

    known_bindings = {
        item.binding_id: item
        for item in isolation.context.semantic_profile.evidence_bindings
    }
    if isolation.context.assembly_profile is not None:
        for item in isolation.context.assembly_profile.evidence_bindings:
            existing = known_bindings.get(item.binding_id)
            if existing is not None and existing != item:
                raise ValueError("validation context has conflicting evidence binding identities")
            known_bindings[item.binding_id] = item
    used_bindings = {
        item
        for requirement in declaration.requirements
        for item in requirement.evidence_binding_ids
    }
    if not used_bindings.issubset(known_bindings):
        raise ValueError("validation requirements cite unknown project evidence bindings")
    if not all(_project_binding_complete(known_bindings[item]) for item in used_bindings):
        raise ValueError("validation requirements require complete reviewed project evidence")

    actual_copper_fp = None if copper is None else copper.semantic_fingerprint()
    if declaration.copper_removal_result_fingerprint != actual_copper_fp:
        raise ValueError("validation declaration/copper-removal authority mismatch")
    actual_bridge_fp = None if bridge is None else bridge.semantic_fingerprint()
    if declaration.sensor_bridge_result_fingerprint != actual_bridge_fp:
        raise ValueError("validation declaration/sensor-bridge authority mismatch")
    if copper is not None and copper.isolation_result != isolation:
        raise ValueError("copper-removal authority retains another isolation result")
    if bridge is not None:
        if copper is None:
            raise ValueError("sensor-bridge authority requires copper-removal authority")
        if bridge.isolation_result != isolation or bridge.copper_removal_result != copper:
            raise ValueError("sensor-bridge authority differs from retained upstream results")


def rederive_sensor_validation_result(
    *,
    isolation_result: SensorIsolationEvaluationResult,
    declaration: SensorValidationDeclaration,
    enclosure_context: SensorEnclosureRevisionContext | None,
    campaigns: Sequence[SensorValidationCampaignRecord],
    copper_removal_result: CopperRemovalEvaluationResult | None = None,
    sensor_bridge_result: SensorBridgeEvaluationResult | None = None,
) -> _Derived:
    """Rebuild validation findings while preserving complete upstream objects."""

    isolation = SensorIsolationEvaluationResult.model_validate_json(
        isolation_result.model_dump_json()
    )
    copper = (
        None
        if copper_removal_result is None
        else CopperRemovalEvaluationResult.model_validate_json(
            copper_removal_result.model_dump_json()
        )
    )
    bridge = (
        None
        if sensor_bridge_result is None
        else SensorBridgeEvaluationResult.model_validate_json(
            sensor_bridge_result.model_dump_json()
        )
    )
    detached_declaration = SensorValidationDeclaration.model_validate_json(
        declaration.model_dump_json()
    )
    detached_enclosure = (
        None
        if enclosure_context is None
        else SensorEnclosureRevisionContext.model_validate_json(
            enclosure_context.model_dump_json()
        )
    )
    canonical_campaigns = tuple(
        sorted(
            (
                SensorValidationCampaignRecord.model_validate_json(item.model_dump_json())
                for item in campaigns
            ),
            key=lambda item: item.record_id,
        )
    )
    if len({item.record_id for item in canonical_campaigns}) != len(canonical_campaigns):
        raise ValueError("sensor validation campaign record identities must be unique")

    _validate_authority_chain(
        isolation,
        detached_declaration,
        copper,
        bridge,
    )
    integrity = _integrity(isolation, copper, bridge)
    findings: list[SemanticFinding] = []
    finding_records: list[SensorValidationFindingRecord] = []
    for requirement in detached_declaration.requirements:
        reasons, exact = _pending_reasons(
            declaration=detached_declaration,
            requirement=requirement,
            enclosure_context=detached_enclosure,
            campaigns=canonical_campaigns,
        )
        if len(exact) > 1:
            raise ValueError(
                f"multiple exact campaign records match requirement {requirement.requirement_id}"
            )
        record = exact[0] if exact else None
        disposition = (
            SemanticDisposition.VALIDATION_PENDING
            if record is None
            else SemanticDisposition.PASS
            if record.passed
            else SemanticDisposition.FAIL
        )
        object_ids = (
            detached_declaration.declaration_id,
            detached_declaration.candidate_id,
        ) + (() if record is None else (record.record_id,))
        finding = SemanticFinding(
            rule_id=f"sensor-validation:{requirement.requirement_id}",
            authority=SemanticAuthorityClass.VALIDATION_REQUIRED,
            disposition=disposition,
            verification=SemanticVerification.EXACT,
            object_ids=object_ids,
            component_refs=(detached_declaration.sensor_reference,),
            evidence_binding_ids=requirement.evidence_binding_ids,
            validation_profile_id=(
                None
                if disposition is SemanticDisposition.VALIDATION_PENDING
                else detached_declaration.validation_profile_id
            ),
            validation_requirement_ids=(requirement.requirement_id,),
            message=(
                "No exact enclosure/campaign record matches this project requirement"
                if record is None
                else "Exact reviewed campaign record passes this project requirement"
                if record.passed
                else "Exact reviewed campaign record fails this project requirement"
            ),
            suggested_action=(
                "Run or attach a campaign with the exact declared enclosure and operating context"
                if record is None
                else "Retain the reviewed campaign record and exact tested context"
                if record.passed
                else "Correct the design or context and repeat the declared campaign"
            ),
        )
        findings.append(finding)
        finding_records.append(
            SensorValidationFindingRecord(
                requirement_id=requirement.requirement_id,
                kind=requirement.kind,
                matched_campaign_record_id=None if record is None else record.record_id,
                disposition=disposition,
                mismatch_reasons=reasons,
                semantic_finding_id=finding.finding_id,
            )
        )
    canonical_findings = tuple(sorted(findings, key=lambda item: item.finding_id))
    canonical_records = tuple(
        sorted(finding_records, key=lambda item: item.requirement_id)
    )
    declaration_fp = detached_declaration.semantic_fingerprint()
    semantic_result = SemanticLayoutResult.build(
        context_fingerprint=isolation.context.semantic_fingerprint(),
        declarations_fingerprint=declaration_fp,
        geometry_fingerprint=integrity.semantic_fingerprint(),
        findings=canonical_findings,
    )
    input_fp = fingerprint(
        {
            "isolation_result_fingerprint": isolation.semantic_fingerprint(),
            "copper_removal_result_fingerprint": (
                None if copper is None else copper.semantic_fingerprint()
            ),
            "sensor_bridge_result_fingerprint": (
                None if bridge is None else bridge.semantic_fingerprint()
            ),
            "declaration_fingerprint": declaration_fp,
            "enclosure_context_fingerprint": (
                None if detached_enclosure is None else detached_enclosure.semantic_fingerprint()
            ),
            "campaign_record_fingerprints": [
                item.semantic_fingerprint() for item in canonical_campaigns
            ],
            "upstream_integrity_fingerprint": integrity.semantic_fingerprint(),
        }
    )
    return {
        "isolation_result": isolation,
        "copper_removal_result": copper,
        "sensor_bridge_result": bridge,
        "declaration": detached_declaration,
        "enclosure_context": detached_enclosure,
        "campaigns": canonical_campaigns,
        "upstream_integrity": integrity,
        "findings": canonical_findings,
        "finding_records": canonical_records,
        "input_fingerprint": input_fp,
        "semantic_result": semantic_result,
    }


def evaluate_sensor_validation(
    isolation_result: SensorIsolationEvaluationResult,
    declaration: SensorValidationDeclaration,
    *,
    enclosure_context: SensorEnclosureRevisionContext | None,
    campaigns: Sequence[SensorValidationCampaignRecord] = (),
    copper_removal_result: CopperRemovalEvaluationResult | None = None,
    sensor_bridge_result: SensorBridgeEvaluationResult | None = None,
) -> SensorValidationEvaluationResult:
    """Evaluate only identified performance campaigns; never geometry authority."""

    derived = rederive_sensor_validation_result(
        isolation_result=isolation_result,
        declaration=declaration,
        enclosure_context=enclosure_context,
        campaigns=campaigns,
        copper_removal_result=copper_removal_result,
        sensor_bridge_result=sensor_bridge_result,
    )
    return SensorValidationEvaluationResult(**derived)
