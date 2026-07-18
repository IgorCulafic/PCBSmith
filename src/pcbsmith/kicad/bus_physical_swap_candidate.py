"""Replay-bound negotiated candidate construction for physical-swap prefixes.

This schema-v1 adapter derives every routing authority from one accepted
physical-swap prefix composition and delegates only the negotiated candidate
search to the ordinary bus-candidate kernel.  It does not counterfeit ordinary
``CertifiedBusMemberPrefix`` authority, commit a transaction, materialize a
board, or claim exact acceptance.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.kicad.bus_candidate import (
    DEFAULT_BUS_CANDIDATE_POLICY,
    BusCandidateBudget,
    BusCandidatePolicy,
    BusCandidateResult,
    ClearanceGroup,
    _build_bus_candidate_from_prefixes,
)
from pcbsmith.kicad.bus_physical_swap_composition import (
    CertifiedPhysicalSwapBusMemberPrefix,
    ReplayBoundPhysicalSwapBusPrefixComposition,
)
from pcbsmith.kicad.bus_transaction import negotiated_grid_route_fingerprint
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_resources import OccupancyLedger, RoutingResourceKey
from pcbsmith.routing_ir import RoutingIrModel


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


class BusPhysicalSwapCandidateHistoryEntry(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-candidate-history-entry"] = (
        "pcbsmith-bus-physical-swap-candidate-history-entry"
    )
    schema_version: Literal[1] = 1
    resource: RoutingResourceKey
    value: int = Field(ge=0)


class BusPhysicalSwapCandidateClearanceGroup(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-candidate-clearance-group"] = (
        "pcbsmith-bus-physical-swap-candidate-clearance-group"
    )
    schema_version: Literal[1] = 1
    nets_a: tuple[str, ...]
    nets_b: tuple[str, ...]
    minimum_clearance_mm: float = Field(gt=0)
    exempt_component_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def group_is_canonical(self) -> Self:
        if not math.isfinite(self.minimum_clearance_mm):
            raise ValueError("candidate clearance must be finite and positive")
        first = tuple(sorted(set(self.nets_a)))
        second = tuple(sorted(set(self.nets_b)))
        exemptions = tuple(sorted(set(self.exempt_component_refs)))
        if not first or not second:
            raise ValueError("candidate clearance groups require two non-empty net sets")
        if any(not item or item != item.strip() for item in (*first, *second, *exemptions)):
            raise ValueError("candidate clearance identities must be canonical")
        low, high = sorted((first, second))
        object.__setattr__(self, "nets_a", low)
        object.__setattr__(self, "nets_b", high)
        object.__setattr__(self, "exempt_component_refs", exemptions)
        return self

    def as_candidate_input(self) -> ClearanceGroup:
        return (
            self.nets_a,
            self.nets_b,
            self.minimum_clearance_mm,
            self.exempt_component_refs,
        )


class BusPhysicalSwapCandidateReplayInput(RoutingIrModel):
    """Complete immutable policy and authority for one candidate replay."""

    schema_id: Literal["pcbsmith-bus-physical-swap-candidate-replay-input"] = (
        "pcbsmith-bus-physical-swap-candidate-replay-input"
    )
    schema_version: Literal[1] = 1
    composition: ReplayBoundPhysicalSwapBusPrefixComposition
    budget: BusCandidateBudget
    policy: BusCandidatePolicy = DEFAULT_BUS_CANDIDATE_POLICY
    history: tuple[BusPhysicalSwapCandidateHistoryEntry, ...] = ()
    present_factor_units: int = Field(default=0, ge=0)
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY
    clearance_groups: tuple[BusPhysicalSwapCandidateClearanceGroup, ...] = ()

    @field_validator("composition", mode="before")
    @classmethod
    def composition_is_json_revalidated(
        cls, value: Any
    ) -> ReplayBoundPhysicalSwapBusPrefixComposition | Any:
        if isinstance(value, ReplayBoundPhysicalSwapBusPrefixComposition):
            return ReplayBoundPhysicalSwapBusPrefixComposition.model_validate_json(
                value.model_dump_json()
            )
        return value

    @model_validator(mode="after")
    def replay_authority_is_canonical(self) -> Self:
        history = tuple(sorted(self.history, key=lambda item: item.resource))
        if len({item.resource for item in history}) != len(history):
            raise ValueError("candidate history contains duplicate resource identities")
        if len(set(self.clearance_groups)) != len(self.clearance_groups):
            raise ValueError("candidate clearance groups contain duplicate declarations")
        groups = tuple(sorted(self.clearance_groups, key=lambda item: item.semantic_json()))
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "clearance_groups", groups)
        return self

    def history_mapping(self) -> dict[RoutingResourceKey, int]:
        return {item.resource: item.value for item in self.history}

    def candidate_clearance_groups(self) -> tuple[ClearanceGroup, ...]:
        return tuple(item.as_candidate_input() for item in self.clearance_groups)


class BusPhysicalSwapCandidateMemberBinding(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-candidate-member-binding"] = (
        "pcbsmith-bus-physical-swap-candidate-member-binding"
    )
    schema_version: Literal[1] = 1
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    member_composition_fingerprint: str
    prefix_alternative_id: str = Field(min_length=1)
    prefix_fingerprint: str
    route_fingerprint: str

    @field_validator(
        "member_composition_fingerprint",
        "prefix_fingerprint",
        "route_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)


class ReplayBoundPhysicalSwapBusCandidate(RoutingIrModel):
    """Candidate result that exactly replays from one physical composition."""

    schema_id: Literal["pcbsmith-replay-bound-physical-swap-bus-candidate"] = (
        "pcbsmith-replay-bound-physical-swap-bus-candidate"
    )
    schema_version: Literal[1] = 1
    replay_input: BusPhysicalSwapCandidateReplayInput
    candidate_result: BusCandidateResult
    composition_fingerprint: str
    candidate_input_fingerprint: str
    candidate_result_fingerprint: str
    bundle_fingerprint: str | None = None
    member_bindings: tuple[BusPhysicalSwapCandidateMemberBinding, ...] = ()
    result_fingerprint: str

    @field_validator("replay_input", mode="before")
    @classmethod
    def replay_input_is_json_revalidated(
        cls, value: Any
    ) -> BusPhysicalSwapCandidateReplayInput | Any:
        if isinstance(value, BusPhysicalSwapCandidateReplayInput):
            return BusPhysicalSwapCandidateReplayInput.model_validate_json(value.model_dump_json())
        return value

    @field_validator(
        "composition_fingerprint",
        "candidate_input_fingerprint",
        "candidate_result_fingerprint",
        "bundle_fingerprint",
        "result_fingerprint",
    )
    @classmethod
    def wrapper_fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def candidate_replays_and_binds_exactly(self) -> Self:
        replay_input = self.replay_input
        replayed = _derive_candidate(replay_input)
        composition_fp = replay_input.composition.semantic_fingerprint()
        input_fp = replay_input.semantic_fingerprint()
        result_fp = replayed.semantic_fingerprint()
        if (
            replayed != self.candidate_result
            or self.composition_fingerprint != composition_fp
            or self.candidate_input_fingerprint != input_fp
            or self.candidate_result_fingerprint != result_fp
        ):
            raise ValueError("physical-swap candidate authority does not replay exactly")
        bundle_fp, bindings = _success_bindings(replay_input, replayed)
        if self.bundle_fingerprint != bundle_fp or self.member_bindings != bindings:
            raise ValueError("physical-swap candidate bundle or prefix binding is stale")
        expected = _result_fingerprint(
            replay_input,
            replayed,
            composition_fp,
            input_fp,
            result_fp,
            bundle_fp,
            bindings,
        )
        if self.result_fingerprint != expected:
            raise ValueError("physical-swap candidate result fingerprint is stale")
        return self


def build_replay_bound_physical_swap_bus_candidate(
    *,
    composition: ReplayBoundPhysicalSwapBusPrefixComposition,
    caller_ledger: OccupancyLedger,
    budget: BusCandidateBudget,
    policy: BusCandidatePolicy = DEFAULT_BUS_CANDIDATE_POLICY,
    history: Mapping[RoutingResourceKey, int] | None = None,
    present_factor_units: int = 0,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    clearance_groups: tuple[BusPhysicalSwapCandidateClearanceGroup, ...] = (),
) -> ReplayBoundPhysicalSwapBusCandidate:
    """Build one pure negotiated candidate from physical-prefix authority."""

    authority = composition.replay_input.plan.replay_input
    expected_claims = authority.initial_claims
    expected_fingerprint = authority.initial_occupancy_fingerprint
    before_claims = caller_ledger.committed_claims()
    before_fingerprint = caller_ledger.semantic_fingerprint()
    if before_claims != expected_claims or before_fingerprint != expected_fingerprint:
        raise ValueError("caller ledger must exactly equal the physical plan initial occupancy")
    replay_input = BusPhysicalSwapCandidateReplayInput(
        composition=composition,
        budget=budget,
        policy=policy,
        history=tuple(
            BusPhysicalSwapCandidateHistoryEntry(resource=resource, value=value)
            for resource, value in (history or {}).items()
        ),
        present_factor_units=present_factor_units,
        cost_policy=cost_policy,
        clearance_groups=clearance_groups,
    )
    candidate = _derive_candidate(replay_input)
    if (
        caller_ledger.committed_claims() != before_claims
        or caller_ledger.semantic_fingerprint() != before_fingerprint
    ):
        raise RuntimeError("physical-swap candidate construction mutated caller occupancy")
    return _envelope(replay_input, candidate)


def _derive_candidate(
    replay_input: BusPhysicalSwapCandidateReplayInput,
) -> BusCandidateResult:
    authority = replay_input.composition.replay_input.plan.replay_input
    prefixes = {item.member_id: item.prefix for item in replay_input.composition.members}
    fingerprints = {
        item.member_id: item.prefix_fingerprint for item in replay_input.composition.members
    }
    member_ids = tuple(item.member_id for item in authority.bus.members)
    if tuple(prefixes) != member_ids or tuple(fingerprints) != member_ids:
        raise ValueError("physical prefix coverage or member order is stale")
    ledger = OccupancyLedger(authority.initial_claims)
    if ledger.semantic_fingerprint() != authority.initial_occupancy_fingerprint:
        raise ValueError("physical candidate initial occupancy authority is stale")
    return _build_bus_candidate_from_prefixes(
        static_layout=authority.layout,
        netlist=authority.netlist,
        bus=authority.bus,
        allocation=authority.allocation,
        prefixes_by_member=prefixes,
        prefix_fingerprints_by_member=fingerprints,
        caller_ledger=ledger,
        budget=replay_input.budget,
        policy=replay_input.policy,
        history=replay_input.history_mapping(),
        present_factor_units=replay_input.present_factor_units,
        cost_policy=replay_input.cost_policy,
        profile=authority.rule_profile,
        clearance_groups=replay_input.candidate_clearance_groups(),
    )


def _success_bindings(
    replay_input: BusPhysicalSwapCandidateReplayInput,
    candidate: BusCandidateResult,
) -> tuple[str | None, tuple[BusPhysicalSwapCandidateMemberBinding, ...]]:
    if not candidate.success:
        return None, ()
    bundle = candidate.bundle
    if bundle is None:
        raise ValueError("successful physical-swap candidate lacks a bundle")
    authority = replay_input.composition.replay_input.plan.replay_input
    prefixes = {item.member_id: item for item in replay_input.composition.members}
    routes = bundle.by_net()
    if set(routes) != {item.net_name for item in authority.bus.members}:
        raise ValueError("successful physical-swap bundle does not exactly cover bus nets")
    bindings: list[BusPhysicalSwapCandidateMemberBinding] = []
    for member in authority.bus.members:
        prefix = prefixes[member.member_id]
        route = routes.get(member.net_name)
        if route is None:
            raise ValueError("successful physical-swap bundle is missing a member route")
        if (
            route.prefix_alternative_id != prefix.prefix.alternative_id
            or route.prefix_fingerprint != prefix.prefix_fingerprint
        ):
            raise ValueError("member route does not bind its physical prefix identity")
        _require_prefix_copper(prefix, route.result.segments, route.result.vias)
        bindings.append(
            BusPhysicalSwapCandidateMemberBinding(
                member_id=member.member_id,
                net_name=member.net_name,
                member_composition_fingerprint=prefix.composition_fingerprint,
                prefix_alternative_id=prefix.prefix.alternative_id,
                prefix_fingerprint=prefix.prefix_fingerprint,
                route_fingerprint=negotiated_grid_route_fingerprint(route),
            )
        )
    return bundle.semantic_fingerprint(), tuple(bindings)


def _require_prefix_copper(
    prefix: CertifiedPhysicalSwapBusMemberPrefix,
    route_segments: tuple[Any, ...],
    route_vias: tuple[Any, ...],
) -> None:
    prefix_segments = {_segment_key(item) for item in prefix.prefix.segments}
    candidate_segments = {_segment_key(item) for item in route_segments}
    prefix_vias = {_via_key(item) for item in prefix.prefix.vias}
    candidate_vias = {_via_key(item) for item in route_vias}
    if not prefix_segments.issubset(candidate_segments) or not prefix_vias.issubset(candidate_vias):
        raise ValueError("candidate route omits or replaces certified physical-prefix copper")


def _segment_key(item: Any) -> tuple[Any, ...]:
    return (
        item.x1,
        item.y1,
        item.x2,
        item.y2,
        item.layer,
        item.net_name,
        item.width_mm,
    )


def _via_key(item: Any) -> tuple[Any, ...]:
    return (
        item.x,
        item.y,
        item.net_name,
        item.size_mm,
        item.drill_mm,
        item.front_mask.value,
        item.back_mask.value,
    )


def _envelope(
    replay_input: BusPhysicalSwapCandidateReplayInput,
    candidate: BusCandidateResult,
) -> ReplayBoundPhysicalSwapBusCandidate:
    composition_fp = replay_input.composition.semantic_fingerprint()
    input_fp = replay_input.semantic_fingerprint()
    candidate_fp = candidate.semantic_fingerprint()
    bundle_fp, bindings = _success_bindings(replay_input, candidate)
    return ReplayBoundPhysicalSwapBusCandidate.model_construct(
        replay_input=replay_input,
        candidate_result=candidate,
        composition_fingerprint=composition_fp,
        candidate_input_fingerprint=input_fp,
        candidate_result_fingerprint=candidate_fp,
        bundle_fingerprint=bundle_fp,
        member_bindings=bindings,
        result_fingerprint=_result_fingerprint(
            replay_input,
            candidate,
            composition_fp,
            input_fp,
            candidate_fp,
            bundle_fp,
            bindings,
        ),
    )


def _result_fingerprint(
    replay_input: BusPhysicalSwapCandidateReplayInput,
    candidate: BusCandidateResult,
    composition_fingerprint: str,
    input_fingerprint: str,
    candidate_fingerprint: str,
    bundle_fingerprint: str | None,
    bindings: tuple[BusPhysicalSwapCandidateMemberBinding, ...],
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-physical-swap-bus-candidate-result",
            "schema_version": 1,
            "composition_fingerprint": composition_fingerprint,
            "input_fingerprint": input_fingerprint,
            "candidate_fingerprint": candidate_fingerprint,
            "candidate_success": candidate.success,
            "bundle_fingerprint": bundle_fingerprint,
            "member_bindings": [item.model_dump(mode="json") for item in bindings],
            "replay_input_fingerprint": replay_input.semantic_fingerprint(),
        }
    )
