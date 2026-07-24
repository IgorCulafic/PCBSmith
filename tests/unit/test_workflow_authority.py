from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.workflow_authority import (
    ALL_PROJECT_CONTEXT_CATEGORIES,
    PHASE16_AUTHORITY_REGISTRY_FINGERPRINT,
    PHASE16_CAPABILITY_MAP_FINGERPRINT,
    PHASE16_LEGACY_ADAPTERS,
    ApplicabilityDisposition,
    ApplicabilityInputs,
    AuthorityContract,
    AuthorityRegistry,
    IdentityDependency,
    ProjectContextBundle,
    ProjectContextCategory,
    ProjectContextRecord,
    ProjectContextStatus,
    WorkflowIdentityKind,
    WorkflowIdentityLedger,
    WorkflowIdentityRecord,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
    assess_legacy_adapter,
    build_phase16_authority_registry,
    build_phase16_capability_map,
    evaluate_authority_applicability,
    transition_workflow,
)


def _sha(value: int) -> str:
    return f"{value:064x}"


def _record(
    kind: WorkflowIdentityKind,
    value: int,
    *dependencies: tuple[WorkflowIdentityKind, int],
) -> WorkflowIdentityRecord:
    return WorkflowIdentityRecord(
        kind=kind,
        artifact_id=f"artifact.{kind.value}",
        content_sha256=_sha(value),
        dependencies=tuple(
            IdentityDependency(kind=dependency_kind, content_sha256=_sha(dependency_value))
            for dependency_kind, dependency_value in dependencies
        ),
    )


def _identities_through(stage: WorkflowStage) -> WorkflowIdentityLedger:
    records = [
        _record(WorkflowIdentityKind.RAW_PROMPT, 1),
        _record(
            WorkflowIdentityKind.OBJECT,
            2,
            (WorkflowIdentityKind.RAW_PROMPT, 1),
        ),
        _record(
            WorkflowIdentityKind.GENERATION,
            3,
            (WorkflowIdentityKind.OBJECT, 2),
        ),
    ]
    additions = (
        (
            WorkflowStage.NORMALIZED_BRIEF,
            _record(
                WorkflowIdentityKind.BRIEF,
                4,
                (WorkflowIdentityKind.GENERATION, 3),
            ),
        ),
        (
            WorkflowStage.CONCEPT_APPROVAL,
            _record(
                WorkflowIdentityKind.CONCEPT,
                5,
                (WorkflowIdentityKind.BRIEF, 4),
            ),
        ),
        (
            WorkflowStage.SCHEMATIC,
            _record(
                WorkflowIdentityKind.SCHEMATIC,
                6,
                (WorkflowIdentityKind.CONCEPT, 5),
            ),
        ),
        (
            WorkflowStage.PLACEMENT,
            _record(
                WorkflowIdentityKind.BOARD,
                7,
                (WorkflowIdentityKind.SCHEMATIC, 6),
            ),
        ),
        (
            WorkflowStage.ROUTING,
            _record(
                WorkflowIdentityKind.ROUTE,
                8,
                (WorkflowIdentityKind.BOARD, 7),
            ),
        ),
        (
            WorkflowStage.REVIEW,
            _record(
                WorkflowIdentityKind.EVIDENCE,
                9,
                (WorkflowIdentityKind.ROUTE, 8),
            ),
        ),
        (
            WorkflowStage.REVIEW,
            _record(
                WorkflowIdentityKind.REVIEW,
                10,
                (WorkflowIdentityKind.EVIDENCE, 9),
            ),
        ),
        (
            WorkflowStage.VERIFICATION,
            _record(
                WorkflowIdentityKind.VERIFICATION,
                11,
                (WorkflowIdentityKind.REVIEW, 10),
            ),
        ),
        (
            WorkflowStage.MANUFACTURING_HANDOFF,
            _record(
                WorkflowIdentityKind.MANUFACTURING,
                12,
                (WorkflowIdentityKind.VERIFICATION, 11),
            ),
        ),
    )
    order = list(WorkflowStage).index(stage)
    records.extend(
        record
        for required_stage, record in additions
        if list(WorkflowStage).index(required_stage) <= order
    )
    return WorkflowIdentityLedger(records=tuple(records))


def _context(
    *,
    unresolved: ProjectContextCategory | None = None,
) -> ProjectContextBundle:
    records = []
    for index, category in enumerate(ALL_PROJECT_CONTEXT_CATEGORIES, start=1):
        if category is unresolved:
            records.append(
                ProjectContextRecord(
                    category=category,
                    context_id=f"context.{category.value}",
                    status=ProjectContextStatus.UNRESOLVED,
                    rationale="Input remains unresolved.",
                    unresolved_ids=(f"missing.{category.value}",),
                )
            )
        else:
            records.append(
                ProjectContextRecord(
                    category=category,
                    context_id=f"context.{category.value}",
                    status=ProjectContextStatus.RESOLVED,
                    payload_sha256=_sha(100 + index),
                    source_binding_ids=(f"source.{category.value}",),
                    rationale="Reviewed project input.",
                )
            )
    return ProjectContextBundle.build(
        project_id="phase16-test",
        generation_sha256=_sha(3),
        records=tuple(records),
    )


def test_workflow_state_machine_requires_every_ordered_stage() -> None:
    state = WorkflowState.build(
        project_id="phase16-test",
        stage=WorkflowStage.RAW_PROMPT,
        status=WorkflowStatus.ACTIVE,
        identities=_identities_through(WorkflowStage.RAW_PROMPT),
    )
    normalized = transition_workflow(
        state,
        stage=WorkflowStage.NORMALIZED_BRIEF,
        identities=_identities_through(WorkflowStage.NORMALIZED_BRIEF),
    )

    assert normalized.previous_state_fingerprint == state.state_fingerprint
    with pytest.raises(ValueError, match="stage bypass"):
        transition_workflow(
            normalized,
            stage=WorkflowStage.SCHEMATIC,
            identities=_identities_through(WorkflowStage.SCHEMATIC),
        )


def test_incomplete_state_requires_reason_and_checkpoint_to_resume() -> None:
    state = WorkflowState.build(
        project_id="phase16-test",
        stage=WorkflowStage.RAW_PROMPT,
        status=WorkflowStatus.ACTIVE,
        identities=_identities_through(WorkflowStage.RAW_PROMPT),
    )
    incomplete = transition_workflow(
        state,
        status=WorkflowStatus.INCOMPLETE,
        reason="Execution budget reached.",
    )
    with pytest.raises(ValueError, match="checkpoint"):
        transition_workflow(incomplete)
    resumed = transition_workflow(
        incomplete,
        resume_checkpoint_sha256=_sha(90),
    )

    assert resumed.status is WorkflowStatus.ACTIVE
    assert resumed.stage is WorkflowStage.RAW_PROMPT


def test_failed_state_is_terminal() -> None:
    state = WorkflowState.build(
        project_id="phase16-test",
        stage=WorkflowStage.RAW_PROMPT,
        status=WorkflowStatus.ACTIVE,
        identities=_identities_through(WorkflowStage.RAW_PROMPT),
    )
    failed = transition_workflow(
        state,
        status=WorkflowStatus.FAILED,
        reason="Invalid source identity.",
    )
    with pytest.raises(ValueError, match="terminal"):
        transition_workflow(failed)


def test_board_identity_change_invalidates_every_downstream_identity() -> None:
    ledger = _identities_through(WorkflowStage.VERIFICATION)
    result = ledger.replace(
        _record(
            WorkflowIdentityKind.BOARD,
            70,
            (WorkflowIdentityKind.SCHEMATIC, 6),
        )
    )

    assert result.invalidated_kinds == (
        WorkflowIdentityKind.EVIDENCE,
        WorkflowIdentityKind.REVIEW,
        WorkflowIdentityKind.ROUTE,
        WorkflowIdentityKind.VERIFICATION,
    )
    assert result.ledger.record(WorkflowIdentityKind.BOARD).content_sha256 == _sha(70)  # type: ignore[union-attr]


def test_stale_downstream_identity_is_rejected_if_caller_bypasses_invalidation() -> None:
    payload = _identities_through(WorkflowStage.ROUTING).model_dump(mode="python")
    board = next(
        item for item in payload["records"] if item["kind"] is WorkflowIdentityKind.BOARD
    )
    board["content_sha256"] = _sha(70)

    with pytest.raises(ValidationError, match="stale board dependency"):
        WorkflowIdentityLedger(**payload)


def test_project_context_requires_every_category_exactly_once() -> None:
    context = _context()
    assert {item.category for item in context.records} == set(
        ALL_PROJECT_CONTEXT_CATEGORIES
    )
    with pytest.raises(ValidationError, match="every category exactly once"):
        ProjectContextBundle.build(
            project_id="phase16-test",
            generation_sha256=_sha(3),
            records=context.records[:-1],
        )


def test_unresolved_context_prevents_rule_authorization() -> None:
    registry = build_phase16_authority_registry()
    contract = registry.contract("fabrication.profile")
    result = evaluate_authority_applicability(
        contract=contract,
        context=_context(unresolved=ProjectContextCategory.FABRICATOR),
    )

    assert result.disposition is ApplicabilityDisposition.UNRESOLVED
    assert result.authorized_authority_id is None


def test_external_provider_unavailability_never_authorizes_a_substitute() -> None:
    registry = build_phase16_authority_registry()
    contract = registry.contract("evidence.live-part-provider")
    blocked = evaluate_authority_applicability(contract=contract, context=_context())
    available = evaluate_authority_applicability(
        contract=contract,
        context=_context(),
        inputs=ApplicabilityInputs(
            available_external_dependency_ids=(
                "provider.credentials-terms-and-cache-rights",
            )
        ),
    )

    assert blocked.disposition is ApplicabilityDisposition.BLOCKED_EXTERNAL
    assert blocked.authorized_authority_id is None
    assert available.disposition is ApplicabilityDisposition.APPLICABLE


def test_human_decision_and_board_trigger_are_explicit() -> None:
    registry = build_phase16_authority_registry()
    human = evaluate_authority_applicability(
        contract=registry.contract("review.human-approval"),
        context=_context(),
    )
    dormant = evaluate_authority_applicability(
        contract=registry.contract("layout.oscillator-zone"),
        context=_context(),
    )

    assert human.disposition is ApplicabilityDisposition.BLOCKED_HUMAN
    assert dormant.disposition is ApplicabilityDisposition.NOT_APPLICABLE


def test_registry_rejects_duplicate_active_semantic_authority() -> None:
    registry = build_phase16_authority_registry()
    original = registry.contract("fabrication.profile")
    payload = original.model_dump(mode="python")
    payload["authority_id"] = "fabrication.profile.duplicate"
    duplicate = AuthorityContract(**payload)

    with pytest.raises(ValidationError, match="duplicate active authority"):
        AuthorityRegistry(contracts=(*registry.contracts, duplicate))


def test_deprecated_one_off_authority_cannot_satisfy_current_workflow() -> None:
    registry = build_phase16_authority_registry()
    result = evaluate_authority_applicability(
        contract=registry.contract("legacy.review.preview-images"),
        context=_context(),
    )

    assert result.disposition is ApplicabilityDisposition.DEPRECATED
    assert result.authorized_authority_id is None


def test_capability_map_covers_phases_1_through_15_and_registered_authorities() -> None:
    registry = build_phase16_authority_registry()
    capability_map = build_phase16_capability_map()
    known = {item.authority_id for item in registry.contracts}

    assert {item.origin_phase for item in capability_map.records} == set(range(1, 16))
    assert all(set(item.authority_ids).issubset(known) for item in capability_map.records)
    assert registry.semantic_fingerprint() == PHASE16_AUTHORITY_REGISTRY_FINGERPRINT
    assert capability_map.semantic_fingerprint() == PHASE16_CAPABILITY_MAP_FINGERPRINT


def test_capability_and_registry_fingerprints_reject_tampering() -> None:
    context = _context()
    payload = deepcopy(context.model_dump(mode="python"))
    payload["project_id"] = "tampered"
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        ProjectContextBundle(**payload)


def test_legacy_adapters_cannot_claim_unemitted_contract_identities() -> None:
    generic, retro_pad = PHASE16_LEGACY_ADAPTERS
    generic_result = assess_legacy_adapter(generic, WorkflowStage.VERIFICATION)
    retro_result = assess_legacy_adapter(retro_pad, WorkflowStage.VERIFICATION)

    assert generic_result.outcome == "partial"
    assert WorkflowIdentityKind.BRIEF in generic_result.missing_identity_kinds
    assert retro_result.outcome == "supported"
