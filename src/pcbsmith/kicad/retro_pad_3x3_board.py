"""Unrouted placement board for the rectangular 3x3 Retro-Pad."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardCutoutPolygon,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    export_kicad_netlist_xml,
    parse_board_netlist,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.retro_pad_board import (
    render_retro_pad_board,
    route_retro_pad_placement_layout,
)
from pcbsmith.kicad.shaped_board import silk_text

BOARD_W = 120.0
BOARD_H = 100.0

KEY_CENTERS = tuple(
    (index + 1, x, y)
    for index, (x, y) in enumerate(
        (  # 19.05 mm Cherry key pitch, centered on the board.
            (40.00, 30.00), (59.05, 30.00), (78.10, 30.00),
            (40.00, 49.05), (59.05, 49.05), (78.10, 49.05),
            (40.00, 68.10), (59.05, 68.10), (78.10, 68.10),
        )
    )
)

PLACEMENTS: dict[str, tuple[float, float, float]] = {
    # Cherry anchor = visual center + (2.54, -5.08) for rotation zero.
    **{
        f"SW{index}": (x + 2.54, y - 5.08, 0.0)
        for index, x, y in KEY_CENTERS
    },
    # EC11 anchor = shaft center + (-7.5, -2.5).
    "SW10": (96.5, 15.5, 0.0),
    # Connector mouth is flush with the straight top board edge.
    "J1": (60.0, 4.2, 180.0),
    # Back-side USB front end.
    # Preserve the proven R002 USB-front-end relative geometry, translated to
    # this board's top-edge connector.  The earlier visually tidy spread put
    # CC1 far left and made the escape domain unroutable.
    "U2": (61.0, 12.4, 0.0),
    "F1": (51.5, 12.0, 90.0),
    "R1": (71.0, 7.9, 0.0),
    "R2": (55.0, 11.9, 0.0),
    "R3": (66.0, 11.9, 0.0),
    "R4": (66.0, 13.9, 0.0),
    # Keep the USB MCU, clock, and local support in the upper control band.
    # The earlier lower-center placement forced USB and raw VBUS through the
    # full 100 mm board height and failed the bounded routing preflight.  This
    # cluster shortens those critical paths and leaves both lower corners open.
    "U1": (78.0, 15.5, 0.0),
    "Y1": (68.0, 14.5, 0.0),
    # Keep the programming header in the same upper control band as U1.  The
    # previous far-left position made all four ISP nets cross the USB and
    # matrix corridors and could only route by blocking ROW2.
    "J2": (100.0, 3.0, 0.0),
    "C19": (45.0, 15.5, 0.0),
    "C1": (65.0, 11.0, 0.0),
    "C2": (65.0, 18.0, 0.0),
    "C3": (87.0, 10.5, 0.0),
    "C4": (90.5, 10.5, 0.0),
    "C5": (87.0, 13.5, 0.0),
    "C6": (90.5, 13.5, 0.0),
    "C7": (87.0, 16.5, 0.0),
    "C8": (90.5, 16.5, 0.0),
    "C9": (87.0, 19.5, 0.0),
    "R5": (68.0, 20.5, 0.0),
    "R6": (60.0, 22.5, 0.0),
    "R7": (91.0, 23.0, 0.0),
    # Encoder pull-ups and debounce sit immediately below its body.
    "R8": (96.0, 31.0, 0.0),
    "R9": (101.0, 31.0, 0.0),
    "R10": (106.0, 31.0, 0.0),
    "C20": (96.0, 34.0, 0.0),
    "C21": (101.0, 34.0, 0.0),
    "C22": (106.0, 34.0, 0.0),
}

for index, x, y in KEY_CENTERS:
    PLACEMENTS[f"D{index}"] = (x + 6.8, y - 5.6, 0.0)
    PLACEMENTS[f"D{index + 9}"] = (x, y + 5.5, 0.0)
    PLACEMENTS[f"C{index + 9}"] = (x + 6.2, y + 5.5, 90.0)

FLIPPED_REFS: tuple[str, ...] = (
    # Keep the USB ESD array and its four immediate resistors on the connector
    # side.  The prior placement put them on B.Cu and made the 0.5 mm-pitch
    # connector breakout unroutable before any matrix net was attempted.
    "U1", "J2", "F1", "Y1",
    *(f"D{index}" for index in range(1, 19)),
    *(f"R{index}" for index in range(5, 11)),
    *(f"C{index}" for index in range(1, 23)),
)

HIDE_REFERENCES: tuple[str, ...] = (
    "J1",
    *(f"SW{index}" for index in range(1, 11)),
)

MOUNTING_HOLES = (
    ("H1", 5.0, 5.0),
    ("H2", 115.0, 5.0),
    ("H3", 5.0, 95.0),
    ("H4", 115.0, 95.0),
)


def compute_retro_pad_3x3_layout(netlist: BoardNetlist) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    rotations: list[tuple[str, float]] = []
    for reference, (x, y, rotation) in PLACEMENTS.items():
        if reference not in by_ref:
            raise BoardGenerationError(f"3x3 Retro-Pad netlist is missing {reference}.")
        placements.append((by_ref[reference], x))
        part_y.append((reference, y))
        if rotation:
            rotations.append((reference, rotation))
    for reference, x, y in MOUNTING_HOLES:
        hole = BoardComponent(
            reference=reference,
            value="M2.5 NPTH",
            footprint="MountingHole:MountingHole_2.7mm_M2.5",
            uuid_path=stable_kicad_uuid(
                "board-component-path", "retro-pad-3x3-hole", reference
            ),
        )
        placements.append((hole, x))
        part_y.append((reference, y))

    key_labels = tuple(
        silk_text(
            f"SW{index}",
            (x - 6.0, y + 8.1),
            BOARD_SHEET_ORIGIN_MM,
            size=0.8,
        )
        for index, x, y in KEY_CENTERS
    )
    graphics = (
        *key_labels,
        silk_text("J1", (66.5, 8.0), BOARD_SHEET_ORIGIN_MM, size=0.8),
        silk_text("USB-C", (52.0, 8.0), BOARD_SHEET_ORIGIN_MM, size=0.8),
        silk_text("SW10  ENC", (96.0, 27.5), BOARD_SHEET_ORIGIN_MM, size=0.8),
        silk_text("RETRO MATRIX 3x3", (48.0, 97.0), BOARD_SHEET_ORIGIN_MM, size=0.9),
        silk_text(
            "C19", (40.0, 18.0), BOARD_SHEET_ORIGIN_MM,
            size=0.8, layer="B.SilkS",
        ),
    )
    led_cutouts = tuple(
        BoardCutoutPolygon(
            points=(
                (x - 1.0, y + 4.5),
                (x + 1.0, y + 4.5),
                (x + 1.0, y + 6.5),
                (x - 1.0, y + 6.5),
            )
        )
        for _index, x, y in KEY_CENTERS
    )
    return BoardLayout(
        placements=tuple(placements),
        segments=(),
        vias=(),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(rotations),
        zones=(
            ("/GND", "F.Cu", (0.75, 0.75, BOARD_W - 0.75, BOARD_H - 0.75)),
            ("/GND", "B.Cu", (0.75, 0.75, BOARD_W - 0.75, BOARD_H - 0.75)),
        ),
        outline=None,
        cutouts=led_cutouts,
        graphics=graphics,
        part_flip=FLIPPED_REFS,
        hide_references=HIDE_REFERENCES,
        part_reference_at=(
            ("J2", (8.0, 4.0, 0.0)),
            ("R3", (0.0, -2.0, 0.0)),
            ("R4", (0.0, 2.0, 0.0)),
        ),
    )


def generate_retro_pad_3x3_placement_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_retro_pad_3x3_layout(netlist)
    board_file.write_text(
        render_retro_pad_board(netlist, layout, switch_count=9, led_count=9),
        encoding="utf-8",
    )
    return netlist, layout


def generate_retro_pad_3x3_routed_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    placement = compute_retro_pad_3x3_layout(netlist)
    routed = route_retro_pad_placement_layout(
        placement,
        netlist,
        maximum_expansions=5_000_000,
        maximum_passes=500,
        maximum_expansions_per_net=2_500_000,
        route_ground_tracks=True,
        route_ground_before_power=True,
        route_clock_before_power=True,
        route_led_before_power=True,
    )
    board_file.write_text(
        render_retro_pad_board(netlist, routed, switch_count=9, led_count=9),
        encoding="utf-8",
    )
    return netlist, routed
