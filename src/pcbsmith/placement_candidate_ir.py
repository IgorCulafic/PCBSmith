"""Engine-neutral deterministic placement-candidate IR for R5.2."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.placement_ir import (
    ComponentPose,
    PlacementBudget,
    PlacementIrModel,
    PlacementLegalizationOutcome,
    PlacementLegalizationPolicy,
    PlacementLegalizationResult,
    placement_pose_set_fingerprint,
)


def _identity(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be a canonical non-empty identity")
    return value


def _identities(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(values))
    if len(set(canonical)) != len(canonical):
        raise ValueError(f"{name} must contain unique identities")
    return tuple(_identity(value, name) for value in canonical)


def _sha256(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


class PlacementMoveKind(StrEnum):
    TRANSLATE = "translate"
    ROTATE = "rotate"
    FLIP = "flip"


class PlacementMovePolicy(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-move-policy"] = "pcbsmith-placement-move-policy"
    schema_version: Literal[1] = 1
    movable_references: tuple[str, ...] = ()
    rotatable_references: tuple[str, ...] = ()
    flippable_references: tuple[str, ...] = ()
    translation_step_mm: float = Field(gt=0)
    maximum_translation_steps: int = Field(ge=0)
    allowed_rotation_deg: tuple[float, ...] = ()
    pair_move_limit: int = Field(ge=0)
    seed: int
    generator_id: Literal["canonical-neighborhood-v1"] = "canonical-neighborhood-v1"

    @model_validator(mode="after")
    def canonicalize(self) -> Self:
        movable = _identities(self.movable_references, "movable_references")
        rotatable = _identities(self.rotatable_references, "rotatable_references")
        flippable = _identities(self.flippable_references, "flippable_references")
        rotations: list[float] = []
        for raw in self.allowed_rotation_deg:
            if not math.isfinite(raw):
                raise ValueError("allowed_rotation_deg values must be finite")
            normalized = raw % 360.0
            rotations.append(0.0 if normalized == 0.0 else normalized)
        allowed = tuple(sorted(set(rotations)))
        if rotatable and not allowed:
            raise ValueError("rotatable references require allowed_rotation_deg")
        object.__setattr__(self, "movable_references", movable)
        object.__setattr__(self, "rotatable_references", rotatable)
        object.__setattr__(self, "flippable_references", flippable)
        object.__setattr__(self, "allowed_rotation_deg", allowed)
        return self


class PlacementMoveClause(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-move-clause"] = "pcbsmith-placement-move-clause"
    schema_version: Literal[1] = 1
    reference: str
    kind: PlacementMoveKind
    delta_x_mm: float | None = None
    delta_y_mm: float | None = None
    rotation_deg: float | None = None
    side: Literal["front", "back"] | None = None

    @model_validator(mode="after")
    def exact_shape(self) -> Self:
        object.__setattr__(self, "reference", _identity(self.reference, "reference"))
        values = (self.delta_x_mm, self.delta_y_mm, self.rotation_deg)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("move values must be finite")
        if self.kind is PlacementMoveKind.TRANSLATE:
            if self.delta_x_mm is None or self.delta_y_mm is None:
                raise ValueError("translation requires both deltas")
            if (self.delta_x_mm == 0.0) == (self.delta_y_mm == 0.0):
                raise ValueError("translation must move on exactly one axis")
            if self.rotation_deg is not None or self.side is not None:
                raise ValueError("translation cannot rotate or flip")
        elif self.kind is PlacementMoveKind.ROTATE:
            if any(value is not None for value in (self.delta_x_mm, self.delta_y_mm, self.side)):
                raise ValueError("rotation contains only rotation_deg")
            if self.rotation_deg is None:
                raise ValueError("rotation requires rotation_deg")
            normalized = self.rotation_deg % 360.0
            object.__setattr__(self, "rotation_deg", 0.0 if normalized == 0.0 else normalized)
        elif (
            any(
                value is not None for value in (self.delta_x_mm, self.delta_y_mm, self.rotation_deg)
            )
            or self.side is None
        ):
            raise ValueError("flip contains only side")
        return self


class PlacementProposalKind(StrEnum):
    BASE = "base"
    SINGLE = "single"
    PAIR = "pair"


class PlacementProposalProvenance(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-proposal-provenance"] = (
        "pcbsmith-placement-proposal-provenance"
    )
    schema_version: Literal[1] = 1
    proposal_kind: PlacementProposalKind
    parent_pose_fingerprint: str | None = None
    moved_references: tuple[str, ...] = ()
    clauses: tuple[PlacementMoveClause, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        moved = _identities(self.moved_references, "moved_references")
        clauses = tuple(
            sorted(self.clauses, key=lambda item: (item.reference, item.semantic_json()))
        )
        if self.proposal_kind is PlacementProposalKind.BASE:
            if self.parent_pose_fingerprint is not None or moved or clauses:
                raise ValueError("base proposal cannot declare moves")
        else:
            if self.parent_pose_fingerprint is None:
                raise ValueError("non-base proposal requires a parent")
            _sha256(self.parent_pose_fingerprint, "parent_pose_fingerprint")
            expected = 1 if self.proposal_kind is PlacementProposalKind.SINGLE else 2
            if len(moved) != expected or len(clauses) != expected:
                raise ValueError("proposal kind has the wrong move count")
            if {clause.reference for clause in clauses} != set(moved):
                raise ValueError("clauses must exactly cover moved references")
        object.__setattr__(self, "moved_references", moved)
        object.__setattr__(self, "clauses", clauses)
        return self


class PlacementSurrogateEvidence(PlacementIrModel):
    """Opaque callback boundary; R5.3 will supply typed placement metrics."""

    schema_id: Literal["pcbsmith-placement-surrogate-boundary-evidence"] = (
        "pcbsmith-placement-surrogate-boundary-evidence"
    )
    schema_version: Literal[1] = 1
    evaluator_id: str
    evidence_fingerprint: str

    @field_validator("evaluator_id")
    @classmethod
    def evaluator_is_canonical(cls, value: str) -> str:
        return _identity(value, "evaluator_id")

    @field_validator("evidence_fingerprint")
    @classmethod
    def evidence_is_sha256(cls, value: str) -> str:
        return _sha256(value, "evidence_fingerprint")


class PlacementCandidateDisposition(StrEnum):
    SURROGATE_EVALUATED = "surrogate_evaluated"
    LEGALIZATION_REJECTED = "legalization_rejected"
    LEGALIZATION_UNVERIFIED = "legalization_unverified"
    SURROGATE_BUDGET_EXHAUSTED = "surrogate_budget_exhausted"


def placement_candidate_fingerprint(
    template_fingerprint: str,
    target_policy_fingerprint: str,
    catalog_fingerprint: str,
    profile_fingerprint: str,
    poses: tuple[ComponentPose, ...],
    move_policy: PlacementMovePolicy,
    legalization_policy: PlacementLegalizationPolicy,
) -> str:
    for name, value in (
        ("template_fingerprint", template_fingerprint),
        ("target_policy_fingerprint", target_policy_fingerprint),
        ("catalog_fingerprint", catalog_fingerprint),
        ("profile_fingerprint", profile_fingerprint),
    ):
        _sha256(value, name)
    payload = {
        "schema_id": "pcbsmith-placement-candidate",
        "schema_version": 1,
        "template_fingerprint": template_fingerprint,
        "target_policy_fingerprint": target_policy_fingerprint,
        "catalog_fingerprint": catalog_fingerprint,
        "profile_fingerprint": profile_fingerprint,
        "pose_fingerprint": placement_pose_set_fingerprint(poses),
        "move_policy_fingerprint": move_policy.semantic_fingerprint(),
        "legalization_policy_fingerprint": legalization_policy.semantic_fingerprint(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _apply_verified_provenance(
    base: tuple[ComponentPose, ...],
    provenance: PlacementProposalProvenance,
    policy: PlacementMovePolicy,
) -> tuple[ComponentPose, ...]:
    """Reproduce one candidate and verify every clause is policy-authorized."""

    pose_by_ref = {pose.reference: pose for pose in base}
    if set(provenance.moved_references) - set(pose_by_ref):
        raise ValueError("candidate provenance references an unknown base pose")
    allowed_deltas = {
        policy.translation_step_mm * step for step in range(1, policy.maximum_translation_steps + 1)
    }
    for clause in provenance.clauses:
        pose = pose_by_ref[clause.reference]
        if clause.kind is PlacementMoveKind.TRANSLATE:
            if clause.reference not in policy.movable_references:
                raise ValueError("translation provenance violates movable permissions")
            assert clause.delta_x_mm is not None and clause.delta_y_mm is not None
            distance = abs(clause.delta_x_mm or clause.delta_y_mm)
            if distance not in allowed_deltas:
                raise ValueError("translation provenance violates step policy")
            pose_by_ref[clause.reference] = ComponentPose(
                reference=pose.reference,
                x_mm=pose.x_mm + clause.delta_x_mm,
                y_mm=pose.y_mm + clause.delta_y_mm,
                rotation_deg=pose.rotation_deg,
                side=pose.side,
            )
        elif clause.kind is PlacementMoveKind.ROTATE:
            if clause.reference not in policy.rotatable_references:
                raise ValueError("rotation provenance violates rotatable permissions")
            assert clause.rotation_deg is not None
            if clause.rotation_deg not in policy.allowed_rotation_deg:
                raise ValueError("rotation provenance violates allowed angles")
            pose_by_ref[clause.reference] = ComponentPose(
                reference=pose.reference,
                x_mm=pose.x_mm,
                y_mm=pose.y_mm,
                rotation_deg=clause.rotation_deg,
                side=pose.side,
            )
        else:
            if clause.reference not in policy.flippable_references:
                raise ValueError("flip provenance violates flippable permissions")
            expected_side: Literal["front", "back"] = "back" if pose.side == "front" else "front"
            if clause.side != expected_side:
                raise ValueError("flip provenance does not toggle the base side")
            pose_by_ref[clause.reference] = ComponentPose(
                reference=pose.reference,
                x_mm=pose.x_mm,
                y_mm=pose.y_mm,
                rotation_deg=pose.rotation_deg,
                side=expected_side,
            )
    return tuple(pose_by_ref[reference] for reference in sorted(pose_by_ref))


class PlacementCandidateRecord(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-candidate-record"] = (
        "pcbsmith-placement-candidate-record"
    )
    schema_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    candidate_fingerprint: str
    probe_layout_fingerprint: str
    poses: tuple[ComponentPose, ...] = Field(min_length=1)
    provenance: PlacementProposalProvenance
    legalization_result: PlacementLegalizationResult
    disposition: PlacementCandidateDisposition
    surrogate_evidence: PlacementSurrogateEvidence | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        poses = tuple(
            ComponentPose.model_validate_json(pose.model_dump_json()) for pose in self.poses
        )
        provenance = PlacementProposalProvenance.model_validate_json(
            self.provenance.model_dump_json()
        )
        legalization = PlacementLegalizationResult.model_validate_json(
            self.legalization_result.model_dump_json()
        )
        evidence = (
            None
            if self.surrogate_evidence is None
            else PlacementSurrogateEvidence.model_validate_json(
                self.surrogate_evidence.model_dump_json()
            )
        )
        fingerprint = _sha256(self.candidate_fingerprint, "candidate_fingerprint")
        _sha256(self.probe_layout_fingerprint, "probe_layout_fingerprint")
        poses = tuple(sorted(poses, key=lambda item: item.reference))
        if self.candidate_id != fingerprint[:12]:
            raise ValueError("candidate_id must be the fingerprint prefix")
        telemetry = legalization.telemetry
        if telemetry.pose_fingerprint != placement_pose_set_fingerprint(poses):
            raise ValueError("legalization result belongs to another pose")
        if telemetry.probe_layout_fingerprint != self.probe_layout_fingerprint:
            raise ValueError("legalization result belongs to another probe")
        outcome = legalization.outcome
        if outcome is PlacementLegalizationOutcome.REJECTED:
            expected = PlacementCandidateDisposition.LEGALIZATION_REJECTED
        elif outcome is PlacementLegalizationOutcome.UNVERIFIED:
            expected = PlacementCandidateDisposition.LEGALIZATION_UNVERIFIED
        elif outcome is PlacementLegalizationOutcome.BUDGET_EXHAUSTED:
            raise ValueError("budget-exhausted legalization is not a candidate evaluation")
        elif evidence is None:
            expected = PlacementCandidateDisposition.SURROGATE_BUDGET_EXHAUSTED
        else:
            expected = PlacementCandidateDisposition.SURROGATE_EVALUATED
        if self.disposition is not expected:
            raise ValueError("candidate disposition is inconsistent")
        if (
            expected is not PlacementCandidateDisposition.SURROGATE_EVALUATED
            and evidence is not None
        ):
            raise ValueError("unexpected surrogate evidence")
        object.__setattr__(self, "poses", poses)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "legalization_result", legalization)
        object.__setattr__(self, "surrogate_evidence", evidence)
        return self


class PlacementCandidateTerminalReason(StrEnum):
    COMPLETED = "completed"
    PROPOSAL_BUDGET_EXHAUSTED = "proposal_budget_exhausted"
    LEGALIZATION_BUDGET_EXHAUSTED = "legalization_budget_exhausted"
    SURROGATE_BUDGET_EXHAUSTED = "surrogate_budget_exhausted"


class PlacementCandidateTelemetry(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-candidate-telemetry"] = (
        "pcbsmith-placement-candidate-telemetry"
    )
    schema_version: Literal[1] = 1
    template_fingerprint: str
    target_policy_fingerprint: str
    catalog_fingerprint: str
    profile_fingerprint: str
    move_policy_fingerprint: str
    legalization_policy_fingerprint: str
    budget_fingerprint: str
    proposal_limit: int = Field(ge=0)
    proposals_consumed: int = Field(ge=0)
    unique_candidates: int = Field(ge=0)
    duplicate_proposals: int = Field(ge=0)
    legalization_limit: int = Field(ge=0)
    legalization_evaluations_consumed: int = Field(ge=0)
    surrogate_limit: int = Field(ge=0)
    surrogate_evaluations_consumed: int = Field(ge=0)
    terminal_reason: PlacementCandidateTerminalReason

    @field_validator(
        "template_fingerprint",
        "target_policy_fingerprint",
        "catalog_fingerprint",
        "profile_fingerprint",
        "move_policy_fingerprint",
        "legalization_policy_fingerprint",
        "budget_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _sha256(value, info.field_name)

    @model_validator(mode="after")
    def work_is_bounded(self) -> Self:
        if self.proposals_consumed > self.proposal_limit:
            raise ValueError("proposal budget exceeded")
        if self.legalization_evaluations_consumed > self.legalization_limit:
            raise ValueError("legalization budget exceeded")
        if self.surrogate_evaluations_consumed > self.surrogate_limit:
            raise ValueError("surrogate budget exceeded")
        if self.unique_candidates != self.legalization_evaluations_consumed:
            raise ValueError("each retained candidate must be legalized once")
        accounted = self.unique_candidates + self.duplicate_proposals
        reason = self.terminal_reason
        if reason is PlacementCandidateTerminalReason.LEGALIZATION_BUDGET_EXHAUSTED:
            if self.proposals_consumed != accounted + 1:
                raise ValueError(
                    "legalization exhaustion must retain one unexecuted unique proposal"
                )
            if self.legalization_evaluations_consumed != self.legalization_limit:
                raise ValueError(
                    "legalization exhaustion requires an exhausted legalization budget"
                )
        elif self.proposals_consumed != accounted:
            raise ValueError("proposal accounting is inconsistent with terminal reason")
        if reason is PlacementCandidateTerminalReason.PROPOSAL_BUDGET_EXHAUSTED:
            if self.proposals_consumed != self.proposal_limit:
                raise ValueError("proposal exhaustion requires an exhausted proposal budget")
        elif reason is PlacementCandidateTerminalReason.SURROGATE_BUDGET_EXHAUSTED:
            if self.surrogate_evaluations_consumed != self.surrogate_limit:
                raise ValueError("surrogate exhaustion requires an exhausted surrogate budget")
            if self.unique_candidates <= self.surrogate_evaluations_consumed:
                raise ValueError(
                    "surrogate exhaustion requires one legalized unevaluated candidate"
                )
        elif reason is PlacementCandidateTerminalReason.COMPLETED:
            if self.proposals_consumed >= self.proposal_limit:
                raise ValueError("completed search must prove stream exhaustion before its limit")
        return self


class PlacementCandidateSearchResult(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-candidate-search-result"] = (
        "pcbsmith-placement-candidate-search-result"
    )
    schema_version: Literal[1] = 1
    move_policy: PlacementMovePolicy
    legalization_policy: PlacementLegalizationPolicy
    budget: PlacementBudget
    candidates: tuple[PlacementCandidateRecord, ...]
    telemetry: PlacementCandidateTelemetry

    @model_validator(mode="after")
    def coherent(self) -> Self:
        move_policy = PlacementMovePolicy.model_validate_json(self.move_policy.model_dump_json())
        legalization_policy = PlacementLegalizationPolicy.model_validate_json(
            self.legalization_policy.model_dump_json()
        )
        budget = PlacementBudget.model_validate_json(self.budget.model_dump_json())
        candidates = tuple(
            PlacementCandidateRecord.model_validate_json(candidate.model_dump_json())
            for candidate in self.candidates
        )
        telemetry = PlacementCandidateTelemetry.model_validate_json(
            self.telemetry.model_dump_json()
        )
        if telemetry.move_policy_fingerprint != move_policy.semantic_fingerprint():
            raise ValueError("move policy fingerprint is stale")
        if telemetry.legalization_policy_fingerprint != legalization_policy.semantic_fingerprint():
            raise ValueError("legalization policy fingerprint is stale")
        if telemetry.budget_fingerprint != budget.semantic_fingerprint():
            raise ValueError("budget fingerprint is stale")
        if len(candidates) != telemetry.unique_candidates:
            raise ValueError("candidate count is stale")
        fingerprints = tuple(item.candidate_fingerprint for item in candidates)
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("candidates must be fingerprint-unique")
        for index, candidate in enumerate(candidates):
            expected = placement_candidate_fingerprint(
                telemetry.template_fingerprint,
                telemetry.target_policy_fingerprint,
                telemetry.catalog_fingerprint,
                telemetry.profile_fingerprint,
                candidate.poses,
                move_policy,
                legalization_policy,
            )
            if candidate.candidate_fingerprint != expected:
                raise ValueError("candidate fingerprint is stale")
            item_telemetry = candidate.legalization_result.telemetry
            if item_telemetry.template_fingerprint != telemetry.template_fingerprint:
                raise ValueError("candidate legalization template fingerprint is stale")
            if item_telemetry.catalog_fingerprint != telemetry.catalog_fingerprint:
                raise ValueError("candidate legalization catalog fingerprint is stale")
            if item_telemetry.policy_fingerprint != telemetry.legalization_policy_fingerprint:
                raise ValueError("candidate legalization policy fingerprint is stale")
            if item_telemetry.budget_fingerprint != telemetry.budget_fingerprint:
                raise ValueError("candidate legalization budget fingerprint is stale")
            if (
                item_telemetry.legalization_evaluations_consumed_before != index
                or item_telemetry.legalization_evaluations_consumed_after != index + 1
            ):
                raise ValueError("candidate legalization work sequence is stale")
        evaluated = sum(
            item.disposition is PlacementCandidateDisposition.SURROGATE_EVALUATED
            for item in candidates
        )
        if evaluated != telemetry.surrogate_evaluations_consumed:
            raise ValueError("surrogate work count is stale")
        if candidates:
            if candidates[0].provenance.proposal_kind is not PlacementProposalKind.BASE:
                raise ValueError("base placement must be the first candidate")
            if any(
                candidate.provenance.proposal_kind is PlacementProposalKind.BASE
                for candidate in candidates[1:]
            ):
                raise ValueError("base placement may appear only once")
            base_pose_fingerprint = placement_pose_set_fingerprint(candidates[0].poses)
            if any(
                candidate.provenance.parent_pose_fingerprint != base_pose_fingerprint
                for candidate in candidates[1:]
            ):
                raise ValueError("candidate provenance has a stale base parent")
            for candidate in candidates[1:]:
                reproduced = _apply_verified_provenance(
                    candidates[0].poses,
                    candidate.provenance,
                    move_policy,
                )
                if reproduced != candidate.poses:
                    raise ValueError("candidate provenance does not reproduce its pose")
        surrogate_exhausted = tuple(
            candidate.disposition is PlacementCandidateDisposition.SURROGATE_BUDGET_EXHAUSTED
            for candidate in candidates
        )
        if telemetry.terminal_reason is PlacementCandidateTerminalReason.SURROGATE_BUDGET_EXHAUSTED:
            if not candidates or not surrogate_exhausted[-1] or any(surrogate_exhausted[:-1]):
                raise ValueError("surrogate exhaustion must occur only on the last candidate")
        elif any(surrogate_exhausted):
            raise ValueError("surrogate-exhausted candidate requires matching terminal reason")
        object.__setattr__(self, "move_policy", move_policy)
        object.__setattr__(self, "legalization_policy", legalization_policy)
        object.__setattr__(self, "budget", budget)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "telemetry", telemetry)
        return self
