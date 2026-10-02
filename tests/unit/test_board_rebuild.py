from __future__ import annotations

import json

import pytest

from pcbsmith.board_rebuild import RebuildDecision, require_generation_mode
from pcbsmith.manufacturing_lineage import file_sha256, native_input_hashes


def decision(board, **kwargs):
    return RebuildDecision(
        source_inputs=native_input_hashes(board),
        rationale="Approved circuit interface change invalidates this fixture layout",
        authorization_reference="synthetic test authorization",
        invalidated_requirements=("interface",),
        local_alternatives=("preserving the old connector would violate the new interface",),
        **kwargs,
    )


def test_initial_generation_existing_board_and_missing_predecessor(tmp_path):
    sch = tmp_path / "board.kicad_sch"
    sch.write_text("(kicad_sch)")
    assert require_generation_mode(sch, None) is None
    board = sch.with_suffix(".kicad_pcb")
    board.write_text("(kicad_pcb)")
    with pytest.raises(ValueError, match="existing PCB"):
        require_generation_mode(sch, None)
    req = decision(board, reason="interface_or_layer_change")
    assert require_generation_mode(sch, req) == board
    sch.write_text("(kicad_sch (changed yes))")
    with pytest.raises(ValueError, match="exact current"):
        require_generation_mode(sch, req)
    board.unlink()
    journal = tmp_path / ".pcbsmith/accepted-board-edits.json"
    journal.parent.mkdir()
    journal.write_text("{}")
    with pytest.raises(ValueError, match="cannot be discarded"):
        require_generation_mode(sch, None)


def test_exhaustion_requires_a_retained_failed_attempt_of_this_source(tmp_path):
    sch = tmp_path / "board.kicad_sch"
    sch.write_text("(kicad_sch)")
    board = sch.with_suffix(".kicad_pcb")
    board.write_text("(kicad_pcb)")
    with pytest.raises(ValueError, match="retained attempt"):
        require_generation_mode(sch, decision(board, reason="exhausted_local_repairs"))
    evidence = tmp_path / "attempt.json"
    for status in ("digitally_checked_candidate", "blocked_candidate"):
        evidence.write_text(
            json.dumps(
                {
                    "schema": "pcbsmith-board-revision-v1",
                    "status": status,
                    "source_inputs": native_input_hashes(board),
                }
            )
        )
        req = decision(
            board,
            reason="exhausted_local_repairs",
            retained_attempts={"attempt.json": file_sha256(evidence)},
        )
        if status == "blocked_candidate":
            assert require_generation_mode(sch, req) == board
        else:
            with pytest.raises(ValueError, match="not a failed edit"):
                require_generation_mode(sch, req)
    evidence.write_text("{}")
    with pytest.raises(ValueError, match="stale"):
        require_generation_mode(sch, req)


def test_accepted_native_edits_are_bound_to_rebuild_decision(tmp_path):
    from pcbsmith.board_rebuild import rebuild_input_hashes

    sch = tmp_path / "board.kicad_sch"
    sch.write_text("(kicad_sch)")
    board = sch.with_suffix(".kicad_pcb")
    board.write_text("(kicad_pcb)")
    req = decision(board, reason="architecture_change")
    ledger = tmp_path / ".pcbsmith/accepted-board-edits.json"
    ledger.parent.mkdir()
    ledger.write_text('{"schema":"pcbsmith-working-edits-v1","edits":[]}')
    with pytest.raises(ValueError, match="exact current"):
        require_generation_mode(sch, req)
    req = req.model_copy(update={"source_inputs": rebuild_input_hashes(board)})
    assert require_generation_mode(sch, req) == board
    ledger.write_text("{}")
    with pytest.raises(ValueError, match="exact current"):
        require_generation_mode(sch, req)


def test_rebuild_authority_binds_local_models_libraries_and_child_sheets(tmp_path):
    from pcbsmith.board_rebuild import rebuild_input_hashes

    sch = tmp_path / "board.kicad_sch"
    sch.write_text('(kicad_sch (sheet (property "Sheetfile" "child.kicad_sch")))')
    (tmp_path / "child.kicad_sch").write_text("(kicad_sch)")
    board = sch.with_suffix(".kicad_pcb")
    board.write_text('(kicad_pcb (footprint "test" (model "part.step")))')
    (tmp_path / "part.step").write_text("synthetic model")
    (tmp_path / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "local") (uri "${KIPRJMOD}/local.kicad_sym")))'
    )
    (tmp_path / "local.kicad_sym").write_text("(kicad_symbol_lib)")
    req = decision(board, reason="architecture_change").model_copy(
        update={"source_inputs": rebuild_input_hashes(board)}
    )
    assert {"child.kicad_sch", "part.step", "local.kicad_sym"} <= req.source_inputs.keys()
    for filename in ("child.kicad_sch", "part.step", "local.kicad_sym"):
        path = tmp_path / filename
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with pytest.raises(ValueError, match="exact current"):
            require_generation_mode(sch, req)
        path.write_bytes(original)
    assert require_generation_mode(sch, req) == board
