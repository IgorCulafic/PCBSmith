from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from tests.unit.kicad.test_bus_transaction import _bundle, _route, _state

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_ir import BusGroup
from pcbsmith.kicad.board import BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.bus_candidate import (
    BusCandidateBudget,
    BusCandidateFailureReason,
    BusCandidatePolicy,
    BusCandidateResult,
    BusMemberCandidateTelemetry,
)
from pcbsmith.kicad.bus_checked_commit import (
    BusCheckedCallbackMutationError,
    BusCheckedCommitCoordinator,
    BusCheckedCommitResult,
    BusCheckedMaterializationMismatchError,
    BusExactDisposition,
    materialize_complete_route_map,
)
from pcbsmith.kicad.bus_transaction import (
    BusRouteBundle,
    bus_route_map_fingerprint,
)
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)


def _full_state() -> tuple[
    BusGroup,
    BusLaneAllocationResult,
    OccupancyLedger,
    dict[str, NegotiatedGridRoute],
]:
    bus, allocation, ledger, routes = _state()
    foreign = _route("/X", 30)
    ledger.commit(foreign.claims)
    routes["/X"] = foreign
    return bus, allocation, ledger, routes


def _static_layout() -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=40.0,
        height_mm=12.0,
        zones=(("GND", "B.Cu", (0.0, 0.0, 40.0, 12.0)),),
        outline=((0.0, 0.0), (40.0, 0.0), (39.0, 12.0), (0.0, 12.0)),
        graphics=("(gr_text preserved)",),
        hide_references=("U1",),
    )


def _successful_candidate(
    bus: BusGroup,
    allocation: BusLaneAllocationResult,
    ledger: OccupancyLedger,
    *,
    bundle: BusRouteBundle | None = None,
) -> BusCandidateResult:
    candidate_bundle = bundle or _bundle(
        bus,
        allocation,
        _route("/A", 11),
        _route("/B", 12),
    )
    ledger_fingerprint = ledger.semantic_fingerprint()
    telemetry = tuple(
        BusMemberCandidateTelemetry(
            member_id=member.member_id,
            net_name=member.net_name,
            prefix_fingerprint=("a" if index == 0 else "b") * 64,
            routed=True,
            expansion_count=route.result.expansion_count,
            segment_count=len(route.result.segments),
            via_count=len(route.result.vias),
        )
        for index, (member, route) in enumerate(
            zip(bus.members, candidate_bundle.member_routes, strict=True)
        )
    )
    return BusCandidateResult(
        success=True,
        complete=True,
        zero_overuse=True,
        bus_id=bus.bus_id,
        bus_fingerprint=bus.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        budget=BusCandidateBudget(
            max_members=len(bus.members),
            max_expansions_per_member=100,
            max_total_expansions=200,
        ),
        policy=BusCandidatePolicy(),
        route_order=tuple(member.member_id for member in bus.members),
        member_telemetry=telemetry,
        expansion_count=sum(item.expansion_count for item in telemetry),
        caller_ledger_before_fingerprint=ledger_fingerprint,
        caller_ledger_after_fingerprint=ledger_fingerprint,
        bundle=candidate_bundle,
    )


def _failed_candidate(
    bus: BusGroup,
    allocation: BusLaneAllocationResult,
    ledger: OccupancyLedger,
) -> BusCandidateResult:
    ledger_fingerprint = ledger.semantic_fingerprint()
    return BusCandidateResult(
        success=False,
        complete=False,
        zero_overuse=False,
        bus_id=bus.bus_id,
        bus_fingerprint=bus.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        budget=BusCandidateBudget(
            max_members=len(bus.members),
            max_expansions_per_member=100,
            max_total_expansions=200,
        ),
        policy=BusCandidatePolicy(),
        route_order=tuple(member.member_id for member in bus.members),
        expansion_count=0,
        failure_reason=BusCandidateFailureReason.ROUTING_ERROR,
        failed_member_id=bus.members[0].member_id,
        caller_ledger_before_fingerprint=ledger_fingerprint,
        caller_ledger_after_fingerprint=ledger_fingerprint,
    )


def _overused_candidate(
    bus: BusGroup,
    allocation: BusLaneAllocationResult,
    ledger: OccupancyLedger,
) -> BusCandidateResult:
    shared = RoutingResourceKey("ordinary", "F.Cu", "cell", 20, 1)
    bundle = _bundle(
        bus,
        allocation,
        _route("/A", 11, resource=shared),
        _route("/B", 12, resource=shared),
    )
    scratch = OccupancyLedger(ledger.committed_claims())
    for route in bundle.member_routes:
        scratch.commit(route.claims)
    base = _successful_candidate(bus, allocation, ledger, bundle=bundle)
    return base.model_copy(
        update={
            "success": False,
            "zero_overuse": False,
            "failure_reason": BusCandidateFailureReason.FINAL_OVERUSE,
            "resource_overuse": scratch.overuse(),
        }
    )


def _before(
    ledger: OccupancyLedger,
    routes: dict[str, NegotiatedGridRoute],
) -> tuple[str, str, tuple[NetResourceClaims, ...], dict[str, NegotiatedGridRoute]]:
    return (
        ledger.semantic_fingerprint(),
        bus_route_map_fingerprint(routes),
        ledger.committed_claims(),
        dict(routes),
    )


def _assert_restored(
    ledger: OccupancyLedger,
    routes: dict[str, NegotiatedGridRoute],
    before: tuple[str, str, tuple[NetResourceClaims, ...], dict[str, NegotiatedGridRoute]],
) -> None:
    ledger_fingerprint, route_fingerprint, claims, old_routes = before
    assert ledger.semantic_fingerprint() == ledger_fingerprint
    assert bus_route_map_fingerprint(routes) == route_fingerprint
    assert ledger.committed_claims() == claims
    assert routes == old_routes


def test_accept_materializes_and_checks_once_then_retains_complete_state() -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    calls = {"candidate": 0, "materializer": 0, "checker": 0}
    static = _static_layout()
    netlist = BoardNetlist(components=(), nets=())

    def candidate_builder(scratch: OccupancyLedger) -> BusCandidateResult:
        calls["candidate"] += 1
        assert not scratch.claims_for("/A").resources
        assert not scratch.claims_for("/B").resources
        assert scratch.claims_for("/X").resources
        return _successful_candidate(bus, allocation, scratch)

    def materializer(
        layout: BoardLayout,
        mixed_routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        calls["materializer"] += 1
        assert layout is not static
        assert mixed_routes is not routes
        assert set(mixed_routes) == {"/A", "/B", "/X"}
        return materialize_complete_route_map(layout, mixed_routes)

    def checker(layout: BoardLayout, checked_netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls["checker"] += 1
        assert layout is not static
        assert checked_netlist is not netlist
        assert layout.graphics == static.graphics
        assert layout.zones == static.zones
        assert layout.outline == static.outline
        assert {segment.net_name for segment in layout.segments} == {"/A", "/B", "/X"}
        return ExactRouteCheckResult(True, "exact-fixture")

    result = coordinator.commit(
        static,
        netlist,
        bus,
        allocation,
        candidate_builder,
        exact_checker=checker,
        materializer=materializer,
    )

    assert calls == {"candidate": 1, "materializer": 1, "checker": 1}
    assert result.algorithmic_success
    assert result.committed
    assert result.accepted
    assert result.exact_disposition is BusExactDisposition.ACCEPTED
    assert result.telemetry.materialization_call_count == 1
    assert result.telemetry.exact_check_call_count == 1
    assert result.materialized_layout is not None
    assert result.checked_netlist == netlist
    assert result.exact_check_evidence is not None
    assert routes["/X"] == old[3]["/X"]
    assert routes["/A"].result.segments[0].x1 == 11
    assert routes["/B"].result.segments[0].x1 == 12
    assert (
        result.telemetry.semantic_fingerprint()
        == "78c19a34771158bfa54b0d0f33b640e50dbf4987b7ad1a4537a19f81184809d6"
    )
    assert (
        result.semantic_fingerprint()
        == "d7d0bc4a8950ff1a002101c80a472ac957ca3bcc32b15ea0b22cc7cf8877ac17"
    )


def test_missing_checker_skips_materialization_and_restores_algorithmic_success() -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)

    def must_not_materialize(*_args: Any, **_kwargs: Any) -> BoardLayout:
        raise AssertionError("materializer must not run without an exact checker")

    result = coordinator.commit(
        _static_layout(),
        BoardNetlist(components=(), nets=()),
        bus,
        allocation,
        lambda scratch: _successful_candidate(bus, allocation, scratch),
        exact_checker=None,
        materializer=must_not_materialize,
    )

    assert result.algorithmic_success
    assert not result.committed
    assert not result.accepted
    assert result.exact_disposition is BusExactDisposition.CHECKER_MISSING
    assert result.telemetry.materialization_call_count == 0
    assert result.telemetry.exact_check_call_count == 0
    _assert_restored(ledger, routes, old)


def test_rejected_report_is_retained_without_fabricating_candidate_failure() -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    report = ExactRouteCheckResult(False, "exact-fixture", ("finding-b", "finding-a"))

    result = coordinator.commit(
        _static_layout(),
        BoardNetlist(components=(), nets=()),
        bus,
        allocation,
        lambda scratch: _successful_candidate(bus, allocation, scratch),
        exact_checker=lambda _layout, _netlist: report,
    )

    assert result.algorithmic_success
    assert result.exact_disposition is BusExactDisposition.REJECTED
    assert result.exact_report == report
    assert result.materialized_layout is not None
    assert result.checked_netlist is not None
    assert result.exact_check_evidence is not None
    assert result.candidate_result.failure_reason is None
    assert not result.committed
    assert result.telemetry.materialization_call_count == 1
    assert result.telemetry.exact_check_call_count == 1
    _assert_restored(ledger, routes, old)


@pytest.mark.parametrize("kind", ("failed", "overused"))
def test_c2_failure_or_overuse_skips_materializer_and_checker(kind: str) -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    calls = {"materializer": 0, "checker": 0}

    def builder(scratch: OccupancyLedger) -> BusCandidateResult:
        if kind == "failed":
            return _failed_candidate(bus, allocation, scratch)
        return _overused_candidate(bus, allocation, scratch)

    def materializer(*_args: Any, **_kwargs: Any) -> BoardLayout:
        calls["materializer"] += 1
        raise AssertionError("failed c2 result must skip materialization")

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls["checker"] += 1
        raise AssertionError("failed c2 result must skip exact check")

    result = coordinator.commit(
        _static_layout(),
        BoardNetlist(components=(), nets=()),
        bus,
        allocation,
        builder,
        exact_checker=checker,
        materializer=materializer,
    )

    assert not result.algorithmic_success
    assert result.exact_disposition is BusExactDisposition.CANDIDATE_FAILED
    assert calls == {"materializer": 0, "checker": 0}
    _assert_restored(ledger, routes, old)


@pytest.mark.parametrize("stage", ("materializer", "checker"))
def test_materializer_and_checker_exceptions_restore_and_preserve_identity(stage: str) -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    sentinel = RuntimeError(f"{stage} exploded")

    def materializer(
        layout: BoardLayout,
        mixed_routes: Any,
    ) -> BoardLayout:
        if stage == "materializer":
            raise sentinel
        return materialize_complete_route_map(layout, mixed_routes)

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        if stage == "checker":
            raise sentinel
        return ExactRouteCheckResult(True, "unreachable")

    with pytest.raises(RuntimeError) as caught:
        coordinator.commit(
            _static_layout(),
            BoardNetlist(components=(), nets=()),
            bus,
            allocation,
            lambda scratch: _successful_candidate(bus, allocation, scratch),
            exact_checker=checker,
            materializer=materializer,
        )

    assert caught.value is sentinel
    _assert_restored(ledger, routes, old)


@pytest.mark.parametrize("field", ("bus_fingerprint", "allocation_fingerprint"))
def test_forged_or_stale_candidate_is_rejected_before_materialization(field: str) -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)

    def builder(scratch: OccupancyLedger) -> BusCandidateResult:
        valid = _successful_candidate(bus, allocation, scratch)
        return valid.model_copy(update={field: "f" * 64})

    result = coordinator.commit(
        _static_layout(),
        BoardNetlist(components=(), nets=()),
        bus,
        allocation,
        builder,
        exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(True, "must-not-run"),
    )

    assert not result.algorithmic_success
    assert result.exact_disposition is BusExactDisposition.CANDIDATE_INVALID
    assert result.telemetry.materialization_call_count == 0
    assert result.telemetry.exact_check_call_count == 0
    _assert_restored(ledger, routes, old)


def test_nested_candidate_forgery_is_revalidated_and_restored() -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    materializer_calls = 0

    def builder(scratch: OccupancyLedger) -> BusCandidateResult:
        valid = _successful_candidate(bus, allocation, scratch)
        forged = valid.member_telemetry[0].model_copy(update={"segment_count": -1})
        return valid.model_copy(
            update={"member_telemetry": (forged, *valid.member_telemetry[1:])}
        )

    def materializer(layout: BoardLayout, _routes: Any) -> BoardLayout:
        nonlocal materializer_calls
        materializer_calls += 1
        return layout

    with pytest.raises(ValueError, match="segment_count"):
        coordinator.commit(
            _static_layout(),
            BoardNetlist(components=(), nets=()),
            bus,
            allocation,
            builder,
            exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(
                True,
                "must-not-run",
            ),
            materializer=materializer,
        )

    assert materializer_calls == 0
    _assert_restored(ledger, routes, old)


@pytest.mark.parametrize("stage", ("candidate", "materializer", "checker"))
def test_callback_foreign_state_mutation_is_detected_and_full_state_restored(stage: str) -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)

    def mutate_foreign() -> None:
        foreign = _route("/X", 35)
        ledger.commit(foreign.claims)
        routes["/X"] = foreign

    def builder(scratch: OccupancyLedger) -> BusCandidateResult:
        result = _successful_candidate(bus, allocation, scratch)
        if stage == "candidate":
            mutate_foreign()
        return result

    def materializer(layout: BoardLayout, mixed_routes: Any) -> BoardLayout:
        materialized = materialize_complete_route_map(layout, mixed_routes)
        if stage == "materializer":
            mutate_foreign()
        return materialized

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        if stage == "checker":
            mutate_foreign()
        return ExactRouteCheckResult(True, "exact-fixture")

    with pytest.raises(BusCheckedCallbackMutationError):
        coordinator.commit(
            _static_layout(),
            BoardNetlist(components=(), nets=()),
            bus,
            allocation,
            builder,
            exact_checker=checker,
            materializer=materializer,
        )

    _assert_restored(ledger, routes, old)


def test_candidate_builder_exception_restores_full_map_and_preserves_identity() -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    sentinel = RuntimeError("candidate search exploded")

    def explode(_scratch: OccupancyLedger) -> BusCandidateResult:
        raise sentinel

    with pytest.raises(RuntimeError) as caught:
        coordinator.commit(
            _static_layout(),
            BoardNetlist(components=(), nets=()),
            bus,
            allocation,
            explode,
            exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(True, "unreachable"),
        )

    assert caught.value is sentinel
    _assert_restored(ledger, routes, old)


def test_materializer_omission_forgery_rolls_back_before_checker() -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    checker_calls = 0

    def omit_candidate_copper(layout: BoardLayout, _routes: Any) -> BoardLayout:
        return layout

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal checker_calls
        checker_calls += 1
        return ExactRouteCheckResult(True, "must-not-certify-forgery")

    with pytest.raises(BusCheckedMaterializationMismatchError):
        coordinator.commit(
            _static_layout(),
            BoardNetlist(components=(), nets=()),
            bus,
            allocation,
            lambda scratch: _successful_candidate(bus, allocation, scratch),
            exact_checker=checker,
            materializer=omit_candidate_copper,
        )

    assert checker_calls == 0
    _assert_restored(ledger, routes, old)


def test_replacement_only_boundary_rejects_missing_existing_bus_before_callback() -> None:
    bus, allocation, ledger, routes = _full_state()
    ledger.rip_up("/B")
    del routes["/B"]
    before = _before(ledger, routes)
    candidate_calls = 0

    def candidate_builder(_scratch: OccupancyLedger) -> BusCandidateResult:
        nonlocal candidate_calls
        candidate_calls += 1
        raise AssertionError("replacement-only validation must run first")

    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    with pytest.raises(ValueError, match="incomplete for bus nets"):
        coordinator.commit(
            _static_layout(),
            BoardNetlist(components=(), nets=()),
            bus,
            allocation,
            candidate_builder,
            exact_checker=None,
        )

    assert candidate_calls == 0
    _assert_restored(ledger, routes, before)


def test_materializer_rejects_preexisting_dynamic_copper_without_losing_layout_fields() -> None:
    _bus_value, _allocation_value, _ledger_value, routes = _full_state()
    static = _static_layout()
    materialized = materialize_complete_route_map(static, routes)
    for field_name in static.__dataclass_fields__:
        if field_name not in {"segments", "vias"}:
            assert getattr(materialized, field_name) == getattr(static, field_name)

    contaminated = replace(static, segments=routes["/X"].result.segments)
    with pytest.raises(ValueError, match="already contains materialized"):
        materialize_complete_route_map(contaminated, routes)


@pytest.mark.parametrize("outcome", ("normal", "raise", "wrong_type"))
def test_materializer_detached_layout_mutation_wins_on_every_return_path(
    outcome: str,
) -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    static = _static_layout()
    netlist = BoardNetlist(components=(), nets=())
    static_before = canonical_board_layout_snapshot_json(static)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)

    def materializer(layout: BoardLayout, mixed_routes: Any) -> Any:
        assert layout is not static
        object.__setattr__(layout, "hide_references", ("MUTATED",))
        if outcome == "raise":
            raise RuntimeError("mutation must take precedence")
        if outcome == "wrong_type":
            return object()
        return materialize_complete_route_map(layout, mixed_routes)

    with pytest.raises(BusCheckedCallbackMutationError, match="detached materializer layout"):
        coordinator.commit(
            static,
            netlist,
            bus,
            allocation,
            lambda scratch: _successful_candidate(bus, allocation, scratch),
            exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(
                True, "must-not-run"
            ),
            materializer=materializer,
        )

    assert canonical_board_layout_snapshot_json(static) == static_before
    assert canonical_board_netlist_snapshot_json(netlist) == netlist_before
    _assert_restored(ledger, routes, old)


def test_materializer_detached_route_map_mutation_is_detected() -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)

    def materializer(layout: BoardLayout, mixed_routes: Any) -> BoardLayout:
        object.__setattr__(mixed_routes["/X"].result, "net_name", "/MUTATED")
        return layout

    with pytest.raises(BusCheckedCallbackMutationError, match="detached route-map"):
        coordinator.commit(
            _static_layout(),
            BoardNetlist(components=(), nets=()),
            bus,
            allocation,
            lambda scratch: _successful_candidate(bus, allocation, scratch),
            exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(
                True, "must-not-run"
            ),
            materializer=materializer,
        )

    _assert_restored(ledger, routes, old)


@pytest.mark.parametrize("target", ("layout", "netlist"))
@pytest.mark.parametrize("outcome", ("normal", "raise", "wrong_type", "invalid_report"))
def test_checker_detached_input_mutation_wins_on_every_report_path(
    target: str,
    outcome: str,
) -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    static = _static_layout()
    netlist = BoardNetlist(components=(), nets=(BoardNet("/N", ()),))
    static_before = canonical_board_layout_snapshot_json(static)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)

    def checker(layout: BoardLayout, checked_netlist: BoardNetlist) -> Any:
        assert layout is not static
        assert checked_netlist is not netlist
        if target == "layout":
            object.__setattr__(layout, "graphics", ("mutated",))
        else:
            object.__setattr__(checked_netlist, "nets", ())
        if outcome == "raise":
            raise RuntimeError("mutation must take precedence")
        if outcome == "wrong_type":
            return object()
        report = ExactRouteCheckResult(True, "exact-fixture", ("finding-a",))
        if outcome == "invalid_report":
            object.__setattr__(report, "finding_fingerprints", ("z", "a"))
        return report

    with pytest.raises(BusCheckedCallbackMutationError, match=f"detached checker {target}"):
        coordinator.commit(
            static,
            netlist,
            bus,
            allocation,
            lambda scratch: _successful_candidate(bus, allocation, scratch),
            exact_checker=checker,
        )

    assert canonical_board_layout_snapshot_json(static) == static_before
    assert canonical_board_netlist_snapshot_json(netlist) == netlist_before
    _assert_restored(ledger, routes, old)


@pytest.mark.parametrize(
    ("stage", "outcome"),
    (
        ("materializer", "normal"),
        ("materializer", "raise"),
        ("materializer", "wrong_type"),
        ("checker", "normal"),
        ("checker", "raise"),
        ("checker", "wrong_type"),
        ("checker", "invalid_report"),
    ),
)
@pytest.mark.parametrize("target", ("layout", "netlist"))
def test_callback_closure_mutation_of_original_board_input_is_detected(
    stage: str,
    outcome: str,
    target: str,
) -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    static = _static_layout()
    netlist = BoardNetlist(components=(), nets=())

    def mutate_original() -> None:
        if target == "layout":
            object.__setattr__(static, "graphics", ("closure mutation",))
        else:
            object.__setattr__(netlist, "nets", (BoardNet("/MUTATED", ()),))

    def materializer(layout: BoardLayout, mixed_routes: Any) -> Any:
        if stage == "materializer":
            mutate_original()
            if outcome == "raise":
                raise RuntimeError("caller mutation must take precedence")
            if outcome == "wrong_type":
                return object()
        return materialize_complete_route_map(layout, mixed_routes)

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> Any:
        if stage == "checker":
            mutate_original()
            if outcome == "raise":
                raise RuntimeError("caller mutation must take precedence")
            if outcome == "wrong_type":
                return object()
        report = ExactRouteCheckResult(True, "exact-fixture")
        if stage == "checker" and outcome == "invalid_report":
            object.__setattr__(report, "checker_id", "")
        return report

    with pytest.raises(BusCheckedCallbackMutationError, match=f"caller {target}"):
        coordinator.commit(
            static,
            netlist,
            bus,
            allocation,
            lambda scratch: _successful_candidate(bus, allocation, scratch),
            exact_checker=checker,
            materializer=materializer,
        )

    _assert_restored(ledger, routes, old)


@pytest.mark.parametrize("outcome", ("wrong_type", "invalid_report"))
def test_checker_bad_report_path_rolls_back_without_retry(outcome: str) -> None:
    bus, allocation, ledger, routes = _full_state()
    coordinator = BusCheckedCommitCoordinator(ledger, routes)
    old = _before(ledger, routes)
    calls = 0

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> Any:
        nonlocal calls
        calls += 1
        if outcome == "wrong_type":
            return object()
        report = ExactRouteCheckResult(True, "exact-fixture")
        object.__setattr__(report, "checker_id", "")
        return report

    expected = TypeError if outcome == "wrong_type" else ValueError
    with pytest.raises(expected):
        coordinator.commit(
            _static_layout(),
            BoardNetlist(components=(), nets=()),
            bus,
            allocation,
            lambda scratch: _successful_candidate(bus, allocation, scratch),
            exact_checker=checker,
        )

    assert calls == 1
    assert coordinator.last_result is None
    _assert_restored(ledger, routes, old)


@pytest.mark.parametrize("accepted", (True, False))
def test_checked_result_roundtrip_retains_exact_inputs_and_replay_evidence(
    accepted: bool,
) -> None:
    bus, allocation, ledger, routes = _full_state()
    static = _static_layout()
    netlist = BoardNetlist(components=(), nets=(BoardNet("/SIGNAL", ()),))
    result = BusCheckedCommitCoordinator(ledger, routes).commit(
        static,
        netlist,
        bus,
        allocation,
        lambda scratch: _successful_candidate(bus, allocation, scratch),
        exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(
            accepted,
            "exact-fixture",
            (() if accepted else ("clearance-1",)),
        ),
    )

    assert result.materialized_layout is not None
    assert {segment.net_name for segment in result.materialized_layout.segments} == {
        "/A",
        "/B",
        "/X",
    }
    assert next(
        segment.x1
        for segment in result.materialized_layout.segments
        if segment.net_name == "/A"
    ) == 11
    assert result.checked_netlist == netlist
    assert result.exact_check_evidence is not None
    assert result.exact_check_evidence.accepted is accepted
    replayed = BusCheckedCommitResult.model_validate_json(result.model_dump_json())
    assert replayed == result
    assert replayed.semantic_fingerprint() == result.semantic_fingerprint()


@pytest.mark.parametrize("target", ("layout", "netlist", "evidence", "report"))
def test_checked_result_rejects_retained_authority_tampering(target: str) -> None:
    bus, allocation, ledger, routes = _full_state()
    result = BusCheckedCommitCoordinator(ledger, routes).commit(
        _static_layout(),
        BoardNetlist(components=(), nets=(BoardNet("/SIGNAL", ()),)),
        bus,
        allocation,
        lambda scratch: _successful_candidate(bus, allocation, scratch),
        exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(
            True, "exact-fixture", ("finding-a",)
        ),
    )
    payload = result.model_dump(mode="json")
    if target == "layout":
        payload["materialized_layout"]["width_mm"] += 1.0
    elif target == "netlist":
        payload["checked_netlist"]["nets"] = []
    elif target == "evidence":
        payload["exact_check_evidence"]["materialized_layout_fingerprint"] = "f" * 64
    else:
        payload["exact_report"]["checker_id"] = "forged-checker"

    with pytest.raises(ValueError, match="exact"):
        BusCheckedCommitResult.model_validate(payload)


def test_unchecked_result_cannot_retain_checked_authority() -> None:
    bus, allocation, ledger, routes = _full_state()
    result = BusCheckedCommitCoordinator(ledger, routes).commit(
        _static_layout(),
        BoardNetlist(components=(), nets=()),
        bus,
        allocation,
        lambda scratch: _successful_candidate(bus, allocation, scratch),
        exact_checker=None,
    )
    assert result.materialized_layout is None
    assert result.checked_netlist is None
    assert result.exact_check_evidence is None
    payload = result.model_dump(mode="json")
    payload["materialized_layout"] = _static_layout()
    with pytest.raises(ValueError, match="unchecked outcomes"):
        BusCheckedCommitResult.model_validate(payload)
