"""Phase 16 workflow authority, identity, context, and migration contracts.

This module consolidates metadata and state boundaries around the existing
bounded authorities.  It deliberately does not replace their geometry,
routing, evidence, or KiCad evaluators.  Phase 17 callers must consume these
contracts before they can claim production-default workflow coverage.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel

PHASE17_MIGRATION_CONTRACT_VERSION: Literal[1] = 1
PHASE16_AUTHORITY_REGISTRY_FINGERPRINT = (
    "abda6f84ece542f90de2702ee7e9fa1169916fcfdf6d493396b11dd58c5acc93"
)
PHASE16_CAPABILITY_MAP_FINGERPRINT = (
    "12d7b8a773d5ad23f80e57aaa31b4ecb7236efd16d04260182a0e779acf7f87e"
)


class WorkflowStage(StrEnum):
    RAW_PROMPT = "raw_prompt"
    NORMALIZED_BRIEF = "normalized_brief"
    CONCEPT_APPROVAL = "concept_approval"
    SCHEMATIC = "schematic"
    PLACEMENT = "placement"
    ROUTING = "routing"
    REVIEW = "review"
    VERIFICATION = "verification"
    MANUFACTURING_HANDOFF = "manufacturing_handoff"


WORKFLOW_STAGE_ORDER = tuple(WorkflowStage)


class WorkflowStatus(StrEnum):
    ACTIVE = "active"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    COMPLETE = "complete"


class WorkflowIdentityKind(StrEnum):
    RAW_PROMPT = "raw_prompt"
    OBJECT = "object"
    GENERATION = "generation"
    BRIEF = "brief"
    CONCEPT = "concept"
    SCHEMATIC = "schematic"
    BOARD = "board"
    ROUTE = "route"
    EVIDENCE = "evidence"
    REVIEW = "review"
    VERIFICATION = "verification"
    MANUFACTURING = "manufacturing"


_STAGE_REQUIRED_IDENTITIES: dict[WorkflowStage, frozenset[WorkflowIdentityKind]] = {
    WorkflowStage.RAW_PROMPT: frozenset(
        {
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
        }
    ),
    WorkflowStage.NORMALIZED_BRIEF: frozenset(
        {
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.BRIEF,
        }
    ),
    WorkflowStage.CONCEPT_APPROVAL: frozenset(
        {
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.BRIEF,
            WorkflowIdentityKind.CONCEPT,
        }
    ),
    WorkflowStage.SCHEMATIC: frozenset(
        {
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.BRIEF,
            WorkflowIdentityKind.CONCEPT,
            WorkflowIdentityKind.SCHEMATIC,
        }
    ),
    WorkflowStage.PLACEMENT: frozenset(
        {
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.BRIEF,
            WorkflowIdentityKind.CONCEPT,
            WorkflowIdentityKind.SCHEMATIC,
            WorkflowIdentityKind.BOARD,
        }
    ),
    WorkflowStage.ROUTING: frozenset(
        {
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.BRIEF,
            WorkflowIdentityKind.CONCEPT,
            WorkflowIdentityKind.SCHEMATIC,
            WorkflowIdentityKind.BOARD,
            WorkflowIdentityKind.ROUTE,
        }
    ),
    WorkflowStage.REVIEW: frozenset(
        {
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.BRIEF,
            WorkflowIdentityKind.CONCEPT,
            WorkflowIdentityKind.SCHEMATIC,
            WorkflowIdentityKind.BOARD,
            WorkflowIdentityKind.ROUTE,
            WorkflowIdentityKind.EVIDENCE,
            WorkflowIdentityKind.REVIEW,
        }
    ),
    WorkflowStage.VERIFICATION: frozenset(
        {
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.BRIEF,
            WorkflowIdentityKind.CONCEPT,
            WorkflowIdentityKind.SCHEMATIC,
            WorkflowIdentityKind.BOARD,
            WorkflowIdentityKind.ROUTE,
            WorkflowIdentityKind.EVIDENCE,
            WorkflowIdentityKind.REVIEW,
            WorkflowIdentityKind.VERIFICATION,
        }
    ),
    WorkflowStage.MANUFACTURING_HANDOFF: frozenset(WorkflowIdentityKind),
}


class IdentityDependency(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-identity-dependency"] = (
        "pcbsmith-workflow-identity-dependency"
    )
    schema_version: Literal[1] = 1
    kind: WorkflowIdentityKind
    content_sha256: str

    @model_validator(mode="after")
    def digest_is_valid(self) -> Self:
        require_sha256(self.content_sha256, "content_sha256")
        return self


class WorkflowIdentityRecord(SemanticIrModel):
    """One immutable identity and the exact upstream identities it consumes."""

    schema_id: Literal["pcbsmith-workflow-identity-record"] = (
        "pcbsmith-workflow-identity-record"
    )
    schema_version: Literal[1] = 1
    kind: WorkflowIdentityKind
    artifact_id: str
    content_sha256: str
    dependencies: tuple[IdentityDependency, ...] = ()

    @model_validator(mode="after")
    def identity_is_canonical(self) -> Self:
        require_identity(self.artifact_id, "artifact_id")
        require_sha256(self.content_sha256, "content_sha256")
        dependencies = tuple(sorted(self.dependencies, key=lambda item: item.kind.value))
        dependency_kinds = tuple(item.kind for item in dependencies)
        if len(dependency_kinds) != len(set(dependency_kinds)):
            raise ValueError("identity dependencies must have unique kinds")
        if self.kind in dependency_kinds:
            raise ValueError("an identity cannot depend on itself")
        object.__setattr__(self, "dependencies", dependencies)
        return self


class WorkflowIdentityLedger(SemanticIrModel):
    """Cross-stage identity ledger with stale-downstream rejection."""

    schema_id: Literal["pcbsmith-workflow-identity-ledger"] = (
        "pcbsmith-workflow-identity-ledger"
    )
    schema_version: Literal[1] = 1
    records: tuple[WorkflowIdentityRecord, ...]

    @model_validator(mode="after")
    def ledger_is_replay_bound(self) -> Self:
        records = tuple(sorted(self.records, key=lambda item: item.kind.value))
        by_kind = {item.kind: item for item in records}
        if len(by_kind) != len(records):
            raise ValueError("workflow identity kinds must be unique")
        for record in records:
            for dependency in record.dependencies:
                current = by_kind.get(dependency.kind)
                if current is None:
                    raise ValueError(
                        f"{record.kind.value} identity depends on missing "
                        f"{dependency.kind.value} identity"
                    )
                if current.content_sha256 != dependency.content_sha256:
                    raise ValueError(
                        f"{record.kind.value} identity retains a stale "
                        f"{dependency.kind.value} dependency"
                    )
        object.__setattr__(self, "records", records)
        return self

    def record(self, kind: WorkflowIdentityKind) -> WorkflowIdentityRecord | None:
        return next((item for item in self.records if item.kind is kind), None)

    def replace(
        self, replacement: WorkflowIdentityRecord
    ) -> IdentityInvalidationResult:
        """Replace one identity and transitively discard stale dependents."""

        by_kind = {item.kind: item for item in self.records}
        old = by_kind.get(replacement.kind)
        if old == replacement:
            return IdentityInvalidationResult(
                ledger=self,
                replacement_kind=replacement.kind,
                invalidated_kinds=(),
            )
        by_kind[replacement.kind] = replacement
        invalidated: set[WorkflowIdentityKind] = set()
        changed = True
        while changed:
            changed = False
            for kind, record in tuple(by_kind.items()):
                if kind is replacement.kind or kind in invalidated:
                    continue
                if any(
                    dependency.kind in invalidated
                    or dependency.kind not in by_kind
                    or by_kind[dependency.kind].content_sha256 != dependency.content_sha256
                    for dependency in record.dependencies
                ):
                    invalidated.add(kind)
                    changed = True
        retained = tuple(
            record for kind, record in by_kind.items() if kind not in invalidated
        )
        return IdentityInvalidationResult(
            ledger=WorkflowIdentityLedger(records=retained),
            replacement_kind=replacement.kind,
            invalidated_kinds=tuple(sorted(invalidated, key=lambda item: item.value)),
        )


class IdentityInvalidationResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-identity-invalidation"] = (
        "pcbsmith-workflow-identity-invalidation"
    )
    schema_version: Literal[1] = 1
    ledger: WorkflowIdentityLedger
    replacement_kind: WorkflowIdentityKind
    invalidated_kinds: tuple[WorkflowIdentityKind, ...]


class WorkflowState(SemanticIrModel):
    """One replay-derived state in the versioned Phase 17 workflow contract."""

    schema_id: Literal["pcbsmith-workflow-state"] = "pcbsmith-workflow-state"
    schema_version: Literal[1] = 1
    contract_version: Literal[1] = PHASE17_MIGRATION_CONTRACT_VERSION
    project_id: str
    stage: WorkflowStage
    status: WorkflowStatus
    identities: WorkflowIdentityLedger
    previous_state_fingerprint: str | None = None
    resume_checkpoint_sha256: str | None = None
    reason: str | None = None
    state_fingerprint: str

    @model_validator(mode="after")
    def state_is_coherent_and_replay_derived(self) -> Self:
        require_identity(self.project_id, "project_id")
        if self.previous_state_fingerprint is not None:
            require_sha256(
                self.previous_state_fingerprint, "previous_state_fingerprint"
            )
        if self.resume_checkpoint_sha256 is not None:
            require_sha256(self.resume_checkpoint_sha256, "resume_checkpoint_sha256")
        if self.status in {WorkflowStatus.INCOMPLETE, WorkflowStatus.FAILED}:
            if self.reason is None:
                raise ValueError("incomplete and failed states require a reason")
            require_identity(self.reason, "reason")
        elif self.reason is not None:
            raise ValueError("active and complete states cannot carry a failure reason")
        if self.status is WorkflowStatus.COMPLETE:
            if self.stage is not WorkflowStage.MANUFACTURING_HANDOFF:
                raise ValueError("only manufacturing handoff may complete the workflow")
            if self.resume_checkpoint_sha256 is not None:
                raise ValueError("complete state cannot retain a resume checkpoint")
        elif (
            self.resume_checkpoint_sha256 is not None
            and self.status is not WorkflowStatus.ACTIVE
        ):
            raise ValueError("only an active resumed state may retain a resume checkpoint")
        present = {item.kind for item in self.identities.records}
        missing = _STAGE_REQUIRED_IDENTITIES[self.stage] - present
        if missing:
            raise ValueError(
                f"{self.stage.value} state lacks required identities: "
                + ", ".join(sorted(item.value for item in missing))
            )
        require_sha256(self.state_fingerprint, "state_fingerprint")
        payload = self.model_dump(mode="json", exclude={"state_fingerprint"})
        if self.state_fingerprint != fingerprint(payload):
            raise ValueError("workflow state fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        stage: WorkflowStage,
        status: WorkflowStatus,
        identities: WorkflowIdentityLedger,
        previous_state_fingerprint: str | None = None,
        resume_checkpoint_sha256: str | None = None,
        reason: str | None = None,
    ) -> WorkflowState:
        fields: dict[str, Any] = {
            "project_id": project_id,
            "stage": stage,
            "status": status,
            "identities": identities,
            "previous_state_fingerprint": previous_state_fingerprint,
            "resume_checkpoint_sha256": resume_checkpoint_sha256,
            "reason": reason,
        }
        provisional = cls.model_construct(**fields, state_fingerprint="0" * 64)
        return cls(
            **fields,
            state_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"state_fingerprint"})
            ),
        )


def transition_workflow(
    previous: WorkflowState,
    *,
    stage: WorkflowStage | None = None,
    status: WorkflowStatus = WorkflowStatus.ACTIVE,
    identities: WorkflowIdentityLedger | None = None,
    reason: str | None = None,
    resume_checkpoint_sha256: str | None = None,
) -> WorkflowState:
    """Apply one legal state transition without permitting stage bypass."""

    if previous.status is WorkflowStatus.FAILED:
        raise ValueError("failed workflow state is terminal")
    target_stage = previous.stage if stage is None else stage
    target_identities = previous.identities if identities is None else identities
    if previous.status is WorkflowStatus.INCOMPLETE:
        if status is not WorkflowStatus.ACTIVE or target_stage is not previous.stage:
            raise ValueError("incomplete workflow may only resume its current stage")
        if resume_checkpoint_sha256 is None:
            raise ValueError("resuming an incomplete workflow requires a checkpoint")
    elif status in {WorkflowStatus.INCOMPLETE, WorkflowStatus.FAILED}:
        if target_stage is not previous.stage:
            raise ValueError("failure/incomplete transition cannot change stage")
        if resume_checkpoint_sha256 is not None:
            raise ValueError("failure/incomplete transition cannot claim a resume checkpoint")
    elif status is WorkflowStatus.COMPLETE:
        if (
            previous.stage is not WorkflowStage.MANUFACTURING_HANDOFF
            or target_stage is not WorkflowStage.MANUFACTURING_HANDOFF
        ):
            raise ValueError("completion requires an active manufacturing-handoff state")
    else:
        previous_index = WORKFLOW_STAGE_ORDER.index(previous.stage)
        if previous_index + 1 >= len(WORKFLOW_STAGE_ORDER):
            raise ValueError("manufacturing handoff must complete instead of advancing")
        expected = WORKFLOW_STAGE_ORDER[previous_index + 1]
        if target_stage is not expected:
            raise ValueError(
                f"workflow stage bypass: expected {expected.value}, got {target_stage.value}"
            )
        if resume_checkpoint_sha256 is not None:
            raise ValueError("ordinary stage transition cannot claim a resume checkpoint")
    return WorkflowState.build(
        project_id=previous.project_id,
        stage=target_stage,
        status=status,
        identities=target_identities,
        previous_state_fingerprint=previous.state_fingerprint,
        resume_checkpoint_sha256=resume_checkpoint_sha256,
        reason=reason,
    )


class ProjectContextCategory(StrEnum):
    INTERFACES = "interfaces"
    FIRMWARE_LIMITS = "firmware_limits"
    ASSEMBLY = "assembly"
    ENVIRONMENT = "environment"
    SAFETY_PROTECTION = "safety_protection"
    POWER_SEQUENCING = "power_sequencing"
    TIMING_SIGNALS = "timing_signals"
    VALIDATION = "validation"
    FABRICATOR = "fabricator"
    EXACT_PART_EVIDENCE = "exact_part_evidence"


ALL_PROJECT_CONTEXT_CATEGORIES = tuple(ProjectContextCategory)


class ProjectContextStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class ProjectContextRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-project-context-record"] = (
        "pcbsmith-project-context-record"
    )
    schema_version: Literal[1] = 1
    category: ProjectContextCategory
    context_id: str
    status: ProjectContextStatus
    payload_sha256: str | None = None
    source_binding_ids: tuple[str, ...] = ()
    reviewer_record_id: str | None = None
    rationale: str
    unresolved_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def context_record_is_truthful(self) -> Self:
        require_identity(self.context_id, "context_id")
        require_identity(self.rationale, "rationale")
        sources = tuple(sorted(self.source_binding_ids))
        unresolved = tuple(sorted(self.unresolved_ids))
        if len(sources) != len(set(sources)) or len(unresolved) != len(set(unresolved)):
            raise ValueError("context source and unresolved identities must be unique")
        for value in (*sources, *unresolved):
            require_identity(value, "context identity")
        if self.reviewer_record_id is not None:
            require_identity(self.reviewer_record_id, "reviewer_record_id")
        if self.status is ProjectContextStatus.RESOLVED:
            if self.payload_sha256 is None or not sources or unresolved:
                raise ValueError(
                    "resolved context requires payload/source identity and no unresolved IDs"
                )
            require_sha256(self.payload_sha256, "payload_sha256")
        elif self.status is ProjectContextStatus.UNRESOLVED:
            if not unresolved:
                raise ValueError("unresolved context requires explicit unresolved IDs")
            if self.payload_sha256 is not None:
                require_sha256(self.payload_sha256, "payload_sha256")
        elif self.payload_sha256 is not None or sources or unresolved:
            raise ValueError(
                "not-applicable context cannot retain payload, source, or unresolved claims"
            )
        object.__setattr__(self, "source_binding_ids", sources)
        object.__setattr__(self, "unresolved_ids", unresolved)
        return self


class ProjectContextBundle(SemanticIrModel):
    schema_id: Literal["pcbsmith-project-context-bundle"] = (
        "pcbsmith-project-context-bundle"
    )
    schema_version: Literal[1] = 1
    project_id: str
    generation_sha256: str
    records: tuple[ProjectContextRecord, ...]
    context_fingerprint: str

    @model_validator(mode="after")
    def bundle_is_complete_and_replay_bound(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_sha256(self.generation_sha256, "generation_sha256")
        records = tuple(sorted(self.records, key=lambda item: item.category.value))
        categories = tuple(item.category for item in records)
        if set(categories) != set(ALL_PROJECT_CONTEXT_CATEGORIES):
            missing = set(ALL_PROJECT_CONTEXT_CATEGORIES) - set(categories)
            extra = set(categories) - set(ALL_PROJECT_CONTEXT_CATEGORIES)
            raise ValueError(
                "project context must declare every category exactly once; "
                f"missing={sorted(item.value for item in missing)!r}, "
                f"extra={sorted(item.value for item in extra)!r}"
            )
        if len(categories) != len(set(categories)):
            raise ValueError("project context categories must be unique")
        object.__setattr__(self, "records", records)
        require_sha256(self.context_fingerprint, "context_fingerprint")
        payload = self.model_dump(mode="json", exclude={"context_fingerprint"})
        if self.context_fingerprint != fingerprint(payload):
            raise ValueError("project context fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        generation_sha256: str,
        records: tuple[ProjectContextRecord, ...],
    ) -> ProjectContextBundle:
        fields: dict[str, Any] = {
            "project_id": project_id,
            "generation_sha256": generation_sha256,
            "records": tuple(sorted(records, key=lambda item: item.category.value)),
        }
        provisional = cls.model_construct(**fields, context_fingerprint="0" * 64)
        return cls(
            **fields,
            context_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"context_fingerprint"})
            ),
        )

    def record(self, category: ProjectContextCategory) -> ProjectContextRecord:
        return next(item for item in self.records if item.category is category)


class AuthorityLifecycle(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ApplicabilityMode(StrEnum):
    ALWAYS = "always"
    BOARD_TRIGGERED = "board_triggered"
    EXTERNAL = "external"
    HUMAN_DECISION = "human_decision"


class ApplicabilityDisposition(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"
    BLOCKED_EXTERNAL = "blocked_external"
    BLOCKED_HUMAN = "blocked_human"
    DEPRECATED = "deprecated"


class AuthorityContract(SemanticIrModel):
    schema_id: Literal["pcbsmith-authority-contract"] = "pcbsmith-authority-contract"
    schema_version: Literal[1] = 1
    authority_id: str
    semantic_scope: str
    owner_module: str
    owner_entrypoint: str
    origin_phases: tuple[int, ...] = Field(min_length=1)
    result_schema_id: str
    result_schema_version: int = Field(ge=1)
    consumer_ids: tuple[str, ...] = Field(min_length=1)
    artifact_type: str
    evidence_requirements: tuple[str, ...] = Field(min_length=1)
    known_limitations: tuple[str, ...] = Field(min_length=1)
    required_context_categories: tuple[ProjectContextCategory, ...] = ()
    applicability_mode: ApplicabilityMode = ApplicabilityMode.ALWAYS
    trigger_ids: tuple[str, ...] = ()
    external_dependency_id: str | None = None
    human_decision_id: str | None = None
    lifecycle: AuthorityLifecycle = AuthorityLifecycle.ACTIVE
    replacement_authority_id: str | None = None

    @model_validator(mode="after")
    def contract_is_canonical(self) -> Self:
        for name in (
            "authority_id",
            "semantic_scope",
            "owner_module",
            "owner_entrypoint",
            "result_schema_id",
            "artifact_type",
        ):
            require_identity(getattr(self, name), name)
        for name in (
            "consumer_ids",
            "evidence_requirements",
            "known_limitations",
            "trigger_ids",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            for value in values:
                require_identity(value, name)
            object.__setattr__(self, name, values)
        phases = tuple(sorted(self.origin_phases))
        if len(phases) != len(set(phases)) or any(phase < 1 or phase > 15 for phase in phases):
            raise ValueError("origin phases must be unique values in Phase 1-15")
        object.__setattr__(self, "origin_phases", phases)
        categories = tuple(
            sorted(set(self.required_context_categories), key=lambda item: item.value)
        )
        if len(categories) != len(self.required_context_categories):
            raise ValueError("required context categories must be unique")
        object.__setattr__(self, "required_context_categories", categories)
        if self.applicability_mode is ApplicabilityMode.BOARD_TRIGGERED:
            if not self.trigger_ids:
                raise ValueError("board-triggered authority requires trigger IDs")
        elif self.trigger_ids:
            raise ValueError("only board-triggered authority may declare trigger IDs")
        if self.applicability_mode is ApplicabilityMode.EXTERNAL:
            if self.external_dependency_id is None:
                raise ValueError("external authority requires its dependency identity")
            require_identity(self.external_dependency_id, "external_dependency_id")
        elif self.external_dependency_id is not None:
            raise ValueError("non-external authority cannot declare external dependency")
        if self.applicability_mode is ApplicabilityMode.HUMAN_DECISION:
            if self.human_decision_id is None:
                raise ValueError("human-decision authority requires a decision identity")
            require_identity(self.human_decision_id, "human_decision_id")
        elif self.human_decision_id is not None:
            raise ValueError("non-human authority cannot declare a human decision")
        if self.lifecycle is AuthorityLifecycle.DEPRECATED:
            if self.replacement_authority_id is None:
                raise ValueError("deprecated authority requires a replacement identity")
            require_identity(self.replacement_authority_id, "replacement_authority_id")
        elif self.replacement_authority_id is not None:
            raise ValueError("active authority cannot declare a replacement")
        return self


class AuthorityRegistry(SemanticIrModel):
    schema_id: Literal["pcbsmith-authority-registry"] = "pcbsmith-authority-registry"
    schema_version: Literal[1] = 1
    contract_version: Literal[1] = PHASE17_MIGRATION_CONTRACT_VERSION
    contracts: tuple[AuthorityContract, ...]

    @model_validator(mode="after")
    def registry_has_one_active_owner_per_scope(self) -> Self:
        contracts = tuple(sorted(self.contracts, key=lambda item: item.authority_id))
        by_id = {item.authority_id: item for item in contracts}
        if len(by_id) != len(contracts):
            raise ValueError("authority identities must be unique")
        active_by_scope: dict[str, AuthorityContract] = {}
        for contract in contracts:
            if contract.lifecycle is AuthorityLifecycle.ACTIVE:
                if contract.semantic_scope in active_by_scope:
                    raise ValueError(
                        "duplicate active authority for semantic scope "
                        f"{contract.semantic_scope!r}"
                    )
                active_by_scope[contract.semantic_scope] = contract
        for contract in contracts:
            if contract.lifecycle is AuthorityLifecycle.DEPRECATED:
                replacement = by_id.get(contract.replacement_authority_id or "")
                if replacement is None or replacement.lifecycle is not AuthorityLifecycle.ACTIVE:
                    raise ValueError("deprecated authority replacement must be active")
                if replacement.semantic_scope != contract.semantic_scope:
                    raise ValueError(
                        "deprecated authority replacement must preserve semantic scope"
                    )
        object.__setattr__(self, "contracts", contracts)
        return self

    def contract(self, authority_id: str) -> AuthorityContract:
        for contract in self.contracts:
            if contract.authority_id == authority_id:
                return contract
        raise KeyError(authority_id)


class ApplicabilityInputs(SemanticIrModel):
    schema_id: Literal["pcbsmith-authority-applicability-inputs"] = (
        "pcbsmith-authority-applicability-inputs"
    )
    schema_version: Literal[1] = 1
    board_trigger_ids: tuple[str, ...] = ()
    available_external_dependency_ids: tuple[str, ...] = ()
    approved_human_decision_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def inputs_are_canonical(self) -> Self:
        for name in (
            "board_trigger_ids",
            "available_external_dependency_ids",
            "approved_human_decision_ids",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            for value in values:
                require_identity(value, name)
            object.__setattr__(self, name, values)
        return self


class AuthorityApplicabilityResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-authority-applicability-result"] = (
        "pcbsmith-authority-applicability-result"
    )
    schema_version: Literal[1] = 1
    authority_id: str
    context_fingerprint: str
    disposition: ApplicabilityDisposition
    authorized_authority_id: str | None
    missing_context_categories: tuple[ProjectContextCategory, ...] = ()
    blocking_dependency_id: str | None = None
    findings: tuple[str, ...] = ()
    result_fingerprint: str

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        require_identity(self.authority_id, "authority_id")
        require_sha256(self.context_fingerprint, "context_fingerprint")
        if self.disposition is ApplicabilityDisposition.APPLICABLE:
            if self.authorized_authority_id != self.authority_id:
                raise ValueError("applicable result must authorize only its own authority")
        elif self.authorized_authority_id is not None:
            raise ValueError("non-applicable result cannot authorize an authority substitute")
        if self.blocking_dependency_id is not None:
            require_identity(self.blocking_dependency_id, "blocking_dependency_id")
        require_sha256(self.result_fingerprint, "result_fingerprint")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("applicability result fingerprint is stale")
        return self


def evaluate_authority_applicability(
    *,
    contract: AuthorityContract,
    context: ProjectContextBundle,
    inputs: ApplicabilityInputs | None = None,
) -> AuthorityApplicabilityResult:
    """Resolve applicability without authorizing substitutes or guessed context."""

    inputs = ApplicabilityInputs() if inputs is None else inputs
    missing_categories = tuple(
        category
        for category in contract.required_context_categories
        if context.record(category).status is ProjectContextStatus.UNRESOLVED
    )
    blocking_dependency: str | None = None
    findings: list[str] = []
    if contract.lifecycle is AuthorityLifecycle.DEPRECATED:
        disposition = ApplicabilityDisposition.DEPRECATED
        findings.append(
            f"Authority is deprecated; migrate explicitly to "
            f"{contract.replacement_authority_id}."
        )
    elif missing_categories:
        disposition = ApplicabilityDisposition.UNRESOLVED
        findings.append("Required project context is unresolved.")
    elif (
        contract.applicability_mode is ApplicabilityMode.BOARD_TRIGGERED
        and not set(contract.trigger_ids).intersection(inputs.board_trigger_ids)
    ):
        disposition = ApplicabilityDisposition.NOT_APPLICABLE
        findings.append("No declared board trigger activates this authority.")
    elif (
        contract.applicability_mode is ApplicabilityMode.EXTERNAL
        and contract.external_dependency_id
        not in inputs.available_external_dependency_ids
    ):
        disposition = ApplicabilityDisposition.BLOCKED_EXTERNAL
        blocking_dependency = contract.external_dependency_id
        findings.append(
            "Required external dependency is unavailable; no substitute is authorized."
        )
    elif (
        contract.applicability_mode is ApplicabilityMode.HUMAN_DECISION
        and contract.human_decision_id not in inputs.approved_human_decision_ids
    ):
        disposition = ApplicabilityDisposition.BLOCKED_HUMAN
        blocking_dependency = contract.human_decision_id
        findings.append("Required human decision is absent.")
    else:
        disposition = ApplicabilityDisposition.APPLICABLE
    fields: dict[str, Any] = {
        "authority_id": contract.authority_id,
        "context_fingerprint": context.context_fingerprint,
        "disposition": disposition,
        "authorized_authority_id": (
            contract.authority_id
            if disposition is ApplicabilityDisposition.APPLICABLE
            else None
        ),
        "missing_context_categories": missing_categories,
        "blocking_dependency_id": blocking_dependency,
        "findings": tuple(findings),
    }
    provisional = AuthorityApplicabilityResult.model_construct(
        **fields, result_fingerprint="0" * 64
    )
    return AuthorityApplicabilityResult(
        **fields,
        result_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"result_fingerprint"})
        ),
    )


class CapabilityAuthorityRecord(SemanticIrModel):
    """Scheduling and ownership map for one retained Phase 1-15 capability."""

    schema_id: Literal["pcbsmith-capability-authority-record"] = (
        "pcbsmith-capability-authority-record"
    )
    schema_version: Literal[1] = 1
    origin_phase: int = Field(ge=1, le=15)
    capability_id: str
    authority_ids: tuple[str, ...] = Field(min_length=1)
    canonical_owner: str
    schemas: tuple[str, ...] = Field(min_length=1)
    callers: tuple[str, ...] = Field(min_length=1)
    tests: tuple[str, ...] = Field(min_length=1)
    artifacts: tuple[str, ...] = Field(min_length=1)
    source_evidence_requirements: tuple[str, ...] = Field(min_length=1)
    known_limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def record_is_complete(self) -> Self:
        for name in ("capability_id", "canonical_owner"):
            require_identity(getattr(self, name), name)
        for name in (
            "authority_ids",
            "schemas",
            "callers",
            "tests",
            "artifacts",
            "source_evidence_requirements",
            "known_limitations",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            for value in values:
                require_identity(value, name)
            object.__setattr__(self, name, values)
        return self


class CapabilityAuthorityMap(SemanticIrModel):
    schema_id: Literal["pcbsmith-capability-authority-map"] = (
        "pcbsmith-capability-authority-map"
    )
    schema_version: Literal[1] = 1
    records: tuple[CapabilityAuthorityRecord, ...]

    @model_validator(mode="after")
    def map_covers_every_retained_phase(self) -> Self:
        records = tuple(
            sorted(self.records, key=lambda item: (item.origin_phase, item.capability_id))
        )
        capability_ids = tuple(item.capability_id for item in records)
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("capability identities must be unique")
        phases = {item.origin_phase for item in records}
        if phases != set(range(1, 16)):
            raise ValueError("capability map must cover every retained Phase 1-15")
        object.__setattr__(self, "records", records)
        return self


class LegacyGeneratorAdapter(SemanticIrModel):
    """Truthful compatibility boundary for a retained pre-Phase-17 generator."""

    schema_id: Literal["pcbsmith-legacy-generator-adapter"] = (
        "pcbsmith-legacy-generator-adapter"
    )
    schema_version: Literal[1] = 1
    adapter_id: str
    generator_id: str
    contract_version: Literal[1] = PHASE17_MIGRATION_CONTRACT_VERSION
    supported_through_stage: WorkflowStage
    emitted_identity_kinds: tuple[WorkflowIdentityKind, ...]
    preserved_evidence_ids: tuple[str, ...] = ()
    known_gaps: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def adapter_is_bounded(self) -> Self:
        require_identity(self.adapter_id, "adapter_id")
        require_identity(self.generator_id, "generator_id")
        emitted = tuple(sorted(set(self.emitted_identity_kinds), key=lambda item: item.value))
        if len(emitted) != len(self.emitted_identity_kinds):
            raise ValueError("adapter emitted identity kinds must be unique")
        unsupported = set(emitted) - _STAGE_REQUIRED_IDENTITIES[self.supported_through_stage]
        if unsupported:
            raise ValueError("adapter cannot emit identities beyond its supported stage")
        for name in ("preserved_evidence_ids", "known_gaps"):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            for value in values:
                require_identity(value, name)
            object.__setattr__(self, name, values)
        object.__setattr__(self, "emitted_identity_kinds", emitted)
        return self


class LegacyAdapterAssessment(SemanticIrModel):
    schema_id: Literal["pcbsmith-legacy-adapter-assessment"] = (
        "pcbsmith-legacy-adapter-assessment"
    )
    schema_version: Literal[1] = 1
    adapter_id: str
    requested_stage: WorkflowStage
    outcome: Literal["supported", "partial"]
    missing_identity_kinds: tuple[WorkflowIdentityKind, ...]
    findings: tuple[str, ...]


def assess_legacy_adapter(
    adapter: LegacyGeneratorAdapter, requested_stage: WorkflowStage
) -> LegacyAdapterAssessment:
    supported_index = WORKFLOW_STAGE_ORDER.index(adapter.supported_through_stage)
    requested_index = WORKFLOW_STAGE_ORDER.index(requested_stage)
    missing = tuple(
        sorted(
            _STAGE_REQUIRED_IDENTITIES[requested_stage]
            - set(adapter.emitted_identity_kinds),
            key=lambda item: item.value,
        )
    )
    supported = requested_index <= supported_index and not missing
    findings = (
        ()
        if supported
        else (
            "Legacy adapter is bounded below the requested workflow claim.",
            *adapter.known_gaps,
        )
    )
    return LegacyAdapterAssessment(
        adapter_id=adapter.adapter_id,
        requested_stage=requested_stage,
        outcome="supported" if supported else "partial",
        missing_identity_kinds=missing,
        findings=findings,
    )


def _authority(
    authority_id: str,
    semantic_scope: str,
    owner_module: str,
    owner_entrypoint: str,
    origin_phases: tuple[int, ...],
    result_schema_id: str,
    consumer_ids: tuple[str, ...],
    artifact_type: str,
    *,
    contexts: tuple[ProjectContextCategory, ...] = (),
    mode: ApplicabilityMode = ApplicabilityMode.ALWAYS,
    triggers: tuple[str, ...] = (),
    external_dependency_id: str | None = None,
    human_decision_id: str | None = None,
) -> AuthorityContract:
    return AuthorityContract(
        authority_id=authority_id,
        semantic_scope=semantic_scope,
        owner_module=owner_module,
        owner_entrypoint=owner_entrypoint,
        origin_phases=origin_phases,
        result_schema_id=result_schema_id,
        result_schema_version=1,
        consumer_ids=consumer_ids,
        artifact_type=artifact_type,
        evidence_requirements=(
            "exact input identity",
            "replay-valid result identity",
            "declared applicability",
        ),
        known_limitations=(
            "bounded to declared inputs and consumers",
            "does not replace KiCad or named human release authority",
        ),
        required_context_categories=contexts,
        applicability_mode=mode,
        trigger_ids=triggers,
        external_dependency_id=external_dependency_id,
        human_decision_id=human_decision_id,
    )


def _deprecated_authority(
    authority_id: str,
    semantic_scope: str,
    owner_module: str,
    replacement_authority_id: str,
    origin_phases: tuple[int, ...],
) -> AuthorityContract:
    return AuthorityContract(
        authority_id=authority_id,
        semantic_scope=semantic_scope,
        owner_module=owner_module,
        owner_entrypoint="deprecated",
        origin_phases=origin_phases,
        result_schema_id="pcbsmith-deprecated-authority",
        result_schema_version=1,
        consumer_ids=("phase17.compatibility-audit",),
        artifact_type="legacy non-authoritative artifact",
        evidence_requirements=("retained historical evidence only",),
        known_limitations=("cannot satisfy the Phase 17 workflow contract",),
        lifecycle=AuthorityLifecycle.DEPRECATED,
        replacement_authority_id=replacement_authority_id,
    )


def build_phase16_authority_registry() -> AuthorityRegistry:
    """Return the frozen v1 canonical-owner registry consumed by Phase 17."""

    c = ProjectContextCategory
    triggered = ApplicabilityMode.BOARD_TRIGGERED
    contracts = (
        _authority(
            "fabrication.profile",
            "fabrication/electrical profile and ordinary geometry",
            "pcbsmith.rule_profiles",
            "ProjectRuleProfile",
            (1,),
            "pcbsmith-project-rule-profile",
            ("phase17.project-context", "phase18.manufacturing-package"),
            "profile JSON",
            contexts=(c.FABRICATOR, c.ENVIRONMENT),
        ),
        _authority(
            "routing.negotiated",
            "negotiated detailed routing and resource capacity",
            "pcbsmith.kicad.group_negotiation",
            "route_board_with_group_negotiation",
            (2,),
            "pcbsmith-routing-run-result",
            ("phase17.routing",),
            "routing result",
            contexts=(c.INTERFACES, c.TIMING_SIGNALS),
        ),
        _authority(
            "routing.corridor",
            "shaped corridor capacity and exchange guidance",
            "pcbsmith.corridor_allocator",
            "allocate_corridor_demands",
            (3,),
            "pcbsmith-corridor-allocation-result",
            ("phase17.placement-capacity", "phase17.routing"),
            "corridor plan",
            contexts=(c.INTERFACES, c.TIMING_SIGNALS),
        ),
        _authority(
            "routing.ordered-bus",
            "ordered bus lane planning and checked physical handoff",
            "pcbsmith.kicad.bus_integration",
            "build_bus_integration",
            (4,),
            "pcbsmith-bus-integration-result",
            ("phase17.routing",),
            "bus handoff",
            contexts=(c.INTERFACES, c.TIMING_SIGNALS),
            mode=triggered,
            triggers=("board.repeated_or_ordered_bus",),
        ),
        _authority(
            "placement.exact",
            "placement candidates, exact geometry, and routability acceptance",
            "pcbsmith.kicad.placement_pilot_acceptance",
            "PlacementPilotAcceptance",
            (5,),
            "pcbsmith-placement-pilot-acceptance",
            ("phase17.placement",),
            "placement acceptance",
            contexts=(c.ASSEMBLY, c.INTERFACES),
        ),
        _authority(
            "layout.semantic-process",
            "semantic and process-scoped layout evaluation",
            "pcbsmith.semantic_ir",
            "SemanticLayoutResult",
            (6,),
            "pcbsmith-semantic-layout-result",
            ("phase17.review", "phase18.dfm"),
            "semantic result",
            contexts=(c.ASSEMBLY, c.ENVIRONMENT, c.VALIDATION),
        ),
        _authority(
            "kicad.saved-board",
            "saved KiCad board ERC/DRC/read-back authority",
            "pcbsmith.kicad.validate",
            "run_drc",
            (7,),
            "pcbsmith-kicad-validation-result",
            ("phase17.verification", "phase18.manufacturing-package"),
            "KiCad reports and saved board",
        ),
        _authority(
            "assets.model-preflight",
            "installed 3D-model path and fidelity preflight",
            "pcbsmith.kicad.model_preflight",
            "preflight_board_models",
            (8, 11),
            "pcbsmith-model-preflight-report",
            ("phase17.review", "phase19.mcad"),
            "model preflight report",
            contexts=(c.EXACT_PART_EVIDENCE,),
            mode=triggered,
            triggers=("board.requires_3d_models",),
        ),
        _authority(
            "workflow.conformance",
            "workflow requirement and deviation conformance",
            "pcbsmith.workflow_conformance",
            "evaluate_workflow_conformance",
            (9, 15),
            "pcbsmith-workflow-conformance-report",
            ("phase17.workflow",),
            "workflow conformance report",
        ),
        _authority(
            "environment.execution-baseline",
            "supported Python/tool environment and deterministic command baseline",
            "pcbsmith.execution",
            "standard_verification_gates",
            (10, 12),
            "pcbsmith-verification-run",
            ("phase17.execution", "repository.release-check"),
            "verification run",
        ),
        _authority(
            "evidence.source-intake",
            "controlled rights-aware source retrieval and cache intake",
            "pcbsmith.evidence.source_intake",
            "retrieve_catalog",
            (11, 14),
            "pcbsmith-source-intake-result",
            ("phase17.evidence", "phase20.analysis"),
            "source intake record",
            contexts=(c.EXACT_PART_EVIDENCE,),
            mode=triggered,
            triggers=("project.requires_external_source",),
        ),
        _authority(
            "evidence.live-part-provider",
            "live exact-part multi-role provider access",
            "pcbsmith.evidence.part_discovery",
            "discover_exact_part_resources",
            (14,),
            "pcbsmith-exact-part-discovery-report",
            ("phase17.part-resolution",),
            "provider discovery report",
            contexts=(c.EXACT_PART_EVIDENCE,),
            mode=ApplicabilityMode.EXTERNAL,
            external_dependency_id="provider.credentials-terms-and-cache-rights",
        ),
        _authority(
            "assets.installation",
            "rights-aware KiCad symbol, footprint, and model installation",
            "pcbsmith.kicad.asset_install",
            "install_asset",
            (11,),
            "pcbsmith-installed-asset-record",
            ("phase17.part-resolution", "phase19.mcad"),
            "installed asset record",
            contexts=(c.EXACT_PART_EVIDENCE,),
            mode=triggered,
            triggers=("project.requires_asset_install",),
        ),
        _authority(
            "review.visual-package",
            "canonical visual-review package and recorded human inspection",
            "pcbsmith.review.visual_package",
            "build_visual_review_package",
            (11,),
            "pcbsmith-visual-review-manifest",
            ("phase17.review",),
            "review package",
        ),
        _authority(
            "review.human-approval",
            "named human visual and release review decision",
            "pcbsmith.review.visual_package",
            "record_visual_review",
            (11, 15),
            "pcbsmith-visual-review-record",
            ("phase17.review", "phase21.release"),
            "review decision",
            mode=ApplicabilityMode.HUMAN_DECISION,
            human_decision_id="reviewer.named-approval",
        ),
        _authority(
            "execution.budgets",
            "execution profiles, budgets, checkpoints, and verification orchestration",
            "pcbsmith.execution",
            "VerificationOrchestrator",
            (12,),
            "pcbsmith-verification-run",
            ("phase17.execution",),
            "execution ledger",
        ),
        _authority(
            "tests.stewardship",
            "test/check ownership, collection, and runtime attribution",
            "tools.audit_test_and_check_suite",
            "build_report",
            (12,),
            "pcbsmith-test-check-stewardship-audit-v2",
            ("repository.maintainer",),
            "stewardship audit",
        ),
        _authority(
            "brief.normalization",
            "project brief normalization and unresolved-decision gate",
            "pcbsmith.project_brief",
            "normalize_project_brief",
            (13,),
            "pcbsmith-project-brief-v1",
            ("phase17.prompt-examiner", "phase17.concept"),
            "normalized brief",
        ),
        _authority(
            "predesign.feasibility",
            "predesign physical conflict and capacity feasibility",
            "pcbsmith.predesign_gate",
            "evaluate_predesign",
            (13,),
            "pcbsmith-predesign-report",
            ("phase17.concept", "phase17.placement-capacity"),
            "predesign report",
            contexts=(c.INTERFACES, c.ASSEMBLY),
        ),
        _authority(
            "engineering.project-gate",
            "reviewed project inventory and rule-family applicability",
            "pcbsmith.project_engineering_gate",
            "evaluate_project_engineering_gate",
            (14,),
            "pcbsmith-project-engineering-gate-result",
            ("phase17.review", "phase20.analysis"),
            "engineering gate result",
            contexts=(c.EXACT_PART_EVIDENCE, c.VALIDATION),
        ),
        _authority(
            "layout.decoupling-loop",
            "routed decoupling-loop topology",
            "pcbsmith.kicad.decoupling_loop",
            "evaluate_decoupling_loop",
            (14,),
            "pcbsmith-decoupling-loop-result",
            ("engineering.project-gate",),
            "semantic evaluation",
            contexts=(c.EXACT_PART_EVIDENCE,),
            mode=triggered,
            triggers=("board.has_decoupling_loop",),
        ),
        _authority(
            "layout.connector-protection-order",
            "connector-to-protection routed ordering",
            "pcbsmith.kicad.connector_protection_order",
            "evaluate_connector_protection_order",
            (14,),
            "pcbsmith-connector-protection-order-result",
            ("engineering.project-gate",),
            "semantic evaluation",
            contexts=(c.INTERFACES, c.SAFETY_PROTECTION),
            mode=triggered,
            triggers=("board.has_protected_connector",),
        ),
        _authority(
            "layout.oscillator-zone",
            "oscillator keepout and evidence zone",
            "pcbsmith.kicad.oscillator_zone",
            "evaluate_oscillator_zone",
            (14,),
            "pcbsmith-oscillator-zone-result",
            ("engineering.project-gate",),
            "semantic evaluation",
            contexts=(c.TIMING_SIGNALS, c.EXACT_PART_EVIDENCE),
            mode=triggered,
            triggers=("board.has_oscillator",),
        ),
        _authority(
            "layout.switching-hot-loop",
            "switching hot-loop membership and projected area",
            "pcbsmith.kicad.switching_hot_loop",
            "evaluate_switching_hot_loop",
            (14,),
            "pcbsmith-switching-hot-loop-result",
            ("engineering.project-gate", "phase20.analysis"),
            "semantic evaluation",
            contexts=(c.POWER_SEQUENCING, c.EXACT_PART_EVIDENCE),
            mode=triggered,
            triggers=("board.has_switching_converter",),
        ),
        _authority(
            "layout.return-adjacency",
            "stack-up and reference-plane continuity",
            "pcbsmith.kicad.return_adjacency",
            "evaluate_return_adjacency",
            (14,),
            "pcbsmith-return-adjacency-result",
            ("engineering.project-gate", "phase20.analysis"),
            "semantic evaluation",
            contexts=(c.INTERFACES, c.FABRICATOR),
            mode=triggered,
            triggers=("board.requires_reference_continuity",),
        ),
        _authority(
            "engineering.multiphysics-foundation",
            "operating scenarios, loss/stress, protection, and electrothermal foundation",
            "pcbsmith.generation.bldc_esc_engineering",
            "build_bldc_esc_engineering_bundle",
            (15,),
            "pcbsmith-bldc-esc-engineering-bundle",
            ("phase20.analysis", "phase21.validation"),
            "engineering bundle",
            contexts=(
                c.ENVIRONMENT,
                c.SAFETY_PROTECTION,
                c.POWER_SEQUENCING,
                c.VALIDATION,
                c.EXACT_PART_EVIDENCE,
            ),
            mode=triggered,
            triggers=("board.requires_multiphysics",),
        ),
        _deprecated_authority(
            "legacy.review.preview-images",
            "canonical visual-review package and recorded human inspection",
            "pcbsmith.kicad.preview",
            "review.visual-package",
            (7, 9),
        ),
        _deprecated_authority(
            "legacy.workflow.directory-existence",
            "workflow requirement and deviation conformance",
            "legacy.generator-scripts",
            "workflow.conformance",
            (9,),
        ),
        _deprecated_authority(
            "legacy.routing.process-order",
            "negotiated detailed routing and resource capacity",
            "pcbsmith.kicad.astar_router",
            "routing.negotiated",
            (2, 7),
        ),
    )
    return AuthorityRegistry(contracts=contracts)


def _capability(
    phase: int,
    capability_id: str,
    authority_ids: tuple[str, ...],
    owner: str,
    schemas: tuple[str, ...],
    callers: tuple[str, ...],
    tests: tuple[str, ...],
    artifacts: tuple[str, ...],
    limitations: tuple[str, ...],
) -> CapabilityAuthorityRecord:
    return CapabilityAuthorityRecord(
        origin_phase=phase,
        capability_id=capability_id,
        authority_ids=authority_ids,
        canonical_owner=owner,
        schemas=schemas,
        callers=callers,
        tests=tests,
        artifacts=artifacts,
        source_evidence_requirements=("declared applicability", "exact retained inputs"),
        known_limitations=limitations,
    )


def build_phase16_capability_map() -> CapabilityAuthorityMap:
    """Build the complete retained Phase 1-15 scheduling/ownership map."""

    records = (
        _capability(
            1,
            "phase1.fabrication-profile",
            ("fabrication.profile",),
            "pcbsmith.rule_profiles",
            ("pcbsmith-project-rule-profile",),
            ("phase17.project-context", "phase18.manufacturing-package"),
            ("tests/unit/kicad/test_rule_profiles.py",),
            ("project profile JSON",),
            ("remaining manufacturing breadth belongs to Phase 18",),
        ),
        _capability(
            2,
            "phase2.negotiated-routing",
            ("routing.negotiated",),
            "pcbsmith.kicad.group_negotiation",
            ("pcbsmith-routing-run-result",),
            ("phase17.routing",),
            ("tests/unit/kicad/test_group_negotiation.py",),
            ("routing result",),
            ("not yet a production-default caller",),
        ),
        _capability(
            3,
            "phase3.corridor-capacity",
            ("routing.corridor",),
            "pcbsmith.corridor_allocator",
            ("pcbsmith-corridor-allocation-result",),
            ("phase17.placement-capacity", "phase17.routing"),
            ("tests/unit/test_corridor_allocator.py",),
            ("corridor plan",),
            ("soft guidance is not physical routability proof",),
        ),
        _capability(
            4,
            "phase4.ordered-bus",
            ("routing.ordered-bus",),
            "pcbsmith.kicad.bus_integration",
            ("pcbsmith-bus-integration-result",),
            ("phase17.routing",),
            ("tests/unit/kicad/test_bus_integration.py",),
            ("checked bus handoff",),
            ("saved/read-back default consumption remains Phase 17",),
        ),
        _capability(
            5,
            "phase5.placement-authority",
            ("placement.exact",),
            "pcbsmith.kicad.placement_pilot_acceptance",
            ("pcbsmith-placement-pilot-acceptance",),
            ("phase17.placement",),
            ("tests/unit/kicad/test_placement_pilot_authority.py",),
            ("placement acceptance",),
            ("bounded pilots do not prove broad placement search",),
        ),
        _capability(
            6,
            "phase6.semantic-process",
            ("layout.semantic-process",),
            "pcbsmith.semantic_ir",
            ("pcbsmith-semantic-layout-result",),
            ("phase17.review", "phase18.dfm"),
            ("tests/unit/test_semantic_ir.py",),
            ("semantic result",),
            ("board declarations remain applicability-scoped",),
        ),
        _capability(
            7,
            "phase7.thermometer-board",
            ("kicad.saved-board",),
            "pcbsmith.kicad.validate",
            ("pcbsmith-kicad-validation-result",),
            ("phase17.verification",),
            ("tests/unit/kicad/test_thermometer_board.py",),
            ("R005 saved board and reports",),
            ("accepted project proof is not generic workflow proof",),
        ),
        _capability(
            8,
            "phase8.3d-assets",
            ("assets.model-preflight",),
            "pcbsmith.kicad.model_preflight",
            ("pcbsmith-model-preflight-report",),
            ("phase17.review", "phase19.mcad"),
            ("tests/unit/kicad/test_model_preflight.py",),
            ("R006 model preflight",),
            ("proxy models are not fit or procurement evidence",),
        ),
        _capability(
            9,
            "phase9.workflow-requirements",
            ("workflow.conformance",),
            "pcbsmith.workflow_conformance",
            ("pcbsmith-workflow-conformance-report",),
            ("phase17.workflow",),
            ("tests/unit/test_workflow_conformance.py",),
            ("workflow conformance report",),
            ("callable conformance is not production invocation",),
        ),
        _capability(
            10,
            "phase10.environment-continuity",
            ("environment.execution-baseline",),
            "pcbsmith.execution",
            ("pcbsmith-verification-run",),
            ("repository.release-check",),
            ("tests/unit/test_execution.py",),
            ("verification run",),
            ("external user snapshot automation remains out of repository scope",),
        ),
        _capability(
            11,
            "phase11.evidence-assets-review",
            (
                "assets.installation",
                "assets.model-preflight",
                "evidence.source-intake",
                "review.human-approval",
                "review.visual-package",
            ),
            "pcbsmith.evidence.source_intake",
            (
                "pcbsmith-installed-asset-record",
                "pcbsmith-source-intake-result",
                "pcbsmith-visual-review-manifest",
            ),
            ("phase17.evidence", "phase17.review"),
            (
                "tests/unit/evidence/test_source_intake.py",
                "tests/unit/review/test_visual_package.py",
            ),
            ("source cache records", "visual review package"),
            ("automatic production invocation remains Phase 17",),
        ),
        _capability(
            12,
            "phase12.execution-test-health",
            ("execution.budgets", "tests.stewardship"),
            "pcbsmith.execution",
            ("pcbsmith-test-check-stewardship-audit-v2", "pcbsmith-verification-run"),
            ("phase17.execution", "repository.maintainer"),
            ("tests/unit/test_execution.py",),
            ("execution ledger", "stewardship audit"),
            ("algorithm-native budget binding remains Phase 17",),
        ),
        _capability(
            13,
            "phase13.project-intake",
            ("brief.normalization", "predesign.feasibility"),
            "pcbsmith.project_brief",
            ("pcbsmith-predesign-report", "pcbsmith-project-brief-v1"),
            ("phase17.prompt-examiner", "phase17.concept"),
            ("tests/unit/test_predesign_gate.py", "tests/unit/test_project_brief.py"),
            ("normalized brief", "predesign report"),
            ("prompt examiner and typed anchors remain Phase 17",),
        ),
        _capability(
            14,
            "phase14.engineering-applicability",
            (
                "engineering.project-gate",
                "evidence.live-part-provider",
                "evidence.source-intake",
                "layout.connector-protection-order",
                "layout.decoupling-loop",
                "layout.oscillator-zone",
                "layout.return-adjacency",
                "layout.switching-hot-loop",
            ),
            "pcbsmith.project_engineering_gate",
            ("pcbsmith-project-engineering-gate-result",),
            ("phase17.review", "phase20.analysis"),
            ("tests/unit/test_project_engineering_gate.py",),
            ("engineering gate result",),
            ("five promoted families are narrow and input-completeness bounded",),
        ),
        _capability(
            15,
            "phase15.workflow-multiphysics",
            ("engineering.multiphysics-foundation", "workflow.conformance"),
            "pcbsmith.generation.bldc_esc_engineering",
            (
                "pcbsmith-bldc-esc-engineering-bundle",
                "pcbsmith-workflow-conformance-report",
            ),
            ("phase20.analysis", "phase21.validation"),
            (
                "tests/unit/generation/test_bldc_esc_engineering.py",
                "tests/unit/test_workflow_conformance.py",
            ),
            ("engineering bundle", "workflow conformance report"),
            ("foundation is indeterminate without exact physical inputs and correlation",),
        ),
    )
    return CapabilityAuthorityMap(records=records)


PHASE16_LEGACY_ADAPTERS = (
    LegacyGeneratorAdapter(
        adapter_id="legacy.authority-generators-v1",
        generator_id="pcbsmith.cli.design-authority-family",
        supported_through_stage=WorkflowStage.VERIFICATION,
        emitted_identity_kinds=(
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.SCHEMATIC,
            WorkflowIdentityKind.BOARD,
            WorkflowIdentityKind.ROUTE,
            WorkflowIdentityKind.EVIDENCE,
            WorkflowIdentityKind.REVIEW,
            WorkflowIdentityKind.VERIFICATION,
        ),
        preserved_evidence_ids=("legacy-authority-bundle",),
        known_gaps=(
            "no normalized-brief identity",
            "no approved-concept identity",
            "not transactional under one generation identity",
        ),
    ),
    LegacyGeneratorAdapter(
        adapter_id="legacy.retro-pad-r002",
        generator_id="tools.generate_retro_pad_r003",
        supported_through_stage=WorkflowStage.VERIFICATION,
        emitted_identity_kinds=(
            WorkflowIdentityKind.RAW_PROMPT,
            WorkflowIdentityKind.OBJECT,
            WorkflowIdentityKind.GENERATION,
            WorkflowIdentityKind.BRIEF,
            WorkflowIdentityKind.CONCEPT,
            WorkflowIdentityKind.SCHEMATIC,
            WorkflowIdentityKind.BOARD,
            WorkflowIdentityKind.ROUTE,
            WorkflowIdentityKind.EVIDENCE,
            WorkflowIdentityKind.REVIEW,
            WorkflowIdentityKind.VERIFICATION,
        ),
        preserved_evidence_ids=("outputs/retro-pad-r002",),
        known_gaps=(
            "execution orchestration is not the normal caller",
            "transaction rollback and resumable route-domain checkpoints are absent",
        ),
    ),
)
