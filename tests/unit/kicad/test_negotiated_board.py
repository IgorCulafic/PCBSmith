from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import pcbsmith.kicad.clearance_domains as clearance_domains
import pcbsmith.kicad.negotiated_board as negotiated_board
from pcbsmith.kicad.astar_router import RouteResult, RoutingError
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.negotiated_board import (
    ExactRouteCheckEvidence,
    ExactRouteCheckResult,
    board_netlist_fingerprint,
    exact_route_check_report_fingerprint,
    route_board_negotiated,
)
from pcbsmith.kicad.negotiated_graph import CandidateRoute
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.routing_ir import RoutingFailureReason
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    OrdinaryClearanceRequirement,
)

FixtureCandidates = dict[str, tuple[CandidateRoute, ...]]
CandidateSearch = Callable[..., NegotiatedGridRoute]


def _load_fixture(name: str) -> tuple[FixtureCandidates, dict[str, str]]:
    path = Path(__file__).parents[2] / "fixtures" / "routing" / name
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    symbols = sorted(
        {
            symbol
            for net in payload["nets"]
            for candidate in net["candidates"]
            for symbol in candidate["resources"]
        }
    )
    resources = {
        symbol: RoutingResourceKey(
            domain_id=f"board-fixture:{payload['fixture_id']}",
            layer="F.Cu",
            kind="cell",
            ix0=index,
            iy0=0,
        )
        for index, symbol in enumerate(symbols, start=1)
    }
    candidates = {
        net["net_name"]: tuple(
            CandidateRoute(
                net_name=net["net_name"],
                candidate_id=candidate["candidate_id"],
                base_cost_units=candidate["base_cost"],
                resources=frozenset(resources[symbol] for symbol in candidate["resources"]),
            )
            for candidate in net["candidates"]
        )
        for net in payload["nets"]
    }
    return candidates, payload["expected_zero_overuse_assignment"]


def _layout() -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(
            TrackSegment(0.0, 0.0, 1.0, 0.0, "F.Cu", "A"),
            TrackSegment(0.0, 1.0, 1.0, 1.0, "B.Cu", "FIXED"),
        ),
        vias=(
            ViaSpec(0.5, 0.0, "B"),
            ViaSpec(0.5, 1.0, "FIXED"),
        ),
        width_mm=20.0,
        height_mm=10.0,
        parts_row_y_mm=3.25,
        part_y_mm=(("U1", 4.0),),
        part_rotation=(("U1", 90.0),),
        zones=(("FIXED", "B.Cu", (1.0, 1.0, 2.0, 2.0)),),
        outline=((0.0, 0.0), (20.0, 0.0), (20.0, 10.0)),
        graphics=("(gr_text fixed)",),
        part_flip=("U1",),
        hide_references=("U1",),
        part_reference_at=(("U1", (1.0, 2.0, 90.0)),),
    )


def _netlist() -> BoardNetlist:
    return BoardNetlist(components=(), nets=())


def _install_fixture_search(
    monkeypatch: pytest.MonkeyPatch,
    candidates: Mapping[str, tuple[CandidateRoute, ...]],
    *,
    fail_call: int | None = None,
    failure_reason: RoutingFailureReason = RoutingFailureReason.UNROUTABLE,
    failure_expansions: int = 0,
    expansions_per_route: int = 1,
    calls: list[tuple[str, BoardLayout, int]] | None = None,
    domain_calls: list[tuple[Any, ...]] | None = None,
) -> CandidateSearch:
    call_count = 0
    candidate_ordinals = {
        (net_name, route.candidate_id): index
        for net_index, net_name in enumerate(sorted(candidates), start=1)
        for index, route in enumerate(candidates[net_name], start=10 * net_index)
    }

    def fake_search(*args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        nonlocal call_count
        call_count += 1
        static_layout = cast(BoardLayout, args[0])
        net_name = cast(str, args[2])
        ledger = cast(OccupancyLedger, args[3])
        history = cast(Mapping[RoutingResourceKey, int], args[4])
        present_factor = cast(int, args[5])
        expansion_cap = cast(int, kwargs["max_expansions"])
        if calls is not None:
            calls.append((net_name, static_layout, expansion_cap))
        if domain_calls is not None:
            domain_calls.append(cast(tuple[Any, ...], kwargs["pairwise_domains"]))
        if fail_call is not None and call_count == fail_call:
            raise RoutingError(
                f"injected failure for {net_name}",
                reason=failure_reason,
                expansion_count=failure_expansions,
            )
        if expansion_cap < expansions_per_route:
            raise RoutingError(
                f"mock expansion budget exhausted for {net_name}",
                reason=RoutingFailureReason.EXPANSION_BUDGET,
                expansion_count=expansion_cap,
            )

        ranked: list[tuple[tuple[int, int, int, str], CandidateRoute, int]] = []
        for candidate in candidates[net_name]:
            congestion = sum(
                present_factor
                * max(
                    0,
                    ledger.demand_without(resource, net_name) + 1 - ledger.capacity,
                )
                + history.get(resource, 0)
                for resource in candidate.resources
            )
            key = (
                candidate.base_cost_units + congestion,
                congestion,
                candidate.base_cost_units,
                candidate.candidate_id,
            )
            ranked.append((key, candidate, congestion))
        _key, selected, congestion = min(ranked, key=lambda item: item[0])
        ordinal = candidate_ordinals[(net_name, selected.candidate_id)]
        result = RouteResult(
            net_name=net_name,
            segments=(
                TrackSegment(
                    float(ordinal),
                    2.0,
                    float(ordinal) + 0.5,
                    2.0,
                    "F.Cu",
                    net_name,
                ),
            ),
            vias=(),
            length_mm=float(selected.base_cost_units),
            expansion_count=expansions_per_route,
        )
        return NegotiatedGridRoute(
            result=result,
            claims=NetResourceClaims(net_name, selected.resources),
            base_cost_units=selected.base_cost_units,
            congestion_cost_units=congestion,
        )

    monkeypatch.setattr(
        negotiated_board,
        "route_net_negotiated_candidate",
        fake_search,
    )
    monkeypatch.setattr(
        negotiated_board,
        "_routable_nets",
        lambda _layout, _netlist, _profile: {
            name: float(index) for index, name in enumerate(sorted(candidates), start=1)
        },
    )
    return fake_search


def _assignment(result: negotiated_board.NegotiatedBoardRouteResult) -> dict[str, int]:
    return {route.net_name: int(route.segments[0].x1) for route in result.results}


@pytest.mark.parametrize(
    ("fixture_name", "expected_passes"),
    [
        ("first_order_crossed_alternatives.json", 2),
        ("second_order_cascade.json", 5),
    ],
)
def test_board_negotiation_converges_with_truthful_stable_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
    expected_passes: int,
) -> None:
    candidates, expected_candidates = _load_fixture(fixture_name)
    _install_fixture_search(monkeypatch, candidates)

    first = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=tuple(reversed(tuple(candidates))),
    )
    repeated = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=tuple(candidates),
    )

    expected_ordinals = {
        net_name: next(
            index
            for index, route in enumerate(candidates[net_name], start=10 * net_index)
            if route.candidate_id == expected_candidates[net_name]
        )
        for net_index, net_name in enumerate(sorted(candidates), start=1)
    }
    assert first.run_result.success
    assert not first.run_result.accepted
    assert first.run_result.exact_check_accepted is None
    assert first.exact_check is None
    assert first.exact_check_evidence is None
    assert first.checked_netlist is None
    assert first.run_result.resource_overuse == ()
    assert len(first.run_result.passes) == expected_passes
    assert first.run_result.restart_count == expected_passes - 1
    assert first.run_result.semantic_fingerprint() == repeated.run_result.semantic_fingerprint()
    assert first.layout == repeated.layout
    assert tuple(item.net_name for item in first.results) == tuple(sorted(candidates))
    assert _assignment(first) == expected_ordinals
    for routing_pass in first.run_result.passes:
        assert routing_pass.expansion_count == len(candidates)
        assert routing_pass.unresolved_net_names == ()
        assert all(item.routed for item in routing_pass.net_telemetry)
        assert all(item.exact_check_accepted is None for item in routing_pass.net_telemetry)
    assert first.run_result.passes[-1].resource_overuse == first.run_result.resource_overuse


@pytest.mark.parametrize(
    ("fixture_name", "required_passes"),
    [
        ("first_order_crossed_alternatives.json", 2),
        ("second_order_cascade.json", 5),
    ],
)
def test_one_less_pass_returns_exact_final_overuse(
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
    required_passes: int,
) -> None:
    candidates, _expected = _load_fixture(fixture_name)
    _install_fixture_search(monkeypatch, candidates)

    result = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=tuple(candidates),
        max_passes=required_passes - 1,
    )

    assert not result.run_result.success
    assert result.run_result.failure_reason is RoutingFailureReason.PASS_BUDGET
    assert len(result.run_result.passes) == required_passes - 1
    assert result.run_result.resource_overuse
    assert result.run_result.resource_overuse == result.run_result.passes[-1].resource_overuse
    assert sum(item.overuse_units for item in result.run_result.resource_overuse) == 1


def test_zero_patience_stops_after_initial_pass() -> None:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")

    def run(monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fixture_search(monkeypatch, candidates)

    monkeypatch = pytest.MonkeyPatch()
    try:
        run(monkeypatch)
        result = route_board_negotiated(
            _layout(),
            _netlist(),
            target_nets=tuple(candidates),
            max_stagnant_passes=0,
        )
    finally:
        monkeypatch.undo()

    assert result.run_result.failure_reason is RoutingFailureReason.OVERUSE_REMAINING
    assert len(result.run_result.passes) == 1
    assert result.run_result.resource_overuse


def test_reroute_failure_restores_complete_old_route_and_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")
    _install_fixture_search(
        monkeypatch,
        candidates,
        fail_call=3,
        failure_reason=RoutingFailureReason.UNROUTABLE,
        failure_expansions=2,
    )

    result = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=tuple(candidates),
    )

    assert not result.run_result.success
    assert result.run_result.failure_reason is RoutingFailureReason.UNROUTABLE
    assert len(result.run_result.passes) == 2
    assert result.run_result.passes[-1].net_telemetry[0].routed is False
    assert result.run_result.unresolved_net_names == ()
    assert result.run_result.resource_overuse == result.run_result.passes[0].resource_overuse
    assert tuple(item.net_name for item in result.results) == ("A", "B")
    assert all(len(item.segments) == 1 for item in result.results)


def test_static_strip_preserves_non_target_geometry_and_never_accumulates_stale_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")
    calls: list[tuple[str, BoardLayout, int]] = []
    _install_fixture_search(monkeypatch, candidates, calls=calls)
    original = _layout()

    result = route_board_negotiated(
        original,
        _netlist(),
        target_nets=("A", "B"),
    )

    assert calls
    assert all(call_layout is calls[0][1] for _, call_layout, _ in calls)
    static = calls[0][1]
    assert static.segments == (original.segments[1],)
    assert static.vias == (original.vias[1],)
    for field in original.__dataclass_fields__:
        if field not in {"segments", "vias"}:
            assert getattr(static, field) == getattr(original, field)
            assert getattr(result.layout, field) == getattr(original, field)
    assert result.layout.segments[0] == original.segments[1]
    assert result.layout.vias == (original.vias[1],)
    assert len(result.layout.segments) == 1 + len(candidates)
    assert sum(segment.net_name == "A" for segment in result.layout.segments) == 1
    assert sum(segment.net_name == "B" for segment in result.layout.segments) == 1


@pytest.mark.parametrize(
    ("max_total", "max_per_net", "expected_calls", "expected_unresolved"),
    [
        (1, 10, 2, ("B",)),
        (10, 0, 1, ("A", "B")),
    ],
)
def test_total_and_per_net_expansion_caps_stop_before_excess_work(
    monkeypatch: pytest.MonkeyPatch,
    max_total: int,
    max_per_net: int,
    expected_calls: int,
    expected_unresolved: tuple[str, ...],
) -> None:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")
    calls: list[tuple[str, BoardLayout, int]] = []
    _install_fixture_search(monkeypatch, candidates, calls=calls)

    result = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=("A", "B"),
        max_expansions=max_total,
        max_expansions_per_net=max_per_net,
    )

    assert result.run_result.failure_reason is RoutingFailureReason.EXPANSION_BUDGET
    assert len(calls) == expected_calls
    assert result.run_result.unresolved_net_names == expected_unresolved
    assert (
        sum(routing_pass.expansion_count for routing_pass in result.run_result.passes) <= max_total
    )


@pytest.mark.parametrize("accepted", [True, False])
def test_exact_checker_accept_and_reject_are_separate_from_algorithmic_success(
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool,
) -> None:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")
    _install_fixture_search(monkeypatch, candidates)
    checked: list[BoardLayout] = []

    def checker(layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        checked.append(layout)
        return ExactRouteCheckResult(
            accepted=accepted,
            checker_id="unit-exact",
            finding_fingerprints=("z", "a", "z"),
        )

    result = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=("A", "B"),
        exact_checker=checker,
    )

    assert result.run_result.success
    assert result.run_result.failure_reason is None
    assert result.run_result.exact_check_accepted is accepted
    assert result.run_result.accepted is accepted
    assert result.exact_check == ExactRouteCheckResult(
        accepted=accepted,
        checker_id="unit-exact",
        finding_fingerprints=("a", "z"),
    )
    assert checked == [result.layout]


def test_exact_checker_is_not_called_before_zero_overuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")
    _install_fixture_search(monkeypatch, candidates)
    calls = 0

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal calls
        calls += 1
        return ExactRouteCheckResult(True, "should-not-run")

    result = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=("A", "B"),
        max_passes=1,
        exact_checker=checker,
    )

    assert not result.run_result.success
    assert calls == 0
    assert result.exact_check is None
    assert result.exact_check_evidence is None
    assert result.checked_netlist is None
    assert result.run_result.exact_check_accepted is None


def test_zero_expansion_cap_allows_an_already_connected_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")
    only_a = {"A": candidates["A"]}
    calls: list[tuple[str, BoardLayout, int]] = []
    _install_fixture_search(
        monkeypatch,
        only_a,
        expansions_per_route=0,
        calls=calls,
    )

    result = route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=("A",),
        max_expansions=0,
        max_expansions_per_net=0,
    )

    assert result.run_result.success
    assert calls[0][2] == 0
    assert result.run_result.passes[0].expansion_count == 0


def test_grid_receives_fab_qualified_and_caller_pairwise_domains_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")
    domain_calls: list[tuple[Any, ...]] = []
    _install_fixture_search(monkeypatch, candidates, domain_calls=domain_calls)
    fab_requirement = OrdinaryClearanceRequirement(
        requirement_id="fab-pair",
        nets_a=("A",),
        nets_b=("B",),
        minimum_clearance_mm=0.7,
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"pairwise_clearances": (fab_requirement,)}
            )
        }
    )
    monkeypatch.setattr(
        clearance_domains,
        "qualified_insulation_clearance_groups",
        lambda _profile: (("qualified-pair", ("A",), ("B",), 0.8, ()),),
    )

    route_board_negotiated(
        _layout(),
        _netlist(),
        target_nets=("A", "B"),
        profile=profile,
        clearance_groups=((("A",), ("B",), 0.9, ()),),
    )

    assert domain_calls
    assert all(domains is domain_calls[0] for domains in domain_calls)
    requirement_ids = {domain.requirement_id for domain in domain_calls[0]}
    assert "fab-pair" in requirement_ids
    assert "qualified-insulation:qualified-pair" in requirement_ids
    assert len([item for item in requirement_ids if item.startswith("caller-clearance:")]) == 1


def test_real_grid_single_net_board_smoke() -> None:
    footprint = "Resistor_SMD:R_0603_1608Metric"
    components = (
        BoardComponent("R1", "1k", footprint, "r1"),
        BoardComponent("R2", "1k", footprint, "r2"),
    )
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet("/SIG", (("R1", "2"), ("R2", "1"))),
            BoardNet("/A", (("R1", "1"),)),
            BoardNet("/B", (("R2", "2"),)),
        ),
    )
    layout = BoardLayout(
        placements=((components[0], 5.0), (components[1], 25.0)),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
        part_y_mm=(("R1", 6.0), ("R2", 6.0)),
    )

    result = route_board_negotiated(
        layout,
        netlist,
        target_nets=("/SIG",),
        grid_mm=1.0,
        net_widths={"/SIG": 0.4},
        max_expansions=20_000,
        max_expansions_per_net=20_000,
    )

    assert result.run_result.success
    assert result.order == ("/SIG",)
    assert len(result.results) == 1
    assert result.results[0].segments
    assert result.run_result.resource_overuse == ()


def _rich_netlist() -> BoardNetlist:
    components = (
        BoardComponent("R2", "2k", "R_0603", "uuid-r2", (("Tolerance", "1%"),)),
        BoardComponent(
            "R1",
            "1k",
            "R_0402",
            "uuid-r1",
            (("Vendor", "A"), ("MPN", "one")),
        ),
    )
    return BoardNetlist(
        components=components,
        nets=(
            BoardNet("/B", (("R2", "2"), ("R1", "1"))),
            BoardNet("/A", (("R2", "1"),)),
        ),
    )


def _run_with_exact_checker(
    monkeypatch: pytest.MonkeyPatch,
    checker: negotiated_board.ExactRouteChecker,
    *,
    layout: BoardLayout | None = None,
    netlist: BoardNetlist | None = None,
) -> negotiated_board.NegotiatedBoardRouteResult:
    candidates, _expected = _load_fixture("first_order_crossed_alternatives.json")
    _install_fixture_search(monkeypatch, candidates)
    return route_board_negotiated(
        _layout() if layout is None else layout,
        _netlist() if netlist is None else netlist,
        target_nets=("A", "B"),
        exact_checker=checker,
    )


def test_board_netlist_fingerprint_is_complete_and_order_canonical() -> None:
    source = _rich_netlist()
    reordered = BoardNetlist(
        components=tuple(reversed(source.components)),
        nets=tuple(BoardNet(net.name, tuple(reversed(net.nodes))) for net in reversed(source.nets)),
    )
    fingerprint = board_netlist_fingerprint(source)

    assert board_netlist_fingerprint(reordered) == fingerprint
    first = source.components[0]
    for changed in (
        replace(first, reference="R9"),
        replace(first, value="3k"),
        replace(first, footprint="R_0201"),
        replace(first, uuid_path="uuid-other"),
        replace(first, fields=(("Tolerance", "5%"),)),
    ):
        assert (
            board_netlist_fingerprint(replace(source, components=(changed, *source.components[1:])))
            != fingerprint
        )
    assert (
        board_netlist_fingerprint(
            replace(source, nets=(replace(source.nets[0], name="/C"), *source.nets[1:]))
        )
        != fingerprint
    )
    assert (
        board_netlist_fingerprint(
            replace(
                source,
                nets=(replace(source.nets[0], nodes=(("R2", "3"),)), *source.nets[1:]),
            )
        )
        != fingerprint
    )


@pytest.mark.parametrize("accepted", [True, False])
def test_exact_checker_retains_replayable_evidence_and_detached_inputs(
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool,
) -> None:
    original_layout = _layout()
    original_netlist = _rich_netlist()
    calls: list[tuple[BoardLayout, BoardNetlist]] = []

    def checker(layout: BoardLayout, netlist: BoardNetlist) -> ExactRouteCheckResult:
        calls.append((layout, netlist))
        return ExactRouteCheckResult(
            accepted,
            "unit-exact-evidence",
            ("finding-z", "finding-a", "finding-z"),
        )

    result = _run_with_exact_checker(
        monkeypatch,
        checker,
        layout=original_layout,
        netlist=original_netlist,
    )

    assert len(calls) == 1
    checked_layout, checked_netlist = calls[0]
    assert checked_layout == result.layout
    assert checked_layout is not result.layout
    assert checked_layout is not original_layout
    assert checked_netlist == original_netlist
    assert checked_netlist is not original_netlist
    assert result.checked_netlist == original_netlist
    assert result.checked_netlist is not original_netlist
    assert result.checked_netlist is not checked_netlist
    assert result.exact_check is not None
    assert result.exact_check.finding_fingerprints == ("finding-a", "finding-z")
    evidence = result.exact_check_evidence
    assert evidence is not None
    assert evidence.accepted is accepted
    assert evidence.checker_id == result.exact_check.checker_id
    assert evidence.finding_identities == result.exact_check.finding_fingerprints
    assert evidence.materialized_layout_fingerprint == negotiated_board.board_layout_fingerprint(
        result.layout
    )
    assert evidence.checked_netlist_fingerprint == board_netlist_fingerprint(original_netlist)
    assert evidence.report_fingerprint == exact_route_check_report_fingerprint(result.exact_check)


def test_exact_result_reconstruction_fails_closed_on_every_stale_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_with_exact_checker(
        monkeypatch,
        lambda _layout, _netlist: ExactRouteCheckResult(
            True, "unit-replay", ("finding-b", "finding-a")
        ),
        netlist=_rich_netlist(),
    )
    report = cast(ExactRouteCheckResult, result.exact_check)
    evidence = cast(ExactRouteCheckEvidence, result.exact_check_evidence)
    checked_netlist = cast(BoardNetlist, result.checked_netlist)

    assert replace(result) == result
    with pytest.raises(ValueError, match="materialized layout"):
        replace(result, layout=replace(result.layout, width_mm=result.layout.width_mm + 1.0))
    with pytest.raises(ValueError, match="checked netlist"):
        replace(
            result,
            checked_netlist=replace(
                checked_netlist,
                nets=(*checked_netlist.nets, BoardNet("/STALE", ())),
            ),
        )
    with pytest.raises(ValueError, match="run verdict"):
        replace(
            result,
            run_result=result.run_result.model_copy(
                update={"exact_check_accepted": not report.accepted}
            ),
        )
    with pytest.raises(ValueError, match="checker IDs"):
        replace(
            result,
            exact_check_evidence=ExactRouteCheckEvidence.from_exact_check(
                result.layout,
                checked_netlist,
                ExactRouteCheckResult(True, "different-checker", report.finding_fingerprints),
            ),
        )
    with pytest.raises(ValueError, match="findings"):
        replace(
            result,
            exact_check=ExactRouteCheckResult(True, report.checker_id, ("different-finding",)),
        )
    with pytest.raises(ValueError, match="finding identity fingerprint"):
        replace(evidence, finding_identities_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="report fingerprint"):
        replace(evidence, report_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="call input fingerprint"):
        replace(evidence, call_input_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="unsupported"):
        replace(evidence, schema_version=2)


@pytest.mark.parametrize("target", ["layout", "netlist"])
@pytest.mark.parametrize("raises_after_mutation", [False, True])
def test_exact_checker_mutation_takes_precedence_and_preserves_caller_inputs(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    raises_after_mutation: bool,
) -> None:
    original_layout = _layout()
    original_netlist = _rich_netlist()
    layout_before = negotiated_board.board_layout_fingerprint(original_layout)
    netlist_before = board_netlist_fingerprint(original_netlist)
    calls = 0

    def checker(layout: BoardLayout, netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal calls
        calls += 1
        if target == "layout":
            object.__setattr__(layout, "width_mm", layout.width_mm + 1.0)
        else:
            object.__setattr__(netlist, "nets", (*netlist.nets, BoardNet("/MUTATED", ())))
        if raises_after_mutation:
            raise RuntimeError("callback failure must lose to mutation")
        return ExactRouteCheckResult(True, "mutating-checker")

    with pytest.raises(ValueError, match="mutated bound input"):
        _run_with_exact_checker(
            monkeypatch,
            checker,
            layout=original_layout,
            netlist=original_netlist,
        )

    assert calls == 1
    assert negotiated_board.board_layout_fingerprint(original_layout) == layout_before
    assert board_netlist_fingerprint(original_netlist) == netlist_before


def test_exact_checker_wrong_type_and_bypassed_invalid_report_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TypeError, match="must return ExactRouteCheckResult"):
        _run_with_exact_checker(monkeypatch, cast(negotiated_board.ExactRouteChecker, lambda *_: 7))

    invalid = object.__new__(ExactRouteCheckResult)
    object.__setattr__(invalid, "accepted", True)
    object.__setattr__(invalid, "checker_id", "bypassed")
    object.__setattr__(invalid, "finding_fingerprints", ("z", "a"))
    with pytest.raises(ValueError, match="non-canonical report"):
        _run_with_exact_checker(monkeypatch, lambda *_: invalid)


def test_exact_checker_ordinary_exception_is_reraised_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def checker(_layout: BoardLayout, _netlist: BoardNetlist) -> ExactRouteCheckResult:
        nonlocal calls
        calls += 1
        raise LookupError("ordinary checker failure")

    with pytest.raises(LookupError, match="ordinary checker failure"):
        _run_with_exact_checker(monkeypatch, checker, netlist=_rich_netlist())
    assert calls == 1
