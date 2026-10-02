"""Selected-net/local-region routing orchestration above immutable transactions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.semantic_ir import SemanticIrModel


class RoutingRepairRegion(SemanticIrModel):
    schema_id: Literal["pcbsmith-routing-repair-region"] = "pcbsmith-routing-repair-region"
    schema_version: Literal[1] = 1
    x_min_mm: float
    y_min_mm: float
    x_max_mm: float
    y_max_mm: float
    expansion_index: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.x_max_mm <= self.x_min_mm or self.y_max_mm <= self.y_min_mm:
            raise ValueError("routing repair region must have positive area")
        return self

    def expanded(self, margin_mm: float) -> RoutingRepairRegion:
        if margin_mm <= 0:
            raise ValueError("expansion margin must be positive")
        return RoutingRepairRegion(
            x_min_mm=self.x_min_mm - margin_mm,
            y_min_mm=self.y_min_mm - margin_mm,
            x_max_mm=self.x_max_mm + margin_mm,
            y_max_mm=self.y_max_mm + margin_mm,
            expansion_index=self.expansion_index + 1,
        )


class SelectedRoutingDomain(SemanticIrModel):
    schema_id: Literal["pcbsmith-selected-routing-repair-domain"] = (
        "pcbsmith-selected-routing-repair-domain"
    )
    schema_version: Literal[1] = 1
    domain_id: str
    validation_scope: Literal["qualified_routing", "geometry_envelope"] = "qualified_routing"
    net_names: tuple[str, ...] = Field(min_length=1)
    mutable_object_ids: tuple[str, ...]
    protected_object_fingerprints: tuple[tuple[str, str], ...]
    initial_region: RoutingRepairRegion
    maximum_expansions: int = Field(ge=0, le=8)

    @model_validator(mode="after")
    def canonical(self) -> Self:
        nets = tuple(sorted(self.net_names))
        mutable = tuple(sorted(self.mutable_object_ids))
        protected = tuple(sorted(self.protected_object_fingerprints))
        if len(nets) != len(set(nets)) or len(mutable) != len(set(mutable)):
            raise ValueError("routing domain identities must be unique")
        if len(protected) != len({item[0] for item in protected}):
            raise ValueError("protected routing object identities must be unique")
        if set(mutable) & {item[0] for item in protected}:
            raise ValueError("mutable and protected routing objects must be disjoint")
        object.__setattr__(self, "net_names", nets)
        object.__setattr__(self, "mutable_object_ids", mutable)
        object.__setattr__(self, "protected_object_fingerprints", protected)
        return self


class RoutingCandidateMetrics(SemanticIrModel):
    schema_id: Literal["pcbsmith-local-routing-candidate-metrics"] = (
        "pcbsmith-local-routing-candidate-metrics"
    )
    schema_version: Literal[1] = 1
    candidate_id: str
    validation_scope: Literal["qualified_routing", "geometry_envelope"] = "qualified_routing"
    engine_id: str
    region: RoutingRepairRegion
    drc_violation_count: int | None = Field(ge=0)
    open_count: int | None = Field(ge=0)
    width_failure_count: int | None = Field(ge=0)
    return_failure_count: int | None = Field(ge=0)
    protected_change_count: int = Field(ge=0)
    unrelated_net_change_count: int = Field(ge=0)
    craft_penalty: float = Field(ge=0)
    route_length_mm: float = Field(ge=0)
    via_count: int = Field(ge=0)
    retained_directory: str

    @property
    def hard_clean(self) -> bool:
        if self.validation_scope == "geometry_envelope":
            return self.protected_change_count == 0 and self.unrelated_net_change_count == 0
        if any(
            value is None
            for value in (
                self.drc_violation_count,
                self.open_count,
                self.width_failure_count,
                self.return_failure_count,
            )
        ):
            return False
        return not any(
            (
                self.drc_violation_count if self.drc_violation_count is not None else 1_000_000,
                self.open_count if self.open_count is not None else 1_000_000,
                self.width_failure_count if self.width_failure_count is not None else 1_000_000,
                self.return_failure_count if self.return_failure_count is not None else 1_000_000,
                self.protected_change_count,
                self.unrelated_net_change_count,
            )
        )

    @property
    def rank_key(self) -> tuple[float | int | str, ...]:
        return (
            0 if self.hard_clean else 1,
            self.drc_violation_count if self.drc_violation_count is not None else 1_000_000,
            self.open_count if self.open_count is not None else 1_000_000,
            self.width_failure_count if self.width_failure_count is not None else 1_000_000,
            self.return_failure_count if self.return_failure_count is not None else 1_000_000,
            self.protected_change_count,
            self.unrelated_net_change_count,
            self.craft_penalty,
            self.route_length_mm,
            self.via_count,
            self.candidate_id,
        )


class LocalRoutingRepairRun(SemanticIrModel):
    schema_id: Literal["pcbsmith-local-routing-repair-run"] = "pcbsmith-local-routing-repair-run"
    schema_version: Literal[1] = 1
    domain: SelectedRoutingDomain
    attempts: tuple[RoutingCandidateMetrics, ...]
    selected_candidate_id: str | None
    accepted: bool
    terminal_reason: str
    run_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if any(item.validation_scope != self.domain.validation_scope for item in self.attempts):
            raise ValueError("routing metrics have the wrong validation scope")
        accepted = tuple(item for item in self.attempts if item.hard_clean)
        expected = min(accepted, key=lambda item: item.rank_key).candidate_id if accepted else None
        if self.selected_candidate_id != expected or self.accepted != (expected is not None):
            raise ValueError("local routing selection is stale")
        payload = self.model_dump(mode="json", exclude={"run_fingerprint"})
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.run_fingerprint != digest:
            # Historical qualified-routing receipts predate the explicit geometry scope.
            if self.domain.validation_scope != "qualified_routing":
                raise ValueError("local routing run fingerprint is stale")
            payload["domain"].pop("validation_scope")
            for attempt in payload["attempts"]:
                attempt.pop("validation_scope")
            legacy = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if self.run_fingerprint != legacy:
                raise ValueError("local routing run fingerprint is stale")
        return self


RoutingCandidateProducer = Callable[[RoutingRepairRegion], tuple[RoutingCandidateMetrics, ...]]


def run_local_routing_repair(
    domain: SelectedRoutingDomain,
    *,
    producer: RoutingCandidateProducer,
    expansion_margin_mm: float,
) -> LocalRoutingRepairRun:
    """Try one region at a time; expand only after every current candidate rejects."""

    attempts: list[RoutingCandidateMetrics] = []
    region = domain.initial_region
    selected: RoutingCandidateMetrics | None = None
    for expansion in range(domain.maximum_expansions + 1):
        current = tuple(sorted(producer(region), key=lambda item: item.candidate_id))
        if any(item.validation_scope != domain.validation_scope for item in current):
            raise ValueError("routing metrics have the wrong validation scope")
        if any(item.region != region for item in current):
            raise ValueError("routing producer returned a candidate for a different region")
        attempts.extend(current)
        clean = tuple(item for item in current if item.hard_clean)
        if clean:
            selected = min(clean, key=lambda item: item.rank_key)
            break
        if expansion < domain.maximum_expansions:
            region = region.expanded(expansion_margin_mm)
    terminal = "accepted" if selected is not None else "bounded_expansions_exhausted"
    fields = {
        "domain": domain,
        "attempts": tuple(attempts),
        "selected_candidate_id": selected.candidate_id if selected is not None else None,
        "accepted": selected is not None,
        "terminal_reason": terminal,
    }
    provisional = LocalRoutingRepairRun.model_construct(
        domain=domain,
        attempts=tuple(attempts),
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        accepted=selected is not None,
        terminal_reason=terminal,
        run_fingerprint="0" * 64,
    )
    payload = provisional.model_dump(mode="json", exclude={"run_fingerprint"})
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return LocalRoutingRepairRun(**fields, run_fingerprint=digest)
