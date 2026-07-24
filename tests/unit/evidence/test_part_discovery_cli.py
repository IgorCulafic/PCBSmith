"""Operational exact-part discovery CLI coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pcbsmith.cli as cli
from pcbsmith.evidence.part_discovery import (
    ExactPartDiscoveryRequest,
    PartResourceCandidate,
    PartResourceRole,
)


class Downloader:
    def download(self, url: str) -> bytes:
        return b"%PDF-1.7\nfixture"


def test_cli_retrieves_exact_part_catalog_and_writes_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = ExactPartDiscoveryRequest(
        manufacturer="Example Semiconductor",
        part_number="EX-1234-A",
        required_roles=(PartResourceRole.DATASHEET,),
        intended_consumer="project gate",
    )
    candidate = PartResourceCandidate(
        provider_id="fixture",
        manufacturer="Example Semiconductor",
        part_number="EX-1234-A",
        role=PartResourceRole.DATASHEET,
        metadata_url="https://example.com/ex-1234-a",
        download_url="https://example.com/ex-1234-a.pdf",
        approved_hosts=("example.com",),
        expected_kind="pdf",
        license_status="local_cache_only",
    )
    request_path = tmp_path / "request.json"
    candidates_path = tmp_path / "candidates.json"
    output_path = tmp_path / "report.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    candidates_path.write_text(
        json.dumps({"candidates": [candidate.model_dump(mode="json")]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_source_intake_downloader", lambda _args: Downloader())

    status = cli.main(
        [
            "part-discover",
            str(request_path),
            str(candidates_path),
            "--private-manifest",
            str(tmp_path / "private.json"),
            "--public-manifest",
            str(tmp_path / "public.json"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--output",
            str(output_path),
        ]
    )

    assert status == 0
    assert json.loads(output_path.read_text("utf-8"))["records"][0]["status"] == (
        "validated_cache"
    )
