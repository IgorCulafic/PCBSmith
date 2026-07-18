"""Replay-bound execution of an already prepared corridor-exchange plan.

This opt-in adapter is deliberately narrower than the legacy convenience
wrapper.  It accepts only an ``APPLIED`` replay-checked preparation, invokes
ordinary R2 exactly once for that execution, and never falls back to an
unguided retry.  Exact checking remains a separate R2 authority boundary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from pcbsmith.corridor_exchange_replay_ir import CorridorExchangePreparationResult
from pcbsmith.corridor_guidance import CorridorGuidanceDisposition
from pcbsmith.corridor_ir import CorridorIrModel
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.negotiated_board import (
    NegotiatedBoardRouteResult,
    route_board_negotiated,
)
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)

_ROUTE_RESULT_ADAPTER = TypeAdapter(NegotiatedBoardRouteResult)


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def negotiated_board_route_result_fingerprint(result: NegotiatedBoardRouteResult) -> str:
    """Fingerprint the complete materialized R2 outcome, not only telemetry."""

    return _fingerprint(
        {
            "schema_id": "pcbsmith-negotiated-board-route-result",
            "schema_version": 1,
            "result": _ROUTE_RESULT_ADAPTER.dump_python(result, mode="json"),
        }
    )


class CorridorExchangeExecutionPolicy(CorridorIrModel):
    """Complete deterministic R2 controls not already retained by preparation."""

    schema_id: Literal["pcbsmith-corridor-exchange-execution-policy"] = (
        "pcbsmith-corridor-exchange-execution-policy"
    )
    schema_version: Literal[1] = 1
    net_order: tuple[str, ...] | None = None
    max_passes: int = Field(default=16, ge=0)
    max_expansions: int = Field(default=2_000_000, ge=0)
    max_expansions_per_net: int = Field(default=250_000, ge=0)
    max_stagnant_passes: int = Field(default=8, ge=0)
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY

    @model_validator(mode="after")
    def route_order_is_explicit_and_unique(self) -> Self:
        if self.net_order is not None:
            if any(not net_name for net_name in self.net_order):
                raise ValueError("execution net_order identities must be non-empty")
            if len(set(self.net_order)) != len(self.net_order):
                raise ValueError("execution net_order identities must be unique")
        return self


class CorridorExchangeExecutionResult(CorridorIrModel):
    """One R2 outcome proven from complete replay-checked exchange authority."""

    schema_id: Literal["pcbsmith-corridor-exchange-execution-result"] = (
        "pcbsmith-corridor-exchange-execution-result"
    )
    schema_version: Literal[1] = 1
    preparation: CorridorExchangePreparationResult
    policy: CorridorExchangeExecutionPolicy
    route_result: NegotiatedBoardRouteResult
    preparation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    routing_run_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_result_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def execution_replays_exactly(self) -> Self:
        if self.preparation.disposition is not CorridorGuidanceDisposition.APPLIED:
            raise ValueError("corridor exchange execution requires APPLIED preparation")
        if self.preparation_fingerprint != self.preparation.semantic_fingerprint():
            raise ValueError("execution preparation fingerprint is stale")
        if self.policy_fingerprint != self.policy.semantic_fingerprint():
            raise ValueError("execution policy fingerprint is stale")
        if self.routing_run_fingerprint != self.route_result.run_result.semantic_fingerprint():
            raise ValueError("execution routing-run fingerprint is stale")
        if self.route_result_fingerprint != negotiated_board_route_result_fingerprint(
            self.route_result
        ):
            raise ValueError("execution route-result fingerprint is stale")
        if any(
            value is not None
            for value in (
                self.route_result.exact_check,
                self.route_result.exact_check_evidence,
                self.route_result.checked_netlist,
            )
        ):
            raise ValueError("corridor exchange R2 execution cannot claim an exact check")
        _require_prepared_prefix_bindings(self.preparation, self.route_result)
        replayed = _execute_once(self.preparation, self.policy)
        if replayed != self.route_result:
            raise ValueError("corridor exchange R2 result does not equal exact replay")
        return self


def _require_prepared_prefix_bindings(
    preparation: CorridorExchangePreparationResult,
    route_result: NegotiatedBoardRouteResult,
) -> None:
    selected = {
        item.net_name: (item.alternative_id, item.prefix_fingerprint)
        for item in preparation.selected_prefixes
    }
    bound = {
        item.net_name: (item.alternative_id, item.prefix_fingerprint)
        for item in route_result.prefix_bindings
    }
    if len(bound) != len(route_result.prefix_bindings):
        raise ValueError("R2 prefix bindings must have unique net identities")
    if any(selected.get(net_name) != identity for net_name, identity in bound.items()):
        raise ValueError("R2 prefix bindings do not match prepared exchange authority")
    if route_result.run_result.success and bound != selected:
        raise ValueError("successful exchange execution must bind every prepared prefix")


def _execute_once(
    preparation: CorridorExchangePreparationResult,
    policy: CorridorExchangeExecutionPolicy,
) -> NegotiatedBoardRouteResult:
    authority = preparation.preparation_input
    layout = authority.layout
    netlist = authority.netlist
    layout_before = canonical_board_layout_snapshot_json(layout)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)
    result = route_board_negotiated(
        layout,
        netlist,
        target_nets=authority.target_nets,
        net_widths={item.net_name: item.width_mm for item in authority.net_widths},
        default_width_mm=authority.default_width_mm,
        profile=authority.profile,
        net_order=policy.net_order,
        grid_mm=authority.grid_mm,
        clearance_groups=tuple(item.as_legacy_tuple() for item in authority.clearance_groups),
        soft_guides={item.net_name: item.guide for item in preparation.soft_guides},
        route_prefixes={item.net_name: item.prefix for item in preparation.route_prefixes},
        max_passes=policy.max_passes,
        max_expansions=policy.max_expansions,
        max_expansions_per_net=policy.max_expansions_per_net,
        max_stagnant_passes=policy.max_stagnant_passes,
        cost_policy=policy.cost_policy,
        exact_checker=None,
    )
    try:
        authority_changed = (
            canonical_board_layout_snapshot_json(layout) != layout_before
            or canonical_board_netlist_snapshot_json(netlist) != netlist_before
        )
    except Exception as error:
        raise RuntimeError("R2 execution mutated retained corridor-exchange authority") from error
    if authority_changed:
        raise RuntimeError("R2 execution mutated retained corridor-exchange authority")
    return result


def execute_prepared_corridor_exchange(
    preparation: CorridorExchangePreparationResult,
    *,
    policy: CorridorExchangeExecutionPolicy | None = None,
) -> CorridorExchangeExecutionResult:
    """Execute one APPLIED preparation without fallback or exact-check claims."""

    retained_preparation = CorridorExchangePreparationResult.model_validate_json(
        preparation.model_dump_json()
    )
    if retained_preparation != preparation:
        raise ValueError("corridor exchange preparation failed exact JSON reconstruction")
    if retained_preparation.disposition is not CorridorGuidanceDisposition.APPLIED:
        raise ValueError("corridor exchange execution requires APPLIED preparation")
    retained_policy = CorridorExchangeExecutionPolicy.model_validate_json(
        (policy or CorridorExchangeExecutionPolicy()).model_dump_json()
    )
    route_result = _execute_once(retained_preparation, retained_policy)
    return CorridorExchangeExecutionResult(
        preparation=retained_preparation,
        policy=retained_policy,
        route_result=route_result,
        preparation_fingerprint=retained_preparation.semantic_fingerprint(),
        policy_fingerprint=retained_policy.semantic_fingerprint(),
        routing_run_fingerprint=route_result.run_result.semantic_fingerprint(),
        route_result_fingerprint=negotiated_board_route_result_fingerprint(route_result),
    )
