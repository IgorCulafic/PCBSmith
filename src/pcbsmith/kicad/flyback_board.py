"""Offline flyback board r003: dual-side, 80 x 42 mm, automation-routed.

The FLBACK-001 reference's construction move applied to our circuit:
the PRIMARY half of the FRONT carries the all-THT mains chain (terminal,
fusible resistor, MOV, X2 cap, bridge, 450 V bulk can, clamp passives,
line Y-caps, earth pad); the entire SMD control circuit lives on the
BACK (UCC28881 cluster on the primary side, rectifier/filter/feedback
on the secondary side). Between the halves runs the machine-checked
ISOLATION DIVIDER at x = 51 with a 6.4 mm project copper-spacing target,
crossed only by the three parts built to cross it: the transformer,
the optocoupler, and the Y-capacitor.

Every trace comes from ``route_board`` (Track 8.2) with ordinary project
geometry groups as router keepouts - the same declarations
`run_design_checks` enforces, built once in :func:`flyback_checks_spec`.
The target is not insulation approval. Qualified clearance must come from
a complete rule profile, and creepage still requires surface-path geometry.
No copper pours are used, keeping the copper geometry directly inspectable.

Predecessors: r002 (88 x 50, single-side, hand waypoints) and the
compaction experiment `tools/flyback_compaction.py`; analysis in
`docs/reference-comparisons/flyback-dual-side-compaction.md`. The
42 mm height floor is the TEZ-22x24 transformer body; matching the
reference's 36.8 mm needs an EFD20-class part (a component change).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.kicad.astar_router import (
    clearance_groups_from_spec,
    route_board,
)
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    export_kicad_netlist_xml,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.shaped_board import silk_line, silk_text

BOARD_W = 80.0
BOARD_H = 42.0
BARRIER_X = 51.0
PROJECT_GAP_TARGET_MM = 6.4

PRIMARY_NETS = ("/L", "/N", "/ACL", "/HVP", "/HVM", "/SW", "/CLAMP", "/VDD", "/FB")
EARTH_NETS = ("/EARTH",)
SECONDARY_NETS = ("/SEC", "/3V3", "/GNDS", "/FBS", "/OPK", "/LEDA")
STRADDLE_REFS = ("T1", "U2", "CY1")

HV_W = 0.8   # mains/bus traces
SIG_W = 0.4

# (x, y, rotation) - pad-1 anchors, from the compaction experiment's
# probe -> route -> live-DRC loop. Every gap here was checked against
# the REAL library courtyards (fp_rect hulls included) and the 1.5 mm
# HV pad clearance class.
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
    # x >= 11: the earth track ENTERING CY3.2's exempt pad still owes
    # rule 10.4's 3.0 mm to U1's west pad column (measured live).
    "U1": (11.0, 34.5, 0.0),
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

FLIPPED_REFS: tuple[str, ...] = (
    "CF1", "CO1", "CO2", "CV1", "D5", "D6", "D7",
    "RFB1", "RFB2", "RO1", "RO2", "RP1", "U1", "U3",
)

# Footprint-local (x, y, total angle) reference-label overrides whose
# defaults land on neighbours in this compacted layout (silk model +
# live-DRC discipline). Back-side labels transform INVERSE rotation
# then x-mirror.
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
    "RFB1": (0.0, -2.6, 0.0),   # west of the divider pair
    "RFB2": (-2.6, 0.0, 0.0),   # north of its own body
    "D7": (0.0, 2.5, 0.0),      # south, clear of CO1's pad
}

FLYBACK_NET_WIDTHS: dict[str, float] = {
    net: HV_W
    for net in (*PRIMARY_NETS, *EARTH_NETS, "/SEC", "/3V3", "/GNDS")
}


def flyback_checks_spec() -> DesignChecksSpec:
    """Flyback geometry targets shared by routing and design review.

    These declarations are ordinary project constraints, not qualified
    insulation clearance or creepage approval.
    """
    return DesignChecksSpec(
        net_currents=(("/3V3", 0.5), ("/GNDS", 0.5)),
        isolation_barrier=(
            BARRIER_X,
            PROJECT_GAP_TARGET_MM,
            PRIMARY_NETS,
            SECONDARY_NETS,
            STRADDLE_REFS,
        ),
        net_group_clearances=(
            (
                "primary-to-secondary project geometry target",
                PRIMARY_NETS,
                SECONDARY_NETS,
                PROJECT_GAP_TARGET_MM,
                STRADDLE_REFS,
            ),
            # Ordinary project geometry: protective earth stays away
            # from the mains nets; only the declared line Y-caps bridge.
            (
                "earth-to-primary clearance",
                ("/EARTH",),
                PRIMARY_NETS,
                3.0,
                ("CY2", "CY3"),
            ),
            (
                "earth-to-secondary clearance",
                ("/EARTH",),
                SECONDARY_NETS,
                PROJECT_GAP_TARGET_MM,
                (),
            ),
        ),
        allowed_unconnected_pins=(
            # UCC28881 is a SOIC-7: leads 6/7 are physically absent
            # (datasheet p3); the SOIC-8 land keeps the pads.
            ("U1", "6"), ("U1", "7"),
            # TEZ land pads not used by this winding spec.
            ("T1", "2"), ("T1", "6"), ("T1", "7"),
        ),
    )


def flyback_silk_graphics(origin: float) -> tuple[str, ...]:
    graphics: list[str] = []
    # Rule 10.2: the barrier drawn on silk. The FRONT at x=51 is almost
    # entirely occupied by the straddle parts (U2 y 1.7-6.8, CY1
    # y 7.3-12.3, T1 y 12.8-37.3), so the front carries the free bottom
    # segment plus the ISOLATION text; the BACK is clear along the whole
    # barrier and carries the full dashed line.
    graphics.append(
        silk_line((BARRIER_X, 37.6), (BARRIER_X, 41.0), origin, width=0.4)
    )
    dash_y = 1.0
    while dash_y + 1.5 <= 41.0:
        graphics.append(
            silk_line(
                (BARRIER_X, dash_y), (BARRIER_X, dash_y + 1.5), origin,
                width=0.4, layer="B.SilkS",
            )
        )
        dash_y += 3.0
    graphics.append(silk_text("ISOLATION", (57.5, 39.4), origin, size=1.0))
    graphics.append(silk_text("DANGER 120VAC", (22.0, 9.0), origin, size=1.0))
    graphics.append(silk_text("HV", (28.5, 21.5), origin, size=1.6))
    graphics.append(silk_text("EARTH", (8.0, 16.5), origin, size=0.8))
    graphics.append(silk_text("3V3", (65.5, 20.0), origin, size=1.6))
    return tuple(graphics)


def _unrouted_layout(netlist: BoardNetlist) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    part_rotation: list[tuple[str, float]] = []
    for reference, (x, y, rotation) in PLACEMENTS.items():
        if reference not in by_ref:
            raise BoardGenerationError(f"Netlist is missing {reference}.")
        placements.append((by_ref[reference], x))
        part_y.append((reference, y))
        if rotation:
            part_rotation.append((reference, rotation))
    return BoardLayout(
        placements=tuple(placements),
        segments=(),
        vias=(),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(part_rotation),
        zones=(),
        graphics=flyback_silk_graphics(BOARD_SHEET_ORIGIN_MM),
        part_reference_at=tuple(REFERENCE_AT.items()),
        part_flip=FLIPPED_REFS,
    )


def compute_flyback_board_layout(netlist: BoardNetlist) -> BoardLayout:
    result = route_board(
        _unrouted_layout(netlist),
        netlist,
        net_widths=FLYBACK_NET_WIDTHS,
        default_width_mm=SIG_W,
        clearance_groups=clearance_groups_from_spec(flyback_checks_spec()),
    )
    if result.failed:
        raise BoardGenerationError(
            "route_board could not route: " + ", ".join(result.failed)
        )
    return result.layout


def generate_flyback_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_flyback_board_layout(netlist)
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    return netlist, layout
