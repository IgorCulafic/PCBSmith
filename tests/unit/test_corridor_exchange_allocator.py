from __future__ import annotations

from collections.abc import Mapping

import pytest

from pcbsmith import corridor_allocator as allocator_module
from pcbsmith.corridor_exchange import CorridorEscapeAlternative, CorridorExchangeDemand
from pcbsmith.corridor_exchange_allocator import negotiate_corridor_exchange_allocations
from pcbsmith.corridor_ir import (
    CorridorBudget,
    CorridorCapacityLedger,
    CorridorCell,
    CorridorCostPolicy,
    CorridorFailureReason,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorNetDemand,
    CorridorPortal,
    CorridorResourceClaim,
    CorridorTerminal,
    CorridorViaPolicy,
    CorridorViaPortal,
)


def _cell(cell_id: str, ix: int, *, layer: str = "F.Cu", owner: str = "") -> CorridorCell:
    return CorridorCell(
        cell_id=cell_id,
        layer=layer,
        ix=ix,
        iy=0,
        bounds_mm=(ix, 0, ix + 1, 1),
        terminal_owner_net_names=((owner,) if owner else ()),
    )


def _portal(
    resource_id: str,
    low: str,
    high: str,
    *,
    capacity: int = 4,
    layer: str = "F.Cu",
) -> CorridorPortal:
    return CorridorPortal(
        resource_id=resource_id,
        layer=layer,
        cell_low=low,
        cell_high=high,
        orientation="vertical_cut",
        guaranteed_span_units=capacity,
        possible_span_units=capacity,
        verification=CorridorGeometryVerification.EXACT,
    )


def _claim(resource_id: str, *, kind: str = "channel", units: int = 1) -> CorridorResourceClaim:
    return CorridorResourceClaim(
        resource_id=resource_id,
        resource_kind=kind,
        demand_units=units,
    )


def _demand(
    demand_id: str = "signal",
    net_name: str = "SIGNAL",
    *,
    via_policy: CorridorViaPolicy = CorridorViaPolicy.ALLOWED,
) -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=demand_id,
        net_name=net_name,
        width_mm=0.2,
        allowed_layers=("F.Cu", "B.Cu"),
        via_policy=via_policy,
        terminals=(
            CorridorTerminal(terminal_id="fine", candidate_cell_ids=("fine",)),
            CorridorTerminal(terminal_id="ordinary", candidate_cell_ids=("ordinary",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )


def _alternative(
    alternative_id: str = "short",
    *,
    exchange_portal_id: str = "exchange",
    entry_cell_id: str = "entry",
    prefix_cell_ids: tuple[str, ...] = ("fine", "entry"),
    prefix_claims: tuple[CorridorResourceClaim, ...] | None = None,
    prefix_cost: int = 1,
) -> CorridorEscapeAlternative:
    return CorridorEscapeAlternative(
        alternative_id=alternative_id,
        demand_id="signal",
        net_name="SIGNAL",
        fine_terminal_ids=("fine",),
        exchange_portal_id=exchange_portal_id,
        area_entry_cell_id=entry_cell_id,
        exit_layer="F.Cu",
        prefix_cell_ids=prefix_cell_ids,
        prefix_claims=prefix_claims or (_claim(exchange_portal_id),),
        prefix_base_cost_units=prefix_cost,
        detailed_prefix_resource_ids=(f"fine:{alternative_id}",),
        detailed_prefix_fingerprint=("a" if alternative_id == "short" else "b") * 64,
    )


def _simple_graph() -> CorridorGraph:
    return CorridorGraph(
        profile_fingerprint="1" * 64,
        layout_geometry_fingerprint="2" * 64,
        coarse_grid_mm=1,
        capacity_quantum_mm=1,
        cells=(
            _cell("fine", 0, owner="SIGNAL"),
            _cell("entry", 1),
            _cell("ordinary", 2, owner="SIGNAL"),
        ),
        portals=(
            _portal("exchange", "fine", "entry"),
            _portal("area", "entry", "ordinary"),
        ),
    )


def _exchange(*alternatives: CorridorEscapeAlternative) -> CorridorExchangeDemand:
    return CorridorExchangeDemand(
        demand=_demand(),
        alternatives=alternatives or (_alternative(),),
    )


def test_one_alternative_unions_prefix_and_area_into_one_net_owned_claim() -> None:
    alternative = _alternative(prefix_claims=(_claim("exchange", units=2),))
    graph = _simple_graph()
    graph = CorridorGraph.model_validate(
        {
            **graph.model_dump(),
            "portals": tuple(
                item.model_copy(update={"guaranteed_span_units": 2, "possible_span_units": 2})
                if item.resource_id == "exchange"
                else item
                for item in graph.portals
            ),
        }
    )
    result = negotiate_corridor_exchange_allocations(graph, (_exchange(alternative),))

    assert result.plan.guidance_ready
    assert len(result.exchange_allocations) == 1
    bound = result.exchange_allocations[0]
    assert bound.selection.alternative.alternative_id == "short"
    assert bound.allocation.demand_id == "signal"
    assert bound.allocation.net_name == "SIGNAL"
    assert bound.allocation.cell_ids == ("entry", "fine", "ordinary")
    assert tuple(item.resource_id for item in bound.allocation.portal_claims) == (
        "area",
        "exchange",
    )
    assert bound.allocation.base_cost_units == 1001
    assert bound.allocation.congestion_cost_units == 0
    assert (
        next(
            item.demand_units
            for item in bound.allocation.portal_claims
            if item.resource_id == "exchange"
        )
        == 2
    )
    assert result.plan.resource_overuse == ()
    assert bound.allocation == result.plan.allocations[0]


def _convergence_graph() -> CorridorGraph:
    return CorridorGraph(
        profile_fingerprint="3" * 64,
        layout_geometry_fingerprint="4" * 64,
        coarse_grid_mm=1,
        capacity_quantum_mm=1,
        cells=(
            _cell("fine", 0),
            _cell("short-entry", 1),
            _cell("long-mid", 2),
            _cell("long-entry", 3),
            _cell("ordinary", 4, owner="SIGNAL"),
        ),
        portals=(
            _portal("p", "fine", "short-entry", capacity=1),
            _portal("short-area", "short-entry", "ordinary", capacity=10),
            _portal("long-1", "fine", "long-mid", capacity=10),
            _portal("long-exchange", "long-mid", "long-entry", capacity=10),
            _portal("long-area", "long-entry", "ordinary", capacity=10),
        ),
    )


def _convergence_exchange(*, frozen: bool = False) -> CorridorExchangeDemand:
    short = _alternative(
        "short",
        exchange_portal_id="p",
        entry_cell_id="short-entry",
        prefix_cell_ids=("fine", "short-entry"),
        prefix_cost=1,
    )
    long = _alternative(
        "long",
        exchange_portal_id="long-exchange",
        entry_cell_id="long-entry",
        prefix_cell_ids=("fine", "long-mid", "long-entry"),
        prefix_claims=(_claim("long-1"), _claim("long-exchange")),
        prefix_cost=5,
    )
    return _exchange(short) if frozen else _exchange(short, long)


def _blocker_demand() -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id="blocker",
        net_name="BLOCKER",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id="blocker-a", candidate_cell_ids=("fine",)),
            CorridorTerminal(
                terminal_id="blocker-b",
                candidate_cell_ids=("short-entry",),
            ),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )


_CONVERGENCE_POLICY = CorridorCostPolicy(
    channel_step_cost_units=1,
    via_step_cost_units=5,
    present_factor_units=1,
    present_growth_numerator=2,
    present_growth_denominator=1,
    history_increment_units=4,
)
_CONVERGENCE_BUDGET = CorridorBudget(
    max_passes=4,
    max_expansions=100,
    max_expansions_per_demand=50,
    max_stagnant_passes=3,
)


def test_history_rips_short_prefix_and_selects_longer_zero_overuse_exit() -> None:
    result = negotiate_corridor_exchange_allocations(
        _convergence_graph(),
        (_convergence_exchange(),),
        ordinary_demands=(_blocker_demand(),),
        demand_order=("signal", "blocker"),
        budget=_CONVERGENCE_BUDGET,
        cost_policy=_CONVERGENCE_POLICY,
    )

    assert result.plan.guidance_ready
    assert len(result.plan.passes) == 2
    assert tuple(item.objective for item in result.plan.passes) == (
        (0, 1, 1, 1),
        (0, 0, 0, 0),
    )
    assert tuple(item.expansion_count for item in result.plan.passes) == (8, 8)
    assert tuple(
        tuple((item.demand_id, item.expansion_count) for item in pass_.demand_attempts)
        for pass_ in result.plan.passes
    ) == (
        (("signal", 4), ("blocker", 4)),
        (("signal", 4), ("blocker", 4)),
    )
    assert tuple(
        tuple((item.resource_id, item.overuse_units) for item in pass_.resource_overuse)
        for pass_ in result.plan.passes
    ) == ((("p", 1),), ())
    bound = result.exchange_allocations[0]
    assert bound.selection.alternative.alternative_id == "long"
    assert tuple(item.resource_id for item in bound.allocation.portal_claims) == (
        "long-1",
        "long-area",
        "long-exchange",
    )
    assert tuple(item.resource_id for item in result.plan.allocations[0].portal_claims) == ("p",)
    assert result.plan.allocations[0].demand_id == "blocker"
    assert tuple(item.semantic_fingerprint() for item in result.plan.passes) == (
        "438d2942596392c63ee5c025c61fb2ac0303e2e40dbe0b8f328eef974d5b6049",
        "2a8f56304e54908f36c78b642fe21a52d78a6678e3fb17df981c49944b77d474",
    )
    assert (
        result.semantic_fingerprint()
        == "fc6162c17f5ed9be569e2e36f4d642e62c41f6a12dc7c3e32fbf1eedc1cba499"
    )


def test_frozen_short_prefix_reproduces_deterministic_overflow_control() -> None:
    result = negotiate_corridor_exchange_allocations(
        _convergence_graph(),
        (_convergence_exchange(frozen=True),),
        ordinary_demands=(_blocker_demand(),),
        demand_order=("signal", "blocker"),
        budget=_CONVERGENCE_BUDGET.model_copy(update={"max_passes": 1}),
        cost_policy=_CONVERGENCE_POLICY,
    )

    assert not result.plan.guidance_ready
    assert result.plan.failure_reason is CorridorFailureReason.PASS_BUDGET
    assert tuple(
        (item.resource_id, item.overuse_units) for item in result.plan.resource_overuse
    ) == (("p", 1),)
    assert result.exchange_allocations[0].selection.alternative.alternative_id == "short"


def _via_graph() -> CorridorGraph:
    return CorridorGraph(
        profile_fingerprint="5" * 64,
        layout_geometry_fingerprint="6" * 64,
        coarse_grid_mm=1,
        capacity_quantum_mm=1,
        cells=(
            _cell("fine", 0, owner="SIGNAL"),
            _cell("back-prefix", 0, layer="B.Cu", owner="SIGNAL"),
            _cell("back-entry", 1, layer="B.Cu"),
            _cell("ordinary", 2, layer="B.Cu", owner="SIGNAL"),
        ),
        portals=(
            _portal("back-exchange", "back-prefix", "back-entry", layer="B.Cu"),
            _portal("back-area", "back-entry", "ordinary", layer="B.Cu"),
        ),
        via_portals=(
            CorridorViaPortal(
                resource_id="prefix-via",
                front_cell_id="fine",
                back_cell_id="back-prefix",
                guaranteed_site_count=1,
                possible_site_count=1,
                candidate_sites_mm=((0.5, 0.5),),
                verification=CorridorGeometryVerification.EXACT,
            ),
        ),
    )


def _via_exchange(via_policy: CorridorViaPolicy) -> CorridorExchangeDemand:
    demand = _demand(via_policy=via_policy).model_copy(
        update={
            "terminals": (
                CorridorTerminal(terminal_id="fine", candidate_cell_ids=("fine",)),
                CorridorTerminal(terminal_id="ordinary", candidate_cell_ids=("ordinary",)),
            )
        }
    )
    alternative = _alternative(
        exchange_portal_id="back-exchange",
        entry_cell_id="back-entry",
        prefix_cell_ids=("fine", "back-prefix", "back-entry"),
        prefix_claims=(
            _claim("prefix-via", kind="via_site"),
            _claim("back-exchange"),
        ),
    ).model_copy(update={"exit_layer": "B.Cu"})
    return CorridorExchangeDemand(demand=demand, alternatives=(alternative,))


def test_prefix_via_satisfies_required_policy_and_is_charged_once() -> None:
    result = negotiate_corridor_exchange_allocations(
        _via_graph(),
        (_via_exchange(CorridorViaPolicy.REQUIRED),),
    )

    assert result.plan.guidance_ready
    allocation = result.exchange_allocations[0].allocation
    assert tuple(item.resource_id for item in allocation.via_claims) == ("prefix-via",)
    assert allocation.via_claims[0].demand_units == 1
    assert tuple(item.resource_id for item in allocation.portal_claims) == (
        "back-area",
        "back-exchange",
    )


def test_via_forbidden_prefix_is_rejected_before_negotiation() -> None:
    with pytest.raises(ValueError, match="via-forbidden demand cannot use a prefix via"):
        negotiate_corridor_exchange_allocations(
            _via_graph(),
            (_via_exchange(CorridorViaPolicy.FORBIDDEN),),
        )

    invalid_quantity = _via_exchange(CorridorViaPolicy.ALLOWED)
    alternative = invalid_quantity.alternatives[0]
    claims = tuple(
        item.model_copy(update={"demand_units": 2}) if item.resource_id == "prefix-via" else item
        for item in alternative.prefix_claims
    )
    invalid_quantity = CorridorExchangeDemand(
        demand=invalid_quantity.demand,
        alternatives=(alternative.model_copy(update={"prefix_claims": claims}),),
    )
    with pytest.raises(ValueError, match="via claim must consume exactly one site"):
        negotiate_corridor_exchange_allocations(_via_graph(), (invalid_quantity,))


@pytest.mark.parametrize(
    ("alternative", "message"),
    (
        (
            _alternative(
                exchange_portal_id="unknown",
                prefix_claims=(_claim("unknown"),),
            ),
            "unknown resource",
        ),
        (
            _alternative(
                prefix_cell_ids=("fine", "entry", "ordinary"),
                prefix_claims=(_claim("exchange"),),
            ),
            "connected acyclic tree",
        ),
        (
            _alternative(prefix_cell_ids=("entry", "ordinary")),
            "claim endpoints must be prefix cells",
        ),
        (
            _alternative(
                exchange_portal_id="area",
                prefix_cell_ids=("entry", "ordinary"),
                prefix_claims=(_claim("area"),),
            ),
            "does not cover every fine terminal",
        ),
        (
            _alternative(
                prefix_cell_ids=("fine", "entry", "ordinary"),
                prefix_claims=(
                    _claim("exchange"),
                    _claim("area", kind="via_site"),
                ),
            ),
            "claim kind does not match graph resource",
        ),
    ),
)
def test_graph_invalid_alternatives_are_rejected_before_allocator_state(
    alternative: CorridorEscapeAlternative,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        negotiate_corridor_exchange_allocations(_simple_graph(), (_exchange(alternative),))


def test_graph_validation_uses_exact_allocator_terminal_ownership_rule() -> None:
    graph = _simple_graph()
    cells = tuple(
        item.model_copy(update={"terminal_owner_net_names": ("SIGNAL", "OTHER")})
        if item.cell_id == "fine"
        else item
        for item in graph.cells
    )
    graph = CorridorGraph.model_validate({**graph.model_dump(), "cells": cells})

    with pytest.raises(ValueError, match="layer or terminal ownership"):
        negotiate_corridor_exchange_allocations(graph, (_exchange(),))


def test_failed_replacement_restores_combined_prefix_and_area_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_search = allocator_module._search_complete_tree
    calls = 0

    def fail_replacement_searches(
        demand: CorridorNetDemand,
        graph: allocator_module._GraphIndex,
        ledger: CorridorCapacityLedger,
        history: Mapping[str, int],
        present_factor: int,
        expansion_limit: int,
    ) -> allocator_module._SearchOutcome:
        nonlocal calls
        calls += 1
        if calls > 3:
            raise allocator_module._SearchFailure(
                CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
                0,
            )
        return real_search(
            demand,
            graph,
            ledger,
            history,
            present_factor,
            expansion_limit,
        )

    monkeypatch.setattr(
        allocator_module,
        "_search_complete_tree",
        fail_replacement_searches,
    )
    result = negotiate_corridor_exchange_allocations(
        _convergence_graph(),
        (_convergence_exchange(),),
        ordinary_demands=(_blocker_demand(),),
        demand_order=("signal", "blocker"),
        budget=_CONVERGENCE_BUDGET,
        cost_policy=_CONVERGENCE_POLICY,
    )

    assert result.plan.failure_reason is CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT
    assert result.exchange_allocations[0].selection.alternative.alternative_id == "short"
    assert tuple(
        item.resource_id for item in result.exchange_allocations[0].allocation.portal_claims
    ) == ("p", "short-area")
    assert (
        result.plan.passes[1].allocation_fingerprint == result.plan.passes[0].allocation_fingerprint
    )
    assert result.plan.passes[1].ledger_fingerprint == result.plan.passes[0].ledger_fingerprint


def test_ordinary_demand_remains_supported_and_separate_same_net_is_rejected() -> None:
    base_graph = _simple_graph()
    graph = CorridorGraph.model_validate(
        {
            **base_graph.model_dump(),
            "cells": (*base_graph.cells, _cell("extra-a", 10), _cell("extra-b", 11)),
            "portals": (*base_graph.portals, _portal("extra-edge", "extra-a", "extra-b")),
        }
    )
    ordinary = CorridorNetDemand(
        demand_id="ordinary-extra",
        net_name="EXTRA",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id="extra-a", candidate_cell_ids=("extra-a",)),
            CorridorTerminal(terminal_id="extra-b", candidate_cell_ids=("extra-b",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )
    result = negotiate_corridor_exchange_allocations(
        graph,
        (_exchange(),),
        ordinary_demands=(ordinary,),
    )
    assert result.plan.guidance_ready
    assert {item.demand_id for item in result.plan.allocations} == {
        "ordinary-extra",
        "signal",
    }
    assert {item.allocation.demand_id for item in result.exchange_allocations} == {"signal"}

    same_net = ordinary.model_copy(update={"net_name": "SIGNAL"})
    with pytest.raises(ValueError, match="at most one demand per net"):
        negotiate_corridor_exchange_allocations(
            graph,
            (_exchange(),),
            ordinary_demands=(same_net,),
        )


def test_ordinary_only_wrapper_is_exactly_the_default_allocator_plan() -> None:
    graph = _simple_graph()
    ordinary = CorridorNetDemand(
        demand_id="ordinary-only",
        net_name="SIGNAL",
        width_mm=0.2,
        allowed_layers=("F.Cu",),
        via_policy=CorridorViaPolicy.FORBIDDEN,
        terminals=(
            CorridorTerminal(terminal_id="a", candidate_cell_ids=("entry",)),
            CorridorTerminal(terminal_id="b", candidate_cell_ids=("fine",)),
        ),
        ordinary_span_units=1,
        effective_clearance_mm=0.1,
    )

    wrapped = negotiate_corridor_exchange_allocations(
        graph,
        (),
        ordinary_demands=(ordinary,),
    )
    default = allocator_module.negotiate_corridor_allocations(graph, (ordinary,))

    assert wrapped.plan == default
    assert wrapped.exchange_demands == ()
    assert wrapped.exchange_allocations == ()
