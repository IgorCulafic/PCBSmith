"""Project-wide applicability-to-execution evidence for Phase 17.

Repository test coverage proves that an evaluator can run.  This manifest
proves which evaluators were applicable to one exact saved design and records
the production executions that actually ran on it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class ProjectCheckApplicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"


class ProjectCheckDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"


class ProjectExecutionAuthority(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class ApplicableCheckRequirement(SemanticIrModel):
    """One authoritative applicability decision for an exact saved design."""

    schema_id: Literal["pcbsmith-applicable-check-requirement"] = (
        "pcbsmith-applicable-check-requirement"
    )
    schema_version: Literal[1] = 1
    check_id: str
    rule_ids: tuple[str, ...] = Field(min_length=1)
    applicability: ProjectCheckApplicability
    applicability_authority_id: str
    exact_input_sha256s: tuple[str, ...] = Field(min_length=1)
    minimum_evaluated_objects: int = Field(ge=0)
    rationale: str
    requirement_fingerprint: str

    @model_validator(mode="after")
    def requirement_is_canonical_and_replay_bound(self) -> Self:
        for name in ("check_id", "applicability_authority_id", "rationale"):
            require_identity(getattr(self, name), name)
        rule_ids = tuple(sorted(self.rule_ids))
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule_ids must be unique")
        for rule_id in rule_ids:
            require_identity(rule_id, "rule_id")
        inputs = tuple(sorted(self.exact_input_sha256s))
        if len(inputs) != len(set(inputs)):
            raise ValueError("exact_input_sha256s must be unique")
        for digest in inputs:
            require_sha256(digest, "exact_input_sha256")
        object.__setattr__(self, "rule_ids", rule_ids)
        object.__setattr__(self, "exact_input_sha256s", inputs)
        if (
            self.applicability is ProjectCheckApplicability.APPLICABLE
            and self.minimum_evaluated_objects < 1
        ):
            raise ValueError("applicable checks must evaluate at least one object")
        if (
            self.applicability is not ProjectCheckApplicability.APPLICABLE
            and self.minimum_evaluated_objects != 0
        ):
            raise ValueError("non-applicable/unresolved checks cannot require objects")
        require_sha256(self.requirement_fingerprint, "requirement_fingerprint")
        payload = self.model_dump(mode="json", exclude={"requirement_fingerprint"})
        if self.requirement_fingerprint != fingerprint(payload):
            raise ValueError("applicable-check requirement fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        check_id: str,
        rule_ids: tuple[str, ...],
        applicability: ProjectCheckApplicability,
        applicability_authority_id: str,
        exact_input_sha256s: tuple[str, ...],
        minimum_evaluated_objects: int,
        rationale: str,
    ) -> ApplicableCheckRequirement:
        fields: dict[str, Any] = {
            "check_id": check_id,
            "rule_ids": tuple(sorted(rule_ids)),
            "applicability": applicability,
            "applicability_authority_id": applicability_authority_id,
            "exact_input_sha256s": tuple(sorted(exact_input_sha256s)),
            "minimum_evaluated_objects": minimum_evaluated_objects,
            "rationale": rationale,
        }
        provisional = cls.model_construct(**fields, requirement_fingerprint="0" * 64)
        return cls(
            **fields,
            requirement_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"requirement_fingerprint"})
            ),
        )


class CheckExecutionRecord(SemanticIrModel):
    """Retained execution of one applicable check."""

    schema_id: Literal["pcbsmith-check-execution-record"] = "pcbsmith-check-execution-record"
    schema_version: Literal[1] = 1
    check_id: str
    exact_input_sha256s: tuple[str, ...] = Field(min_length=1)
    producer_id: str
    tool_version: str
    evaluated_object_count: int = Field(ge=0)
    disposition: ProjectCheckDisposition
    result_sha256: str
    limitations: tuple[str, ...] = ()
    execution_fingerprint: str

    @model_validator(mode="after")
    def execution_is_canonical_and_replay_bound(self) -> Self:
        for name in ("check_id", "producer_id", "tool_version"):
            require_identity(getattr(self, name), name)
        inputs = tuple(sorted(self.exact_input_sha256s))
        if len(inputs) != len(set(inputs)):
            raise ValueError("exact_input_sha256s must be unique")
        for digest in inputs:
            require_sha256(digest, "exact_input_sha256")
        limitations = tuple(sorted(self.limitations))
        if len(limitations) != len(set(limitations)):
            raise ValueError("limitations must be unique")
        for limitation in limitations:
            require_identity(limitation, "limitation")
        object.__setattr__(self, "exact_input_sha256s", inputs)
        object.__setattr__(self, "limitations", limitations)
        require_sha256(self.result_sha256, "result_sha256")
        require_sha256(self.execution_fingerprint, "execution_fingerprint")
        payload = self.model_dump(mode="json", exclude={"execution_fingerprint"})
        if self.execution_fingerprint != fingerprint(payload):
            raise ValueError("check execution fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        check_id: str,
        exact_input_sha256s: tuple[str, ...],
        producer_id: str,
        tool_version: str,
        evaluated_object_count: int,
        disposition: ProjectCheckDisposition,
        result_sha256: str,
        limitations: tuple[str, ...] = (),
    ) -> CheckExecutionRecord:
        fields: dict[str, Any] = {
            "check_id": check_id,
            "exact_input_sha256s": tuple(sorted(exact_input_sha256s)),
            "producer_id": producer_id,
            "tool_version": tool_version,
            "evaluated_object_count": evaluated_object_count,
            "disposition": disposition,
            "result_sha256": result_sha256,
            "limitations": tuple(sorted(limitations)),
        }
        provisional = cls.model_construct(**fields, execution_fingerprint="0" * 64)
        return cls(
            **fields,
            execution_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"execution_fingerprint"})
            ),
        )


class ProjectApplicabilityExecutionManifest(SemanticIrModel):
    """Fail-closed coverage proof for every declared project check."""

    schema_id: Literal["pcbsmith-project-applicability-execution-manifest"] = (
        "pcbsmith-project-applicability-execution-manifest"
    )
    schema_version: Literal[1] = 1
    project_id: str
    saved_design_sha256: str
    requirements: tuple[ApplicableCheckRequirement, ...] = Field(min_length=1)
    executions: tuple[CheckExecutionRecord, ...] = ()
    authority: ProjectExecutionAuthority
    blockers: tuple[str, ...]
    manifest_fingerprint: str

    @model_validator(mode="after")
    def manifest_is_complete_and_replay_bound(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_sha256(self.saved_design_sha256, "saved_design_sha256")
        requirements = tuple(sorted(self.requirements, key=lambda item: item.check_id))
        executions = tuple(sorted(self.executions, key=lambda item: item.check_id))
        if len({item.check_id for item in requirements}) != len(requirements):
            raise ValueError("check requirements must have unique check IDs")
        if len({item.check_id for item in executions}) != len(executions):
            raise ValueError("check executions must have unique check IDs")
        object.__setattr__(self, "requirements", requirements)
        object.__setattr__(self, "executions", executions)
        expected_blockers = derive_execution_blockers(
            saved_design_sha256=self.saved_design_sha256,
            requirements=requirements,
            executions=executions,
        )
        if self.blockers != expected_blockers:
            raise ValueError("applicability/execution blockers are stale")
        expected_authority = (
            ProjectExecutionAuthority.READY
            if not expected_blockers
            else ProjectExecutionAuthority.BLOCKED
        )
        if self.authority is not expected_authority:
            raise ValueError("applicability/execution authority is stale")
        require_sha256(self.manifest_fingerprint, "manifest_fingerprint")
        payload = self.model_dump(mode="json", exclude={"manifest_fingerprint"})
        if self.manifest_fingerprint != fingerprint(payload):
            raise ValueError("applicability/execution manifest fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        saved_design_sha256: str,
        requirements: tuple[ApplicableCheckRequirement, ...],
        executions: tuple[CheckExecutionRecord, ...],
    ) -> ProjectApplicabilityExecutionManifest:
        canonical_requirements = tuple(sorted(requirements, key=lambda item: item.check_id))
        canonical_executions = tuple(sorted(executions, key=lambda item: item.check_id))
        blockers = derive_execution_blockers(
            saved_design_sha256=saved_design_sha256,
            requirements=canonical_requirements,
            executions=canonical_executions,
        )
        fields: dict[str, Any] = {
            "project_id": project_id,
            "saved_design_sha256": saved_design_sha256,
            "requirements": canonical_requirements,
            "executions": canonical_executions,
            "authority": (
                ProjectExecutionAuthority.READY
                if not blockers
                else ProjectExecutionAuthority.BLOCKED
            ),
            "blockers": blockers,
        }
        provisional = cls.model_construct(**fields, manifest_fingerprint="0" * 64)
        return cls(
            **fields,
            manifest_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"manifest_fingerprint"})
            ),
        )


def derive_execution_blockers(
    *,
    saved_design_sha256: str,
    requirements: tuple[ApplicableCheckRequirement, ...],
    executions: tuple[CheckExecutionRecord, ...],
) -> tuple[str, ...]:
    """Derive deterministic coverage blockers from declarations and executions."""

    require_sha256(saved_design_sha256, "saved_design_sha256")
    execution_by_id = {item.check_id: item for item in executions}
    requirement_by_id = {item.check_id: item for item in requirements}
    blockers: list[str] = []
    for requirement in sorted(requirements, key=lambda item: item.check_id):
        check_id = requirement.check_id
        execution = execution_by_id.get(check_id)
        if saved_design_sha256 not in requirement.exact_input_sha256s:
            blockers.append(f"{check_id}: applicability is stale for the saved design")
        if requirement.applicability is ProjectCheckApplicability.UNRESOLVED:
            blockers.append(f"{check_id}: applicability is unresolved")
            if execution is not None:
                blockers.append(f"{check_id}: unresolved check has conflicting execution")
            continue
        if requirement.applicability is ProjectCheckApplicability.NOT_APPLICABLE:
            if execution is not None:
                blockers.append(f"{check_id}: not-applicable check has conflicting execution")
            continue
        if execution is None:
            blockers.append(f"{check_id}: applicable check execution is missing")
            continue
        if execution.exact_input_sha256s != requirement.exact_input_sha256s:
            blockers.append(f"{check_id}: execution inputs are stale or conflicting")
        if execution.evaluated_object_count < requirement.minimum_evaluated_objects:
            blockers.append(
                f"{check_id}: evaluated-object count is "
                f"{execution.evaluated_object_count}, expected at least "
                f"{requirement.minimum_evaluated_objects}"
            )
        if execution.disposition is not ProjectCheckDisposition.PASS:
            blockers.append(f"{check_id}: production execution is {execution.disposition.value}")
    for execution in sorted(executions, key=lambda item: item.check_id):
        if execution.check_id not in requirement_by_id:
            blockers.append(f"{execution.check_id}: execution has no applicability declaration")
    return tuple(blockers)
