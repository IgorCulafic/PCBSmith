"""Replay-bound authority for certified bus escape and prefix generation.

This opt-in envelope retains every typed input consumed by the existing pure
escape generator and proves its retained result by deterministic replay on a
fresh occupancy ledger.  It does not alter the generator or make any stronger
physical-routing claim than that generator already makes.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any, Literal, Self

from pydantic import Field, field_serializer, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_geometry import (
    CertifiedBusEscapeGraphRegistry,
    CertifiedLaneGeometryRegistry,
)
from pcbsmith.bus_ir import BusGroup, CorridorCapacityCertificate
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.bus_candidate import (
    DEFAULT_BUS_CANDIDATE_POLICY,
    BusCandidateBudget,
    BusCandidatePolicy,
)
from pcbsmith.kicad.bus_escape import (
    BusEscapeBudget,
    BusEscapeGenerationResult,
    ClearanceGroup,
    generate_certified_bus_escape_candidate,
)
from pcbsmith.kicad.bus_transition import BusTransitionBudget
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_grid import CertifiedEndpointTerminalSource
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
)
from pcbsmith.routing_ir import RoutingIrModel
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


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


class BusEscapeTerminalSourceEntry(RoutingIrModel):
    """One terminal mapping entry; tuple order is not routing order."""

    terminal_id: str = Field(min_length=1)
    source: CertifiedEndpointTerminalSource


class BusEscapeHistoryEntry(RoutingIrModel):
    """One set-like resource history-cost entry."""

    resource: RoutingResourceKey
    value: int = Field(ge=0)


class BusEscapeClearanceGroup(RoutingIrModel):
    """Canonical form of one unordered pairwise clearance group."""

    nets_a: tuple[str, ...]
    nets_b: tuple[str, ...]
    gap_mm: float = Field(gt=0)
    exempt_component_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def identities_are_canonical(self) -> Self:
        first = tuple(sorted(set(self.nets_a)))
        second = tuple(sorted(set(self.nets_b)))
        if not first or not second:
            raise ValueError("escape clearance groups require two non-empty net sets")
        exemptions = tuple(sorted(set(self.exempt_component_refs)))
        if any(
            not item or item != item.strip()
            for item in (*first, *second, *exemptions)
        ):
            raise ValueError("escape clearance identities must be non-empty and stripped")
        low, high = sorted((first, second))
        object.__setattr__(self, "nets_a", low)
        object.__setattr__(self, "nets_b", high)
        object.__setattr__(self, "exempt_component_refs", exemptions)
        return self

    def as_generator_input(self) -> ClearanceGroup:
        return self.nets_a, self.nets_b, self.gap_mm, self.exempt_component_refs


class BusEscapeReplayInput(RoutingIrModel):
    """Complete immutable authority required to replay one escape run."""

    schema_id: Literal["pcbsmith-bus-escape-replay-input"] = (
        "pcbsmith-bus-escape-replay-input"
    )
    schema_version: Literal[1] = 1
    static_layout_snapshot_json: str = Field(min_length=2)
    netlist_snapshot_json: str = Field(min_length=2)
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    lane_registry: CertifiedLaneGeometryRegistry
    escape_registry: CertifiedBusEscapeGraphRegistry
    terminal_sources: tuple[BusEscapeTerminalSourceEntry, ...]
    initial_claims: tuple[NetResourceClaims, ...] = ()
    escape_budget: BusEscapeBudget
    candidate_budget: BusCandidateBudget
    candidate_policy: BusCandidatePolicy
    history: tuple[BusEscapeHistoryEntry, ...] = ()
    present_factor_units: int = Field(ge=0)
    cost_policy: NegotiatedCostPolicy
    profile: PcbRuleProfile
    clearance_groups: tuple[BusEscapeClearanceGroup, ...] = ()
    hard_forbidden_resources: tuple[RoutingResourceKey, ...] = ()
    transition_budget: BusTransitionBudget | None = None

    @model_validator(mode="after")
    def authority_is_complete_and_canonical(self) -> Self:
        parse_canonical_board_layout_snapshot(self.static_layout_snapshot_json)
        parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)

        source_ids = tuple(item.terminal_id for item in self.terminal_sources)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("terminal source authority contains duplicate terminal IDs")
        object.__setattr__(
            self,
            "terminal_sources",
            tuple(sorted(self.terminal_sources, key=lambda item: item.terminal_id)),
        )

        claim_names = tuple(item.net_name for item in self.initial_claims)
        if len(set(claim_names)) != len(claim_names):
            raise ValueError("initial occupancy contains duplicate net claim identities")
        object.__setattr__(
            self,
            "initial_claims",
            tuple(sorted(self.initial_claims, key=lambda item: item.net_name)),
        )

        history_resources = tuple(item.resource for item in self.history)
        if len(set(history_resources)) != len(history_resources):
            raise ValueError("escape history contains duplicate resource identities")
        object.__setattr__(
            self,
            "history",
            tuple(sorted(self.history, key=lambda item: item.resource)),
        )

        object.__setattr__(
            self,
            "clearance_groups",
            tuple(sorted(set(self.clearance_groups), key=lambda item: item.semantic_json())),
        )
        object.__setattr__(
            self,
            "hard_forbidden_resources",
            tuple(sorted(set(self.hard_forbidden_resources))),
        )
        return self

    @field_serializer("initial_claims")
    def serialize_initial_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        return [
            {
                "net_name": claim.net_name,
                "resources": [
                    _resource_payload(resource) for resource in sorted(claim.resources)
                ],
            }
            for claim in claims
        ]

    @field_serializer("hard_forbidden_resources")
    def serialize_forbidden_resources(
        self, resources: tuple[RoutingResourceKey, ...]
    ) -> list[dict[str, Any]]:
        return [_resource_payload(resource) for resource in resources]

    @property
    def static_layout(self) -> BoardLayout:
        return parse_canonical_board_layout_snapshot(self.static_layout_snapshot_json)

    @property
    def netlist(self) -> BoardNetlist:
        return parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)

    def terminal_source_mapping(self) -> dict[str, CertifiedEndpointTerminalSource]:
        return {item.terminal_id: item.source for item in self.terminal_sources}

    def initial_ledger(self) -> OccupancyLedger:
        return OccupancyLedger(self.initial_claims)

    def history_mapping(self) -> dict[RoutingResourceKey, int]:
        return {item.resource: item.value for item in self.history}

    def generator_clearance_groups(self) -> tuple[ClearanceGroup, ...]:
        return tuple(item.as_generator_input() for item in self.clearance_groups)


class BusEscapeReplayResult(RoutingIrModel):
    """An existing escape result proven by exact deterministic replay."""

    schema_id: Literal["pcbsmith-bus-escape-replay-result"] = (
        "pcbsmith-bus-escape-replay-result"
    )
    schema_version: Literal[1] = 1
    replay_input: BusEscapeReplayInput
    generation_result: BusEscapeGenerationResult

    @model_validator(mode="after")
    def generation_is_exactly_replayable(self) -> Self:
        replay_input = BusEscapeReplayInput.model_validate_json(
            self.replay_input.model_dump_json()
        )
        if replay_input != self.replay_input:
            raise ValueError("escape replay input failed exact JSON reconstruction")

        ledger = replay_input.initial_ledger()
        claims_before = ledger.committed_claims()
        fingerprint_before = ledger.semantic_fingerprint()
        replayed = generate_certified_bus_escape_candidate(
            replay_input.static_layout,
            replay_input.netlist,
            replay_input.bus,
            replay_input.certificate,
            replay_input.allocation,
            replay_input.lane_registry,
            replay_input.escape_registry,
            replay_input.terminal_source_mapping(),
            ledger,
            replay_input.escape_budget,
            replay_input.candidate_budget,
            candidate_policy=replay_input.candidate_policy,
            history=replay_input.history_mapping(),
            present_factor_units=replay_input.present_factor_units,
            cost_policy=replay_input.cost_policy,
            profile=replay_input.profile,
            clearance_groups=replay_input.generator_clearance_groups(),
            hard_forbidden_resources=replay_input.hard_forbidden_resources,
            transition_budget=replay_input.transition_budget,
        )
        retained = BusEscapeGenerationResult.model_validate_json(
            self.generation_result.model_dump_json()
        )
        if retained != self.generation_result or replayed != retained:
            raise ValueError("retained escape result does not equal exact replay")
        if (
            ledger.committed_claims() != claims_before
            or ledger.semantic_fingerprint() != fingerprint_before
        ):
            raise ValueError("escape replay mutated its occupancy ledger")
        if (
            retained.caller_ledger_before_fingerprint != fingerprint_before
            or retained.caller_ledger_after_fingerprint != fingerprint_before
        ):
            raise ValueError("escape result is not bound to the retained occupancy snapshot")
        return self


def generate_replay_bound_bus_escape_candidate(
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
) -> BusEscapeReplayResult:
    """Snapshot all caller authority and generate on detached immutable state."""

    layout_before = canonical_board_layout_snapshot_json(static_layout)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)
    claims_before = caller_ledger.committed_claims()
    ledger_fingerprint_before = caller_ledger.semantic_fingerprint()
    fixed_history = {} if history is None else dict(history)
    replay_input = BusEscapeReplayInput(
        static_layout_snapshot_json=layout_before,
        netlist_snapshot_json=netlist_before,
        bus=bus,
        certificate=certificate,
        allocation=allocation,
        lane_registry=lane_registry,
        escape_registry=escape_registry,
        terminal_sources=tuple(
            BusEscapeTerminalSourceEntry(terminal_id=key, source=value)
            for key, value in terminal_sources.items()
        ),
        initial_claims=claims_before,
        escape_budget=escape_budget,
        candidate_budget=candidate_budget,
        candidate_policy=candidate_policy,
        history=tuple(
            BusEscapeHistoryEntry(resource=key, value=value)
            for key, value in fixed_history.items()
        ),
        present_factor_units=present_factor_units,
        cost_policy=cost_policy,
        profile=profile,
        clearance_groups=tuple(
            BusEscapeClearanceGroup(
                nets_a=tuple(group[0]),
                nets_b=tuple(group[1]),
                gap_mm=group[2],
                exempt_component_refs=tuple(group[3]),
            )
            for group in clearance_groups
        ),
        hard_forbidden_resources=tuple(hard_forbidden_resources),
        transition_budget=transition_budget,
    )
    isolated_ledger = replay_input.initial_ledger()
    generation_result = generate_certified_bus_escape_candidate(
        replay_input.static_layout,
        replay_input.netlist,
        replay_input.bus,
        replay_input.certificate,
        replay_input.allocation,
        replay_input.lane_registry,
        replay_input.escape_registry,
        replay_input.terminal_source_mapping(),
        isolated_ledger,
        replay_input.escape_budget,
        replay_input.candidate_budget,
        candidate_policy=replay_input.candidate_policy,
        history=replay_input.history_mapping(),
        present_factor_units=replay_input.present_factor_units,
        cost_policy=replay_input.cost_policy,
        profile=replay_input.profile,
        clearance_groups=replay_input.generator_clearance_groups(),
        hard_forbidden_resources=replay_input.hard_forbidden_resources,
        transition_budget=replay_input.transition_budget,
    )
    if (
        canonical_board_layout_snapshot_json(static_layout) != layout_before
        or canonical_board_netlist_snapshot_json(netlist) != netlist_before
        or caller_ledger.committed_claims() != claims_before
        or caller_ledger.semantic_fingerprint() != ledger_fingerprint_before
    ):
        raise RuntimeError("escape replay builder mutated caller authority")
    return BusEscapeReplayResult(
        replay_input=replay_input,
        generation_result=generation_result,
    )
