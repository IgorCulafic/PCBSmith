from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.evidence import (
    EvidenceExtractionResult,
    EvidenceExtractionService,
    register_local_evidence,
)
from pcbsmith.evidence.models import EvidenceExtractionJob, EvidenceFact, EvidenceLocator


def _clock() -> str:
    return "2026-07-02"


def _register(manifest_path: Path, pdf: Path) -> None:
    register_local_evidence(
        manifest_path=manifest_path,
        source_file=pdf,
        manufacturer="Kingbright",
        part_number="APT1608SRCPRV",
        role="indicator_led",
        symbol_id="stdlib:LED",
        value="Kingbright APT1608SRCPRV",
        footprint="LED_SMD:LED_0603_1608Metric",
        source_url="https://example.invalid/apt1608srcprv.pdf",
        clock=_clock,
    )


def test_register_local_evidence_writes_component_and_pending_job(tmp_path: Path) -> None:
    pdf = tmp_path / "datasheets" / "led.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF datasheet payload")
    manifest_path = tmp_path / "manifest.json"

    _register(manifest_path, pdf)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert data["schema"] == "pcbsmith-evidence-manifest-v1"
    component = data["components"][0]
    assert component["part_number"] == "APT1608SRCPRV"
    assert component["symbol_id"] == "stdlib:LED"
    assert component["footprint"] == "LED_SMD:LED_0603_1608Metric"
    assert component["files"][0]["local_path"] == "datasheets/led.pdf"
    assert len(component["files"][0]["sha256"]) == 64
    job = data["extraction_jobs"][0]
    assert job["status"] == "pending_extraction"
    assert job["role"] == "indicator_led"
    assert job["local_path"] == "datasheets/led.pdf"


def test_register_local_evidence_replaces_existing_identity(tmp_path: Path) -> None:
    pdf = tmp_path / "led.pdf"
    pdf.write_bytes(b"%PDF datasheet payload")
    manifest_path = tmp_path / "manifest.json"

    _register(manifest_path, pdf)
    _register(manifest_path, pdf)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(data["components"]) == 1
    assert len(data["extraction_jobs"]) == 1


def test_register_local_evidence_keeps_jobs_for_shared_datasheet(tmp_path: Path) -> None:
    pdf = tmp_path / "resistor-series.pdf"
    pdf.write_bytes(b"%PDF series datasheet")
    manifest_path = tmp_path / "manifest.json"

    for role, part in (
        ("divider_top", "CRCW060310K0FKEA"),
        ("divider_bottom", "CRCW060310K0FKEA"),
        ("led_current_limit", "CRCW0603680RFKEA"),
    ):
        register_local_evidence(
            manifest_path=manifest_path,
            source_file=pdf,
            manufacturer="Vishay",
            part_number=part,
            role=role,
            symbol_id="stdlib:R",
            value=part,
            footprint="Resistor_SMD:R_0603_1608Metric",
            source_url=None,
            clock=_clock,
        )
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(data["components"]) == 3
    assert len(data["extraction_jobs"]) == 3
    assert {job["role"] for job in data["extraction_jobs"]} == {
        "divider_top",
        "divider_bottom",
        "led_current_limit",
    }


class ScriptedExtractor:
    def __init__(self, result: EvidenceExtractionResult) -> None:
        self.result = result
        self.calls = 0

    def extract(
        self,
        path: Path,
        job: EvidenceExtractionJob,
    ) -> EvidenceExtractionResult:
        self.calls += 1
        return self.result


def test_extraction_service_retries_failed_jobs_when_requested(tmp_path: Path) -> None:
    pdf = tmp_path / "led.pdf"
    pdf.write_bytes(b"%PDF datasheet payload")
    manifest_path = tmp_path / "manifest.json"
    _register(manifest_path, pdf)

    failing = ScriptedExtractor(
        EvidenceExtractionResult(status="failed", findings=("no provider",))
    )
    EvidenceExtractionService(manifest_path=manifest_path, extractor=failing).process_pending()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["extraction_jobs"][0]["status"] == "failed"

    succeeding = ScriptedExtractor(
        EvidenceExtractionResult(
            status="machine_extracted",
            facts=(
                EvidenceFact(
                    name="forward_voltage_v_typ",
                    value=1.85,
                    unit="V",
                    conditions="IF=20mA",
                    locator=EvidenceLocator(local_file="led.pdf", page=3),
                    confidence="machine_extracted",
                ),
            ),
        )
    )
    skipped = EvidenceExtractionService(
        manifest_path=manifest_path,
        extractor=succeeding,
    ).process_pending()
    assert skipped.processed_jobs == 0

    retried = EvidenceExtractionService(
        manifest_path=manifest_path,
        extractor=succeeding,
    ).process_pending(retry_failed=True)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert retried.processed_jobs == 1
    assert data["extraction_jobs"][0]["status"] == "machine_extracted"
    assert data["extraction_jobs"][0]["findings"] == []
    assert data["components"][0]["facts"][0]["name"] == "forward_voltage_v_typ"
    assert data["components"][0]["facts"][0]["value"] == 1.85
