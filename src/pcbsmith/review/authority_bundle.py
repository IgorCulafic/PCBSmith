from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.models import (
    AuthorityReviewBundle,
    AuthorityStatus,
    CircuitObject,
    EvidenceReport,
    KiCadReport,
    ReconciliationReport,
    RevisionRecord,
    SimulationReport,
)


def write_authority_review_bundle(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    evidence: EvidenceReport,
    kicad: KiCadReport,
    simulation: SimulationReport,
    reconciliation: ReconciliationReport,
    revisions: tuple[RevisionRecord, ...] = (),
    artifacts: dict[str, str],
) -> Path:
    bundle = AuthorityReviewBundle(
        schema_id="pcbsmith-circuit-review-bundle-v2",
        status=_derive_status(
            circuit=circuit,
            evidence=evidence,
            kicad=kicad,
            simulation=simulation,
            reconciliation=reconciliation,
        ),
        intent=circuit.intent,
        pcbs_internal=circuit,
        evidence=evidence,
        kicad=kicad,
        ngspice=simulation,
        reconciliation=reconciliation,
        revisions=revisions,
        artifacts=artifacts,
    )
    path = output_dir / "review-bundle-v2.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle.model_dump(by_alias=True), indent=2) + "\n", encoding="utf-8")
    return path


def _derive_status(
    *,
    circuit: CircuitObject,
    evidence: EvidenceReport,
    kicad: KiCadReport,
    simulation: SimulationReport,
    reconciliation: ReconciliationReport,
) -> AuthorityStatus:
    validation_statuses = (kicad.status, simulation.status, reconciliation.status)
    if "failed" in validation_statuses:
        return "failed"
    if kicad.status == "unavailable" or simulation.status == "unavailable":
        return "unavailable"

    authority_statuses = (evidence.status, kicad.status, simulation.status, reconciliation.status)
    if "not_run" in authority_statuses:
        return "not_run"

    if (
        evidence.status != "passed"
        or kicad.status != "passed"
        or simulation.status != "passed"
        or reconciliation.status != "passed"
        or any(component.support_status != "supported" for component in circuit.components)
    ):
        return "needs_human_review"
    return "passed"
