from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

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
from pcbsmith.kicad.negotiated_board import route_board_negotiated
from pcbsmith.kicad.negotiated_grid import (
    NegotiatedGridRoute,
    ordinary_claim_domain,
    route_net_negotiated_candidate,
)
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
    capsule_segment_claims,
    via_claims,
)
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.routing_ir import RoutingFailureReason

GRID_MM = 1.0
TRACK_WIDTH_MM = 0.4
RESISTOR = "Resistor_SMD:R_0603_1608Metric"


def _fixture(*, back_second: bool = False) -> tuple[BoardLayout, BoardNetlist]:
    components = (
        BoardComponent("R1", "1k", RESISTOR, "r1"),
        BoardComponent("R2", "1k", RESISTOR, "r2"),
    )
    return (
        BoardLayout(
            placements=((components[0], 5.0), (components[1], 25.0)),
            segments=(),
            vias=(),
            width_mm=30.0,
            height_mm=12.0,
            part_y_mm=(("R1", 6.0), ("R2", 6.0)),
            part_flip=(("R2",) if back_second else ()),
        ),
        BoardNetlist(
            components=components,
            nets=(
                BoardNet("/SIG", (("R1", "2"), ("R2", "1"))),
                BoardNet("/A", (("R1", "1"),)),
                BoardNet("/B", (("R2", "2"),)),
            ),
        ),
    )


def _front_prefix(*, source_id: str = "pad:R1:1", width_mm: float = 0.4) -> GridRoutePrefix:
    return GridRoutePrefix(
        alternative_id="front-exit",
        net_name="/SIG",
        grid_mm=GRID_MM,
        exit_node=("F.Cu", 10, 6),
        covered_pad_anchors=((source_id, ("F.Cu", 6, 6)),),
        segments=(TrackSegment(6.0, 6.0, 10.0, 6.0, "F.Cu", "/SIG", width_mm),),
    )


def _back_prefix() -> GridRoutePrefix:
    return GridRoutePrefix(
        alternative_id="back-exit",
        net_name="/SIG",
        grid_mm=GRID_MM,
        exit_node=("B.Cu", 12, 6),
        covered_pad_anchors=(("pad:R1:1", ("F.Cu", 6, 6)),),
        segments=(
            TrackSegment(6.0, 6.0, 10.0, 6.0, "F.Cu", "/SIG", TRACK_WIDTH_MM),
            TrackSegment(10.0, 6.0, 12.0, 6.0, "B.Cu", "/SIG", TRACK_WIDTH_MM),
        ),
        vias=(ViaSpec(10.0, 6.0, "/SIG", 0.6, 0.3),),
    )


def _candidate(
    prefix: GridRoutePrefix,
    *,
    ledger: OccupancyLedger | None = None,
    history: Mapping[RoutingResourceKey, int] | None = None,
    present_factor: int = 0,
    max_expansions: int | None = None,
) -> NegotiatedGridRoute:
    layout, netlist = _fixture(back_second=prefix.alternative_id == "back-exit")
    return route_net_negotiated_candidate(
        layout,
        netlist,
        "/SIG",
        ledger or OccupancyLedger(),
        history or {},
        present_factor,
        track_width_mm=TRACK_WIDTH_MM,
        grid_mm=GRID_MM,
        max_expansions=(20_000 if max_expansions is None else max_expansions),
        route_prefix=prefix,
    )


def _front_prefix_resources() -> frozenset[RoutingResourceKey]:
    domain = ordinary_claim_domain(TRACK_WIDTH_MM)
    return capsule_segment_claims(
        domain.domain_id,
        "F.Cu",
        (6.0, 6.0),
        (10.0, 6.0),
        GRID_MM,
        domain.track_halo_radius_mm,
    )


def test_prefix_and_area_emit_one_geometry_and_claim_union_with_audit_identity() -> None:
    prefix = _front_prefix()
    candidate = _candidate(prefix)
    prefix_resources = _front_prefix_resources()

    assert prefix_resources <= candidate.claims.resources
    assert any(
        segment.layer == "F.Cu"
        and min(segment.x1, segment.x2) <= 6.0
        and max(segment.x1, segment.x2) >= 10.0
        for segment in candidate.result.segments
    )
    assert candidate.prefix_alternative_id == prefix.alternative_id
    assert candidate.prefix_fingerprint == prefix.semantic_fingerprint()
    assert len(candidate.claims.resources) == len(set(candidate.claims.resources))


def test_prefix_exit_layer_and_bound_via_survive_combined_candidate() -> None:
    prefix = _back_prefix()
    candidate = _candidate(prefix)
    domain = ordinary_claim_domain(TRACK_WIDTH_MM)
    bound_via_claims = via_claims(
        domain.domain_id,
        10,
        6,
        GRID_MM,
        domain.via_halo_radius_mm,
    )

    assert ViaSpec(10.0, 6.0, "/SIG", 0.6, 0.3) in candidate.result.vias
    assert bound_via_claims <= candidate.claims.resources
    assert any(segment.layer == "B.Cu" for segment in candidate.result.segments)


def test_prefix_congestion_and_history_are_charged_once() -> None:
    prefix = _front_prefix()
    resources = _front_prefix_resources()
    ledger = OccupancyLedger((NetResourceClaims("/OTHER", resources),))
    history = {resource: 11 for resource in resources}

    candidate = _candidate(
        prefix,
        ledger=ledger,
        history=history,
        present_factor=7,
    )

    assert candidate.congestion_cost_units == len(resources) * 18
    assert ledger.claims_for("/SIG").resources == frozenset()


def test_valid_prefix_area_failure_is_not_retried_without_prefix() -> None:
    with pytest.raises(RoutingError) as caught:
        _candidate(_front_prefix(), max_expansions=0)

    assert caught.value.reason is RoutingFailureReason.EXPANSION_BUDGET
    assert caught.value.expansion_count == 0


@pytest.mark.parametrize(
    "prefix",
    (
        _front_prefix(source_id="unknown-pad"),
        _front_prefix(width_mm=0.3),
    ),
)
def test_candidate_rejects_invalid_prefix_binding(prefix: GridRoutePrefix) -> None:
    with pytest.raises(ValueError, match="route prefix"):
        _candidate(prefix)


def _board_prefix(net_name: str = "A") -> GridRoutePrefix:
    return GridRoutePrefix(
        alternative_id="board-prefix",
        net_name=net_name,
        grid_mm=1.0,
        exit_node=("F.Cu", 1, 1),
        covered_pad_anchors=(("synthetic-pad", ("F.Cu", 0, 1)),),
        segments=(TrackSegment(0.0, 1.0, 1.0, 1.0, "F.Cu", net_name, 0.4),),
    )


def _transaction_fixture_search(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_replacement: bool,
    prefix_calls: list[tuple[str, GridRoutePrefix | None]],
) -> None:
    shared = RoutingResourceKey("tx", "F.Cu", "cell", 1, 1)
    old_prefix = RoutingResourceKey("tx", "F.Cu", "cell", 2, 1)
    new_prefix = RoutingResourceKey("tx", "F.Cu", "cell", 3, 1)
    other = RoutingResourceKey("tx", "F.Cu", "cell", 4, 1)
    calls: dict[str, int] = {"A": 0, "B": 0}

    def fake_search(*args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        net_name = cast(str, args[2])
        calls[net_name] += 1
        prefix = cast(GridRoutePrefix | None, kwargs["route_prefix"])
        prefix_calls.append((net_name, prefix))
        if fail_replacement and net_name == "A" and calls[net_name] == 2:
            raise RoutingError("injected prefix+area replacement failure")
        if net_name == "A" and calls[net_name] > 1:
            resources = frozenset((new_prefix,))
            marker = 20.0
        elif net_name == "A":
            resources = frozenset((shared, old_prefix))
            marker = 10.0
        else:
            resources = frozenset((shared, other))
            marker = 30.0
        result = RouteResult(
            net_name=net_name,
            segments=(TrackSegment(marker, 2.0, marker + 1.0, 2.0, "F.Cu", net_name),),
            vias=(),
            length_mm=1.0,
            expansion_count=1,
        )
        return NegotiatedGridRoute(
            result=result,
            claims=NetResourceClaims(net_name, resources),
            base_cost_units=1,
            congestion_cost_units=0,
            prefix_alternative_id=(prefix.alternative_id if prefix is not None else None),
            prefix_fingerprint=(prefix.semantic_fingerprint() if prefix is not None else None),
        )

    monkeypatch.setattr(negotiated_board, "route_net_negotiated_candidate", fake_search)
    monkeypatch.setattr(
        negotiated_board,
        "_routable_nets",
        lambda _layout, _netlist, _profile: {"A": 1.0, "B": 2.0},
    )


def _empty_board() -> tuple[BoardLayout, BoardNetlist]:
    return (
        BoardLayout(placements=(), segments=(), vias=(), width_mm=40.0, height_mm=10.0),
        BoardNetlist(components=(), nets=()),
    )


def test_board_replacement_and_failure_restore_are_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = _board_prefix()
    layout, netlist = _empty_board()
    successful_calls: list[tuple[str, GridRoutePrefix | None]] = []
    _transaction_fixture_search(
        monkeypatch,
        fail_replacement=False,
        prefix_calls=successful_calls,
    )

    success = route_board_negotiated(
        layout,
        netlist,
        route_prefixes={"A": prefix},
        max_passes=3,
    )

    assert success.run_result.success
    assert next(result for result in success.results if result.net_name == "A").segments[0].x1 == 20
    assert success.prefix_bindings[0].prefix_fingerprint == prefix.semantic_fingerprint()
    assert all(item is prefix for name, item in successful_calls if name == "A")
    assert all(item is None for name, item in successful_calls if name == "B")

    monkeypatch.undo()
    failed_calls: list[tuple[str, GridRoutePrefix | None]] = []
    _transaction_fixture_search(
        monkeypatch,
        fail_replacement=True,
        prefix_calls=failed_calls,
    )
    failed = route_board_negotiated(
        layout,
        netlist,
        route_prefixes={"A": prefix},
        max_passes=3,
    )

    assert not failed.run_result.success
    assert next(result for result in failed.results if result.net_name == "A").segments[0].x1 == 10
    assert failed.prefix_bindings[0].prefix_fingerprint == prefix.semantic_fingerprint()
    assert failed.run_result.resource_overuse[0].net_names == ("A", "B")
    assert all(item is prefix for name, item in failed_calls if name == "A")


def test_board_rejects_prefix_outside_computed_route_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _empty_board()
    monkeypatch.setattr(
        negotiated_board,
        "_routable_nets",
        lambda _layout, _netlist, _profile: {"A": 1.0},
    )

    with pytest.raises(ValueError, match="outside the computed route order"):
        route_board_negotiated(layout, netlist, route_prefixes={"B": _board_prefix("B")})
