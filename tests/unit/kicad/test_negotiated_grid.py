"""R2.2b per-net negotiated search on the production KiCad grid."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from pcbsmith.kicad.astar_router import RoutingError, route_net
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
)
from pcbsmith.kicad.negotiated_grid import (
    GridNode,
    GridSoftGuide,
    NegotiatedGridRoute,
    ordinary_claim_domain,
    route_net_negotiated_candidate,
)
from pcbsmith.kicad.negotiated_resources import (
    LayerName,
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
    capsule_segment_claims,
    via_claims,
)
from pcbsmith.routing_ir import RoutingFailureReason

GRID_MM = 1.0
TRACK_WIDTH_MM = 0.4
RESISTOR = "Resistor_SMD:R_0603_1608Metric"


def _fixture() -> tuple[BoardLayout, BoardNetlist]:
    components = (
        BoardComponent("R1", "1k", RESISTOR, "r1"),
        BoardComponent("R2", "1k", RESISTOR, "r2"),
    )
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet("/SIG", (("R1", "2"), ("R2", "1"))),
            BoardNet("/A", (("R1", "1"),)),
            BoardNet("/B", (("R2", "2"),)),
        ),
    )
    return (
        BoardLayout(
            placements=((components[0], 5.0), (components[1], 25.0)),
            segments=(),
            vias=(),
            width_mm=30.0,
            height_mm=12.0,
            part_y_mm=(("R1", 6.0), ("R2", 6.0)),
        ),
        netlist,
    )


def _candidate(
    *,
    ledger: OccupancyLedger | None = None,
    history: dict[RoutingResourceKey, int] | None = None,
    present_factor_units: int = 0,
    max_expansions: int | None = None,
    soft_guide: GridSoftGuide | None = None,
    fixture: tuple[BoardLayout, BoardNetlist] | None = None,
) -> NegotiatedGridRoute:
    layout, netlist = fixture or _fixture()
    return route_net_negotiated_candidate(
        layout,
        netlist,
        "/SIG",
        ledger or OccupancyLedger(),
        history or {},
        present_factor_units,
        track_width_mm=TRACK_WIDTH_MM,
        grid_mm=GRID_MM,
        max_expansions=max_expansions,
        soft_guide=soft_guide,
    )


def _soft_guide(
    waypoints: tuple[GridNode, ...],
    *,
    penalty: int,
) -> GridSoftGuide:
    nodes: set[GridNode] = set()
    transitions: set[tuple[GridNode, GridNode]] = set()
    via_cells: set[tuple[int, int]] = set()
    for start, end in zip(waypoints, waypoints[1:], strict=False):
        nodes.add(start)
        nodes.add(end)
        if start[0] != end[0]:
            assert start[1:] == end[1:]
            via_cells.add(start[1:])
            continue
        dx = (end[1] > start[1]) - (end[1] < start[1])
        dy = (end[2] > start[2]) - (end[2] < start[2])
        assert dx == 0 or dy == 0 or abs(end[1] - start[1]) == abs(end[2] - start[2])
        current = start
        while current != end:
            following = (current[0], current[1] + dx, current[2] + dy)
            nodes.add(following)
            transitions.add((current, following))
            current = following
    return GridSoftGuide(
        grid_mm=GRID_MM,
        allowed_track_nodes=frozenset(nodes),
        allowed_track_transitions=frozenset(transitions),
        allowed_via_cells=frozenset(via_cells),
        off_guide_transition_cost_units=penalty,
    )


def _middle_resources(
    resources: frozenset[RoutingResourceKey],
) -> frozenset[RoutingResourceKey]:
    return frozenset(
        resource
        for resource in resources
        if resource.domain_id == "ordinary"
        and resource.layer == "F.Cu"
        and 11.0 <= resource.ix0 * GRID_MM <= 19.0
    )


def test_no_congestion_matches_legacy_direct_geometry_and_is_deterministic() -> None:
    layout, netlist = _fixture()
    legacy_before = route_net(
        layout,
        netlist,
        "/SIG",
        track_width_mm=TRACK_WIDTH_MM,
        grid_mm=GRID_MM,
    )

    first = _candidate()
    second = _candidate()
    legacy_after = route_net(
        layout,
        netlist,
        "/SIG",
        track_width_mm=TRACK_WIDTH_MM,
        grid_mm=GRID_MM,
    )

    assert first == second
    assert first.result.segments == legacy_before.segments
    assert first.result.vias == legacy_before.vias
    assert legacy_after == legacy_before
    assert first.claims.resources


def test_soft_preclaim_shares_at_zero_cost_without_mutating_ledger() -> None:
    direct = _candidate()
    occupied = _middle_resources(direct.claims.resources)
    assert occupied
    ledger = OccupancyLedger((NetResourceClaims("/OTHER", occupied),))
    before = ledger.semantic_fingerprint()

    shared = _candidate(ledger=ledger)

    assert shared.claims.resources & occupied
    assert ledger.semantic_fingerprint() == before
    assert ledger.overuse() == ()
    ledger.commit(shared.claims)
    assert ledger.overuse()


def test_high_present_and_history_cost_choose_longer_zero_overuse_detour() -> None:
    direct = _candidate()
    occupied = _middle_resources(direct.claims.resources)
    ledger = OccupancyLedger((NetResourceClaims("/OTHER", occupied),))
    before = ledger.semantic_fingerprint()
    history = {resource: 100_000 for resource in sorted(occupied)}

    detour = _candidate(
        ledger=ledger,
        history=history,
        present_factor_units=100_000,
    )
    repeated = _candidate(
        ledger=ledger,
        history=dict(reversed(tuple(history.items()))),
        present_factor_units=100_000,
    )

    assert detour == repeated
    assert detour.result.length_mm > direct.result.length_mm
    assert detour.claims.resources.isdisjoint(occupied)
    assert ledger.semantic_fingerprint() == before
    ledger.commit(detour.claims)
    assert ledger.overuse() == ()


def test_history_alone_can_steer_away_from_unoccupied_resources() -> None:
    direct = _candidate()
    discouraged = _middle_resources(direct.claims.resources)

    detour = _candidate(
        history={resource: 100_000 for resource in discouraged},
    )

    assert detour.result.length_mm > direct.result.length_mm
    assert detour.claims.resources.isdisjoint(discouraged)
    assert detour.congestion_cost_units == 0


def test_final_claims_reconstruct_every_emitted_segment_and_via() -> None:
    candidate = _candidate()
    domain = ordinary_claim_domain(TRACK_WIDTH_MM)
    expected: set[RoutingResourceKey] = set()

    for segment in candidate.result.segments:
        expected.update(
            capsule_segment_claims(
                domain.domain_id,
                cast(LayerName, segment.layer),
                (segment.x1, segment.y1),
                (segment.x2, segment.y2),
                GRID_MM,
                domain.track_halo_radius_mm,
            )
        )
    for via in candidate.result.vias:
        expected.update(
            via_claims(
                domain.domain_id,
                round(via.x / GRID_MM),
                round(via.y / GRID_MM),
                GRID_MM,
                domain.via_halo_radius_mm,
            )
        )

    assert candidate.claims.resources == frozenset(expected)


def test_zero_expansion_budget_is_a_typed_failure() -> None:
    with pytest.raises(RoutingError) as caught:
        _candidate(max_expansions=0)

    assert caught.value.reason is RoutingFailureReason.EXPANSION_BUDGET
    assert caught.value.expansion_count == 0


def test_zero_penalty_guide_is_exactly_identical_to_unguided_search() -> None:
    guide = GridSoftGuide(
        grid_mm=GRID_MM,
        allowed_track_nodes=frozenset(),
        allowed_track_transitions=frozenset(),
        allowed_via_cells=frozenset(),
        off_guide_transition_cost_units=0,
    )

    assert _candidate(soft_guide=guide) == _candidate()


def test_positive_soft_cost_steers_to_longer_preferred_track_path() -> None:
    direct = _candidate()
    guide = _soft_guide(
        (
            ("F.Cu", 6, 6),
            ("F.Cu", 6, 8),
            ("F.Cu", 24, 8),
            ("F.Cu", 24, 6),
        ),
        penalty=1_000,
    )

    guided = _candidate(soft_guide=guide)

    assert guided.result.length_mm > direct.result.length_mm
    assert any(segment.y1 == segment.y2 == 8.0 for segment in guided.result.segments)
    assert guided.guidance_cost_units == 0


def test_soft_guide_does_not_prevent_escape_around_hard_obstacle() -> None:
    guide = _soft_guide(
        (
            ("F.Cu", 6, 6),
            ("F.Cu", 6, 0),
            ("F.Cu", 24, 0),
            ("F.Cu", 24, 6),
        ),
        penalty=1,
    )

    escaped = _candidate(soft_guide=guide)

    assert escaped.result.segments
    assert escaped.guidance_cost_units > 0


def test_layer_specific_track_and_via_permissions_steer_to_back_copper() -> None:
    guide = _soft_guide(
        (
            ("F.Cu", 6, 6),
            ("B.Cu", 6, 6),
            ("B.Cu", 24, 6),
            ("F.Cu", 24, 6),
        ),
        penalty=1_000,
    )

    guided = _candidate(soft_guide=guide)

    assert len(guided.result.vias) == 2
    assert any(segment.layer == "B.Cu" for segment in guided.result.segments)
    assert guided.guidance_cost_units == 0


def test_adjacent_allowed_nodes_still_pay_for_unlisted_transition() -> None:
    complete = _soft_guide(
        (("F.Cu", 6, 6), ("F.Cu", 24, 6)),
        penalty=1,
    )
    omitted = tuple(
        transition
        for transition in complete.allowed_track_transitions
        if frozenset(transition) != frozenset((("F.Cu", 14, 6), ("F.Cu", 15, 6)))
    )
    guide = replace(
        complete,
        allowed_track_transitions=frozenset(omitted),
    )

    guided = _candidate(soft_guide=guide)

    assert guided.result == _candidate().result
    assert guided.guidance_cost_units == 1


def test_pad_stub_cost_is_not_counted_as_off_guide_search_cost() -> None:
    guide = _soft_guide(
        (("F.Cu", 6, 6), ("F.Cu", 24, 6)),
        penalty=1_000,
    )

    guided = _candidate(soft_guide=guide)

    assert guided.base_cost_units > 18 * 1_000
    assert guided.guidance_cost_units == 0
