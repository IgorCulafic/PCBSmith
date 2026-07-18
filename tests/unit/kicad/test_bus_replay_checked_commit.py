"""Tests for the opt-in replay-bound exact checked bus commit."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_escape_replay as replay_fixtures
from tests.unit.kicad import test_bus_transaction as transaction_fixtures

from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.bus_candidate_transaction import ReplayBoundBusRouteBundle
from pcbsmith.kicad.bus_checked_commit import (
    BusCheckedCommitCoordinator,
    BusExactDisposition,
    materialize_complete_route_map,
)
from pcbsmith.kicad.bus_replay_checked_commit import (
    ReplayBoundBusCheckedCommitResult,
    commit_replay_bound_bus_exact,
)
from pcbsmith.kicad.bus_transaction import bus_route_map_fingerprint
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import OccupancyLedger


def _authority(
    *, foreign: NegotiatedGridRoute | None = None
) -> ReplayBoundBusRouteBundle:
    ledger = OccupancyLedger(() if foreign is None else (foreign.claims,))
    replay = replay_fixtures._generate(ledger=ledger)
    assert replay.generation_result.success
    assert replay.generation_result.candidate is not None
    assert replay.generation_result.candidate.bundle is not None
    return ReplayBoundBusRouteBundle(
        escape_replay=replay,
        bundle=replay.generation_result.candidate.bundle,
    )


def _coordinator(
    authority: ReplayBoundBusRouteBundle,
    *,
    foreign: NegotiatedGridRoute | None = None,
) -> BusCheckedCommitCoordinator:
    routes = {
        member.net_name: transaction_fixtures._route(member.net_name, 90 + index)
        for index, member in enumerate(authority.bundle.bus.members)
    }
    if foreign is not None:
        routes[foreign.result.net_name] = foreign
    return BusCheckedCommitCoordinator(
        OccupancyLedger(route.claims for route in routes.values()),
        routes,
    )


def _checker(accepted: bool):
    def check(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        return ExactRouteCheckResult(accepted, "replay-exact-fixture")

    return check


def _state(coordinator: BusCheckedCommitCoordinator) -> tuple[object, object, object]:
    return (
        coordinator.ledger.committed_claims(),
        coordinator.ledger.semantic_fingerprint(),
        bus_route_map_fingerprint(coordinator.routes_by_net),
    )


def test_accepts_real_escape_candidate_once_and_roundtrips_full_authority() -> None:
    authority = _authority()
    coordinator = _coordinator(authority)
    calls = {"materializer": 0, "checker": 0}

    def materializer(
        layout: BoardLayout,
        routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        calls["materializer"] += 1
        return materialize_complete_route_map(layout, routes)

    def checker(layout: BoardLayout, netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls["checker"] += 1
        return _checker(True)(layout, netlist)

    result = commit_replay_bound_bus_exact(
        coordinator,
        authority,
        exact_checker=checker,
        materializer=materializer,
    )

    assert calls == {"materializer": 1, "checker": 1}
    assert result.checked_result.accepted
    assert result.checked_result.telemetry.candidate_call_count == 1
    assert result.checked_result.candidate_result == (
        authority.escape_replay.generation_result.candidate
    )
    assert coordinator.routes_by_net == authority.bundle.by_net()
    assert (
        ReplayBoundBusCheckedCommitResult.model_validate_json(result.model_dump_json())
        == result
    )


def test_rejection_retains_exact_evidence_and_restores_old_routes() -> None:
    authority = _authority()
    coordinator = _coordinator(authority)
    before = _state(coordinator)

    result = commit_replay_bound_bus_exact(
        coordinator,
        authority,
        exact_checker=_checker(False),
    )

    assert result.checked_result.exact_disposition is BusExactDisposition.REJECTED
    assert not result.checked_result.committed
    assert result.checked_result.materialized_layout is not None
    assert result.checked_result.checked_netlist == authority.escape_replay.replay_input.netlist
    assert result.checked_result.exact_check_evidence is not None
    assert _state(coordinator) == before


def test_missing_checker_preserves_checked_result_semantics_and_restores() -> None:
    authority = _authority()
    coordinator = _coordinator(authority)
    before = _state(coordinator)

    result = commit_replay_bound_bus_exact(
        coordinator,
        authority,
        exact_checker=None,
    )

    assert result.checked_result.algorithmic_success
    assert result.checked_result.exact_disposition is BusExactDisposition.CHECKER_MISSING
    assert result.checked_result.materialized_layout is None
    assert result.checked_result.exact_check_evidence is None
    assert _state(coordinator) == before


def test_wrong_external_occupancy_rolls_back_before_materialization_or_check() -> None:
    authority = _authority()
    foreign = transaction_fixtures._route("/FOREIGN", 80)
    coordinator = _coordinator(authority, foreign=foreign)
    before = _state(coordinator)
    calls = {"materializer": 0, "checker": 0}

    def materializer(
        layout: BoardLayout,
        routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        calls["materializer"] += 1
        return materialize_complete_route_map(layout, routes)

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls["checker"] += 1
        return ExactRouteCheckResult(True, "must-not-run")

    with pytest.raises(ValueError, match="stripped coordinator occupancy"):
        commit_replay_bound_bus_exact(
            coordinator,
            authority,
            exact_checker=checker,
            materializer=materializer,
        )

    assert calls == {"materializer": 0, "checker": 0}
    assert coordinator.last_result is None
    assert _state(coordinator) == before


def test_coherent_replay_bound_foreign_state_is_preserved() -> None:
    foreign = transaction_fixtures._route("/FOREIGN", 80)
    authority = _authority(foreign=foreign)
    coordinator = _coordinator(authority, foreign=foreign)

    result = commit_replay_bound_bus_exact(
        coordinator,
        authority,
        exact_checker=_checker(True),
    )

    assert result.checked_result.accepted
    assert coordinator.routes_by_net["/FOREIGN"] == foreign
    assert coordinator.ledger.claims_for("/FOREIGN") == foreign.claims


def test_incoherent_route_and_ledger_state_is_rejected_before_commit() -> None:
    authority = _authority()
    coordinator = _coordinator(authority)
    coordinator.ledger.commit(transaction_fixtures._route("/SHADOW", 81).claims)

    with pytest.raises(ValueError, match="exactly represent committed claims"):
        commit_replay_bound_bus_exact(
            coordinator,
            authority,
            exact_checker=_checker(True),
        )

    assert coordinator.last_result is None


def test_materializer_exception_is_rolled_back_without_retry() -> None:
    authority = _authority()
    coordinator = _coordinator(authority)
    before = _state(coordinator)
    calls = 0

    def failing_materializer(
        _layout: BoardLayout,
        _routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        nonlocal calls
        calls += 1
        raise RuntimeError("materializer failed")

    with pytest.raises(RuntimeError, match="materializer failed"):
        commit_replay_bound_bus_exact(
            coordinator,
            authority,
            exact_checker=_checker(True),
            materializer=failing_materializer,
        )

    assert calls == 1
    assert coordinator.last_result is None
    assert _state(coordinator) == before


def test_stale_authority_is_rejected_before_coordinator_use() -> None:
    authority = _authority()
    coordinator = _coordinator(authority)
    payload = authority.model_dump(mode="json")
    payload["escape_replay"]["generation_result"]["candidate"]["expansion_count"] += 1

    with pytest.raises(ValidationError):
        stale = ReplayBoundBusRouteBundle.model_validate(payload)
        commit_replay_bound_bus_exact(
            coordinator,
            stale,
            exact_checker=_checker(True),
        )
    assert coordinator.last_result is None


def test_envelope_rejects_other_checked_candidate() -> None:
    authority = _authority()
    coordinator = _coordinator(authority)
    result = commit_replay_bound_bus_exact(
        coordinator,
        authority,
        exact_checker=_checker(True),
    )
    payload = result.model_dump(mode="json")
    payload["checked_result"]["candidate_result"]["expansion_count"] += 1

    with pytest.raises(ValidationError):
        ReplayBoundBusCheckedCommitResult.model_validate(payload)


def test_envelope_rejects_stale_exact_evidence() -> None:
    authority = _authority()
    coordinator = _coordinator(authority)
    result = commit_replay_bound_bus_exact(
        coordinator,
        authority,
        exact_checker=_checker(True),
    )
    payload = result.model_dump(mode="json")
    payload["checked_result"]["exact_check_evidence"][
        "materialized_layout_fingerprint"
    ] = "a" * 64

    with pytest.raises(ValidationError, match="exact evidence"):
        ReplayBoundBusCheckedCommitResult.model_validate(payload)
