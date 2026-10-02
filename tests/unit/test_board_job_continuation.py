from __future__ import annotations

import hashlib

import pytest
from tests.unit.test_board_job import Clock, claim, finish
from tests.unit.test_board_job_diagnostic import assessment

from pcbsmith.board_job import BoardJob, ContinuationRequest, JobStopped


@pytest.fixture
def stopped(tmp_path):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="synthetic continuation fixture")
    for cycle, key in enumerate("abc"):
        if cycle:
            job.correction(reason="fixture failure", change="different input")
        finish(job, claim(job, operation="placement", key=key))
    job.stop("allowance exhausted")
    clock.now += 2000
    report = assessment(tmp_path).model_copy(update={"action": "local_edit"})
    path = tmp_path / "assessment.json"
    path.write_text(report.model_dump_json())
    request = ContinuationRequest(
        predecessor_sha256=hashlib.sha256(job.path.read_bytes()).hexdigest(),
        assessment_file="assessment.json",
        assessment_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_reference="Explicit synthetic user continuation decision",
        seconds=600,
        reserve_seconds=120,
        build_operations=("edit", "routing"),
    )
    return job, clock, request


def test_continuation_retains_original_limits_and_history(stopped):
    job, clock, request = stopped
    raw = job.path.read_bytes()
    job.continue_authorized(request)
    state = job.snapshot()
    assert (job.root / ".pcbsmith/continuation-predecessor.json").read_bytes() == raw
    assert state.deadline == 2800 and state.started_at == 1000 and state.cycle == 2
    assert len(state.attempts) == 3 and len(state.corrections) == 2
    assert state.active_deadline == clock.now + 600
    finish(job, claim(job, operation="edit", key="d"))
    finish(job, claim(job, operation="routing", key="e"))
    with pytest.raises(JobStopped, match="allowance"):
        claim(job, operation="edit", key="f")
    assert job.snapshot().continuation.diagnostic is not None


def test_continuation_cannot_reset_on_new_instance(stopped):
    job, clock, request = stopped
    job.continue_authorized(request)
    restarted = BoardJob(job.root, clock=clock, monotonic=clock)
    updated = request.model_copy(
        update={"predecessor_sha256": hashlib.sha256(job.path.read_bytes()).hexdigest()}
    )
    with pytest.raises(JobStopped, match="one continuation"):
        restarted.continue_authorized(updated)
    assert restarted.snapshot().continuation.deadline == 3600


def test_continuation_scope_and_expiry(stopped):
    job, clock, request = stopped
    job.continue_authorized(request)
    with pytest.raises(JobStopped, match="scope"):
        claim(job, operation="placement", key="d")
    clock.now += 480
    with pytest.raises(JobStopped, match="reserve"):
        claim(job, operation="edit", key="d")
    finish(job, claim(job, operation="inspect", phase="verify", key="e"))
    clock.now += 120
    with pytest.raises(JobStopped, match="deadline"):
        claim(job, operation="routed-review", phase="verify", key="f")


def test_failed_continuation_enters_new_bounded_diagnostic(stopped):
    job, clock, request = stopped
    job.continue_authorized(request)
    finish(job, claim(job, operation="edit", key="d"), "failed", "blocked")
    with pytest.raises(JobStopped, match="diagnostic"):
        claim(job, operation="routing", key="e")
    review = job.begin_diagnostic("Broader review of failed edit")
    assert review.deadline == clock.now + 300
    job.complete_diagnostic(assessment(job.root))
    with pytest.raises(JobStopped, match="diagnostic"):
        claim(job, operation="routing", key="f")
    assert job.snapshot().cycle == 2


def test_stale_request_and_evidence_rejected_without_ledger_mutation(stopped):
    job, _, request = stopped
    raw = job.path.read_bytes()
    bad = request.model_copy(update={"predecessor_sha256": "0" * 64})
    with pytest.raises(JobStopped, match="predecessor changed"):
        job.continue_authorized(bad)
    (job.root / "finding.txt").write_text("changed")
    with pytest.raises(JobStopped, match="evidence changed"):
        job.continue_authorized(request)
    assert job.path.read_bytes() == raw


def test_continuation_grants_no_correction_cycles(stopped):
    job, _, request = stopped
    job.continue_authorized(request)
    with pytest.raises(JobStopped, match="allowance"):
        job.correction(reason="retry", change="new inputs")
    assert job.snapshot().cycle == 2


def test_no_continuation_with_unsettled_worker(stopped):
    job, _, request = stopped
    # Synthetic old unsettled lease; not a normal board mutation.
    with job._access() as state:
        state.attempts[-1].status = "running"
    request = request.model_copy(
        update={"predecessor_sha256": hashlib.sha256(job.path.read_bytes()).hexdigest()}
    )
    with pytest.raises(JobStopped, match="active worker"):
        job.continue_authorized(request)


def test_blank_authorization_and_small_reserve_rejected(stopped):
    _, _, request = stopped
    for field, value in (("authorization_reference", " "), ("reserve_seconds", 1)):
        payload = request.model_dump()
        payload[field] = value
        with pytest.raises(ValueError):
            ContinuationRequest.model_validate(payload)


def test_cli_continuation_retains_job_identity(stopped, monkeypatch, capsys):
    from pcbsmith import board_job

    job, _, request = stopped
    monkeypatch.setattr(board_job, "BoardJob", lambda root: job)
    path = job.root / "continuation-request.json"
    path.write_text(request.model_dump_json())
    assert board_job.main(["continue-authorized", str(job.root), "--request", str(path)]) == 0
    assert '"explicit_continuation"' in capsys.readouterr().out
    assert job.snapshot().cycle == 2


def test_concurrent_continuation_cannot_grant_two_windows(stopped):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    job, clock, request = stopped
    barrier = Barrier(2)

    def grant(_):
        other = BoardJob(job.root, clock=clock, monotonic=clock)
        barrier.wait()
        try:
            other.continue_authorized(request)
            return "granted"
        except JobStopped:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(grant, range(2))) == ["blocked", "granted"]


def test_original_diagnostic_is_preserved_after_explicit_continuation(stopped):
    from pcbsmith.board_job import DiagnosticCheckpoint

    job, _, request = stopped
    with job._access() as state:
        state.diagnostic = DiagnosticCheckpoint(
            trigger="old exhausted allowance", requested_at=2000
        )
    request = request.model_copy(
        update={"predecessor_sha256": hashlib.sha256(job.path.read_bytes()).hexdigest()}
    )
    job.continue_authorized(request)
    finish(job, claim(job, operation="edit", key="d"))
    assert job.snapshot().diagnostic.trigger == "old exhausted allowance"
    assert job.snapshot().continuation.diagnostic is None


def recovery_request(job, initial):
    job.begin_diagnostic("Upstream evidence missing")
    job.complete_diagnostic(assessment(job.root))
    job.stop("Await evidence preparation")
    path = job.root / "resolution.txt"
    path.write_text("synthetic resolved prerequisite")
    (job.root / "resolved-assessment.json").write_text(assessment(job.root).model_dump_json())
    return initial.model_copy(
        update={
            "predecessor_sha256": hashlib.sha256(job.path.read_bytes()).hexdigest(),
            "assessment_file": "resolved-assessment.json",
            "assessment_sha256": hashlib.sha256(
                (job.root / "resolved-assessment.json").read_bytes()
            ).hexdigest(),
            "authorization_reference": "New explicit user instruction after resolving the blocker",
            "blocker_resolution": "Prepared the missing synthetic prerequisite",
            "resolved_evidence": {"resolution.txt": hashlib.sha256(path.read_bytes()).hexdigest()},
            "build_operations": ("routing",),
        }
    )


def test_resolved_blocker_recovery_retains_all_prior_scopes(stopped):
    job, clock, request = stopped
    job.continue_authorized(request)
    finish(job, claim(job, operation="edit", key="d"))
    recovery = recovery_request(job, request)
    predecessor = job.path.read_bytes()
    job.continue_authorized(recovery)
    state = job.snapshot()
    assert len(state.continuation_history) == 1
    assert state.continuation_history[0].diagnostic.status == "complete"
    assert state.cycle == 2 and state.deadline == 2800
    assert (job.root / ".pcbsmith/continuation-predecessor-2.json").read_bytes() == predecessor
    finish(job, claim(job, operation="routing", key="e"))
    with pytest.raises(JobStopped):
        job.correction(reason="again", change="more retries")


def test_resolved_blocker_cannot_reuse_authorization(stopped):
    job, _, request = stopped
    job.continue_authorized(request)
    recovery = recovery_request(job, request)
    recovery = recovery.model_copy(
        update={"authorization_reference": request.authorization_reference}
    )
    with pytest.raises(JobStopped, match="new explicit"):
        job.continue_authorized(recovery)


def test_resolved_blocker_requires_unchanged_evidence(stopped):
    job, _, request = stopped
    job.continue_authorized(request)
    recovery = recovery_request(job, request)
    before = job.path.read_bytes()
    (job.root / "resolution.txt").write_text("changed")
    with pytest.raises(JobStopped, match="resolution evidence changed"):
        job.continue_authorized(recovery)
    assert job.path.read_bytes() == before


def test_new_user_recovery_can_retry_only_bound_failed_routing(stopped):
    job, _, request = stopped
    job.continue_authorized(request)
    attempted = claim(job, operation="routing", key="d")
    finish(job, attempted, "failed", "expansion budget")
    recovery = recovery_request(job, request)
    recovery = recovery.model_copy(update={"retry_failed_operations": {"routing": attempted.token}})
    job.continue_authorized(recovery)
    with pytest.raises(JobStopped, match="identical effective"):
        claim(job, operation="routing", key="d")
    finish(job, claim(job, operation="routing", key="e"))
    assert job.snapshot().cycle == 2
    assert len([a for a in job.snapshot().attempts if a.operation == "routing"]) == 2
    with pytest.raises(JobStopped, match="one attempt"):
        claim(job, operation="routing", key="f")


def test_explicit_routing_retry_rejects_foreign_failure_token(stopped):
    job, _, request = stopped
    job.continue_authorized(request)
    finish(job, claim(job, operation="routing", key="d"), "failed", "expansion budget")
    recovery = recovery_request(job, request)
    recovery = recovery.model_copy(update={"retry_failed_operations": {"routing": "foreign"}})
    before = job.path.read_bytes()
    with pytest.raises(JobStopped, match="latest failed"):
        job.continue_authorized(recovery)
    assert job.path.read_bytes() == before


def test_explicit_verification_only_recovery_grants_no_build_operation(stopped):
    job, _, request = stopped
    job.continue_authorized(request)
    recovery = recovery_request(job, request)
    recovery = recovery.model_copy(update={"build_operations": ()})
    job.continue_authorized(recovery)
    with pytest.raises(JobStopped, match="outside explicitly authorized"):
        claim(job, operation="routing", key="new")
    attempt = job.claim(
        operation="routing-validation",
        phase="verify",
        input_sha256="f" * 64,
        command=("fixture-validation",),
    )
    finish(job, attempt)
    assert job.snapshot().cycle == 2


@pytest.fixture
def initial_resolved(tmp_path):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="synthetic first-scope handoff")
    for cycle, key in enumerate("abc"):
        if cycle:
            job.correction(reason="fixture failure", change="different input")
        finish(
            job, claim(job, operation="placement-review", phase="verify", key=key), "failed", key
        )
    job.begin_diagnostic("Review initial handoff failure")
    report = assessment(tmp_path)
    job.complete_diagnostic(report)
    job.stop("Await explicitly authorized recovery")
    path = tmp_path / "assessment.json"
    path.write_text(report.model_dump_json())
    request = ContinuationRequest(
        predecessor_sha256=hashlib.sha256(job.path.read_bytes()).hexdigest(),
        assessment_file=path.name,
        assessment_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_reference="User explicitly authorizes resolving this handoff",
        seconds=600,
        reserve_seconds=120,
        evaluation_seconds=600,
        build_operations=("routing",),
        blocker_resolution="Synthetic evidence handoff repaired",
        resolved_evidence=report.evidence,
    )
    return job, clock, request


def test_initial_resolved_scope_preserves_history_and_lifetime_limits(initial_resolved):
    job, clock, request = initial_resolved
    raw = job.path.read_bytes()
    job.continue_authorized(request)
    state = job.snapshot()
    assert state.cycle == 2 and len(state.attempts) == 3
    assert state.deadline == 2800 and state.continuation_history == []
    assert state.diagnostic.status == "complete"
    assert (job.root / ".pcbsmith/continuation-predecessor.json").read_bytes() == raw
    with pytest.raises(JobStopped, match="outside explicitly authorized"):
        claim(job, operation="placement", key="d")
    with pytest.raises(JobStopped, match="operation attempt allowance"):
        claim(job, operation="placement-review", phase="verify", key="d")


def test_initial_recovery_rejects_changed_resolution(initial_resolved):
    job, _, request = initial_resolved
    raw = job.path.read_bytes()
    (job.root / "finding.txt").write_text("changed")
    with pytest.raises(JobStopped, match="resolution evidence changed"):
        job.continue_authorized(request)
    assert job.path.read_bytes() == raw


def test_initial_recovery_rejects_replaced_diagnostic(initial_resolved):
    job, _, request = initial_resolved
    path = job.root / "assessment.json"
    report = assessment(job.root).model_copy(update={"rationale": "Different decision"})
    path.write_text(report.model_dump_json())
    request = request.model_copy(
        update={"assessment_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    )
    raw = job.path.read_bytes()
    with pytest.raises(JobStopped, match="differs from completed diagnostic"):
        job.continue_authorized(request)
    assert job.path.read_bytes() == raw


def test_initial_resolved_scope_requires_completed_diagnostic(stopped):
    job, _, request = stopped
    report = assessment(job.root)
    request = request.model_copy(
        update={
            "blocker_resolution": "Claimed resolution without completed checkpoint",
            "resolved_evidence": report.evidence,
        }
    )
    raw = job.path.read_bytes()
    with pytest.raises(JobStopped, match="requires a completed diagnostic"):
        job.continue_authorized(request)
    assert job.path.read_bytes() == raw


@pytest.fixture
def unstarted_preparation(tmp_path):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="moderate", rationale="Synthetic stopped preparation")
    for op, key in (("native-preparation", "a"), ("predesign-prepare", "b")):
        finish(job, claim(job, operation=op, key=key))
    job.begin_diagnostic("Synthetic platform review-input block")
    report = assessment(tmp_path).model_copy(update={"cause": "platform", "action": "stop"})
    job.complete_diagnostic(report)
    job.stop("Wait for explicit user recovery")
    path = tmp_path / "assessment.json"
    path.write_text(report.model_dump_json())
    request = ContinuationRequest(
        predecessor_sha256=hashlib.sha256(job.path.read_bytes()).hexdigest(),
        assessment_file=path.name,
        assessment_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_reference="User explicitly requests finishing the prepared board",
        seconds=600,
        reserve_seconds=120,
        evaluation_seconds=600,
        build_operations=("predesign-approve", "placement", "routing"),
        blocker_resolution="Synthetic typed input preparation repaired; original inputs retained",
        resolved_evidence=report.evidence,
    )
    return job, request


def test_unstarted_preparation_continues_once_without_reset(unstarted_preparation):
    job, request = unstarted_preparation
    raw = job.path.read_bytes()
    job.continue_authorized(request)
    for op, key in (("predesign-approve", "c"), ("placement", "d"), ("routing", "e")):
        finish(job, claim(job, operation=op, key=key))
    assert job.snapshot().cycle == 0
    assert len(job.snapshot().attempts) == 5
    assert (job.root / ".pcbsmith/continuation-predecessor.json").read_bytes() == raw
    with pytest.raises(JobStopped, match="one attempt"):
        claim(job, operation="placement", key="f")


@pytest.mark.parametrize("prior_operation", ["placement", "predesign-approve"])
def test_unstarted_recovery_refuses_existing_attempt(unstarted_preparation, prior_operation):
    job, request = unstarted_preparation
    # Synthetic corrupt-scope fixture, never a production ledger mutation.
    with job._access() as state:
        state.attempts[0].operation = prior_operation
    request = request.model_copy(
        update={"predecessor_sha256": hashlib.sha256(job.path.read_bytes()).hexdigest()}
    )
    with pytest.raises(JobStopped, match="cannot repeat an attempted stage"):
        job.continue_authorized(request)


def test_unstarted_recovery_requires_resolution(unstarted_preparation):
    job, request = unstarted_preparation
    request = request.model_copy(update={"blocker_resolution": None, "resolved_evidence": {}})
    with pytest.raises(JobStopped, match="diagnosed platform blocker"):
        job.continue_authorized(request)


def test_local_scope_addition_preserves_clock_and_counters(unstarted_preparation):
    job, request = unstarted_preparation
    job.continue_authorized(request)
    before = job.snapshot()
    raw = job.path.read_bytes()
    job.authorize_local_correction(
        "Explicit user completion instruction", request.resolved_evidence
    )
    after = job.snapshot()
    assert after.active_deadline == before.active_deadline
    assert after.cycle == before.cycle and after.attempts == before.attempts
    assert (job.root / ".pcbsmith/local-correction-predecessor.json").read_bytes() == raw
    for op, key in (("edit", "c"), ("apply-edit", "d")):
        finish(job, claim(job, operation=op, key=key))
    with pytest.raises(JobStopped, match="previously attempted"):
        job.authorize_local_correction("Another wording", request.resolved_evidence)


def test_local_scope_addition_checks_source_hash(unstarted_preparation):
    job, request = unstarted_preparation
    job.continue_authorized(request)
    evidence = {key: "0" * 64 for key in request.resolved_evidence}
    with pytest.raises(JobStopped, match="evidence changed"):
        job.authorize_local_correction("Explicit user", evidence)
    assert not (job.root / ".pcbsmith/local-correction-predecessor.json").exists()


def test_resolved_local_correction_can_retry_once_after_new_authorization(stopped):
    job, _, request = stopped
    job.continue_authorized(request)
    failed = claim(job, operation="routing", key="d")
    finish(job, failed, "failed", "stale-detached-input")
    job.begin_diagnostic("Detached annotation differs from accepted native edit")
    report = assessment(job.root).model_copy(update={"cause": "evidence", "action": "local_edit"})
    job.complete_diagnostic(report)
    job.stop("Completed diagnosis; new explicit user decision received")
    path = job.root / "resolved-local.json"
    path.write_text(report.model_dump_json())
    request = request.model_copy(
        update={
            "predecessor_sha256": hashlib.sha256(job.path.read_bytes()).hexdigest(),
            "assessment_file": path.name,
            "assessment_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "authorization_reference": "New explicit user approval after diagnosis",
            "blocker_resolution": "Corrected detached input verified against native source",
            "resolved_evidence": report.evidence,
            "build_operations": ("routing",),
            "retry_failed_operations": {"routing": failed.token},
        }
    )
    job.continue_authorized(request)
    finish(job, claim(job, operation="routing", key="e"))
    assert len(job.snapshot().continuation_history) == 1
    assert job.snapshot().cycle == 2
    with pytest.raises(JobStopped, match="one attempt"):
        claim(job, operation="routing", key="f")


def test_fourth_route_requires_explicit_resolved_recovery(stopped):
    _, _, request = stopped
    data = request.model_dump()
    data["routing_attempt_limit"] = 4
    with pytest.raises(ValueError, match="fourth routing"):
        ContinuationRequest.model_validate(data)
    data.update(
        blocker_resolution="structurally different plane recovery",
        resolved_evidence={"proof.json": "a" * 64},
        retry_failed_operations={"routing": "latest-failed"},
    )
    assert ContinuationRequest.model_validate(data).routing_attempt_limit == 4
    data["routing_attempt_limit"] = 5
    with pytest.raises(ValueError):
        ContinuationRequest.model_validate(data)


def test_preflight_fifth_invocation_requires_matching_token_and_no_sixth(stopped):
    _, _, request = stopped
    data = request.model_dump()
    data.update(
        routing_attempt_limit=5,
        blocker_resolution="input-only failure",
        resolved_evidence={"log": "a" * 64},
        retry_failed_operations={"routing": "failed"},
    )
    with pytest.raises(ValueError, match="proven preflight"):
        ContinuationRequest.model_validate(data)
    data["routing_preflight_failure_token"] = "failed"
    assert ContinuationRequest.model_validate(data).routing_attempt_limit == 5
    data["routing_attempt_limit"] = 6
    with pytest.raises(ValueError):
        ContinuationRequest.model_validate(data)


def test_expired_diagnostic_recovery_is_explicit_and_verification_only(stopped):
    job, clock, request = stopped
    job.continue_authorized(request)
    finish(job, claim(job, operation="edit", key="d"), "failed", "blocked")
    job.begin_diagnostic("Retained candidate analysis")
    clock.now += 301
    job.stop("Preserve expired diagnostic")
    before = job.path.read_bytes()
    report = assessment(job.root).model_copy(update={"action": "local_edit"})
    path = job.root / "retrospective.json"
    path.write_text(report.model_dump_json())
    recovery = ContinuationRequest(
        predecessor_sha256=hashlib.sha256(before).hexdigest(),
        assessment_file=path.name,
        assessment_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_reference="Explicit authorization after missed diagnostic, no rerouting",
        seconds=600,
        reserve_seconds=120,
        build_operations=(),
        blocker_resolution="Source-bound retained-candidate verification",
        resolved_evidence=report.evidence,
        retrospective_diagnostic=True,
    )
    job.continue_authorized(recovery)
    state = job.snapshot()
    assert state.continuation_history[-1].diagnostic.status == "reviewing"
    assert state.continuation_history[-1].diagnostic.completed_at is None
    assert state.cycle == 2
    with pytest.raises(JobStopped, match="scope"):
        claim(job, operation="routing", key="e")


def test_retained_native_repair_is_build_not_verification():
    from pcbsmith.board_job import operation_for

    assert operation_for(
        "pcbsmith.production_routing",
        ["--revalidate-result", "old.json", "--native-repair", "delta.json"],
    ) == ("native-repair", "build")
    assert operation_for("pcbsmith.production_routing", ["--revalidate-result", "old.json"]) == (
        "routing-validation",
        "verify",
    )


def test_deadline_stop_allows_bounded_retrospective_diagnostic(tmp_path):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(
        complexity="simple",
        rationale="terminal diagnostic fixture",
        seconds=600,
        evaluation_seconds=10,
    )
    clock.now += 611
    with pytest.raises(JobStopped, match="deadline"):
        claim(job, operation="placement", key="expired")
    assert job.snapshot().stop_kind == "deadline"

    review = job.begin_diagnostic("Assess retained inputs after terminal deadline")
    assert review.status == "reviewing"
    assert review.deadline == clock.now + 300
    job.complete_diagnostic(
        assessment(tmp_path).model_copy(update={"cause": "platform", "action": "platform_work"})
    )
    assert job.snapshot().diagnostic.status == "complete"

def test_operation_for_predesign_recovery_is_distinct_and_bounded():
    from pcbsmith.board_job import operation_for

    assert operation_for(
        "pcbsmith.predesign_preparation", ["refresh", "a", "b", "c"]
    ) == ("predesign-refresh", "build")
    assert operation_for(
        "pcbsmith.predesign_preparation", ["reapprove", "a", "b", "c"]
    ) == ("predesign-reapprove", "build")


@pytest.mark.parametrize("missing", [None, "edit", "predesign-refresh"])
def test_existing_board_revision_reapproval_uses_revision_stages(initial_resolved, missing):
    job, _, request = initial_resolved
    operations = ["edit", "apply-edit", "predesign-refresh", "predesign-reapprove"]
    if missing:
        operations.remove(missing)
    request = request.model_copy(update={"build_operations": tuple(operations)})
    before = job.path.read_bytes()
    if missing:
        with pytest.raises(JobStopped, match="edit and refreshed inputs"):
            job.continue_authorized(request)
        assert job.path.read_bytes() == before
        return
    job.continue_authorized(request)
    state = job.snapshot()
    assert state.cycle == 2 and len(state.attempts) == 3
    assert (job.root / ".pcbsmith/continuation-predecessor.json").read_bytes() == before
    for i, operation in enumerate(operations):
        finish(job, claim(job, operation=operation, key=str(i)))
    with pytest.raises(JobStopped, match="allowance"):
        claim(job, operation="predesign-reapprove", key="repeat")


def test_revision_reapproval_does_not_grant_initial_placement(initial_resolved):
    job, _, request = initial_resolved
    request = request.model_copy(update={"build_operations": (
        "edit", "predesign-refresh", "predesign-reapprove", "placement"
    )})
    before = job.path.read_bytes()
    with pytest.raises(JobStopped, match="retained prepared inputs"):
        job.continue_authorized(request)
    assert job.path.read_bytes() == before
