from __future__ import annotations

import hashlib

import pytest
from tests.unit.test_board_job import Clock, claim, finish

from pcbsmith.board_job import BoardJob, DiagnosticRecommendation, JobStopped


@pytest.fixture
def job(tmp_path):
    clock = Clock()
    instance = BoardJob(tmp_path, clock=clock, monotonic=clock)
    instance.start(complexity="simple", rationale="diagnostic fixture")
    return instance, clock


def assessment(root):
    path = root / "finding.txt"
    path.write_text("retained failure evidence", encoding="utf-8")
    return DiagnosticRecommendation(
        cause="platform",
        progress_assessment="Native preparation passed; routing not reached.",
        root_cause_analysis="Input loader used a different library source.",
        alternatives_considered="Rebuilding the circuit does not address the input loader.",
        action="platform_work",
        rationale="Repair the shared source resolver separately.",
        estimated_seconds=600,
        verification_criteria=("Exact retained source replays.",),
        uncertainties="Fresh routed acceptance remains unverified.",
        evidence={"finding.txt": hashlib.sha256(path.read_bytes()).hexdigest()},
    )


def exhaust(instance):
    for cycle, key in enumerate("abc"):
        if cycle:
            instance.correction(reason="diagnosed issue", change="new effective inputs")
        finish(instance, claim(instance, key=key))
    with pytest.raises(JobStopped, match="allowance"):
        instance.correction(reason="again", change="again")


def test_limit_queues_one_checkpoint_and_blocks_unrelated_build(job):
    instance, _ = job
    exhaust(instance)
    state = instance.snapshot()
    assert state.diagnostic.status == "pending"
    with pytest.raises(JobStopped, match="diagnostic"):
        claim(instance, operation="another-build")
    assert instance.snapshot().cycle == 2


def test_repeat_failure_triggers_before_limit(job):
    instance, _ = job
    finish(instance, claim(instance), "failed", "same-obstruction")
    instance.correction(reason="obstruction", change="move one component")
    finish(instance, claim(instance, key="b"), "failed", "same-obstruction")
    state = instance.snapshot()
    assert state.cycle == 1 and state.diagnostic.status == "pending"
    review = instance.begin_diagnostic("Review repeated obstruction")
    assert review.deadline == review.started_at + 300


def test_last_cycle_failure_queues_checkpoint_without_extra_retry(job):
    instance, _ = job
    for cycle, key in enumerate("abc"):
        if cycle:
            instance.correction(reason="diagnosed failure", change="different inputs")
        finish(instance, claim(instance, key=key), "failed", key)
    assert instance.snapshot().diagnostic.trigger == "failure after final corrective cycle"


def test_completed_review_cannot_authorize_attempt_or_reset_counters(job):
    instance, clock = job
    exhaust(instance)
    before = instance.snapshot()
    instance.begin_diagnostic("Broader assessment")
    clock.now += 20
    instance.complete_diagnostic(assessment(instance.root))
    after = instance.snapshot()
    assert after.diagnostic.status == "complete"
    assert (before.job_id, before.deadline, before.cycle, before.escalations) == (
        after.job_id,
        after.deadline,
        after.cycle,
        after.escalations,
    )
    with pytest.raises(JobStopped, match="diagnostic"):
        claim(instance, operation="new-stage")
    with pytest.raises(JobStopped, match="already started"):
        instance.begin_diagnostic("Try another review")
    finish(instance, claim(instance, operation="native-check", phase="verify", key="d"))


def test_window_clamped_before_verification_reserve(job):
    instance, clock = job
    clock.now += 1400
    d = instance.begin_diagnostic("Stagnation reported by reviewer")
    assert d.deadline - d.started_at == 40
    clock.now += 40
    with pytest.raises(JobStopped, match="expired"):
        instance.complete_diagnostic(assessment(instance.root))
    assert instance.snapshot().diagnostic.status == "expired"
    with pytest.raises(JobStopped):
        instance.begin_diagnostic("Cannot get more time")


def test_resumed_chat_cannot_restart_review(job):
    instance, clock = job
    instance.begin_diagnostic("Early review")
    clock.now += 301
    resumed = BoardJob(instance.root, clock=clock, monotonic=clock)
    with pytest.raises(JobStopped, match="expired"):
        resumed.complete_diagnostic(assessment(instance.root))
    with pytest.raises(JobStopped, match="already started"):
        resumed.begin_diagnostic("new chat")


def test_no_diagnostic_inside_reserve_or_after_deadline(job):
    instance, clock = job
    clock.now += 1440
    with pytest.raises(JobStopped, match="reserve"):
        instance.begin_diagnostic("too late")
    assert instance.snapshot().diagnostic is None
    clock.now += 360
    with pytest.raises(JobStopped):
        instance.begin_diagnostic("expired job")


def test_stale_evidence_rejected_without_granting_work(job):
    instance, _ = job
    instance.begin_diagnostic("Early review")
    report = assessment(instance.root)
    (instance.root / "finding.txt").write_text("changed")
    with pytest.raises(ValueError, match="evidence changed"):
        instance.complete_diagnostic(report)
    with pytest.raises(JobStopped, match="diagnostic"):
        claim(instance)


def test_no_concurrent_worker_review(job):
    instance, _ = job
    claim(instance)
    with pytest.raises(JobStopped, match="active worker"):
        instance.begin_diagnostic("Review cannot race worker")


def test_clock_rollback_does_not_extend_window(job):
    instance, clock = job
    instance.begin_diagnostic("Early review")
    clock.now -= 10
    with pytest.raises(JobStopped, match="clock"):
        instance.complete_diagnostic(assessment(instance.root))


def test_blank_assessment_is_not_a_diagnosis(job):
    instance, _ = job
    payload = assessment(instance.root).model_dump()
    payload["root_cause_analysis"] = " "
    with pytest.raises(ValueError, match="blank"):
        DiagnosticRecommendation.model_validate(payload)


def test_legacy_ledger_without_diagnostic_loads_without_budget_reset(job):
    import json

    from pcbsmith.board_job import _digest

    instance, clock = job
    envelope = json.loads(instance.path.read_text())
    envelope["state"].pop("diagnostic")
    envelope["sha256"] = _digest(envelope["state"])
    instance.path.write_text(json.dumps(envelope))
    state = BoardJob(instance.root, clock=clock, monotonic=clock).snapshot()
    assert state.diagnostic is None and state.deadline == 2800


def test_cli_records_assessment_without_authorizing_work(job, monkeypatch, capsys):
    from pcbsmith import board_job

    instance, _ = job
    monkeypatch.setattr(board_job, "BoardJob", lambda root: instance)
    assert board_job.main(["diagnose-start", str(instance.root), "--reason", "No progress"]) == 0
    path = instance.root / "assessment.json"
    path.write_text(assessment(instance.root).model_dump_json(), encoding="utf-8")
    assert board_job.main(["diagnose-complete", str(instance.root), "--assessment", str(path)]) == 0
    assert '"authorizes_work": false' in capsys.readouterr().out
    with pytest.raises(JobStopped, match="diagnostic"):
        claim(instance)


def test_cancellation_resume_does_not_clear_diagnostic_hold(job):
    instance, _ = job
    instance.begin_diagnostic("Early stagnation")
    instance.stop("pause")
    instance.resume("same allowance")
    with pytest.raises(JobStopped, match="diagnostic"):
        instance.correction(reason="try again", change="different board")
    assert instance.snapshot().diagnostic.started_at == 1000


def test_concurrent_review_start_cannot_mint_two_windows(job):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    instance, clock = job
    barrier = Barrier(2)

    def attempt(_):
        other = BoardJob(instance.root, clock=clock, monotonic=clock)
        barrier.wait()
        try:
            other.begin_diagnostic("Concurrent assessment")
            return "started"
        except JobStopped:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["blocked", "started"]
    assert instance.snapshot().diagnostic.deadline == 1300
