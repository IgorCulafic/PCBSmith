"""Engine-neutral, deterministic routing-run interchange models.

The current KiCad A* result types can be adapted into this schema later. This
module deliberately contains no router behavior or KiCad geometry types.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoutingFailureReason(StrEnum):
    """Terminal reasons understood by routing orchestration."""

    UNROUTABLE = "unroutable"
    EXPANSION_BUDGET = "expansion_budget"
    PASS_BUDGET = "pass_budget"
    STAGNATION = "stagnation"
    EXACT_CHECK_REJECTION = "exact_check_rejection"
    OVERUSE_REMAINING = "overuse_remaining"


class RoutingIrModel(BaseModel):
    """Frozen base with canonical semantic serialization."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
    )

    def semantic_json(self) -> str:
        """Return deterministic JSON suitable for cache and audit keys."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def semantic_fingerprint(self) -> str:
        """SHA-256 of the complete versioned semantic representation."""
        return hashlib.sha256(self.semantic_json().encode("utf-8")).hexdigest()


class RoutingBudget(RoutingIrModel):
    """Fixed deterministic work limits for one routing run."""

    max_passes: int = Field(ge=0)
    max_expansions: int = Field(ge=0)
    max_expansions_per_net: int = Field(ge=0)
    max_stagnant_passes: int = Field(ge=0)
    max_exact_check_rejections: int = Field(ge=0)


class ResourceOveruseSummary(RoutingIrModel):
    """Capacity accounting for one engine-neutral routing resource."""

    resource_id: str = Field(min_length=1)
    resource_kind: Literal["edge", "via_site", "channel", "region", "other"]
    capacity_units: int = Field(ge=0)
    demand_units: int = Field(ge=0)
    overuse_units: int = Field(ge=0)
    net_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def overuse_matches_capacity_accounting(self) -> Self:
        expected = max(0, self.demand_units - self.capacity_units)
        if self.overuse_units != expected:
            raise ValueError("overuse_units must equal max(0, demand_units - capacity_units)")
        if len(set(self.net_names)) != len(self.net_names):
            raise ValueError("resource overuse net_names must be unique")
        object.__setattr__(self, "net_names", tuple(sorted(self.net_names)))
        return self


class NetRoutingTelemetry(RoutingIrModel):
    """One deterministic route attempt for one net in one pass."""

    net_name: str = Field(min_length=1)
    pass_index: int = Field(ge=0)
    attempt_index: int = Field(ge=0)
    expansion_count: int = Field(ge=0)
    segment_count: int = Field(default=0, ge=0)
    via_count: int = Field(default=0, ge=0)
    length_mm: float = Field(default=0.0, ge=0)
    routed: bool
    failure_reason: RoutingFailureReason | None = None
    exact_check_accepted: bool | None = None

    @model_validator(mode="after")
    def outcome_fields_are_coherent(self) -> Self:
        if self.routed and self.failure_reason is not None:
            raise ValueError("a routed net attempt cannot report a failure reason")
        if not self.routed and self.failure_reason is None:
            raise ValueError("an unresolved net attempt requires a failure reason")
        if self.exact_check_accepted is False and (
            self.failure_reason is not RoutingFailureReason.EXACT_CHECK_REJECTION
        ):
            raise ValueError("an exact-check rejection requires exact_check_rejection")
        if (
            self.failure_reason is RoutingFailureReason.EXACT_CHECK_REJECTION
            and self.exact_check_accepted is not False
        ):
            raise ValueError("exact_check_rejection requires exact_check_accepted=False")
        return self


class RoutingPassTelemetry(RoutingIrModel):
    """Per-pass net attempts, work counts, and resource state."""

    pass_index: int = Field(ge=0)
    net_telemetry: tuple[NetRoutingTelemetry, ...] = ()
    unresolved_net_names: tuple[str, ...] = ()
    resource_overuse: tuple[ResourceOveruseSummary, ...] = ()
    expansion_count: int = Field(default=0, ge=0)
    exact_check_rejection_count: int = Field(default=0, ge=0)
    stagnant: bool = False

    @model_validator(mode="after")
    def summaries_match_attempts(self) -> Self:
        attempt_keys = [(item.net_name, item.attempt_index) for item in self.net_telemetry]
        if len(set(attempt_keys)) != len(attempt_keys):
            raise ValueError("net attempts must be unique within a routing pass")
        if any(item.pass_index != self.pass_index for item in self.net_telemetry):
            raise ValueError("net telemetry pass_index must match its parent pass")
        if len(set(self.unresolved_net_names)) != len(self.unresolved_net_names):
            raise ValueError("unresolved_net_names must be unique")
        object.__setattr__(self, "unresolved_net_names", tuple(sorted(self.unresolved_net_names)))
        resource_ids = [item.resource_id for item in self.resource_overuse]
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("resource_id values must be unique within a pass")
        object.__setattr__(
            self,
            "resource_overuse",
            tuple(sorted(self.resource_overuse, key=lambda item: item.resource_id)),
        )
        expected_expansions = sum(item.expansion_count for item in self.net_telemetry)
        if self.expansion_count != expected_expansions:
            raise ValueError("pass expansion_count must equal net telemetry total")
        expected_rejections = sum(
            item.failure_reason is RoutingFailureReason.EXACT_CHECK_REJECTION
            for item in self.net_telemetry
        )
        if self.exact_check_rejection_count != expected_rejections:
            raise ValueError("pass exact_check_rejection_count must equal net telemetry total")
        return self


class RoutingRunResult(RoutingIrModel):
    """Versioned routing-run result suitable for engine adapters.

    `success` means the routing algorithm completed with no unresolved nets or
    capacity overuse. It is not an exact-geometry acceptance decision.
    """

    schema_id: Literal["pcbsmith-routing-run"] = "pcbsmith-routing-run"
    schema_version: Literal[2] = 2
    producer: str = Field(min_length=1)
    budget: RoutingBudget
    success: bool
    exact_check_accepted: bool | None = None
    failure_reason: RoutingFailureReason | None = None
    route_order: tuple[str, ...] = ()
    unresolved_net_names: tuple[str, ...] = ()
    restart_count: int = Field(default=0, ge=0)
    passes: tuple[RoutingPassTelemetry, ...] = ()
    resource_overuse: tuple[ResourceOveruseSummary, ...] = ()

    @property
    def accepted(self) -> bool:
        """Whether routing completed and an exact checker accepted it."""
        return self.success and self.exact_check_accepted is True

    @model_validator(mode="after")
    def result_is_coherent_and_within_budget(self) -> Self:
        if len(set(self.route_order)) != len(self.route_order):
            raise ValueError("route_order must contain unique net names")
        if len(set(self.unresolved_net_names)) != len(self.unresolved_net_names):
            raise ValueError("unresolved_net_names must be unique")
        if not set(self.unresolved_net_names).issubset(self.route_order):
            raise ValueError("unresolved nets must be present in route_order")
        object.__setattr__(self, "unresolved_net_names", tuple(sorted(self.unresolved_net_names)))
        resource_ids = [item.resource_id for item in self.resource_overuse]
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("final resource_id values must be unique")
        object.__setattr__(
            self,
            "resource_overuse",
            tuple(sorted(self.resource_overuse, key=lambda item: item.resource_id)),
        )

        expected_pass_indices = tuple(range(len(self.passes)))
        if tuple(item.pass_index for item in self.passes) != expected_pass_indices:
            raise ValueError("routing pass indices must be consecutive from zero")
        if len(self.passes) > self.budget.max_passes:
            raise ValueError("routing passes exceed the fixed pass budget")
        total_expansions = sum(item.expansion_count for item in self.passes)
        if total_expansions > self.budget.max_expansions:
            raise ValueError("routing expansions exceed the fixed expansion budget")
        if any(
            net.expansion_count > self.budget.max_expansions_per_net
            for route_pass in self.passes
            for net in route_pass.net_telemetry
        ):
            raise ValueError("net expansions exceed the fixed per-net budget")
        total_rejections = sum(item.exact_check_rejection_count for item in self.passes)
        if total_rejections > self.budget.max_exact_check_rejections:
            raise ValueError("exact-check rejections exceed the fixed budget")
        longest_stagnation = 0
        current_stagnation = 0
        for route_pass in self.passes:
            current_stagnation = current_stagnation + 1 if route_pass.stagnant else 0
            longest_stagnation = max(longest_stagnation, current_stagnation)
        if longest_stagnation > self.budget.max_stagnant_passes:
            raise ValueError("stagnant passes exceed the fixed stagnation budget")

        if self.passes:
            final_pass = self.passes[-1]
            if final_pass.unresolved_net_names != self.unresolved_net_names:
                raise ValueError("final pass unresolved nets must match the run result")
            if final_pass.resource_overuse != self.resource_overuse:
                raise ValueError("final pass overuse must match the run result")

        total_overuse = sum(item.overuse_units for item in self.resource_overuse)
        if self.exact_check_accepted is True and not self.success:
            raise ValueError("exact-check acceptance requires algorithmic success")
        if (
            self.failure_reason is RoutingFailureReason.EXACT_CHECK_REJECTION
            and self.exact_check_accepted is not False
        ):
            raise ValueError("exact_check_rejection requires exact_check_accepted=False")
        if self.success:
            if self.failure_reason is not None:
                raise ValueError("a successful run cannot report a failure reason")
            if self.unresolved_net_names:
                raise ValueError("a successful run cannot contain unresolved nets")
            if total_overuse:
                raise ValueError("a successful run requires zero resource overuse")
        elif self.failure_reason is None:
            raise ValueError("a failed run requires a typed failure reason")
        if self.failure_reason is RoutingFailureReason.OVERUSE_REMAINING and total_overuse == 0:
            raise ValueError("overuse_remaining requires positive resource overuse")
        if (
            self.failure_reason is RoutingFailureReason.EXACT_CHECK_REJECTION
            and total_rejections == 0
        ):
            raise ValueError("exact_check_rejection requires a rejected exact check")
        return self
