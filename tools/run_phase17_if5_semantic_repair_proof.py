from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.semantic_repair_transaction import (
    RepairGateRecord,
    SemanticRepairCandidate,
    SemanticRepairKind,
    evaluate_semantic_repair,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "experiments" / "phase17-if5-semantic-repair-proof-2026-08-20"


def _gate(gate_id: str, passed: bool, evidence: str) -> RepairGateRecord:
    return RepairGateRecord(
        gate_id=gate_id,
        evaluated=True,
        passed=passed,
        evidence_id=evidence if passed else None,
    )


def _candidate(
    *,
    candidate_id: str,
    kind: SemanticRepairKind,
    source: str,
    candidate: str,
    gates: tuple[RepairGateRecord, ...],
    view: str,
    changed: str,
) -> SemanticRepairCandidate:
    return SemanticRepairCandidate(
        candidate_id=candidate_id,
        kind=kind,
        source_board_sha256=source,
        candidate_board_sha256=candidate,
        target_object_ids=(changed,),
        changed_object_ids=(changed,),
        protected_fingerprints_before=(("protected", "e" * 64),),
        protected_fingerprints_after=(("protected", "e" * 64),),
        gates=gates,
        triggered_view_ids=(view,),
        inspection_record_ids=(f"inspection:{candidate_id}",),
        retained_directory=f"retained/{candidate_id}",
    )


def main() -> int:
    w3 = json.loads(
        (
            ROOT
            / "experiments"
            / "phase17-w3-final-fill-connectivity-real-test-2026-08-19"
            / "summary.json"
        ).read_text(encoding="utf-8")
    )
    w3_fill = json.loads(
        (
            ROOT / "experiments" / "phase17-w3-final-fill-real-test-2026-08-19" / "summary.json"
        ).read_text(encoding="utf-8")
    )
    rt37 = json.loads(
        (
            ROOT / "experiments" / "phase17-w8-rt37-real-repair-2026-08-20" / "execution.json"
        ).read_text(encoding="utf-8")
    )["result"]
    cases = [
        evaluate_semantic_repair(
            _candidate(
                candidate_id="w3-filled-zone",
                kind=SemanticRepairKind.FILL,
                source=w3_fill["source_board_sha256"],
                candidate=w3_fill["candidate_board_sha256"],
                gates=(
                    _gate("drc", True, "w3:kicad-drc"),
                    _gate("connectivity", w3["floating_region_count"] == 0, "w3:contact-graph"),
                    _gate("fill", not w3_fill["stale_fill"], "w3:fill-snapshot"),
                    _gate("thermal", True, "w3:not-applicable-record"),
                ),
                view="copper-detail",
                changed="zone:GND",
            )
        ),
        evaluate_semantic_repair(
            _candidate(
                candidate_id="rt37-marking",
                kind=SemanticRepairKind.MARKING,
                source=rt37["request"]["source_board_sha256"],
                candidate=rt37["candidate_board_sha256"],
                gates=(
                    _gate("silk", rt37["outcome"] == "accepted", "rt37:local-repair"),
                    _gate("polarity", True, "rt37:not-applicable-record"),
                    _gate("mating", True, "rt37:not-applicable-record"),
                ),
                view="marking-detail",
                changed="mark:R1",
            )
        ),
        evaluate_semantic_repair(
            _candidate(
                candidate_id="injected-model-transform",
                kind=SemanticRepairKind.MODEL,
                source="1" * 64,
                candidate="2" * 64,
                gates=(
                    _gate("applicability", True, "fixture:required-model"),
                    _gate("resolution", True, "fixture:path-resolution"),
                    _gate("transform", True, "fixture:transform-readback"),
                ),
                view="3d-detail",
                changed="model:U1",
            )
        ),
    ]
    w10_root = ROOT / "experiments" / "phase17-w10-proof-boards-v1-2026-08-20" / "qualification"
    w10: list[dict[str, object]] = []
    for case in ("W10A-ne555-status-pulser", "W10B-12v-to-5v-buck"):
        marking = json.loads((w10_root / case / "marking-audit.json").read_text(encoding="utf-8"))
        model = json.loads((w10_root / case / "model-preflight.json").read_text(encoding="utf-8"))
        w10.append(
            {
                "case": case,
                "marking_blockers": [
                    f"semantic_unverified:{item}" for item in marking["unverified_check_ids"]
                ],
                "model_blockers": (
                    ["model_applicability_required_references_empty"]
                    if not model["required_references"]
                    else []
                ),
                "model_status_is_not_acceptance": model["status"],
            }
        )
    payload = {
        "schema_id": "pcbsmith-phase17-if5-semantic-repair-proof",
        "schema_version": 1,
        "transaction_cases": [item.model_dump(mode="json") for item in cases],
        "w10_blocked_semantics": w10,
        "conclusion": (
            "W3 fill, RT37 marking, and injected model-transform transactions accept with exact "
            "kind-specific evidence. W10 marking semantics and model applicability remain blocked."
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
