"""Separate clocks preserve finite supervision and old trial identities."""

import json

import pytest
from tests.unit.test_board_job import Clock, claim, finish

from pcbsmith.board_job import BoardJob, JobStopped, main


def job_at(tmp_path):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="separate timing fixture", evaluation_seconds=1200)
    return job, clock


def test_evaluation_and_execution_do_not_consume_each_other(tmp_path):
    job, clock = job_at(tmp_path)
    clock.now += 1100
    first = claim(job)
    assert job.remaining(first.token) == 1440
    clock.now += 1300
    assert job.remaining(first.token) == 140
    finish(job, first)
    resumed = BoardJob(tmp_path, clock=clock, monotonic=clock)
    clock.now += 90
    state = resumed.snapshot()
    assert state.status == "active"
    assert state.timing_usage(clock.now) == dict(
        mode="separate",
        scope_wall_seconds=2490,
        total_wall_seconds=2490,
        execution_seconds=1300,
        evaluation_seconds=1190,
    )
    review = claim(resumed, operation="review", phase="verify", key="b")
    assert resumed.remaining(review.token) == 500


def test_reserve_is_execution_time_even_after_long_evaluation(tmp_path):
    job, clock = job_at(tmp_path)
    clock.now += 1100
    first = claim(job)
    clock.now += 1440
    with pytest.raises(JobStopped, match="reserve"):
        job.remaining(first.token)
    finish(job, first, "stopped")
    assert job.snapshot().status == "active"
    review = claim(job, operation="review", phase="verify", key="b")
    assert job.remaining(review.token) == 360
    clock.now += 360
    with pytest.raises(JobStopped, match="execution allowance"):
        job.remaining(review.token)


def test_evaluation_cannot_be_paused_by_new_instance_or_status(tmp_path):
    job, clock = job_at(tmp_path)
    clock.now += 600
    job.snapshot()
    clock.now += 600
    resumed = BoardJob(tmp_path, clock=clock, monotonic=clock)
    with pytest.raises(JobStopped, match="evaluation allowance"):
        claim(resumed)
    assert resumed.snapshot().attempts == []


def test_terminal_execution_needs_exact_timestamps(tmp_path):
    job, clock = job_at(tmp_path)
    attempt = claim(job)
    clock.now += 5
    finish(job, attempt)
    state = job.snapshot()
    payload = state.model_dump()
    payload["attempts"][0].pop("ended_at")
    with pytest.raises(ValueError, match="timing is missing"):
        type(state).model_validate(payload)


def test_cli_starts_separate_clocks(tmp_path, capsys):
    assert main(["start", str(tmp_path), "--rationale", "fixture"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["evaluation_seconds"] == 1200
    assert result["limit_seconds"] == 1800
    assert result["timing"]["mode"] == "separate"


def test_visual_render_is_verification_and_output_does_not_reset_identity(tmp_path):
    from pcbsmith.board_job import input_identity, operation_for

    first = ["visual-review", "board.kicad_pcb", "out-a", "--stage", "final"]
    second = ["visual-review", "board.kicad_pcb", "out-b", "--stage", "final"]
    assert operation_for("pcbsmith.cli", first) == ("visual-render", "verify")
    assert input_identity("pcbsmith.cli", first) == input_identity("pcbsmith.cli", second)


def test_completed_timing_does_not_grow_or_expire_after_handover(tmp_path):
    job, clock = job_at(tmp_path)
    clock.now += 30
    attempt = claim(job)
    clock.now += 60
    finish(job, attempt)
    job.stop("completed fixture", finished=True)
    before = job.snapshot().timing_usage(clock.now)
    clock.now += 10000
    after = job.snapshot()
    assert after.status == "finished"
    assert after.timing_usage(clock.now) == before
    assert before["total_wall_seconds"] == 90
