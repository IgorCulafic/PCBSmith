"""Opt-in pinned-engine smoke on a synthetic interchange, never a production board."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from tests.unit.kicad.test_routing_external_adapters import _layout
from tests.unit.kicad.test_routing_net_constraints import two_net_request

from pcbsmith.kicad.freerouting_production import (
    FreeroutingProductionConfig,
    constrain_freerouting_dsn,
)
from pcbsmith.kicad.library import _atom, _children, parse_sexpr

SYNTHETIC_DSN = """(pcb constraint-fixture
(parser (string_quote ") (space_in_quoted_tokens on))
(resolution um 10) (unit um)
(structure (layer F.Cu (type signal) (property (index 0)))
(layer B.Cu (type signal) (property (index 1)))
(boundary (rect pcb 20000 -32000 50000 -20000)) (via old)
(rule (width 400) (clearance 200)))
(placement
(component front (place A 25000 -24500 front 0) (place B 45000 -24500 front 0)
(place C 25000 -28000 front 0))
(component rear (place D 45000 -28000 front 0)))
(library (image front (pin pf 1 0 0)) (image rear (pin pb 1 0 0))
(padstack pf (shape (circle F.Cu 1500)))
(padstack pb (shape (circle B.Cu 1500)))
(padstack old (shape (circle F.Cu 600)) (shape (circle B.Cu 600))))
(network (net /SIG (pins A-1 B-1)) (net /AUX (pins C-1 D-1))
(class Default /SIG /AUX (circuit (use_via old)) (rule (width 400) (clearance 200)))))"""


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_FREEROUTING_CONSTRAINT_SMOKE"),
    reason="requires local pinned Freerouting configuration",
)
@pytest.mark.parametrize("impossible_power", [False, True])
def test_pinned_router_obeys_power_class_without_disabling_signal_vias(tmp_path, impossible_power):
    config = FreeroutingProductionConfig.model_validate_json(
        Path(".pcbsmith/freerouting.json").read_bytes()
    )
    config.preflight()
    folder = Path(os.environ.get("PCBSMITH_CONSTRAINT_SMOKE_OUTPUT", str(tmp_path))).resolve()
    folder = folder / ("impossible" if impossible_power else "feasible")
    folder.mkdir(parents=True, exist_ok=True)
    source, output = folder / "synthetic.dsn", folder / "synthetic.ses"
    assert not source.exists() and not output.exists(), "retain previous smoke evidence"
    payload = SYNTHETIC_DSN
    if impossible_power:
        payload = payload.replace("(place B 45000 -24500 front 0)", "")
        payload = payload.replace(
            "(component rear ", "(component rear (place B 45000 -24500 front 0) "
        )
    source.write_bytes(constrain_freerouting_dsn(payload, _layout(), two_net_request(), 1))
    command = [
        config.java_executable,
        "-jar",
        config.binding.entrypoint_path,
        "-de",
        str(source),
        "-do",
        str(output),
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
    ]
    result = subprocess.run(command, capture_output=True, timeout=60, check=False)
    (folder / "stdout.log").write_bytes(result.stdout)
    (folder / "stderr.log").write_bytes(result.stderr)
    assert result.returncode == 0 and output.is_file()
    assert b"via rule not found" not in result.stdout
    tree = parse_sexpr(
        output.read_text(encoding="utf-8").replace(
            '(string_quote ")', "(string_quote double_quote)"
        )
    )
    routes = _children(tree, "routes")[0]
    network = _children(routes, "network_out")[0]
    nets = {_atom(n[1]): n for n in _children(network, "net")}
    assert "/AUX" in nets
    power = nets.get("/SIG", [])
    power_wires = _children(power, "wire")
    assert not _children(power, "via")
    if impossible_power:
        assert b"1 unrouted and 0 violations" in result.stdout
    else:
        assert power_wires
        assert b"0 unrouted and 0 violations" in result.stdout
    assert all(_atom(_children(w, "path")[0][1]) == "F.Cu" for w in power_wires)
    signal_vias = _children(nets["/AUX"], "via")
    assert signal_vias, "cross-face signal must retain its independent via permission"
    (folder / "result.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "purpose": "synthetic adapter qualification only",
                "impossible_power_connection": impossible_power,
                "power_net_layers": ["F.Cu"],
                "power_vias": 0,
                "signal_vias": len(signal_vias),
                "router_sha256": config.binding.entrypoint_sha256,
                "production_board_modified_or_routed": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
