from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SupportStatus = Literal["supported", "demo_only", "needs_datasheet_review", "unsupported"]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    title: str
    locator: str


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
    evidence: tuple[EvidenceRef, ...] = ()


class MathReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["passed", "warning", "failed"]
    calculations: dict[str, float]
    findings: tuple[str, ...] = ()


class SimulationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: Literal["ngspice"]
    status: Literal["passed", "warning", "failed", "unavailable"]
    command: tuple[str, ...] = ()
    measurements: dict[str, float] = Field(default_factory=dict)
    findings: tuple[str, ...] = ()
    raw_output_path: str | None = None


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
    artifacts: dict[str, str]
