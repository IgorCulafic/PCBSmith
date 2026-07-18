"""Firing tests for replay-bound certified bus escape authority."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_candidate as candidate_fixtures
from tests.unit.kicad import test_bus_escape as escape_fixtures
from tests.unit.kicad import test_bus_transition as transition_fixtures

from pcbsmith.bus_allocator import (
    BusLaneAllocationResult,
    BusLayerTransitionEvent,
    BusMemberViaCount,
    bus_lane_allocation_fingerprint,
)
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.bus_candidate import BusCandidateBudget, BusCandidateFailureReason
from pcbsmith.kicad.bus_escape import (
    BusEscapeBudget,
    BusEscapeFailureReason,
    ClearanceGroup,
    generate_certified_bus_escape_candidate,
)
from pcbsmith.kicad.bus_escape_replay import (
    BusEscapeReplayInput,
    BusEscapeReplayResult,
    generate_replay_bound_bus_escape_candidate,
)
from pcbsmith.kicad.bus_transition import BusTransitionBudget
from pcbsmith.kicad.negotiated_grid import CertifiedEndpointTerminalSource
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)


def _resource(seed: int, *, edge: bool = False) -> RoutingResourceKey:
    if edge:
        return RoutingResourceKey("ordinary", "F.Cu", "edge", seed, seed, seed + 1, seed)
    return RoutingResourceKey("ordinary", "F.Cu", "cell", seed, seed)


def _generate(
    *,
    ledger: OccupancyLedger | None = None,
    sources: dict[str, CertifiedEndpointTerminalSource] | None = None,
    escape_budget: BusEscapeBudget = escape_fixtures.DEFAULT_ESCAPE_BUDGET,
    candidate_budget: BusCandidateBudget = candidate_fixtures.DEFAULT_BUDGET,
    history: dict[RoutingResourceKey, int] | None = None,
    clearance_groups: tuple[ClearanceGroup, ...] = (),
    hard_forbidden: tuple[RoutingResourceKey, ...] = (),
    transition_budget: BusTransitionBudget | None = None,
) -> BusEscapeReplayResult:
    fixture = escape_fixtures._fixture()
    terminal_sources = fixture.sources if sources is None else sources
    return generate_replay_bound_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.registry,
        terminal_sources,
        OccupancyLedger() if ledger is None else ledger,
        escape_budget,
        candidate_budget,
        history=history,
        clearance_groups=clearance_groups,
        hard_forbidden_resources=hard_forbidden,
        transition_budget=transition_budget,
    )


def test_real_candidate_matches_generator_repeats_roundtrips_and_isolates_callers() -> None:
    fixture = escape_fixtures._fixture()
    claim = NetResourceClaims("/FOREIGN", frozenset((_resource(40), _resource(41, edge=True))))
    ledger = OccupancyLedger((claim,))
    sources = dict(reversed(tuple(fixture.sources.items())))
    history = {_resource(43, edge=True): 2, _resource(42): 1}
    clearance_groups = (
        ({"/Z", "/Y"}, {"/Q"}, 0.1, {"U2", "U1"}),
        ({"/M"}, {"/N"}, 0.2, set()),
    )
    forbidden = (_resource(45, edge=True), _resource(44))
    layout_before = canonical_board_layout_snapshot_json(fixture.layout)
    netlist_before = canonical_board_netlist_snapshot_json(fixture.netlist)
    claims_before = ledger.committed_claims()
    ledger_before = ledger.semantic_fingerprint()
    sources_before = dict(sources)
    history_before = dict(history)
    groups_before = tuple(
        (set(a), set(b), gap, set(exempt)) for a, b, gap, exempt in clearance_groups
    )

    wrapped = generate_replay_bound_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.registry,
        sources,
        ledger,
        escape_fixtures.DEFAULT_ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
        history=history,
        clearance_groups=clearance_groups,
        hard_forbidden_resources=forbidden,
    )
    repeated = generate_replay_bound_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.registry,
        sources,
        OccupancyLedger((claim,)),
        escape_fixtures.DEFAULT_ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
        history=history,
        clearance_groups=clearance_groups,
        hard_forbidden_resources=forbidden,
    )
    direct = generate_certified_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.registry,
        sources,
        OccupancyLedger((claim,)),
        escape_fixtures.DEFAULT_ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
        history=history,
        clearance_groups=clearance_groups,
        hard_forbidden_resources=forbidden,
    )

    assert wrapped.generation_result.success
    assert wrapped.generation_result == direct
    assert repeated == wrapped
    assert BusEscapeReplayResult.model_validate_json(wrapped.model_dump_json()) == wrapped
    assert canonical_board_layout_snapshot_json(fixture.layout) == layout_before
    assert canonical_board_netlist_snapshot_json(fixture.netlist) == netlist_before
    assert ledger.committed_claims() == claims_before
    assert ledger.semantic_fingerprint() == ledger_before
    assert sources == sources_before
    assert history == history_before
    assert (
        tuple((set(a), set(b), gap, set(exempt)) for a, b, gap, exempt in clearance_groups)
        == groups_before
    )


def test_set_like_authority_reversal_is_byte_deterministic() -> None:
    fixture = escape_fixtures._fixture()
    resource_a = _resource(50)
    resource_b = _resource(51, edge=True)
    claims = (
        NetResourceClaims("a", frozenset((resource_a, resource_b))),
        NetResourceClaims("z", frozenset((_resource(52), _resource(53, edge=True)))),
    )
    history = {_resource(54): 1, _resource(55, edge=True): 2}
    groups = (
        ({"/Y", "/Z"}, {"/Q"}, 0.1, {"U2", "U1"}),
        ({"/M"}, {"/N"}, 0.2, set()),
    )
    forbidden = (_resource(56), _resource(57, edge=True))

    forward = generate_replay_bound_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.registry,
        fixture.sources,
        OccupancyLedger(claims),
        escape_fixtures.DEFAULT_ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
        history=history,
        clearance_groups=groups,
        hard_forbidden_resources=forbidden,
    )
    reversed_result = generate_replay_bound_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.registry,
        dict(reversed(tuple(fixture.sources.items()))),
        OccupancyLedger(tuple(reversed(claims))),
        escape_fixtures.DEFAULT_ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
        history=dict(reversed(tuple(history.items()))),
        clearance_groups=tuple(reversed(groups)),
        hard_forbidden_resources=tuple(reversed(forbidden)),
    )

    assert forward.semantic_json() == reversed_result.semantic_json()
    assert forward.semantic_fingerprint() == reversed_result.semantic_fingerprint()


@pytest.mark.parametrize(
    ("budget", "reason", "work"),
    (
        (
            BusEscapeBudget(
                max_members=0,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=4,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.MEMBER_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=1,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=4,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.MEMBER_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=0,
                max_expansions_per_terminal=2,
                max_expansions_per_member=4,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.TERMINAL_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=3,
                max_expansions_per_terminal=2,
                max_expansions_per_member=4,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.TERMINAL_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=0,
                max_expansions_per_member=4,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.PER_TERMINAL_EXPANSION_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=1,
                max_expansions_per_member=4,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.PER_TERMINAL_EXPANSION_BUDGET,
            1,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=0,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.PER_MEMBER_EXPANSION_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=3,
                max_total_expansions=8,
            ),
            BusEscapeFailureReason.PER_MEMBER_EXPANSION_BUDGET,
            3,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=4,
                max_total_expansions=0,
            ),
            BusEscapeFailureReason.TOTAL_EXPANSION_BUDGET,
            0,
        ),
        (
            BusEscapeBudget(
                max_members=2,
                max_terminals=4,
                max_expansions_per_terminal=2,
                max_expansions_per_member=4,
                max_total_expansions=7,
            ),
            BusEscapeFailureReason.TOTAL_EXPANSION_BUDGET,
            7,
        ),
    ),
)
def test_zero_and_one_less_escape_budgets_are_replay_bound(
    budget: BusEscapeBudget, reason: BusEscapeFailureReason, work: int
) -> None:
    result = _generate(escape_budget=budget)

    assert result.generation_result.failure_reason is reason
    assert result.generation_result.escape_expansion_count == work


@pytest.mark.parametrize("max_members", (0, 1))
def test_zero_and_one_less_candidate_member_budget_is_replay_bound(max_members: int) -> None:
    result = _generate(
        candidate_budget=BusCandidateBudget(
            max_members=max_members,
            max_expansions_per_member=10_000,
            max_total_expansions=20_000,
        )
    )

    assert result.generation_result.failure_reason is BusEscapeFailureReason.CANDIDATE_FAILURE
    assert result.generation_result.escape_expansion_count == 8
    assert result.generation_result.candidate is not None
    assert (
        result.generation_result.candidate.failure_reason is BusCandidateFailureReason.MEMBER_BUDGET
    )


def test_typed_invalid_source_and_source_at_portal_noop_are_replay_bound() -> None:
    fixture = escape_fixtures._fixture()
    invalid_sources = dict(fixture.sources)
    invalid_sources["data0:sink"] = replace(invalid_sources["data0:sink"], component_ref="R9")
    at_portal = dict(fixture.sources)
    at_portal["data0:sink"] = replace(at_portal["data0:sink"], source_node=("F.Cu", 22, 4))

    invalid = _generate(sources=invalid_sources)
    noop = _generate(sources=at_portal)

    assert invalid.generation_result.failure_reason is BusEscapeFailureReason.INVALID_SOURCE_BINDING
    assert (
        noop.generation_result.failure_reason is BusEscapeFailureReason.SOURCE_AT_PORTAL_UNSUPPORTED
    )
    assert noop.generation_result.escape_expansion_count == 0
    assert noop.generation_result.pigtails == ()


def test_transition_without_budget_remains_explicitly_unsupported() -> None:
    fixture = escape_fixtures._fixture()
    transition = BusLayerTransitionEvent(
        section_id="trunk",
        boundary_id="exit",
        window_id="window:test",
        member_id="data0",
        from_layer="F.Cu",
        to_layer="B.Cu",
    )
    via_counts = (
        BusMemberViaCount(member_id="data0", via_count=1),
        BusMemberViaCount(member_id="data1", via_count=0),
    )
    fingerprint = bus_lane_allocation_fingerprint(
        bus_fingerprint=fixture.allocation.bus_fingerprint,
        certificate_fingerprint=fixture.allocation.certificate_fingerprint,
        normalized_boundary_orders=fixture.allocation.normalized_boundary_orders,
        assignments=fixture.allocation.assignments,
        activations=fixture.allocation.activations,
        swaps=fixture.allocation.swaps,
        layer_transitions=(transition,),
        via_counts=via_counts,
        permutation_boundary_ids=fixture.allocation.permutation_boundary_ids,
    )
    payload = fixture.allocation.model_dump()
    payload.update(
        layer_transition_count=1,
        layer_transitions=(transition,),
        via_counts=via_counts,
        allocation_fingerprint=fingerprint,
    )
    allocation = BusLaneAllocationResult.model_validate(payload)

    result = generate_replay_bound_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        allocation,
        fixture.lanes,
        fixture.registry,
        fixture.sources,
        OccupancyLedger(),
        escape_fixtures.DEFAULT_ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
    )

    assert (
        result.generation_result.failure_reason
        is BusEscapeFailureReason.TRANSITION_VIAS_UNSUPPORTED
    )
    assert result.generation_result.escape_expansion_count == 0


def test_certified_cross_layer_escape_success_replays_and_roundtrips() -> None:
    fixture = transition_fixtures._two_member_fixture(mixed_transition=True)
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    first = generate_replay_bound_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.escapes,
        fixture.sources,
        ledger,
        transition_fixtures.ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
        transition_budget=transition_fixtures.TRANSITION_BUDGET,
    )
    repeated = generate_replay_bound_bus_escape_candidate(
        fixture.layout,
        fixture.netlist,
        fixture.bus,
        fixture.certificate,
        fixture.allocation,
        fixture.lanes,
        fixture.escapes,
        dict(reversed(tuple(fixture.sources.items()))),
        OccupancyLedger(),
        transition_fixtures.ESCAPE_BUDGET,
        candidate_fixtures.DEFAULT_BUDGET,
        transition_budget=transition_fixtures.TRANSITION_BUDGET,
    )

    assert first.generation_result.success
    assert first == repeated
    assert BusEscapeReplayResult.model_validate_json(first.model_dump_json()) == first
    assert {
        (prefix.member_id, prefix.authority_kind, len(prefix.prefix.vias))
        for _member_id, prefix in first.generation_result.prefixes_by_member
    } == {
        ("data0", "transition_fragments", 1),
        ("data1", "same_layer_trunk", 0),
    }
    assert first.generation_result.candidate is not None
    assert first.generation_result.candidate.success
    assert ledger.semantic_fingerprint() == before


@pytest.mark.parametrize("field", ("terminal_sources", "initial_claims", "history"))
def test_duplicate_authority_is_rejected(field: str) -> None:
    result = _generate(
        ledger=OccupancyLedger((NetResourceClaims("foreign", frozenset((_resource(60),))),)),
        history={_resource(61): 1},
    )
    payload = json.loads(result.replay_input.model_dump_json())
    payload[field].append(payload[field][0])

    with pytest.raises(ValidationError, match="duplicate"):
        BusEscapeReplayInput.model_validate(payload)


def test_zero_clearance_gap_is_rejected_at_replay_authority_boundary() -> None:
    payload = json.loads(_generate().replay_input.model_dump_json())
    payload["clearance_groups"] = [{"nets_a": ["/A"], "nets_b": ["/B"], "gap_mm": 0.0}]

    with pytest.raises(ValidationError, match="greater than 0"):
        BusEscapeReplayInput.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("replay_input", "bus", "bus_id"), "stale-bus"),
        (("replay_input", "terminal_sources", 0, "source", "component_ref"), "R9"),
        (("replay_input", "escape_budget", "max_total_expansions"), 7),
        (("generation_result", "pigtails", 0, "portal_point"), [21, 4]),
    ),
)
def test_nested_authority_and_result_tamper_are_rejected(
    path: tuple[str | int, ...], value: object
) -> None:
    payload = json.loads(_generate().model_dump_json())
    target: object = payload
    for item in path[:-1]:
        target = target[item]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        BusEscapeReplayResult.model_validate(payload)


def test_claim_history_and_forbidden_tamper_are_rejected_by_exact_replay() -> None:
    result = _generate(
        ledger=OccupancyLedger((NetResourceClaims("foreign", frozenset((_resource(70),))),)),
        history={_resource(71): 1},
        hard_forbidden=(_resource(72),),
    )
    for field in ("initial_claims", "history", "hard_forbidden_resources"):
        payload = json.loads(result.model_dump_json())
        if field == "initial_claims":
            payload["replay_input"][field][0]["net_name"] = "changed"
        elif field == "history":
            payload["replay_input"][field][0]["value"] = 2
        else:
            payload["replay_input"][field][0]["ix0"] = 73
            payload["replay_input"][field][0]["iy0"] = 73

        with pytest.raises(ValidationError):
            BusEscapeReplayResult.model_validate(payload)
