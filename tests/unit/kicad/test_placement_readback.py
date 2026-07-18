"""Semantic and live-KiCad tests for the R5 save/read-back authority."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_placement_serialization import _build, _component

from pcbsmith.kicad.board import BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.library import QuotedString, SExpr, parse_sexpr
from pcbsmith.kicad.placement_readback import (
    PlacementKiCadSaveRoundtripAuthority,
    extract_kicad_board_readback,
    verify_placement_kicad_save_roundtrip,
)
from pcbsmith.kicad.placement_serialization import build_placement_serialization_authority
from pcbsmith.placement_serialization_ir import PlacementSerializationAuthority


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lists(node: SExpr) -> list[list[SExpr]]:
    if not isinstance(node, list):
        return []
    return [node, *(nested for child in node for nested in _lists(child))]


def _retained_authority() -> PlacementKiCadSaveRoundtripAuthority:
    serialization = _build()
    text = serialization.rendered_board_text
    snapshot = extract_kicad_board_readback(text)
    report = json.dumps(
        {"schematic_parity": [], "unconnected_items": [], "violations": []},
        sort_keys=True,
        separators=(",", ":"),
    )
    return PlacementKiCadSaveRoundtripAuthority(
        serialization_authority=serialization,
        kicad_cli_version="10.0-test",
        initial_board_text=text,
        saved_board_text=text,
        initial_board_sha256=_sha256(text),
        saved_board_sha256=_sha256(text),
        repeated_saved_board_sha256=_sha256(text),
        initial_snapshot=snapshot,
        saved_snapshot=snapshot,
        drc_status="passed",
        drc_report_json=report,
        drc_report_sha256=_sha256(report),
    )


def _clean_shaped_authority() -> PlacementSerializationAuthority:
    component = _component("R1")
    layout = BoardLayout(
        placements=((component, 8.0),),
        segments=(),
        vias=(),
        width_mm=16.0,
        height_mm=12.0,
        part_y_mm=(("R1", 6.0),),
        part_rotation=(("R1", 25.0),),
        outline=(
            (0.0, 2.0),
            (2.0, 0.0),
            (14.0, 0.0),
            (16.0, 2.0),
            (16.0, 10.0),
            (14.0, 12.0),
            (2.0, 12.0),
            (0.0, 10.0),
        ),
    )
    netlist = BoardNetlist(
        components=(component,),
        nets=(BoardNet("/LOCAL", (("R1", "1"),)),),
    )
    return build_placement_serialization_authority(
        layout,
        netlist,
        layout,
        ("/LOCAL",),
        ("R1",),
    )


def test_numeric_spelling_and_direct_clause_order_are_semantically_stable() -> None:
    text = _build().rendered_board_text
    numeric_variant = text.replace("(at 26.25 26 17)", "(at 26.2500 26.000 17.0)", 1)
    assert numeric_variant != text
    assert extract_kicad_board_readback(numeric_variant) == extract_kicad_board_readback(text)


def test_kicad_implicit_duplicate_pad_jumper_default_is_semantically_stable() -> None:
    text = _build().rendered_board_text
    footprint_prefix = '(footprint "Resistor_SMD:R_0603_1608Metric"\n'
    assert footprint_prefix in text
    explicit_no = text.replace(
        footprint_prefix,
        footprint_prefix + "    (duplicate_pad_numbers_are_jumpers no)\n",
        1,
    )
    explicit_yes = explicit_no.replace(
        "(duplicate_pad_numbers_are_jumpers no)",
        "(duplicate_pad_numbers_are_jumpers yes)",
        1,
    )

    baseline = extract_kicad_board_readback(text)
    assert extract_kicad_board_readback(explicit_no) == baseline
    assert extract_kicad_board_readback(explicit_yes).footprints != baseline.footprints


def test_renderer_uses_only_kicad_10_named_net_clauses() -> None:
    root = parse_sexpr(_build().rendered_board_text)
    net_clauses = [item for item in _lists(root) if item and item[0] == "net"]
    assert net_clauses
    assert all(len(item) == 2 and isinstance(item[1], QuotedString) for item in net_clauses)


@pytest.mark.parametrize(
    ("old", "new", "surface"),
    [
        ("(at 26.25 26 17)", "(at 26.26 26 17)", "footprints"),
        ("(xy 50 20)", "(xy 49.9 20)", "edge_cuts"),
        ('(gr_text "R5.6b sentinel"', '(gr_text "changed"', "board_graphics"),
        ("(min_thickness 0.25)", "(min_thickness 0.26)", "zones"),
        ("(width 0.23)", "(width 0.24)", "segments"),
        ("(size 0.66)", "(size 0.67)", "vias"),
        ('(net "/TARGET")', '(net "/TARGET-CHANGED")', "nets"),
        ('(31 "B.Cu" signal)', '(31 "B.Cu" power)', "layers"),
    ],
)
def test_each_claimed_semantic_surface_detects_a_change(
    old: str,
    new: str,
    surface: str,
) -> None:
    text = _build().rendered_board_text
    assert old in text
    changed = text.replace(old, new, 1)
    before = extract_kicad_board_readback(text)
    after = extract_kicad_board_readback(changed)
    assert getattr(before, surface) != getattr(after, surface)
    for other in (
        "footprints",
        "edge_cuts",
        "board_graphics",
        "zones",
        "segments",
        "vias",
        "nets",
        "layers",
        "setup",
    ):
        net_rename_dependents = {"footprints", "segments", "vias"}
        if other != surface and not (surface == "nets" and other in net_rename_dependents):
            assert getattr(before, other) == getattr(after, other)


def test_setup_is_part_of_the_closed_surface_when_present() -> None:
    text = _build().rendered_board_text
    first = text.removesuffix(")\n") + "  (setup (pad_to_mask_clearance 0))\n)\n"
    second = first.replace("(pad_to_mask_clearance 0)", "(pad_to_mask_clearance 0.01)")
    before = extract_kicad_board_readback(first)
    after = extract_kicad_board_readback(second)
    assert before.setup != after.setup
    for surface in (
        "footprints",
        "edge_cuts",
        "board_graphics",
        "zones",
        "segments",
        "vias",
        "nets",
        "layers",
    ):
        assert getattr(before, surface) == getattr(after, surface)


def test_complete_authority_roundtrips_and_rejects_tamper() -> None:
    authority = _retained_authority()
    assert (
        PlacementKiCadSaveRoundtripAuthority.model_validate_json(authority.model_dump_json())
        == authority
    )

    payload = authority.model_dump(mode="json")
    payload["saved_board_text"] = payload["saved_board_text"].replace(
        "(at 26.25 26 17)", "(at 26.26 26 17)", 1
    )
    payload["saved_board_sha256"] = _sha256(payload["saved_board_text"])
    payload["repeated_saved_board_sha256"] = payload["saved_board_sha256"]
    with pytest.raises(ValidationError, match="snapshot is stale"):
        PlacementKiCadSaveRoundtripAuthority.model_validate(payload)


def test_required_drc_pass_rejects_findings() -> None:
    payload = _retained_authority().model_dump(mode="json")
    payload["drc_status"] = "failed"
    payload["drc_findings"] = ["one exact finding"]
    with pytest.raises(ValidationError, match="DRC did not pass"):
        PlacementKiCadSaveRoundtripAuthority.model_validate(payload)


def test_report_execution_timestamp_is_not_valid_retained_authority() -> None:
    payload = _retained_authority().model_dump(mode="json")
    report = json.loads(payload["drc_report_json"])
    report["date"] = "2026-07-17T21:54:43"
    payload["drc_report_json"] = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload["drc_report_sha256"] = _sha256(payload["drc_report_json"])
    with pytest.raises(ValidationError, match="execution date"):
        PlacementKiCadSaveRoundtripAuthority.model_validate(payload)


@pytest.mark.skipif(
    os.environ.get("PCBSMITH_R5_KICAD_GOLDEN") != "1",
    reason="set PCBSMITH_R5_KICAD_GOLDEN=1 to exercise the installed KiCad CLI",
)
def test_live_kicad_save_readback_is_deterministic(tmp_path: Path) -> None:
    result = verify_placement_kicad_save_roundtrip(
        _clean_shaped_authority(),
        tmp_path,
        require_drc_pass=True,
    )
    assert result.kicad_cli_version
    assert result.initial_snapshot == result.saved_snapshot
    assert result.saved_board_sha256 == result.repeated_saved_board_sha256
    assert result.drc_status == "passed"
    assert not result.drc_findings


@pytest.mark.skipif(
    os.environ.get("PCBSMITH_R5_KICAD_GOLDEN") != "1",
    reason="set PCBSMITH_R5_KICAD_GOLDEN=1 to exercise the installed KiCad CLI",
)
def test_live_kicad_rejects_a_semantically_rewritten_dirty_board(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="semantic surface"):
        verify_placement_kicad_save_roundtrip(
            _build(),
            tmp_path,
            require_drc_pass=False,
        )
