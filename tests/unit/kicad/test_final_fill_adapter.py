from __future__ import annotations

import hashlib
from pathlib import Path

from pcbsmith.kicad.final_fill_adapter import (
    FillReachability,
    parse_kicad_final_fill_snapshot,
)

BOARD = """(kicad_pcb
  (version 20251126)
  (generator pcbsmith-test)
  (zone
    (net "GND")
    (layer "B.Cu")
    (uuid "00000000-0000-0000-0000-000000000001")
    (priority 2)
    (connect_pads yes (clearance 0.3))
    (min_thickness 0.25)
    (fill yes (thermal_gap 0.4) (thermal_bridge_width 0.5) (island_removal_mode 1))
    (polygon (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10)))
    {filled}
  )
)"""


def test_final_fill_parser_retains_intent_and_each_connected_region(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_pcb"
    filled = tmp_path / "filled.kicad_pcb"
    source.write_text(BOARD.format(filled=""), encoding="utf-8")
    filled.write_text(
        BOARD.format(
            filled="""
    (filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 4 0) (xy 4 4) (xy 0 4)))
    (filled_polygon (layer "B.Cu") (pts (xy 6 6) (xy 10 6) (xy 10 10) (xy 6 10)))
"""
        ),
        encoding="utf-8",
    )

    snapshot = parse_kicad_final_fill_snapshot(
        source,
        filled,
        kicad_version="10.0-test",
        refilled_by_kicad=True,
    )

    assert snapshot.zone_intent_unchanged
    assert not snapshot.stale_fill
    assert len(snapshot.regions) == 2
    assert all(item.reachability is FillReachability.UNVERIFIED for item in snapshot.regions)
    assert snapshot.zones[0].thermal_bridge_width_mm == 0.5
    assert snapshot.zones[0].island_removal_mode == 1
    assert snapshot.filled_board_sha256 == hashlib.sha256(filled.read_bytes()).hexdigest()


def test_missing_refill_or_changed_intent_is_stale(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_pcb"
    changed = tmp_path / "changed.kicad_pcb"
    source.write_text(BOARD.format(filled=""), encoding="utf-8")
    changed.write_text(
        BOARD.replace("(priority 2)", "(priority 3)").format(
            filled=('(filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 4 0) (xy 4 4) (xy 0 4)))')
        ),
        encoding="utf-8",
    )

    snapshot = parse_kicad_final_fill_snapshot(
        source,
        changed,
        kicad_version="10.0-test",
        refilled_by_kicad=False,
    )

    assert not snapshot.zone_intent_unchanged
    assert snapshot.stale_fill


def test_native_refill_retains_rules_and_rejects_context_mutation(tmp_path, monkeypatch):
    import json

    import pytest

    import pcbsmith.kicad.final_fill_adapter as adapter
    from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult

    source = tmp_path / "source" / "fixture.kicad_pcb"
    source.parent.mkdir()
    source.write_text(BOARD.format(filled="").replace("(fill yes", "(fill"))
    source.with_suffix(".kicad_pro").write_text(
        '{"board_design_settings": {"rules": {"min_clearance": 0.5}}}'
    )
    source.with_suffix(".kicad_dru").write_text("(version 1)")
    monkeypatch.setattr(
        adapter,
        "find_kicad_cli",
        lambda: KiCadInstall(path=tmp_path / "test-only-cli", source="test"),
    )
    corrupt = False

    def run(command):
        if command[-1] == "--version":
            return KiCadProcessResult(
                command=tuple(map(str, command)), returncode=0, stdout="10.0.3", stderr=""
            )
        candidate = Path(command[-1])
        assert (
            candidate.with_suffix(".kicad_pro").read_bytes()
            == source.with_suffix(".kicad_pro").read_bytes()
        )
        assert candidate.with_suffix(".kicad_dru").read_bytes() == b"(version 1)"
        candidate.write_text(
            BOARD.format(filled='(filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 4 0) (xy 4 4)))')
        )
        if corrupt:
            candidate.with_suffix(".kicad_dru").write_text("weakened rules")
        report = Path(command[command.index("--output") + 1])
        report.write_text(
            json.dumps(
                {
                    "$schema": "https://schemas.kicad.org/drc.v1.json",
                    "source": candidate.name,
                    "date": "2026-09-06T00:00:00",
                    "kicad_version": "10.0.3",
                    "coordinate_units": "mm",
                    "violations": [],
                    "unconnected_items": [],
                    "schematic_parity": [],
                }
            )
        )
        return KiCadProcessResult(
            command=tuple(map(str, command)), returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(adapter, "run_kicad_process", run)
    _, snapshot = adapter.refill_and_read_kicad_board(source, tmp_path / "good")
    assert not snapshot.stale_fill
    corrupt = True
    with pytest.raises(ValueError, match="rules or dependencies"):
        adapter.refill_and_read_kicad_board(source, tmp_path / "bad")
    assert source.with_suffix(".kicad_dru").read_bytes() == b"(version 1)"
