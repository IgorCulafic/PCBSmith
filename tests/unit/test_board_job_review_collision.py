from types import SimpleNamespace

import pytest
from tests.unit.test_board_job import finish
from tests.unit.test_board_job_continuation import stopped as stopped

from pcbsmith.board_job import JobStopped


@pytest.fixture
def collision(stopped, monkeypatch):
    job, clock, request = stopped
    job.continue_authorized(request)
    root = job.root / "publication"
    (root / "generations/old").mkdir(parents=True)
    command = (
        "pcbsmith.cli",
        "production-visual-inspect",
        str(root),
        "--generation-id",
        "old",
        "--generation-sha256",
        "a" * 64,
    )
    attempt = job.claim(
        operation="visual-inspect", phase="verify", input_sha256="d" * 64, command=command
    )
    finish(job, attempt, "failed", "name collision")
    log = job.root / ".pcbsmith/job-runs" / attempt.token / "logs/visual-inspect.stderr.txt"
    log.parent.mkdir(parents=True)
    log.write_text("error: generation path already exists: " + str(root / "generations/old"))
    monkeypatch.setattr(
        "pcbsmith.production_workflow.resolve_current_generation",
        lambda _: SimpleNamespace(
            generation_id="old", generation_sha256="a" * 64, transaction_fingerprint="b" * 64
        ),
    )
    return job, attempt, command, log


def test_collision_resolution_preserves_clock_cycles_and_failed_attempt(collision):
    job, attempt, command, _ = collision
    before = job.snapshot()
    job.resolve_review_generation_collision(token=attempt.token, successor_id="reviewed")
    after = job.snapshot()
    assert after.active_deadline == before.active_deadline
    assert after.cycle == before.cycle
    assert after.attempts == before.attempts
    assert after.active_diagnostic is None
    changed = list(command)
    changed[changed.index("--generation-id") + 1] = "reviewed"
    next_attempt = job.claim(
        operation="visual-inspect", phase="verify", input_sha256="e" * 64, command=tuple(changed)
    )
    finish(job, next_attempt)


def test_collision_resolution_rejects_real_review_failure(collision):
    job, attempt, _, log = collision
    log.write_text("error: inspection rejected")
    with pytest.raises(JobStopped, match="exact precommit"):
        job.resolve_review_generation_collision(token=attempt.token, successor_id="reviewed")
    assert job.snapshot().active_diagnostic is not None


def test_collision_resolution_rejects_existing_successor(collision):
    job, attempt, _, _ = collision
    with pytest.raises(JobStopped, match="fresh"):
        job.resolve_review_generation_collision(token=attempt.token, successor_id="old")


def test_collision_retry_cannot_change_other_inputs(collision):
    job, attempt, command, _ = collision
    job.resolve_review_generation_collision(token=attempt.token, successor_id="reviewed")
    with pytest.raises(JobStopped, match="only successor"):
        job.claim(
            operation="visual-inspect", phase="verify", input_sha256="e" * 64, command=command
        )
