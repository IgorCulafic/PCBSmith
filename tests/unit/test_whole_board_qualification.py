from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.whole_board_qualification import (
    REQUIRED_GATE_IDS,
    QualificationDisposition,
    QualificationGate,
    RoutingCraftAssessment,
    WholeBoardQualification,
)

BOARD = "a" * 64
EVIDENCE = "b" * 64


def _gate(
    gate_id: str,
    disposition: QualificationDisposition = QualificationDisposition.PASS,
    *,
    board: str = BOARD,
    findings: tuple[str, ...] = (),
    applicable: bool = True,
) -> QualificationGate:
    return QualificationGate(
        gate_id=gate_id,
        board_sha256=board,
        disposition=disposition,
        applicable=applicable,
        evaluated_object_count=1 if applicable else 0,
        evidence_fingerprints=(EVIDENCE,) if applicable else (),
        finding_ids=findings,
    )


def _craft(**changes: object) -> RoutingCraftAssessment:
    values: dict[str, object] = {
        "board_sha256": BOARD,
        "acute_bend_count": 0,
        "needless_bend_count": 0,
        "excessive_jog_count": 0,
        "unnecessary_via_count": 0,
        "long_detour_count": 0,
        "bus_disorder_count": 0,
        "congested_region_count": 0,
        "repair_recommended": False,
        "rank_cost_units": 0,
    }
    values.update(changes)
    return RoutingCraftAssessment.model_validate(values)


def _all_pass() -> tuple[QualificationGate, ...]:
    return tuple(_gate(item) for item in REQUIRED_GATE_IDS)


def test_release_pass_requires_every_gate_on_one_refilled_hash() -> None:
    result = WholeBoardQualification.build(
        case_id="W7-clean",
        refilled_board_sha256=BOARD,
        gates=_all_pass(),
        craft=_craft(),
    )
    assert result.release_qualified
    assert result.blocker_ids == ()
    assert result.unverified_gate_ids == ()


def test_unconnected_item_blocks_even_if_every_other_gate_passes() -> None:
    gates = tuple(
        _gate(
            item,
            QualificationDisposition.FAIL,
            findings=("kicad_unconnected_items",),
        )
        if item == "kicad_integrity"
        else _gate(item)
        for item in REQUIRED_GATE_IDS
    )
    result = WholeBoardQualification.build(
        case_id="W7-open", refilled_board_sha256=BOARD, gates=gates, craft=_craft()
    )
    assert not result.release_qualified
    assert result.blocker_ids == ("kicad_integrity:kicad_unconnected_items",)


def test_missing_environment_model_stays_unverified_not_ampacity_pass() -> None:
    gates = tuple(
        _gate(item, QualificationDisposition.UNVERIFIED)
        if item == "current_environment_model"
        else _gate(item)
        for item in REQUIRED_GATE_IDS
    )
    result = WholeBoardQualification.build(
        case_id="W7-no-ipc", refilled_board_sha256=BOARD, gates=gates, craft=_craft()
    )
    assert not result.release_qualified
    assert result.unverified_gate_ids == ("current_environment_model",)


def test_w3_region_and_reference_limits_remain_explicitly_unverified() -> None:
    gates = tuple(
        _gate(item, QualificationDisposition.UNVERIFIED)
        if item in {"filled_region_connectivity", "reference_continuity"}
        else _gate(item)
        for item in REQUIRED_GATE_IDS
    )
    result = WholeBoardQualification.build(
        case_id="W7-w3-blocked", refilled_board_sha256=BOARD, gates=gates, craft=_craft()
    )
    assert result.unverified_gate_ids == (
        "filled_region_connectivity",
        "reference_continuity",
    )
    assert not result.release_qualified


def test_uncited_craft_defects_rank_and_request_repair_but_do_not_fail_electrical_gate() -> None:
    craft = _craft(needless_bend_count=2, repair_recommended=True, rank_cost_units=2)
    result = WholeBoardQualification.build(
        case_id="W7-craft", refilled_board_sha256=BOARD, gates=_all_pass(), craft=craft
    )
    assert result.release_qualified
    assert result.craft.repair_recommended


def test_cited_hard_craft_rule_can_block_release() -> None:
    craft = _craft(
        acute_bend_count=1,
        repair_recommended=True,
        rank_cost_units=1,
        hard_rule_finding_ids=("acute-copper-1",),
        hard_rule_authority_ids=("pcbsmith-rule-11.1",),
    )
    result = WholeBoardQualification.build(
        case_id="W7-hard-craft", refilled_board_sha256=BOARD, gates=_all_pass(), craft=craft
    )
    assert not result.release_qualified
    assert result.blocker_ids == ("routing_craft:acute-copper-1",)


def test_zero_evaluated_objects_cannot_be_a_pass() -> None:
    with pytest.raises(ValidationError, match="zero evaluated objects cannot become PASS"):
        QualificationGate(
            gate_id="kicad_integrity",
            board_sha256=BOARD,
            disposition=QualificationDisposition.PASS,
            applicable=True,
            evaluated_object_count=0,
            evidence_fingerprints=(EVIDENCE,),
            finding_ids=(),
        )


def test_mixed_board_hashes_and_missing_gates_fail_closed() -> None:
    mixed = list(_all_pass())
    mixed[0] = _gate(mixed[0].gate_id, board="c" * 64)
    with pytest.raises(ValidationError, match="mixed board revisions"):
        WholeBoardQualification.build(
            case_id="W7-mixed",
            refilled_board_sha256=BOARD,
            gates=tuple(mixed),
            craft=_craft(),
        )
    with pytest.raises(ValidationError, match="required qualification gates are missing"):
        WholeBoardQualification.build(
            case_id="W7-missing",
            refilled_board_sha256=BOARD,
            gates=_all_pass()[:-1],
            craft=_craft(),
        )
