from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.review.circuit_bundle import write_circuit_review_bundle
from pcbsmith.simulation.ngspice import run_ngspice_simulation


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
