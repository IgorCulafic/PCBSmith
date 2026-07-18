from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from pcbsmith.kicad.negotiated_resources import (
    LayerName,
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
    build_pairwise_clearance_domains,
    capsule_move_claims,
    capsule_segment_claims,
    clearance_domains_for_net,
    symmetric_halo_radius,
    via_claims,
)
from pcbsmith.rule_profiles import OrdinaryClearanceRequirement


class CandidateFixture(TypedDict):
    candidate_id: str
    base_cost: int
    resources: list[str]


class NetFixture(TypedDict):
    net_name: str
    candidates: list[CandidateFixture]


class GraphFixture(TypedDict):
    schema_id: str
    schema_version: int
    fixture_id: str
    nets: list[NetFixture]
    expected_zero_overuse_assignment: dict[str, str]


FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "routing"
FIXTURE_NAMES = ("first_order_crossed_alternatives", "second_order_cascade")


def _resource(index: int, *, kind: str = "cell") -> RoutingResourceKey:
    if kind == "via_site":
        return RoutingResourceKey("ordinary", "through", "via_site", index, 0)
    if kind == "edge":
        return RoutingResourceKey("ordinary", "F.Cu", "edge", index, 0, index + 1, 0)
    if kind == "crossing":
        return RoutingResourceKey("ordinary", "F.Cu", "crossing", index, 0)
    return RoutingResourceKey("ordinary", "F.Cu", "cell", index, 0)


def _load_fixture(name: str) -> GraphFixture:
    path = FIXTURE_ROOT / f"{name}.json"
    return cast(GraphFixture, json.loads(path.read_text(encoding="utf-8")))


def _candidates_by_net(fixture: GraphFixture) -> dict[str, list[CandidateFixture]]:
    return {item["net_name"]: item["candidates"] for item in fixture["nets"]}


def _legacy_shortest_first_completes(fixture: GraphFixture, order: tuple[str, ...]) -> bool:
    occupied: set[str] = set()
    candidates = _candidates_by_net(fixture)
    for net_name in order:
        feasible = [
            item
            for item in sorted(
                candidates[net_name], key=lambda item: (item["base_cost"], item["candidate_id"])
            )
            if occupied.isdisjoint(item["resources"])
        ]
        if not feasible:
            return False
        occupied.update(feasible[0]["resources"])
    return True


def _zero_overuse_assignments(fixture: GraphFixture) -> list[dict[str, str]]:
    nets = [item["net_name"] for item in fixture["nets"]]
    candidates = _candidates_by_net(fixture)
    assignments: list[dict[str, str]] = []
    for selection in itertools.product(*(candidates[net] for net in nets)):
        resources = [resource for candidate in selection for resource in candidate["resources"]]
        if len(resources) == len(set(resources)):
            assignments.append(
                {
                    net: candidate["candidate_id"]
                    for net, candidate in zip(nets, selection, strict=True)
                }
            )
    return assignments


def _fixture_ledger(fixture: GraphFixture, *, reverse: bool) -> OccupancyLedger:
    symbols = sorted(
        {
            resource
            for net in fixture["nets"]
            for candidate in net["candidates"]
            for resource in candidate["resources"]
        }
    )
    keys = {symbol: _resource(index) for index, symbol in enumerate(symbols)}
    expected = fixture["expected_zero_overuse_assignment"]
    nets = list(reversed(fixture["nets"])) if reverse else fixture["nets"]
    claims: list[NetResourceClaims] = []
    for net in nets:
        candidate = next(
            item for item in net["candidates"] if item["candidate_id"] == expected[net["net_name"]]
        )
        resources = list(reversed(candidate["resources"])) if reverse else candidate["resources"]
        claims.append(
            NetResourceClaims(net["net_name"], frozenset(keys[resource] for resource in resources))
        )
    return OccupancyLedger(claims)


def test_resource_edges_are_normalized_and_ids_are_canonical() -> None:
    forward = RoutingResourceKey("ordinary", "F.Cu", "edge", -1, 2, 0, 1)
    reverse = RoutingResourceKey("ordinary", "F.Cu", "edge", 0, 1, -1, 2)

    assert forward == reverse
    assert forward.resource_id == reverse.resource_id
    assert forward == sorted((reverse, forward))[0]


def test_resource_kind_layer_and_coordinate_invariants_are_validated() -> None:
    with pytest.raises(ValueError, match="through"):
        RoutingResourceKey("ordinary", "F.Cu", "via_site", 0, 0)
    with pytest.raises(ValueError, match="adjacent"):
        RoutingResourceKey("ordinary", "F.Cu", "edge", 0, 0, 2, 0)
    with pytest.raises(ValueError, match="second endpoint"):
        RoutingResourceKey("ordinary", "F.Cu", "cell", 0, 0, 1, 0)


def test_layers_are_isolated_for_identical_moves() -> None:
    front = capsule_move_claims("ordinary", "F.Cu", (0, 0), (1, 0), 1.0, 0.0)
    back = capsule_move_claims("ordinary", "B.Cu", (0, 0), (1, 0), 1.0, 0.0)

    assert front.isdisjoint(back)
    assert {item.layer for item in front} == {"F.Cu"}
    assert {item.layer for item in back} == {"B.Cu"}


def test_opposite_diagonals_share_crossing_but_not_normalized_edge() -> None:
    rising = capsule_move_claims("ordinary", "F.Cu", (0, 0), (1, 1), 1.0, 0.0)
    falling = capsule_move_claims("ordinary", "F.Cu", (0, 1), (1, 0), 1.0, 0.0)

    rising_crossings = {item for item in rising if item.kind == "crossing"}
    falling_crossings = {item for item in falling if item.kind == "crossing"}
    rising_edges = {item for item in rising if item.kind == "edge"}
    falling_edges = {item for item in falling if item.kind == "edge"}
    assert rising_crossings == falling_crossings
    assert len(rising_crossings) == 1
    assert rising_edges.isdisjoint(falling_edges)


def test_capsule_supercover_claims_exact_boundary_touching_cells() -> None:
    claims = capsule_move_claims("ordinary", "F.Cu", (0, 0), (1, 0), 1.0, 0.5)
    cells = {(item.ix0, item.iy0) for item in claims if item.kind == "cell"}

    assert cells == {
        (-1, 0),
        (0, -1),
        (0, 0),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
        (2, 0),
    }


def test_intersecting_adjacent_halos_share_at_least_one_cell() -> None:
    lower = capsule_move_claims("ordinary", "F.Cu", (0, 0), (1, 0), 1.0, 0.5)
    upper = capsule_move_claims("ordinary", "F.Cu", (0, 1), (1, 1), 1.0, 0.5)
    lower_cells = {item for item in lower if item.kind == "cell"}
    upper_cells = {item for item in upper if item.kind == "cell"}

    assert lower_cells & upper_cells


def test_width_and_clearance_are_combined_by_the_caller_as_half_sums() -> None:
    radius = symmetric_halo_radius(copper_width_mm=0.2, clearance_mm=0.3)

    assert radius == pytest.approx(0.25)
    assert capsule_move_claims("ordinary", "F.Cu", (0, 0), (1, 0), 1.0, radius) == (
        capsule_move_claims("ordinary", "F.Cu", (0, 0), (1, 0), 1.0, 0.25)
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [((0, 0), (4, 0)), ((0, 0), (0, -4)), ((-2, -2), (2, 2))],
)
def test_long_lattice_segment_equals_union_of_adjacent_move_claims(
    start: tuple[int, int], end: tuple[int, int]
) -> None:
    segment = capsule_segment_claims(
        "ordinary",
        "F.Cu",
        (float(start[0]), float(start[1])),
        (float(end[0]), float(end[1])),
        1.0,
        0.25,
    )
    dx = (end[0] > start[0]) - (end[0] < start[0])
    dy = (end[1] > start[1]) - (end[1] < start[1])
    current = start
    moves: set[RoutingResourceKey] = set()
    while current != end:
        following = (current[0] + dx, current[1] + dy)
        moves.update(capsule_move_claims("ordinary", "F.Cu", current, following, 1.0, 0.25))
        current = following

    assert segment == frozenset(moves)


def test_reversed_long_diagonal_preserves_all_canonical_crossings() -> None:
    forward = capsule_segment_claims("ordinary", "F.Cu", (0.0, 0.0), (4.0, 4.0), 1.0, 0.0)
    reverse = capsule_segment_claims("ordinary", "F.Cu", (4.0, 4.0), (0.0, 0.0), 1.0, 0.0)

    forward_crossings = {item for item in forward if item.kind == "crossing"}
    assert forward == reverse
    assert len(forward_crossings) == 4
    assert {(item.ix0, item.iy0) for item in forward_crossings} == {
        (0, 0),
        (1, 1),
        (2, 2),
        (3, 3),
    }


def test_opposite_diagonal_through_long_segment_square_shares_crossing() -> None:
    long_rising = capsule_segment_claims("ordinary", "F.Cu", (0.0, 0.0), (4.0, 4.0), 1.0, 0.0)
    opposite = capsule_move_claims("ordinary", "F.Cu", (2, 3), (3, 2), 1.0, 0.0)

    shared_crossings = {item for item in long_rising & opposite if item.kind == "crossing"}
    assert shared_crossings == {RoutingResourceKey("ordinary", "F.Cu", "crossing", 2, 2)}


def test_off_grid_arbitrary_stub_has_exact_cells_without_invented_edges() -> None:
    claims = capsule_segment_claims("ordinary", "F.Cu", (0.1, 0.1), (0.9, 0.4), 1.0, 0.0)

    assert {(item.ix0, item.iy0) for item in claims} == {(0, 0), (1, 0)}
    assert {item.kind for item in claims} == {"cell"}


def test_zero_length_on_grid_segment_is_a_cell_only_disc() -> None:
    claims = capsule_segment_claims("ordinary", "F.Cu", (0.0, 0.0), (0.0, 0.0), 1.0, 0.5)

    assert {(item.ix0, item.iy0) for item in claims} == {
        (-1, 0),
        (0, -1),
        (0, 0),
        (0, 1),
        (1, 0),
    }
    assert {item.kind for item in claims} == {"cell"}


def test_physical_segment_claims_are_identical_when_endpoints_are_reversed() -> None:
    forward = capsule_segment_claims("ordinary", "F.Cu", (-1.7, 0.2), (2.3, 1.6), 1.0, 0.25)
    reverse = capsule_segment_claims("ordinary", "F.Cu", (2.3, 1.6), (-1.7, 0.2), 1.0, 0.25)

    assert forward == reverse


def test_on_grid_noncanonical_angle_remains_cell_only() -> None:
    claims = capsule_segment_claims("ordinary", "F.Cu", (0.0, 0.0), (2.0, 1.0), 1.0, 0.0)

    assert claims
    assert {item.kind for item in claims} == {"cell"}


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ((float("nan"), 0.0), (1.0, 0.0)),
        ((0.0, float("inf")), (1.0, 0.0)),
        ((0.0, 0.0), (float("-inf"), 0.0)),
    ],
)
def test_physical_segment_rejects_nonfinite_endpoints(
    start: tuple[float, float], end: tuple[float, float]
) -> None:
    with pytest.raises(ValueError, match="finite"):
        capsule_segment_claims("ordinary", "F.Cu", start, end, 1.0, 0.0)


def test_physical_segment_validates_endpoints_grid_radius_and_layer() -> None:
    with pytest.raises(ValueError, match="two finite"):
        capsule_segment_claims(
            "ordinary",
            "F.Cu",
            cast(tuple[float, float], (0.0,)),
            (1.0, 0.0),
            1.0,
            0.0,
        )
    with pytest.raises(ValueError, match="grid_mm"):
        capsule_segment_claims("ordinary", "F.Cu", (0.0, 0.0), (1.0, 0.0), 0.0, 0.0)
    with pytest.raises(ValueError, match="halo_radius"):
        capsule_segment_claims("ordinary", "F.Cu", (0.0, 0.0), (1.0, 0.0), 1.0, -0.1)
    with pytest.raises(ValueError, match="layer"):
        capsule_segment_claims(
            "ordinary",
            cast(LayerName, "Inner.1"),
            (0.0, 0.0),
            (1.0, 0.0),
            1.0,
            0.0,
        )


def test_via_claims_both_layer_halos_and_one_through_site() -> None:
    claims = via_claims("ordinary", 3, -2, 1.0, 0.0)

    sites = {item for item in claims if item.kind == "via_site"}
    cells = {item for item in claims if item.kind == "cell"}
    assert sites == {RoutingResourceKey("ordinary", "through", "via_site", 3, -2)}
    assert cells == {
        RoutingResourceKey("ordinary", "F.Cu", "cell", 3, -2),
        RoutingResourceKey("ordinary", "B.Cu", "cell", 3, -2),
    }


def test_same_net_duplicates_consume_once_and_overuse_is_positive_only() -> None:
    shared = _resource(0)
    ledger = OccupancyLedger()
    ledger.commit(NetResourceClaims("A", frozenset((shared, shared))))

    assert ledger.demand_without(shared, "B") == 1
    assert ledger.demand_without(shared, "A") == 0
    assert ledger.overuse() == ()

    ledger.commit(NetResourceClaims("B", frozenset((shared,))))
    summary = ledger.overuse()
    assert len(summary) == 1
    assert summary[0].demand_units == 2
    assert summary[0].overuse_units == 1
    assert summary[0].net_names == ("A", "B")


def test_overuse_telemetry_maps_internal_resource_kinds_and_sorts_ids() -> None:
    resources = frozenset(
        (
            _resource(3, kind="via_site"),
            _resource(2, kind="crossing"),
            _resource(1, kind="edge"),
            _resource(0),
        )
    )
    ledger = OccupancyLedger((NetResourceClaims("B", resources), NetResourceClaims("A", resources)))

    summaries = ledger.overuse()
    assert [item.resource_id for item in summaries] == sorted(
        item.resource_id for item in summaries
    )
    by_internal_kind = {
        resource.kind: next(
            item for item in summaries if item.resource_id == resource.resource_id
        ).resource_kind
        for resource in resources
    }
    assert by_internal_kind == {
        "cell": "region",
        "edge": "edge",
        "crossing": "edge",
        "via_site": "via_site",
    }


def test_rip_up_restore_and_commit_are_whole_net_replacements() -> None:
    old = NetResourceClaims("A", frozenset((_resource(0), _resource(1))))
    replacement = NetResourceClaims("A", frozenset((_resource(2),)))
    ledger = OccupancyLedger((old,))

    ripped = ledger.rip_up("A")
    assert ripped == old
    assert ledger.committed_claims() == ()
    ledger.commit(replacement)
    assert ledger.claims_for("A") == replacement
    assert ledger.demand_without(_resource(0), "B") == 0
    ledger.restore(old)
    assert ledger.claims_for("A") == old
    assert ledger.demand_without(_resource(2), "B") == 0
    assert ledger.demand_without(_resource(0), "B") == 1


def test_fingerprint_is_stable_across_input_order_and_same_net_duplicates() -> None:
    first = OccupancyLedger(
        (
            NetResourceClaims("B", frozenset((_resource(2), _resource(1)))),
            NetResourceClaims("A", frozenset((_resource(0), _resource(0)))),
        )
    )
    second = OccupancyLedger(
        (
            NetResourceClaims("A", frozenset((_resource(0),))),
            NetResourceClaims("B", frozenset((_resource(1), _resource(2)))),
        )
    )

    assert first.semantic_fingerprint() == second.semantic_fingerprint()


def test_pairwise_domains_are_canonical_and_never_join_same_side_nets() -> None:
    requirement = OrdinaryClearanceRequirement(
        requirement_id="logic-to-power",
        nets_a=("A2", "A1"),
        nets_b=("B2", "B1"),
        minimum_clearance_mm=0.8,
        mask_states_a=("masked",),
        mask_states_b=("fully_exposed",),
        roles_a=("routed_conductor",),
        roles_b=("via_land",),
        exempt_component_refs=("J2", "J1"),
        rule_ids=("rule-z", "rule-a"),
    )
    domains = build_pairwise_clearance_domains("fab-profile", (requirement,))

    assert len(domains) == 4
    assert {domain.net_names for domain in domains} == {
        ("A1", "B1"),
        ("A1", "B2"),
        ("A2", "B1"),
        ("A2", "B2"),
    }
    a1_ids = {domain.domain_id for domain in clearance_domains_for_net(domains, "A1")}
    a2_ids = {domain.domain_id for domain in clearance_domains_for_net(domains, "A2")}
    assert a1_ids.isdisjoint(a2_ids)
    selected = next(domain for domain in domains if domain.net_names == ("A1", "B1"))
    assert selected.selectors_for("A1") == (("masked",), ("routed_conductor",))
    assert selected.selectors_for("B1") == (("fully_exposed",), ("via_land",))

    side_swapped = OrdinaryClearanceRequirement(
        requirement_id="logic-to-power",
        nets_a=("B1", "B2"),
        nets_b=("A1", "A2"),
        minimum_clearance_mm=0.8,
        mask_states_a=("fully_exposed",),
        mask_states_b=("masked",),
        roles_a=("via_land",),
        roles_b=("routed_conductor",),
        exempt_component_refs=("J1", "J2"),
        rule_ids=("rule-a", "rule-z"),
    )
    assert domains == build_pairwise_clearance_domains("fab-profile", (side_swapped,))


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_every_legacy_sequential_shortest_first_order_fails(fixture_name: str) -> None:
    fixture = _load_fixture(fixture_name)
    nets = tuple(item["net_name"] for item in fixture["nets"])

    assert fixture["schema_id"] == "pcbsmith-routing-resource-graph"
    assert fixture["schema_version"] == 1
    assert all(
        not _legacy_shortest_first_completes(fixture, order)
        for order in itertools.permutations(nets)
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_fixture_has_documented_unique_zero_overuse_assignment(fixture_name: str) -> None:
    fixture = _load_fixture(fixture_name)

    assert _zero_overuse_assignments(fixture) == [fixture["expected_zero_overuse_assignment"]]


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_fixture_assignment_commits_whole_candidates_deterministically(
    fixture_name: str,
) -> None:
    fixture = _load_fixture(fixture_name)
    forward = _fixture_ledger(fixture, reverse=False)
    reversed_input = _fixture_ledger(fixture, reverse=True)

    assert forward.overuse() == ()
    assert forward.semantic_fingerprint() == reversed_input.semantic_fingerprint()
    assert {claims.net_name for claims in forward.committed_claims()} == set(
        fixture["expected_zero_overuse_assignment"]
    )
