"""Dual-side flyback polish harness (Track 8.2 follow-up).

Originally the compaction EXPERIMENT that produced the 80 x 42 dual-side
layout; that layout was promoted into `kicad/flyback_board.py` (r003)
and this script now imports the promoted placements instead of carrying
its own copy - one truth, no drift. What remains here is the search
harness: route the promoted base, score it, then run the
`climb_placements` polish (nudge / rotate / side-flip local search)
and report whether the incumbent improves.

History and analysis:
`docs/reference-comparisons/flyback-dual-side-compaction.md`.

Run:  python -X utf8 tools/flyback_compaction.py <output-dir> [--skip-climb]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.flyback import compose_flyback
from pcbsmith.kicad.astar_router import (
    clearance_groups_from_spec,
    route_board,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardNet,
    BoardNetlist,
    render_board_from_layout,
)
from pcbsmith.kicad.export_flyback import INSTANCES
from pcbsmith.kicad.flyback_board import (
    BOARD_H,
    BOARD_W,
    FLIPPED_REFS,
    FLYBACK_NET_WIDTHS,
    PLACEMENTS,
    REFERENCE_AT,
    SIG_W,
    flyback_checks_spec,
)
from pcbsmith.kicad.layout_score import score_layout
from pcbsmith.kicad.placement_search import (
    _pre_gate,
    bare_layout,
    climb_placements,
)


def offline_netlist() -> BoardNetlist:
    intent = classify_circuit_intent("120 VAC to 3.3 V flyback converter")
    design = compose_flyback(intent, select_topology(intent))
    footprints = {c.reference: c.footprint for c in design.components}
    nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for reference, _lib, _x, pin_nets in INSTANCES:
        for pin, net in pin_nets.items():
            nodes[net].append((reference, pin))
    return BoardNetlist(
        components=tuple(
            BoardComponent(
                reference=reference, value=reference, footprint=footprint,
                uuid_path=f"uuid-{reference}",
            )
            for reference, footprint in footprints.items()
        ),
        nets=tuple(
            BoardNet(name=f"/{name}", nodes=tuple(pins))
            for name, pins in sorted(nodes.items())
        ),
    )


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "outputs/flyback-compaction"
    )
    skip_climb = "--skip-climb" in sys.argv
    output_dir.mkdir(parents=True, exist_ok=True)

    netlist = offline_netlist()
    spec = flyback_checks_spec()
    groups = clearance_groups_from_spec(spec)
    flipped = frozenset(FLIPPED_REFS)

    layout = bare_layout(
        netlist, PLACEMENTS, width_mm=BOARD_W, height_mm=BOARD_H,
        part_flip=flipped,
        part_reference_at=tuple(REFERENCE_AT.items()),
    )
    gate = _pre_gate(layout, netlist)
    if gate:
        print(f"PRE-GATE: {gate}")
        return 1
    print("pre-gate: clean (courtyards + silk model)")

    outcome = route_board(
        layout, netlist,
        net_widths=FLYBACK_NET_WIDTHS, default_width_mm=SIG_W,
        clearance_groups=groups,
    )
    if outcome.failed:
        print(f"ROUTING FAILED: {outcome.failed} after "
              f"{outcome.restarts} restarts")
        return 1
    score = score_layout(outcome.layout, netlist, spec)
    print(
        f"routed: track={score.total_track_mm:.0f}mm "
        f"vias={score.via_count} hard_violations={score.hard_violations}"
    )
    for finding in (*score.virtual_drc_findings, *score.blocker_findings):
        print(f"  finding: {finding}")

    best_layout = outcome.layout
    best_score = score
    best_placements = dict(PLACEMENTS)
    best_flipped = flipped
    if not skip_climb and score.is_viable:
        trajectory = climb_placements(
            netlist, PLACEMENTS,
            board_w=BOARD_W, board_h=BOARD_H,
            movable=tuple(PLACEMENTS),
            rotatable=FLIPPED_REFS,
            flippable=FLIPPED_REFS,
            base_flipped=flipped,
            rounds=3, candidates=6, seed=1,
            net_widths=FLYBACK_NET_WIDTHS, clearance_groups=groups,
            spec=spec,
            part_reference_at=tuple(REFERENCE_AT.items()),
            on_progress=lambda line: print(f"  climb: {line}"),
        )
        if trajectory and trajectory[-1].score is not None:
            final = trajectory[-1]
            if final.layout is not None and final.score is not None:
                best_layout = final.layout
                best_score = final.score
                best_placements = dict(final.placements)
                best_flipped = final.flipped

    board_file = output_dir / "flyback-compact.kicad_pcb"
    board_file.write_text(
        render_board_from_layout(netlist, best_layout), encoding="utf-8"
    )
    report = {
        "board_mm": [BOARD_W, BOARD_H],
        "reference_mm": [80.4, 36.8],
        "previous_mm": [88.0, 50.0],
        "flipped": sorted(best_flipped),
        "placements": best_placements,
        "score": best_score.as_dict(),
        "route_restarts": outcome.restarts,
    }
    (output_dir / "compaction-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(f"board: {board_file}")
    print(f"score: {json.dumps(best_score.as_dict(), indent=2)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
