from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from pcbsmith.board_job import (
    ROOT_ENV,
    TOKEN_ENV,
    BoardJob,
    JobStopped,
    input_identity,
    operation_for,
    require_worker,
    run_operation,
)
from pcbsmith.execution import EXECUTION_PROFILES, SubprocessGateRunner, VerificationGate


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def running(tmp_path):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="fixture")
    return job, clock


def claim(job, *, operation="routing", key="a", phase="build"):
    return job.claim(
        operation=operation,
        phase=phase,
        input_sha256=key * 64,
        command=("pcbsmith.production_routing", "--output", "candidate"),
    )


def finish(job, attempt, status="passed", signature=None):
    job.finish_attempt(attempt.token, status=status, result={}, failure_signature=signature)


def test_restart_and_new_root_cannot_reset_ledger(running, tmp_path):
    job, clock = running
    claim(job)
    with pytest.raises(JobStopped, match="already exists"):
        job.start(complexity="complex", rationale="more time")
    resumed = BoardJob(tmp_path, clock=clock, monotonic=clock)
    assert resumed.snapshot().job_id == job.snapshot().job_id
    assert len(resumed.snapshot().attempts) == 1
    copied = tmp_path / "another-attempt"
    (copied / ".pcbsmith").mkdir(parents=True)
    (copied / ".pcbsmith/board-job.json").write_bytes(job.path.read_bytes())
    with pytest.raises(JobStopped, match="another root"):
        BoardJob(copied, clock=clock, monotonic=clock).snapshot()


def test_time_between_commands_counts_and_expiry_preserves_candidate(running, tmp_path):
    job, clock = running
    board = tmp_path / "candidate.kicad_pcb"
    board.write_bytes(b"retained unverified candidate")
    first = claim(job)
    finish(job, first)
    clock.now += 1800
    resumed = BoardJob(tmp_path, clock=clock, monotonic=clock)
    with pytest.raises(JobStopped, match="deadline"):
        claim(resumed, operation="routed-review", phase="verify")
    assert board.read_bytes() == b"retained unverified candidate"
    assert resumed.snapshot().status == "stopped"
    assert len(resumed.snapshot().attempts) == 1


def test_reserve_blocks_build_but_permits_verification(running):
    job, clock = running
    clock.now += 1440
    with pytest.raises(JobStopped, match="reserve"):
        claim(job)
    verification = claim(job, operation="review", phase="verify")
    assert verification.phase == "verify"
    assert job.remaining(verification.token) == 360


def test_only_two_correction_cycles_and_one_escalation(running):
    job, _ = running
    for cycle, key in enumerate("abc"):
        if cycle:
            job.correction(
                reason="diagnosed obstruction", change="different placement", escalation=cycle == 1
            )
        finish(job, claim(job, key=key))
    with pytest.raises(JobStopped, match="allowance"):
        job.correction(reason="again", change="again")
    assert len(job.snapshot().attempts) == 3


def test_unchanged_retry_rejected_even_after_correction(running):
    job, _ = running
    finish(job, claim(job), "failed", "obstruction")
    job.correction(reason="obstruction", change="claimed change")
    with pytest.raises(JobStopped, match="identical"):
        claim(job)
    assert len(job.snapshot().attempts) == 1


def test_second_same_failure_stops_job(running):
    job, _ = running
    finish(job, claim(job), "failed", "obstruction")
    job.correction(reason="obstruction", change="move component")
    finish(job, claim(job, key="b"), "failed", "obstruction")
    with pytest.raises(JobStopped, match="same failure"):
        claim(job, operation="placement")
    assert job.snapshot().status == "stopped"


def test_cancel_is_persistent_and_does_not_refund_attempt(running):
    job, _ = running
    first = claim(job)
    job.stop("user cancelled")
    with pytest.raises(JobStopped, match="cancelled"):
        job.remaining(first.token)
    assert job.snapshot().attempts[0].status == "running"
    finish(job, first, "stopped")
    with pytest.raises(JobStopped):
        job.correction(reason="resume", change="new directory")
    assert len(job.snapshot().attempts) == 1


def test_no_concurrent_double_claim(running):
    job, clock = running
    barrier = Barrier(2)

    def compete(_):
        contender = BoardJob(job.root, clock=clock, monotonic=clock)
        barrier.wait()
        try:
            claim(contender)
            return "claimed"
        except RuntimeError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(compete, range(2)))
    assert sorted(results) == ["claimed", "denied"]
    assert len(job.snapshot().attempts) == 1


@pytest.mark.parametrize("payload", ["{}", "{", '{"state": {}, "sha256": "bad"}'])
def test_corrupt_ledger_fails_closed(tmp_path, payload):
    path = tmp_path / ".pcbsmith/board-job.json"
    path.parent.mkdir()
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(JobStopped, match="Invalid job"):
        claim(BoardJob(tmp_path))
    assert path.read_text(encoding="utf-8") == payload


def test_missing_ledger_is_not_created_by_claim(tmp_path):
    with pytest.raises(JobStopped, match="Missing"):
        claim(BoardJob(tmp_path))
    assert not (tmp_path / ".pcbsmith/board-job.json").exists()


def test_backwards_clock_on_resume_stops(running):
    job, clock = running
    clock.now += 60
    job.snapshot()
    clock.now -= 10
    resumed = BoardJob(job.root, clock=clock, monotonic=clock)
    with pytest.raises(JobStopped, match="backwards"):
        claim(resumed)


def test_monotonic_time_enforces_deadline_when_wall_time_stalls(tmp_path):
    wall, mono = Clock(), Clock()
    job = BoardJob(tmp_path, clock=wall, monotonic=mono)
    job.start(complexity="simple", rationale="fixture")
    mono.now += 1801
    with pytest.raises(JobStopped, match="deadline"):
        claim(job)


def test_second_escalation_is_rejected(running):
    job, _ = running
    finish(job, claim(job))
    job.correction(reason="failed", change="new order", escalation=True)
    finish(job, claim(job, key="b"))
    with pytest.raises(JobStopped, match="allowance"):
        job.correction(reason="failed", change="deep", escalation=True)


@pytest.mark.parametrize(
    "module,args1,args2",
    [
        (
            "pcbsmith.production_routing",
            ["--board", "x", "--output", "one"],
            ["--board", "x", "--output", "two"],
        ),
        (
            "pcbsmith.cli",
            ["production-generate-board", "source", "one"],
            ["production-generate-board", "source", "two"],
        ),
        (
            "pcbsmith.native_project",
            ["spec", "one", "--symbol-root", "lib"],
            ["spec", "two", "--symbol-root", "lib"],
        ),
        (
            "pcbsmith.predesign_preparation",
            ["prepare", "spec", "project", "one"],
            ["prepare", "spec", "project", "two"],
        ),
    ],
)
def test_output_directory_is_not_effective_change(module, args1, args2):
    assert input_identity(module, args1) == input_identity(module, args2)


def test_file_content_change_counts_but_renaming_identical_input_does_not(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text("{}")
    b.write_text("{}")
    baseline = input_identity("pcbsmith.production_routing", ["--layout", str(a)])
    assert baseline == input_identity("pcbsmith.production_routing", ["--layout", str(b)])
    b.write_text('{"x": 1}')
    assert baseline != input_identity("pcbsmith.production_routing", ["--layout", str(b)])


def test_stage_classification_cannot_be_supplied_by_caller():
    assert operation_for("pcbsmith.production_routing", []) == ("routing", "build")
    with pytest.raises(ValueError, match="not a supported"):
        operation_for("arbitrary.script", ["--stage", "verify"])


def test_unsupervised_production_cli_rejects_before_work(tmp_path, monkeypatch, capsys):
    from pcbsmith.cli import main

    monkeypatch.delenv(ROOT_ENV, raising=False)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    output = tmp_path / "not-written.json"
    assert (
        main(
            [
                "production-inspect-board",
                str(tmp_path / "missing.kicad_pcb"),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert "board-job run" in capsys.readouterr().err
    assert not output.exists()


def test_stale_or_different_worker_command_rejected(tmp_path, monkeypatch):
    job = BoardJob(tmp_path)
    job.start(complexity="simple", rationale="fixture")
    lease = claim(job)
    job.launched(lease.token, 2147483647)
    ready = tmp_path / ".pcbsmith/job-runs" / lease.token / "worker-ready"
    ready.parent.mkdir(parents=True)
    ready.write_text(lease.token, encoding="utf-8")
    monkeypatch.setenv(ROOT_ENV, str(tmp_path))
    monkeypatch.setenv(TOKEN_ENV, lease.token)
    with pytest.raises(JobStopped, match="does not match"):
        require_worker("pcbsmith.native_project", ["other"])
    with pytest.raises(JobStopped, match="contained worker"):
        require_worker("pcbsmith.production_routing", ["--output", "candidate"])


def test_real_supported_child_and_persistent_receipt(tmp_path):
    job = BoardJob(tmp_path)
    job.start(complexity="simple", rationale="read-only generator inventory", seconds=30)
    result = run_operation(job, "pcbsmith.cli", ["production-generator-audit"], profile="quick")
    assert result == 0
    state = job.snapshot()
    assert state.attempts[0].status == "passed"
    assert state.attempts[0].worker_pid is not None
    assert state.attempts[0].result["memory_limit_enforced"]
    assert (tmp_path / ".pcbsmith/job-runs" / state.attempts[0].token / "result.json").is_file()
    assert state.status == "active"  # command success is not job/release approval


def test_hung_process_is_killed_by_shared_runner(tmp_path):
    started = time.monotonic()
    result = SubprocessGateRunner().run(
        VerificationGate(
            gate_id="hang",
            command=(sys.executable, "-c", "import time; time.sleep(30)"),
            timeout_seconds=0.4,
        ),
        profile=EXECUTION_PROFILES["quick"],
        output_dir=tmp_path,
        emit=lambda *_: None,
        require_tree_limit=True,
    )
    assert result.termination == "timeout"
    assert result.memory_limit_enforced
    assert time.monotonic() - started < 5


def test_cancel_prevents_process_launch(tmp_path):
    marker = tmp_path / "launched"
    result = SubprocessGateRunner().run(
        VerificationGate(
            gate_id="cancel",
            command=(
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')",
            ),
        ),
        profile=EXECUTION_PROFILES["quick"],
        output_dir=tmp_path,
        emit=lambda *_: None,
        stop_requested=lambda: "cancelled",
    )
    assert result.termination == "unavailable"
    assert not marker.exists()


def test_live_cancellation_kills_descendants(tmp_path):
    ready, orphan = tmp_path / "ready", tmp_path / "orphan"
    grandchild = (
        "import time; from pathlib import Path; time.sleep(2); "
        f"Path({str(orphan)!r}).write_text('bad')"
    )
    script = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
        f"Path({str(ready)!r}).write_text('ready'); time.sleep(30)"
    )
    result = SubprocessGateRunner().run(
        VerificationGate(gate_id="tree", command=(sys.executable, "-c", script), timeout_seconds=5),
        profile=EXECUTION_PROFILES["quick"],
        output_dir=tmp_path,
        emit=lambda *_: None,
        stop_requested=lambda: "cancelled" if ready.exists() else None,
        require_tree_limit=True,
    )
    assert result.termination == "interrupted"
    assert result.memory_limit_enforced
    time.sleep(2.2)
    assert not orphan.exists()


def test_job_snapshot_is_json_and_never_grants_engineering_acceptance(running):
    job, _ = running
    finish(job, claim(job))
    job.stop("execution finished; see separate native checks", finished=True)
    state = json.loads(job.path.read_text())["state"]
    assert state["status"] == "finished"
    assert "manufacturing_approved" not in state


def test_graceful_resume_keeps_deadline_and_spent_attempts(running):
    job, clock = running
    first = claim(job)
    finish(job, first, "stopped")
    deadline = job.snapshot().deadline
    clock.now += 60
    job.resume("operator resumes the same work")
    assert job.snapshot().deadline == deadline
    assert len(job.snapshot().attempts) == 1
    with pytest.raises(JobStopped, match="already attempted"):
        claim(job)
    job.correction(reason="interrupted", change="changed route order")
    assert claim(job, key="b").cycle == 1


def test_resume_cannot_bypass_expiry_or_repeated_failure(running):
    job, clock = running
    finish(job, claim(job), "failed", "same")
    job.correction(reason="same", change="move")
    finish(job, claim(job, key="b"), "failed", "same")
    with pytest.raises(JobStopped, match="only cancellation"):
        job.resume("try again")
    clock.now += 1800
    with pytest.raises(JobStopped):
        job.resume("more time")


def test_supervisor_deep_profile_cannot_restart_expired_job(running, monkeypatch):
    job, clock = running
    clock.now += 1801

    def unexpected(*args, **kwargs):
        pytest.fail("expired job must not launch a process")

    monkeypatch.setattr(SubprocessGateRunner, "run", unexpected)
    with pytest.raises(JobStopped, match="deadline"):
        run_operation(job, "pcbsmith.production_routing", ["--output", "new"], profile="deep")


def test_managed_revision_cannot_resume_without_its_job(tmp_path, monkeypatch):
    from pcbsmith.board_job import bind_revision_job

    monkeypatch.delenv(ROOT_ENV, raising=False)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    binding = tmp_path / "board-job-binding.json"
    binding.write_text('{"job_id": "old", "job_root": "old"}')
    with pytest.raises(JobStopped, match="original"):
        bind_revision_job(tmp_path, resume=True)
    assert json.loads(binding.read_text())["job_id"] == "old"


def test_running_build_stops_at_reserve_without_using_final_check_time(running):
    job, clock = running
    first = claim(job)
    assert job.remaining(first.token) == 1440
    clock.now += 1440
    with pytest.raises(JobStopped, match="reserve"):
        job.remaining(first.token)
    finish(job, first, "stopped")
    assert job.snapshot().status == "active"
    verification = claim(job, operation="routed-review", phase="verify")
    assert job.remaining(verification.token) == 360


def test_cancel_cannot_relabel_repeated_failure_into_resumable_state(running):
    job, _ = running
    finish(job, claim(job), "failed", "same")
    job.correction(reason="failure", change="new order")
    finish(job, claim(job, key="b"), "failed", "same")
    with pytest.raises(JobStopped, match="cannot be relabeled"):
        job.stop("cancel then resume")
    with pytest.raises(JobStopped, match="only cancellation"):
        job.resume("reset")
    assert job.snapshot().stop_kind == "repeated_failure"


def test_revision_binding_rejects_a_different_job(tmp_path, monkeypatch):
    import os

    from pcbsmith.board_job import bind_revision_job

    output = tmp_path / "revision"
    output.mkdir()
    for index in range(2):
        job = BoardJob(tmp_path / str(index))
        job.start(complexity="simple", rationale="fixture")
        lease = claim(job)
        job.launched(lease.token, os.getpid())
        job.authorize(lease.token, lease.command)
        monkeypatch.setenv(ROOT_ENV, str(job.root))
        monkeypatch.setenv(TOKEN_ENV, lease.token)
        if index == 0:
            bind_revision_job(output, resume=False)
            bind_revision_job(output, resume=True)
            finish(job, lease)
        else:
            with pytest.raises(JobStopped, match="another"):
                bind_revision_job(output, resume=True)


@pytest.mark.parametrize(
    "module,name",
    [
        ("native_project", "prepare_native_project"),
        ("predesign_preparation", "prepare_predesign_inputs"),
        ("predesign_preparation", "approve_prepared_predesign"),
        ("production_generators", "generate_registered_board_candidate"),
        ("production_generators", "persist_registered_placement_candidate"),
        ("production_generators", "persist_registered_routed_candidate"),
        ("production_workflow", "produce_budgeted_placement_review"),
        ("production_workflow", "persist_placement_and_generate_review"),
        ("production_workflow", "persist_routed_board_and_generate_review"),
        ("production_workflow", "repair_current_component_review"),
        ("production_workflow", "commit_generation_transaction"),
        ("production_workflow", "route_native_board"),
        ("production_routing", "route_saved_placement_candidate"),
        ("board_revision", "create_board_revision"),
        ("board_revision", "apply_board_revision"),
    ],
)
def test_direct_supported_producers_cannot_bypass_job(module, name, tmp_path, monkeypatch):
    import importlib
    import inspect

    monkeypatch.delenv(ROOT_ENV, raising=False)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    producer = getattr(importlib.import_module("pcbsmith." + module), name)
    arguments = {
        key: None
        for key, param in inspect.signature(producer).parameters.items()
        if param.default is inspect.Parameter.empty
    }
    with pytest.raises(JobStopped, match="active supervised"):
        producer(**arguments)
    assert list(tmp_path.iterdir()) == []


def test_active_lease_without_worker_ownership_does_not_authorize_producer(tmp_path, monkeypatch):
    from pcbsmith.board_job import require_library_worker

    job = BoardJob(tmp_path)
    job.start(complexity="simple", rationale="fixture")
    lease = claim(job)
    monkeypatch.setenv(ROOT_ENV, str(job.root))
    monkeypatch.setenv(TOKEN_ENV, lease.token)
    with pytest.raises(JobStopped, match="does not own"):
        require_library_worker()


def test_changed_candidate_can_be_verified_without_inventing_a_correction(running):
    job, _ = running
    first = claim(job, operation="inspect", phase="verify")
    finish(job, first)
    second = claim(job, operation="inspect", phase="verify", key="b")
    finish(job, second)
    assert job.snapshot().cycle == 0
    with pytest.raises(JobStopped, match="identical"):
        claim(job, operation="inspect", phase="verify", key="b")
    finish(job, claim(job, operation="inspect", phase="verify", key="c"))
    with pytest.raises(JobStopped, match="allowance"):
        claim(job, operation="inspect", phase="verify", key="d")


def test_real_supervised_operation_stops_at_whole_job_deadline(tmp_path, monkeypatch):
    # Isolate the child-deadline test from source inventory time; preflight expiry
    # has its own tests and legitimately stops before a child can start.
    monkeypatch.setattr(
        "pcbsmith.board_job._IMPLEMENTATION_ROOT", tmp_path / "empty-source-fixture"
    )
    job = BoardJob(tmp_path)
    job.start(complexity="simple", rationale="forced deadline fixture", seconds=0.2)
    started = time.monotonic()
    assert run_operation(job, "pcbsmith.cli", ["production-generator-audit"]) == 2
    state = job.snapshot()
    assert state.status == "stopped"
    assert state.stop_kind == "deadline"
    assert len(state.attempts) == 1
    assert time.monotonic() - started < 5


def test_missing_process_containment_never_authorizes_worker(tmp_path, monkeypatch):
    import pcbsmith.execution as execution

    class Process:
        killed = False

        def poll(self):
            return -1 if self.killed else None

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            assert self.killed
            return -1

    process = Process()
    monkeypatch.setattr(execution, "_spawn_limited_process", lambda *a, **k: (process, None))
    events = []
    result = SubprocessGateRunner().run(
        VerificationGate(gate_id="uncontained", command=(sys.executable, "-c", "pass")),
        profile=EXECUTION_PROFILES["quick"],
        output_dir=tmp_path,
        emit=lambda event, _: events.append(event),
        require_tree_limit=True,
    )
    assert process.killed
    assert "process_started" not in events
    assert result.termination == "unavailable"
    assert not result.memory_limit_enforced


def test_expired_job_rejects_before_input_hashing(running, monkeypatch):
    import pcbsmith.board_job as module

    job, clock = running
    clock.now += 1801

    def forbidden(*args, **kwargs):
        pytest.fail("input hashing must not start after the deadline")

    monkeypatch.setattr(module, "input_identity", forbidden)
    with pytest.raises(JobStopped, match="deadline"):
        run_operation(job, "pcbsmith.production_routing", ["--layout", "large.json"])


def test_large_input_hashing_checks_budget_between_chunks(tmp_path):
    data = tmp_path / "large.json"
    data.write_bytes(b"x" * (3 * 1024 * 1024))
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise JobStopped("deadline")

    with pytest.raises(JobStopped, match="deadline"):
        input_identity("pcbsmith.production_routing", ["--layout", str(data)], check=check)
    assert calls == 3


def test_retry_identity_tracks_shared_code_not_documentation(tmp_path, monkeypatch):
    import pcbsmith.board_job as module

    monkeypatch.setattr(module, "_IMPLEMENTATION_ROOT", tmp_path)
    source = tmp_path / "producer.py"
    source.write_text("value = 1")
    before = input_identity("pcbsmith.cli", ["production-generate-board", "s", "out"])
    (tmp_path / "note.md").write_text("cosmetic note")
    assert before == input_identity("pcbsmith.cli", ["production-generate-board", "s", "new"])
    source.write_text("value = 2")
    assert before != input_identity("pcbsmith.cli", ["production-generate-board", "s", "out"])


def test_retained_routing_validation_is_verification_only():
    from pcbsmith.board_job import operation_for

    assert operation_for(
        "pcbsmith.production_routing", ["--revalidate-result", "retained.json"]
    ) == ("routing-validation", "verify")
    assert operation_for("pcbsmith.production_routing", ["--board", "source.kicad_pcb"]) == (
        "routing",
        "build",
    )


def test_preparation_checkpoint_polls_without_skipping_hashes(running, monkeypatch, tmp_path):
    import pcbsmith.board_job as module

    job, clock = running
    monkeypatch.setattr(module.time, "monotonic", clock)
    source = tmp_path / "input.json"
    source.write_bytes(b"x" * (3 * 1024 * 1024))
    original = job.preflight
    calls = []

    def counted(phase):
        calls.append(clock.now)
        original(phase)

    monkeypatch.setattr(job, "preflight", counted)
    checkpoint = module._preparation_checkpoint(job, "build")
    args = ["--layout", str(source)]
    assert input_identity("pcbsmith.production_routing", args, check=checkpoint) == input_identity(
        "pcbsmith.production_routing", args
    )
    assert len(calls) == 1
    clock.now += 0.11
    checkpoint()
    assert len(calls) == 2
    source.write_bytes(b"changed")
    assert input_identity("pcbsmith.production_routing", args, check=checkpoint) != input_identity(
        "pcbsmith.production_routing", ["--layout", "absent.json"]
    )


@pytest.mark.parametrize("condition", ["expired", "stopped", "corrupt"])
def test_preparation_checkpoint_rejects_changed_job(running, monkeypatch, condition):
    import pcbsmith.board_job as module

    job, clock = running
    monkeypatch.setattr(module.time, "monotonic", clock)
    checkpoint = module._preparation_checkpoint(job, "build")
    checkpoint()
    if condition == "expired":
        clock.now += 1801
    elif condition == "stopped":
        job.stop("cancelled during input preparation")
    else:
        job.path.write_text("{}")
    clock.now += 0.11
    with pytest.raises((JobStopped, ValueError)):
        checkpoint()


def test_claim_rechecks_after_hashing_inside_poll_interval(running, monkeypatch):
    import pcbsmith.board_job as module

    job, clock = running
    monkeypatch.setattr(module.time, "monotonic", clock)

    def cancel_after_check(*args, check, **kwargs):
        check()
        job.stop("cancelled after last poll")
        check()  # Same instant: the throttled poll may return, but claim must fail.
        return "a" * 64

    monkeypatch.setattr(module, "input_identity", cancel_after_check)
    with pytest.raises(JobStopped):
        run_operation(job, "pcbsmith.production_routing", ["--layout", "input.json"])
    assert not job.snapshot().attempts


def test_laser_artwork_has_supervised_verification_operation():
    from pcbsmith.board_job import MODULES, input_identity, operation_for

    assert "pcbsmith.laser_artwork" in MODULES
    assert operation_for("pcbsmith.laser_artwork", ["--board", "board.kicad_pcb"]) == (
        "laser-artwork",
        "verify",
    )
    assert input_identity(
        "pcbsmith.laser_artwork", ["--board", "a", "--output", "x"]
    ) == input_identity("pcbsmith.laser_artwork", ["--board", "a", "--output", "y"])
    assert input_identity("pcbsmith.laser_artwork", ["--board", "a"]) != input_identity(
        "pcbsmith.laser_artwork", ["--board", "b"]
    )


def test_laser_identity_binds_native_closure_and_ignores_relocation(tmp_path, monkeypatch):
    import shutil

    import pcbsmith.board_job as module

    monkeypatch.setattr(module, "_IMPLEMENTATION_ROOT", tmp_path / "empty-implementation")
    project = tmp_path / "project"
    project.mkdir()
    board = project / "fixture.kicad_pcb"
    board.write_text('(kicad_pcb (version 20260206))')

    def identity(path, output="output"):
        return input_identity(
            "pcbsmith.laser_artwork", ["--board", str(path), "--output", output]
        )

    standalone = identity(board)
    board.with_suffix(".kicad_sch").write_text('(kicad_sch (version 20260101))')
    board.with_suffix(".kicad_pro").write_text('{"board": {}}')
    complete = identity(board)
    assert complete != standalone
    assert complete == identity(board, "another-output")
    moved = tmp_path / "relocated"
    shutil.copytree(project, moved)
    assert complete == identity(moved / board.name)
    board.with_suffix(".kicad_prl").write_text('{"irrelevant_ui_state": true}')
    assert complete == identity(board)
    board.with_suffix(".kicad_pro").write_text('{"board": {"changed_rule": true}}')
    assert complete != identity(board)

    library = project / "Local.pretty"
    library.mkdir()
    footprint = library / "Pad.kicad_mod"
    footprint.write_text('(footprint "Pad" (layer "F.Cu"))')
    (project / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "Local") (uri "${KIPRJMOD}/Local.pretty")))'
    )
    pinned = identity(board)
    footprint.write_text('(footprint "Pad" (layer "F.Cu") (attr smd))')
    assert pinned != identity(board)


def test_annotation_retry_requires_retained_electrically_complete_candidate(tmp_path):
    # Synthetic scope-control fixture, not a native acceptance report.
    import hashlib
    import json
    from types import SimpleNamespace

    from pcbsmith.board_job import JobStopped, _validate_edit_input_retry
    from pcbsmith.board_revision import BoardRevisionRequest
    from pcbsmith.kicad.native_edits import NativeEdit

    output = tmp_path / "revision"
    (output / "design").mkdir(parents=True)
    (output / "checks").mkdir()
    board = output / "design/board.kicad_pcb"
    board.write_text("(kicad_pcb)")
    inputs = {board.name: hashlib.sha256(board.read_bytes()).hexdigest()}
    (output / "revision.json").write_text(
        json.dumps({"candidate_inputs": inputs, "synthetic_test_only": True})
    )
    summary = {
        "erc_findings": 0,
        "drc_findings": {"unconnected_items": 0, "schematic_parity": 0},
        "synthetic_test_only": True,
    }
    (output / "checks/summary.json").write_text(json.dumps(summary))
    (output / "checks/drc.json").write_text(
        json.dumps({"violations": [{"type": "silk_overlap"}], "synthetic_test_only": True})
    )
    request_path = tmp_path / "correction.json"
    attempt = SimpleNamespace(
        command=(
            "pcbsmith.cli",
            "production-edit-board",
            str(tmp_path / "source/board.kicad_pcb"),
            "--output",
            str(output),
        )
    )

    def request(edit):
        r = BoardRevisionRequest(
            source_inputs=inputs, rationale="Test-only annotation correction", edits=(edit,)
        )
        request_path.write_text(r.model_dump_json())
        files = [
            request_path,
            output / "revision.json",
            output / "checks/summary.json",
            output / "checks/drc.json",
        ]
        return SimpleNamespace(
            edit_retry_request="correction.json",
            resolved_evidence={
                f.relative_to(tmp_path).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
                for f in files
            },
        )

    good = request(NativeEdit(kind="text", target="label", position_mm=(1, 1)))
    _validate_edit_input_retry(tmp_path, attempt, good)
    with pytest.raises(JobStopped, match="only retained candidate labels"):
        _validate_edit_input_retry(
            tmp_path,
            attempt,
            request(NativeEdit(kind="component", target="R1", position_mm=(1, 1))),
        )
    summary["drc_findings"]["unconnected_items"] = 1
    (output / "checks/summary.json").write_text(json.dumps(summary))
    with pytest.raises(JobStopped, match="electrically complete"):
        _validate_edit_input_retry(
            tmp_path, attempt, request(NativeEdit(kind="text", target="label", position_mm=(1, 1)))
        )
