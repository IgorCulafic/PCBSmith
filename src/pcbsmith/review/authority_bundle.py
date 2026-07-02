from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.models import (
    AuthorityReviewBundle,
    AuthorityStatus,
    BoardReport,
    CircuitObject,
    DesignReviewReport,
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
    board: BoardReport | None = None,
    design_review: DesignReviewReport | None = None,
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
            board=board,
            design_review=design_review,
        ),
        intent=circuit.intent,
        pcbs_internal=circuit,
        evidence=evidence,
        kicad=kicad,
        ngspice=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
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
    board: BoardReport | None = None,
    design_review: DesignReviewReport | None = None,
) -> AuthorityStatus:
    authority_statuses = (evidence.status, kicad.status, simulation.status, reconciliation.status)
    board_status = board.status if board is not None else None
    review_status = design_review.status if design_review is not None else None
    if circuit.math.status == "failed" or "failed" in authority_statuses:
        return "failed"
    if board_status == "failed" or review_status == "failed":
        return "failed"
    if "unavailable" in authority_statuses or board_status == "unavailable":
        return "unavailable"
    if "not_run" in authority_statuses:
        return "not_run"

    if (
        circuit.math.status != "passed"
        or evidence.status != "passed"
        or kicad.status != "passed"
        or simulation.status != "passed"
        or reconciliation.status != "passed"
        or (board_status is not None and board_status != "passed")
        or (review_status is not None and review_status != "passed")
        or any(component.support_status != "supported" for component in circuit.components)
    ):
        return "needs_human_review"
    return "passed"
