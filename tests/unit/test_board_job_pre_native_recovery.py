from __future__ import annotations

import hashlib

import pytest
from tests.unit.test_board_job import Clock, claim, finish
from tests.unit.test_board_job_diagnostic import assessment

from pcbsmith.board_job import (
    BoardJob,
    ContinuationRequest,
    JobStopped,
    PreNativeLayoutApproval,
    PreNativeRecovery,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def pre_native(tmp_path):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="synthetic concept", evaluation_seconds=1200)
    report = assessment(tmp_path).model_copy(update={"cause": "architecture", "action": "stop"})
    job.begin_diagnostic("Incomplete concept routing")
    job.complete_diagnostic(report)
    job.stop("Await explicit concept decision")
    (tmp_path / "assessment.json").write_text(report.model_dump_json())
    for name, value in (("plan.svg", "<svg/>"), ("plan.png", "synthetic PNG"), ("plan.json", "{}")):
        (tmp_path / name).write_text(value)
    approval = PreNativeLayoutApproval(
        schema_id="pcbsmith-pre-native-layout-approval-v1",
        authorization_reference="Explicit synthetic approval and repair authorization",
        approved_artifacts={
            name: digest(tmp_path / name) for name in ("plan.svg", "plan.png", "plan.json")
        },
    )
    (tmp_path / "approval.json").write_text(approval.model_dump_json())
    request = ContinuationRequest(
        predecessor_sha256=digest(job.path),
        assessment_file="assessment.json",
        assessment_sha256=digest(tmp_path / "assessment.json"),
        authorization_reference=approval.authorization_reference,
        seconds=600,
        reserve_seconds=120,
        evaluation_seconds=900,
        build_operations=(
            "native-preparation",
            "predesign-prepare",
            "predesign-approve",
            "placement",
            "routing",
        ),
        pre_native_recovery=PreNativeRecovery(
            approval_file="approval.json", approval_sha256=digest(tmp_path / "approval.json")
        ),
        blocker_resolution="Separately verified synthetic recovery-path repair",
        resolved_evidence={"approval.json": digest(tmp_path / "approval.json")},
    )
    return job, clock, request


def test_pre_native_recovery_preserves_identity_clocks_diagnostic_and_predecessor(pre_native):
    job, clock, request = pre_native
    raw = job.path.read_bytes()
    before = job.snapshot()
    request = request.model_copy(update={"predecessor_sha256": digest(job.path)})
    raw = job.path.read_bytes()
    clock.now += 2000
    job.continue_authorized(request)
    after = job.snapshot()
    assert (job.root / ".pcbsmith/continuation-predecessor.json").read_bytes() == raw
    assert (after.job_id, after.started_at, after.deadline, after.cycle) == (
        before.job_id,
        before.started_at,
        before.deadline,
        0,
    )
    assert after.diagnostic == before.diagnostic
    assert after.continuation.diagnostic is None
    assert after.active_deadline == clock.now + 1500
    assert after.active_evaluation_seconds == 900
    for i, operation in enumerate(request.build_operations):
        finish(job, claim(job, operation=operation, key=str(i)))
    assert len(job.snapshot().attempts) == 5
    with pytest.raises(JobStopped, match="one attempt"):
        claim(job, operation="placement", key="x")


@pytest.mark.parametrize("filename", ["plan.svg", "plan.png", "plan.json"])
def test_pre_native_recovery_rejects_changed_approved_artifacts(pre_native, filename):
    job, _, request = pre_native
    raw = job.path.read_bytes()
    (job.root / filename).write_text("changed")
    with pytest.raises(JobStopped, match="artifact changed"):
        job.continue_authorized(request)
    assert job.path.read_bytes() == raw


@pytest.mark.parametrize("suffix", ["kicad_sch", "kicad_pcb"])
def test_pre_native_recovery_rejects_even_unrecorded_native_inputs(pre_native, suffix):
    job, _, request = pre_native
    (job.root / ("existing." + suffix)).write_text("unverified native input")
    raw = job.path.read_bytes()
    with pytest.raises(JobStopped, match="retained native"):
        job.continue_authorized(request)
    assert job.path.read_bytes() == raw


def test_pre_native_recovery_cannot_adopt_a_job_with_prior_attempts(pre_native):
    job, _, request = pre_native
    # Synthetic prior attempt without changing the actual diagnostic/continuation checks.
    with job._access() as state:
        from pcbsmith.board_job import Attempt

        state.attempts.append(
            Attempt(
                token="fixture",
                operation="inspect",
                phase="verify",
                input_sha256="a" * 64,
                command=("fixture",),
                cycle=0,
                started_at=1000,
                ended_at=1000,
                supervisor_pid=1,
                status="passed",
            )
        )
    request = request.model_copy(update={"predecessor_sha256": digest(job.path)})
    raw = job.path.read_bytes()
    with pytest.raises(JobStopped, match="untouched"):
        job.continue_authorized(request)
    assert job.path.read_bytes() == raw


def test_pre_native_recovery_cannot_renew_itself(pre_native):
    job, _, request = pre_native
    job.continue_authorized(request)
    report = assessment(job.root).model_copy(update={"action": "stop"})
    job.begin_diagnostic("Synthetic subsequent stop")
    job.complete_diagnostic(report)
    job.stop("No renewal")
    (job.root / "assessment.json").write_text(report.model_dump_json())
    payload = request.model_dump()
    payload.update(
        predecessor_sha256=digest(job.path),
        assessment_sha256=digest(job.root / "assessment.json"),
        authorization_reference="Another explicit request",
    )
    with pytest.raises(JobStopped, match="untouched"):
        job.continue_authorized(ContinuationRequest.model_validate(payload))


def test_pre_native_recovery_requires_matching_authorization(pre_native):
    job, _, request = pre_native
    changed = request.model_copy(update={"authorization_reference": "Unrelated decision"})
    with pytest.raises(JobStopped, match="current explicit authorization"):
        job.continue_authorized(changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("pre_native_recovery", None),
        ("evaluation_seconds", None),
        ("build_operations", ("placement",)),
        ("retry_failed_operations", {"routing": "old-token"}),
    ],
)
def test_pre_native_scope_cannot_bypass_explicit_initial_stage_policy(pre_native, field, value):
    _, _, request = pre_native
    payload = request.model_dump()
    payload[field] = value
    with pytest.raises(ValueError):
        ContinuationRequest.model_validate(payload)


def test_pre_native_recovery_cannot_add_corrections_or_undeclared_operations(pre_native):
    job, _, request = pre_native
    job.continue_authorized(request)
    with pytest.raises(JobStopped, match="scope"):
        claim(job, operation="native-repair", key="x")
    with pytest.raises(JobStopped, match="allowance"):
        job.correction(reason="more", change="extra")
    assert job.snapshot().cycle == 0


def test_pre_native_recovery_failed_operation_stops_subsequent_creation(pre_native):
    job, _, request = pre_native
    job.continue_authorized(request)
    finish(job, claim(job, operation="native-preparation"), "failed", "input-failure")
    with pytest.raises(JobStopped, match="diagnostic"):
        claim(job, operation="placement", key="b")


@pytest.fixture
def missing_native_input(pre_native):
    from pcbsmith.native_project import NativeProjectSpec
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

    job, clock, request = pre_native
    job.continue_authorized(request)
    spec_file = job.root / "corrected.json"
    output = job.root / "native"
    command = ("pcbsmith.native_project", str(spec_file), str(output), "--symbol-root", "symbols")
    attempt = job.claim(
        operation="native-preparation", phase="build", input_sha256="a" * 64, command=command
    )
    finish(job, attempt, "failed", "missing-spec")
    log = job.root / ".pcbsmith/job-runs" / attempt.token / "logs/native-preparation.stderr.txt"
    log.parent.mkdir(parents=True)
    log.write_text(
        "args.spec.read_text\nFileNotFoundError: [Errno 2] No such file or directory: "
        + repr(str(spec_file))
    )
    spec = NativeProjectSpec(
        project_id="fixture",
        title="Fixture",
        user_request="Synthetic recovery",
        width_mm=30,
        height_mm=30,
        profile=DEFAULT_PCB_RULE_PROFILE,
        parts=(
            {
                "reference": "R1",
                "symbol": "Device:R",
                "value": "1k",
                "footprint": "Resistor:R",
                "mpn": "fixture",
                "role": "test",
                "pins": {"1": "V", "2": "GND"},
                "schematic_at": (12.7, 12.7),
                "board_at": (10, 10, 0),
            },
        ),
    )
    spec_file.write_text(spec.model_dump_json())
    return job, clock, attempt, command, spec_file, output, log


def test_missing_spec_recovery_retains_failure_and_allows_only_exact_retry(missing_native_input):
    job, clock, attempt, command, spec_file, output, log = missing_native_input
    before = job.snapshot()
    job.resolve_native_preparation_input(token=attempt.token)
    state = job.snapshot()
    assert state.deadline == before.deadline
    assert state.continuation.deadline == before.continuation.deadline
    assert state.cycle == 0 and state.attempts[0].status == "failed"
    retry = job.claim(
        operation="native-preparation", phase="build", input_sha256="b" * 64, command=command
    )
    finish(job, retry)
    with pytest.raises(JobStopped):
        job.resolve_native_preparation_input(token=attempt.token)
    with pytest.raises(JobStopped, match="one attempt"):
        job.claim(
            operation="native-preparation", phase="build", input_sha256="c" * 64, command=command
        )


@pytest.mark.parametrize("change", ["output", "error", "invalid-spec"])
def test_missing_spec_recovery_rejects_nonmatching_failure(missing_native_input, change):
    job, _, attempt, _, spec_file, output, log = missing_native_input
    if change == "output":
        output.mkdir()
    if change == "error":
        log.write_text("FileNotFoundError: unrelated library")
    if change == "invalid-spec":
        spec_file.write_text("{}")
    with pytest.raises((JobStopped, ValueError)):
        job.resolve_native_preparation_input(token=attempt.token)
    assert job.snapshot().continuation.request.native_preparation_input_retry is None


def test_missing_spec_retry_rejects_changed_corrected_input(missing_native_input):
    job, _, attempt, command, spec_file, _, _ = missing_native_input
    job.resolve_native_preparation_input(token=attempt.token)
    spec_file.write_text(spec_file.read_text() + " ")
    with pytest.raises(JobStopped, match="pinned correction"):
        job.claim(
            operation="native-preparation", phase="build", input_sha256="b" * 64, command=command
        )
