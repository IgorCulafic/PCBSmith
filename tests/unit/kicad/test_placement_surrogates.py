from __future__ import annotations

import pytest
from pydantic import ValidationError

import pcbsmith.kicad.clearance_domains as clearance_domains
import pcbsmith.kicad.placement_surrogates as surrogates
from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_ir import (
    CorridorBudget,
    CorridorCell,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPortal,
    CorridorTerminal,
)
from pcbsmith.corridor_summary import (
    VerifiedCorridorPlanSummary,
    verify_corridor_plan_summary,
)
from pcbsmith.kicad.placement_surrogates import evaluate_placement_surrogates as _evaluate
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.placement_surrogate_ir import (
    BusBoundaryOrderObservation,
    CallerClearanceGroup,
    EscapeObstacle,
    EscapeRay,
    PlacedTerminalCopper,
    PlacementCorridorEvidence,
    PlacementCorridorState,
    PortalOverloadEvidence,
    SketchIntersectionKind,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, OrdinaryClearanceRequirement


def _rect(cx: float, cy: float, h: float = 0.05) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(
                outer=((cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h))
            ),
        )
    )


DEFAULT_ESCAPE_RAY = EscapeRay(dx=1, dy=0)
POSE_FP = "1" * 64
PROBE_FP = "2" * 64


def _eval(terminals, **kwargs):
    return _evaluate(
        terminals,
        pose_fingerprint=POSE_FP,
        probe_layout_fingerprint=PROBE_FP,
        **kwargs,
    )


def _t(
    tid: str,
    net: str,
    x: float,
    y: float,
    *,
    ray: EscapeRay | None = DEFAULT_ESCAPE_RAY,
    layer: str = "F.Cu",
) -> PlacedTerminalCopper:
    return PlacedTerminalCopper(
        terminal_id=tid,
        source_id=f"src:{tid}:{layer}",
        component_reference=tid.split(":")[0],
        net_name=net,
        layer=layer,
        center_mm=(x, y),
        copper=_rect(x, y),
        escape_rays=() if ray is None else (ray,),
    )


def _profile(*req: OrdinaryClearanceRequirement):
    return DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"pairwise_clearances": req}
            )
        }
    )


def _verified(*, ready: bool, overflow: int = 0) -> VerifiedCorridorPlanSummary:
    graph = CorridorGraph(
        profile_fingerprint="a" * 64,
        layout_geometry_fingerprint="b" * 64,
        coarse_grid_mm=1.0,
        capacity_quantum_mm=1.0,
        cells=(
            CorridorCell(
                cell_id="left",
                layer="F.Cu",
                ix=0,
                iy=0,
                bounds_mm=(0.0, 0.0, 1.0, 1.0),
                terminal_owner_net_names=("A",),
            ),
            CorridorCell(
                cell_id="right",
                layer="F.Cu",
                ix=1,
                iy=0,
                bounds_mm=(1.0, 0.0, 2.0, 1.0),
                terminal_owner_net_names=("A",),
            ),
        ),
        portals=(
            CorridorPortal(
                resource_id="neck",
                layer="F.Cu",
                cell_low="left",
                cell_high="right",
                orientation="vertical_cut",
                guaranteed_span_units=1,
                possible_span_units=1,
                verification=CorridorGeometryVerification.EXACT,
            ),
        ),
    )
    demand = CorridorNetDemand(
        demand_id="demand:a",
        net_name="A",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        terminals=(
            CorridorTerminal(terminal_id="a:start", candidate_cell_ids=("left",)),
            CorridorTerminal(terminal_id="a:end", candidate_cell_ids=("right",)),
        ),
        ordinary_span_units=1 + overflow,
        effective_clearance_mm=0.1,
    )
    budget = (
        CorridorBudget(
            max_passes=1, max_expansions=0, max_expansions_per_demand=0, max_stagnant_passes=0
        )
        if not ready and overflow == 0
        else CorridorBudget(
            max_passes=2, max_expansions=20, max_expansions_per_demand=20, max_stagnant_passes=1
        )
    )
    plan = negotiate_corridor_allocations(graph, (demand,), budget=budget)
    verified = verify_corridor_plan_summary(graph, (demand,), plan)
    assert verified.summary.guidance_ready is ready
    assert verified.summary.channel_total_overflow_units == overflow
    return verified


def test_pairwise_terminal_margin_overrides_ordinary_minimum() -> None:
    req = OrdinaryClearanceRequirement(
        requirement_id="tight-ab", nets_a=("A",), nets_b=("B",), minimum_clearance_mm=0.5
    )
    result = _eval((_t("U1:1", "A", 0, 0), _t("U2:1", "B", 0.4, 0)), profile=_profile(req))
    item = result.clearance_evidence[0]
    assert item.distance_floor_um == 300 and item.required_clearance_um == 500
    assert item.exact_violation and result.terminal_clearance_violation_count == 1
    assert len(item.contributing_domain_ids) == 1 and "creepage" not in result.semantic_json()


def test_qualified_and_caller_clearance_arrive_once_and_never_creepage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        clearance_domains,
        "qualified_insulation_clearance_groups",
        lambda _p: (("qualified", ("A",), ("B",), 0.6, ()),),
    )
    real = clearance_domains.build_route_pairwise_clearance_domains
    calls = []

    def counted(profile, groups=()):
        calls.append(tuple(groups))
        return real(profile, groups)

    monkeypatch.setattr(surrogates, "build_route_pairwise_clearance_domains", counted)
    result = _eval(
        (_t("U1:1", "A", 0, 0), _t("U2:1", "B", 1, 0)),
        clearance_groups=(
            CallerClearanceGroup(nets_a=("A",), nets_b=("B",), minimum_clearance_mm=0.7),
        ),
    )
    assert len(calls) == 1 and len(result.clearance_domain_ids) == 2
    assert sum("qualified-insulation" in x for x in result.clearance_requirement_ids) == 1
    assert sum("caller-clearance" in x for x in result.clearance_requirement_ids) == 1
    assert "creepage" not in result.semantic_json()


def test_two_net_cross_fires_and_moved_terminal_removes_it_without_scalar_priority() -> None:
    crossed = (
        _t("A:1", "A", 0, 1),
        _t("A:2", "A", 2, 1),
        _t("B:1", "B", 1, 0),
        _t("B:2", "B", 1, 2),
    )
    moved = (_t("A:1", "A", 0, 0), _t("A:2", "A", 2, 0), _t("B:1", "B", 0, 1), _t("B:2", "B", 2, 1))
    first = _eval(crossed)
    second = _eval(moved)
    assert first.geometric_crossing_count == 1 and second.geometric_crossing_count == 0
    assert first.total_hpwl_um == second.total_hpwl_um == 4000
    assert "score" not in type(first).model_fields


def test_declared_bus_inversion_and_allowed_whole_reversal_are_distinct() -> None:
    base = dict(
        bus_id="data",
        boundary_id="neck",
        declared_member_ids=("D0", "D1", "D2"),
        observed_member_ids=("D2", "D1", "D0"),
    )
    conflict = _eval(
        (_t("U1:1", "A", 0, 0),), bus_observations=(BusBoundaryOrderObservation(**base),)
    )
    allowed = _eval(
        (_t("U1:1", "A", 0, 0),),
        bus_observations=(BusBoundaryOrderObservation(**base, allow_whole_bundle_reversal=True),),
    )
    assert conflict.declared_order_conflict_count == 1
    assert (
        allowed.declared_order_conflict_count == 0
        and allowed.bus_order_evidence[0].accepted_as == "whole_reversal"
    )


def test_shorter_hpwl_portal_overload_stays_separate_from_longer_zero_overflow() -> None:
    short = PlacementCorridorEvidence(
        state="unsupported",
        verified_summary=_verified(ready=False, overflow=2),
        portal_overloads=(
            PortalOverloadEvidence(
                resource_id="neck", overuse_units=2, contributing_demand_ids=("A",)
            ),
        ),
    )
    clear = PlacementCorridorEvidence(state="ready", verified_summary=_verified(ready=True))
    a = _eval((_t("A:1", "A", 0, 0), _t("A:2", "A", 1, 0)), corridor=short)
    b = _eval((_t("A:1", "A", 0, 0), _t("A:2", "A", 3, 0)), corridor=clear)
    assert a.total_hpwl_um < b.total_hpwl_um
    assert a.corridor.summary and a.corridor.summary.channel_total_overflow_units == 2
    assert b.corridor.summary and b.corridor.summary.channel_total_overflow_units == 0


def test_r3_absent_unsupported_and_zero_overflow_are_not_aliased() -> None:
    terms = (_t("U1:1", "A", 0, 0),)
    absent = _eval(terms)
    unsupported = _eval(
        terms,
        corridor=PlacementCorridorEvidence(
            state="unsupported", verified_summary=_verified(ready=False)
        ),
    )
    ready = _eval(
        terms,
        corridor=PlacementCorridorEvidence(state="ready", verified_summary=_verified(ready=True)),
    )
    assert (absent.corridor.state, unsupported.corridor.state, ready.corridor.state) == (
        PlacementCorridorState.ABSENT,
        PlacementCorridorState.UNSUPPORTED,
        PlacementCorridorState.READY,
    )


def test_bare_summary_is_rejected_for_ready_and_unsupported() -> None:
    ready = _verified(ready=True).summary
    unsupported = _verified(ready=False).summary
    with pytest.raises(ValidationError):
        PlacementCorridorEvidence(state="ready", summary=ready)
    with pytest.raises(ValidationError):
        PlacementCorridorEvidence(state="unsupported", summary=unsupported)


def test_blocked_first_transition_and_rotation_exposing_escape_fire() -> None:
    obstacle = EscapeObstacle(obstacle_id="U2", compound=_rect(0.3, 0, 0.15))
    blocked = _eval(
        (_t("U1:1", "A", 0, 0, ray=EscapeRay(dx=1, dy=0)),), escape_obstacles=(obstacle,)
    )
    open_result = _eval(
        (_t("U1:1", "A", 0, 0, ray=EscapeRay(dx=-1, dy=0)),), escape_obstacles=(obstacle,)
    )
    assert blocked.unescaped_terminal_count == 1 and blocked.pin_escape_evidence[
        0
    ].blocked_obstacle_ids == ("U2",)
    assert open_result.unescaped_terminal_count == 0


def test_off_grid_stub_is_diagnostic_but_not_unroutable() -> None:
    result = _eval((_t("U1:1", "A", 0.13, 0.13),))
    escape = result.pin_escape_evidence[0]
    assert escape.off_grid_diagnostic and escape.grid_residual_um > 0
    assert not escape.unescaped and result.unescaped_terminal_count == 0


def test_evidence_and_fingerprint_ignore_construction_order_and_are_pinned() -> None:
    terms = (_t("A:1", "A", 0, 1), _t("A:2", "A", 2, 1), _t("B:1", "B", 1, 0), _t("B:2", "B", 1, 2))
    first = _eval(terms)
    second = _eval(tuple(reversed(terms)))
    assert first == second and first.semantic_fingerprint() == second.semantic_fingerprint()
    assert (
        first.semantic_fingerprint()
        == "12ef040078dc9c44a2c9ec4f289bf24ff57fec4190ae85a78ea5d2bd0f5a2ca6"
    )
    with pytest.raises(ValidationError):
        PlacementCorridorEvidence(state="absent", verified_summary=_verified(ready=True))


def test_clearance_exemptions_and_duplicate_caller_groups_are_authoritative() -> None:
    requirement = OrdinaryClearanceRequirement(
        requirement_id="exempt-u1",
        nets_a=("A",),
        nets_b=("B",),
        minimum_clearance_mm=0.5,
        exempt_component_refs=("U1",),
    )
    terms = (_t("U1:1", "A", 0, 0), _t("U2:1", "B", 0.4, 0))
    result = _eval(terms, profile=_profile(requirement))
    item = result.clearance_evidence[0]
    assert item.contributing_domain_ids == ()
    assert (
        item.required_clearance_mm
        == DEFAULT_PCB_RULE_PROFILE.fab_spacing.minimum_copper_clearance_mm
    )
    group = CallerClearanceGroup(nets_a=("A",), nets_b=("B",), minimum_clearance_mm=0.7)
    with pytest.raises(ValueError, match="duplicate caller clearance"):
        _eval(terms, clearance_groups=(group, group))


def test_duplicate_authorities_and_whitespace_member_ids_are_rejected() -> None:
    terms = (_t("U1:1", "A", 0, 0),)
    observation = BusBoundaryOrderObservation(
        bus_id="data",
        boundary_id="neck",
        declared_member_ids=("D0", "D1"),
        observed_member_ids=("D0", "D1"),
    )
    with pytest.raises(ValueError, match="duplicate bus boundary"):
        _eval(terms, bus_observations=(observation, observation))
    front = EscapeObstacle(obstacle_id="keepout", layer="F.Cu", compound=_rect(1, 1))
    back = EscapeObstacle(obstacle_id="keepout", layer="B.Cu", compound=_rect(1, 1))
    with pytest.raises(ValueError, match="duplicate escape obstacles"):
        _eval(terms, escape_obstacles=(front, back))
    with pytest.raises(ValidationError):
        BusBoundaryOrderObservation(
            bus_id="data",
            boundary_id="neck",
            declared_member_ids=("D0", "D1"),
            observed_member_ids=("D0", "D1"),
            allowed_member_permutations=(("D0", " D1"),),
        )


def test_escape_obstacles_are_exact_filled_layer_scoped_compounds_with_holes() -> None:
    filled = ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((-0.1, -0.2), (1.0, -0.2), (1.0, 0.2), (-0.1, 0.2))),)
    )
    terms = (_t("U1:1", "A", 0, 0),)
    wrong_layer = _eval(
        terms,
        escape_obstacles=(EscapeObstacle(obstacle_id="back", layer="B.Cu", compound=filled),),
    )
    wholly_inside = _eval(
        terms,
        escape_obstacles=(EscapeObstacle(obstacle_id="front", layer="F.Cu", compound=filled),),
    )
    assert wrong_layer.unescaped_terminal_count == 0
    assert wholly_inside.unescaped_terminal_count == 1

    donut = ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(
                outer=((-0.1, -0.2), (1.0, -0.2), (1.0, 0.2), (-0.1, 0.2)),
                holes=(((0.2, -0.1), (0.9, -0.1), (0.9, 0.1), (0.2, 0.1)),),
            ),
        )
    )
    in_hole = _eval(
        (_t("U1:1", "A", 0.3, 0),),
        escape_obstacles=(EscapeObstacle(obstacle_id="donut", compound=donut),),
    )
    assert in_hole.unescaped_terminal_count == 0


def test_json_revalidation_rejects_model_copy_tampering() -> None:
    result = _eval((_t("U1:1", "A", 0, 0), _t("U2:1", "B", 0.4, 0)))
    stale_input = result.model_copy(update={"input_fingerprint": "0" * 64})
    with pytest.raises(ValidationError, match="input fingerprint is stale"):
        type(result).model_validate_json(stale_input.model_dump_json())

    clearance = result.clearance_evidence[0]
    stale_clearance = clearance.model_copy(
        update={"distance_floor_um": clearance.distance_floor_um + 1}
    )
    stale_result = result.model_copy(update={"clearance_evidence": (stale_clearance,)})
    with pytest.raises(ValidationError, match="distance floor is stale"):
        type(result).model_validate_json(stale_result.model_dump_json())

    crossing = _eval(
        (
            _t("A:1", "A", 0, 1),
            _t("A:2", "A", 2, 1),
            _t("B:1", "B", 1, 0),
            _t("B:2", "B", 1, 2),
        )
    )
    intersection = crossing.sketch_intersections[0].model_copy(
        update={"kind": SketchIntersectionKind.COLLINEAR_AMBIGUITY}
    )
    stale_crossing = crossing.model_copy(update={"sketch_intersections": (intersection,)})
    with pytest.raises(ValidationError, match="intersection kind is stale"):
        type(crossing).model_validate_json(stale_crossing.model_dump_json())


def test_escape_obstacle_self_exemption_is_explicit_not_inferred_from_id() -> None:
    filled = EscapeObstacle(obstacle_id="U1", compound=_rect(0.25, 0, 0.3))
    blocked = _eval((_t("U1:1", "A", 0, 0),), escape_obstacles=(filled,))
    exempt = _eval(
        (_t("U1:1", "A", 0, 0),),
        escape_obstacles=(
            EscapeObstacle(
                obstacle_id="U1",
                compound=_rect(0.25, 0, 0.3),
                exempt_component_refs=("U1",),
            ),
        ),
    )
    assert blocked.unescaped_terminal_count == 1
    assert exempt.unescaped_terminal_count == 0
