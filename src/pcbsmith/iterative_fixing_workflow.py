"""Checkpointed IF6 orchestration, evidence closure, and atomic promotion."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.semantic_ir import SemanticIrModel


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fp(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class WorkflowStepOutcome(StrEnum):
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class WorkflowStepResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-iterative-fix-step-result"] = "pcbsmith-iterative-fix-step-result"
    schema_version: Literal[1] = 1
    step_id: str
    outcome: WorkflowStepOutcome
    result_fingerprint: str
    evidence_paths: tuple[str, ...]
    candidate_path: str | None = None
    candidate_sha256: str | None = None
    attempts_used: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    changed_object_count: int = Field(ge=0)
    preserved_object_count: int = Field(ge=0)
    blockers: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.outcome is WorkflowStepOutcome.ACCEPTED and self.blockers:
            raise ValueError("accepted workflow step cannot retain blockers")
        if self.outcome is WorkflowStepOutcome.BLOCKED and not self.blockers:
            raise ValueError("blocked workflow step requires a blocker")
        if (self.candidate_path is None) != (self.candidate_sha256 is None):
            raise ValueError("candidate path and hash must be present together")
        return self


class WorkflowCheckpoint(SemanticIrModel):
    schema_id: Literal["pcbsmith-iterative-fix-checkpoint"] = "pcbsmith-iterative-fix-checkpoint"
    schema_version: Literal[1] = 1
    case_id: str
    source_sha256: str
    configuration_fingerprint: str
    step_results: tuple[WorkflowStepResult, ...]
    terminal: bool
    checkpoint_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        ids = tuple(item.step_id for item in self.step_results)
        if ids != _STEPS[: len(ids)]:
            raise ValueError("checkpoint steps must follow canonical order")
        if len(ids) != len(set(ids)):
            raise ValueError("checkpoint step identities must be unique")
        payload = self.model_dump(mode="json", exclude={"checkpoint_fingerprint"})
        if self.checkpoint_fingerprint != _fp(payload):
            raise ValueError("checkpoint fingerprint is stale")
        return self


class EvidenceManifestItem(SemanticIrModel):
    schema_id: Literal["pcbsmith-iterative-fix-evidence-item"] = (
        "pcbsmith-iterative-fix-evidence-item"
    )
    schema_version: Literal[1] = 1
    step_id: str
    path: str
    sha256: str


class IterativeFixEvidenceManifest(SemanticIrModel):
    schema_id: Literal["pcbsmith-iterative-fix-evidence-manifest"] = (
        "pcbsmith-iterative-fix-evidence-manifest"
    )
    schema_version: Literal[1] = 1
    case_id: str
    source_sha256: str
    checkpoint_fingerprint: str
    items: tuple[EvidenceManifestItem, ...]
    complete: bool
    missing_paths: tuple[str, ...]


class BaselineComparison(SemanticIrModel):
    schema_id: Literal["pcbsmith-iterative-fix-baseline-comparison"] = (
        "pcbsmith-iterative-fix-baseline-comparison"
    )
    schema_version: Literal[1] = 1
    iterative_attempts: int = Field(ge=0)
    full_regeneration_attempts: int = Field(ge=0)
    iterative_elapsed_seconds: float = Field(ge=0)
    full_regeneration_elapsed_seconds: float = Field(ge=0)
    iterative_changed_object_count: int = Field(ge=0)
    full_regeneration_changed_object_count: int = Field(ge=0)
    preserved_object_count: int = Field(ge=0)
    attempt_reduction: int
    changed_object_reduction: int
    time_reduction_seconds: float


StepRunner = Callable[[], WorkflowStepResult]
_STEPS = ("IF1", "IF2", "IF3", "IF4", "IF5")


def _checkpoint(
    *,
    case_id: str,
    source_sha256: str,
    configuration_fingerprint: str,
    results: tuple[WorkflowStepResult, ...],
    terminal: bool,
) -> WorkflowCheckpoint:
    fields = {
        "case_id": case_id,
        "source_sha256": source_sha256,
        "configuration_fingerprint": configuration_fingerprint,
        "step_results": results,
        "terminal": terminal,
    }
    provisional = WorkflowCheckpoint.model_construct(
        case_id=case_id,
        source_sha256=source_sha256,
        configuration_fingerprint=configuration_fingerprint,
        step_results=results,
        terminal=terminal,
        checkpoint_fingerprint="0" * 64,
    )
    payload = provisional.model_dump(mode="json", exclude={"checkpoint_fingerprint"})
    return WorkflowCheckpoint(**fields, checkpoint_fingerprint=_fp(payload))


def _atomic_json(path: Path, model: SemanticIrModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_iterative_fix_workflow(
    *,
    case_id: str,
    source_board: Path,
    configuration_fingerprint: str,
    checkpoint_path: Path,
    runners: Mapping[str, StepRunner],
) -> WorkflowCheckpoint:
    """Run in canonical order, resume safely, and checkpoint after every step."""

    if set(runners) != set(_STEPS):
        raise ValueError("workflow runners must exactly cover IF1 through IF5")
    source_sha256 = _sha(source_board)
    results: list[WorkflowStepResult] = []
    if checkpoint_path.exists():
        existing = WorkflowCheckpoint.model_validate_json(
            checkpoint_path.read_text(encoding="utf-8")
        )
        if (
            existing.case_id != case_id
            or existing.source_sha256 != source_sha256
            or existing.configuration_fingerprint != configuration_fingerprint
        ):
            raise ValueError("checkpoint does not match current workflow authority")
        results.extend(existing.step_results)
        if existing.terminal:
            return existing
    completed = {item.step_id for item in results}
    for step_id in _STEPS:
        if step_id in completed:
            continue
        started = time.monotonic()
        result = runners[step_id]()
        if result.step_id != step_id:
            raise ValueError("workflow runner returned the wrong step identity")
        if result.elapsed_seconds == 0:
            result = result.model_copy(update={"elapsed_seconds": time.monotonic() - started})
        results.append(result)
        terminal = result.outcome is WorkflowStepOutcome.BLOCKED or step_id == _STEPS[-1]
        current = _checkpoint(
            case_id=case_id,
            source_sha256=source_sha256,
            configuration_fingerprint=configuration_fingerprint,
            results=tuple(results),
            terminal=terminal,
        )
        _atomic_json(checkpoint_path, current)
        if terminal:
            return current
    raise RuntimeError("iterative workflow ended without a terminal checkpoint")


def build_evidence_manifest(
    checkpoint: WorkflowCheckpoint, *, root: Path
) -> IterativeFixEvidenceManifest:
    items: list[EvidenceManifestItem] = []
    missing: list[str] = []
    for result in checkpoint.step_results:
        for relative in result.evidence_paths:
            path = root / relative
            if not path.is_file():
                missing.append(relative)
            else:
                items.append(
                    EvidenceManifestItem(step_id=result.step_id, path=relative, sha256=_sha(path))
                )
    return IterativeFixEvidenceManifest(
        case_id=checkpoint.case_id,
        source_sha256=checkpoint.source_sha256,
        checkpoint_fingerprint=checkpoint.checkpoint_fingerprint,
        items=tuple(sorted(items, key=lambda item: (item.step_id, item.path))),
        complete=not missing,
        missing_paths=tuple(sorted(set(missing))),
    )


def promote_candidate_atomically(result: WorkflowStepResult, *, canonical_board: Path) -> str:
    """Publish only an accepted, hash-bound candidate using same-volume replace."""

    if result.outcome is not WorkflowStepOutcome.ACCEPTED or result.candidate_path is None:
        raise ValueError("only an accepted candidate may be promoted")
    candidate = Path(result.candidate_path)
    if not candidate.is_file() or _sha(candidate) != result.candidate_sha256:
        raise ValueError("promotion candidate is missing or stale")
    canonical_board.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=canonical_board.parent, prefix=".pcbsmith-promote-", delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(candidate, temporary)
        os.replace(temporary, canonical_board)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha(canonical_board)


def compare_with_full_regeneration(
    *,
    checkpoint: WorkflowCheckpoint,
    full_regeneration_attempts: int,
    full_regeneration_elapsed_seconds: float,
    full_regeneration_changed_object_count: int,
) -> BaselineComparison:
    attempts = sum(item.attempts_used for item in checkpoint.step_results)
    elapsed = sum(item.elapsed_seconds for item in checkpoint.step_results)
    changed = sum(item.changed_object_count for item in checkpoint.step_results)
    preserved = max((item.preserved_object_count for item in checkpoint.step_results), default=0)
    return BaselineComparison(
        iterative_attempts=attempts,
        full_regeneration_attempts=full_regeneration_attempts,
        iterative_elapsed_seconds=elapsed,
        full_regeneration_elapsed_seconds=full_regeneration_elapsed_seconds,
        iterative_changed_object_count=changed,
        full_regeneration_changed_object_count=full_regeneration_changed_object_count,
        preserved_object_count=preserved,
        attempt_reduction=full_regeneration_attempts - attempts,
        changed_object_reduction=full_regeneration_changed_object_count - changed,
        time_reduction_seconds=full_regeneration_elapsed_seconds - elapsed,
    )
