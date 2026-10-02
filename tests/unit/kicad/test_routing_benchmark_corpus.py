from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pcbsmith.kicad.board import render_board_from_layout
from pcbsmith.kicad.library import load_footprint
from pcbsmith.kicad.routing_benchmark_corpus import (
    build_routing_benchmark_cases,
    case_layout,
    case_netlist,
    register_benchmark_footprints,
    write_routing_benchmark_corpus,
)


def test_corpus_has_five_balanced_tiers_and_unique_ids() -> None:
    cases = build_routing_benchmark_cases()

    assert len(cases) == 40
    assert len({case.case_id for case in cases}) == 40
    assert Counter(case.tier for case in cases) == {1: 8, 2: 8, 3: 8, 4: 8, 5: 8}
    assert cases[0].case_id == "RC01"
    assert cases[-1].case_id == "RC40"


def test_corpus_progresses_to_dense_and_width_driven_cases() -> None:
    cases = build_routing_benchmark_cases()

    assert max(len(case.placements) for case in cases[:8]) < max(
        len(case.placements) for case in cases[-8:]
    )
    assert max(net.width_mm for case in cases[:8] for net in case.nets) == 0.5
    assert max(net.width_mm for case in cases[-8:] for net in case.nets) == 2.0
    assert all("two-layer" in case.tags for case in cases)


def test_every_node_binds_to_a_real_footprint_pad() -> None:
    register_benchmark_footprints()
    for case in build_routing_benchmark_cases():
        pad_names = {
            placement.reference: {
                pad.name for pad in load_footprint(placement.footprint).spec.pads if pad.name
            }
            for placement in case.placements
        }
        claimed_nodes: set[tuple[str, str]] = set()
        for net in case.nets:
            assert len(set(net.nodes)) >= 2
            for reference, pad in net.nodes:
                assert reference in pad_names
                assert pad in pad_names[reference]
                assert (reference, pad) not in claimed_nodes
                claimed_nodes.add((reference, pad))


def test_first_and_last_cases_serialize_as_kicad_boards() -> None:
    register_benchmark_footprints()
    cases = build_routing_benchmark_cases()
    for case in (cases[0], cases[-1]):
        board = render_board_from_layout(case_netlist(case), case_layout(case))
        assert board.startswith("(kicad_pcb")
        assert 'layer "Edge.Cuts"' in board
        assert "(footprint" in board


def test_writer_retains_contract_and_kicad_files(tmp_path: Path) -> None:
    summary = write_routing_benchmark_corpus(tmp_path)

    assert summary["case_count"] == 40
    assert len(list((tmp_path / "boards").glob("*/case-contract.json"))) == 40
    assert len(list((tmp_path / "boards").glob("*/*.kicad_pcb"))) == 40
    assert len(list((tmp_path / "boards").glob("*/*.kicad_pro"))) == 40
    protocol = json.loads((tmp_path / "protocol.json").read_text(encoding="utf-8"))
    assert "no electrical" in protocol["qualification_boundary"].lower()
    assert (tmp_path / "artifact-manifest.json").exists()
