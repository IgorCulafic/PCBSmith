"""Functional sheet controls and real KiCad proof; no board acceptance is implied."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.native_project import (
    NativeProjectSpec,
    prepare_native_project,
    resolve_symbol,
    symbol_pins,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE
from pcbsmith.schematic_presentation import (
    compile_presentation,
    placed_pin,
)

FIXTURE = Path(__file__).parents[1] / "fixtures/schematic_presentation/functional-blocks.json"


def demo_spec() -> NativeProjectSpec:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["profile"] = DEFAULT_PCB_RULE_PROFILE.model_dump(mode="json")
    return NativeProjectSpec.model_validate(data)


def geometry(spec):
    offsets = {
        "Device:R": {"1": ((0, 3.81), 270), "2": ((0, -3.81), 90)},
        "Device:C": {"1": ((0, 3.81), 270), "2": ((0, -3.81), 90)},
        "Device:LED": {"1": ((-3.81, 0), 0), "2": ((3.81, 0), 180)},
        "Connector_Generic:Conn_01x02": {"1": ((-5.08, 0), 0), "2": ((-5.08, -2.54), 0)},
    }
    return {
        (part.reference, pin): placed_pin(
            part.schematic_at, at, angle, part.schematic_rotation, part.pins[pin]
        )
        for part in spec.parts
        for pin, (at, angle) in offsets[part.symbol].items()
    }


def compile_spec(spec):
    return compile_presentation(
        spec.schematic_presentation,
        geometry(spec),
        {p.reference: p.schematic_at for p in spec.parts},
        identity=spec.project_id,
    )


def test_local_wires_have_branch_junctions_and_fewer_labels():
    spec = demo_spec()
    result = compile_spec(spec)
    tree = parse_sexpr("(items " + "\n".join(result.items) + ")")
    assert len(_children(tree, "polyline")) == 3
    assert len(_children(tree, "text")) == 6
    assert len(_children(tree, "junction")) == 3
    assert len(_children(tree, "label")) == 8  # one per connected net/block, not per pin
    assert len(_children(tree, "label")) < len(geometry(spec))
    uuids = [_atom(_children(item, "uuid")[0][1]) for item in tree[1:]]
    assert len(uuids) == len(set(uuids))
    assert result == compile_spec(spec)
    # Every geometric wire end without a component pin terminates at a label.
    endpoints = {}
    for wire in _children(tree, "wire"):
        for xy in _children(_children(wire, "pts")[0], "xy"):
            at = (float(_atom(xy[1])), float(_atom(xy[2])))
            endpoints[at] = endpoints.get(at, 0) + 1
    label_points = {
        tuple(float(_atom(v)) for v in _children(label, "at")[0][1:3])
        for label in _children(tree, "label")
    }
    pin_points = {pin.at for pin in geometry(spec).values()}
    assert all(count != 1 or at in pin_points | label_points for at, count in endpoints.items())


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_nonfinite_presentation_coordinates_are_rejected(value):
    data = demo_spec().model_dump(mode="json")
    data["schematic_presentation"]["blocks"][0]["bounds_mm"][0] = value
    with pytest.raises(ValueError):
        NativeProjectSpec.model_validate(data)


def test_wire_into_symbol_body_is_rejected():
    data = demo_spec().model_dump(mode="json")
    data["schematic_presentation"]["wires"][0]["via_mm"] = [
        [50.8, 86.36],
        [50.8, 76.2],
        [63.5, 76.2],
    ]
    with pytest.raises(ValueError, match="outward direction"):
        compile_spec(NativeProjectSpec.model_validate(data))


@pytest.mark.parametrize("change", ["duplicate", "outside", "title"])
def test_invalid_block_definition_is_rejected(change):
    data = demo_spec().model_dump(mode="json")
    block = data["schematic_presentation"]["blocks"][0]
    if change == "duplicate":
        block["members"].append("R1")
    elif change == "outside":
        block["bounds_mm"][2] = 500
    else:
        block["title"] = "Too long to fit " * 30
    with pytest.raises(ValueError):
        NativeProjectSpec.model_validate(data)


@pytest.mark.parametrize(
    "rotation,at,end",
    [
        (0, (25.4, 21.59), (25.4, 16.51)),
        (90, (21.59, 25.4), (16.51, 25.4)),
        (180, (25.4, 29.21), (25.4, 34.29)),
        (270, (29.21, 25.4), (34.29, 25.4)),
    ],
)
def test_native_pin_rotation_includes_escape_direction(rotation, at, end):
    result = placed_pin((25.4, 25.4), (0, 3.81), 270, rotation, "N")
    assert result.at == at
    assert result.stub_end == end


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda d: d["schematic_presentation"]["blocks"][0]["members"].append("GHOST"), "exactly"),
        (lambda d: d["schematic_presentation"]["wires"][0].update(end=["C2", "99"]), "unknown"),
        (lambda d: d["schematic_presentation"]["wires"][0].update(end=["C2", "2"]), "same net"),
        (lambda d: d["schematic_presentation"]["wires"][0].update(end=["R1", "1"]), "interfaces"),
        (lambda d: d["schematic_presentation"]["wires"].pop(0), "connected local"),
        (lambda d: d["schematic_presentation"]["wires"][0].update(via_mm=[]), "orthogonal"),
        (lambda d: d["schematic_presentation"]["wires"][0].update(via_mm=[[30, 50]]), "grid"),
        (
            lambda d: d["schematic_presentation"]["blocks"][0].update(bounds_mm=[20, 35, 110, 155]),
            "overlap",
        ),
        (lambda d: d["schematic_presentation"]["blocks"][0].update(explanation=""), "at least"),
        (lambda d: d["parts"][0].update(schematic_at=[40.64, 40.64]), "annotations"),
        (lambda d: d["parts"][0]["pins"].update({"1": None}), "same net"),
    ],
)
def test_bad_presentation_is_rejected(mutation, match):
    data = demo_spec().model_dump(mode="json")
    mutation(data)
    with pytest.raises(ValueError, match=match):
        compile_spec(NativeProjectSpec.model_validate(data))


def test_different_net_crossing_and_nc_contact_rejected():
    spec = demo_spec()
    data = spec.model_dump(mode="json")
    data["schematic_presentation"]["wires"][0]["via_mm"] = [
        [25.4, 86.36],
        [25.4, 127],
        [58.42, 127],
        [58.42, 76.2],
        [63.5, 76.2],
    ]
    with pytest.raises(ValueError, match="cross or touch"):
        compile_spec(NativeProjectSpec.model_validate(data))
    pins = geometry(spec)
    pins["X", "1"] = placed_pin((50.8, 76.2), (0, 0), 0, 0, None)
    with pytest.raises(ValueError, match="NC pin"):
        compile_presentation(
            spec.schematic_presentation,
            pins,
            {p.reference: p.schematic_at for p in spec.parts},
            identity="fault",
        )


def test_optional_fields_preserve_legacy_serialization_and_binding():
    data = demo_spec().model_dump(mode="json")
    data.pop("schematic_presentation")
    for part in data["parts"]:
        for field in ("schematic_rotation", "schematic_reference_at", "schematic_value_at"):
            part.pop(field, None)
    old_json = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    spec = NativeProjectSpec.model_validate_json(old_json)
    assert spec.model_dump_json() == old_json
    assert spec.schematic_presentation is None


def test_current_presentation_is_part_of_the_exact_specification_identity():
    spec = demo_spec()
    data = spec.model_dump(mode="json")
    data["schematic_presentation"]["blocks"][0]["explanation"] += " Changed."
    assert NativeProjectSpec.model_validate(data).model_dump_json() != spec.model_dump_json()


@pytest.mark.parametrize("case", ["wrong_net", "relocated_flag"])
def test_invalid_presentation_stops_before_project_creation(tmp_path, monkeypatch, case):
    from pcbsmith.kicad.cli import find_kicad_cli

    install = find_kicad_cli()
    if install is None:
        pytest.skip("Native KiCad not installed")
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    spec = demo_spec()
    data = spec.model_dump(mode="json")
    if case == "wrong_net":
        data["schematic_presentation"]["wires"][0]["end"] = ["C2", "2"]
        message = "same net"
    else:
        data["power_flag_positions"] = {"+5V": [40.64, 86.36]}
        message = "power flags"
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match=message):
        prepare_native_project(
            NativeProjectSpec.model_validate(data),
            output,
            install.path.parent.parent / "share/kicad/symbols",
        )
    assert not output.exists()


def test_real_kicad_connected_sheet_preserves_netlist_and_board(tmp_path, monkeypatch):
    from pcbsmith.board_revision import _native_checks
    from pcbsmith.kicad.board import generate_board
    from pcbsmith.kicad.cli import find_kicad_cli
    from pcbsmith.kicad.native_format import upgrade_generated_native_file
    from pcbsmith.kicad.validate import export_schematic_svg
    from pcbsmith.native_project import require_native_input_closure
    from pcbsmith.review.visual_package import rasterize_svg_with_resvg

    install = find_kicad_cli()
    if install is None:
        pytest.skip("Native KiCad not installed")
    symbols = install.path.parent.parent / "share/kicad/symbols"
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    spec = demo_spec()
    # Verify test geometry against the installed library, not just our fixtures.
    for part in spec.parts:
        native_pins = symbol_pins(resolve_symbol(part.symbol, symbols)[0])
        for number, pin in native_pins.items():
            at = _children(pin, "at")[0]
            assert geometry(spec)[part.reference, number] == placed_pin(
                part.schematic_at,
                (float(_atom(at[1])), float(_atom(at[2]))),
                float(_atom(at[3])),
                part.schematic_rotation,
                part.pins[number],
            )
    baseline = spec.model_copy(update={"schematic_presentation": None})
    plain = prepare_native_project(baseline, tmp_path / "baseline", symbols)
    styled = prepare_native_project(spec, tmp_path / "connected", symbols)
    before = require_native_input_closure(baseline, plain.parent)
    after = require_native_input_closure(spec, styled.parent)
    assert {n.name: set(n.nodes) for n in before.nets} == {n.name: set(n.nodes) for n in after.nets}
    assert before.components == after.components
    # Same PCB bytes checked against the redesigned schematic: presentation only.
    board = plain.with_suffix(".kicad_pcb")
    generate_board(
        schematic_file=plain,
        board_file=board,
        layout_input={
            "width_mm": 70,
            "height_mm": 100,
            "placements": {p.reference: p.board_at for p in spec.parts},
        },
    )
    upgrade_generated_native_file(board, plain.parent / "board-format.json")
    styled_board = styled.with_suffix(".kicad_pcb")
    styled_board.write_bytes(board.read_bytes())
    checks = _native_checks(
        styled_board, tmp_path / "checks", check_models=False, unrouted_placement=True
    )
    assert checks["passed"], checks
    assert checks["erc_findings"] == 0
    assert checks["drc_findings"]["schematic_parity"] == 0
    assert styled_board.read_bytes() == board.read_bytes()
    svg, failures = export_schematic_svg(styled)
    assert not failures and svg
    png = styled.parent / "preview.png"
    rasterize_svg_with_resvg(Path(svg), png, 2400, 1000, (10, 10, 390, 162.5))
    evidence = {
        "scope": "Platform regression fixture, not a production board or engineering approval",
        "native_checks": checks,
        "netlist_equal": True,
        "pcb_sha256": hashlib.sha256(board.read_bytes()).hexdigest(),
        "schematic_sha256": hashlib.sha256(styled.read_bytes()).hexdigest(),
        "svg_sha256": hashlib.sha256(Path(svg).read_bytes()).hexdigest(),
        "png_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
        "visual_inspection": "pending",
    }
    (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
