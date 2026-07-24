"""Placement and deterministic routing for the eight-channel protocol analyzer."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from pcbsmith.kicad.astar_router import route_board
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
    export_kicad_netlist_xml,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import load_footprint
from pcbsmith.kicad.shaped_board import silk_text
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    FabElectricalSpacingProfile,
    FabricationGeometryProfile,
    PcbRuleProfile,
)

BOARD_W = 88.0
BOARD_H = 50.0
SIGNAL_W = 0.20

PROTOCOL_ANALYZER_RULE_PROFILE = PcbRuleProfile(
    profile_id="protocol-analyzer-8ch-budget-fab-v1",
    geometry=FabricationGeometryProfile(
        profile_id="protocol-analyzer-8ch-geometry-v1",
        basis="project_requirement",
        minimum_trace_width_mm=0.15,
        default_signal_trace_width_mm=SIGNAL_W,
        default_power_trace_width_mm=0.35,
        routing_via_diameter_mm=0.60,
        routing_via_drill_mm=0.30,
        power_via_diameter_mm=0.80,
        power_via_drill_mm=0.40,
        board_thickness_mm=1.6,
        copper_layer_count=2,
        substrate_description="FR-4",
    ),
    fab_spacing=FabElectricalSpacingProfile(
        profile_id="protocol-analyzer-8ch-spacing-v1",
        basis="project_requirement",
        minimum_copper_clearance_mm=0.15,
        minimum_copper_to_edge_mm=0.30,
        minimum_hole_to_copper_mm=0.25,
    ),
    insulation=DEFAULT_PCB_RULE_PROFILE.insulation,
)

# The placements are the engineering translation of the accepted vector study:
# connector protection flows from the edges inward, the 20-pin target interface
# has a complete alternating ground column, and the RP2040 core remains central.
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "J1": (4.20, 25.00, 90.0),
    "U8": (10.50, 25.00, 0.0),
    "R3": (33.00, 20.50, 0.0),
    "R4": (33.00, 18.50, 0.0),
    "U3": (14.00, 11.50, 90.0),
    "C1": (7.50, 10.00, 90.0),
    "C2": (10.00, 10.00, 90.0),
    "C3": (18.00, 10.00, 90.0),
    "C4": (21.00, 10.00, 90.0),
    "R1": (4.00, 33.00, 90.0),
    "R2": (4.00, 17.00, 90.0),
    "U1": (42.00, 25.00, 0.0),
    "U2": (42.00, 16.00, 270.0),
    "Y1": (31.00, 31.00, 0.0),
    "R5": (35.00, 31.00, 90.0),
    "C5": (27.00, 28.00, 0.0),
    "C6": (33.00, 34.00, 0.0),
    "SW1": (27.00, 7.00, 0.0),
    "SW2": (35.00, 7.00, 0.0),
    "R6": (28.00, 12.00, 0.0),
    "R7": (31.00, 12.00, 0.0),
    "R8": (35.00, 12.00, 0.0),
    "J3": (45.00, 38.00, 0.0),
    "D1": (17.00, 42.00, 0.0),
    "R9": (20.00, 42.00, 0.0),
    "D2": (31.00, 40.00, 0.0),
    "R10": (35.00, 40.00, 180.0),
    "J2": (82.00, 12.50, 0.0),
    "U6": (75.50, 16.31, 0.0),
    "U7": (75.50, 26.47, 0.0),
    "U4": (60.00, 25.00, 0.0),
    "U9": (65.00, 35.36, 180.0),
    "D3": (77.00, 38.00, 90.0),
    "R19": (72.00, 35.36, 180.0),
    "R22": (80.00, 39.00, 90.0),
    "R20": (76.00, 32.82, 180.0),
    "R21": (74.00, 42.00, 0.0),
    "C19": (69.00, 42.00, 0.0),
    "C7": (57.00, 20.00, 0.0),
    "C8": (57.00, 30.00, 0.0),
    "C9": (62.00, 39.00, 0.0),
    "C10": (35.00, 24.00, 90.0),
    "C11": (49.00, 24.00, 90.0),
    "C12": (38.00, 31.00, 0.0),
    "C13": (46.00, 31.00, 0.0),
    "C14": (38.00, 35.00, 0.0),
    "C15": (46.00, 35.00, 0.0),
    "C16": (53.00, 45.00, 0.0),
    "C17": (42.00, 31.50, 0.0),
    "C18": (47.00, 16.00, 90.0),
}

for index in range(8):
    PLACEMENTS[f"R{index + 11}"] = (
        68.0,
        12.50 + index * 2.54,
        180.0,
    )

MOUNTING_HOLES = (
    ("H1", 4.0, 4.0),
    ("H2", 84.0, 4.0),
    ("H3", 4.0, 46.0),
    ("H4", 84.0, 46.0),
)

HIDE_REFERENCES = ("J1", "J2", "J3", "SW1", "SW2")


def compute_protocol_analyzer_placement(netlist: BoardNetlist) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    rotations: list[tuple[str, float]] = []
    for reference, (x, y, rotation) in PLACEMENTS.items():
        if reference not in by_ref:
            raise BoardGenerationError(
                f"Protocol-analyzer netlist is missing {reference}."
            )
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
                "board-component-path", "protocol-analyzer-hole", reference
            ),
        )
        placements.append((hole, x))
        part_y.append((reference, y))
    graphics = (
        silk_text("USB", (2.0, 34.0), BOARD_SHEET_ORIGIN_MM, size=0.9),
        silk_text("8-CH PROTOCOL ANALYZER", (27.0, 48.0), BOARD_SHEET_ORIGIN_MM, size=1.0),
        silk_text("CH0", (77.0, 11.5), BOARD_SHEET_ORIGIN_MM, size=0.70),
        silk_text("CH7", (77.0, 38.8), BOARD_SHEET_ORIGIN_MM, size=0.70),
        silk_text("VT", (78.0, 43.0), BOARD_SHEET_ORIGIN_MM, size=0.70),
        silk_text("TRIG", (75.0, 47.5), BOARD_SHEET_ORIGIN_MM, size=0.70),
        silk_text("BOOT", (23.0, 10.5), BOARD_SHEET_ORIGIN_MM, size=0.70),
        silk_text("RESET", (34.0, 10.5), BOARD_SHEET_ORIGIN_MM, size=0.70),
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
            ("/3V3", "F.Cu", (0.60, 0.60, BOARD_W - 0.60, BOARD_H - 0.60)),
            ("/GND", "B.Cu", (0.60, 0.60, BOARD_W - 0.60, BOARD_H - 0.60)),
        ),
        graphics=graphics,
        hide_references=HIDE_REFERENCES,
    )


def compute_protocol_analyzer_routed_layout(netlist: BoardNetlist) -> BoardLayout:
    working = _usb_connector_fanout(compute_protocol_analyzer_placement(netlist))
    routable = {net.name for net in netlist.nets if len(set(net.nodes)) >= 2}
    frozen: set[str] = {
        "/GND",
        "/USB_DP_CONN", "/USB_DM_CONN",
        "/USB_DP_ESD", "/USB_DM_ESD",
        "/USB_DP_MCU", "/USB_DM_MCU",
        "/CC1", "/CC2",
        "/QSPI_SCLK", "/QSPI_SD0", "/QSPI_SD1",
        "/QSPI_SD2", "/QSPI_SD3", "/QSPI_SS",
        "/XIN", "/XOUT_RAW", "/XOUT",
        *(f"/CH{index}_RAW" for index in range(8)),
        *(f"/CH{index}_BUF" for index in range(8)),
        "/VTARGET_RAW", "/VTARGET_ADC",
        "/RUN",
        "/STATUS_GPIO", "/STATUS_LED_A",
        "/SWCLK", "/SWDIO",
        "/VBUS", "/3V3", "/1V1",
    }

    def route_domain(
        label: str,
        names: tuple[str, ...],
        *,
        widths: dict[str, float] | None = None,
        fine: bool = False,
        max_expansions: int = 250_000,
        max_expansions_per_net: int = 40_000,
    ) -> None:
        nonlocal working
        active = tuple(name for name in names if name in routable and name not in frozen)
        if not active:
            return
        active_widths = (
            {name: width for name, width in widths.items() if name in active}
            if widths is not None
            else None
        )
        result = route_board(
            working,
            netlist,
            fine_pitch_nets=(
                active_widths or {name: 0.15 for name in active}
            ) if fine else None,
            fine_grid_mm=0.05,
            net_widths=active_widths,
            default_width_mm=SIGNAL_W,
            net_order=active,
            skip_nets=routable - set(active),
            max_restarts=2,
            max_expansions=max_expansions,
            max_expansions_per_net=max_expansions_per_net,
            profile=PROTOCOL_ANALYZER_RULE_PROFILE,
        )
        if result.failed:
            raise BoardGenerationError(
                f"{label} routing could not route: " + ", ".join(result.failed)
            )
        working = result.layout
        frozen.update(active)

    route_domain(
        "USB",
        (
            "/USB_DM_CONN", "/USB_DP_CONN", "/USB_DM_ESD", "/USB_DP_ESD",
            "/USB_DM_MCU", "/USB_DP_MCU", "/CC1", "/CC2",
        ),
        widths={
            "/USB_DM_CONN": 0.15, "/USB_DP_CONN": 0.15,
            "/USB_DM_ESD": 0.15, "/USB_DP_ESD": 0.15,
            "/USB_DM_MCU": 0.15, "/USB_DP_MCU": 0.15,
            "/CC1": 0.20, "/CC2": 0.20,
        },
        fine=True,
    )
    route_domain(
        "QSPI",
        (
            "/QSPI_SCLK", "/QSPI_SD0", "/QSPI_SD1", "/QSPI_SD2",
            "/QSPI_SD3", "/QSPI_SS",
        ),
        widths={name: 0.15 for name in (
            "/QSPI_SCLK", "/QSPI_SD0", "/QSPI_SD1", "/QSPI_SD2",
            "/QSPI_SD3", "/QSPI_SS",
        )},
        fine=True,
    )
    route_domain("clock", ("/XIN", "/XOUT_RAW", "/XOUT"), fine=True)
    route_domain(
        "input conditioning",
        tuple(f"/CH{index}_IN" for index in range(8)),
        fine=True,
        max_expansions=1_000_000,
        max_expansions_per_net=150_000,
    )
    route_domain(
        "buffer outputs",
        tuple(f"/CH{index}_BUF" for index in range(8)),
        fine=True,
        max_expansions=1_000_000,
        max_expansions_per_net=150_000,
    )
    route_domain(
        "trigger and target monitor",
        ("/TRIG_RAW", "/TRIG_IN", "/TRIG_BUF", "/VTARGET_RAW", "/VTARGET_ADC"),
    )
    route_domain(
        "debug and controls",
        (
            "/RUN", "/SWCLK", "/SWDIO", "/BOOT_BTN",
            "/STATUS_GPIO", "/STATUS_LED_A", "/PWR_LED_K",
        ),
    )
    route_domain(
        "power",
        ("/VBUS", "/3V3", "/1V1"),
        widths={"/VBUS": 0.35, "/3V3": 0.35, "/1V1": 0.30},
    )
    remaining = tuple(sorted(routable - frozen))
    route_domain("remaining", remaining)
    # Ground remains a bottom-plane authority.  The final KiCad DRC is run
    # after zone fill; local return vias are added only when the DRC/readback
    # identifies an SMD ground island that the plane cannot reach.
    return working


def _usb_connector_fanout(layout: BoardLayout) -> BoardLayout:
    """Resolve the reversible USB-C A/B contact interleave before A* routing.

    The GCT receptacle exposes D+/D- in the B6, A7, A6, B7 order.  One member
    of each duplicated pair takes a short bottom-layer dogleg so the two nets
    do not cross or depend on a heuristic escape.
    """

    segments = (
        TrackSegment(0.52, 24.25, 9.363, 24.05, "F.Cu", "/USB_DP_CONN", 0.15),
        TrackSegment(0.52, 25.75, 9.363, 25.95, "F.Cu", "/USB_DM_CONN", 0.15),
        TrackSegment(0.52, 25.25, 2.00, 25.25, "F.Cu", "/USB_DP_CONN", 0.15),
        TrackSegment(2.00, 25.25, 2.00, 22.50, "B.Cu", "/USB_DP_CONN", 0.15),
        TrackSegment(2.00, 22.50, 6.00, 22.50, "B.Cu", "/USB_DP_CONN", 0.15),
        TrackSegment(6.00, 22.50, 6.00, 24.126, "B.Cu", "/USB_DP_CONN", 0.15),
        TrackSegment(0.52, 24.75, 3.50, 24.75, "F.Cu", "/USB_DM_CONN", 0.15),
        TrackSegment(3.50, 24.75, 3.50, 27.50, "B.Cu", "/USB_DM_CONN", 0.15),
        TrackSegment(3.50, 27.50, 6.50, 27.50, "B.Cu", "/USB_DM_CONN", 0.15),
        TrackSegment(6.50, 27.50, 6.50, 25.885, "B.Cu", "/USB_DM_CONN", 0.15),
        TrackSegment(11.637, 24.05, 18.00, 24.05, "F.Cu", "/USB_DP_ESD", 0.15),
        TrackSegment(18.00, 24.05, 23.00, 19.05, "F.Cu", "/USB_DP_ESD", 0.15),
        TrackSegment(23.00, 19.05, 32.175, 18.50, "F.Cu", "/USB_DP_ESD", 0.15),
        TrackSegment(11.637, 25.95, 18.00, 25.95, "F.Cu", "/USB_DM_ESD", 0.15),
        TrackSegment(18.00, 25.95, 23.00, 20.95, "F.Cu", "/USB_DM_ESD", 0.15),
        TrackSegment(23.00, 20.95, 32.175, 20.50, "F.Cu", "/USB_DM_ESD", 0.15),
        TrackSegment(33.825, 18.50, 36.00, 18.50, "F.Cu", "/USB_DP_MCU", 0.15),
        TrackSegment(36.00, 18.50, 40.00, 18.50, "B.Cu", "/USB_DP_MCU", 0.15),
        TrackSegment(40.00, 18.50, 43.00, 20.50, "B.Cu", "/USB_DP_MCU", 0.15),
        TrackSegment(43.00, 20.50, 43.00, 21.562, "F.Cu", "/USB_DP_MCU", 0.15),
        TrackSegment(33.825, 20.50, 39.00, 20.50, "F.Cu", "/USB_DM_MCU", 0.15),
        TrackSegment(39.00, 20.50, 41.00, 22.30, "F.Cu", "/USB_DM_MCU", 0.15),
        TrackSegment(41.00, 22.30, 43.40, 21.562, "F.Cu", "/USB_DM_MCU", 0.15),
        TrackSegment(0.52, 26.25, 2.00, 26.25, "F.Cu", "/CC1", 0.20),
        TrackSegment(2.00, 26.25, 2.00, 32.175, "F.Cu", "/CC1", 0.20),
        TrackSegment(2.00, 32.175, 4.00, 32.175, "F.Cu", "/CC1", 0.20),
        TrackSegment(0.52, 23.25, 2.00, 23.25, "F.Cu", "/CC2", 0.20),
        TrackSegment(2.00, 23.25, 2.00, 16.175, "F.Cu", "/CC2", 0.20),
        TrackSegment(2.00, 16.175, 4.00, 16.175, "F.Cu", "/CC2", 0.20),
        TrackSegment(40.095, 18.475, 40.60, 21.562, "F.Cu", "/QSPI_SD0", 0.15),
        TrackSegment(41.365, 18.475, 41.00, 21.562, "F.Cu", "/QSPI_SCLK", 0.15),
        TrackSegment(42.635, 18.475, 41.40, 21.562, "F.Cu", "/QSPI_SD3", 0.15),
        TrackSegment(42.635, 13.525, 42.635, 11.50, "F.Cu", "/QSPI_SD1", 0.15),
        TrackSegment(42.635, 11.50, 38.00, 11.50, "F.Cu", "/QSPI_SD1", 0.15),
        TrackSegment(38.00, 11.50, 38.00, 20.60, "F.Cu", "/QSPI_SD1", 0.15),
        TrackSegment(38.00, 20.60, 39.80, 21.562, "F.Cu", "/QSPI_SD1", 0.15),
        TrackSegment(41.365, 13.525, 41.365, 11.00, "F.Cu", "/QSPI_SD2", 0.15),
        TrackSegment(41.365, 11.00, 36.50, 11.00, "B.Cu", "/QSPI_SD2", 0.15),
        TrackSegment(36.50, 11.00, 36.50, 22.50, "B.Cu", "/QSPI_SD2", 0.15),
        TrackSegment(36.50, 22.50, 40.20, 22.50, "B.Cu", "/QSPI_SD2", 0.15),
        TrackSegment(40.20, 22.50, 40.20, 21.562, "F.Cu", "/QSPI_SD2", 0.15),
        TrackSegment(43.905, 13.525, 43.905, 12.50, "F.Cu", "/QSPI_SS", 0.15),
        TrackSegment(43.905, 12.50, 46.00, 12.50, "B.Cu", "/QSPI_SS", 0.15),
        TrackSegment(46.00, 12.50, 46.00, 20.50, "B.Cu", "/QSPI_SS", 0.15),
        TrackSegment(46.00, 20.50, 45.30, 20.50, "B.Cu", "/QSPI_SS", 0.15),
        TrackSegment(45.30, 20.50, 44.30, 20.50, "F.Cu", "/QSPI_SS", 0.15),
        TrackSegment(44.30, 20.50, 39.40, 20.50, "B.Cu", "/QSPI_SS", 0.15),
        TrackSegment(39.40, 20.50, 39.40, 21.562, "F.Cu", "/QSPI_SS", 0.15),
        TrackSegment(41.40, 28.438, 38.00, 29.50, "F.Cu", "/XIN", 0.15),
        TrackSegment(38.00, 29.50, 33.50, 31.85, "F.Cu", "/XIN", 0.15),
        TrackSegment(33.50, 31.85, 29.90, 31.85, "F.Cu", "/XIN", 0.15),
        TrackSegment(29.90, 31.85, 26.225, 28.00, "F.Cu", "/XIN", 0.15),
        TrackSegment(41.80, 28.438, 42.50, 29.20, "F.Cu", "/XOUT_RAW", 0.15),
        TrackSegment(42.50, 29.20, 35.80, 32.50, "B.Cu", "/XOUT_RAW", 0.15),
        TrackSegment(35.80, 32.50, 35.00, 31.825, "F.Cu", "/XOUT_RAW", 0.15),
        TrackSegment(35.00, 30.175, 32.10, 30.15, "F.Cu", "/XOUT", 0.15),
        TrackSegment(32.10, 30.15, 32.225, 34.00, "F.Cu", "/XOUT", 0.15),
        *(
            TrackSegment(
                68.825, 12.50 + index * 2.54,
                82.00, 12.50 + index * 2.54,
                "F.Cu", f"/CH{index}_RAW", 0.15,
            )
            for index in range(8)
        ),
        TrackSegment(75.115, 12.50, 75.115, 15.31, "F.Cu", "/CH0_RAW", 0.15),
        TrackSegment(75.115, 15.04, 75.115, 15.81, "F.Cu", "/CH1_RAW", 0.15),
        TrackSegment(75.115, 17.58, 75.115, 16.81, "F.Cu", "/CH2_RAW", 0.15),
        TrackSegment(75.115, 20.12, 75.115, 17.31, "F.Cu", "/CH3_RAW", 0.15),
        TrackSegment(75.115, 22.66, 75.115, 25.47, "F.Cu", "/CH4_RAW", 0.15),
        TrackSegment(75.115, 25.20, 75.115, 25.97, "F.Cu", "/CH5_RAW", 0.15),
        TrackSegment(75.115, 27.74, 75.115, 26.97, "F.Cu", "/CH6_RAW", 0.15),
        TrackSegment(75.115, 30.28, 75.115, 27.47, "F.Cu", "/CH7_RAW", 0.15),
        TrackSegment(57.138, 23.375, 52.00, 23.375, "F.Cu", "/CH4_BUF", 0.15),
        TrackSegment(52.00, 23.375, 48.00, 24.80, "F.Cu", "/CH4_BUF", 0.15),
        TrackSegment(48.00, 24.80, 45.438, 24.80, "F.Cu", "/CH4_BUF", 0.15),
        TrackSegment(57.138, 24.675, 52.00, 24.675, "F.Cu", "/CH5_BUF", 0.15),
        TrackSegment(52.00, 24.675, 48.00, 25.20, "F.Cu", "/CH5_BUF", 0.15),
        TrackSegment(48.00, 25.20, 45.438, 25.20, "F.Cu", "/CH5_BUF", 0.15),
        TrackSegment(57.138, 25.975, 52.00, 25.975, "F.Cu", "/CH6_BUF", 0.15),
        TrackSegment(52.00, 25.975, 48.00, 25.60, "F.Cu", "/CH6_BUF", 0.15),
        TrackSegment(48.00, 25.60, 45.438, 25.60, "F.Cu", "/CH6_BUF", 0.15),
        TrackSegment(57.138, 27.275, 52.00, 27.275, "F.Cu", "/CH7_BUF", 0.15),
        TrackSegment(52.00, 27.275, 48.00, 26.40, "F.Cu", "/CH7_BUF", 0.15),
        TrackSegment(48.00, 26.40, 45.438, 26.40, "F.Cu", "/CH7_BUF", 0.15),
        TrackSegment(62.862, 23.375, 64.00, 23.375, "F.Cu", "/CH0_BUF", 0.15),
        TrackSegment(64.00, 23.375, 64.00, 31.00, "B.Cu", "/CH0_BUF", 0.15),
        TrackSegment(64.00, 31.00, 48.00, 31.00, "B.Cu", "/CH0_BUF", 0.15),
        TrackSegment(48.00, 31.00, 48.00, 23.20, "B.Cu", "/CH0_BUF", 0.15),
        TrackSegment(48.00, 23.20, 45.438, 23.20, "F.Cu", "/CH0_BUF", 0.15),
        TrackSegment(62.862, 24.675, 65.00, 24.675, "F.Cu", "/CH1_BUF", 0.15),
        TrackSegment(65.00, 24.675, 65.00, 32.00, "B.Cu", "/CH1_BUF", 0.15),
        TrackSegment(65.00, 32.00, 49.00, 32.00, "B.Cu", "/CH1_BUF", 0.15),
        TrackSegment(49.00, 32.00, 49.00, 23.60, "B.Cu", "/CH1_BUF", 0.15),
        TrackSegment(49.00, 23.60, 45.438, 23.60, "F.Cu", "/CH1_BUF", 0.15),
        TrackSegment(62.862, 25.975, 66.00, 25.975, "F.Cu", "/CH2_BUF", 0.15),
        TrackSegment(66.00, 25.975, 66.00, 33.00, "B.Cu", "/CH2_BUF", 0.15),
        TrackSegment(66.00, 33.00, 50.00, 33.00, "B.Cu", "/CH2_BUF", 0.15),
        TrackSegment(50.00, 33.00, 50.00, 24.00, "B.Cu", "/CH2_BUF", 0.15),
        TrackSegment(50.00, 24.00, 45.438, 24.00, "F.Cu", "/CH2_BUF", 0.15),
        TrackSegment(62.862, 27.275, 67.00, 27.275, "F.Cu", "/CH3_BUF", 0.15),
        TrackSegment(67.00, 27.275, 67.00, 34.00, "B.Cu", "/CH3_BUF", 0.15),
        TrackSegment(67.00, 34.00, 51.00, 34.00, "B.Cu", "/CH3_BUF", 0.15),
        TrackSegment(51.00, 34.00, 51.00, 24.40, "B.Cu", "/CH3_BUF", 0.15),
        TrackSegment(51.00, 24.40, 45.438, 24.40, "F.Cu", "/CH3_BUF", 0.15),
        TrackSegment(82.00, 32.82, 76.825, 32.82, "F.Cu", "/VTARGET_RAW", 0.20),
        TrackSegment(75.175, 32.82, 76.00, 36.50, "F.Cu", "/VTARGET_ADC", 0.20),
        TrackSegment(76.00, 36.50, 47.00, 36.50, "B.Cu", "/VTARGET_ADC", 0.20),
        TrackSegment(47.00, 36.50, 47.00, 22.80, "B.Cu", "/VTARGET_ADC", 0.20),
        TrackSegment(47.00, 22.80, 45.438, 22.80, "F.Cu", "/VTARGET_ADC", 0.20),
        TrackSegment(75.175, 32.82, 75.175, 40.50, "F.Cu", "/VTARGET_ADC", 0.20),
        TrackSegment(75.175, 40.50, 73.175, 42.00, "F.Cu", "/VTARGET_ADC", 0.20),
        TrackSegment(75.175, 40.50, 68.225, 40.50, "F.Cu", "/VTARGET_ADC", 0.20),
        TrackSegment(68.225, 40.50, 68.225, 42.00, "F.Cu", "/VTARGET_ADC", 0.20),
        TrackSegment(32.375, 6.15, 37.625, 6.15, "F.Cu", "/RUN", 0.20),
        TrackSegment(35.825, 6.15, 35.825, 12.00, "F.Cu", "/RUN", 0.20),
        TrackSegment(35.825, 12.00, 34.00, 13.00, "F.Cu", "/RUN", 0.20),
        TrackSegment(34.00, 13.00, 34.00, 30.00, "B.Cu", "/RUN", 0.20),
        TrackSegment(34.00, 30.00, 43.80, 30.00, "B.Cu", "/RUN", 0.20),
        TrackSegment(43.80, 30.00, 43.80, 28.438, "F.Cu", "/RUN", 0.20),
        TrackSegment(46.27, 43.08, 44.50, 41.50, "F.Cu", "/RUN", 0.20),
        TrackSegment(44.50, 41.50, 44.50, 30.00, "B.Cu", "/RUN", 0.20),
        TrackSegment(44.50, 30.00, 43.80, 30.00, "B.Cu", "/RUN", 0.20),
        TrackSegment(44.20, 28.438, 42.50, 31.50, "F.Cu", "/STATUS_GPIO", 0.20),
        TrackSegment(42.50, 31.50, 42.50, 37.00, "B.Cu", "/STATUS_GPIO", 0.20),
        TrackSegment(42.50, 37.00, 36.50, 39.00, "B.Cu", "/STATUS_GPIO", 0.20),
        TrackSegment(36.50, 39.00, 35.825, 40.00, "F.Cu", "/STATUS_GPIO", 0.20),
        TrackSegment(34.175, 40.00, 31.788, 40.00, "F.Cu", "/STATUS_LED_A", 0.20),
        TrackSegment(43.40, 28.438, 45.50, 31.00, "F.Cu", "/SWDIO", 0.15),
        TrackSegment(45.50, 31.00, 45.50, 36.00, "F.Cu", "/SWDIO", 0.15),
        TrackSegment(45.50, 36.00, 46.27, 38.00, "F.Cu", "/SWDIO", 0.15),
        TrackSegment(43.00, 28.438, 44.70, 31.00, "F.Cu", "/SWCLK", 0.15),
        TrackSegment(44.70, 31.00, 44.70, 37.00, "F.Cu", "/SWCLK", 0.15),
        TrackSegment(44.70, 37.00, 46.27, 39.27, "F.Cu", "/SWCLK", 0.15),
        TrackSegment(0.52, 22.60, 0.90, 22.60, "F.Cu", "/VBUS", 0.35),
        TrackSegment(0.52, 27.40, 0.90, 27.40, "F.Cu", "/VBUS", 0.35),
        TrackSegment(0.90, 22.60, 0.90, 27.40, "B.Cu", "/VBUS", 0.35),
        TrackSegment(0.90, 22.60, 0.90, 12.00, "B.Cu", "/VBUS", 0.35),
        TrackSegment(0.90, 12.00, 12.00, 12.00, "B.Cu", "/VBUS", 0.35),
        TrackSegment(12.00, 12.00, 13.05, 12.637, "F.Cu", "/VBUS", 0.35),
        TrackSegment(13.05, 12.637, 14.95, 12.637, "F.Cu", "/VBUS", 0.35),
        TrackSegment(12.00, 12.00, 10.00, 10.95, "F.Cu", "/VBUS", 0.35),
        TrackSegment(10.00, 10.95, 7.50, 10.95, "F.Cu", "/VBUS", 0.35),
        TrackSegment(11.637, 25.00, 12.50, 25.00, "F.Cu", "/VBUS", 0.35),
        TrackSegment(12.50, 25.00, 12.00, 12.00, "B.Cu", "/VBUS", 0.35),
        TrackSegment(43.80, 21.562, 44.80, 19.50, "F.Cu", "/1V1", 0.30),
        TrackSegment(41.80, 21.562, 41.80, 19.50, "F.Cu", "/1V1", 0.30),
        TrackSegment(41.80, 19.50, 44.80, 19.50, "B.Cu", "/1V1", 0.30),
        TrackSegment(44.80, 19.50, 44.80, 29.50, "B.Cu", "/1V1", 0.30),
        TrackSegment(44.80, 29.50, 42.60, 29.50, "B.Cu", "/1V1", 0.30),
        TrackSegment(42.60, 29.50, 42.60, 28.438, "F.Cu", "/1V1", 0.30),
        TrackSegment(42.60, 29.50, 41.225, 31.50, "F.Cu", "/1V1", 0.30),
    )
    vias = (
        ViaSpec(2.00, 25.25, "/USB_DP_CONN"),
        ViaSpec(6.00, 24.126, "/USB_DP_CONN"),
        ViaSpec(3.50, 24.75, "/USB_DM_CONN"),
        ViaSpec(6.50, 25.885, "/USB_DM_CONN"),
        ViaSpec(36.00, 18.50, "/USB_DP_MCU"),
        ViaSpec(43.00, 20.50, "/USB_DP_MCU"),
        ViaSpec(41.365, 11.00, "/QSPI_SD2"),
        ViaSpec(40.20, 22.50, "/QSPI_SD2"),
        ViaSpec(43.905, 12.50, "/QSPI_SS"),
        ViaSpec(45.30, 20.50, "/QSPI_SS"),
        ViaSpec(44.30, 20.50, "/QSPI_SS"),
        ViaSpec(39.40, 20.50, "/QSPI_SS"),
        ViaSpec(42.50, 29.20, "/XOUT_RAW"),
        ViaSpec(35.80, 32.50, "/XOUT_RAW"),
        ViaSpec(64.00, 23.375, "/CH0_BUF"),
        ViaSpec(48.00, 23.20, "/CH0_BUF"),
        ViaSpec(65.00, 24.675, "/CH1_BUF"),
        ViaSpec(49.00, 23.60, "/CH1_BUF"),
        ViaSpec(66.00, 25.975, "/CH2_BUF"),
        ViaSpec(50.00, 24.00, "/CH2_BUF"),
        ViaSpec(67.00, 27.275, "/CH3_BUF"),
        ViaSpec(51.00, 24.40, "/CH3_BUF"),
        ViaSpec(76.00, 36.50, "/VTARGET_ADC"),
        ViaSpec(47.00, 22.80, "/VTARGET_ADC"),
        ViaSpec(34.00, 13.00, "/RUN"),
        ViaSpec(43.80, 30.00, "/RUN"),
        ViaSpec(44.50, 41.50, "/RUN"),
        ViaSpec(42.50, 31.50, "/STATUS_GPIO"),
        ViaSpec(36.50, 39.00, "/STATUS_GPIO"),
        ViaSpec(0.90, 22.60, "/VBUS"),
        ViaSpec(0.90, 27.40, "/VBUS"),
        ViaSpec(12.00, 12.00, "/VBUS"),
        ViaSpec(12.50, 25.00, "/VBUS"),
        ViaSpec(44.80, 19.50, "/1V1"),
        ViaSpec(41.80, 19.50, "/1V1"),
        ViaSpec(42.60, 29.50, "/1V1"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _generate(
    *,
    schematic_file: Path,
    board_file: Path,
    routed: bool,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    for footprint in {component.footprint for component in netlist.components}:
        if footprint not in FOOTPRINT_LIBRARY:
            FOOTPRINT_LIBRARY[footprint] = load_footprint(footprint).spec
    layout = (
        compute_protocol_analyzer_routed_layout(netlist)
        if routed
        else compute_protocol_analyzer_placement(netlist)
    )
    board_file.write_text(
        render_board_from_layout(
            netlist, layout, profile=PROTOCOL_ANALYZER_RULE_PROFILE
        ),
        encoding="utf-8",
    )
    return netlist, layout


def generate_protocol_analyzer_placement_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    return _generate(
        schematic_file=schematic_file,
        board_file=board_file,
        routed=False,
        finder=finder,
        runner=runner,
    )


def generate_protocol_analyzer_routed_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    return _generate(
        schematic_file=schematic_file,
        board_file=board_file,
        routed=True,
        finder=finder,
        runner=runner,
    )
