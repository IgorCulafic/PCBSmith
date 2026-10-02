from __future__ import annotations

from pcbsmith.semantic_repair_transaction import (
    RepairGateRecord,
    SemanticRepairCandidate,
    SemanticRepairKind,
    evaluate_semantic_repair,
)


def _gate(gate_id: str, passed: bool = True) -> RepairGateRecord:
    return RepairGateRecord(
        gate_id=gate_id,
        evaluated=True,
        passed=passed,
        evidence_id=f"evidence:{gate_id}" if passed else None,
    )


def _candidate(kind: SemanticRepairKind) -> SemanticRepairCandidate:
    gates = {
        SemanticRepairKind.FILL: ("drc", "connectivity", "fill", "thermal"),
        SemanticRepairKind.MARKING: ("silk", "polarity", "mating"),
        SemanticRepairKind.MODEL: ("applicability", "resolution", "transform"),
    }[kind]
    view = {
        SemanticRepairKind.FILL: "copper-detail",
        SemanticRepairKind.MARKING: "marking-detail",
        SemanticRepairKind.MODEL: "3d-detail",
    }[kind]
    return SemanticRepairCandidate(
        candidate_id=f"candidate-{kind.value}",
        kind=kind,
        source_board_sha256="a" * 64,
        candidate_board_sha256="b" * 64,
        target_object_ids=("target",),
        changed_object_ids=("target",),
        protected_fingerprints_before=(("protected", "c" * 64),),
        protected_fingerprints_after=(("protected", "c" * 64),),
        gates=tuple(_gate(item) for item in gates),
        triggered_view_ids=(view,),
        inspection_record_ids=("inspection:1",),
        retained_directory="retained",
    )


def test_all_three_semantic_repair_kinds_accept_complete_evidence() -> None:
    for kind in SemanticRepairKind:
        assert evaluate_semantic_repair(_candidate(kind)).accepted


def test_model_pass_without_applicability_is_blocked() -> None:
    candidate = _candidate(SemanticRepairKind.MODEL)
    candidate = candidate.model_copy(
        update={"gates": tuple(gate for gate in candidate.gates if gate.gate_id != "applicability")}
    )
    decision = evaluate_semantic_repair(candidate)
    assert not decision.accepted
    assert "gate_missing:applicability" in decision.blockers


def test_protected_change_and_missing_detail_view_are_blockers() -> None:
    candidate = _candidate(SemanticRepairKind.MARKING).model_copy(
        update={
            "protected_fingerprints_after": (("protected", "d" * 64),),
            "triggered_view_ids": (),
        }
    )
    decision = evaluate_semantic_repair(candidate)
    assert "protected_object_changed" in decision.blockers
    assert "view_missing:marking-detail" in decision.blockers
