"""Pure certified-bus candidate construction over negotiated R2 resources.

R4.2c2 consumes complete member prefixes produced by ``bus_integration`` and
builds one all-member ``BusRouteBundle`` in a scratch occupancy ledger.  It
does not mutate caller routing state, materialize partial results, run an exact
checker, or commit a bus transaction.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_geometry import CertifiedLaneGeometryRegistry
from pcbsmith.bus_ir import BusGroup, CorridorCapacityCertificate
from pcbsmith.kicad.astar_router import RoutingError
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.bus_integration import CertifiedBusMemberPrefix
from pcbsmith.kicad.bus_transaction import BusRouteBundle
from pcbsmith.kicad.clearance_domains import build_route_pairwise_clearance_domains
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_grid import route_net_negotiated_candidate
from pcbsmith.kicad.negotiated_resources import (
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.routing_ir import ResourceOveruseSummary, RoutingFailureReason, RoutingIrModel
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

ClearanceGroup = tuple[Collection[str], Collection[str], float, Collection[str]]


class BusCandidateBudget(RoutingIrModel):
    """Fixed deterministic work limits for one all-member candidate attempt."""

    schema_id: Literal["pcbsmith-bus-candidate-budget"] = "pcbsmith-bus-candidate-budget"
    schema_version: Literal[1] = 1
    max_members: int = Field(ge=0)
    max_expansions_per_member: int = Field(ge=0)
    max_total_expansions: int = Field(ge=0)


class BusCandidateCallerOveruseMode(StrEnum):
    """Whether existing external overuse is rejected or preserved in scratch."""

    REJECT = "reject"
    PRESERVE_FOR_NEGOTIATION = "preserve_for_negotiation"


class BusCandidatePolicy(RoutingIrModel):
    """Versioned orchestration policy; strict rejection remains the default."""

    schema_id: Literal["pcbsmith-bus-candidate-policy"] = "pcbsmith-bus-candidate-policy"
    schema_version: Literal[1] = 1
    caller_overuse_mode: BusCandidateCallerOveruseMode = BusCandidateCallerOveruseMode.REJECT


DEFAULT_BUS_CANDIDATE_POLICY = BusCandidatePolicy()


class BusCandidateFailureReason(StrEnum):
    """Terminal, non-accepting outcomes of pure candidate construction."""

    INVALID_BUS_BINDING = "invalid_bus_binding"
    INVALID_PREFIX_COVERAGE = "invalid_prefix_coverage"
    STATIC_TARGET_COPPER = "static_target_copper"
    CALLER_MEMBER_CLAIMS = "caller_member_claims"
    CALLER_OVERUSE = "caller_overuse"
    MEMBER_BUDGET = "member_budget"
    INVALID_ROUTING_INPUT = "invalid_routing_input"
    ROUTING_ERROR = "routing_error"
    PER_MEMBER_EXPANSION_BUDGET = "per_member_expansion_budget"
    TOTAL_EXPANSION_BUDGET = "total_expansion_budget"
    FINAL_OVERUSE = "final_overuse"


class BusMemberCandidateTelemetry(RoutingIrModel):
    """Deterministic record of one canonical member route attempt."""

    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    prefix_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    routed: bool
    expansion_count: int = Field(ge=0)
    segment_count: int = Field(default=0, ge=0)
    via_count: int = Field(default=0, ge=0)
    routing_failure_reason: RoutingFailureReason | None = None

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        if self.routed and self.routing_failure_reason is not None:
            raise ValueError("a routed bus member cannot carry a routing failure reason")
        if not self.routed and self.segment_count + self.via_count:
            raise ValueError("a failed bus member cannot report emitted geometry")
        return self


class BusCandidateResult(RoutingIrModel):
    """Pure all-member candidate outcome; success is not exact acceptance."""

    schema_id: Literal["pcbsmith-bus-candidate-result"] = "pcbsmith-bus-candidate-result"
    schema_version: Literal[1] = 1
    success: bool
    complete: bool
    zero_overuse: bool
    bus_id: str = Field(min_length=1)
    bus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: BusCandidateBudget
    policy: BusCandidatePolicy
    route_order: tuple[str, ...]
    member_telemetry: tuple[BusMemberCandidateTelemetry, ...] = ()
    expansion_count: int = Field(ge=0)
    failure_reason: BusCandidateFailureReason | None = None
    failed_member_id: str | None = None
    resource_overuse: tuple[ResourceOveruseSummary, ...] = ()
    caller_ledger_before_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    caller_ledger_after_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle: BusRouteBundle | None = None

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        if len(set(self.route_order)) != len(self.route_order):
            raise ValueError("bus candidate route_order must contain unique member IDs")
        if (
            tuple(item.member_id for item in self.member_telemetry)
            != self.route_order[: len(self.member_telemetry)]
        ):
            raise ValueError("member telemetry must be a canonical route-order prefix")
        if self.expansion_count != sum(item.expansion_count for item in self.member_telemetry):
            raise ValueError("candidate expansion_count must equal member telemetry total")
        if self.caller_ledger_before_fingerprint != self.caller_ledger_after_fingerprint:
            raise ValueError("pure candidate construction cannot mutate the caller ledger")
        if self.success != (self.complete and self.zero_overuse):
            raise ValueError("candidate success requires complete routing and zero overuse")
        if self.complete:
            if self.bundle is None:
                raise ValueError("a complete candidate requires a route bundle")
            if len(self.member_telemetry) != len(self.route_order) or not all(
                item.routed for item in self.member_telemetry
            ):
                raise ValueError("a complete candidate must route every member")
            if self.failed_member_id is not None:
                raise ValueError("a complete candidate cannot name a failed member")
            if self.zero_overuse:
                if self.failure_reason is not None or self.resource_overuse:
                    raise ValueError("a zero-overuse candidate cannot report a failure")
            elif (
                self.failure_reason is not BusCandidateFailureReason.FINAL_OVERUSE
                or not self.resource_overuse
            ):
                raise ValueError("a complete overused candidate requires exact final overuse")
        else:
            if self.zero_overuse:
                raise ValueError("an incomplete candidate cannot claim zero overuse")
            if self.failure_reason is None:
                raise ValueError("an incomplete candidate requires a typed failure reason")
            if self.bundle is not None:
                raise ValueError("an incomplete candidate cannot expose a route bundle")
        if self.success and (
            self.expansion_count > self.budget.max_total_expansions
            or any(
                item.expansion_count > self.budget.max_expansions_per_member
                for item in self.member_telemetry
            )
        ):
            raise ValueError("a successful candidate cannot exceed its expansion budget")
        return self

    def semantic_json(self) -> str:
        """Serialize bundle identity canonically, independent of frozenset order."""

        payload = self.model_dump(mode="json", exclude={"bundle"})
        payload["bundle_fingerprint"] = (
            None if self.bundle is None else self.bundle.semantic_fingerprint()
        )
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


def build_certified_bus_candidate(
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    geometry_registry: CertifiedLaneGeometryRegistry,
    prefixes_by_member: Mapping[str, CertifiedBusMemberPrefix],
    caller_ledger: OccupancyLedger,
    budget: BusCandidateBudget,
    *,
    policy: BusCandidatePolicy = DEFAULT_BUS_CANDIDATE_POLICY,
    history: Mapping[RoutingResourceKey, int] | None = None,
    present_factor_units: int = 0,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    clearance_groups: Sequence[ClearanceGroup] = (),
) -> BusCandidateResult:
    """Build one zero-overuse bundle without mutating caller-owned state.

    Prefixes and members are routed in canonical ``member_id`` order.  Search
    sees committed external claims plus earlier scratch member claims; only the
    scratch ledger is committed.  ``success`` remains an algorithmic routing
    result and is never an exact-geometry acceptance verdict.
    """

    ledger_before = caller_ledger.semantic_fingerprint()
    route_order = tuple(member.member_id for member in bus.members)
    common = {
        "bus_id": bus.bus_id,
        "bus_fingerprint": bus.semantic_fingerprint(),
        "allocation_fingerprint": allocation.allocation_fingerprint,
        "budget": budget,
        "policy": policy,
        "route_order": route_order,
        "caller_ledger_before_fingerprint": ledger_before,
    }

    binding_failure = _binding_failure(bus, allocation, profile)
    if binding_failure is not None:
        return _failed_result(common, caller_ledger, binding_failure)

    prefix_failure = _prefix_failure(
        bus,
        certificate,
        allocation,
        geometry_registry,
        prefixes_by_member,
    )
    if prefix_failure is not None:
        return _failed_result(common, caller_ledger, prefix_failure)

    return _build_bus_candidate_from_prefixes(
        static_layout=static_layout,
        netlist=netlist,
        bus=bus,
        allocation=allocation,
        prefixes_by_member={
            member_id: certified.prefix for member_id, certified in prefixes_by_member.items()
        },
        prefix_fingerprints_by_member={
            member_id: certified.prefix_fingerprint
            for member_id, certified in prefixes_by_member.items()
        },
        caller_ledger=caller_ledger,
        budget=budget,
        policy=policy,
        history=history,
        present_factor_units=present_factor_units,
        cost_policy=cost_policy,
        profile=profile,
        clearance_groups=clearance_groups,
        common=common,
    )


def _build_bus_candidate_from_prefixes(
    *,
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    bus: BusGroup,
    allocation: BusLaneAllocationResult,
    prefixes_by_member: Mapping[str, GridRoutePrefix],
    prefix_fingerprints_by_member: Mapping[str, str],
    caller_ledger: OccupancyLedger,
    budget: BusCandidateBudget,
    policy: BusCandidatePolicy,
    history: Mapping[RoutingResourceKey, int] | None,
    present_factor_units: int,
    cost_policy: NegotiatedCostPolicy,
    profile: PcbRuleProfile,
    clearance_groups: Sequence[ClearanceGroup],
    common: Mapping[str, object] | None = None,
) -> BusCandidateResult:
    """Route already-validated connected prefixes with ordinary candidate semantics."""

    if common is None:
        ledger_before = caller_ledger.semantic_fingerprint()
        route_order = tuple(member.member_id for member in bus.members)
        common = {
            "bus_id": bus.bus_id,
            "bus_fingerprint": bus.semantic_fingerprint(),
            "allocation_fingerprint": allocation.allocation_fingerprint,
            "budget": budget,
            "policy": policy,
            "route_order": route_order,
            "caller_ledger_before_fingerprint": ledger_before,
        }

    target_nets = frozenset(member.net_name for member in bus.members)
    if any(segment.net_name in target_nets for segment in static_layout.segments) or any(
        via.net_name in target_nets for via in static_layout.vias
    ):
        return _failed_result(common, caller_ledger, BusCandidateFailureReason.STATIC_TARGET_COPPER)

    committed = caller_ledger.committed_claims()
    if any(claim.net_name in target_nets for claim in committed):
        return _failed_result(common, caller_ledger, BusCandidateFailureReason.CALLER_MEMBER_CLAIMS)
    caller_overuse = caller_ledger.overuse()
    if caller_overuse and policy.caller_overuse_mode is BusCandidateCallerOveruseMode.REJECT:
        return _failed_result(
            common,
            caller_ledger,
            BusCandidateFailureReason.CALLER_OVERUSE,
            resource_overuse=caller_overuse,
        )
    if len(bus.members) > budget.max_members:
        return _failed_result(common, caller_ledger, BusCandidateFailureReason.MEMBER_BUDGET)
    if (
        not isinstance(present_factor_units, int)
        or isinstance(present_factor_units, bool)
        or present_factor_units < 0
    ):
        return _failed_result(
            common,
            caller_ledger,
            BusCandidateFailureReason.INVALID_ROUTING_INPUT,
        )

    scratch = OccupancyLedger(committed)
    domains = build_route_pairwise_clearance_domains(profile, clearance_groups)
    fixed_history = {} if history is None else dict(history)
    telemetry: list[BusMemberCandidateTelemetry] = []
    routes = []
    total_expansions = 0

    for member in bus.members:
        prefix = prefixes_by_member[member.member_id]
        prefix_fingerprint = prefix_fingerprints_by_member[member.member_id]
        remaining_total = budget.max_total_expansions - total_expansions
        effective_limit = min(budget.max_expansions_per_member, remaining_total)
        try:
            route = route_net_negotiated_candidate(
                static_layout,
                netlist,
                member.net_name,
                scratch,
                fixed_history,
                present_factor_units,
                cost_policy,
                track_width_mm=member.width_mm,
                grid_mm=prefix.grid_mm,
                profile=profile,
                clearance_groups=clearance_groups,
                pairwise_domains=domains,
                max_expansions=effective_limit,
                route_prefix=prefix,
            )
        except RoutingError as error:
            telemetry.append(
                BusMemberCandidateTelemetry(
                    member_id=member.member_id,
                    net_name=member.net_name,
                    prefix_fingerprint=prefix_fingerprint,
                    routed=False,
                    expansion_count=error.expansion_count,
                    routing_failure_reason=error.reason,
                )
            )
            if error.reason is RoutingFailureReason.EXPANSION_BUDGET:
                failure = (
                    BusCandidateFailureReason.TOTAL_EXPANSION_BUDGET
                    if remaining_total <= budget.max_expansions_per_member
                    else BusCandidateFailureReason.PER_MEMBER_EXPANSION_BUDGET
                )
            else:
                failure = BusCandidateFailureReason.ROUTING_ERROR
            return _failed_result(
                common,
                caller_ledger,
                failure,
                telemetry=tuple(telemetry),
                failed_member_id=member.member_id,
            )
        except (TypeError, ValueError):
            return _failed_result(
                common,
                caller_ledger,
                BusCandidateFailureReason.INVALID_ROUTING_INPUT,
                telemetry=tuple(telemetry),
                failed_member_id=member.member_id,
            )

        expansions = route.result.expansion_count
        if expansions > budget.max_expansions_per_member:
            telemetry.append(
                BusMemberCandidateTelemetry(
                    member_id=member.member_id,
                    net_name=member.net_name,
                    prefix_fingerprint=prefix_fingerprint,
                    routed=True,
                    expansion_count=expansions,
                    segment_count=len(route.result.segments),
                    via_count=len(route.result.vias),
                )
            )
            return _failed_result(
                common,
                caller_ledger,
                BusCandidateFailureReason.PER_MEMBER_EXPANSION_BUDGET,
                telemetry=tuple(telemetry),
                failed_member_id=member.member_id,
            )
        if total_expansions + expansions > budget.max_total_expansions:
            telemetry.append(
                BusMemberCandidateTelemetry(
                    member_id=member.member_id,
                    net_name=member.net_name,
                    prefix_fingerprint=prefix_fingerprint,
                    routed=True,
                    expansion_count=expansions,
                    segment_count=len(route.result.segments),
                    via_count=len(route.result.vias),
                )
            )
            return _failed_result(
                common,
                caller_ledger,
                BusCandidateFailureReason.TOTAL_EXPANSION_BUDGET,
                telemetry=tuple(telemetry),
                failed_member_id=member.member_id,
            )
        total_expansions += expansions
        telemetry.append(
            BusMemberCandidateTelemetry(
                member_id=member.member_id,
                net_name=member.net_name,
                prefix_fingerprint=prefix_fingerprint,
                routed=True,
                expansion_count=expansions,
                segment_count=len(route.result.segments),
                via_count=len(route.result.vias),
            )
        )
        scratch.commit(route.claims)
        routes.append(route)

    bundle = BusRouteBundle(bus=bus, allocation=allocation, member_routes=tuple(routes))
    overuse = scratch.overuse()
    ledger_after = caller_ledger.semantic_fingerprint()
    if overuse:
        return BusCandidateResult(
            success=False,
            complete=True,
            zero_overuse=False,
            **common,
            member_telemetry=tuple(telemetry),
            expansion_count=total_expansions,
            failure_reason=BusCandidateFailureReason.FINAL_OVERUSE,
            resource_overuse=overuse,
            caller_ledger_after_fingerprint=ledger_after,
            bundle=bundle,
        )

    return BusCandidateResult(
        success=True,
        complete=True,
        zero_overuse=True,
        **common,
        member_telemetry=tuple(telemetry),
        expansion_count=total_expansions,
        caller_ledger_after_fingerprint=ledger_after,
        bundle=bundle,
    )


def materialize_bus_bundle(static_layout: BoardLayout, bundle: BusRouteBundle) -> BoardLayout:
    """Return a lossless layout copy with one complete bus bundle appended."""

    target_nets = frozenset(member.net_name for member in bundle.bus.members)
    if any(segment.net_name in target_nets for segment in static_layout.segments) or any(
        via.net_name in target_nets for via in static_layout.vias
    ):
        raise ValueError("static layout already contains target bus copper")
    segments = tuple(segment for route in bundle.member_routes for segment in route.result.segments)
    vias = tuple(via for route in bundle.member_routes for via in route.result.vias)
    return replace(
        static_layout,
        segments=(*static_layout.segments, *segments),
        vias=(*static_layout.vias, *vias),
    )


def _binding_failure(
    bus: BusGroup,
    allocation: BusLaneAllocationResult,
    profile: PcbRuleProfile,
) -> BusCandidateFailureReason | None:
    try:
        validated = BusLaneAllocationResult.model_validate(allocation.model_dump(mode="python"))
    except ValueError:
        return BusCandidateFailureReason.INVALID_BUS_BINDING
    if not validated.success:
        return BusCandidateFailureReason.INVALID_BUS_BINDING
    if validated.bus_fingerprint != bus.semantic_fingerprint():
        return BusCandidateFailureReason.INVALID_BUS_BINDING
    if bus.rule_profile_id != profile.profile_id:
        return BusCandidateFailureReason.INVALID_BUS_BINDING
    member_by_id = {member.member_id: member for member in bus.members}
    assigned = {assignment.member_id for assignment in validated.assignments}
    if assigned != set(member_by_id):
        return BusCandidateFailureReason.INVALID_BUS_BINDING
    if any(
        assignment.member_id not in member_by_id
        or member_by_id[assignment.member_id].net_name != assignment.net_name
        for assignment in validated.assignments
    ):
        return BusCandidateFailureReason.INVALID_BUS_BINDING
    return None


def _prefix_failure(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    registry: CertifiedLaneGeometryRegistry,
    prefixes_by_member: Mapping[str, CertifiedBusMemberPrefix],
) -> BusCandidateFailureReason | None:
    member_by_id = {member.member_id: member for member in bus.members}
    if set(prefixes_by_member) != set(member_by_id):
        return BusCandidateFailureReason.INVALID_PREFIX_COVERAGE
    grids: set[float] = set()
    for member_id, member in member_by_id.items():
        certified_prefix = prefixes_by_member[member_id]
        if certified_prefix.member_id != member_id or certified_prefix.net_name != member.net_name:
            return BusCandidateFailureReason.INVALID_PREFIX_COVERAGE
        try:
            certified_prefix.require_authority(bus, certificate, allocation, registry)
        except ValueError:
            return BusCandidateFailureReason.INVALID_PREFIX_COVERAGE
        grids.add(certified_prefix.prefix.grid_mm)
    if len(grids) != 1:
        return BusCandidateFailureReason.INVALID_PREFIX_COVERAGE
    return None


def _failed_result(
    common: Mapping[str, object],
    caller_ledger: OccupancyLedger,
    reason: BusCandidateFailureReason,
    *,
    telemetry: tuple[BusMemberCandidateTelemetry, ...] = (),
    failed_member_id: str | None = None,
    resource_overuse: tuple[ResourceOveruseSummary, ...] = (),
) -> BusCandidateResult:
    return BusCandidateResult(
        success=False,
        complete=False,
        zero_overuse=False,
        **common,
        member_telemetry=telemetry,
        expansion_count=sum(item.expansion_count for item in telemetry),
        failure_reason=reason,
        failed_member_id=failed_member_id,
        resource_overuse=resource_overuse,
        caller_ledger_after_fingerprint=caller_ledger.semantic_fingerprint(),
    )
