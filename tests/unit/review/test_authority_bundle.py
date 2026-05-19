from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.models import (
    CircuitObject,
    EvidenceReport,
    KiCadReport,
    ReconciliationReport,
    RevisionRecord,
    SimulationReport,
)
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.review.authority_bundle import write_authority_review_bundle


def _circuit() -> CircuitObject:
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    return compose_divider_highpass_led(intent, select_topology(intent))


def _supported_circuit(*, math_status: str = "passed") -> CircuitObject:
    circuit = _circuit()
    return circuit.model_copy(
        update={
            "topology": circuit.topology.model_copy(update={"warnings": ()}),
            "components": tuple(
                component.model_copy(update={"support_status": "supported"})
                for component in circuit.components
            ),
            "math": circuit.math.model_copy(update={"status": math_status, "findings": ()}),
        },
    )


def _write_all_pass_bundle(circuit: CircuitObject, tmp_path: Path) -> dict:
    bundle_path = write_authority_review_bundle(
        circuit,
        tmp_path,
        evidence=EvidenceReport(status="passed"),
        kicad=KiCadReport(status="passed"),
        simulation=SimulationReport(backend="ngspice", status="passed"),
        reconciliation=ReconciliationReport(status="passed"),
        artifacts={},
    )
    return json.loads(bundle_path.read_text(encoding="utf-8"))


def test_authority_bundle_keeps_authority_sections_separate(tmp_path: Path) -> None:
    bundle_path = write_authority_review_bundle(
        _circuit(),
        tmp_path,
        evidence=EvidenceReport(status="needs_human_review", findings=("Generic parts only.",)),
        kicad=KiCadReport(status="passed", schematic_file="Slice.kicad_sch"),
        simulation=SimulationReport(backend="ngspice", status="passed"),
        reconciliation=ReconciliationReport(status="warning", findings=("LED needs review.",)),
        revisions=(
            RevisionRecord(
                revision_id="rev-1",
                next_action="Human review generic LED evidence.",
            ),
        ),
        artifacts={"kicad_project": str(tmp_path)},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-circuit-review-bundle-v2"
    assert data["status"] == "needs_human_review"
    assert data["kicad"]["status"] == "passed"
    assert data["ngspice"]["status"] == "passed"
    assert data["reconciliation"]["status"] == "warning"
    assert data["revisions"][0]["revision_id"] == "rev-1"
    assert "simulation" not in data
    assert "items" not in data


def test_authority_bundle_failure_dominates_unavailable_and_review(
    tmp_path: Path,
) -> None:
    bundle_path = write_authority_review_bundle(
        _circuit(),
        tmp_path,
        evidence=EvidenceReport(status="needs_human_review"),
        kicad=KiCadReport(status="failed"),
        simulation=SimulationReport(backend="ngspice", status="unavailable"),
        reconciliation=ReconciliationReport(status="warning"),
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"


def test_authority_bundle_preserves_not_run_before_human_review(
    tmp_path: Path,
) -> None:
    bundle_path = write_authority_review_bundle(
        _circuit(),
        tmp_path,
        evidence=EvidenceReport(status="passed"),
        kicad=KiCadReport(status="not_run"),
        simulation=SimulationReport(backend="ngspice", status="not_run"),
        reconciliation=ReconciliationReport(status="passed"),
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "not_run"
    assert data["kicad"]["status"] == "not_run"
    assert data["ngspice"]["status"] == "not_run"


def test_authority_bundle_component_review_drives_human_review(
    tmp_path: Path,
) -> None:
    bundle_path = write_authority_review_bundle(
        _circuit(),
        tmp_path,
        evidence=EvidenceReport(status="passed"),
        kicad=KiCadReport(status="passed"),
        simulation=SimulationReport(backend="ngspice", status="passed"),
        reconciliation=ReconciliationReport(status="passed"),
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "needs_human_review"


def test_authority_bundle_fully_supported_all_passes(tmp_path: Path) -> None:
    data = _write_all_pass_bundle(_supported_circuit(), tmp_path)

    assert data["status"] == "passed"


def test_authority_bundle_internal_math_failed_dominates_passed_authorities(
    tmp_path: Path,
) -> None:
    data = _write_all_pass_bundle(_supported_circuit(math_status="failed"), tmp_path)

    assert data["status"] == "failed"


def test_authority_bundle_internal_math_warning_needs_human_review(
    tmp_path: Path,
) -> None:
    data = _write_all_pass_bundle(_supported_circuit(math_status="warning"), tmp_path)

    assert data["status"] == "needs_human_review"


def test_authority_bundle_evidence_failed_dominates_passed_validation(
    tmp_path: Path,
) -> None:
    bundle_path = write_authority_review_bundle(
        _supported_circuit(),
        tmp_path,
        evidence=EvidenceReport(status="failed"),
        kicad=KiCadReport(status="passed"),
        simulation=SimulationReport(backend="ngspice", status="passed"),
        reconciliation=ReconciliationReport(status="passed"),
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"


def test_authority_bundle_evidence_unavailable_dominates_human_review(
    tmp_path: Path,
) -> None:
    bundle_path = write_authority_review_bundle(
        _circuit(),
        tmp_path,
        evidence=EvidenceReport(status="unavailable"),
        kicad=KiCadReport(status="passed"),
        simulation=SimulationReport(backend="ngspice", status="passed"),
        reconciliation=ReconciliationReport(status="passed"),
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "unavailable"


def test_authority_bundle_failure_dominates_evidence_unavailable(
    tmp_path: Path,
) -> None:
    bundle_path = write_authority_review_bundle(
        _supported_circuit(),
        tmp_path,
        evidence=EvidenceReport(status="unavailable"),
        kicad=KiCadReport(status="failed"),
        simulation=SimulationReport(backend="ngspice", status="passed"),
        reconciliation=ReconciliationReport(status="passed"),
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"


def test_authority_bundle_reconciliation_unavailable_dominates_human_review(
    tmp_path: Path,
) -> None:
    bundle_path = write_authority_review_bundle(
        _circuit(),
        tmp_path,
        evidence=EvidenceReport(status="passed"),
        kicad=KiCadReport(status="passed"),
        simulation=SimulationReport(backend="ngspice", status="passed"),
        reconciliation=ReconciliationReport(status="unavailable"),
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "unavailable"


def test_authority_bundle_failure_dominates_reconciliation_unavailable(
    tmp_path: Path,
) -> None:
    bundle_path = write_authority_review_bundle(
        _supported_circuit(),
        tmp_path,
        evidence=EvidenceReport(status="passed"),
        kicad=KiCadReport(status="passed"),
        simulation=SimulationReport(backend="ngspice", status="failed"),
        reconciliation=ReconciliationReport(status="unavailable"),
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
