"""Replay-bound accounting plan for ordered physical bus-swap carriers.

This module proves event coverage, isolated carrier replay, combined resource
occupancy, and cumulative via-policy accounting.  It does not compose carrier
copper into routed prefixes, commit a transaction, invoke an exact checker, or
materialize a board.  Schema v1 therefore rejects multiple physical events in
one corridor section because it has no certified intermediate portal authority.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_serializer, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult, allocate_bus_lanes
from pcbsmith.bus_geometry import CertifiedLaneGeometryRegistry
from pcbsmith.bus_ir import BusGroup, CorridorCapacityCertificate
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.bus_physical_swap import (
    BusPhysicalSwapPolicy,
    CertifiedBusSwapRegion,
    bus_physical_swap_board_geometry_fingerprint,
    bus_physical_swap_profile_fingerprint,
    bus_physical_swap_static_obstacle_fingerprint,
)
from pcbsmith.kicad.bus_swap_carrier import (
    BusSwapCarrierDisposition,
    CertifiedBusSwapCarrier,
    ReplayBoundCertifiedBusSwapCarrier,
    generate_certified_bus_swap_carrier,
)
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
    union_net_resource_claims,
)
from pcbsmith.routing_ir import ResourceOveruseSummary, RoutingIrModel
from pcbsmith.rule_profiles import PcbRuleProfile


class BusPhysicalSwapPlanDisposition(StrEnum):
    BUILT = "built"
    FAILED = "failed"


class BusPhysicalSwapPlanFailureReason(StrEnum):
    INVALID_EVENT_COVERAGE = "invalid_event_coverage"
    CARRIER_GENERATION_FAILED = "carrier_generation_failed"
    CROSS_CARRIER_CONFLICT = "cross_carrier_conflict"
    CUMULATIVE_VIA_POLICY = "cumulative_via_policy"


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resource_payload(resource: RoutingResourceKey) -> dict[str, Any]:
    return {
        "domain_id": resource.domain_id,
        "layer": resource.layer,
        "kind": resource.kind,
        "ix0": resource.ix0,
        "iy0": resource.iy0,
        "ix1": resource.ix1,
        "iy1": resource.iy1,
    }


def _claim_payload(claim: NetResourceClaims) -> dict[str, Any]:
    return {
        "net_name": claim.net_name,
        "resources": [_resource_payload(item) for item in sorted(claim.resources)],
    }


class BusPhysicalSwapPlanInput(RoutingIrModel):
    """Complete immutable authority consumed by one plan build."""

    schema_id: Literal["pcbsmith-bus-physical-swap-plan-input"] = (
        "pcbsmith-bus-physical-swap-plan-input"
    )
    schema_version: Literal[1] = 1
    layout_snapshot_json: str = Field(min_length=2)
    netlist_snapshot_json: str = Field(min_length=2)
    layout_snapshot_fingerprint: str
    netlist_snapshot_fingerprint: str
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    lane_geometry_registry: CertifiedLaneGeometryRegistry
    rule_profile: PcbRuleProfile
    physical_policy: BusPhysicalSwapPolicy
    initial_claims: tuple[NetResourceClaims, ...] = ()
    initial_occupancy_fingerprint: str
    regions: tuple[CertifiedBusSwapRegion, ...] = ()

    @field_serializer("initial_claims")
    def serialize_initial_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [_claim_payload(item) for item in claims]

    @model_validator(mode="after")
    def top_level_authority_is_exact(self) -> Self:
        layout = parse_canonical_board_layout_snapshot(self.layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)
        if self.layout_snapshot_fingerprint != board_layout_snapshot_fingerprint(
            self.layout_snapshot_json
        ):
            raise ValueError("plan layout snapshot fingerprint is stale")
        if self.netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            self.netlist_snapshot_json
        ):
            raise ValueError("plan netlist snapshot fingerprint is stale")
        if self.certificate.board_geometry_fingerprint != (
            bus_physical_swap_board_geometry_fingerprint(layout)
        ):
            raise ValueError("plan certificate board geometry is stale")
        if self.certificate.static_obstacle_fingerprint != (
            bus_physical_swap_static_obstacle_fingerprint(layout, netlist)
        ):
            raise ValueError("plan certificate static obstacle authority is stale")
        if self.certificate.rule_profile_fingerprint != (
            bus_physical_swap_profile_fingerprint(self.rule_profile)
        ):
            raise ValueError("plan certificate rule profile is stale")
        if self.certificate.demand_fingerprint != self.bus.semantic_fingerprint():
            raise ValueError("plan certificate bus demand is stale")
        if layout.placements or layout.graphics or layout.zones:
            raise ValueError("plan neutral board contains unsupported opaque geometry")
        if any(segment.layer not in {"F.Cu", "B.Cu"} for segment in layout.segments):
            raise ValueError("plan neutral board contains unsupported static copper")
        if self.bus.rule_profile_id != self.rule_profile.profile_id:
            raise ValueError("plan bus and rule-profile identities differ")
        if self.allocation.bus_fingerprint != self.bus.semantic_fingerprint():
            raise ValueError("plan allocation bus authority is stale")
        if self.allocation.certificate_fingerprint != self.certificate.semantic_fingerprint():
            raise ValueError("plan allocation certificate authority is stale")
        replayed_allocation = allocate_bus_lanes(
            self.bus, self.certificate, budget=self.allocation.budget
        )
        if replayed_allocation != self.allocation:
            raise ValueError("plan semantic allocation does not replay exactly")
        if not self.allocation.success:
            raise ValueError("physical-swap plan requires a successful semantic allocation")
        event_sections = [item.section_id for item in self.allocation.swaps]
        if len(set(event_sections)) != len(event_sections):
            raise ValueError(
                "schema-v1 physical swaps allow at most one event per corridor section"
            )
        if self.lane_geometry_registry.certificate_fingerprint != (
            self.certificate.semantic_fingerprint()
        ):
            raise ValueError("plan lane registry certificate authority is stale")
        if self.lane_geometry_registry.allocation_fingerprint != (
            self.allocation.allocation_fingerprint
        ):
            raise ValueError("plan lane registry allocation authority is stale")
        if self.lane_geometry_registry.grid_mm != self.certificate.grid_mm:
            raise ValueError("plan lane registry grid differs from its certificate")
        component_ids = {item.reference for item in netlist.components}
        net_nodes = {item.name: set(item.nodes) for item in netlist.nets}
        if len(component_ids) != len(netlist.components) or len(net_nodes) != len(netlist.nets):
            raise ValueError("plan board netlist identities must be unique")
        for member in self.bus.members:
            nodes = net_nodes.get(member.net_name)
            if nodes is None:
                raise ValueError("plan board netlist is missing a bus-member net")
            for terminal in member.terminals:
                if (
                    terminal.component_ref not in component_ids
                    or (terminal.component_ref, terminal.pad_number) not in nodes
                ):
                    raise ValueError("plan board netlist bus-terminal ownership is stale")

        slots = {
            (section.section_id, slot.slot_id): slot
            for section in self.certificate.sections
            for slot in section.lane_slots
        }
        members = {item.member_id: item for item in self.bus.members}
        geometries = {
            item.centerline_geometry_id: item for item in self.lane_geometry_registry.geometries
        }
        expected_geometry_ids: set[str] = set()
        for assignment in self.allocation.assignments:
            slot = slots.get((assignment.section_id, assignment.slot_id))
            assigned_member = members.get(assignment.member_id)
            if slot is None or assigned_member is None or slot.layer != assignment.layer:
                raise ValueError("plan allocation assignment is stale")
            geometry = geometries.get(slot.centerline_geometry_id)
            if geometry is None or geometry.section_id != assignment.section_id:
                raise ValueError("plan lane registry assignment geometry is stale")
            if (
                geometry.track_width_mm != assigned_member.width_mm
                or assigned_member.width_mm > slot.maximum_track_width_mm
                or assigned_member.width_mm < self.rule_profile.geometry.minimum_trace_width_mm
            ):
                raise ValueError("plan lane registry track width authority is stale")
            expected_geometry_ids.add(slot.centerline_geometry_id)
        if set(geometries) != expected_geometry_ids:
            raise ValueError("plan lane registry must contain exact assigned geometries")

        claims = tuple(sorted(self.initial_claims, key=lambda item: item.net_name))
        if len({item.net_name for item in claims}) != len(claims):
            raise ValueError("plan initial occupancy contains duplicate net identities")
        ledger = OccupancyLedger(claims)
        if ledger.semantic_fingerprint() != self.initial_occupancy_fingerprint:
            raise ValueError("plan initial occupancy fingerprint is stale")
        event_member_ids = {
            member_id
            for event in self.allocation.swaps
            for member_id in (event.first_member_id, event.second_member_id)
        }
        event_net_names = {
            member.net_name for member in self.bus.members if member.member_id in event_member_ids
        }
        if event_net_names & {item.net_name for item in claims}:
            raise ValueError("plan initial occupancy must be foreign to every swap event")
        object.__setattr__(self, "initial_claims", claims)
        event_windows = {item.window_id for item in self.allocation.swaps}
        policy_windows = {item.window_id for item in self.physical_policy.windows}
        if event_windows != policy_windows:
            raise ValueError("plan physical policy does not map exact swap windows")
        if len(self.allocation.swaps) > self.physical_policy.budget.max_events:
            raise ValueError("plan physical policy event budget is insufficient")

        for region in self.regions:
            region.require_authority()
            if (
                region.layout_snapshot_json != self.layout_snapshot_json
                or region.netlist_snapshot_json != self.netlist_snapshot_json
                or region.layout_snapshot_fingerprint != self.layout_snapshot_fingerprint
                or region.netlist_snapshot_fingerprint != self.netlist_snapshot_fingerprint
                or region.bus != self.bus
                or region.certificate != self.certificate
                or region.allocation != self.allocation
                or region.lane_geometry_registry != self.lane_geometry_registry
                or region.rule_profile != self.rule_profile
                or region.physical_policy != self.physical_policy
            ):
                raise ValueError("plan region differs from its complete top-level authority")
        return self

    @property
    def layout(self) -> BoardLayout:
        return parse_canonical_board_layout_snapshot(self.layout_snapshot_json)

    @property
    def netlist(self) -> BoardNetlist:
        return parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)


class BusPhysicalSwapMemberViaAccounting(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-member-via-accounting"] = (
        "pcbsmith-bus-physical-swap-member-via-accounting"
    )
    schema_version: Literal[1] = 1
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    semantic_via_count: int = Field(ge=0)
    physical_via_count: int = Field(ge=0)
    combined_via_count: int = Field(ge=0)

    @model_validator(mode="after")
    def total_is_exact(self) -> Self:
        if self.combined_via_count != self.semantic_via_count + self.physical_via_count:
            raise ValueError("combined via count must equal semantic plus physical")
        return self


class BusPhysicalSwapPlanTelemetry(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-plan-telemetry"] = (
        "pcbsmith-bus-physical-swap-plan-telemetry"
    )
    schema_version: Literal[1] = 1
    declared_event_count: int = Field(ge=0)
    region_count: int = Field(ge=0)
    carrier_attempt_count: int = Field(ge=0)
    generated_carrier_count: int = Field(ge=0)
    failed_carrier_count: int = Field(ge=0)
    candidate_attempt_count: int = Field(ge=0)
    expansion_count: int = Field(ge=0)


class BusPhysicalSwapPlan(RoutingIrModel):
    """Successful ordered coverage, occupancy, and via-accounting authority."""

    schema_id: Literal["pcbsmith-bus-physical-swap-plan"] = "pcbsmith-bus-physical-swap-plan"
    schema_version: Literal[1] = 1
    replay_input: BusPhysicalSwapPlanInput
    carrier_results: tuple[ReplayBoundCertifiedBusSwapCarrier, ...]
    carriers: tuple[CertifiedBusSwapCarrier, ...]
    combined_claims: tuple[NetResourceClaims, ...]
    combined_occupancy_fingerprint: str
    via_accounting: tuple[BusPhysicalSwapMemberViaAccounting, ...]
    telemetry: BusPhysicalSwapPlanTelemetry
    plan_fingerprint: str

    @field_serializer("combined_claims")
    def serialize_combined_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [_claim_payload(item) for item in claims]

    @model_validator(mode="after")
    def successful_plan_rederives_exactly(self) -> Self:
        derived = _derive_plan_data(self.replay_input, self.carrier_results)
        if derived.failure_reason is not None:
            raise ValueError("successful plan retains failed coverage, carriers, or accounting")
        if (
            self.carriers
            != tuple(
                result.outcome.carrier
                for result in self.carrier_results
                if result.outcome.carrier is not None
            )
            or self.combined_claims != derived.combined_claims
            or self.combined_occupancy_fingerprint != derived.combined_occupancy_fingerprint
            or self.via_accounting != derived.via_accounting
            or self.telemetry != derived.telemetry
        ):
            raise ValueError("successful physical-swap plan data does not rederive exactly")
        expected = _fingerprint(
            {
                "schema_id": "pcbsmith-bus-physical-swap-plan-decision",
                "schema_version": 1,
                "plan": self.model_dump(mode="json", exclude={"plan_fingerprint"}),
            }
        )
        if self.plan_fingerprint != expected:
            raise ValueError("physical-swap plan fingerprint is stale")
        return self


class BusPhysicalSwapPlanBuildOutcome(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-plan-build-outcome"] = (
        "pcbsmith-bus-physical-swap-plan-build-outcome"
    )
    schema_version: Literal[1] = 1
    disposition: BusPhysicalSwapPlanDisposition
    failure_reason: BusPhysicalSwapPlanFailureReason | None
    carrier_results: tuple[ReplayBoundCertifiedBusSwapCarrier, ...]
    combined_claims: tuple[NetResourceClaims, ...] = ()
    combined_occupancy_fingerprint: str | None = None
    combined_resource_overuse: tuple[ResourceOveruseSummary, ...] = ()
    via_accounting: tuple[BusPhysicalSwapMemberViaAccounting, ...] = ()
    telemetry: BusPhysicalSwapPlanTelemetry
    plan: BusPhysicalSwapPlan | None
    outcome_fingerprint: str

    @field_serializer("combined_claims")
    def serialize_combined_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [_claim_payload(item) for item in claims]

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        built = self.disposition is BusPhysicalSwapPlanDisposition.BUILT
        if built != (self.plan is not None) or built == (self.failure_reason is not None):
            raise ValueError("physical-swap plan outcome disposition is incoherent")
        if built and self.combined_resource_overuse:
            raise ValueError("successful physical-swap plan cannot retain resource overuse")
        if self.plan is not None and (
            self.carrier_results != self.plan.carrier_results
            or self.combined_claims != self.plan.combined_claims
            or self.combined_occupancy_fingerprint != self.plan.combined_occupancy_fingerprint
            or self.via_accounting != self.plan.via_accounting
            or self.telemetry != self.plan.telemetry
        ):
            raise ValueError("successful outcome and retained plan data differ")
        if (self.failure_reason is BusPhysicalSwapPlanFailureReason.CROSS_CARRIER_CONFLICT) != bool(
            self.combined_resource_overuse
        ):
            raise ValueError("cross-carrier failure must equal retained resource overuse")
        expected = _fingerprint(
            {
                "schema_id": "pcbsmith-bus-physical-swap-plan-outcome-decision",
                "schema_version": 1,
                "outcome": self.model_dump(mode="json", exclude={"outcome_fingerprint"}),
            }
        )
        if self.outcome_fingerprint != expected:
            raise ValueError("physical-swap plan outcome fingerprint is stale")
        return self


class ReplayBoundBusPhysicalSwapPlan(RoutingIrModel):
    """Input plus build outcome proven by deterministic allocation/carrier replay."""

    schema_id: Literal["pcbsmith-replay-bound-bus-physical-swap-plan"] = (
        "pcbsmith-replay-bound-bus-physical-swap-plan"
    )
    schema_version: Literal[1] = 1
    replay_input: BusPhysicalSwapPlanInput
    outcome: BusPhysicalSwapPlanBuildOutcome

    @model_validator(mode="after")
    def build_replays_exactly(self) -> Self:
        replay_input = BusPhysicalSwapPlanInput.model_validate_json(
            self.replay_input.model_dump_json()
        )
        if replay_input != self.replay_input:
            raise ValueError("physical-swap plan input changed during JSON reconstruction")
        replayed = _build_outcome(replay_input)
        if replayed != self.outcome:
            raise ValueError("retained physical-swap plan outcome does not equal exact replay")
        return self


class _DerivedPlanData(RoutingIrModel):
    failure_reason: BusPhysicalSwapPlanFailureReason | None
    combined_claims: tuple[NetResourceClaims, ...]
    combined_occupancy_fingerprint: str | None
    resource_overuse: tuple[ResourceOveruseSummary, ...]
    via_accounting: tuple[BusPhysicalSwapMemberViaAccounting, ...]
    telemetry: BusPhysicalSwapPlanTelemetry

    @field_serializer("combined_claims")
    def serialize_combined_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [_claim_payload(item) for item in claims]


def build_replay_bound_bus_physical_swap_plan(
    *,
    layout: BoardLayout,
    netlist: BoardNetlist,
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    lane_geometry_registry: CertifiedLaneGeometryRegistry,
    rule_profile: PcbRuleProfile,
    physical_policy: BusPhysicalSwapPolicy,
    initial_occupancy: OccupancyLedger,
    regions: tuple[CertifiedBusSwapRegion, ...],
) -> ReplayBoundBusPhysicalSwapPlan:
    """Build one immutable plan without mutating the caller occupancy ledger."""

    claims_before = initial_occupancy.committed_claims()
    fingerprint_before = initial_occupancy.semantic_fingerprint()
    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    replay_input = BusPhysicalSwapPlanInput(
        layout_snapshot_json=layout_json,
        netlist_snapshot_json=netlist_json,
        layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(layout_json),
        netlist_snapshot_fingerprint=board_netlist_snapshot_fingerprint(netlist_json),
        bus=bus,
        certificate=certificate,
        allocation=allocation,
        lane_geometry_registry=lane_geometry_registry,
        rule_profile=rule_profile,
        physical_policy=physical_policy,
        initial_claims=claims_before,
        initial_occupancy_fingerprint=fingerprint_before,
        regions=regions,
    )
    outcome = _build_outcome(replay_input)
    if (
        initial_occupancy.committed_claims() != claims_before
        or initial_occupancy.semantic_fingerprint() != fingerprint_before
    ):
        raise RuntimeError("physical-swap plan build mutated caller occupancy")
    return ReplayBoundBusPhysicalSwapPlan(replay_input=replay_input, outcome=outcome)


def _build_outcome(replay_input: BusPhysicalSwapPlanInput) -> BusPhysicalSwapPlanBuildOutcome:
    if not _coverage_is_exact(replay_input):
        telemetry = _telemetry(replay_input, ())
        return _outcome(
            disposition=BusPhysicalSwapPlanDisposition.FAILED,
            failure_reason=BusPhysicalSwapPlanFailureReason.INVALID_EVENT_COVERAGE,
            carrier_results=(),
            derived=_DerivedPlanData(
                failure_reason=BusPhysicalSwapPlanFailureReason.INVALID_EVENT_COVERAGE,
                combined_claims=(),
                combined_occupancy_fingerprint=None,
                resource_overuse=(),
                via_accounting=(),
                telemetry=telemetry,
            ),
            plan=None,
        )

    carrier_results = tuple(
        generate_certified_bus_swap_carrier(region, OccupancyLedger(replay_input.initial_claims))
        for region in replay_input.regions
    )
    derived = _derive_plan_data(replay_input, carrier_results)
    if derived.failure_reason is not None:
        return _outcome(
            disposition=BusPhysicalSwapPlanDisposition.FAILED,
            failure_reason=derived.failure_reason,
            carrier_results=carrier_results,
            derived=derived,
            plan=None,
        )

    values: dict[str, Any] = {
        "replay_input": replay_input,
        "carrier_results": carrier_results,
        "carriers": tuple(
            result.outcome.carrier
            for result in carrier_results
            if result.outcome.carrier is not None
        ),
        "combined_claims": derived.combined_claims,
        "combined_occupancy_fingerprint": derived.combined_occupancy_fingerprint,
        "via_accounting": derived.via_accounting,
        "telemetry": derived.telemetry,
    }
    payload = BusPhysicalSwapPlan.model_construct(**values, plan_fingerprint="0" * 64).model_dump(
        mode="json", exclude={"plan_fingerprint"}
    )
    values["plan_fingerprint"] = _fingerprint(
        {
            "schema_id": "pcbsmith-bus-physical-swap-plan-decision",
            "schema_version": 1,
            "plan": payload,
        }
    )
    plan = BusPhysicalSwapPlan.model_validate(values)
    return _outcome(
        disposition=BusPhysicalSwapPlanDisposition.BUILT,
        failure_reason=None,
        carrier_results=carrier_results,
        derived=derived,
        plan=plan,
    )


def _coverage_is_exact(replay_input: BusPhysicalSwapPlanInput) -> bool:
    events = replay_input.allocation.swaps
    regions = replay_input.regions
    if len(regions) != len(events):
        return False
    if len({item.region_id for item in regions}) != len(regions):
        return False
    return tuple(item.swap_event for item in regions) == events


def _derive_plan_data(
    replay_input: BusPhysicalSwapPlanInput,
    carrier_results: tuple[ReplayBoundCertifiedBusSwapCarrier, ...],
) -> _DerivedPlanData:
    telemetry = _telemetry(replay_input, carrier_results)
    if not _coverage_is_exact(replay_input) or len(carrier_results) != len(replay_input.regions):
        return _DerivedPlanData(
            failure_reason=BusPhysicalSwapPlanFailureReason.INVALID_EVENT_COVERAGE,
            combined_claims=(),
            combined_occupancy_fingerprint=None,
            resource_overuse=(),
            via_accounting=(),
            telemetry=telemetry,
        )
    for region, result in zip(replay_input.regions, carrier_results, strict=True):
        if (
            result.region != region
            or result.initial_claims != replay_input.initial_claims
            or result.initial_occupancy_fingerprint != replay_input.initial_occupancy_fingerprint
            or result.outcome.disposition is not BusSwapCarrierDisposition.GENERATED
            or result.outcome.carrier is None
        ):
            return _DerivedPlanData(
                failure_reason=BusPhysicalSwapPlanFailureReason.CARRIER_GENERATION_FAILED,
                combined_claims=(),
                combined_occupancy_fingerprint=None,
                resource_overuse=(),
                via_accounting=(),
                telemetry=telemetry,
            )

    ledger = OccupancyLedger(replay_input.initial_claims)
    accumulated_by_net: dict[str, NetResourceClaims] = {}
    for result in carrier_results:
        carrier = result.outcome.carrier
        if carrier is None:
            raise RuntimeError("generated carrier result unexpectedly lacks a carrier")
        for member in carrier.members:
            previous = accumulated_by_net.get(
                member.net_name, NetResourceClaims(member.net_name, frozenset())
            )
            combined = union_net_resource_claims(member.net_name, previous, member.claims)
            accumulated_by_net[member.net_name] = combined
            ledger.commit(combined)
    combined_claims = ledger.committed_claims()
    combined_fingerprint = ledger.semantic_fingerprint()
    overuse = ledger.overuse()
    accounting = _via_accounting(replay_input, carrier_results)
    policy_ok = _via_policy_is_satisfied(replay_input, accounting)
    if overuse:
        failure = BusPhysicalSwapPlanFailureReason.CROSS_CARRIER_CONFLICT
    elif not policy_ok:
        failure = BusPhysicalSwapPlanFailureReason.CUMULATIVE_VIA_POLICY
    else:
        failure = None
    return _DerivedPlanData(
        failure_reason=failure,
        combined_claims=combined_claims,
        combined_occupancy_fingerprint=combined_fingerprint,
        resource_overuse=overuse,
        via_accounting=accounting,
        telemetry=telemetry,
    )


def _via_accounting(
    replay_input: BusPhysicalSwapPlanInput,
    carrier_results: tuple[ReplayBoundCertifiedBusSwapCarrier, ...],
) -> tuple[BusPhysicalSwapMemberViaAccounting, ...]:
    semantic = {item.member_id: item.via_count for item in replay_input.allocation.via_counts}
    physical = {item.member_id: 0 for item in replay_input.bus.members}
    for result in carrier_results:
        carrier = result.outcome.carrier
        if carrier is None:
            continue
        for member in carrier.members:
            physical[member.member_id] += len(member.vias)
    return tuple(
        BusPhysicalSwapMemberViaAccounting(
            member_id=member.member_id,
            net_name=member.net_name,
            semantic_via_count=semantic[member.member_id],
            physical_via_count=physical[member.member_id],
            combined_via_count=semantic[member.member_id] + physical[member.member_id],
        )
        for member in sorted(replay_input.bus.members, key=lambda item: item.member_id)
    )


def _via_policy_is_satisfied(
    replay_input: BusPhysicalSwapPlanInput,
    accounting: tuple[BusPhysicalSwapMemberViaAccounting, ...],
) -> bool:
    if not accounting:
        return True
    policy = replay_input.physical_policy
    bus_policy = replay_input.bus.layer_policy.via_policy
    physical = tuple(item.physical_via_count for item in accounting)
    combined = tuple(item.combined_via_count for item in accounting)
    spread = max(combined) - min(combined)
    return (
        max(physical) <= policy.maximum_physical_vias_per_member
        and max(combined) <= policy.maximum_combined_vias_per_member
        and spread <= policy.maximum_combined_via_count_spread
        and max(combined) <= bus_policy.maximum_vias_per_member
        and (
            bus_policy.maximum_via_count_spread is None
            or spread <= bus_policy.maximum_via_count_spread
        )
    )


def _telemetry(
    replay_input: BusPhysicalSwapPlanInput,
    carrier_results: tuple[ReplayBoundCertifiedBusSwapCarrier, ...],
) -> BusPhysicalSwapPlanTelemetry:
    attempts = tuple(
        attempt for result in carrier_results for attempt in result.outcome.attempted_candidates
    )
    generated = sum(
        result.outcome.disposition is BusSwapCarrierDisposition.GENERATED
        for result in carrier_results
    )
    return BusPhysicalSwapPlanTelemetry(
        declared_event_count=len(replay_input.allocation.swaps),
        region_count=len(replay_input.regions),
        carrier_attempt_count=len(carrier_results),
        generated_carrier_count=generated,
        failed_carrier_count=len(carrier_results) - generated,
        candidate_attempt_count=len(attempts),
        expansion_count=sum(item.expansion_count for item in attempts),
    )


def _outcome(
    *,
    disposition: BusPhysicalSwapPlanDisposition,
    failure_reason: BusPhysicalSwapPlanFailureReason | None,
    carrier_results: tuple[ReplayBoundCertifiedBusSwapCarrier, ...],
    derived: _DerivedPlanData,
    plan: BusPhysicalSwapPlan | None,
) -> BusPhysicalSwapPlanBuildOutcome:
    values: dict[str, Any] = {
        "disposition": disposition,
        "failure_reason": failure_reason,
        "carrier_results": carrier_results,
        "combined_claims": derived.combined_claims,
        "combined_occupancy_fingerprint": derived.combined_occupancy_fingerprint,
        "combined_resource_overuse": derived.resource_overuse,
        "via_accounting": derived.via_accounting,
        "telemetry": derived.telemetry,
        "plan": plan,
    }
    payload = BusPhysicalSwapPlanBuildOutcome.model_construct(
        **values, outcome_fingerprint="0" * 64
    ).model_dump(mode="json", exclude={"outcome_fingerprint"})
    values["outcome_fingerprint"] = _fingerprint(
        {
            "schema_id": "pcbsmith-bus-physical-swap-plan-outcome-decision",
            "schema_version": 1,
            "outcome": payload,
        }
    )
    return BusPhysicalSwapPlanBuildOutcome.model_validate(values)
