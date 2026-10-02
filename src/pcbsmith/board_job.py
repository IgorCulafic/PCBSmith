"""Persistent whole-board budgets and supervised supported CLI operations.

A job is an execution record, never engineering or manufacturing approval.
The ledger detects corruption; it is not authentication against a local file editor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.execution import EXECUTION_PROFILES, SubprocessGateRunner, VerificationGate
from pcbsmith.operations.file_transaction import FileTransactionError, _project_lock, atomic_write

if TYPE_CHECKING:
    from pcbsmith.inspection_completion import InspectionCompletionRequest

_IMPLEMENTATION_ROOT = Path(__file__).parent

ROOT_ENV = "PCBSMITH_BOARD_JOB_ROOT"
TOKEN_ENV = "PCBSMITH_BOARD_JOB_TOKEN"
DEFAULT_SECONDS = {"simple": 1800, "moderate": 3600, "complex": 7200}
# Operation identity and phase are derived, never supplied as an arbitrary stage label.
CLI_OPERATIONS = {
    "asset-resolve": ("asset-resolution", "build"),
    "production-generate-board": ("placement", "build"),
    "production-placement-review": ("placement-review", "verify"),
    "production-routed-review": ("routed-review", "verify"),
    "production-component-review-repair": ("component-repair", "build"),
    "production-edit-board": ("edit", "build"),
    "production-apply-board-edit": ("apply-edit", "build"),
    "production-inspect-board": ("inspect", "verify"),
    "production-visual-inspect": ("visual-inspect", "verify"),
    "visual-review": ("visual-render", "verify"),
    "visual-complete-diagnostics": ("diagnostic-completion", "verify"),
    "production-generator-audit": ("generator-audit", "verify"),
}
MODULES = (
    "pcbsmith.cli",
    "pcbsmith.native_project",
    "pcbsmith.predesign_preparation",
    "pcbsmith.production_routing",
    "pcbsmith.laser_artwork",
)


class JobStopped(RuntimeError):
    """No new work is authorized by this job's remaining allowance."""


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class DiagnosticRecommendation(Record):
    cause: Literal["local_design", "architecture", "constraints", "evidence", "platform", "unknown"]
    progress_assessment: str = Field(min_length=1)
    root_cause_analysis: str = Field(min_length=1)
    alternatives_considered: str = Field(min_length=1)
    action: Literal["local_edit", "rebuild", "platform_work", "stop"]
    rationale: str = Field(min_length=1)
    estimated_seconds: int = Field(gt=0, le=7200)
    verification_criteria: tuple[str, ...] = Field(min_length=1)
    uncertainties: str = Field(min_length=1)
    evidence: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def substantive(self) -> Self:
        for value in (
            self.progress_assessment,
            self.root_cause_analysis,
            self.alternatives_considered,
            self.rationale,
            self.uncertainties,
            *self.verification_criteria,
        ):
            if not value.strip():
                raise ValueError("diagnostic assessment cannot contain blank answers")
        if any(
            len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
            for v in self.evidence.values()
        ):
            raise ValueError("diagnostic evidence requires SHA-256 identities")
        return self


class DiagnosticCheckpoint(Record):
    trigger: str = Field(min_length=1)
    requested_at: float
    status: Literal["pending", "reviewing", "complete", "expired"] = "pending"
    started_at: float | None = None
    deadline: float | None = None
    completed_at: float | None = None
    recommendation: DiagnosticRecommendation | None = None

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if (self.started_at is None) != (self.deadline is None):
            raise ValueError("diagnostic window is incomplete")
        if self.started_at is not None and self.deadline is not None:
            if not 0 < self.deadline - self.started_at <= 300:
                raise ValueError("diagnostic window exceeds five minutes")
        if self.status in {"reviewing", "complete"} and self.started_at is None:
            raise ValueError("diagnostic review has no start time")
        if self.status == "complete" and (
            self.recommendation is None
            or self.completed_at is None
            or self.deadline is None
            or self.completed_at > self.deadline
        ):
            raise ValueError("diagnostic completion is missing or late")
        return self


class PreNativeLayoutApproval(Record):
    """An explicit layout decision, not native or manufacturing acceptance."""

    schema_id: Literal["pcbsmith-pre-native-layout-approval-v1"]
    authorization_reference: str = Field(min_length=1)
    approved_artifacts: dict[str, str] = Field(min_length=1)


class PreNativeRecovery(Record):
    approval_file: str = Field(min_length=1)
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContinuationRequest(Record):
    predecessor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment_file: str = Field(min_length=1)
    assessment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_reference: str = Field(min_length=1)
    seconds: int = Field(gt=0, le=1800)
    reserve_seconds: int = Field(gt=0)
    evaluation_seconds: int | None = Field(
        default=None, gt=0, le=7200, exclude_if=lambda v: v is None
    )
    build_operations: tuple[
        Literal[
            "edit",
            "apply-edit",
            "routing",
            "native-repair",
            "native-preparation",
            "predesign-prepare",
            "predesign-approve",
            "predesign-refresh",
            "predesign-reapprove",
            "placement",
        ],
        ...,
    ]
    pre_native_recovery: PreNativeRecovery | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    native_preparation_input_retry: str | None = Field(default=None, exclude_if=lambda v: v is None)
    blocker_resolution: str | None = None
    resolved_evidence: dict[str, str] = Field(default_factory=dict)
    retry_failed_operations: dict[str, str] = Field(default_factory=dict)
    retrospective_diagnostic: bool = Field(default=False, exclude_if=lambda v: not v)
    edit_retry_request: str | None = Field(default=None, exclude_if=lambda v: v is None)
    local_completion_board: str | None = Field(default=None, exclude_if=lambda v: v is None)
    placement_followup_plan: str | None = Field(default=None, exclude_if=lambda v: v is None)
    final_render_plan: str | None = Field(default=None, exclude_if=lambda v: v is None)
    routing_backend_config: str | None = Field(default=None, exclude_if=lambda v: v is None)
    routing_attempt_limit: Literal[3, 4, 5] = Field(default=3, exclude_if=lambda v: v == 3)

    routing_adapter_repair_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", exclude_if=lambda v: v is None
    )

    routing_preflight_failure_token: str | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if not self.authorization_reference.strip():
            raise ValueError("explicit user authorization reference is required")
        preparation = {"native-preparation", "predesign-prepare"}
        input_retry = self.native_preparation_input_retry
        if input_retry is not None and (
            self.pre_native_recovery is None
            or self.retry_failed_operations != {"native-preparation": input_retry}
        ):
            raise ValueError("native input retry requires its exact pre-native scope")
        if self.pre_native_recovery is not None:
            required = preparation | {"predesign-approve", "placement"}
            allowed = required | {"routing", "edit", "apply-edit", "native-repair"}
            if (
                not required <= set(self.build_operations) <= allowed
                or (self.retry_failed_operations and input_retry is None)
                or self.retrospective_diagnostic
                or self.blocker_resolution is None
                or self.evaluation_seconds is None
            ):
                raise ValueError(
                    "pre-native recovery requires bounded initial stages and resolution"
                )
        elif preparation & set(self.build_operations):
            raise ValueError("preparation recovery requires explicit pre-native scope")
        if not self.seconds * 0.2 <= self.reserve_seconds < self.seconds:
            raise ValueError("continuation must reserve at least twenty percent for verification")
        if self.blocker_resolution is not None:
            if not self.blocker_resolution.strip() or not self.resolved_evidence:
                raise ValueError("recovery requires a substantive resolution and retained evidence")
        elif self.resolved_evidence:
            raise ValueError("resolution evidence requires a declared blocker resolution")
        if any(
            len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
            for v in self.resolved_evidence.values()
        ):
            raise ValueError("resolution evidence requires SHA-256 identities")
        if self.retry_failed_operations and (
            not self.blocker_resolution
            or not set(self.retry_failed_operations)
            <= (
                {"routing", "edit", "native-repair", "placement"}
                | ({"native-preparation"} if input_retry else set())
            )
            or not set(self.retry_failed_operations) <= set(self.build_operations)
        ):
            raise ValueError("explicit retry requires resolved recovery and declared operation")
        if ("edit" in self.retry_failed_operations) != (self.edit_retry_request is not None):
            raise ValueError("edit retry requires an exact corrected request")
        if self.local_completion_board is not None and (
            not self.blocker_resolution
            or self.local_completion_board not in self.resolved_evidence
            or set(self.build_operations) != {"edit", "apply-edit"}
            or self.retry_failed_operations
        ):
            raise ValueError(
                "local completion requires exact native source and one edit/apply scope"
            )
        if self.routing_adapter_repair_sha256 is not None and (
            set(self.build_operations) != {"routing"}
            or set(self.retry_failed_operations) != {"routing"}
            or self.routing_adapter_repair_sha256 not in self.resolved_evidence.values()
            or self.routing_attempt_limit != 3
        ):
            raise ValueError("adapter repair requires one exact evidenced routing retry")
        if self.routing_backend_config is not None and (
            self.routing_attempt_limit != 4
            or set(self.build_operations) != {"routing"}
            or set(self.retry_failed_operations) != {"routing"}
            or self.routing_backend_config not in self.resolved_evidence
        ):
            raise ValueError("backend transition requires one exact fourth routing scope")
        if self.routing_attempt_limit >= 4 and (
            not self.blocker_resolution or "routing" not in self.retry_failed_operations
        ):
            raise ValueError("fourth routing attempt requires explicit diagnosed recovery")
        if (self.routing_attempt_limit == 5) != (self.routing_preflight_failure_token is not None):
            raise ValueError("fifth invocation requires a proven preflight-only failure")
        if self.routing_preflight_failure_token is not None and (
            self.retry_failed_operations.get("routing") != self.routing_preflight_failure_token
        ):
            raise ValueError("preflight recovery must bind its routing retry token")
        if not self.build_operations and not self.blocker_resolution:
            raise ValueError("verification-only continuation requires resolved-blocker evidence")
        if self.final_render_plan is not None and (
            not self.blocker_resolution
            or self.final_render_plan not in self.resolved_evidence
            or self.build_operations
            or self.retry_failed_operations
        ):
            raise ValueError("final render completion requires a bound verification-only scope")
        if self.placement_followup_plan is not None and (
            not self.blocker_resolution
            or self.placement_followup_plan not in self.resolved_evidence
            or not {"edit", "apply-edit"} <= set(self.build_operations)
            or set(self.build_operations)
            - {"edit", "apply-edit", "predesign-refresh", "predesign-reapprove", "routing"}
            or set(self.retry_failed_operations) - {"routing"}
        ):
            raise ValueError("placement follow-up requires an exact bounded pose-only scope")
        if len(set(self.build_operations)) != len(self.build_operations):
            raise ValueError("duplicate continuation operations")
        return self


def _validate_routing_adapter_repair(root: Path, request: ContinuationRequest) -> None:
    """Permit only an explicitly diagnosed, hash-bound adapter repair, never a budget retry."""
    from pcbsmith.operations.file_transaction import project_path

    assessment = project_path(root, request.assessment_file).read_bytes()
    if hashlib.sha256(assessment).hexdigest() != request.assessment_sha256:
        raise JobStopped("adapter repair assessment changed")
    recommendation = DiagnosticRecommendation.model_validate_json(assessment)
    if recommendation.cause != "platform" or recommendation.action != "platform_work":
        raise JobStopped("adapter repair requires a diagnosed platform integration failure")
    adapter = _IMPLEMENTATION_ROOT / "kicad/freerouting_production.py"
    if hashlib.sha256(adapter.read_bytes()).hexdigest() != request.routing_adapter_repair_sha256:
        raise JobStopped("qualified routing adapter changed")
    for relative, expected in request.resolved_evidence.items():
        if hashlib.sha256(project_path(root, relative).read_bytes()).hexdigest() != expected:
            raise JobStopped("adapter repair resolution evidence changed")


class Continuation(Record):
    request: ContinuationRequest
    started_at: float
    deadline: float
    prior_attempt_count: int = Field(ge=0)
    diagnostic: DiagnosticCheckpoint | None = None

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if (
            abs(
                self.deadline
                - self.started_at
                - self.request.seconds
                - (self.request.evaluation_seconds or 0)
            )
            > 0.001
        ):
            raise ValueError("inconsistent continuation deadline")
        if self.diagnostic and self.diagnostic.deadline is not None:
            if self.diagnostic.deadline > self.deadline - self.request.reserve_seconds:
                raise ValueError("continuation diagnostic consumes verification reserve")
        return self


class Attempt(Record):
    routing_design_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", exclude_if=lambda v: v is None
    )
    token: str
    operation: str
    phase: Literal["build", "verify"]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    command: tuple[str, ...]
    cycle: int = Field(ge=0, le=2)
    started_at: float
    ended_at: float | None = Field(default=None, exclude_if=lambda v: v is None)
    supervisor_pid: int
    launcher_pid: int | None = None
    worker_pid: int | None = None
    status: Literal["running", "passed", "failed", "stopped"] = "running"
    failure_signature: str | None = None
    result: dict[str, object] | None = None


NEW_JOB_ROUTING_POLICY = "freerouting-one-retry-v1"


class JobState(Record):
    routing_policy: Literal["freerouting-one-retry-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    schema_version: Literal[1] = 1
    job_id: str
    root: str
    complexity: Literal["simple", "moderate", "complex"]
    rationale: str = Field(min_length=1)
    started_at: float
    deadline: float
    limit_seconds: float = Field(gt=0, le=7200)
    reserve_fraction: float = Field(ge=0.2, lt=1)
    evaluation_seconds: float | None = Field(
        default=None, gt=0, le=7200, exclude_if=lambda v: v is None
    )
    last_seen: float
    finished_at: float | None = Field(default=None, exclude_if=lambda v: v is None)
    cycle: int = Field(ge=0, le=2)
    escalations: int = Field(ge=0, le=1)
    status: Literal["active", "stopped", "finished"] = "active"
    reason: str = ""
    stop_kind: Literal[
        "", "deadline", "cancelled", "interrupted", "repeated_failure", "clock", "finished"
    ] = ""
    events: list[dict[str, object]] = Field(default_factory=list)
    attempts: list[Attempt] = Field(default_factory=list)
    corrections: list[dict[str, object]] = Field(default_factory=list)
    diagnostic: DiagnosticCheckpoint | None = None
    continuation: Continuation | None = None
    continuation_history: list[Continuation] = Field(default_factory=list)

    @property
    def active_evaluation_seconds(self) -> float | None:
        return (
            self.continuation.request.evaluation_seconds
            if self.continuation
            else self.evaluation_seconds
        )

    @property
    def active_execution_seconds(self) -> float:
        return self.continuation.request.seconds if self.continuation else self.limit_seconds

    def timing_usage(self, now: float) -> dict[str, float | str]:
        """Disjoint wall-time accounting; idle/preparation/review time is evaluation.

        Only a contained supported operation owns execution time. No caller can
        relabel stages or pause a clock. Resume and output directories grant no time.
        """
        if self.finished_at is not None:
            now = min(now, self.finished_at)
        start = self.continuation.started_at if self.continuation else self.started_at
        first = self.continuation.prior_attempt_count if self.continuation else 0
        elapsed = max(0.0, now - start)
        execution = sum(
            max(0.0, min(now, a.ended_at or now) - a.started_at) for a in self.attempts[first:]
        )
        return {
            "mode": "separate" if self.active_evaluation_seconds is not None else "legacy_wall",
            "scope_wall_seconds": elapsed,
            "total_wall_seconds": max(0.0, now - self.started_at),
            "execution_seconds": execution,
            "evaluation_seconds": max(0.0, elapsed - execution),
        }

    @property
    def active_deadline(self) -> float:
        return self.continuation.deadline if self.continuation else self.deadline

    @property
    def reserve_seconds(self) -> float:
        return (
            self.continuation.request.reserve_seconds
            if self.continuation
            else self.limit_seconds * self.reserve_fraction
        )

    @property
    def active_diagnostic(self) -> DiagnosticCheckpoint | None:
        return self.continuation.diagnostic if self.continuation else self.diagnostic

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.continuation_history and self.continuation is None:
            raise ValueError("continuation history requires an active/latest record")
        scopes = [*self.continuation_history, *([self.continuation] if self.continuation else [])]
        for index, c in enumerate(scopes):
            end = (
                scopes[index + 1].prior_attempt_count
                if index + 1 < len(scopes)
                else len(self.attempts)
            )
            if c.started_at < self.started_at or not c.prior_attempt_count <= end <= len(
                self.attempts
            ):
                raise ValueError("inconsistent continuation history")
            if index and c.started_at < scopes[index - 1].started_at:
                raise ValueError("continuation history runs backwards")
            added = self.attempts[c.prior_attempt_count : end]
            build_attempts = [a for a in added if a.phase == "build"]
            builds = [a.operation for a in build_attempts]
            repeated_invalid = False
            for operation in set(builds):
                attempts = [a for a in build_attempts if a.operation == operation]
                if len(attempts) > 1 and not (
                    len(attempts) == 2
                    and attempts[0].status == "failed"
                    and c.request.retry_failed_operations.get(operation) == attempts[0].token
                ):
                    repeated_invalid = True
            if repeated_invalid or any(
                operation not in c.request.build_operations for operation in builds
            ):
                raise ValueError("continuation exceeds explicit operation scope")
        if (
            abs(
                self.deadline
                - self.started_at
                - self.limit_seconds
                - (self.evaluation_seconds or 0)
            )
            > 0.001
        ):
            raise ValueError("inconsistent job deadline")
        if self.limit_seconds > DEFAULT_SECONDS[self.complexity]:
            raise ValueError("job exceeds its declared complexity allowance")
        if self.diagnostic and self.diagnostic.deadline is not None:
            reserve_at = self.deadline - self.limit_seconds * self.reserve_fraction
            if self.diagnostic.deadline > reserve_at and not (
                self.status == "stopped" and self.stop_kind == "deadline"
            ):
                raise ValueError("diagnostic consumes verification reserve")
        if self.last_seen < self.started_at or self.cycle != len(self.corrections):
            raise ValueError("inconsistent clock/correction history")
        if sum(a.status == "running" for a in self.attempts) > 1:
            raise ValueError("multiple active attempts")
        first = self.continuation.prior_attempt_count if self.continuation else 0
        if self.active_evaluation_seconds is not None:
            previous_end = self.continuation.started_at if self.continuation else self.started_at
            for attempt in self.attempts[first:]:
                if attempt.started_at < previous_end:
                    raise ValueError("overlapping execution timing")
                if attempt.status == "running":
                    if attempt.ended_at is not None:
                        raise ValueError("running attempt has an end timestamp")
                    previous_end = self.last_seen
                else:
                    if attempt.ended_at is None or attempt.ended_at < attempt.started_at:
                        raise ValueError("completed execution timing is missing or inconsistent")
                    previous_end = attempt.ended_at
        if any(a.cycle > self.cycle for a in self.attempts):
            raise ValueError("attempt belongs to a future correction")
        seen: dict[tuple[str, int], Attempt] = {}
        for index, attempt in enumerate(self.attempts):
            if attempt.phase != "build":
                continue
            key = (attempt.operation, attempt.cycle)
            previous = seen.get(key)
            if previous is not None:
                scope = next((c for c in reversed(scopes) if c.prior_attempt_count <= index), None)
                explicit_retry = (
                    scope is not None
                    and previous.status == "failed"
                    and scope.request.retry_failed_operations.get(attempt.operation)
                    == previous.token
                    and bool(scope.request.blocker_resolution)
                )
                placement_followup = (
                    scope is not None
                    and scope.request.placement_followup_plan is not None
                    and attempt.operation
                    in {"edit", "apply-edit", "predesign-refresh", "predesign-reapprove"}
                    and previous in self.attempts[: scope.prior_attempt_count]
                )
                if not explicit_retry and not placement_followup:
                    raise ValueError("duplicate build operation in one correction cycle")
            seen[key] = attempt
        routing_limit = (
            2
            if self.routing_policy
            else max((c.request.routing_attempt_limit for c in scopes), default=3)
        )
        final_scopes = [c for c in scopes if c.request.final_render_plan is not None]
        if len(final_scopes) > 1:
            raise ValueError("final render completion is available only once")
        if final_scopes:
            completion = final_scopes[0]
            before = self.attempts[: completion.prior_attempt_count]
            renders = [a for a in before if a.operation == "visual-render"]
            after = [
                a
                for a in self.attempts[completion.prior_attempt_count :]
                if a.operation == "visual-render"
            ]
            if (
                len(renders) != 3
                or any(
                    a.status != "passed" or not _visual_stage(a.command, "placement")
                    for a in renders
                )
                or len(after) > 1
                or any(a.phase != "verify" or not _visual_stage(a.command, "final") for a in after)
            ):
                raise ValueError("final render completion exceeds its exact stage scope")
        if any(
            sum(b.operation == a.operation for b in self.attempts)
            > (
                routing_limit
                if a.operation == "routing"
                else 4
                if a.operation == "visual-render" and final_scopes
                else 3
            )
            for a in self.attempts
        ):
            raise ValueError("operation exceeds its total attempt allowance")
        return self


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class BoardJob:
    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = root.resolve()
        self.path = self.root / ".pcbsmith" / "board-job.json"
        self.clock = clock
        self.monotonic = monotonic
        self.anchor_wall = clock()
        self.anchor_mono = monotonic()

    def authorize_inspection_completion(
        self, request: InspectionCompletionRequest
    ) -> dict[str, Any]:
        from pcbsmith.inspection_completion import authorize

        return authorize(self, request)

    def complete_inspection(
        self, decisions: dict[str, Any], resume_failure_sha256: str | None = None
    ) -> dict[str, Any]:
        from pcbsmith.inspection_completion import complete

        return complete(self, decisions, resume_failure_sha256)

    def _now(self) -> float:
        return max(self.clock(), self.anchor_wall + self.monotonic() - self.anchor_mono)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        # Parent monitoring and worker entry briefly contend on the same record.
        # Reuse the project OS lock, with a bounded wait instead of a false stop.
        until = time.monotonic() + 0.5
        with ExitStack() as stack:
            while True:
                try:
                    stack.enter_context(_project_lock(self.root))
                    break
                except FileTransactionError:
                    if time.monotonic() >= until:
                        raise JobStopped("job ledger lock remained busy") from None
                    time.sleep(0.01)
            yield

    def _save(self, state: JobState) -> None:
        value = state.model_dump(mode="json")
        JobState.model_validate(value)
        atomic_write(
            self.path,
            (json.dumps({"sha256": _digest(value), "state": value}, indent=2) + "\n").encode(),
        )

    @contextmanager
    def _access(self) -> Iterator[JobState]:
        if not self.path.is_file():
            raise JobStopped(
                "Missing board job; start once in the stable workspace before preparation"
            )
        with self._locked():
            try:
                envelope = json.loads(self.path.read_text(encoding="utf-8"))
                if (
                    set(envelope) != {"sha256", "state"}
                    or _digest(envelope["state"]) != envelope["sha256"]
                ):
                    raise ValueError("job integrity mismatch")
                state = JobState.model_validate(envelope["state"])
                if state.root != str(self.root):
                    raise ValueError("job copied to another root")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise JobStopped(f"Invalid job ledger; refusing work: {exc}") from exc
            try:
                yield state
            finally:
                self._save(state)

    def start(
        self,
        *,
        complexity: str,
        rationale: str,
        seconds: float | None = None,
        evaluation_seconds: float | None = None,
    ) -> JobState:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._locked():
            if self.path.exists():
                raise JobStopped("Job already exists; attempts/resume cannot reset it")
            now = self._now()
            limit = DEFAULT_SECONDS[complexity] if seconds is None else seconds
            state = JobState(
                routing_policy=NEW_JOB_ROUTING_POLICY,
                job_id=uuid.uuid4().hex,
                root=str(self.root),
                complexity=complexity,
                rationale=rationale,
                started_at=now,
                deadline=now + limit + (evaluation_seconds or 0),
                evaluation_seconds=evaluation_seconds,
                limit_seconds=limit,
                reserve_fraction=0.2,
                last_seen=now,
                cycle=0,
                escalations=0,
            )
            self._save(state)
            return state

    def continue_authorized(self, request: ContinuationRequest) -> None:
        """Record an explicit finite allowance, retaining all original limits/history.

        Authorization is an operator assertion, not an authentication mechanism.
        No generic resume, diagnosis or worker can call this control implicitly.
        """
        from pcbsmith.operations.file_transaction import project_path

        with self._locked():
            raw = self.path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != request.predecessor_sha256:
                raise JobStopped("continuation predecessor changed")
            envelope = json.loads(raw)
            if _digest(envelope["state"]) != envelope["sha256"]:
                raise JobStopped("continuation predecessor integrity mismatch")
            state = JobState.model_validate(envelope["state"])
            if state.root != str(self.root):
                raise JobStopped("job copied to another root")
            if state.continuation is not None:
                if request.blocker_resolution is None:
                    raise JobStopped(
                        "one continuation only without an explicit resolved-blocker decision"
                    )
                previous_scope = state.continuation
                if previous_scope.diagnostic is None or (
                    previous_scope.diagnostic.status != "complete"
                    and not (
                        request.retrospective_diagnostic
                        and previous_scope.diagnostic.deadline is not None
                        and self._now() >= previous_scope.diagnostic.deadline
                    )
                ):
                    raise JobStopped("resolved-blocker recovery requires a completed diagnostic")
                used_authorizations = [
                    c.request.authorization_reference
                    for c in [*state.continuation_history, previous_scope]
                ]
                if request.authorization_reference in used_authorizations:
                    raise JobStopped("recovery requires a new explicit user authorization")
            elif request.blocker_resolution is not None:
                if state.diagnostic is None or state.diagnostic.status != "complete":
                    raise JobStopped("resolved-blocker recovery requires a completed diagnostic")
            if request.blocker_resolution is not None:
                for relative, expected in request.resolved_evidence.items():
                    if (
                        hashlib.sha256(project_path(self.root, relative).read_bytes()).hexdigest()
                        != expected
                    ):
                        raise JobStopped("blocker resolution evidence changed")
                for operation, token in request.retry_failed_operations.items():
                    previous_attempts = [
                        a
                        for a in state.attempts
                        if a.operation == operation
                        or (operation == "native-repair" and "--native-repair" in a.command)
                    ]
                    if (
                        not previous_attempts
                        or previous_attempts[-1].token != token
                        or previous_attempts[-1].status != "failed"
                    ):
                        raise JobStopped("explicit retry must bind the latest failed operation")
                    if operation == "edit":
                        _validate_edit_input_retry(self.root, previous_attempts[-1], request)
                    if operation == "routing" and request.routing_attempt_limit == 5:
                        failed = previous_attempts[-1]
                        args = failed.command
                        output = Path(args[args.index("--output") + 1]).resolve()
                        log = (
                            self.root
                            / ".pcbsmith/job-runs"
                            / failed.token
                            / "logs/routing.stderr.txt"
                        )
                        relative = log.relative_to(self.root).as_posix()
                        if (
                            output.exists()
                            or not output.is_relative_to(self.root)
                            or request.resolved_evidence.get(relative)
                            != hashlib.sha256(log.read_bytes()).hexdigest()
                            or not log.read_text(encoding="utf-8")
                            .strip()
                            .endswith(
                                "ValueError: route order must cover every routable net exactly once"
                            )
                        ):
                            raise JobStopped(
                                "fifth invocation requires an unchanged preflight-only failure"
                            )
                    limit = request.routing_attempt_limit if operation == "routing" else 3
                    if len(previous_attempts) >= limit:
                        raise JobStopped(
                            "explicit retry cannot exceed lifetime operation allowance"
                        )
            if state.status == "finished" or state.stop_kind == "clock":
                raise JobStopped("finished or clock-inconsistent job cannot continue")
            if any(a.status == "running" for a in state.attempts):
                raise JobStopped("settle the active worker before continuation")
            now = self._now()
            if self.clock() < state.last_seen - 1:
                raise JobStopped("clock moved backwards")
            if state.status == "active" and now < state.active_deadline:
                raise JobStopped("stop the current allowance before requesting continuation")
            assessment = project_path(self.root, request.assessment_file).read_bytes()
            if hashlib.sha256(assessment).hexdigest() != request.assessment_sha256:
                raise JobStopped("continuation assessment changed")
            recommendation = DiagnosticRecommendation.model_validate_json(assessment)
            if request.blocker_resolution is not None:
                diagnostic = state.active_diagnostic
                if diagnostic is None or (
                    not request.retrospective_diagnostic
                    and diagnostic.recommendation != recommendation
                ):
                    raise JobStopped("recovery assessment differs from completed diagnostic")
            if request.routing_adapter_repair_sha256 is not None:
                _validate_routing_adapter_repair(self.root, request)
            if request.placement_followup_plan is not None:
                _validate_placement_followup(self.root, state.attempts, request)
            if request.final_render_plan is not None:
                if any(
                    c.request.final_render_plan is not None
                    for c in [
                        *state.continuation_history,
                        *([state.continuation] if state.continuation else []),
                    ]
                ):
                    raise JobStopped("final render completion is available only once")
                _validate_final_render(self.root, state.attempts, request)
            # Reapproval refreshes a checked existing-board revision; it is not
            # first-time preparation/placement in this stable revision job.
            if "predesign-reapprove" in request.build_operations:
                revision_stages = set(request.build_operations) | {
                    a.operation for a in state.attempts if a.status == "passed"
                }
                if not {"edit", "predesign-refresh"} <= revision_stages:
                    raise JobStopped("revision reapproval requires an edit and refreshed inputs")
            approval_operations = {"predesign-approve"}
            unstarted = set(request.build_operations) & (approval_operations | {"placement"})
            if request.pre_native_recovery is not None:
                _validate_pre_native_recovery(self.root, state, request, recommendation)
            elif unstarted:
                if not request.blocker_resolution or recommendation.cause != "platform":
                    raise JobStopped(
                        "unstarted-stage recovery requires a diagnosed platform blocker"
                    )
                if any(
                    a.operation == "placement" or a.operation in unstarted for a in state.attempts
                ):
                    raise JobStopped("unstarted-stage recovery cannot repeat an attempted stage")
                passed = {a.operation for a in state.attempts if a.status == "passed"}
                if not {"native-preparation", "predesign-prepare"} <= passed:
                    raise JobStopped("unstarted-stage recovery requires retained prepared inputs")
                if "placement" in unstarted and not (
                    approval_operations & unstarted or approval_operations & passed
                ):
                    raise JobStopped("initial placement still requires predesign approval")
            allowed_actions = (
                {"platform_work", "local_edit"} if request.blocker_resolution else {"local_edit"}
            )
            stopped_before_placement = bool(unstarted) and recommendation.action == "stop"
            backend_transition = request.routing_backend_config is not None
            if backend_transition:
                _validate_routing_backend_transition(self.root, state.attempts, request)
            local_completion = request.local_completion_board is not None
            if local_completion:
                assert request.local_completion_board is not None
                if any(a.operation in {"edit", "apply-edit"} for a in state.attempts):
                    raise JobStopped("local completion cannot renew an existing edit")
                board = project_path(self.root, request.local_completion_board)
                if board.suffix != ".kicad_pcb" or not board.is_file():
                    raise JobStopped("local completion requires a retained native board")
            if (
                recommendation.action not in allowed_actions
                and not stopped_before_placement
                and not backend_transition
                and not local_completion
            ):
                raise JobStopped("continuation action does not match the declared recovery scope")
            for relative, expected in recommendation.evidence.items():
                actual = hashlib.sha256(project_path(self.root, relative).read_bytes()).hexdigest()
                if actual != expected:
                    raise JobStopped("continuation diagnostic evidence changed")
            if request.retrospective_diagnostic:
                if request.build_operations or request.retry_failed_operations:
                    raise JobStopped(
                        "retrospective recovery permits verification/retained repair only"
                    )
                if (
                    state.active_diagnostic is None
                    or state.active_diagnostic.deadline is None
                    or now < state.active_diagnostic.deadline
                ):
                    raise JobStopped("retrospective recovery requires an expired diagnostic")
            previous = (
                self.root
                / ".pcbsmith"
                / (
                    "continuation-predecessor.json"
                    if state.continuation is None
                    else f"continuation-predecessor-{len(state.continuation_history) + 2}.json"
                )
            )
            if previous.exists() and previous.read_bytes() != raw:
                raise JobStopped("retained continuation predecessor conflicts")
            atomic_write(previous, raw)
            now = self._now()
            payload = state.model_dump()
            if state.continuation is not None:
                payload["continuation_history"].append(state.continuation.model_dump())
            payload.update(
                status="active",
                stop_kind="",
                reason="",
                last_seen=now,
                continuation=Continuation(
                    request=request,
                    started_at=now,
                    deadline=now + request.seconds + (request.evaluation_seconds or 0),
                    prior_attempt_count=len(state.attempts),
                ).model_dump(),
            )
            state = JobState.model_validate(payload)
            state.events.append(
                {
                    "event": "explicit_continuation",
                    "at": now,
                    "authorization_reference": request.authorization_reference,
                    "original_deadline": state.deadline,
                    "extra_deadline": state.active_deadline,
                    "original_cycle": state.cycle,
                    "additional_correction_cycles": 0,
                }
            )
            self._save(state)

    def _check(self, state: JobState, *, phase: str = "verify") -> float:
        if state.status == "finished":
            raise JobStopped(state.reason or "finished")
        now = self._now()
        if self.clock() < state.last_seen - 1:
            state.status, state.reason = "stopped", "clock moved backwards"
            state.stop_kind = "clock"
        state.last_seen = max(state.last_seen, now)
        if state.active_evaluation_seconds is not None:
            usage = state.timing_usage(now)
            if float(usage["execution_seconds"]) >= state.active_execution_seconds:
                state.status, state.reason = "stopped", "execution allowance exhausted"
                state.stop_kind = "deadline"
            elif float(usage["evaluation_seconds"]) >= state.active_evaluation_seconds:
                state.status, state.reason = "stopped", "evaluation allowance exhausted"
                state.stop_kind = "deadline"
        if now >= state.active_deadline:
            state.status, state.reason = "stopped", "whole-job deadline exhausted"
            state.stop_kind = "deadline"
        if state.status != "active":
            raise JobStopped(state.reason or state.status)
        if state.active_diagnostic is not None:
            d = state.active_diagnostic
            if d.status == "reviewing" and d.deadline is not None and now >= d.deadline:
                d.status = "expired"
            if phase == "build":
                raise JobStopped("diagnostic checkpoint required; recommendation grants no retries")
        remaining = state.active_deadline - now
        if state.active_evaluation_seconds is not None:
            remaining = min(
                remaining,
                state.active_execution_seconds
                - float(state.timing_usage(now)["execution_seconds"]),
            )
        if phase == "build" and remaining <= state.reserve_seconds:
            raise JobStopped("verification reserve reached; no new build/correction work")
        return remaining

    def snapshot(self) -> JobState:
        with self._access() as state:
            try:
                self._check(state)
            except JobStopped:
                pass
            return state.model_copy(deep=True)

    def correction(self, *, reason: str, change: str, escalation: bool = False) -> None:
        if not reason.strip() or not change.strip():
            raise ValueError("correction requires diagnosis and intended effective change")
        with self._access() as state:
            self._check(state, phase="build")
            if any(a.status == "running" for a in state.attempts):
                raise JobStopped("an attempt is still running")
            if state.continuation or state.cycle == 2 or (escalation and state.escalations == 1):
                self._request_diagnostic(state, "correction/strategy allowance exhausted")
                raise JobStopped("correction/strategy allowance exhausted; diagnostic required")
            if not any(a.cycle == state.cycle for a in state.attempts):
                raise JobStopped("cannot consume empty correction cycles")
            # Update together because cycle/history consistency is validated on assignment.
            state.corrections.append(
                {"at": self._now(), "reason": reason, "change": change, "escalation": escalation}
            )
            state.cycle += 1
            state.escalations += int(escalation)

    def authorize_local_correction(
        self, authorization_reference: str, evidence: dict[str, str]
    ) -> None:
        """Add one edit/apply pair to an active scope, without new time or attempts.

        This records explicit user-authorized completion work omitted from the
        original operation list. It cannot renew an exhausted/diagnostic scope.
        """
        from pcbsmith.operations.file_transaction import project_path

        if not authorization_reference.strip() or not evidence:
            raise ValueError("local correction requires authorization and source evidence")
        with self._access() as state:
            self._check(state, phase="build")
            if state.continuation is None or any(a.status == "running" for a in state.attempts):
                raise JobStopped("local correction requires an idle active continuation")
            if any(a.operation in {"edit", "apply-edit"} for a in state.attempts):
                raise JobStopped("local correction cannot renew previously attempted edits")
            proof = self.root / ".pcbsmith/local-correction-predecessor.json"
            if proof.exists():
                raise JobStopped("local correction scope was already added")
            for relative, expected in evidence.items():
                if (
                    hashlib.sha256(project_path(self.root, relative).read_bytes()).hexdigest()
                    != expected
                ):
                    raise JobStopped("local correction evidence changed")
            request = state.continuation.request.model_dump()
            request["build_operations"] = tuple(
                dict.fromkeys((*state.continuation.request.build_operations, "edit", "apply-edit"))
            )
            validated = ContinuationRequest.model_validate(request)
            atomic_write(proof, self.path.read_bytes())
            state.continuation.request = validated
            state.events.append(
                {
                    "event": "local_correction_scope_added",
                    "at": self._now(),
                    "authorization_reference": authorization_reference,
                    "evidence": evidence,
                    "extra_seconds": 0,
                    "additional_correction_cycles": 0,
                }
            )

    def authorize_annotation_completion(
        self, authorization_reference: str, request_file: str
    ) -> None:
        """Authorize one source-bound label-only closure; no new time or routing scope.

        The original failed edit and completed diagnostic are retained. A native
        electrically complete candidate with only silkscreen findings is required.
        """
        from pcbsmith.operations.file_transaction import project_path

        if not authorization_reference.strip():
            raise ValueError("Annotation completion requires explicit user authorization")
        with self._access() as state:
            self._check(state)
            c = state.continuation
            if c is None or c.diagnostic is None or c.diagnostic.status != "complete":
                raise JobStopped("Annotation completion requires a completed diagnostic")
            if any(a.status == "running" for a in state.attempts):
                raise JobStopped("A worker is still running")
            previous = [a for a in state.attempts if a.operation == "edit"]
            if len(previous) != 1 or previous[0].status != "failed":
                raise JobStopped("Annotation completion permits only one retained first edit")
            proof = self.root / ".pcbsmith/annotation-completion-predecessor.json"
            if proof.exists():
                raise JobStopped("Annotation completion already authorized")
            path = project_path(self.root, request_file)
            old = previous[0]
            output = Path(old.command[old.command.index("--output") + 1]).resolve()
            payload = c.request.model_dump()
            payload.update(
                local_completion_board=None,
                retry_failed_operations={"edit": old.token},
                edit_retry_request=request_file,
            )
            evidence = dict(payload["resolved_evidence"])
            for item in [
                path,
                output / "revision.json",
                output / "checks/summary.json",
                output / "checks/drc.json",
            ]:
                evidence[item.relative_to(self.root).as_posix()] = hashlib.sha256(
                    item.read_bytes()
                ).hexdigest()
            payload["resolved_evidence"] = evidence
            request = ContinuationRequest.model_validate(payload)
            _validate_edit_input_retry(self.root, old, request)
            atomic_write(proof, self.path.read_bytes())
            state.events.append(
                {
                    "event": "annotation_completion_authorized",
                    "at": self._now(),
                    "authorization_reference": authorization_reference,
                    "diagnostic": c.diagnostic.model_dump(),
                    "request_file": request_file,
                    "request_sha256": evidence[request_file],
                    "extra_seconds": 0,
                    "additional_routing_attempts": 0,
                }
            )
            c.request = request
            c.diagnostic = None

    def resolve_placement_rounding_mismatch(self, *, token: str) -> None:
        """Reclassify a placement rejected only by sub-grid serialization rounding."""
        from pcbsmith.kicad.floorplan import require_native_floorplan

        with self._access() as state:
            diagnostic = state.active_diagnostic
            if (
                diagnostic is None
                or diagnostic.status not in {"pending", "reviewing", "expired"}
                or state.status != "active"
                or not state.attempts
                or state.continuation is None
            ):
                raise JobStopped(
                    "placement rounding recovery requires an active failed continuation"
                )
            attempt = state.attempts[-1]
            if (
                attempt.token != token
                or attempt.operation != "placement"
                or attempt.phase != "build"
                or attempt.status != "failed"
                or attempt.command[:2] != ("pcbsmith.cli", "production-generate-board")
            ):
                raise JobStopped(
                    "placement rounding recovery must bind the latest placement failure"
                )
            if any(e.get("event") == "placement_rounding_reclassified" for e in state.events):
                raise JobStopped("placement rounding can be reclassified only once")
            stderr = self.root / ".pcbsmith/job-runs" / token / "logs/placement.stderr.txt"
            if (
                not stderr.read_text(encoding="utf-8")
                .strip()
                .startswith("error: native placement differs from floorplan: ")
            ):
                raise JobStopped("placement recovery requires the exact floorplan mismatch error")
            output = Path(attempt.command[3]).resolve()
            if not output.is_relative_to(self.root):
                raise JobStopped("placement output is outside the job")
            boards = list((output / "design").glob("*.kicad_pcb"))
            if len(boards) != 1:
                raise JobStopped("placement recovery requires one retained native board")
            prepared = json.loads((output / "predesign-inputs/floorplan.json").read_bytes())
            require_native_floorplan(boards[0], prepared["layout_input"], origin_mm=20.0)
            request = state.continuation.request.model_dump()
            retries = dict(state.continuation.request.retry_failed_operations)
            retries["placement"] = token
            request["retry_failed_operations"] = retries
            state.continuation.request = ContinuationRequest.model_validate(request)
            state.events.append(
                {
                    "event": "placement_rounding_reclassified",
                    "at": self._now(),
                    "attempt_token": token,
                    "checkpoint": diagnostic.model_dump(),
                    "board_sha256": hashlib.sha256(boards[0].read_bytes()).hexdigest(),
                    "additional_seconds": 0,
                    "additional_correction_cycles": 0,
                    "reason": (
                        "Retained board passes floorplan replay at KiCad serialization precision"
                    ),
                }
            )
            state.continuation.diagnostic = None
            self._check(state, phase="verify")

    def resolve_predesign_policy_omission(self, *, token: str, policy_file: Path) -> None:
        """Reclassify one exact missing-policy input failure without new time or cycles."""
        from pcbsmith.kicad.component_readiness import SelectedModelPolicy
        from pcbsmith.operations.file_transaction import project_path

        with self._access() as state:
            diagnostic = state.active_diagnostic
            if (
                diagnostic is None
                or diagnostic.status not in {"pending", "reviewing", "expired"}
                or state.status != "active"
                or not state.attempts
                or state.continuation is None
            ):
                raise JobStopped("predesign policy recovery requires an active failed continuation")
            attempt = state.attempts[-1]
            if (
                attempt.token != token
                or attempt.operation != "predesign-approve"
                or attempt.phase != "build"
                or attempt.status != "failed"
                or attempt.command[:2] != ("pcbsmith.predesign_preparation", "approve")
            ):
                raise JobStopped("predesign policy recovery must bind the latest approval failure")
            if any(
                e.get("event") == "predesign_policy_omission_reclassified" for e in state.events
            ):
                raise JobStopped("predesign policy omission can be reclassified only once")
            stderr = self.root / ".pcbsmith/job-runs" / token / "logs/predesign-approve.stderr.txt"
            if (
                "ValueError: Predesign approval requires an explicit selected model policy"
                not in stderr.read_text(encoding="utf-8")
            ):
                raise JobStopped(
                    "predesign policy recovery requires the exact missing-policy error"
                )
            policy_path = project_path(self.root, str(policy_file))
            if policy_path.name != "component-model-selection.json":
                raise JobStopped("recovery policy must use the canonical filename")
            policy = SelectedModelPolicy.model_validate_json(policy_path.read_bytes())
            if policy.applicability != "applicable":
                raise JobStopped("recovery requires an applicable selected-model policy")
            request = state.continuation.request.model_dump()
            operations: list[str] = list(state.continuation.request.build_operations)
            placement_index = (
                operations.index("placement") if "placement" in operations else len(operations)
            )
            for operation in reversed(("predesign-refresh", "predesign-reapprove")):
                if operation not in operations:
                    operations.insert(placement_index, operation)
            request["build_operations"] = tuple(operations)
            state.continuation.request = ContinuationRequest.model_validate(request)
            state.events.append(
                {
                    "event": "predesign_policy_omission_reclassified",
                    "at": self._now(),
                    "attempt_token": token,
                    "checkpoint": diagnostic.model_dump(),
                    "policy_file": str(policy_path.relative_to(self.root)).replace("\\", "/"),
                    "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
                    "additional_seconds": 0,
                    "additional_correction_cycles": 0,
                    "reason": "Verified missing model-policy input; no CAD correction failure",
                }
            )
            state.continuation.diagnostic = None
            self._check(state, phase="verify")

    def resolve_native_preparation_input(self, *, token: str) -> None:
        """One exact missing-spec recovery, retaining failure, clocks and counters."""
        from pcbsmith.native_project import NativeProjectSpec
        from pcbsmith.operations.file_transaction import project_path

        with self._access() as state:
            self._check(state, phase="verify")
            c = state.continuation
            if (
                c is None
                or c.request.pre_native_recovery is None
                or c.request.native_preparation_input_retry is not None
                or c.diagnostic is None
                or c.diagnostic.status != "pending"
                or len(state.attempts) != 1
            ):
                raise JobStopped("native input recovery requires the first failed preparation")
            a = state.attempts[-1]
            if (
                a.token != token
                or a.operation != "native-preparation"
                or a.status != "failed"
                or len(a.command) != 5
                or a.command[0] != "pcbsmith.native_project"
                or a.command[3] != "--symbol-root"
            ):
                raise JobStopped("native input recovery must bind the exact preparation command")
            spec_path = Path(a.command[1]).resolve()
            if not spec_path.is_relative_to(self.root):
                raise JobStopped("native input specification is outside the job")
            spec = project_path(self.root, spec_path.relative_to(self.root).as_posix())
            output = Path(a.command[2]).resolve()
            if not output.is_relative_to(self.root) or output.exists():
                raise JobStopped("native input recovery requires no preparation output")
            if any(self.root.rglob("*.kicad_sch")) or any(self.root.rglob("*.kicad_pcb")):
                raise JobStopped("native input recovery cannot adopt native files")
            log = self.root / ".pcbsmith/job-runs" / token / "logs/native-preparation.stderr.txt"
            error = log.read_text(encoding="utf-8").strip()
            expected = "FileNotFoundError: [Errno 2] No such file or directory: " + repr(
                str(Path(a.command[1]))
            )
            if not error.endswith(expected) or "args.spec.read_text" not in error:
                raise JobStopped("native input recovery requires the exact missing-spec failure")
            NativeProjectSpec.model_validate_json(spec.read_bytes())
            payload = c.request.model_dump()
            payload["native_preparation_input_retry"] = token
            payload["retry_failed_operations"] = {"native-preparation": token}
            c.request = ContinuationRequest.model_validate(payload)
            state.events.append(
                {
                    "event": "native_preparation_input_reclassified",
                    "at": self._now(),
                    "attempt_token": token,
                    "checkpoint": c.diagnostic.model_dump(),
                    "spec_file": spec.relative_to(self.root).as_posix(),
                    "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
                    "stderr_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                    "additional_seconds": 0,
                    "additional_correction_cycles": 0,
                }
            )
            c.diagnostic = None

    def resolve_review_generation_collision(self, *, token: str, successor_id: str) -> None:
        """Reclassify one proven review-output name collision; grant no runtime or cycles.

        A verification publication input error is not a failed CAD correction.
        Actual inspection and transaction checks still run on the next attempt.
        """
        from pcbsmith.operations.file_transaction import project_path
        from pcbsmith.production_workflow import resolve_current_generation

        with self._access() as state:
            diagnostic = state.active_diagnostic
            if (
                diagnostic is None
                or diagnostic.status != "pending"
                or state.status != "active"
                or not state.attempts
            ):
                raise JobStopped("review collision requires a pending input-error checkpoint")
            attempt = state.attempts[-1]
            args = attempt.command
            if (
                attempt.token != token
                or attempt.operation != "visual-inspect"
                or attempt.phase != "verify"
                or attempt.status != "failed"
                or args[:2] != ("pcbsmith.cli", "production-visual-inspect")
            ):
                raise JobStopped("review collision must bind the latest failed visual inspection")
            if any(e.get("event") == "review_collision_reclassified" for e in state.events):
                raise JobStopped("review collision recovery is allowed only once per job")
            transaction_root = Path(args[2]).resolve()
            if not transaction_root.is_relative_to(self.root):
                raise JobStopped("review collision transaction is outside the job")
            old_id = args[args.index("--generation-id") + 1]
            sha = args[args.index("--generation-sha256") + 1]
            current = resolve_current_generation(transaction_root)
            if current.generation_id != old_id or current.generation_sha256 != sha:
                raise JobStopped("review collision current generation changed")
            destination = project_path(transaction_root / "generations", successor_id)
            if destination.exists() or successor_id == old_id or "/" in successor_id:
                raise JobStopped("review collision successor must be a fresh simple identifier")
            stderr = self.root / ".pcbsmith/job-runs" / token / "logs/visual-inspect.stderr.txt"
            expected = "error: generation path already exists: " + str(
                transaction_root / "generations" / old_id
            )
            if stderr.read_text(encoding="utf-8").strip() != expected:
                raise JobStopped("review collision requires the exact precommit path error")
            # Resolving current replays all retained artifact hashes. Preserve the
            # failed attempt and checkpoint in the event, with original clocks.
            state.events.append(
                {
                    "event": "review_collision_reclassified",
                    "at": self._now(),
                    "attempt_token": token,
                    "checkpoint": diagnostic.model_dump(),
                    "transaction_fingerprint": current.transaction_fingerprint,
                    "successor_id": successor_id,
                    "additional_seconds": 0,
                    "additional_correction_cycles": 0,
                    "reason": "Verified immutable-output name collision; no CAD correction failure",
                }
            )
            if state.continuation:
                state.continuation.diagnostic = None
            else:
                state.diagnostic = None
            self._check(state, phase="verify")

    def claim(
        self, *, operation: str, phase: str, input_sha256: str, command: Sequence[str]
    ) -> Attempt:
        with self._access() as state:
            self._check(state, phase=phase)
            if any(a.status == "running" for a in state.attempts):
                raise JobStopped("another attempt owns the job; no concurrent work")
            if phase == "build" and state.continuation:
                c = state.continuation
                if operation not in c.request.build_operations:
                    raise JobStopped("operation outside explicitly authorized continuation scope")
                scope_attempts = [
                    a for a in state.attempts[c.prior_attempt_count :] if a.operation == operation
                ]
                scoped_retry = (
                    bool(scope_attempts)
                    and scope_attempts[-1].status == "failed"
                    and c.request.retry_failed_operations.get(operation) == scope_attempts[-1].token
                )
                if scope_attempts and not scoped_retry:
                    self._request_diagnostic(state, "continuation operation allowance exhausted")
                    raise JobStopped("continuation operation allowance is one attempt")
            if operation == "visual-inspect":
                recovery = next(
                    (
                        e
                        for e in reversed(state.events)
                        if e.get("event") == "review_collision_reclassified"
                    ),
                    None,
                )
                if recovery and state.attempts[-1].token == recovery["attempt_token"]:
                    old_args = list(state.attempts[-1].command)
                    index = old_args.index("--generation-id") + 1
                    old_args[index] = str(recovery["successor_id"])
                    if list(command) != old_args:
                        raise JobStopped("review collision retry may change only successor ID")
            previous = [
                a
                for a in state.attempts
                if a.operation == operation
                or (operation == "native-repair" and "--native-repair" in a.command)
            ]
            design_sha256 = None
            if operation == "routing" and state.routing_policy:
                if len(previous) >= 2:
                    self._request_diagnostic(
                        state, "automatic routing permits one initial run and one retry"
                    )
                    raise JobStopped(
                        "Automatic routing attempts exhausted; "
                        "retain the candidate and diagnose placement/jumpers"
                    )
                if tuple(command[:1]) == ("pcbsmith.production_routing",):
                    from pcbsmith.routing_policy import routing_design_fingerprint

                    if "--layout" not in command or "--netlist" not in command:
                        raise JobStopped(
                            "Automatic routing requires pinned layout and netlist inputs"
                        )
                    design_sha256 = routing_design_fingerprint(
                        Path(command[command.index("--layout") + 1]),
                        Path(command[command.index("--netlist") + 1]),
                    )
                    repaired_adapter = (
                        state.continuation is not None
                        and state.continuation.request.routing_adapter_repair_sha256 is not None
                        and bool(previous)
                        and previous[-1].status == "failed"
                        and state.continuation.request.retry_failed_operations.get("routing")
                        == previous[-1].token
                    )
                    if repaired_adapter:
                        assert state.continuation is not None
                        _validate_routing_adapter_repair(self.root, state.continuation.request)
                    if (
                        previous
                        and previous[-1].routing_design_sha256 == design_sha256
                        and not repaired_adapter
                    ):
                        raise JobStopped(
                            "Routing retry requires a placement or netlist change; "
                            "changing budgets/order is not a correction"
                        )
            limit = (
                state.continuation.request.routing_attempt_limit
                if operation == "routing" and state.continuation
                else 3
            )
            if (
                operation == "visual-render"
                and state.continuation
                and state.continuation.request.final_render_plan
            ):
                c = state.continuation
                if len(previous) >= 4:
                    self._request_diagnostic(state, "final render completion already used")
                    raise JobStopped("final render completion permits only one attempt")
                if phase != "verify":
                    raise JobStopped("final render completion requires verification phase")
                _validate_final_render(
                    self.root, state.attempts[: c.prior_attempt_count], c.request, command
                )
                limit = 4
            if len(previous) >= limit:
                self._request_diagnostic(state, "operation attempt allowance exhausted")
                raise JobStopped("operation attempt allowance exhausted; diagnostic required")
            if phase == "build" and any(a.cycle == state.cycle for a in previous):
                explicit_retry = (
                    state.continuation is not None
                    and previous[-1].status == "failed"
                    and state.continuation.request.retry_failed_operations.get(operation)
                    == previous[-1].token
                )
                placement_followup = (
                    state.continuation is not None
                    and state.continuation.request.placement_followup_plan is not None
                    and operation
                    in {"edit", "apply-edit", "predesign-refresh", "predesign-reapprove"}
                )
                if not explicit_retry and not placement_followup:
                    raise JobStopped(
                        "operation already attempted; record a bounded correction first"
                    )
            if (
                state.continuation
                and state.continuation.request.placement_followup_plan is not None
            ):
                _validate_placement_followup(
                    self.root,
                    state.attempts[: state.continuation.prior_attempt_count],
                    state.continuation.request,
                    operation=operation,
                    command=command,
                )
            if (
                operation == "edit"
                and state.continuation
                and "edit" in state.continuation.request.retry_failed_operations
            ):
                _validate_edit_input_retry(
                    self.root, previous[-1], state.continuation.request, command
                )
            if (
                operation == "native-preparation"
                and state.continuation
                and state.continuation.request.native_preparation_input_retry
            ):
                event = next(
                    e
                    for e in reversed(state.events)
                    if e.get("event") == "native_preparation_input_reclassified"
                )
                from pcbsmith.operations.file_transaction import project_path

                corrected = project_path(self.root, str(event["spec_file"]))
                if (
                    tuple(command) != previous[-1].command
                    or hashlib.sha256(corrected.read_bytes()).hexdigest() != event["spec_sha256"]
                ):
                    raise JobStopped("native input retry differs from the pinned correction")
            if (
                operation == "routing"
                and state.continuation
                and state.continuation.request.routing_backend_config
            ):
                _validate_routing_backend_transition(
                    self.root, state.attempts, state.continuation.request, command
                )
            if (
                operation in {"edit", "apply-edit"}
                and state.continuation
                and state.continuation.request.local_completion_board
            ):
                expected = self.root / state.continuation.request.local_completion_board
                if len(command) < 3 or Path(command[2]).resolve() != expected:
                    raise JobStopped("local completion command targets another native board")
            if previous and previous[-1].input_sha256 == input_sha256:
                raise JobStopped("identical effective inputs; output directory is not a correction")
            attempt = Attempt(
                routing_design_sha256=design_sha256,
                token=uuid.uuid4().hex,
                operation=operation,
                phase=phase,
                input_sha256=input_sha256,
                command=tuple(command),
                cycle=state.cycle,
                started_at=self._now(),
                supervisor_pid=os.getpid(),
            )
            state.attempts.append(attempt)
            return attempt.model_copy(deep=True)

    def preflight(self, phase: str) -> None:
        with self._access() as state:
            self._check(state, phase=phase)
            if any(a.status == "running" for a in state.attempts):
                raise JobStopped("another attempt owns the job; no concurrent preparation")

    def remaining(self, token: str) -> float:
        with self._access() as state:
            attempt = next((a for a in state.attempts if a.token == token), None)
            if attempt is None or attempt.status != "running":
                raise JobStopped("missing or completed attempt lease")
            remaining = self._check(state, phase=attempt.phase)
            if attempt.phase == "build":
                remaining -= state.reserve_seconds
            return remaining

    def launched(self, token: str, pid: int) -> None:
        with self._access() as state:
            self._check(state)
            attempt = next(a for a in state.attempts if a.token == token)
            if attempt.status != "running" or attempt.supervisor_pid != os.getpid():
                raise JobStopped("only the active supervisor can record containment")
            if attempt.launcher_pid is not None:
                raise JobStopped("attempt already launched")
            attempt.launcher_pid = pid

    def authorize(self, token: str, command: Sequence[str]) -> None:
        with self._access() as state:
            self._check(state)
            attempt = next((a for a in state.attempts if a.token == token), None)
            if attempt is None or attempt.status != "running" or attempt.command != tuple(command):
                raise JobStopped("worker command does not match active job lease")
            # Windows venv executables may redirect through one launcher process.
            # The recorded launcher and its children are already in the OS job.
            if attempt.launcher_pid is None or (
                os.getpid() != attempt.launcher_pid and os.getppid() != attempt.launcher_pid
            ):
                raise JobStopped("worker is not the recorded contained worker or launcher child")
            if attempt.worker_pid not in {None, os.getpid()}:
                raise JobStopped("attempt lease already claimed by another worker")
            attempt.worker_pid = os.getpid()

    def finish_attempt(
        self,
        token: str,
        *,
        status: Literal["passed", "failed", "stopped"],
        result: dict[str, object],
        failure_signature: str | None = None,
    ) -> None:
        with self._access() as state:
            attempt = next(a for a in state.attempts if a.token == token)
            if attempt.status != "running":
                raise JobStopped("attempt is already terminal")
            now = self._now()
            attempt.ended_at = now
            attempt.status = status
            attempt.result = result
            attempt.failure_signature = failure_signature
            try:
                self._check(state, phase="verify")
            except JobStopped:
                pass
            if state.last_seen >= state.active_deadline:
                state.status, state.reason = "stopped", "whole-job deadline exhausted"
                state.stop_kind = "deadline"
            elif status == "stopped" and state.status != "stopped":
                reserve_at = state.active_deadline - state.reserve_seconds
                usage = state.timing_usage(state.last_seen)
                reserve_reached = (
                    float(usage["execution_seconds"])
                    >= state.active_execution_seconds - state.reserve_seconds
                    if state.active_evaluation_seconds is not None
                    else state.last_seen >= reserve_at
                )
                if attempt.phase == "build" and reserve_reached:
                    state.reason = "build stopped at verification reserve"
                else:
                    state.status, state.reason = "stopped", "worker interrupted or timed out"
                    state.stop_kind = "interrupted"
            if failure_signature and any(
                a.token != token
                and a.operation == attempt.operation
                and a.failure_signature == failure_signature
                for a in state.attempts
            ):
                state.status, state.reason = "stopped", "same failure recurred after correction"
                state.stop_kind = "repeated_failure"
                self._request_diagnostic(state, "same failure recurred after correction")
            elif status != "passed" and (state.continuation or state.cycle == 2):
                self._request_diagnostic(state, "failure after final corrective cycle")

    @staticmethod
    def _set_diagnostic(state: JobState, diagnostic: DiagnosticCheckpoint) -> None:
        if state.continuation:
            state.continuation.diagnostic = diagnostic
        else:
            state.diagnostic = diagnostic

    def _request_diagnostic(self, state: JobState, reason: str) -> None:
        if state.active_diagnostic is None:
            self._set_diagnostic(
                state, DiagnosticCheckpoint(trigger=reason, requested_at=self._now())
            )
            state.events.append(
                {"event": "diagnostic_required", "at": self._now(), "reason": reason}
            )

    def begin_diagnostic(self, reason: str) -> DiagnosticCheckpoint:
        """One short assessment window; never changes job status or allowances."""
        if not reason.strip():
            raise ValueError("diagnostic review requires a reason")
        with self._access() as state:
            if any(a.status == "running" for a in state.attempts):
                raise JobStopped("settle the active worker before diagnostic review")
            now = self._now()
            if self.clock() < state.last_seen - 1:
                raise JobStopped("clock moved backwards")
            if state.status == "finished" or state.stop_kind == "clock":
                raise JobStopped("finished or clock-inconsistent job cannot be diagnosed")
            retrospective = state.status == "stopped" and state.stop_kind == "deadline"
            if retrospective:
                # Preserve the elapsed allowance. This bounded review grants no build
                # time; recovery still requires a source-bound continuation request
                # and explicit user authorization through continue_authorized.
                reserve_at = now + 300
            else:
                reserve_at = state.active_deadline - state.reserve_seconds
                if state.active_evaluation_seconds is not None:
                    usage = state.timing_usage(now)
                    reserve_at = min(
                        reserve_at,
                        now + state.active_evaluation_seconds - float(usage["evaluation_seconds"]),
                    )
                if now >= reserve_at:
                    raise JobStopped("no diagnostic time remains before verification reserve")
            if (
                state.active_diagnostic is not None
                and state.active_diagnostic.started_at is not None
            ):
                raise JobStopped("diagnostic already started; no restart or extra review window")
            self._request_diagnostic(state, reason)
            assert state.active_diagnostic is not None
            payload = state.active_diagnostic.model_dump()
            payload.update(status="reviewing", started_at=now, deadline=min(now + 300, reserve_at))
            self._set_diagnostic(state, DiagnosticCheckpoint.model_validate(payload))
            state.last_seen = max(state.last_seen, now)
            return state.active_diagnostic.model_copy(deep=True)

    def complete_diagnostic(self, recommendation: DiagnosticRecommendation) -> None:
        from pcbsmith.operations.file_transaction import project_path

        with self._access() as state:

            def check_window() -> float:
                now = self._now()
                d = state.active_diagnostic
                if d is None or d.status != "reviewing" or d.deadline is None:
                    raise JobStopped("no active diagnostic review")
                if self.clock() < state.last_seen - 1 or now >= d.deadline:
                    d.status = "expired"
                    raise JobStopped("diagnostic window expired or clock inconsistent")
                state.last_seen = max(state.last_seen, now)
                return now

            check_window()
            for relative, expected in recommendation.evidence.items():
                path = project_path(self.root, relative)
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    while True:
                        check_window()
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError("diagnostic evidence changed")
            now = check_window()
            assert state.active_diagnostic is not None
            payload = state.active_diagnostic.model_dump()
            payload.update(status="complete", completed_at=now, recommendation=recommendation)
            self._set_diagnostic(state, DiagnosticCheckpoint.model_validate(payload))
            state.events.append(
                {
                    "event": "diagnostic_completed",
                    "at": now,
                    "action": recommendation.action,
                    "authorizes_work": False,
                }
            )

    def stop(self, reason: str, *, finished: bool = False) -> None:
        with self._access() as state:
            if state.status != "active":
                raise JobStopped("terminal state cannot be relabeled to reset a stop condition")
            if finished:
                self._check(state)
                if any(a.status == "running" for a in state.attempts):
                    raise JobStopped("cannot finish with a running attempt")
            if finished:
                state.finished_at = self._now()
                state.last_seen = max(state.last_seen, state.finished_at)
            state.status, state.reason = ("finished" if finished else "stopped"), reason
            state.stop_kind = "finished" if finished else "cancelled"
            state.events.append({"event": state.stop_kind, "at": self._now(), "reason": reason})

    def resume(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("resume needs an explicit reason")
        with self._access() as state:
            if state.stop_kind not in {"cancelled", "interrupted"}:
                raise JobStopped(
                    "only cancellation/interruption can resume within the original deadline"
                )
            if any(a.status == "running" for a in state.attempts):
                raise JobStopped(
                    "unsettled worker lease; preserve state and investigate before recovery"
                )
            state.status = "active"
            self._check(state)
            state.events.append({"event": "resumed", "at": self._now(), "reason": reason})
            state.stop_kind, state.reason = "", ""


def _validate_pre_native_recovery(
    root: Path,
    state: JobState,
    request: ContinuationRequest,
    recommendation: DiagnosticRecommendation,
) -> None:
    from pcbsmith.operations.file_transaction import project_path

    recovery = request.pre_native_recovery
    assert recovery is not None
    if (
        state.continuation is not None
        or state.continuation_history
        or state.attempts
        or state.corrections
        or state.cycle != 0
        or state.diagnostic is None
        or state.diagnostic.status != "complete"
        or state.diagnostic.recommendation != recommendation
        or recommendation.action not in {"stop", "local_edit", "platform_work"}
    ):
        raise JobStopped("pre-native recovery requires an untouched, diagnosed initial job")
    if any(root.rglob("*.kicad_pcb")) or any(root.rglob("*.kicad_sch")):
        raise JobStopped("pre-native recovery cannot replace retained native inputs")
    source = project_path(root, recovery.approval_file).read_bytes()
    if hashlib.sha256(source).hexdigest() != recovery.approval_sha256:
        raise JobStopped("pre-native layout approval changed")
    approval = PreNativeLayoutApproval.model_validate_json(source)
    if approval.authorization_reference != request.authorization_reference:
        raise JobStopped("pre-native approval requires the current explicit authorization")
    suffixes = {Path(name).suffix.lower() for name in approval.approved_artifacts}
    if not {".svg", ".png", ".json"} <= suffixes:
        raise JobStopped("pre-native approval requires vector, preview and structured intent")
    for relative, expected in approval.approved_artifacts.items():
        if hashlib.sha256(project_path(root, relative).read_bytes()).hexdigest() != expected:
            raise JobStopped("pre-native approved artifact changed")


def _validate_edit_input_retry(
    root: Path,
    attempt: Attempt,
    request: ContinuationRequest,
    command: Sequence[str] | None = None,
) -> None:
    """Permit only an explicit retry of an unchanged, pre-mutation input failure."""
    from pcbsmith.board_revision import BoardRevisionRequest
    from pcbsmith.operations.file_transaction import project_path

    args = attempt.command
    if len(args) < 3 or args[:2] != ("pcbsmith.cli", "production-edit-board"):
        raise JobStopped("edit retry requires a recorded supported edit command")
    board = Path(args[2]).resolve()
    output = Path(args[args.index("--output") + 1]).resolve()
    if not board.is_relative_to(root) or not output.is_relative_to(root):
        raise JobStopped("edit retry inputs must remain in the original job")
    if (output / "revision.json").is_file():
        # A completed native candidate may need one annotation-only closure.
        assert request.edit_retry_request is not None
        corrected_path = project_path(root, request.edit_retry_request)
        for item in [
            corrected_path,
            output / "revision.json",
            output / "checks/summary.json",
            output / "checks/drc.json",
        ]:
            if (
                request.resolved_evidence.get(item.relative_to(root).as_posix())
                != hashlib.sha256(item.read_bytes()).hexdigest()
            ):
                raise JobStopped("Annotation completion evidence is not bound")
        summary = json.loads((output / "checks/summary.json").read_bytes())
        drc = json.loads((output / "checks/drc.json").read_bytes())
        if (
            summary.get("erc_findings") != 0
            or summary.get("drc_findings", {}).get("unconnected_items") != 0
            or summary.get("drc_findings", {}).get("schematic_parity") != 0
        ):
            raise JobStopped("Annotation completion requires electrically complete native checks")
        violations = drc.get("violations", [])
        if not violations or any(
            v.get("type")
            not in {
                "silk_overlap",
                "silk_over_copper",
                "silk_edge_clearance",
                "silk_text_height",
                "silk_text_thickness",
            }
            for v in violations
        ):
            raise JobStopped("Annotation completion is limited to silkscreen findings")
        new = BoardRevisionRequest.model_validate_json(corrected_path.read_bytes())
        record = json.loads((output / "revision.json").read_bytes())
        candidate = output / "design" / board.name
        if (
            new.source_inputs != record.get("candidate_inputs")
            or new.substitutions
            or new.zero_ohm_links
            or new.mutable_zone_ids
            or new.validation_stage != "routed"
            or new.intent != "requested"
            or not 1 <= len(new.edits) <= 8
            or any(e.kind not in {"reference", "text"} for e in new.edits)
        ):
            raise JobStopped("Annotation completion may change only retained candidate labels")
        for relative, expected in new.source_inputs.items():
            if (
                hashlib.sha256(project_path(candidate.parent, relative).read_bytes()).hexdigest()
                != expected
            ):
                raise JobStopped("Annotation completion candidate changed")
        if command is not None and (
            len(command) < 3
            or command[:2] != ("pcbsmith.cli", "production-edit-board")
            or Path(command[2]).resolve() != candidate
            or Path(command[command.index("--request") + 1]).resolve() != corrected_path
        ):
            raise JobStopped("Annotation completion command differs from its pinned request")
        return
    if any((output / name).exists() for name in ("revision.json", "delta.json", "workflow")):
        raise JobStopped("edit retry requires failure before mutation stages")
    failure_path = output / "failure.json"
    failure_relative = failure_path.relative_to(root).as_posix()
    if (
        request.resolved_evidence.get(failure_relative)
        != hashlib.sha256(failure_path.read_bytes()).hexdigest()
    ):
        raise JobStopped("edit retry requires bound failure evidence")
    failure = json.loads(failure_path.read_bytes())
    if (
        failure.get("status") != "failed"
        or not failure.get("source_inputs")
        or not failure.get("error", "").startswith(
            "ValueError: edit target is missing or ambiguous:"
        )
    ):
        raise JobStopped("edit retry is limited to pre-mutation selector failures")
    for relative, expected in failure["source_inputs"].items():
        for directory in (board.parent, output / "before", output / "design"):
            if (
                hashlib.sha256(project_path(directory, relative).read_bytes()).hexdigest()
                != expected
            ):
                raise JobStopped("edit retry source or failed candidate changed")
    assert request.edit_retry_request is not None
    corrected_path = project_path(root, request.edit_retry_request)
    if (
        request.resolved_evidence.get(request.edit_retry_request)
        != hashlib.sha256(corrected_path.read_bytes()).hexdigest()
    ):
        raise JobStopped("edit retry corrected request is not bound")
    old = BoardRevisionRequest.model_validate_json((output / "request.json").read_bytes())
    new = BoardRevisionRequest.model_validate_json(corrected_path.read_bytes())
    if old.source_inputs != failure["source_inputs"] or new.source_inputs != old.source_inputs:
        raise JobStopped("edit retry source mapping changed")
    old_data, new_data = old.model_dump(), new.model_dump()
    old_data.pop("rationale")
    new_data.pop("rationale")
    old_targets = [edit.pop("target") for edit in old_data["edits"]]
    new_targets = [edit.pop("target") for edit in new_data["edits"]]
    if old_data != new_data or old_targets == new_targets:
        raise JobStopped("edit retry may correct only selectors")
    if command is not None:
        if (
            len(command) < 3
            or command[:2] != ("pcbsmith.cli", "production-edit-board")
            or Path(command[2]).resolve() != board
            or Path(command[command.index("--request") + 1]).resolve() != corrected_path
        ):
            raise JobStopped("edit retry command differs from the authorized request")


def _visual_stage(command: Sequence[str], stage: str) -> bool:
    return (
        tuple(command[:2]) == ("pcbsmith.cli", "visual-review")
        and command.count("--stage") == 1
        and command.index("--stage") + 1 < len(command)
        and command[command.index("--stage") + 1] == stage
    )


def _validate_final_render(
    root: Path,
    prior_attempts: Sequence[Attempt],
    request: ContinuationRequest,
    command: Sequence[str] | None = None,
) -> None:
    """One first final render after three successful, materially revised placement views.

    This read-only validator grants neither CAD operations nor automatic renewal.
    Native evidence, project closure and the accepted routing result remain mandatory.
    """
    from pcbsmith.kicad.project_dependencies import native_project_hashes
    from pcbsmith.kicad.routing_candidate_transaction import (
        AcceptedRoutingExecution,
        RoutingCandidateTransactionResult,
    )
    from pcbsmith.mandatory_review import require_current_native_checks
    from pcbsmith.operations.file_transaction import project_path

    assert request.final_render_plan is not None
    plan_file = project_path(root, request.final_render_plan)
    if hashlib.sha256(plan_file.read_bytes()).hexdigest() != request.resolved_evidence.get(
        request.final_render_plan
    ):
        raise JobStopped("final render plan changed")
    plan = json.loads(plan_file.read_bytes())
    if set(plan) != {"command", "inputs"}:
        raise JobStopped("final render plan fields are invalid")
    expected = tuple(plan["command"])
    if (
        len(expected) != 12
        or not _visual_stage(expected, "final")
        or expected[4::2] != ("--stage", "--features", "--model-preflight", "--native-checks")
        or (command is not None and tuple(command) != expected)
    ):
        raise JobStopped("final render command differs from the bound final-stage scope")
    paths = [Path(expected[i]).resolve() for i in (2, 3, 7, 9, 11)]
    if any(not p.is_relative_to(root) for p in paths):
        raise JobStopped("final render inputs/output must stay within the same job")
    board, output, features, models, checks = paths
    if output.exists():
        raise JobStopped("final render output must be unstarted")
    renders = [a for a in prior_attempts if a.operation == "visual-render"]
    if len(renders) != 3 or any(
        a.status != "passed" or not _visual_stage(a.command, "placement") for a in renders
    ):
        raise JobStopped("final render completion requires three successful placement renders")
    routes = [a for a in prior_attempts if a.operation == "routing"]
    if not routes or routes[-1].status != "passed" or "--output" not in routes[-1].command:
        raise JobStopped("final render completion requires an accepted routing attempt")
    args = routes[-1].command
    result_file = Path(args[args.index("--output") + 1]).resolve() / "result.json"
    if not result_file.is_relative_to(root):
        raise JobStopped("routing result is outside the job")
    required = {board, features, models, result_file}
    required.update(board.parent / p for p in native_project_hashes(board))
    required.update(p for p in checks.rglob("*") if p.is_file())
    inputs = plan["inputs"]
    if not {p.relative_to(root).as_posix() for p in required} <= set(inputs):
        raise JobStopped("final render plan omits current source/evidence inputs")
    for relative, digest in inputs.items():
        if hashlib.sha256(project_path(root, relative).read_bytes()).hexdigest() != digest:
            raise JobStopped("final render input changed")
    transaction = RoutingCandidateTransactionResult.model_validate_json(result_file.read_bytes())
    receipt = AcceptedRoutingExecution.from_transaction(transaction)
    if hashlib.sha256(board.read_bytes()).hexdigest() != receipt.board_sha256:
        raise JobStopped("final render board differs from accepted routing")
    require_current_native_checks(board, checks)


def _validate_placement_followup(
    root: Path,
    prior_attempts: Sequence[Attempt],
    request: ContinuationRequest,
    *,
    operation: str | None = None,
    command: Sequence[str] = (),
) -> None:
    """One explicit pose correction after annotations, never a repeated placement edit.

    The ordinary lifetime, per-scope, effective-input and routing limits remain in claim.
    The plan is bound before preparation; the revision still requires reviewed floorplan
    inputs and native validation. No board is generated or changed by this validator.
    """
    from pcbsmith.board_revision import BoardRevisionRequest, _require_unrouted_annotations
    from pcbsmith.kicad.native_edits import NativeEdit
    from pcbsmith.operations.file_transaction import project_path

    assert request.placement_followup_plan is not None
    path = project_path(root, request.placement_followup_plan)
    if (
        request.resolved_evidence.get(request.placement_followup_plan)
        != hashlib.sha256(path.read_bytes()).hexdigest()
    ):
        raise JobStopped("placement follow-up plan changed")
    plan = json.loads(path.read_bytes())
    if set(plan) != {"board", "source_inputs", "edits"}:
        raise JobStopped("placement follow-up plan fields are invalid")
    board = project_path(root, plan["board"])
    edits = tuple(NativeEdit.model_validate(e) for e in plan["edits"])
    if not edits or any(e.kind != "component" for e in edits):
        raise JobStopped("placement follow-up must contain only component poses")
    if len({e.target for e in edits}) != len(edits):
        raise JobStopped("placement follow-up has duplicate targets")
    if board.name not in plan["source_inputs"]:
        raise JobStopped("placement follow-up must pin its native board")
    earlier = [a for a in prior_attempts if a.operation == "edit"]
    if not earlier or any(a.status != "passed" for a in earlier):
        raise JobStopped("placement follow-up requires successful prior annotations")
    for attempt in earlier:
        old_path = Path(attempt.command[attempt.command.index("--request") + 1]).resolve()
        old = BoardRevisionRequest.model_validate_json(old_path.read_bytes())
        if old.validation_stage != "unrouted_annotations" or any(
            e.kind not in {"text", "reference"} for e in old.edits
        ):
            raise JobStopped("placement follow-up cannot repeat a prior placement or copper edit")
        if Path(attempt.command[2]).resolve() != board:
            raise JobStopped("placement follow-up must preserve its prior board path")
    if operation is None or operation == "edit":
        _require_unrouted_annotations(board)
        for relative, digest in plan["source_inputs"].items():
            if (
                hashlib.sha256(project_path(board.parent, relative).read_bytes()).hexdigest()
                != digest
            ):
                raise JobStopped("placement follow-up native source changed")
    if operation in {"edit", "apply-edit"}:
        expected_command = (
            "production-edit-board" if operation == "edit" else "production-apply-board-edit"
        )
        if (
            tuple(command[:2]) != ("pcbsmith.cli", expected_command)
            or Path(command[2]).resolve() != board
        ):
            raise JobStopped("placement follow-up targets another command or board")
        if operation == "edit":
            revised_path = Path(command[command.index("--request") + 1])
        else:
            revised_path = Path(command[command.index("--revision") + 1]) / "request.json"
        revised = BoardRevisionRequest.model_validate_json(revised_path.read_bytes())
        if (
            revised.validation_stage != "unrouted_placement"
            or revised.edits != edits
            or any(revised.source_inputs.get(k) != v for k, v in plan["source_inputs"].items())
        ):
            raise JobStopped("placement follow-up differs from its exact approved pose plan")


def require_library_worker() -> None:
    """Supported producers require the same active, contained worker as their CLI."""
    root, token = os.environ.get(ROOT_ENV), os.environ.get(TOKEN_ENV)
    if not root or not token:
        raise JobStopped("Supported producer requires an active supervised board job")
    job = BoardJob(Path(root))
    job.remaining(token)
    state = job.snapshot()
    attempt = next(a for a in state.attempts if a.token == token)
    if attempt.worker_pid != os.getpid():
        raise JobStopped("producer caller does not own the active worker lease")
    ready = job.root / ".pcbsmith/job-runs" / token / "worker-ready"
    if not ready.is_file() or ready.read_text(encoding="utf-8") != token:
        raise JobStopped("producer has no process containment receipt")


def bind_revision_job(output: Path, *, resume: bool) -> None:
    """Carry the job identity with an edit checkpoint; resuming never creates a job."""
    binding = output / "board-job-binding.json"
    root, token = os.environ.get(ROOT_ENV), os.environ.get(TOKEN_ENV)
    if not root or not token:
        if binding.exists():
            raise JobStopped("managed revision requires its original active board job")
        return  # Existing direct library/research calls are outside supervised CLI coverage.
    job = BoardJob(Path(root))
    job.remaining(token)
    state = job.snapshot()
    attempt = next(a for a in state.attempts if a.token == token)
    if attempt.worker_pid != os.getpid():
        raise JobStopped("revision caller does not own the active worker lease")
    identity = {"job_id": state.job_id, "job_root": str(job.root)}
    if resume:
        if not binding.is_file() or json.loads(binding.read_text(encoding="utf-8")) != identity:
            raise JobStopped("revision checkpoint belongs to another or missing board job")
    else:
        atomic_write(binding, (json.dumps(identity, indent=2) + "\n").encode())


def operation_for(module: str, args: Sequence[str]) -> tuple[str, str]:
    if module == "pcbsmith.cli" and args and args[0] in CLI_OPERATIONS:
        return CLI_OPERATIONS[args[0]]
    if module == "pcbsmith.native_project":
        return "native-preparation", "build"
    if module == "pcbsmith.laser_artwork":
        return "laser-artwork", "verify"
    if module == "pcbsmith.production_routing":
        if "--native-repair" in args:
            return "native-repair", "build"
        if "--revalidate-result" in args:
            return "routing-validation", "verify"
        return "routing", "build"
    if module == "pcbsmith.predesign_preparation" and args:
        if args[0] in {"prepare", "approve", "refresh", "reapprove"}:
            return "predesign-" + args[0], "build"
    raise ValueError("command is not a supported board-job operation")


def input_identity(
    module: str, args: Sequence[str], *, check: Callable[[], None] | None = None
) -> str:
    """Hash explicit input files; ignore output locations, not real option changes.

    Directory dependency closure is still checked by each production owner.
    This conservative retry key does not replace their release fingerprints.
    """
    normalized: list[object] = [module]
    skip = False
    for index, arg in enumerate(args):
        if skip:
            skip = False
            continue
        if arg in {"--output", "--output-dir"}:
            skip = True
            continue
        if arg.startswith(("--output=", "--output-dir=")):
            continue
        if (
            module == "pcbsmith.cli"
            and args[0]
            in {
                "production-generate-board",
                "production-placement-review",
                "production-routed-review",
                "visual-review",
            }
            and index == 2
        ):
            continue
        if module == "pcbsmith.native_project" and index == 1:
            continue
        if module == "pcbsmith.predesign_preparation" and args[0] == "prepare" and index == 3:
            continue
        path = Path(arg.split("=", 1)[-1])
        try:
            is_file = path.is_file()
        except OSError:
            is_file = False
        if is_file:
            digest = hashlib.sha256()
            if check is not None:
                check()
            with path.open("rb") as handle:
                while True:
                    if check is not None:
                        check()
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            normalized.append({"file": digest.hexdigest()})
        else:
            normalized.append(arg)
    if (
        module == "pcbsmith.production_routing"
        and "--board" in args
        and not any(
            flag in args
            for flag in ("--freerouting-config", "--legacy-native-reason", "--revalidate-result")
        )
    ):
        from pcbsmith.routing_policy import resolve_freerouting_config

        settings = resolve_freerouting_config(Path(args[args.index("--board") + 1]))
        normalized.append(
            {"implicit_freerouting_config": hashlib.sha256(settings.read_bytes()).hexdigest()}
        )
    if (
        module == "pcbsmith.laser_artwork"
        and "--board" in args
        and Path(args[args.index("--board") + 1]).is_file()
    ):
        from pcbsmith.kicad.project_dependencies import native_project_hashes

        if check is not None:
            check()
        normalized.append(
            {
                "laser_native_inputs": native_project_hashes(
                    Path(args[args.index("--board") + 1])
                )
            }
        )
        if check is not None:
            check()
    # A diagnosed shared-code fix is a changed implementation input, unlike a
    # fresh output directory. It still consumes the same global correction cap.
    implementation = hashlib.sha256()
    for source in sorted(_IMPLEMENTATION_ROOT.rglob("*.py")):
        if check is not None:
            check()
        implementation.update(source.relative_to(_IMPLEMENTATION_ROOT).as_posix().encode())
        with source.open("rb") as handle:
            while True:
                if check is not None:
                    check()
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                implementation.update(chunk)
    normalized.append({"implementation_sha256": implementation.hexdigest()})
    # The native footprint resolver consumes this root outside project-local tables.
    # A repaired dependency lookup is an effective input, not an output-path retry.
    private_root = os.environ.get("PCBSMITH_PRIVATE_ASSET_ROOT")
    if private_root:
        asset_root = Path(private_root).resolve()
        assets = {}
        if asset_root.is_dir():
            for asset in sorted(asset_root.rglob("*")):
                if not asset.is_file() or asset.suffix.lower() not in {
                    ".kicad_mod",
                    ".kicad_sym",
                    ".step",
                    ".stp",
                    ".wrl",
                }:
                    continue
                digest = hashlib.sha256()
                with asset.open("rb") as handle:
                    while True:
                        if check is not None:
                            check()
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                assets[asset.relative_to(asset_root).as_posix()] = digest.hexdigest()
        normalized.append({"private_asset_root": str(asset_root), "assets": assets})
    return _digest(normalized)


def require_worker(module: str, args: Sequence[str]) -> None:
    root, token = os.environ.get(ROOT_ENV), os.environ.get(TOKEN_ENV)
    if not root or not token:
        raise JobStopped(
            "Use pcbsmith board-job run with the existing job root; no unsupervised board CLI"
        )
    job = BoardJob(Path(root))
    ready = job.root / ".pcbsmith" / "job-runs" / token / "worker-ready"
    wait_until = time.monotonic() + 5
    while not ready.is_file():
        job.remaining(token)
        if time.monotonic() >= wait_until:
            raise JobStopped("supervisor did not establish process-tree containment")
        time.sleep(0.02)
    if ready.read_text(encoding="utf-8") != token:
        raise JobStopped("invalid worker containment receipt")
    job.authorize(token, (module, *args))


def _preparation_checkpoint(job: BoardJob, phase: str) -> Callable[[], None]:
    """Poll during hashing without rewriting the ledger for every tiny file.

    Every byte is still hashed. Preparation remains charged to evaluation; the
    unconditional preflight and atomic claim bound this poll, and claim rechecks
    before a worker starts. Worker checks and deadlines are unchanged.
    """
    last_checked = float("-inf")

    def check() -> None:
        nonlocal last_checked
        now = time.monotonic()
        if now - last_checked >= 0.1 or now < last_checked:
            job.preflight(phase)
            last_checked = now

    return check


def run_operation(
    job: BoardJob, module: str, args: Sequence[str], *, profile: str = "standard"
) -> int:
    operation, phase = operation_for(module, args)
    job.preflight(phase)
    identity = input_identity(module, args, check=_preparation_checkpoint(job, phase))
    attempt = job.claim(
        operation=operation,
        phase=phase,
        input_sha256=_digest([identity, profile]),
        command=(module, *args),
    )
    run_dir = job.root / ".pcbsmith" / "job-runs" / attempt.token
    run_dir.mkdir(parents=True)

    def cancelled() -> str | None:
        try:
            job.remaining(attempt.token)
        except (RuntimeError, OSError, ValueError) as exc:
            return str(exc)
        return None

    def emit(event: str, fields: Mapping[str, object]) -> None:
        if event == "process_started":
            job.launched(attempt.token, int(str(fields["pid"])))
            atomic_write(run_dir / "worker-ready", attempt.token.encode())
        with (run_dir / "progress.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": event, "at": time.time(), "fields": fields}) + "\n")

    try:
        gate = VerificationGate(
            gate_id=operation,
            command=(sys.executable, "-B", "-m", module, *args),
            timeout_seconds=min(
                job.remaining(attempt.token),
                EXECUTION_PROFILES[profile].default_gate_timeout_seconds,
            ),
            environment={ROOT_ENV: str(job.root), TOKEN_ENV: attempt.token},
        )
        result = SubprocessGateRunner().run(
            gate,
            profile=EXECUTION_PROFILES[profile],
            output_dir=run_dir,
            emit=emit,
            stop_requested=cancelled,
            require_tree_limit=True,
        )
        data = result.model_dump(mode="json")
        atomic_write(run_dir / "result.json", (json.dumps(data, indent=2) + "\n").encode())
        failed = result.termination != "passed"
        signature = None
        if failed:
            stderr = (
                Path(result.stderr_file).read_text(encoding="utf-8") if result.stderr_file else ""
            )
            # Ignore the storage root while retaining the final actual diagnostic.
            stderr = stderr.replace(str(run_dir), "<attempt>")
            diagnostic = stderr.strip().splitlines()[-1:] or [result.termination]
            signature = _digest([operation, result.termination, diagnostic])
        status: Literal["passed", "failed", "stopped"] = (
            "stopped"
            if result.termination in {"timeout", "interrupted"}
            else "failed"
            if failed
            else "passed"
        )
        job.finish_attempt(attempt.token, status=status, result=data, failure_signature=signature)
        print(
            json.dumps(
                {
                    "operation": operation,
                    "termination": result.termination,
                    "job_status": job.snapshot().status,
                    "evidence": str(run_dir),
                }
            )
        )
        return 2 if failed or job.snapshot().status == "stopped" else 0
    except BaseException:
        try:
            job.finish_attempt(
                attempt.token, status="stopped", result={"error": "supervisor interrupted"}
            )
        except JobStopped:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in (
        "start",
        "status",
        "correct",
        "cancel",
        "resume",
        "finish",
        "run",
        "diagnose-start",
        "diagnose-complete",
        "continue-authorized",
        "authorize-local-correction",
        "authorize-inspection-completion",
        "complete-inspection",
        "resolve-predesign-policy-omission",
        "resolve-native-preparation-input",
        "resolve-placement-rounding-mismatch",
    ):
        p = sub.add_parser(action)
        p.add_argument("root", type=Path, help="stable board workspace, never an attempt directory")
        if action == "start":
            p.add_argument("--complexity", choices=tuple(DEFAULT_SECONDS), default="simple")
            p.add_argument("--rationale", required=True)
            p.add_argument(
                "--evaluation-seconds",
                type=float,
                default=1200,
                help="separate evaluation allowance; never a combined job limit",
            )
            p.add_argument(
                "--execution-seconds",
                type=float,
                help="supervised execution allowance including verification reserve",
            )
        if action == "correct":
            p.add_argument("--reason", required=True)
            p.add_argument("--change", required=True)
            p.add_argument("--escalation", action="store_true")
        if action == "authorize-local-correction":
            p.add_argument("--authorization-reference", required=True)
            p.add_argument("--evidence", type=Path, required=True)
        if action == "authorize-inspection-completion":
            p.add_argument("--request", type=Path, required=True)
        if action == "complete-inspection":
            p.add_argument("--decisions", type=Path, required=True)
            p.add_argument("--resume-failure-sha256")
        if action == "continue-authorized":
            p.add_argument("--request", type=Path, required=True)
        if action == "resolve-predesign-policy-omission":
            p.add_argument("--token", required=True)
            p.add_argument("--policy", type=Path, required=True)
        if action in {"resolve-placement-rounding-mismatch", "resolve-native-preparation-input"}:
            p.add_argument("--token", required=True)
        if action == "diagnose-complete":
            p.add_argument("--assessment", type=Path, required=True)
        if action in {"cancel", "resume", "finish", "diagnose-start"}:
            p.add_argument("--reason", required=True)
        if action == "run":
            p.add_argument("--module", choices=MODULES, default="pcbsmith.cli")
            p.add_argument("--profile", choices=tuple(EXECUTION_PROFILES), default="standard")
            p.add_argument("--args", nargs=argparse.REMAINDER, required=True)
    a = parser.parse_args(argv)
    try:
        job = BoardJob(a.root)
        if a.action == "authorize-inspection-completion":
            from pcbsmith.inspection_completion import InspectionCompletionRequest

            print(
                json.dumps(
                    job.authorize_inspection_completion(
                        InspectionCompletionRequest.model_validate_json(a.request.read_bytes())
                    ),
                    indent=2,
                )
            )
            return 0
        if a.action == "complete-inspection":
            result = job.complete_inspection(
                json.loads(a.decisions.read_bytes()), a.resume_failure_sha256
            )
            print(json.dumps(result, indent=2))
            return 0
        if a.action == "start":
            job.start(
                complexity=a.complexity,
                rationale=a.rationale,
                seconds=a.execution_seconds,
                evaluation_seconds=a.evaluation_seconds,
            )
        elif a.action == "authorize-local-correction":
            job.authorize_local_correction(
                a.authorization_reference, json.loads(a.evidence.read_bytes())
            )
        elif a.action == "continue-authorized":
            job.continue_authorized(ContinuationRequest.model_validate_json(a.request.read_bytes()))
        elif a.action == "resolve-predesign-policy-omission":
            job.resolve_predesign_policy_omission(token=a.token, policy_file=a.policy)
        elif a.action == "resolve-native-preparation-input":
            job.resolve_native_preparation_input(token=a.token)
        elif a.action == "resolve-placement-rounding-mismatch":
            job.resolve_placement_rounding_mismatch(token=a.token)
        elif a.action == "diagnose-start":
            job.begin_diagnostic(a.reason)
        elif a.action == "diagnose-complete":
            job.complete_diagnostic(
                DiagnosticRecommendation.model_validate_json(a.assessment.read_bytes())
            )
        elif a.action == "correct":
            job.correction(reason=a.reason, change=a.change, escalation=a.escalation)
        elif a.action == "resume":
            job.resume(a.reason)
        elif a.action in {"cancel", "finish"}:
            job.stop(a.reason, finished=a.action == "finish")
        elif a.action == "run":
            return run_operation(job, a.module, a.args, profile=a.profile)
        snapshot = job.snapshot()
        print(
            json.dumps(
                {
                    **snapshot.model_dump(mode="json"),
                    "timing": snapshot.timing_usage(snapshot.last_seen),
                },
                indent=2,
            )
        )
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"board job stopped: {exc}", file=sys.stderr)
        return 2


def _validate_routing_backend_transition(
    root: Path,
    attempts: list[Attempt],
    request: ContinuationRequest,
    command: Sequence[str] | None = None,
) -> None:
    from pcbsmith.kicad.freerouting_production import FreeroutingProductionConfig
    from pcbsmith.operations.file_transaction import project_path

    assert request.routing_backend_config is not None
    config = project_path(root, request.routing_backend_config)
    if hashlib.sha256(config.read_bytes()).hexdigest() != request.resolved_evidence.get(
        request.routing_backend_config
    ):
        raise JobStopped("routing backend configuration changed")
    FreeroutingProductionConfig.model_validate_json(config.read_bytes()).preflight()
    previous = [a for a in attempts if a.operation == "routing"]
    if not previous or any("--freerouting-config" in a.command for a in previous):
        raise JobStopped("backend transition requires a native-only predecessor")
    if command is not None:
        if (
            "--freerouting-config" not in command
            or Path(command[command.index("--freerouting-config") + 1]).resolve() != config
        ):
            raise JobStopped("routing command differs from the authorized backend")


if __name__ == "__main__":
    raise SystemExit(main())
