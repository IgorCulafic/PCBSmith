from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib import request

from pcbsmith.evidence.cache import EvidenceCache
from pcbsmith.evidence.models import (
    CachedEvidenceFile,
    ComponentEvidence,
    EvidenceAcquisitionReport,
    EvidenceAcquisitionRequest,
    EvidenceExtractionJob,
    EvidenceManifest,
    EvidenceSourceCandidate,
)


class EvidenceProvider(Protocol):
    def search(
        self,
        request: EvidenceAcquisitionRequest,
    ) -> tuple[EvidenceSourceCandidate, ...]:
        ...


class EvidenceDownloader(Protocol):
    def download(self, url: str) -> bytes:
        ...


class EvidenceDownloadError(RuntimeError):
    pass


class UrlLibEvidenceDownloader:
    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        self._timeout_seconds = timeout_seconds

    def download(self, url: str) -> bytes:
        http_request = request.Request(
            url,
            headers={"User-Agent": "pcbsmith-evidence/0.1"},
        )
        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                payload = response.read()
        except OSError as exc:
            raise EvidenceDownloadError(f"Datasheet download failed: {exc}") from exc
        if not isinstance(payload, bytes) or not payload:
            raise EvidenceDownloadError("Datasheet download returned no data.")
        return payload


def register_local_evidence(
    *,
    manifest_path: Path,
    source_file: Path,
    manufacturer: str,
    part_number: str,
    role: str,
    symbol_id: str,
    value: str,
    footprint: str | None,
    source_url: str | None,
    clock: Callable[[], str],
) -> ComponentEvidence:
    payload = source_file.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    manifest = _load_or_init_manifest(manifest_path)
    local_path = _relative_path(source_file.resolve(), manifest_path.parent)

    cached_file = CachedEvidenceFile(
        local_path=local_path,
        sha256=digest,
        source_url=source_url,
        retrieved_at=clock(),
        license_status="local_cache_only",
    )
    component = ComponentEvidence(
        manufacturer=manufacturer,
        part_number=part_number,
        role=role,
        symbol_id=symbol_id,
        value=value,
        footprint=footprint,
        files=(cached_file,),
        facts=(),
    )
    _write_manifest_file(
        manifest_path,
        EvidenceManifest(
            schema_id="pcbsmith-evidence-manifest-v1",
            components=(*_without_exact_component(manifest, component), component),
            extraction_jobs=(
                *_without_same_extraction_job(
                    manifest,
                    local_path=local_path,
                    sha256=digest,
                ),
                EvidenceExtractionJob(
                    status="pending_extraction",
                    component_manufacturer=manufacturer,
                    component_part_number=part_number,
                    role=role,
                    local_path=local_path,
                    sha256=digest,
                    source_url=source_url,
                    created_at=clock(),
                ),
            ),
        ),
    )
    return component


def _load_or_init_manifest(manifest_path: Path) -> EvidenceManifest:
    if not manifest_path.exists():
        _write_manifest_file(
            manifest_path,
            EvidenceManifest(
                schema_id="pcbsmith-evidence-manifest-v1",
                components=(),
            ),
        )
    return EvidenceManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))


def _write_manifest_file(manifest_path: Path, manifest: EvidenceManifest) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )


class EvidenceAcquisitionService:
    def __init__(
        self,
        *,
        manifest_path: Path,
        cache_dir: Path,
        provider: EvidenceProvider,
        downloader: EvidenceDownloader,
        clock: Callable[[], str],
    ) -> None:
        self._manifest_path = manifest_path
        self._cache_dir = cache_dir
        self._provider = provider
        self._downloader = downloader
        self._clock = clock

    def acquire(self, request: EvidenceAcquisitionRequest) -> EvidenceAcquisitionReport:
        manifest = self._load_manifest()
        cached_component = _find_exact_component(manifest, request)
        if cached_component is not None and self._component_files_exist(cached_component):
            return EvidenceAcquisitionReport(
                status="cache_hit",
                component=cached_component,
                cached_files=tuple(
                    str(self._resolve_cached_file(cached_file))
                    for cached_file in cached_component.files
                ),
            )

        candidates = self._provider.search(request)
        if not candidates:
            return EvidenceAcquisitionReport(
                status="missing",
                findings=(f"No provider candidates found for {request.role}.",),
            )

        candidate = candidates[0]
        if candidate.datasheet_url is None:
            return EvidenceAcquisitionReport(
                status="missing",
                candidate=candidate,
                findings=(
                    f"Provider candidate {candidate.manufacturer} "
                    f"{candidate.part_number} has no datasheet URL.",
                ),
            )

        return self._download_candidate(manifest, candidate)

    def _download_candidate(
        self,
        manifest: EvidenceManifest,
        candidate: EvidenceSourceCandidate,
    ) -> EvidenceAcquisitionReport:
        assert candidate.datasheet_url is not None
        payload = self._downloader.download(candidate.datasheet_url)
        digest = hashlib.sha256(payload).hexdigest()
        cached_path = self._cache_path_for(candidate, digest)
        cached_path.parent.mkdir(parents=True, exist_ok=True)
        cached_path.write_bytes(payload)

        cached_file = CachedEvidenceFile(
            local_path=_relative_path(cached_path, self._manifest_path.parent),
            sha256=digest,
            source_url=candidate.datasheet_url,
            retrieved_at=self._clock(),
            license_status=candidate.license_status,
        )
        component = ComponentEvidence(
            manufacturer=candidate.manufacturer,
            part_number=candidate.part_number,
            role=candidate.role,
            symbol_id=candidate.symbol_id or "",
            value=candidate.value or candidate.part_number,
            footprint=candidate.footprint,
            files=(cached_file,),
            facts=(),
        )
        self._write_manifest(
            EvidenceManifest(
                schema_id="pcbsmith-evidence-manifest-v1",
                components=(*_without_exact_component(manifest, component), component),
                extraction_jobs=(
                    *_without_same_extraction_job(
                        manifest,
                        local_path=cached_file.local_path,
                        sha256=digest,
                    ),
                    EvidenceExtractionJob(
                        status="pending_extraction",
                        component_manufacturer=candidate.manufacturer,
                        component_part_number=candidate.part_number,
                        role=candidate.role,
                        local_path=cached_file.local_path,
                        sha256=digest,
                        source_url=candidate.datasheet_url,
                        created_at=self._clock(),
                    ),
                ),
            )
        )
        return EvidenceAcquisitionReport(
            status="downloaded",
            component=component,
            candidate=candidate,
            cached_files=(str(cached_path),),
        )

    def _load_manifest(self) -> EvidenceManifest:
        return _load_or_init_manifest(self._manifest_path)

    def _write_manifest(self, manifest: EvidenceManifest) -> None:
        _write_manifest_file(self._manifest_path, manifest)

    def _component_files_exist(self, component: ComponentEvidence) -> bool:
        if not component.files:
            return False
        return all(
            self._resolve_cached_file(cached_file).exists()
            for cached_file in component.files
        )

    def _resolve_cached_file(self, cached_file: CachedEvidenceFile) -> Path:
        return EvidenceCache(
            manifest_path=self._manifest_path,
            manifest=self._load_manifest(),
        ).resolve_cached_file(cached_file)

    def _cache_path_for(self, candidate: EvidenceSourceCandidate, digest: str) -> Path:
        return (
            self._cache_dir
            / "datasheets"
            / f"{_safe_filename(candidate.manufacturer)}-{_safe_filename(candidate.part_number)}"
            f"-{digest[:12]}.pdf"
        ).resolve()


def _find_exact_component(
    manifest: EvidenceManifest,
    request: EvidenceAcquisitionRequest,
) -> ComponentEvidence | None:
    if request.manufacturer is None or request.part_number is None:
        return None
    requested_manufacturer = _normalize_identity(request.manufacturer)
    requested_part = _normalize_identity(request.part_number)
    for component in manifest.components:
        if (
            _normalize_identity(component.manufacturer) == requested_manufacturer
            and _normalize_identity(component.part_number) == requested_part
            and component.role == request.role
        ):
            return component
    return None


def _without_exact_component(
    manifest: EvidenceManifest,
    replacement: ComponentEvidence,
) -> tuple[ComponentEvidence, ...]:
    return tuple(
        component
        for component in manifest.components
        if not (
            _normalize_identity(component.manufacturer)
            == _normalize_identity(replacement.manufacturer)
            and _normalize_identity(component.part_number)
            == _normalize_identity(replacement.part_number)
            and component.role == replacement.role
        )
    )


def _without_same_extraction_job(
    manifest: EvidenceManifest,
    *,
    local_path: str,
    sha256: str,
) -> tuple[EvidenceExtractionJob, ...]:
    return tuple(
        job
        for job in manifest.extraction_jobs
        if not (job.local_path == local_path and job.sha256 == sha256)
    )


def _normalize_identity(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return normalized or "unknown"


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)
