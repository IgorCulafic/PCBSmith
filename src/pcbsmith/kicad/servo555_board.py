"""555 servo tester board: the first automation-routed PCBSmith board.

The module supplies only the *placement* (coarse, requirement-driven:
power entry west, servo header east, buttons on the south edge, test
pads along the north edge, timing parts hugging the 555) plus zones and
silkscreen; every trace comes from ``route_board`` (Track 8.2's A*
router) instead of hand-listed waypoints. Solid GND pours on both
layers, 1.0 mm (>= 40 mil) VCC/GND traces, M3 mounting holes in all
four corners. 56 x 40 mm: slightly over the requested ~50 x 35 because
every component value lives on the silkscreen at KiCad's 0.8 mm text
minimum, which needs real corridors between part outlines.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.kicad.astar_router import route_board
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    export_kicad_netlist_xml,
    mounting_hole_placements,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.shaped_board import silk_text

BOARD_W = 56.0
BOARD_H = 40.0

POWER_NETS = ("/VCC", "/GND")
POWER_W = 1.0  # >= 40 mil for the servo current path
SIG_W = 0.4

# (x, y, rotation) - pad-1 anchors. The servo current path (J1 -> C4 ->
# J2) runs along the south/east while the timing network (R1/C1/C2)
# stays at the 555's own pins in the center. Vertical pitch in the
# capacitor column is 5.3 mm: KiCad silk text is ~1.5 mm tall at the
# 0.8 mm DRC minimum, and the value labels need a real corridor between
# part outlines (the 52x38 first cut failed live silk DRC on this).
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "J1": (7.0, 20.0, 90.0),     # power entry, west edge, wires exit west
    "U1": (19.0, 15.0, 0.0),     # DIP-8 socket, pin 1 north-west
    "R4": (31.5, 5.0, 0.0),      # OUT -> base, north lane
    "R1": (31.5, 9.3, 0.0),      # VCC -> DISCH charge resistor
    "C3": (31.2, 13.3, 0.0),     # VCC bypass beside pin 8
    "C1": (31.2, 18.6, 0.0),     # timing cap at THRES (pin 6)
    "C2": (31.2, 23.9, 0.0),     # CONT bypass at pin 5
    "R2": (11.0, 27.5, 0.0),     # FORWARD branch to SW1
    "R3": (25.0, 27.6, 0.0),     # REVERSE branch to SW2
    "SW1": (12.0, 31.5, 0.0),    # FWD button, south edge
    "SW2": (24.5, 31.5, 0.0),    # REV button, south edge
    "R5": (39.0, 13.3, 0.0),     # collector pull-up toward the header
    "Q1": (39.5, 18.5, 0.0),     # BC547 inverter
    "C4": (41.5, 28.6, 0.0),     # bulk cap beside the servo header
    "J2": (52.5, 18.0, 0.0),     # servo header, east edge
    "TP1": (12.0, 4.5, 0.0),     # test pads along the north edge
    "TP2": (17.0, 4.5, 0.0),
    "TP3": (22.0, 4.5, 0.0),
    "TP4": (27.0, 4.5, 0.0),
}

# Footprint-local reference label overrides (crowded neighbours; KiCad
# checks reference fields against other footprints' silk with REAL text
# metrics, so every label below sits in a measured >=0.2 mm corridor).
REFERENCE_AT: dict[str, tuple[float, float, float]] = {
    "J1": (-4.5, 0.0, 0.0),   # south of the body; rotation walks the
                              # default label off the west board edge
    "R1": (-2.3, 0.0, 0.0),   # west gap; default lands on R4's body
    "C1": (-2.3, 0.0, 0.0),   # west gap, clear of the disc pads
    "C2": (-2.3, 0.0, 0.0),   # west gap; default lands on C1's body
    "C3": (-2.3, 0.0, 0.0),   # west gap; default lands on its value text
    "R3": (12.3, 0.0, 0.0),   # east of pad 2; default lands on C2's body
    "SW1": (-3.5, 2.3, 0.0),  # west gap; default touches R2's outline
    "SW2": (10.3, 2.3, 0.0),  # east gap; default touches R3's outline
    "Q1": (1.27, 3.1, 0.0),   # below the body; default touches R5's
    "J2": (0.0, 7.5, 0.0),    # below the pads; default sits near R5.2
    "C4": (1.75, 5.4, 0.0),   # below the can; default lands on the value
}

# Solid GND pour on BOTH layers (requirement); the router's explicit
# GND traces guarantee connectivity even where the pour necks down.
ZONES: tuple[tuple[str, str, tuple[float, float, float, float]], ...] = (
    ("/GND", "F.Cu", (1.5, 1.5, BOARD_W - 1.5, BOARD_H - 1.5)),
    ("/GND", "B.Cu", (1.5, 1.5, BOARD_W - 1.5, BOARD_H - 1.5)),
)


def servo555_silk_graphics(origin: float) -> tuple[str, ...]:
    # All sizes >= 0.8 mm: the board's silk text-height DRC minimum.
    texts: tuple[tuple[str, float, float, float], ...] = (
        # Connector + control labels.
        ("5-6V", 7.0, 10.9, 0.8),
        ("+V", 14.7, 20.0, 0.8),
        ("GND", 14.7, 14.92, 0.8),
        ("FWD", 15.25, 38.6, 1.0),
        ("REV", 27.75, 38.6, 1.0),
        ("GND", 48.9, 18.0, 0.8),
        ("+V", 48.9, 20.54, 0.8),
        ("SIG", 48.9, 23.08, 0.8),
        # Test pad labels.
        ("VCC", 12.0, 7.3, 0.8),
        ("GND", 17.0, 7.3, 0.8),
        ("OUT", 22.0, 7.3, 0.8),
        ("SIG", 27.0, 7.3, 0.8),
        # Component values (the passives' silk carries no value text).
        ("1k", 44.2, 5.0, 0.8),
        ("33k", 44.6, 9.1, 0.8),
        ("100n", 33.7, 15.95, 0.8),
        ("100n", 33.7, 21.25, 0.8),
        ("10n", 39.1, 23.3, 0.8),
        ("68k", 7.3, 27.5, 0.8),
        ("10k", 35.6, 31.5, 0.8),
        ("4.7k", 48.0, 10.9, 0.8),
        ("470u", 43.25, 36.2, 0.8),
        ("BC547", 45.9, 16.1, 0.8),
    )
    return tuple(
        silk_text(text, (x, y), origin, size=size)
        for text, x, y, size in texts
    )


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
    for component, x, y in mounting_hole_placements(BOARD_W, BOARD_H):
        placements.append((component, x))
        part_y.append((component.reference, y))
    return BoardLayout(
        placements=tuple(placements),
        segments=(),
        vias=(),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(part_rotation),
        zones=ZONES,
        graphics=servo555_silk_graphics(BOARD_SHEET_ORIGIN_MM),
        part_reference_at=tuple(REFERENCE_AT.items()),
    )


def compute_servo555_board_layout(netlist: BoardNetlist) -> BoardLayout:
    result = route_board(
        _unrouted_layout(netlist),
        netlist,
        net_widths={net: POWER_W for net in POWER_NETS},
        default_width_mm=SIG_W,
    )
    if result.failed:
        raise BoardGenerationError(
            "route_board could not route: " + ", ".join(result.failed)
        )
    return result.layout


def generate_servo555_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(
        schematic_file, finder=finder, runner=runner
    )
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_servo555_board_layout(netlist)
    board_file.write_text(
        render_board_from_layout(netlist, layout), encoding="utf-8"
    )
    return netlist, layout
