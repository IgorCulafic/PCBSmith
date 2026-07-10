"""Dual-side flyback compaction experiment (Track 8.2 follow-up).

Goal: shrink the 88 x 50 mm flyback r002 toward the FLBACK-001
reference (80.4 x 36.8 mm) by moving the SMD control circuitry to the
BACK, the way the reference does. Our TEZ-22x24 transformer is
physically larger than their EFD20 (24.5 x 22.5 mm courtyard), so the
honest floor for this magnetics choice is ~80 x 40.

Stages (each gated by the machinery that judges real boards):
1. courtyard/silk pre-gate on the hand-drafted dual-side placements
2. route_board with the rule-10.1 creepage clearance groups
3. layout_score (virtual DRC + design checks as hard gates)
4. climb_placements polish (nudge / rotate / flip local search)
5. write the routed .kicad_pcb + a score report for review

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
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.export_flyback import INSTANCES
from pcbsmith.kicad.flyback_board import (
    EARTH_NETS,
    HV_W,
    ISOLATION_GAP_MM,
    PRIMARY_NETS,
    SECONDARY_NETS,
    SIG_W,
    STRADDLE_REFS,
)
from pcbsmith.kicad.layout_score import score_layout
from pcbsmith.kicad.placement_search import (
    _pre_gate,
    bare_layout,
    climb_placements,
)

BOARD_W = 80.0
BOARD_H = 42.0
BARRIER_X = 51.0

# (x, y, rotation). Anchors chosen against the probed courtyard hulls;
# the pre-gate (courtyards + real-metric silk model) is the referee.
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    # -- front, primary THT ------------------------------------------
    "J1": (4.5, 7.8, 0.0),
    "E1": (3.0, 16.5, 0.0),
    "CY2": (14.5, 22.5, 180.0),
    "CY3": (14.5, 29.5, 180.0),
    "RF1": (17.0, 3.5, 0.0),
    "RV1": (37.0, 8.7, 180.0),
    "CX1": (33.0, 14.2, 180.0),
    "BR1": (25.0, 25.0, 180.0),
    "CB1": (34.5, 32.0, 180.0),
    "TP1": (37.0, 20.0, 0.0),
    "RC1": (3.5, 38.5, 0.0),
    "CC1": (23.5, 38.5, 90.0),
    # -- the barrier band --------------------------------------------
    "T1": (43.0, 17.5, 270.0),
    "U2": (55.0, 5.0, 180.0),
    "CY1": (45.0, 9.75, 0.0),
    # -- front, secondary --------------------------------------------
    "TP2": (58.0, 8.0, 0.0),
    "J2": (71.0, 33.5, 0.0),
    # -- back, primary SMD control -----------------------------------
    # U1's cluster lives in the only back-primary pocket clear of THT
    # annuli (CY2/CY3/CB1/BR1/RC1 pads all poke through): the HV pad
    # clearance is 1.5 mm edge-to-edge and placement must supply it.
    "U1": (9.5, 34.5, 0.0),
    "CV1": (12.5, 25.5, 0.0),
    "RP1": (8.5, 27.0, 0.0),
    "D5": (33.0, 20.0, 90.0),
    "D6": (35.0, 37.0, 0.0),
    # -- back, secondary SMD -----------------------------------------
    # D7/RO1 keep >2.5 mm from the T1 secondary pin row at x=58: the
    # UNUSED transformer pins are still THT copper and wall in any SMD
    # pad parked next to them (grid router lesson).
    "D7": (62.5, 28.0, 0.0),
    "CO1": (64.0, 20.0, 90.0),
    "CO2": (60.0, 34.0, 0.0),
    "U3": (71.0, 15.0, 0.0),
    "RFB1": (75.0, 28.0, 90.0),
    "RFB2": (77.5, 28.0, 90.0),
    "RO1": (55.5, 18.0, 90.0),
    "RO2": (59.5, 5.5, 0.0),
    "CF1": (72.5, 24.0, 90.0),
}

FLIPPED: frozenset[str] = frozenset(
    {"U1", "CV1", "RP1", "D5", "D6",
     "D7", "CO1", "CO2", "U3", "RFB1", "RFB2", "RO1", "RO2", "CF1"}
)

# Footprint-local (x, y, total angle) reference-label overrides whose
# defaults land on neighbours in this compacted layout (silk model +
# live-DRC discipline, same mechanism as the r002 board).
REFERENCE_AT: dict[str, tuple[float, float, float]] = {
    "E1": (0.0, 3.3, 0.0),      # below the wire pad, off J1's body
    "RF1": (7.62, 3.5, 0.0),    # south of the axial body (edge clip)
    "CX1": (7.5, 0.5, 0.0),     # over its own film body, off BR1
    "BR1": (3.8, 2.4, 0.0),     # over its own body, off CC1
    "U2": (-2.5, 2.5, 0.0),     # east of the DIP, clear of CY1
    "CY1": (12.0, 1.25, 0.0),   # east of the disc, under TP2
    "U1": (0.0, 4.2, 0.0),      # south of the SOIC (back silk)
    "CO2": (0.0, 2.0, 0.0),     # south of the cap, off T1's pads
    "RO2": (0.0, -1.7, 0.0),    # north of the body, off TP2's annulus
    "CY3": (3.5, 0.0, 0.0),     # over its own disc, off RC1's label
    # Live kicad-cli findings: KiCad's real text boxes put these three
    # back-silk labels on neighbouring pads/outlines. Back side label
    # transform is INVERSE rotation then x-mirror.
    "RFB1": (0.0, -2.6, 0.0),   # west of the divider pair
    "RFB2": (-2.6, 0.0, 0.0),   # north of its own body
    "D7": (0.0, 2.5, 0.0),      # south, clear of CO1's pad
}


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


def checks_spec() -> DesignChecksSpec:
    return DesignChecksSpec(
        isolation_barrier=(
            BARRIER_X, ISOLATION_GAP_MM,
            PRIMARY_NETS, SECONDARY_NETS, STRADDLE_REFS,
        ),
        allowed_unconnected_pins=(
            ("U1", "6"), ("U1", "7"),
            ("T1", "2"), ("T1", "6"), ("T1", "7"),
        ),
    )


def net_widths() -> dict[str, float]:
    return {
        net: HV_W
        for net in (*PRIMARY_NETS, *EARTH_NETS, "/SEC", "/3V3", "/GNDS")
    }


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "outputs/flyback-compaction"
    )
    skip_climb = "--skip-climb" in sys.argv
    output_dir.mkdir(parents=True, exist_ok=True)

    netlist = offline_netlist()
    spec = checks_spec()
    groups = clearance_groups_from_spec(spec)

    layout = bare_layout(
        netlist, PLACEMENTS, width_mm=BOARD_W, height_mm=BOARD_H,
        part_flip=FLIPPED,
        part_reference_at=tuple(REFERENCE_AT.items()),
    )
    gate = _pre_gate(layout, netlist)
    if gate:
        print(f"PRE-GATE: {gate}")
        return 1
    print("pre-gate: clean (courtyards + silk model)")

    outcome = route_board(
        layout, netlist,
        net_widths=net_widths(), default_width_mm=SIG_W,
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
    best_flipped = FLIPPED
    if not skip_climb and score.is_viable:
        trajectory = climb_placements(
            netlist, PLACEMENTS,
            board_w=BOARD_W, board_h=BOARD_H,
            movable=tuple(PLACEMENTS),
            rotatable=tuple(FLIPPED),
            flippable=tuple(FLIPPED),
            base_flipped=FLIPPED,
            rounds=3, candidates=6, seed=1,
            net_widths=net_widths(), clearance_groups=groups,
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
        "barrier_x": BARRIER_X,
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
