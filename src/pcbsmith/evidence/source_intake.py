"""Local-first intake for documents and CAD assets.

This module deliberately separates the private cache record from the
redistributable metadata projection.  It downloads only an explicitly approved
HTTPS URL whose host is on the request allow-list, validates the payload before
writing it, and records typed blocked/failure states instead of calling every
absence "missing".
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pcbsmith.evidence.acquisition import DownloadAttempt, SourceDownloadResult

SourceKind = Literal["pdf", "zip", "step", "vrml", "text", "binary"]
LicenseStatus = Literal[
    "redistributable",
    "local_cache_only",
    "metadata_only",
    "unknown",
]
IntakeStatus = Literal["cache_hit", "downloaded", "blocked", "failed"]
BlockedReason = Literal[
    "host_not_approved",
    "insecure_url",
    "network_error",
    "authentication_required",
    "license_not_approved",
    "identity_mismatch",
    "empty_payload",
]


class SourceDownloader(Protocol):
    def download(self, url: str) -> bytes: ...


class SourceIntakeRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    source_url: str
    approved_hosts: tuple[str, ...] = Field(min_length=1)
    intended_consumer: str = Field(min_length=1)
    expected_kind: SourceKind
    license_status: LicenseStatus
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_archive_members: tuple[str, ...] = ()

    @field_validator("approved_hosts")
    @classmethod
    def normalize_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({host.strip().lower().rstrip(".") for host in value}))
        if any(not host or "/" in host for host in normalized):
            raise ValueError("approved hosts must be bare DNS host names")
        return normalized


class SourceIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: SourceKind
    byte_count: int = Field(gt=0)
    archive_members: tuple[str, ...] = ()


class RetrievalAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt: int = Field(ge=1)
    header_profile: str
    outcome: str
    status_code: int | None = None
    error_type: str | None = None
    retry_after: str | None = None
    scheduled_delay_seconds: float | None = Field(default=None, ge=0)


class RetrievalTelemetry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    final_url: str | None = None
    attempt_count: int = Field(ge=1)
    attempts: tuple[RetrievalAttempt, ...]
    content_disposition: str | None = None


class PrivateSourceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    status: IntakeStatus
    source_url: str
    intended_consumer: str
    license_status: LicenseStatus
    retrieved_at: str | None = None
    local_path: str | None = None
    identity: SourceIdentity | None = None
    blocked_reason: BlockedReason | None = None
    findings: tuple[str, ...] = ()
    retrieval: RetrievalTelemetry | None = None


class PublicSourceRecord(BaseModel):
    """Safe committed projection: no local cache path and no source payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    status: IntakeStatus
    source_url: str
    intended_consumer: str
    license_status: LicenseStatus
    retrieved_at: str | None = None
    identity: SourceIdentity | None = None
    blocked_reason: BlockedReason | None = None
    findings: tuple[str, ...] = ()
    retrieval: RetrievalTelemetry | None = None


class PrivateSourceManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-private-source-intake-v1", "pcbsmith-private-source-intake-v2"] = (
        Field(
            default="pcbsmith-private-source-intake-v2",
            validation_alias="schema",
            serialization_alias="schema",
        )
    )
    records: tuple[PrivateSourceRecord, ...] = ()


class PublicSourceManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-source-intake-v1", "pcbsmith-source-intake-v2"] = Field(
        default="pcbsmith-source-intake-v2", validation_alias="schema", serialization_alias="schema"
    )
    records: tuple[PublicSourceRecord, ...] = ()


class SourceIntakeBatchReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[PrivateSourceRecord, ...]
    cache_hits: int = Field(ge=0)
    downloaded: int = Field(ge=0)
    blocked: int = Field(ge=0)
    failed: int = Field(ge=0)

    @property
    def successful(self) -> bool:
        return self.blocked == 0 and self.failed == 0


class SourceIntakeService:
    def __init__(
        self,
        *,
        private_manifest_path: Path,
        public_manifest_path: Path,
        cache_dir: Path,
        downloader: SourceDownloader,
        clock: Callable[[], str],
    ) -> None:
        self._private_manifest_path = private_manifest_path.resolve()
        self._public_manifest_path = public_manifest_path.resolve()
        self._cache_dir = cache_dir.resolve()
        self._downloader = downloader
        self._clock = clock

    def acquire(self, intake: SourceIntakeRequest) -> PrivateSourceRecord:
        prior = self._find_record(intake.source_id)
        if prior is not None and self._cached_record_is_valid(prior, intake):
            cached = prior.model_copy(update={"status": "cache_hit"})
            self._store(cached)
            return cached

        blocked = _preflight_request(intake)
        if blocked is not None:
            self._store(blocked)
            return blocked

        retrieval: RetrievalTelemetry | None = None
        try:
            payload, retrieval = self._download(intake.source_url)
        except Exception as exc:  # downloader boundaries are intentionally normalized
            retrieval = _telemetry_from_exception(exc)
            reason = _blocked_reason_from_exception(exc)
            finding = (
                "The approved source requires authentication or denied automated access."
                if reason == "authentication_required"
                else f"Download failed: {type(exc).__name__}: {exc}"
            )
            record = _blocked_record(
                intake,
                reason=reason,
                finding=finding,
                retrieval=retrieval,
            )
            self._store(record)
            return record

        if retrieval is not None and retrieval.final_url is not None:
            redirected_block = _preflight_url(
                retrieval.final_url,
                approved_hosts=intake.approved_hosts,
                label="Final redirected source",
            )
            if redirected_block is not None:
                reason, finding = redirected_block
                record = _blocked_record(
                    intake,
                    reason=reason,
                    finding=finding,
                    retrieval=retrieval,
                )
                self._store(record)
                return record

        if not payload:
            record = _blocked_record(
                intake,
                reason="empty_payload",
                finding="The approved source returned an empty payload.",
                retrieval=retrieval,
            )
            self._store(record)
            return record

        try:
            identity = inspect_source_payload(payload, expected_kind=intake.expected_kind)
            _validate_expected_identity(identity, intake)
        except ValueError as exc:
            record = _blocked_record(
                intake,
                reason="identity_mismatch",
                finding=str(exc),
                status="failed",
                retrieval=retrieval,
            )
            self._store(record)
            return record

        destination = self._cache_path(intake, identity)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        record = PrivateSourceRecord(
            source_id=intake.source_id,
            status="downloaded",
            source_url=intake.source_url,
            intended_consumer=intake.intended_consumer,
            license_status=intake.license_status,
            retrieved_at=self._clock(),
            local_path=str(destination),
            identity=identity,
            retrieval=retrieval,
        )
        self._store(record)
        return record

    def acquire_many(
        self,
        intakes: tuple[SourceIntakeRequest, ...],
    ) -> SourceIntakeBatchReport:
        records = tuple(self.acquire(intake) for intake in intakes)
        return SourceIntakeBatchReport(
            records=records,
            cache_hits=sum(record.status == "cache_hit" for record in records),
            downloaded=sum(record.status == "downloaded" for record in records),
            blocked=sum(record.status == "blocked" for record in records),
            failed=sum(record.status == "failed" for record in records),
        )

    def _download(self, url: str) -> tuple[bytes, RetrievalTelemetry | None]:
        metadata_download = getattr(self._downloader, "download_with_metadata", None)
        if callable(metadata_download):
            result = metadata_download(url)
            if not isinstance(result, SourceDownloadResult):
                raise TypeError("download_with_metadata must return SourceDownloadResult")
            return result.payload, _telemetry_from_result(result)
        return self._downloader.download(url), None

    def _find_record(self, source_id: str) -> PrivateSourceRecord | None:
        manifest = self._load_private()
        return next((record for record in manifest.records if record.source_id == source_id), None)

    def _cached_record_is_valid(
        self,
        record: PrivateSourceRecord,
        intake: SourceIntakeRequest,
    ) -> bool:
        if record.local_path is None or record.identity is None:
            return False
        path = Path(record.local_path)
        if not path.exists():
            return False
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != record.identity.sha256:
            return False
        if intake.expected_sha256 is not None and digest != intake.expected_sha256:
            return False
        identity = inspect_source_payload(payload, expected_kind=intake.expected_kind)
        return identity == record.identity

    def _cache_path(self, intake: SourceIntakeRequest, identity: SourceIdentity) -> Path:
        suffix = {
            "pdf": ".pdf",
            "zip": ".zip",
            "step": ".step",
            "vrml": ".wrl",
            "text": ".txt",
            "binary": ".bin",
        }[identity.kind]
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", intake.source_id).strip("-.")
        return self._cache_dir / f"{name}-{identity.sha256[:12]}{suffix}"

    def _load_private(self) -> PrivateSourceManifest:
        if not self._private_manifest_path.exists():
            return PrivateSourceManifest(schema_id="pcbsmith-private-source-intake-v2")
        return PrivateSourceManifest.model_validate_json(
            self._private_manifest_path.read_text(encoding="utf-8")
        )

    def _store(self, replacement: PrivateSourceRecord) -> None:
        current = self._load_private()
        records = tuple(
            sorted(
                (
                    *(
                        record
                        for record in current.records
                        if record.source_id != replacement.source_id
                    ),
                    replacement,
                ),
                key=lambda record: record.source_id,
            )
        )
        _write_json(
            self._private_manifest_path,
            PrivateSourceManifest(
                schema_id="pcbsmith-private-source-intake-v2",
                records=records,
            ),
        )
        public_records = tuple(
            PublicSourceRecord(**record.model_dump(exclude={"local_path"})) for record in records
        )
        _write_json(
            self._public_manifest_path,
            PublicSourceManifest(
                schema_id="pcbsmith-source-intake-v2",
                records=public_records,
            ),
        )


def inspect_source_payload(payload: bytes, *, expected_kind: SourceKind) -> SourceIdentity:
    actual_kind = _detect_kind(payload)
    if expected_kind != "binary" and actual_kind != expected_kind:
        raise ValueError(f"Expected {expected_kind} content but detected {actual_kind}.")
    archive_members: tuple[str, ...] = ()
    if actual_kind == "zip":
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                archive_members = tuple(sorted(item.filename for item in archive.infolist()))
                bad_member = archive.testzip()
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValueError(f"ZIP archive identity check failed: {exc}") from exc
        if bad_member is not None:
            raise ValueError(f"ZIP archive has a corrupt member: {bad_member}")
    return SourceIdentity(
        sha256=hashlib.sha256(payload).hexdigest(),
        kind=actual_kind,
        byte_count=len(payload),
        archive_members=archive_members,
    )


def _detect_kind(payload: bytes) -> SourceKind:
    prefix = payload[:4096].lstrip()
    if prefix.startswith(b"%PDF-"):
        return "pdf"
    if payload.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    upper = prefix.upper()
    if upper.startswith(b"ISO-10303-21"):
        return "step"
    if upper.startswith(b"#VRML"):
        return "vrml"
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "text"


def _preflight_request(intake: SourceIntakeRequest) -> PrivateSourceRecord | None:
    url_block = _preflight_url(
        intake.source_url,
        approved_hosts=intake.approved_hosts,
        label="Source",
    )
    if url_block is not None:
        reason, finding = url_block
        return _blocked_record(
            intake,
            reason=reason,
            finding=finding,
        )
    if intake.license_status == "unknown":
        return _blocked_record(
            intake,
            reason="license_not_approved",
            finding="Automatic intake requires an explicit license/cache disposition.",
        )
    return None


def _preflight_url(
    url: str,
    *,
    approved_hosts: tuple[str, ...],
    label: str,
) -> tuple[BlockedReason, str] | None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        return "insecure_url", f"{label} must use HTTPS."
    host = (parsed.hostname or "").lower().rstrip(".")
    approved = any(host == root or host.endswith(f".{root}") for root in approved_hosts)
    if not approved:
        return (
            "host_not_approved",
            f"{label} host {host or '<missing>'!r} is not in the approved host set.",
        )
    return None


def _validate_expected_identity(
    identity: SourceIdentity,
    intake: SourceIntakeRequest,
) -> None:
    if intake.expected_sha256 is not None and identity.sha256 != intake.expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch: expected {intake.expected_sha256}, got {identity.sha256}."
        )
    missing_members = tuple(
        member
        for member in intake.expected_archive_members
        if member not in identity.archive_members
    )
    if missing_members:
        raise ValueError(f"Archive is missing expected members: {', '.join(missing_members)}")


def _blocked_record(
    intake: SourceIntakeRequest,
    *,
    reason: BlockedReason,
    finding: str,
    status: IntakeStatus = "blocked",
    retrieval: RetrievalTelemetry | None = None,
) -> PrivateSourceRecord:
    return PrivateSourceRecord(
        source_id=intake.source_id,
        status=status,
        source_url=intake.source_url,
        intended_consumer=intake.intended_consumer,
        license_status=intake.license_status,
        blocked_reason=reason,
        findings=(finding,),
        retrieval=retrieval,
    )


def _telemetry_from_result(result: SourceDownloadResult) -> RetrievalTelemetry:
    return RetrievalTelemetry(
        final_url=result.final_url,
        attempt_count=len(result.attempts),
        attempts=tuple(_attempt_model(attempt) for attempt in result.attempts),
        content_disposition=result.content_disposition,
    )


def _telemetry_from_exception(exc: Exception) -> RetrievalTelemetry | None:
    raw_attempts = getattr(exc, "attempts", ())
    if not isinstance(raw_attempts, tuple) or not raw_attempts:
        return None
    if not all(isinstance(attempt, DownloadAttempt) for attempt in raw_attempts):
        return None
    final_url = getattr(exc, "final_url", None)
    return RetrievalTelemetry(
        final_url=final_url if isinstance(final_url, str) else None,
        attempt_count=len(raw_attempts),
        attempts=tuple(_attempt_model(attempt) for attempt in raw_attempts),
    )


def _blocked_reason_from_exception(exc: Exception) -> BlockedReason:
    raw_attempts = getattr(exc, "attempts", ())
    if isinstance(raw_attempts, tuple) and raw_attempts:
        last_attempt = raw_attempts[-1]
        if isinstance(last_attempt, DownloadAttempt) and last_attempt.status_code in {401, 403}:
            return "authentication_required"
    return "network_error"


def _attempt_model(attempt: DownloadAttempt) -> RetrievalAttempt:
    return RetrievalAttempt(
        attempt=attempt.attempt,
        header_profile=attempt.header_profile,
        outcome=attempt.outcome,
        status_code=attempt.status_code,
        error_type=attempt.error_type,
        retry_after=attempt.retry_after,
        scheduled_delay_seconds=attempt.scheduled_delay_seconds,
    )


def _write_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_dump(mode="json", by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )
