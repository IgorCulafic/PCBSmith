from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.kicad.test_board import SAMPLE_NETLIST_XML

from pcbsmith.kicad import board
from pcbsmith.kicad.project_dependencies import retain_project_libraries


def test_reviewed_layout_retains_native_components_and_anchors(tmp_path, monkeypatch):
    xml = tmp_path / "net.xml"
    xml.write_text(SAMPLE_NETLIST_XML, encoding="utf-8")
    netlist = board.parse_board_netlist(SAMPLE_NETLIST_XML)
    layout = board.BoardLayout(
        placements=tuple((c, 7.0 + i * 12) for i, c in enumerate(netlist.components)),
        segments=(),
        vias=(),
        width_mm=50,
        height_mm=30,
        part_y_mm=tuple((c.reference, 15.0) for c in netlist.components),
    )
    monkeypatch.setattr(board, "export_kicad_netlist_xml", lambda *a, **k: xml)
    target = tmp_path / "candidate.kicad_pcb"
    board.generate_board(
        schematic_file=tmp_path / "input.kicad_sch", board_file=target, layout=layout
    )
    saved = target.read_text(encoding="utf-8")
    assert "(at 27 35" in saved
    assert saved.count("(footprint ") == len(netlist.components)
    assert "(segment " not in saved and "(via " not in saved
    target.unlink()
    with pytest.raises(board.BoardGenerationError, match="differs from schematic"):
        board.generate_board(
            schematic_file=tmp_path / "input.kicad_sch",
            board_file=target,
            layout=replace(layout, placements=layout.placements[:-1]),
        )
    assert not target.exists()
    altered = replace(layout.placements[0][0], value="WRONG")
    with pytest.raises(board.BoardGenerationError, match="differs from schematic"):
        board.generate_board(
            schematic_file=tmp_path / "input.kicad_sch",
            board_file=target,
            layout=replace(layout, placements=((altered, 7), *layout.placements[1:])),
        )
    assert not target.exists()


def table(path: Path, uri: str):
    path.write_text(
        f'(sym_lib_table (lib (name "local") (type "KiCad") (uri "{uri}")))', encoding="utf-8"
    )


def test_local_libraries_are_copied_byte_exact_and_snapshotted(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    dest = tmp_path / "isolated"
    symbol = source / "parts.kicad_sym"
    symbol.write_bytes(b"(symbol_lib)\n")
    table(source / "sym-lib-table", "${KIPRJMOD}/parts.kicad_sym")
    lib = source / "footprints.pretty"
    lib.mkdir()
    fp = lib / "part.kicad_mod"
    fp.write_bytes(b'(footprint "real")\n')
    table(source / "fp-lib-table", "${KIPRJMOD}/footprints.pretty")
    snapshots = retain_project_libraries(source, dest)
    assert snapshots == {symbol: symbol.read_bytes(), fp: fp.read_bytes()}
    assert (dest / "parts.kicad_sym").read_bytes() == symbol.read_bytes()
    assert (dest / "footprints.pretty/part.kicad_mod").read_bytes() == fp.read_bytes()
    (dest / "parts.kicad_sym").write_bytes(b"changed")
    with pytest.raises(ValueError, match="collision"):
        retain_project_libraries(source, dest)
    assert symbol.read_bytes() == snapshots[symbol]


@pytest.mark.parametrize(
    "uri", ["${KIPRJMOD}/../outside.kicad_sym", "${KIPRJMOD}/", "${KIPRJMOD}/missing.kicad_sym"]
)
def test_local_library_missing_or_escape_is_rejected(tmp_path, uri):
    source = tmp_path / "source"
    source.mkdir()
    table(source / "sym-lib-table", uri)
    with pytest.raises(ValueError):
        retain_project_libraries(source, tmp_path / "isolated")


def test_generation_retains_missing_library_failure_before_builder(tmp_path, monkeypatch):
    from tests.unit.test_production_readiness import readiness_fixture

    from pcbsmith.production_generators import generate_registered_board_candidate

    source, evidence, request = readiness_fixture(tmp_path)
    # Use an initial-generation source: constructing a rebuild decision after
    # breaking its dependency closure fails before this generator is entered.
    initial = tmp_path / "initial"
    initial.mkdir()
    schematic = initial / "initial.kicad_sch"
    schematic.write_bytes(source.with_suffix(".kicad_sch").read_bytes())
    table(initial / "sym-lib-table", "${KIPRJMOD}/absent.kicad_sym")

    def unreachable(*, schematic_file, board_file):
        pytest.fail("builder must not run")

    monkeypatch.setattr(board, "generate_board", unreachable)
    output = tmp_path / "failed-attempt"
    with pytest.raises(ValueError, match="missing"):
        generate_registered_board_candidate(
            generator_id="pcbsmith.kicad.board:generate_board",
            schematic_file=schematic,
            output_directory=output,
            predesign=request.predesign,
            artifact_root=evidence,
        )
    assert (output / "builder-failure.json").is_file()


@pytest.fixture(autouse=True)
def isolated_producer_contracts(monkeypatch):
    """Synthetic inner-contract tests; real job authorization is tested separately."""
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    # These are inner generation/retention contracts, not floorplan acceptance tests.
    monkeypatch.setattr(
        "pcbsmith.kicad.floorplan.require_floorplan",
        lambda *a: {"width_mm": 1, "height_mm": 1, "placements": {}},
    )
    monkeypatch.setattr("pcbsmith.kicad.floorplan.require_native_floorplan", lambda *a, **k: None)
