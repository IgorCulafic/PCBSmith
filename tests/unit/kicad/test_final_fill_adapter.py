from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("mutation", [None, "priority", "uuid", "layer", "clearance"])
def test_native_zone_reordering_preserves_uuid_bound_intent_only(tmp_path, mutation):
    from pcbsmith.kicad.library import _children, parse_sexpr, serialize_sexpr

    tree = parse_sexpr(
        BOARD.format(filled='(filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 4 0) (xy 4 4)))')
    )
    second = parse_sexpr(
        serialize_sexpr(_children(tree, "zone")[0]).replace(
            "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
        )
    )
    tree.append(second)
    source, filled = tmp_path / "source.kicad_pcb", tmp_path / "filled.kicad_pcb"
    source.write_text(serialize_sexpr(tree))
    tree[-2:] = reversed(tree[-2:])
    text = serialize_sexpr(tree)
    if mutation:
        before, after = {
            "priority": ("(priority 2)", "(priority 3)"),
            "uuid": (
                "00000000-0000-0000-0000-000000000002",
                "00000000-0000-0000-0000-000000000003",
            ),
            "layer": ('(layer "B.Cu")', '(layer "In1.Cu")'),
            "clearance": ("(clearance 0.3)", "(clearance 0.4)"),
        }[mutation]
        text = text.replace(before, after)
    filled.write_text(text)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="test", refilled_by_kicad=True
    )
    assert snapshot.zone_identity_authority == "uuid-bound-zone-intent-v2"
    assert snapshot.zone_intent_unchanged == (mutation is None)
    assert snapshot.stale_fill == (mutation is not None)


@pytest.mark.parametrize("clause", ['(layers "F.Cu" "B.Cu")', "(keepout (tracks not_allowed))"])
def test_unsupported_zone_inventory_cannot_be_reported_as_missing_or_clean(tmp_path, clause):
    board = tmp_path / "unsupported.kicad_pcb"
    board.write_text(BOARD.format(filled="").replace("(priority 2)", clause))
    with pytest.raises(ValueError, match="one copper layer per non-rule-area zone"):
        parse_kicad_final_fill_snapshot(
            board, board, kicad_version="10.0.6", refilled_by_kicad=True
        )


@pytest.mark.parametrize(
    "field,value",
    [("layer", "In1.Cu"), ("net_name", "OTHER"), ("source_artifact_sha256", "f" * 64)],
)
def test_snapshot_rejects_region_from_another_authority(tmp_path, field, value):
    from pcbsmith.kicad.final_fill_adapter import KiCadFilledCopperRegion, KiCadFinalFillSnapshot

    board = tmp_path / "fixture.kicad_pcb"
    board.write_text(
        BOARD.format(filled='(filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 4 0) (xy 4 4)))')
    )
    snapshot = parse_kicad_final_fill_snapshot(
        board, board, kicad_version="10.0.6", refilled_by_kicad=True
    )
    region = snapshot.regions[0].model_dump(exclude={"region_fingerprint"})
    region[field] = value
    foreign = KiCadFilledCopperRegion.build(**region)
    values = snapshot.model_dump(
        exclude={
            "snapshot_fingerprint",
            "zone_intent_unchanged",
            "stale_fill",
            "unverified_region_ids",
            "regions",
            "zones",
        }
    )
    with pytest.raises(ValueError, match="zone and board authority"):
        KiCadFinalFillSnapshot.build(**values, regions=(foreign,), zones=snapshot.zones)


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
    candidate, snapshot = adapter.refill_and_read_kicad_board(source, tmp_path / "good")
    assert not snapshot.stale_fill
    report = candidate.parent / "fill-drc.json"
    execution = adapter.verify_native_fill_execution(candidate, report)
    assert execution["board_sha256"] == snapshot.filled_board_sha256
    candidate.with_suffix(".kicad_dru").write_text("changed after native execution")
    with pytest.raises(ValueError, match="inputs or report changed"):
        adapter.verify_native_fill_execution(candidate, report)
    candidate.with_suffix(".kicad_dru").write_text("(version 1)")
    report.write_text(report.read_text() + "\n")
    with pytest.raises(ValueError, match="inputs or report changed"):
        adapter.verify_native_fill_execution(candidate, report)
    corrupt = True
    with pytest.raises(ValueError, match="rules or dependencies"):
        adapter.refill_and_read_kicad_board(source, tmp_path / "bad")
    assert source.with_suffix(".kicad_dru").read_bytes() == b"(version 1)"
