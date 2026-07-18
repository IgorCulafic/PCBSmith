from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest
from pydantic import ValidationError

from pcbsmith.corridor_guidance import CorridorGuidanceDisposition, CorridorGuidanceReport
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNetlist, TrackSegment
from pcbsmith.kicad.placement_candidates import generate_placement_candidates
from pcbsmith.kicad.placement_exact import (
    placement_exact_netlist_fingerprint,
    placement_route_geometry_fingerprint,
)
from pcbsmith.kicad.placement_routability import (
    PlacementProbe,
    bind_component_placement_geometry,
    board_layout_fingerprint,
    build_placement_geometry_catalog,
)
from pcbsmith.placement_candidate_ir import PlacementMovePolicy
from pcbsmith.placement_detail_ir import PlacementCandidateDetailRecord, PlacementDetailState
from pcbsmith.placement_exact_ir import (
    PlacementExactCandidateRecord,
    PlacementExactCheckEvidence,
    PlacementExactDisposition,
    PlacementFinalState,
    exact_candidate_input_fingerprint,
    exact_checker_report_fingerprint,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.placement_ir import (
    FootprintPlacementRegion,
    PlacementBudget,
    PlacementLegalizationPolicy,
    PlacementOccupancySpan,
    PlacementRegionVerification,
)
from pcbsmith.routing_ir import RoutingBudget, RoutingRunResult
from pcbsmith.semantic_integration_ir import (
    ExactRankValue,
    RetainedExactOutcome,
    RetainedR2RouteOutcome,
    SemanticAdvisoryOutcome,
    SemanticAdvisoryRankTerm,
    SemanticAxisEvaluation,
    SemanticAxisEvaluationState,
    SemanticAxisKind,
    SemanticBlockingOutcome,
    SemanticCandidateIntegration,
    SemanticDeclarationBinding,
    SemanticEvaluatorIdentity,
    SemanticIntegrationPhase,
    SemanticRankDirection,
    SemanticValidationOutcome,
)
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticMetric,
    SemanticQuantity,
    SemanticVerification,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
CONTEXT = "c" * 64


def _rect(size: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(outer=((-size, -size), (size, -size), (size, size), (-size, size))),
        )
    )


def _candidate() -> tuple[Any, PlacementProbe, BoardNetlist]:
    component = BoardComponent("U1", "fixture", "fixture:U1", "uuid:U1")
    layout = BoardLayout(
        placements=((component, 5.0),),
        segments=(TrackSegment(0.0, 0.0, 1.0, 0.0, "F.Cu", "FIXED", 0.2),),
        vias=(),
        width_mm=10.0,
        height_mm=10.0,
        parts_row_y_mm=5.0,
        outline=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        graphics=("(gr_text fixture (at 1 1) (layer F.SilkS))",),
        hide_references=("U1",),
    )
    body = FootprintPlacementRegion(
        region_id="U1:body",
        purpose="body",
        occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
        local_compound=_rect(0.2),
        verification=PlacementRegionVerification.EXACT,
        source_layers=("F.Fab",),
        source_fingerprint=_rect(0.2).semantic_fingerprint(),
    )
    courtyard = body.model_copy(
        update={
            "region_id": "U1:courtyard",
            "purpose": "courtyard",
            "local_compound": _rect(0.3),
            "source_layers": ("F.CrtYd",),
            "source_fingerprint": _rect(0.3).semantic_fingerprint(),
        }
    )
    catalog = build_placement_geometry_catalog(
        layout,
        (bind_component_placement_geometry(component, regions=(body, courtyard)),),
    )
    budget = PlacementBudget(
        max_proposals=2,
        max_legalization_evaluations=1,
        max_surrogate_evaluations=0,
        max_corridor_plans=0,
        max_detailed_candidates=0,
        max_exact_checks=0,
        max_r3_geometry_cells_per_candidate=0,
        max_r3_geometry_portals_per_candidate=0,
        max_r3_expansions_per_candidate=0,
        max_r2_passes_per_candidate=0,
        max_r2_expansions_per_candidate=0,
        max_r2_expansions_per_net=0,
        max_r2_stagnant_passes=0,
    )
    search = generate_placement_candidates(
        layout,
        catalog,
        PlacementMovePolicy(
            translation_step_mm=1.0,
            maximum_translation_steps=0,
            pair_move_limit=0,
            seed=1,
        ),
        PlacementLegalizationPolicy(
            policy_id="semantic-integration-fixture",
            minimum_body_spacing_mm=0.01,
            minimum_courtyard_spacing_mm=0.0,
            minimum_body_outer_edge_clearance_mm=0.01,
            minimum_body_cutout_clearance_mm=0.01,
            require_courtyard_containment=False,
            minimum_courtyard_outer_edge_clearance_mm=0.0,
        ),
        budget,
        target_nets=("A",),
        known_net_names=("A", "FIXED"),
        surrogate_evaluator=lambda _probe, _legalization: (_ for _ in ()).throw(
            AssertionError("surrogate budget is zero")
        ),
    )
    assert len(search.result.candidates) == len(search.probes) == 1
    return (
        search.result.candidates[0],
        search.probes[0],
        BoardNetlist(components=(component,), nets=()),
    )


def _binding(
    declaration_id: str,
    kind: SemanticAxisKind,
    authority: SemanticAuthorityClass,
    fingerprint: str,
) -> SemanticDeclarationBinding:
    return SemanticDeclarationBinding(
        declaration_id=declaration_id,
        axis_kind=kind,
        authority=authority,
        declaration_fingerprint=fingerprint,
    )


def _finding(
    authority: SemanticAuthorityClass,
    disposition: SemanticDisposition,
) -> SemanticFinding:
    common: dict[str, Any] = {
        "rule_id": f"rule:{authority}:{disposition}",
        "authority": authority,
        "disposition": disposition,
        "verification": (
            SemanticVerification.UNSUPPORTED
            if disposition is SemanticDisposition.UNVERIFIED
            else SemanticVerification.EXACT
        ),
        "evidence_binding_ids": ("binding:fixture",),
        "message": "fixture semantic result",
        "suggested_action": "inspect fixture",
    }
    if authority is SemanticAuthorityClass.HARD_GEOMETRY:
        common["region_ids"] = ("region:fixture",)
    elif authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT:
        common["process_profile_id"] = "process:fixture"
        common["qualified_process_record_id"] = "qualification:fixture"
    elif authority is SemanticAuthorityClass.VALIDATION_REQUIRED:
        common["validation_requirement_ids"] = ("validation:fixture",)
        if disposition in {SemanticDisposition.PASS, SemanticDisposition.FAIL}:
            common["validation_profile_id"] = "campaign:fixture"
    return SemanticFinding(**common)


def _metric(metric_id: str, value: int = 1) -> SemanticMetric:
    return SemanticMetric(
        metric_id=metric_id,
        verification=SemanticVerification.EXACT,
        quantity=SemanticQuantity(
            quantity_id=f"quantity:{metric_id}",
            value=value,
            unit="um",
            source_binding_ids=("binding:fixture",),
        ),
    )


def _axis(
    binding: SemanticDeclarationBinding,
    candidate_fingerprint: str,
    layout_snapshot_fingerprint: str,
    netlist_snapshot_fingerprint: str,
    *,
    disposition: SemanticDisposition | None,
    phase: SemanticIntegrationPhase = SemanticIntegrationPhase.PLACEMENT,
    state: SemanticAxisEvaluationState = SemanticAxisEvaluationState.EVALUATED,
    metric: SemanticMetric | None = None,
) -> SemanticAxisEvaluation:
    findings = () if disposition is None else (_finding(binding.authority, disposition),)
    metrics = () if metric is None else (metric,)
    result = SemanticLayoutResult.build(
        context_fingerprint=CONTEXT,
        declarations_fingerprint=binding.declaration_fingerprint,
        geometry_fingerprint=layout_snapshot_fingerprint,
        placement_candidate_fingerprint=candidate_fingerprint,
        findings=findings,
        metrics=metrics,
    )
    evaluator = SemanticEvaluatorIdentity(
        evaluator_id=f"evaluator:{binding.declaration_id}",
        evaluator_revision="1",
        implementation_fingerprint=SHA_B,
        phase=phase,
    )
    return SemanticAxisEvaluation.build(
        axis_id=f"axis:{binding.declaration_id}",
        declaration=binding,
        phase=phase,
        state=state,
        evaluator=evaluator,
        phase_layout_snapshot_fingerprint=layout_snapshot_fingerprint,
        phase_netlist_snapshot_fingerprint=netlist_snapshot_fingerprint,
        context_fingerprint=CONTEXT,
        placement_candidate_fingerprint=candidate_fingerprint,
        semantic_result=result,
    )


def _empty() -> SemanticCandidateIntegration:
    candidate, probe, netlist = _candidate()
    return SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=candidate,
        probe_result=probe.result,
        probe_layout=probe.layout,
        netlist=netlist,
        existing_r5_rank_key=(4, Fraction(3, 2), 7),
        primary_safety_key_length=1,
    )


def _detail_and_exact(
    candidate_fingerprint: str,
    probe_layout: BoardLayout,
    netlist: BoardNetlist,
) -> tuple[BoardLayout, PlacementCandidateDetailRecord, PlacementExactCandidateRecord]:
    routed_segment = TrackSegment(2.0, 2.0, 3.0, 2.0, "F.Cu", "A", 0.2)
    final_layout = replace(probe_layout, segments=(*probe_layout.segments, routed_segment))
    routing = RoutingRunResult(
        producer="semantic-integration-fixture",
        budget=RoutingBudget(
            max_passes=1,
            max_expansions=1,
            max_expansions_per_net=1,
            max_stagnant_passes=1,
            max_exact_check_rejections=0,
        ),
        success=True,
        route_order=("A",),
    )
    guidance = CorridorGuidanceReport(
        disposition=CorridorGuidanceDisposition.ABSENT,
        unguided_net_names=("A",),
        routing_run_fingerprint=routing.semantic_fingerprint(),
    )
    final_fp = board_layout_fingerprint(final_layout)
    route_fp = placement_route_geometry_fingerprint(final_layout, frozenset(("A",)))
    detail = PlacementCandidateDetailRecord(
        candidate_fingerprint=candidate_fingerprint,
        detail_input_fingerprint="d" * 64,
        selected=True,
        state=PlacementDetailState.ROUTED_UNCHECKED,
        r3_evaluations_consumed=0,
        r2_evaluations_consumed=1,
        guidance=guidance,
        routing_run=routing,
        materialized_layout_fingerprint=final_fp,
        route_geometry_fingerprint=route_fp,
        algorithmic_success=True,
        zero_overuse=True,
        routed_unchecked=True,
    )
    detail_fp = detail.semantic_fingerprint()
    netlist_fp = placement_exact_netlist_fingerprint(netlist)
    checker_id = "exact:fixture"
    report = PlacementExactCheckEvidence(
        candidate_fingerprint=candidate_fingerprint,
        detail_record_fingerprint=detail_fp,
        routing_run_fingerprint=routing.semantic_fingerprint(),
        route_geometry_fingerprint=route_fp,
        materialized_layout_fingerprint=final_fp,
        checker_id=checker_id,
        checker_report_fingerprint=exact_checker_report_fingerprint(True, checker_id, ()),
        accepted=True,
        call_index=0,
    )
    exact = PlacementExactCandidateRecord(
        candidate_fingerprint=candidate_fingerprint,
        detail_record=detail,
        detail_record_fingerprint=detail_fp,
        netlist_fingerprint=netlist_fp,
        exact_input_fingerprint=exact_candidate_input_fingerprint(
            candidate_fingerprint,
            detail_fp,
            routing.semantic_fingerprint(),
            route_fp,
            final_fp,
            netlist_fp,
        ),
        exact_checks_consumed=1,
        checker_call_index=0,
        disposition=PlacementExactDisposition.EXACT_ACCEPTED,
        final_state=PlacementFinalState.ACCEPTED,
        exact_report=report,
        accepted=True,
    )
    return final_layout, detail, exact


def test_empty_declarations_preserve_lossless_probe_and_existing_rank_key() -> None:
    result = _empty()
    assert result.empty_semantic_result is not None
    assert result.empty_semantic_result.outcome.value == "not_applicable"
    assert result.semantic_comparison_key == result.existing_r5_rank_key
    assert result.comparison_key() == (Fraction(4), Fraction(3, 2), Fraction(7))
    assert result.probe_layout.graphics == ("(gr_text fixture (at 1 1) (layer F.SilkS))",)
    assert result.probe_layout.hide_references == ("U1",)
    assert result == SemanticCandidateIntegration.model_validate_json(result.model_dump_json())


def test_hard_and_process_failures_precede_hpwl_and_advisory_terms() -> None:
    base = _empty()
    hard = _binding(
        "antenna", SemanticAxisKind.ANTENNA, SemanticAuthorityClass.HARD_GEOMETRY, SHA_A
    )
    process = _binding(
        "retention",
        SemanticAxisKind.SIDE_ASSIGNMENT,
        SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
        SHA_B,
    )
    advisory_metric = _metric("metric:distance", 10_000)
    advisory = _binding(
        "distance",
        SemanticAxisKind.THERMAL,
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        "e" * 64,
    )
    axes = (
        _axis(
            advisory,
            base.candidate_record.candidate_fingerprint,
            base.probe_layout_snapshot_fingerprint,
            base.netlist_snapshot_fingerprint,
            disposition=SemanticDisposition.ADVISORY,
            metric=advisory_metric,
        ),
        _axis(
            hard,
            base.candidate_record.candidate_fingerprint,
            base.probe_layout_snapshot_fingerprint,
            base.netlist_snapshot_fingerprint,
            disposition=SemanticDisposition.FAIL,
        ),
        _axis(
            process,
            base.candidate_record.candidate_fingerprint,
            base.probe_layout_snapshot_fingerprint,
            base.netlist_snapshot_fingerprint,
            disposition=SemanticDisposition.FAIL,
        ),
    )
    failed = SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=base.candidate_record,
        probe_result=base.probe_result,
        probe_layout=base.probe_layout,
        netlist=base.netlist,
        declarations=(hard, process, advisory),
        axis_evaluations=axes,
        existing_r5_rank_key=(0, 1),  # primary safety, then very favorable HPWL
        primary_safety_key_length=1,
        advisory_rank_terms=(
            SemanticAdvisoryRankTerm(
                axis_id="axis:distance",
                metric_id="metric:distance",
                metric_fingerprint=advisory_metric.semantic_fingerprint(),
                quantity_unit="um",
                direction=SemanticRankDirection.HIGHER_IS_BETTER,
                value=ExactRankValue.build(10_000),
            ),
        ),
    )
    passing_axis = _axis(
        hard,
        base.candidate_record.candidate_fingerprint,
        base.probe_layout_snapshot_fingerprint,
        base.netlist_snapshot_fingerprint,
        disposition=SemanticDisposition.PASS,
    )
    passing_process = _axis(
        process,
        base.candidate_record.candidate_fingerprint,
        base.probe_layout_snapshot_fingerprint,
        base.netlist_snapshot_fingerprint,
        disposition=SemanticDisposition.PASS,
    )
    passing = SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=base.candidate_record,
        probe_result=base.probe_result,
        probe_layout=base.probe_layout,
        netlist=base.netlist,
        declarations=(hard, process, advisory),
        axis_evaluations=(passing_axis, passing_process, axes[0]),
        existing_r5_rank_key=(0, 999_999),
        primary_safety_key_length=1,
    )
    assert failed.hard_geometry_outcome is SemanticBlockingOutcome.REJECTED
    assert failed.qualified_process_outcome is SemanticBlockingOutcome.REJECTED
    assert failed.advisory_outcome is SemanticAdvisoryOutcome.REVIEW
    assert failed.semantic_route_acceptance_blocked
    assert passing.comparison_key() < failed.comparison_key()
    payload = failed.model_dump(mode="json")
    payload["advisory_rank_terms"][0]["value"]["numerator"] = 9_999
    with pytest.raises(ValidationError, match="retained metric"):
        SemanticCandidateIntegration.model_validate(payload)


def test_placement_cannot_claim_routed_success_and_record_order_is_set_like() -> None:
    base = _empty()
    loop = _binding(
        "loop", SemanticAxisKind.DECOUPLING_LOOP, SemanticAuthorityClass.HARD_GEOMETRY, SHA_A
    )
    with pytest.raises(ValidationError, match="placement cannot claim routed"):
        _axis(
            loop,
            base.candidate_record.candidate_fingerprint,
            base.probe_layout_snapshot_fingerprint,
            base.netlist_snapshot_fingerprint,
            disposition=SemanticDisposition.PASS,
        )

    wrong_geometry_result = SemanticLayoutResult.build(
        context_fingerprint=CONTEXT,
        declarations_fingerprint=loop.declaration_fingerprint,
        geometry_fingerprint="f" * 64,
        placement_candidate_fingerprint=base.candidate_record.candidate_fingerprint,
        findings=(_finding(loop.authority, SemanticDisposition.PASS),),
    )
    with pytest.raises(ValidationError, match="geometry differs"):
        SemanticAxisEvaluation.build(
            axis_id="axis:loop",
            declaration=loop,
            phase=SemanticIntegrationPhase.ROUTED,
            state=SemanticAxisEvaluationState.EVALUATED,
            evaluator=SemanticEvaluatorIdentity(
                evaluator_id="evaluator:loop",
                evaluator_revision="1",
                implementation_fingerprint=SHA_B,
                phase=SemanticIntegrationPhase.ROUTED,
            ),
            phase_layout_snapshot_fingerprint=base.probe_layout_snapshot_fingerprint,
            phase_netlist_snapshot_fingerprint=base.netlist_snapshot_fingerprint,
            context_fingerprint=CONTEXT,
            placement_candidate_fingerprint=base.candidate_record.candidate_fingerprint,
            semantic_result=wrong_geometry_result,
        )

    deferred = _axis(
        loop,
        base.candidate_record.candidate_fingerprint,
        base.probe_layout_snapshot_fingerprint,
        base.netlist_snapshot_fingerprint,
        disposition=None,
        state=SemanticAxisEvaluationState.DEFERRED_TO_ROUTED,
    )
    antenna = _binding(
        "antenna", SemanticAxisKind.ANTENNA, SemanticAuthorityClass.HARD_GEOMETRY, SHA_B
    )
    antenna_axis = _axis(
        antenna,
        base.candidate_record.candidate_fingerprint,
        base.probe_layout_snapshot_fingerprint,
        base.netlist_snapshot_fingerprint,
        disposition=SemanticDisposition.PASS,
    )
    first = SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=base.candidate_record,
        probe_result=base.probe_result,
        probe_layout=base.probe_layout,
        netlist=base.netlist,
        declarations=(loop, antenna),
        axis_evaluations=(deferred, antenna_axis),
    )
    second = SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=base.candidate_record,
        probe_result=base.probe_result,
        probe_layout=base.probe_layout,
        netlist=base.netlist,
        declarations=(loop, antenna),
        axis_evaluations=(antenna_axis, deferred),
    )
    assert first.axis_evaluations == second.axis_evaluations
    assert first.semantic_fingerprint() == second.semantic_fingerprint()


def test_r2_success_exact_acceptance_and_routed_semantic_failure_coexist() -> None:
    base = _empty()
    final_layout, detail, exact = _detail_and_exact(
        base.candidate_record.candidate_fingerprint,
        base.probe_layout,
        base.netlist,
    )
    loop = _binding(
        "loop", SemanticAxisKind.DECOUPLING_LOOP, SemanticAuthorityClass.HARD_GEOMETRY, SHA_A
    )
    from pcbsmith.kicad.board_serialization import (  # local keeps fixture intent explicit
        board_layout_snapshot_fingerprint,
        canonical_board_layout_snapshot_json,
    )

    final_snapshot_fp = board_layout_snapshot_fingerprint(
        canonical_board_layout_snapshot_json(final_layout)
    )
    routed_failure = _axis(
        loop,
        base.candidate_record.candidate_fingerprint,
        final_snapshot_fp,
        base.netlist_snapshot_fingerprint,
        disposition=SemanticDisposition.FAIL,
        phase=SemanticIntegrationPhase.ROUTED,
    )
    integrated = SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=base.candidate_record,
        probe_result=base.probe_result,
        probe_layout=base.probe_layout,
        netlist=base.netlist,
        declarations=(loop,),
        axis_evaluations=(routed_failure,),
        final_routed_layout=final_layout,
        detail_record=detail,
        exact_record=exact,
        existing_r5_rank_key=(0, 10),
        primary_safety_key_length=1,
    )
    assert integrated.route_outcome is RetainedR2RouteOutcome.SUCCEEDED_ZERO_OVERUSE
    assert integrated.exact_outcome is RetainedExactOutcome.ACCEPTED
    assert integrated.hard_geometry_outcome is SemanticBlockingOutcome.REJECTED
    assert integrated.detail_record == detail
    assert integrated.exact_record == exact


def test_validation_pending_is_distinct_and_advisory_never_blocks() -> None:
    base = _empty()
    validation = _binding(
        "rf-validation",
        SemanticAxisKind.ANTENNA,
        SemanticAuthorityClass.VALIDATION_REQUIRED,
        SHA_A,
    )
    advisory = _binding(
        "thermal-distance",
        SemanticAxisKind.THERMAL,
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        SHA_B,
    )
    axes = (
        _axis(
            validation,
            base.candidate_record.candidate_fingerprint,
            base.probe_layout_snapshot_fingerprint,
            base.netlist_snapshot_fingerprint,
            disposition=SemanticDisposition.VALIDATION_PENDING,
        ),
        _axis(
            advisory,
            base.candidate_record.candidate_fingerprint,
            base.probe_layout_snapshot_fingerprint,
            base.netlist_snapshot_fingerprint,
            disposition=SemanticDisposition.ADVISORY,
        ),
    )
    result = SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=base.candidate_record,
        probe_result=base.probe_result,
        probe_layout=base.probe_layout,
        netlist=base.netlist,
        declarations=(validation, advisory),
        axis_evaluations=axes,
    )
    assert result.validation_outcome is SemanticValidationOutcome.PENDING
    assert result.route_outcome is RetainedR2RouteOutcome.NOT_EVALUATED
    assert result.exact_outcome is RetainedExactOutcome.NOT_EVALUATED
    assert not result.semantic_route_acceptance_blocked


def test_ordered_declarations_and_all_replay_bindings_reject_tamper() -> None:
    base = _empty()
    first_binding = _binding(
        "first", SemanticAxisKind.ANTENNA, SemanticAuthorityClass.HARD_GEOMETRY, SHA_A
    )
    second_binding = _binding(
        "second", SemanticAxisKind.OSCILLATOR, SemanticAuthorityClass.HARD_GEOMETRY, SHA_B
    )
    axes = tuple(
        _axis(
            binding,
            base.candidate_record.candidate_fingerprint,
            base.probe_layout_snapshot_fingerprint,
            base.netlist_snapshot_fingerprint,
            disposition=SemanticDisposition.PASS,
        )
        for binding in (first_binding, second_binding)
    )
    forward = SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=base.candidate_record,
        probe_result=base.probe_result,
        probe_layout=base.probe_layout,
        netlist=base.netlist,
        declarations=(first_binding, second_binding),
        axis_evaluations=axes,
    )
    reversed_declarations = SemanticCandidateIntegration.build(
        context_fingerprint=CONTEXT,
        candidate_record=base.candidate_record,
        probe_result=base.probe_result,
        probe_layout=base.probe_layout,
        netlist=base.netlist,
        declarations=(second_binding, first_binding),
        axis_evaluations=reversed(axes),
    )
    assert forward.declarations_fingerprint != reversed_declarations.declarations_fingerprint
    assert forward.axis_evaluations == reversed_declarations.axis_evaluations

    for field, value, message in (
        ("context_fingerprint", "f" * 64, "context"),
        ("probe_layout_snapshot_fingerprint", "f" * 64, "snapshot"),
        ("input_fingerprint", "f" * 64, "input fingerprint"),
    ):
        payload = forward.model_dump(mode="json")
        payload[field] = value
        with pytest.raises(ValidationError, match=message):
            SemanticCandidateIntegration.model_validate(payload)

    payload = forward.model_dump(mode="json")
    payload["axis_evaluations"][0]["evaluator"]["evaluator_revision"] = "2"
    with pytest.raises(ValidationError, match="evaluator fingerprint"):
        SemanticCandidateIntegration.model_validate(payload)

    payload = forward.model_dump(mode="json")
    payload["axis_evaluations"][0]["semantic_result"]["outcome"] = "hard_rejected"
    with pytest.raises(ValidationError, match="outcome is not derived"):
        SemanticCandidateIntegration.model_validate(payload)

    with pytest.raises(ValidationError, match="frozen"):
        forward.context_fingerprint = "f" * 64
