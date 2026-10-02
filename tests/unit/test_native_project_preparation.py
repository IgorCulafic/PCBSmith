from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.board_revision import BoardRevisionRequest, _require_unrouted_annotations
from pcbsmith.kicad.board import BoardComponent, BoardNetlist
from pcbsmith.kicad.layout_input import ReviewedLayoutInput
from pcbsmith.kicad.native_edits import NativeEdit
from pcbsmith.native_project import resolve_symbol


def test_unrouted_scope_rejects_geometry_changes():
    with pytest.raises(ValueError, match="only text/reference"):
        BoardRevisionRequest(
            source_inputs={"b": "0" * 64},
            rationale="move",
            validation_stage="unrouted_annotations",
            edits=(NativeEdit(kind="component", target="U1", position_mm=(1, 2)),),
        )


@pytest.mark.parametrize("object_type", ["segment", "arc", "via", "zone"])
def test_unrouted_scope_rejects_every_copper_kind(tmp_path, object_type):
    p = tmp_path / "board.kicad_pcb"
    p.write_text("(kicad_pcb (" + object_type + "))", encoding="utf-8")
    with pytest.raises(ValueError, match="no tracks"):
        _require_unrouted_annotations(p)


def test_existing_request_fingerprint_is_preserved():
    r = BoardRevisionRequest(
        source_inputs={"b": "0" * 64},
        rationale="move",
        edits=(NativeEdit(kind="text", target="x", position_mm=(1, 2)),),
    )
    payload = r.model_dump(mode="json")
    payload.pop("validation_stage")
    # Empty optional extensions remain absent from the retained legacy identity.
    for field in (
        "substitutions",
        "zero_ohm_links",
        "floorplan_bundle_path",
        "floorplan_origin_mm",
    ):
        payload.pop(field)
    assert r.semantic_json() == json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    different = r.model_copy(update={"validation_stage": "unrouted_annotations"})
    assert different.semantic_fingerprint() != r.semantic_fingerprint()


def test_layout_requires_exact_native_reference_coverage():
    n = BoardNetlist(
        components=(BoardComponent(reference="R1", value="1k", footprint="R:R", uuid_path="r"),),
        nets=(),
    )
    with pytest.raises(ValueError, match="exact native component"):
        ReviewedLayoutInput(width_mm=20, height_mm=20, placements={"R2": (1, 2, 0)}).bind(n)


@pytest.mark.parametrize("field", ["width_mm", "height_mm"])
def test_layout_rejects_nonfinite_dimensions(field):
    values = dict(width_mm=20, height_mm=20, placements={})
    values[field] = float("inf")
    with pytest.raises(ValueError):
        ReviewedLayoutInput(**values)


def test_symbol_resolver_rejects_cycles_and_path_escape(tmp_path):
    (tmp_path / "L.kicad_sym").write_text(
        '(kicad_symbol_lib (symbol "A" (extends "B")) (symbol "B" (extends "A")))', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="cycle"):
        resolve_symbol("L:A", tmp_path)
    with pytest.raises(ValueError, match="identifier"):
        resolve_symbol("../L:A", tmp_path)


def test_symbol_resolver_rejects_multi_unit(tmp_path):
    (tmp_path / "L.kicad_sym").write_text(
        '(kicad_symbol_lib (symbol "A" (symbol "A_2_1")))', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Multi-unit"):
        resolve_symbol("L:A", tmp_path)


def test_native_kicad_nc_pads_have_clean_parity(tmp_path, monkeypatch):
    """Real KiCad regression fixture, not production board acceptance."""
    from pcbsmith.board_revision import _native_checks
    from pcbsmith.kicad.board import generate_board
    from pcbsmith.kicad.cli import find_kicad_cli
    from pcbsmith.kicad.native_format import upgrade_generated_native_file
    from pcbsmith.native_project import NativeProjectSpec, prepare_native_project
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

    install = find_kicad_cli()
    if install is None:
        pytest.skip("Native KiCad is not installed")
    symbols = install.path.parent.parent / "share/kicad/symbols"
    if not (symbols / "Device.kicad_sym").is_file():
        pytest.skip("Installed native symbol library is unavailable")
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    spec = NativeProjectSpec(
        project_id="ncfixture",
        title="NC parser native regression",
        user_request="Synthetic integration fixture, not a deliverable",
        width_mm=30,
        height_mm=30,
        profile=DEFAULT_PCB_RULE_PROFILE,
        parts=[
            dict(
                reference="R1",
                symbol="Device:R",
                value="1k",
                footprint="Resistor_SMD:R_1206_3216Metric",
                mpn="fixture",
                role="synthetic",
                pins={"1": None, "2": None},
                schematic_at=(25.4, 25.4),
                board_at=(15, 15, 0),
            )
        ],
    )
    output = tmp_path / "native"
    schematic = prepare_native_project(spec, output, symbols)
    board = output / "ncfixture.kicad_pcb"
    netlist = generate_board(
        schematic_file=Path(schematic),
        board_file=board,
        layout_input={"width_mm": 30, "height_mm": 30, "placements": {"R1": (15, 15, 0)}},
    )
    assert not netlist.nets
    upgrade_generated_native_file(board, output / "board-format.json")
    result = _native_checks(board, tmp_path / "checks", check_models=False, unrouted_placement=True)
    (tmp_path / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    assert result["passed"], result
    assert result["erc_findings"] == 0
    assert result["drc_findings"] == {
        "violations": 0,
        "unconnected_items": 0,
        "schematic_parity": 0,
    }

    # Reproduce the old producer's synthetic-net bindings, then exercise the
    # source-checked local edit, replay and apply with real native checks.
    import xml.etree.ElementTree as ET

    from pcbsmith.board_revision import (
        apply_board_revision,
        create_board_revision,
        inspect_board_revision,
        replay_board_revision,
    )
    from pcbsmith.kicad.board import export_kicad_netlist_xml
    from pcbsmith.kicad.library import (
        QuotedString,
        _atom,
        _children,
        parse_sexpr,
        serialize_sexpr,
    )

    xml = ET.parse(export_kicad_netlist_xml(schematic))
    old_nets = {
        node.get("pin"): net.get("name") for net in xml.iter("net") for node in net.iter("node")
    }
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    footprint = _children(tree, "footprint")[0]
    for pad in _children(footprint, "pad"):
        pad.append(["net", QuotedString(old_nets[_atom(pad[1])])])
    board.write_text(serialize_sexpr(tree), encoding="utf-8")
    invalid = board.read_bytes()
    control = _native_checks(
        board, tmp_path / "control", check_models=False, unrouted_placement=True
    )
    assert control["drc_findings"]["schematic_parity"] == 2
    request = BoardRevisionRequest(
        source_inputs=inspect_board_revision(board)["source_inputs"],
        rationale="Real native NC repair regression fixture",
        validation_stage="unrouted_no_connects",
        no_connect_terminals=(("R1", "1"), ("R1", "2")),
        maximum_changed_objects=1,
    )
    candidate = create_board_revision(board=board, request=request, output=tmp_path / "revision")
    assert board.read_bytes() == invalid
    assert replay_board_revision(tmp_path / "revision")[0] == candidate
    apply_board_revision(board=board, directory=tmp_path / "revision")
    assert board.read_bytes() == candidate.read_bytes()
