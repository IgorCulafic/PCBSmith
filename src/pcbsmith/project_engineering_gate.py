"""Automatic applicability and exact-part readiness gate for Phase 14."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from pcbsmith.evidence.part_discovery import (
    INSTALL_REQUIRED_ROLES,
    ExactPartDiscoveryReport,
    PartResourceStatus,
)
from pcbsmith.project_engineering_gate_ir import (
    ALL_PHASE14_RULE_FAMILIES,
    ComponentIdentityStatus,
    InventoryStatus,
    PartResourceReadinessRecord,
    Phase14AxisGateRecord,
    Phase14EvaluationBundle,
    Phase14RuleFamily,
    ProjectEngineeringContext,
    ProjectEngineeringGateResult,
    ProjectGateOutcome,
)
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.semantic_ir import SemanticDisposition, SemanticResultOutcome

_DISPOSITION_PRIORITY = {
    SemanticDisposition.FAIL: 6,
    SemanticDisposition.UNVERIFIED: 5,
    SemanticDisposition.VALIDATION_PENDING: 4,
    SemanticDisposition.ADVISORY: 3,
    SemanticDisposition.PASS: 2,
    SemanticDisposition.NOT_APPLICABLE: 1,
}


def _worst(dispositions: Iterable[SemanticDisposition]) -> SemanticDisposition:
    values = tuple(dispositions)
    return (
        max(values, key=_DISPOSITION_PRIORITY.__getitem__)
        if values
        else SemanticDisposition.PASS
    )


def _part_identity(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _semantic_result_disposition(result: Any) -> SemanticDisposition:
    findings = tuple(item.disposition for item in result.findings)
    if findings:
        return _worst(findings)
    return {
        SemanticResultOutcome.HARD_REJECTED: SemanticDisposition.FAIL,
        SemanticResultOutcome.HARD_SCOPE_UNVERIFIED: SemanticDisposition.UNVERIFIED,
        SemanticResultOutcome.VALIDATION_FAILED: SemanticDisposition.FAIL,
        SemanticResultOutcome.VALIDATION_PENDING: SemanticDisposition.VALIDATION_PENDING,
        SemanticResultOutcome.ADVISORY_REVIEW: SemanticDisposition.ADVISORY,
        SemanticResultOutcome.PASSED: SemanticDisposition.PASS,
        SemanticResultOutcome.NOT_APPLICABLE: SemanticDisposition.NOT_APPLICABLE,
    }[result.outcome]


def _family_results(
    bundle: Phase14EvaluationBundle,
    family: Phase14RuleFamily,
) -> tuple[tuple[str, str, SemanticDisposition, str, str], ...]:
    if family is Phase14RuleFamily.DECOUPLING_LOOP:
        return tuple(
            (
                item.declaration.declaration_id,
                item.result_fingerprint,
                item.disposition,
                item.declaration.board_layout_snapshot_fingerprint,
                item.declaration.board_netlist_snapshot_fingerprint,
            )
            for item in bundle.decoupling_loops
        )
    if family is Phase14RuleFamily.CONNECTOR_PROTECTION_ORDER:
        return tuple(
            (
                item.declaration.declaration_id,
                item.result_fingerprint,
                item.disposition,
                item.declaration.board_layout_snapshot_fingerprint,
                item.declaration.board_netlist_snapshot_fingerprint,
            )
            for item in bundle.connector_protection_orders
        )
    if family is Phase14RuleFamily.OSCILLATOR_ZONE:
        return tuple(
            (
                item.declaration.declaration_id,
                item.result_fingerprint,
                _semantic_result_disposition(item.semantic_result),
                item.declaration.board_layout_snapshot_fingerprint,
                item.declaration.board_netlist_snapshot_fingerprint,
            )
            for item in bundle.oscillator_zones
        )
    if family is Phase14RuleFamily.SWITCHING_HOT_LOOP:
        return tuple(
            (
                item.declaration.declaration_id,
                item.result_fingerprint,
                item.disposition,
                item.declaration.board_layout_snapshot_fingerprint,
                item.declaration.board_netlist_snapshot_fingerprint,
            )
            for item in bundle.switching_hot_loops
        )
    return tuple(
        (
            item.declaration.declaration_id,
            item.result_fingerprint,
            _worst(finding.disposition for finding in item.findings),
            item.declaration.board_layout_snapshot_fingerprint,
            item.declaration.board_netlist_snapshot_fingerprint,
        )
        for item in bundle.return_adjacencies
    )


def _axis_records(
    context: ProjectEngineeringContext,
    bundle: Phase14EvaluationBundle,
) -> tuple[Phase14AxisGateRecord, ...]:
    features_by_family = {
        family: tuple(item for item in context.phase14_features if item.family is family)
        for family in ALL_PHASE14_RULE_FAMILIES
    }
    records: list[Phase14AxisGateRecord] = []
    for family in ALL_PHASE14_RULE_FAMILIES:
        findings: tuple[str, ...]
        supplied = _family_results(bundle, family)
        supplied_ids = tuple(item[0] for item in supplied)
        supplied_fingerprints = tuple(item[1] for item in supplied)
        if context.inventory_status is InventoryStatus.INCOMPLETE:
            records.append(
                Phase14AxisGateRecord(
                    family=family,
                    applicability="unresolved",
                    required_declaration_ids=(),
                    supplied_declaration_ids=supplied_ids,
                    result_fingerprints=supplied_fingerprints,
                    disposition=SemanticDisposition.UNVERIFIED,
                    findings=("Project engineering inventory is incomplete.",),
                )
            )
            continue
        required_ids = tuple(
            sorted(
                {
                    declaration_id
                    for feature in features_by_family[family]
                    for declaration_id in feature.required_declaration_ids
                }
            )
        )
        if not required_ids:
            if supplied:
                disposition = SemanticDisposition.UNVERIFIED
                findings = ("Evaluator results exist without a reviewed applicability feature.",)
            else:
                disposition = SemanticDisposition.NOT_APPLICABLE
                findings = ()
            records.append(
                Phase14AxisGateRecord(
                    family=family,
                    applicability="not_applicable",
                    required_declaration_ids=(),
                    supplied_declaration_ids=supplied_ids,
                    result_fingerprints=supplied_fingerprints,
                    disposition=disposition,
                    findings=findings,
                )
            )
            continue
        snapshots_match = all(
            layout_fingerprint == context.board_layout_snapshot_fingerprint
            and netlist_fingerprint == context.board_netlist_snapshot_fingerprint
            for _, _, _, layout_fingerprint, netlist_fingerprint in supplied
        )
        if supplied_ids != required_ids or not snapshots_match:
            reasons = []
            if supplied_ids != required_ids:
                reasons.append("Required and supplied declaration identities differ.")
            if not snapshots_match:
                reasons.append("A supplied result belongs to another board snapshot.")
            disposition = SemanticDisposition.UNVERIFIED
            findings = tuple(reasons)
        else:
            disposition = _worst(item[2] for item in supplied)
            if disposition is SemanticDisposition.NOT_APPLICABLE:
                disposition = SemanticDisposition.UNVERIFIED
                findings = ("Applicable evaluator returned not-applicable.",)
            else:
                findings = ()
        records.append(
            Phase14AxisGateRecord(
                family=family,
                applicability="applicable",
                required_declaration_ids=required_ids,
                supplied_declaration_ids=supplied_ids,
                result_fingerprints=supplied_fingerprints,
                disposition=disposition,
                findings=findings,
            )
        )
    return tuple(records)


def _resource_records(
    context: ProjectEngineeringContext,
    reports: tuple[ExactPartDiscoveryReport, ...],
) -> tuple[PartResourceReadinessRecord, ...]:
    records: list[PartResourceReadinessRecord] = []
    for component in context.component_profiles:
        if component.identity_status is not ComponentIdentityStatus.EXACT_MPN:
            continue
        assert component.manufacturer is not None
        assert component.part_number is not None
        report = next(
            (
                item
                for item in reports
                if _part_identity(item.request.manufacturer)
                == _part_identity(component.manufacturer)
                and _part_identity(item.request.part_number)
                == _part_identity(component.part_number)
            ),
            None,
        )
        for role in component.required_resource_roles:
            discovery = (
                next((item for item in report.records if item.role is role), None)
                if report is not None
                else None
            )
            ready_statuses = (
                {PartResourceStatus.INSTALLED}
                if role in INSTALL_REQUIRED_ROLES
                else {PartResourceStatus.INSTALLED, PartResourceStatus.VALIDATED_CACHE}
            )
            ready = bool(
                report is not None
                and report.provider_search_complete
                and discovery is not None
                and discovery.status in ready_statuses
                and (
                    role in INSTALL_REQUIRED_ROLES
                    or bool(discovery.revision and discovery.revision.strip())
                )
            )
            resource_findings = (
                ()
                if ready
                else (
                    (
                        "Required CAD asset is not installed."
                        if role in INSTALL_REQUIRED_ROLES and discovery is not None
                        else (
                            "Required exact-part document lacks a source revision."
                            if discovery is not None
                            and discovery.status in ready_statuses
                            and not discovery.revision
                            else "Required exact-part resource is not ready."
                        )
                    ),
                )
            )
            records.append(
                PartResourceReadinessRecord(
                    component_reference=component.reference,
                    manufacturer=component.manufacturer,
                    part_number=component.part_number,
                    role=role,
                    ready=ready,
                    discovery_report_fingerprint=(
                        report.report_fingerprint if report is not None else None
                    ),
                    status=(discovery.status.value if discovery is not None else "not_searched"),
                    findings=resource_findings,
                )
            )
    return tuple(
        sorted(records, key=lambda item: (item.component_reference, item.role.value))
    )


def rederive_project_engineering_gate(
    context: ProjectEngineeringContext,
    evaluation_bundle: Phase14EvaluationBundle,
    discovery_reports: tuple[ExactPartDiscoveryReport, ...],
) -> dict[str, Any]:
    reports = tuple(
        sorted(
            discovery_reports,
            key=lambda item: (
                _part_identity(item.request.manufacturer),
                _part_identity(item.request.part_number),
            ),
        )
    )
    identities = tuple(
        (
            _part_identity(item.request.manufacturer),
            _part_identity(item.request.part_number),
        )
        for item in reports
    )
    if len(identities) != len(set(identities)):
        raise ValueError("exact-part discovery reports must have unique part identities")
    axes = _axis_records(context, evaluation_bundle)
    resources = _resource_records(context, reports)
    dispositions = tuple(item.disposition for item in axes)
    if SemanticDisposition.FAIL in dispositions:
        outcome = ProjectGateOutcome.BLOCKED
    elif SemanticDisposition.UNVERIFIED in dispositions or any(
        not item.ready for item in resources
    ):
        outcome = ProjectGateOutcome.UNVERIFIED
    elif any(
        item in dispositions
        for item in (SemanticDisposition.ADVISORY, SemanticDisposition.VALIDATION_PENDING)
    ):
        outcome = ProjectGateOutcome.REVIEW
    else:
        outcome = ProjectGateOutcome.READY
    return {
        "discovery_reports": reports,
        "axis_records": axes,
        "part_resource_records": resources,
        "outcome": outcome,
    }


def evaluate_project_engineering_gate(
    context: ProjectEngineeringContext,
    evaluation_bundle: Phase14EvaluationBundle,
    discovery_reports: tuple[ExactPartDiscoveryReport, ...] = (),
) -> ProjectEngineeringGateResult:
    derived = rederive_project_engineering_gate(
        context,
        evaluation_bundle,
        discovery_reports,
    )
    fields = {
        "context": context,
        "evaluation_bundle": evaluation_bundle,
        **derived,
    }
    provisional = ProjectEngineeringGateResult.model_construct(
        **fields, result_fingerprint="0" * 64
    )
    payload = provisional.model_dump(mode="json", exclude={"result_fingerprint"})
    return ProjectEngineeringGateResult(**fields, result_fingerprint=fingerprint(payload))
