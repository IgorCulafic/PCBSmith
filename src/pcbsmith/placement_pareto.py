"""Hard-gated Pareto selection for routability-aware placement candidates."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self, TypedDict

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class PlacementCandidateDisposition(StrEnum):
    HARD_ILLEGAL = "hard_illegal"
    DOMINATED = "dominated"
    PARETO_RETAINED = "pareto_retained"


class LocalPinAccessEvidence(SemanticIrModel):
    evidence_id: str
    owner_reference: str
    terminal_ids: tuple[str, ...] = Field(min_length=1)
    blocking_reference_ids: tuple[str, ...]
    exact_geometry_fingerprints: tuple[str, ...] = Field(min_length=1)
    blocked_terminal_count: int = Field(ge=0)
    evidence_fingerprint: str

    @model_validator(mode="after")
    def evidence_is_local_and_replay_bound(self) -> Self:
        require_identity(self.evidence_id, "evidence_id")
        require_identity(self.owner_reference, "owner_reference")
        terminals = tuple(sorted(self.terminal_ids))
        blockers = tuple(sorted(self.blocking_reference_ids))
        if len(terminals) != len(set(terminals)) or len(blockers) != len(set(blockers)):
            raise ValueError("local pin-access identities must be unique")
        if self.owner_reference in blockers:
            raise ValueError("pin-access owner cannot block itself")
        geometry = tuple(sorted(self.exact_geometry_fingerprints))
        for digest in geometry:
            require_sha256(digest, "exact_geometry_fingerprints")
        object.__setattr__(self, "terminal_ids", terminals)
        object.__setattr__(self, "blocking_reference_ids", blockers)
        object.__setattr__(self, "exact_geometry_fingerprints", geometry)
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"evidence_fingerprint"}))
        if self.evidence_fingerprint != expected:
            raise ValueError("local pin-access evidence fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> LocalPinAccessEvidence:
        provisional = cls.model_construct(**values, evidence_fingerprint="0" * 64)
        return cls(
            **values,
            evidence_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
            ),
        )


class PlacementRoutabilityMetrics(SemanticIrModel):
    candidate_id: str
    placement_sha256: str
    hard_illegal_finding_ids: tuple[str, ...] = ()
    local_pin_access: tuple[LocalPinAccessEvidence, ...]
    coarse_capacity_overflow_units: int = Field(ge=0)
    corridor_overflow_units: int = Field(ge=0)
    net_crossing_count: int = Field(ge=0)
    terminal_order_inversion_count: int = Field(ge=0)
    power_return_reservation_conflict_count: int = Field(ge=0)
    predicted_reference_fragmentation_count: int = Field(ge=0)
    predicted_unavoidable_slot_length_mm: float = Field(ge=0)
    topology_loop_length_mm: float = Field(ge=0)
    access_conflict_count: int = Field(ge=0)
    estimated_wirelength_mm: float = Field(ge=0)
    estimated_via_count: int = Field(ge=0)
    bounded_probe_unresolved_net_count: int = Field(ge=0)
    metrics_fingerprint: str

    @model_validator(mode="after")
    def metrics_are_canonical(self) -> Self:
        require_identity(self.candidate_id, "candidate_id")
        require_sha256(self.placement_sha256, "placement_sha256")
        hard = tuple(sorted(self.hard_illegal_finding_ids))
        access = tuple(sorted(self.local_pin_access, key=lambda item: item.evidence_id))
        if len(access) != len({item.evidence_id for item in access}):
            raise ValueError("local pin-access evidence identities must be unique")
        object.__setattr__(self, "hard_illegal_finding_ids", hard)
        object.__setattr__(self, "local_pin_access", access)
        require_sha256(self.metrics_fingerprint, "metrics_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"metrics_fingerprint"}))
        if self.metrics_fingerprint != expected:
            raise ValueError("placement routability metrics fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> PlacementRoutabilityMetrics:
        provisional = cls.model_construct(**values, metrics_fingerprint="0" * 64)
        return cls(
            **values,
            metrics_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"metrics_fingerprint"})
            ),
        )

    def objective_vector(self) -> tuple[float, ...]:
        return (
            float(sum(item.blocked_terminal_count for item in self.local_pin_access)),
            float(self.coarse_capacity_overflow_units),
            float(self.corridor_overflow_units),
            float(self.net_crossing_count),
            float(self.terminal_order_inversion_count),
            float(self.power_return_reservation_conflict_count),
            float(self.predicted_reference_fragmentation_count),
            self.predicted_unavoidable_slot_length_mm,
            self.topology_loop_length_mm,
            float(self.access_conflict_count),
            self.estimated_wirelength_mm,
            float(self.estimated_via_count),
            float(self.bounded_probe_unresolved_net_count),
        )


class PlacementParetoDecision(SemanticIrModel):
    candidate_id: str
    disposition: PlacementCandidateDisposition
    dominating_candidate_ids: tuple[str, ...]


class _PlacementParetoValues(TypedDict):
    candidates: tuple[PlacementRoutabilityMetrics, ...]
    decisions: tuple[PlacementParetoDecision, ...]
    retained_candidate_ids: tuple[str, ...]


class PlacementParetoSet(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-pareto-set"] = "pcbsmith-placement-pareto-set"
    schema_version: Literal[1] = 1
    candidates: tuple[PlacementRoutabilityMetrics, ...] = Field(min_length=1)
    decisions: tuple[PlacementParetoDecision, ...]
    retained_candidate_ids: tuple[str, ...]
    result_fingerprint: str

    @model_validator(mode="after")
    def result_is_replay_bound(self) -> Self:
        require_sha256(self.result_fingerprint, "result_fingerprint")
        expected = select_placement_pareto_set(self.candidates)
        if self.decisions != expected["decisions"]:
            raise ValueError("placement Pareto decisions are stale")
        if self.retained_candidate_ids != expected["retained_candidate_ids"]:
            raise ValueError("placement Pareto retained candidates are stale")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("placement Pareto result fingerprint is stale")
        return self


class BoardSizeFeasibilityAmendment(SemanticIrModel):
    schema_id: Literal["pcbsmith-board-size-feasibility-amendment"] = (
        "pcbsmith-board-size-feasibility-amendment"
    )
    schema_version: Literal[1] = 1
    amendment_id: str
    original_outline_sha256: str
    proposed_width_mm: float = Field(gt=0)
    proposed_height_mm: float = Field(gt=0)
    triggering_finding_ids: tuple[str, ...] = Field(min_length=1)
    preserves_required_interface_ids: tuple[str, ...]
    user_or_design_authority_approval_id: str | None = None
    automatic_apply_authorized: Literal[False] = False


def _dominates(left: PlacementRoutabilityMetrics, right: PlacementRoutabilityMetrics) -> bool:
    left_vector = left.objective_vector()
    right_vector = right.objective_vector()
    return all(a <= b for a, b in zip(left_vector, right_vector, strict=True)) and any(
        a < b for a, b in zip(left_vector, right_vector, strict=True)
    )


def select_placement_pareto_set(
    candidates: tuple[PlacementRoutabilityMetrics, ...],
) -> _PlacementParetoValues:
    if not candidates:
        raise ValueError("placement Pareto selection requires candidates")
    canonical = tuple(sorted(candidates, key=lambda item: item.candidate_id))
    if len(canonical) != len({item.candidate_id for item in canonical}):
        raise ValueError("placement candidate identities must be unique")
    decisions: list[PlacementParetoDecision] = []
    retained: list[str] = []
    legal = tuple(item for item in canonical if not item.hard_illegal_finding_ids)
    for candidate in canonical:
        if candidate.hard_illegal_finding_ids:
            disposition = PlacementCandidateDisposition.HARD_ILLEGAL
            dominators: tuple[str, ...] = ()
        else:
            dominators = tuple(
                item.candidate_id
                for item in legal
                if item.candidate_id != candidate.candidate_id and _dominates(item, candidate)
            )
            disposition = (
                PlacementCandidateDisposition.DOMINATED
                if dominators
                else PlacementCandidateDisposition.PARETO_RETAINED
            )
            if not dominators:
                retained.append(candidate.candidate_id)
        decisions.append(
            PlacementParetoDecision(
                candidate_id=candidate.candidate_id,
                disposition=disposition,
                dominating_candidate_ids=dominators,
            )
        )
    return {
        "candidates": canonical,
        "decisions": tuple(decisions),
        "retained_candidate_ids": tuple(retained),
    }


def build_placement_pareto_set(
    candidates: tuple[PlacementRoutabilityMetrics, ...],
) -> PlacementParetoSet:
    values = select_placement_pareto_set(candidates)
    provisional = PlacementParetoSet.model_construct(**values, result_fingerprint="0" * 64)
    return PlacementParetoSet(
        **values,
        result_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"result_fingerprint"})
        ),
    )


__all__ = [
    "BoardSizeFeasibilityAmendment",
    "LocalPinAccessEvidence",
    "PlacementCandidateDisposition",
    "PlacementParetoDecision",
    "PlacementParetoSet",
    "PlacementRoutabilityMetrics",
    "build_placement_pareto_set",
    "select_placement_pareto_set",
]
