from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.unit.production_evidence_fixtures import write_marking_example

from pcbsmith.production_marking_adapter import (
    ProductionMarkingRequirements,
    _drc_finding_id,
    audit_kicad_production_markings,
    inspect_saved_board_markings,
)


def _board(tmp_path: Path, *, hide: bool = False) -> Path:
    hidden = "(hide yes)" if hide else ""
    board = tmp_path / "board.kicad_pcb"
    board.write_text(
        f"""(kicad_pcb (version 20241229)
          (footprint "Resistor_SMD:R_0603_1608Metric"
            (layer "F.Cu")
            (property "Reference" "R1" (at 0 0) (layer "F.SilkS") {hidden})
            (fp_line (start 0 0) (end 1 0) (stroke (width 0.1) (type solid))
              (layer "F.SilkS"))))""",
        encoding="utf-8",
    )
    return board


def _requirements(board: Path, *, complete: bool = True):
    return ProductionMarkingRequirements.build(
        board_sha256=hashlib.sha256(board.read_bytes()).hexdigest(),
        source_authority_sha256="b" * 64,
        declaration_complete=complete,
        required_refdes_refs=("R1",),
    )


def _drc(tmp_path: Path, violations: list[dict[str, object]]) -> Path:
    path = tmp_path / "drc.json"
    path.write_text(json.dumps({"violations": violations}), encoding="utf-8")
    return path


def test_exact_saved_board_inventory_and_empty_drc_can_clear_marking_gate(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path)
    inventory = inspect_saved_board_markings(board)
    audit = audit_kicad_production_markings(
        inventory=inventory,
        requirements=_requirements(board),
        drc_report=_drc(tmp_path, []),
        drc_report_board_sha256=inventory.board_sha256,
    )
    assert audit.inspected_mark_count == 2
    assert audit.finding_ids == ()
    assert audit.unverified_check_ids == ()


def test_hidden_refdes_and_incomplete_requirements_fail_closed(tmp_path: Path) -> None:
    board = _board(tmp_path, hide=True)
    inventory = inspect_saved_board_markings(board)
    audit = audit_kicad_production_markings(
        inventory=inventory,
        requirements=_requirements(board, complete=False),
        drc_report=_drc(tmp_path, []),
        drc_report_board_sha256=inventory.board_sha256,
    )
    assert audit.missing_refdes_finding_ids == ("missing_refdes:R1",)
    assert audit.unverified_check_ids == ("requirements_declaration_incomplete",)


def test_drc_categories_are_retained(tmp_path: Path) -> None:
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
    assert len(audit.silk_over_copper_finding_ids) == 8
    assert len(audit.silk_over_silk_finding_ids) == 3
    assert audit.missing_refdes_finding_ids == ()
    assert audit.unverified_check_ids == ("requirements_declaration_incomplete",)


def test_drc_finding_identity_is_stable_when_report_order_changes() -> None:
    violation = {
        "type": "silk_overlap",
        "items": [{"uuid": "b"}, {"uuid": "a"}],
    }
    assert _drc_finding_id(0, violation) == _drc_finding_id(99, violation)


def test_saved_board_inventory_verifies_declared_polarity_and_mating_visibility(
    tmp_path: Path,
) -> None:
    board = tmp_path / "semantic-marks.kicad_pcb"
    board.write_text(
        """(kicad_pcb (version 20241229)
          (footprint "PCBSmith:LED"
            (layer "F.Cu")
            (property "Reference" "LED1" (at 0 0) (layer "F.SilkS"))
            (property "PCBSmith_Polarity" "1=K;2=A" (at 0 0) (layer "F.Fab")
              (effects (font (size 0.5 0.5)) (hide yes)))
            (fp_text user "K" (at -2 0) (layer "F.SilkS")))
          (footprint "PCBSmith:CONN"
            (layer "F.Cu")
            (property "Reference" "J1" (at 0 0) (layer "F.SilkS"))
            (property "PCBSmith_Mating" "VIN" (at 0 0) (layer "F.Fab")
              (effects (font (size 0.5 0.5)) (hide yes))))
          (gr_text "VIN 7-24V" (at 2 2) (layer "F.SilkS")))""",
        encoding="utf-8",
    )
    inventory = inspect_saved_board_markings(board)
    assert inventory.polarity_semantics_supported
    assert inventory.connector_mating_semantics_supported
    assert inventory.verified_polarity_refs == ("LED1",)
    assert inventory.verified_connector_mating_refs == ("J1",)

    requirements = ProductionMarkingRequirements.build(
        board_sha256=inventory.board_sha256,
        source_authority_sha256="d" * 64,
        declaration_complete=True,
        required_refdes_refs=("J1", "LED1"),
        required_polarity_refs=("LED1",),
        required_connector_mating_refs=("J1",),
    )
    audit = audit_kicad_production_markings(
        inventory=inventory,
        requirements=requirements,
        drc_report=_drc(tmp_path, []),
        drc_report_board_sha256=inventory.board_sha256,
    )
    assert audit.finding_ids == ()
    assert audit.unverified_check_ids == ()


def test_declared_polarity_without_visible_marker_fails_closed(tmp_path: Path) -> None:
    board = tmp_path / "missing-marker.kicad_pcb"
    board.write_text(
        """(kicad_pcb (version 20241229)
          (footprint "PCBSmith:LED"
            (layer "F.Cu")
            (property "Reference" "LED1" (at 0 0) (layer "F.SilkS"))
            (property "PCBSmith_Polarity" "1=K;2=A" (at 0 0) (layer "F.Fab")
              (effects (font (size 0.5 0.5)) (hide yes)))))""",
        encoding="utf-8",
    )
    inventory = inspect_saved_board_markings(board)
    requirements = ProductionMarkingRequirements.build(
        board_sha256=inventory.board_sha256,
        source_authority_sha256="e" * 64,
        declaration_complete=True,
        required_refdes_refs=("LED1",),
        required_polarity_refs=("LED1",),
    )
    audit = audit_kicad_production_markings(
        inventory=inventory,
        requirements=requirements,
        drc_report=_drc(tmp_path, []),
        drc_report_board_sha256=inventory.board_sha256,
    )
    assert audit.missing_polarity_finding_ids == ("missing_polarity:LED1",)


def test_requirements_build_canonicalizes_unsorted_reference_contracts() -> None:
    requirements = ProductionMarkingRequirements.build(
        board_sha256="a" * 64,
        source_authority_sha256="b" * 64,
        declaration_complete=True,
        required_refdes_refs=("U1", "J1", "C1"),
        required_polarity_refs=("D2", "D1"),
        required_connector_mating_refs=("J2", "J1"),
    )
    assert requirements.required_refdes_refs == ("C1", "J1", "U1")
    assert requirements.required_polarity_refs == ("D1", "D2")
    assert requirements.required_connector_mating_refs == ("J1", "J2")
