from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.local_routing_repair import RoutingRepairRegion, SelectedRoutingDomain
from pcbsmith.saved_board_routing_evidence import (
    evaluate_saved_routing_candidate,
    extract_saved_routing_snapshot,
)


def _board(path: Path, *, protected_end: int = 20, include_repair: bool = False) -> Path:
    repair = (
        """
  (segment (start 20 10) (end 30 10) (width 0.3) (layer "F.Cu")
    (net 1) (uuid "22222222-2222-2222-2222-222222222222"))"""
        if include_repair
        else ""
    )
    path.write_text(
        f"""(kicad_pcb (version 20240108)
  (net 1 "SIG") (net 2 "GND")
  (segment (start 10 10) (end {protected_end} 10) (width 0.3) (layer "F.Cu")
    (net 1) (uuid "11111111-1111-1111-1111-111111111111")){repair})
""",
        encoding="utf-8",
    )
    return path


def _report(path: Path, *, opens: int = 0) -> Path:
    path.write_text(
        json.dumps(
            {
                "violations": [],
                "unconnected_items": [{} for _ in range(opens)],
                "schematic_parity": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _domain(source: Path) -> SelectedRoutingDomain:
    snapshot = extract_saved_routing_snapshot(source)
    protected = snapshot.objects[0]
    return SelectedRoutingDomain(
        domain_id="sig-open",
        net_names=("SIG",),
        mutable_object_ids=("segment:22222222-2222-2222-2222-222222222222",),
        protected_object_fingerprints=((protected.object_id, protected.content_sha256),),
        initial_region=RoutingRepairRegion(
            x_min_mm=19, y_min_mm=9, x_max_mm=31, y_max_mm=11, expansion_index=0
        ),
        maximum_expansions=0,
    )


def test_exact_restoration_is_hard_clean_and_preserves_protected_route(tmp_path: Path) -> None:
    source = _board(tmp_path / "source.kicad_pcb")
    candidate = _board(tmp_path / "candidate.kicad_pcb", include_repair=True)
    domain = _domain(source)
    metrics = evaluate_saved_routing_candidate(
        source_board=source,
        candidate_board=candidate,
        domain=domain,
        region=domain.initial_region,
        drc_report=_report(tmp_path / "drc.json"),
        required_widths_mm={"SIG": 0.3},
        return_failure_count=0,
        candidate_id="restored",
        engine_id="fixture",
        retained_directory="candidate",
    )
    assert metrics.hard_clean
    assert metrics.protected_change_count == 0
    assert metrics.unrelated_net_change_count == 0
    assert (
        extract_saved_routing_snapshot(source).non_routing_sha256
        == extract_saved_routing_snapshot(candidate).non_routing_sha256
    )


def test_protected_route_mutation_and_open_are_rejected(tmp_path: Path) -> None:
    source = _board(tmp_path / "source.kicad_pcb")
    candidate = _board(tmp_path / "candidate.kicad_pcb", protected_end=21)
    domain = _domain(source)
    metrics = evaluate_saved_routing_candidate(
        source_board=source,
        candidate_board=candidate,
        domain=domain,
        region=domain.initial_region,
        drc_report=_report(tmp_path / "drc.json", opens=1),
        required_widths_mm={"SIG": 0.3},
        return_failure_count=0,
        candidate_id="bad",
        engine_id="fixture",
        retained_directory="candidate",
    )
    assert not metrics.hard_clean
    assert metrics.protected_change_count == 1
    assert metrics.open_count == 1
