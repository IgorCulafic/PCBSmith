"""Versioned soft-guidance artifacts derived from exact corridor allocations."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from pcbsmith.corridor_ir import (
    CorridorAllocation,
    CorridorCell,
    CorridorFailureReason,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorIrModel,
    CorridorPlanResult,
    CorridorPortal,
    CorridorViaPortal,
)


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


class CorridorGuidanceDisposition(StrEnum):
    """How corridor planning affected one detailed-routing run."""

    ABSENT = "absent"
    APPLIED = "applied"
    PLAN_NOT_READY = "plan_not_ready"
    INCOMPLETE_INPUT = "incomplete_input"
    INCOMPATIBLE = "incompatible"


class CorridorNetGuide(CorridorIrModel):
    """One allocation's canonical coarse resources before grid projection."""

    net_name: str = Field(min_length=1)
    demand_id: str = Field(min_length=1)
    allocation_fingerprint: str
    preferred_cell_ids: tuple[str, ...]
    preferred_portal_ids: tuple[str, ...] = ()
    preferred_via_resource_ids: tuple[str, ...] = ()
    terminal_cell_ids: tuple[str, ...] = ()

    @field_validator("allocation_fingerprint")
    @classmethod
    def fingerprint_is_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def collections_are_canonical(self) -> Self:
        for field_name in (
            "preferred_cell_ids",
            "preferred_portal_ids",
            "preferred_via_resource_ids",
            "terminal_cell_ids",
        ):
            values = tuple(sorted(set(getattr(self, field_name))))
            if any(not value for value in values):
                raise ValueError(f"{field_name} values must be non-empty")
            object.__setattr__(self, field_name, values)
        if not self.preferred_cell_ids:
            raise ValueError("a corridor net guide requires at least one preferred cell")
        if not set(self.terminal_cell_ids).issubset(self.preferred_cell_ids):
            raise ValueError("terminal cells must be preferred cells")
        return self


class CorridorRouteGuide(CorridorIrModel):
    """Immutable coarse guidance input for an opt-in detailed-routing run."""

    schema_id: Literal["pcbsmith-corridor-route-guide"] = "pcbsmith-corridor-route-guide"
    schema_version: Literal[1] = 1
    plan_fingerprint: str
    graph_fingerprint: str
    layout_geometry_fingerprint: str
    off_corridor_penalty_units: StrictInt = Field(ge=0)
    net_guides: tuple[CorridorNetGuide, ...]

    @field_validator(
        "plan_fingerprint",
        "graph_fingerprint",
        "layout_geometry_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def net_guides_are_canonical(self) -> Self:
        by_name: dict[str, CorridorNetGuide] = {}
        demand_ids: set[str] = set()
        for guide in self.net_guides:
            previous = by_name.get(guide.net_name)
            if previous is not None and previous != guide:
                raise ValueError(f"conflicting guide for net {guide.net_name!r}")
            if guide.demand_id in demand_ids:
                raise ValueError("corridor guide demand identities must be unique")
            by_name[guide.net_name] = guide
            demand_ids.add(guide.demand_id)
        if not by_name:
            raise ValueError("a corridor route guide requires at least one net")
        object.__setattr__(self, "net_guides", tuple(by_name[name] for name in sorted(by_name)))
        return self


class CorridorGuidanceReport(CorridorIrModel):
    """Separate authority envelope; it never changes RoutingRunResult semantics."""

    schema_id: Literal["pcbsmith-corridor-guidance-report"] = "pcbsmith-corridor-guidance-report"
    schema_version: Literal[1] = 1
    disposition: CorridorGuidanceDisposition
    plan_fingerprint: str | None = None
    graph_fingerprint: str | None = None
    guide_fingerprint: str | None = None
    plan_failure_reason: CorridorFailureReason | None = None
    guided_net_names: tuple[str, ...] = ()
    unguided_net_names: tuple[str, ...] = ()
    routing_run_fingerprint: str
    exact_check_fingerprint: str | None = None

    @field_validator(
        "plan_fingerprint",
        "graph_fingerprint",
        "guide_fingerprint",
        "routing_run_fingerprint",
        "exact_check_fingerprint",
    )
    @classmethod
    def optional_fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def state_is_coherent(self) -> Self:
        guided = tuple(sorted(set(self.guided_net_names)))
        unguided = tuple(sorted(set(self.unguided_net_names)))
        if any(not name for name in (*guided, *unguided)):
            raise ValueError("guided and unguided net names must be non-empty")
        if set(guided) & set(unguided):
            raise ValueError("a net cannot be both guided and unguided")
        if self.disposition is CorridorGuidanceDisposition.APPLIED:
            if self.guide_fingerprint is None or not guided:
                raise ValueError("applied guidance requires a guide and at least one guided net")
            if self.plan_fingerprint is None or self.graph_fingerprint is None:
                raise ValueError("applied guidance requires plan and graph fingerprints")
            if self.plan_failure_reason is not None:
                raise ValueError("applied guidance cannot retain a plan failure")
        elif self.guide_fingerprint is not None or guided:
            raise ValueError("non-applied guidance cannot contain an active guide")
        if self.disposition is CorridorGuidanceDisposition.ABSENT and (
            self.plan_fingerprint is not None
            or self.graph_fingerprint is not None
            or self.plan_failure_reason is not None
        ):
            raise ValueError("absent guidance cannot reference a corridor plan or graph")
        if self.disposition is CorridorGuidanceDisposition.PLAN_NOT_READY and (
            self.plan_fingerprint is None or self.plan_failure_reason is None
        ):
            raise ValueError("a non-ready plan report requires its fingerprint and failure")
        if self.disposition is CorridorGuidanceDisposition.INCOMPLETE_INPUT and (
            (self.plan_fingerprint is None) == (self.graph_fingerprint is None)
        ):
            raise ValueError("incomplete guidance input requires exactly one supplied artifact")
        if self.disposition is CorridorGuidanceDisposition.INCOMPATIBLE and (
            self.plan_fingerprint is None or self.graph_fingerprint is None
        ):
            raise ValueError("incompatible guidance requires plan and graph fingerprints")
        object.__setattr__(self, "guided_net_names", guided)
        object.__setattr__(self, "unguided_net_names", unguided)
        return self


def build_corridor_route_guide(
    graph: CorridorGraph,
    plan: CorridorPlanResult,
    *,
    off_corridor_penalty_units: int,
) -> CorridorRouteGuide | None:
    """Return exact compatible guidance, or ``None`` for a soft fallback."""
    if not isinstance(off_corridor_penalty_units, int) or isinstance(
        off_corridor_penalty_units, bool
    ):
        raise ValueError("off_corridor_penalty_units must be a non-negative integer")
    if off_corridor_penalty_units < 0:
        raise ValueError("off_corridor_penalty_units must be a non-negative integer")
    graph_fingerprint = graph.semantic_fingerprint()
    if not plan.guidance_ready or plan.graph_fingerprint != graph_fingerprint:
        return None
    if not graph.geometry_complete:
        return None
    if (
        any(item.verification is not CorridorGeometryVerification.EXACT for item in graph.portals)
        or any(
            item.verification is not CorridorGeometryVerification.EXACT
            for item in graph.via_portals
        )
        or any(item.verification is not CorridorGeometryVerification.EXACT for item in graph.issues)
    ):
        return None

    cells = {item.cell_id: item for item in graph.cells}
    portals = {item.resource_id: item for item in graph.portals}
    via_portals = {item.resource_id: item for item in graph.via_portals}
    guides = tuple(
        _net_guide(allocation, cells, portals, via_portals) for allocation in plan.allocations
    )
    return CorridorRouteGuide(
        plan_fingerprint=plan.semantic_fingerprint(),
        graph_fingerprint=graph_fingerprint,
        layout_geometry_fingerprint=graph.layout_geometry_fingerprint,
        off_corridor_penalty_units=off_corridor_penalty_units,
        net_guides=guides,
    )


def _net_guide(
    allocation: CorridorAllocation,
    cells: dict[str, CorridorCell],
    portals: dict[str, CorridorPortal],
    via_portals: dict[str, CorridorViaPortal],
) -> CorridorNetGuide:
    cell_ids = set(allocation.cell_ids)
    if not cell_ids or not cell_ids.issubset(cells):
        raise ValueError("corridor allocation references unknown or empty cells")
    portal_ids = tuple(item.resource_id for item in allocation.portal_claims)
    via_ids = tuple(item.resource_id for item in allocation.via_claims)
    if not set(portal_ids).issubset(portals) or not set(via_ids).issubset(via_portals):
        raise ValueError("corridor allocation references an unknown resource")
    for resource_id in portal_ids:
        channel_portal = portals[resource_id]
        if channel_portal.cell_low not in cell_ids or channel_portal.cell_high not in cell_ids:
            raise ValueError("selected portal endpoints must both be allocated cells")
    for resource_id in via_ids:
        via_portal = via_portals[resource_id]
        if via_portal.front_cell_id not in cell_ids or via_portal.back_cell_id not in cell_ids:
            raise ValueError("selected via endpoints must both be allocated cells")
    tree_edges = tuple(
        (portals[resource_id].cell_low, portals[resource_id].cell_high)
        for resource_id in portal_ids
    ) + tuple(
        (
            via_portals[resource_id].front_cell_id,
            via_portals[resource_id].back_cell_id,
        )
        for resource_id in via_ids
    )
    if len(tree_edges) != len(cell_ids) - 1:
        raise ValueError("corridor allocation resources must form a tree over its cells")
    adjacency = {cell_id: set[str]() for cell_id in cell_ids}
    for low, high in tree_edges:
        adjacency[low].add(high)
        adjacency[high].add(low)
    reached: set[str] = set()
    pending = [min(cell_ids)]
    while pending:
        cell_id = pending.pop()
        if cell_id in reached:
            continue
        reached.add(cell_id)
        pending.extend(sorted(adjacency[cell_id] - reached, reverse=True))
    if reached != cell_ids:
        raise ValueError("corridor allocation tree must be connected")
    terminal_cells = tuple(
        cell_id
        for cell_id in sorted(cell_ids)
        if allocation.net_name in cells[cell_id].terminal_owner_net_names
    )
    return CorridorNetGuide(
        net_name=allocation.net_name,
        demand_id=allocation.demand_id,
        allocation_fingerprint=allocation.semantic_fingerprint(),
        preferred_cell_ids=tuple(cell_ids),
        preferred_portal_ids=portal_ids,
        preferred_via_resource_ids=via_ids,
        terminal_cell_ids=terminal_cells,
    )
