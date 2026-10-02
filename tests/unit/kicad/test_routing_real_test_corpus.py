from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pcbsmith.kicad.library import load_footprint
from pcbsmith.kicad.routing_real_test_corpus import (
    TIER_LABELS,
    build_real_test_cases,
    write_real_test_corpus,
)


def test_real_test_has_four_named_tiers_of_ten() -> None:
    cases = build_real_test_cases()

    assert len(cases) == 40
    assert len({case.case_id for case in cases}) == 40
    assert Counter(case.difficulty for case in cases) == {label: 10 for label in TIER_LABELS}
    assert cases[0].case_id == "RT01"
    assert cases[-1].case_id == "RT40"


def test_real_test_progresses_in_components_nets_and_width_intent() -> None:
    cases = build_real_test_cases()
    tiers = {label: [case for case in cases if case.difficulty == label] for label in TIER_LABELS}

    assert [max(len(case.placements) for case in tiers[label]) for label in TIER_LABELS] == sorted(
        max(len(case.placements) for case in tiers[label]) for label in TIER_LABELS
    )
    assert [max(len(case.nets) for case in tiers[label]) for label in TIER_LABELS] == sorted(
        max(len(case.nets) for case in tiers[label]) for label in TIER_LABELS
    )
    assert max(net.width_mm for case in tiers["very_simple"] for net in case.nets) == 0.5
    assert max(net.width_mm for case in tiers["medium"] for net in case.nets) == 1.5


def test_real_test_nodes_bind_to_real_footprint_pads() -> None:
    for case in build_real_test_cases():
        pads = {
            placement.reference: {
                pad.name for pad in load_footprint(placement.footprint).spec.pads if pad.name
            }
            for placement in case.placements
        }
        claimed: set[tuple[str, str]] = set()
        for net in case.nets:
            for node in net.nodes:
                reference, pad = node
                assert reference in pads
                assert pad in pads[reference]
                assert node not in claimed
                claimed.add(node)


def test_real_test_writer_retains_reviewable_kicad_files(tmp_path: Path) -> None:
    summary = write_real_test_corpus(tmp_path)

    assert summary["case_count"] == 40
    assert summary["success_count"] == 40
    assert len(list((tmp_path / "boards").glob("*/*.kicad_pcb"))) == 40
    assert len(list((tmp_path / "boards").glob("*/*.kicad_pro"))) == 40
    assert len(list((tmp_path / "boards").glob("*/generation-evidence.json"))) == 40
    protocol = json.loads((tmp_path / "protocol.json").read_text(encoding="utf-8"))
    assert protocol["tier_counts"] == {label: 10 for label in TIER_LABELS}
    assert "no schematic" in protocol["scope"].lower()
