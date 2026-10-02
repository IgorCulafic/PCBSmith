"""Transactional W8 execution over independently-audited local repair candidates."""

from __future__ import annotations

import hashlib
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.bounded_local_repair import (
    LocalRepairOutcome,
    LocalRepairRequest,
    LocalRepairResult,
    RepairFindingClass,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.whole_board_qualification import WholeBoardQualification


class LocalizedRepairFinding(SemanticIrModel):
    finding_id: str
    qualification_blocker_id: str
    finding_class: RepairFindingClass
    target_region_mm: tuple[float, float, float, float]
    affected_net_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def finding_is_localized(self) -> Self:
        require_identity(self.finding_id, "finding_id")
        require_identity(self.qualification_blocker_id, "qualification_blocker_id")
        x1, y1, x2, y2 = self.target_region_mm
        if not (x1 < x2 and y1 < y2):
            raise ValueError("localized repair finding requires positive area")
        return self


class RepairCandidateAssessment(SemanticIrModel):
    candidate_board_sha256: str
    changed_object_ids: tuple[str, ...]
    moved_component_displacements_mm: dict[str, float]
    removed_segment_ids: tuple[str, ...] = ()
    removed_via_ids: tuple[str, ...] = ()
    added_segment_ids: tuple[str, ...] = ()
    added_via_ids: tuple[str, ...] = ()
    change_bounds_mm: tuple[float, float, float, float]
    target_findings_removed: tuple[str, ...]
    new_finding_ids: tuple[str, ...]
    protected_region_fingerprints: dict[str, str]
    unresolved_burden: int = Field(ge=0)
    craft_cost: int = Field(ge=0)
    assessment_fingerprint: str

    @model_validator(mode="after")
    def assessment_is_canonical(self) -> Self:
        require_sha256(self.candidate_board_sha256, "candidate_board_sha256")
        require_sha256(self.assessment_fingerprint, "assessment_fingerprint")
        for name in (
            "changed_object_ids",
            "removed_segment_ids",
            "removed_via_ids",
            "added_segment_ids",
            "added_via_ids",
            "target_findings_removed",
            "new_finding_ids",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique identities")
            object.__setattr__(self, name, values)
        for value in self.protected_region_fingerprints.values():
            require_sha256(value, "protected_region_fingerprints")
        payload = self.model_dump(mode="json", exclude={"assessment_fingerprint"})
        if self.assessment_fingerprint != fingerprint(payload):
            raise ValueError("repair candidate assessment fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> RepairCandidateAssessment:
        provisional = cls.model_construct(**values, assessment_fingerprint="0" * 64)
        return cls(
            **values,
            assessment_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"assessment_fingerprint"})
            ),
        )


class LocalRepairExecution(SemanticIrModel):
    schema_id: Literal["pcbsmith-local-repair-execution-v1"] = "pcbsmith-local-repair-execution-v1"
    source_board_file: str
    retained_candidate_file: str | None
    source_board_sha256_before: str
    source_board_sha256_after: str
    attempt_assessment_fingerprints: tuple[str, ...]
    result: LocalRepairResult

    @model_validator(mode="after")
    def execution_preserved_source(self) -> Self:
        if self.source_board_sha256_before != self.source_board_sha256_after:
            raise ValueError("local repair execution mutated the source board")
        if self.source_board_sha256_before != self.result.request.source_board_sha256:
            raise ValueError("local repair request targets another source board")
        if self.result.publish_authorized != (self.retained_candidate_file is not None):
            raise ValueError("only an accepted candidate may be retained for publication")
        return self


Proposer = Callable[[Path, Path, int], Path]
Assessor = Callable[[Path], RepairCandidateAssessment]


def execute_bounded_local_repair(
    *,
    source_board: Path,
    transaction_root: Path,
    request: LocalRepairRequest,
    source_protected_region_fingerprints: dict[str, str],
    source_unresolved_burden: int,
    source_craft_cost: int,
    proposer: Proposer,
    assessor: Assessor,
) -> LocalRepairExecution:
    """Evaluate isolated candidates and retain only a monotonic, budgeted repair."""

    source = source_board.resolve()
    before = _sha(source)
    if before != request.source_board_sha256:
        raise ValueError("local repair request targets another source board")
    transaction_root.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    assessments: list[RepairCandidateAssessment] = []
    blockers: list[str] = []
    final: RepairCandidateAssessment | None = None
    retained: Path | None = None
    outcome = LocalRepairOutcome.EXHAUSTED
    attempts_run = 0
    for attempt in range(1, request.budget.maximum_attempt_count + 1):
        attempts_run = attempt
        elapsed = time.monotonic() - start
        if elapsed >= request.budget.maximum_elapsed_seconds:
            blockers.append("repair_time_budget_exhausted")
            break
        attempt_dir = transaction_root / f"attempt-{attempt:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        candidate = proposer(source, attempt_dir, attempt).resolve()
        if not candidate.is_file() or candidate == source:
            blockers.append(f"attempt-{attempt}:candidate_not_isolated")
            continue
        assessment = assessor(candidate)
        assessments.append(assessment)
        if time.monotonic() - start > request.budget.maximum_elapsed_seconds:
            blockers.append(f"attempt-{attempt}:repair_time_budget_exhausted")
            outcome = LocalRepairOutcome.EXHAUSTED
            break
        if _sha(candidate) != assessment.candidate_board_sha256:
            blockers.append(f"attempt-{attempt}:candidate_hash_mismatch")
            continue
        violations = _budget_violations(request, assessment)
        if violations:
            blockers.extend(f"attempt-{attempt}:{item}" for item in violations)
            outcome = LocalRepairOutcome.REJECTED_REGRESSION
            continue
        candidate_result = LocalRepairResult.build(
            request=request,
            candidate_board_sha256=assessment.candidate_board_sha256,
            outcome=LocalRepairOutcome.ACCEPTED,
            attempts_used=attempt,
            elapsed_seconds=time.monotonic() - start,
            target_findings_removed=assessment.target_findings_removed,
            new_finding_ids=assessment.new_finding_ids,
            protected_region_fingerprints_before=source_protected_region_fingerprints,
            protected_region_fingerprints_after=assessment.protected_region_fingerprints,
            source_unresolved_burden=source_unresolved_burden,
            candidate_unresolved_burden=assessment.unresolved_burden,
            source_craft_cost=source_craft_cost,
            candidate_craft_cost=assessment.craft_cost,
            blocker_ids=(),
        )
        if not candidate_result.publish_authorized:
            blockers.append(f"attempt-{attempt}:monotonic_acceptance_failed")
            outcome = LocalRepairOutcome.REJECTED_REGRESSION
            continue
        retained = transaction_root / "accepted" / candidate.name
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, retained)
        final = assessment
        outcome = LocalRepairOutcome.ACCEPTED
        break
    elapsed = time.monotonic() - start
    if final is not None:
        result = LocalRepairResult.build(
            request=request,
            candidate_board_sha256=final.candidate_board_sha256,
            outcome=LocalRepairOutcome.ACCEPTED,
            attempts_used=attempts_run,
            elapsed_seconds=elapsed,
            target_findings_removed=final.target_findings_removed,
            new_finding_ids=final.new_finding_ids,
            protected_region_fingerprints_before=source_protected_region_fingerprints,
            protected_region_fingerprints_after=final.protected_region_fingerprints,
            source_unresolved_burden=source_unresolved_burden,
            candidate_unresolved_burden=final.unresolved_burden,
            source_craft_cost=source_craft_cost,
            candidate_craft_cost=final.craft_cost,
            blocker_ids=(),
        )
    else:
        result = LocalRepairResult.build(
            request=request,
            candidate_board_sha256=None,
            outcome=outcome,
            attempts_used=attempts_run,
            elapsed_seconds=elapsed,
            target_findings_removed=(),
            new_finding_ids=(),
            protected_region_fingerprints_before=source_protected_region_fingerprints,
            protected_region_fingerprints_after=source_protected_region_fingerprints,
            source_unresolved_burden=source_unresolved_burden,
            candidate_unresolved_burden=None,
            source_craft_cost=source_craft_cost,
            candidate_craft_cost=None,
            blocker_ids=tuple(sorted(set(blockers or ("repair_attempt_budget_exhausted",)))),
        )
    after = _sha(source)
    return LocalRepairExecution(
        source_board_file=str(source),
        retained_candidate_file=None if retained is None else str(retained),
        source_board_sha256_before=before,
        source_board_sha256_after=after,
        attempt_assessment_fingerprints=tuple(item.assessment_fingerprint for item in assessments),
        result=result,
    )


def assert_localized_finding_is_qualified(
    qualification: WholeBoardQualification, finding: LocalizedRepairFinding
) -> None:
    if finding.qualification_blocker_id not in qualification.blocker_ids:
        raise ValueError("localized repair finding is absent from source qualification")


def _budget_violations(
    request: LocalRepairRequest, assessment: RepairCandidateAssessment
) -> tuple[str, ...]:
    violations: list[str] = []
    x1, y1, x2, y2 = request.target_region_mm
    cx1, cy1, cx2, cy2 = assessment.change_bounds_mm
    if cx1 < x1 or cy1 < y1 or cx2 > x2 or cy2 > y2:
        violations.append("change_outside_target_region")
    if set(assessment.changed_object_ids) & set(request.immutable_object_ids):
        violations.append("immutable_object_changed")
    if set(assessment.moved_component_displacements_mm) - set(request.movable_component_references):
        violations.append("unauthorized_component_moved")
    if any(
        value > request.budget.maximum_displacement_mm
        for value in assessment.moved_component_displacements_mm.values()
    ):
        violations.append("component_displacement_budget_exceeded")
    removed_copper = set(assessment.removed_segment_ids) | set(assessment.removed_via_ids)
    if removed_copper - set(request.rip_authorized_copper_ids):
        violations.append("unauthorized_copper_ripup")
    counts = (
        (
            len(assessment.removed_segment_ids),
            request.budget.maximum_ripped_segment_count,
            "ripped_segment_budget_exceeded",
        ),
        (
            len(assessment.removed_via_ids),
            request.budget.maximum_ripped_via_count,
            "ripped_via_budget_exceeded",
        ),
        (
            len(assessment.added_segment_ids),
            request.budget.maximum_added_segment_count,
            "added_segment_budget_exceeded",
        ),
        (
            len(assessment.added_via_ids),
            request.budget.maximum_added_via_count,
            "added_via_budget_exceeded",
        ),
    )
    violations.extend(label for actual, maximum, label in counts if actual > maximum)
    return tuple(sorted(violations))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "LocalRepairExecution",
    "LocalizedRepairFinding",
    "RepairCandidateAssessment",
    "assert_localized_finding_is_qualified",
    "execute_bounded_local_repair",
]
