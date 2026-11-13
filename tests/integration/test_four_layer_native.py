"""Opt-in four-layer interchange proof. Synthetic fixture, no production-board acceptance."""

import hashlib
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.kicad.test_four_layer_logic import LAYERS, four_layer_profile
from tests.unit.kicad.test_routing_external_adapters import _layout
from tests.unit.kicad.test_routing_net_constraints import two_net_request

from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist, render_board_from_layout
from pcbsmith.kicad.copper_layers import saved_copper_layers
from pcbsmith.kicad.freerouting_production import (
    FreeroutingProductionConfig,
    constrain_freerouting_dsn,
    read_single_sided_routes,
)
from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph
from pcbsmith.manufacturing_release import _require_copper_gerbers
from pcbsmith.production_decoupling import _select_path, native_terminal_anchors
from pcbsmith.routing_ir import RouteRequest


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_FOUR_LAYER_SMOKE"),
    reason="requires pinned local Freerouting and KiCad runtimes",
)
def test_four_layer_native_roundtrip_router_and_gerbers(tmp_path):
    config = FreeroutingProductionConfig.model_validate_json(
        Path(".pcbsmith/freerouting.json").read_bytes()
    )
    config.preflight()
    folder = Path(os.environ.get("PCBSMITH_FOUR_LAYER_OUTPUT", str(tmp_path))).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    board = folder / "four-layer-software-fixture.kicad_pcb"
    assert not board.exists(), "retain prior proof evidence"
    parts = tuple(
        BoardComponent(ref, "SOFTWARE TEST", footprint, f"/{ref}")
        for ref, footprint in (
            ("A", "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"),
            ("B", "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"),
            ("C", "TestPoint:TestPoint_Pad_D1.5mm"),
            ("D", "TestPoint:TestPoint_Pad_D1.5mm"),
        )
    )
    layout = replace(
        _layout(),
        placements=tuple(zip(parts, (5, 25, 5, 25), strict=True)),
        part_y_mm=(("A", 4), ("B", 4), ("C", 8), ("D", 8)),
        part_flip=("D",),
        hide_references=("A", "B", "C", "D"),
    )
    netlist = BoardNetlist(
        parts,
        (
            BoardNet("/SIG", (("A", "1"), ("B", "1"))),
            BoardNet("/AUX", (("C", "1"), ("D", "1"))),
        ),
    )
    board.write_text(
        render_board_from_layout(netlist, layout, profile=four_layer_profile()), encoding="utf-8"
    )
    raw = two_net_request().model_dump()
    raw["allowed_layers"] = LAYERS
    raw["net_layer_constraints"][0]["allowed_layers"] = ["In1.Cu"]
    outer_traces = bool(os.environ.get("PCBSMITH_FOUR_LAYER_OUTER_TRACES"))
    if outer_traces:
        raw["net_layer_constraints"] += (
            {
                "constraint_id": "outer-signal-traces",
                "net_names": ["/AUX"],
                "allowed_layers": LAYERS,
                "allowed_trace_layers": ["F.Cu", "B.Cu"],
                "allow_vias": True,
            },
        )
    request = RouteRequest.model_validate(raw)
    bridge = Path("tools/kicad_dsn_ses_bridge.py").resolve()
    commands = []

    def run(label, command, timeout=60):
        result = subprocess.run(
            list(map(str, command)), capture_output=True, timeout=timeout, check=False
        )
        (folder / f"{label}.stdout.log").write_bytes(result.stdout)
        (folder / f"{label}.stderr.log").write_bytes(result.stderr)
        commands.append(
            {"label": label, "command": list(map(str, command)), "returncode": result.returncode}
        )
        (folder / "commands.json").write_text(json.dumps(commands, indent=2), encoding="utf-8")
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result

    dsn, ses, routed = folder / "source.dsn", folder / "routed.ses", folder / "routed.kicad_pcb"
    run("native-export", [config.kicad_python, bridge, "export", board, dsn])
    constrained = folder / "constrained.dsn"
    constrained.write_bytes(constrain_freerouting_dsn(dsn.read_text(), layout, request, 1))
    result = run(
        "freerouting",
        [
            config.java_executable,
            "-jar",
            config.binding.entrypoint_path,
            "-de",
            constrained,
            "-do",
            ses,
            "-mp",
            "5",
            "-mt",
            "1",
            "--gui.enabled=false",
            "--router.fanout.enabled=false",
            "--router.automatic_neckdown=false",
            "-da",
            "--logging.file.enabled=false",
            "--user_data_path=" + str(folder / "user-data"),
        ],
    )
    assert b"0 unrouted and 0 violations" in result.stdout
    run("native-import", [config.kicad_python, bridge, "import", board, ses, routed])
    assert saved_copper_layers(parse_sexpr(routed.read_text())) == LAYERS
    imported = read_single_sided_routes(routed, board, layout, request)
    assert {s.layer for s in imported.segments if s.net_name == "/SIG"} == {"In1.Cu"}
    assert any(v.net_name == "/AUX" for v in imported.vias)
    assert not any(v.net_name == "/SIG" for v in imported.vias)
    if outer_traces:
        assert {s.layer for s in imported.segments if s.net_name == "/AUX"} == {"F.Cu", "B.Cu"}
    cli = Path(config.kicad_python).with_name("kicad-cli.exe")
    drc = folder / "drc.json"
    run("native-drc", [cli, "pcb", "drc", "--format", "json", "--output", drc, routed])
    checks = json.loads(drc.read_text())
    assert not checks["unconnected_items"]
    assert not [v for v in checks["violations"] if v["severity"] == "error"]
    gerbers = folder / "gerbers"
    run(
        "gerbers",
        [
            cli,
            "pcb",
            "export",
            "gerbers",
            "--layers",
            ",".join((*LAYERS, "Edge.Cuts")),
            "--output",
            str(gerbers) + os.sep,
            routed,
        ],
    )
    _require_copper_gerbers(tuple(gerbers.glob("*")), LAYERS)
    run(
        "drill",
        [
            cli,
            "pcb",
            "export",
            "drill",
            "--format",
            "excellon",
            "--output",
            str(folder / "drill") + os.sep,
            routed,
        ],
    )
    for layer in ("In1.Cu", "In2.Cu"):
        run(
            "svg-" + layer,
            [
                cli,
                "pcb",
                "export",
                "svg",
                "--layers",
                layer + ",Edge.Cuts",
                "--output",
                folder / (layer + ".svg"),
                routed,
            ],
        )
    (folder / "result.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "purpose": "synthetic four-layer software interchange proof",
                "copper_layers": LAYERS,
                "segments": len(imported.segments),
                "vias": len(imported.vias),
                "drc_errors": 0,
                "drc_warnings": checks["violations"],
                "unconnected_items": 0,
                "router_sha256": config.binding.entrypoint_sha256,
                "board_sha256": hashlib.sha256(routed.read_bytes()).hexdigest(),
                "production_board_modified_or_qualified": False,
                "explicit_outer_trace_restriction": outer_traces,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_FOUR_LAYER_RETAINED_PROOF"),
    reason="requires retained native four-layer interchange proof; read-only replay",
)
def test_retained_native_four_layer_electrical_graph(tmp_path):
    folder = Path(os.environ["PCBSMITH_FOUR_LAYER_RETAINED_PROOF"]).resolve()
    routed, source = folder / "routed.kicad_pcb", folder / "four-layer-software-fixture.kicad_pcb"
    before = hashlib.sha256(routed.read_bytes()).hexdigest()
    retained = json.loads((folder / "result.json").read_text())
    assert before == retained["board_sha256"]
    # Reconstruct the same test declaration, then independently read native
    # pads, routes and layer order. No native save or routing operation occurs.
    parts = tuple(
        BoardComponent(ref, "SOFTWARE TEST", footprint, f"/{ref}")
        for ref, footprint in (
            ("A", "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"),
            ("B", "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"),
            ("C", "TestPoint:TestPoint_Pad_D1.5mm"),
            ("D", "TestPoint:TestPoint_Pad_D1.5mm"),
        )
    )
    placement = replace(
        _layout(),
        placements=tuple(zip(parts, (5, 25, 5, 25), strict=True)),
        part_y_mm=(("A", 4), ("B", 4), ("C", 8), ("D", 8)),
        part_flip=("D",),
        hide_references=("A", "B", "C", "D"),
    )
    netlist = BoardNetlist(
        parts,
        (BoardNet("/SIG", (("A", "1"), ("B", "1"))), BoardNet("/AUX", (("C", "1"), ("D", "1")))),
    )
    raw = two_net_request().model_dump()
    raw["allowed_layers"] = LAYERS
    raw["net_layer_constraints"][0]["allowed_layers"] = ["In1.Cu"]
    imported = read_single_sided_routes(routed, source, placement, RouteRequest.model_validate(raw))
    anchors = native_terminal_anchors(routed, netlist)
    graph = build_routed_copper_graph(
        imported,
        netlist,
        anchors,
        resolve_point_contacts=True,
        copper_layer_order=saved_copper_layers(parse_sexpr(routed.read_text())),
    )
    results = {}
    for net, start, end in (("/SIG", "A", "B"), ("/AUX", "C", "D")):
        result = _select_path(graph, f"pad:{start}:1", f"pad:{end}:1", net, "native:" + net)
        assert result.connectivity_state == "connected"
        results[net] = result.model_dump(mode="json")
    assert results["/AUX"]["via_count"] == 2
    assert hashlib.sha256(routed.read_bytes()).hexdigest() == before
    evidence = Path(
        os.environ.get("PCBSMITH_FOUR_LAYER_ELECTRICAL_OUTPUT", str(tmp_path))
    ).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    target = evidence / "native-electrical-replay.json"
    assert not target.exists(), "retain prior proof evidence"
    target.write_text(
        json.dumps(
            {
                "board_sha256": before,
                "results": results,
                "board_modified": False,
                "production_acceptance": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_NATIVE_PAD_READBACK"),
    reason="requires local KiCad Python for independent pad-position comparison",
)
def test_native_terminal_anchor_positions_match_kicad_on_both_faces(tmp_path):
    config = FreeroutingProductionConfig.model_validate_json(
        Path(".pcbsmith/freerouting.json").read_bytes()
    )
    folder = Path(os.environ.get("PCBSMITH_NATIVE_PAD_OUTPUT", str(tmp_path))).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    assert not (folder / "pad-reader-result.json").exists(), "retain prior proof evidence"
    part = BoardComponent("R1", "SOFTWARE TEST", "Resistor_SMD:R_0805_2012Metric", "/R1")
    netlist = BoardNetlist((part,), (BoardNet("/SIG", (("R1", "1"), ("R1", "2"))),))
    paths = []
    expected = {}
    for face in ("F.Cu", "B.Cu"):
        for angle in (0, 90, 180, 270):
            layout = replace(
                _layout(),
                placements=((part, 5),),
                part_y_mm=(("R1", 5),),
                part_rotation=(("R1", angle),),
                part_flip=("R1",) if face == "B.Cu" else (),
            )
            board = folder / f"{face}-{angle}.kicad_pcb"
            assert not board.exists()
            board.write_text(
                render_board_from_layout(netlist, layout, profile=four_layer_profile()),
                encoding="utf-8",
            )
            paths.append(str(board))
            expected[str(board)] = {
                a.pad_number: [float(a.x_mm), float(a.y_mm), a.layer]
                for a in native_terminal_anchors(board, netlist)
            }
    # Independent pcbnew reader: the production reader above parses saved text.
    script = """import json, sys, pcbnew
result = {}
for path in sys.argv[1:]:
    board = pcbnew.LoadBoard(path)
    pads = {}
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            copper_layers = list(pad.GetLayerSet().CuStack())
            assert len(copper_layers) == 1
            pads[pad.GetNumber()] = [
                round(pcbnew.ToMM(pad.GetPosition().x)-20, 9),
                round(pcbnew.ToMM(pad.GetPosition().y)-20, 9),
                board.GetLayerName(copper_layers[0]),
            ]
    result[path] = pads
print(json.dumps(result))
"""
    process = subprocess.run(
        [config.kicad_python, "-c", script, *paths], capture_output=True, timeout=60, check=False
    )
    (folder / "native-pad-reader.stdout.log").write_bytes(process.stdout)
    (folder / "native-pad-reader.stderr.log").write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    observed = json.loads(process.stdout)
    assert observed == expected
    (folder / "pad-reader-result.json").write_text(
        json.dumps({"expected": expected, "native": observed, "passed": True}, indent=2),
        encoding="utf-8",
    )
