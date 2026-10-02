"""Fail-closed W7 aggregation for one refilled saved-board revision."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class QualificationDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"


class QualificationGate(SemanticIrModel):
    """One independently-derived gate bound to the exact saved board."""

    schema_id: Literal["pcbsmith-whole-board-qualification-gate"] = (
        "pcbsmith-whole-board-qualification-gate"
    )
    schema_version: Literal[1] = 1
    gate_id: str
    board_sha256: str
    disposition: QualificationDisposition
    applicable: bool
    evaluated_object_count: int = Field(ge=0)
    evidence_fingerprints: tuple[str, ...]
    finding_ids: tuple[str, ...]
    authority_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def gate_is_truthful(self) -> Self:
        require_identity(self.gate_id, "gate_id")
        require_sha256(self.board_sha256, "board_sha256")
        for field_name in ("evidence_fingerprints", "finding_ids", "authority_ids"):
            values = tuple(sorted(getattr(self, field_name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique values")
            object.__setattr__(self, field_name, values)
        for value in self.evidence_fingerprints:
            require_sha256(value, "evidence_fingerprints")
        if self.applicable and self.disposition is QualificationDisposition.NOT_APPLICABLE:
            raise ValueError("applicable gate cannot be not-applicable")
        if not self.applicable and self.disposition is not QualificationDisposition.NOT_APPLICABLE:
            raise ValueError("non-applicable gate must be explicitly not-applicable")
        if self.disposition is QualificationDisposition.PASS:
            if self.evaluated_object_count == 0:
                raise ValueError("zero evaluated objects cannot become PASS")
            if not self.evidence_fingerprints:
                raise ValueError("PASS requires revision-bound evidence")
            if self.finding_ids:
                raise ValueError("PASS cannot retain findings")
        if self.disposition is QualificationDisposition.FAIL and not self.finding_ids:
            raise ValueError("FAIL requires at least one finding")
        return self


class RoutingCraftAssessment(SemanticIrModel):
    """Deterministic aesthetics/cost evidence, separate from electrical truth."""

    schema_id: Literal["pcbsmith-routing-craft-assessment"] = "pcbsmith-routing-craft-assessment"
    schema_version: Literal[1] = 1
    board_sha256: str
    acute_bend_count: int = Field(ge=0)
    needless_bend_count: int = Field(ge=0)
    excessive_jog_count: int = Field(ge=0)
    unnecessary_via_count: int = Field(ge=0)
    long_detour_count: int = Field(ge=0)
    bus_disorder_count: int = Field(ge=0)
    congested_region_count: int = Field(ge=0)
    hard_rule_finding_ids: tuple[str, ...] = ()
    hard_rule_authority_ids: tuple[str, ...] = ()
    repair_recommended: bool
    rank_cost_units: int = Field(ge=0)

    @model_validator(mode="after")
    def assessment_is_coherent(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        counts = (
            self.acute_bend_count,
            self.needless_bend_count,
            self.excessive_jog_count,
            self.unnecessary_via_count,
            self.long_detour_count,
            self.bus_disorder_count,
            self.congested_region_count,
        )
        expected = sum(counts)
        if self.rank_cost_units != expected:
            raise ValueError("craft rank cost is stale")
        if self.repair_recommended != bool(expected):
            raise ValueError("craft repair recommendation is stale")
        findings = tuple(sorted(self.hard_rule_finding_ids))
        authorities = tuple(sorted(self.hard_rule_authority_ids))
        if bool(findings) != bool(authorities):
            raise ValueError("hard craft findings require explicit authority and vice versa")
        object.__setattr__(self, "hard_rule_finding_ids", findings)
        object.__setattr__(self, "hard_rule_authority_ids", authorities)
        return self


REQUIRED_GATE_IDS = (
    "kicad_integrity",
    "routed_copper_carrier_coverage",
    "filled_region_connectivity",
    "current_path_ledger",
    "current_environment_model",
    "reference_continuity",
    "functional_topology",
    "production_marking",
    "visual_review",
)


class WholeBoardQualification(SemanticIrModel):
    schema_id: Literal["pcbsmith-whole-board-qualification"] = "pcbsmith-whole-board-qualification"
    schema_version: Literal[1] = 1
    case_id: str
    refilled_board_sha256: str
    gates: tuple[QualificationGate, ...]
    craft: RoutingCraftAssessment
    release_qualified: bool
    blocker_ids: tuple[str, ...]
    unverified_gate_ids: tuple[str, ...]
    qualification_fingerprint: str

    @model_validator(mode="after")
    def result_is_replay_bound(self) -> Self:
        require_identity(self.case_id, "case_id")
        require_sha256(self.refilled_board_sha256, "refilled_board_sha256")
        gate_ids = tuple(item.gate_id for item in self.gates)
        if gate_ids != tuple(sorted(gate_ids)) or len(gate_ids) != len(set(gate_ids)):
            raise ValueError("qualification gates must be unique and canonical")
        missing = sorted(set(REQUIRED_GATE_IDS) - set(gate_ids))
        if missing:
            raise ValueError(f"required qualification gates are missing: {missing}")
        if any(item.board_sha256 != self.refilled_board_sha256 for item in self.gates):
            raise ValueError("mixed board revisions cannot be qualified together")
        if self.craft.board_sha256 != self.refilled_board_sha256:
            raise ValueError("craft evidence targets a different board revision")
        blockers = sorted(
            [f"{item.gate_id}:{finding}" for item in self.gates for finding in item.finding_ids]
            + [f"routing_craft:{item}" for item in self.craft.hard_rule_finding_ids]
        )
        unverified = sorted(
            item.gate_id
            for item in self.gates
            if item.applicable and item.disposition is QualificationDisposition.UNVERIFIED
        )
        all_required_clear = all(
            item.disposition
            in {
                QualificationDisposition.PASS,
                QualificationDisposition.NOT_APPLICABLE,
            }
            for item in self.gates
        )
        expected_release = all_required_clear and not blockers
        if tuple(blockers) != self.blocker_ids:
            raise ValueError("qualification blockers are stale")
        if tuple(unverified) != self.unverified_gate_ids:
            raise ValueError("unverified gate identities are stale")
        if self.release_qualified != expected_release:
            raise ValueError("release qualification disposition is stale")
        payload = self.model_dump(mode="json", exclude={"qualification_fingerprint"})
        if self.qualification_fingerprint != fingerprint(payload):
            raise ValueError("qualification fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        case_id: str,
        refilled_board_sha256: str,
        gates: tuple[QualificationGate, ...],
        craft: RoutingCraftAssessment,
    ) -> WholeBoardQualification:
        ordered = tuple(sorted(gates, key=lambda item: item.gate_id))
        blockers = tuple(
            sorted(
                [f"{item.gate_id}:{finding}" for item in ordered for finding in item.finding_ids]
                + [f"routing_craft:{item}" for item in craft.hard_rule_finding_ids]
            )
        )
        unverified = tuple(
            sorted(
                item.gate_id
                for item in ordered
                if item.applicable and item.disposition is QualificationDisposition.UNVERIFIED
            )
        )
        release = (
            all(
                item.disposition
                in {
                    QualificationDisposition.PASS,
                    QualificationDisposition.NOT_APPLICABLE,
                }
                for item in ordered
            )
            and not blockers
        )
        values: dict[str, Any] = {
            "case_id": case_id,
            "refilled_board_sha256": refilled_board_sha256,
            "gates": ordered,
            "craft": craft,
            "release_qualified": release,
            "blocker_ids": blockers,
            "unverified_gate_ids": unverified,
        }
        provisional = cls.model_construct(**values, qualification_fingerprint="0" * 64)
        return cls(
            **values,
            qualification_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"qualification_fingerprint"})
            ),
        )


__all__ = [
    "QualificationDisposition",
    "QualificationGate",
    "REQUIRED_GATE_IDS",
    "RoutingCraftAssessment",
    "WholeBoardQualification",
]
