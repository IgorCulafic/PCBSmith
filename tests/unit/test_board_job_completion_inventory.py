from __future__ import annotations

import hashlib
import json

import pytest
from tests.unit.test_board_job import Clock, claim, finish
from tests.unit.test_board_job_diagnostic import assessment

from pcbsmith.board_job import BoardJob, ContinuationRequest, JobStopped


def completion(tmp_path, operation="native-preparation"):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="completion fixture")
    for cycle, key in enumerate("abc"):
        if cycle:
            job.correction(reason="distinct input defect", change="resolved source input")
        finish(job, claim(job, operation=operation, key=key))
    job.begin_diagnostic("operation allowance exhausted")
    report = assessment(tmp_path).model_copy(update={"action": "local_edit"})
    job.complete_diagnostic(report)
    job.stop("retain diagnosed attempt")
    path = tmp_path / "assessment.json"
    path.write_text(report.model_dump_json())
    request = ContinuationRequest(
        predecessor_sha256=hashlib.sha256(job.path.read_bytes()).hexdigest(),
        assessment_file=path.name,
        assessment_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_reference="Human explicitly requested completion after the diagnostic",
        seconds=600,
        reserve_seconds=120,
        evaluation_seconds=1200,
        build_operations=(operation,),
        blocker_resolution="Source input repaired; one further invocation, all checks retained",
        resolved_evidence=report.evidence,
        completion_allowances={operation: 1, "visual-render": 2},
    )
    return job, clock, request


def test_completion_keeps_all_history_and_allows_only_declared_counts(tmp_path):
    job, clock, request = completion(tmp_path)
    raw = job.path.read_bytes()
    job.continue_authorized(request)
    finish(job, claim(job, operation="native-preparation", key="d"))
    for key in "ef":
        finish(job, claim(job, operation="visual-render", phase="verify", key=key))
    restarted = BoardJob(tmp_path, clock=clock, monotonic=clock)
    state = restarted.snapshot()
    assert len(state.attempts) == 6 and state.cycle == 2
    assert state.started_at == 1000 and state.deadline == 2800
    assert (tmp_path / ".pcbsmith/continuation-predecessor.json").read_bytes() == raw
    with pytest.raises(JobStopped, match="completion inventory"):
        claim(restarted, operation="visual-render", phase="verify", key="g")


def test_completion_rejects_unlisted_verification_and_unchanged_input(tmp_path):
    job, _, request = completion(tmp_path)
    job.continue_authorized(request)
    with pytest.raises(JobStopped, match="identical"):
        claim(job, operation="native-preparation", key="c")
    with pytest.raises(JobStopped, match="completion inventory"):
        claim(job, operation="routed-review", phase="verify", key="d")


def test_completion_cannot_regenerate_placement(tmp_path):
    job, _, request = completion(tmp_path, operation="placement")
    with pytest.raises(JobStopped, match="regenerate"):
        job.continue_authorized(request)


def restored_input_fixture(tmp_path, monkeypatch):
    job, clock, request = completion(tmp_path, operation="predesign-approve")
    job.continue_authorized(request)
    prepared = tmp_path / "prepared"
    native = tmp_path / "native"
    prepared.mkdir()
    native.mkdir()
    (prepared / "prepared-inputs.json").write_text(
        json.dumps(
            {
                "native_project_path": str(native),
                "component_readiness_sha256": "a" * 64,
            }
        )
    )
    monkeypatch.setattr(
        "pcbsmith.kicad.component_readiness.require_component_readiness_snapshot",
        lambda *a, **k: None,
    )
    command = (
        "pcbsmith.predesign_preparation",
        "approve",
        str(prepared),
        "engineering",
        "assertion",
    )
    attempt = job.claim(
        operation="predesign-approve", phase="build", input_sha256="d" * 64, command=command
    )
    finish(job, attempt, "failed", "cache mismatch")
    logs = tmp_path / ".pcbsmith/job-runs" / attempt.token / "logs"
    logs.mkdir(parents=True)
    (logs / "predesign-approve.stderr.txt").write_text(
        "ValueError: Missing or stale native input closure: netlist_sha256\n"
    )
    job.begin_diagnostic("cache only")
    job.complete_diagnostic(assessment(tmp_path).model_copy(update={"action": "local_edit"}))
    return job, command, prepared, logs


def test_restored_input_keeps_deadline_and_allows_one_exact_retry(tmp_path, monkeypatch):
    job, command, _, _ = restored_input_fixture(tmp_path, monkeypatch)
    before = job.snapshot()
    job.authorize_restored_predesign_input(authorization="User authorized routine completion")
    attempt = job.claim(
        operation="predesign-approve", phase="build", input_sha256="d" * 64, command=command
    )
    finish(job, attempt)
    after = job.snapshot()
    assert after.deadline == before.deadline
    assert after.continuation.deadline == before.continuation.deadline
    assert len(after.attempts) == len(before.attempts) + 1
    with pytest.raises(JobStopped):
        job.authorize_restored_predesign_input(authorization="again")


def test_restored_input_rejects_changed_source(tmp_path, monkeypatch):
    job, command, prepared, _ = restored_input_fixture(tmp_path, monkeypatch)
    job.authorize_restored_predesign_input(authorization="User authorized routine completion")
    (prepared / "prepared-inputs.json").write_text("changed")
    with pytest.raises(JobStopped, match="inputs changed"):
        job.claim(
            operation="predesign-approve", phase="build", input_sha256="e" * 64, command=command
        )


def test_restored_input_rejects_other_failure(tmp_path, monkeypatch):
    job, _, _, logs = restored_input_fixture(tmp_path, monkeypatch)
    (logs / "predesign-approve.stderr.txt").write_text("Unrelated failure")
    with pytest.raises(JobStopped, match="exact netlist"):
        job.authorize_restored_predesign_input(authorization="User authorized routine completion")


def test_restored_input_rejects_malformed_binding_record(tmp_path, monkeypatch):
    job, command, _, _ = restored_input_fixture(tmp_path, monkeypatch)
    job.authorize_restored_predesign_input(authorization="User authorized routine completion")
    with job._access() as state:
        state.events[-1]["input_bindings"] = []
    with pytest.raises(JobStopped, match="bindings are invalid"):
        job.claim(
            operation="predesign-approve", phase="build", input_sha256="e" * 64, command=command
        )


def test_completion_remains_one_shot_and_failure_still_stops_build(tmp_path):
    job, _, request = completion(tmp_path)
    job.continue_authorized(request)
    finish(job, claim(job, operation="native-preparation", key="d"), "failed", "new failure")
    with pytest.raises(JobStopped, match="diagnostic"):
        claim(job, operation="native-preparation", key="e")
    request = request.model_copy(
        update={
            "predecessor_sha256": hashlib.sha256(job.path.read_bytes()).hexdigest(),
            "authorization_reference": "different text cannot renew inventory",
        }
    )
    with pytest.raises(JobStopped, match="cannot renew"):
        job.continue_authorized(request)


@pytest.mark.parametrize("allowances", [{"routing": 2}, {"unknown": 1}, {"edit": 2}])
def test_completion_rejects_expanded_or_unknown_build_allowances(tmp_path, allowances):
    _, _, request = completion(tmp_path)
    with pytest.raises(ValueError, match="finite evidenced"):
        ContinuationRequest.model_validate(
            {
                **request.model_dump(),
                "completion_allowances": allowances,
            }
        )


def annotation_fixture(tmp_path, violation="silk_overlap"):
    job, clock, request = completion(tmp_path, operation="edit")
    job.continue_authorized(request)
    output = tmp_path / "failed-edit"
    (output / "design").mkdir(parents=True)
    (output / "checks").mkdir()
    board = output / "design/fixture.kicad_pcb"
    board.write_text("Synthetic native fixture")
    inputs = {board.name: hashlib.sha256(board.read_bytes()).hexdigest()}
    (output / "revision.json").write_text(json.dumps({"candidate_inputs": inputs}))
    (output / "checks/summary.json").write_text(json.dumps({"erc_findings": 0}))
    (output / "checks/drc.json").write_text(
        json.dumps(
            {
                "schematic_parity": [],
                "violations": [{"type": violation}],
            }
        )
    )
    attempt = job.claim(
        operation="edit",
        phase="build",
        input_sha256="d" * 64,
        command=("pcbsmith.cli", "production-edit-board", str(board), "--output", str(output)),
    )
    finish(job, attempt, "failed", "annotation")
    job.begin_diagnostic("source-bound annotation finding")
    job.complete_diagnostic(assessment(tmp_path).model_copy(update={"action": "local_edit"}))
    from pcbsmith.board_revision import BoardRevisionRequest

    edit = BoardRevisionRequest(
        source_inputs=inputs,
        validation_stage="unrouted_annotations",
        rationale="Move collided reference only",
        edits=[
            {
                "kind": "reference",
                "target": "fixture",
                "position_mm": [0, 2.5],
            }
        ],
    )
    path = tmp_path / "annotation.json"
    path.write_text(edit.model_dump_json())
    return job, clock, path


def test_annotation_completion_preserves_clock_and_limits_followup(tmp_path):
    job, clock, path = annotation_fixture(tmp_path)
    before = job.snapshot()
    job.authorize_completion_annotation(request_file=path.name, authorization="Finish routine work")
    state = job.snapshot()
    assert state.continuation.deadline == before.continuation.deadline
    assert state.continuation.request == before.continuation.request
    assert state.events[-1]["checkpoint"]["status"] == "complete"
    with pytest.raises(JobStopped, match="exact reviewed request"):
        claim(job, operation="edit", key="e")
    followup = job.claim(
        operation="edit",
        phase="build",
        input_sha256="e" * 64,
        command=("pcbsmith.cli", "production-edit-board", "--request", str(path)),
    )
    finish(job, followup)
    assert len(BoardJob(tmp_path, clock=clock, monotonic=clock).snapshot().attempts) == 5
    with pytest.raises(JobStopped):
        job.authorize_completion_annotation(request_file=path.name, authorization="No renewal")
    with pytest.raises(JobStopped):
        claim(job, operation="edit", key="f")


def test_annotation_completion_rejects_electrical_or_copper_failure(tmp_path):
    job, _, path = annotation_fixture(tmp_path, violation="clearance")
    with pytest.raises(JobStopped, match="cannot waive"):
        job.authorize_completion_annotation(request_file=path.name, authorization="Finish")


def test_annotation_completion_rejects_changed_candidate(tmp_path):
    job, _, path = annotation_fixture(tmp_path)
    (tmp_path / "failed-edit/design/fixture.kicad_pcb").write_text("changed")
    with pytest.raises(JobStopped, match="candidate changed"):
        job.authorize_completion_annotation(request_file=path.name, authorization="Finish")
