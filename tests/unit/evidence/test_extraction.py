from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.evidence import EvidenceExtractionResult, EvidenceExtractionService
from pcbsmith.evidence.models import EvidenceFact, EvidenceLocator


class RecordingExtractor:
    def __init__(self, result: EvidenceExtractionResult) -> None:
        self.result = result
        self.paths: list[Path] = []

    def extract(self, path: Path) -> EvidenceExtractionResult:
        self.paths.append(path)
        return self.result


def test_extraction_service_writes_machine_extracted_facts_and_updates_job(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "datasheets" / "example.pdf"
    source_file.parent.mkdir()
    source_file.write_bytes(b"%PDF not parsed by this test")
    manifest_path = _write_manifest_with_pending_job(tmp_path, source_file)
    extractor = RecordingExtractor(
        EvidenceExtractionResult(
            status="machine_extracted",
            facts=(
                EvidenceFact(
                    name="forward_voltage_v_typ",
                    value=2.0,
                    unit="V",
                    conditions="IF=5mA fixture extractor",
                    locator=EvidenceLocator(
                        local_file="datasheets/example.pdf",
                        page=2,
                        table="Electrical characteristics",
                    ),
                    confidence="machine_extracted",
                ),
            ),
        )
    )
    service = EvidenceExtractionService(manifest_path=manifest_path, extractor=extractor)

    report = service.process_pending()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert report.processed_jobs == 1
    assert extractor.paths == [source_file.resolve()]
    assert data["components"][0]["facts"][0]["name"] == "forward_voltage_v_typ"
    assert data["components"][0]["facts"][0]["confidence"] == "machine_extracted"
    assert data["extraction_jobs"][0]["status"] == "machine_extracted"


def test_extraction_service_marks_job_failed_without_adding_facts(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "datasheets" / "example.pdf"
    source_file.parent.mkdir()
    source_file.write_bytes(b"%PDF not parsed by this test")
    manifest_path = _write_manifest_with_pending_job(tmp_path, source_file)
    service = EvidenceExtractionService(
        manifest_path=manifest_path,
        extractor=RecordingExtractor(
            EvidenceExtractionResult(
                status="failed",
                findings=("No parseable text found.",),
            )
        ),
    )

    report = service.process_pending()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert report.processed_jobs == 1
    assert data["components"][0]["facts"] == []
    assert data["extraction_jobs"][0]["status"] == "failed"
    assert data["extraction_jobs"][0]["findings"] == ["No parseable text found."]


def _write_manifest_with_pending_job(tmp_path: Path, source_file: Path) -> Path:
    manifest_path = tmp_path / "manifest.json"
    local_path = source_file.relative_to(tmp_path).as_posix()
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-evidence-manifest-v1",
                "components": [
                    {
                        "manufacturer": "Example",
                        "part_number": "EX-LED-0603",
                        "role": "indicator_led",
                        "symbol_id": "stdlib:LED",
                        "value": "Example red LED",
                        "footprint": "LED_SMD:LED_0603_1608Metric",
                        "files": [
                            {
                                "local_path": local_path,
                                "sha256": "test-sha",
                                "source_url": "https://example.invalid/example.pdf",
                                "retrieved_at": "2026-05-20",
                                "license_status": "local_cache_only",
                            }
                        ],
                        "facts": [],
                    }
                ],
                "extraction_jobs": [
                    {
                        "status": "pending_extraction",
                        "component_manufacturer": "Example",
                        "component_part_number": "EX-LED-0603",
                        "role": "indicator_led",
                        "local_path": local_path,
                        "sha256": "test-sha",
                        "source_url": "https://example.invalid/example.pdf",
                        "created_at": "2026-05-20",
                        "findings": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path

