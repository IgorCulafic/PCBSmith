"""Synthetic guard tests; actual native board qualification remains separate."""

from __future__ import annotations

import hashlib
import json

import pytest
from tests.unit.test_board_job import BoardJob, Clock, finish
from tests.unit.test_board_job_diagnostic import assessment

from pcbsmith.board_job import ContinuationRequest, JobStopped, _validate_placement_followup
from pcbsmith.board_revision import BoardRevisionRequest, _require_unrouted_annotations


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def followup(tmp_path):
    root = tmp_path.resolve()
    board = root / "board.kicad_pcb"
    board.write_text("(kicad_pcb)")
    old = BoardRevisionRequest(
        source_inputs={board.name: sha(board)},
        rationale="Synthetic earlier annotation only",
        validation_stage="unrouted_annotations",
        edits=[{"kind": "reference", "target": "R1", "position_mm": [0, -2]}],
    )
    old_path = root / "old.json"
    old_path.write_text(old.model_dump_json())
    clock = Clock()
    job = BoardJob(root, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="Synthetic placement follow-up")
    command = ("pcbsmith.cli", "production-edit-board", str(board), "--request", str(old_path))
    finish(job, job.claim(operation="edit", phase="build", input_sha256="a" * 64, command=command))
    job.begin_diagnostic("Synthetic missing pose stage")
    diagnostic = assessment(root)
    job.complete_diagnostic(diagnostic)
    (root / "diagnostic.json").write_text(diagnostic.model_dump_json())
    job.stop("Synthetic stopped scope")
    edits = [{"kind": "component", "target": "R1", "position_mm": [10, 10], "rotation_deg": 180}]
    plan = root / "plan.json"
    plan.write_text(
        json.dumps({"board": board.name, "source_inputs": {board.name: sha(board)}, "edits": edits})
    )
    request = ContinuationRequest(
        predecessor_sha256=sha(job.path),
        assessment_file="diagnostic.json",
        assessment_sha256=sha(root / "diagnostic.json"),
        authorization_reference="Explicit new synthetic pose approval",
        seconds=600,
        reserve_seconds=120,
        build_operations=("edit", "apply-edit", "predesign-refresh", "predesign-reapprove"),
        blocker_resolution="Qualified exact pose-only path after annotations",
        resolved_evidence={"plan.json": sha(plan)},
        placement_followup_plan="plan.json",
    )
    new = BoardRevisionRequest(
        source_inputs={board.name: sha(board)},
        rationale="Synthetic requested rotation",
        validation_stage="unrouted_placement",
        edits=edits,
    )
    new_path = root / "new.json"
    new_path.write_text(new.model_dump_json())
    new_command = ("pcbsmith.cli", "production-edit-board", str(board), "--request", str(new_path))
    return job, request, board, old_path, new_path, new_command


def test_explicit_followup_retains_history_and_allows_only_one_pose_edit(followup):
    job, request, _, _, _, command = followup
    before = job.snapshot()
    job.continue_authorized(request)
    after = job.snapshot()
    assert after.cycle == before.cycle and after.started_at == before.started_at
    assert after.attempts == before.attempts and after.deadline == before.deadline
    finish(job, job.claim(operation="edit", phase="build", input_sha256="b" * 64, command=command))
    with pytest.raises(JobStopped, match="one attempt"):
        job.claim(operation="edit", phase="build", input_sha256="c" * 64, command=command)


@pytest.mark.parametrize("mutation", ["plan", "board", "request", "prior_placement"])
def test_stale_or_different_scope_is_rejected(followup, mutation):
    job, request, board, old_path, new_path, command = followup
    if mutation == "plan":
        (job.root / "plan.json").write_text("{}")
    elif mutation == "board":
        board.write_text("(kicad_pcb (segment))")
    elif mutation == "request":
        payload = json.loads(new_path.read_text())
        payload["edits"][0]["rotation_deg"] = 90
        new_path.write_text(json.dumps(payload))
    else:
        old_path.write_bytes(new_path.read_bytes())
    with pytest.raises((JobStopped, ValueError)):
        _validate_placement_followup(
            job.root, job.snapshot().attempts, request, operation="edit", command=command
        )


def test_apply_is_bound_to_the_same_pose_request(followup):
    job, request, board, _, new_path, _ = followup
    revision = job.root / "revision"
    revision.mkdir()
    (revision / "request.json").write_bytes(new_path.read_bytes())
    command = (
        "pcbsmith.cli",
        "production-apply-board-edit",
        str(board),
        "--revision",
        str(revision),
    )
    _validate_placement_followup(
        job.root, job.snapshot().attempts, request, operation="apply-edit", command=command
    )
    (revision / "request.json").write_text((new_path.read_text()).replace("180.0", "90.0"))
    with pytest.raises(JobStopped, match="exact approved"):
        _validate_placement_followup(
            job.root, job.snapshot().attempts, request, operation="apply-edit", command=command
        )


@pytest.mark.parametrize(
    "edit",
    [
        {"kind": "reference", "target": "R1", "position_mm": [0, -2]},
        {"kind": "segment_remove", "target": "trace"},
        {"kind": "model_offset", "target": "R1", "offset_mm": [0, 0, 1]},
    ],
)
def test_placement_stage_rejects_non_pose_scope(edit):
    with pytest.raises(ValueError, match="poses and annotations only"):
        BoardRevisionRequest(
            source_inputs={"b": "a" * 64},
            rationale="Synthetic invalid scope",
            validation_stage="unrouted_placement",
            edits=[edit],
        )


@pytest.mark.parametrize("kind", ["segment", "arc", "via", "zone"])
def test_pre_route_guard_rejects_existing_copper(tmp_path, kind):
    board = tmp_path / "board.kicad_pcb"
    board.write_text(f"(kicad_pcb ({kind}))")
    with pytest.raises(ValueError, match="no tracks"):
        _require_unrouted_annotations(board)
