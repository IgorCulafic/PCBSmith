from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcbsmith.evidence import (
    EvidenceAcquisitionRequest,
    EvidenceAcquisitionService,
    EvidenceSourceCandidate,
)


class RecordingProvider:
    def __init__(self, candidates: tuple[EvidenceSourceCandidate, ...]) -> None:
        self.candidates = candidates
        self.requests: list[EvidenceAcquisitionRequest] = []

    def search(
        self,
        request: EvidenceAcquisitionRequest,
    ) -> tuple[EvidenceSourceCandidate, ...]:
        self.requests.append(request)
        return self.candidates


class RecordingDownloader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def download(self, url: str) -> bytes:
        self.urls.append(url)
        return self.payload


def test_acquisition_returns_cache_hit_without_provider_or_downloader(
    tmp_path: Path,
) -> None:
    manifest_path = _write_existing_manifest(tmp_path)
    provider = RecordingProvider(())
    downloader = RecordingDownloader(b"should not download")
    service = EvidenceAcquisitionService(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        provider=provider,
        downloader=downloader,
        clock=lambda: "2026-05-20",
    )

    report = service.acquire(
        EvidenceAcquisitionRequest(
            role="indicator_led",
            query="fixture red led",
            manufacturer="PCBSmith Fixture",
            part_number="FIX-RED-LED-0603-D1",
        )
    )

    assert report.status == "cache_hit"
    assert report.component is not None
    assert report.component.part_number == "FIX-RED-LED-0603-D1"
    assert provider.requests == []
    assert downloader.urls == []


def test_acquisition_reports_missing_when_provider_has_no_candidates(tmp_path: Path) -> None:
    manifest_path = _write_empty_manifest(tmp_path)
    provider = RecordingProvider(())
    downloader = RecordingDownloader(b"should not download")
    service = EvidenceAcquisitionService(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        provider=provider,
        downloader=downloader,
        clock=lambda: "2026-05-20",
    )

    report = service.acquire(EvidenceAcquisitionRequest(role="divider_top", query="10k resistor"))

    assert report.status == "missing"
    assert report.component is None
    assert provider.requests[0].role == "divider_top"
    assert downloader.urls == []
    assert report.findings == ("No provider candidates found for divider_top.",)


def test_acquisition_does_not_download_candidate_without_datasheet_url(tmp_path: Path) -> None:
    manifest_path = _write_empty_manifest(tmp_path)
    provider = RecordingProvider(
        (
            EvidenceSourceCandidate(
                provider="unit-test",
                manufacturer="Example",
                part_number="NO-DATASHEET",
                role="indicator_led",
                source_url="https://example.invalid/no-datasheet",
                datasheet_url=None,
                license_status="metadata_only",
            ),
        )
    )
    downloader = RecordingDownloader(b"should not download")
    service = EvidenceAcquisitionService(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        provider=provider,
        downloader=downloader,
        clock=lambda: "2026-05-20",
    )

    report = service.acquire(EvidenceAcquisitionRequest(role="indicator_led", query="red led"))

    assert report.status == "missing"
    assert downloader.urls == []
    assert report.findings == (
        "Provider candidate Example NO-DATASHEET has no datasheet URL.",
    )


def test_acquisition_downloads_selected_datasheet_and_updates_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = _write_empty_manifest(tmp_path)
    payload = b"%PDF fixture datasheet bytes"
    provider = RecordingProvider(
        (
            EvidenceSourceCandidate(
                provider="unit-test",
                manufacturer="Example",
                part_number="EX-LED-0603",
                role="indicator_led",
                symbol_id="stdlib:LED",
                value="Example red LED",
                footprint="LED_SMD:LED_0603_1608Metric",
                source_url="https://example.invalid/products/ex-led-0603",
                datasheet_url="https://example.invalid/datasheets/ex-led-0603.pdf",
                license_status="local_cache_only",
            ),
        )
    )
    downloader = RecordingDownloader(payload)
    service = EvidenceAcquisitionService(
        manifest_path=manifest_path,
        cache_dir=tmp_path / "cache",
        provider=provider,
        downloader=downloader,
        clock=lambda: "2026-05-20",
    )

    report = service.acquire(EvidenceAcquisitionRequest(role="indicator_led", query="red led"))
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert report.status == "downloaded"
    assert report.component is not None
    assert report.component.facts == ()
    assert downloader.urls == ["https://example.invalid/datasheets/ex-led-0603.pdf"]
    assert len(data["components"]) == 1
    cached_file = Path(data["components"][0]["files"][0]["local_path"])
    cached_path = manifest_path.parent / cached_file
    assert cached_path.exists()
    assert cached_path.read_bytes() == payload
    assert data["components"][0]["files"][0]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert data["components"][0]["files"][0]["source_url"] == (
        "https://example.invalid/datasheets/ex-led-0603.pdf"
    )
    assert data["components"][0]["files"][0]["retrieved_at"] == "2026-05-20"
    assert data["components"][0]["facts"] == []
    assert data["extraction_jobs"] == [
        {
            "status": "pending_extraction",
            "component_manufacturer": "Example",
            "component_part_number": "EX-LED-0603",
            "role": "indicator_led",
            "local_path": data["components"][0]["files"][0]["local_path"],
            "sha256": hashlib.sha256(payload).hexdigest(),
            "source_url": "https://example.invalid/datasheets/ex-led-0603.pdf",
            "created_at": "2026-05-20",
            "findings": [],
        }
    ]

    second_report = service.acquire(
        EvidenceAcquisitionRequest(
            role="indicator_led",
            query="red led",
            manufacturer="Example",
            part_number="EX-LED-0603",
        )
    )

    assert second_report.status == "cache_hit"
    assert downloader.urls == ["https://example.invalid/datasheets/ex-led-0603.pdf"]


def _write_empty_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schema": "pcbsmith-evidence-manifest-v1", "components": []}),
        encoding="utf-8",
    )
    return manifest_path


def _write_existing_manifest(tmp_path: Path) -> Path:
    cached_file = tmp_path / "fixture-passives-led.txt"
    cached_file.write_text("fixture", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-evidence-manifest-v1",
                "components": [
                    {
                        "manufacturer": "PCBSmith Fixture",
                        "part_number": "FIX-RED-LED-0603-D1",
                        "role": "indicator_led",
                        "symbol_id": "stdlib:LED",
                        "value": "Fixture red LED",
                        "footprint": "LED_SMD:LED_0603_1608Metric",
                        "files": [
                            {
                                "local_path": "fixture-passives-led.txt",
                                "sha256": hashlib.sha256(b"fixture").hexdigest(),
                                "source_url": "fixture://passives-led",
                                "retrieved_at": "2026-05-19",
                                "license_status": "test_fixture_only",
                            }
                        ],
                        "facts": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path
