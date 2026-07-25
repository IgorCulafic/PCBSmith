"""Phase 17 production gates, bounded execution, transactions, and route replay."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.applicability_execution import (
    ProjectApplicabilityExecutionManifest,
    ProjectExecutionAuthority,
)
from pcbsmith.execution import (
    ExecutionProfile,
    WorkBudgetLedger,
)
from pcbsmith.kicad.astar_router import BoardRouteResult, route_board
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.negotiated_board import (
    ExactRouteChecker,
    ExactRouteCheckResult,
)
from pcbsmith.kicad.routing_evidence import (
    KiCadDrcEvidence,
    RoutingArtifactState,
    SavedBoardRoutingEvidence,
    inspect_kicad_drc_report,
    inspect_saved_board_routing,
    retarget_kicad_drc_evidence,
    retarget_saved_board_routing_evidence,
)
from pcbsmith.project_engineering_gate_ir import (
    InventoryStatus,
    ProjectEngineeringGateResult,
    ProjectGateOutcome,
)
from pcbsmith.prompt_examiner import PromptExamination
from pcbsmith.review.visual_package import (
    InspectionState,
    VisualReviewManifest,
    record_visual_inspection,
    write_visual_review_manifest,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.routing_ir import RoutingPassTelemetry
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.workflow_authority import (
    ProjectContextBundle,
    ProjectContextStatus,
    WorkflowStage,
)
from pcbsmith.workflow_feasibility import (
    ConceptDriftReport,
    FeasibilityOutcome,
    PreRouteFeasibilityReport,
)

ArtifactRole = Literal[
    "prompt",
    "brief",
    "concept",
    "schematic",
    "board",
    "route",
    "evidence",
    "review",
    "verification",
    "other",
]


class NativeAlgorithm(StrEnum):
    PLACEMENT = "placement"
    ROUTING = "routing"
    RENDERING = "rendering"
    VERIFICATION = "verification"


class AlgorithmBudgetBinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-algorithm-budget-binding"] = "pcbsmith-algorithm-budget-binding"
    schema_version: Literal[1] = 1
    profile_name: Literal["quick", "standard", "deep"]
    algorithm: NativeAlgorithm
    maximum_expansions: int = Field(gt=0)
    maximum_passes: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    heartbeat_seconds: float = Field(gt=0)
    memory_limit_mb: int = Field(gt=0)

    def new_ledger(self) -> WorkBudgetLedger:
        from pcbsmith.execution import DeterministicWorkBudget

        return WorkBudgetLedger(
            DeterministicWorkBudget(
                maximum_expansions=self.maximum_expansions,
                maximum_passes=self.maximum_passes,
            )
        )


def bind_execution_profile(
    profile: ExecutionProfile,
) -> tuple[AlgorithmBudgetBinding, ...]:
    """Bind every native production algorithm to one selected profile."""

    return tuple(
        AlgorithmBudgetBinding(
            profile_name=profile.name,
            algorithm=algorithm,
            maximum_expansions=profile.work_budget.maximum_expansions,
            maximum_passes=profile.work_budget.maximum_passes,
            timeout_seconds=profile.default_gate_timeout_seconds,
            heartbeat_seconds=profile.heartbeat_seconds,
            memory_limit_mb=profile.memory_limit_mb,
        )
        for algorithm in NativeAlgorithm
    )


class AlgorithmStageTelemetry(SemanticIrModel):
    schema_id: Literal["pcbsmith-algorithm-stage-telemetry"] = "pcbsmith-algorithm-stage-telemetry"
    schema_version: Literal[1] = 1
    generation_sha256: str
    algorithm: NativeAlgorithm
    profile_name: Literal["quick", "standard", "deep"]
    termination: Literal[
        "completed",
        "budget_exhausted",
        "timeout",
        "failed",
        "incomplete",
    ]
    expansions: int = Field(ge=0)
    passes: int = Field(ge=0)
    heartbeat_count: int = Field(ge=0)
    checkpoint_sha256: str | None = None
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def telemetry_is_bound(self) -> Self:
        require_sha256(self.generation_sha256, "generation_sha256")
        if self.checkpoint_sha256 is not None:
            require_sha256(self.checkpoint_sha256, "checkpoint_sha256")
        if self.termination == "incomplete" and self.checkpoint_sha256 is None:
            raise ValueError("incomplete telemetry requires a resume checkpoint")
        return self


class NativeStageTimeout(RuntimeError):
    pass


class NativeStageController:
    """Budget and heartbeat handle passed into a native board algorithm."""

    def __init__(
        self,
        *,
        binding: AlgorithmBudgetBinding,
        clock: Callable[[], float] = time.monotonic,
        heartbeat_sink: Callable[[str, Mapping[str, object]], None] | None = None,
    ) -> None:
        self.binding = binding
        self.ledger = binding.new_ledger()
        self._clock = clock
        self._started = clock()
        self._last_heartbeat = self._started
        self._heartbeat_count = 0
        self._checkpoint_sha256: str | None = None
        self._sink = heartbeat_sink or (lambda _event, _fields: None)

    @property
    def heartbeat_count(self) -> int:
        return self._heartbeat_count

    @property
    def checkpoint_sha256(self) -> str | None:
        return self._checkpoint_sha256

    def consume_expansions(self, count: int = 1) -> None:
        self._check_time()
        self.ledger.consume_expansions(count)
        self._emit_heartbeat_if_due("work")

    def consume_pass(self) -> None:
        self._check_time()
        self.ledger.consume_pass()
        self._emit_heartbeat_if_due("pass")

    def heartbeat(
        self,
        boundary: str,
        *,
        checkpoint_sha256: str | None = None,
    ) -> None:
        require_identity(boundary, "heartbeat boundary")
        if checkpoint_sha256 is not None:
            require_sha256(checkpoint_sha256, "checkpoint_sha256")
            self._checkpoint_sha256 = checkpoint_sha256
        self._check_time()
        self._emit(boundary)

    def telemetry(
        self,
        *,
        generation_sha256: str,
        termination: Literal[
            "completed",
            "budget_exhausted",
            "timeout",
            "failed",
            "incomplete",
        ],
        findings: tuple[str, ...] = (),
    ) -> AlgorithmStageTelemetry:
        return AlgorithmStageTelemetry(
            generation_sha256=generation_sha256,
            algorithm=self.binding.algorithm,
            profile_name=self.binding.profile_name,
            termination=termination,
            expansions=self.ledger.expansions,
            passes=self.ledger.passes,
            heartbeat_count=self._heartbeat_count,
            checkpoint_sha256=self._checkpoint_sha256,
            findings=findings,
        )

    def _check_time(self) -> None:
        elapsed = self._clock() - self._started
        if elapsed > self.binding.timeout_seconds:
            raise NativeStageTimeout(
                f"{self.binding.algorithm.value} exceeded {self.binding.timeout_seconds:g} seconds"
            )

    def _emit_heartbeat_if_due(self, boundary: str) -> None:
        if self._clock() - self._last_heartbeat >= self.binding.heartbeat_seconds:
            self._emit(boundary)

    def _emit(self, boundary: str) -> None:
        now = self._clock()
        self._heartbeat_count += 1
        self._last_heartbeat = now
        self._sink(
            "heartbeat",
            {
                "algorithm": self.binding.algorithm.value,
                "profile": self.binding.profile_name,
                "boundary": boundary,
                "elapsed_seconds": now - self._started,
                "expansions": self.ledger.expansions,
                "passes": self.ledger.passes,
                "checkpoint_sha256": self._checkpoint_sha256,
            },
        )


class GenerationArtifact(SemanticIrModel):
    schema_id: Literal["pcbsmith-generation-artifact"] = "pcbsmith-generation-artifact"
    schema_version: Literal[1] = 1
    artifact_id: str
    role: ArtifactRole
    relative_path: str
    content_sha256: str

    @model_validator(mode="after")
    def artifact_is_safe(self) -> Self:
        require_identity(self.artifact_id, "artifact_id")
        require_sha256(self.content_sha256, "content_sha256")
        _safe_relative_path(self.relative_path)
        return self


class GenerationTransactionManifest(SemanticIrModel):
    schema_id: Literal["pcbsmith-generation-transaction"] = "pcbsmith-generation-transaction"
    schema_version: Literal[1] = 1
    project_id: str
    generation_id: str
    generation_sha256: str
    stage: WorkflowStage
    status: Literal["staged", "committed", "rolled_back"]
    artifacts: tuple[GenerationArtifact, ...]
    previous_current_sha256: str | None = None
    reason: str | None = None
    transaction_fingerprint: str

    @model_validator(mode="after")
    def transaction_is_replay_bound(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_identity(self.generation_id, "generation_id")
        require_sha256(self.generation_sha256, "generation_sha256")
        if self.previous_current_sha256 is not None:
            require_sha256(self.previous_current_sha256, "previous_current_sha256")
        artifacts = tuple(sorted(self.artifacts, key=lambda item: item.artifact_id))
        ids = tuple(item.artifact_id for item in artifacts)
        paths = tuple(item.relative_path for item in artifacts)
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ValueError("transaction artifact identities and paths must be unique")
        if self.status == "rolled_back":
            if self.reason is None:
                raise ValueError("rolled-back transaction requires a reason")
            require_identity(self.reason, "reason")
        elif self.reason is not None:
            raise ValueError("only a rolled-back transaction may carry a reason")
        object.__setattr__(self, "artifacts", artifacts)
        require_sha256(self.transaction_fingerprint, "transaction_fingerprint")
        payload = self.model_dump(mode="json", exclude={"transaction_fingerprint"})
        if self.transaction_fingerprint != fingerprint(payload):
            raise ValueError("generation transaction fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        generation_id: str,
        generation_sha256: str,
        stage: WorkflowStage,
        status: Literal["staged", "committed", "rolled_back"],
        artifacts: tuple[GenerationArtifact, ...],
        previous_current_sha256: str | None = None,
        reason: str | None = None,
    ) -> GenerationTransactionManifest:
        fields: dict[str, Any] = {
            "project_id": project_id,
            "generation_id": generation_id,
            "generation_sha256": generation_sha256,
            "stage": stage,
            "status": status,
            "artifacts": tuple(sorted(artifacts, key=lambda item: item.artifact_id)),
            "previous_current_sha256": previous_current_sha256,
            "reason": reason,
        }
        provisional = cls.model_construct(**fields, transaction_fingerprint="0" * 64)
        return cls(
            **fields,
            transaction_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"transaction_fingerprint"})
            ),
        )


class GenerationTransactionResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-generation-transaction-result"] = (
        "pcbsmith-generation-transaction-result"
    )
    schema_version: Literal[1] = 1
    manifest: GenerationTransactionManifest
    current_generation_before: str | None
    current_generation_after: str | None
    retained_directory: str


class PlacementReviewTransactionResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-review-transaction-result"] = (
        "pcbsmith-placement-review-transaction-result"
    )
    schema_version: Literal[1] = 1
    transaction: GenerationTransactionResult
    review_manifest: VisualReviewManifest


class RoutedReviewTransactionResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-routed-review-transaction-result"] = (
        "pcbsmith-routed-review-transaction-result"
    )
    schema_version: Literal[1] = 1
    transaction: GenerationTransactionResult
    review_manifest: VisualReviewManifest
    routing_evidence: SavedBoardRoutingEvidence
    drc_evidence: KiCadDrcEvidence


def prepare_generation_transaction(
    *,
    project_id: str,
    generation_id: str,
    generation_sha256: str,
    stage: WorkflowStage,
    payloads: Mapping[str, bytes],
    roles: Mapping[str, ArtifactRole],
    previous_current_sha256: str | None = None,
) -> GenerationTransactionManifest:
    """Create a staged manifest whose artifacts all share one generation."""

    if set(payloads) != set(roles):
        raise ValueError("transaction payload and role paths must match exactly")
    artifacts = tuple(
        GenerationArtifact(
            artifact_id=f"{generation_id}.{index:04d}",
            role=roles[path],
            relative_path=path,
            content_sha256=_bytes_sha256(payloads[path]),
        )
        for index, path in enumerate(sorted(payloads), start=1)
    )
    return GenerationTransactionManifest.build(
        project_id=project_id,
        generation_id=generation_id,
        generation_sha256=generation_sha256,
        stage=stage,
        status="staged",
        artifacts=artifacts,
        previous_current_sha256=previous_current_sha256,
    )


def persist_placement_and_generate_review(
    *,
    transaction_root: Path,
    project_id: str,
    generation_id: str,
    generation_sha256: str,
    board_relative_path: str,
    board_payload: bytes,
    review_generator: Callable[[Path, Path], VisualReviewManifest],
) -> PlacementReviewTransactionResult:
    """Persist a placement board and invoke its canonical review in one revision.

    The callback receives an isolated saved board and output root. It must
    return a placement-stage visual manifest. All emitted review files and the
    board are then committed under one immutable generation identity.
    """

    _safe_relative_path(board_relative_path)
    root = transaction_root.resolve()
    work_parent = root / ".review-work"
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{generation_id}-", dir=work_parent) as temporary:
        work_root = Path(temporary)
        board_file = work_root / PurePosixPath(board_relative_path)
        _require_descendant(work_root, board_file)
        board_file.parent.mkdir(parents=True, exist_ok=True)
        board_file.write_bytes(board_payload)
        review_output = work_root / "review-output"
        generated_manifest = review_generator(board_file, review_output)
        board_sha256 = _bytes_sha256(board_payload)
        if generated_manifest.stage != "placement":
            raise ValueError("automatic pre-route review must use placement stage")
        if generated_manifest.board_sha256 != board_sha256:
            raise ValueError("review manifest does not bind the saved placement board")

        final_board = root / "generations" / generation_id / PurePosixPath(board_relative_path)
        retained_manifest = generated_manifest.model_copy(
            update={
                "board_file": str(final_board),
                "routing_evidence": (
                    None
                    if generated_manifest.routing_evidence is None
                    else retarget_saved_board_routing_evidence(
                        generated_manifest.routing_evidence,
                        final_board,
                    )
                ),
            }
        )
        payloads: dict[str, bytes] = {board_relative_path: board_payload}
        roles: dict[str, ArtifactRole] = {board_relative_path: "board"}
        if review_output.exists():
            for path in sorted(item for item in review_output.rglob("*") if item.is_file()):
                relative = PurePosixPath("review") / path.relative_to(review_output).as_posix()
                relative_text = relative.as_posix()
                payloads[relative_text] = path.read_bytes()
                roles[relative_text] = "review"
        manifest_path = "review/manifest.json"
        payloads[manifest_path] = (
            json.dumps(
                retained_manifest.model_dump(mode="json", by_alias=True),
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        roles[manifest_path] = "review"
        _, previous_current_sha256 = _read_current_pointer(root / "CURRENT.json")
        transaction = prepare_generation_transaction(
            project_id=project_id,
            generation_id=generation_id,
            generation_sha256=generation_sha256,
            stage=WorkflowStage.PLACEMENT,
            payloads=payloads,
            roles=roles,
            previous_current_sha256=previous_current_sha256,
        )
        result = commit_generation_transaction(
            transaction_root=root,
            manifest=transaction,
            payloads=payloads,
        )
    return PlacementReviewTransactionResult(
        transaction=result,
        review_manifest=retained_manifest,
    )


def persist_routed_board_and_generate_review(
    *,
    transaction_root: Path,
    project_id: str,
    generation_id: str,
    generation_sha256: str,
    board_relative_path: str,
    board_payload: bytes,
    review_generator: Callable[[Path, Path], VisualReviewManifest],
    drc_generator: Callable[[Path, Path], None],
) -> RoutedReviewTransactionResult:
    """Persist one routed board, exact DRC, and final review atomically.

    The candidate is rejected before publication unless objective saved-board
    inspection finds copper carriers for every routable net, the retained
    KiCad JSON DRC is clean, and the generated review is a final-stage package
    bound to that exact board revision.
    """

    _safe_relative_path(board_relative_path)
    root = transaction_root.resolve()
    work_parent = root / ".review-work"
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{generation_id}-routed-", dir=work_parent
    ) as temporary:
        work_root = Path(temporary)
        board_file = work_root / PurePosixPath(board_relative_path)
        _require_descendant(work_root, board_file)
        board_file.parent.mkdir(parents=True, exist_ok=True)
        board_file.write_bytes(board_payload)

        routing_evidence = inspect_saved_board_routing(board_file)
        if routing_evidence.state is not RoutingArtifactState.ROUTED_CANDIDATE:
            raise ValueError(
                "routed transaction requires complete saved-board carrier "
                f"coverage; observed {routing_evidence.state.value}"
            )

        verification_output = work_root / "verification-output"
        verification_output.mkdir(parents=True)
        drc_report = verification_output / "drc.json"
        drc_generator(board_file, drc_report)
        if not drc_report.is_file():
            raise ValueError("DRC generator did not retain its JSON report")
        drc_evidence = inspect_kicad_drc_report(drc_report)
        if not drc_evidence.clean:
            raise ValueError(
                "routed transaction requires a clean KiCad DRC report: "
                f"{drc_evidence.violation_count} violations, "
                f"{drc_evidence.unconnected_item_count} unconnected items, "
                f"{drc_evidence.schematic_parity_count} parity findings"
            )

        review_output = work_root / "review-output"
        generated_manifest = review_generator(board_file, review_output)
        if generated_manifest.stage != "final":
            raise ValueError("routed review must use final stage")
        if generated_manifest.board_sha256 != routing_evidence.board_sha256:
            raise ValueError("review manifest does not bind the saved routed board")
        manifest_routing = generated_manifest.routing_evidence
        if manifest_routing is None:
            raise ValueError("final review omitted saved-board routing evidence")
        if (
            manifest_routing.board_sha256 != routing_evidence.board_sha256
            or manifest_routing.state is not RoutingArtifactState.ROUTED_CANDIDATE
            or manifest_routing.evidence_fingerprint != routing_evidence.evidence_fingerprint
        ):
            raise ValueError("final review routing evidence does not equal exact board inspection")

        final_root = root / "generations" / generation_id
        final_board = final_root / PurePosixPath(board_relative_path)
        final_drc_report = final_root / "verification" / "drc.json"
        retained_routing = retarget_saved_board_routing_evidence(
            routing_evidence,
            final_board,
        )
        retained_drc = retarget_kicad_drc_evidence(
            drc_evidence,
            final_drc_report,
        )
        retained_manifest = generated_manifest.model_copy(
            update={
                "board_file": str(final_board),
                "routing_evidence": retained_routing,
            }
        )

        payloads: dict[str, bytes] = {board_relative_path: board_payload}
        roles: dict[str, ArtifactRole] = {board_relative_path: "board"}
        if review_output.exists():
            for path in sorted(item for item in review_output.rglob("*") if item.is_file()):
                relative = PurePosixPath("review") / path.relative_to(review_output).as_posix()
                relative_text = relative.as_posix()
                payloads[relative_text] = path.read_bytes()
                roles[relative_text] = "review"
        payloads["review/manifest.json"] = (
            json.dumps(
                retained_manifest.model_dump(mode="json", by_alias=True),
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        roles["review/manifest.json"] = "review"
        payloads["verification/drc.json"] = drc_report.read_bytes()
        roles["verification/drc.json"] = "verification"
        payloads["verification/routing-evidence.json"] = (
            json.dumps(
                retained_routing.model_dump(mode="json", by_alias=True),
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        roles["verification/routing-evidence.json"] = "evidence"
        payloads["verification/drc-evidence.json"] = (
            json.dumps(
                retained_drc.model_dump(mode="json", by_alias=True),
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        roles["verification/drc-evidence.json"] = "evidence"

        _, previous_current_sha256 = _read_current_pointer(root / "CURRENT.json")
        transaction = prepare_generation_transaction(
            project_id=project_id,
            generation_id=generation_id,
            generation_sha256=generation_sha256,
            stage=WorkflowStage.REVIEW,
            payloads=payloads,
            roles=roles,
            previous_current_sha256=previous_current_sha256,
        )
        result = commit_generation_transaction(
            transaction_root=root,
            manifest=transaction,
            payloads=payloads,
        )
    return RoutedReviewTransactionResult(
        transaction=result,
        review_manifest=retained_manifest,
        routing_evidence=retained_routing,
        drc_evidence=retained_drc,
    )


def inspect_current_placement_review(
    *,
    transaction_root: Path,
    generation_id: str,
    generation_sha256: str,
    reviewer: str,
    mechanism: str,
    decisions: dict[str, tuple[InspectionState, tuple[str, ...]]],
) -> PlacementReviewTransactionResult:
    """Record review decisions as a new immutable generation revision."""

    root = transaction_root.resolve()
    current = resolve_current_generation(root)
    current_dir = root / "generations" / current.generation_id
    review_artifact = next(
        (item for item in current.artifacts if item.relative_path == "review/manifest.json"),
        None,
    )
    if review_artifact is None:
        raise ValueError("current generation has no canonical review manifest")
    work_parent = root / ".review-work"
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{generation_id}-inspection-", dir=work_parent
    ) as temporary:
        work_root = Path(temporary)
        roles: dict[str, ArtifactRole] = {}
        for artifact in current.artifacts:
            source = current_dir / PurePosixPath(artifact.relative_path)
            destination = work_root / PurePosixPath(artifact.relative_path)
            _require_descendant(work_root, destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            roles[artifact.relative_path] = artifact.role
        updated_manifest = record_visual_inspection(
            work_root / "review" / "manifest.json",
            reviewer=reviewer,
            mechanism=mechanism,
            decisions=decisions,
        )
        board_artifacts = tuple(item for item in current.artifacts if item.role == "board")
        if len(board_artifacts) != 1:
            raise ValueError("placement inspection requires exactly one canonical board artifact")
        board_relative_path = board_artifacts[0].relative_path
        updated_manifest = updated_manifest.model_copy(
            update={
                "board_file": str(
                    root / "generations" / generation_id / PurePosixPath(board_relative_path)
                ),
                "routing_evidence": (
                    None
                    if updated_manifest.routing_evidence is None
                    else retarget_saved_board_routing_evidence(
                        updated_manifest.routing_evidence,
                        (root / "generations" / generation_id / PurePosixPath(board_relative_path)),
                    )
                ),
            }
        )
        write_visual_review_manifest(work_root / "review" / "manifest.json", updated_manifest)
        payloads = {
            path.relative_to(work_root).as_posix(): path.read_bytes()
            for path in sorted(item for item in work_root.rglob("*") if item.is_file())
        }
        for path in payloads:
            roles.setdefault(path, "review")
        _, previous_current_sha256 = _read_current_pointer(root / "CURRENT.json")
        staged = prepare_generation_transaction(
            project_id=current.project_id,
            generation_id=generation_id,
            generation_sha256=generation_sha256,
            stage=WorkflowStage.PLACEMENT,
            payloads=payloads,
            roles=roles,
            previous_current_sha256=previous_current_sha256,
        )
        result = commit_generation_transaction(
            transaction_root=root,
            manifest=staged,
            payloads=payloads,
        )
    return PlacementReviewTransactionResult(
        transaction=result,
        review_manifest=updated_manifest,
    )


def commit_generation_transaction(
    *,
    transaction_root: Path,
    manifest: GenerationTransactionManifest,
    payloads: Mapping[str, bytes],
    before_pointer_swap: Callable[[], None] | None = None,
) -> GenerationTransactionResult:
    """Publish one immutable generation by atomically swapping a small pointer.

    A failed generation is retained under ``failed`` for diagnosis. The
    previously committed ``CURRENT.json`` is never modified until every new
    artifact and the final manifest have been written and verified.
    """

    if manifest.status != "staged":
        raise ValueError("only a staged transaction may be committed")
    by_path = {item.relative_path: item for item in manifest.artifacts}
    if set(by_path) != set(payloads):
        raise ValueError("payload paths do not equal the staged manifest")
    for path, payload in payloads.items():
        if _bytes_sha256(payload) != by_path[path].content_sha256:
            raise ValueError(f"payload digest changed after staging: {path}")

    root = transaction_root.resolve()
    staging_parent = root / ".staging"
    generations_parent = root / "generations"
    failed_parent = root / "failed"
    staging = staging_parent / manifest.generation_id
    committed_dir = generations_parent / manifest.generation_id
    failed_dir = failed_parent / manifest.generation_id
    temporary_pointer = root / ".CURRENT.json.tmp"
    for candidate in (staging, committed_dir, failed_dir):
        _require_descendant(root, candidate)
        if candidate.exists():
            raise ValueError(f"generation path already exists: {candidate}")
    current_path = root / "CURRENT.json"
    current_before, current_payload_sha256 = _read_current_pointer(current_path)
    if manifest.previous_current_sha256 != current_payload_sha256:
        raise ValueError("staged transaction does not bind the current generation pointer")

    staging.mkdir(parents=True)
    promoted = False
    try:
        for relative_path, payload in sorted(payloads.items()):
            target = staging / PurePosixPath(relative_path)
            _require_descendant(staging, target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        for artifact in manifest.artifacts:
            retained = staging / PurePosixPath(artifact.relative_path)
            if _file_sha256(retained) != artifact.content_sha256:
                raise RuntimeError(f"staged artifact verification failed: {artifact.relative_path}")
        committed = GenerationTransactionManifest.build(
            project_id=manifest.project_id,
            generation_id=manifest.generation_id,
            generation_sha256=manifest.generation_sha256,
            stage=manifest.stage,
            status="committed",
            artifacts=manifest.artifacts,
            previous_current_sha256=manifest.previous_current_sha256,
        )
        _write_manifest(staging / "transaction.json", committed)
        generations_parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, committed_dir)
        promoted = True
        if before_pointer_swap is not None:
            before_pointer_swap()
        pointer_payload = _canonical_bytes(
            {
                "schema": "pcbsmith-current-generation-v1",
                "generation_id": committed.generation_id,
                "generation_sha256": committed.generation_sha256,
                "transaction_fingerprint": committed.transaction_fingerprint,
            }
        )
        root.mkdir(parents=True, exist_ok=True)
        temporary_pointer.write_bytes(pointer_payload)
        os.replace(temporary_pointer, current_path)
        return GenerationTransactionResult(
            manifest=committed,
            current_generation_before=current_before,
            current_generation_after=committed.generation_id,
            retained_directory=str(committed_dir),
        )
    except Exception as exc:
        rolled_back = GenerationTransactionManifest.build(
            project_id=manifest.project_id,
            generation_id=manifest.generation_id,
            generation_sha256=manifest.generation_sha256,
            stage=manifest.stage,
            status="rolled_back",
            artifacts=manifest.artifacts,
            previous_current_sha256=manifest.previous_current_sha256,
            reason=f"{type(exc).__name__}: {exc}",
        )
        failure_source = committed_dir if promoted else staging
        if failure_source.exists():
            _write_manifest(failure_source / "transaction.json", rolled_back)
            failed_parent.mkdir(parents=True, exist_ok=True)
            os.replace(failure_source, failed_dir)
        else:
            failed_dir.mkdir(parents=True, exist_ok=False)
            _write_manifest(failed_dir / "transaction.json", rolled_back)
        if temporary_pointer.exists():
            retained_pointer = failed_dir / "uncommitted-CURRENT.json"
            os.replace(temporary_pointer, retained_pointer)
        return GenerationTransactionResult(
            manifest=rolled_back,
            current_generation_before=current_before,
            current_generation_after=current_before,
            retained_directory=str(failed_dir),
        )


def resolve_current_generation(
    transaction_root: Path,
) -> GenerationTransactionManifest:
    """Resolve and hash-check the current immutable generation."""

    root = transaction_root.resolve()
    current_path = root / "CURRENT.json"
    pointer = json.loads(current_path.read_text(encoding="utf-8"))
    if pointer.get("schema") != "pcbsmith-current-generation-v1":
        raise ValueError("current-generation pointer schema is unsupported")
    generation_id = require_identity(pointer["generation_id"], "generation_id")
    generation_dir = root / "generations" / generation_id
    _require_descendant(root, generation_dir)
    manifest = GenerationTransactionManifest.model_validate_json(
        (generation_dir / "transaction.json").read_text(encoding="utf-8")
    )
    if manifest.status != "committed":
        raise ValueError("current pointer targets a non-committed transaction")
    if (
        pointer.get("generation_sha256") != manifest.generation_sha256
        or pointer.get("transaction_fingerprint") != manifest.transaction_fingerprint
    ):
        raise ValueError("current pointer and transaction identities disagree")
    for artifact in manifest.artifacts:
        retained = generation_dir / PurePosixPath(artifact.relative_path)
        _require_descendant(generation_dir, retained)
        if _file_sha256(retained) != artifact.content_sha256:
            raise ValueError(f"current artifact digest is stale: {artifact.relative_path}")
    return manifest


def _read_current_pointer(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    payload = path.read_bytes()
    pointer = json.loads(payload)
    generation_id = require_identity(pointer["generation_id"], "generation_id")
    return generation_id, _bytes_sha256(payload)


def _write_manifest(path: Path, manifest: GenerationTransactionManifest) -> None:
    path.write_bytes(_canonical_bytes(manifest.model_dump(mode="json")))


def _safe_relative_path(value: str) -> PurePosixPath:
    require_identity(value, "relative_path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() in {"", "."}:
        raise ValueError("artifact relative_path must remain inside its generation")
    return path


def _require_descendant(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if child_resolved == parent_resolved or parent_resolved not in child_resolved.parents:
        raise ValueError(f"path escapes its transaction root: {child}")


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _bytes_sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _bytes_sha256(path.read_bytes())


class RouteDomainRequest(SemanticIrModel):
    schema_id: Literal["pcbsmith-route-domain-request"] = "pcbsmith-route-domain-request"
    schema_version: Literal[1] = 1
    domain_id: str
    priority: int = Field(ge=0)
    dependency_domain_ids: tuple[str, ...] = ()
    net_names: tuple[str, ...] = Field(min_length=1)
    input_fingerprint: str

    @model_validator(mode="after")
    def request_is_canonical(self) -> Self:
        require_identity(self.domain_id, "domain_id")
        require_sha256(self.input_fingerprint, "input_fingerprint")
        dependencies = tuple(sorted(self.dependency_domain_ids))
        nets = tuple(sorted(self.net_names))
        if len(dependencies) != len(set(dependencies)) or len(nets) != len(set(nets)):
            raise ValueError("route dependencies and net names must be unique")
        if self.domain_id in dependencies:
            raise ValueError("route domain cannot depend on itself")
        object.__setattr__(self, "dependency_domain_ids", dependencies)
        object.__setattr__(self, "net_names", nets)
        return self


class DeterministicRoutePlan(SemanticIrModel):
    schema_id: Literal["pcbsmith-deterministic-route-plan"] = "pcbsmith-deterministic-route-plan"
    schema_version: Literal[1] = 1
    generation_sha256: str
    start_board_sha256: str
    ordered_domains: tuple[RouteDomainRequest, ...]
    ordered_net_names: tuple[str, ...]
    plan_fingerprint: str

    @model_validator(mode="after")
    def plan_is_replay_bound(self) -> Self:
        require_sha256(self.generation_sha256, "generation_sha256")
        require_sha256(self.start_board_sha256, "start_board_sha256")
        ids = tuple(item.domain_id for item in self.ordered_domains)
        if len(ids) != len(set(ids)):
            raise ValueError("route plan domain identities must be unique")
        expected_nets = tuple(net for domain in self.ordered_domains for net in domain.net_names)
        if expected_nets != self.ordered_net_names:
            raise ValueError("ordered net names are stale")
        if len(expected_nets) != len(set(expected_nets)):
            raise ValueError("a net may belong to only one route domain")
        completed: set[str] = set()
        for domain in self.ordered_domains:
            if not set(domain.dependency_domain_ids).issubset(completed):
                raise ValueError("route plan violates a domain dependency")
            completed.add(domain.domain_id)
        require_sha256(self.plan_fingerprint, "plan_fingerprint")
        payload = self.model_dump(mode="json", exclude={"plan_fingerprint"})
        if self.plan_fingerprint != fingerprint(payload):
            raise ValueError("deterministic route plan fingerprint is stale")
        return self


def build_deterministic_route_plan(
    *,
    generation_sha256: str,
    start_board_sha256: str,
    domains: tuple[RouteDomainRequest, ...],
) -> DeterministicRoutePlan:
    """Topologically order domains with repository-owned stable tie breakers."""

    require_sha256(generation_sha256, "generation_sha256")
    require_sha256(start_board_sha256, "start_board_sha256")
    by_id = {item.domain_id: item for item in domains}
    if len(by_id) != len(domains):
        raise ValueError("route domain identities must be unique")
    unknown = sorted(
        {
            dependency
            for item in domains
            for dependency in item.dependency_domain_ids
            if dependency not in by_id
        }
    )
    if unknown:
        raise ValueError(f"route domains reference unknown dependencies: {unknown!r}")
    remaining = set(by_id)
    ordered: list[RouteDomainRequest] = []
    completed: set[str] = set()
    while remaining:
        ready = sorted(
            (
                by_id[domain_id]
                for domain_id in remaining
                if set(by_id[domain_id].dependency_domain_ids).issubset(completed)
            ),
            key=lambda item: (item.priority, item.domain_id, item.input_fingerprint),
        )
        if not ready:
            raise ValueError("route domain dependency graph contains a cycle")
        selected = ready[0]
        ordered.append(selected)
        remaining.remove(selected.domain_id)
        completed.add(selected.domain_id)
    fields: dict[str, Any] = {
        "generation_sha256": generation_sha256,
        "start_board_sha256": start_board_sha256,
        "ordered_domains": tuple(ordered),
        "ordered_net_names": tuple(net for domain in ordered for net in domain.net_names),
    }
    provisional = DeterministicRoutePlan.model_construct(**fields, plan_fingerprint="0" * 64)
    return DeterministicRoutePlan(
        **fields,
        plan_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"plan_fingerprint"})
        ),
    )


class CompletedRouteDomain(SemanticIrModel):
    schema_id: Literal["pcbsmith-completed-route-domain"] = "pcbsmith-completed-route-domain"
    schema_version: Literal[1] = 1
    domain_id: str
    domain_input_fingerprint: str
    input_board_sha256: str
    output_board_sha256: str
    exact_acceptance_sha256: str
    accepted: Literal[True] = True

    @model_validator(mode="after")
    def completion_is_bound(self) -> Self:
        require_identity(self.domain_id, "domain_id")
        for field_name in (
            "domain_input_fingerprint",
            "input_board_sha256",
            "output_board_sha256",
            "exact_acceptance_sha256",
        ):
            require_sha256(getattr(self, field_name), field_name)
        return self


class RouteDomainCheckpoint(SemanticIrModel):
    schema_id: Literal["pcbsmith-route-domain-checkpoint"] = "pcbsmith-route-domain-checkpoint"
    schema_version: Literal[1] = 1
    generation_sha256: str
    plan_fingerprint: str
    completed_domains: tuple[CompletedRouteDomain, ...]
    current_board_sha256: str
    checkpoint_fingerprint: str

    @model_validator(mode="after")
    def checkpoint_is_replay_bound(self) -> Self:
        require_sha256(self.generation_sha256, "generation_sha256")
        require_sha256(self.plan_fingerprint, "plan_fingerprint")
        require_sha256(self.current_board_sha256, "current_board_sha256")
        require_sha256(self.checkpoint_fingerprint, "checkpoint_fingerprint")
        payload = self.model_dump(mode="json", exclude={"checkpoint_fingerprint"})
        if self.checkpoint_fingerprint != fingerprint(payload):
            raise ValueError("route-domain checkpoint fingerprint is stale")
        return self


def build_route_domain_checkpoint(
    *,
    plan: DeterministicRoutePlan,
    completed_domains: tuple[CompletedRouteDomain, ...],
) -> RouteDomainCheckpoint:
    """Checkpoint only an exact-accepted replay-equivalent plan prefix."""

    if len(completed_domains) > len(plan.ordered_domains):
        raise ValueError("checkpoint completes more domains than its route plan")
    current_board = plan.start_board_sha256
    for expected, completed in zip(plan.ordered_domains, completed_domains, strict=False):
        if (
            completed.domain_id != expected.domain_id
            or completed.domain_input_fingerprint != expected.input_fingerprint
        ):
            raise ValueError("checkpoint is not a replay-equivalent route-plan prefix")
        if completed.input_board_sha256 != current_board:
            raise ValueError("completed route-domain board chain is discontinuous")
        current_board = completed.output_board_sha256
    fields: dict[str, Any] = {
        "generation_sha256": plan.generation_sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "completed_domains": completed_domains,
        "current_board_sha256": current_board,
    }
    provisional = RouteDomainCheckpoint.model_construct(**fields, checkpoint_fingerprint="0" * 64)
    return RouteDomainCheckpoint(
        **fields,
        checkpoint_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"checkpoint_fingerprint"})
        ),
    )


def remaining_route_domains(
    *,
    plan: DeterministicRoutePlan,
    checkpoint: RouteDomainCheckpoint,
) -> tuple[RouteDomainRequest, ...]:
    if (
        checkpoint.generation_sha256 != plan.generation_sha256
        or checkpoint.plan_fingerprint != plan.plan_fingerprint
    ):
        raise ValueError("checkpoint belongs to another generation or route plan")
    # Rebuild to revalidate the retained prefix and board chain.
    build_route_domain_checkpoint(plan=plan, completed_domains=checkpoint.completed_domains)
    return plan.ordered_domains[len(checkpoint.completed_domains) :]


class RoutingEntryGateReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-routing-entry-gate"] = "pcbsmith-routing-entry-gate"
    schema_version: Literal[1] = 1
    generation_sha256: str
    saved_board_sha256: str
    saved_layout_fingerprint: str
    allowed: bool
    blockers: tuple[str, ...]
    prompt_examination_fingerprint: str
    context_fingerprint: str
    feasibility_fingerprint: str
    concept_drift_fingerprint: str
    review_transaction_fingerprint: str
    engineering_gate_fingerprint: str
    budget_profile_name: Literal["quick", "standard", "deep"]
    report_fingerprint: str

    @model_validator(mode="after")
    def gate_is_replay_bound(self) -> Self:
        for field_name in (
            "generation_sha256",
            "saved_board_sha256",
            "saved_layout_fingerprint",
            "prompt_examination_fingerprint",
            "context_fingerprint",
            "feasibility_fingerprint",
            "concept_drift_fingerprint",
            "review_transaction_fingerprint",
            "engineering_gate_fingerprint",
            "report_fingerprint",
        ):
            require_sha256(getattr(self, field_name), field_name)
        if self.allowed != (not self.blockers):
            raise ValueError("routing gate disposition is stale")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("routing-entry report fingerprint is stale")
        return self


def evaluate_routing_entry_gate(
    *,
    generation_sha256: str,
    saved_board_sha256: str,
    saved_layout_fingerprint: str,
    examination: PromptExamination,
    context: ProjectContextBundle,
    feasibility: PreRouteFeasibilityReport,
    concept_drift: ConceptDriftReport,
    placement_review: VisualReviewManifest,
    committed_review_transaction: GenerationTransactionManifest,
    engineering_gate: ProjectEngineeringGateResult,
    budget_bindings: tuple[AlgorithmBudgetBinding, ...],
) -> RoutingEntryGateReport:
    """Fail closed before routing unless every shared production gate passed."""

    require_sha256(generation_sha256, "generation_sha256")
    require_sha256(saved_board_sha256, "saved_board_sha256")
    require_sha256(saved_layout_fingerprint, "saved_layout_fingerprint")
    blockers: list[str] = []
    if examination.project_id != context.project_id:
        blockers.append("prompt examination and project context identify different projects")
    if context.generation_sha256 != generation_sha256:
        blockers.append("project context belongs to another generation")
    if examination.outcome != "ready_for_concept":
        blockers.append("prompt examination is unresolved or blocked")
    unresolved_context = tuple(
        item.category.value
        for item in context.records
        if item.status is ProjectContextStatus.UNRESOLVED
    )
    if unresolved_context:
        blockers.append("project context is unresolved: " + ", ".join(unresolved_context))
    if feasibility.outcome not in {
        FeasibilityOutcome.READY,
        FeasibilityOutcome.ATTENTION_REQUIRED,
    }:
        blockers.append(f"pre-route feasibility is {feasibility.outcome.value}")
    if feasibility.outcome is FeasibilityOutcome.ATTENTION_REQUIRED:
        blockers.append("pre-route feasibility requires a retained decision")
    if not concept_drift.conformant:
        blockers.append("saved design drifted from the approved concept")
    if concept_drift.observed_design_sha256 != saved_board_sha256:
        blockers.append("concept-drift report targets a different saved board")
    if placement_review.stage != "placement":
        blockers.append("canonical review package is not a placement-stage package")
    if placement_review.board_sha256 != saved_board_sha256:
        blockers.append("placement review targets a different saved board")
    if placement_review.package_status != "accepted":
        blockers.append(f"placement review package is {placement_review.package_status}")
    if placement_review.workflow_conformance_status not in {
        "conformant",
        "conformant_with_waivers",
    }:
        blockers.append("placement review workflow profile is not conformant")
    if committed_review_transaction.status != "committed":
        blockers.append("placement/review generation transaction is not committed")
    if committed_review_transaction.generation_sha256 != generation_sha256:
        blockers.append("placement/review transaction belongs to another generation")
    if committed_review_transaction.project_id != context.project_id:
        blockers.append("placement/review transaction belongs to another project")
    if engineering_gate.context.project_id != context.project_id:
        blockers.append("engineering applicability gate belongs to another project")
    if engineering_gate.context.board_layout_snapshot_fingerprint != saved_layout_fingerprint:
        blockers.append("engineering applicability gate targets another saved layout snapshot")
    if engineering_gate.context.inventory_status is not InventoryStatus.COMPLETE_REVIEWED:
        blockers.append("engineering component/feature inventory is not complete and reviewed")
    if engineering_gate.outcome is not ProjectGateOutcome.READY:
        blockers.append(f"engineering applicability gate is {engineering_gate.outcome.value}")
    retained_board = tuple(
        item
        for item in committed_review_transaction.artifacts
        if item.role == "board" and item.content_sha256 == saved_board_sha256
    )
    expected_review_sha256 = _bytes_sha256(
        (
            json.dumps(
                placement_review.model_dump(mode="json", by_alias=True),
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    )
    retained_review = tuple(
        item
        for item in committed_review_transaction.artifacts
        if (
            item.role == "review"
            and item.relative_path == "review/manifest.json"
            and item.content_sha256 == expected_review_sha256
        )
    )
    if not retained_board:
        blockers.append("committed transaction lacks the reviewed saved board")
    if not retained_review:
        blockers.append("committed transaction lacks the exact canonical review manifest")
    algorithms = tuple(item.algorithm for item in budget_bindings)
    if len(algorithms) != len(set(algorithms)) or set(algorithms) != set(NativeAlgorithm):
        blockers.append("execution profile is not bound to every native algorithm")
    profile_names = {item.profile_name for item in budget_bindings}
    if len(profile_names) != 1:
        blockers.append("native algorithms do not share one execution profile")
    profile_name: Literal["quick", "standard", "deep"] = (
        next(iter(profile_names)) if len(profile_names) == 1 else "quick"
    )
    fields: dict[str, Any] = {
        "generation_sha256": generation_sha256,
        "saved_board_sha256": saved_board_sha256,
        "saved_layout_fingerprint": saved_layout_fingerprint,
        "allowed": not blockers,
        "blockers": tuple(blockers),
        "prompt_examination_fingerprint": examination.examination_fingerprint,
        "context_fingerprint": context.context_fingerprint,
        "feasibility_fingerprint": feasibility.report_fingerprint,
        "concept_drift_fingerprint": concept_drift.report_fingerprint,
        "review_transaction_fingerprint": (committed_review_transaction.transaction_fingerprint),
        "engineering_gate_fingerprint": engineering_gate.result_fingerprint,
        "budget_profile_name": profile_name,
    }
    provisional = RoutingEntryGateReport.model_construct(**fields, report_fingerprint="0" * 64)
    return RoutingEntryGateReport(
        **fields,
        report_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"report_fingerprint"})
        ),
    )


class RoutedVerificationKind(StrEnum):
    EXACT_ROUTE = "exact_route"
    KICAD_READBACK = "kicad_readback"
    NETLIST_EQUIVALENCE = "netlist_equivalence"


class RoutedVerificationRecord(SemanticIrModel):
    """Retained producer evidence for one routed-board release assertion."""

    schema_id: Literal["pcbsmith-routed-verification-record"] = (
        "pcbsmith-routed-verification-record"
    )
    schema_version: Literal[1] = 1
    kind: RoutedVerificationKind
    board_sha256: str
    producer_id: str
    tool_version: str
    input_sha256s: tuple[str, ...]
    accepted: bool
    result_code: str
    limitations: tuple[str, ...] = ()
    record_fingerprint: str

    @model_validator(mode="after")
    def record_is_replay_bound(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_identity(self.producer_id, "producer_id")
        require_identity(self.tool_version, "tool_version")
        require_identity(self.result_code, "result_code")
        if not self.input_sha256s:
            raise ValueError("routed verification requires retained input identities")
        for digest in self.input_sha256s:
            require_sha256(digest, "input_sha256")
        if len(self.input_sha256s) != len(set(self.input_sha256s)):
            raise ValueError("routed verification input identities must be unique")
        if self.accepted and self.result_code != "accepted":
            raise ValueError("accepted routed verification requires accepted result code")
        if not self.accepted and self.result_code == "accepted":
            raise ValueError("rejected routed verification cannot use accepted result code")
        require_sha256(self.record_fingerprint, "record_fingerprint")
        payload = self.model_dump(mode="json", exclude={"record_fingerprint"})
        if self.record_fingerprint != fingerprint(payload):
            raise ValueError("routed verification record fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        kind: RoutedVerificationKind,
        board_sha256: str,
        producer_id: str,
        tool_version: str,
        input_sha256s: tuple[str, ...],
        accepted: bool,
        result_code: str,
        limitations: tuple[str, ...] = (),
    ) -> RoutedVerificationRecord:
        fields: dict[str, Any] = {
            "kind": kind,
            "board_sha256": board_sha256,
            "producer_id": producer_id,
            "tool_version": tool_version,
            "input_sha256s": tuple(sorted(input_sha256s)),
            "accepted": accepted,
            "result_code": result_code,
            "limitations": tuple(sorted(limitations)),
        }
        provisional = cls.model_construct(**fields, record_fingerprint="0" * 64)
        return cls(
            **fields,
            record_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"record_fingerprint"})
            ),
        )


class RoutedBoardVerificationEvidence(SemanticIrModel):
    """Exact three-authority bundle replacing release-time caller booleans."""

    schema_id: Literal["pcbsmith-routed-board-verification-evidence"] = (
        "pcbsmith-routed-board-verification-evidence"
    )
    schema_version: Literal[1] = 1
    board_sha256: str
    records: tuple[RoutedVerificationRecord, ...]
    bundle_fingerprint: str

    @model_validator(mode="after")
    def bundle_is_complete_and_replay_bound(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        records = tuple(sorted(self.records, key=lambda item: item.kind.value))
        expected = set(RoutedVerificationKind)
        supplied = {item.kind for item in records}
        if supplied != expected or len(records) != len(expected):
            raise ValueError(
                "routed verification bundle requires exactly one exact-route, "
                "KiCad read-back, and netlist-equivalence record"
            )
        if any(item.board_sha256 != self.board_sha256 for item in records):
            raise ValueError("routed verification records target different boards")
        object.__setattr__(self, "records", records)
        require_sha256(self.bundle_fingerprint, "bundle_fingerprint")
        payload = self.model_dump(mode="json", exclude={"bundle_fingerprint"})
        if self.bundle_fingerprint != fingerprint(payload):
            raise ValueError("routed verification bundle fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        board_sha256: str,
        records: tuple[RoutedVerificationRecord, ...],
    ) -> RoutedBoardVerificationEvidence:
        fields: dict[str, Any] = {
            "board_sha256": board_sha256,
            "records": tuple(sorted(records, key=lambda item: item.kind.value)),
        }
        provisional = cls.model_construct(**fields, bundle_fingerprint="0" * 64)
        return cls(
            **fields,
            bundle_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"bundle_fingerprint"})
            ),
        )

    def record(self, kind: RoutedVerificationKind) -> RoutedVerificationRecord:
        return next(item for item in self.records if item.kind is kind)


class RoutedBoardReleaseGateReport(SemanticIrModel):
    """Final fail-closed verdict for one exact saved routed-board revision."""

    schema_id: Literal["pcbsmith-routed-board-release-gate"] = "pcbsmith-routed-board-release-gate"
    schema_version: Literal[1] = 1
    board_routing: SavedBoardRoutingEvidence
    kicad_drc: KiCadDrcEvidence
    verification_evidence: RoutedBoardVerificationEvidence
    applicability_execution: ProjectApplicabilityExecutionManifest
    transaction_fingerprint: str
    final_review_sha256: str
    allowed: bool
    blockers: tuple[str, ...]
    report_fingerprint: str

    @model_validator(mode="after")
    def gate_is_replay_bound(self) -> Self:
        require_sha256(self.transaction_fingerprint, "transaction_fingerprint")
        require_sha256(self.final_review_sha256, "final_review_sha256")
        require_sha256(self.report_fingerprint, "report_fingerprint")
        if self.allowed != (not self.blockers):
            raise ValueError("routed-board release disposition is stale")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("routed-board release fingerprint is stale")
        return self


def evaluate_routed_board_release_gate(
    *,
    board_file: Path,
    drc_report_file: Path,
    final_review: VisualReviewManifest,
    committed_transaction: GenerationTransactionManifest,
    verification_evidence: RoutedBoardVerificationEvidence,
    applicability_execution: ProjectApplicabilityExecutionManifest,
) -> RoutedBoardReleaseGateReport:
    """Require copper, connectivity, DRC, review, and transaction identity.

    Segment/carrier coverage is only an inexpensive omission detector.  This
    gate also requires exact-route, read-back, netlist, and KiCad authorities.
    """

    board_routing = inspect_saved_board_routing(board_file)
    kicad_drc = inspect_kicad_drc_report(drc_report_file)
    blockers: list[str] = []
    if "placement" in board_file.name.casefold():
        blockers.append("canonical handoff board is still named as a placement artifact")
    if board_routing.state is not RoutingArtifactState.ROUTED_CANDIDATE:
        blockers.append(f"saved board routing state is {board_routing.state.value}")
    if board_routing.segment_count == 0:
        blockers.append("saved board contains no track segments")
    if board_routing.copper_carrier_net_coverage < 1.0:
        blockers.append("saved board lacks copper carriers for one or more routable nets")
    if verification_evidence.board_sha256 != board_routing.board_sha256:
        blockers.append("routed verification evidence targets a different saved board")
    if applicability_execution.saved_design_sha256 != board_routing.board_sha256:
        blockers.append("applicability/execution manifest targets a different saved board")
    if applicability_execution.authority is not ProjectExecutionAuthority.READY:
        blockers.append(
            "project applicability/execution coverage is blocked: "
            + "; ".join(applicability_execution.blockers)
        )
    exact_route = verification_evidence.record(RoutedVerificationKind.EXACT_ROUTE)
    readback = verification_evidence.record(RoutedVerificationKind.KICAD_READBACK)
    netlist = verification_evidence.record(RoutedVerificationKind.NETLIST_EQUIVALENCE)
    if not exact_route.accepted:
        blockers.append("mandatory exact route checker did not accept the board")
    if not readback.accepted:
        blockers.append("saved KiCad board read-back is not verified")
    if not netlist.accepted:
        blockers.append("saved board and intended netlist are not proven equivalent")
    if not kicad_drc.clean:
        blockers.append(
            "KiCad DRC is not clean: "
            f"{kicad_drc.violation_count} violations, "
            f"{kicad_drc.unconnected_item_count} unconnected items, "
            f"{kicad_drc.schematic_parity_count} schematic-parity findings"
        )
    if final_review.stage != "final":
        blockers.append("canonical visual review is not final-stage")
    if final_review.board_sha256 != board_routing.board_sha256:
        blockers.append("final review targets a different saved board")
    if final_review.routing_evidence is None:
        blockers.append("final review lacks saved-board routing evidence")
    elif (
        final_review.routing_evidence.board_sha256 != board_routing.board_sha256
        or final_review.routing_evidence.segment_count != board_routing.segment_count
        or final_review.routing_evidence.via_count != board_routing.via_count
        or final_review.routing_evidence.state != board_routing.state
    ):
        blockers.append("final review routing inventory does not match the saved board")
    if final_review.package_status != "accepted":
        blockers.append(f"final visual review is {final_review.package_status}")
    if final_review.workflow_conformance_status not in {
        "conformant",
        "conformant_with_waivers",
    }:
        blockers.append("final visual review workflow is not conformant")
    if committed_transaction.status != "committed":
        blockers.append("final generation transaction is not committed")
    if committed_transaction.stage not in {
        WorkflowStage.REVIEW,
        WorkflowStage.VERIFICATION,
    }:
        blockers.append("final generation transaction has not reached review or verification")
    retained_board = tuple(
        item
        for item in committed_transaction.artifacts
        if item.role == "board" and item.content_sha256 == board_routing.board_sha256
    )
    if not retained_board:
        blockers.append("committed transaction lacks the exact routed board")
    review_payload = (
        json.dumps(final_review.model_dump(mode="json", by_alias=True), indent=2) + "\n"
    ).encode("utf-8")
    review_sha256 = _bytes_sha256(review_payload)
    retained_review = tuple(
        item
        for item in committed_transaction.artifacts
        if (
            item.role == "review"
            and item.relative_path == "review/manifest.json"
            and item.content_sha256 == review_sha256
        )
    )
    if not retained_review:
        blockers.append("committed transaction lacks the exact final review manifest")
    fields: dict[str, Any] = {
        "board_routing": board_routing,
        "kicad_drc": kicad_drc,
        "verification_evidence": verification_evidence,
        "applicability_execution": applicability_execution,
        "transaction_fingerprint": committed_transaction.transaction_fingerprint,
        "final_review_sha256": review_sha256,
        "allowed": not blockers,
        "blockers": tuple(blockers),
    }
    provisional = RoutedBoardReleaseGateReport.model_construct(
        **fields, report_fingerprint="0" * 64
    )
    return RoutedBoardReleaseGateReport(
        **fields,
        report_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"report_fingerprint"})
        ),
    )


@dataclass(frozen=True)
class ProductionNativeRouteResult:
    """One routing result plus the execution telemetry that governed it."""

    result: BoardRouteResult
    exact_check: ExactRouteCheckResult | None
    telemetry: AlgorithmStageTelemetry


def route_native_board(
    *,
    layout: BoardLayout,
    netlist: BoardNetlist,
    routing_gate: RoutingEntryGateReport,
    binding: AlgorithmBudgetBinding,
    exact_checker: ExactRouteChecker,
    net_order: tuple[str, ...] | None = None,
    max_expansions_per_net: int | None = None,
    heartbeat_sink: Callable[[str, Mapping[str, object]], None] | None = None,
) -> ProductionNativeRouteResult:
    """Run the native A* router only through an accepted production gate.

    The execution profile supplies the operative pass and expansion ceilings.
    Each completed router pass updates the shared native ledger and emits a
    checkpoint-bound heartbeat.
    """

    if not routing_gate.allowed:
        raise ValueError("native production routing requires an accepted routing gate")
    if binding.algorithm is not NativeAlgorithm.ROUTING:
        raise ValueError("native production routing requires the routing budget binding")
    if binding.profile_name != routing_gate.budget_profile_name:
        raise ValueError("routing gate and native routing profile differ")

    controller = NativeStageController(
        binding=binding,
        heartbeat_sink=heartbeat_sink,
    )

    def observe_pass(pass_record: RoutingPassTelemetry) -> None:
        controller.consume_expansions(pass_record.expansion_count)
        controller.consume_pass()
        controller.heartbeat(
            "routing.pass.complete",
            checkpoint_sha256=fingerprint(pass_record.model_dump(mode="json")),
        )

    per_net = (
        binding.maximum_expansions
        if max_expansions_per_net is None
        else min(max_expansions_per_net, binding.maximum_expansions)
    )
    result = route_board(
        layout,
        netlist,
        net_order=net_order,
        max_restarts=max(0, (binding.maximum_passes // 2) - 1),
        max_passes=binding.maximum_passes,
        max_expansions=binding.maximum_expansions,
        max_expansions_per_net=per_net,
        pass_observer=observe_pass,
    )
    exact_check = exact_checker(result.layout, netlist) if result.run_result.success else None
    if exact_check is not None and not isinstance(exact_check, ExactRouteCheckResult):
        raise TypeError("native production exact checker returned an invalid result")
    budget_failure = (
        result.run_result.failure_reason is not None
        and result.run_result.failure_reason.value in {"expansion_budget", "pass_budget"}
    )
    termination: Literal[
        "completed",
        "budget_exhausted",
        "timeout",
        "failed",
        "incomplete",
    ] = (
        "completed"
        if result.run_result.success and exact_check is not None and exact_check.accepted
        else ("budget_exhausted" if budget_failure else "failed")
    )
    findings = tuple(
        sorted(
            {
                *(
                    ()
                    if result.run_result.failure_reason is None
                    else (result.run_result.failure_reason.value,)
                ),
                *(() if exact_check is None else exact_check.finding_fingerprints),
            }
        )
    )
    return ProductionNativeRouteResult(
        result=result,
        exact_check=exact_check,
        telemetry=controller.telemetry(
            generation_sha256=routing_gate.generation_sha256,
            termination=termination,
            findings=findings,
        ),
    )
