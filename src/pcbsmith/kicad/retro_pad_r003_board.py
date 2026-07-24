"""Unrouted engineering placement for the symmetric Retro-Pad R003 bone."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardCutoutPolygon,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
    export_kicad_netlist_xml,
    parse_board_netlist,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.raster_artwork import trace_board_outline
from pcbsmith.kicad.retro_pad_board import (
    _pixel_heart_graphics,
    render_retro_pad_board,
    route_retro_pad_placement_layout,
)
from pcbsmith.kicad.shaped_board import silk_text

BOARD_W = 145.0
BOARD_H = 55.0

# Cherry footprint anchors are offset from the visual key centers.  These
# rotations put one exact switch footprint in each of the four enlarged end
# lobes while keeping every pad, locator hole, and nominal 18 mm keycap within
# the board silhouette.
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "SW1": (17.46, 20.08, 180.0),
    "SW2": (22.54, 34.92, 0.0),
    "SW3": (122.46, 20.08, 180.0),
    "SW4": (127.54, 34.92, 0.0),
    # EC11 anchor is 7.5 mm left and 2.5 mm above the shaft center.
    "SW5": (65.0, 30.8, 0.0),
    # The mating face is centered on the recessed top waist boundary.
    "J1": (72.5, 20.1, 180.0),
    # Keep the Type-C protection, fuse, and first series elements on the same
    # side of the reversible connector.  This gives the interleaved A/B data
    # contacts a legal two-layer fanout around the VBUS trunk.
    "U2": (62.0, 22.0, 0.0),
    "R3": (56.0, 21.5, 0.0),
    "R4": (56.0, 23.5, 0.0),
    "F1": (50.0, 20.5, 90.0),
    "R1": (82.0, 17.5, 0.0),
    "R2": (64.0, 19.0, 0.0),
    "U1": (88.0, 30.0, 0.0),
    "Y1": (77.0, 26.5, 0.0),
    "C1": (72.0, 24.0, 0.0),
    "C2": (77.0, 30.0, 0.0),
    "C3": (98.0, 24.0, 0.0),
    "C4": (98.0, 27.0, 0.0),
    "C5": (98.0, 30.0, 0.0),
    "C6": (98.0, 33.0, 0.0),
    "C7": (97.5, 39.0, 0.0),
    "C8": (98.0, 36.0, 0.0),
    "C9": (102.0, 38.0, 0.0),
    "R5": (84.0, 39.0, 0.0),
    "R6": (56.0, 24.0, 0.0),
    "R7": (60.0, 27.0, 0.0),
    # Keep the back-side ISP header beside the MCU.  Placing it west of the
    # encoder forced three programming nets through every central-board
    # corridor and made the otherwise feasible two-layer route unnecessarily
    # fragile.
    "J2": (102.0, 20.0, 90.0),
    "C14": (108.0, 30.0, 0.0),
    # Matrix diodes live between each lobe and the central routing waist.
    "D1": (35.0, 16.0, 0.0),
    "D2": (35.0, 38.5, 0.0),
    "D3": (110.0, 16.0, 180.0),
    "D4": (110.0, 38.5, 180.0),
    # Reverse-mount LEDs align with the lamp window of each rotated switch.
    "D5": (20.0, 9.5, 0.0),
    "D6": (20.0, 45.5, 0.0),
    "D7": (125.0, 9.5, 0.0),
    "D8": (125.0, 45.5, 0.0),
    "C10": (28.0, 9.5, 0.0),
    "C11": (28.0, 45.5, 0.0),
    "C12": (117.0, 9.5, 0.0),
    "C13": (117.0, 45.5, 0.0),
    # Encoder pull-ups/debounce remain close to its pins but clear the ISP.
    "R8": (56.0, 34.0, 0.0),
    "R9": (60.0, 34.0, 0.0),
    "R10": (56.0, 38.0, 90.0),
    "C15": (60.0, 38.0, 0.0),
    "C16": (64.0, 39.0, 0.0),
    "C17": (68.0, 39.0, 0.0),
}

FLIPPED_REFS: tuple[str, ...] = (
    "U1", "J2", "Y1",
    *(f"D{index}" for index in range(1, 9)),
    *(f"R{index}" for index in range(5, 11)),
    *(f"C{index}" for index in range(1, 18)),
)

# R003 is an engineering-review board, so every component reference remains
# visible on its assembly side.  The earlier placement candidate inherited
# R002's presentation-oriented suppression and omitted most designators.
# J1 retains an explicit, deliberately positioned front label beside the
# connector, so suppress only its native footprint label to avoid duplication.
HIDE_REFERENCES: tuple[str, ...] = ("J1", "Y1")

MOUNTING_HOLES = (
    ("H1", 7.5, 7.5),
    ("H2", 137.5, 7.5),
    ("H3", 7.5, 47.5),
    ("H4", 137.5, 47.5),
)

LED_CENTERS = ((20.0, 9.5), (20.0, 45.5), (125.0, 9.5), (125.0, 45.5))


def compute_retro_pad_r003_placement_layout(
    netlist: BoardNetlist,
    *,
    outline_file: Path,
    silkscreen_file: Path,
) -> BoardLayout:
    outline_trace = trace_board_outline(outline_file, target_width_mm=BOARD_W)
    by_ref = {component.reference: component for component in netlist.components}
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    rotations: list[tuple[str, float]] = []
    for reference, (x, y, rotation) in PLACEMENTS.items():
        if reference not in by_ref:
            raise BoardGenerationError(f"Retro-Pad R003 netlist is missing {reference}.")
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
                "board-component-path", "retro-pad-r003-hole", reference
            ),
        )
        placements.append((hole, x))
        part_y.append((reference, y))

    graphics = (
        *_pixel_heart_graphics(
            silkscreen_file,
            center=(111.0, 30.5),
            width_mm=12.0,
        ),
        silk_text("USB-C", (64.0, 16.0), BOARD_SHEET_ORIGIN_MM, size=0.8),
        silk_text("J1", (81.0, 16.0), BOARD_SHEET_ORIGIN_MM, size=0.8),
        # The Cherry library outline is intentionally moved to Dwgs.User by
        # the shared renderer, so retain explicit front-side designators in
        # the open gap between each vertical switch pair.
        silk_text("SW1", (14.5, 25.0), BOARD_SHEET_ORIGIN_MM, size=0.8),
        silk_text("SW2", (14.5, 30.0), BOARD_SHEET_ORIGIN_MM, size=0.8),
        silk_text("SW3", (130.5, 25.0), BOARD_SHEET_ORIGIN_MM, size=0.8),
        silk_text("SW4", (130.5, 30.0), BOARD_SHEET_ORIGIN_MM, size=0.8),
        # The shared renderer moves the bulk capacitor's package outline to
        # B.Fab, so retain its reference explicitly on the assembly side.
        silk_text(
            "C14", (112.5, 35.0), BOARD_SHEET_ORIGIN_MM,
            size=0.8, layer="B.SilkS",
        ),
    )
    cutouts = tuple(
        BoardCutoutPolygon(
            points=(
                (x - 1.0, y - 1.0),
                (x + 1.0, y - 1.0),
                (x + 1.0, y + 1.0),
                (x - 1.0, y + 1.0),
            )
        )
        for x, y in LED_CENTERS
    )
    return BoardLayout(
        placements=tuple(placements),
        segments=(),
        vias=(),
        width_mm=BOARD_W,
        height_mm=outline_trace.target_size_mm[1],
        part_y_mm=tuple(part_y),
        part_rotation=tuple(rotations),
        zones=(
            ("/GND", "F.Cu", (0.75, 0.75, BOARD_W - 0.75, BOARD_H - 0.75)),
            ("/GND", "B.Cu", (0.75, 0.75, BOARD_W - 0.75, BOARD_H - 0.75)),
        ),
        outline=outline_trace.outline,
        cutouts=cutouts,
        graphics=graphics,
        part_flip=FLIPPED_REFS,
        hide_references=HIDE_REFERENCES,
        part_reference_at=(
            ("R1", (4.0, 0.0, 0.0)),
            ("R3", (0.0, -2.0, 0.0)),
            ("R4", (0.0, 2.0, 0.0)),
            ("U2", (0.0, 4.0, 0.0)),
            ("C2", (0.0, 2.0, 0.0)),
            ("Y1", (0.0, 4.0, 0.0)),
            ("D1", (0.0, 3.0, 0.0)),
            ("D4", (0.0, 3.0, 0.0)),
        ),
    )


def generate_retro_pad_r003_placement_board(
    *,
    schematic_file: Path,
    board_file: Path,
    outline_file: Path,
    silkscreen_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_retro_pad_r003_placement_layout(
        netlist,
        outline_file=outline_file,
        silkscreen_file=silkscreen_file,
    )
    board_file.write_text(render_retro_pad_board(netlist, layout), encoding="utf-8")
    return netlist, layout


def generate_retro_pad_r003_routed_board(
    *,
    schematic_file: Path,
    board_file: Path,
    outline_file: Path,
    silkscreen_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    placement = compute_retro_pad_r003_placement_layout(
        netlist,
        outline_file=outline_file,
        silkscreen_file=silkscreen_file,
    )
    placement = _seed_usb_c_fanout(placement)
    placement = _seed_isp_fanout(placement)
    routed = route_retro_pad_placement_layout(
        placement,
        netlist,
        maximum_expansions=5_000_000,
        maximum_passes=500,
        maximum_expansions_per_net=5_000_000,
        route_ground_before_power=True,
        route_ground_before_matrix=True,
        route_clock_before_power=True,
        route_led_before_power=False,
        route_power_before_matrix=False,
        completed_net_names={
            "/VBUS_RAW",
            "/USB_DP_CONN",
            "/USB_DM_CONN",
        },
    )
    routed = _prune_unused_isp_fanout(routed)
    board_file.write_text(render_retro_pad_board(netlist, routed), encoding="utf-8")
    return netlist, routed


def _seed_usb_c_fanout(layout: BoardLayout) -> BoardLayout:
    """Seed the three topology-critical Type-C fanout trees.

    The reversible connector orders the duplicated contacts as interleaved
    D+/D- pairs between two VBUS contacts.  A purely sequential router can
    legally route either data pair or the VBUS trunk, but whichever is routed
    first can cut off the other two.  This deterministic escape uses the
    front layer for the upper D+ loop and VBUS trunk, and crosses only D- to
    the back layer before returning beside U2.
    """

    def segment(
        start: tuple[float, float],
        end: tuple[float, float],
        net_name: str,
        *,
        width_mm: float = 0.15,
        layer: str = "F.Cu",
    ) -> TrackSegment:
        return TrackSegment(
            x1=start[0],
            y1=start[1],
            x2=end[0],
            y2=end[1],
            layer=layer,
            net_name=net_name,
            width_mm=width_mm,
        )

    data_plus = (
        segment((71.70, 23.25), (72.05, 22.90), "/USB_DP_CONN"),
        segment((72.05, 22.90), (72.45, 22.90), "/USB_DP_CONN"),
        segment((72.45, 22.90), (72.80, 23.25), "/USB_DP_CONN"),
        segment((72.75, 24.21), (72.80, 23.25), "/USB_DP_CONN"),
        segment((71.70, 23.25), (71.75, 24.21), "/USB_DP_CONN"),
        segment((71.70, 23.25), (71.70, 22.70), "/USB_DP_CONN"),
        segment((71.70, 22.70), (68.95, 20.40), "/USB_DP_CONN"),
        segment((68.95, 20.40), (61.95, 20.40), "/USB_DP_CONN"),
        segment((61.95, 20.40), (61.40, 20.95), "/USB_DP_CONN"),
        segment((61.40, 20.95), (60.19, 21.05), "/USB_DP_CONN"),
    )
    data_minus = (
        segment((72.95, 24.65), (73.25, 24.35), "/USB_DM_CONN"),
        segment((72.55, 24.65), (72.95, 24.65), "/USB_DM_CONN"),
        segment((72.25, 24.35), (72.55, 24.65), "/USB_DM_CONN"),
        segment((72.25, 24.21), (72.25, 24.35), "/USB_DM_CONN"),
        segment((73.25, 24.21), (73.25, 24.35), "/USB_DM_CONN"),
        segment((73.25, 24.35), (73.55, 24.65), "/USB_DM_CONN"),
        segment((73.55, 24.65), (73.20, 25.10), "/USB_DM_CONN"),
        segment(
            (73.20, 25.10),
            (65.00, 25.10),
            "/USB_DM_CONN",
            layer="B.Cu",
        ),
        segment((65.00, 25.10), (64.10, 23.60), "/USB_DM_CONN"),
        segment((64.10, 23.60), (61.95, 23.60), "/USB_DM_CONN"),
        segment((61.95, 23.60), (61.40, 23.05), "/USB_DM_CONN"),
        segment((61.40, 23.05), (60.19, 22.95), "/USB_DM_CONN"),
    )
    vbus = (
        segment(
            (49.75, 21.90), (50.80, 22.00), "/VBUS_RAW", width_mm=0.25
        ),
        segment(
            (50.80, 22.00), (53.60, 26.00), "/VBUS_RAW", width_mm=0.25
        ),
        segment(
            (53.60, 26.00), (86.80, 26.00), "/VBUS_RAW", width_mm=0.25
        ),
        segment((70.00, 24.00), (70.00, 26.00), "/VBUS_RAW", width_mm=0.25),
        segment((74.80, 24.00), (74.80, 26.00), "/VBUS_RAW", width_mm=0.25),
        segment(
            (86.80, 26.00), (92.80, 30.80), "/VBUS_RAW", width_mm=0.25
        ),
        segment(
            (92.80, 30.80),
            (94.125, 30.80),
            "/VBUS_RAW",
            width_mm=0.25,
            layer="B.Cu",
        ),
    )
    vias = (
        ViaSpec(x=73.20, y=25.10, net_name="/USB_DM_CONN"),
        ViaSpec(x=65.00, y=25.10, net_name="/USB_DM_CONN"),
        ViaSpec(x=92.80, y=30.80, net_name="/VBUS_RAW"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *data_plus, *data_minus, *vbus),
        vias=(*layout.vias, *vias),
    )


def _seed_isp_fanout(layout: BoardLayout) -> BoardLayout:
    """Escape the three adjacent ISP pads from the MCU before global routing.

    The pads sit on the back-side east edge of U1 at 0.8 mm pitch.  Without
    reserving three short, parallel escapes, a sequential global route can use
    one pad's only corridor while connecting another net.  Each seed terminates
    in a via so the global router can continue independently on either layer.
    """

    fanout = tuple(
        TrackSegment(
            x1=94.125,
            y1=y_mm,
            x2=95.5,
            y2=y_mm,
            layer="B.Cu",
            net_name=net_name,
            width_mm=0.15,
        )
        for net_name, y_mm in (
            ("/SCK", 32.4),
            ("/MOSI", 33.2),
            ("/MISO", 34.0),
        )
    )
    vias = tuple(
        ViaSpec(x=95.5, y=y_mm, net_name=net_name)
        for net_name, y_mm in (
            ("/SCK", 32.4),
            ("/MOSI", 33.2),
            ("/MISO", 34.0),
        )
    )
    return replace(
        layout,
        segments=(*layout.segments, *fanout),
        vias=(*layout.vias, *vias),
    )


def _prune_unused_isp_fanout(layout: BoardLayout) -> BoardLayout:
    """Remove the temporary ISP escape reservations after routing.

    The router uses the seeded stubs and vias as corridor reservations, then
    creates its own connected pad escapes.  Retaining the temporary branches
    would leave dangling vias and, in MOSI's case, two drills almost
    coincident.  Only the three exact seed objects are removed.
    """

    seed_points = {
        ("/SCK", 32.4),
        ("/MOSI", 33.2),
        ("/MISO", 34.0),
    }
    segments = tuple(
        segment
        for segment in layout.segments
        if not (
            segment.layer == "B.Cu"
            and (segment.net_name, segment.y1) in seed_points
            and abs(segment.x1 - 94.125) < 1e-9
            and abs(segment.x2 - 95.5) < 1e-9
            and abs(segment.y2 - segment.y1) < 1e-9
        )
    )
    vias = tuple(
        via
        for via in layout.vias
        if not (
            (via.net_name, via.y) in seed_points
            and abs(via.x - 95.5) < 1e-9
        )
    )
    return replace(layout, segments=segments, vias=vias)


def _repair_usb_dp_clearance(layout: BoardLayout) -> BoardLayout:
    """Repair the retained pre-gate D+ diagonal beside J1.A8, if present."""

    repaired: list[TrackSegment] = []
    replaced = False
    for item in layout.segments:
        if (
            item.net_name == "/USB_DP_CONN"
            and item.layer == "F.Cu"
            and abs(item.x1 - 71.70) < 1e-9
            and abs(item.y1 - 23.25) < 1e-9
            and abs(item.x2 - 68.95) < 1e-9
            and abs(item.y2 - 20.40) < 1e-9
        ):
            repaired.extend(
                (
                    replace(item, x2=71.70, y2=22.70),
                    replace(item, x1=71.70, y1=22.70),
                )
            )
            replaced = True
        else:
            repaired.append(item)
    if not replaced:
        return layout
    return replace(layout, segments=tuple(repaired))
