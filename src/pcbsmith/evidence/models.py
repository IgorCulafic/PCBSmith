from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.circuit.models import AuthorityStatus


class EvidenceLocator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    local_file: str | None = None
    source_url: str | None = None
    page: int | None = None
    section: str | None = None
    table: str | None = None
    figure: str | None = None

    def describe(self) -> str:
        parts: list[str] = []
        if self.local_file is not None:
            parts.append(self.local_file)
        if self.page is not None:
            parts.append(f"page {self.page}")
        if self.section is not None:
            parts.append(f"section {self.section}")
        if self.table is not None:
            parts.append(f"table {self.table}")
        if self.figure is not None:
            parts.append(f"figure {self.figure}")
        if self.source_url is not None:
            parts.append(f"source {self.source_url}")
        return ", ".join(parts) if parts else "manifest locator unavailable"


class EvidenceFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    value: float | str | bool
    unit: str | None = None
    conditions: str | None = None
    locator: EvidenceLocator
    confidence: Literal["fixture", "machine_extracted", "human_reviewed"]


class CachedEvidenceFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    local_path: str
    sha256: str
    source_url: str | None = None
    retrieved_at: str | None = None
    license_status: str


class ComponentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manufacturer: str
    part_number: str
    role: str
    symbol_id: str
    value: str
    footprint: str | None = None
    files: tuple[CachedEvidenceFile, ...] = ()
    facts: tuple[EvidenceFact, ...] = ()

    def fact(self, name: str) -> EvidenceFact | None:
        for fact in self.facts:
            if fact.name == name:
                return fact
        return None


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-evidence-manifest-v1"] = Field(
        validation_alias="schema",
        serialization_alias="schema",
    )
    components: tuple[ComponentEvidence, ...]


class ComponentSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    role: str
    status: Literal["selected", "missing", "failed"]
    component: ComponentEvidence | None = None
    findings: tuple[str, ...] = ()


class EvidenceSelectionReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AuthorityStatus
    findings: tuple[str, ...] = ()
    cached_files: tuple[str, ...] = ()
    selections: tuple[ComponentSelection, ...] = ()


class EvidenceAcquisitionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    query: str
    manufacturer: str | None = None
    part_number: str | None = None


class EvidenceSourceCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    manufacturer: str
    part_number: str
    role: str
    source_url: str
    datasheet_url: str | None = None
    symbol_id: str | None = None
    value: str | None = None
    footprint: str | None = None
    license_status: str


class EvidenceAcquisitionReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["cache_hit", "downloaded", "missing", "failed"]
    component: ComponentEvidence | None = None
    findings: tuple[str, ...] = ()
    cached_files: tuple[str, ...] = ()
    candidate: EvidenceSourceCandidate | None = None
