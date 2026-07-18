"""Pure generated same-layer bus escapes, certified prefixes, and c2 candidate.

This opt-in R4.2c4c adapter consumes live c4a escape graphs and the c4b
endpoint search.  It never materializes a board, calls an exact checker, or
mutates caller routing state.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_geometry import (
    CertifiedBusEscapeGraphRegistry,
    CertifiedBusEscapeRegion,
    CertifiedBusTrunkRealization,
    CertifiedLaneGeometryRegistry,
    realize_certified_trunk_subset,
    realize_certified_trunks,
)
from pcbsmith.bus_ir import BusGroup, CorridorCapacityCertificate
from pcbsmith.kicad.astar_router import RoutingError
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.bus_candidate import (
    DEFAULT_BUS_CANDIDATE_POLICY,
    BusCandidateBudget,
    BusCandidateFailureReason,
    BusCandidatePolicy,
    BusCandidateResult,
    build_certified_bus_candidate,
)
from pcbsmith.kicad.bus_integration import (
    CertifiedBusMemberPrefix,
    CertifiedBusPigtail,
    CertifiedBusTransitionVia,
    compose_member_route_prefix,
)
from pcbsmith.kicad.bus_transition import (
    BusTransitionBudget,
    generate_certified_bus_transition_vias,
)
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_grid import (
    CertifiedEndpointGraph,
    CertifiedEndpointTerminalSource,
    GridNode,
    certified_endpoint_graph_fingerprint,
    route_certified_endpoint_to_portal,
)
from pcbsmith.kicad.negotiated_resources import OccupancyLedger, RoutingResourceKey
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.routing_ir import RoutingFailureReason, RoutingIrModel
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

ClearanceGroup = tuple[Collection[str], Collection[str], float, Collection[str]]


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_layout_fingerprint(layout: BoardLayout) -> str:
    canonical = replace(
        layout,
        placements=tuple(
            sorted(
                layout.placements,
                key=lambda item: (
                    item[0].reference,
                    item[0].value,
                    item[0].footprint,
                    item[0].uuid_path,
                    tuple(sorted(item[0].fields)),
                    item[1],
                ),
            )
        ),
        segments=tuple(
            sorted(
                layout.segments,
                key=lambda item: (
                    item.net_name,
                    item.layer,
                    item.width_mm,
                    item.x1,
                    item.y1,
                    item.x2,
                    item.y2,
                ),
            )
        ),
        vias=tuple(
            sorted(
                layout.vias,
                key=lambda item: (
                    item.net_name,
                    item.x,
                    item.y,
                    item.size_mm,
                    item.drill_mm,
                    item.front_mask.value,
                    item.back_mask.value,
                ),
            )
        ),
        part_y_mm=tuple(sorted(layout.part_y_mm)),
        part_rotation=tuple(sorted(layout.part_rotation)),
        zones=tuple(sorted(layout.zones)),
        graphics=tuple(sorted(layout.graphics)),
        part_flip=tuple(sorted(layout.part_flip)),
        hide_references=tuple(sorted(layout.hide_references)),
        part_reference_at=tuple(sorted(layout.part_reference_at)),
        mask_apertures=tuple(
            sorted(layout.mask_apertures, key=lambda item: item.semantic_fingerprint())
        ),
        cutouts=tuple(sorted(layout.cutouts, key=lambda item: item.semantic_fingerprint())),
    )
    return board_layout_fingerprint(canonical)


def _netlist_fingerprint(netlist: BoardNetlist) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-generated-bus-escape-netlist",
            "schema_version": 1,
            "components": sorted(
                (
                    {
                        "reference": item.reference,
                        "value": item.value,
                        "footprint": item.footprint,
                        "uuid_path": item.uuid_path,
                        "fields": sorted(item.fields),
                    }
                    for item in netlist.components
                ),
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
            "nets": sorted(
                ({"name": item.name, "nodes": sorted(item.nodes)} for item in netlist.nets),
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
        }
    )


def _canonical_clearance_groups(
    groups: Sequence[ClearanceGroup],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]], ...]:
    normalized: set[tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]]] = set()
    for nets_a, nets_b, gap_mm, exempt in groups:
        if not math.isfinite(gap_mm) or gap_mm < 0:
            raise ValueError("escape clearance gap must be finite and non-negative")
        low, high = sorted((tuple(sorted(set(nets_a))), tuple(sorted(set(nets_b)))))
        exemptions = tuple(sorted(set(exempt)))
        if (
            not low
            or not high
            or any(not item or item != item.strip() for item in (*low, *high, *exemptions))
        ):
            raise ValueError("escape clearance identities must be non-empty and stripped")
        normalized.add((low, high, gap_mm, exemptions))
    return tuple(sorted(normalized))


class BusEscapeFailureReason(StrEnum):
    INVALID_AUTHORITY = "invalid_authority"
    TRANSITION_VIAS_UNSUPPORTED = "transition_vias_unsupported"
    TRANSITION_CARRIER_GENERATION = "transition_carrier_generation"
    INVALID_ESCAPE_AUTHORITY = "invalid_escape_authority"
    INVALID_SOURCE_BINDING = "invalid_source_binding"
    INVALID_GRAPH_BINDING = "invalid_graph_binding"
    SOURCE_AT_PORTAL_UNSUPPORTED = "source_at_portal_unsupported"
    MEMBER_BUDGET = "member_budget"
    TERMINAL_BUDGET = "terminal_budget"
    PER_TERMINAL_EXPANSION_BUDGET = "per_terminal_expansion_budget"
    PER_MEMBER_EXPANSION_BUDGET = "per_member_expansion_budget"
    TOTAL_EXPANSION_BUDGET = "total_expansion_budget"
    ROUTING_ERROR = "routing_error"
    PREFIX_COMPOSITION = "prefix_composition"
    CANDIDATE_FAILURE = "candidate_failure"


class BusEscapeBudget(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-escape-budget"] = "pcbsmith-bus-escape-budget"
    schema_version: Literal[1] = 1
    max_members: int = Field(ge=0)
    max_terminals: int = Field(ge=0)
    max_expansions_per_terminal: int = Field(ge=0)
    max_expansions_per_member: int = Field(ge=0)
    max_total_expansions: int = Field(ge=0)


class BusEscapeInputBinding(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-escape-input-binding"] = "pcbsmith-bus-escape-input-binding"
    schema_version: Literal[1] = 1
    canonical_payload_json: str = Field(min_length=2)

    @model_validator(mode="after")
    def payload_is_canonical(self) -> Self:
        try:
            payload = json.loads(self.canonical_payload_json)
        except json.JSONDecodeError as error:
            raise ValueError("escape input binding is not valid JSON") from error
        if not isinstance(payload, dict) or payload.get("schema_id") != (
            "pcbsmith-generated-bus-escape-inputs"
        ):
            raise ValueError("escape input binding schema is invalid")
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if canonical != self.canonical_payload_json:
            raise ValueError("escape input binding JSON is not canonical")
        return self


class BusEscapeTerminalTelemetry(RoutingIrModel):
    member_id: str = Field(min_length=1)
    terminal_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    expansion_count: int = Field(ge=0)
    routed: bool
    connection_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    search_input_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pigtail_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    routing_failure_reason: RoutingFailureReason | None = None
    failure_reason: BusEscapeFailureReason | None = None

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        fingerprints = (
            self.connection_fingerprint,
            self.search_input_fingerprint,
            self.pigtail_fingerprint,
        )
        if self.routed:
            if any(item is None for item in fingerprints):
                raise ValueError("routed terminal telemetry requires all generated fingerprints")
            if self.routing_failure_reason is not None or self.failure_reason is not None:
                raise ValueError("routed terminal telemetry cannot carry failure")
        elif any(item is not None for item in fingerprints) or self.failure_reason is None:
            raise ValueError("failed terminal telemetry must carry only a typed failure")
        return self


class BusEscapeMemberTelemetry(RoutingIrModel):
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    terminal_ids: tuple[str, ...]
    expansion_count: int = Field(ge=0)
    completed: bool
    prefix_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        if tuple(sorted(set(self.terminal_ids))) != self.terminal_ids:
            raise ValueError("member telemetry terminals must be canonical and unique")
        if self.completed != (self.prefix_fingerprint is not None):
            raise ValueError("completed member telemetry requires exactly one prefix")
        return self


class BusEscapeGenerationResult(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-escape-generation-result"] = (
        "pcbsmith-bus-escape-generation-result"
    )
    schema_version: Literal[1] = 1
    success: bool
    bus_id: str = Field(min_length=1)
    bus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    escape_registry_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_binding: BusEscapeInputBinding
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: BusEscapeBudget
    candidate_budget: BusCandidateBudget
    terminal_order: tuple[str, ...]
    terminal_telemetry: tuple[BusEscapeTerminalTelemetry, ...] = ()
    member_telemetry: tuple[BusEscapeMemberTelemetry, ...] = ()
    escape_expansion_count: int = Field(ge=0)
    pigtails: tuple[CertifiedBusPigtail, ...] = ()
    prefixes_by_member: tuple[tuple[str, CertifiedBusMemberPrefix], ...] = ()
    candidate: BusCandidateResult | None = None
    failure_reason: BusEscapeFailureReason | None = None
    candidate_failure_reason: BusCandidateFailureReason | None = None
    failed_member_id: str | None = None
    failed_terminal_id: str | None = None
    caller_ledger_before_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    caller_ledger_after_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def outcome_is_canonical_and_nested(self) -> Self:
        if self.input_fingerprint != self.input_binding.semantic_fingerprint():
            raise ValueError("escape input fingerprint is stale")
        if self.caller_ledger_before_fingerprint != self.caller_ledger_after_fingerprint:
            raise ValueError("generated escape construction cannot mutate caller state")
        if tuple(sorted(set(self.terminal_order))) != self.terminal_order:
            raise ValueError("escape terminal order must be canonical and unique")
        attempted = tuple(item.terminal_id for item in self.terminal_telemetry)
        if attempted != self.terminal_order[: len(attempted)]:
            raise ValueError("terminal telemetry must be an attempted-order prefix")
        if self.escape_expansion_count != sum(
            item.expansion_count for item in self.terminal_telemetry
        ):
            raise ValueError("escape expansion count must equal terminal telemetry work")
        prefix_keys = tuple(item[0] for item in self.prefixes_by_member)
        if prefix_keys != tuple(sorted(set(prefix_keys))):
            raise ValueError("generated prefixes must be canonical and unique")
        if any(key != prefix.member_id for key, prefix in self.prefixes_by_member):
            raise ValueError("generated prefix mapping key is stale")
        if tuple(sorted(self.pigtails, key=lambda item: (item.member_id, item.terminal_id))) != (
            self.pigtails
        ):
            raise ValueError("generated pigtails must be canonical")
        for pigtail in self.pigtails:
            if CertifiedBusPigtail.model_validate_json(pigtail.model_dump_json()) != pigtail:
                raise ValueError("generated pigtail failed nested revalidation")
        for _member_id, prefix in self.prefixes_by_member:
            if CertifiedBusMemberPrefix.model_validate_json(prefix.model_dump_json()) != prefix:
                raise ValueError("generated prefix failed nested revalidation")
        if self.candidate is not None and (
            BusCandidateResult.model_validate_json(self.candidate.model_dump_json())
            != self.candidate
        ):
            raise ValueError("generated candidate failed nested revalidation")
        routed_pigtail_fingerprints = {
            item.pigtail_fingerprint for item in self.terminal_telemetry if item.routed
        }
        if routed_pigtail_fingerprints != {item.semantic_fingerprint() for item in self.pigtails}:
            raise ValueError("terminal telemetry does not exactly bind generated pigtails")
        completed_prefixes = {
            item.prefix_fingerprint for item in self.member_telemetry if item.completed
        }
        if completed_prefixes != {
            prefix.prefix_fingerprint for _key, prefix in self.prefixes_by_member
        }:
            raise ValueError("member telemetry does not exactly bind generated prefixes")
        if self.success:
            if (
                self.failure_reason is not None
                or self.candidate_failure_reason is not None
                or self.failed_member_id is not None
                or self.failed_terminal_id is not None
                or self.candidate is None
                or not self.candidate.success
                or len(self.terminal_telemetry) != len(self.terminal_order)
                or not all(item.routed for item in self.terminal_telemetry)
                or not all(item.completed for item in self.member_telemetry)
            ):
                raise ValueError("successful escape generation has incoherent nested outcome")
        else:
            if self.failure_reason is None:
                raise ValueError("failed escape generation requires a typed failure")
            if self.failure_reason is BusEscapeFailureReason.CANDIDATE_FAILURE:
                if self.candidate is None or self.candidate.success:
                    raise ValueError("candidate failure requires a failed nested candidate")
                if self.candidate_failure_reason != self.candidate.failure_reason:
                    raise ValueError("nested candidate failure reason is stale")
            elif self.candidate is not None or self.candidate_failure_reason is not None:
                raise ValueError("pre-candidate failure cannot expose a nested candidate")
        return self

    def semantic_json(self) -> str:
        payload = self.model_dump(mode="json", exclude={"candidate"})
        payload["candidate_fingerprint"] = (
            None if self.candidate is None else self.candidate.semantic_fingerprint()
        )
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


def _input_binding(
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    lane_registry: CertifiedLaneGeometryRegistry,
    escape_registry: CertifiedBusEscapeGraphRegistry,
    terminal_sources: Mapping[str, CertifiedEndpointTerminalSource],
    caller_ledger: OccupancyLedger,
    history: Mapping[RoutingResourceKey, int],
    present_factor_units: int,
    cost_policy: NegotiatedCostPolicy,
    profile: PcbRuleProfile,
    clearance_groups: Sequence[ClearanceGroup],
    hard_forbidden: frozenset[RoutingResourceKey],
    budget: BusEscapeBudget,
    candidate_budget: BusCandidateBudget,
    candidate_policy: BusCandidatePolicy,
    transition_budget: BusTransitionBudget | None,
) -> BusEscapeInputBinding:
    payload = {
        "schema_id": "pcbsmith-generated-bus-escape-inputs",
        "schema_version": 1,
        "static_layout_fingerprint": _canonical_layout_fingerprint(static_layout),
        "netlist_fingerprint": _netlist_fingerprint(netlist),
        "bus_fingerprint": bus.semantic_fingerprint(),
        "certificate_fingerprint": certificate.semantic_fingerprint(),
        "allocation_fingerprint": allocation.allocation_fingerprint,
        "lane_registry_fingerprint": lane_registry.semantic_fingerprint(),
        "escape_registry_fingerprint": escape_registry.semantic_fingerprint(),
        "terminal_sources": sorted(
            (terminal_id, source.semantic_fingerprint())
            for terminal_id, source in terminal_sources.items()
        ),
        "caller_ledger_fingerprint": caller_ledger.semantic_fingerprint(),
        "history": sorted((resource.resource_id, value) for resource, value in history.items()),
        "present_factor_units": present_factor_units,
        "cost_policy": cost_policy.semantic_payload(),
        "profile": profile.model_dump(mode="json"),
        "clearance_groups": _canonical_clearance_groups(clearance_groups),
        "hard_forbidden_resource_ids": sorted(item.resource_id for item in hard_forbidden),
        "budget": budget.model_dump(mode="json"),
        "candidate_budget": candidate_budget.model_dump(mode="json"),
        "candidate_policy": candidate_policy.model_dump(mode="json"),
    }
    if transition_budget is not None:
        payload["transition_budget"] = transition_budget.model_dump(mode="json")
    return BusEscapeInputBinding(
        canonical_payload_json=json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def _terminal_order(bus: BusGroup) -> tuple[str, ...]:
    return tuple(
        terminal.terminal_id
        for member in bus.members
        for terminal in sorted(member.terminals, key=lambda item: item.terminal_id)
    )


@dataclass(frozen=True)
class _FailureContext:
    bus: BusGroup
    allocation: BusLaneAllocationResult
    escape_registry: CertifiedBusEscapeGraphRegistry
    input_binding: BusEscapeInputBinding
    budget: BusEscapeBudget
    candidate_budget: BusCandidateBudget
    terminal_order: tuple[str, ...]
    caller_ledger: OccupancyLedger
    ledger_before: str


def _failed_result(
    *,
    context: _FailureContext,
    reason: BusEscapeFailureReason,
    terminal_telemetry: Sequence[BusEscapeTerminalTelemetry] = (),
    member_telemetry: Sequence[BusEscapeMemberTelemetry] = (),
    pigtails: Sequence[CertifiedBusPigtail] = (),
    prefixes: Mapping[str, CertifiedBusMemberPrefix] | None = None,
    candidate: BusCandidateResult | None = None,
    failed_member_id: str | None = None,
    failed_terminal_id: str | None = None,
) -> BusEscapeGenerationResult:
    return BusEscapeGenerationResult(
        success=False,
        bus_id=context.bus.bus_id,
        bus_fingerprint=context.bus.semantic_fingerprint(),
        allocation_fingerprint=context.allocation.allocation_fingerprint,
        escape_registry_fingerprint=context.escape_registry.semantic_fingerprint(),
        input_binding=context.input_binding,
        input_fingerprint=context.input_binding.semantic_fingerprint(),
        budget=context.budget,
        candidate_budget=context.candidate_budget,
        terminal_order=context.terminal_order,
        terminal_telemetry=tuple(terminal_telemetry),
        member_telemetry=tuple(member_telemetry),
        escape_expansion_count=sum(item.expansion_count for item in terminal_telemetry),
        pigtails=tuple(sorted(pigtails, key=lambda item: (item.member_id, item.terminal_id))),
        prefixes_by_member=tuple(sorted((prefixes or {}).items())),
        candidate=candidate,
        failure_reason=reason,
        candidate_failure_reason=(None if candidate is None else candidate.failure_reason),
        failed_member_id=failed_member_id,
        failed_terminal_id=failed_terminal_id,
        caller_ledger_before_fingerprint=context.ledger_before,
        caller_ledger_after_fingerprint=context.caller_ledger.semantic_fingerprint(),
    )


def _endpoint_graph(region: CertifiedBusEscapeRegion) -> CertifiedEndpointGraph:
    nodes = frozenset((region.layer, point[0], point[1]) for point in region.allowed_track_nodes)
    transitions = frozenset(
        (
            (region.layer, first[0], first[1]),
            (region.layer, second[0], second[1]),
        )
        for first, second in region.allowed_track_transitions
    )
    portal: GridNode = (region.layer, *region.portal_point)
    graph_fingerprint = certified_endpoint_graph_fingerprint(
        grid_mm=region.grid_mm,
        layer=region.layer,
        portal_node=portal,
        allowed_track_nodes=nodes,
        allowed_track_transitions=transitions,
    )
    return CertifiedEndpointGraph(
        grid_mm=region.grid_mm,
        layer=region.layer,
        portal_node=portal,
        allowed_track_nodes=nodes,
        allowed_track_transitions=transitions,
        graph_fingerprint=graph_fingerprint,
    )


def _compressed_points(path: Sequence[GridNode]) -> tuple[tuple[int, int], ...]:
    if len(path) < 2:
        raise ValueError("source-at-portal zero-length escape is unsupported")
    points = [(node[1], node[2]) for node in path]
    compressed = [points[0]]
    previous_direction: tuple[int, int] | None = None
    for index, (start, end) in enumerate(zip(points, points[1:], strict=False)):
        direction = (
            (end[0] > start[0]) - (end[0] < start[0]),
            (end[1] > start[1]) - (end[1] < start[1]),
        )
        if previous_direction is not None and direction != previous_direction:
            compressed.append(start)
        previous_direction = direction
        if index == len(points) - 2:
            compressed.append(end)
    return tuple(compressed)


def _pigtail(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    lane_registry: CertifiedLaneGeometryRegistry,
    region: CertifiedBusEscapeRegion,
    source: CertifiedEndpointTerminalSource,
    connection_fingerprint: str,
    path: Sequence[GridNode],
) -> CertifiedBusPigtail:
    points = _compressed_points(path)
    return CertifiedBusPigtail(
        pigtail_id=(f"generated-pigtail:{region.terminal_id}:{connection_fingerprint}"),
        bus_fingerprint=bus.semantic_fingerprint(),
        certificate_fingerprint=certificate.semantic_fingerprint(),
        allocation_fingerprint=allocation.allocation_fingerprint,
        geometry_registry_fingerprint=lane_registry.semantic_fingerprint(),
        member_id=region.member_id,
        net_name=region.net_name,
        terminal_id=region.terminal_id,
        boundary_id=region.boundary_id,
        assigned_geometry_id=region.assigned_geometry_id,
        portal_kind=region.portal_kind,
        physical_pad_source_id=source.physical_pad_source_id,
        grid_mm=region.grid_mm,
        layer=region.layer,
        pad_anchor_point=points[0],
        portal_point=points[-1],
        points=points,
    )


def _budget_failure(
    per_terminal: int,
    member_remaining: int,
    total_remaining: int,
) -> BusEscapeFailureReason:
    effective = min(per_terminal, member_remaining, total_remaining)
    if total_remaining == effective:
        return BusEscapeFailureReason.TOTAL_EXPANSION_BUDGET
    if member_remaining == effective:
        return BusEscapeFailureReason.PER_MEMBER_EXPANSION_BUDGET
    return BusEscapeFailureReason.PER_TERMINAL_EXPANSION_BUDGET


def _invalid_search_reason(error: ValueError) -> BusEscapeFailureReason:
    message = str(error).lower()
    if any(
        token in message
        for token in ("terminal", "physical pad", "component", "netlist", "source node")
    ):
        return BusEscapeFailureReason.INVALID_SOURCE_BINDING
    return BusEscapeFailureReason.INVALID_GRAPH_BINDING


def generate_certified_bus_escape_candidate(
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    lane_registry: CertifiedLaneGeometryRegistry,
    escape_registry: CertifiedBusEscapeGraphRegistry,
    terminal_sources: Mapping[str, CertifiedEndpointTerminalSource],
    caller_ledger: OccupancyLedger,
    escape_budget: BusEscapeBudget,
    candidate_budget: BusCandidateBudget,
    *,
    candidate_policy: BusCandidatePolicy = DEFAULT_BUS_CANDIDATE_POLICY,
    history: Mapping[RoutingResourceKey, int] | None = None,
    present_factor_units: int = 0,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    clearance_groups: Sequence[ClearanceGroup] = (),
    hard_forbidden_resources: Collection[RoutingResourceKey] = (),
    transition_budget: BusTransitionBudget | None = None,
) -> BusEscapeGenerationResult:
    """Generate certified endpoint escapes, member prefixes, and one pure c2 candidate."""

    fixed_sources = dict(terminal_sources)
    fixed_history = {} if history is None else dict(history)
    hard_forbidden = frozenset(hard_forbidden_resources)
    if any(not isinstance(item, RoutingResourceKey) for item in hard_forbidden):
        raise TypeError("hard-forbidden escape resources must be RoutingResourceKey values")
    ledger_before = caller_ledger.semantic_fingerprint()
    terminal_order = _terminal_order(bus)
    input_binding = _input_binding(
        static_layout,
        netlist,
        bus,
        certificate,
        allocation,
        lane_registry,
        escape_registry,
        fixed_sources,
        caller_ledger,
        fixed_history,
        present_factor_units,
        cost_policy,
        profile,
        clearance_groups,
        hard_forbidden,
        escape_budget,
        candidate_budget,
        candidate_policy,
        transition_budget,
    )
    context = _FailureContext(
        bus=bus,
        allocation=allocation,
        escape_registry=escape_registry,
        input_binding=input_binding,
        budget=escape_budget,
        candidate_budget=candidate_budget,
        terminal_order=terminal_order,
        caller_ledger=caller_ledger,
        ledger_before=ledger_before,
    )

    try:
        if BusGroup.model_validate_json(bus.model_dump_json()) != bus:
            raise ValueError("bus is not canonical")
        if (
            CorridorCapacityCertificate.model_validate_json(certificate.model_dump_json())
            != certificate
        ):
            raise ValueError("certificate is not canonical")
        if BusLaneAllocationResult.model_validate_json(allocation.model_dump_json()) != allocation:
            raise ValueError("allocation is not canonical")
        if (
            CertifiedLaneGeometryRegistry.model_validate_json(lane_registry.model_dump_json())
            != lane_registry
        ):
            raise ValueError("lane registry is not canonical")
        if (
            CertifiedBusEscapeGraphRegistry.model_validate_json(escape_registry.model_dump_json())
            != escape_registry
        ):
            raise ValueError("escape registry is not canonical")
        if bus.rule_profile_id != profile.profile_id:
            raise ValueError("bus rule profile is stale")
    except (TypeError, ValueError):
        return _failed_result(reason=BusEscapeFailureReason.INVALID_AUTHORITY, context=context)

    if allocation.layer_transitions and transition_budget is None:
        return _failed_result(
            reason=BusEscapeFailureReason.TRANSITION_VIAS_UNSUPPORTED,
            context=context,
        )
    try:
        escape_registry.require_authority(bus, certificate, allocation, lane_registry)
    except (TypeError, ValueError):
        return _failed_result(
            reason=BusEscapeFailureReason.INVALID_ESCAPE_AUTHORITY,
            context=context,
        )

    realization: CertifiedBusTrunkRealization | None
    transition_carriers: tuple[CertifiedBusTransitionVia, ...] = ()
    if allocation.layer_transitions:
        assert transition_budget is not None
        transition_member_ids = {event.member_id for event in allocation.layer_transitions}
        transition_result = generate_certified_bus_transition_vias(
            bus,
            certificate,
            allocation,
            lane_registry,
            caller_ledger,
            transition_budget,
            profile=profile,
        )
        if not transition_result.success:
            return _failed_result(
                reason=BusEscapeFailureReason.TRANSITION_CARRIER_GENERATION,
                context=context,
            )
        transition_carriers = transition_result.carriers
        same_layer_member_ids = tuple(
            sorted(
                member.member_id
                for member in bus.members
                if member.member_id not in transition_member_ids
            )
        )
        if same_layer_member_ids:
            try:
                realization = realize_certified_trunk_subset(
                    bus,
                    certificate,
                    allocation,
                    lane_registry,
                    same_layer_member_ids,
                    profile=profile,
                )
            except (TypeError, ValueError):
                return _failed_result(
                    reason=BusEscapeFailureReason.INVALID_ESCAPE_AUTHORITY,
                    context=context,
                )
        else:
            realization = None
    else:
        try:
            realization = realize_certified_trunks(
                bus,
                certificate,
                allocation,
                lane_registry,
                profile=profile,
            )
        except (TypeError, ValueError):
            return _failed_result(
                reason=BusEscapeFailureReason.INVALID_ESCAPE_AUTHORITY,
                context=context,
            )

    expected_terminals = {
        terminal.terminal_id: (member, terminal)
        for member in bus.members
        for terminal in member.terminals
    }
    if set(fixed_sources) != set(expected_terminals) or len(
        {source.physical_pad_source_id for source in fixed_sources.values()}
    ) != len(fixed_sources):
        return _failed_result(
            reason=BusEscapeFailureReason.INVALID_SOURCE_BINDING,
            context=context,
        )
    for terminal_id, source in fixed_sources.items():
        member, terminal = expected_terminals[terminal_id]
        if (
            source.component_ref != terminal.component_ref
            or source.pad_number != terminal.pad_number
            or source.net_name != member.net_name
        ):
            return _failed_result(
                reason=BusEscapeFailureReason.INVALID_SOURCE_BINDING,
                failed_member_id=member.member_id,
                failed_terminal_id=terminal_id,
                context=context,
            )
    if len(bus.members) > escape_budget.max_members:
        return _failed_result(reason=BusEscapeFailureReason.MEMBER_BUDGET, context=context)
    if len(terminal_order) > escape_budget.max_terminals:
        return _failed_result(reason=BusEscapeFailureReason.TERMINAL_BUDGET, context=context)

    regions = {(item.member_id, item.terminal_id): item for item in escape_registry.regions}
    terminal_telemetry: list[BusEscapeTerminalTelemetry] = []
    member_telemetry: list[BusEscapeMemberTelemetry] = []
    pigtails: list[CertifiedBusPigtail] = []
    prefixes: dict[str, CertifiedBusMemberPrefix] = {}
    total_expansions = 0

    for member in bus.members:
        member_expansions = 0
        member_pigtails: list[CertifiedBusPigtail] = []
        source_map: dict[str, str] = {}
        member_terminal_ids = tuple(sorted(terminal.terminal_id for terminal in member.terminals))
        for terminal_id in member_terminal_ids:
            region = regions[(member.member_id, terminal_id)]
            source = fixed_sources[terminal_id]
            portal: GridNode = (region.layer, *region.portal_point)
            if source.source_node == portal:
                terminal_telemetry.append(
                    BusEscapeTerminalTelemetry(
                        member_id=member.member_id,
                        terminal_id=terminal_id,
                        net_name=member.net_name,
                        expansion_count=0,
                        routed=False,
                        failure_reason=BusEscapeFailureReason.SOURCE_AT_PORTAL_UNSUPPORTED,
                    )
                )
                member_telemetry.append(
                    BusEscapeMemberTelemetry(
                        member_id=member.member_id,
                        net_name=member.net_name,
                        terminal_ids=tuple(
                            item.terminal_id
                            for item in terminal_telemetry
                            if item.member_id == member.member_id
                        ),
                        expansion_count=member_expansions,
                        completed=False,
                    )
                )
                return _failed_result(
                    reason=BusEscapeFailureReason.SOURCE_AT_PORTAL_UNSUPPORTED,
                    terminal_telemetry=terminal_telemetry,
                    member_telemetry=member_telemetry,
                    pigtails=pigtails,
                    prefixes=prefixes,
                    failed_member_id=member.member_id,
                    failed_terminal_id=terminal_id,
                    context=context,
                )
            member_remaining = escape_budget.max_expansions_per_member - member_expansions
            total_remaining = escape_budget.max_total_expansions - total_expansions
            effective_limit = min(
                escape_budget.max_expansions_per_terminal,
                member_remaining,
                total_remaining,
            )
            try:
                graph = _endpoint_graph(region)
                connection = route_certified_endpoint_to_portal(
                    static_layout,
                    netlist,
                    source,
                    graph,
                    portal,
                    caller_ledger,
                    fixed_history,
                    present_factor_units,
                    cost_policy,
                    track_width_mm=member.width_mm,
                    profile=profile,
                    clearance_groups=clearance_groups,
                    hard_forbidden_resources=hard_forbidden,
                    max_expansions=effective_limit,
                )
            except RoutingError as error:
                reason = (
                    _budget_failure(
                        escape_budget.max_expansions_per_terminal,
                        member_remaining,
                        total_remaining,
                    )
                    if error.reason is RoutingFailureReason.EXPANSION_BUDGET
                    else BusEscapeFailureReason.ROUTING_ERROR
                )
                terminal_telemetry.append(
                    BusEscapeTerminalTelemetry(
                        member_id=member.member_id,
                        terminal_id=terminal_id,
                        net_name=member.net_name,
                        expansion_count=error.expansion_count,
                        routed=False,
                        routing_failure_reason=error.reason,
                        failure_reason=reason,
                    )
                )
                member_expansions += error.expansion_count
                member_telemetry.append(
                    BusEscapeMemberTelemetry(
                        member_id=member.member_id,
                        net_name=member.net_name,
                        terminal_ids=tuple(
                            item.terminal_id
                            for item in terminal_telemetry
                            if item.member_id == member.member_id
                        ),
                        expansion_count=member_expansions,
                        completed=False,
                    )
                )
                return _failed_result(
                    reason=reason,
                    terminal_telemetry=terminal_telemetry,
                    member_telemetry=member_telemetry,
                    pigtails=pigtails,
                    prefixes=prefixes,
                    failed_member_id=member.member_id,
                    failed_terminal_id=terminal_id,
                    context=context,
                )
            except (TypeError, ValueError) as error:
                reason = _invalid_search_reason(
                    error if isinstance(error, ValueError) else ValueError(str(error))
                )
                terminal_telemetry.append(
                    BusEscapeTerminalTelemetry(
                        member_id=member.member_id,
                        terminal_id=terminal_id,
                        net_name=member.net_name,
                        expansion_count=0,
                        routed=False,
                        failure_reason=reason,
                    )
                )
                member_telemetry.append(
                    BusEscapeMemberTelemetry(
                        member_id=member.member_id,
                        net_name=member.net_name,
                        terminal_ids=tuple(
                            item.terminal_id
                            for item in terminal_telemetry
                            if item.member_id == member.member_id
                        ),
                        expansion_count=member_expansions,
                        completed=False,
                    )
                )
                return _failed_result(
                    reason=reason,
                    terminal_telemetry=terminal_telemetry,
                    member_telemetry=member_telemetry,
                    pigtails=pigtails,
                    prefixes=prefixes,
                    failed_member_id=member.member_id,
                    failed_terminal_id=terminal_id,
                    context=context,
                )

            connection_fingerprint = connection.semantic_fingerprint()
            generated = _pigtail(
                bus,
                certificate,
                allocation,
                lane_registry,
                region,
                source,
                connection_fingerprint,
                connection.path,
            )
            expansions = connection.expansion_count
            total_expansions += expansions
            member_expansions += expansions
            member_pigtails.append(generated)
            pigtails.append(generated)
            source_map[terminal_id] = source.physical_pad_source_id
            terminal_telemetry.append(
                BusEscapeTerminalTelemetry(
                    member_id=member.member_id,
                    terminal_id=terminal_id,
                    net_name=member.net_name,
                    expansion_count=expansions,
                    routed=True,
                    connection_fingerprint=connection_fingerprint,
                    search_input_fingerprint=connection.search_input_fingerprint,
                    pigtail_fingerprint=generated.semantic_fingerprint(),
                )
            )

        member_transition_carriers = tuple(
            item for item in transition_carriers if item.member_id == member.member_id
        )
        member_realization = None if member_transition_carriers else realization
        try:
            prefix = compose_member_route_prefix(
                bus,
                certificate,
                allocation,
                lane_registry,
                member_realization,
                member.member_id,
                member_pigtails,
                member_transition_carriers,
                source_map,
                profile=profile,
            )
            prefix.require_authority(bus, certificate, allocation, lane_registry)
        except (TypeError, ValueError):
            member_telemetry.append(
                BusEscapeMemberTelemetry(
                    member_id=member.member_id,
                    net_name=member.net_name,
                    terminal_ids=member_terminal_ids,
                    expansion_count=member_expansions,
                    completed=False,
                )
            )
            return _failed_result(
                reason=BusEscapeFailureReason.PREFIX_COMPOSITION,
                terminal_telemetry=terminal_telemetry,
                member_telemetry=member_telemetry,
                pigtails=pigtails,
                prefixes=prefixes,
                failed_member_id=member.member_id,
                context=context,
            )
        prefixes[member.member_id] = prefix
        member_telemetry.append(
            BusEscapeMemberTelemetry(
                member_id=member.member_id,
                net_name=member.net_name,
                terminal_ids=member_terminal_ids,
                expansion_count=member_expansions,
                completed=True,
                prefix_fingerprint=prefix.prefix_fingerprint,
            )
        )

    candidate = build_certified_bus_candidate(
        static_layout,
        netlist,
        bus,
        certificate,
        allocation,
        lane_registry,
        prefixes,
        caller_ledger,
        candidate_budget,
        policy=candidate_policy,
        history=fixed_history,
        present_factor_units=present_factor_units,
        cost_policy=cost_policy,
        profile=profile,
        clearance_groups=clearance_groups,
    )
    if not candidate.success:
        return _failed_result(
            reason=BusEscapeFailureReason.CANDIDATE_FAILURE,
            terminal_telemetry=terminal_telemetry,
            member_telemetry=member_telemetry,
            pigtails=pigtails,
            prefixes=prefixes,
            candidate=candidate,
            context=context,
        )
    return BusEscapeGenerationResult(
        success=True,
        bus_id=context.bus.bus_id,
        bus_fingerprint=context.bus.semantic_fingerprint(),
        allocation_fingerprint=context.allocation.allocation_fingerprint,
        escape_registry_fingerprint=context.escape_registry.semantic_fingerprint(),
        input_binding=context.input_binding,
        input_fingerprint=context.input_binding.semantic_fingerprint(),
        budget=escape_budget,
        candidate_budget=context.candidate_budget,
        terminal_order=context.terminal_order,
        terminal_telemetry=tuple(terminal_telemetry),
        member_telemetry=tuple(member_telemetry),
        escape_expansion_count=total_expansions,
        pigtails=tuple(sorted(pigtails, key=lambda item: (item.member_id, item.terminal_id))),
        prefixes_by_member=tuple(sorted(prefixes.items())),
        candidate=candidate,
        caller_ledger_before_fingerprint=context.ledger_before,
        caller_ledger_after_fingerprint=context.caller_ledger.semantic_fingerprint(),
    )
