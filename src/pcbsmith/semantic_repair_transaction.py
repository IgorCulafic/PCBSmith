"""Common fail-closed acceptance record for fill, marking, and 3D repairs."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.semantic_ir import SemanticIrModel


class SemanticRepairKind(StrEnum):
    FILL = "fill"
    MARKING = "marking"
    MODEL = "model"


class RepairGateRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-semantic-repair-gate"] = "pcbsmith-semantic-repair-gate"
    schema_version: Literal[1] = 1
    gate_id: str
    evaluated: bool
    passed: bool
    evidence_id: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.passed and not self.evaluated:
            raise ValueError("unevaluated repair gate cannot pass")
        if self.passed and self.evidence_id is None:
            raise ValueError("passing repair gate requires evidence")
        return self


class SemanticRepairCandidate(SemanticIrModel):
    schema_id: Literal["pcbsmith-semantic-repair-candidate"] = "pcbsmith-semantic-repair-candidate"
    schema_version: Literal[1] = 1
    candidate_id: str
    kind: SemanticRepairKind
    source_board_sha256: str
    candidate_board_sha256: str
    target_object_ids: tuple[str, ...] = Field(min_length=1)
    changed_object_ids: tuple[str, ...] = Field(min_length=1)
    protected_fingerprints_before: tuple[tuple[str, str], ...]
    protected_fingerprints_after: tuple[tuple[str, str], ...]
    gates: tuple[RepairGateRecord, ...]
    triggered_view_ids: tuple[str, ...]
    inspection_record_ids: tuple[str, ...]
    retained_directory: str

    @model_validator(mode="after")
    def canonical(self) -> Self:
        targets = tuple(sorted(self.target_object_ids))
        changed = tuple(sorted(self.changed_object_ids))
        gates = tuple(sorted(self.gates, key=lambda item: item.gate_id))
        if not set(changed) <= set(targets):
            raise ValueError("semantic repair changed an undeclared object")
        if len(gates) != len({item.gate_id for item in gates}):
            raise ValueError("semantic repair gate identities must be unique")
        object.__setattr__(self, "target_object_ids", targets)
        object.__setattr__(self, "changed_object_ids", changed)
        object.__setattr__(self, "gates", gates)
        object.__setattr__(self, "triggered_view_ids", tuple(sorted(self.triggered_view_ids)))
        object.__setattr__(self, "inspection_record_ids", tuple(sorted(self.inspection_record_ids)))
        return self


class SemanticRepairDecision(SemanticIrModel):
    schema_id: Literal["pcbsmith-semantic-repair-decision"] = "pcbsmith-semantic-repair-decision"
    schema_version: Literal[1] = 1
    candidate: SemanticRepairCandidate
    accepted: bool
    blockers: tuple[str, ...]


_REQUIRED_GATES: dict[SemanticRepairKind, frozenset[str]] = {
    SemanticRepairKind.FILL: frozenset({"drc", "connectivity", "fill", "thermal"}),
    SemanticRepairKind.MARKING: frozenset({"silk", "polarity", "mating"}),
    SemanticRepairKind.MODEL: frozenset({"applicability", "resolution", "transform"}),
}
_REQUIRED_VIEWS: dict[SemanticRepairKind, frozenset[str]] = {
    SemanticRepairKind.FILL: frozenset({"copper-detail"}),
    SemanticRepairKind.MARKING: frozenset({"marking-detail"}),
    SemanticRepairKind.MODEL: frozenset({"3d-detail"}),
}


def evaluate_semantic_repair(candidate: SemanticRepairCandidate) -> SemanticRepairDecision:
    blockers: list[str] = []
    if candidate.source_board_sha256 == candidate.candidate_board_sha256:
        blockers.append("candidate_board_unchanged")
    if candidate.protected_fingerprints_before != candidate.protected_fingerprints_after:
        blockers.append("protected_object_changed")
    by_gate = {item.gate_id: item for item in candidate.gates}
    for gate_id in sorted(_REQUIRED_GATES[candidate.kind]):
        gate = by_gate.get(gate_id)
        if gate is None:
            blockers.append(f"gate_missing:{gate_id}")
        elif not gate.evaluated:
            blockers.append(f"gate_unverified:{gate_id}")
        elif not gate.passed:
            blockers.append(f"gate_failed:{gate_id}")
    for view_id in sorted(_REQUIRED_VIEWS[candidate.kind] - set(candidate.triggered_view_ids)):
        blockers.append(f"view_missing:{view_id}")
    if not candidate.inspection_record_ids:
        blockers.append("inspection_record_missing")
    canonical = tuple(sorted(set(blockers)))
    return SemanticRepairDecision(
        candidate=candidate,
        accepted=not canonical,
        blockers=canonical,
    )
