"""Deterministic workflow-profile conformance and deviation governance.

This authority deliberately compares semantic requirement identities and
material artifact properties.  Directory existence and filename similarity are
not evidence that a required workflow step was completed.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.semantic_ir import SemanticIrModel


def _identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def _canonical(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(sorted(_identity(value, field_name) for value in values))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must contain unique identities")
    return normalized


class DeviationLevel(StrEnum):
    ADDITION = "D0"
    REFINEMENT = "D1"
    EQUIVALENT_SUBSTITUTION = "D2"
    OMISSION = "D3"
    AUTHORITY_CHANGE = "D4"


class ApprovalKind(StrEnum):
    HUMAN = "human"
    AUTOMATION = "automation"
    AI = "ai"


class RequirementRisk(StrEnum):
    ORDINARY = "ordinary"
    SAFETY_OR_RELEASE = "safety_or_release"
    WORKFLOW_AUTHORITY = "workflow_authority"


class ConformanceDisposition(StrEnum):
    CONFORMANT = "conformant"
    CONFORMANT_WITH_WAIVERS = "conformant_with_waivers"
    NONCONFORMANT = "nonconformant"


class RequirementState(StrEnum):
    SATISFIED = "satisfied"
    SUBSTITUTED = "substituted"
    WAIVED = "waived"
    MISSING = "missing"
    INVALID = "invalid"


class ArtifactConstraint(SemanticIrModel):
    """Material properties that a satisfying artifact must preserve."""

    schema_id: Literal["pcbsmith-workflow-artifact-constraint"] = (
        "pcbsmith-workflow-artifact-constraint"
    )
    schema_version: Literal[1] = 1
    media_type: str | None = None
    side: Literal["front", "back", "both", "none"] | None = None
    mirrored: bool | None = None
    camera: str | None = None
    population: Literal["populated", "bare", "not_applicable"] | None = None
    layers_exact: tuple[str, ...] | None = None
    minimum_pixels_per_mm: float | None = Field(default=None, gt=0)
    minimum_long_edge_px: int | None = Field(default=None, ge=1)
    board_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    stage: str | None = None

    @model_validator(mode="after")
    def canonicalize(self) -> Self:
        if self.media_type is not None:
            _identity(self.media_type, "media_type")
        if self.camera is not None:
            _identity(self.camera, "camera")
        if self.stage is not None:
            _identity(self.stage, "stage")
        if self.layers_exact is not None:
            object.__setattr__(self, "layers_exact", _canonical(self.layers_exact, "layers"))
        return self


class WorkflowRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-requirement"] = "pcbsmith-workflow-requirement"
    schema_version: Literal[1] = 1
    requirement_id: str
    expected_artifact_id: str
    constraint: ArtifactConstraint
    rationale: str
    risk: RequirementRisk = RequirementRisk.ORDINARY

    @model_validator(mode="after")
    def identities_are_valid(self) -> Self:
        _identity(self.requirement_id, "requirement_id")
        _identity(self.expected_artifact_id, "expected_artifact_id")
        _identity(self.rationale, "rationale")
        return self


class WorkflowProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-profile"] = "pcbsmith-workflow-profile"
    schema_version: Literal[1] = 1
    profile_id: str
    profile_version: int = Field(ge=1)
    requirements: tuple[WorkflowRequirement, ...]

    @model_validator(mode="after")
    def profile_is_canonical(self) -> Self:
        _identity(self.profile_id, "profile_id")
        requirements = tuple(sorted(self.requirements, key=lambda item: item.requirement_id))
        if len(requirements) != len({item.requirement_id for item in requirements}):
            raise ValueError("workflow requirement identities must be unique")
        expected = tuple(item.expected_artifact_id for item in requirements)
        if len(expected) != len(set(expected)):
            raise ValueError("baseline artifact identities must satisfy only one requirement")
        object.__setattr__(self, "requirements", requirements)
        return self


class WorkflowArtifactObservation(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-artifact-observation"] = (
        "pcbsmith-workflow-artifact-observation"
    )
    schema_version: Literal[1] = 1
    artifact_id: str
    generated: bool
    media_type: str
    side: Literal["front", "back", "both", "none"] = "none"
    mirrored: bool = False
    camera: str | None = None
    population: Literal["populated", "bare", "not_applicable"] = "not_applicable"
    layers: tuple[str, ...] = ()
    pixels_per_mm: float | None = Field(default=None, gt=0)
    pixel_size: tuple[int, int] | None = None
    board_sha256: str
    stage: str
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    integrity_valid: bool = True
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def observation_is_canonical(self) -> Self:
        _identity(self.artifact_id, "artifact_id")
        _identity(self.media_type, "media_type")
        _identity(self.stage, "stage")
        if len(self.board_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.board_sha256
        ):
            raise ValueError("board_sha256 must be a lowercase SHA-256 digest")
        if self.camera is not None:
            _identity(self.camera, "camera")
        if self.pixel_size is not None and any(value < 1 for value in self.pixel_size):
            raise ValueError("pixel_size dimensions must be positive")
        object.__setattr__(self, "layers", _canonical(self.layers, "layers"))
        object.__setattr__(self, "findings", tuple(self.findings))
        return self


class DeviationApproval(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-deviation-approval"] = (
        "pcbsmith-workflow-deviation-approval"
    )
    schema_version: Literal[1] = 1
    approver_id: str
    approver_kind: ApprovalKind
    approved_on: date
    expires_on: date | None = None
    closure_condition: str | None = None

    @model_validator(mode="after")
    def approval_is_coherent(self) -> Self:
        _identity(self.approver_id, "approver_id")
        if self.expires_on is None and self.closure_condition is None:
            raise ValueError("approval requires an expiry or closure condition")
        if self.expires_on is not None and self.expires_on < self.approved_on:
            raise ValueError("approval expiry precedes its approval date")
        if self.closure_condition is not None:
            _identity(self.closure_condition, "closure_condition")
        return self


class WorkflowDeviation(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-deviation"] = "pcbsmith-workflow-deviation"
    schema_version: Literal[1] = 1
    deviation_id: str
    level: DeviationLevel
    requirement_id: str | None = None
    artifact_id: str | None = None
    reason: str
    consequence: str
    residual_risk: str
    compensating_artifact_ids: tuple[str, ...] = ()
    approval: DeviationApproval | None = None

    @model_validator(mode="after")
    def deviation_shape_matches_level(self) -> Self:
        _identity(self.deviation_id, "deviation_id")
        _identity(self.reason, "reason")
        _identity(self.consequence, "consequence")
        _identity(self.residual_risk, "residual_risk")
        if self.requirement_id is not None:
            _identity(self.requirement_id, "requirement_id")
        if self.artifact_id is not None:
            _identity(self.artifact_id, "artifact_id")
        object.__setattr__(
            self,
            "compensating_artifact_ids",
            _canonical(self.compensating_artifact_ids, "compensating_artifact_ids"),
        )
        if self.level is DeviationLevel.ADDITION:
            if self.requirement_id is not None or self.artifact_id is None:
                raise ValueError("D0 additions require an artifact and cannot target a requirement")
        elif self.level is DeviationLevel.REFINEMENT:
            if self.requirement_id is None or self.artifact_id is None:
                raise ValueError("D1 refinements require requirement and artifact identities")
        elif self.level is DeviationLevel.EQUIVALENT_SUBSTITUTION:
            if self.requirement_id is None or self.artifact_id is None:
                raise ValueError("D2 substitutions require requirement and artifact identities")
            if self.approval is None:
                raise ValueError("D2 substitutions require retained reviewer approval")
        elif self.level is DeviationLevel.OMISSION:
            if self.requirement_id is None or self.artifact_id is not None:
                raise ValueError("D3 omissions require a requirement and no substitute artifact")
            if self.approval is None:
                raise ValueError("D3 omissions require retained approval")
        elif self.level is DeviationLevel.AUTHORITY_CHANGE and self.requirement_id is None:
            raise ValueError("D4 authority changes must identify the affected requirement")
        return self


class RequirementEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-requirement-evaluation"] = (
        "pcbsmith-workflow-requirement-evaluation"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    state: RequirementState
    artifact_id: str | None = None
    deviation_id: str | None = None
    findings: tuple[str, ...] = ()


class WorkflowConformanceReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-workflow-conformance-report"] = (
        "pcbsmith-workflow-conformance-report"
    )
    schema_version: Literal[1] = 1
    profile: WorkflowProfile
    evaluated_on: date
    disposition: ConformanceDisposition
    evaluations: tuple[RequirementEvaluation, ...]
    deviations: tuple[WorkflowDeviation, ...] = ()
    supplemental_artifact_ids: tuple[str, ...] = ()
    undeclared_artifact_ids: tuple[str, ...] = ()
    prohibited_deviation_ids: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()


def evaluate_workflow_conformance(
    *,
    profile: WorkflowProfile,
    observations: tuple[WorkflowArtifactObservation, ...],
    deviations: tuple[WorkflowDeviation, ...] = (),
    evaluated_on: date,
) -> WorkflowConformanceReport:
    """Evaluate one immutable profile against current observations.

    The date is an input so waiver expiry and replay remain deterministic.
    """

    by_artifact: dict[str, WorkflowArtifactObservation] = {}
    duplicate_artifacts: set[str] = set()
    for item in observations:
        if item.artifact_id in by_artifact:
            duplicate_artifacts.add(item.artifact_id)
        by_artifact[item.artifact_id] = item
    by_requirement: dict[str, list[WorkflowDeviation]] = {}
    additions: set[str] = set()
    declared_deviation_artifacts: set[str] = set()
    prohibited: set[str] = set()
    global_findings: list[str] = []
    for deviation in deviations:
        if deviation.level is DeviationLevel.ADDITION and deviation.artifact_id is not None:
            additions.add(deviation.artifact_id)
        if deviation.artifact_id is not None:
            declared_deviation_artifacts.add(deviation.artifact_id)
        if deviation.requirement_id is not None:
            by_requirement.setdefault(deviation.requirement_id, []).append(deviation)
        if deviation.level is DeviationLevel.AUTHORITY_CHANGE:
            prohibited.add(deviation.deviation_id)
    if duplicate_artifacts:
        global_findings.append(
            "Duplicate artifact identities: " + ", ".join(sorted(duplicate_artifacts))
        )

    evaluations: list[RequirementEvaluation] = []
    expected_ids = {item.expected_artifact_id for item in profile.requirements}
    requirement_ids = {item.requirement_id for item in profile.requirements}
    unknown_deviations = sorted(
        deviation.deviation_id
        for deviation in deviations
        if deviation.requirement_id is not None
        and deviation.requirement_id not in requirement_ids
    )
    if unknown_deviations:
        global_findings.append(
            "Deviations target unknown requirements: " + ", ".join(unknown_deviations)
        )

    for requirement in profile.requirements:
        direct = by_artifact.get(requirement.expected_artifact_id)
        direct_findings = _constraint_findings(requirement.constraint, direct)
        if direct is not None and not direct_findings:
            evaluations.append(
                RequirementEvaluation(
                    requirement_id=requirement.requirement_id,
                    state=RequirementState.SATISFIED,
                    artifact_id=direct.artifact_id,
                )
            )
            continue

        candidates = by_requirement.get(requirement.requirement_id, [])
        accepted = False
        invalid_findings = list(direct_findings)
        for deviation in candidates:
            if deviation.level in {
                DeviationLevel.REFINEMENT,
                DeviationLevel.EQUIVALENT_SUBSTITUTION,
            }:
                substitute = (
                    None
                    if deviation.artifact_id is None
                    else by_artifact.get(deviation.artifact_id)
                )
                findings = _constraint_findings(requirement.constraint, substitute)
                approval_finding = _approval_finding(
                    requirement=requirement,
                    deviation=deviation,
                    evaluated_on=evaluated_on,
                    substitution=True,
                )
                if approval_finding is not None:
                    findings.append(approval_finding)
                if not findings:
                    evaluations.append(
                        RequirementEvaluation(
                            requirement_id=requirement.requirement_id,
                            state=RequirementState.SUBSTITUTED,
                            artifact_id=deviation.artifact_id,
                            deviation_id=deviation.deviation_id,
                        )
                    )
                    accepted = True
                    break
                invalid_findings.extend(findings)
            elif deviation.level is DeviationLevel.OMISSION:
                approval_finding = _approval_finding(
                    requirement=requirement,
                    deviation=deviation,
                    evaluated_on=evaluated_on,
                    substitution=False,
                )
                if approval_finding is None:
                    evaluations.append(
                        RequirementEvaluation(
                            requirement_id=requirement.requirement_id,
                            state=RequirementState.WAIVED,
                            deviation_id=deviation.deviation_id,
                            findings=(deviation.residual_risk,),
                        )
                    )
                    accepted = True
                    break
                invalid_findings.append(approval_finding)
            elif deviation.level is DeviationLevel.AUTHORITY_CHANGE:
                invalid_findings.append("D4 authority changes are prohibited in this workflow")
        if accepted:
            continue
        state = (
            RequirementState.INVALID
            if candidates or direct is not None
            else RequirementState.MISSING
        )
        if not invalid_findings:
            invalid_findings.append("Required artifact identity was not observed")
        evaluations.append(
            RequirementEvaluation(
                requirement_id=requirement.requirement_id,
                state=state,
                artifact_id=None if direct is None else direct.artifact_id,
                findings=tuple(dict.fromkeys(invalid_findings)),
            )
        )

    undeclared = sorted(
        artifact_id
        for artifact_id in by_artifact
        if artifact_id not in expected_ids and artifact_id not in declared_deviation_artifacts
    )
    if undeclared:
        global_findings.append(
            "Artifacts outside the baseline lack D0 declarations: " + ", ".join(undeclared)
        )
    failed = bool(
        duplicate_artifacts
        or prohibited
        or unknown_deviations
        or undeclared
        or any(
            item.state in {RequirementState.MISSING, RequirementState.INVALID}
            for item in evaluations
        )
    )
    waived = any(item.state is RequirementState.WAIVED for item in evaluations)
    disposition = (
        ConformanceDisposition.NONCONFORMANT
        if failed
        else (
            ConformanceDisposition.CONFORMANT_WITH_WAIVERS
            if waived
            else ConformanceDisposition.CONFORMANT
        )
    )
    return WorkflowConformanceReport(
        profile=profile,
        evaluated_on=evaluated_on,
        disposition=disposition,
        deviations=tuple(sorted(deviations, key=lambda item: item.deviation_id)),
        evaluations=tuple(evaluations),
        supplemental_artifact_ids=tuple(sorted(additions)),
        undeclared_artifact_ids=tuple(undeclared),
        prohibited_deviation_ids=tuple(sorted(prohibited)),
        findings=tuple(global_findings),
    )


def _constraint_findings(
    constraint: ArtifactConstraint,
    observation: WorkflowArtifactObservation | None,
) -> list[str]:
    if observation is None:
        return ["Required artifact identity was not observed"]
    findings: list[str] = []
    if not observation.generated:
        findings.append("Artifact file is missing")
    if not observation.integrity_valid:
        findings.append("Artifact content integrity does not match its retained record")
    exact_fields = (
        ("media_type", constraint.media_type, observation.media_type),
        ("side", constraint.side, observation.side),
        ("mirrored", constraint.mirrored, observation.mirrored),
        ("camera", constraint.camera, observation.camera),
        ("population", constraint.population, observation.population),
        ("board_sha256", constraint.board_sha256, observation.board_sha256),
        ("stage", constraint.stage, observation.stage),
    )
    for name, expected, actual in exact_fields:
        if expected is not None and actual != expected:
            findings.append(f"{name} mismatch: expected {expected!r}, observed {actual!r}")
    if constraint.layers_exact is not None and tuple(observation.layers) != tuple(
        constraint.layers_exact
    ):
        findings.append(
            f"layer mismatch: expected {constraint.layers_exact!r}, observed {observation.layers!r}"
        )
    if constraint.minimum_pixels_per_mm is not None and (
        observation.pixels_per_mm is None
        or observation.pixels_per_mm < constraint.minimum_pixels_per_mm
    ):
        findings.append(
            "physical resolution below minimum: "
            f"expected >= {constraint.minimum_pixels_per_mm}, "
            f"observed {observation.pixels_per_mm}"
        )
    if constraint.minimum_long_edge_px is not None and (
        observation.pixel_size is None
        or max(observation.pixel_size) < constraint.minimum_long_edge_px
    ):
        findings.append(
            "pixel resolution below minimum: "
            f"expected long edge >= {constraint.minimum_long_edge_px}, "
            f"observed {observation.pixel_size}"
        )
    return findings


def _approval_finding(
    *,
    requirement: WorkflowRequirement,
    deviation: WorkflowDeviation,
    evaluated_on: date,
    substitution: bool,
) -> str | None:
    approval = deviation.approval
    if deviation.level is DeviationLevel.REFINEMENT and substitution and approval is None:
        return None
    if approval is None:
        return "Deviation lacks retained approval"
    if approval.approved_on > evaluated_on:
        return "Deviation approval is dated after this evaluation"
    if approval.expires_on is not None and approval.expires_on < evaluated_on:
        return "Deviation approval has expired"
    if requirement.risk is RequirementRisk.SAFETY_OR_RELEASE and (
        approval.approver_kind is not ApprovalKind.HUMAN
    ):
        return "Safety/release deviations require human approval"
    if requirement.risk is RequirementRisk.WORKFLOW_AUTHORITY:
        return "Workflow-authority requirements cannot be waived or substituted in-version"
    return None
