"""Engine-neutral ordered-bus declarations and R3 capacity certificates."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.routing_ir import RoutingIrModel

BusLayer = Literal["F.Cu", "B.Cu"]
BusTerminalRole = Literal["source", "sink", "tap", "passive_endpoint"]


def _canonical_strings(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(set(values)))
    if len(canonical) != len(values) or any(not value for value in canonical):
        raise ValueError(f"{field_name} must contain unique non-empty identities")
    return canonical


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


class BusTerminalRef(RoutingIrModel):
    terminal_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    component_ref: str = Field(min_length=1)
    pad_number: str = Field(min_length=1)
    role: BusTerminalRole


class BusMember(RoutingIrModel):
    member_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    terminals: tuple[BusTerminalRef, ...] = Field(min_length=1)
    width_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def terminals_are_unique_and_owned(self) -> Self:
        if not math.isfinite(self.width_mm):
            raise ValueError("member width_mm must be finite and positive")
        terminal_ids = [terminal.terminal_id for terminal in self.terminals]
        if len(set(terminal_ids)) != len(terminal_ids):
            raise ValueError("member terminal identities must be unique")
        if any(terminal.net_name != self.net_name for terminal in self.terminals):
            raise ValueError("every member terminal must name the member net")
        object.__setattr__(
            self,
            "terminals",
            tuple(sorted(self.terminals, key=lambda terminal: terminal.terminal_id)),
        )
        return self


class BoundaryMemberRef(RoutingIrModel):
    member_id: str = Field(min_length=1)
    terminal_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def terminal_id_set_is_canonical(self) -> Self:
        object.__setattr__(
            self,
            "terminal_ids",
            _canonical_strings(self.terminal_ids, "terminal_ids"),
        )
        return self


class BusBoundary(RoutingIrModel):
    boundary_id: str = Field(min_length=1)
    corridor_portal_id: str = Field(min_length=1)
    orientation: Literal["forward", "reverse"]
    ordered_members: tuple[BoundaryMemberRef, ...]
    inactive_member_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def member_sets_are_coherent(self) -> Self:
        member_ids = tuple(member.member_id for member in self.ordered_members)
        if len(set(member_ids)) != len(member_ids):
            raise ValueError("boundary ordered member identities must be unique")
        inactive = _canonical_strings(self.inactive_member_ids, "inactive_member_ids")
        if set(member_ids) & set(inactive):
            raise ValueError("a boundary member cannot be both active and inactive")
        object.__setattr__(self, "inactive_member_ids", inactive)
        return self


class BusSwapWindow(RoutingIrModel):
    window_id: str = Field(min_length=1)
    corridor_region_id: str = Field(min_length=1)
    allowed_adjacent_pairs: tuple[tuple[str, str], ...] = ()
    allowed_layers: tuple[BusLayer, ...] = ()
    maximum_swaps: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def declarations_are_canonical_and_coherent(self) -> Self:
        pairs: list[tuple[str, str]] = []
        for pair in self.allowed_adjacent_pairs:
            low, high = pair
            if not low or not high or low == high:
                raise ValueError("swap pairs require two distinct non-empty member identities")
            pairs.append((low, high) if low < high else (high, low))
        canonical_pairs = tuple(sorted(set(pairs)))
        if len(canonical_pairs) != len(pairs):
            raise ValueError("swap pairs must be unique")
        layers = _canonical_strings(self.allowed_layers, "allowed_layers")
        if self.maximum_swaps > 0 and (not canonical_pairs or not layers):
            raise ValueError("a positive swap budget requires member pairs and allowed layers")
        if self.maximum_swaps == 0 and canonical_pairs:
            raise ValueError("declared swap pairs require a positive maximum_swaps")
        object.__setattr__(self, "allowed_adjacent_pairs", canonical_pairs)
        object.__setattr__(self, "allowed_layers", layers)
        return self


class BusPermutationPolicy(RoutingIrModel):
    allow_whole_bundle_reversal: bool = False
    allowed_boundary_permutations: tuple[tuple[str, tuple[str, ...]], ...] = ()
    swap_windows: tuple[BusSwapWindow, ...] = ()

    @model_validator(mode="after")
    def declarations_are_canonical(self) -> Self:
        permutations: list[tuple[str, tuple[str, ...]]] = []
        boundary_ids: set[str] = set()
        for boundary_id, member_ids in self.allowed_boundary_permutations:
            if not boundary_id or boundary_id in boundary_ids:
                raise ValueError("boundary permutation identities must be unique and non-empty")
            if not member_ids or any(not item for item in member_ids):
                raise ValueError("boundary permutations require non-empty member identities")
            if len(set(member_ids)) != len(member_ids):
                raise ValueError("boundary permutation member identities must be unique")
            boundary_ids.add(boundary_id)
            permutations.append((boundary_id, member_ids))
        windows = tuple(sorted(self.swap_windows, key=lambda item: item.window_id))
        if len({item.window_id for item in windows}) != len(windows):
            raise ValueError("swap window identities must be unique")
        object.__setattr__(
            self,
            "allowed_boundary_permutations",
            tuple(sorted(permutations, key=lambda item: item[0])),
        )
        object.__setattr__(self, "swap_windows", windows)
        return self


class BusViaPolicy(RoutingIrModel):
    mode: Literal[
        "forbidden",
        "escape_only",
        "declared_transition_windows",
        "independent_bounded",
        "synchronous",
    ]
    transition_window_ids: tuple[str, ...] = ()
    maximum_vias_per_member: int = Field(default=0, ge=0)
    maximum_via_count_spread: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def mode_and_limits_are_coherent(self) -> Self:
        windows = _canonical_strings(self.transition_window_ids, "transition_window_ids")
        if self.mode == "forbidden":
            if windows or self.maximum_vias_per_member != 0 or self.maximum_via_count_spread:
                raise ValueError("via-forbidden policy cannot declare windows or positive limits")
        else:
            if self.maximum_vias_per_member == 0:
                raise ValueError("a via-permitting policy requires a positive via limit")
            if (
                self.maximum_via_count_spread is not None
                and self.maximum_via_count_spread > self.maximum_vias_per_member
            ):
                raise ValueError("maximum via-count spread cannot exceed the per-member limit")
        needs_windows = self.mode in {"declared_transition_windows", "synchronous"}
        if needs_windows != bool(windows):
            raise ValueError("via mode and transition-window declarations are incoherent")
        object.__setattr__(self, "transition_window_ids", windows)
        return self


class BusLayerPolicy(RoutingIrModel):
    allowed_layers: tuple[BusLayer, ...] = Field(min_length=1)
    preferred_layers: tuple[BusLayer, ...] = ()
    via_policy: BusViaPolicy

    @model_validator(mode="after")
    def layer_sets_are_canonical_and_coherent(self) -> Self:
        allowed = _canonical_strings(self.allowed_layers, "allowed_layers")
        preferred = _canonical_strings(self.preferred_layers, "preferred_layers")
        if not set(preferred).issubset(allowed):
            raise ValueError("preferred layers must be a subset of allowed layers")
        if len(allowed) == 1 and self.via_policy.mode not in {"forbidden", "escape_only"}:
            raise ValueError("single-layer routing cannot declare routing-layer transitions")
        object.__setattr__(self, "allowed_layers", allowed)
        object.__setattr__(self, "preferred_layers", preferred)
        return self


class BusFallbackPolicy(RoutingIrModel):
    allow_individual_fallback: bool = False
    maximum_fallback_members: int = Field(default=0, ge=0)
    hard_constraints_may_degrade: Literal[False] = False

    @model_validator(mode="after")
    def fallback_limit_matches_permission(self) -> Self:
        if self.allow_individual_fallback != (self.maximum_fallback_members > 0):
            raise ValueError("individual fallback permission requires a coherent positive limit")
        return self


class ConstraintAuthority(RoutingIrModel):
    enforcement: Literal["advisory", "hard"]
    evidence: tuple[EvidenceRef, ...] = ()
    applicability_conditions: tuple[str, ...] = ()
    validation_method_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def evidence_and_conditions_are_canonical(self) -> Self:
        evidence_keys = tuple(item.model_dump_json() for item in self.evidence)
        if len(set(evidence_keys)) != len(evidence_keys):
            raise ValueError("constraint evidence references must be unique")
        evidence = tuple(item for _, item in sorted(zip(evidence_keys, self.evidence, strict=True)))
        conditions = _canonical_strings(
            self.applicability_conditions,
            "applicability_conditions",
        )
        validation_ids = _canonical_strings(
            self.validation_method_ids,
            "validation_method_ids",
        )
        if self.enforcement == "hard":
            if not conditions:
                raise ValueError("hard authority requires non-empty applicability_conditions")
            if not any(_evidence_supports_hard_authority(item, conditions) for item in evidence):
                raise ValueError(
                    "hard authority requires pinned SHA-backed, locator-verified, "
                    "applicability-confirmed evidence with all required conditions"
                )
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "applicability_conditions", conditions)
        object.__setattr__(self, "validation_method_ids", validation_ids)
        return self


def _evidence_supports_hard_authority(
    evidence: EvidenceRef,
    applicability_conditions: tuple[str, ...],
) -> bool:
    digest = evidence.local_sha256 or ""
    return (
        evidence.source_status == "pinned"
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and evidence.locator_status in {"text_verified", "figure_verified", "figure_bound"}
        and evidence.applicability_status == "confirmed"
        and set(evidence.required_conditions).issubset(applicability_conditions)
    )


def _validate_optional_numbers(
    values: Mapping[str, float | None],
    *,
    allow_zero: frozenset[str] = frozenset(),
) -> None:
    for field_name, value in values.items():
        if value is None:
            continue
        if not math.isfinite(value) or value < 0 or (value == 0 and field_name not in allow_zero):
            raise ValueError(f"{field_name} must be finite and positive")


class BusTimingBudget(RoutingIrModel):
    clock_or_toggle_frequency_hz: float | None = None
    driver_rise_time_ns: float | None = None
    maximum_skew_ps: float | None = None
    maximum_delay_spread_ps: float | None = None
    maximum_length_spread_mm: float | None = None
    propagation_model_id: str | None = None
    authority: ConstraintAuthority

    @model_validator(mode="after")
    def numeric_limits_and_authority_are_coherent(self) -> Self:
        _validate_optional_numbers(
            {
                "clock_or_toggle_frequency_hz": self.clock_or_toggle_frequency_hz,
                "driver_rise_time_ns": self.driver_rise_time_ns,
                "maximum_skew_ps": self.maximum_skew_ps,
                "maximum_delay_spread_ps": self.maximum_delay_spread_ps,
                "maximum_length_spread_mm": self.maximum_length_spread_mm,
            },
            allow_zero=frozenset(
                {"maximum_skew_ps", "maximum_delay_spread_ps", "maximum_length_spread_mm"}
            ),
        )
        if self.propagation_model_id is not None and not self.propagation_model_id:
            raise ValueError("propagation_model_id must be non-empty when supplied")
        operative = (
            self.maximum_skew_ps,
            self.maximum_delay_spread_ps,
            self.maximum_length_spread_mm,
        )
        if self.authority.enforcement == "hard" and all(item is None for item in operative):
            raise ValueError("hard timing authority requires an operative numeric limit")
        return self


class BusCouplingBudget(RoutingIrModel):
    signal_swing_v: float | None = None
    acceptable_noise_v: float | None = None
    acceptable_noise_fraction: float | None = None
    maximum_parallel_run_mm: float | None = None
    reference_structure_id: str | None = None
    stackup_id: str | None = None
    adjacent_member_clearance_mm: float | None = None
    foreign_net_clearance_mm: float | None = None
    victim_class_ids: tuple[str, ...] = ()
    authority: ConstraintAuthority

    @model_validator(mode="after")
    def numeric_limits_and_authority_are_coherent(self) -> Self:
        _validate_optional_numbers(
            {
                "signal_swing_v": self.signal_swing_v,
                "acceptable_noise_v": self.acceptable_noise_v,
                "acceptable_noise_fraction": self.acceptable_noise_fraction,
                "maximum_parallel_run_mm": self.maximum_parallel_run_mm,
                "adjacent_member_clearance_mm": self.adjacent_member_clearance_mm,
                "foreign_net_clearance_mm": self.foreign_net_clearance_mm,
            },
            allow_zero=frozenset(
                {
                    "maximum_parallel_run_mm",
                    "adjacent_member_clearance_mm",
                    "foreign_net_clearance_mm",
                }
            ),
        )
        if self.acceptable_noise_fraction is not None and self.acceptable_noise_fraction > 1:
            raise ValueError("acceptable_noise_fraction cannot exceed one")
        for field_name in ("reference_structure_id", "stackup_id"):
            value = getattr(self, field_name)
            if value is not None and not value:
                raise ValueError(f"{field_name} must be non-empty when supplied")
        victims = _canonical_strings(self.victim_class_ids, "victim_class_ids")
        operative = (
            self.acceptable_noise_v,
            self.acceptable_noise_fraction,
            self.maximum_parallel_run_mm,
            self.adjacent_member_clearance_mm,
            self.foreign_net_clearance_mm,
        )
        if self.authority.enforcement == "hard" and all(item is None for item in operative):
            raise ValueError("hard coupling authority requires an operative numeric limit")
        object.__setattr__(self, "victim_class_ids", victims)
        return self


class BusCoherencePolicy(RoutingIrModel):
    minimum_coherence_fraction: float | None = None
    maximum_pitch_deviation_mm: float | None = None
    maximum_order_violations: int = Field(default=0, ge=0)
    authority: ConstraintAuthority

    @model_validator(mode="after")
    def numeric_limits_are_coherent(self) -> Self:
        _validate_optional_numbers(
            {
                "minimum_coherence_fraction": self.minimum_coherence_fraction,
                "maximum_pitch_deviation_mm": self.maximum_pitch_deviation_mm,
            },
            allow_zero=frozenset({"minimum_coherence_fraction", "maximum_pitch_deviation_mm"}),
        )
        if self.minimum_coherence_fraction is not None and not (
            0 <= self.minimum_coherence_fraction <= 1
        ):
            raise ValueError("minimum_coherence_fraction must be between zero and one")
        return self


class BusGroup(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-group"] = "pcbsmith-bus-group"
    schema_version: Literal[1] = 1
    bus_id: str = Field(min_length=1)
    members: tuple[BusMember, ...] = Field(min_length=1)
    boundaries: tuple[BusBoundary, ...] = Field(min_length=1)
    permutation_policy: BusPermutationPolicy
    layer_policy: BusLayerPolicy
    timing_budget: BusTimingBudget | None = None
    coupling_budget: BusCouplingBudget | None = None
    coherence_policy: BusCoherencePolicy | None = None
    fallback_policy: BusFallbackPolicy = BusFallbackPolicy()
    rule_profile_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def declarations_are_referentially_sound(self) -> Self:
        member_by_id = {member.member_id: member for member in self.members}
        if len(member_by_id) != len(self.members):
            raise ValueError("bus member identities must be unique")
        if len({member.net_name for member in self.members}) != len(self.members):
            raise ValueError("bus member nets must be unique")
        terminal_by_id = {
            terminal.terminal_id: terminal
            for member in self.members
            for terminal in member.terminals
        }
        if len(terminal_by_id) != sum(len(member.terminals) for member in self.members):
            raise ValueError("bus terminal identities must be globally unique")
        boundary_ids = [boundary.boundary_id for boundary in self.boundaries]
        portal_ids = [boundary.corridor_portal_id for boundary in self.boundaries]
        if len(set(boundary_ids)) != len(boundary_ids):
            raise ValueError("bus boundary identities must be unique")
        if len(set(portal_ids)) != len(portal_ids):
            raise ValueError("bus boundary portal identities must be unique")
        boundary_by_id = {boundary.boundary_id: boundary for boundary in self.boundaries}
        for boundary_id, permutation in self.permutation_policy.allowed_boundary_permutations:
            boundary = boundary_by_id.get(boundary_id)
            if boundary is None:
                raise ValueError("boundary permutation references an unknown boundary")
            active_member_ids = {item.member_id for item in boundary.ordered_members}
            if set(permutation) != active_member_ids:
                raise ValueError(
                    "boundary permutation must contain exactly the boundary's active members"
                )
        for window in self.permutation_policy.swap_windows:
            if not set(window.allowed_layers).issubset(self.layer_policy.allowed_layers):
                raise ValueError("swap window layer must be allowed by the bus layer policy")
            for low, high in window.allowed_adjacent_pairs:
                if low not in member_by_id or high not in member_by_id:
                    raise ValueError("swap window references an unknown bus member")
        if self.fallback_policy.maximum_fallback_members > len(self.members):
            raise ValueError("fallback member limit cannot exceed the bus member count")

        active_indices: dict[str, list[int]] = {member_id: [] for member_id in member_by_id}
        active_refs: dict[tuple[str, int], BoundaryMemberRef] = {}
        inactive_indices: dict[str, list[int]] = {member_id: [] for member_id in member_by_id}
        for boundary_index, boundary in enumerate(self.boundaries):
            for member_ref in boundary.ordered_members:
                member = member_by_id.get(member_ref.member_id)
                if member is None:
                    raise ValueError("boundary references an unknown bus member")
                owned_terminal_ids = {terminal.terminal_id for terminal in member.terminals}
                if not set(member_ref.terminal_ids).issubset(owned_terminal_ids):
                    raise ValueError("boundary references a terminal not owned by its member")
                active_indices[member_ref.member_id].append(boundary_index)
                active_refs[(member_ref.member_id, boundary_index)] = member_ref
            for member_id in boundary.inactive_member_ids:
                if member_id not in member_by_id:
                    raise ValueError("boundary references an unknown inactive member")
                inactive_indices[member_id].append(boundary_index)

        for member_id, indices in active_indices.items():
            if not indices:
                raise ValueError("every bus member must be active on at least one boundary")
            if not any(index < len(self.boundaries) - 1 for index in indices):
                raise ValueError("every bus member must be active on at least one corridor section")
            if indices != list(range(indices[0], indices[-1] + 1)):
                raise ValueError("member activity must form one connected boundary interval")
            if any(index <= indices[-1] for index in inactive_indices[member_id]):
                raise ValueError("a member may become inactive only after its active interval")
            later_boundaries = set(range(indices[-1] + 1, len(self.boundaries)))
            if set(inactive_indices[member_id]) != later_boundaries:
                raise ValueError("an ended member must be declared inactive thereafter")
            member = member_by_id[member_id]
            terminal_roles = {terminal.terminal_id: terminal.role for terminal in member.terminals}
            if indices[0] > 0:
                first_ref = active_refs[(member_id, indices[0])]
                if not any(
                    terminal_roles[terminal_id] in {"source", "tap"}
                    for terminal_id in first_ref.terminal_ids
                ):
                    raise ValueError("late member activation requires a declared source or tap")
            if indices[-1] < len(self.boundaries) - 1:
                last_ref = active_refs[(member_id, indices[-1])]
                if not any(
                    terminal_roles[terminal_id] in {"sink", "tap", "passive_endpoint"}
                    for terminal_id in last_ref.terminal_ids
                ):
                    raise ValueError("member disappearance requires a declared terminal or tap")
        object.__setattr__(
            self,
            "members",
            tuple(sorted(self.members, key=lambda member: member.member_id)),
        )
        return self


class CertifiedLaneSlot(RoutingIrModel):
    slot_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    layer: BusLayer
    order_index: int = Field(ge=0)
    centerline_geometry_id: str = Field(min_length=1)
    maximum_track_width_mm: float = Field(gt=0)
    supported_clearance_domain_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def capability_is_canonical(self) -> Self:
        if not math.isfinite(self.maximum_track_width_mm):
            raise ValueError("maximum_track_width_mm must be finite and positive")
        object.__setattr__(
            self,
            "supported_clearance_domain_ids",
            _canonical_strings(
                self.supported_clearance_domain_ids,
                "supported_clearance_domain_ids",
            ),
        )
        return self


class CertifiedCorridorSection(RoutingIrModel):
    section_id: str = Field(min_length=1)
    entry_portal_id: str = Field(min_length=1)
    exit_portal_id: str = Field(min_length=1)
    lane_slots: tuple[CertifiedLaneSlot, ...] = Field(min_length=1)
    swap_window_ids: tuple[str, ...] = ()
    transition_window_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def slots_and_windows_are_coherent(self) -> Self:
        if self.entry_portal_id == self.exit_portal_id:
            raise ValueError("a corridor section requires distinct entry and exit portals")
        slot_ids = [slot.slot_id for slot in self.lane_slots]
        if len(set(slot_ids)) != len(slot_ids):
            raise ValueError("lane slot identities must be unique within a section")
        if any(slot.section_id != self.section_id for slot in self.lane_slots):
            raise ValueError("lane slot section_id must match its parent section")
        if tuple(slot.order_index for slot in self.lane_slots) != tuple(
            range(len(self.lane_slots))
        ):
            raise ValueError("lane slots must be declared in consecutive order")
        object.__setattr__(
            self,
            "swap_window_ids",
            _canonical_strings(self.swap_window_ids, "swap_window_ids"),
        )
        object.__setattr__(
            self,
            "transition_window_ids",
            _canonical_strings(self.transition_window_ids, "transition_window_ids"),
        )
        return self


class CorridorCapacityCertificate(RoutingIrModel):
    schema_id: Literal["pcbsmith-corridor-capacity-certificate"] = (
        "pcbsmith-corridor-capacity-certificate"
    )
    schema_version: Literal[1] = 1
    certificate_id: str = Field(min_length=1)
    board_geometry_fingerprint: str
    static_obstacle_fingerprint: str
    rule_profile_fingerprint: str
    demand_fingerprint: str
    corridor_graph_fingerprint: str
    grid_mm: float = Field(gt=0)
    sections: tuple[CertifiedCorridorSection, ...] = Field(min_length=1)
    reserved_demand_ids: tuple[str, ...] = ()
    exact_capacity_proof_id: str = Field(min_length=1)

    @field_validator(
        "board_geometry_fingerprint",
        "static_obstacle_fingerprint",
        "rule_profile_fingerprint",
        "demand_fingerprint",
        "corridor_graph_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def sections_form_a_canonical_chain(self) -> Self:
        if not math.isfinite(self.grid_mm):
            raise ValueError("grid_mm must be finite and positive")
        section_ids = [section.section_id for section in self.sections]
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("certificate section identities must be unique")
        slot_ids = [slot.slot_id for section in self.sections for slot in section.lane_slots]
        if len(set(slot_ids)) != len(slot_ids):
            raise ValueError("certificate lane slot identities must be globally unique")
        for previous, following in zip(self.sections, self.sections[1:], strict=False):
            if previous.exit_portal_id != following.entry_portal_id:
                raise ValueError("certificate sections must form one connected portal chain")
        object.__setattr__(
            self,
            "reserved_demand_ids",
            _canonical_strings(self.reserved_demand_ids, "reserved_demand_ids"),
        )
        return self


class BusTerminalOwnership(RoutingIrModel):
    terminal_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    component_ref: str = Field(min_length=1)
    pad_number: str = Field(min_length=1)


class BusCertificateContext(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-certificate-context"] = "pcbsmith-bus-certificate-context"
    schema_version: Literal[1] = 1
    board_geometry_fingerprint: str
    static_obstacle_fingerprint: str
    rule_profile_fingerprint: str
    demand_fingerprint: str
    corridor_graph_fingerprint: str
    grid_mm: float = Field(gt=0)

    @field_validator(
        "board_geometry_fingerprint",
        "static_obstacle_fingerprint",
        "rule_profile_fingerprint",
        "demand_fingerprint",
        "corridor_graph_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def grid_is_finite(self) -> Self:
        if not math.isfinite(self.grid_mm):
            raise ValueError("grid_mm must be finite and positive")
        return self


class BusCertificateHandshakeReason(StrEnum):
    READY = "ready"
    MISSING_CERTIFICATE = "missing_certificate"
    STALE_BOARD_GEOMETRY = "stale_board_geometry"
    STALE_STATIC_OBSTACLES = "stale_static_obstacles"
    STALE_RULE_PROFILE = "stale_rule_profile"
    STALE_DEMAND = "stale_demand"
    STALE_CORRIDOR_GRAPH = "stale_corridor_graph"
    WRONG_GRID = "wrong_grid"
    TERMINAL_OWNERSHIP_MISMATCH = "terminal_ownership_mismatch"
    TRACK_WIDTH_BELOW_PROFILE_MINIMUM = "track_width_below_profile_minimum"
    CERTIFICATE_REFERENCE_MISMATCH = "certificate_reference_mismatch"


class BusCertificateHandshakeResult(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-certificate-handshake"] = "pcbsmith-bus-certificate-handshake"
    schema_version: Literal[1] = 1
    ready: bool
    reason: BusCertificateHandshakeReason
    group_fingerprint: str
    context_fingerprint: str
    certificate_fingerprint: str | None = None
    detail_ids: tuple[str, ...] = ()

    @field_validator("group_fingerprint", "context_fingerprint")
    @classmethod
    def required_fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @field_validator("certificate_fingerprint")
    @classmethod
    def optional_fingerprint_is_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def state_is_coherent_and_canonical(self) -> Self:
        if self.ready != (self.reason is BusCertificateHandshakeReason.READY):
            raise ValueError("ready must exactly match the typed handshake reason")
        if self.ready and self.certificate_fingerprint is None:
            raise ValueError("a ready handshake requires a certificate fingerprint")
        if (
            self.reason is BusCertificateHandshakeReason.MISSING_CERTIFICATE
            and self.certificate_fingerprint is not None
        ):
            raise ValueError("a missing-certificate result cannot bind a certificate")
        object.__setattr__(self, "detail_ids", _canonical_strings(self.detail_ids, "detail_ids"))
        return self


def validate_bus_certificate(
    group: BusGroup,
    certificate: CorridorCapacityCertificate | None,
    context: BusCertificateContext,
    terminal_ownership: Mapping[str, BusTerminalOwnership],
    minimum_track_width_mm: float,
) -> BusCertificateHandshakeResult:
    """Validate declaration ownership and exact R3 certificate freshness."""

    if not math.isfinite(minimum_track_width_mm) or minimum_track_width_mm <= 0:
        raise ValueError("minimum_track_width_mm must be finite and positive")
    if certificate is None:
        return _handshake_result(
            group,
            context,
            None,
            BusCertificateHandshakeReason.MISSING_CERTIFICATE,
        )
    freshness_checks = (
        (
            certificate.board_geometry_fingerprint,
            context.board_geometry_fingerprint,
            BusCertificateHandshakeReason.STALE_BOARD_GEOMETRY,
        ),
        (
            certificate.static_obstacle_fingerprint,
            context.static_obstacle_fingerprint,
            BusCertificateHandshakeReason.STALE_STATIC_OBSTACLES,
        ),
        (
            certificate.rule_profile_fingerprint,
            context.rule_profile_fingerprint,
            BusCertificateHandshakeReason.STALE_RULE_PROFILE,
        ),
        (
            certificate.demand_fingerprint,
            context.demand_fingerprint,
            BusCertificateHandshakeReason.STALE_DEMAND,
        ),
        (
            certificate.corridor_graph_fingerprint,
            context.corridor_graph_fingerprint,
            BusCertificateHandshakeReason.STALE_CORRIDOR_GRAPH,
        ),
    )
    for actual, expected, reason in freshness_checks:
        if actual != expected:
            return _handshake_result(group, context, certificate, reason)
    if certificate.grid_mm != context.grid_mm:
        return _handshake_result(
            group,
            context,
            certificate,
            BusCertificateHandshakeReason.WRONG_GRID,
        )

    mismatched_terminals: list[str] = []
    for member in group.members:
        for terminal in member.terminals:
            ownership = terminal_ownership.get(terminal.terminal_id)
            if ownership is None or (
                ownership.terminal_id != terminal.terminal_id
                or ownership.net_name != terminal.net_name
                or ownership.component_ref != terminal.component_ref
                or ownership.pad_number != terminal.pad_number
            ):
                mismatched_terminals.append(terminal.terminal_id)
    if mismatched_terminals:
        return _handshake_result(
            group,
            context,
            certificate,
            BusCertificateHandshakeReason.TERMINAL_OWNERSHIP_MISMATCH,
            mismatched_terminals,
        )
    narrow_members = [
        member.member_id for member in group.members if member.width_mm < minimum_track_width_mm
    ]
    if narrow_members:
        return _handshake_result(
            group,
            context,
            certificate,
            BusCertificateHandshakeReason.TRACK_WIDTH_BELOW_PROFILE_MINIMUM,
            narrow_members,
        )
    reference_errors = _certificate_reference_errors(group, certificate)
    if reference_errors:
        return _handshake_result(
            group,
            context,
            certificate,
            BusCertificateHandshakeReason.CERTIFICATE_REFERENCE_MISMATCH,
            reference_errors,
        )
    return _handshake_result(
        group,
        context,
        certificate,
        BusCertificateHandshakeReason.READY,
    )


def _certificate_reference_errors(
    group: BusGroup,
    certificate: CorridorCapacityCertificate,
) -> tuple[str, ...]:
    portal_ids = {
        portal_id
        for section in certificate.sections
        for portal_id in (section.entry_portal_id, section.exit_portal_id)
    }
    errors = [
        f"boundary:{boundary.boundary_id}"
        for boundary in group.boundaries
        if boundary.corridor_portal_id not in portal_ids
    ]
    section_by_id = {item.section_id: item for item in certificate.sections}
    for window in group.permutation_policy.swap_windows:
        section = section_by_id.get(window.corridor_region_id)
        if section is None or window.window_id not in section.swap_window_ids:
            errors.append(f"swap-window:{window.window_id}")
            continue
        available_layers = {item.layer for item in section.lane_slots}
        if not set(window.allowed_layers).issubset(available_layers):
            errors.append(f"swap-window-layer:{window.window_id}")
    certified_transition_ids = {
        window_id for section in certificate.sections for window_id in section.transition_window_ids
    }
    for window_id in group.layer_policy.via_policy.transition_window_ids:
        if window_id not in certified_transition_ids:
            errors.append(f"transition-window:{window_id}")
    return _canonical_strings(tuple(errors), "certificate_reference_errors")


def _handshake_result(
    group: BusGroup,
    context: BusCertificateContext,
    certificate: CorridorCapacityCertificate | None,
    reason: BusCertificateHandshakeReason,
    detail_ids: Sequence[str] = (),
) -> BusCertificateHandshakeResult:
    return BusCertificateHandshakeResult(
        ready=reason is BusCertificateHandshakeReason.READY,
        reason=reason,
        group_fingerprint=group.semantic_fingerprint(),
        context_fingerprint=context.semantic_fingerprint(),
        certificate_fingerprint=(
            None if certificate is None else certificate.semantic_fingerprint()
        ),
        detail_ids=tuple(detail_ids),
    )
