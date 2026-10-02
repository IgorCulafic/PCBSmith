import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.kicad.test_routing_external_adapters import _binding, _layout, _request

from pcbsmith.kicad import routing_external_adapters as adapters
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.freerouting_production import constrain_single_sided_dsn
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.routing_ir import RouteRequest, RoutingBudget


def external_request():
    r = _request(_layout())
    return RouteRequest.model_validate(
        {
            **r.model_dump(),
            "allowed_layers": ["F.Cu"],
            "via_technologies": [],
            "budget": {
                **r.budget.model_dump(),
                "max_expansions": 0,
                "max_expansions_per_net": 0,
                "external_process_seconds": 20,
            },
        }
    )


def test_external_budget_cannot_claim_native_expansions():
    with pytest.raises(ValueError, match="no expansion claim"):
        RoutingBudget(
            max_passes=4,
            max_expansions=10,
            max_expansions_per_net=10,
            max_stagnant_passes=0,
            max_exact_check_rejections=0,
            external_process_seconds=20,
        )


def test_single_sided_dsn_keeps_widths_clearance_and_inset():
    dsn = (
        '(pcb x (parser (string_quote ")) (unit um) (structure (layer F.Cu (type signal)) '
        "(layer B.Cu (type signal)) (boundary (rect pcb 0 0 30000 12000)) (via v1) (rule "
        "(width 200) (clearance 200) (clearance 50 (type smd_smd)))) "
        "(library (padstack v1 (shape (circle F.Cu 600)) (shape (circle B.Cu 600)))) "
        "(network (net /SIG (pins "
        "R1-2 R2-1)) (class Default /SIG (rule (width 200) (clearance 200)))))"
    )
    data = constrain_single_sided_dsn(dsn, _layout(), external_request(), 2).decode()
    tree = parse_sexpr(data.replace('(string_quote ")', "(string_quote double_quote)"))
    structure = _children(tree, "structure")[0]
    assert [_atom(n[1]) for n in _children(structure, "layer")] == ["F.Cu"]
    assert [_atom(n) for n in _children(structure, "via")[0][1:]] == [
        "PCBSMITH_NoVia_Compatibility"
    ]
    settings = _children(structure, "autoroute_settings")[0]
    assert _children(settings, "vias") == [["vias", "off"]]
    library = _children(tree, "library")[0]
    stacks = _children(library, "padstack")
    assert len(stacks) == 1
    assert [_atom(n[1][1]) for n in _children(stacks[0], "shape")] == ["F.Cu"]
    cls = _children(_children(tree, "network")[0], "class")[0]
    assert _atom(_children(_children(cls, "circuit")[0], "use_via")[0][1]) == (
        "PCBSMITH_NoVia_Compatibility"
    )
    assert "(width 400.0)" in data
    assert "(clearance 50" not in data
    assert "22200.0" in data


@pytest.mark.parametrize("verified", [True, False])
def test_external_completion_needs_real_verifier_and_owned_timeout(tmp_path, monkeypatch, verified):
    jar = tmp_path / "router.jar"
    jar.write_bytes(b"fixture")
    observed = []

    def run(command, **kwargs):
        observed.append(kwargs["timeout"])
        Path(command[command.index("-do") + 1]).write_bytes(b"session")
        return subprocess.CompletedProcess(command, 0, b"fixture", b"")

    monkeypatch.setattr(adapters.subprocess, "run", run)
    result = adapters.run_freerouting_dsn_ses_candidate(
        request=external_request(),
        source_layout=_layout(),
        candidate_directory=tmp_path / "candidate",
        spec=adapters.FREEROUTING_V2_3_0,
        binding=_binding(jar),
        dsn_payload=b"fixture",
        ses_importer=lambda _: replace(
            _layout(), segments=(TrackSegment(1, 1, 3, 1, "F.Cu", "/SIG", 0.4),)
        ),
        completion_verifier=lambda: verified,
    )
    assert observed == [20]
    assert (result.partial_status.value == "complete") == verified
    assert bool(result.failures) != verified


def test_two_layer_dsn_preserves_layers_and_binds_via_rules():
    from pcbsmith.kicad.freerouting_production import constrain_freerouting_dsn

    dsn = (
        "(pcb x (unit um) (structure (layer F.Cu (type signal)) (layer B.Cu (type signal)) "
        "(boundary (rect pcb 0 0 30000 12000)) (via old)) (library (padstack old (shape "
        "(circle F.Cu 900)))) (network (net /SIG (pins R1-2 R2-1)) (class Default /SIG "
        "(circuit (use_via old)) (rule (width 200) (clearance 200)))))"
    )
    tree = parse_sexpr(constrain_freerouting_dsn(dsn, _layout(), _request(_layout()), 2).decode())
    structure = _children(tree, "structure")[0]
    assert [_atom(n[1]) for n in _children(structure, "layer")] == ["F.Cu", "B.Cu"]
    name = _atom(_children(structure, "via")[0][1])
    assert name == "Via[0-1]_600:300_um"
    padstack = _children(_children(tree, "library")[0], "padstack")[0]
    assert _atom(padstack[1]) == name
    assert [float(n[1][2]) for n in _children(padstack, "shape")] == [600, 600]
    cls = _children(_children(tree, "network")[0], "class")[0]
    assert _atom(_children(_children(cls, "circuit")[0], "use_via")[0][1]) == name


@pytest.mark.parametrize("diameter,allowed", [(0.6, True), (0.9, False)])
def test_two_layer_readback_accepts_only_declared_vias(tmp_path, diameter, allowed):
    from pcbsmith.kicad.freerouting_production import read_single_sided_routes

    source = tmp_path / "source.kicad_pcb"
    board = tmp_path / "routed.kicad_pcb"
    source.write_text('(kicad_pcb (net 1 "/SIG"))')
    board.write_text(
        f'(kicad_pcb (net 1 "/SIG") (segment (start 21 21) (end 23 21) (width 0.4) (layer "B.Cu") (net 1)) (via (at 23 21) (size {diameter}) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1)))'  # noqa: E501 -- native fixture
    )
    if allowed:
        result = read_single_sided_routes(board, source, _layout(), _request(_layout()))
        assert result.segments[0].layer == "B.Cu"
        assert len(result.vias) == 1 and result.vias[0].size_mm == 0.6
    else:
        with pytest.raises(ValueError, match="declared through-via"):
            read_single_sided_routes(board, source, _layout(), _request(_layout()))
    with pytest.raises(ValueError, match="forbidden vias"):
        read_single_sided_routes(board, source, _layout(), external_request())


def test_production_dispatch_retains_external_nonempty_logs(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from pcbsmith import production_routing
    from pcbsmith.kicad import freerouting_production

    expected = SimpleNamespace()

    def external(**kwargs):
        folder = kwargs["work"] / "engine"
        folder.mkdir(parents=True)
        (folder / "stdout.log").write_bytes(b"actual external stdout\r\n")
        (folder / "stderr.log").write_bytes(b"actual external diagnostic\n")
        return expected

    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    monkeypatch.setattr(freerouting_production, "route_freerouting_production", external)
    result = production_routing._dispatch_routing_candidate(
        external_request(),
        tmp_path,
        board=tmp_path / "board.kicad_pcb",
        layout=_layout(),
        netlist=None,
        profile=None,
        external=object(),
    )
    assert result is expected
    for stream in ("stdout", "stderr"):
        assert (tmp_path / "engine" / f"{stream}.log").read_bytes() == (
            tmp_path / "freerouting/engine" / f"{stream}.log"
        ).read_bytes()


@pytest.mark.parametrize("layer,width", [("B.Cu", 0.4), ("F.Cu", 0.1)])
def test_single_layer_import_rejects_back_copper_and_narrow_tracks(tmp_path, layer, width):
    from pcbsmith.kicad.freerouting_production import read_single_sided_routes

    source = tmp_path / "source.kicad_pcb"
    board = tmp_path / "routed.kicad_pcb"
    source.write_text('(kicad_pcb (net 1 "/SIG"))')
    board.write_text(
        f'(kicad_pcb (net 1 "/SIG") (segment (start 21 21) (end 23 21) '
        f'(width {width}) (layer "{layer}") (net 1)))'
    )
    with pytest.raises(ValueError, match="layer or requested minimum width"):
        read_single_sided_routes(board, source, _layout(), external_request())


def test_single_layer_overrides_existing_via_settings_idempotently():
    dsn = (
        "(pcb x (unit um) (structure (layer F.Cu (type signal)) "
        "(layer B.Cu (type signal)) (boundary (rect pcb 0 0 30000 12000)) "
        "(via old) (autoroute_settings (vias on))) "
        "(library (padstack old (shape (circle F.Cu 600)) (shape (circle B.Cu 600)))) "
        "(network (net /SIG (pins R1-2 R2-1)) (class Default /SIG "
        "(circuit (use_via old)) (rule (width 200) (clearance 200)))))"
    )
    data = constrain_single_sided_dsn(dsn, _layout(), external_request(), 2)
    assert constrain_single_sided_dsn(data.decode(), _layout(), external_request(), 2) == data
    assert b"(vias off)" in data and b"(vias on)" not in data and b"B.Cu" not in data
