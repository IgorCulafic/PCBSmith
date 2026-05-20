from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from pcbsmith.evidence.models import (
    ComponentEvidence,
    EvidenceExtractionJob,
    EvidenceFact,
    EvidenceManifest,
)


class EvidenceExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    facts: tuple[EvidenceFact, ...] = ()
    findings: tuple[str, ...] = ()


class EvidenceExtractionReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    processed_jobs: int
    findings: tuple[str, ...] = ()


class EvidenceExtractor(Protocol):
    def extract(self, path: Path) -> EvidenceExtractionResult:
        ...


class EvidenceExtractionService:
    def __init__(
        self,
        *,
        manifest_path: Path,
        extractor: EvidenceExtractor,
    ) -> None:
        self._manifest_path = manifest_path
        self._extractor = extractor

    def process_pending(self) -> EvidenceExtractionReport:
        manifest = self._load_manifest()
        components = list(manifest.components)
        jobs: list[EvidenceExtractionJob] = []
        processed = 0
        findings: list[str] = []

        for job in manifest.extraction_jobs:
            if job.status != "pending_extraction":
                jobs.append(job)
                continue
            processed += 1
            source_path = self._resolve_job_path(job)
            result = self._extractor.extract(source_path)
            if result.status == "machine_extracted":
                components = _merge_facts_into_component(components, job, result.facts)
                jobs.append(job.model_copy(update={"status": "machine_extracted"}))
                continue
            jobs.append(
                job.model_copy(
                    update={
                        "status": "failed",
                        "findings": result.findings or ("Extraction did not produce facts.",),
                    }
                )
            )
            findings.extend(result.findings)

        self._write_manifest(
            manifest.model_copy(
                update={
                    "components": tuple(components),
                    "extraction_jobs": tuple(jobs),
                }
            )
        )
        return EvidenceExtractionReport(processed_jobs=processed, findings=tuple(findings))

    def _load_manifest(self) -> EvidenceManifest:
        return EvidenceManifest.model_validate_json(
            self._manifest_path.read_text(encoding="utf-8")
        )

    def _write_manifest(self, manifest: EvidenceManifest) -> None:
        self._manifest_path.write_text(
            json.dumps(manifest.model_dump(by_alias=True), indent=2) + "\n",
            encoding="utf-8",
        )

    def _resolve_job_path(self, job: EvidenceExtractionJob) -> Path:
        path = Path(job.local_path)
        if path.is_absolute():
            return path
        return (self._manifest_path.parent / path).resolve()


def _merge_facts_into_component(
    components: list[ComponentEvidence],
    job: EvidenceExtractionJob,
    facts: tuple[EvidenceFact, ...],
) -> list[ComponentEvidence]:
    merged: list[ComponentEvidence] = []
    for component in components:
        if not _matches_job(component, job):
            merged.append(component)
            continue
        merged.append(
            component.model_copy(
                update={
                    "facts": _replace_same_named_facts(component.facts, facts),
                }
            )
        )
    return merged


def _matches_job(component: ComponentEvidence, job: EvidenceExtractionJob) -> bool:
    return (
        _normalize(component.manufacturer) == _normalize(job.component_manufacturer)
        and _normalize(component.part_number) == _normalize(job.component_part_number)
        and component.role == job.role
    )


def _replace_same_named_facts(
    existing: tuple[EvidenceFact, ...],
    new_facts: tuple[EvidenceFact, ...],
) -> tuple[EvidenceFact, ...]:
    new_names = {fact.name for fact in new_facts}
    return (*tuple(fact for fact in existing if fact.name not in new_names), *new_facts)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())

