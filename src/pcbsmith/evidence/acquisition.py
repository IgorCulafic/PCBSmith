from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Protocol
from urllib import error, request

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
    ) -> tuple[EvidenceSourceCandidate, ...]: ...


class EvidenceDownloader(Protocol):
    def download(self, url: str) -> bytes: ...


@dataclass(frozen=True)
class DownloadAttempt:
    attempt: int
    header_profile: str
    outcome: str
    status_code: int | None = None
    error_type: str | None = None
    retry_after: str | None = None
    scheduled_delay_seconds: float | None = None


@dataclass(frozen=True)
class SourceDownloadResult:
    payload: bytes
    final_url: str
    attempts: tuple[DownloadAttempt, ...]
    content_disposition: str | None = None


class EvidenceDownloadError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempts: tuple[DownloadAttempt, ...] = (),
        final_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.final_url = final_url


class UrlLibEvidenceDownloader:
    _RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        max_attempts: int = 1,
        retry_delay_seconds: float = 1.0,
        max_retry_delay_seconds: float = 30.0,
        browser_fallback: bool = True,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if retry_delay_seconds < 0 or max_retry_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._max_retry_delay_seconds = max_retry_delay_seconds
        self._browser_fallback = browser_fallback
        self._sleeper = sleeper

    def download(self, url: str) -> bytes:
        return self.download_with_metadata(url).payload

    def download_with_metadata(self, url: str) -> SourceDownloadResult:
        attempts: list[DownloadAttempt] = []
        last_final_url: str | None = None
        for attempt_number in range(1, self._max_attempts + 1):
            profile = self._header_profile(attempt_number)
            http_request = request.Request(url, headers=self._headers(profile))
            try:
                with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                    payload = response.read()
                    final_url = response.geturl()
                    last_final_url = final_url
                    status_code = getattr(response, "status", None)
                    content_disposition = response.headers.get("Content-Disposition")
            except error.HTTPError as exc:
                retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
                retryable = exc.code in self._RETRYABLE_HTTP_STATUS
                delay: float | None = None
                if retryable:
                    delay = self._retry_delay(attempt_number, retry_after)
                attempts.append(
                    DownloadAttempt(
                        attempt=attempt_number,
                        header_profile=profile,
                        outcome="retryable_error" if retryable else "terminal_error",
                        status_code=exc.code,
                        error_type=type(exc).__name__,
                        retry_after=retry_after,
                        scheduled_delay_seconds=(
                            delay if retryable and attempt_number < self._max_attempts else None
                        ),
                    )
                )
                if retryable and attempt_number < self._max_attempts:
                    assert delay is not None
                    self._sleeper(delay)
                    continue
                raise EvidenceDownloadError(
                    f"Datasheet download failed with HTTP {exc.code}: {exc.reason}",
                    attempts=tuple(attempts),
                    final_url=last_final_url,
                ) from exc
            except (OSError, TimeoutError) as exc:
                delay = self._retry_delay(attempt_number, None)
                attempts.append(
                    DownloadAttempt(
                        attempt=attempt_number,
                        header_profile=profile,
                        outcome="retryable_error",
                        error_type=type(exc).__name__,
                        scheduled_delay_seconds=(
                            delay if attempt_number < self._max_attempts else None
                        ),
                    )
                )
                if attempt_number < self._max_attempts:
                    self._sleeper(delay)
                    continue
                raise EvidenceDownloadError(
                    f"Datasheet download failed: {exc}",
                    attempts=tuple(attempts),
                    final_url=last_final_url,
                ) from exc

            if not isinstance(payload, bytes) or not payload:
                attempts.append(
                    DownloadAttempt(
                        attempt=attempt_number,
                        header_profile=profile,
                        outcome="terminal_error",
                        status_code=status_code,
                        error_type="EmptyPayload",
                    )
                )
                raise EvidenceDownloadError(
                    "Datasheet download returned no data.",
                    attempts=tuple(attempts),
                    final_url=final_url,
                )
            attempts.append(
                DownloadAttempt(
                    attempt=attempt_number,
                    header_profile=profile,
                    outcome="success",
                    status_code=status_code,
                )
            )
            return SourceDownloadResult(
                payload=payload,
                final_url=final_url,
                attempts=tuple(attempts),
                content_disposition=content_disposition,
            )
        raise AssertionError("download attempt loop exited without a result")

    def _header_profile(self, attempt_number: int) -> str:
        if (
            self._browser_fallback
            and self._max_attempts > 1
            and attempt_number == self._max_attempts
        ):
            return "browser-compatible"
        return "pcbsmith"

    @staticmethod
    def _headers(profile: str) -> dict[str, str]:
        if profile == "browser-compatible":
            return {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
                ),
                "Accept": "application/pdf,application/zip,application/octet-stream,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "close",
            }
        return {
            "User-Agent": "pcbsmith-evidence/0.2",
            "Accept": "application/pdf,application/zip,application/octet-stream,*/*;q=0.8",
            "Connection": "close",
        }

    def _retry_delay(self, attempt_number: int, retry_after: str | None) -> float:
        exponential = self._retry_delay_seconds * (2.0 ** (attempt_number - 1))
        requested = _retry_after_seconds(retry_after)
        delay = max(exponential, requested or 0.0)
        return min(delay, self._max_retry_delay_seconds)


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value.strip())
    except ValueError:
        return None
    return max(parsed, 0.0)


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
                    manufacturer=manufacturer,
                    part_number=part_number,
                    role=role,
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
                        manufacturer=candidate.manufacturer,
                        part_number=candidate.part_number,
                        role=candidate.role,
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
            self._resolve_cached_file(cached_file).exists() for cached_file in component.files
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
    manufacturer: str,
    part_number: str,
    role: str,
) -> tuple[EvidenceExtractionJob, ...]:
    return tuple(
        job
        for job in manifest.extraction_jobs
        if not (
            _normalize_identity(job.component_manufacturer) == _normalize_identity(manufacturer)
            and _normalize_identity(job.component_part_number) == _normalize_identity(part_number)
            and job.role == role
        )
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
