"""Production adapters and one-shot checked commit for mixed route groups.

This module is intentionally opt-in.  It adapts ordinary R2 searches and
certified R4 bus candidates to the pure R4.3a group kernel, then installs and
exact-checks one complete mixed route map as a single rollback transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Any

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_geometry import CertifiedLaneGeometryRegistry
from pcbsmith.bus_ir import (
    BusCertificateContext,
    BusCertificateHandshakeResult,
    BusGroup,
    BusTerminalOwnership,
    CorridorCapacityCertificate,
    validate_bus_certificate,
)
from pcbsmith.kicad.astar_router import RoutingError
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.bus_candidate import (
    BusCandidateBudget,
    BusCandidateCallerOveruseMode,
    BusCandidateFailureReason,
    BusCandidatePolicy,
    BusCandidateResult,
    build_certified_bus_candidate,
)
from pcbsmith.kicad.bus_checked_commit import (
    BusRouteMapMaterializer,
    exact_route_check_fingerprint,
    materialize_complete_route_map,
)
from pcbsmith.kicad.bus_integration import CertifiedBusMemberPrefix
from pcbsmith.kicad.bus_transaction import (
    bus_route_map_fingerprint,
    negotiated_grid_route_fingerprint,
)
from pcbsmith.kicad.group_negotiation import (
    BusGroupCandidate,
    GroupAttemptDisposition,
    GroupCandidateContext,
    GroupCandidateFailure,
    GroupCandidateOutcome,
    GroupNegotiationBudget,
    GroupNegotiationResult,
    GroupNegotiationTargetRef,
    GroupRunDisposition,
    GroupTargetKind,
    OrdinaryGroupCandidate,
    negotiate_route_groups,
)
from pcbsmith.kicad.negotiated_board import ExactRouteChecker, ExactRouteCheckResult
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_grid import (
    GridSoftGuide,
    NegotiatedGridRoute,
    route_net_negotiated_candidate,
)
from pcbsmith.kicad.negotiated_resources import NetResourceClaims, OccupancyLedger
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.routing_ir import RoutingFailureReason
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

ClearanceGroup = tuple[Sequence[str], Sequence[str], float, Sequence[str]]


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")


def _canonical_payload(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical identity cannot contain non-finite floats")
        return value
    if isinstance(value, Enum):
        return {
            "enum_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_payload(value.value),
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "dataclass_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [
                [field.name, _canonical_payload(getattr(value, field.name))]
                for field in fields(value)
            ],
        }
    if isinstance(value, Mapping):
        encoded = [
            [_canonical_payload(key), _canonical_payload(item)] for key, item in value.items()
        ]
        return sorted(
            encoded,
            key=lambda item: json.dumps(item[0], sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, (tuple, list)):
        return [_canonical_payload(item) for item in value]
    raise TypeError(f"unsupported canonical identity value {type(value).__qualname__}")


def _profile_fingerprint(profile: PcbRuleProfile) -> str:
    return _fingerprint(profile.model_dump(mode="json"))


def _netlist_fingerprint(netlist: BoardNetlist) -> str:
    component_refs = tuple(component.reference for component in netlist.components)
    component_paths = tuple(component.uuid_path for component in netlist.components)
    net_names = tuple(net.name for net in netlist.nets)
    all_nodes = tuple(node for net in netlist.nets for node in net.nodes)
    for values, label in (
        (component_refs, "component references"),
        (component_paths, "component UUID paths"),
        (net_names, "net names"),
        (all_nodes, "net nodes"),
    ):
        if len(set(values)) != len(values):
            raise ValueError(f"board netlist contains duplicate {label}")
    components = []
    for component in netlist.components:
        component_fields = []
        for field in fields(component):
            value = getattr(component, field.name)
            if field.name == "fields":
                value = tuple(sorted(value))
            component_fields.append([field.name, _canonical_payload(value)])
        components.append(
            {
                "dataclass_type": f"{type(component).__module__}.{type(component).__qualname__}",
                "fields": component_fields,
            }
        )
    nets = []
    for net in netlist.nets:
        net_fields = []
        for field in fields(net):
            value = getattr(net, field.name)
            if field.name == "nodes":
                value = tuple(sorted(value))
            net_fields.append([field.name, _canonical_payload(value)])
        nets.append(
            {
                "dataclass_type": f"{type(net).__module__}.{type(net).__qualname__}",
                "fields": net_fields,
            }
        )
    def canonical_json(item: Any) -> str:
        return json.dumps(item, sort_keys=True, separators=(",", ":"))
    return _fingerprint(
        {
            "schema_id": "pcbsmith-board-netlist-complete",
            "schema_version": 1,
            "netlist_type": f"{type(netlist).__module__}.{type(netlist).__qualname__}",
            "components": sorted(components, key=canonical_json),
            "nets": sorted(nets, key=canonical_json),
        }
    )


def _static_binding_fingerprint(layout: BoardLayout, netlist: BoardNetlist) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-mixed-group-static-binding",
            "schema_version": 1,
            "layout": board_layout_fingerprint(layout),
            "netlist": _netlist_fingerprint(netlist),
        }
    )


def _canonical_clearance_groups(
    groups: Sequence[ClearanceGroup],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]], ...]:
    normalized = set()
    for nets_a, nets_b, gap_mm, exempt in groups:
        if not math.isfinite(gap_mm) or gap_mm < 0:
            raise ValueError("clearance group gap must be finite and non-negative")
        side_a = tuple(sorted(set(nets_a)))
        side_b = tuple(sorted(set(nets_b)))
        if not side_a or not side_b or any(not name for name in (*side_a, *side_b)):
            raise ValueError("clearance group net sets must be non-empty")
        low, high = sorted((side_a, side_b))
        normalized.add((low, high, gap_mm, tuple(sorted(set(exempt)))))
    return tuple(sorted(normalized))


def _guide_payload(guide: GridSoftGuide | None) -> Any:
    if guide is None:
        return None
    return {
        "grid_mm": guide.grid_mm,
        "nodes": sorted(guide.allowed_track_nodes),
        "transitions": sorted(guide.allowed_track_transitions),
        "vias": sorted(guide.allowed_via_cells),
        "penalty": guide.off_guide_transition_cost_units,
    }


@dataclass(frozen=True)
class OrdinaryGroupSearchSpec:
    target: GroupNegotiationTargetRef
    track_width_mm: float
    grid_mm: float
    soft_guide: GridSoftGuide | None = None
    route_prefix: GridRoutePrefix | None = None

    def __post_init__(self) -> None:
        if self.target.kind is not GroupTargetKind.ORDINARY:
            raise ValueError("ordinary search spec requires an ordinary target")
        if not math.isfinite(self.track_width_mm) or self.track_width_mm <= 0:
            raise ValueError("ordinary track width must be finite and positive")
        if not math.isfinite(self.grid_mm) or self.grid_mm <= 0:
            raise ValueError("ordinary grid must be finite and positive")
        if self.soft_guide is not None and self.soft_guide.grid_mm != self.grid_mm:
            raise ValueError("ordinary soft guide grid is stale")
        if self.route_prefix is not None:
            if self.route_prefix.net_name != self.target.net_names[0]:
                raise ValueError("ordinary route prefix owns the wrong net")
            if self.route_prefix.grid_mm != self.grid_mm:
                raise ValueError("ordinary route prefix grid is stale")

    def binding_fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema_id": "pcbsmith-ordinary-group-search-spec",
                "schema_version": 1,
                "target": self.target.semantic_fingerprint(),
                "track_width_mm": self.track_width_mm,
                "grid_mm": self.grid_mm,
                "soft_guide": _guide_payload(self.soft_guide),
                "route_prefix": (
                    None
                    if self.route_prefix is None
                    else self.route_prefix.semantic_fingerprint()
                ),
            }
        )


@dataclass(frozen=True)
class CertifiedBusGroupSearchSpec:
    target: GroupNegotiationTargetRef
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    geometry_registry: CertifiedLaneGeometryRegistry
    prefixes_by_member: Mapping[str, CertifiedBusMemberPrefix]
    certificate_context: BusCertificateContext
    terminal_ownership: Mapping[str, BusTerminalOwnership]
    minimum_track_width_mm: float
    candidate_budget: BusCandidateBudget
    candidate_policy: BusCandidatePolicy

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prefixes_by_member",
            MappingProxyType(dict(sorted(self.prefixes_by_member.items()))),
        )
        object.__setattr__(
            self,
            "terminal_ownership",
            MappingProxyType(dict(sorted(self.terminal_ownership.items()))),
        )
        if self.target.kind is not GroupTargetKind.BUS:
            raise ValueError("certified bus spec requires a bus target")
        if set(self.target.net_names) != {member.net_name for member in self.bus.members}:
            raise ValueError("bus target nets do not exactly match bus members")
        if self.target.bus_fingerprint != self.bus.semantic_fingerprint():
            raise ValueError("bus target fingerprint is stale")
        if self.target.allocation_fingerprint != self.allocation.allocation_fingerprint:
            raise ValueError("bus target allocation fingerprint is stale")
        if self.candidate_policy.caller_overuse_mode is not (
            BusCandidateCallerOveruseMode.PRESERVE_FOR_NEGOTIATION
        ):
            raise ValueError("group bus candidates must preserve caller overuse")
        handshake = self.handshake()
        if not handshake.ready:
            raise ValueError(f"bus certificate handshake is not ready: {handshake.reason}")
        expected_members = {member.member_id for member in self.bus.members}
        if set(self.prefixes_by_member) != expected_members:
            raise ValueError("certified prefixes must exactly cover bus members")
        for member_id, prefix in self.prefixes_by_member.items():
            if prefix.member_id != member_id:
                raise ValueError("certified prefix mapping key is stale")
            prefix.require_authority(
                self.bus,
                self.certificate,
                self.allocation,
                self.geometry_registry,
            )

    def handshake(self) -> BusCertificateHandshakeResult:
        return validate_bus_certificate(
            self.bus,
            self.certificate,
            self.certificate_context,
            self.terminal_ownership,
            self.minimum_track_width_mm,
        )

    def binding_fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema_id": "pcbsmith-certified-bus-group-search-spec",
                "schema_version": 1,
                "target": self.target.semantic_fingerprint(),
                "bus": self.bus.semantic_fingerprint(),
                "certificate": self.certificate.semantic_fingerprint(),
                "allocation": self.allocation.semantic_fingerprint(),
                "registry": self.geometry_registry.semantic_fingerprint(),
                "prefixes": [
                    [member_id, prefix.semantic_fingerprint()]
                    for member_id, prefix in sorted(self.prefixes_by_member.items())
                ],
                "context": self.certificate_context.semantic_fingerprint(),
                "ownership": [
                    [terminal_id, ownership.semantic_fingerprint()]
                    for terminal_id, ownership in sorted(self.terminal_ownership.items())
                ],
                "minimum_track_width_mm": self.minimum_track_width_mm,
                "candidate_budget": self.candidate_budget.model_dump(mode="json"),
                "candidate_policy": self.candidate_policy.model_dump(mode="json"),
                "handshake": self.handshake().semantic_fingerprint(),
            }
        )


GroupSearchSpec = OrdinaryGroupSearchSpec | CertifiedBusGroupSearchSpec


@dataclass(frozen=True, order=True)
class GroupSearchBinding:
    target_id: str
    target_kind: GroupTargetKind
    binding_fingerprint: str

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ValueError("search binding target_id must be non-empty")
        _require_sha256(self.binding_fingerprint, "binding_fingerprint")


@dataclass(frozen=True, order=True)
class BusCandidateAttemptAudit:
    pass_index: int
    attempt_index: int
    target_id: str
    result_fingerprint: str
    expansion_count: int
    complete: bool
    zero_overuse: bool
    failure_reason: BusCandidateFailureReason | None

    def __post_init__(self) -> None:
        if self.pass_index < 0 or self.attempt_index < 0 or self.expansion_count < 0:
            raise ValueError("bus attempt indices and work must be non-negative")
        if not self.target_id:
            raise ValueError("bus attempt target_id must be non-empty")
        _require_sha256(self.result_fingerprint, "result_fingerprint")
        if self.complete:
            if self.zero_overuse and self.failure_reason is not None:
                raise ValueError("complete zero-overuse bus attempt cannot report failure")
            if not self.zero_overuse and self.failure_reason is not (
                BusCandidateFailureReason.FINAL_OVERUSE
            ):
                raise ValueError("complete overused bus attempt requires FINAL_OVERUSE")
        elif self.zero_overuse or self.failure_reason in {
            None,
            BusCandidateFailureReason.FINAL_OVERUSE,
        }:
            raise ValueError("incomplete bus attempt requires a non-final typed failure")


@dataclass(frozen=True)
class MixedGroupCandidateResult:
    negotiation: GroupNegotiationResult
    search_bindings: tuple[GroupSearchBinding, ...]
    bus_attempts: tuple[BusCandidateAttemptAudit, ...]
    static_binding_fingerprint: str
    profile_fingerprint: str

    def __post_init__(self) -> None:
        _require_sha256(self.static_binding_fingerprint, "static_binding_fingerprint")
        _require_sha256(self.profile_fingerprint, "profile_fingerprint")
        bindings = tuple(sorted(self.search_bindings))
        if bindings != self.search_bindings:
            raise ValueError("mixed search bindings must be sorted")
        if len({item.target_id for item in bindings}) != len(bindings):
            raise ValueError("mixed search binding targets must be unique")
        targets = {item.target_id: item for item in self.negotiation.target_refs}
        if {item.target_id for item in bindings} != set(targets):
            raise ValueError("mixed search bindings must cover every target")
        if any(item.target_kind is not targets[item.target_id].kind for item in bindings):
            raise ValueError("mixed search binding target kind is stale")
        attempts = tuple(sorted(self.bus_attempts))
        if attempts != self.bus_attempts or len(
            {(item.pass_index, item.attempt_index, item.target_id) for item in attempts}
        ) != len(attempts):
            raise ValueError("bus attempt audits must be canonical and unique")
        expected = tuple(
            attempt
            for pass_telemetry in self.negotiation.passes
            for attempt in pass_telemetry.attempts
            if targets[attempt.target_id].kind is GroupTargetKind.BUS
        )
        if len(attempts) != len(expected):
            raise ValueError("bus attempt audits must cover every bus attempt")
        for audit, attempt in zip(attempts, expected, strict=True):
            if (
                audit.pass_index != attempt.pass_index
                or audit.attempt_index != attempt.attempt_index
                or audit.target_id != attempt.target_id
                or audit.expansion_count != attempt.expansion_count
            ):
                raise ValueError("bus attempt audit does not match group telemetry")
            installed = attempt.disposition is GroupAttemptDisposition.INSTALLED
            if audit.complete != installed:
                raise ValueError("bus attempt completion does not match group telemetry")

    @property
    def algorithmic_success(self) -> bool:
        return self.negotiation.success

    def semantic_fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema_id": "pcbsmith-mixed-group-candidate-result",
                "schema_version": 1,
                "negotiation": self.negotiation.semantic_fingerprint(),
                "bindings": [
                    {
                        "target_id": item.target_id,
                        "target_kind": item.target_kind.value,
                        "binding_fingerprint": item.binding_fingerprint,
                    }
                    for item in self.search_bindings
                ],
                "bus_attempts": [
                    {
                        **item.__dict__,
                        "failure_reason": (
                            item.failure_reason.value if item.failure_reason else None
                        ),
                    }
                    for item in self.bus_attempts
                ],
                "static_binding": self.static_binding_fingerprint,
                "profile": self.profile_fingerprint,
            }
        )

def build_mixed_group_candidate(
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    ledger: OccupancyLedger,
    routes_by_net: Mapping[str, NegotiatedGridRoute],
    specs: Sequence[GroupSearchSpec],
    *,
    budget: GroupNegotiationBudget,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    clearance_groups: Sequence[ClearanceGroup] = (),
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    baseline_order: Sequence[str] | None = None,
) -> MixedGroupCandidateResult:
    """Prevalidate and run ordinary/certified callbacks without hidden work."""

    specs = tuple(specs)
    if not specs:
        raise ValueError("mixed group routing requires at least one search spec")
    canonical_clearance_groups = _canonical_clearance_groups(clearance_groups)
    by_target: dict[str, GroupSearchSpec] = {}
    net_names = {net.name for net in netlist.nets}
    for spec in specs:
        if spec.target.target_id in by_target:
            raise ValueError("mixed search target IDs must be unique")
        if not set(spec.target.net_names).issubset(net_names):
            raise ValueError("mixed search target references an unknown net")
        if isinstance(spec, CertifiedBusGroupSearchSpec):
            if spec.bus.rule_profile_id != profile.profile_id:
                raise ValueError("certified bus rule profile is stale")
            if spec.minimum_track_width_mm != profile.geometry.minimum_trace_width_mm:
                raise ValueError("certified bus minimum track width is stale")
            if spec.certificate.grid_mm != spec.geometry_registry.grid_mm:
                raise ValueError("certified bus registry grid is stale")
        by_target[spec.target.target_id] = spec
    _validate_static_layout(static_layout, routes_by_net, by_target.values())
    static_fp = _static_binding_fingerprint(static_layout, netlist)
    profile_fp = _profile_fingerprint(profile)
    bindings = tuple(
        sorted(
            GroupSearchBinding(
                target_id=spec.target.target_id,
                target_kind=spec.target.kind,
                binding_fingerprint=_fingerprint(
                    {
                        "spec": spec.binding_fingerprint(),
                        "static": static_fp,
                        "profile": profile_fp,
                        "clearance_groups": [list(item) for item in canonical_clearance_groups],
                        "cost_policy": cost_policy.semantic_payload(),
                    }
                ),
            )
            for spec in specs
        )
    )
    audits: list[BusCandidateAttemptAudit] = []

    def search(context: GroupCandidateContext) -> GroupCandidateOutcome:
        spec = by_target[context.target.target_id]
        if isinstance(spec, OrdinaryGroupSearchSpec):
            try:
                route = route_net_negotiated_candidate(
                    static_layout,
                    netlist,
                    context.target.net_names[0],
                    context.ledger,
                    context.history,
                    context.present_factor_units,
                    cost_policy,
                    track_width_mm=spec.track_width_mm,
                    grid_mm=spec.grid_mm,
                    profile=profile,
                    clearance_groups=canonical_clearance_groups,
                    max_expansions=context.maximum_attempt_expansions,
                    soft_guide=spec.soft_guide,
                    route_prefix=spec.route_prefix,
                )
            except RoutingError as error:
                return GroupCandidateFailure(
                    context.target,
                    error.reason,
                    error.expansion_count,
                    f"ordinary:{error.reason.value}",
                )
            return OrdinaryGroupCandidate(
                context.target,
                route,
                route.result.expansion_count,
            )

        effective_total = min(
            spec.candidate_budget.max_total_expansions,
            context.maximum_attempt_expansions,
        )
        effective_budget = BusCandidateBudget(
            max_members=spec.candidate_budget.max_members,
            max_expansions_per_member=min(
                spec.candidate_budget.max_expansions_per_member,
                effective_total,
            ),
            max_total_expansions=effective_total,
        )
        result = build_certified_bus_candidate(
            static_layout,
            netlist,
            spec.bus,
            spec.certificate,
            spec.allocation,
            spec.geometry_registry,
            spec.prefixes_by_member,
            context.ledger,
            effective_budget,
            policy=spec.candidate_policy,
            history=context.history,
            present_factor_units=context.present_factor_units,
            cost_policy=cost_policy,
            profile=profile,
            clearance_groups=canonical_clearance_groups,
        )
        audits.append(
            BusCandidateAttemptAudit(
                pass_index=context.pass_index,
                attempt_index=context.attempt_index,
                target_id=context.target.target_id,
                result_fingerprint=result.semantic_fingerprint(),
                expansion_count=result.expansion_count,
                complete=result.complete,
                zero_overuse=result.zero_overuse,
                failure_reason=result.failure_reason,
            )
        )
        if result.complete and result.bundle is not None:
            return BusGroupCandidate(
                context.target,
                result.bundle,
                result.expansion_count,
            )
        return GroupCandidateFailure(
            context.target,
            _bus_routing_failure(result),
            result.expansion_count,
            f"certified_bus:{result.failure_reason}",
        )

    negotiation = negotiate_route_groups(
        tuple(spec.target for spec in specs),
        ledger,
        routes_by_net,
        search,
        budget=budget,
        baseline_order=baseline_order,
        policy=cost_policy,
    )
    return MixedGroupCandidateResult(
        negotiation=negotiation,
        search_bindings=bindings,
        bus_attempts=tuple(sorted(audits)),
        static_binding_fingerprint=static_fp,
        profile_fingerprint=profile_fp,
    )


def _bus_routing_failure(result: BusCandidateResult) -> RoutingFailureReason:
    if result.member_telemetry:
        reason = result.member_telemetry[-1].routing_failure_reason
        if reason is not None:
            return reason
    if result.failure_reason in {
        BusCandidateFailureReason.PER_MEMBER_EXPANSION_BUDGET,
        BusCandidateFailureReason.TOTAL_EXPANSION_BUDGET,
    }:
        return RoutingFailureReason.EXPANSION_BUDGET
    return RoutingFailureReason.UNROUTABLE


def _validate_static_layout(
    layout: BoardLayout,
    routes: Mapping[str, NegotiatedGridRoute],
    specs: Iterable[GroupSearchSpec],
) -> None:
    forbidden = set(routes)
    for spec in specs:
        forbidden.update(spec.target.net_names)
    if any(item.net_name in forbidden for item in layout.segments) or any(
        item.net_name in forbidden for item in layout.vias
    ):
        raise ValueError("static layout contains negotiable route-map copper")


class MixedGroupExactDisposition(StrEnum):
    NEGOTIATION_FAILED = "negotiation_failed"
    CANDIDATE_INVALID = "candidate_invalid"
    CHECKER_MISSING = "checker_missing"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


@dataclass(frozen=True)
class MixedGroupCheckedResult:
    algorithmic_success: bool
    exact_disposition: MixedGroupExactDisposition
    exact_report: ExactRouteCheckResult | None
    committed: bool
    candidate: MixedGroupCandidateResult
    candidate_fingerprint: str
    exact_report_fingerprint: str | None
    layout: BoardLayout | None
    materialized_layout_fingerprint: str | None
    materialization_call_count: int
    exact_check_call_count: int
    ledger_before_fingerprint: str
    ledger_after_fingerprint: str
    route_map_before_fingerprint: str
    route_map_after_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_fingerprint",
            "ledger_before_fingerprint",
            "ledger_after_fingerprint",
            "route_map_before_fingerprint",
            "route_map_after_fingerprint",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        if self.exact_report_fingerprint is not None:
            _require_sha256(self.exact_report_fingerprint, "exact_report_fingerprint")
        if self.materialized_layout_fingerprint is not None:
            _require_sha256(
                self.materialized_layout_fingerprint,
                "materialized_layout_fingerprint",
            )
        if self.candidate_fingerprint != self.candidate.semantic_fingerprint():
            raise ValueError("mixed candidate fingerprint is stale")
        if self.exact_report_fingerprint != exact_route_check_fingerprint(self.exact_report):
            raise ValueError("mixed exact-report fingerprint is stale")
        actual_layout_fingerprint = (
            None if self.layout is None else board_layout_fingerprint(self.layout)
        )
        if self.layout is not None and (
            self.materialized_layout_fingerprint != actual_layout_fingerprint
        ):
            raise ValueError("mixed materialized-layout fingerprint is stale")
        accepted = self.exact_disposition is MixedGroupExactDisposition.ACCEPTED
        checked = self.exact_disposition in {
            MixedGroupExactDisposition.ACCEPTED,
            MixedGroupExactDisposition.REJECTED,
        }
        if self.committed != accepted:
            raise ValueError("only an accepted mixed group may remain committed")
        if self.materialization_call_count != int(checked):
            raise ValueError("mixed materialization count is incoherent")
        if self.exact_check_call_count != int(checked):
            raise ValueError("mixed exact-check count is incoherent")
        if (self.exact_report is not None) != checked:
            raise ValueError("mixed exact report presence is incoherent")
        if (self.materialized_layout_fingerprint is not None) != checked:
            raise ValueError("mixed checked-layout fingerprint presence is incoherent")
        if accepted and (self.exact_report is None or not self.exact_report.accepted):
            raise ValueError("accepted mixed group requires exact acceptance")
        if self.exact_disposition is MixedGroupExactDisposition.REJECTED and (
            self.exact_report is None or self.exact_report.accepted
        ):
            raise ValueError("rejected mixed group requires exact rejection")
        if self.algorithmic_success != self.candidate.negotiation.success:
            raise ValueError("mixed algorithmic verdict is stale")
        if self.exact_disposition is MixedGroupExactDisposition.NEGOTIATION_FAILED:
            if self.algorithmic_success:
                raise ValueError("negotiation failure cannot follow algorithmic success")
        elif not self.algorithmic_success:
            raise ValueError("post-negotiation dispositions require algorithmic success")
        if self.layout is not None and not accepted:
            raise ValueError("only accepted mixed results expose a committed layout")
        if accepted != (self.layout is not None):
            raise ValueError("accepted mixed result requires its materialized layout")
        if not accepted and (
            self.ledger_before_fingerprint != self.ledger_after_fingerprint
            or self.route_map_before_fingerprint != self.route_map_after_fingerprint
        ):
            raise ValueError("unaccepted mixed results must restore exact caller state")
        if accepted and (
            self.ledger_after_fingerprint
            != self.candidate.negotiation.final_ledger_fingerprint
            or self.route_map_after_fingerprint
            != self.candidate.negotiation.final_route_map_fingerprint
        ):
            raise ValueError("accepted mixed state does not match its candidate")

    @property
    def accepted(self) -> bool:
        return self.committed and self.exact_disposition is MixedGroupExactDisposition.ACCEPTED

    def semantic_fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema_id": "pcbsmith-mixed-group-checked-result",
                "schema_version": 1,
                "algorithmic_success": self.algorithmic_success,
                "exact_disposition": self.exact_disposition.value,
                "exact_report": self.exact_report_fingerprint,
                "committed": self.committed,
                "candidate": self.candidate_fingerprint,
                "materialized_layout": self.materialized_layout_fingerprint,
                "materialization_call_count": self.materialization_call_count,
                "exact_check_call_count": self.exact_check_call_count,
                "ledger_before": self.ledger_before_fingerprint,
                "ledger_after": self.ledger_after_fingerprint,
                "route_map_before": self.route_map_before_fingerprint,
                "route_map_after": self.route_map_after_fingerprint,
            }
        )


class MixedGroupRollbackError(RuntimeError):
    def __init__(self, original_error: Exception, rollback_error: Exception) -> None:
        super().__init__(f"mixed group rollback failed after {type(original_error).__name__}")
        self.original_error = original_error
        self.rollback_error = rollback_error


class MixedGroupCheckedCommitCoordinator:
    def __init__(
        self,
        ledger: OccupancyLedger,
        routes_by_net: MutableMapping[str, NegotiatedGridRoute],
    ) -> None:
        self.ledger = ledger
        self.routes_by_net = routes_by_net

    def commit(
        self,
        static_layout: BoardLayout,
        netlist: BoardNetlist,
        specs: Sequence[GroupSearchSpec],
        *,
        budget: GroupNegotiationBudget,
        exact_checker: ExactRouteChecker | None,
        profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
        clearance_groups: Sequence[ClearanceGroup] = (),
        cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
        baseline_order: Sequence[str] | None = None,
        materializer: BusRouteMapMaterializer = materialize_complete_route_map,
    ) -> MixedGroupCheckedResult:
        frozen_specs = tuple(specs)
        snapshot_claims = self.ledger.committed_claims()
        snapshot_routes = dict(self.routes_by_net)
        ledger_before = self.ledger.semantic_fingerprint()
        route_before = bus_route_map_fingerprint(self.routes_by_net)
        candidate = build_mixed_group_candidate(
            static_layout,
            netlist,
            self.ledger,
            self.routes_by_net,
            frozen_specs,
            budget=budget,
            profile=profile,
            clearance_groups=clearance_groups,
            cost_policy=cost_policy,
            baseline_order=baseline_order,
        )
        if not candidate.negotiation.success:
            return self._result(
                candidate,
                MixedGroupExactDisposition.NEGOTIATION_FAILED,
                None,
                None,
                0,
                0,
                ledger_before,
                route_before,
            )
        try:
            self._install_candidate(candidate, snapshot_routes, frozen_specs)
        except ValueError as error:
            self._restore_after_invalid(error, snapshot_claims, snapshot_routes)
            return self._result(
                candidate,
                MixedGroupExactDisposition.CANDIDATE_INVALID,
                None,
                None,
                0,
                0,
                ledger_before,
                route_before,
            )
        except Exception as error:
            self._restore_or_raise(error, snapshot_claims, snapshot_routes)
        if exact_checker is None:
            self._restore_for_result(snapshot_claims, snapshot_routes)
            return self._result(
                candidate,
                MixedGroupExactDisposition.CHECKER_MISSING,
                None,
                None,
                0,
                0,
                ledger_before,
                route_before,
            )
        provisional_ledger = self.ledger.semantic_fingerprint()
        provisional_routes = bus_route_map_fingerprint(self.routes_by_net)
        report: ExactRouteCheckResult | None = None
        try:
            layout = materializer(
                static_layout,
                MappingProxyType(dict(self.routes_by_net)),
            )
            self._require_state(provisional_ledger, provisional_routes, "materializer")
            _validate_materialized_layout(static_layout, self.routes_by_net, layout)
            report = exact_checker(layout, netlist)
            if not isinstance(report, ExactRouteCheckResult):
                raise TypeError("exact checker must return ExactRouteCheckResult")
            self._require_state(provisional_ledger, provisional_routes, "exact checker")
        except Exception as error:
            self._restore_or_raise(error, snapshot_claims, snapshot_routes)
        assert report is not None
        if not report.accepted:
            self._restore_for_result(snapshot_claims, snapshot_routes)
            return self._result(
                candidate,
                MixedGroupExactDisposition.REJECTED,
                report,
                None,
                1,
                1,
                ledger_before,
                route_before,
                checked_layout_fingerprint=board_layout_fingerprint(layout),
            )
        return self._result(
            candidate,
            MixedGroupExactDisposition.ACCEPTED,
            report,
            layout,
            1,
            1,
            ledger_before,
            route_before,
        )

    def _install_candidate(
        self,
        candidate: MixedGroupCandidateResult,
        snapshot_routes: Mapping[str, NegotiatedGridRoute],
        specs: Sequence[GroupSearchSpec],
    ) -> None:
        result = candidate.negotiation
        if result.disposition is not GroupRunDisposition.COMPLETED or result.resource_overuse:
            raise ValueError("mixed group candidate is not complete and zero-overuse")
        routes = result.route_map()
        targets = {net for spec in specs for net in spec.target.net_names}
        if not targets.issubset(routes):
            raise ValueError("mixed group candidate omitted target nets")
        allowed_routes = set(snapshot_routes) | targets
        if set(routes) != allowed_routes:
            raise ValueError("mixed group candidate contains unexpected extra routes")
        for net_name, old in snapshot_routes.items():
            if net_name in targets:
                continue
            new = routes.get(net_name)
            if new is None or negotiated_grid_route_fingerprint(new) != (
                negotiated_grid_route_fingerprint(old)
            ):
                raise ValueError("mixed group candidate changed a non-target route")
        self._restore_state(
            tuple(route.claims for route in routes.values()),
            routes,
        )
        if self.ledger.overuse():
            raise ValueError("provisional mixed group has capacity overuse")
        if self.ledger.semantic_fingerprint() != result.final_ledger_fingerprint:
            raise ValueError("provisional mixed ledger fingerprint is stale")
        if bus_route_map_fingerprint(self.routes_by_net) != result.final_route_map_fingerprint:
            raise ValueError("provisional mixed route-map fingerprint is stale")

    def _require_state(self, ledger_fp: str, routes_fp: str, callback: str) -> None:
        if self.ledger.semantic_fingerprint() != ledger_fp or (
            bus_route_map_fingerprint(self.routes_by_net) != routes_fp
        ):
            raise RuntimeError(f"{callback} mutated mixed coordinator state")

    def _restore_state(
        self,
        claims: Sequence[NetResourceClaims],
        routes: Mapping[str, NegotiatedGridRoute],
    ) -> None:
        for current in self.ledger.committed_claims():
            self.ledger.rip_up(current.net_name)
        for claim in claims:
            self.ledger.restore(claim)
        self.routes_by_net.clear()
        self.routes_by_net.update(routes)

    def _restore_or_raise(
        self,
        error: Exception,
        claims: Sequence[NetResourceClaims],
        routes: Mapping[str, NegotiatedGridRoute],
    ) -> None:
        try:
            self._restore_state(claims, routes)
        except Exception as rollback_error:
            raise MixedGroupRollbackError(error, rollback_error) from error
        raise error

    def _restore_after_invalid(
        self,
        error: ValueError,
        claims: Sequence[NetResourceClaims],
        routes: Mapping[str, NegotiatedGridRoute],
    ) -> None:
        try:
            self._restore_state(claims, routes)
        except Exception as rollback_error:
            raise MixedGroupRollbackError(error, rollback_error) from error

    def _restore_for_result(
        self,
        claims: Sequence[NetResourceClaims],
        routes: Mapping[str, NegotiatedGridRoute],
    ) -> None:
        sentinel = RuntimeError("mixed group outcome requires rollback")
        try:
            self._restore_state(claims, routes)
        except Exception as rollback_error:
            raise MixedGroupRollbackError(sentinel, rollback_error) from sentinel

    def _result(
        self,
        candidate: MixedGroupCandidateResult,
        disposition: MixedGroupExactDisposition,
        report: ExactRouteCheckResult | None,
        layout: BoardLayout | None,
        materializations: int,
        exact_checks: int,
        ledger_before: str,
        route_before: str,
        *,
        checked_layout_fingerprint: str | None = None,
    ) -> MixedGroupCheckedResult:
        return MixedGroupCheckedResult(
            algorithmic_success=candidate.negotiation.success,
            exact_disposition=disposition,
            exact_report=report,
            committed=disposition is MixedGroupExactDisposition.ACCEPTED,
            candidate=candidate,
            candidate_fingerprint=candidate.semantic_fingerprint(),
            exact_report_fingerprint=exact_route_check_fingerprint(report),
            layout=layout,
            materialized_layout_fingerprint=(
                board_layout_fingerprint(layout)
                if layout is not None
                else checked_layout_fingerprint
            ),
            materialization_call_count=materializations,
            exact_check_call_count=exact_checks,
            ledger_before_fingerprint=ledger_before,
            ledger_after_fingerprint=self.ledger.semantic_fingerprint(),
            route_map_before_fingerprint=route_before,
            route_map_after_fingerprint=bus_route_map_fingerprint(self.routes_by_net),
        )


def _validate_materialized_layout(
    static: BoardLayout,
    routes: Mapping[str, NegotiatedGridRoute],
    materialized: BoardLayout,
) -> None:
    static_fields = tuple(item.name for item in fields(static))
    materialized_fields = tuple(item.name for item in fields(materialized))
    if static_fields != materialized_fields:
        raise ValueError("materialized BoardLayout field schema changed")
    ordered = tuple(routes[name] for name in sorted(routes))
    expected_segments = (
        *static.segments,
        *(segment for route in ordered for segment in route.result.segments),
    )
    expected_vias = (
        *static.vias,
        *(via for route in ordered for via in route.result.vias),
    )
    for field_name in static_fields:
        expected = (
            expected_segments
            if field_name == "segments"
            else expected_vias
            if field_name == "vias"
            else getattr(static, field_name)
        )
        if getattr(materialized, field_name) != expected:
            raise ValueError(f"materializer changed or omitted BoardLayout.{field_name}")
