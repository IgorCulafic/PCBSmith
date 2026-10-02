import hashlib
import json
import sys
from dataclasses import replace

import pytest

from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist, render_board_from_layout
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
)
from pcbsmith.kicad.layout_input import ReviewedLayoutInput, main, synchronize_native_placement
from pcbsmith.kicad.library import _atom, _children, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.routing_candidate_transaction import require_saved_layout_matches
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE as PROFILE


def fixture():
    parts = (BoardComponent("R1", "1k", "Resistor_SMD:R_0603_1608Metric", "fixture/r1"),)
    netlist = BoardNetlist(
        parts, (BoardNet("GND", (("R1", "1"),)), BoardNet("VCC", (("R1", "2"),)))
    )
    layout = ReviewedLayoutInput.model_validate(
        dict(
            width_mm=30,
            height_mm=20,
            placements={"R1": (10, 10, 0)},
            labels=[dict(text="5V", at_mm=(4, 4))],
        )
    ).bind(netlist)
    return (layout, netlist)


@pytest.mark.parametrize(
    "change", ["none", "label", "reference", "component", "rotation", "combined"]
)
def test_refresh_matches_saved_native(change):
    base, netlist = fixture()
    tree = parse_sexpr(render_board_from_layout(netlist, base, profile=PROFILE))
    fp = _children(tree, "footprint")[0]
    if change in {"label", "combined"}:
        _children(_children(tree, "gr_text")[0], "at")[0][1] = "29"
    if change in {"reference", "combined"}:
        ref = next(p for p in _children(fp, "property") if _atom(p[1]) == "Reference")
        _children(ref, "at")[0][1] = "3"
    if change in {"component", "combined"}:
        _children(fp, "at")[0][1] = "33"
    if change == "rotation":
        changed = replace(base, part_rotation=(("R1", 90),))
        tree = parse_sexpr(render_board_from_layout(netlist, changed, profile=PROFILE))
    source = serialize_sexpr(tree)
    result = synchronize_native_placement(source, base, netlist, PROFILE)
    require_saved_layout_matches(source, result, netlist, PROFILE)
    assert result.segments == base.segments and result.vias == base.vias
    if change in {"component", "combined"}:
        assert result.placements[0][1] == 13
    if change in {"label", "combined"}:
        assert _children(parse_sexpr(result.graphics[0]), "at")[0][1] == "29"


@pytest.mark.parametrize("change", ["pad", "outline", "value", "missing", "duplicate"])
def test_unsupported_or_inconsistent_input_fails(change):
    base, netlist = fixture()
    tree = parse_sexpr(render_board_from_layout(netlist, base, profile=PROFILE))
    fp = _children(tree, "footprint")[0]
    if change == "pad":
        _children(_children(fp, "pad")[0], "size")[0][1] = "9"
    elif change == "outline":
        _children(_children(tree, "gr_rect")[0], "end")[0][1] = "99"
    elif change == "value":
        next(p for p in _children(fp, "property") if _atom(p[1]) == "Value")[2] = "wrong"
    elif change == "missing":
        tree.remove(fp)
    else:
        tree.append(fp)
    with pytest.raises(ValueError):
        synchronize_native_placement(serialize_sexpr(tree), base, netlist, PROFILE)


def test_cli_preserves_input_and_never_overwrites(tmp_path, monkeypatch):
    base, netlist = fixture()
    source = render_board_from_layout(netlist, base, profile=PROFILE).encode()
    board = tmp_path / "fixture.kicad_pcb"
    board.write_bytes(source)
    layout = tmp_path / "base.json"
    layout.write_text(canonical_board_layout_snapshot_json(base))
    nets = tmp_path / "nets.json"
    nets.write_text(canonical_board_netlist_snapshot_json(netlist))
    profile = tmp_path / "profile.json"
    profile.write_text(PROFILE.model_dump_json())
    output = tmp_path / "derived"
    args = [
        "layout_input",
        "--board",
        str(board),
        "--source-sha256",
        hashlib.sha256(source).hexdigest(),
        "--base-layout",
        str(layout),
        "--netlist",
        str(nets),
        "--profile",
        str(profile),
        "--output",
        str(output),
    ]
    monkeypatch.setattr(sys, "argv", args)
    main()
    assert board.read_bytes() == source
    result = parse_canonical_board_layout_snapshot((output / "layout.json").read_text())
    require_saved_layout_matches(source.decode(), result, netlist, PROFILE)
    assert (
        json.loads((output / "preparation.json").read_text())["status"] == "matched_native_snapshot"
    )
    with pytest.raises(ValueError, match="must be new"):
        main()
    args[args.index("--output") + 1] = str(tmp_path / "stale")
    args[args.index("--source-sha256") + 1] = "0" * 64
    with pytest.raises(ValueError, match="source SHA"):
        main()
    assert not (tmp_path / "stale").exists()


def test_native_save_equivalent_rotation_notation_is_accepted():
    base, netlist = fixture()
    layout = replace(base, part_rotation=(("R1", 270),))
    text = render_board_from_layout(netlist, layout, profile=PROFILE)
    tree = parse_sexpr(text)
    at = _children(_children(tree, "footprint")[0], "at")[0]
    assert float(at[3]) == 270
    at[3] = "-90"
    require_saved_layout_matches(serialize_sexpr(tree), layout, netlist, PROFILE)
    at[3] = "-89"
    with pytest.raises(ValueError, match="does not match"):
        require_saved_layout_matches(serialize_sexpr(tree), layout, netlist, PROFILE)


@pytest.mark.parametrize("angle", [0, 90, 180])
def test_actual_native_pose_edit_with_hidden_metadata_synchronizes(angle):
    from pcbsmith.kicad.native_edits import NativeEdit, apply_native_edits

    base, original = fixture()
    part = replace(original.components[0], fields=(("MPN", "TEST-RESISTOR"),))
    netlist = replace(original, components=(part,))
    base = replace(base, placements=((part, base.placements[0][1]),))
    source = render_board_from_layout(netlist, base, profile=PROFILE).encode()
    edited, _ = apply_native_edits(
        source,
        (NativeEdit(kind="component", target="R1", position_mm=(31, 32), rotation_deg=angle),),
        maximum_displacement_mm=10,
        maximum_changed_objects=1,
    )
    result = synchronize_native_placement(edited.decode(), base, netlist, PROFILE)
    require_saved_layout_matches(edited.decode(), result, netlist, PROFILE)
    assert source != edited

    # Equivalence must not hide changed content, positions, visibility or copper.
    for mutation in ("content", "position", "visibility", "visible_angle", "pad_angle"):
        tree = parse_sexpr(edited.decode())
        fp = _children(tree, "footprint")[0]
        metadata = next(p for p in _children(fp, "property") if _atom(p[1]) == "MPN")
        if mutation == "content":
            metadata[2] = "different"
        elif mutation == "position":
            _children(metadata, "at")[0][1] = "9"
        elif mutation == "visibility":
            _children(metadata, "hide")[0][1] = "no"
        elif mutation == "visible_angle":
            prop = next(p for p in _children(fp, "property") if _atom(p[1]) == "Value")
            _children(prop, "at")[0][3] = str(angle + 15)
        else:
            _children(_children(fp, "pad")[0], "at")[0][3] = str(angle + 15)
        with pytest.raises(ValueError, match="does not match"):
            require_saved_layout_matches(serialize_sexpr(tree), result, netlist, PROFILE)
