"""Synthetic controller checks; these do not assert native board acceptance."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from tests.unit.test_board_job import claim, finish
from tests.unit.test_board_job_completion_inventory import completion
from tests.unit.test_board_job_diagnostic import assessment

from pcbsmith.board_job import ContinuationRequest, JobStopped, _validate_automatic_retry
from pcbsmith.native_project import NativeProjectSpec
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def recovery(tmp_path):
    job, clock, initial = completion(tmp_path)
    initial = initial.model_copy(
        update={
            "build_operations": ("native-preparation", "routing"),
            "completion_allowances": {"native-preparation": 1, "routing": 1, "visual-render": 2},
        }
    )
    job.continue_authorized(initial)
    finish(job, claim(job, operation="native-preparation", key="d"))
    route = job.claim(
        operation="routing",
        phase="build",
        input_sha256="e" * 64,
        command=("synthetic-routing-fixture",),
    )
    finish(job, route, "failed", "one open")
    job.begin_diagnostic("one placement obstruction")
    clock.now += 301
    job.snapshot()
    job.stop("retain expired diagnosis")
    report = assessment(tmp_path).model_copy(
        update={"cause": "local_design", "action": "local_edit"}
    )
    report_file = tmp_path / "pose-diagnosis.json"
    report_file.write_text(report.model_dump_json())
    spec = NativeProjectSpec.model_validate(
        dict(
            project_id="fixture",
            title="Fixture",
            user_request="Synthetic pose guard",
            width_mm=70,
            height_mm=100,
            profile=DEFAULT_PCB_RULE_PROFILE,
            parts=[
                dict(
                    reference="J1",
                    symbol="Test:Pad",
                    value="Pad",
                    footprint="Test:Pad",
                    mpn="COPPER",
                    role="contact",
                    pins={"1": "GND"},
                    schematic_at=[12.7, 12.7],
                    board_at=[60, 20, 90],
                )
            ],
        )
    )
    old = tmp_path / "old-spec.json"
    old.write_text(spec.model_dump_json())
    new = tmp_path / "new-spec.json"
    revised = spec.model_copy(
        update={"parts": (spec.parts[0].model_copy(update={"board_at": (56, 20, 90)}),)}
    )
    new.write_text(revised.model_dump_json())
    board = tmp_path / "board.kicad_pcb"
    board.write_text(
        '(kicad_pcb (footprint "Pad" (uuid "pad-id") (at 80 40 90) '
        '(property "Reference" "J1" (at 0 0))))'
    )
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "source_spec": old.name,
                "revised_spec": new.name,
                "board": board.name,
                "source_inputs": {p.name: sha(p) for p in [old, new, board]},
                "edits": [{"kind": "component", "target": "pad-id", "position_mm": [76, 40]}],
            }
        )
    )
    request = ContinuationRequest(
        predecessor_sha256=sha(job.path),
        assessment_file=report_file.name,
        assessment_sha256=sha(report_file),
        authorization_reference="Explicit approval of bounded pose recovery",
        seconds=600,
        reserve_seconds=120,
        evaluation_seconds=1200,
        build_operations=(
            "native-preparation",
            "predesign-refresh",
            "predesign-reapprove",
            "edit",
            "routing",
        ),
        blocker_resolution="One exact local pose correction and final automatic route",
        resolved_evidence={plan.name: sha(plan)},
        retry_failed_operations={"routing": route.token},
        automatic_retry_plan=plan.name,
        retrospective_diagnostic=True,
    )
    return job, clock, request, plan, new


def test_recovery_preserves_predecessor_and_separates_inventory_scopes(recovery):
    job, _, request, _, spec = recovery
    before = job.snapshot()
    raw = job.path.read_bytes()
    request = request.model_copy(update={"predecessor_sha256": sha(job.path)})
    job.continue_authorized(request)
    state = job.snapshot()
    assert state.started_at == before.started_at and state.deadline == before.deadline
    assert state.continuation_history[0].deadline == before.continuation.deadline
    assert state.continuation_history[0].diagnostic.status == "expired"
    assert (job.root / ".pcbsmith/continuation-predecessor-2.json").read_bytes() == raw
    attempt = job.claim(
        operation="native-preparation",
        phase="build",
        input_sha256="f" * 64,
        command=("pcbsmith.native_project", str(spec)),
    )
    finish(job, attempt)
    assert len(job.snapshot().attempts) == len(before.attempts) + 1
    with pytest.raises(JobStopped, match="one attempt"):
        job.claim(
            operation="native-preparation",
            phase="build",
            input_sha256="g" * 64,
            command=("pcbsmith.native_project", str(spec)),
        )


@pytest.mark.parametrize("mutation", ["plan", "source", "electrical", "wrong_target", "large_move"])
def test_recovery_rejects_changed_or_expanded_plan(recovery, mutation):
    job, _, request, plan, spec = recovery
    payload = json.loads(plan.read_text())
    if mutation == "plan":
        plan.write_text("{}")
    elif mutation == "source":
        spec.write_text("{}")
    else:
        if mutation == "wrong_target":
            payload["edits"][0]["target"] = "other"
        else:
            data = json.loads(spec.read_text())
            if mutation == "electrical":
                data["parts"][0]["pins"] = {"1": "OTHER"}
            else:
                data["parts"][0]["board_at"][0] = 20
            spec.write_text(json.dumps(data))
            payload["source_inputs"][spec.name] = sha(spec)
        plan.write_text(json.dumps(payload))
        request = request.model_copy(update={"resolved_evidence": {plan.name: sha(plan)}})
    with pytest.raises((JobStopped, ValueError)):
        _validate_automatic_retry(job.root, job.snapshot().attempts, request)


def test_recovery_cannot_renew_or_allow_third_route(recovery):
    job, _, request, _, _ = recovery
    job.continue_authorized(request)
    finish(
        job,
        job.claim(
            operation="routing",
            phase="build",
            input_sha256="f" * 64,
            command=("synthetic-routing-fixture",),
        ),
    )
    with pytest.raises(JobStopped):
        claim(job, operation="routing", key="g")
    job.begin_diagnostic("test renewal rejection")
    job.complete_diagnostic(assessment(job.root).model_copy(update={"action": "local_edit"}))
    job.stop("test stopped")
    request = request.model_copy(
        update={
            "predecessor_sha256": sha(job.path),
            "authorization_reference": "Cannot renew exact recovery",
        }
    )
    with pytest.raises(JobStopped):
        job.continue_authorized(request)


def inspection_preflight(recovery, monkeypatch):
    job, _, request, _, _ = recovery
    job.continue_authorized(request)
    root = job.root / "transactions"
    root.mkdir()
    decisions = job.root / "decisions.json"
    decisions.write_text("Synthetic observation inputs")
    command = (
        "pcbsmith.cli",
        "production-visual-inspect",
        str(root),
        "--generation-id",
        "inspected",
        "--decisions",
        str(decisions),
        "--output",
        str(job.root / "result.json"),
    )
    attempt = job.claim(
        operation="visual-inspect", phase="verify", input_sha256="a" * 64, command=command
    )
    finish(job, attempt, "failed", "argparse missing inputs")
    logs = job.root / ".pcbsmith/job-runs" / attempt.token / "logs"
    logs.mkdir(parents=True)
    log = logs / "visual-inspect.stderr.txt"
    log.write_text(
        "pcbsmith production-visual-inspect: error: the following arguments "
        "are required: --generation-sha256, --reviewer, --mechanism\n"
    )
    monkeypatch.setattr(
        "pcbsmith.production_workflow.resolve_current_generation",
        lambda p: SimpleNamespace(generation_sha256="b" * 64, transaction_fingerprint="c" * 64),
    )
    return (
        job,
        command
        + (
            "--generation-sha256",
            "b" * 64,
            "--reviewer",
            "reviewer",
            "--mechanism",
            "actual viewed inputs",
        ),
        log,
        decisions,
    )


def test_inspection_argument_repair_preserves_time_and_two_real_inspections(recovery, monkeypatch):
    job, command, _, _ = inspection_preflight(recovery, monkeypatch)
    before = job.snapshot()
    job.resolve_inspection_argument_preflight(command)
    finish(
        job,
        job.claim(
            operation="visual-inspect", phase="verify", input_sha256="b" * 64, command=command
        ),
    )
    finish(
        job,
        job.claim(
            operation="visual-inspect",
            phase="verify",
            input_sha256="c" * 64,
            command=("synthetic-final-inspection",),
        ),
    )
    assert job.snapshot().continuation.deadline == before.continuation.deadline
    with pytest.raises(JobStopped):
        job.claim(
            operation="visual-inspect", phase="verify", input_sha256="d" * 64, command=command
        )


def test_inspection_argument_repair_rejects_other_error(recovery, monkeypatch):
    job, command, log, _ = inspection_preflight(recovery, monkeypatch)
    log.write_text("Actual visual rejection")
    with pytest.raises(JobStopped, match="argparse preflight"):
        job.resolve_inspection_argument_preflight(command)


def test_inspection_argument_repair_rejects_changed_decisions(recovery, monkeypatch):
    job, command, _, decisions = inspection_preflight(recovery, monkeypatch)
    job.resolve_inspection_argument_preflight(command)
    decisions.write_text("Changed")
    with pytest.raises(JobStopped, match="exact preflight recovery"):
        job.claim(
            operation="visual-inspect", phase="verify", input_sha256="b" * 64, command=command
        )
