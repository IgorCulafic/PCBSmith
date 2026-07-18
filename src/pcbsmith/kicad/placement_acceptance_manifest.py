"""Replay-bound composition of placement and aggregate acceptance authority.

This manifest proves that existing authority records describe one accepted
synthetic board.  It does not claim thermometer readiness, live-tool execution,
or semantic equivalence between the retained CircuitObject and BoardNetlist.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from pcbsmith.corridor_guidance import CorridorGuidanceDisposition
from pcbsmith.kicad.aggregate_exact_checker import (
    KICAD_SAVE_ROUNDTRIP_ADAPTER_ID,
    READER_NETLIST_EQUALITY_ADAPTER_ID,
    THERMOMETER_NGSPICE_ADAPTER_ID,
    AggregateCheckStatus,
    AggregateSubcheckApplicability,
    AggregateSubcheckKind,
    KiCadSaveRoundtripSubcheckEvidence,
    MissingSubcheckEvidence,
    ReaderNetlistEqualitySubcheckEvidence,
    StableAggregateExactCheckEvidence,
    ThermometerNgspiceSubcheckEvidence,
)
from pcbsmith.kicad.board_serialization import (
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.placement_exact import (
    placement_exact_netlist_fingerprint,
    placement_route_geometry_fingerprint,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.placement_exact_ir import (
    PlacementExactCandidateRecord,
    PlacementExactDisposition,
    PlacementExactRunResult,
    PlacementFinalState,
    exact_checker_report_fingerprint,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


class PlacementAcceptanceProducerRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subcheck_id: str
    subcheck_version: str
    producer_id: str

    @model_validator(mode="after")
    def identities_are_canonical(self) -> Self:
        for field_name in ("subcheck_id", "subcheck_version", "producer_id"):
            _require_identity(getattr(self, field_name), field_name)
        return self


REQUIRED_ACCEPTANCE_PRODUCERS = (
    PlacementAcceptanceProducerRequirement(
        subcheck_id="kicad-roundtrip",
        subcheck_version="1",
        producer_id=KICAD_SAVE_ROUNDTRIP_ADAPTER_ID,
    ),
    PlacementAcceptanceProducerRequirement(
        subcheck_id="reader-equality",
        subcheck_version="1",
        producer_id=READER_NETLIST_EQUALITY_ADAPTER_ID,
    ),
    PlacementAcceptanceProducerRequirement(
        subcheck_id="thermometer-simulation",
        subcheck_version="1",
        producer_id=THERMOMETER_NGSPICE_ADAPTER_ID,
    ),
)

ROUTING_ONLY_ACCEPTANCE_PRODUCERS = REQUIRED_ACCEPTANCE_PRODUCERS[:2]
_V1_POLICY_ID = "r5-placement-acceptance-composition-v1"
_V2_ROUTING_ONLY_POLICY_ID = "r5-routing-only-placement-acceptance-composition-v2"
_NOT_APPLICABLE_REASON = "policy explicitly declares this external subcheck not applicable"


class PlacementAcceptanceManifestPolicy(BaseModel):
    """Fixed v1 thermometer or v2 routing-only producer contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-placement-acceptance-manifest-policy"] = (
        "pcbsmith-placement-acceptance-manifest-policy"
    )
    schema_version: Literal[1] = 1
    policy_id: str = _V1_POLICY_ID
    policy_version: str = "1"
    required_producers: tuple[PlacementAcceptanceProducerRequirement, ...] = (
        REQUIRED_ACCEPTANCE_PRODUCERS
    )
    policy_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"policy_fingerprint"})

    @model_validator(mode="after")
    def policy_is_exact_and_fresh(self) -> Self:
        _require_identity(self.policy_id, "policy_id")
        _require_identity(self.policy_version, "policy_version")
        _require_sha256(self.policy_fingerprint, "policy_fingerprint")
        identity = (self.policy_id, self.policy_version)
        expected: tuple[PlacementAcceptanceProducerRequirement, ...]
        if identity == (_V1_POLICY_ID, "1"):
            expected = REQUIRED_ACCEPTANCE_PRODUCERS
        elif identity == (_V2_ROUTING_ONLY_POLICY_ID, "2"):
            expected = ROUTING_ONLY_ACCEPTANCE_PRODUCERS
        else:
            raise ValueError("manifest policy identity is not a supported acceptance phase")
        if self.required_producers != expected:
            raise ValueError("manifest policy producers differ from its acceptance phase")
        if self.policy_fingerprint != _fingerprint(self.fingerprint_payload()):
            raise ValueError("manifest policy fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        policy_id: str | None = None,
        policy_version: str | None = None,
        routing_only: bool = False,
    ) -> Self:
        default_id = _V2_ROUTING_ONLY_POLICY_ID if routing_only else _V1_POLICY_ID
        default_version = "2" if routing_only else "1"
        fields: dict[str, Any] = {
            "policy_id": policy_id or default_id,
            "policy_version": policy_version or default_version,
            "required_producers": (
                ROUTING_ONLY_ACCEPTANCE_PRODUCERS
                if routing_only
                else REQUIRED_ACCEPTANCE_PRODUCERS
            ),
        }
        provisional = cls.model_construct(**fields, policy_fingerprint="0" * 64)
        return cls(**fields, policy_fingerprint=_fingerprint(provisional.fingerprint_payload()))


class PlacementAcceptanceManifest(BaseModel):
    """One accepted placement exact result composed with phase-exact aggregate gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-placement-acceptance-manifest"] = (
        "pcbsmith-placement-acceptance-manifest"
    )
    schema_version: Literal[1] = 1
    manifest_policy: PlacementAcceptanceManifestPolicy
    manifest_policy_fingerprint: str
    placement_exact_result: PlacementExactRunResult
    placement_exact_result_fingerprint: str
    accepted_candidate_fingerprint: str
    accepted_candidate_record: PlacementExactCandidateRecord
    accepted_candidate_record_fingerprint: str
    detail_record_fingerprint: str
    routing_run_fingerprint: str
    guidance_fingerprint: str
    corridor_graph_fingerprint: str
    corridor_plan_fingerprint: str
    corridor_guide_fingerprint: str
    route_geometry_fingerprint: str
    materialized_layout_fingerprint: str
    netlist_fingerprint: str
    aggregate_evidence: StableAggregateExactCheckEvidence
    aggregate_evidence_fingerprint: str
    aggregate_policy_fingerprint: str
    aggregate_subcheck_fingerprints: tuple[tuple[str, str, str], ...]
    circuit_board_equivalence_claimed: Literal[False] = False
    authority_scope_note: Literal[
        "Authority composition only; no thermometer readiness or circuit-to-board equivalence."
    ] = "Authority composition only; no thermometer readiness or circuit-to-board equivalence."
    manifest_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"manifest_fingerprint"})

    @model_validator(mode="after")
    def all_authority_replays_and_cross_binds(self) -> Self:
        manifest_policy = PlacementAcceptanceManifestPolicy.model_validate_json(
            self.manifest_policy.model_dump_json()
        )
        exact = PlacementExactRunResult.model_validate_json(
            self.placement_exact_result.model_dump_json()
        )
        aggregate = StableAggregateExactCheckEvidence.model_validate_json(
            self.aggregate_evidence.model_dump_json()
        )
        for field_name in (
            "manifest_policy_fingerprint",
            "placement_exact_result_fingerprint",
            "accepted_candidate_fingerprint",
            "accepted_candidate_record_fingerprint",
            "detail_record_fingerprint",
            "routing_run_fingerprint",
            "guidance_fingerprint",
            "corridor_graph_fingerprint",
            "corridor_plan_fingerprint",
            "corridor_guide_fingerprint",
            "route_geometry_fingerprint",
            "materialized_layout_fingerprint",
            "netlist_fingerprint",
            "aggregate_evidence_fingerprint",
            "aggregate_policy_fingerprint",
            "manifest_fingerprint",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        if self.manifest_policy_fingerprint != manifest_policy.policy_fingerprint:
            raise ValueError("manifest policy fingerprint is stale")
        if self.placement_exact_result_fingerprint != exact.semantic_fingerprint():
            raise ValueError("placement exact result fingerprint is stale")
        if len(exact.accepted_candidate_fingerprints) != 1:
            raise ValueError("manifest requires exactly one accepted placement candidate")
        candidate_id = exact.accepted_candidate_fingerprints[0]
        accepted = tuple(item for item in exact.candidate_records if item.accepted)
        if len(accepted) != 1 or accepted[0].candidate_fingerprint != candidate_id:
            raise ValueError("accepted placement candidate record is missing or ambiguous")
        record = PlacementExactCandidateRecord.model_validate_json(accepted[0].model_dump_json())
        if self.accepted_candidate_fingerprint != candidate_id:
            raise ValueError("selected accepted candidate fingerprint is stale")
        if self.accepted_candidate_record != record:
            raise ValueError("retained accepted candidate record differs from exact result")
        if self.accepted_candidate_record_fingerprint != record.semantic_fingerprint():
            raise ValueError("accepted candidate record fingerprint is stale")
        if (
            not record.accepted
            or record.disposition is not PlacementExactDisposition.EXACT_ACCEPTED
            or record.final_state is not PlacementFinalState.ACCEPTED
            or record.exact_report is None
        ):
            raise ValueError("manifest candidate is not exactly accepted")
        detail = record.detail_record
        if self.detail_record_fingerprint != detail.semantic_fingerprint():
            raise ValueError("detail record fingerprint is stale")
        routing = detail.routing_run
        guidance = detail.guidance
        if (
            routing is None
            or not routing.success
            or routing.resource_overuse
            or routing.exact_check_accepted is not None
            or detail.r2_evaluations_consumed != 1
            or not detail.algorithmic_success
            or not detail.zero_overuse
            or not detail.routed_unchecked
        ):
            raise ValueError("accepted detail does not bind a successful zero-overuse R2 run")
        if self.routing_run_fingerprint != routing.semantic_fingerprint():
            raise ValueError("routing run fingerprint is stale")
        if (
            guidance is None
            or guidance.disposition is not CorridorGuidanceDisposition.APPLIED
            or detail.r3_evaluations_consumed != 1
            or detail.corridor_graph_fingerprint is None
            or detail.corridor_plan_fingerprint is None
            or guidance.graph_fingerprint != detail.corridor_graph_fingerprint
            or guidance.plan_fingerprint != detail.corridor_plan_fingerprint
            or guidance.guide_fingerprint is None
            or guidance.routing_run_fingerprint != routing.semantic_fingerprint()
        ):
            raise ValueError("accepted detail lacks bound applied R3 guidance fingerprints")
        if self.guidance_fingerprint != guidance.semantic_fingerprint():
            raise ValueError("guidance fingerprint is stale")
        if self.corridor_graph_fingerprint != detail.corridor_graph_fingerprint:
            raise ValueError("corridor graph fingerprint is stale")
        if self.corridor_plan_fingerprint != detail.corridor_plan_fingerprint:
            raise ValueError("corridor plan fingerprint is stale")
        if self.corridor_guide_fingerprint != guidance.guide_fingerprint:
            raise ValueError("corridor guide fingerprint is stale")

        if not aggregate.aggregate_result.accepted:
            raise ValueError("aggregate evidence is not accepted")
        if (
            aggregate.aggregate_result.checker_id != exact.exact_policy.checker_id
            or record.exact_report.checker_id != exact.exact_policy.checker_id
        ):
            raise ValueError("aggregate and placement exact checker identities differ")
        aggregate_findings = tuple(
            sorted(set(aggregate.aggregate_result.finding_fingerprints))
        )
        if (
            record.exact_report.accepted != aggregate.aggregate_result.accepted
            or record.exact_report.finding_fingerprints != aggregate_findings
        ):
            raise ValueError("placement exact report differs from aggregate exact result")
        expected_report_fingerprint = exact_checker_report_fingerprint(
            aggregate.aggregate_result.accepted,
            aggregate.aggregate_result.checker_id,
            aggregate_findings,
        )
        if record.exact_report.checker_report_fingerprint != expected_report_fingerprint:
            raise ValueError("placement exact checker report fingerprint differs from aggregate")
        layout = parse_canonical_board_layout_snapshot(aggregate.layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(aggregate.netlist_snapshot_json)
        expected_layout = board_layout_fingerprint(layout)
        expected_route = placement_route_geometry_fingerprint(
            layout, frozenset(exact.detail_result.r2_policy.target_nets)
        )
        expected_netlist = placement_exact_netlist_fingerprint(netlist)
        if (
            self.materialized_layout_fingerprint != expected_layout
            or detail.materialized_layout_fingerprint != expected_layout
            or record.exact_report.materialized_layout_fingerprint != expected_layout
        ):
            raise ValueError("aggregate layout differs from accepted materialized layout")
        if (
            self.route_geometry_fingerprint != expected_route
            or detail.route_geometry_fingerprint != expected_route
            or record.exact_report.route_geometry_fingerprint != expected_route
        ):
            raise ValueError("aggregate layout differs from accepted route geometry")
        if (
            self.netlist_fingerprint != expected_netlist
            or record.netlist_fingerprint != expected_netlist
        ):
            raise ValueError("aggregate netlist differs from accepted exact-record netlist")

        external_requirements = tuple(
            item
            for item in aggregate.policy.subchecks
            if item.kind is AggregateSubcheckKind.EXTERNAL_ARTIFACT
        )
        required = manifest_policy.required_producers
        routing_only = manifest_policy.policy_id == _V2_ROUTING_ONLY_POLICY_ID
        expected_requirements = tuple(
            (
                item.subcheck_id,
                item.subcheck_version,
                item.producer_id,
                AggregateSubcheckApplicability.REQUIRED,
            )
            for item in required
        )
        if routing_only:
            simulation_requirement = REQUIRED_ACCEPTANCE_PRODUCERS[2]
            expected_requirements += (
                (
                    simulation_requirement.subcheck_id,
                    simulation_requirement.subcheck_version,
                    simulation_requirement.producer_id,
                    AggregateSubcheckApplicability.NOT_APPLICABLE,
                ),
            )
        actual_requirements = tuple(
            (
                item.subcheck_id,
                item.subcheck_version,
                item.producer_id,
                item.applicability,
            )
            for item in external_requirements
        )
        if actual_requirements != expected_requirements:
            raise ValueError("aggregate policy does not match the manifest acceptance phase")
        by_key = {(item.subcheck_id, item.subcheck_version): item for item in aggregate.subchecks}
        all_specialized_types = (
            KiCadSaveRoundtripSubcheckEvidence,
            ReaderNetlistEqualitySubcheckEvidence,
            ThermometerNgspiceSubcheckEvidence,
        )
        expected_types = (
            KiCadSaveRoundtripSubcheckEvidence,
            ReaderNetlistEqualitySubcheckEvidence,
        ) + (() if routing_only else (ThermometerNgspiceSubcheckEvidence,))
        specialized: list[
            KiCadSaveRoundtripSubcheckEvidence
            | ReaderNetlistEqualitySubcheckEvidence
            | ThermometerNgspiceSubcheckEvidence
        ] = []
        for requirement, expected_type in zip(required, expected_types, strict=True):
            item = by_key.get((requirement.subcheck_id, requirement.subcheck_version))
            if not isinstance(item, expected_type) or item.producer_id != requirement.producer_id:
                raise ValueError("aggregate specialized evidence does not match manifest producer")
            specialized.append(item)
        expected_specialized_count = 2 if routing_only else 3
        if (
            sum(isinstance(item, all_specialized_types) for item in aggregate.subchecks)
            != expected_specialized_count
        ):
            raise ValueError("aggregate specialized producer record count differs from phase")
        roundtrip, reader = specialized[:2]
        assert isinstance(roundtrip, KiCadSaveRoundtripSubcheckEvidence)
        assert isinstance(reader, ReaderNetlistEqualitySubcheckEvidence)
        serialization = roundtrip.roundtrip_authority.serialization_authority
        if (
            serialization.final_layout_snapshot_json != aggregate.layout_snapshot_json
            or serialization.source_netlist_snapshot_json != aggregate.netlist_snapshot_json
        ):
            raise ValueError("nested KiCad serialization differs from aggregate board inputs")
        if reader.machine_netlist_snapshot_json != aggregate.netlist_snapshot_json:
            raise ValueError("reader machine netlist differs from aggregate netlist")
        simulation_key = ("thermometer-simulation", "1")
        simulation = by_key.get(simulation_key)
        if routing_only:
            if (
                not isinstance(simulation, MissingSubcheckEvidence)
                or simulation.status is not AggregateCheckStatus.NOT_APPLICABLE
                or simulation.reason != _NOT_APPLICABLE_REASON
                or simulation.finding_fingerprint is not None
            ):
                raise ValueError(
                    "routing-only manifest requires the exact typed simulation N/A record"
                )
        elif (
            not isinstance(simulation, ThermometerNgspiceSubcheckEvidence)
            or simulation.status.value != "pass"
        ):
            raise ValueError("retained thermometer simulation producer is not accepted")

        expected_subchecks = tuple(
            (
                item.subcheck_id,
                item.subcheck_version,
                _fingerprint(item.model_dump(mode="json")),
            )
            for item in aggregate.subchecks
        )
        for _, _, fingerprint in self.aggregate_subcheck_fingerprints:
            _require_sha256(fingerprint, "aggregate subcheck fingerprint")
        if self.aggregate_subcheck_fingerprints != expected_subchecks:
            raise ValueError("aggregate subcheck fingerprints are stale")
        if self.aggregate_evidence_fingerprint != aggregate.evidence_fingerprint:
            raise ValueError("aggregate evidence fingerprint is stale")
        if self.aggregate_policy_fingerprint != aggregate.policy.policy_fingerprint:
            raise ValueError("aggregate policy fingerprint is stale")
        if self.manifest_fingerprint != _fingerprint(self.fingerprint_payload()):
            raise ValueError("placement acceptance manifest fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        manifest_policy: PlacementAcceptanceManifestPolicy,
        placement_exact_result: PlacementExactRunResult,
        aggregate_evidence: StableAggregateExactCheckEvidence,
    ) -> Self:
        retained_policy = PlacementAcceptanceManifestPolicy.model_validate_json(
            manifest_policy.model_dump_json()
        )
        exact = PlacementExactRunResult.model_validate_json(
            placement_exact_result.model_dump_json()
        )
        aggregate = StableAggregateExactCheckEvidence.model_validate_json(
            aggregate_evidence.model_dump_json()
        )
        if len(exact.accepted_candidate_fingerprints) != 1:
            raise ValueError("manifest requires exactly one accepted placement candidate")
        candidate_id = exact.accepted_candidate_fingerprints[0]
        record = next(
            item
            for item in exact.candidate_records
            if item.candidate_fingerprint == candidate_id
        )
        detail = record.detail_record
        if detail.routing_run is None or detail.guidance is None:
            raise ValueError("accepted candidate lacks routing or guidance authority")
        fields: dict[str, Any] = {
            "manifest_policy": retained_policy,
            "manifest_policy_fingerprint": retained_policy.policy_fingerprint,
            "placement_exact_result": exact,
            "placement_exact_result_fingerprint": exact.semantic_fingerprint(),
            "accepted_candidate_fingerprint": candidate_id,
            "accepted_candidate_record": record,
            "accepted_candidate_record_fingerprint": record.semantic_fingerprint(),
            "detail_record_fingerprint": detail.semantic_fingerprint(),
            "routing_run_fingerprint": detail.routing_run.semantic_fingerprint(),
            "guidance_fingerprint": detail.guidance.semantic_fingerprint(),
            "corridor_graph_fingerprint": detail.corridor_graph_fingerprint,
            "corridor_plan_fingerprint": detail.corridor_plan_fingerprint,
            "corridor_guide_fingerprint": detail.guidance.guide_fingerprint,
            "route_geometry_fingerprint": detail.route_geometry_fingerprint,
            "materialized_layout_fingerprint": detail.materialized_layout_fingerprint,
            "netlist_fingerprint": record.netlist_fingerprint,
            "aggregate_evidence": aggregate,
            "aggregate_evidence_fingerprint": aggregate.evidence_fingerprint,
            "aggregate_policy_fingerprint": aggregate.policy.policy_fingerprint,
            "aggregate_subcheck_fingerprints": tuple(
                (
                    item.subcheck_id,
                    item.subcheck_version,
                    _fingerprint(item.model_dump(mode="json")),
                )
                for item in aggregate.subchecks
            ),
        }
        if any(
            fields[name] is None
            for name in (
                "corridor_graph_fingerprint",
                "corridor_plan_fingerprint",
                "corridor_guide_fingerprint",
                "route_geometry_fingerprint",
                "materialized_layout_fingerprint",
                "netlist_fingerprint",
            )
        ):
            raise ValueError("accepted candidate authority is incomplete")
        provisional = cls.model_construct(**fields, manifest_fingerprint="0" * 64)
        return cls(**fields, manifest_fingerprint=_fingerprint(provisional.fingerprint_payload()))
