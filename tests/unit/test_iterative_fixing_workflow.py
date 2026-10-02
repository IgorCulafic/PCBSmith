from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pcbsmith.iterative_fixing_workflow import (
    WorkflowStepOutcome,
    WorkflowStepResult,
    build_evidence_manifest,
    compare_with_full_regeneration,
    promote_candidate_atomically,
    run_iterative_fix_workflow,
)


def _result(step: str, outcome: WorkflowStepOutcome, evidence: str) -> WorkflowStepResult:
    return WorkflowStepResult(
        step_id=step,
        outcome=outcome,
        result_fingerprint=hashlib.sha256(step.encode()).hexdigest(),
        evidence_paths=(evidence,),
        attempts_used=1,
        elapsed_seconds=1,
        changed_object_count=1,
        preserved_object_count=9,
        blockers=(f"blocked:{step}",) if outcome is WorkflowStepOutcome.BLOCKED else (),
    )


def test_workflow_stops_at_blocker_and_resume_does_not_repeat(tmp_path: Path) -> None:
    board = tmp_path / "x.kicad_pcb"
    board.write_text("board", encoding="utf-8")
    calls: list[str] = []

    def runner(step: str, outcome: WorkflowStepOutcome):
        def run() -> WorkflowStepResult:
            calls.append(step)
            return _result(step, outcome, "evidence.json")

        return run

    runners = {
        "IF1": runner("IF1", WorkflowStepOutcome.ACCEPTED),
        "IF2": runner("IF2", WorkflowStepOutcome.BLOCKED),
        "IF3": runner("IF3", WorkflowStepOutcome.ACCEPTED),
        "IF4": runner("IF4", WorkflowStepOutcome.ACCEPTED),
        "IF5": runner("IF5", WorkflowStepOutcome.ACCEPTED),
    }
    first = run_iterative_fix_workflow(
        case_id="case",
        source_board=board,
        configuration_fingerprint="c" * 64,
        checkpoint_path=tmp_path / "checkpoint.json",
        runners=runners,
    )
    second = run_iterative_fix_workflow(
        case_id="case",
        source_board=board,
        configuration_fingerprint="c" * 64,
        checkpoint_path=tmp_path / "checkpoint.json",
        runners=runners,
    )
    assert first == second
    assert calls == ["IF1", "IF2"]


def test_manifest_fails_closed_on_missing_evidence(tmp_path: Path) -> None:
    board = tmp_path / "x.kicad_pcb"
    board.write_text("board", encoding="utf-8")
    runners = {
        step: (lambda value=step: _result(value, WorkflowStepOutcome.ACCEPTED, "missing.json"))
        for step in ("IF1", "IF2", "IF3", "IF4", "IF5")
    }
    checkpoint = run_iterative_fix_workflow(
        case_id="case",
        source_board=board,
        configuration_fingerprint="c" * 64,
        checkpoint_path=tmp_path / "checkpoint.json",
        runners=runners,
    )
    manifest = build_evidence_manifest(checkpoint, root=tmp_path)
    assert not manifest.complete
    assert manifest.missing_paths == ("missing.json",)


def test_atomic_promotion_and_baseline_comparison(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.kicad_pcb"
    candidate.write_text("candidate", encoding="utf-8")
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    accepted = _result("IF5", WorkflowStepOutcome.ACCEPTED, "evidence.json").model_copy(
        update={"candidate_path": str(candidate), "candidate_sha256": digest}
    )
    assert (
        promote_candidate_atomically(accepted, canonical_board=tmp_path / "current.kicad_pcb")
        == digest
    )
    with pytest.raises(ValueError, match="accepted"):
        promote_candidate_atomically(
            _result("IF2", WorkflowStepOutcome.BLOCKED, "evidence.json"),
            canonical_board=tmp_path / "bad.kicad_pcb",
        )

    board = tmp_path / "source.kicad_pcb"
    board.write_text("source", encoding="utf-8")
    runners = {
        step: (lambda value=step: _result(value, WorkflowStepOutcome.ACCEPTED, "evidence.json"))
        for step in ("IF1", "IF2", "IF3", "IF4", "IF5")
    }
    checkpoint = run_iterative_fix_workflow(
        case_id="baseline",
        source_board=board,
        configuration_fingerprint="d" * 64,
        checkpoint_path=tmp_path / "baseline.json",
        runners=runners,
    )
    comparison = compare_with_full_regeneration(
        checkpoint=checkpoint,
        full_regeneration_attempts=9,
        full_regeneration_elapsed_seconds=20,
        full_regeneration_changed_object_count=50,
    )
    assert comparison.attempt_reduction == 4
    assert comparison.changed_object_reduction == 45
