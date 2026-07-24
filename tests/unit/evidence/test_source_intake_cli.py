from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.cli import _load_source_intake_catalog, build_parser


def test_catalog_loader_accepts_research_annotations(tmp_path: Path) -> None:
    catalog = tmp_path / "sources.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-research-source-request-catalog-v1",
                "purpose": "fixture",
                "sources": [
                    {
                        "source_id": "vendor-guide",
                        "title": "Vendor design guide",
                        "category": "layout",
                        "source_url": "https://vendor.example/guide.pdf",
                        "approved_hosts": ["vendor.example"],
                        "intended_consumer": "fixture rule research",
                        "expected_kind": "pdf",
                        "license_status": "local_cache_only",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    requests = _load_source_intake_catalog(catalog)

    assert len(requests) == 1
    assert requests[0].source_id == "vendor-guide"
    assert requests[0].approved_hosts == ("vendor.example",)


def test_catalog_loader_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    source = {
        "source_id": "duplicate",
        "source_url": "https://vendor.example/guide.pdf",
        "approved_hosts": ["vendor.example"],
        "intended_consumer": "fixture rule research",
        "expected_kind": "pdf",
        "license_status": "local_cache_only",
    }
    catalog = tmp_path / "sources.json"
    catalog.write_text(json.dumps([source, source]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate source_id"):
        _load_source_intake_catalog(catalog)


def test_batch_parser_uses_resilient_download_defaults() -> None:
    args = build_parser().parse_args(
        [
            "source-intake-batch",
            "catalog.json",
            "--private-manifest",
            "private.json",
            "--public-manifest",
            "public.json",
            "--cache-dir",
            "cache",
        ]
    )

    assert args.attempts == 3
    assert args.retry_delay == 1.0
    assert args.max_retry_delay == 30.0
    assert not args.no_browser_fallback
