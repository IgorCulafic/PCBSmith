from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.production_evidence_fixtures import write_marking_example

from pcbsmith.bounded_local_repair import LocalRepairBudget
from pcbsmith.marking_repair_integration import build_marking_repair_plan
from pcbsmith.production_marking_adapter import (
    ProductionMarkingRequirements,
    audit_kicad_production_markings,
    inspect_saved_board_markings,
)


def _budget() -> LocalRepairBudget:
    return LocalRepairBudget(
        maximum_displacement_mm=3.0,
        maximum_ripped_segment_count=0,
        maximum_ripped_via_count=0,
        maximum_added_segment_count=0,
        maximum_added_via_count=0,
        maximum_attempt_count=4,
        maximum_elapsed_seconds=60.0,
    )


def _synthetic_markings(tmp_path: Path):
    board, drc = write_marking_example(tmp_path)
    inventory = inspect_saved_board_markings(board)
    requirements = ProductionMarkingRequirements.build(
        board_sha256=inventory.board_sha256,
        source_authority_sha256="c" * 64,
        declaration_complete=False,
        required_refdes_refs=inventory.footprint_refs,
    )
    audit = audit_kicad_production_markings(
        inventory=inventory,
        requirements=requirements,
        drc_report=drc,
        drc_report_board_sha256=inventory.board_sha256,
    )
    return audit, drc


def test_marking_findings_become_bounded_local_requests(tmp_path: Path) -> None:
    audit, drc = _synthetic_markings(tmp_path)
    plan = build_marking_repair_plan(
        audit=audit,
        drc_report=drc,
        source_qualification_fingerprint="d" * 64,
        budget=_budget(),
    )
    assert len(plan.repair_requests) == 11
    assert plan.unlocalized_finding_ids == ()
    assert all(
        request.source_board_sha256 == audit.board_sha256 for request in plan.repair_requests
    )
    assert all(request.rip_authorized_copper_ids == () for request in plan.repair_requests)
    assert any(request.immutable_object_ids for request in plan.repair_requests)


def test_repair_plan_rejects_drc_other_than_audited_report(tmp_path: Path) -> None:
    audit, _drc = _synthetic_markings(tmp_path)
    foreign = tmp_path / "drc.json"
    foreign.write_text('{"violations": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        build_marking_repair_plan(
            audit=audit,
            drc_report=foreign,
            source_qualification_fingerprint="d" * 64,
            budget=_budget(),
        )
