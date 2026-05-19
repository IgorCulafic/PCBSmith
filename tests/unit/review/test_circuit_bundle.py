from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.review.circuit_bundle import write_circuit_review_bundle
from pcbsmith.simulation.ngspice import run_ngspice_simulation


def _supported_circuit_without_findings() -> CircuitObject:
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    circuit = compose_divider_highpass_led(intent, select_topology(intent))
    return circuit.model_copy(
        update={
            "topology": circuit.topology.model_copy(update={"warnings": ()}),
            "components": tuple(
                component.model_copy(update={"support_status": "supported"})
                for component in circuit.components
            ),
            "math": circuit.math.model_copy(update={"status": "passed", "findings": ()}),
        },
    )


def test_review_bundle_records_math_simulation_and_human_review_items(tmp_path: Path) -> None:
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    circuit = compose_divider_highpass_led(intent, select_topology(intent))
    simulation = run_ngspice_simulation(circuit, tmp_path, finder=lambda: None)

    bundle_path = write_circuit_review_bundle(
        circuit,
        tmp_path,
        simulation_report=simulation,
        kicad_status="not_run",
        artifacts={"pcbs_project": str(tmp_path)},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-circuit-review-bundle-v1"
    assert data["status"] == "needs_human_review"
    assert (
        "ngspice executable was not found; set PCBSMITH_NGSPICE or install "
        "standalone ngspice before claiming simulation evidence."
        in data["items"]
    )
    assert (
        "Generic LED/passive bindings are demo-only until backed by real KiCad "
        "library and datasheet evidence."
        in data["items"]
    )


def test_review_bundle_includes_simulation_report_evidence(tmp_path: Path) -> None:
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    circuit = compose_divider_highpass_led(intent, select_topology(intent))
    simulation = SimulationReport(
        backend="ngspice",
        status="passed",
        command=("ngspice_con.exe", "-b", "divider_highpass_led.cir"),
        measurements={
            "op_div_out_v": 2.5,
            "ac_hp_out_1khz_mag_v": 0.331,
        },
        raw_output_path=str(tmp_path / "simulation-output.txt"),
    )

    bundle_path = write_circuit_review_bundle(
        circuit,
        tmp_path,
        simulation_report=simulation,
        kicad_status="not_run",
        artifacts={"pcbs_project": str(tmp_path)},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["simulation"]["backend"] == "ngspice"
    assert data["simulation"]["status"] == "passed"
    assert data["simulation"]["measurements"]["op_div_out_v"] == 2.5
    assert data["simulation"]["raw_output_path"] == str(tmp_path / "simulation-output.txt")


def test_review_bundle_records_not_run_simulation_as_review_item(tmp_path: Path) -> None:
    simulation = SimulationReport(backend="ngspice", status="not_run")

    bundle_path = write_circuit_review_bundle(
        _supported_circuit_without_findings(),
        tmp_path,
        simulation_report=simulation,
        kicad_status="passed",
        artifacts={},
    )

    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert data["status"] == "needs_human_review"
    assert "ngspice simulation status: not_run." in data["items"]
