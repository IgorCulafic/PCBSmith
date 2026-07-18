"""Typed R5.4 Pareto-selection and detailed-routing evidence."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.corridor_guidance import CorridorGuidanceReport
from pcbsmith.placement_ir import PlacementIrModel
from pcbsmith.routing_ir import RoutingBudget, RoutingRunResult


def _sha(value: str, name: str) -> str:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _ids(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    out = tuple(sorted(values))
    if len(set(out)) != len(out) or any(not x or x != x.strip() for x in out):
        raise ValueError(f"{name} must contain unique canonical identities")
    return out


def _fp(payload: object) -> str:
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(text.encode()).hexdigest()


class PlacementMarginRank(StrEnum):
    KNOWN_NONNEGATIVE = "known_nonnegative"
    UNKNOWN = "unknown"
    KNOWN_NEGATIVE = "known_negative"


class PlacementSelectionReason(StrEnum):
    NOT_SELECTED = "not_selected"
    BASE = "base"
    COARSE_FAILURE_EXPLORATION = "coarse_failure_exploration"
    FRONT_LEADER = "front_leader"
    CORRIDOR_DIVERSITY = "corridor_diversity"
    FLIP_BUCKET_DIVERSITY = "flip_bucket_diversity"
    FRONT_FILL = "front_fill"


class PlacementDetailState(StrEnum):
    NOT_SELECTED = "not_selected"
    CORRIDOR_BUDGET_EXHAUSTED = "corridor_budget_exhausted"
    ROUTING_BUDGET_EXHAUSTED = "routing_budget_exhausted"
    UNGUIDED_FORBIDDEN = "unguided_forbidden"
    ROUTING_FAILED = "routing_failed"
    ROUTED_UNCHECKED = "routed_unchecked"


class PlacementDetailSelectionPolicy(PlacementIrModel):
    policy_id: str = "r5.4-pareto-v1"
    portal_overflow_bucket_upper_bounds: tuple[int, ...] = (0, 1, 3, 7)
    coarse_failure_exploration_quota: int = Field(default=1, ge=0)
    allow_unguided_when_corridor_unavailable: bool = True

    @model_validator(mode="after")
    def valid(self) -> Self:
        if not self.policy_id or self.policy_id != self.policy_id.strip():
            raise ValueError("policy_id must be canonical")
        bounds = tuple(sorted(set(self.portal_overflow_bucket_upper_bounds)))
        if bounds != self.portal_overflow_bucket_upper_bounds or any(x < 0 for x in bounds):
            raise ValueError("overflow buckets must be sorted unique nonnegative bounds")
        return self


class PlacementDetailBudget(PlacementIrModel):
    max_selected_candidates: int = Field(ge=0)
    max_corridor_evaluations: int = Field(ge=0)
    max_routing_evaluations: int = Field(ge=0)


class PlacementR2Policy(PlacementIrModel):
    target_nets: tuple[str, ...]
    net_widths_mm: tuple[tuple[str, float], ...] = ()
    net_order: tuple[str, ...] = ()
    default_width_mm: float = Field(default=0.4, gt=0)
    grid_mm: float = Field(default=0.25, gt=0)
    off_corridor_penalty_units: int = Field(default=0, ge=0)
    max_passes: int = Field(default=16, ge=0)
    max_expansions: int = Field(default=250_000, ge=0)
    max_expansions_per_net: int = Field(default=50_000, ge=0)
    max_stagnant_passes: int = Field(default=8, ge=0)
    length_units_per_grid: int = Field(default=1000, gt=0)
    diagonal_length_units: int = Field(default=1414, gt=0)
    via_cost_units: int = Field(default=5000, gt=0)
    turn_cost_units: int = Field(default=100, ge=0)
    present_factor_units: int = Field(default=1, ge=0)
    present_growth_numerator: int = Field(default=2, gt=0)
    present_growth_denominator: int = Field(default=1, gt=0)
    history_increment_units: int = Field(default=4, gt=0)

    @model_validator(mode="after")
    def valid(self) -> Self:
        targets = _ids(self.target_nets, "target_nets")
        if not targets:
            raise ValueError("R2 policy needs target nets")
        widths = tuple(sorted(self.net_widths_mm))
        if len({x[0] for x in widths}) != len(widths) or any(
            not name or name != name.strip() or width <= 0 for name, width in widths
        ):
            raise ValueError("net widths must be unique, canonical, and positive")
        order = tuple(self.net_order)
        if len(set(order)) != len(order) or any(not x or x != x.strip() for x in order):
            raise ValueError("net_order must be canonical and unique")
        if order and set(order) != set(targets):
            raise ValueError("net_order must exactly cover target_nets")
        object.__setattr__(self, "target_nets", targets)
        object.__setattr__(self, "net_widths_mm", widths)
        return self


PrimaryPlacementVector = tuple[int, int, int, int, int, int, int, int, int]


class PlacementParetoEvidence(PlacementIrModel):
    candidate_fingerprint: str
    primary_vector: PrimaryPlacementVector
    hpwl_total_um: int = Field(ge=0)
    minimum_margin_rank: PlacementMarginRank
    minimum_terminal_margin_um: int | None
    corridor_allocation_fingerprint: str | None = None
    flip_set: tuple[str, ...] = ()
    portal_overflow_bucket: int = Field(ge=0)
    base_candidate: bool
    coarse_failure: bool
    pareto_front_index: int = Field(ge=0)
    dominated_by_candidate_fingerprints: tuple[str, ...] = ()
    selected: bool
    selection_reason: PlacementSelectionReason

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _sha(self.candidate_fingerprint, "candidate_fingerprint")
        if self.corridor_allocation_fingerprint is not None:
            _sha(self.corridor_allocation_fingerprint, "corridor_allocation_fingerprint")
        if any(x < 0 for x in self.primary_vector):
            raise ValueError("primary axes must be nonnegative")
        expected = (
            PlacementMarginRank.UNKNOWN
            if self.minimum_terminal_margin_um is None
            else PlacementMarginRank.KNOWN_NONNEGATIVE
            if self.minimum_terminal_margin_um >= 0
            else PlacementMarginRank.KNOWN_NEGATIVE
        )
        if self.minimum_margin_rank is not expected:
            raise ValueError("margin rank is stale")
        dominated = _ids(
            self.dominated_by_candidate_fingerprints, "dominated_by_candidate_fingerprints"
        )
        for item in dominated:
            _sha(item, "dominator fingerprint")
        if self.selected == (self.selection_reason is PlacementSelectionReason.NOT_SELECTED):
            raise ValueError("selection reason is stale")
        object.__setattr__(self, "flip_set", _ids(self.flip_set, "flip_set"))
        object.__setattr__(self, "dominated_by_candidate_fingerprints", dominated)
        return self


class PlacementCandidateDetailRecord(PlacementIrModel):
    candidate_fingerprint: str
    detail_input_fingerprint: str
    selected: bool
    state: PlacementDetailState
    r3_evaluations_consumed: int = Field(ge=0, le=1)
    r2_evaluations_consumed: int = Field(ge=0, le=1)
    corridor_graph_fingerprint: str | None = None
    corridor_plan_fingerprint: str | None = None
    guidance: CorridorGuidanceReport | None = None
    routing_run: RoutingRunResult | None = None
    materialized_layout_fingerprint: str | None = None
    route_geometry_fingerprint: str | None = None
    algorithmic_success: bool = False
    zero_overuse: bool = False
    routed_unchecked: bool = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        for name in (
            "candidate_fingerprint",
            "detail_input_fingerprint",
            "corridor_graph_fingerprint",
            "corridor_plan_fingerprint",
            "materialized_layout_fingerprint",
            "route_geometry_fingerprint",
        ):
            value = getattr(self, name)
            if value is not None:
                _sha(value, name)
        guidance = (
            None
            if self.guidance is None
            else CorridorGuidanceReport.model_validate_json(self.guidance.model_dump_json())
        )
        routing = (
            None
            if self.routing_run is None
            else RoutingRunResult.model_validate_json(self.routing_run.model_dump_json())
        )
        if not self.selected:
            if self.state is not PlacementDetailState.NOT_SELECTED or any(
                (self.r3_evaluations_consumed, self.r2_evaluations_consumed)
            ):
                raise ValueError("unselected record consumed work")
        elif self.state is PlacementDetailState.NOT_SELECTED:
            raise ValueError("selected record lacks a terminal state")
        if routing is None:
            if guidance is not None or any(
                (
                    self.materialized_layout_fingerprint,
                    self.route_geometry_fingerprint,
                    self.algorithmic_success,
                    self.zero_overuse,
                    self.routed_unchecked,
                )
            ):
                raise ValueError("routing-derived evidence lacks a routing run")
        else:
            if routing.exact_check_accepted is not None:
                raise ValueError("R5.4 cannot contain an exact-check verdict")
            success = routing.success
            zero = not routing.resource_overuse
            unchecked = success and zero and routing.exact_check_accepted is None
            if (
                self.algorithmic_success != success
                or self.zero_overuse != zero
                or self.routed_unchecked != unchecked
            ):
                raise ValueError("routing flags are stale")
            if self.r2_evaluations_consumed != 1:
                raise ValueError("routing evidence requires one R2 evaluation")
            expected = (
                PlacementDetailState.ROUTED_UNCHECKED
                if unchecked
                else PlacementDetailState.ROUTING_FAILED
            )
            if self.state is not expected:
                raise ValueError("routing state is stale")
            if (
                guidance is None
                or guidance.routing_run_fingerprint != routing.semantic_fingerprint()
            ):
                raise ValueError("guidance does not bind routing")
            if (
                self.materialized_layout_fingerprint is None
                or self.route_geometry_fingerprint is None
            ):
                raise ValueError("routing evidence lacks geometry fingerprints")
        object.__setattr__(self, "guidance", guidance)
        object.__setattr__(self, "routing_run", routing)
        return self


class PlacementDetailRunResult(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-detail-run"] = "pcbsmith-placement-detail-run"
    schema_version: Literal[1] = 1
    input_catalog_fingerprint: str
    selection_policy_fingerprint: str
    budget_fingerprint: str
    r2_policy_fingerprint: str
    profile_fingerprint: str
    input_fingerprint: str
    selection_policy: PlacementDetailSelectionPolicy
    budget: PlacementDetailBudget
    r2_policy: PlacementR2Policy
    pareto_evidence: tuple[PlacementParetoEvidence, ...]
    selected_candidate_fingerprints: tuple[str, ...]
    candidate_records: tuple[PlacementCandidateDetailRecord, ...]
    corridor_evaluations_consumed: int = Field(ge=0)
    routing_evaluations_consumed: int = Field(ge=0)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        components = (
            "input_catalog_fingerprint",
            "selection_policy_fingerprint",
            "budget_fingerprint",
            "r2_policy_fingerprint",
            "profile_fingerprint",
        )
        for name in (*components, "input_fingerprint"):
            _sha(getattr(self, name), name)
        expected = _fp(
            {
                "schema_id": "pcbsmith-placement-detail-input",
                "schema_version": 1,
                **{name: getattr(self, name) for name in components},
            }
        )
        if self.input_fingerprint != expected:
            raise ValueError("detail input fingerprint is stale")
        selection_policy = PlacementDetailSelectionPolicy.model_validate_json(
            self.selection_policy.model_dump_json()
        )
        budget = PlacementDetailBudget.model_validate_json(self.budget.model_dump_json())
        r2_policy = PlacementR2Policy.model_validate_json(self.r2_policy.model_dump_json())
        if selection_policy.semantic_fingerprint() != self.selection_policy_fingerprint:
            raise ValueError("selection policy fingerprint is stale")
        if budget.semantic_fingerprint() != self.budget_fingerprint:
            raise ValueError("detail budget fingerprint is stale")
        if r2_policy.semantic_fingerprint() != self.r2_policy_fingerprint:
            raise ValueError("R2 policy fingerprint is stale")
        pareto = tuple(
            sorted(
                (
                    PlacementParetoEvidence.model_validate_json(item.model_dump_json())
                    for item in self.pareto_evidence
                ),
                key=lambda item: item.candidate_fingerprint,
            )
        )
        records = tuple(
            sorted(
                (
                    PlacementCandidateDetailRecord.model_validate_json(item.model_dump_json())
                    for item in self.candidate_records
                ),
                key=lambda item: item.candidate_fingerprint,
            )
        )
        pareto_ids = tuple(item.candidate_fingerprint for item in pareto)
        record_ids = tuple(item.candidate_fingerprint for item in records)
        if len(set(pareto_ids)) != len(pareto) or pareto_ids != record_ids:
            raise ValueError("Pareto and detail records must cover unique matching candidates")
        selected = _ids(self.selected_candidate_fingerprints, "selected candidates")
        for item in selected:
            _sha(item, "selected fingerprint")
        if set(selected) != {x.candidate_fingerprint for x in pareto if x.selected} or set(
            selected
        ) != {x.candidate_fingerprint for x in records if x.selected}:
            raise ValueError("selected candidate evidence is stale")
        if self.corridor_evaluations_consumed != sum(x.r3_evaluations_consumed for x in records):
            raise ValueError("corridor work count is stale")
        if self.routing_evaluations_consumed != sum(x.r2_evaluations_consumed for x in records):
            raise ValueError("routing work count is stale")
        if len(selected) > budget.max_selected_candidates:
            raise ValueError("selected candidates exceed the fixed selection budget")
        if self.corridor_evaluations_consumed > budget.max_corridor_evaluations:
            raise ValueError("corridor work exceeds the fixed budget")
        if self.routing_evaluations_consumed > budget.max_routing_evaluations:
            raise ValueError("routing work exceeds the fixed budget")
        expected_routing_budget = RoutingBudget(
            max_passes=r2_policy.max_passes,
            max_expansions=r2_policy.max_expansions,
            max_expansions_per_net=r2_policy.max_expansions_per_net,
            max_stagnant_passes=r2_policy.max_stagnant_passes,
            max_exact_check_rejections=0,
        )
        if any(
            item.routing_run is not None and item.routing_run.budget != expected_routing_budget
            for item in records
        ):
            raise ValueError("nested routing run used a different fixed R2 budget")
        if any(
            item.portal_overflow_bucket
            != bisect_right(
                selection_policy.portal_overflow_bucket_upper_bounds,
                item.primary_vector[4],
            )
            for item in pareto
        ):
            raise ValueError("portal overflow bucket evidence is stale")
        object.__setattr__(self, "selection_policy", selection_policy)
        object.__setattr__(self, "budget", budget)
        object.__setattr__(self, "r2_policy", r2_policy)
        object.__setattr__(self, "pareto_evidence", pareto)
        object.__setattr__(self, "selected_candidate_fingerprints", selected)
        object.__setattr__(self, "candidate_records", records)
        return self
