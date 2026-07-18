from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SupportStatus = Literal["supported", "demo_only", "needs_datasheet_review", "unsupported"]
SourceStatus = Literal["pinned", "unpinned", "lead_only", "unknown"]
LocatorStatus = Literal[
    "text_verified",
    "figure_verified",
    "figure_bound",
    "ocr_ambiguous",
    "unverified",
]
ApplicabilityStatus = Literal["confirmed", "conditional", "inferred", "unknown"]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    title: str
    locator: str
    source_id: str | None = None
    organization_or_author: str | None = None
    revision: str | None = None
    official_url: str | None = None
    local_sha256: str | None = None
    source_status: SourceStatus = "unknown"
    locator_status: LocatorStatus = "unverified"
    applicability_status: ApplicabilityStatus = "unknown"
    required_conditions: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    origin_id: str | None = None


class CircuitIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_request: str
    intent_id: str
    status: Literal["supported", "unsupported"]
    assumptions: dict[str, float | str | bool] = Field(default_factory=dict)
    unsupported_reasons: tuple[str, ...] = ()


class TopologySelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    topology_id: str
    title: str
    status: Literal["selected", "unsupported"]
    evidence: tuple[EvidenceRef, ...]
    warnings: tuple[str, ...] = ()


class ComponentRole(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    role: str
    symbol_id: str
    value: str
    support_status: SupportStatus
    footprint: str | None = None
    evidence: tuple[EvidenceRef, ...] = ()


class MathReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["passed", "warning", "failed"]
    calculations: dict[str, float]
    findings: tuple[str, ...] = ()


class SimulationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: Literal["ngspice"]
    status: Literal["passed", "warning", "failed", "unavailable", "not_run"]
    command: tuple[str, ...] = ()
    measurements: dict[str, float] = Field(default_factory=dict)
    findings: tuple[str, ...] = ()
    raw_output_path: str | None = None


AuthorityStatus = Literal[
    "passed",
    "warning",
    "failed",
    "unavailable",
    "not_run",
    "needs_human_review",
]


class KiCadReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    command: tuple[str, ...] = ()
    schematic_file: str | None = None
    erc_report: str | None = None
    spice_netlist: str | None = None
    findings: tuple[str, ...] = ()


class BoardReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    command: tuple[str, ...] = ()
    board_file: str | None = None
    drc_report: str | None = None
    findings: tuple[str, ...] = ()


class ReviewFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: str
    severity: Literal["blocker", "warning", "style"]
    scope: Literal["component", "net", "region", "global"]
    where: str
    evidence: str
    suggested_action: str
    source: Literal["check", "model_review", "human"]
    fingerprint: str | None = None
    phase: str | None = None
    category: str | None = None
    object_ids: tuple[str, ...] = ()
    component_refs: tuple[str, ...] = ()
    pin_refs: tuple[str, ...] = ()
    net_refs: tuple[str, ...] = ()
    constraint_ids: tuple[str, ...] = ()
    related_locations: tuple[str, ...] = ()
    recurrence_count: int = Field(default=1, ge=1)
    suppression_reason: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def populate_fingerprint(self) -> Self:
        """Derive a stable diagnostic identity from semantic fields.

        Human-readable wording may evolve, but the rule, scope, location and
        referenced design objects define recurrence for repair and regression
        tracking. Callers may supply a fingerprint when migrating an existing
        diagnostic identity.
        """
        if self.fingerprint is not None:
            return self
        payload = {
            "rule": self.rule,
            "severity": self.severity,
            "scope": self.scope,
            "where": self.where,
            "source": self.source,
            "phase": self.phase,
            "category": self.category,
            "object_ids": self.object_ids,
            "component_refs": self.component_refs,
            "pin_refs": self.pin_refs,
            "net_refs": self.net_refs,
            "constraint_ids": self.constraint_ids,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
        object.__setattr__(self, "fingerprint", f"pcbsmith:{digest}")
        return self


class DesignReviewReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    checks_run: tuple[str, ...] = ()
    findings: tuple[ReviewFinding, ...] = ()


class EvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    findings: tuple[str, ...] = ()
    cached_files: tuple[str, ...] = ()


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    checks: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()


class RevisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: str
    parent_revision_id: str | None = None
    changed_artifacts: tuple[str, ...] = ()
    authority_checks: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    next_action: str


class CircuitObject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: CircuitIntent
    topology: TopologySelection
    components: tuple[ComponentRole, ...]
    nets: tuple[str, ...]
    math: MathReport


class CircuitReviewBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-circuit-review-bundle-v1"] = Field(
        validation_alias="schema",
        serialization_alias="schema",
    )
    intent_id: str
    status: Literal["passed", "warning", "failed", "unavailable", "needs_human_review"]
    items: tuple[str, ...]
    simulation: SimulationReport
    artifacts: dict[str, str]


class AuthorityReviewBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-circuit-review-bundle-v2"] = Field(
        validation_alias="schema",
        serialization_alias="schema",
    )
    status: AuthorityStatus
    intent: CircuitIntent
    pcbs_internal: CircuitObject
    evidence: EvidenceReport
    kicad: KiCadReport
    ngspice: SimulationReport
    reconciliation: ReconciliationReport
    board: BoardReport | None = None
    design_review: DesignReviewReport | None = None
    revisions: tuple[RevisionRecord, ...] = ()
    artifacts: dict[str, str]
