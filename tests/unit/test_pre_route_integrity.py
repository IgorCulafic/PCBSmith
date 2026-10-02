from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.pre_route_integrity import inspect_pre_route_integrity


def _files(
    tmp_path: Path,
    *,
    erc_violations: list[dict[str, str]] | None = None,
    parity: list[dict[str, str]] | None = None,
    include_parity: bool = True,
    drc_source: str = "board.kicad_pcb",
    unconnected: list[dict[str, str]] | None = None,
) -> tuple[Path, Path, Path, Path]:
    board = tmp_path / "board.kicad_pcb"
    schematic = tmp_path / "board.kicad_sch"
    erc = tmp_path / "erc.json"
    drc = tmp_path / "drc.json"
    board.write_text("(kicad_pcb (version 20241229) (generator pcbnew))", encoding="utf-8")
    schematic.write_text("(kicad_sch (version 20231120) (generator eeschema))", encoding="utf-8")
    erc.write_text(
        json.dumps(
            {
                "source": schematic.name,
                "sheets": [{"violations": erc_violations or []}],
            }
        ),
        encoding="utf-8",
    )
    payload: dict[str, object] = {
        "source": drc_source,
        "violations": [],
        "unconnected_items": unconnected or [],
    }
    if include_parity:
        payload["schematic_parity"] = parity or []
    drc.write_text(json.dumps(payload), encoding="utf-8")
    return board, schematic, erc, drc


def test_clean_erc_and_explicit_clean_parity_accept_exact_placement(tmp_path: Path) -> None:
    board, schematic, erc, drc = _files(tmp_path)

    evidence = inspect_pre_route_integrity(
        board_file=board,
        schematic_file=schematic,
        erc_report=erc,
        drc_report=drc,
    )

    assert evidence.accepted
    assert evidence.schematic_parity_evaluated
    assert not evidence.blockers


def test_absent_parity_section_is_not_treated_as_zero_findings(tmp_path: Path) -> None:
    board, schematic, erc, drc = _files(tmp_path, include_parity=False)
    # The shared parser now rejects incomplete reports before producing evidence.
    with pytest.raises(ValueError, match="schematic_parity must be a list"):
        inspect_pre_route_integrity(
            board_file=board,
            schematic_file=schematic,
            erc_report=erc,
            drc_report=drc,
        )


def test_erc_and_parity_findings_both_block_routing(tmp_path: Path) -> None:
    finding = {"severity": "error", "description": "fixture finding"}
    board, schematic, erc, drc = _files(
        tmp_path,
        erc_violations=[finding],
        parity=[finding],
    )

    evidence = inspect_pre_route_integrity(
        board_file=board,
        schematic_file=schematic,
        erc_report=erc,
        drc_report=drc,
    )

    assert not evidence.accepted
    assert "erc_findings:1" in evidence.blockers
    assert "schematic_parity_findings:1" in evidence.blockers


def test_report_source_mismatch_is_rejected_before_counting(tmp_path: Path) -> None:
    board, schematic, erc, drc = _files(tmp_path, drc_source="other.kicad_pcb")

    with pytest.raises(ValueError, match="does not name the supplied board"):
        inspect_pre_route_integrity(
            board_file=board,
            schematic_file=schematic,
            erc_report=erc,
            drc_report=drc,
        )


def test_unconnected_items_are_recorded_but_deferred_until_post_route(tmp_path: Path) -> None:
    finding = {"severity": "error", "description": "expected unrouted net"}
    board, schematic, erc, drc = _files(tmp_path, unconnected=[finding])

    evidence = inspect_pre_route_integrity(
        board_file=board,
        schematic_file=schematic,
        erc_report=erc,
        drc_report=drc,
    )

    assert evidence.drc_unconnected_item_count == 1
    assert evidence.accepted
    assert not evidence.blockers
