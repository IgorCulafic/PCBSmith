"""Versioned structural records for fine/ordinary corridor exchange.

This module deliberately wraps the existing corridor demand and allocation
models instead of extending them.  R3.7a therefore adds no routing behavior and
does not change the semantic serialization of any existing corridor record.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, Self, TypeVar

from pydantic import Field, field_validator, model_validator

from pcbsmith.corridor_ir import (
    CorridorAllocation,
    CorridorCellId,
    CorridorIrModel,
    CorridorLayer,
    CorridorNetDemand,
    CorridorPlanResult,
    CorridorResourceClaim,
    CorridorResourceId,
)

_T = TypeVar("_T")


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _ordered_unique_strings(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(not value for value in result):
        raise ValueError(f"{field_name} values must be non-empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} values must be unique")
    return result


def _canonical_unique_strings(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    result = _ordered_unique_strings(values, field_name)
    return tuple(sorted(result))


def _canonical_unique_by_id(
    values: Iterable[_T],
    *,
    identity: Any,
    label: str,
) -> tuple[_T, ...]:
    result = tuple(values)
    identities = tuple(identity(value) for value in result)
    _ordered_unique_strings(identities, f"{label} identities")
    return tuple(value for _, value in sorted(zip(identities, result, strict=True)))


class CorridorEscapeAlternative(CorridorIrModel):
    """One precomputed fine-prefix exit presented to the corridor allocator."""

    schema_id: Literal["pcbsmith-corridor-escape-alternative"] = (
        "pcbsmith-corridor-escape-alternative"
    )
    schema_version: Literal[1] = 1
    alternative_id: str = Field(min_length=1)
    demand_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    fine_terminal_ids: tuple[str, ...] = Field(min_length=1)
    exchange_portal_id: CorridorResourceId = Field(min_length=1)
    area_entry_cell_id: CorridorCellId = Field(min_length=1)
    exit_layer: CorridorLayer
    prefix_cell_ids: tuple[CorridorCellId, ...] = Field(min_length=1)
    prefix_claims: tuple[CorridorResourceClaim, ...] = Field(min_length=1)
    prefix_base_cost_units: int = Field(ge=0)
    detailed_prefix_resource_ids: tuple[str, ...] = Field(min_length=1)
    detailed_prefix_fingerprint: str

    @field_validator("detailed_prefix_fingerprint")
    @classmethod
    def fingerprint_is_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def collections_and_exchange_identity_are_coherent(self) -> Self:
        fine_terminal_ids = _ordered_unique_strings(
            self.fine_terminal_ids,
            "fine_terminal_ids",
        )
        prefix_cell_ids = _canonical_unique_strings(self.prefix_cell_ids, "prefix_cell_ids")
        detailed_ids = _canonical_unique_strings(
            self.detailed_prefix_resource_ids,
            "detailed_prefix_resource_ids",
        )
        prefix_claims = _canonical_unique_by_id(
            self.prefix_claims,
            identity=lambda item: item.resource_id,
            label="prefix resource",
        )
        exchange_claim = next(
            (item for item in prefix_claims if item.resource_id == self.exchange_portal_id),
            None,
        )
        if exchange_claim is None:
            raise ValueError("exchange_portal_id must be present in prefix_claims")
        if exchange_claim.resource_kind != "channel":
            raise ValueError("exchange_portal_id must identify a channel claim")
        if self.area_entry_cell_id not in prefix_cell_ids:
            raise ValueError("area_entry_cell_id must be present in prefix_cell_ids")
        object.__setattr__(self, "fine_terminal_ids", fine_terminal_ids)
        object.__setattr__(self, "prefix_cell_ids", prefix_cell_ids)
        object.__setattr__(self, "prefix_claims", prefix_claims)
        object.__setattr__(self, "detailed_prefix_resource_ids", detailed_ids)
        return self


class CorridorExchangeDemand(CorridorIrModel):
    """An existing physical-net demand plus its interchangeable fine exits."""

    schema_id: Literal["pcbsmith-corridor-exchange-demand"] = "pcbsmith-corridor-exchange-demand"
    schema_version: Literal[1] = 1
    demand: CorridorNetDemand
    alternatives: tuple[CorridorEscapeAlternative, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def alternatives_are_bound_to_one_demand(self) -> Self:
        alternatives = _canonical_unique_by_id(
            self.alternatives,
            identity=lambda item: item.alternative_id,
            label="escape alternative",
        )
        terminal_ids = {item.terminal_id for item in self.demand.terminals}
        expected_fine_ids = alternatives[0].fine_terminal_ids
        for alternative in alternatives:
            if (
                alternative.demand_id != self.demand.demand_id
                or alternative.net_name != self.demand.net_name
            ):
                raise ValueError("escape alternative must match demand and net identity")
            if alternative.fine_terminal_ids != expected_fine_ids:
                raise ValueError("all alternatives must cover the same ordered fine terminals")
            if not set(alternative.fine_terminal_ids).issubset(terminal_ids):
                raise ValueError("fine_terminal_ids must be a subset of demand terminals")
        if not terminal_ids - set(expected_fine_ids):
            raise ValueError("exchange demand requires at least one remaining ordinary terminal")
        object.__setattr__(self, "alternatives", alternatives)
        return self

    def alternative(self, alternative_id: str) -> CorridorEscapeAlternative:
        """Return a declared alternative by stable identity."""

        for alternative in self.alternatives:
            if alternative.alternative_id == alternative_id:
                return alternative
        raise KeyError(alternative_id)


class CorridorEscapeSelection(CorridorIrModel):
    """A selected alternative bound to an exact exchange-demand fingerprint."""

    schema_id: Literal["pcbsmith-corridor-escape-selection"] = "pcbsmith-corridor-escape-selection"
    schema_version: Literal[1] = 1
    exchange_demand_fingerprint: str
    demand_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    alternative: CorridorEscapeAlternative

    @field_validator("exchange_demand_fingerprint")
    @classmethod
    def fingerprint_is_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def selected_alternative_is_bound_to_demand(self) -> Self:
        if (
            self.alternative.demand_id != self.demand_id
            or self.alternative.net_name != self.net_name
        ):
            raise ValueError("selected alternative must match demand and net identity")
        return self

    @classmethod
    def from_exchange_demand(
        cls,
        exchange_demand: CorridorExchangeDemand,
        alternative_id: str,
    ) -> CorridorEscapeSelection:
        return cls(
            exchange_demand_fingerprint=exchange_demand.semantic_fingerprint(),
            demand_id=exchange_demand.demand.demand_id,
            net_name=exchange_demand.demand.net_name,
            alternative=exchange_demand.alternative(alternative_id),
        )


class CorridorExchangeAllocation(CorridorIrModel):
    """Existing area allocation and selected fine prefix as one bound record."""

    schema_id: Literal["pcbsmith-corridor-exchange-allocation"] = (
        "pcbsmith-corridor-exchange-allocation"
    )
    schema_version: Literal[1] = 1
    exchange_demand: CorridorExchangeDemand
    allocation: CorridorAllocation
    selection: CorridorEscapeSelection

    @model_validator(mode="after")
    def demand_allocation_and_selection_are_coherent(self) -> Self:
        demand = self.exchange_demand.demand
        if (
            self.allocation.demand_id != demand.demand_id
            or self.allocation.net_name != demand.net_name
        ):
            raise ValueError("allocation must match exchange demand and net identity")
        if (
            self.selection.demand_id != demand.demand_id
            or self.selection.net_name != demand.net_name
        ):
            raise ValueError("selection must match exchange demand and net identity")
        if (
            self.selection.exchange_demand_fingerprint
            != self.exchange_demand.semantic_fingerprint()
        ):
            raise ValueError("selection must bind the exact exchange demand fingerprint")
        try:
            declared = self.exchange_demand.alternative(self.selection.alternative.alternative_id)
        except KeyError as error:
            raise ValueError("selected alternative is not declared by exchange demand") from error
        if declared != self.selection.alternative:
            raise ValueError("selected alternative content differs from exchange demand")
        return self


class CorridorExchangePlanResult(CorridorIrModel):
    """Negotiated plan plus final fine-prefix selections for exchange demands."""

    schema_id: Literal["pcbsmith-corridor-exchange-plan"] = "pcbsmith-corridor-exchange-plan"
    schema_version: Literal[1] = 1
    plan: CorridorPlanResult
    exchange_demands: tuple[CorridorExchangeDemand, ...] = ()
    exchange_allocations: tuple[CorridorExchangeAllocation, ...] = ()

    @model_validator(mode="after")
    def exchange_allocations_match_final_plan(self) -> Self:
        exchange_demands = _canonical_unique_by_id(
            self.exchange_demands,
            identity=lambda item: item.demand.demand_id,
            label="exchange demand",
        )
        exchange_allocations = _canonical_unique_by_id(
            self.exchange_allocations,
            identity=lambda item: item.allocation.demand_id,
            label="exchange allocation",
        )
        exchange_by_demand = {item.demand.demand_id: item for item in exchange_demands}
        exchange_ids = set(exchange_by_demand)
        if not exchange_ids.issubset(self.plan.baseline_demand_order):
            raise ValueError("exchange demands must be accounted by the plan baseline")
        plan_by_demand = {item.demand_id: item for item in self.plan.allocations}
        bound_ids: set[str] = set()
        for exchange_allocation in exchange_allocations:
            demand_id = exchange_allocation.allocation.demand_id
            declared = exchange_by_demand.get(demand_id)
            if declared is None:
                raise ValueError("exchange allocation must reference a declared exchange demand")
            if declared != exchange_allocation.exchange_demand:
                raise ValueError("exchange allocation embeds a different exchange demand")
            planned = plan_by_demand.get(demand_id)
            if planned is None:
                raise ValueError("exchange allocation must reference a final plan allocation")
            if planned != exchange_allocation.allocation:
                raise ValueError("exchange allocation must equal its final plan allocation")
            bound_ids.add(demand_id)
        expected_bound_ids = exchange_ids & set(plan_by_demand)
        if bound_ids != expected_bound_ids:
            raise ValueError("every final exchange allocation requires exactly one bound selection")
        if exchange_ids - bound_ids != exchange_ids & set(self.plan.unresolved_demand_ids):
            raise ValueError("unbound exchange demands must be unresolved by the final plan")
        object.__setattr__(self, "exchange_demands", exchange_demands)
        object.__setattr__(self, "exchange_allocations", exchange_allocations)
        return self
