from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_corridor_exchange_preparation import (
    _exchange_plan,
    _graph,
    _prefix,
    _prepare,
)
from tests.unit.kicad.test_corridor_exchange_routing import _route_result

import pcbsmith.kicad.corridor_exchange_execution as execution
import pcbsmith.kicad.negotiated_board as negotiated_board
from pcbsmith.corridor_guidance import CorridorGuidanceDisposition
from pcbsmith.corridor_ir import CorridorFailureReason
from pcbsmith.kicad.astar_router import RouteResult
from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment
from pcbsmith.kicad.corridor_exchange_execution import (
    CorridorExchangeExecutionPolicy,
    CorridorExchangeExecutionResult,
    execute_prepared_corridor_exchange,
)
from pcbsmith.kicad.negotiated_board import AppliedRoutePrefixBinding
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import NetResourceClaims, RoutingResourceKey
from pcbsmith.kicad.route_prefix import GridRoutePrefix


def _install_r2_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    success: bool = True,
    wrong_binding: bool = False,
    mutate: str | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_route(
        layout: BoardLayout,
        netlist: BoardNetlist,
        **kwargs: Any,
    ) -> Any:
        calls.append(kwargs)
        if mutate == "layout":
            object.__setattr__(layout, "width_mm", layout.width_mm + 1.0)
        if mutate == "netlist":
            object.__setattr__(netlist, "nets", ())
            object.__setattr__(netlist, "components", ())
            object.__setattr__(netlist, "nets", ("forged",))
        prefixes = kwargs["route_prefixes"]
        prefix = prefixes["SIGNAL"]
        result = _route_result(layout, netlist, prefix=prefix, success=success)
        if wrong_binding and success:
            result = replace(
                result,
                prefix_bindings=(
                    AppliedRoutePrefixBinding(
                        net_name="SIGNAL",
                        alternative_id="wrong-alternative",
                        prefix_fingerprint=prefix.semantic_fingerprint(),
                    ),
                ),
            )
        return result

    monkeypatch.setattr(execution, "route_board_negotiated", fake_route)
    return calls


def test_applied_preparation_executes_guided_r2_and_replays_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = _prepare(monkeypatch)
    calls = _install_r2_stub(monkeypatch)
    policy = CorridorExchangeExecutionPolicy(
        net_order=("SIGNAL",),
        max_passes=3,
        max_expansions=40,
        max_expansions_per_net=20,
        max_stagnant_passes=2,
    )

    result = execute_prepared_corridor_exchange(preparation, policy=policy)

    assert len(calls) == 2  # execution plus result-validator replay
    assert all(set(call["route_prefixes"]) == {"SIGNAL"} for call in calls)
    assert all(set(call["soft_guides"]) == {"SIGNAL"} for call in calls)
    assert all(call["exact_checker"] is None for call in calls)
    assert result.route_result.run_result.success
    assert result.route_result.prefix_bindings[0].alternative_id == "escape-a"
    assert result.preparation == preparation
    assert result.policy == policy


def test_result_json_roundtrip_replays_full_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = _prepare(monkeypatch)
    calls = _install_r2_stub(monkeypatch)
    result = execute_prepared_corridor_exchange(preparation)

    roundtrip = CorridorExchangeExecutionResult.model_validate_json(result.model_dump_json())

    assert roundtrip == result
    assert len(calls) == 3
    assert roundtrip.semantic_fingerprint() == result.semantic_fingerprint()


def test_algorithmic_failure_remains_applied_and_is_not_retried_unguided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = _prepare(monkeypatch)
    calls = _install_r2_stub(monkeypatch, success=False)

    result = execute_prepared_corridor_exchange(preparation)

    assert not result.route_result.run_result.success
    assert result.preparation.disposition is CorridorGuidanceDisposition.APPLIED
    assert result.route_result.prefix_bindings == ()
    assert len(calls) == 2
    assert all(call["route_prefixes"] for call in calls)
    assert all(call["soft_guides"] for call in calls)


def test_genuine_non_applied_preparation_is_rejected_before_r2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph()
    prefix = _prefix()
    plan = _exchange_plan(graph, prefix)
    plan = plan.model_copy(
        update={
            "plan": plan.plan.model_copy(
                update={
                    "guidance_ready": False,
                    "failure_reason": CorridorFailureReason.COARSE_CAPACITY_INSUFFICIENT,
                }
            )
        }
    )
    preparation = _prepare(monkeypatch, graph=graph, plan=plan)
    calls = _install_r2_stub(monkeypatch)

    with pytest.raises(ValueError, match="requires APPLIED"):
        execute_prepared_corridor_exchange(preparation)

    assert calls == []


@pytest.mark.parametrize(
    "net_order",
    (("",), ("SIGNAL", "SIGNAL")),
    ids=("empty", "duplicate"),
)
def test_execution_policy_rejects_ambiguous_net_order(net_order: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="non-empty|unique"):
        CorridorExchangeExecutionPolicy(net_order=net_order)


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("preparation_fingerprint",), "f" * 64),
        (("policy_fingerprint",), "e" * 64),
        (("routing_run_fingerprint",), "d" * 64),
        (("route_result_fingerprint",), "c" * 64),
        (("route_result", "run_result", "producer"), "forged-producer"),
    ),
)
def test_retained_fingerprint_and_nested_route_tamper_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, ...],
    replacement: str,
) -> None:
    preparation = _prepare(monkeypatch)
    _install_r2_stub(monkeypatch)
    result = execute_prepared_corridor_exchange(preparation)
    payload = json.loads(result.model_dump_json())
    target: Any = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(ValidationError, match="stale|exact replay|replay"):
        CorridorExchangeExecutionResult.model_validate(payload)


def test_r2_prefix_binding_must_equal_selected_exchange_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = _prepare(monkeypatch)
    _install_r2_stub(monkeypatch, wrong_binding=True)

    with pytest.raises(ValidationError, match="prepared exchange authority"):
        execute_prepared_corridor_exchange(preparation)


@pytest.mark.parametrize("mutate", ("layout", "netlist"))
def test_r2_cannot_mutate_reconstructed_preparation_inputs(
    monkeypatch: pytest.MonkeyPatch,
    mutate: str,
) -> None:
    preparation = _prepare(monkeypatch)
    _install_r2_stub(monkeypatch, mutate=mutate)

    with pytest.raises(RuntimeError, match="mutated retained"):
        execute_prepared_corridor_exchange(preparation)


def test_route_prefix_type_is_preserved_through_execution_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = _prepare(monkeypatch)
    _install_r2_stub(monkeypatch)

    result = execute_prepared_corridor_exchange(preparation)
    roundtrip = CorridorExchangeExecutionResult.model_validate_json(result.model_dump_json())

    assert isinstance(roundtrip.preparation.route_prefixes[0].prefix, GridRoutePrefix)


def test_prepared_execution_drives_real_r2_orchestration_once_per_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = _prepare(monkeypatch)
    search_calls: list[tuple[str, GridRoutePrefix | None]] = []
    resource = RoutingResourceKey("ordinary", "F.Cu", "cell", 2, 0)

    monkeypatch.setattr(
        negotiated_board,
        "_routable_nets",
        lambda *_args, **_kwargs: {"SIGNAL": 1.0},
    )

    def fake_candidate(*args: Any, **kwargs: Any) -> NegotiatedGridRoute:
        net_name = args[2]
        prefix = kwargs["route_prefix"]
        search_calls.append((net_name, prefix))
        assert prefix is not None
        return NegotiatedGridRoute(
            result=RouteResult(
                net_name=net_name,
                segments=(
                    TrackSegment(0.0, 0.0, 2.0, 0.0, "F.Cu", net_name, 0.4),
                ),
                vias=(),
                length_mm=2.0,
                expansion_count=1,
            ),
            claims=NetResourceClaims(net_name, frozenset((resource,))),
            base_cost_units=2,
            congestion_cost_units=0,
            prefix_alternative_id=prefix.alternative_id,
            prefix_fingerprint=prefix.semantic_fingerprint(),
        )

    monkeypatch.setattr(
        negotiated_board,
        "route_net_negotiated_candidate",
        fake_candidate,
    )

    result = execute_prepared_corridor_exchange(preparation)

    assert result.route_result.run_result.success
    assert result.route_result.order == ("SIGNAL",)
    assert result.route_result.prefix_bindings[0].alternative_id == "escape-a"
    assert len(search_calls) == 2
    assert all(call[0] == "SIGNAL" and call[1] is not None for call in search_calls)
