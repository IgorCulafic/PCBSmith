from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.parity_repair_transaction import (
    ParityAuthority,
    compare_parity,
    parse_kicad_parity_report,
    run_parity_candidate_transaction,
)


def _report(path: Path, findings: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"schematic_parity": findings}), encoding="utf-8")
    return path


def _finding(kind: str, description: str, item: str = "Footprint U1") -> dict[str, object]:
    return {
        "type": kind,
        "description": description,
        "severity": "warning",
        "items": [{"description": item, "uuid": "x"}],
    }


def test_parser_distinguishes_namespace_from_real_pin_map_conflict(tmp_path: Path) -> None:
    report = _report(
        tmp_path / "drc.json",
        [
            _finding(
                "net_conflict",
                "Pad net (GND) doesn't match net given by schematic (/GND)",
                "Pad 2 [GND] of U1 on F.Cu",
            ),
            _finding(
                "net_conflict",
                "Pad net (VIN) doesn't match net given by schematic (/GND)",
                "Pad 1 [VIN] of U1 on F.Cu",
            ),
        ],
    )
    evidence = parse_kicad_parity_report(report)
    assert {item.authority for item in evidence.items} == {
        ParityAuthority.COMPONENT_MAP_REQUIRED,
        ParityAuthority.NAMESPACE_LOCAL,
    }
    assert evidence.component_blockers == ("component_map:U1:pad:1:pcb:VIN:schematic:/GND",)


def test_count_only_report_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "count.json"
    path.write_text('{"schematic_parity_count": 2}', encoding="utf-8")
    with pytest.raises(ValueError, match="detailed"):
        parse_kicad_parity_report(path)


def test_compare_parity_is_exact_and_deterministic(tmp_path: Path) -> None:
    item = _finding("extra_footprint", "Extra footprint", "Footprint J9")
    before = parse_kicad_parity_report(_report(tmp_path / "before.json", [item]))
    after = parse_kicad_parity_report(_report(tmp_path / "after.json", []))
    delta = compare_parity(before, after)
    assert delta.before_count == 1
    assert delta.after_count == 0
    assert len(delta.removed_item_ids) == 1
    assert not delta.added_item_ids


def test_transaction_isolated_and_accepts_clean_metadata_repair(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    board = project / "x.kicad_pcb"
    schematic = project / "x.kicad_sch"
    board.write_text("board", encoding="utf-8")
    schematic.write_text("old", encoding="utf-8")
    before = _report(
        tmp_path / "before.json",
        [_finding("footprint_symbol_field_mismatch", "description differs", "Footprint R1")],
    )

    def mutate(root: Path) -> None:
        (root / "x.kicad_sch").write_text("new", encoding="utf-8")

    def validate(root: Path) -> Path:
        return _report(root / "after.json", [])

    result = run_parity_candidate_transaction(
        project_files=(board, schematic),
        before_report=before,
        retained_root=tmp_path / "retained",
        mutator=mutate,
        validator=validate,
    )
    assert result.accepted
    assert result.changed_paths == ("x.kicad_sch",)
    assert not result.copper_changed
    assert board.read_text(encoding="utf-8") == "board"
    assert schematic.read_text(encoding="utf-8") == "old"


def test_transaction_rejects_unauthorized_board_change(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    board = project / "x.kicad_pcb"
    schematic = project / "x.kicad_sch"
    board.write_text("board", encoding="utf-8")
    schematic.write_text("schematic", encoding="utf-8")
    before = _report(tmp_path / "before.json", [])

    def mutate(root: Path) -> None:
        (root / "x.kicad_pcb").write_text("changed", encoding="utf-8")

    def validate(root: Path) -> Path:
        return _report(root / "after.json", [])

    result = run_parity_candidate_transaction(
        project_files=(board, schematic),
        before_report=before,
        retained_root=tmp_path / "retained",
        mutator=mutate,
        validator=validate,
    )
    assert not result.accepted
    assert result.blockers == ("unauthorized_physical_copper_change",)
