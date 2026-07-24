"""Exact-MPN document and KiCad-resource discovery over the safe intake boundary."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, cast
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pcbsmith.evidence.acquisition import EvidenceProvider
from pcbsmith.evidence.models import EvidenceAcquisitionRequest
from pcbsmith.evidence.source_intake import (
    LicenseStatus,
    SourceIntakeRequest,
    SourceIntakeService,
    SourceKind,
)

if TYPE_CHECKING:
    from pcbsmith.kicad.asset_install import InstalledKiCadAsset


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identity(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._:-]+", "-", value).strip("-.")


class PartResourceRole(StrEnum):
    DATASHEET = "datasheet"
    ERRATA = "errata"
    HARDWARE_GUIDE = "hardware_guide"
    PACKAGE_DRAWING = "package_drawing"
    REFERENCE_DESIGN = "reference_design"
    SIMULATION_MODEL = "simulation_model"
    KICAD_SYMBOL = "kicad_symbol"
    KICAD_FOOTPRINT = "kicad_footprint"
    MODEL_3D = "model_3d"


INSTALL_REQUIRED_ROLES = frozenset(
    {
        PartResourceRole.KICAD_SYMBOL,
        PartResourceRole.KICAD_FOOTPRINT,
        PartResourceRole.MODEL_3D,
    }
)


class PartResourceStatus(StrEnum):
    INSTALLED = "installed"
    VALIDATED_CACHE = "validated_cache"
    LOCATED = "located"
    BLOCKED = "blocked"
    MISSING = "missing"
    REJECTED = "rejected"


class ExactPartDiscoveryRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manufacturer: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    required_roles: tuple[PartResourceRole, ...] = Field(min_length=1)
    intended_consumer: str = Field(min_length=1)

    @field_validator("required_roles")
    @classmethod
    def roles_are_canonical(
        cls, value: tuple[PartResourceRole, ...]
    ) -> tuple[PartResourceRole, ...]:
        canonical = tuple(sorted(set(value), key=lambda item: item.value))
        if len(canonical) != len(value):
            raise ValueError("required part-resource roles must be unique")
        return canonical


class PartResourceCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    role: PartResourceRole
    metadata_url: str
    download_url: str | None
    approved_hosts: tuple[str, ...] = Field(min_length=1)
    expected_kind: SourceKind
    license_status: LicenseStatus
    revision: str | None = None
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_archive_members: tuple[str, ...] = ()

    @field_validator("approved_hosts")
    @classmethod
    def hosts_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        canonical = tuple(sorted({item.strip().lower().rstrip(".") for item in value}))
        if not canonical or any(not item or "/" in item for item in canonical):
            raise ValueError("approved hosts must be non-empty bare DNS names")
        return canonical


class InstalledPartResource(BaseModel):
    """Public installed-asset identity; it never carries a private local path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    role: PartResourceRole
    installed_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    installation_record_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str | None = None

    @model_validator(mode="after")
    def role_requires_installation(self) -> Self:
        if self.role not in INSTALL_REQUIRED_ROLES:
            raise ValueError("installed part resources are only CAD installation records")
        return self


class PartResourceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: PartResourceRole
    status: PartResourceStatus
    provider_id: str | None = None
    metadata_url: str | None = None
    source_url: str | None = None
    source_id: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    revision: str | None = None
    installed_resource: InstalledPartResource | None = None
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def status_has_matching_evidence(self) -> Self:
        if self.status is PartResourceStatus.INSTALLED:
            if self.installed_resource is None or self.installed_resource.role is not self.role:
                raise ValueError("installed status requires a matching installation record")
        elif self.installed_resource is not None:
            raise ValueError("non-installed resource cannot retain installation evidence")
        if self.status is PartResourceStatus.VALIDATED_CACHE and (
            self.source_id is None or self.source_sha256 is None
        ):
            raise ValueError("validated cache status requires source identity and SHA-256")
        return self


class ExactPartDiscoveryReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-exact-part-discovery-report"] = (
        "pcbsmith-exact-part-discovery-report"
    )
    schema_version: Literal[1] = 1
    request: ExactPartDiscoveryRequest
    provider_search_complete: bool
    records: tuple[PartResourceRecord, ...]
    report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def report_is_complete_and_replay_bound(self) -> Self:
        records = tuple(sorted(self.records, key=lambda item: item.role.value))
        if tuple(item.role for item in records) != self.request.required_roles:
            raise ValueError("discovery records must exactly cover every requested role")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != _fingerprint(payload):
            raise ValueError("exact-part discovery report fingerprint is stale")
        object.__setattr__(self, "records", records)
        return self

    @classmethod
    def build(
        cls,
        *,
        request: ExactPartDiscoveryRequest,
        provider_search_complete: bool,
        records: tuple[PartResourceRecord, ...],
    ) -> ExactPartDiscoveryReport:
        canonical_records = tuple(sorted(records, key=lambda item: item.role.value))
        provisional = cls.model_construct(
            request=request,
            provider_search_complete=provider_search_complete,
            records=canonical_records,
            report_fingerprint="0" * 64,
        )
        payload = provisional.model_dump(mode="json", exclude={"report_fingerprint"})
        return cls(
            request=request,
            provider_search_complete=provider_search_complete,
            records=canonical_records,
            report_fingerprint=_fingerprint(payload),
        )


class PartResourceProvider(Protocol):
    def discover(
        self, request: ExactPartDiscoveryRequest
    ) -> tuple[PartResourceCandidate, ...]: ...


class CatalogPartResourceProvider:
    """Deterministic provider for API/exported candidate catalogs."""

    def __init__(self, candidates: tuple[PartResourceCandidate, ...]) -> None:
        self._candidates = tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.role.value,
                    item.provider_id,
                    item.metadata_url,
                    item.download_url or "",
                ),
            )
        )

    def discover(
        self, request: ExactPartDiscoveryRequest
    ) -> tuple[PartResourceCandidate, ...]:
        return self._candidates


class DatasheetEvidenceProviderAdapter:
    """Expose an existing Nexar-compatible evidence provider as exact-part discovery."""

    def __init__(self, provider: EvidenceProvider) -> None:
        self._provider = provider

    def discover(
        self, request: ExactPartDiscoveryRequest
    ) -> tuple[PartResourceCandidate, ...]:
        if PartResourceRole.DATASHEET not in request.required_roles:
            return ()
        candidates = self._provider.search(
            EvidenceAcquisitionRequest(
                role="component",
                query=f"{request.manufacturer} {request.part_number}",
                manufacturer=request.manufacturer,
                part_number=request.part_number,
            )
        )
        results: list[PartResourceCandidate] = []
        for candidate in candidates:
            hosts = {
                parsed.hostname
                for url in (candidate.source_url, candidate.datasheet_url)
                if url is not None
                for parsed in (urlparse(url),)
                if parsed.hostname is not None
            }
            if not hosts:
                continue
            license_status: LicenseStatus = (
                cast(LicenseStatus, candidate.license_status)
                if candidate.license_status
                in {"redistributable", "local_cache_only", "metadata_only", "unknown"}
                else "unknown"
            )
            results.append(
                PartResourceCandidate(
                    provider_id=candidate.provider,
                    manufacturer=candidate.manufacturer,
                    part_number=candidate.part_number,
                    role=PartResourceRole.DATASHEET,
                    metadata_url=candidate.source_url,
                    download_url=candidate.datasheet_url,
                    approved_hosts=tuple(hosts),
                    expected_kind="pdf",
                    license_status=license_status,
                )
            )
        return tuple(results)


class ExactPartDiscoveryService:
    """Discover exact identities and optionally retrieve them through source intake."""

    def __init__(
        self,
        *,
        provider: PartResourceProvider,
        source_intake: SourceIntakeService | None = None,
    ) -> None:
        self._provider = provider
        self._source_intake = source_intake

    def discover(
        self,
        request: ExactPartDiscoveryRequest,
        *,
        installed_resources: tuple[InstalledPartResource, ...] = (),
    ) -> ExactPartDiscoveryReport:
        candidates = self._provider.discover(request)
        records = tuple(
            self._resolve_role(request, role, candidates, installed_resources)
            for role in request.required_roles
        )
        return ExactPartDiscoveryReport.build(
            request=request,
            provider_search_complete=True,
            records=records,
        )

    def _resolve_role(
        self,
        request: ExactPartDiscoveryRequest,
        role: PartResourceRole,
        candidates: tuple[PartResourceCandidate, ...],
        installed_resources: tuple[InstalledPartResource, ...],
    ) -> PartResourceRecord:
        installed = next(
            (
                item
                for item in installed_resources
                if item.role is role
                and _identity(item.manufacturer) == _identity(request.manufacturer)
                and _identity(item.part_number) == _identity(request.part_number)
            ),
            None,
        )
        if installed is not None:
            return PartResourceRecord(
                role=role,
                status=PartResourceStatus.INSTALLED,
                installed_resource=installed,
                revision=installed.source_revision,
            )

        role_candidates = tuple(item for item in candidates if item.role is role)
        exact = tuple(
            item
            for item in role_candidates
            if _identity(item.manufacturer) == _identity(request.manufacturer)
            and _identity(item.part_number) == _identity(request.part_number)
        )
        if not exact:
            status = (
                PartResourceStatus.REJECTED
                if role_candidates
                else PartResourceStatus.MISSING
            )
            finding = (
                "Provider candidates did not match the exact manufacturer and MPN."
                if role_candidates
                else "No provider candidate was returned for the required role."
            )
            return PartResourceRecord(role=role, status=status, findings=(finding,))
        if len(exact) > 1:
            return PartResourceRecord(
                role=role,
                status=PartResourceStatus.REJECTED,
                findings=(
                    "Multiple exact candidates require an explicit provider/revision selection.",
                ),
            )
        candidate = exact[0]
        base = {
            "role": role,
            "provider_id": candidate.provider_id,
            "metadata_url": candidate.metadata_url,
            "source_url": candidate.download_url,
            "revision": candidate.revision,
        }
        if candidate.download_url is None or self._source_intake is None:
            return PartResourceRecord(**base, status=PartResourceStatus.LOCATED)
        source_id = _safe_id(
            f"part:{request.manufacturer}:{request.part_number}:{role.value}"
        )
        intake_record = self._source_intake.acquire(
            SourceIntakeRequest(
                source_id=source_id,
                source_url=candidate.download_url,
                approved_hosts=candidate.approved_hosts,
                intended_consumer=request.intended_consumer,
                expected_kind=candidate.expected_kind,
                license_status=candidate.license_status,
                expected_sha256=candidate.expected_sha256,
                expected_archive_members=candidate.expected_archive_members,
            )
        )
        if intake_record.status in {"downloaded", "cache_hit"}:
            assert intake_record.identity is not None
            return PartResourceRecord(
                **base,
                status=PartResourceStatus.VALIDATED_CACHE,
                source_id=source_id,
                source_sha256=intake_record.identity.sha256,
            )
        return PartResourceRecord(
            **base,
            status=PartResourceStatus.BLOCKED,
            source_id=source_id,
            findings=intake_record.findings,
        )


def installed_part_resource_from_asset(
    *,
    manufacturer: str,
    part_number: str,
    role: PartResourceRole,
    asset: InstalledKiCadAsset,
) -> InstalledPartResource:
    """Bind an installed KiCad asset to an exact part without retaining private paths."""

    expected_kind = {
        PartResourceRole.KICAD_SYMBOL: "symbol",
        PartResourceRole.KICAD_FOOTPRINT: "footprint",
        PartResourceRole.MODEL_3D: "model",
    }.get(role)
    if expected_kind is None:
        raise ValueError("only KiCad CAD roles can bind installed assets")
    if asset.kind != expected_kind:
        raise ValueError("installed KiCad asset kind does not match the requested role")
    if asset.part_number is None or _identity(asset.part_number) != _identity(part_number):
        raise ValueError("installed KiCad asset lacks matching exact-MPN identity")
    public_payload = asset.model_dump(mode="json", exclude={"local_path"})
    registry = public_payload.get("model_registry_entry")
    if isinstance(registry, dict):
        registry.pop("local_path", None)
    return InstalledPartResource(
        asset_id=asset.asset_id,
        manufacturer=manufacturer,
        part_number=part_number,
        role=role,
        installed_asset_sha256=asset.sha256,
        installation_record_fingerprint=_fingerprint(public_payload),
        source_revision=asset.source_revision,
    )
