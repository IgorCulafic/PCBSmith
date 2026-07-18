"""Thermometer-shaped display board: bulb, stem, mercury, graduations.

Outline: a classic laboratory thermometer - a 42 mm bulb at the bottom,
a 24 mm rounded stem rising to a hanging hole in the tip, and a flat
tab spliced into the bulb's underside for the USB-C mouth. The FRONT
face carries only what the eye should see: the 16-LED mercury column
on the stem centerline, the two OLED headers, the SHT31 in the bulb
with free air, the power LED, test points, and the printed scale.
Everything else (module, shift registers, series resistors, power
chain, pull-ups) lives on the BACK.

The printed graduations and the LED positions both come from
``thermometer_scale_fraction`` - the same function the firmware
thresholds cite - so the mercury column and the scale cannot disagree.
Every trace comes from ``route_board`` (rule 11 craft pipeline).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import uuid4

from pcbsmith.calculators.electronics import thermometer_scale_fraction
from pcbsmith.kicad.astar_router import route_board
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
from pcbsmith.kicad.shaped_board import (
    clipped_circle_outline,
    silk_line,
    silk_text,
    splice_rect_tab,
)

BOARD_W = 46.0
BOARD_H = 158.0

STEM_CX = 23.0
STEM_HALF = 12.0
TIP_CY = 20.0            # stem tip arc center (radius = STEM_HALF)
BULB_CX, BULB_CY, BULB_R = 23.0, 136.0, 21.0
USB_TAB_HALF = 5.8

# The printed scale: 0C at the bottom of the stem scale, 50C at the
# top, exactly the calculator's range.
SCALE_MIN_C, SCALE_MAX_C = 0.0, 50.0
SCALE_Y0 = 98.0          # y of the 0C graduation
SCALE_Y50 = 20.0         # y of the 50C graduation
LED_COUNT = 16

POWER_NETS = ("/VBUS", "/VBUSF", "/VCC", "/GND")
# 0.4mm carries the 0.45A worst-case rail with >2x IPC-2221 margin;
# anything wider cannot ENTER the USB receptacle's 1.15mm-pitch pad
# row (all four VBUS pads walled at 0.6mm - measured, not guessed).
POWER_W = 0.4
SIG_W = 0.25


def scale_y(temperature_c: float) -> float:
    """Board y of a temperature on the printed scale (shared truth)."""
    fraction = thermometer_scale_fraction(
        temperature_c, scale_min_c=SCALE_MIN_C, scale_max_c=SCALE_MAX_C
    )
    return round(SCALE_Y0 - fraction * (SCALE_Y0 - SCALE_Y50), 3)


def led_y(index: int) -> float:
    """Board y of mercury LED ``index`` (1-based): the LED sits AT its
    firmware threshold temperature on the printed scale."""
    threshold = SCALE_MIN_C + index * (SCALE_MAX_C - SCALE_MIN_C) / LED_COUNT
    return scale_y(threshold)


# The registers' pin rows own a horizontal band (pin centers +/-2.275,
# pad reach and a via diameter on top); a series resistor whose LK lane
# sits inside it cannot cross to its LED (live: /LK4's lane ran through
# U2 pin 8). Only the FRONT LEDs must sit at the scale positions - the
# back-side resistors slide to the band edge.
_REGISTER_YS = (76.1, 48.1)
_PIN_BAND_HALF = 3.6


def _series_r_y(index: int) -> float:
    y = led_y(index)
    for register_y in _REGISTER_YS:
        if abs(y - register_y) < _PIN_BAND_HALF:
            y = register_y + math.copysign(_PIN_BAND_HALF, y - register_y)
    return round(y, 3)


def thermometer_outline() -> tuple[tuple[float, float], ...]:
    """Stem tip arc, straight walls, bulb circle, USB tab splice."""
    points: list[tuple[float, float]] = []
    # Tip arc: left wall top around the tip to the right wall top.
    for step in range(0, 37):
        angle = math.radians(180.0 + step * 5.0)
        points.append((
            round(STEM_CX + STEM_HALF * math.cos(angle), 3),
            round(TIP_CY + STEM_HALF * math.sin(angle), 3),
        ))
    junction_dy = math.sqrt(BULB_R**2 - STEM_HALF**2)
    junction_y = round(BULB_CY - junction_dy, 3)
    points.append((STEM_CX + STEM_HALF, junction_y))
    # Bulb: from the right junction clockwise (through the bottom, +y)
    # to the left junction. In y-down coordinates the right junction
    # sits at angle atan2(-dy, +half) and the left at 180 - that angle.
    start_deg = math.degrees(math.atan2(-junction_dy, STEM_HALF))
    end_deg = 180.0 - start_deg
    sweep = end_deg - start_deg
    steps = max(8, int(sweep / 5.0))
    for step in range(1, steps):
        angle = math.radians(start_deg + sweep * step / steps)
        points.append((
            round(BULB_CX + BULB_R * math.cos(angle), 3),
            round(BULB_CY + BULB_R * math.sin(angle), 3),
        ))
    points.append((STEM_CX - STEM_HALF, junction_y))
    points.append((STEM_CX - STEM_HALF, TIP_CY))
    return splice_rect_tab(
        tuple(points),
        center_x=STEM_CX,
        half_width=USB_TAB_HALF,
        end_y=BOARD_H,
        join_y=BULB_CY + math.sqrt(BULB_R**2 - USB_TAB_HALF**2),
        outward_up=False,
    )


# (x, y, rotation) pad-1 anchors. FRONT: the display face. BACK (in
# FLIPPED_REFS): control and power. Anchors verified against the probed
# courtyards and the bulb/stem chords.
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    # -- front: mercury column (positions from the shared scale) -----
    **{
        f"D{index}": (STEM_CX, led_y(index), 0.0)
        for index in range(1, LED_COUNT + 1)
    },
    # -- front: displays, sensor, indicator, test points -------------
    # x=20.39 clears the rule-8.2 "+" mark (at pad1 - 3.9mm) from
    # the TEMP/HUM labels on the left; live silk_overlap at 19.19.
    "J2": (20.39, 104.0, 90.0),
    "J3": (20.39, 111.0, 90.0),
    # y at 130.05: the 0.05 offset lands the DFN's 0.5mm-pitch pads
    # EXACTLY on the 0.1mm fine-routing grid (pads sit at anchor
    # +/-0.25/+/-0.75; the offset absorbs the quarter-step).
    "U4": (23.0, 130.05, 0.0),
    "C7": (28.5, 130.0, 90.0),
    "D17": (31.0, 147.0, 0.0),
    "R17": (35.0, 147.0, 0.0),
    # y=124 keeps the PTH loops out of U1's back courtyard (top
    # edge y=127.25; live pth_inside_courtyard at y=127).
    "TP1": (10.0, 124.0, 0.0),
    "TP2": (36.0, 124.0, 0.0),
    # -- back: USB, module, power chain. The module's 28.5x25.5
    # courtyard owns the bulb's back from y=121.7 to 147.2; the power
    # cluster fits the two pockets between it and the USB body.
    # x=23.05 lands the receptacle's 0.5mm-pitch data pads ON the
    # 0.2mm routing grid (at 23.0 the D+/D- centerlines fall between
    # cells and every in-pad cell violates clearance to the
    # interleaved neighbour - measured).
    "J1": (23.05, 154.2, 0.0),
    "U1": (23.0, 140.0, 0.0),
    "U5": (11.5, 150.0, 90.0),
    "C5": (15.2, 149.3, 90.0),
    "C6": (15.2, 153.0, 90.0),
    "F1": (29.8, 150.3, 90.0),
    # CC pull-downs ride the narrow band left of the module courtyard.
    "RCC1": (6.8, 138.0, 0.0),
    "RCC2": (6.8, 141.5, 0.0),
    # -- back: registers and series resistors along the stem ---------
    # y at x.1: the TSSOP's 0.65 pitch lands pad-entry margins exactly
    # ON the 0.2 grid boundary at integral y (float-noise walls).
    # Each register sits IN its load zone: U2 drives SEG1-8 (LEDs at
    # y 78-93), U3 drives SEG9-16 (y 24-54). The inverted arrangement
    # made all sixteen SEG nets cross the other register's zone and
    # /SEG9 became unroutable (live).
    "U2": (23.0, 76.1, 0.0),
    "U3": (23.0, 48.1, 0.0),
    # Resistor columns follow the SOURCE pin side, not LED parity: a
    # TSSOP '595 exposes seven outputs on one column and QA alone on
    # the other, so an odd/even split forced seven of each register's
    # eight SEG nets across the stem center (live: /SEG9, /SEG6, /SEG5
    # unroutable in three successive layouts). R1/R9 (QA) sit left;
    # the rest alternate between two right-side columns - one column
    # cannot hold consecutive LEDs' resistors (2.44mm pitch vs the
    # 2.96mm courtyard span, probed).
    **{
        f"R{index}": (
            15.5 if index in (1, 9)
            else (28.5 if index % 2 == 0 else 32.5),
            _series_r_y(index),
            90.0,
        )
        for index in range(1, LED_COUNT + 1)
    },
    # -- back: module support and pull-up field. The series-resistor
    # columns at x=16.5/29.5 own their lanes; the pull-ups live in the
    # center corridor between them.
    "C1": (14.5, 119.0, 0.0),
    "C2": (31.5, 119.0, 0.0),
    "REN1": (13.0, 116.5, 0.0),
    "CEN1": (18.5, 116.5, 0.0),
    "RS1": (24.0, 116.5, 0.0),
    "RS2": (29.5, 116.5, 0.0),
    "ROE1": (13.0, 99.0, 0.0),
    "C3": (23.0, 70.0, 0.0),
    "C4": (23.0, 42.0, 0.0),
    "RI1": (21.0, 92.0, 0.0),
    "RI2": (25.0, 92.0, 0.0),
    "RI3": (21.0, 95.0, 0.0),
    "RI4": (25.0, 95.0, 0.0),
}

FLIPPED_REFS: tuple[str, ...] = (
    # R17 rides the FRONT beside the power LED it feeds.
    "J1", "U1", "U2", "U3", "U5", "C1", "C2", "C3", "C4", "C5", "C6",
    "F1", "RCC1", "RCC2", "REN1", "CEN1", "RS1", "RS2", "ROE1",
    "RI1", "RI2", "RI3", "RI4",
    *(f"R{index}" for index in range(1, LED_COUNT + 1)),
)

# Footprint-local (x, y, total angle); back-side labels transform
# INVERSE rotation then x-mirror.
REFERENCE_AT: dict[str, tuple[float, float, float]] = {
    "F1": (0.0, 3.6, 0.0),    # right of the fuse, off U1's outline
    "C1": (0.0, 1.9, 0.0),    # below the cap, off REN1's pads
    "RCC2": (0.0, 1.9, 0.0),  # below its body, off RCC1's label
    "C5": (0.0, 1.9, 0.0),    # right of the cap, off U5's outline
}


def _graduations(origin: float) -> list[str]:
    graphics: list[str] = []
    for temperature in range(0, 51, 2):
        y = scale_y(float(temperature))
        major = temperature % 10 == 0
        x_start = 15.5 if major else 17.5
        graphics.append(
            silk_line((x_start, y), (19.5, y), origin,
                      width=0.3 if major else 0.18)
        )
        if major:
            graphics.append(
                silk_text(str(temperature), (13.2, y), origin, size=0.9)
            )
    # Glass highlight: a thin decorative line right of the mercury.
    graphics.append(silk_line((27.2, 22.0), (27.2, 96.0), origin, width=0.15))
    return graphics


def _icons(origin: float) -> list[str]:
    graphics: list[str] = []
    # Sun beside the hot end.
    sun = (30.5, 25.0)
    graphics.extend(clipped_circle_outline(sun, 1.1, (), origin, width=0.2))
    for step in range(8):
        angle = math.radians(step * 45.0)
        graphics.append(silk_line(
            (sun[0] + 1.5 * math.cos(angle), sun[1] + 1.5 * math.sin(angle)),
            (sun[0] + 2.3 * math.cos(angle), sun[1] + 2.3 * math.sin(angle)),
            origin, width=0.2,
        ))
    # Snowflake beside the cold end.
    flake = (30.5, 92.0)
    for step in range(3):
        angle = math.radians(step * 60.0)
        dx, dy = 1.9 * math.cos(angle), 1.9 * math.sin(angle)
        graphics.append(silk_line(
            (flake[0] - dx, flake[1] - dy), (flake[0] + dx, flake[1] + dy),
            origin, width=0.2,
        ))
    # Thermometer glyph beside the TEMP display.
    graphics.append(silk_line((31.0, 101.5), (31.0, 104.3), origin, width=0.3))
    graphics.extend(
        clipped_circle_outline((31.0, 105.0), 0.7, (), origin, width=0.25)
    )
    # Droplet beside the HUM display.
    graphics.append(silk_line((30.3, 109.6), (31.0, 108.2), origin, width=0.2))
    graphics.append(silk_line((31.7, 109.6), (31.0, 108.2), origin, width=0.2))
    graphics.extend(
        clipped_circle_outline((31.0, 110.2), 0.8, (), origin, width=0.2)
    )
    return graphics


def thermometer_silk_graphics(origin: float) -> tuple[str, ...]:
    graphics: list[str] = [
        *(_graduations(origin)),
        *(_icons(origin)),
        silk_text("TEMP", (13.6, 104.0), origin, size=0.8),
        silk_text("HUM", (13.6, 111.0), origin, size=0.8),
        silk_text("USB-C 5V", (23.0, 145.2), origin, size=0.8),
    ]
    return tuple(graphics)


def _hanging_hole() -> tuple[BoardComponent, float, float]:
    return (
        BoardComponent(
            reference="H1",
            value="M3",
            footprint="MountingHole:MountingHole_3.2mm_M3",
            uuid_path=str(uuid4()),
        ),
        STEM_CX,
        13.5,
    )


def thermometer_checks_spec() -> DesignChecksSpec:
    worst = 0.45  # calculator worst-case rail (WiFi burst), rounded up
    return DesignChecksSpec(
        net_currents=tuple((net, worst) for net in POWER_NETS),
        component_cards=(
            ("U1", "ESP32-C3-WROOM-02"),
            ("U2", "SN74HC595PW"),
            ("U3", "SN74HC595PW"),
            ("U4", "SHT31-DIS"),
        ),
        tie_nets=(("GND", "/GND"), ("VCC", "/VCC")),
        # J2/J3 hold the OLED modules ON the board - they are not
        # off-board wiring and sit mid-stem by design.
        connector_edge_exempt_refs=("J2", "J3"),
        allowed_unconnected_pins=(
            # USB 2.0 leaves the SBU pair open; the shell's unnamed
            # anchors carry no net by design.
            ("J1", "A8"), ("J1", "B8"),
            # Module: IO9 strap uses the internal pull-up; UART unused.
            ("U1", "8"), ("U1", "11"), ("U1", "12"),
            # End of the 74HC595 cascade.
            ("U3", "9"),
            # SHT31 ALERT/nRESET float per Table 7.
            ("U4", "3"), ("U4", "6"),
            # AP2112 package NC.
            ("U5", "4"),
        ),
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
    hole, hole_x, hole_y = _hanging_hole()
    placements.append((hole, hole_x))
    part_y.append((hole.reference, hole_y))
    return BoardLayout(
        placements=tuple(placements),
        segments=(),
        vias=(),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(part_rotation),
        zones=(),
        outline=thermometer_outline(),
        graphics=thermometer_silk_graphics(BOARD_SHEET_ORIGIN_MM),
        part_reference_at=tuple(REFERENCE_AT.items()),
        part_flip=FLIPPED_REFS,
    )


# Nets that must ENTER 0.5mm-pitch pads (USB-C data/CC row, the
# SHT31 DFN) or thread the USB shell's hole belt. Declaration order is
# routing priority: the pad-pinned USB signals first (their only exit
# is the narrow corridor between the shell's NPTH holes), then the
# 0.4mm power pair (it can dive to the empty front to cross), then
# VCC/GND, whose many pads leave them the most freedom. Widths
# verified against IPC-2221 by the trace_current check at the
# worst-case rail current.
FINE_PITCH_NETS: dict[str, float] = {
    "/DP": 0.2, "/DM": 0.2,
    "/VBUS": 0.4, "/VBUSF": 0.4,
    "/CC1": 0.2, "/CC2": 0.2,
    "/SDA1": 0.25, "/SCL1": 0.25,
    # /CAS spans both TSSOP pin columns (U2.9 -> U3.14) with its pads
    # pinched between the registers' VCC pins - it must claim its stem
    # lane before the rails do.
    "/CAS": 0.2,
    "/VCC": 0.25, "/GND": 0.25,
}


def compute_thermometer_board_layout(netlist: BoardNetlist) -> BoardLayout:
    result = route_board(
        _unrouted_layout(netlist),
        netlist,
        fine_pitch_nets=FINE_PITCH_NETS,
        net_widths={
            # 74HC595 nets enter the 0.65mm-pitch TSSOP rows: 0.2mm
            # keeps every pad enterable at any grid parity, and the
            # slimmer class relieves the stem's three-column squeeze.
            **{f"/SEG{i}": 0.2 for i in range(1, LED_COUNT + 1)},
            "/SER": 0.2, "/SRCLK": 0.2,
            "/RCLK": 0.2, "/OE": 0.2,
        },
        default_width_mm=SIG_W,
        # The four control trunks run the full stem (module to both
        # registers) and are the least flexible nets on the board;
        # shortest-first ordering let the local SEG/LK crowd wall them
        # in (probed: /SER routes in one try when FIRST, fails after
        # sixteen restarts when last).
        net_order=("/SER", "/SRCLK", "/RCLK", "/OE"),
        # The stem is one long shared corridor: single-net promotion
        # needs more attempts than an open board.
        max_restarts=16,
    )
    if result.failed:
        raise BoardGenerationError(
            "route_board could not route: " + ", ".join(result.failed)
        )
    return result.layout


def generate_thermometer_board(
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
    layout = compute_thermometer_board_layout(netlist)
    board_file.write_text(
        render_board_from_layout(netlist, layout), encoding="utf-8"
    )
    return netlist, layout
