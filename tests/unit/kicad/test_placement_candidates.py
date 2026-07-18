from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from pydantic import ValidationError

import pcbsmith.kicad.placement_candidates as placement_candidates
from pcbsmith.kicad.board import BoardComponent, BoardLayout
from pcbsmith.kicad.placement_candidates import generate_placement_candidates
from pcbsmith.kicad.placement_routability import (
    PlacementProbe,
    bind_component_placement_geometry,
    build_placement_geometry_catalog,
)
from pcbsmith.kicad.placement_surrogates import (
    DeterministicPlacementSurrogateEvaluator,
    PlacementSurrogateInput,
)
from pcbsmith.placement_candidate_ir import (
    PlacementCandidateDisposition,
    PlacementCandidateSearchResult,
    PlacementCandidateTerminalReason,
    PlacementMoveKind,
    PlacementMovePolicy,
    PlacementProposalKind,
    PlacementSurrogateEvidence,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.placement_ir import (
    FootprintPlacementRegion,
    PlacementBudget,
    PlacementGeometryCatalog,
    PlacementLegalizationOutcome,
    PlacementLegalizationPolicy,
    PlacementLegalizationResult,
    PlacementOccupancySpan,
    PlacementRegionVerification,
)
from pcbsmith.placement_surrogate_ir import PlacedTerminalCopper
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=f"value:{reference}",
        footprint=f"fixture:{reference}",
        uuid_path=f"uuid:{reference}",
    )


def _layout(
    *,
    outline: tuple[tuple[float, float], ...] | None = None,
    graphics: tuple[str, ...] = (),
    positions: tuple[tuple[str, float, float], ...] = (
        ("U1", 5.0, 5.0),
        ("U2", 10.0, 10.0),
        ("U3", 15.0, 15.0),
    ),
) -> BoardLayout:
    return BoardLayout(
        placements=tuple((_component(reference), x_mm) for reference, x_mm, _y_mm in positions),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=20.0,
        parts_row_y_mm=positions[0][2],
        part_y_mm=tuple((reference, y_mm) for reference, _x_mm, y_mm in positions[1:]),
        outline=outline,
        graphics=graphics,
    )


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _region(reference: str, purpose: str, size: float) -> FootprintPlacementRegion:
    compound = _rect(-size, -size, size, size)
    return FootprintPlacementRegion(
        region_id=f"{reference}:{purpose}",
        purpose=purpose,
        occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
        local_compound=compound,
        verification=PlacementRegionVerification.EXACT,
        source_layers=("F.Fab" if purpose == "body" else "F.CrtYd",),
        source_fingerprint=compound.semantic_fingerprint(),
    )


def _catalog(layout: BoardLayout) -> PlacementGeometryCatalog:
    components = tuple(
        bind_component_placement_geometry(
            component,
            regions=(
                _region(component.reference, "body", 0.2),
                _region(component.reference, "courtyard", 0.3),
            ),
        )
        for component, _x_mm in layout.placements
    )
    return build_placement_geometry_catalog(layout, components)


def _legalization_policy() -> PlacementLegalizationPolicy:
    return PlacementLegalizationPolicy(
        policy_id="r5.2-fixture",
        minimum_body_spacing_mm=0.01,
        minimum_courtyard_spacing_mm=0.0,
        minimum_body_outer_edge_clearance_mm=0.01,
        minimum_body_cutout_clearance_mm=0.01,
        require_courtyard_containment=False,
        minimum_courtyard_outer_edge_clearance_mm=0.0,
    )


def _move_policy(
    *,
    rotations: tuple[float, ...] = (0.0, 90.0),
    seed: int = 7,
    step: float = 1.0,
    pairs: int = 3,
) -> PlacementMovePolicy:
    return PlacementMovePolicy(
        movable_references=("U1",),
        rotatable_references=("U2",),
        flippable_references=("U3",),
        translation_step_mm=step,
        maximum_translation_steps=1,
        allowed_rotation_deg=rotations,
        pair_move_limit=pairs,
        seed=seed,
    )


def _budget(
    *,
    proposals: int = 100,
    legalizations: int = 100,
    surrogates: int = 100,
) -> PlacementBudget:
    return PlacementBudget(
        max_proposals=proposals,
        max_legalization_evaluations=legalizations,
        max_surrogate_evaluations=surrogates,
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


class _Surrogate:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(
        self,
        probe: PlacementProbe,
        legalization_result: PlacementLegalizationResult,
    ) -> PlacementSurrogateEvidence:
        assert legalization_result.outcome in {
            PlacementLegalizationOutcome.LEGAL_EXACT,
            PlacementLegalizationOutcome.LEGAL_BOUNDED,
        }
        pose_fingerprint = probe.result.telemetry.pose_fingerprint
        self.calls.append(pose_fingerprint)
        return PlacementSurrogateEvidence(
            evaluator_id="fixture-surrogate-boundary",
            evidence_fingerprint=hashlib.sha256(
                f"surrogate:{pose_fingerprint}".encode()
            ).hexdigest(),
        )


def _run(
    layout: BoardLayout,
    *,
    move_policy: PlacementMovePolicy | None = None,
    budget: PlacementBudget | None = None,
    target_nets: tuple[str, ...] = ("/A", "/B"),
    known_net_names: tuple[str, ...] = ("/A", "/B"),
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    surrogate: _Surrogate | None = None,
):
    evaluator = surrogate or _Surrogate()
    return generate_placement_candidates(
        layout,
        _catalog(layout),
        move_policy or _move_policy(),
        _legalization_policy(),
        budget or _budget(),
        target_nets=target_nets,
        known_net_names=known_net_names,
        profile=profile,
        surrogate_evaluator=evaluator,
    )


def _ids(result: PlacementCandidateSearchResult) -> tuple[str, ...]:
    return tuple(candidate.candidate_id for candidate in result.candidates)


def test_repeated_and_reversed_inputs_pin_order_and_base_first() -> None:
    layout = _layout()
    first = _run(layout, target_nets=("/B", "/A"), known_net_names=("/B", "/A"))
    second = _run(layout, target_nets=("/A", "/B"), known_net_names=("/A", "/B"))
    assert first.result == second.result
    assert (
        _ids(first.result)
        == _ids(second.result)
        == (
            "9424ab5b3fb1",
            "0650e6eae696",
            "890bbf4d4ebe",
            "3d1479ea0d24",
            "ed1daa42b0cf",
            "2c4df210fe86",
            "1eaa1147dbdc",
            "4cad49a771b0",
            "5f8fb704bbf8",
            "1e5049346e60",
        )
    )
    assert first.result.candidates[0].provenance.proposal_kind is PlacementProposalKind.BASE
    assert all(
        candidate.candidate_id == candidate.candidate_fingerprint[:12]
        for candidate in first.result.candidates
    )
    assert first.result.telemetry.terminal_reason is PlacementCandidateTerminalReason.COMPLETED
    assert first.result.semantic_fingerprint() == second.result.semantic_fingerprint()
    assert first.result.semantic_fingerprint() == (
        "05bfebc39cf0a1decb32214b7ae65db17eda12ac1ffc9c10d4e1470664f5ada0"
    )
    assert first.result.telemetry.semantic_fingerprint() == (
        "c2895b46631900fd5a23ab3a821f4711e251ab0df1be2fdf3ac32fd74f4649f1"
    )


def test_duplicate_move_is_canonicalized_and_does_not_renumber_later_candidates() -> None:
    layout = _layout()
    ordinary = _run(layout, move_policy=_move_policy(rotations=(0.0, 90.0))).result
    duplicated = _run(
        layout,
        move_policy=_move_policy(rotations=(360.0, 0.0, 90.0, 450.0)),
    ).result
    assert ordinary.move_policy == duplicated.move_policy
    assert _ids(ordinary) == _ids(duplicated)
    assert ordinary.telemetry.duplicate_proposals == 1
    assert ordinary.telemetry.proposals_consumed == len(ordinary.candidates) + 1


def test_shaped_edge_move_is_rejected_by_legalization_without_rectangle_clamp() -> None:
    outline = (
        (0.0, 0.0),
        (20.0, 0.0),
        (20.0, 20.0),
        (7.0, 20.0),
        (7.0, 5.0),
        (3.0, 5.0),
        (3.0, 20.0),
        (0.0, 20.0),
    )
    layout = _layout(
        outline=outline,
        positions=(("U1", 2.0, 6.0), ("U2", 12.0, 5.0), ("U3", 16.0, 10.0)),
    )
    search = _run(
        layout,
        move_policy=PlacementMovePolicy(
            movable_references=("U1",),
            translation_step_mm=2.0,
            maximum_translation_steps=1,
            pair_move_limit=0,
            seed=1,
        ),
    )
    moved_into_notch = next(
        candidate
        for candidate in search.result.candidates
        if candidate.provenance.clauses and candidate.provenance.clauses[0].delta_x_mm == 2.0
    )
    moved_pose = next(pose for pose in moved_into_notch.poses if pose.reference == "U1")
    assert (moved_pose.x_mm, moved_pose.y_mm) == (4.0, 6.0)
    assert moved_into_notch.disposition is PlacementCandidateDisposition.LEGALIZATION_REJECTED
    assert moved_into_notch.legalization_result.outcome is PlacementLegalizationOutcome.REJECTED
    assert moved_into_notch.surrogate_evidence is None


def test_translation_rotation_and_flip_permissions_fire_independently() -> None:
    result = _run(_layout(), move_policy=_move_policy(pairs=0)).result
    singles = tuple(
        candidate
        for candidate in result.candidates
        if candidate.provenance.proposal_kind is PlacementProposalKind.SINGLE
    )
    for candidate in singles:
        clause = candidate.provenance.clauses[0]
        poses = {pose.reference: pose for pose in candidate.poses}
        if clause.kind is PlacementMoveKind.TRANSLATE:
            assert clause.reference == "U1"
            assert poses["U1"].rotation_deg == 0.0 and poses["U1"].side == "front"
        elif clause.kind is PlacementMoveKind.ROTATE:
            assert clause.reference == "U2"
            assert (poses["U2"].x_mm, poses["U2"].y_mm, poses["U2"].side) == (
                10.0,
                10.0,
                "front",
            )
        else:
            assert clause.reference == "U3"
            assert (poses["U3"].x_mm, poses["U3"].y_mm, poses["U3"].rotation_deg) == (
                15.0,
                15.0,
                0.0,
            )
            assert poses["U3"].side == "back"


def test_zero_stage_budgets_have_typed_reasons_and_truthful_work() -> None:
    layout = _layout()
    proposal_zero = _run(layout, budget=_budget(proposals=0)).result
    assert not proposal_zero.candidates
    assert (
        proposal_zero.telemetry.terminal_reason
        is PlacementCandidateTerminalReason.PROPOSAL_BUDGET_EXHAUSTED
    )
    assert proposal_zero.telemetry.proposals_consumed == 0

    legalization_zero = _run(layout, budget=_budget(legalizations=0)).result
    assert not legalization_zero.candidates
    assert (
        legalization_zero.telemetry.terminal_reason
        is PlacementCandidateTerminalReason.LEGALIZATION_BUDGET_EXHAUSTED
    )
    assert legalization_zero.telemetry.proposals_consumed == 1
    assert legalization_zero.telemetry.legalization_evaluations_consumed == 0

    surrogate = _Surrogate()
    surrogate_zero = _run(layout, budget=_budget(surrogates=0), surrogate=surrogate).result
    assert len(surrogate_zero.candidates) == 1
    assert (
        surrogate_zero.candidates[0].disposition
        is PlacementCandidateDisposition.SURROGATE_BUDGET_EXHAUSTED
    )
    assert (
        surrogate_zero.telemetry.terminal_reason
        is PlacementCandidateTerminalReason.SURROGATE_BUDGET_EXHAUSTED
    )
    assert surrogate_zero.telemetry.legalization_evaluations_consumed == 1
    assert surrogate_zero.telemetry.surrogate_evaluations_consumed == 0
    assert surrogate.calls == []


def test_one_less_stage_budgets_stop_before_forbidden_work() -> None:
    layout = _layout()
    full = _run(layout).result
    proposal_limit = full.telemetry.proposals_consumed - 1
    proposal_short = _run(layout, budget=_budget(proposals=proposal_limit)).result
    assert proposal_short.telemetry.proposals_consumed == proposal_limit
    assert (
        proposal_short.telemetry.terminal_reason
        is PlacementCandidateTerminalReason.PROPOSAL_BUDGET_EXHAUSTED
    )

    legalization_limit = len(full.candidates) - 1
    legalization_short = _run(
        layout,
        budget=_budget(legalizations=legalization_limit),
    ).result
    assert legalization_short.telemetry.legalization_evaluations_consumed == legalization_limit
    assert (
        legalization_short.telemetry.terminal_reason
        is PlacementCandidateTerminalReason.LEGALIZATION_BUDGET_EXHAUSTED
    )

    surrogate_limit = full.telemetry.surrogate_evaluations_consumed - 1
    evaluator = _Surrogate()
    surrogate_short = _run(
        layout,
        budget=_budget(surrogates=surrogate_limit),
        surrogate=evaluator,
    ).result
    assert surrogate_short.telemetry.surrogate_evaluations_consumed == surrogate_limit
    assert len(evaluator.calls) == surrogate_limit
    assert (
        surrogate_short.telemetry.terminal_reason
        is PlacementCandidateTerminalReason.SURROGATE_BUDGET_EXHAUSTED
    )


def test_zero_and_early_proposal_budgets_never_enter_pair_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_pair_lookup(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("pair enumeration crossed the proposal budget")

    monkeypatch.setattr(placement_candidates, "_pair_clause_at", forbidden_pair_lookup)
    layout = _layout()
    zero = _run(layout, budget=_budget(proposals=0)).result
    early = _run(layout, budget=_budget(proposals=2)).result
    assert zero.telemetry.proposals_consumed == 0
    assert early.telemetry.proposals_consumed == 2
    assert (
        early.telemetry.terminal_reason
        is PlacementCandidateTerminalReason.PROPOSAL_BUDGET_EXHAUSTED
    )


def test_expected_context_changes_are_fingerprint_scoped_and_models_fail_closed() -> None:
    layout = _layout()
    base = _run(layout).result
    seeded = _run(layout, move_policy=_move_policy(seed=8)).result
    moved = _run(layout, move_policy=_move_policy(step=2.0)).result
    target = _run(layout, target_nets=("/A",)).result
    changed_layout = replace(layout, graphics=('(gr_text "changed" (layer "F.SilkS"))',))
    templated = _run(changed_layout).result
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(update={"profile_id": "fixture-profile"})
    profiled = _run(layout, profile=profile).result

    assert seeded.telemetry.template_fingerprint == base.telemetry.template_fingerprint
    assert seeded.telemetry.target_policy_fingerprint == base.telemetry.target_policy_fingerprint
    assert seeded.telemetry.catalog_fingerprint == base.telemetry.catalog_fingerprint
    assert seeded.telemetry.profile_fingerprint == base.telemetry.profile_fingerprint
    assert seeded.telemetry.move_policy_fingerprint != base.telemetry.move_policy_fingerprint
    assert _ids(seeded) != _ids(base)
    assert moved.telemetry.move_policy_fingerprint != base.telemetry.move_policy_fingerprint
    assert target.telemetry.target_policy_fingerprint != base.telemetry.target_policy_fingerprint
    assert target.telemetry.template_fingerprint == base.telemetry.template_fingerprint
    assert templated.telemetry.template_fingerprint != base.telemetry.template_fingerprint
    assert templated.telemetry.catalog_fingerprint != base.telemetry.catalog_fingerprint
    assert profiled.telemetry.profile_fingerprint != base.telemetry.profile_fingerprint
    assert profiled.telemetry.template_fingerprint == base.telemetry.template_fingerprint

    with pytest.raises(ValidationError, match="Extra inputs"):
        PlacementMovePolicy.model_validate(
            {**base.move_policy.model_dump(mode="json"), "future_permission": True}
        )
    forged = base.model_dump(mode="json")
    forged["telemetry"]["move_policy_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="move policy fingerprint is stale"):
        PlacementCandidateSearchResult.model_validate(forged)


def test_model_copy_forgery_and_false_provenance_fail_closed() -> None:
    base = _run(_layout()).result
    copied_telemetry = base.telemetry.model_copy(update={"proposals_consumed": 999})
    copied_result = base.model_copy(update={"telemetry": copied_telemetry})
    with pytest.raises(ValidationError, match="proposal budget exceeded"):
        PlacementCandidateSearchResult.model_validate_json(copied_result.model_dump_json())

    first = base.candidates[0]
    stale_telemetry = first.legalization_result.telemetry.model_copy(
        update={"catalog_fingerprint": "0" * 64}
    )
    stale_legalization = first.legalization_result.model_copy(update={"telemetry": stale_telemetry})
    stale_candidate = first.model_copy(update={"legalization_result": stale_legalization})
    copied_result = base.model_copy(update={"candidates": (stale_candidate, *base.candidates[1:])})
    with pytest.raises(ValidationError, match="catalog fingerprint is stale"):
        PlacementCandidateSearchResult.model_validate_json(copied_result.model_dump_json())

    later = base.candidates[1]
    false_provenance = later.provenance.model_copy(update={"parent_pose_fingerprint": "1" * 64})
    false_candidate = later.model_copy(update={"provenance": false_provenance})
    copied_result = base.model_copy(
        update={"candidates": (base.candidates[0], false_candidate, *base.candidates[2:])}
    )
    with pytest.raises(ValidationError, match="stale base parent"):
        PlacementCandidateSearchResult.model_validate_json(copied_result.model_dump_json())


def test_r5_3_adapter_consumes_only_the_fixed_r5_2_surrogate_budget() -> None:
    layout = _layout()
    preflight = _run(layout)
    terminal = PlacedTerminalCopper(
        terminal_id="U1:1",
        source_id="fixture:U1:1:F.Cu",
        component_reference="U1",
        net_name="/A",
        layer="F.Cu",
        center_mm=(5.0, 5.0),
        copper=_rect(4.9, 4.9, 5.1, 5.1),
    )
    typed_inputs = {
        probe.result.telemetry.pose_fingerprint: PlacementSurrogateInput(
            pose_fingerprint=probe.result.telemetry.pose_fingerprint,
            probe_layout_fingerprint=probe.result.telemetry.probe_layout_fingerprint,
            terminals=(terminal,),
        )
        for probe in preflight.probes
    }
    first_probe = preflight.probes[0]
    first_pose = first_probe.result.telemetry.pose_fingerprint
    with pytest.raises(ValueError, match="key must equal its pose fingerprint"):
        DeterministicPlacementSurrogateEvaluator({"0" * 64: typed_inputs[first_pose]})
    stale_source = replace(typed_inputs[first_pose], probe_layout_fingerprint="0" * 64)
    stale_evaluator = DeterministicPlacementSurrogateEvaluator({first_pose: stale_source})
    with pytest.raises(ValueError, match="stale for the probe layout"):
        stale_evaluator(first_probe, preflight.result.candidates[0].legalization_result)

    evaluator = DeterministicPlacementSurrogateEvaluator(typed_inputs)
    limited = _run(layout, budget=_budget(surrogates=2), surrogate=evaluator).result
    assert limited.telemetry.surrogate_evaluations_consumed == 2
    assert len(evaluator.results) == 2
    assert (
        limited.telemetry.terminal_reason
        is PlacementCandidateTerminalReason.SURROGATE_BUDGET_EXHAUSTED
    )
    evaluated = tuple(
        candidate
        for candidate in limited.candidates
        if candidate.disposition is PlacementCandidateDisposition.SURROGATE_EVALUATED
    )
    assert len(evaluated) == 2
    for candidate in evaluated:
        pose_fingerprint = candidate.legalization_result.telemetry.pose_fingerprint
        assert candidate.surrogate_evidence is not None
        assert (
            candidate.surrogate_evidence.evidence_fingerprint
            == evaluator.results[pose_fingerprint].semantic_fingerprint()
        )
