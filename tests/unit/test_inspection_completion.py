"""Synthetic metadata-completion controls; no physical or board approval proof."""

from __future__ import annotations

import hashlib

import pytest
from tests.unit.test_board_job import Clock
from tests.unit.test_production_workflow import _empty_component_review

from pcbsmith.board_job import BoardJob, JobStopped, require_library_worker
from pcbsmith.inspection_completion import InspectionCompletionRequest
from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.production_workflow import (
    commit_generation_transaction,
    prepare_generation_transaction,
    resolve_current_generation,
)
from pcbsmith.review.visual_package import RenderProfile, ReviewArtifact, VisualReviewManifest
from pcbsmith.workflow_authority import WorkflowStage


@pytest.fixture
def closed(tmp_path, monkeypatch, request):
    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="Synthetic completion control")
    target = tmp_path / "production"
    source = target / "generations/old"
    board = b"synthetic native fixture, not a usable PCB"
    image = b"synthetic test artifact, not an inspected real image"

    def sha(b):
        return hashlib.sha256(b).hexdigest()

    visual = VisualReviewManifest(
        schema_id="pcbsmith-visual-review-manifest-v1",
        render_profile=RenderProfile(),
        stage="final" if getattr(request, "param", None) == "legacy" else "placement",
        board_file=str(source / "design/test.kicad_pcb"),
        board_sha256=sha(board),
        copper_sha256=sha(board),
        kicad_version="synthetic",
        renderer_version="synthetic",
        model_preflight_status="passed",
        workflow_conformance_status="conformant",
        package_status="generated_pending_inspection",
        artifacts=(
            ReviewArtifact(
                artifact_id="front",
                category="overview/front",
                relative_path="front.png",
                media_type="image/png",
                required=True,
                state="generated",
                sha256=sha(image),
            ),
        ),
    )
    payloads = {
        "design/test.kicad_pcb": board,
        "review/front.png": image,
        "review/manifest.json": visual.model_dump_json(by_alias=True).encode(),
        "review/review-report.md": b"Synthetic predecessor report",
        "evidence/component-review/execution.json": _empty_component_review()
        .model_dump_json()
        .encode(),
    }
    if getattr(request, "param", None) == "legacy":
        del payloads["evidence/component-review/execution.json"]
    staged = prepare_generation_transaction(
        project_id="project",
        generation_id="old",
        generation_sha256="a" * 64,
        stage=WorkflowStage.REVIEW,
        payloads=payloads,
        roles={k: "board" if k.endswith("kicad_pcb") else "review" for k in payloads},
    )
    # Only synthetic predecessor setup bypasses the worker; completion runs with the real guard.
    with monkeypatch.context() as m:
        m.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
        commit_generation_transaction(transaction_root=target, manifest=staged, payloads=payloads)
    job.stop("Synthetic predecessor finished", finished=True)
    request = InspectionCompletionRequest(
        authorization_reference="Synthetic test authorization",
        transaction_root="production",
        predecessor_pointer_sha256=file_sha256(target / "CURRENT.json"),
        predecessor_manifest_sha256=file_sha256(source / "review/manifest.json"),
        successor_generation_id="inspected",
        evaluation_seconds=60,
        execution_seconds=60,
        reviewer="synthetic reviewer",
        mechanism="Synthetic test decision only",
    )
    decisions = {
        "front": {
            "sha256": sha(image),
            "inspection": "accepted",
            "findings": ["Synthetic fixture observation; no real visual claim."],
        }
    }
    return job, clock, request, decisions, source


def test_completion_preserves_original_ledger_and_every_nonreview_byte(closed):
    job, _, request, decisions, source = closed
    before = {
        p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
    ledger = job.path.read_bytes()
    job.authorize_inspection_completion(request)
    result = job.complete_inspection(decisions)
    assert result["status"] == "committed"
    assert result["inspection_status"] == "accepted"
    assert result["job_history_preserved"]
    assert job.path.read_bytes() == ledger
    assert all((source / name).read_bytes() == data for name, data in before.items())
    successor = resolve_current_generation(job.root / "production")
    assert successor.stage == WorkflowStage.REVIEW
    new = job.root / "production/generations/inspected"
    for name, data in before.items():
        if name not in {"review/manifest.json", "review/review-report.md", "transaction.json"}:
            assert (new / name).read_bytes() == data
    with pytest.raises(JobStopped):
        require_library_worker()
    with pytest.raises(ValueError):
        job.complete_inspection(decisions)


@pytest.mark.parametrize("mutation", ["authority", "path", "stale", "active"])
def test_authorization_rejects_invalid_scope(closed, mutation):
    job, _, request, _, _ = closed
    data = request.model_dump()
    if mutation == "authority":
        data["authorization_reference"] = " "
    if mutation == "path":
        data["transaction_root"] = "../foreign"
    if mutation == "stale":
        data["predecessor_pointer_sha256"] = "0" * 64
    if mutation == "active":
        other = BoardJob(job.root / "active")
        other.start(complexity="simple", rationale="fixture")
        job = other
    with pytest.raises((ValueError, RuntimeError)):
        job.authorize_inspection_completion(InspectionCompletionRequest.model_validate(data))
    assert not (job.root / ".pcbsmith/inspection-completion").exists()


@pytest.mark.parametrize("mutation", ["missing", "hash", "empty", "state", "geometry", "ledger"])
def test_completion_rejects_stale_or_incomplete_review(closed, mutation):
    job, _, request, decisions, source = closed
    job.authorize_inspection_completion(request)
    if mutation == "missing":
        decisions = {}
    if mutation == "hash":
        decisions["front"]["sha256"] = "0" * 64
    if mutation == "empty":
        decisions["front"]["findings"] = []
    if mutation == "state":
        decisions["front"]["inspection"] = "uninspected"
    if mutation == "geometry":
        (source / "design/test.kicad_pcb").write_bytes(b"changed")
    if mutation == "ledger":
        job.path.write_bytes(job.path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        job.complete_inspection(decisions)
    assert not (job.root / "production/generations/inspected").exists()


def test_evaluation_deadline_does_not_renew(closed):
    job, clock, request, decisions, _ = closed
    job.authorize_inspection_completion(request)
    clock.now += 61
    with pytest.raises(ValueError, match="evaluation allowance"):
        job.complete_inspection(decisions)
    with pytest.raises(ValueError, match="already authorized"):
        job.authorize_inspection_completion(request)


@pytest.mark.parametrize("fault", ["geometry", "timeout"])
def test_commit_rechecks_scope_and_retains_failed_attempt(closed, monkeypatch, fault):
    import pcbsmith.production_workflow as workflow

    job, clock, request, decisions, _ = closed
    job.authorize_inspection_completion(request)
    original = workflow.prepare_generation_transaction

    def mutate(**kwargs):
        if fault == "geometry":
            kwargs["payloads"]["design/test.kicad_pcb"] = b"unauthorized edit"
        else:
            clock.now += 61
        return original(**kwargs)

    monkeypatch.setattr(workflow, "prepare_generation_transaction", mutate)
    with pytest.raises(ValueError):
        job.complete_inspection(decisions)
    assert resolve_current_generation(job.root / "production").generation_id == "old"
    assert (job.root / ".pcbsmith/inspection-completion/failure.json").exists()
    with pytest.raises(ValueError):
        job.complete_inspection(decisions)


def test_attention_is_retained_not_promoted_to_acceptance(closed):
    job, _, request, decisions, _ = closed
    decisions["front"]["inspection"] = "attention_required"
    job.authorize_inspection_completion(request)
    result = job.complete_inspection(decisions)
    assert result["inspection_status"] == "attention_required"


@pytest.mark.parametrize("closed", ["legacy"], indirect=True)
def test_legacy_final_completion_does_not_invent_component_evidence(closed):
    job, _, request, decisions, _ = closed
    job.authorize_inspection_completion(request)
    result = job.complete_inspection(decisions)
    assert result["status"] == "committed"
    # This deliberately unrouted final fixture remains rejected by visual owner.
    assert result["inspection_status"] == "generation_failed"
    current = resolve_current_generation(job.root / "production")
    assert not any("component-review" in a.relative_path for a in current.artifacts)


def test_exact_legacy_failure_can_resume_without_resetting_allowance(closed, monkeypatch):
    import pcbsmith.production_workflow as workflow

    job, clock, request, decisions, _ = closed
    job.authorize_inspection_completion(request)
    original = workflow.inspect_current_placement_review

    def fail(**kwargs):
        clock.now += 2
        raise ValueError("current generation has no component review execution")

    monkeypatch.setattr(workflow, "inspect_current_placement_review", fail)
    with pytest.raises(ValueError):
        job.complete_inspection(decisions)
    prior = job.root / ".pcbsmith/inspection-completion/failure.json"
    digest = file_sha256(prior)
    monkeypatch.setattr(workflow, "inspect_current_placement_review", original)
    result = job.complete_inspection(decisions, digest)
    assert result["execution_seconds"] >= 2
    assert file_sha256(prior) == digest
    with pytest.raises(ValueError):
        job.complete_inspection(decisions, digest)
