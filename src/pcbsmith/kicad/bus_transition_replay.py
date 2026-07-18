"""Replay-bound authority for generated certified bus transition carriers.

This is an opt-in envelope around the existing pure transition generator.  It
does not change that generator and deliberately preserves its fail-closed
handling of semantic swap events.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import field_serializer, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_geometry import CertifiedLaneGeometryRegistry
from pcbsmith.bus_ir import BusGroup, CorridorCapacityCertificate
from pcbsmith.kicad.bus_transition import (
    BusTransitionBudget,
    BusTransitionGenerationResult,
    generate_certified_bus_transition_vias,
)
from pcbsmith.kicad.negotiated_resources import NetResourceClaims, OccupancyLedger
from pcbsmith.routing_ir import RoutingIrModel
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


class BusTransitionReplayInput(RoutingIrModel):
    """Complete, immutable preparation authority for one transition run."""

    schema_id: Literal["pcbsmith-bus-transition-replay-input"] = (
        "pcbsmith-bus-transition-replay-input"
    )
    schema_version: Literal[1] = 1
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    geometry_registry: CertifiedLaneGeometryRegistry
    profile: PcbRuleProfile
    budget: BusTransitionBudget
    initial_claims: tuple[NetResourceClaims, ...] = ()

    @model_validator(mode="after")
    def claims_are_canonical_and_unique(self) -> Self:
        names = tuple(claim.net_name for claim in self.initial_claims)
        if len(set(names)) != len(names):
            raise ValueError("initial occupancy contains duplicate net claim identities")
        canonical = tuple(sorted(self.initial_claims, key=lambda claim: claim.net_name))
        object.__setattr__(self, "initial_claims", canonical)
        return self

    @field_serializer("initial_claims")
    def serialize_initial_claims(
        self, claims: tuple[NetResourceClaims, ...]
    ) -> list[dict[str, Any]]:
        """Serialize both set-like levels in a stable canonical order."""

        return [
            {
                "net_name": claim.net_name,
                "resources": [
                    {
                        "domain_id": resource.domain_id,
                        "layer": resource.layer,
                        "kind": resource.kind,
                        "ix0": resource.ix0,
                        "iy0": resource.iy0,
                        "ix1": resource.ix1,
                        "iy1": resource.iy1,
                    }
                    for resource in sorted(claim.resources)
                ],
            }
            for claim in claims
        ]


class BusTransitionReplayResult(RoutingIrModel):
    """An exact existing transition result proven by deterministic replay."""

    schema_id: Literal["pcbsmith-bus-transition-replay-result"] = (
        "pcbsmith-bus-transition-replay-result"
    )
    schema_version: Literal[1] = 1
    replay_input: BusTransitionReplayInput
    generation_result: BusTransitionGenerationResult

    @model_validator(mode="after")
    def generation_is_exactly_replayable(self) -> Self:
        replay_input = BusTransitionReplayInput.model_validate_json(
            self.replay_input.model_dump_json()
        )
        if replay_input != self.replay_input:
            raise ValueError("transition replay input failed exact JSON reconstruction")

        ledger = OccupancyLedger(replay_input.initial_claims)
        claims_before = ledger.committed_claims()
        fingerprint_before = ledger.semantic_fingerprint()
        replayed = generate_certified_bus_transition_vias(
            replay_input.bus,
            replay_input.certificate,
            replay_input.allocation,
            replay_input.geometry_registry,
            ledger,
            replay_input.budget,
            profile=replay_input.profile,
        )
        retained = BusTransitionGenerationResult.model_validate_json(
            self.generation_result.model_dump_json()
        )
        if retained != self.generation_result or replayed != retained:
            raise ValueError("retained transition result does not equal exact replay")
        if (
            ledger.committed_claims() != claims_before
            or ledger.semantic_fingerprint() != fingerprint_before
        ):
            raise ValueError("transition replay mutated its occupancy ledger")
        if (
            retained.caller_ledger_before_fingerprint != fingerprint_before
            or retained.caller_ledger_after_fingerprint != fingerprint_before
        ):
            raise ValueError("transition result is not bound to the retained occupancy snapshot")
        return self


def generate_replay_bound_bus_transition_vias(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
    geometry_registry: CertifiedLaneGeometryRegistry,
    caller_ledger: OccupancyLedger,
    budget: BusTransitionBudget,
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> BusTransitionReplayResult:
    """Snapshot caller state and generate on a fresh, isolated ledger."""

    caller_claims_before = caller_ledger.committed_claims()
    caller_fingerprint_before = caller_ledger.semantic_fingerprint()
    replay_input = BusTransitionReplayInput(
        bus=bus,
        certificate=certificate,
        allocation=allocation,
        geometry_registry=geometry_registry,
        profile=profile,
        budget=budget,
        initial_claims=caller_claims_before,
    )
    isolated_ledger = OccupancyLedger(replay_input.initial_claims)
    generation_result = generate_certified_bus_transition_vias(
        replay_input.bus,
        replay_input.certificate,
        replay_input.allocation,
        replay_input.geometry_registry,
        isolated_ledger,
        replay_input.budget,
        profile=replay_input.profile,
    )
    if (
        caller_ledger.committed_claims() != caller_claims_before
        or caller_ledger.semantic_fingerprint() != caller_fingerprint_before
    ):
        raise RuntimeError("transition replay builder mutated caller occupancy")
    return BusTransitionReplayResult(
        replay_input=replay_input,
        generation_result=generation_result,
    )
