from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

import pytest

import pcbsmith.kicad.group_board as group_board
from pcbsmith.bus_allocator import allocate_bus_lanes
from pcbsmith.bus_geometry import realize_certified_trunks
from pcbsmith.kicad.astar_router import RoutingError
from pcbsmith.kicad.board import BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.bus_candidate import (
    BusCandidateBudget,
    BusCandidateCallerOveruseMode,
    BusCandidateFailureReason,
    BusCandidatePolicy,
)
from pcbsmith.kicad.bus_checked_commit import materialize_complete_route_map
from pcbsmith.kicad.bus_integration import compose_member_route_prefix
from pcbsmith.kicad.group_board import (
    BusCandidateAttemptAudit,
    CertifiedBusGroupSearchSpec,
    GroupSearchBinding,
    MixedGroupCandidateResult,
    MixedGroupCheckedCommitCoordinator,
    MixedGroupExactDisposition,
    MixedGroupRollbackError,
    OrdinaryGroupSearchSpec,
    build_mixed_group_candidate,
)
from pcbsmith.kicad.group_negotiation import (
    BusGroupCandidate,
    GroupCandidateContext,
    GroupNegotiationBudget,
    GroupNegotiationTargetRef,
    GroupTargetKind,
    negotiate_route_groups,
)
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import OccupancyLedger
from pcbsmith.routing_ir import RoutingFailureReason
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

_group_helpers: Any = importlib.import_module("tests.unit.kicad.test_group_negotiation")
_budget = _group_helpers._budget
_bundle = _group_helpers._bundle
_resource = _group_helpers._resource
_route = _group_helpers._route
_mixed_kernel_state = _group_helpers._state
_bus_candidate_helpers: Any = importlib.import_module("tests.unit.kicad.test_bus_candidate")
_bus_ir_helpers: Any = importlib.import_module("tests.unit.test_bus_ir")


def _static_layout() -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=10.0,
        zones=(("GND", "B.Cu", (0.0, 0.0, 20.0, 10.0)),),
        graphics=("(gr_text preserved)",),
    )


def _netlist(*, reverse: bool = False) -> BoardNetlist:
    n_nodes = (("U1", "1"), ("U2", "1"))
    nets = (
        BoardNet("/N", tuple(reversed(n_nodes)) if reverse else n_nodes),
        BoardNet("/X", (("U3", "1"),)),
    )
    return BoardNetlist(components=(), nets=tuple(reversed(nets)) if reverse else nets)


def _target() -> GroupNegotiationTargetRef:
    return GroupNegotiationTargetRef(
        target_id="ordinary:/N",
        kind=GroupTargetKind.ORDINARY,
        net_names=("/N",),
    )


def _spec() -> OrdinaryGroupSearchSpec:
    return OrdinaryGroupSearchSpec(
        target=_target(),
        track_width_mm=0.2,
        grid_mm=0.5,
    )


def _state(warm: bool = True) -> tuple[OccupancyLedger, dict[str, NegotiatedGridRoute]]:
    routes = {"/N": _route("/N", _resource(90))} if warm else {}
    return OccupancyLedger(route.claims for route in routes.values()), routes


def _real_bus_fixture(
    *,
    max_members: int = 2,
) -> tuple[CertifiedBusGroupSearchSpec, BoardLayout, BoardNetlist, Any]:
    authority = _bus_candidate_helpers._authority()
    bus, certificate, allocation, registry, _realization = authority
    target = GroupNegotiationTargetRef(
        target_id="bus:two-member",
        kind=GroupTargetKind.BUS,
        net_names=tuple(member.net_name for member in bus.members),
        bus_fingerprint=bus.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
    )
    spec = CertifiedBusGroupSearchSpec(
        target=target,
        bus=bus,
        certificate=certificate,
        allocation=allocation,
        geometry_registry=registry,
        prefixes_by_member=_bus_candidate_helpers._prefixes(authority),
        certificate_context=_bus_ir_helpers._context(certificate),
        terminal_ownership=_bus_ir_helpers._ownership(bus),
        minimum_track_width_mm=DEFAULT_PCB_RULE_PROFILE.geometry.minimum_trace_width_mm,
        candidate_budget=BusCandidateBudget(
            max_members=max_members,
            max_expansions_per_member=10,
            max_total_expansions=20,
        ),
        candidate_policy=BusCandidatePolicy(
            caller_overuse_mode=BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION
        ),
    )
    layout, netlist = _bus_candidate_helpers._layout_and_netlist()
    return spec, layout, netlist, authority


def _second_real_bus_fixture() -> tuple[
    CertifiedBusGroupSearchSpec,
    BoardLayout,
    BoardNetlist,
]:
    first_spec, first_layout, first_netlist, first_authority = _real_bus_fixture()
    first_bus, certificate, _first_allocation, first_registry, _first_realization = (
        first_authority
    )
    net_names = {"/A": "/C", "/B": "/D"}
    component_refs = {"R1": "S1", "R2": "S2", "R3": "S3", "R4": "S4"}
    members = tuple(
        member.model_copy(
            update={
                "net_name": net_names[member.net_name],
                "terminals": tuple(
                    terminal.model_copy(
                        update={
                            "net_name": net_names[terminal.net_name],
                            "component_ref": component_refs[terminal.component_ref],
                        }
                    )
                    for terminal in member.terminals
                ),
            }
        )
        for member in first_bus.members
    )
    second_bus = type(first_bus).model_validate(
        {
            **first_bus.model_dump(),
            "bus_id": "two-member-second",
            "members": [member.model_dump() for member in members],
        }
    )
    allocation = allocate_bus_lanes(second_bus, certificate)
    assert allocation.success
    shifted_y = {"centerline:0": 6, "centerline:1": 15}
    geometries = tuple(
        type(geometry).model_validate(
            {
                **geometry.model_dump(),
                "entry_portal_point": (8, shifted_y[geometry.centerline_geometry_id]),
                "exit_portal_point": (22, shifted_y[geometry.centerline_geometry_id]),
                "points": (
                    (8, shifted_y[geometry.centerline_geometry_id]),
                    (22, shifted_y[geometry.centerline_geometry_id]),
                ),
            }
        )
        for geometry in first_registry.geometries
    )
    registry = type(first_registry).model_validate(
        {
            **first_registry.model_dump(),
            "allocation_fingerprint": allocation.allocation_fingerprint,
            "geometries": [geometry.model_dump() for geometry in geometries],
        }
    )
    realization = realize_certified_trunks(
        second_bus,
        certificate,
        allocation,
        registry,
    )
    authority = (second_bus, certificate, allocation, registry, realization)
    prefix_inputs = (
        ("data0", "/C", 6, "centerline:0", "pad:S1:1", "pad:S2:0"),
        ("data1", "/D", 15, "centerline:1", "pad:S3:1", "pad:S4:0"),
    )
    prefixes = {}
    for member_id, net_name, y, geometry_id, source_id, sink_id in prefix_inputs:
        source_terminal = f"{member_id}:source"
        sink_terminal = f"{member_id}:sink"
        pigtails = (
            _bus_candidate_helpers._pigtail(
                authority,
                member_id=member_id,
                net_name=net_name,
                terminal_id=source_terminal,
                boundary_id="entry",
                geometry_id=geometry_id,
                portal_kind="entry",
                source_id=source_id,
                points=((6, y), (8, y)),
            ),
            _bus_candidate_helpers._pigtail(
                authority,
                member_id=member_id,
                net_name=net_name,
                terminal_id=sink_terminal,
                boundary_id="exit",
                geometry_id=geometry_id,
                portal_kind="exit",
                source_id=sink_id,
                points=((24, y), (22, y)),
            ),
        )
        prefixes[member_id] = compose_member_route_prefix(
            second_bus,
            certificate,
            allocation,
            registry,
            realization,
            member_id,
            pigtails,
            (),
            {source_terminal: source_id, sink_terminal: sink_id},
        )
    target = GroupNegotiationTargetRef(
        target_id="bus:two-member-second",
        kind=GroupTargetKind.BUS,
        net_names=tuple(member.net_name for member in second_bus.members),
        bus_fingerprint=second_bus.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
    )
    spec = CertifiedBusGroupSearchSpec(
        target=target,
        bus=second_bus,
        certificate=certificate,
        allocation=allocation,
        geometry_registry=registry,
        prefixes_by_member=prefixes,
        certificate_context=_bus_ir_helpers._context(certificate),
        terminal_ownership=_bus_ir_helpers._ownership(second_bus),
        minimum_track_width_mm=DEFAULT_PCB_RULE_PROFILE.geometry.minimum_trace_width_mm,
        candidate_budget=BusCandidateBudget(
            max_members=2,
            max_expansions_per_member=10,
            max_total_expansions=20,
        ),
        candidate_policy=BusCandidatePolicy(
            caller_overuse_mode=BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION
        ),
    )
    second_components = tuple(
        replace(
            component,
            reference=component_refs[component.reference],
            uuid_path=component_refs[component.reference].lower(),
        )
        for component in first_netlist.components
    )
    layout = replace(
        first_layout,
        placements=(
            *first_layout.placements,
            (second_components[0], 5.0),
            (second_components[1], 25.0),
            (second_components[2], 5.0),
            (second_components[3], 25.0),
        ),
        part_y_mm=(
            *first_layout.part_y_mm,
            ("S1", 6.0),
            ("S2", 6.0),
            ("S3", 15.0),
            ("S4", 15.0),
        ),
    )
    netlist = replace(
        first_netlist,
        components=(*first_netlist.components, *second_components),
        nets=(
            *first_netlist.nets,
            BoardNet("/C", (("S1", "2"), ("S2", "1"))),
            BoardNet("/D", (("S3", "2"), ("S4", "1"))),
        ),
    )
    assert first_spec.target.target_id != spec.target.target_id
    return spec, layout, netlist


def _real_mixed_fixture(
    *,
    bus_max_members: int = 2,
) -> tuple[
    tuple[OrdinaryGroupSearchSpec, CertifiedBusGroupSearchSpec],
    BoardLayout,
    BoardNetlist,
    Any,
]:
    bus_spec, layout, netlist, authority = _real_bus_fixture(max_members=bus_max_members)
    ordinary = _spec()
    mixed_netlist = replace(
        netlist,
        nets=(*netlist.nets, BoardNet("/N", (("U9", "1"), ("U10", "1")))),
    )
    return (ordinary, bus_spec), layout, mixed_netlist, authority


def _fixed_group_budget(expansions: int) -> GroupNegotiationBudget:
    return GroupNegotiationBudget(
        max_passes=4,
        max_expansions=expansions,
        max_expansions_per_target=expansions,
        max_stagnant_passes=2,
    )


def _install_ordinary_search(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resource_index: int = 1,
    calls: list[int] | None = None,
) -> NegotiatedGridRoute:
    route = _route("/N", _resource(resource_index))

    def search(*_args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        if calls is not None:
            calls.append(kwargs["max_expansions"])
        return route

    monkeypatch.setattr(group_board, "route_net_negotiated_candidate", search)
    return route


def _before(
    ledger: OccupancyLedger,
    routes: dict[str, NegotiatedGridRoute],
) -> tuple[str, dict[str, NegotiatedGridRoute]]:
    return ledger.semantic_fingerprint(), dict(routes)


@pytest.mark.parametrize("warm", [False, True])
def test_checked_commit_accepts_cold_and_warm_target_once(
    monkeypatch: pytest.MonkeyPatch,
    warm: bool,
) -> None:
    calls: list[int] = []
    expected = _install_ordinary_search(monkeypatch, calls=calls)
    ledger, routes = _state(warm)
    coordinator = MixedGroupCheckedCommitCoordinator(ledger, routes)
    callback_calls = {"materializer": 0, "checker": 0}

    def materializer(
        layout: BoardLayout,
        mixed_routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        callback_calls["materializer"] += 1
        return materialize_complete_route_map(layout, mixed_routes)

    def checker(layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        callback_calls["checker"] += 1
        assert layout.graphics == _static_layout().graphics
        assert tuple(segment.net_name for segment in layout.segments) == ("/N",)
        return ExactRouteCheckResult(True, "exact-fixture")

    result = coordinator.commit(
        _static_layout(),
        _netlist(),
        (_spec(),),
        budget=_budget(),
        exact_checker=checker,
        materializer=materializer,
    )

    assert calls == [10]
    assert callback_calls == {"materializer": 1, "checker": 1}
    assert result.accepted
    assert result.exact_disposition is MixedGroupExactDisposition.ACCEPTED
    assert (
        result.candidate.semantic_fingerprint()
        == "198afa99ec7f2a000583f797b1016de21e1d28bef44b0b0132ac3aa10b71d9d7"
    )
    expected_result_fingerprint = (
        "0fbfe19ac4db75052920d66913e130da263d6c5afabb72321067cf05585a9d19"
        if warm
        else "1a89daab65d38ff75f90aeef0d6e7b47d8c37bb0dc832bb5bc153bd1ac5c42d1"
    )
    assert result.semantic_fingerprint() == expected_result_fingerprint
    assert (
        result.materialized_layout_fingerprint
        == "da92ce4b6b8a6a331ba43b24f77fc159eb0741cc89e07bc5f6b5950e1de689f4"
    )
    assert routes["/N"] == expected
    assert ledger.claims_for("/N") == expected.claims


def test_missing_checker_does_no_exact_work_and_restores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ordinary_search(monkeypatch)
    ledger, routes = _state()
    before = _before(ledger, routes)
    coordinator = MixedGroupCheckedCommitCoordinator(ledger, routes)

    def unreachable(*_args: Any, **_kwargs: Any) -> BoardLayout:
        raise AssertionError("materializer must not run")

    result = coordinator.commit(
        _static_layout(),
        _netlist(),
        (_spec(),),
        budget=_budget(),
        exact_checker=None,
        materializer=unreachable,
    )

    assert result.exact_disposition is MixedGroupExactDisposition.CHECKER_MISSING
    assert result.materialization_call_count == result.exact_check_call_count == 0
    assert _before(ledger, routes) == before


def test_rejection_restores_but_retains_report_and_checked_layout_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ordinary_search(monkeypatch)
    ledger, routes = _state()
    before = _before(ledger, routes)
    report = ExactRouteCheckResult(False, "exact-fixture", ("finding",))

    result = MixedGroupCheckedCommitCoordinator(ledger, routes).commit(
        _static_layout(),
        _netlist(),
        (_spec(),),
        budget=_budget(),
        exact_checker=lambda _layout, _netlist: report,
    )

    assert result.exact_disposition is MixedGroupExactDisposition.REJECTED
    assert result.exact_report is report
    assert result.layout is None
    assert result.materialized_layout_fingerprint is not None
    assert _before(ledger, routes) == before


def test_canonical_bindings_ignore_equivalent_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ordinary_search(monkeypatch)
    ledger, routes = _state()
    first = build_mixed_group_candidate(
        _static_layout(),
        _netlist(),
        ledger,
        routes,
        (_spec(),),
        budget=_budget(),
        clearance_groups=(
            (("/N",), ("/X",), 0.3, ("U2", "U1")),
            (("/N",), ("/X",), 0.3, ("U1", "U2")),
        ),
    )
    second = build_mixed_group_candidate(
        _static_layout(),
        _netlist(reverse=True),
        ledger,
        routes,
        (_spec(),),
        budget=_budget(),
        clearance_groups=((('/X',), ('/N',), 0.3, ("U1", "U2")),),
    )

    assert first.static_binding_fingerprint == second.static_binding_fingerprint
    assert first.search_bindings == second.search_bindings


@pytest.mark.parametrize(
    "netlist, message",
    [
        (
            BoardNetlist(
                components=(),
                nets=(BoardNet("/N", (("U1", "1"),)), BoardNet("/N", (("U2", "1"),))),
            ),
            "duplicate net names",
        ),
        (
            BoardNetlist(
                components=(),
                nets=(BoardNet("/N", (("U1", "1"),)), BoardNet("/X", (("U1", "1"),))),
            ),
            "duplicate net nodes",
        ),
    ],
)
def test_duplicate_netlist_identities_fail_before_search(
    monkeypatch: pytest.MonkeyPatch,
    netlist: BoardNetlist,
    message: str,
) -> None:
    calls: list[int] = []
    _install_ordinary_search(monkeypatch, calls=calls)
    ledger, routes = _state()

    with pytest.raises(ValueError, match=message):
        build_mixed_group_candidate(
            _static_layout(),
            netlist,
            ledger,
            routes,
            (_spec(),),
            budget=_budget(),
        )

    assert calls == []


def test_forged_extra_route_is_typed_candidate_invalid_without_exact_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ordinary_search(monkeypatch)
    ledger, routes = _state()
    before = _before(ledger, routes)
    candidate = build_mixed_group_candidate(
        _static_layout(), _netlist(), ledger, routes, (_spec(),), budget=_budget()
    )
    extra = _route("/EXTRA", _resource(77))
    forged_negotiation = replace(
        candidate.negotiation,
        routes_by_net=tuple(sorted((*candidate.negotiation.routes_by_net, ("/EXTRA", extra)))),
    )
    forged = replace(candidate, negotiation=forged_negotiation)
    monkeypatch.setattr(group_board, "build_mixed_group_candidate", lambda *_a, **_k: forged)
    exact_calls = 0

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal exact_calls
        exact_calls += 1
        return ExactRouteCheckResult(True, "unreachable")

    result = MixedGroupCheckedCommitCoordinator(ledger, routes).commit(
        _static_layout(),
        _netlist(),
        (_spec(),),
        budget=_budget(),
        exact_checker=checker,
    )

    assert result.exact_disposition is MixedGroupExactDisposition.CANDIDATE_INVALID
    assert result.materialization_call_count == result.exact_check_call_count == 0
    assert exact_calls == 0
    assert _before(ledger, routes) == before


def test_materializer_field_mismatch_runs_once_and_restores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ordinary_search(monkeypatch)
    ledger, routes = _state()
    before = _before(ledger, routes)
    calls = {"materializer": 0, "checker": 0}

    def materializer(
        layout: BoardLayout,
        mixed_routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        calls["materializer"] += 1
        return replace(materialize_complete_route_map(layout, mixed_routes), graphics=("forged",))

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls["checker"] += 1
        return ExactRouteCheckResult(True, "unreachable")

    with pytest.raises(ValueError, match=r"BoardLayout\.graphics"):
        MixedGroupCheckedCommitCoordinator(ledger, routes).commit(
            _static_layout(),
            _netlist(),
            (_spec(),),
            budget=_budget(),
            exact_checker=checker,
            materializer=materializer,
        )

    assert calls == {"materializer": 1, "checker": 0}
    assert _before(ledger, routes) == before


def test_exact_exception_identity_and_callback_mutation_both_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ordinary_search(monkeypatch)
    ledger, routes = _state()
    before = _before(ledger, routes)
    sentinel = RuntimeError("exact sentinel")

    def raises(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        raise sentinel

    with pytest.raises(RuntimeError) as caught:
        MixedGroupCheckedCommitCoordinator(ledger, routes).commit(
            _static_layout(),
            _netlist(),
            (_spec(),),
            budget=_budget(),
            exact_checker=raises,
        )
    assert caught.value is sentinel
    assert _before(ledger, routes) == before

    def mutates(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        routes.clear()
        return ExactRouteCheckResult(True, "forged")

    with pytest.raises(RuntimeError, match="exact checker mutated"):
        MixedGroupCheckedCommitCoordinator(ledger, routes).commit(
            _static_layout(),
            _netlist(),
            (_spec(),),
            budget=_budget(),
            exact_checker=mutates,
        )
    assert _before(ledger, routes) == before


def test_rollback_failure_preserves_original_and_rollback_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ordinary_search(monkeypatch)
    ledger, routes = _state()
    coordinator = MixedGroupCheckedCommitCoordinator(ledger, routes)
    original = RuntimeError("original")
    rollback = RuntimeError("rollback")

    def broken_restore(*_args: Any, **_kwargs: Any) -> None:
        raise rollback

    def materializer(
        _layout: BoardLayout,
        _routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        monkeypatch.setattr(coordinator, "_restore_state", broken_restore)
        raise original

    with pytest.raises(MixedGroupRollbackError) as caught:
        coordinator.commit(
            _static_layout(),
            _netlist(),
            (_spec(),),
            budget=_budget(),
            exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(True, "unreachable"),
            materializer=materializer,
        )

    assert caught.value.original_error is original
    assert caught.value.rollback_error is rollback


def test_complete_overused_bus_audit_is_valid_and_telemetry_mismatch_fires() -> None:
    bus, allocation, targets, ledger, routes = _mixed_kernel_state()
    target = targets[0]

    def search(context: GroupCandidateContext) -> BusGroupCandidate:
        return BusGroupCandidate(
            context.target,
            _bundle(bus, allocation, _resource(1), _resource(2)),
            2,
        )

    negotiation = negotiate_route_groups((target,), ledger, routes, search, budget=_budget())
    attempt = negotiation.passes[0].attempts[0]
    audit = BusCandidateAttemptAudit(
        pass_index=attempt.pass_index,
        attempt_index=attempt.attempt_index,
        target_id=attempt.target_id,
        result_fingerprint="a" * 64,
        expansion_count=attempt.expansion_count,
        complete=True,
        zero_overuse=False,
        failure_reason=BusCandidateFailureReason.FINAL_OVERUSE,
    )
    binding = GroupSearchBinding(target.target_id, GroupTargetKind.BUS, "b" * 64)
    candidate = MixedGroupCandidateResult(
        negotiation=negotiation,
        search_bindings=(binding,),
        bus_attempts=(audit,),
        static_binding_fingerprint="c" * 64,
        profile_fingerprint="d" * 64,
    )

    assert candidate.algorithmic_success
    with pytest.raises(ValueError, match="does not match group telemetry"):
        replace(candidate, bus_attempts=(replace(audit, expansion_count=3),))
    with pytest.raises(ValueError, match="incomplete bus attempt"):
        replace(audit, complete=False)


def test_fingerprint_validators_reject_noncanonical_sha() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        GroupSearchBinding("target", GroupTargetKind.ORDINARY, "A" * 64)



def test_certified_bus_spec_freezes_authority_and_profile_width_is_not_weakenable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _bus_candidate_helpers._authority()
    bus, certificate, allocation, registry, _realization = authority
    prefixes = _bus_candidate_helpers._prefixes(authority)
    ownership = _bus_ir_helpers._ownership(bus)
    target = GroupNegotiationTargetRef(
        target_id="bus:two-member",
        kind=GroupTargetKind.BUS,
        net_names=tuple(member.net_name for member in bus.members),
        bus_fingerprint=bus.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
    )
    policy = BusCandidatePolicy(
        caller_overuse_mode=BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION
    )
    spec = CertifiedBusGroupSearchSpec(
        target=target,
        bus=bus,
        certificate=certificate,
        allocation=allocation,
        geometry_registry=registry,
        prefixes_by_member=prefixes,
        certificate_context=_bus_ir_helpers._context(certificate),
        terminal_ownership=ownership,
        minimum_track_width_mm=DEFAULT_PCB_RULE_PROFILE.geometry.minimum_trace_width_mm,
        candidate_budget=BusCandidateBudget(
            max_members=2,
            max_expansions_per_member=10,
            max_total_expansions=20,
        ),
        candidate_policy=policy,
    )
    prefixes.clear()
    ownership.clear()
    assert set(spec.prefixes_by_member) == {"data0", "data1"}
    assert len(spec.terminal_ownership) == 4
    with pytest.raises(TypeError):
        spec.prefixes_by_member["forged"] = next(iter(spec.prefixes_by_member.values()))  # type: ignore[index]

    weakened = replace(spec, minimum_track_width_mm=0.1)
    layout, netlist = _bus_candidate_helpers._layout_and_netlist()
    calls = 0

    def must_not_route(*_args: Any, **_kwargs: Any) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(group_board, "build_certified_bus_candidate", must_not_route)
    with pytest.raises(ValueError, match="minimum track width is stale"):
        build_mixed_group_candidate(
            layout,
            netlist,
            OccupancyLedger(),
            {},
            (weakened,),
            budget=_budget(),
        )
    assert calls == 0



def test_real_certified_bus_adapter_reports_exact_nested_expansion_work() -> None:
    authority = _bus_candidate_helpers._authority()
    bus, certificate, allocation, registry, _realization = authority
    target = GroupNegotiationTargetRef(
        target_id="bus:two-member",
        kind=GroupTargetKind.BUS,
        net_names=tuple(member.net_name for member in bus.members),
        bus_fingerprint=bus.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
    )
    spec = CertifiedBusGroupSearchSpec(
        target=target,
        bus=bus,
        certificate=certificate,
        allocation=allocation,
        geometry_registry=registry,
        prefixes_by_member=_bus_candidate_helpers._prefixes(authority),
        certificate_context=_bus_ir_helpers._context(certificate),
        terminal_ownership=_bus_ir_helpers._ownership(bus),
        minimum_track_width_mm=DEFAULT_PCB_RULE_PROFILE.geometry.minimum_trace_width_mm,
        candidate_budget=BusCandidateBudget(
            max_members=2,
            max_expansions_per_member=10,
            max_total_expansions=20,
        ),
        candidate_policy=BusCandidatePolicy(
            caller_overuse_mode=BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION
        ),
    )
    layout, netlist = _bus_candidate_helpers._layout_and_netlist()

    result = build_mixed_group_candidate(
        layout,
        netlist,
        OccupancyLedger(),
        {},
        (spec,),
        budget=_budget(),
    )

    assert result.algorithmic_success
    assert len(result.bus_attempts) == 1
    audit = result.bus_attempts[0]
    assert audit.complete and audit.zero_overuse
    assert audit.expansion_count == result.negotiation.total_expansions == 0
    assert result.negotiation.bundle_map()[target.target_id].bus == bus
    assert (
        result.semantic_fingerprint()
        == "b50884166b74fcd0bb5c893a5f7334d73557665fbf7b9444e7e0626a8011d40b"
    )
    assert (
        result.search_bindings[0].binding_fingerprint
        == "ada1869ed2e1f9a339d455889e09f11d05a4dcb65099ec62e11bf9ac1ab79e56"
    )
    assert (
        audit.result_fingerprint
        == "12bcd4ae16550c6138996b54b3c967b4f0b9c65035503d8d97dec4be1db46585"
    )



def test_real_mixed_bus_and_ordinary_commit_has_one_group_exact_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, layout, netlist, _authority = _real_mixed_fixture()
    expected = _install_ordinary_search(monkeypatch, resource_index=900)
    ledger = OccupancyLedger()
    routes: dict[str, NegotiatedGridRoute] = {}
    calls = {"materializer": 0, "checker": 0}

    def materializer(
        static: BoardLayout,
        mixed_routes: dict[str, NegotiatedGridRoute] | Any,
    ) -> BoardLayout:
        calls["materializer"] += 1
        assert set(mixed_routes) == {"/A", "/B", "/N"}
        return materialize_complete_route_map(static, mixed_routes)

    def checker(checked: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls["checker"] += 1
        assert {segment.net_name for segment in checked.segments} == {"/A", "/B", "/N"}
        return ExactRouteCheckResult(True, "mixed-exact")

    result = MixedGroupCheckedCommitCoordinator(ledger, routes).commit(
        layout,
        netlist,
        specs,
        budget=_budget(),
        exact_checker=checker,
        baseline_order=(specs[1].target.target_id, specs[0].target.target_id),
        materializer=materializer,
    )

    assert result.accepted
    assert calls == {"materializer": 1, "checker": 1}
    assert result.materialization_call_count == result.exact_check_call_count == 1
    assert routes["/N"] == expected
    assert len(result.candidate.bus_attempts) == 1


def test_actual_complete_overused_c2_bundle_enters_group_then_converges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, layout, netlist, _authority = _real_mixed_fixture()
    standalone = _bus_candidate_helpers._build(
        policy=BusCandidatePolicy(
            caller_overuse_mode=BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION
        )
    )
    assert standalone.bundle is not None
    collision = min(
        resource
        for route in standalone.bundle.member_routes
        for resource in route.claims.resources
    )
    safe = _resource(999)

    def ordinary_search(*args: Any, **_kwargs: Any) -> NegotiatedGridRoute:
        present_factor_units = args[5]
        resource = collision if present_factor_units == 1 else safe
        return _route("/N", resource)

    monkeypatch.setattr(group_board, "route_net_negotiated_candidate", ordinary_search)
    result = build_mixed_group_candidate(
        layout,
        netlist,
        OccupancyLedger(),
        {},
        specs,
        budget=_budget(),
        baseline_order=(specs[0].target.target_id, specs[1].target.target_id),
    )

    assert result.algorithmic_success
    assert len(result.negotiation.passes) == 2
    assert any(
        audit.complete
        and not audit.zero_overuse
        and audit.failure_reason is BusCandidateFailureReason.FINAL_OVERUSE
        for audit in result.bus_attempts
    )
    assert result.negotiation.resource_overuse == ()
    assert result.negotiation.route_map()["/N"].claims.resources == frozenset((safe,))


@pytest.mark.parametrize("late_target", ["ordinary", "bus"])
def test_late_mixed_search_failure_restores_full_warm_entry_without_exact_work(
    monkeypatch: pytest.MonkeyPatch,
    late_target: str,
) -> None:
    specs, layout, netlist, _authority = _real_mixed_fixture(
        bus_max_members=1 if late_target == "bus" else 2
    )
    standalone = _bus_candidate_helpers._build()
    assert standalone.bundle is not None
    warm_routes = standalone.bundle.by_net()
    warm_routes["/N"] = _route("/N", _resource(700))
    ledger = OccupancyLedger(route.claims for route in warm_routes.values())
    routes = dict(warm_routes)
    before = _before(ledger, routes)
    exact_calls = 0

    if late_target == "ordinary":
        def ordinary_search(*_args: Any, **_kwargs: Any) -> NegotiatedGridRoute:
            raise RoutingError(
                "late ordinary failure",
                reason=RoutingFailureReason.UNROUTABLE,
                expansion_count=0,
            )
        order = (specs[1].target.target_id, specs[0].target.target_id)
    else:
        _install_ordinary_search(monkeypatch, resource_index=701)
        order = (specs[0].target.target_id, specs[1].target.target_id)
        ordinary_search = group_board.route_net_negotiated_candidate
    monkeypatch.setattr(group_board, "route_net_negotiated_candidate", ordinary_search)

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal exact_calls
        exact_calls += 1
        return ExactRouteCheckResult(True, "unreachable")

    result = MixedGroupCheckedCommitCoordinator(ledger, routes).commit(
        layout,
        netlist,
        specs,
        budget=_budget(),
        exact_checker=checker,
        baseline_order=order,
    )

    assert result.exact_disposition is MixedGroupExactDisposition.NEGOTIATION_FAILED
    assert result.materialization_call_count == result.exact_check_call_count == 0
    assert exact_calls == 0
    assert _before(ledger, routes) == before


def test_real_group_and_bus_budget_boundaries_fire_without_hidden_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def expanding(*_args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        calls.append(kwargs["max_expansions"])
        if kwargs["max_expansions"] < 1:
            raise RoutingError(
                "one expansion required",
                reason=RoutingFailureReason.EXPANSION_BUDGET,
                expansion_count=kwargs["max_expansions"],
            )
        return _route("/N", _resource(808))

    monkeypatch.setattr(group_board, "route_net_negotiated_candidate", expanding)
    ledger, routes = _state(False)
    enough = build_mixed_group_candidate(
        _static_layout(),
        _netlist(),
        ledger,
        routes,
        (_spec(),),
        budget=_fixed_group_budget(1),
    )
    one_less = build_mixed_group_candidate(
        _static_layout(),
        _netlist(),
        ledger,
        routes,
        (_spec(),),
        budget=_fixed_group_budget(0),
    )
    assert enough.algorithmic_success and enough.negotiation.total_expansions == 1
    assert not one_less.algorithmic_success and one_less.negotiation.total_expansions == 0
    assert calls == [1, 0]

    valid_spec, layout, netlist, _authority = _real_bus_fixture(max_members=2)
    zero_work = build_mixed_group_candidate(
        layout,
        netlist,
        OccupancyLedger(),
        {},
        (valid_spec,),
        budget=_fixed_group_budget(0),
    )
    short_spec, _layout, _netlist_value, _authority = _real_bus_fixture(max_members=1)
    one_member_short = build_mixed_group_candidate(
        layout,
        netlist,
        OccupancyLedger(),
        {},
        (short_spec,),
        budget=_fixed_group_budget(0),
    )
    assert zero_work.algorithmic_success and zero_work.negotiation.total_expansions == 0
    assert not one_member_short.algorithmic_success
    assert one_member_short.bus_attempts[0].expansion_count == 0



def test_two_real_certified_buses_share_one_group_exact_check() -> None:
    first_spec, _first_layout, _first_netlist, _authority = _real_bus_fixture()
    second_spec, layout, netlist = _second_real_bus_fixture()
    ledger = OccupancyLedger()
    routes: dict[str, NegotiatedGridRoute] = {}
    exact_calls = 0

    def checker(checked: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal exact_calls
        exact_calls += 1
        assert {segment.net_name for segment in checked.segments} == {"/A", "/B", "/C", "/D"}
        return ExactRouteCheckResult(True, "two-bus-exact")

    result = MixedGroupCheckedCommitCoordinator(ledger, routes).commit(
        layout,
        netlist,
        (first_spec, second_spec),
        budget=_budget(),
        exact_checker=checker,
    )

    assert result.accepted
    assert exact_calls == 1
    assert result.materialization_call_count == result.exact_check_call_count == 1
    assert len(result.candidate.bus_attempts) == 2
    assert all(audit.complete and audit.zero_overuse for audit in result.candidate.bus_attempts)
    assert set(routes) == {"/A", "/B", "/C", "/D"}
    assert (
        result.candidate.semantic_fingerprint()
        == "483c41a4f35ab061f9408745aec0a3238413e69d9b93d61383581cbcd1b07cf4"
    )
    assert (
        result.semantic_fingerprint()
        == "7d1b22f6397d95425e2a8c8b8810b1aa53a35f8f3acf457cb18adfde955eff45"
    )
