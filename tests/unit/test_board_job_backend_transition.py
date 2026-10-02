import hashlib

import pytest
from tests.unit.test_board_job import Clock, claim, finish
from tests.unit.test_board_job_diagnostic import assessment

from pcbsmith.board_job import (
    BoardJob,
    ContinuationRequest,
    JobStopped,
    _validate_routing_backend_transition,
)
from pcbsmith.kicad.freerouting_production import FreeroutingProductionConfig
from pcbsmith.kicad.routing_external_adapters import ExternalToolBinding


def test_backend_transition_keeps_stopped_predecessor_and_binds_exact_command(tmp_path):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="Synthetic backend-transition fixture")
    failed = claim(job)
    finish(job, failed, "failed", "stagnation")
    job.begin_diagnostic("native backend stagnated")
    report = assessment(tmp_path).model_copy(update={"action": "stop"})
    job.complete_diagnostic(report)
    job.stop("native stagnation; user may select a different backend")
    path = tmp_path / "assessment.json"
    path.write_text(report.model_dump_json())
    jar = tmp_path / "fixture.jar"
    jar.write_bytes(b"synthetic runtime")
    digest = hashlib.sha256(jar.read_bytes()).hexdigest()
    cfg = FreeroutingProductionConfig(
        binding=ExternalToolBinding(
            root_path=str(jar),
            entrypoint_path=str(jar),
            entrypoint_sha256=digest,
            distribution_sha256=digest,
        ),
        java_executable=str(jar),
        kicad_python=str(jar),
        process_seconds=20,
        max_passes=4,
    )
    config = tmp_path / "router.json"
    config.write_text(cfg.model_dump_json())
    before = job.path.read_bytes()
    req = ContinuationRequest(
        predecessor_sha256=hashlib.sha256(before).hexdigest(),
        assessment_file="assessment.json",
        assessment_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_reference=(
            "Synthetic explicit switch to Freerouting after stopped native search"
        ),
        seconds=600,
        reserve_seconds=120,
        evaluation_seconds=600,
        build_operations=("routing",),
        blocker_resolution="Pinned production backend with independent native validation",
        resolved_evidence={"router.json": hashlib.sha256(config.read_bytes()).hexdigest()},
        retry_failed_operations={"routing": failed.token},
        routing_attempt_limit=4,
        routing_backend_config="router.json",
    )
    job.continue_authorized(req)
    state = job.snapshot()
    assert len(state.attempts) == 1
    assert state.attempts[0].token == failed.token
    assert (tmp_path / ".pcbsmith/continuation-predecessor.json").read_bytes() == before
    with pytest.raises(JobStopped, match="authorized backend"):
        _validate_routing_backend_transition(
            tmp_path, state.attempts, req, ("pcbsmith.production_routing",)
        )
    _validate_routing_backend_transition(
        tmp_path,
        state.attempts,
        req,
        ("pcbsmith.production_routing", "--freerouting-config", str(config)),
    )
    config.write_text(config.read_text() + " ")
    with pytest.raises(JobStopped, match="configuration changed"):
        _validate_routing_backend_transition(tmp_path, state.attempts, req)
