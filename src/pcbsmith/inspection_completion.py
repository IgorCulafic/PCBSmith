"""Finite inspection-only successors for finished jobs; never a build lease."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.operations.file_transaction import atomic_write, project_path
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pcbsmith.board_job import BoardJob
    from pcbsmith.production_workflow import GenerationTransactionManifest


class InspectionCompletionRequest(SemanticIrModel):
    schema_id: Literal["pcbsmith-inspection-completion-request-v1"] = (
        "pcbsmith-inspection-completion-request-v1"
    )
    authorization_reference: str = Field(min_length=1)
    transaction_root: str = Field(min_length=1)
    predecessor_pointer_sha256: str
    predecessor_manifest_sha256: str
    successor_generation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    evaluation_seconds: float = Field(gt=0, le=3600)
    execution_seconds: float = Field(gt=0, le=600)
    reviewer: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid(self) -> Self:
        for value in (self.authorization_reference, self.reviewer, self.mechanism):
            if not value.strip():
                raise ValueError("inspection completion requires recorded authority and reviewer")
        require_sha256(self.predecessor_pointer_sha256, "predecessor pointer")
        require_sha256(self.predecessor_manifest_sha256, "predecessor review")
        return self


def _finished_state(job: BoardJob) -> dict[str, Any]:
    # Read without BoardJob._access: even reserializing the closed ledger is forbidden.
    from pcbsmith.board_job import JobState, _digest

    envelope = json.loads(job.path.read_bytes())
    state = JobState.model_validate(envelope["state"])
    if (
        envelope["sha256"] != _digest(envelope["state"])
        or state.root != str(job.root)
        or state.status != "finished"
        or any(a.status == "running" for a in state.attempts)
    ):
        raise ValueError("inspection completion requires the intact finished original job")
    return state.model_dump(mode="json")


def authorize(job: BoardJob, request: InspectionCompletionRequest) -> dict[str, Any]:
    from pcbsmith.production_workflow import resolve_current_generation
    from pcbsmith.review.visual_package import VisualReviewManifest

    with job._locked():
        _finished_state(job)
        target = project_path(job.root, request.transaction_root)
        current = resolve_current_generation(target)
        review = target / "generations" / current.generation_id / "review/manifest.json"
        if (
            file_sha256(target / "CURRENT.json") != request.predecessor_pointer_sha256
            or file_sha256(review) != request.predecessor_manifest_sha256
        ):
            raise ValueError("inspection completion targets stale predecessor inputs")
        visual = VisualReviewManifest.model_validate_json(review.read_bytes())
        if not any(a.inspection == "uninspected" for a in visual.artifacts if a.required):
            raise ValueError("no missing required inspection decisions to complete")
        state_dir = job.root / ".pcbsmith/inspection-completion"
        if state_dir.exists():
            raise ValueError("inspection completion already authorized; no automatic renewal")
        now = job._now()
        record = dict(
            request=request.model_dump(mode="json"),
            started_at=now,
            evaluation_deadline=now + request.evaluation_seconds,
            job_ledger_sha256=file_sha256(job.path),
            predecessor_transaction_fingerprint=current.transaction_fingerprint,
        )
        state_dir.mkdir()
        atomic_write(state_dir / "authorization.json", json.dumps(record, indent=2).encode())
        return record


class InspectionCompletionPermit:
    """Narrow commit capability; every payload is checked against the predecessor."""

    expected_package_status: str
    expected_report_bytes: bytes

    def __init__(
        self, job: BoardJob, decisions: dict[str, Any], resume_failure_sha256: str | None = None
    ) -> None:
        from pcbsmith.production_workflow import resolve_current_generation
        from pcbsmith.review.visual_package import VisualReviewManifest

        self.job = job
        self.directory = job.root / ".pcbsmith/inspection-completion"
        self.authorization_file = self.directory / "authorization.json"
        self.authorization = json.loads(self.authorization_file.read_bytes())
        self.authorization_sha256 = file_sha256(self.authorization_file)
        self.request = InspectionCompletionRequest.model_validate(self.authorization["request"])
        self.root = project_path(job.root, self.request.transaction_root)
        self.current = resolve_current_generation(self.root)
        self.source_root = self.root / "generations" / self.current.generation_id
        self.review_file = self.source_root / "review/manifest.json"
        self.visual = VisualReviewManifest.model_validate_json(self.review_file.read_bytes())
        self.decisions = decisions
        self.started_at = job._now()
        self.prior_execution_seconds = 0.0
        self.resumed = resume_failure_sha256 is not None
        if self.resumed:
            failure_path = self.directory / "failure.json"
            attempt_path = self.directory / "attempt.json"
            previous = json.loads(attempt_path.read_bytes())
            failure = json.loads(failure_path.read_bytes())
            if (
                file_sha256(failure_path) != resume_failure_sha256
                or failure["error"]
                != "ValueError: current generation has no component review execution"
                or previous["decisions"] != decisions
                or (self.directory / "resumption.json").exists()
                or (self.directory / "result.json").exists()
            ):
                raise ValueError("only one exact diagnosed legacy-metadata resumption is permitted")
            self.prior_execution_seconds = failure["failed_at"] - previous["started_at"]
            if self.prior_execution_seconds < 0:
                raise ValueError("inspection execution history is inconsistent")
        self.evaluation_seconds = (
            self.started_at - self.authorization["started_at"] - self.prior_execution_seconds
        )
        if not 0 <= self.evaluation_seconds <= self.request.evaluation_seconds:
            raise ValueError("inspection evaluation allowance exhausted")
        remaining = self.request.execution_seconds - self.prior_execution_seconds
        if remaining <= 0:
            raise ValueError("inspection execution allowance exhausted")
        self.deadline = self.started_at + remaining
        self.check_sources()
        artifact_map = {a.artifact_id: a for a in self.visual.artifacts}
        missing = {
            a.artifact_id
            for a in self.visual.artifacts
            if a.required and a.inspection == "uninspected"
        }
        uninspected = {
            a.artifact_id for a in self.visual.artifacts if a.inspection == "uninspected"
        }
        if not missing or not missing <= set(decisions) <= uninspected:
            raise ValueError(
                "decisions must cover missing required artifacts without reopening others"
            )
        for key, decision in decisions.items():
            if (
                not isinstance(decision, dict)
                or set(decision) != {"sha256", "inspection", "findings"}
                or decision["sha256"] != artifact_map[key].sha256
                or decision["inspection"] not in {"accepted", "attention_required"}
                or not isinstance(decision["findings"], list)
                or not decision["findings"]
                or any(not isinstance(n, str) or not n.strip() for n in decision["findings"])
            ):
                raise ValueError("inspection decision lacks exact artifact or actual observations")
        # Claims refer to the original retained images, never replacement render outputs.
        for artifact in self.visual.artifacts:
            path = project_path(self.source_root / "review", artifact.relative_path)
            if artifact.state != "generated" or file_sha256(path) != artifact.sha256:
                raise ValueError("inspection artifact is missing or stale")
        with job._locked():
            attempt = self.directory / ("resumption.json" if self.resumed else "attempt.json")
            if attempt.exists():
                raise ValueError("inspection completion already attempted; no repeated completion")
            atomic_write(
                attempt,
                json.dumps(
                    dict(
                        started_at=self.started_at,
                        deadline=self.deadline,
                        decisions=decisions,
                        resumed_failure_sha256=resume_failure_sha256,
                        prior_execution_seconds=self.prior_execution_seconds,
                    ),
                    indent=2,
                ).encode(),
            )

    def check_sources(self) -> None:
        from pcbsmith.production_workflow import resolve_current_generation

        _finished_state(self.job)
        if self.job._now() > self.deadline:
            raise ValueError("inspection execution allowance exhausted")
        if file_sha256(self.authorization_file) != self.authorization_sha256:
            raise ValueError("inspection authorization changed")
        if file_sha256(self.job.path) != self.authorization["job_ledger_sha256"]:
            raise ValueError("finished job ledger changed")
        if file_sha256(self.root / "CURRENT.json") != self.request.predecessor_pointer_sha256:
            raise ValueError("inspection predecessor pointer changed")
        current = resolve_current_generation(self.root)
        if (
            current.transaction_fingerprint
            != self.authorization["predecessor_transaction_fingerprint"]
            or file_sha256(self.review_file) != self.request.predecessor_manifest_sha256
        ):
            raise ValueError("inspection predecessor changed")

    def validate_commit(
        self, root: Path, manifest: GenerationTransactionManifest, payloads: Mapping[str, bytes]
    ) -> None:
        from pcbsmith.review.visual_package import VisualReviewManifest

        self.check_sources()
        if (
            root.resolve() != self.root
            or manifest.stage != self.current.stage
            or manifest.project_id != self.current.project_id
            or manifest.generation_id != self.request.successor_generation_id
            or manifest.generation_sha256 != self.generation_sha256
        ):
            raise ValueError("inspection commit scope differs from authorization")
        original = {a.relative_path: a for a in self.current.artifacts}
        if set(payloads) != set(original):
            raise ValueError("inspection completion cannot add or remove generation artifacts")
        allowed = {"review/manifest.json", "review/review-report.md"}
        from hashlib import sha256

        for name, payload in payloads.items():
            if name not in allowed and sha256(payload).hexdigest() != original[name].content_sha256:
                raise ValueError("inspection completion cannot change CAD, checks or renders")
        updated = VisualReviewManifest.model_validate_json(payloads["review/manifest.json"])
        expected = self.visual.model_dump(mode="json", by_alias=True)
        observed = updated.model_dump(mode="json", by_alias=True)
        # Only immutable path retargeting and recorded inspection fields may differ.
        board = next(a for a in self.current.artifacts if a.role == "board")
        expected_board = self.root / "generations" / manifest.generation_id / board.relative_path
        expected["board_file"] = str(expected_board)
        if self.visual.routing_evidence is not None:
            from pcbsmith.kicad.routing_evidence import retarget_saved_board_routing_evidence

            expected["routing_evidence"] = retarget_saved_board_routing_evidence(
                self.visual.routing_evidence, expected_board
            ).model_dump(mode="json")
        for artifact in expected["artifacts"]:
            decision = self.decisions.get(artifact["artifact_id"])
            if decision:
                artifact.update(
                    inspection=decision["inspection"],
                    findings=decision["findings"],
                    reviewer=self.request.reviewer,
                    inspection_mechanism=self.request.mechanism,
                )
        # Reuse the inspection owner's exact status derivation, not caller-provided success.
        expected["package_status"] = self.expected_package_status
        if observed != expected:
            raise ValueError("inspection successor changed fields beyond authorized decisions")
        if payloads["review/review-report.md"] != self.expected_report_bytes:
            raise ValueError("inspection report differs from shared owner output")

    @property
    def generation_sha256(self) -> str:
        return fingerprint(dict(authorization=self.authorization_sha256, decisions=self.decisions))


def complete(
    job: BoardJob, decisions: dict[str, Any], resume_failure_sha256: str | None = None
) -> dict[str, Any]:
    from pcbsmith.production_workflow import inspect_current_placement_review

    permit = InspectionCompletionPermit(job, decisions, resume_failure_sha256)
    try:
        result = inspect_current_placement_review(
            transaction_root=permit.root,
            generation_id=permit.request.successor_generation_id,
            generation_sha256=permit.generation_sha256,
            reviewer=permit.request.reviewer,
            mechanism=permit.request.mechanism,
            decisions={
                key: (value["inspection"], tuple(value["findings"]))
                for key, value in decisions.items()
            },
            inspection_completion=permit,
        )
        record = dict(
            status=result.transaction.manifest.status,
            authorization_sha256=permit.authorization_sha256,
            original_job_ledger_sha256=permit.authorization["job_ledger_sha256"],
            successor=result.transaction.model_dump(mode="json"),
            board_sha256=result.review_manifest.board_sha256,
            copper_sha256=result.review_manifest.copper_sha256,
            inspection_status=result.review_manifest.package_status,
            evaluation_seconds=permit.evaluation_seconds,
            execution_seconds=permit.prior_execution_seconds + job._now() - permit.started_at,
            job_history_preserved=file_sha256(job.path)
            == permit.authorization["job_ledger_sha256"],
        )
        atomic_write(permit.directory / "result.json", json.dumps(record, indent=2).encode())
        if record["status"] != "committed":
            raise RuntimeError("inspection successor rolled back; result and predecessor retained")
        return record
    except Exception as exc:
        atomic_write(
            permit.directory / ("resumption-failure.json" if permit.resumed else "failure.json"),
            json.dumps(
                dict(error=f"{type(exc).__name__}: {exc}", failed_at=job._now()), indent=2
            ).encode(),
        )
        raise
