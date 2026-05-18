from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject, CircuitReviewBundle, SimulationReport


def write_circuit_review_bundle(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    simulation_report: SimulationReport,
    kicad_status: str,
    artifacts: dict[str, str],
) -> Path:
    items: list[str] = []
    items.extend(circuit.topology.warnings)
    items.extend(circuit.math.findings)
    items.extend(simulation_report.findings)
    if kicad_status != "passed":
        items.append(f"KiCad validation status: {kicad_status}.")
    if any(component.support_status != "supported" for component in circuit.components):
        items.append("One or more selected components are demo-only or need datasheet review.")

    status = "needs_human_review" if items else "passed"
    bundle = CircuitReviewBundle(
        schema="pcbsmith-circuit-review-bundle-v1",
        intent_id=circuit.intent.intent_id,
        status=status,
        items=tuple(dict.fromkeys(items)),
        artifacts=artifacts,
    )
    path = output_dir / "review-bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle.model_dump(by_alias=True), indent=2) + "\n", encoding="utf-8")
    return path
