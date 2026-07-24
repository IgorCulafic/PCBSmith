from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

from pcbsmith.evidence.acquisition import (
    DownloadAttempt,
    EvidenceDownloadError,
    SourceDownloadResult,
)
from pcbsmith.evidence.source_intake import SourceIntakeRequest, SourceIntakeService


class Downloader:
    def __init__(self, payload: bytes | Exception) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def download(self, url: str) -> bytes:
        self.urls.append(url)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class MetadataDownloader:
    def __init__(self, result: SourceDownloadResult) -> None:
        self.result = result
        self.urls: list[str] = []

    def download(self, url: str) -> bytes:
        raise AssertionError("metadata-aware download should be preferred")

    def download_with_metadata(self, url: str) -> SourceDownloadResult:
        self.urls.append(url)
        return self.result


def _service(
    tmp_path: Path,
    downloader: Downloader | MetadataDownloader,
) -> SourceIntakeService:
    return SourceIntakeService(
        private_manifest_path=tmp_path / "private" / "sources.json",
        public_manifest_path=tmp_path / "committed" / "sources.json",
        cache_dir=tmp_path / "cache",
        downloader=downloader,
        clock=lambda: "2026-07-20T12:00:00Z",
    )


def _request(**changes: object) -> SourceIntakeRequest:
    values: dict[str, object] = {
        "source_id": "sensirion-sht-guide-v2",
        "source_url": "https://sensirion.com/media/documents/guide.pdf",
        "approved_hosts": ("sensirion.com",),
        "intended_consumer": "sensor placement advisory",
        "expected_kind": "pdf",
        "license_status": "local_cache_only",
    }
    values.update(changes)
    return SourceIntakeRequest(**values)


def test_downloads_only_approved_content_and_writes_redacted_projection(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\nfixture"
    downloader = Downloader(payload)
    service = _service(tmp_path, downloader)

    record = service.acquire(_request())
    private = json.loads((tmp_path / "private" / "sources.json").read_text("utf-8"))
    public = json.loads((tmp_path / "committed" / "sources.json").read_text("utf-8"))

    assert record.status == "downloaded"
    assert record.identity is not None
    assert record.identity.sha256 == hashlib.sha256(payload).hexdigest()
    assert Path(record.local_path or "").read_bytes() == payload
    assert "local_path" in private["records"][0]
    assert "local_path" not in public["records"][0]
    assert public["records"][0]["intended_consumer"] == "sensor placement advisory"


def test_cache_hit_revalidates_bytes_without_downloading(tmp_path: Path) -> None:
    first = Downloader(b"%PDF-1.7\nfixture")
    service = _service(tmp_path, first)
    service.acquire(_request())

    second = Downloader(AssertionError("download should not run"))
    cached = _service(tmp_path, second).acquire(_request())

    assert cached.status == "cache_hit"
    assert second.urls == []


def test_unapproved_host_and_unknown_license_are_typed_blockers(tmp_path: Path) -> None:
    downloader = Downloader(b"%PDF-1.7\nfixture")
    service = _service(tmp_path, downloader)

    host = service.acquire(_request(source_url="https://mirror.invalid/guide.pdf"))
    license_block = service.acquire(_request(source_id="unknown-license", license_status="unknown"))

    assert host.status == "blocked"
    assert host.blocked_reason == "host_not_approved"
    assert license_block.blocked_reason == "license_not_approved"
    assert downloader.urls == []


def test_hash_or_content_mismatch_fails_without_caching_payload(tmp_path: Path) -> None:
    payload = b"not a pdf"
    service = _service(tmp_path, Downloader(payload))

    wrong_kind = service.acquire(_request())
    wrong_hash = _service(tmp_path, Downloader(b"%PDF-1.7\nfixture")).acquire(
        _request(source_id="hash-mismatch", expected_sha256="0" * 64)
    )

    assert wrong_kind.status == "failed"
    assert wrong_kind.blocked_reason == "identity_mismatch"
    assert wrong_hash.status == "failed"
    assert not list((tmp_path / "cache").glob("*"))


def test_zip_identity_records_sorted_members_and_required_member_check(tmp_path: Path) -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("usb20/usb_20.pdf", b"pdf")
        archive.writestr("README.txt", b"bundle")
    service = _service(tmp_path, Downloader(buffer.getvalue()))

    record = service.acquire(
        _request(
            source_id="usb20-bundle",
            source_url="https://usb.org/specifications/bundle.zip",
            approved_hosts=("usb.org",),
            expected_kind="zip",
            expected_archive_members=("usb20/usb_20.pdf",),
        )
    )

    assert record.status == "downloaded"
    assert record.identity is not None
    assert record.identity.archive_members == ("README.txt", "usb20/usb_20.pdf")


def test_final_redirect_must_remain_on_approved_host(tmp_path: Path) -> None:
    result = SourceDownloadResult(
        payload=b"%PDF-1.7\nfixture",
        final_url="https://unapproved.invalid/guide.pdf",
        attempts=(
            DownloadAttempt(
                attempt=1,
                header_profile="pcbsmith",
                outcome="success",
                status_code=200,
            ),
        ),
    )
    downloader = MetadataDownloader(result)

    record = _service(tmp_path, downloader).acquire(_request())
    public = json.loads((tmp_path / "committed" / "sources.json").read_text("utf-8"))

    assert record.status == "blocked"
    assert record.blocked_reason == "host_not_approved"
    assert record.retrieval is not None
    assert record.retrieval.final_url == "https://unapproved.invalid/guide.pdf"
    assert public["schema"] == "pcbsmith-source-intake-v2"
    assert public["records"][0]["retrieval"]["attempt_count"] == 1
    assert not list((tmp_path / "cache").glob("*"))


def test_batch_intake_resumes_from_each_persisted_source(tmp_path: Path) -> None:
    first_downloader = Downloader(b"%PDF-1.7\nfirst")
    first_service = _service(tmp_path, first_downloader)
    first_request = _request(source_id="first")
    second_request = _request(source_id="second")
    first_service.acquire(first_request)

    resumed_downloader = Downloader(b"%PDF-1.7\nsecond")
    report = _service(tmp_path, resumed_downloader).acquire_many((first_request, second_request))
    private = json.loads((tmp_path / "private" / "sources.json").read_text("utf-8"))

    assert report.successful
    assert report.cache_hits == 1
    assert report.downloaded == 1
    assert report.blocked == 0
    assert report.failed == 0
    assert resumed_downloader.urls == [second_request.source_url]
    assert tuple(record["source_id"] for record in private["records"]) == (
        "first",
        "second",
    )


def test_v1_private_manifest_remains_loadable_and_is_upgraded_on_write(
    tmp_path: Path,
) -> None:
    private_path = tmp_path / "private" / "sources.json"
    private_path.parent.mkdir(parents=True)
    private_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-private-source-intake-v1",
                "records": [],
            }
        ),
        encoding="utf-8",
    )

    record = _service(tmp_path, Downloader(b"%PDF-1.7\nfixture")).acquire(_request())
    upgraded = json.loads(private_path.read_text("utf-8"))

    assert record.status == "downloaded"
    assert upgraded["schema"] == "pcbsmith-private-source-intake-v2"


def test_authentication_failure_is_distinct_from_network_failure(tmp_path: Path) -> None:
    error = EvidenceDownloadError(
        "HTTP 403",
        attempts=(
            DownloadAttempt(
                attempt=1,
                header_profile="pcbsmith",
                outcome="terminal_error",
                status_code=403,
                error_type="HTTPError",
            ),
        ),
    )

    record = _service(tmp_path, Downloader(error)).acquire(_request())

    assert record.status == "blocked"
    assert record.blocked_reason == "authentication_required"
    assert record.retrieval is not None
    assert record.retrieval.attempts[0].status_code == 403
