from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pcbsmith.execution import EXECUTION_PROFILES, WorkBudgetExhausted
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
)
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.production_workflow import (
    CompletedRouteDomain,
    GenerationArtifact,
    GenerationTransactionManifest,
    NativeAlgorithm,
    NativeStageController,
    NativeStageTimeout,
    RouteDomainRequest,
    bind_execution_profile,
    build_deterministic_route_plan,
    build_route_domain_checkpoint,
    commit_generation_transaction,
    evaluate_routing_entry_gate,
    inspect_current_placement_review,
    persist_placement_and_generate_review,
    persist_routed_board_and_generate_review,
    prepare_generation_transaction,
    produce_budgeted_placement_review,
    remaining_route_domains,
    resolve_current_generation,
    route_native_board,
)
from pcbsmith.project_engineering_gate import evaluate_project_engineering_gate
from pcbsmith.project_engineering_gate_ir import (
    InventoryStatus,
    Phase14EvaluationBundle,
    ProjectEngineeringContext,
)
from pcbsmith.prompt_examiner import (
    ExaminedClaim,
    PromptResolution,
    SourceSpan,
    examine_prompt,
)
from pcbsmith.review.visual_package import (
    RenderProfile,
    ReviewArtifact,
    VisualReviewManifest,
)
from pcbsmith.workflow_authority import (
    ALL_PROJECT_CONTEXT_CATEGORIES,
    ProjectContextBundle,
    ProjectContextRecord,
    ProjectContextStatus,
    WorkflowStage,
)
from pcbsmith.workflow_feasibility import (
    compare_concept_anchors,
    evaluate_pre_route_feasibility,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _transaction(
    *,
    generation_id: str = "generation-1",
    generation_sha256: str = SHA_A,
    previous_current_sha256: str | None = None,
):
    payloads = {
        "design/board.kicad_pcb": b"board-v1",
        "review/manifest.json": b"review-v1",
    }
    manifest = prepare_generation_transaction(
        project_id="project",
        generation_id=generation_id,
        generation_sha256=generation_sha256,
        stage=WorkflowStage.PLACEMENT,
        payloads=payloads,
        roles={
            "design/board.kicad_pcb": "board",
            "review/manifest.json": "review",
        },
        previous_current_sha256=previous_current_sha256,
    )
    return manifest, payloads


def test_generation_commit_publishes_one_hash_checked_generation(tmp_path: Path) -> None:
    manifest, payloads = _transaction()
    result = commit_generation_transaction(
        transaction_root=tmp_path,
        manifest=manifest,
        payloads=payloads,
    )

    assert result.manifest.status == "committed"
    assert result.current_generation_after == "generation-1"
    assert resolve_current_generation(tmp_path) == result.manifest


def test_failed_second_generation_retains_previous_pointer_and_failure(
    tmp_path: Path,
) -> None:
    first, first_payloads = _transaction()
    first_result = commit_generation_transaction(
        transaction_root=tmp_path,
        manifest=first,
        payloads=first_payloads,
    )
    current_sha = hashlib.sha256((tmp_path / "CURRENT.json").read_bytes()).hexdigest()
    second, second_payloads = _transaction(
        generation_id="generation-2",
        generation_sha256=SHA_B,
        previous_current_sha256=current_sha,
    )

    def fail_before_pointer_swap() -> None:
        raise RuntimeError("injected promotion failure")

    second_result = commit_generation_transaction(
        transaction_root=tmp_path,
        manifest=second,
        payloads=second_payloads,
        before_pointer_swap=fail_before_pointer_swap,
    )

    assert second_result.manifest.status == "rolled_back"
    assert second_result.current_generation_after == "generation-1"
    assert resolve_current_generation(tmp_path) == first_result.manifest
    assert (tmp_path / "failed" / "generation-2" / "transaction.json").is_file()


def test_placement_persistence_automatically_invokes_review_and_commits_it(
    tmp_path: Path,
) -> None:
    calls: list[Path] = []
    board_payload = b"saved-placement-board"
    board_sha = hashlib.sha256(board_payload).hexdigest()

    def review_generator(board_file: Path, output_dir: Path) -> VisualReviewManifest:
        calls.append(board_file)
        output_dir.mkdir(parents=True)
        (output_dir / "front.png").write_bytes(b"review-image")
        return VisualReviewManifest(
            schema_id="pcbsmith-visual-review-manifest-v1",
            render_profile=RenderProfile(),
            stage="placement",
            board_file=str(board_file),
            board_sha256=board_sha,
            copper_sha256=SHA_C,
            kicad_version="9.0",
            renderer_version="test",
            model_preflight_status="passed",
            workflow_conformance_status="conformant",
            package_status="generated_pending_inspection",
            artifacts=(
                ReviewArtifact(
                    artifact_id="2d:front-design:png",
                    category="overview/front",
                    relative_path="front.png",
                    media_type="image/png",
                    required=True,
                    state="generated",
                    side="front",
                    sha256=hashlib.sha256(b"review-image").hexdigest(),
                ),
            ),
        )

    result = persist_placement_and_generate_review(
        transaction_root=tmp_path,
        project_id="project",
        generation_id="placement-1",
        generation_sha256=SHA_A,
        board_relative_path="design/board.kicad_pcb",
        board_payload=board_payload,
        review_generator=review_generator,
    )

    assert len(calls) == 1
    assert result.transaction.manifest.status == "committed"
    assert {item.role for item in result.transaction.manifest.artifacts} == {"board", "review"}
    assert Path(result.review_manifest.board_file).read_bytes() == board_payload
    assert (
        tmp_path / "generations" / "placement-1" / "review" / "front.png"
    ).read_bytes() == b"review-image"

    inspected = inspect_current_placement_review(
        transaction_root=tmp_path,
        generation_id="placement-2",
        generation_sha256=SHA_B,
        reviewer="fixture-reviewer",
        mechanism="human visual inspection",
        decisions={"2d:front-design:png": ("accepted", ())},
    )
    assert inspected.transaction.manifest.status == "committed"
    assert inspected.review_manifest.package_status == "accepted"
    assert resolve_current_generation(tmp_path).generation_id == "placement-2"
    assert Path(inspected.review_manifest.board_file).read_bytes() == board_payload


def test_budgeted_placement_and_per_artifact_rendering_are_operative(
    tmp_path: Path,
) -> None:
    bindings = {
        item.algorithm: item for item in bind_execution_profile(EXECUTION_PROFILES["quick"])
    }
    board_payload = b"budgeted-placement-board"
    board_sha = hashlib.sha256(board_payload).hexdigest()

    def placement(controller: NativeStageController) -> bytes:
        controller.consume_pass()
        controller.consume_expansions(4)
        return board_payload

    def render(
        controller: NativeStageController,
        board_file: Path,
        output_dir: Path,
    ) -> VisualReviewManifest:
        output_dir.mkdir(parents=True)
        artifacts = []
        for artifact_id in ("front", "back"):
            controller.consume_pass()
            controller.consume_expansions(2)
            payload = artifact_id.encode()
            relative = f"{artifact_id}.png"
            (output_dir / relative).write_bytes(payload)
            artifacts.append(
                ReviewArtifact(
                    artifact_id=f"2d:{artifact_id}:png",
                    category=f"overview/{artifact_id}",
                    relative_path=relative,
                    media_type="image/png",
                    required=True,
                    state="generated",
                    side=artifact_id,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
        return VisualReviewManifest(
            schema_id="pcbsmith-visual-review-manifest-v1",
            render_profile=RenderProfile(),
            stage="placement",
            board_file=str(board_file),
            board_sha256=board_sha,
            copper_sha256=SHA_C,
            kicad_version="10.0",
            renderer_version="test",
            model_preflight_status="passed",
            workflow_conformance_status="conformant",
            package_status="generated_pending_inspection",
            artifacts=tuple(artifacts),
        )

    result = produce_budgeted_placement_review(
        transaction_root=tmp_path,
        project_id="project",
        generation_id="budgeted-1",
        generation_sha256=SHA_A,
        board_relative_path="design/board.kicad_pcb",
        placement_binding=bindings[NativeAlgorithm.PLACEMENT],
        rendering_binding=bindings[NativeAlgorithm.RENDERING],
        placement_generator=placement,
        review_generator=render,
    )

    assert result.allowed
    assert result.transaction is not None
    assert result.placement_telemetry.passes == 1
    assert result.placement_telemetry.expansions == 4
    assert result.rendering_telemetry.passes == 2
    assert result.rendering_telemetry.expansions == 4
    assert resolve_current_generation(tmp_path).generation_id == "budgeted-1"


def test_budgeted_rendering_cannot_omit_per_artifact_accounting(
    tmp_path: Path,
) -> None:
    bindings = {
        item.algorithm: item for item in bind_execution_profile(EXECUTION_PROFILES["quick"])
    }
    board_payload = b"budgeted-placement-board"
    board_sha = hashlib.sha256(board_payload).hexdigest()

    def placement(controller: NativeStageController) -> bytes:
        controller.consume_pass()
        controller.consume_expansions()
        return board_payload

    def unaccounted_render(
        _controller: NativeStageController,
        board_file: Path,
        output_dir: Path,
    ) -> VisualReviewManifest:
        output_dir.mkdir(parents=True)
        payload = b"front"
        (output_dir / "front.png").write_bytes(payload)
        return VisualReviewManifest(
            schema_id="pcbsmith-visual-review-manifest-v1",
            render_profile=RenderProfile(),
            stage="placement",
            board_file=str(board_file),
            board_sha256=board_sha,
            copper_sha256=SHA_C,
            kicad_version="10.0",
            renderer_version="test",
            model_preflight_status="passed",
            workflow_conformance_status="conformant",
            package_status="generated_pending_inspection",
            artifacts=(
                ReviewArtifact(
                    artifact_id="2d:front:png",
                    category="overview/front",
                    relative_path="front.png",
                    media_type="image/png",
                    required=True,
                    state="generated",
                    side="front",
                    sha256=hashlib.sha256(payload).hexdigest(),
                ),
            ),
        )

    result = produce_budgeted_placement_review(
        transaction_root=tmp_path,
        project_id="project",
        generation_id="budgeted-failed",
        generation_sha256=SHA_A,
        board_relative_path="design/board.kicad_pcb",
        placement_binding=bindings[NativeAlgorithm.PLACEMENT],
        rendering_binding=bindings[NativeAlgorithm.RENDERING],
        placement_generator=placement,
        review_generator=unaccounted_render,
    )

    assert not result.allowed
    assert result.transaction is None
    assert result.rendering_telemetry.termination == "failed"
    assert any("did not account for every review artifact" in item for item in result.blockers)
    assert not (tmp_path / "CURRENT.json").exists()


def _routed_board_payload(*, include_segment: bool = True) -> bytes:
    segment = (
        """
  (segment
    (start 1 1)
    (end 5 1)
    (width 0.25)
    (layer "F.Cu")
    (net 1)
  )
"""
        if include_segment
        else ""
    )
    return f"""(kicad_pcb
  (version 20260206)
  (net 1 "SIG")
  (footprint "Test:A"
    (layer "F.Cu")
    (at 1 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  (footprint "Test:B"
    (layer "F.Cu")
    (at 5 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  {segment}
)
""".encode()


def test_routed_persistence_requires_exact_clean_drc_and_final_review(
    tmp_path: Path,
) -> None:
    board_payload = _routed_board_payload()

    def drc_generator(_board: Path, report: Path) -> None:
        report.write_text(
            json.dumps(
                {
                    "violations": [],
                    "unconnected_items": [],
                    "schematic_parity": [],
                }
            ),
            encoding="utf-8",
        )

    def review_generator(board: Path, output: Path) -> VisualReviewManifest:
        from pcbsmith.kicad.routing_evidence import inspect_saved_board_routing

        output.mkdir(parents=True)
        (output / "front.png").write_bytes(b"routed-review")
        routing = inspect_saved_board_routing(board)
        return VisualReviewManifest(
            schema_id="pcbsmith-visual-review-manifest-v1",
            render_profile=RenderProfile(),
            stage="final",
            board_file=str(board),
            board_sha256=routing.board_sha256,
            copper_sha256=SHA_C,
            routing_evidence=routing,
            kicad_version="9.0",
            renderer_version="test",
            model_preflight_status="passed",
            workflow_conformance_status="conformant",
            package_status="generated_pending_inspection",
            artifacts=(),
        )

    result = persist_routed_board_and_generate_review(
        transaction_root=tmp_path,
        project_id="project",
        generation_id="route-1",
        generation_sha256=SHA_A,
        board_relative_path="design/board.kicad_pcb",
        board_payload=board_payload,
        review_generator=review_generator,
        drc_generator=drc_generator,
    )

    assert result.transaction.manifest.status == "committed"
    assert result.transaction.manifest.stage is WorkflowStage.REVIEW
    assert result.routing_evidence.state.value == "routed_candidate"
    assert result.drc_evidence.clean
    assert Path(result.review_manifest.board_file).read_bytes() == board_payload
    assert Path(result.drc_evidence.report_file).is_file()


def test_routed_persistence_rejects_placement_only_board_before_callbacks(
    tmp_path: Path,
) -> None:
    called = False

    def drc_generator(_board: Path, _report: Path) -> None:
        nonlocal called
        called = True

    with pytest.raises(ValueError, match="complete saved-board carrier coverage"):
        persist_routed_board_and_generate_review(
            transaction_root=tmp_path,
            project_id="project",
            generation_id="route-1",
            generation_sha256=SHA_A,
            board_relative_path="design/board.kicad_pcb",
            board_payload=_routed_board_payload(include_segment=False),
            review_generator=lambda _board, _output: pytest.fail("review must not run"),
            drc_generator=drc_generator,
        )

    assert not called
    assert not (tmp_path / "CURRENT.json").exists()


def test_routed_persistence_rejects_unclean_drc_before_review(
    tmp_path: Path,
) -> None:
    def drc_generator(_board: Path, report: Path) -> None:
        report.write_text(
            json.dumps(
                {
                    "violations": [{"type": "clearance"}],
                    "unconnected_items": [],
                    "schematic_parity": [],
                }
            ),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="clean KiCad DRC"):
        persist_routed_board_and_generate_review(
            transaction_root=tmp_path,
            project_id="project",
            generation_id="route-1",
            generation_sha256=SHA_A,
            board_relative_path="design/board.kicad_pcb",
            board_payload=_routed_board_payload(),
            review_generator=lambda _board, _output: pytest.fail("review must not run"),
            drc_generator=drc_generator,
        )

    assert not (tmp_path / "CURRENT.json").exists()


def test_transaction_rejects_payload_revision_mixing_before_writes(
    tmp_path: Path,
) -> None:
    manifest, payloads = _transaction()
    changed = dict(payloads)
    changed["design/board.kicad_pcb"] = b"foreign-revision"

    with pytest.raises(ValueError, match="digest changed"):
        commit_generation_transaction(
            transaction_root=tmp_path,
            manifest=manifest,
            payloads=changed,
        )

    assert not (tmp_path / "CURRENT.json").exists()


def _route_domain(
    domain_id: str,
    *,
    priority: int,
    dependencies: tuple[str, ...] = (),
    nets: tuple[str, ...] | None = None,
    input_fingerprint: str = SHA_A,
) -> RouteDomainRequest:
    return RouteDomainRequest(
        domain_id=domain_id,
        priority=priority,
        dependency_domain_ids=dependencies,
        net_names=nets or (f"/{domain_id}",),
        input_fingerprint=input_fingerprint,
    )


def test_route_order_is_topological_and_repository_deterministic() -> None:
    plan = build_deterministic_route_plan(
        generation_sha256=SHA_A,
        start_board_sha256=SHA_B,
        domains=(
            _route_domain("power", priority=1),
            _route_domain("signals", priority=0, dependencies=("power",)),
            _route_domain("clock", priority=0),
        ),
    )

    assert tuple(item.domain_id for item in plan.ordered_domains) == (
        "clock",
        "power",
        "signals",
    )
    repeated = build_deterministic_route_plan(
        generation_sha256=SHA_A,
        start_board_sha256=SHA_B,
        domains=tuple(reversed(plan.ordered_domains)),
    )
    assert repeated.plan_fingerprint == plan.plan_fingerprint


def test_route_checkpoint_requires_exact_accepted_prefix_and_board_chain() -> None:
    plan = build_deterministic_route_plan(
        generation_sha256=SHA_A,
        start_board_sha256=SHA_B,
        domains=(
            _route_domain("power", priority=0),
            _route_domain("signals", priority=1, dependencies=("power",)),
        ),
    )
    completed = CompletedRouteDomain(
        domain_id="power",
        domain_input_fingerprint=SHA_A,
        input_board_sha256=SHA_B,
        output_board_sha256=SHA_C,
        exact_acceptance_sha256=SHA_D,
    )
    checkpoint = build_route_domain_checkpoint(plan=plan, completed_domains=(completed,))

    assert checkpoint.current_board_sha256 == SHA_C
    assert tuple(
        item.domain_id for item in remaining_route_domains(plan=plan, checkpoint=checkpoint)
    ) == ("signals",)

    foreign = completed.model_copy(update={"domain_id": "signals"})
    with pytest.raises(ValueError, match="replay-equivalent"):
        build_route_domain_checkpoint(plan=plan, completed_domains=(foreign,))


def test_profile_binds_every_native_algorithm_and_native_ledger() -> None:
    bindings = bind_execution_profile(EXECUTION_PROFILES["quick"])

    assert {item.algorithm for item in bindings} == set(NativeAlgorithm)
    routing = next(item for item in bindings if item.algorithm is NativeAlgorithm.ROUTING)
    ledger = routing.new_ledger()
    ledger.consume_expansions(routing.maximum_expansions)
    with pytest.raises(WorkBudgetExhausted):
        ledger.consume_expansions()


def test_native_stage_controller_emits_heartbeats_checkpoints_and_timeout() -> None:
    binding = next(
        item
        for item in bind_execution_profile(EXECUTION_PROFILES["quick"])
        if item.algorithm is NativeAlgorithm.ROUTING
    ).model_copy(update={"heartbeat_seconds": 2.0, "timeout_seconds": 5.0})
    now = [0.0]
    events: list[tuple[str, dict[str, object]]] = []
    controller = NativeStageController(
        binding=binding,
        clock=lambda: now[0],
        heartbeat_sink=lambda event, fields: events.append((event, dict(fields))),
    )
    controller.consume_expansions(2)
    now[0] = 2.1
    controller.consume_pass()
    controller.heartbeat("domain.complete", checkpoint_sha256=SHA_D)
    telemetry = controller.telemetry(
        generation_sha256=SHA_A,
        termination="incomplete",
    )

    assert telemetry.expansions == 2
    assert telemetry.passes == 1
    assert telemetry.heartbeat_count == 2
    assert telemetry.checkpoint_sha256 == SHA_D
    assert len(events) == 2

    now[0] = 5.1
    with pytest.raises(NativeStageTimeout):
        controller.consume_expansions()


def _ready_gate_inputs():
    text = "Use a rectangular board."
    span = SourceSpan(span_id="span.1", start=0, end=len(text), exact_text=text)
    examination = examine_prompt(
        project_id="project",
        original_text=text,
        spans=(span,),
        claims=(
            ExaminedClaim(
                claim_id="board.shape",
                field_path="mechanical.shape",
                value="rectangle",
                resolution=PromptResolution.EXPLICIT,
                source_span_ids=("span.1",),
            ),
        ),
    )
    context = ProjectContextBundle.build(
        project_id="project",
        generation_sha256=SHA_A,
        records=tuple(
            ProjectContextRecord(
                category=category,
                context_id=f"project.{category.value}",
                status=ProjectContextStatus.NOT_APPLICABLE,
                rationale="Not applicable in this focused gate fixture.",
            )
            for category in ALL_PROJECT_CONTEXT_CATEGORIES
        ),
    )
    feasibility = evaluate_pre_route_feasibility(
        board_outline=((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)),
        board_outline_sha256=SHA_B,
        keepout_polygons=(),
        envelopes=(),
        necks=(),
        net_demands=(),
    )
    drift = compare_concept_anchors(
        approved_concept_sha256=SHA_C,
        observed_design_sha256=SHA_B,
        approved=(),
        observed=(),
    )
    review = VisualReviewManifest(
        schema_id="pcbsmith-visual-review-manifest-v1",
        render_profile=RenderProfile(),
        stage="placement",
        board_file="board.kicad_pcb",
        board_sha256=SHA_B,
        copper_sha256=SHA_C,
        kicad_version="9.0",
        renderer_version="test",
        model_preflight_status="passed",
        workflow_conformance_status="conformant",
        package_status="accepted",
        artifacts=(),
    )
    review_bytes = (
        json.dumps(
            review.model_dump(mode="json", by_alias=True),
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    committed = GenerationTransactionManifest.build(
        project_id="project",
        generation_id="generation-1",
        generation_sha256=SHA_A,
        stage=WorkflowStage.PLACEMENT,
        status="committed",
        artifacts=(
            GenerationArtifact(
                artifact_id="generation-1.0001",
                role="board",
                relative_path="board.kicad_pcb",
                content_sha256=SHA_B,
            ),
            GenerationArtifact(
                artifact_id="generation-1.0002",
                role="review",
                relative_path="review/manifest.json",
                content_sha256=hashlib.sha256(review_bytes).hexdigest(),
            ),
        ),
    )
    engineering_gate = evaluate_project_engineering_gate(
        ProjectEngineeringContext.build(
            project_id="project",
            complexity_level="L0",
            board_layout_snapshot_fingerprint=SHA_B,
            board_netlist=BoardNetlist(components=(), nets=()),
            inventory_status=InventoryStatus.COMPLETE_REVIEWED,
            component_profiles=(),
            phase14_features=(),
            source_context_ids=("context.fixture-review",),
            reviewer_record_id="review.fixture-engineering",
            intended_consumer="production routing-entry gate fixture",
        ),
        Phase14EvaluationBundle(),
    )
    return (
        examination,
        context,
        feasibility,
        drift,
        review,
        committed,
        engineering_gate,
    )


def test_routing_entry_gate_requires_reviewed_transactional_saved_board() -> None:
    (
        examination,
        context,
        feasibility,
        drift,
        review,
        committed,
        engineering_gate,
    ) = _ready_gate_inputs()
    report = evaluate_routing_entry_gate(
        generation_sha256=SHA_A,
        saved_board_sha256=SHA_B,
        saved_layout_fingerprint=SHA_B,
        examination=examination,
        context=context,
        feasibility=feasibility,
        concept_drift=drift,
        placement_review=review,
        committed_review_transaction=committed,
        engineering_gate=engineering_gate,
        budget_bindings=bind_execution_profile(EXECUTION_PROFILES["quick"]),
    )

    assert report.allowed
    rejected = evaluate_routing_entry_gate(
        generation_sha256=SHA_A,
        saved_board_sha256=SHA_D,
        saved_layout_fingerprint=SHA_B,
        examination=examination,
        context=context,
        feasibility=feasibility,
        concept_drift=drift,
        placement_review=review,
        committed_review_transaction=committed,
        engineering_gate=engineering_gate,
        budget_bindings=bind_execution_profile(EXECUTION_PROFILES["quick"]),
    )
    assert not rejected.allowed
    assert any("different saved board" in item for item in rejected.blockers)

    incomplete_engineering = evaluate_project_engineering_gate(
        ProjectEngineeringContext.build(
            project_id="project",
            complexity_level="L0",
            board_layout_snapshot_fingerprint=SHA_B,
            board_netlist=BoardNetlist(components=(), nets=()),
            inventory_status=InventoryStatus.INCOMPLETE,
            component_profiles=(),
            phase14_features=(),
            source_context_ids=(),
            reviewer_record_id=None,
            intended_consumer="production routing-entry gate fixture",
        ),
        Phase14EvaluationBundle(),
    )
    engineering_rejected = evaluate_routing_entry_gate(
        generation_sha256=SHA_A,
        saved_board_sha256=SHA_B,
        saved_layout_fingerprint=SHA_B,
        examination=examination,
        context=context,
        feasibility=feasibility,
        concept_drift=drift,
        placement_review=review,
        committed_review_transaction=committed,
        engineering_gate=incomplete_engineering,
        budget_bindings=bind_execution_profile(EXECUTION_PROFILES["quick"]),
    )
    assert not engineering_rejected.allowed
    assert any("engineering" in item for item in engineering_rejected.blockers)


def test_native_router_consumes_gate_profile_budget_and_emits_pass_telemetry() -> None:
    (
        examination,
        context,
        feasibility,
        drift,
        review,
        committed,
        engineering_gate,
    ) = _ready_gate_inputs()
    bindings = bind_execution_profile(EXECUTION_PROFILES["quick"])
    gate = evaluate_routing_entry_gate(
        generation_sha256=SHA_A,
        saved_board_sha256=SHA_B,
        saved_layout_fingerprint=SHA_B,
        examination=examination,
        context=context,
        feasibility=feasibility,
        concept_drift=drift,
        placement_review=review,
        committed_review_transaction=committed,
        engineering_gate=engineering_gate,
        budget_bindings=bindings,
    )
    components = (
        BoardComponent(
            "R1",
            "1k",
            "Resistor_SMD:R_0603_1608Metric",
            "production-route-r1",
        ),
        BoardComponent(
            "R2",
            "1k",
            "Resistor_SMD:R_0603_1608Metric",
            "production-route-r2",
        ),
    )
    layout = BoardLayout(
        placements=((components[0], 5.0), (components[1], 20.0)),
        segments=(),
        vias=(),
        width_mm=25.0,
        height_mm=12.0,
        parts_row_y_mm=6.0,
    )
    netlist = BoardNetlist(
        components=components,
        nets=(BoardNet("/SIG", (("R1", "2"), ("R2", "1"))),),
    )
    events: list[tuple[str, dict[str, object]]] = []
    result = route_native_board(
        layout=layout,
        netlist=netlist,
        routing_gate=gate,
        binding=next(item for item in bindings if item.algorithm is NativeAlgorithm.ROUTING),
        exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(
            accepted=True,
            checker_id="fixture.native-production-exact-check",
        ),
        heartbeat_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    assert result.result.run_result.success
    assert result.exact_check is not None and result.exact_check.accepted
    assert result.telemetry.termination == "completed"
    assert result.telemetry.passes == len(result.result.run_result.passes)
    assert result.telemetry.expansions == sum(
        item.expansion_count for item in result.result.run_result.passes
    )
    assert result.telemetry.heartbeat_count == len(events)
    assert result.telemetry.checkpoint_sha256 is not None

    exact_rejected = route_native_board(
        layout=layout,
        netlist=netlist,
        routing_gate=gate,
        binding=next(item for item in bindings if item.algorithm is NativeAlgorithm.ROUTING),
        exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(
            accepted=False,
            checker_id="fixture.native-production-exact-check",
            finding_fingerprints=(SHA_D,),
        ),
    )
    assert exact_rejected.result.run_result.success
    assert exact_rejected.telemetry.termination == "failed"
    assert exact_rejected.telemetry.findings == (SHA_D,)
