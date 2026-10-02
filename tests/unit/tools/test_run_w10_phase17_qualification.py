from __future__ import annotations

import json
from pathlib import Path

from tools.run_w10_phase17_qualification import _case_records, _hard_set_inventory


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_historical_success_is_never_reused_as_w10_pass(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    board = corpus / "boards" / "case.kicad_pcb"
    board.parent.mkdir(parents=True)
    board.write_text("(kicad_pcb)", encoding="utf-8")
    import hashlib

    board_hash = hashlib.sha256(board.read_bytes()).hexdigest()
    _write(
        corpus / "results.json",
        {
            "cases": [
                {
                    "case_id": "RT01",
                    "tier": "very_simple",
                    "routed_board": "boards/case.kicad_pcb",
                    "routed_board_sha256": board_hash,
                    "success": True,
                    "unconnected": 0,
                    "drc_violations": 0,
                }
            ]
        },
    )
    record = _case_records(corpus, live_drc=False)[0]
    assert record["historical_hash_matches"]
    assert record["historical_success"]
    assert not record["historical_label_reused_as_w10_pass"]


def test_hard_set_inventory_preserves_silk_as_a_separate_gate(tmp_path: Path) -> None:
    hard = tmp_path / "hard"
    board = hard / "boards" / "RT01-case" / "RT01-placement.kicad_pcb"
    board.parent.mkdir(parents=True)
    board.write_text("(kicad_pcb)", encoding="utf-8")
    _write(
        hard / "generation-summary.json",
        {
            "cases": [
                {"case_id": "RT01", "placement_board": "boards/RT01-case/RT01-placement.kicad_pcb"}
            ]
        },
    )
    _write(
        hard / "placement-preflight-summary.json",
        {
            "cases": [
                {
                    "case_id": "RT01",
                    "placement_geometry_clean": True,
                    "silkscreen_clean": False,
                }
            ]
        },
    )
    record = _hard_set_inventory(hard)[0]
    assert record["placement_geometry_clean"] is True
    assert record["silkscreen_clean"] is False
    assert record["retained_freerouting_2_3_candidate_count"] == 0
