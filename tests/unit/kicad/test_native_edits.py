from __future__ import annotations

import pytest

from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.kicad.native_edits import NativeEdit, apply_native_edits, atom, child, children

# Synthetic adapter fixture. Native KiCad acceptance is exercised separately.
BOARD = b"""(kicad_pcb (version 20260206) (net 1 "SIG")
 (footprint "Test:Rect" (layer "F.Cu") (at 10 10) (uuid "part")
  (property "Reference" "R1" (at 0 -2 0 unlocked))
  (pad "1" smd rect (at 0 0) (size 2 1) (layers "F.Cu") (net 1 "SIG"))
  (pad "2" smd rect (at 2 0) (size 2 1) (layers "F.Cu") (net 1 "SIG"))
  (model "test.step" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0))))
 (segment (start 12 10) (end 20 10) (width 0.3) (layer "F.Cu") (net 1) (uuid "route"))
 (via (at 20 10) (size 1) (drill 0.5) (layers "F.Cu" "B.Cu") (net 1) (uuid "via"))
 (gr_text "SILK" (at 1 1) (layer "F.SilkS") (uuid "text"))
 (gr_rect (start 0 0) (end 30 30) (layer "Edge.Cuts") (uuid "outline")))"""


def edit(kind, target, payload=BOARD, **fields):
    return apply_native_edits(
        payload,
        (NativeEdit(kind=kind, target=target, **fields),),
        maximum_displacement_mm=5,
        maximum_changed_objects=10,
    )


def test_text_changes_only_text_and_noop_preserves_exact_bytes():
    output, delta = edit("text", "text", position_mm=(1.5, 1))
    assert delta["changed_ids"] == ["text"]
    assert delta["generator_invocations"] == 0
    assert delta["router_invocations"] == 0
    assert child(children(parse_sexpr(output.decode()), "gr_text")[0], "at")[1:] == ["1.5", "1"]
    assert edit("text", "text", position_mm=(1, 1))[0] == BOARD


def test_component_move_stretches_only_attached_copper():
    output, delta = edit("component", "R1", position_mm=(10, 11))
    tree = parse_sexpr(output.decode())
    segment = children(tree, "segment")[0]
    assert child(segment, "start")[1:] == ["12", "11"]
    assert child(segment, "end")[1:] == ["20", "10"]
    assert delta["changed_ids"] == ["part", "route"]
    assert child(segment, "net")[1:] == ["1"]
    assert child(segment, "width")[1:] == ["0.3"]


def test_rotation_transforms_pad_centres_and_absolute_pad_angles():
    output, delta = edit("component", "R1", position_mm=(10, 10), rotation_deg=90)
    tree = parse_sexpr(output.decode())
    assert child(children(tree, "segment")[0], "start")[1:] == ["10", "8"]
    footprint = children(tree, "footprint")[0]
    assert child(children(footprint, "pad")[1], "at")[1:] == ["2", "0", "90"]
    assert child(children(footprint, "property")[0], "at")[1:] == ["0", "-2", "90", "unlocked"]
    assert delta["changed_ids"] == ["part", "route"]


def test_detour_preserves_endpoints_attributes_and_unrelated_geometry():
    output, delta = edit("segment", "route", points_mm=((12, 10), (16, 11), (20, 10)))
    segments = children(parse_sexpr(output.decode()), "segment")
    assert len(segments) == 2
    assert child(segments[0], "start")[1:] == ["12", "10"]
    assert child(segments[1], "end")[1:] == ["20", "10"]
    for item in segments:
        assert atom(child(item, "layer")[1]) == "F.Cu"
        assert child(item, "net")[1:] == ["1"]
        assert child(item, "width")[1:] == ["0.3"]
    assert len(delta["changed_ids"]) == 2
    assert "part" not in delta["changed_ids"]
    assert output == edit("segment", "route", points_mm=((12, 10), (16, 11), (20, 10)))[0]


def test_via_move_and_model_offset_are_local():
    output, delta = edit("via", "via", position_mm=(21, 10))
    assert child(children(parse_sexpr(output.decode()), "segment")[0], "end")[1:] == ["21", "10"]
    assert delta["changed_ids"] == ["route", "via"]
    output, delta = edit("model_offset", "R1", offset_mm=(0, 0, 0.2))
    footprint = children(parse_sexpr(output.decode()), "footprint")[0]
    assert child(child(child(footprint, "model"), "offset"), "xyz")[1:] == ["0", "0", "0.2"]
    assert delta["changed_ids"] == ["part"]


@pytest.mark.parametrize(
    "payload,match",
    [
        (BOARD.replace(b'(uuid "part")', b'(uuid "part") (locked yes)'), "locked"),
        (BOARD.replace(b'(layer "F.Cu") (at 10', b'(layer "B.Cu") (at 10'), "back-side"),
        (BOARD[:-1] + b"(zone (net 1)))", "zones"),
        (BOARD.replace(b'(uuid "route")', b'(uuid "route") locked'), "locked copper"),
    ],
)
def test_unsupported_or_locked_changes_do_not_silently_rebuild(payload, match):
    with pytest.raises(ValueError, match=match):
        edit("component", "R1", payload=payload, position_mm=(10, 11))


def test_region_endpoints_and_changed_object_budgets_are_enforced():
    with pytest.raises(ValueError, match="endpoints"):
        edit("segment", "route", points_mm=((11, 10), (20, 10)))
    with pytest.raises(ValueError, match="region"):
        edit("segment", "route", points_mm=((12, 10), (16, 100), (20, 10)))
    with pytest.raises(ValueError, match="changed-object"):
        apply_native_edits(
            BOARD,
            (NativeEdit(kind="component", target="R1", position_mm=(10, 11)),),
            maximum_displacement_mm=5,
            maximum_changed_objects=1,
        )
    with pytest.raises(ValueError, match="displacement"):
        edit("component", "R1", position_mm=(100, 100))


def test_native_edit_rejects_extra_parameters_and_nonfinite_values():
    with pytest.raises(ValueError):
        NativeEdit(kind="component", target="R1", position_mm=(float("nan"), 0))
    with pytest.raises(ValueError):
        NativeEdit(kind="component", target="R1", position_mm=(1, 0), net=2)


def test_zone_clearance_is_local_and_requires_authority():
    board = (
        b'(kicad_pcb (zone (net "VCC") (layer "F.Cu") (uuid "z") '
        b"(connect_pads yes (clearance 0.5))))"
    )
    item = NativeEdit(kind="zone_clearance", target="z", clearance_mm=0.3)
    with pytest.raises(ValueError, match="authority"):
        apply_native_edits(board, (item,), maximum_displacement_mm=1, maximum_changed_objects=1)
    out, delta = apply_native_edits(
        board,
        (item,),
        maximum_displacement_mm=1,
        maximum_changed_objects=1,
        allowed_zone_ids=("z",),
    )
    assert delta["changed_ids"] == ["z"]
    assert b"(clearance 0.3)" in out
    assert delta["router_invocations"] == 0
    with pytest.raises(ValueError):
        NativeEdit(kind="zone_clearance", target="z", clearance_mm=0)
    with pytest.raises(ValueError):
        NativeEdit(kind="zone_refill", target="z", clearance_mm=0.3)


def test_pad_area_move_preserves_offcentre_attachment():
    board = BOARD.replace(b"(start 12 10)", b"(start 12.2 10.1)")
    out, delta = edit(
        "component", "R1", payload=board, position_mm=(10, 11), attachment_policy="pad_area"
    )
    seg = children(parse_sexpr(out.decode()), "segment")[0]
    assert child(seg, "start")[1:] == ["12.2", "11.1"]
    assert "route" in delta["changed_ids"]
    assert child(seg, "end")[1:] == ["20", "10"]


def test_insert_copper_retains_all_source_objects_and_net():
    output, delta = edit(
        "segment_add",
        "new-branch",
        net_name="SIG",
        width_mm=0.8,
        layer="F.Cu",
        points_mm=((12, 10), (12, 14), (20, 14)),
    )
    tree = parse_sexpr(output.decode())
    assert len(children(tree, "segment")) == 3
    assert len(delta["changed_ids"]) == 2
    assert "route" in delta["protected_ids"] and "part" in delta["protected_ids"]
    for seg in children(tree, "segment")[1:]:
        assert child(seg, "net")[1] == "1"
        assert child(seg, "width")[1] == "0.8"
    assert (
        edit(
            "segment_add",
            "new-branch",
            net_name="SIG",
            width_mm=0.8,
            layer="F.Cu",
            points_mm=((12, 10), (12, 14), (20, 14)),
        )[0]
        == output
    )


def test_insert_unknown_net_and_zero_length_rejected():
    with pytest.raises(ValueError, match="unknown native net"):
        edit(
            "segment_add",
            "branch",
            net_name="unknown",
            width_mm=0.8,
            layer="F.Cu",
            points_mm=((1, 1), (2, 2)),
        )
    with pytest.raises(ValueError, match="invalid inserted"):
        edit(
            "segment_add",
            "branch",
            net_name="SIG",
            width_mm=0.8,
            layer="F.Cu",
            points_mm=((1, 1), (1, 1)),
        )


def test_remove_only_exact_segment():
    output, delta = edit("segment_remove", "route")
    assert not children(parse_sexpr(output.decode()), "segment")
    assert delta["changed_ids"] == ["route"]
    with pytest.raises(ValueError, match="does not match"):
        edit("segment_remove", "part")
