from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.corridor_exchange import (
    CorridorEscapeAlternative,
    CorridorEscapeSelection,
    CorridorExchangeAllocation,
    CorridorExchangeDemand,
)
from pcbsmith.corridor_ir import (
    CorridorAllocation,
    CorridorNetDemand,
    CorridorResourceClaim,
    CorridorTerminal,
    CorridorViaPolicy,
)


def _demand(*, demand_id: str = "signal", net_name: str = "SIGNAL") -> CorridorNetDemand:
    return CorridorNetDemand(
        demand_id=demand_id,
        net_name=net_name,
        width_mm=0.2,
        allowed_layers=("F.Cu", "B.Cu"),
        via_policy=CorridorViaPolicy.ALLOWED,
        terminals=(
            CorridorTerminal(terminal_id="fine-2", candidate_cell_ids=("fine-b",)),
            CorridorTerminal(terminal_id="ordinary", candidate_cell_ids=("area",)),
            CorridorTerminal(terminal_id="fine-1", candidate_cell_ids=("fine-a",)),
        ),
        ordinary_span_units=2,
        effective_clearance_mm=0.15,
    )


def _claim(
    resource_id: str,
    *,
    kind: str = "channel",
    units: int = 1,
) -> CorridorResourceClaim:
    return CorridorResourceClaim(
        resource_id=resource_id,
        resource_kind=kind,
        demand_units=units,
    )


def _alternative(
    alternative_id: str = "exit-a",
    *,
    demand_id: str = "signal",
    net_name: str = "SIGNAL",
    fine_terminal_ids: tuple[str, ...] = ("fine-2", "fine-1"),
    exchange_portal_id: str | None = None,
) -> CorridorEscapeAlternative:
    exchange_id = exchange_portal_id or f"{alternative_id}-exchange"
    return CorridorEscapeAlternative(
        alternative_id=alternative_id,
        demand_id=demand_id,
        net_name=net_name,
        fine_terminal_ids=fine_terminal_ids,
        exchange_portal_id=exchange_id,
        area_entry_cell_id=f"{alternative_id}-entry",
        exit_layer="F.Cu",
        prefix_cell_ids=(f"{alternative_id}-entry", "fine-b", "fine-a"),
        prefix_claims=(
            _claim(f"{alternative_id}-prefix"),
            _claim(exchange_id, units=2),
        ),
        prefix_base_cost_units=7,
        detailed_prefix_resource_ids=(
            f"fine-grid:{alternative_id}:2",
            f"fine-grid:{alternative_id}:1",
        ),
        detailed_prefix_fingerprint=alternative_id[-1] * 64,
    )


def _exchange_demand() -> CorridorExchangeDemand:
    return CorridorExchangeDemand(
        demand=_demand(),
        alternatives=(_alternative("exit-b"), _alternative("exit-a")),
    )


def _allocation(*, demand_id: str = "signal", net_name: str = "SIGNAL") -> CorridorAllocation:
    return CorridorAllocation(
        demand_id=demand_id,
        net_name=net_name,
        cell_ids=("area", "exit-a-entry"),
        portal_claims=(_claim("area-portal", units=2),),
        base_cost_units=10,
        congestion_cost_units=0,
    )


def test_alternative_is_frozen_versioned_and_canonical_without_reordering_terminals() -> None:
    alternative = _alternative()

    assert alternative.schema_id == "pcbsmith-corridor-escape-alternative"
    assert alternative.schema_version == 1
    assert alternative.fine_terminal_ids == ("fine-2", "fine-1")
    assert alternative.prefix_cell_ids == ("exit-a-entry", "fine-a", "fine-b")
    assert tuple(item.resource_id for item in alternative.prefix_claims) == (
        "exit-a-exchange",
        "exit-a-prefix",
    )
    assert alternative.detailed_prefix_resource_ids == (
        "fine-grid:exit-a:1",
        "fine-grid:exit-a:2",
    )
    with pytest.raises(ValidationError):
        alternative.alternative_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("update", "message"),
    (
        ({"fine_terminal_ids": ("fine-1", "fine-1")}, "fine_terminal_ids values must be unique"),
        (
            {"detailed_prefix_resource_ids": ("fine-grid:one", "fine-grid:one")},
            "detailed_prefix_resource_ids values must be unique",
        ),
        (
            {"detailed_prefix_fingerprint": "A" * 64},
            "must be a lowercase SHA-256 hex digest",
        ),
        ({"area_entry_cell_id": "missing"}, "must be present in prefix_cell_ids"),
    ),
)
def test_alternative_rejects_invalid_ordered_ids_resources_and_fingerprint(
    update: dict[str, object],
    message: str,
) -> None:
    payload = _alternative().model_dump()
    payload.update(update)

    with pytest.raises(ValidationError, match=message):
        CorridorEscapeAlternative.model_validate(payload)


def test_alternative_requires_one_unique_channel_exchange_claim() -> None:
    payload = _alternative().model_dump()
    payload["prefix_claims"] = (_claim("not-the-exchange"),)
    with pytest.raises(ValidationError, match="must be present in prefix_claims"):
        CorridorEscapeAlternative.model_validate(payload)

    payload = _alternative().model_dump()
    payload["prefix_claims"] = (
        _claim("exit-a-exchange", kind="via_site"),
        _claim("exit-a-exchange", kind="via_site"),
    )
    with pytest.raises(ValidationError, match="prefix resource identities values must be unique"):
        CorridorEscapeAlternative.model_validate(payload)


def test_exchange_demand_canonicalizes_alternatives_and_binds_terminal_subset() -> None:
    exchange = _exchange_demand()

    assert exchange.schema_id == "pcbsmith-corridor-exchange-demand"
    assert tuple(item.alternative_id for item in exchange.alternatives) == ("exit-a", "exit-b")
    assert exchange.alternative("exit-b").alternative_id == "exit-b"
    with pytest.raises(KeyError):
        exchange.alternative("unknown")


@pytest.mark.parametrize(
    ("alternatives", "message"),
    (
        (
            (_alternative(), _alternative("exit-b", demand_id="other")),
            "must match demand and net identity",
        ),
        (
            (_alternative(), _alternative("exit-b", fine_terminal_ids=("fine-1", "fine-2"))),
            "same ordered fine terminals",
        ),
        (
            (_alternative(fine_terminal_ids=("not-a-terminal",)),),
            "must be a subset of demand terminals",
        ),
        (
            (_alternative(fine_terminal_ids=("fine-1", "fine-2", "ordinary")),),
            "at least one remaining ordinary terminal",
        ),
    ),
)
def test_exchange_demand_rejects_invalid_binding_or_terminal_partition(
    alternatives: tuple[CorridorEscapeAlternative, ...],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        CorridorExchangeDemand(demand=_demand(), alternatives=alternatives)


def test_exchange_demand_rejects_duplicate_alternative_and_resource_identities() -> None:
    duplicate = _alternative()
    with pytest.raises(
        ValidationError, match="escape alternative identities values must be unique"
    ):
        CorridorExchangeDemand(demand=_demand(), alternatives=(duplicate, duplicate))

    payload = _alternative().model_dump()
    payload["prefix_claims"] = (
        _claim("exit-a-exchange"),
        _claim("exit-a-exchange", units=2),
    )
    with pytest.raises(ValidationError, match="prefix resource identities values must be unique"):
        CorridorEscapeAlternative.model_validate(payload)


def test_selection_factory_binds_exact_exchange_demand_and_selected_alternative() -> None:
    exchange = _exchange_demand()
    selection = CorridorEscapeSelection.from_exchange_demand(exchange, "exit-b")

    assert selection.schema_id == "pcbsmith-corridor-escape-selection"
    assert selection.exchange_demand_fingerprint == exchange.semantic_fingerprint()
    assert selection.demand_id == exchange.demand.demand_id
    assert selection.net_name == exchange.demand.net_name
    assert selection.alternative == exchange.alternative("exit-b")


def test_selection_rejects_mismatched_demand_or_net_and_bad_fingerprint() -> None:
    exchange = _exchange_demand()
    selection = CorridorEscapeSelection.from_exchange_demand(exchange, "exit-a")
    for update, message in (
        ({"demand_id": "other"}, "must match demand and net identity"),
        ({"net_name": "OTHER"}, "must match demand and net identity"),
        ({"exchange_demand_fingerprint": "bad"}, "lowercase SHA-256"),
    ):
        with pytest.raises(ValidationError, match=message):
            CorridorEscapeSelection.model_validate(selection.model_copy(update=update).model_dump())


def test_exchange_allocation_binds_existing_records_without_mutating_fingerprints() -> None:
    exchange = _exchange_demand()
    allocation = _allocation()
    demand_fingerprint = exchange.demand.semantic_fingerprint()
    allocation_fingerprint = allocation.semantic_fingerprint()
    selection = CorridorEscapeSelection.from_exchange_demand(exchange, "exit-a")

    bound = CorridorExchangeAllocation(
        exchange_demand=exchange,
        allocation=allocation,
        selection=selection,
    )

    assert bound.schema_id == "pcbsmith-corridor-exchange-allocation"
    assert bound.exchange_demand.demand.semantic_fingerprint() == demand_fingerprint
    assert bound.allocation.semantic_fingerprint() == allocation_fingerprint


def test_exchange_allocation_rejects_stale_or_foreign_records() -> None:
    exchange = _exchange_demand()
    selection = CorridorEscapeSelection.from_exchange_demand(exchange, "exit-a")
    with pytest.raises(ValidationError, match="allocation must match"):
        CorridorExchangeAllocation(
            exchange_demand=exchange,
            allocation=_allocation(demand_id="other"),
            selection=selection,
        )

    stale = selection.model_copy(update={"exchange_demand_fingerprint": "f" * 64})
    with pytest.raises(ValidationError, match="exact exchange demand fingerprint"):
        CorridorExchangeAllocation(
            exchange_demand=exchange,
            allocation=_allocation(),
            selection=stale,
        )

    foreign = _alternative("exit-a").model_copy(update={"prefix_base_cost_units": 99})
    altered_selection = selection.model_copy(update={"alternative": foreign})
    with pytest.raises(ValidationError, match="content differs"):
        CorridorExchangeAllocation(
            exchange_demand=exchange,
            allocation=_allocation(),
            selection=altered_selection,
        )
