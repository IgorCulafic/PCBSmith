from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from pcbsmith.bounded_local_repair import (
    LocalRepairBudget,
    LocalRepairOutcome,
    LocalRepairRequest,
    RepairFindingClass,
)
from pcbsmith.local_repair_execution import (
    LocalizedRepairFinding,
    RepairCandidateAssessment,
    assert_localized_finding_is_qualified,
    execute_bounded_local_repair,
)
from pcbsmith.whole_board_qualification import (
    REQUIRED_GATE_IDS,
    QualificationDisposition,
    QualificationGate,
    RoutingCraftAssessment,
    WholeBoardQualification,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(source: Path, *, immutable: tuple[str, ...] = ()) -> LocalRepairRequest:
    return LocalRepairRequest.build(
        request_id="repair-1",
        source_board_sha256=_sha(source),
        source_qualification_fingerprint="b" * 64,
        finding_class=RepairFindingClass.SILKSCREEN_OVERLAP,
        target_finding_ids=("silk-1",),
        target_region_mm=(0.0, 0.0, 10.0, 10.0),
        affected_net_names=(),
        immutable_object_ids=immutable,
        movable_component_references=("R1",),
        rip_authorized_copper_ids=("segment:old",),
        budget=LocalRepairBudget(
            maximum_displacement_mm=1.0,
            maximum_ripped_segment_count=1,
            maximum_ripped_via_count=0,
            maximum_added_segment_count=1,
            maximum_added_via_count=0,
            maximum_attempt_count=2,
            maximum_elapsed_seconds=10.0,
        ),
    )


def _assessment(candidate: Path, *, changed: tuple[str, ...] = ("R1",)):
    return RepairCandidateAssessment.build(
        candidate_board_sha256=_sha(candidate),
        changed_object_ids=changed,
        moved_component_displacements_mm={"R1": 0.5},
        removed_segment_ids=(),
        removed_via_ids=(),
        added_segment_ids=("segment:new",),
        added_via_ids=(),
        change_bounds_mm=(1.0, 1.0, 2.0, 2.0),
        target_findings_removed=("silk-1",),
        new_finding_ids=(),
        protected_region_fingerprints={"accepted-power": "c" * 64},
        unresolved_burden=1,
        craft_cost=2,
    )


def _proposer(source: Path, attempt_dir: Path, attempt: int) -> Path:
    candidate = attempt_dir / f"candidate-{attempt}.kicad_pcb"
    shutil.copy2(source, candidate)
    candidate.write_bytes(candidate.read_bytes() + b"\n(repair)\n")
    return candidate


def test_executor_retains_only_monotonic_isolated_candidate(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_pcb"
    source.write_bytes(b"(kicad_pcb)")
    before = _sha(source)
    execution = execute_bounded_local_repair(
        source_board=source,
        transaction_root=tmp_path / "transaction",
        request=_request(source),
        source_protected_region_fingerprints={"accepted-power": "c" * 64},
        source_unresolved_burden=2,
        source_craft_cost=2,
        proposer=_proposer,
        assessor=_assessment,
    )
    assert execution.result.outcome is LocalRepairOutcome.ACCEPTED
    assert execution.result.publish_authorized
    assert execution.retained_candidate_file is not None
    assert _sha(source) == before


def test_immutable_change_rolls_back_without_source_mutation(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_pcb"
    source.write_bytes(b"(kicad_pcb)")
    execution = execute_bounded_local_repair(
        source_board=source,
        transaction_root=tmp_path / "transaction",
        request=_request(source, immutable=("R1",)),
        source_protected_region_fingerprints={"accepted-power": "c" * 64},
        source_unresolved_burden=2,
        source_craft_cost=2,
        proposer=_proposer,
        assessor=_assessment,
    )
    assert execution.result.outcome is LocalRepairOutcome.REJECTED_REGRESSION
    assert not execution.result.publish_authorized
    assert execution.retained_candidate_file is None
    assert any("immutable_object_changed" in item for item in execution.result.blocker_ids)


def test_localized_finding_must_exist_in_source_qualification() -> None:
    # This unit test checks blocker membership, not a retained experiment result.
    board_hash = "a" * 64
    qualification = WholeBoardQualification.build(
        case_id="synthetic-open-net", refilled_board_sha256=board_hash,
        gates=tuple(QualificationGate(
            gate_id=gate_id, board_sha256=board_hash,
            disposition=(QualificationDisposition.FAIL
                         if gate_id == "routed_copper_carrier_coverage"
                         else QualificationDisposition.UNVERIFIED),
            applicable=True, evaluated_object_count=1, evidence_fingerprints=("b" * 64,),
            finding_ids=(("uncovered_net:GATE1_LOCAL",)
                         if gate_id == "routed_copper_carrier_coverage" else ()),
        ) for gate_id in REQUIRED_GATE_IDS),
        craft=RoutingCraftAssessment(
            board_sha256=board_hash, acute_bend_count=0, needless_bend_count=0,
            excessive_jog_count=0, unnecessary_via_count=0, long_detour_count=0,
            bus_disorder_count=0, congested_region_count=0,
            repair_recommended=False, rank_cost_units=0,
        ),
    )
    valid = LocalizedRepairFinding(
        finding_id="uncovered-net",
        qualification_blocker_id=(
            "routed_copper_carrier_coverage:uncovered_net:GATE1_LOCAL"
        ),
        finding_class=RepairFindingClass.OPEN_ENDPOINT,
        target_region_mm=(0.0, 0.0, 1.0, 1.0),
    )
    assert_localized_finding_is_qualified(qualification, valid)
    with pytest.raises(ValueError, match="absent"):
        assert_localized_finding_is_qualified(
            qualification,
            valid.model_copy(update={"qualification_blocker_id": "not-present"}),
        )
