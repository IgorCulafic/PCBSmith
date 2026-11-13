"""Native filled-plane electrical integration, using synthetic saved copper only."""

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.kicad.test_four_layer_logic import four_layer_profile
from tests.unit.test_production_decoupling import fixture

from pcbsmith.kicad.board import render_board_from_layout
from pcbsmith.kicad.final_fill_adapter import refill_and_read_kicad_board
from pcbsmith.kicad.final_fill_connectivity import KiCadFinalFillConnectivityObservation
from pcbsmith.kicad.native_fill_graph import retain_native_fill
from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph
from pcbsmith.production_decoupling import (
    _select_path,
    execute_native_loops,
    native_terminal_anchors,
)
from pcbsmith.routed_copper_graph_ir import RoutedCopperGraphResult


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_NATIVE_FILL_PROOF"), reason="requires native KiCad"
)
@pytest.mark.parametrize("plane_only", [False, True])
def test_native_planes_bind_to_electrical_graph_without_inventing_path_metrics(
    tmp_path, plane_only
):
    root = Path(os.environ.get("PCBSMITH_NATIVE_FILL_OUTPUT", str(tmp_path))) / (
        "plane-only-return" if plane_only else "traced-return-with-planes"
    )
    root.mkdir(parents=True, exist_ok=False)
    board, layout, netlist, source = fixture(root)
    profile = four_layer_profile()
    layout = replace(
        layout,
        segments=layout.segments[:1] if plane_only else layout.segments,
        zones=tuple(("GND", layer, (1, 1, 41, 19)) for layer in ("In1.Cu", "In2.Cu")),
    )
    board.write_text(render_board_from_layout(netlist, layout, profile=profile), encoding="utf-8")
    board.with_suffix(".kicad_pro").write_text(json.dumps({"board_design_settings": {}}))
    filled, snapshot = refill_and_read_kicad_board(board, root / "fill")
    observed = root / "contacts.json"
    process = subprocess.run(
        [
            "C:/Program Files/KiCad/10.0/bin/python.exe",
            "tools/kicad_final_fill_connectivity_bridge.py",
            str(filled),
            str(observed),
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )
    (root / "contacts.stderr.log").write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    contacts = KiCadFinalFillConnectivityObservation.model_validate_json(observed.read_bytes())
    native = retain_native_fill(filled, snapshot, contacts)
    anchors = native_terminal_anchors(filled, netlist)
    graph = build_routed_copper_graph(
        layout,
        netlist,
        anchors,
        resolve_point_contacts=True,
        copper_layer_order=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
        native_filled_copper=native,
    )
    (root / "graph.json").write_text(graph.model_dump_json(indent=2))
    assert not graph.unknown_zone_reasons
    assert any(e.kind == "exact_zone_fill" for e in graph.edges)
    assert all(e.planar_squared_length is None for e in graph.edges if e.kind == "exact_zone_fill")
    assert RoutedCopperGraphResult.model_validate_json(graph.model_dump_json()) == graph
    source = source.model_copy(
        update={"loops": (source.loops[0].model_copy(update={"require_dedicated": False}),)}
    )
    (result,) = execute_native_loops(
        board=filled,
        layout=layout,
        netlist=netlist,
        profile=profile,
        source=source,
        source_sha256="a" * 64,
        native_filled_copper=native,
    )
    (root / "decoupling.json").write_text(result.model_dump_json(indent=2))
    assert result.disposition.value == ("unverified" if plane_only else "pass")
    if plane_only:
        path = _select_path(graph, "pad:C1:2", "pad:U1:2", "GND", "no-inferred-metric")
        assert path.connectivity_state == "unverified"
        assert path.exact_rational_planar_length_mm is None
    with pytest.raises(ValueError, match="track inventory"):
        build_routed_copper_graph(
            replace(layout, segments=()),
            netlist,
            anchors,
            copper_layer_order=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
            native_filled_copper=native,
        )
