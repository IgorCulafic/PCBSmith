"""Focused exact-checked commit tests for physical-swap candidates."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_physical_swap_candidate as candidate_fixtures
from tests.unit.kicad.test_bus_physical_swap_candidate_transaction import (
    _authority,
    _routes,
)

from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.bus_checked_commit import (
    BusCheckedCommitCoordinator,
    BusExactDisposition,
    materialize_complete_route_map,
)
from pcbsmith.kicad.bus_physical_swap_replay_checked_commit import (
    ReplayBoundPhysicalSwapBusCheckedCommitResult,
    _validate_checked_commit,
    commit_replay_bound_physical_swap_bus_exact,
)
from pcbsmith.kicad.bus_transaction import (
    bus_route_map_fingerprint,
)
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)


@pytest.fixture(autouse=True)
def _deterministic_router(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate_fixtures._install_router(monkeypatch)


def _coordinator() -> BusCheckedCommitCoordinator:
    routes = _routes(_authority())
    return BusCheckedCommitCoordinator(
        OccupancyLedger(route.claims for route in routes.values()),
        routes,
    )


def _state(coordinator: BusCheckedCommitCoordinator) -> tuple[Any, ...]:
    return (
        coordinator.ledger.committed_claims(),
        coordinator.ledger.semantic_fingerprint(),
        bus_route_map_fingerprint(coordinator.routes_by_net),
        dict(coordinator.routes_by_net),
    )


def _checker(accepted: bool):
    def check(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        return ExactRouteCheckResult(accepted, "physical-swap-exact-fixture")

    return check


def test_accepted_exact_commit_checks_full_physical_and_foreign_copper_once() -> None:
    authority = _authority()
    coordinator = _coordinator()
    calls = {"materializer": 0, "checker": 0}
    composition = authority.candidate.replay_input.composition
    m0_prefix = composition.members[0].prefix
    foreign = coordinator.routes_by_net["/FOREIGN"]

    def materializer(
        layout: BoardLayout,
        routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        calls["materializer"] += 1
        assert set(routes) == {"/D0", "/D1", "/D2", "/FOREIGN"}
        return materialize_complete_route_map(layout, routes)

    def checker(layout: BoardLayout, netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls["checker"] += 1
        plan_input = composition.replay_input.plan.replay_input
        assert netlist == plan_input.netlist
        assert len(m0_prefix.vias) == 4
        assert all(via in layout.vias for via in m0_prefix.vias)
        assert all(segment in layout.segments for segment in foreign.result.segments)
        for member in composition.members:
            assert all(segment in layout.segments for segment in member.prefix.segments)
            assert all(via in layout.vias for via in member.prefix.vias)
        return ExactRouteCheckResult(True, "physical-swap-exact-fixture")

    result = commit_replay_bound_physical_swap_bus_exact(
        coordinator,
        authority,
        exact_checker=checker,
        materializer=materializer,
    )

    assert calls == {"materializer": 1, "checker": 1}
    assert result.checked_result.accepted
    assert result.checked_result.telemetry.candidate_call_count == 1
    assert coordinator.routes_by_net == {
        "/FOREIGN": foreign,
        **authority.bundle.by_net(),
    }
    assert (
        ReplayBoundPhysicalSwapBusCheckedCommitResult.model_validate_json(result.model_dump_json())
        == result
    )


@pytest.mark.parametrize("accepted", (False, None))
def test_exact_reject_and_checker_missing_restore_the_full_old_state(
    accepted: bool | None,
) -> None:
    authority = _authority()
    coordinator = _coordinator()
    before = _state(coordinator)
    result = commit_replay_bound_physical_swap_bus_exact(
        coordinator,
        authority,
        exact_checker=None if accepted is None else _checker(accepted),
    )

    expected = (
        BusExactDisposition.CHECKER_MISSING if accepted is None else BusExactDisposition.REJECTED
    )
    assert result.checked_result.exact_disposition is expected
    assert not result.checked_result.committed
    assert result.after_state == result.before_state
    assert _state(coordinator) == before
    if accepted is None:
        assert result.checked_result.materialized_layout is None
    else:
        assert result.checked_result.materialized_layout is not None
        assert result.checked_result.exact_check_evidence is not None


@pytest.mark.parametrize(
    "stage",
    ("materializer_omission", "materializer_mutation", "checker_mutation", "checker_error"),
)
def test_materializer_and_checker_failures_roll_back_without_retry(stage: str) -> None:
    authority = _authority()
    coordinator = _coordinator()
    before = _state(coordinator)
    calls = {"materializer": 0, "checker": 0}

    def materializer(
        layout: BoardLayout,
        routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        calls["materializer"] += 1
        if stage == "materializer_omission":
            return layout
        mixed = materialize_complete_route_map(layout, routes)
        if stage == "materializer_mutation":
            return replace(mixed, width_mm=mixed.width_mm + 1.0)
        return mixed

    def checker(layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls["checker"] += 1
        if stage == "checker_mutation":
            object.__setattr__(layout, "width_mm", layout.width_mm + 1.0)
        if stage == "checker_error":
            raise RuntimeError("checker exploded")
        return ExactRouteCheckResult(True, "physical-swap-exact-fixture")

    error = RuntimeError if stage == "checker_error" else Exception
    with pytest.raises(error):
        commit_replay_bound_physical_swap_bus_exact(
            coordinator,
            authority,
            exact_checker=checker,
            materializer=materializer,
        )

    assert calls["materializer"] == 1
    assert calls["checker"] == int(stage.startswith("checker"))
    assert coordinator.last_result is None
    assert _state(coordinator) == before


def test_checked_commit_rejects_shadow_state_before_candidate_release() -> None:
    authority = _authority()
    coordinator = _coordinator()
    coordinator.ledger.commit(
        NetResourceClaims(
            "/SHADOW",
            frozenset({RoutingResourceKey("ordinary", "F.Cu", "cell", 60, 60)}),
        )
    )
    before = _state(coordinator)

    with pytest.raises(ValueError):
        commit_replay_bound_physical_swap_bus_exact(
            coordinator,
            authority,
            exact_checker=_checker(True),
        )

    assert coordinator.last_result is None
    assert _state(coordinator) == before


def test_materialized_prefix_layout_report_evidence_telemetry_and_wrapper_tamper_reject() -> None:
    authority = _authority()
    coordinator = _coordinator()
    result = commit_replay_bound_physical_swap_bus_exact(
        coordinator,
        authority,
        exact_checker=_checker(True),
    )
    checked = result.checked_result
    assert checked.materialized_layout is not None
    assert checked.exact_report is not None
    assert checked.exact_check_evidence is not None

    changed_layout = replace(
        checked.materialized_layout,
        vias=checked.materialized_layout.vias[1:],
    )
    with pytest.raises(ValueError):
        _validate_checked_commit(
            authority,
            checked.model_copy(update={"materialized_layout": changed_layout}),
            result.before_state,
            result.after_state,
        )

    stale_report = replace(checked.exact_report, accepted=False)
    with pytest.raises(ValueError):
        checked.model_copy(update={"exact_report": stale_report}).outcome_is_coherent()
    stale_telemetry = checked.telemetry.model_copy(
        update={"candidate_result_fingerprint": "0" * 64}
    )
    with pytest.raises(ValueError):
        checked.model_copy(update={"telemetry": stale_telemetry}).outcome_is_coherent()
    with pytest.raises(ValueError, match="fingerprint"):
        result.model_copy(
            update={"result_fingerprint": "0" * 64}
        ).checked_result_is_exactly_physical_replay_bound()

    first_binding = authority.member_bindings[0].model_copy(update={"prefix_fingerprint": "0" * 64})
    stale_authority = authority.model_copy(
        update={"member_bindings": (first_binding, *authority.member_bindings[1:])}
    )
    with pytest.raises(ValueError):
        _validate_checked_commit(
            stale_authority,
            checked,
            result.before_state,
            result.after_state,
        )


def test_checked_envelope_json_rejects_nested_materialized_evidence_tamper() -> None:
    result = commit_replay_bound_physical_swap_bus_exact(
        _coordinator(),
        _authority(),
        exact_checker=_checker(True),
    )
    payload = result.model_dump(mode="json")
    payload["checked_result"]["exact_check_evidence"]["materialized_layout_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError):
        ReplayBoundPhysicalSwapBusCheckedCommitResult.model_validate(payload)
