from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    CorridorGuidanceReport,
    build_corridor_route_guide,
)
from pcbsmith.corridor_ir import (
    CorridorAllocation,
    CorridorBudget,
    CorridorCell,
    CorridorFailureReason,
    CorridorGeometryIssue,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorPlanResult,
    CorridorPortal,
    CorridorResourceClaim,
    CorridorViaPortal,
)


def _digest(character: str) -> str:
    return character * 64


def _cell(
    cell_id: str,
    layer: str,
    ix: int,
    *,
    owner: str | None = None,
) -> CorridorCell:
    return CorridorCell(
        cell_id=cell_id,
        layer=layer,
        ix=ix,
        iy=0,
        bounds_mm=(float(ix), 0.0, float(ix + 1), 1.0),
        terminal_owner_net_names=() if owner is None else (owner,),
    )


def _portal(
    resource_id: str,
    cell_low: str,
    cell_high: str,
    *,
    verification: CorridorGeometryVerification = CorridorGeometryVerification.EXACT,
) -> CorridorPortal:
    return CorridorPortal(
        resource_id=resource_id,
        layer="F.Cu",
        cell_low=cell_low,
        cell_high=cell_high,
        orientation="vertical_cut",
        guaranteed_span_units=2,
        possible_span_units=2,
        verification=verification,
        maximum_error_mm=(
            0.01 if verification is CorridorGeometryVerification.BOUNDED_APPROXIMATION else None
        ),
    )


def _via(
    resource_id: str,
    front_cell_id: str,
    back_cell_id: str,
    *,
    verification: CorridorGeometryVerification = CorridorGeometryVerification.EXACT,
) -> CorridorViaPortal:
    return CorridorViaPortal(
        resource_id=resource_id,
        front_cell_id=front_cell_id,
        back_cell_id=back_cell_id,
        guaranteed_site_count=1,
        possible_site_count=1,
        candidate_sites_mm=((0.5, 0.5),),
        verification=verification,
        maximum_error_mm=(
            0.01 if verification is CorridorGeometryVerification.BOUNDED_APPROXIMATION else None
        ),
    )


def _graph(
    *,
    reverse: bool = False,
    geometry_complete: bool = True,
    portal_verification: CorridorGeometryVerification = CorridorGeometryVerification.EXACT,
    via_verification: CorridorGeometryVerification = CorridorGeometryVerification.EXACT,
    bounded_issue: bool = False,
) -> CorridorGraph:
    cells = (
        _cell("a-front-terminal", "F.Cu", 0, owner="/A"),
        _cell("a-front-via", "F.Cu", 1),
        _cell("a-back-terminal", "B.Cu", 1, owner="/A"),
        _cell("z-front-terminal", "F.Cu", 3, owner="/Z"),
        _cell("z-front-via", "F.Cu", 4),
        _cell("z-back-terminal", "B.Cu", 4, owner="/Z"),
    )
    portals = (
        _portal(
            "portal:a",
            "a-front-terminal",
            "a-front-via",
            verification=portal_verification,
        ),
        _portal(
            "portal:z",
            "z-front-terminal",
            "z-front-via",
            verification=portal_verification,
        ),
    )
    via_portals = (
        _via(
            "via:a",
            "a-front-via",
            "a-back-terminal",
            verification=via_verification,
        ),
        _via(
            "via:z",
            "z-front-via",
            "z-back-terminal",
            verification=via_verification,
        ),
    )
    issues: tuple[CorridorGeometryIssue, ...] = ()
    if bounded_issue:
        issues = (
            CorridorGeometryIssue(
                source_id="bounded-outline-envelope",
                layer="F.Cu",
                verification=CorridorGeometryVerification.BOUNDED_APPROXIMATION,
                maximum_error_mm=0.01,
                reason="test-only approximation",
                affected_cell_ids=("a-front-terminal",),
            ),
        )
    if reverse:
        cells = tuple(reversed(cells))
        portals = tuple(reversed(portals))
        via_portals = tuple(reversed(via_portals))
        issues = tuple(reversed(issues))
    return CorridorGraph(
        profile_fingerprint=_digest("1"),
        layout_geometry_fingerprint=_digest("2"),
        coarse_grid_mm=1.0,
        capacity_quantum_mm=0.01,
        geometry_complete=geometry_complete,
        cells=cells,
        portals=portals,
        via_portals=via_portals,
        issues=issues,
    )


def _claim(resource_id: str, resource_kind: str) -> CorridorResourceClaim:
    return CorridorResourceClaim(
        resource_id=resource_id,
        resource_kind=resource_kind,
        demand_units=1,
    )


def _allocations(*, reverse: bool = False) -> tuple[CorridorAllocation, ...]:
    allocations = (
        CorridorAllocation(
            demand_id="demand-a",
            net_name="/A",
            cell_ids=("a-front-via", "a-back-terminal", "a-front-terminal"),
            portal_claims=(_claim("portal:a", "channel"),),
            via_claims=(_claim("via:a", "via_site"),),
            base_cost_units=10,
            congestion_cost_units=0,
        ),
        CorridorAllocation(
            demand_id="demand-z",
            net_name="/Z",
            cell_ids=("z-front-via", "z-back-terminal", "z-front-terminal"),
            portal_claims=(_claim("portal:z", "channel"),),
            via_claims=(_claim("via:z", "via_site"),),
            base_cost_units=20,
            congestion_cost_units=0,
        ),
    )
    return tuple(reversed(allocations)) if reverse else allocations


def _ready_plan(
    graph: CorridorGraph,
    allocations: tuple[CorridorAllocation, ...] | None = None,
    *,
    graph_fingerprint: str | None = None,
) -> CorridorPlanResult:
    selected = _allocations() if allocations is None else allocations
    baseline = tuple(sorted(allocation.demand_id for allocation in selected))
    return CorridorPlanResult(
        guidance_ready=True,
        graph_fingerprint=(
            graph.semantic_fingerprint() if graph_fingerprint is None else graph_fingerprint
        ),
        demand_fingerprint=_digest("3"),
        cost_policy_fingerprint=_digest("4"),
        baseline_demand_order=baseline,
        allocations=selected,
        budget=CorridorBudget(
            max_passes=0,
            max_expansions=0,
            max_expansions_per_demand=0,
            max_stagnant_passes=0,
        ),
    )


def _failed_plan(graph: CorridorGraph) -> CorridorPlanResult:
    return CorridorPlanResult(
        guidance_ready=False,
        failure_reason=CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
        graph_fingerprint=graph.semantic_fingerprint(),
        demand_fingerprint=_digest("3"),
        cost_policy_fingerprint=_digest("4"),
        baseline_demand_order=("demand-a",),
        unresolved_demand_ids=("demand-a",),
        budget=CorridorBudget(
            max_passes=0,
            max_expansions=0,
            max_expansions_per_demand=0,
            max_stagnant_passes=0,
        ),
    )


def test_route_guide_is_canonical_and_stable_under_reordered_construction() -> None:
    graph = _graph()
    reordered_graph = _graph(reverse=True)
    plan = _ready_plan(graph)
    reordered_plan = _ready_plan(reordered_graph, _allocations(reverse=True))

    guide = build_corridor_route_guide(
        graph,
        plan,
        off_corridor_penalty_units=17,
    )
    reordered_guide = build_corridor_route_guide(
        reordered_graph,
        reordered_plan,
        off_corridor_penalty_units=17,
    )

    assert graph.semantic_fingerprint() == reordered_graph.semantic_fingerprint()
    assert plan.semantic_fingerprint() == reordered_plan.semantic_fingerprint()
    assert guide is not None
    assert reordered_guide is not None
    assert guide == reordered_guide
    assert guide.semantic_json() == reordered_guide.semantic_json()
    assert guide.semantic_fingerprint() == reordered_guide.semantic_fingerprint()
    assert (
        guide.semantic_fingerprint()
        == "1d2017661b83ee9a89408a16c5554264414ae3e21f6575e68b2b9e2c37d2ce08"
    )
    assert guide.net_guides[0].net_name == "/A"
    assert guide.net_guides[0].preferred_cell_ids == (
        "a-back-terminal",
        "a-front-terminal",
        "a-front-via",
    )
    assert guide.net_guides[0].preferred_portal_ids == ("portal:a",)
    assert guide.net_guides[0].preferred_via_resource_ids == ("via:a",)
    assert guide.net_guides[0].terminal_cell_ids == (
        "a-back-terminal",
        "a-front-terminal",
    )
    assert guide.net_guides[1].net_name == "/Z"
    assert guide.net_guides[1].preferred_portal_ids == ("portal:z",)
    assert guide.net_guides[1].preferred_via_resource_ids == ("via:z",)
    assert guide.net_guides[1].terminal_cell_ids == (
        "z-back-terminal",
        "z-front-terminal",
    )


def test_non_ready_or_graph_mismatched_plan_softly_declines_guidance() -> None:
    graph = _graph()

    assert (
        build_corridor_route_guide(
            graph,
            _failed_plan(graph),
            off_corridor_penalty_units=1,
        )
        is None
    )
    assert (
        build_corridor_route_guide(
            graph,
            _ready_plan(graph, graph_fingerprint=_digest("f")),
            off_corridor_penalty_units=1,
        )
        is None
    )


@pytest.mark.parametrize(
    "graph_factory",
    (
        lambda: _graph(geometry_complete=False),
        lambda: _graph(portal_verification=CorridorGeometryVerification.BOUNDED_APPROXIMATION),
        lambda: _graph(via_verification=CorridorGeometryVerification.BOUNDED_APPROXIMATION),
        lambda: _graph(bounded_issue=True),
    ),
)
def test_only_complete_exact_graphs_can_produce_guidance(
    graph_factory: Callable[[], CorridorGraph],
) -> None:
    graph = graph_factory()

    assert (
        build_corridor_route_guide(
            graph,
            _ready_plan(graph),
            off_corridor_penalty_units=1,
        )
        is None
    )


@pytest.mark.parametrize(
    ("allocation", "message"),
    (
        (
            CorridorAllocation(
                demand_id="bad-cell",
                net_name="/BAD",
                cell_ids=("missing-cell",),
                base_cost_units=0,
                congestion_cost_units=0,
            ),
            "unknown or empty cells",
        ),
        (
            CorridorAllocation(
                demand_id="bad-resource",
                net_name="/BAD",
                cell_ids=("a-front-terminal",),
                portal_claims=(_claim("missing-portal", "channel"),),
                base_cost_units=0,
                congestion_cost_units=0,
            ),
            "unknown resource",
        ),
        (
            CorridorAllocation(
                demand_id="bad-portal-endpoint",
                net_name="/BAD",
                cell_ids=("a-front-terminal",),
                portal_claims=(_claim("portal:a", "channel"),),
                base_cost_units=0,
                congestion_cost_units=0,
            ),
            "portal endpoints",
        ),
        (
            CorridorAllocation(
                demand_id="bad-via-endpoint",
                net_name="/BAD",
                cell_ids=("a-front-via",),
                via_claims=(_claim("via:a", "via_site"),),
                base_cost_units=0,
                congestion_cost_units=0,
            ),
            "via endpoints",
        ),
    ),
)
def test_unknown_or_endpoint_incoherent_allocation_is_rejected(
    allocation: CorridorAllocation,
    message: str,
) -> None:
    graph = _graph()
    plan = _ready_plan(graph, (allocation,))

    with pytest.raises(ValueError, match=message):
        build_corridor_route_guide(
            graph,
            plan,
            off_corridor_penalty_units=1,
        )


@pytest.mark.parametrize("penalty", (-1, 1.5, True))
def test_guidance_penalty_requires_a_non_negative_strict_integer(
    penalty: object,
) -> None:
    graph = _graph()

    with pytest.raises(ValueError, match="non-negative integer"):
        build_corridor_route_guide(
            graph,
            _ready_plan(graph),
            off_corridor_penalty_units=penalty,  # type: ignore[arg-type]
        )


def test_guidance_report_accepts_and_canonicalizes_each_disposition() -> None:
    absent = CorridorGuidanceReport(
        disposition=CorridorGuidanceDisposition.ABSENT,
        unguided_net_names=("/Z", "/A", "/Z"),
        routing_run_fingerprint=_digest("a"),
        exact_check_fingerprint=_digest("b"),
    )
    applied = CorridorGuidanceReport(
        disposition=CorridorGuidanceDisposition.APPLIED,
        plan_fingerprint=_digest("c"),
        graph_fingerprint=_digest("d"),
        guide_fingerprint=_digest("e"),
        guided_net_names=("/Z", "/A", "/Z"),
        unguided_net_names=("/U",),
        routing_run_fingerprint=_digest("f"),
        exact_check_fingerprint=_digest("0"),
    )
    not_ready = CorridorGuidanceReport(
        disposition=CorridorGuidanceDisposition.PLAN_NOT_READY,
        plan_fingerprint=_digest("1"),
        graph_fingerprint=_digest("2"),
        plan_failure_reason=CorridorFailureReason.STAGNATION,
        unguided_net_names=("/A",),
        routing_run_fingerprint=_digest("3"),
    )
    incompatible = CorridorGuidanceReport(
        disposition=CorridorGuidanceDisposition.INCOMPATIBLE,
        plan_fingerprint=_digest("4"),
        graph_fingerprint=_digest("5"),
        unguided_net_names=("/A",),
        routing_run_fingerprint=_digest("6"),
    )

    assert absent.unguided_net_names == ("/A", "/Z")
    assert applied.guided_net_names == ("/A", "/Z")
    assert applied.unguided_net_names == ("/U",)
    assert not_ready.plan_failure_reason is CorridorFailureReason.STAGNATION
    assert incompatible.disposition is CorridorGuidanceDisposition.INCOMPATIBLE
    assert (
        len(
            {
                absent.semantic_fingerprint(),
                applied.semantic_fingerprint(),
                not_ready.semantic_fingerprint(),
                incompatible.semantic_fingerprint(),
            }
        )
        == 4
    )


@pytest.mark.parametrize(
    "payload",
    (
        {
            "disposition": CorridorGuidanceDisposition.APPLIED,
            "guided_net_names": ("/A",),
            "routing_run_fingerprint": _digest("0"),
        },
        {
            "disposition": CorridorGuidanceDisposition.APPLIED,
            "guide_fingerprint": _digest("1"),
            "guided_net_names": ("/A",),
            "plan_failure_reason": CorridorFailureReason.STAGNATION,
            "routing_run_fingerprint": _digest("0"),
        },
        {
            "disposition": CorridorGuidanceDisposition.ABSENT,
            "plan_fingerprint": _digest("1"),
            "routing_run_fingerprint": _digest("0"),
        },
        {
            "disposition": CorridorGuidanceDisposition.PLAN_NOT_READY,
            "plan_fingerprint": _digest("1"),
            "routing_run_fingerprint": _digest("0"),
        },
        {
            "disposition": CorridorGuidanceDisposition.INCOMPATIBLE,
            "plan_fingerprint": _digest("1"),
            "routing_run_fingerprint": _digest("0"),
        },
        {
            "disposition": CorridorGuidanceDisposition.INCOMPATIBLE,
            "plan_fingerprint": _digest("1"),
            "graph_fingerprint": _digest("2"),
            "guided_net_names": ("/A",),
            "routing_run_fingerprint": _digest("0"),
        },
        {
            "disposition": CorridorGuidanceDisposition.APPLIED,
            "guide_fingerprint": _digest("1"),
            "guided_net_names": ("/A",),
            "unguided_net_names": ("/A",),
            "routing_run_fingerprint": _digest("0"),
        },
    ),
)
def test_guidance_report_rejects_incoherent_disposition_state(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CorridorGuidanceReport(**payload)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    (
        "plan_fingerprint",
        "graph_fingerprint",
        "guide_fingerprint",
        "routing_run_fingerprint",
        "exact_check_fingerprint",
    ),
)
def test_guidance_report_rejects_noncanonical_fingerprints(field_name: str) -> None:
    payload: dict[str, object] = {
        "disposition": CorridorGuidanceDisposition.APPLIED,
        "plan_fingerprint": _digest("1"),
        "graph_fingerprint": _digest("2"),
        "guide_fingerprint": _digest("3"),
        "guided_net_names": ("/A",),
        "routing_run_fingerprint": _digest("4"),
        "exact_check_fingerprint": _digest("5"),
    }
    payload[field_name] = "A" * 64

    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        CorridorGuidanceReport(**payload)  # type: ignore[arg-type]
