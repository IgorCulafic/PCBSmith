"""Exact-MPN multi-role discovery and safe-intake coverage."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from pcbsmith.evidence.models import EvidenceAcquisitionRequest, EvidenceSourceCandidate
from pcbsmith.evidence.part_discovery import (
    DatasheetEvidenceProviderAdapter,
    ExactPartDiscoveryReport,
    ExactPartDiscoveryRequest,
    ExactPartDiscoveryService,
    InstalledPartResource,
    PartResourceCandidate,
    PartResourceRole,
    PartResourceStatus,
)
from pcbsmith.evidence.source_intake import SourceIntakeService


class Provider:
    def __init__(self, candidates: tuple[PartResourceCandidate, ...]) -> None:
        self.candidates = candidates
        self.requests: list[ExactPartDiscoveryRequest] = []

    def discover(
        self, request: ExactPartDiscoveryRequest
    ) -> tuple[PartResourceCandidate, ...]:
        self.requests.append(request)
        return self.candidates


class ExistingEvidenceProvider:
    def __init__(self) -> None:
        self.requests: list[EvidenceAcquisitionRequest] = []

    def search(
        self, request: EvidenceAcquisitionRequest
    ) -> tuple[EvidenceSourceCandidate, ...]:
        self.requests.append(request)
        return (
            EvidenceSourceCandidate(
                provider="nexar-fixture",
                manufacturer="Example Semiconductor",
                part_number="EX-1234-A",
                role="component",
                source_url="https://example.com/products/ex-1234-a",
                datasheet_url="https://cdn.example.com/ex-1234-a.pdf",
                license_status="local_cache_only",
            ),
        )


class Downloader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def download(self, url: str) -> bytes:
        self.urls.append(url)
        return self.payload


def _request(*roles: PartResourceRole) -> ExactPartDiscoveryRequest:
    return ExactPartDiscoveryRequest(
        manufacturer="Example Semiconductor",
        part_number="EX-1234-A",
        required_roles=roles,
        intended_consumer="project engineering gate",
    )


def _candidate(
    role: PartResourceRole,
    *,
    part_number: str = "EX-1234-A",
    download_url: str | None = "https://example.com/files/resource.pdf",
    expected_kind: str = "pdf",
) -> PartResourceCandidate:
    return PartResourceCandidate(
        provider_id="fixture-provider",
        manufacturer="Example Semiconductor",
        part_number=part_number,
        role=role,
        metadata_url="https://example.com/products/ex-1234-a",
        download_url=download_url,
        approved_hosts=("example.com",),
        expected_kind=expected_kind,
        license_status="local_cache_only",
        revision="A",
    )


def _intake(tmp_path: Path, downloader: Downloader) -> SourceIntakeService:
    return SourceIntakeService(
        private_manifest_path=tmp_path / "private" / "sources.json",
        public_manifest_path=tmp_path / "public" / "sources.json",
        cache_dir=tmp_path / "cache",
        downloader=downloader,
        clock=lambda: "2026-07-22T12:00:00Z",
    )


def test_exact_datasheet_is_retrieved_through_safe_source_intake(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\nfixture"
    downloader = Downloader(payload)
    provider = Provider((_candidate(PartResourceRole.DATASHEET),))
    service = ExactPartDiscoveryService(
        provider=provider,
        source_intake=_intake(tmp_path, downloader),
    )

    report = service.discover(_request(PartResourceRole.DATASHEET))

    assert report.records[0].status is PartResourceStatus.VALIDATED_CACHE
    assert report.records[0].source_sha256 == hashlib.sha256(payload).hexdigest()
    assert report.records[0].revision == "A"
    assert downloader.urls == ["https://example.com/files/resource.pdf"]
    public = (tmp_path / "public" / "sources.json").read_text(encoding="utf-8")
    assert str(tmp_path.resolve()) not in public


def test_fuzzy_or_different_mpn_is_rejected_without_download(tmp_path: Path) -> None:
    downloader = Downloader(b"%PDF-1.7\nwrong")
    service = ExactPartDiscoveryService(
        provider=Provider(
            (_candidate(PartResourceRole.DATASHEET, part_number="EX-1234-B"),)
        ),
        source_intake=_intake(tmp_path, downloader),
    )

    report = service.discover(_request(PartResourceRole.DATASHEET))

    assert report.records[0].status is PartResourceStatus.REJECTED
    assert downloader.urls == []


def test_multiple_exact_candidates_require_explicit_selection(tmp_path: Path) -> None:
    downloader = Downloader(b"%PDF-1.7\nambiguous")
    service = ExactPartDiscoveryService(
        provider=Provider(
            (
                _candidate(PartResourceRole.DATASHEET),
                _candidate(PartResourceRole.DATASHEET).model_copy(
                    update={"provider_id": "second-provider", "revision": "B"}
                ),
            )
        ),
        source_intake=_intake(tmp_path, downloader),
    )

    report = service.discover(_request(PartResourceRole.DATASHEET))

    assert report.records[0].status is PartResourceStatus.REJECTED
    assert "Multiple exact candidates" in report.records[0].findings[0]
    assert downloader.urls == []


def test_existing_nexar_compatible_provider_can_feed_exact_datasheet_discovery() -> None:
    provider = ExistingEvidenceProvider()
    candidates = DatasheetEvidenceProviderAdapter(provider).discover(
        _request(PartResourceRole.DATASHEET, PartResourceRole.MODEL_3D)
    )

    assert provider.requests[0].manufacturer == "Example Semiconductor"
    assert provider.requests[0].part_number == "EX-1234-A"
    assert len(candidates) == 1
    assert candidates[0].role is PartResourceRole.DATASHEET
    assert candidates[0].approved_hosts == ("cdn.example.com", "example.com")


def test_installed_cad_identity_wins_and_located_asset_is_not_called_installed() -> None:
    candidate = _candidate(
        PartResourceRole.MODEL_3D,
        download_url="https://example.com/files/model.step",
        expected_kind="step",
    )
    provider = Provider((candidate,))
    service = ExactPartDiscoveryService(provider=provider)
    located = service.discover(_request(PartResourceRole.MODEL_3D))
    assert located.records[0].status is PartResourceStatus.LOCATED

    installed = InstalledPartResource(
        asset_id="asset:ex-1234-a:model3d",
        manufacturer="Example Semiconductor",
        part_number="EX-1234-A",
        role=PartResourceRole.MODEL_3D,
        installed_asset_sha256="a" * 64,
        installation_record_fingerprint="b" * 64,
    )
    ready = service.discover(
        _request(PartResourceRole.MODEL_3D),
        installed_resources=(installed,),
    )
    assert ready.records[0].status is PartResourceStatus.INSTALLED
    assert ready.records[0].installed_resource == installed


def test_report_exactly_covers_requested_roles_and_rejects_tampering() -> None:
    report = ExactPartDiscoveryService(provider=Provider(())).discover(
        _request(PartResourceRole.DATASHEET, PartResourceRole.ERRATA)
    )
    assert tuple(item.role for item in report.records) == (
        PartResourceRole.DATASHEET,
        PartResourceRole.ERRATA,
    )
    payload = report.model_dump(mode="python")
    payload["provider_search_complete"] = False
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        ExactPartDiscoveryReport(**payload)
