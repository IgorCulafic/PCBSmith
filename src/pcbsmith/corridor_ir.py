"""Engine-neutral deterministic models for shaped-corridor planning.

R3.1 deliberately contains no board adapter or search.  It defines immutable,
versioned interchange models and a transactional variable-capacity ledger.
Channel capacities are physical span quanta; via capacities are site counts.
Those unit kinds may never alias under one resource identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Any, Literal, Self, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from pcbsmith.routing_ir import ResourceOveruseSummary

CorridorLayer: TypeAlias = Literal["F.Cu", "B.Cu"]
CorridorCellId: TypeAlias = str
CorridorResourceId: TypeAlias = str
CorridorResourceKind: TypeAlias = Literal["channel", "via_site"]
CorridorOrientation: TypeAlias = Literal["horizontal_cut", "vertical_cut"]
CorridorObjective: TypeAlias = tuple[int, int, int, int]

_T = TypeVar("_T")


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _canonical_strings(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    result = tuple(sorted(set(values)))
    if any(not value for value in result):
        raise ValueError(f"{field_name} values must be non-empty")
    return result


def _canonical_by_identity(
    values: Iterable[_T],
    identity: Callable[[_T], str],
    label: str,
) -> tuple[_T, ...]:
    by_identity: dict[str, _T] = {}
    for value in values:
        item_id = identity(value)
        previous = by_identity.get(item_id)
        if previous is not None and previous != value:
            raise ValueError(f"duplicate {label} identity {item_id!r} has unequal content")
        by_identity[item_id] = value
    return tuple(by_identity[item_id] for item_id in sorted(by_identity))


class CorridorIrModel(BaseModel):
    """Frozen base with canonical semantic serialization."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    def semantic_json(self) -> str:
        return _canonical_json(self.model_dump(mode="json"))

    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class CorridorGeometryVerification(StrEnum):
    EXACT = "exact"
    BOUNDED_APPROXIMATION = "bounded_approximation"
    UNSUPPORTED = "unsupported"


class CorridorDemandKind(StrEnum):
    AREA = "area"
    FINE_ESCAPE = "fine_escape"


class CorridorViaPolicy(StrEnum):
    FORBIDDEN = "forbidden"
    ALLOWED = "allowed"
    REQUIRED = "required"


class CorridorFailureReason(StrEnum):
    GEOMETRY_BUDGET = "geometry_budget"
    UNSUPPORTED_GEOMETRY = "unsupported_geometry"
    TERMINAL_UNMAPPED = "terminal_unmapped"
    COARSE_CAPACITY_INSUFFICIENT = "coarse_capacity_insufficient"
    EXPANSION_BUDGET = "expansion_budget"
    PASS_BUDGET = "pass_budget"
    STAGNATION = "stagnation"


class CorridorCostPolicy(CorridorIrModel):
    """Fixed integer negotiated-capacity costs for the engine-neutral allocator."""

    channel_step_cost_units: StrictInt = Field(default=1000, ge=0)
    via_step_cost_units: StrictInt = Field(default=5000, ge=0)
    present_factor_units: StrictInt = Field(default=1, ge=0)
    present_growth_numerator: StrictInt = Field(default=2, ge=1)
    present_growth_denominator: StrictInt = Field(default=1, ge=1)
    history_increment_units: StrictInt = Field(default=4, ge=0)


def _validate_verification_metadata(
    verification: CorridorGeometryVerification,
    maximum_error_mm: float | None,
    *,
    label: str,
) -> None:
    if verification is CorridorGeometryVerification.BOUNDED_APPROXIMATION:
        if maximum_error_mm is None:
            raise ValueError(f"bounded {label} requires maximum_error_mm")
    elif maximum_error_mm is not None:
        raise ValueError(f"{verification.value} {label} cannot carry maximum_error_mm")


class CorridorGeometryIssue(CorridorIrModel):
    source_id: str = Field(min_length=1)
    layer: CorridorLayer | None = None
    verification: CorridorGeometryVerification
    maximum_error_mm: float | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1)
    affected_cell_ids: tuple[CorridorCellId, ...] = ()

    @model_validator(mode="after")
    def metadata_is_coherent(self) -> Self:
        _validate_verification_metadata(
            self.verification,
            self.maximum_error_mm,
            label="geometry issue",
        )
        object.__setattr__(
            self,
            "affected_cell_ids",
            _canonical_strings(self.affected_cell_ids, "affected_cell_ids"),
        )
        return self


class CorridorCell(CorridorIrModel):
    cell_id: CorridorCellId = Field(min_length=1)
    layer: CorridorLayer
    ix: int
    iy: int
    bounds_mm: tuple[float, float, float, float]
    terminal_owner_net_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def bounds_are_finite_and_ordered(self) -> Self:
        min_x, min_y, max_x, max_y = self.bounds_mm
        if any(not math.isfinite(value) for value in self.bounds_mm):
            raise ValueError("cell bounds must be finite")
        if min_x >= max_x or min_y >= max_y:
            raise ValueError("cell bounds must have positive width and height")
        object.__setattr__(
            self,
            "terminal_owner_net_names",
            _canonical_strings(
                self.terminal_owner_net_names,
                "terminal_owner_net_names",
            ),
        )
        return self


class CorridorPortal(CorridorIrModel):
    resource_id: CorridorResourceId = Field(min_length=1)
    layer: CorridorLayer
    cell_low: CorridorCellId = Field(min_length=1)
    cell_high: CorridorCellId = Field(min_length=1)
    orientation: CorridorOrientation
    guaranteed_span_units: int = Field(ge=0)
    possible_span_units: int = Field(ge=0)
    verification: CorridorGeometryVerification
    maximum_error_mm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def identity_capacity_and_metadata_are_coherent(self) -> Self:
        if self.cell_low == self.cell_high:
            raise ValueError("portal cells must be distinct")
        if self.cell_high < self.cell_low:
            low, high = self.cell_high, self.cell_low
            object.__setattr__(self, "cell_low", low)
            object.__setattr__(self, "cell_high", high)
        if self.possible_span_units < self.guaranteed_span_units:
            raise ValueError("possible span cannot be below guaranteed span")
        _validate_verification_metadata(
            self.verification,
            self.maximum_error_mm,
            label="portal",
        )
        if self.verification is CorridorGeometryVerification.UNSUPPORTED and (
            self.guaranteed_span_units or self.possible_span_units
        ):
            raise ValueError("unsupported portal cannot carry numeric capacity")
        return self


class CorridorViaPortal(CorridorIrModel):
    resource_id: CorridorResourceId = Field(min_length=1)
    front_cell_id: CorridorCellId = Field(min_length=1)
    back_cell_id: CorridorCellId = Field(min_length=1)
    guaranteed_site_count: int = Field(ge=0)
    possible_site_count: int = Field(ge=0)
    candidate_sites_mm: tuple[tuple[float, float], ...] = ()
    verification: CorridorGeometryVerification
    maximum_error_mm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def capacity_sites_and_metadata_are_coherent(self) -> Self:
        if self.possible_site_count < self.guaranteed_site_count:
            raise ValueError("possible site count cannot be below guaranteed site count")
        sites = tuple(sorted(set(self.candidate_sites_mm)))
        if any(not math.isfinite(coordinate) for site in sites for coordinate in site):
            raise ValueError("candidate via sites must be finite")
        if len(sites) < self.guaranteed_site_count:
            raise ValueError("guaranteed via site count exceeds candidate sites")
        object.__setattr__(self, "candidate_sites_mm", sites)
        _validate_verification_metadata(
            self.verification,
            self.maximum_error_mm,
            label="via portal",
        )
        if self.verification is CorridorGeometryVerification.UNSUPPORTED and (
            self.guaranteed_site_count or self.possible_site_count
        ):
            raise ValueError("unsupported via portal cannot carry numeric capacity")
        return self


class CorridorGraph(CorridorIrModel):
    schema_id: Literal["pcbsmith-corridor-graph"] = "pcbsmith-corridor-graph"
    schema_version: Literal[1] = 1
    profile_fingerprint: str
    layout_geometry_fingerprint: str
    coarse_grid_mm: float = Field(gt=0)
    capacity_quantum_mm: float = Field(gt=0)
    geometry_complete: bool = True
    cells: tuple[CorridorCell, ...] = ()
    portals: tuple[CorridorPortal, ...] = ()
    via_portals: tuple[CorridorViaPortal, ...] = ()
    issues: tuple[CorridorGeometryIssue, ...] = ()

    @field_validator("profile_fingerprint", "layout_geometry_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def graph_entities_are_canonical_and_referentially_sound(self) -> Self:
        cells = _canonical_by_identity(self.cells, lambda item: item.cell_id, "cell")
        portals = _canonical_by_identity(
            self.portals,
            lambda item: item.resource_id,
            "portal",
        )
        via_portals = _canonical_by_identity(
            self.via_portals,
            lambda item: item.resource_id,
            "via portal",
        )
        shared_resource_ids = {item.resource_id for item in portals} & {
            item.resource_id for item in via_portals
        }
        if shared_resource_ids:
            raise ValueError(
                "resource identity mixes channel and via-site kinds: "
                + ", ".join(sorted(shared_resource_ids))
            )
        cell_by_id = {item.cell_id: item for item in cells}
        for portal in portals:
            for cell_id in (portal.cell_low, portal.cell_high):
                cell = cell_by_id.get(cell_id)
                if cell is None:
                    raise ValueError(f"portal references unknown cell {cell_id!r}")
                if cell.layer != portal.layer:
                    raise ValueError("portal and referenced cells must share a layer")
        for via_portal in via_portals:
            front = cell_by_id.get(via_portal.front_cell_id)
            back = cell_by_id.get(via_portal.back_cell_id)
            if front is None or back is None:
                raise ValueError("via portal references an unknown cell")
            if front.layer != "F.Cu" or back.layer != "B.Cu":
                raise ValueError("via portal requires front then back cell identities")
        issues = tuple(
            sorted(
                self.issues,
                key=lambda item: (
                    item.source_id,
                    item.layer or "",
                    item.verification.value,
                    item.reason,
                    item.affected_cell_ids,
                ),
            )
        )
        object.__setattr__(self, "cells", cells)
        object.__setattr__(self, "portals", portals)
        object.__setattr__(self, "via_portals", via_portals)
        object.__setattr__(self, "issues", issues)
        return self


class CorridorTerminal(CorridorIrModel):
    terminal_id: str = Field(min_length=1)
    candidate_cell_ids: tuple[CorridorCellId, ...] = ()

    @model_validator(mode="after")
    def candidate_cells_are_canonical(self) -> Self:
        object.__setattr__(
            self,
            "candidate_cell_ids",
            _canonical_strings(self.candidate_cell_ids, "candidate_cell_ids"),
        )
        return self


class CorridorNetDemand(CorridorIrModel):
    demand_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    kind: CorridorDemandKind = CorridorDemandKind.AREA
    width_mm: float = Field(gt=0)
    allowed_layers: tuple[CorridorLayer, ...] = Field(min_length=1)
    via_policy: CorridorViaPolicy = CorridorViaPolicy.ALLOWED
    terminals: tuple[CorridorTerminal, ...] = Field(min_length=2)
    ordinary_span_units: int = Field(gt=0)
    effective_clearance_mm: float = Field(ge=0)
    pairwise_domain_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def demand_collections_are_canonical(self) -> Self:
        layers = tuple(sorted(set(self.allowed_layers)))
        terminals = _canonical_by_identity(
            self.terminals,
            lambda item: item.terminal_id,
            "terminal",
        )
        if len(terminals) < 2:
            raise ValueError("corridor demand requires two distinct terminals")
        object.__setattr__(self, "allowed_layers", layers)
        object.__setattr__(self, "terminals", terminals)
        object.__setattr__(
            self,
            "pairwise_domain_ids",
            _canonical_strings(self.pairwise_domain_ids, "pairwise_domain_ids"),
        )
        return self


class CorridorResourceCapacity(CorridorIrModel):
    resource_id: CorridorResourceId = Field(min_length=1)
    resource_kind: CorridorResourceKind
    capacity_units: int = Field(ge=0)


class CorridorResourceClaim(CorridorIrModel):
    resource_id: CorridorResourceId = Field(min_length=1)
    resource_kind: CorridorResourceKind
    demand_units: int = Field(gt=0)


def _canonical_claims(
    values: Iterable[CorridorResourceClaim],
) -> tuple[CorridorResourceClaim, ...]:
    return _canonical_by_identity(values, lambda item: item.resource_id, "resource claim")


class CorridorDemandClaims(CorridorIrModel):
    demand_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    claims: tuple[CorridorResourceClaim, ...] = ()

    @model_validator(mode="after")
    def claims_are_canonical(self) -> Self:
        object.__setattr__(self, "claims", _canonical_claims(self.claims))
        return self


class CorridorAllocation(CorridorIrModel):
    demand_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    cell_ids: tuple[CorridorCellId, ...] = ()
    portal_claims: tuple[CorridorResourceClaim, ...] = ()
    via_claims: tuple[CorridorResourceClaim, ...] = ()
    base_cost_units: int = Field(ge=0)
    congestion_cost_units: int = Field(ge=0)

    @model_validator(mode="after")
    def resources_are_canonical_and_kind_safe(self) -> Self:
        portal_claims = _canonical_claims(self.portal_claims)
        via_claims = _canonical_claims(self.via_claims)
        if any(item.resource_kind != "channel" for item in portal_claims):
            raise ValueError("portal claims require channel resources")
        if any(item.resource_kind != "via_site" for item in via_claims):
            raise ValueError("via claims require via_site resources")
        overlap = {item.resource_id for item in portal_claims} & {
            item.resource_id for item in via_claims
        }
        if overlap:
            raise ValueError("allocation resource identity mixes channel and via-site kinds")
        object.__setattr__(self, "cell_ids", _canonical_strings(self.cell_ids, "cell_ids"))
        object.__setattr__(self, "portal_claims", portal_claims)
        object.__setattr__(self, "via_claims", via_claims)
        return self


class CorridorBudget(CorridorIrModel):
    max_passes: int = Field(ge=0)
    max_expansions: int = Field(ge=0)
    max_expansions_per_demand: int = Field(ge=0)
    max_stagnant_passes: int = Field(ge=0)


class CorridorDemandAttemptTelemetry(CorridorIrModel):
    demand_id: str = Field(min_length=1)
    expansion_count: int = Field(ge=0)


def _canonical_overuse(
    values: Iterable[ResourceOveruseSummary],
) -> tuple[ResourceOveruseSummary, ...]:
    return _canonical_by_identity(values, lambda item: item.resource_id, "resource overuse")


class CorridorPassTelemetry(CorridorIrModel):
    pass_index: int = Field(ge=0)
    demand_order: tuple[str, ...]
    demand_attempts: tuple[CorridorDemandAttemptTelemetry, ...]
    expansion_count: int = Field(ge=0)
    unresolved_demand_ids: tuple[str, ...] = ()
    resource_overuse: tuple[ResourceOveruseSummary, ...] = ()
    objective: CorridorObjective
    history_fingerprint: str
    ledger_fingerprint: str
    allocation_fingerprint: str
    run_context_fingerprint: str
    present_factor_units: int = Field(ge=0)
    stagnant: bool = False

    @field_validator(
        "history_fingerprint",
        "ledger_fingerprint",
        "allocation_fingerprint",
        "run_context_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def pass_state_is_canonical(self) -> Self:
        if len(set(self.demand_order)) != len(self.demand_order) or any(
            not item for item in self.demand_order
        ):
            raise ValueError("demand_order must contain unique non-empty identities")
        attempt_order = tuple(item.demand_id for item in self.demand_attempts)
        if attempt_order != self.demand_order:
            raise ValueError("demand_attempts must exactly match demand_order")
        if sum(item.expansion_count for item in self.demand_attempts) != self.expansion_count:
            raise ValueError("demand attempt expansions must sum to pass expansion_count")
        if any(value < 0 for value in self.objective):
            raise ValueError("corridor objective values must be non-negative")
        overuse = _canonical_overuse(self.resource_overuse)
        unresolved = _canonical_strings(
            self.unresolved_demand_ids,
            "unresolved_demand_ids",
        )
        overuse_values = tuple(item.overuse_units for item in overuse)
        expected_objective = (
            len(unresolved),
            sum(overuse_values),
            len(overuse_values),
            max(overuse_values, default=0),
        )
        if self.objective != expected_objective:
            raise ValueError("corridor objective must match unresolved demands and overuse")
        object.__setattr__(self, "resource_overuse", overuse)
        object.__setattr__(self, "unresolved_demand_ids", unresolved)
        return self


def corridor_allocations_fingerprint(values: Iterable[CorridorAllocation]) -> str:
    allocations = _canonical_by_identity(values, lambda item: item.demand_id, "allocation")
    return _fingerprint(
        {
            "schema_id": "pcbsmith-corridor-allocations",
            "schema_version": 1,
            "allocations": [item.model_dump(mode="json") for item in allocations],
        }
    )


class CorridorPlanResult(CorridorIrModel):
    schema_id: Literal["pcbsmith-corridor-plan"] = "pcbsmith-corridor-plan"
    schema_version: Literal[1] = 1
    guidance_ready: bool
    failure_reason: CorridorFailureReason | None = None
    graph_fingerprint: str
    demand_fingerprint: str
    cost_policy_fingerprint: str
    baseline_demand_order: tuple[str, ...] = ()
    allocations: tuple[CorridorAllocation, ...] = ()
    unresolved_demand_ids: tuple[str, ...] = ()
    resource_overuse: tuple[ResourceOveruseSummary, ...] = ()
    passes: tuple[CorridorPassTelemetry, ...] = ()
    budget: CorridorBudget

    @field_validator("graph_fingerprint", "demand_fingerprint", "cost_policy_fingerprint")
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_state_is_coherent_and_canonical(self) -> Self:
        allocations = _canonical_by_identity(
            self.allocations,
            lambda item: item.demand_id,
            "allocation",
        )
        allocation_nets = [item.net_name for item in allocations]
        if len(set(allocation_nets)) != len(allocation_nets):
            raise ValueError("one corridor plan permits at most one allocation per net")
        unresolved = _canonical_strings(self.unresolved_demand_ids, "unresolved_demand_ids")
        overuse = _canonical_overuse(self.resource_overuse)
        if len(set(self.baseline_demand_order)) != len(self.baseline_demand_order) or any(
            not item for item in self.baseline_demand_order
        ):
            raise ValueError("baseline_demand_order must contain unique non-empty identities")
        if tuple(item.pass_index for item in self.passes) != tuple(range(len(self.passes))):
            raise ValueError("corridor pass indices must be consecutive from zero")
        if len(self.passes) > self.budget.max_passes:
            raise ValueError("corridor passes exceed the fixed budget")
        if sum(item.expansion_count for item in self.passes) > self.budget.max_expansions:
            raise ValueError("corridor expansions exceed the fixed budget")
        stagnant_run = 0
        for item in self.passes:
            if any(
                attempt.expansion_count > self.budget.max_expansions_per_demand
                for attempt in item.demand_attempts
            ):
                raise ValueError("corridor demand attempt exceeds the per-demand budget")
            stagnant_run = stagnant_run + 1 if item.stagnant else 0
            if stagnant_run > self.budget.max_stagnant_passes:
                raise ValueError("corridor stagnant passes exceed the fixed budget")
        if self.passes and self.passes[-1].resource_overuse != overuse:
            raise ValueError("final pass overuse must match plan result")
        if any(
            not set(item.demand_order).issubset(self.baseline_demand_order) for item in self.passes
        ):
            raise ValueError("pass demand_order references an unknown demand")
        if self.passes and self.passes[-1].unresolved_demand_ids != unresolved:
            raise ValueError("final pass unresolved demands must match plan result")
        allocation_fingerprint = corridor_allocations_fingerprint(allocations)
        if self.passes and self.passes[-1].allocation_fingerprint != allocation_fingerprint:
            raise ValueError("final pass allocations must match plan result")
        allocated_ids = {item.demand_id for item in allocations}
        unresolved_ids = set(unresolved)
        if allocated_ids & unresolved_ids:
            raise ValueError("allocations and unresolved demands must be disjoint")
        accounted = allocated_ids | unresolved_ids
        if accounted != set(self.baseline_demand_order):
            raise ValueError("allocations and unresolved demands must cover baseline order")
        if self.guidance_ready:
            if self.failure_reason is not None or unresolved or overuse:
                raise ValueError(
                    "guidance-ready plan requires no failure, unresolved demand, or overuse"
                )
            if len(allocations) != len(self.baseline_demand_order):
                raise ValueError("guidance-ready plan requires every baseline demand allocation")
        elif self.failure_reason is None:
            raise ValueError("non-ready corridor plan requires a typed failure reason")
        object.__setattr__(self, "allocations", allocations)
        object.__setattr__(self, "unresolved_demand_ids", unresolved)
        object.__setattr__(self, "resource_overuse", overuse)
        return self


class CorridorCapacityLedger:
    """Variable-capacity, whole-demand transactional occupancy ledger."""

    def __init__(
        self,
        capacities: Iterable[CorridorResourceCapacity],
        claims: Iterable[CorridorDemandClaims] = (),
    ) -> None:
        canonical_capacities = _canonical_by_identity(
            capacities,
            lambda item: item.resource_id,
            "resource capacity",
        )
        canonical_claims = _canonical_by_identity(
            claims,
            lambda item: item.demand_id,
            "demand claims",
        )
        self._capacities = {item.resource_id: item for item in canonical_capacities}
        self._by_demand: dict[str, CorridorDemandClaims] = {}
        self._by_resource: dict[str, dict[str, int]] = {}
        for item in canonical_claims:
            self.commit(item)

    def capacities(self) -> tuple[CorridorResourceCapacity, ...]:
        return tuple(self._capacities[item_id] for item_id in sorted(self._capacities))

    def capacity_for(self, resource_id: str) -> CorridorResourceCapacity:
        try:
            return self._capacities[resource_id]
        except KeyError as error:
            raise KeyError(f"unknown corridor resource {resource_id!r}") from error

    def claims_for(self, demand_id: str) -> tuple[CorridorResourceClaim, ...]:
        bundle = self._by_demand.get(demand_id)
        return bundle.claims if bundle is not None else ()

    def committed_claims(self) -> tuple[CorridorDemandClaims, ...]:
        return tuple(self._by_demand[demand_id] for demand_id in sorted(self._by_demand))

    def rip_up(self, demand_id: str) -> CorridorDemandClaims | None:
        previous = self._by_demand.get(demand_id)
        self._remove(demand_id)
        return previous

    def restore(self, claims: CorridorDemandClaims) -> None:
        self._replace(claims)

    def commit(self, claims: CorridorDemandClaims) -> None:
        self._replace(claims)

    def demand_without(self, resource_id: str, demand_id: str) -> int:
        self.capacity_for(resource_id)
        return sum(
            units
            for owner, units in self._by_resource.get(resource_id, {}).items()
            if owner != demand_id
        )

    def projected_overuse(
        self,
        demand_id: str,
        claim: CorridorResourceClaim,
    ) -> int:
        capacity = self._validated_capacity(claim)
        projected = self.demand_without(claim.resource_id, demand_id) + claim.demand_units
        return max(0, projected - capacity.capacity_units)

    def overuse(self) -> tuple[ResourceOveruseSummary, ...]:
        result: list[ResourceOveruseSummary] = []
        for resource_id, owners in sorted(self._by_resource.items()):
            capacity = self._capacities[resource_id]
            demand_units = sum(owners.values())
            if demand_units <= capacity.capacity_units:
                continue
            result.append(
                ResourceOveruseSummary(
                    resource_id=resource_id,
                    resource_kind=capacity.resource_kind,
                    capacity_units=capacity.capacity_units,
                    demand_units=demand_units,
                    overuse_units=demand_units - capacity.capacity_units,
                    net_names=tuple(
                        sorted({self._by_demand[demand_id].net_name for demand_id in owners})
                    ),
                )
            )
        return tuple(result)

    def semantic_fingerprint(self) -> str:
        payload = {
            "schema_id": "pcbsmith-corridor-capacity-ledger",
            "schema_version": 1,
            "capacities": [item.model_dump(mode="json") for item in self.capacities()],
            "claims": [item.model_dump(mode="json") for item in self.committed_claims()],
        }
        return _fingerprint(payload)

    def _replace(self, claims: CorridorDemandClaims) -> None:
        previous = self._by_demand.get(claims.demand_id)
        if previous is not None and previous.net_name != claims.net_name:
            raise ValueError("a committed demand identity cannot change its owning net")
        for claim in claims.claims:
            self._validated_capacity(claim)
        self._remove(claims.demand_id)
        self._by_demand[claims.demand_id] = claims
        for claim in claims.claims:
            self._by_resource.setdefault(claim.resource_id, {})[claims.demand_id] = (
                claim.demand_units
            )

    def _remove(self, demand_id: str) -> None:
        previous = self._by_demand.pop(demand_id, None)
        if previous is None:
            return
        for claim in previous.claims:
            owners = self._by_resource[claim.resource_id]
            owners.pop(demand_id, None)
            if not owners:
                del self._by_resource[claim.resource_id]

    def _validated_capacity(
        self,
        claim: CorridorResourceClaim,
    ) -> CorridorResourceCapacity:
        capacity = self.capacity_for(claim.resource_id)
        if capacity.resource_kind != claim.resource_kind:
            raise ValueError(
                f"resource {claim.resource_id!r} mixes {capacity.resource_kind} "
                f"capacity with {claim.resource_kind} demand"
            )
        return capacity
