"""Read-only placement surrogate summaries for corridor planning outcomes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.corridor_ir import (
    CorridorFailureReason,
    CorridorGeometryIssue,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorIrModel,
    CorridorNetDemand,
    CorridorPlanResult,
)


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _normalize_demands(
    demands: Sequence[CorridorNetDemand],
) -> tuple[CorridorNetDemand, ...]:
    by_id: dict[str, CorridorNetDemand] = {}
    net_names: set[str] = set()
    for demand in demands:
        previous = by_id.get(demand.demand_id)
        if previous is not None and previous != demand:
            raise ValueError(f"duplicate demand identity {demand.demand_id!r} has unequal content")
        if demand.net_name in net_names and previous is None:
            raise ValueError("one corridor summary permits at most one demand per net")
        by_id[demand.demand_id] = demand
        net_names.add(demand.net_name)
    return tuple(by_id[demand_id] for demand_id in sorted(by_id))


def _demands_fingerprint(demands: tuple[CorridorNetDemand, ...]) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-corridor-demands",
            "schema_version": 1,
            "demands": [demand.model_dump(mode="json") for demand in demands],
        }
    )


class CorridorGeometryIssueSummary(CorridorIrModel):
    source_id: str = Field(min_length=1)
    layer: Literal["F.Cu", "B.Cu"] | None = None
    verification: CorridorGeometryVerification
    maximum_error_mm: float | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1)
    affected_cell_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def affected_cells_are_canonical(self) -> Self:
        cells = tuple(sorted(set(self.affected_cell_ids)))
        if len(cells) != len(self.affected_cell_ids) or any(not cell for cell in cells):
            raise ValueError("affected_cell_ids must contain unique non-empty identities")
        object.__setattr__(self, "affected_cell_ids", cells)
        return self


class CorridorPlanSummary(CorridorIrModel):
    """Small, exact, read-only signal for later placement ranking."""

    schema_id: Literal["pcbsmith-corridor-plan-summary"] = "pcbsmith-corridor-plan-summary"
    schema_version: Literal[1] = 1
    graph_fingerprint: str
    demand_fingerprint: str
    plan_fingerprint: str
    geometry_complete: bool
    geometry_issues: tuple[CorridorGeometryIssueSummary, ...] = ()
    guidance_ready: bool
    failure_reason: CorridorFailureReason | None = None
    unresolved_demand_ids: tuple[str, ...] = ()
    pass_count: int = Field(ge=0)
    expansion_count: int = Field(ge=0)
    channel_guaranteed_capacity_units: int = Field(ge=0)
    channel_committed_demand_units: int = Field(ge=0)
    channel_total_overflow_units: int = Field(ge=0)
    channel_maximum_overflow_units: int = Field(ge=0)
    via_guaranteed_capacity_units: int = Field(ge=0)
    via_committed_demand_units: int = Field(ge=0)
    via_total_overflow_units: int = Field(ge=0)
    via_maximum_overflow_units: int = Field(ge=0)

    @field_validator("graph_fingerprint", "demand_fingerprint", "plan_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def summary_state_is_canonical(self) -> Self:
        unresolved = tuple(sorted(set(self.unresolved_demand_ids)))
        if len(unresolved) != len(self.unresolved_demand_ids) or any(
            not demand_id for demand_id in unresolved
        ):
            raise ValueError("unresolved demand identities must be unique and non-empty")
        issues = tuple(
            sorted(
                self.geometry_issues,
                key=lambda issue: (
                    issue.source_id,
                    issue.layer or "",
                    issue.verification.value,
                    issue.reason,
                    issue.affected_cell_ids,
                ),
            )
        )
        if self.channel_maximum_overflow_units > self.channel_total_overflow_units:
            raise ValueError("maximum channel overflow cannot exceed total channel overflow")
        if self.via_maximum_overflow_units > self.via_total_overflow_units:
            raise ValueError("maximum via overflow cannot exceed total via overflow")
        if self.guidance_ready and (self.failure_reason is not None or unresolved):
            raise ValueError("guidance-ready summary cannot retain failure or unresolved demand")
        if not self.guidance_ready and self.failure_reason is None:
            raise ValueError("non-ready summary requires a typed failure reason")
        object.__setattr__(self, "unresolved_demand_ids", unresolved)
        object.__setattr__(self, "geometry_issues", issues)
        return self


def summarize_corridor_plan(
    graph: CorridorGraph,
    demands: Sequence[CorridorNetDemand],
    plan: CorridorPlanResult,
) -> CorridorPlanSummary:
    """Validate and summarize exact graph/plan quantities without routing."""
    normalized_demands = _normalize_demands(demands)
    graph_fingerprint = graph.semantic_fingerprint()
    demand_fingerprint = _demands_fingerprint(normalized_demands)
    if plan.graph_fingerprint != graph_fingerprint:
        raise ValueError("corridor plan graph fingerprint is stale")
    if plan.demand_fingerprint != demand_fingerprint:
        raise ValueError("corridor plan demand fingerprint is stale")
    demand_by_id = {demand.demand_id: demand for demand in normalized_demands}
    if set(plan.baseline_demand_order) != set(demand_by_id):
        raise ValueError("corridor plan demand identities do not match summary input")
    for allocation in plan.allocations:
        demand = demand_by_id.get(allocation.demand_id)
        if demand is None or demand.net_name != allocation.net_name:
            raise ValueError("corridor allocation does not match its declared demand")

    channel_capacity = {
        portal.resource_id: portal.guaranteed_span_units for portal in graph.portals
    }
    via_capacity = {
        portal.resource_id: portal.guaranteed_site_count for portal in graph.via_portals
    }
    channel_demand = {resource_id: 0 for resource_id in channel_capacity}
    via_demand = {resource_id: 0 for resource_id in via_capacity}
    for allocation in plan.allocations:
        for claim in allocation.portal_claims:
            if claim.resource_id not in channel_capacity:
                raise ValueError("corridor allocation references an unknown channel")
            channel_demand[claim.resource_id] += claim.demand_units
        for claim in allocation.via_claims:
            if claim.resource_id not in via_capacity:
                raise ValueError("corridor allocation references an unknown via site")
            via_demand[claim.resource_id] += claim.demand_units

    channel_overflow = tuple(
        max(0, channel_demand[resource_id] - capacity)
        for resource_id, capacity in sorted(channel_capacity.items())
    )
    via_overflow = tuple(
        max(0, via_demand[resource_id] - capacity)
        for resource_id, capacity in sorted(via_capacity.items())
    )
    issues = tuple(_issue_summary(issue) for issue in graph.issues)
    return CorridorPlanSummary(
        graph_fingerprint=graph_fingerprint,
        demand_fingerprint=demand_fingerprint,
        plan_fingerprint=plan.semantic_fingerprint(),
        geometry_complete=graph.geometry_complete,
        geometry_issues=issues,
        guidance_ready=plan.guidance_ready,
        failure_reason=plan.failure_reason,
        unresolved_demand_ids=plan.unresolved_demand_ids,
        pass_count=len(plan.passes),
        expansion_count=sum(route_pass.expansion_count for route_pass in plan.passes),
        channel_guaranteed_capacity_units=sum(channel_capacity.values()),
        channel_committed_demand_units=sum(channel_demand.values()),
        channel_total_overflow_units=sum(channel_overflow),
        channel_maximum_overflow_units=max(channel_overflow, default=0),
        via_guaranteed_capacity_units=sum(via_capacity.values()),
        via_committed_demand_units=sum(via_demand.values()),
        via_total_overflow_units=sum(via_overflow),
        via_maximum_overflow_units=max(via_overflow, default=0),
    )


class VerifiedCorridorPlanSummary(CorridorIrModel):
    """Replay-bound full R3 authority plus its exact derived summary."""

    schema_id: Literal["pcbsmith-verified-corridor-plan-summary"] = (
        "pcbsmith-verified-corridor-plan-summary"
    )
    schema_version: Literal[1] = 1
    graph: CorridorGraph
    demands: tuple[CorridorNetDemand, ...]
    plan: CorridorPlanResult
    summary: CorridorPlanSummary

    @model_validator(mode="after")
    def sources_replay_to_exact_summary(self) -> Self:
        demands = _normalize_demands(self.demands)
        replayed = summarize_corridor_plan(self.graph, demands, self.plan)
        if self.summary != replayed:
            raise ValueError("verified corridor summary does not match source replay")
        object.__setattr__(self, "demands", demands)
        return self


def verify_corridor_plan_summary(
    graph: CorridorGraph,
    demands: Sequence[CorridorNetDemand],
    plan: CorridorPlanResult,
) -> VerifiedCorridorPlanSummary:
    """Build the replay-bound envelope while preserving the public summarizer."""

    normalized = _normalize_demands(demands)
    return VerifiedCorridorPlanSummary(
        graph=graph,
        demands=normalized,
        plan=plan,
        summary=summarize_corridor_plan(graph, normalized, plan),
    )


def _issue_summary(issue: CorridorGeometryIssue) -> CorridorGeometryIssueSummary:
    return CorridorGeometryIssueSummary(
        source_id=issue.source_id,
        layer=issue.layer,
        verification=issue.verification,
        maximum_error_mm=issue.maximum_error_mm,
        reason=issue.reason,
        affected_cell_ids=issue.affected_cell_ids,
    )
