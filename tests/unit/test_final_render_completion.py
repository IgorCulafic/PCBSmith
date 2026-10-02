"""Synthetic guard tests; real native receipts are qualified separately."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from tests.unit.test_board_job import Clock, finish
from tests.unit.test_board_job_diagnostic import assessment

from pcbsmith.board_job import BoardJob, ContinuationRequest, JobStopped, _validate_final_render


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def completion(tmp_path, monkeypatch):
    from pcbsmith import mandatory_review, routing_policy
    from pcbsmith.kicad import project_dependencies, routing_candidate_transaction

    root = tmp_path.resolve()
    board = root / "board.kicad_pcb"
    board.write_text("synthetic accepted routed board")
    board_hash = sha(board)
    features, models = root / "features.json", root / "models.json"
    features.write_text("{}")
    models.write_text("{}")
    checks = root / "checks"
    checks.mkdir()
    (checks / "summary.json").write_text("synthetic current native evidence")
    route = root / "route"
    route.mkdir()
    (route / "result.json").write_text("synthetic routing owner result")
    monkeypatch.setattr(project_dependencies, "native_project_hashes", lambda b: {b.name: sha(b)})
    monkeypatch.setattr(mandatory_review, "require_current_native_checks", lambda b, c: {})
    monkeypatch.setattr(routing_policy, "routing_design_fingerprint", lambda a, b: "d" * 64)
    monkeypatch.setattr(
        routing_candidate_transaction.RoutingCandidateTransactionResult,
        "model_validate_json",
        lambda raw: object(),
    )
    monkeypatch.setattr(
        routing_candidate_transaction.AcceptedRoutingExecution,
        "from_transaction",
        lambda result: SimpleNamespace(board_sha256=board_hash),
    )
    clock = Clock()
    job = BoardJob(root, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="Synthetic render completion guards")
    command = (
        "pcbsmith.cli",
        "visual-review",
        str(board),
        str(root / "final"),
        "--stage",
        "final",
        "--features",
        str(features),
        "--model-preflight",
        str(models),
        "--native-checks",
        str(checks),
    )
    for i in range(3):
        placement = list(command)
        placement[3] = str(root / f"placement-{i}")
        placement[5] = "placement"
        finish(
            job,
            job.claim(
                operation="visual-render",
                phase="verify",
                input_sha256=str(i) * 64,
                command=placement,
            ),
        )
    finish(
        job,
        job.claim(
            operation="routing",
            phase="build",
            input_sha256="a" * 64,
            command=(
                "pcbsmith.production_routing",
                "--output",
                str(route),
                "--layout",
                "synthetic-layout",
                "--netlist",
                "synthetic-netlist",
            ),
        ),
    )
    job.begin_diagnostic("Synthetic final render allowance blocker")
    diagnostic = assessment(root)
    job.complete_diagnostic(diagnostic)
    (root / "diagnostic.json").write_text(diagnostic.model_dump_json())
    job.stop("Synthetic preservation before explicit completion")
    inputs = {
        p.relative_to(root).as_posix(): sha(p)
        for p in [board, features, models, checks / "summary.json", route / "result.json"]
    }
    plan = root / "plan.json"
    plan.write_text(json.dumps({"command": command, "inputs": inputs}))
    request = ContinuationRequest(
        predecessor_sha256=sha(job.path),
        assessment_file="diagnostic.json",
        assessment_sha256=sha(root / "diagnostic.json"),
        authorization_reference="New explicit synthetic final-only approval",
        seconds=600,
        reserve_seconds=120,
        evaluation_seconds=600,
        build_operations=(),
        blocker_resolution="Qualified one source-bound final render with preserved history",
        resolved_evidence={"plan.json": sha(plan)},
        final_render_plan="plan.json",
    )
    return job, request, command, plan, board


def test_completion_preserves_history_and_allows_only_one_final_render(completion):
    job, request, command, _, _ = completion
    before = job.snapshot()
    job.continue_authorized(request)
    after = job.snapshot()
    assert after.started_at == before.started_at and after.cycle == before.cycle
    assert after.deadline == before.deadline and after.attempts == before.attempts
    finish(
        job,
        job.claim(
            operation="visual-render", phase="verify", input_sha256="b" * 64, command=command
        ),
    )
    assert len([a for a in job.snapshot().attempts if a.operation == "visual-render"]) == 4
    with pytest.raises(JobStopped, match="only one"):
        job.claim(operation="visual-render", phase="verify", input_sha256="c" * 64, command=command)


@pytest.mark.parametrize("mutation", ["board", "plan", "evidence", "output"])
def test_stale_inputs_and_started_output_rejected(completion, mutation):
    job, request, _, plan, board = completion
    if mutation == "board":
        board.write_text("changed board")
    elif mutation == "plan":
        plan.write_text("{}")
    elif mutation == "evidence":
        (job.root / "checks/summary.json").write_text("changed evidence")
    else:
        (job.root / "final").mkdir()
    with pytest.raises((JobStopped, ValueError)):
        job.continue_authorized(request)


@pytest.mark.parametrize("mutation", ["placement", "board", "output", "features", "extra"])
def test_command_cannot_change_after_authorization(completion, mutation):
    job, request, command, _, _ = completion
    job.continue_authorized(request)
    altered = list(command)
    if mutation == "extra":
        altered.extend(["--stage", "final"])
    else:
        altered[{"placement": 5, "board": 2, "output": 3, "features": 7}[mutation]] = mutation
    with pytest.raises(JobStopped, match="command differs"):
        job.claim(operation="visual-render", phase="verify", input_sha256="b" * 64, command=altered)


def test_ordinary_lifetime_limit_is_unchanged(completion):
    job, request, command, _, _ = completion
    request.final_render_plan = None
    job.continue_authorized(request)
    with pytest.raises(JobStopped, match="allowance exhausted"):
        job.claim(operation="visual-render", phase="verify", input_sha256="b" * 64, command=command)


def test_no_build_or_routing_operations_are_granted(completion):
    job, request, _, _, _ = completion
    job.continue_authorized(request)
    for operation in ("edit", "routing", "placement"):
        with pytest.raises(JobStopped, match="outside explicitly authorized"):
            job.claim(operation=operation, phase="build", input_sha256="b" * 64, command=())


def test_rebound_board_still_must_match_accepted_route(completion):
    job, request, _, plan, board = completion
    board.write_text("different native board")
    payload = json.loads(plan.read_text())
    payload["inputs"][board.name] = sha(board)
    plan.write_text(json.dumps(payload))
    request.resolved_evidence[plan.name] = sha(plan)
    with pytest.raises(JobStopped, match="differs from accepted routing"):
        job.continue_authorized(request)


@pytest.mark.parametrize("mutation", ["failed", "already_final", "only_two", "route_failed"])
def test_requires_three_successful_placement_views_and_accepted_route(completion, mutation):
    job, request, _, _, _ = completion
    attempts = job.snapshot().attempts
    if mutation == "only_two":
        attempts.pop(0)
    elif mutation == "already_final":
        command = list(attempts[0].command)
        command[5] = "final"
        attempts[0].command = tuple(command)
    else:
        attempts[-1 if mutation == "route_failed" else 0].status = "failed"
    with pytest.raises(JobStopped):
        _validate_final_render(job.root, attempts, request)


def test_native_evidence_owner_failure_propagates(completion, monkeypatch):
    from pcbsmith import mandatory_review

    job, request, _, _, _ = completion

    def reject(board, checks):
        raise ValueError("native receipts do not match current source")

    monkeypatch.setattr(mandatory_review, "require_current_native_checks", reject)
    with pytest.raises(ValueError, match="native receipts"):
        job.continue_authorized(request)


def test_inputs_are_checked_again_when_worker_is_claimed(completion):
    job, request, command, _, board = completion
    job.continue_authorized(request)
    board.write_text("changed after continuation approval")
    with pytest.raises(JobStopped, match="input changed"):
        job.claim(operation="visual-render", phase="verify", input_sha256="b" * 64, command=command)


def test_missing_dependency_in_plan_is_rejected(completion):
    job, request, _, plan, _ = completion
    payload = json.loads(plan.read_text())
    del payload["inputs"]["checks/summary.json"]
    plan.write_text(json.dumps(payload))
    request.resolved_evidence[plan.name] = sha(plan)
    with pytest.raises(JobStopped, match="omits current"):
        job.continue_authorized(request)


def test_new_continuation_cannot_renew_final_render(completion):
    job, request, command, _, _ = completion
    job.continue_authorized(request)
    finish(
        job,
        job.claim(
            operation="visual-render", phase="verify", input_sha256="b" * 64, command=command
        ),
    )
    job.begin_diagnostic("Synthetic attempt to renew completion")
    diagnostic = assessment(job.root)
    job.complete_diagnostic(diagnostic)
    job.stop("Synthetic stop")
    request.predecessor_sha256 = sha(job.path)
    request.authorization_reference = "Another synthetic decision cannot renew this scope"
    with pytest.raises(JobStopped, match="available only once"):
        job.continue_authorized(request)


def test_completion_request_cannot_include_build_scope(completion):
    _, request, _, _, _ = completion
    with pytest.raises(ValueError, match="verification-only"):
        ContinuationRequest.model_validate({**request.model_dump(), "build_operations": ["edit"]})
