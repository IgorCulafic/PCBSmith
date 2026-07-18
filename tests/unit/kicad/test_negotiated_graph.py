from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest

from pcbsmith.kicad.negotiated_graph import (
    CandidateRoute,
    NegotiatedCostPolicy,
    negotiate_candidate_routes,
)
from pcbsmith.kicad.negotiated_resources import RoutingResourceKey
from pcbsmith.routing_ir import RoutingFailureReason

FixtureCandidates = dict[str, tuple[CandidateRoute, ...]]
FixtureCase = tuple[FixtureCandidates, dict[str, str]]


def _load_fixture(name: str) -> FixtureCase:
    fixture_path = Path(__file__).parents[2] / "fixtures" / "routing" / name
    payload: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
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
            domain_id=f"fixture:{payload['fixture_id']}",
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


@pytest.mark.parametrize(
    ("fixture_name", "expected_pass_fingerprints", "expected_result_fingerprint"),
    [
        (
            "first_order_crossed_alternatives.json",
            (
                "43e8356cc15139dca68d97b96dc29b2546a40b0f2c0129f200b747e1a174c4ee",
                "212283da30be54872d18ee9acc6fd59c70fe1bc8947cc9acbcee913d4d01cc57",
            ),
            "9d2bf9edf651d4c78d16a3f1aa4ebabbd80d2b3efb7298592ef789f70fe438ec",
        ),
        (
            "second_order_cascade.json",
            (
                "73929c20b8aaeb21b7687a93f204ec073687dc1280d69698a7085550934e22ce",
                "99fbafb0d07bef353fb0ed7c5881d641cd5a2e42b25a5f19a7b7dbb33dcae0d7",
                "ee8467c44e8c539025236413ce4cc6a769911a99dcf5b85a21090928de176244",
                "b79338ff6f81db1dbdd7a999cdaa0a108333971e3c9821703a63a8e6ffaf11cf",
                "6d39a4982774a2ad601e217a0bea7369ba05b846b8e451093fc410ded456796a",
            ),
            "11ecd795a6a61f509e4cbf30d1d2f5d59478c98d4a6018b7236dff487f9e5884",
        ),
    ],
)
def test_negotiation_converges_with_stable_telemetry(
    fixture_name: str,
    expected_pass_fingerprints: tuple[str, ...],
    expected_result_fingerprint: str,
) -> None:
    candidates, expected_assignment = _load_fixture(fixture_name)

    result = negotiate_candidate_routes(candidates)

    assert result.success
    assert result.failure_reason is None
    assert result.assignment == expected_assignment
    assert result.resource_overuse == ()
    assert result.objective == (0, 0, 0, 0)
    assert len(result.passes) == len(expected_pass_fingerprints)
    assert tuple(item.pass_index for item in result.passes) == tuple(
        range(len(expected_pass_fingerprints))
    )
    assert (
        tuple(item.semantic_fingerprint() for item in result.passes) == expected_pass_fingerprints
    )
    assert result.semantic_fingerprint() == expected_result_fingerprint
    assert result.history_fingerprint == result.passes[-1].history_fingerprint
    assert result.resource_fingerprint == result.passes[-1].resource_fingerprint
    assert len(result.semantic_fingerprint()) == 64
    for routing_pass in result.passes:
        assert len(routing_pass.history_fingerprint) == 64
        assert len(routing_pass.resource_fingerprint) == 64
        assert len(routing_pass.semantic_fingerprint()) == 64


@pytest.mark.parametrize(
    "fixture_name",
    [
        "first_order_crossed_alternatives.json",
        "second_order_cascade.json",
    ],
)
def test_every_pass_selects_one_complete_declared_candidate(
    fixture_name: str,
) -> None:
    candidates, _expected_assignment = _load_fixture(fixture_name)
    declared = {
        (route.net_name, route.candidate_id): tuple(
            sorted(resource.resource_id for resource in route.resources)
        )
        for routes in candidates.values()
        for route in routes
    }

    result = negotiate_candidate_routes(candidates)

    for routing_pass in result.passes:
        assert tuple(choice.net_name for choice in routing_pass.chosen_candidates) == tuple(
            sorted(candidates)
        )
        for choice in routing_pass.chosen_candidates:
            assert choice.resource_ids == declared[(choice.net_name, choice.candidate_id)]


@pytest.mark.parametrize(
    "fixture_name",
    [
        "first_order_crossed_alternatives.json",
        "second_order_cascade.json",
    ],
)
def test_reversed_input_and_repeated_runs_are_semantically_identical(
    fixture_name: str,
) -> None:
    candidates, _expected_assignment = _load_fixture(fixture_name)
    reversed_candidates: Mapping[str, tuple[CandidateRoute, ...]] = {
        net_name: tuple(reversed(candidates[net_name])) for net_name in reversed(tuple(candidates))
    }

    first = negotiate_candidate_routes(candidates)
    repeated = negotiate_candidate_routes(candidates)
    reversed_result = negotiate_candidate_routes(reversed_candidates)

    assert first == repeated == reversed_result
    assert first.semantic_json() == reversed_result.semantic_json()
    assert first.semantic_fingerprint() == reversed_result.semantic_fingerprint()


@pytest.mark.parametrize(
    ("fixture_name", "required_passes", "expected_nets"),
    [
        ("first_order_crossed_alternatives.json", 2, ("A", "B")),
        ("second_order_cascade.json", 5, ("A", "B")),
    ],
)
def test_one_less_pass_returns_typed_budget_failure_and_final_overuse(
    fixture_name: str,
    required_passes: int,
    expected_nets: tuple[str, ...],
) -> None:
    candidates, _expected_assignment = _load_fixture(fixture_name)

    result = negotiate_candidate_routes(candidates, max_passes=required_passes - 1)

    assert not result.success
    assert result.failure_reason is RoutingFailureReason.PASS_BUDGET
    assert len(result.passes) == required_passes - 1
    assert result.resource_overuse == result.passes[-1].resource_overuse
    assert result.resource_overuse
    assert result.objective == (0, 1, 1, 1)
    assert result.resource_overuse[0].net_names == expected_nets


def test_zero_stagnation_patience_returns_immediate_typed_overuse() -> None:
    candidates, _expected_assignment = _load_fixture("first_order_crossed_alternatives.json")

    result = negotiate_candidate_routes(candidates, max_stagnant_passes=0)

    assert not result.success
    assert result.failure_reason is RoutingFailureReason.OVERUSE_REMAINING
    assert len(result.passes) == 1
    assert result.passes[0].pass_index == 0
    assert not result.passes[0].stagnant
    assert result.resource_overuse


def test_stagnation_budget_has_a_distinct_typed_exit() -> None:
    candidates, _expected_assignment = _load_fixture("second_order_cascade.json")

    result = negotiate_candidate_routes(candidates, max_stagnant_passes=1)

    assert not result.success
    assert result.failure_reason is RoutingFailureReason.STAGNATION
    assert len(result.passes) == 2
    assert result.passes[-1].stagnant
    assert result.resource_overuse


def test_candidate_and_policy_validation_is_strict_and_frozen() -> None:
    resource = RoutingResourceKey("validation", "F.Cu", "cell", 1, 1)
    candidate = CandidateRoute("N", "one", 0, frozenset({resource}))

    with pytest.raises(FrozenInstanceError):
        candidate.candidate_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="at least one resource"):
        CandidateRoute("N", "empty", 0, frozenset())
    with pytest.raises(ValueError, match="non-negative integer"):
        CandidateRoute("N", "bad-cost", -1, frozenset({resource}))
    with pytest.raises(ValueError, match="positive integer"):
        NegotiatedCostPolicy(present_growth_denominator=0)


def test_mapping_ownership_order_and_budget_validation() -> None:
    resource = RoutingResourceKey("validation", "F.Cu", "cell", 1, 1)
    candidate = CandidateRoute("N", "one", 0, frozenset({resource}))

    with pytest.raises(ValueError, match="at least one net"):
        negotiate_candidate_routes({})
    with pytest.raises(ValueError, match="no route candidates"):
        negotiate_candidate_routes({"N": ()})
    with pytest.raises(ValueError, match="ownership mismatch"):
        negotiate_candidate_routes({"other": (candidate,)})
    with pytest.raises(ValueError, match="duplicate candidate IDs"):
        negotiate_candidate_routes({"N": (candidate, candidate)})
    with pytest.raises(ValueError, match="every candidate net exactly once"):
        negotiate_candidate_routes({"N": (candidate,)}, baseline_order=("other",))
    with pytest.raises(ValueError, match="positive integer"):
        negotiate_candidate_routes({"N": (candidate,)}, max_passes=0)
    with pytest.raises(ValueError, match="non-negative integer"):
        negotiate_candidate_routes({"N": (candidate,)}, max_stagnant_passes=-1)


def test_direct_pass_and_result_construction_rejects_inconsistent_net_sets() -> None:
    candidates, _expected_assignment = _load_fixture("first_order_crossed_alternatives.json")
    result = negotiate_candidate_routes(candidates)
    first_pass = result.passes[0]
    final_pass = result.passes[-1]

    with pytest.raises(ValueError, match="unique non-empty nets"):
        replace(first_pass, route_order=())
    with pytest.raises(ValueError, match="every chosen net exactly once"):
        replace(first_pass, route_order=("A",))
    with pytest.raises(ValueError, match="at least one resource"):
        replace(first_pass.chosen_candidates[0], resource_ids=())
    with pytest.raises(ValueError, match="unique non-empty nets"):
        replace(result, baseline_order=())
    with pytest.raises(ValueError, match="unique non-empty nets"):
        replace(result, baseline_order=("A", "A"))
    with pytest.raises(ValueError, match="unique non-empty nets"):
        replace(result, baseline_order=("A", ""))

    short_choices = (final_pass.chosen_candidates[0],)
    short_final = replace(
        final_pass,
        pass_index=0,
        route_order=(short_choices[0].net_name,),
        chosen_candidates=short_choices,
    )
    with pytest.raises(ValueError, match="every baseline net exactly once"):
        replace(result, chosen_candidates=short_choices, passes=(short_final,))

    short_first = replace(
        first_pass,
        route_order=(first_pass.chosen_candidates[0].net_name,),
        chosen_candidates=(first_pass.chosen_candidates[0],),
    )
    with pytest.raises(ValueError, match="exactly the baseline net set"):
        replace(result, passes=(short_first, final_pass))
