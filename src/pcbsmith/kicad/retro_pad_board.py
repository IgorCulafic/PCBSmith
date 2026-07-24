"""Routed two-layer dogbone board for the Retro-Pad macro keyboard."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

from pcbsmith.kicad.astar_router import route_board
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardCutoutPolygon,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    export_kicad_netlist_xml,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.raster_artwork import trace_board_outline
from pcbsmith.kicad.shaped_board import silk_line, silk_text
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    FabElectricalSpacingProfile,
    FabricationGeometryProfile,
    PcbRuleProfile,
)

BOARD_W = 120.0
BOARD_H = 46.5306
SIGNAL_W = 0.25
POWER_W = 0.4

# Switch anchors are derived from the probed Cherry footprint center
# (-2.54, +5.08 relative to pad 1).  The top and bottom rows face inward so
# their electrical pads remain on the dogbone substrate while preserving a
# true 19.05 mm key-center grid.
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "SW1": (17.46, 18.58, 180.0),
    "SW2": (36.51, 18.58, 180.0),
    "SW3": (22.54, 27.47, 0.0),
    "SW4": (41.59, 27.47, 0.0),
    "SW5": (98.0, 20.5, 0.0),
    "J1": (60.0, 13.3, 180.0),
    # Back-side USB and controller core.
    "U2": (61.0, 21.5, 0.0),
    "R3": (66.0, 21.0, 0.0),
    "R4": (66.0, 23.0, 0.0),
    "F1": (53.0, 15.0, 90.0),
    "R1": (71.0, 17.0, 0.0),
    "R2": (55.0, 21.0, 0.0),
    "U1": (70.0, 29.0, 0.0),
    "Y1": (56.0, 30.0, 0.0),
    "C1": (53.0, 29.0, 90.0),
    "C2": (56.0, 34.0, 0.0),
    "C3": (80.0, 29.0, 180.0),
    "C4": (74.0, 18.0, 0.0),
    "C5": (79.0, 25.0, 0.0),
    "C6": (80.0, 31.5, 0.0),
    "C7": (61.0, 36.0, 0.0),
    "C8": (64.0, 21.0, 0.0),
    "C9": (88.0, 29.5, 0.0),
    "R5": (61.0, 33.0, 0.0),
    "R6": (58.0, 23.5, 0.0),
    "R7": (59.0, 27.0, 90.0),
    "J2": (83.0, 36.0, 90.0),
    "C14": (103.0, 33.0, 0.0),
    # Matrix diodes sit between the key rows, away from the LED apertures.
    "D1": (11.0, 23.0, 90.0),
    "D2": (24.0, 23.0, 90.0),
    "D3": (33.0, 23.0, 90.0),
    "D4": (46.0, 23.0, 90.0),
    # Reverse-mount emitters use the south-facing Cherry lamp window.  Their
    # pads clear the switch's plated and locating holes by more than 1 mm.
    "D5": (20.0, 8.0, 0.0),
    "D6": (35.05, 8.0, 0.0),
    "D7": (20.0, 38.05, 0.0),
    "D8": (35.05, 38.05, 0.0),
    "C10": (26.0, 11.0, 0.0),
    "C11": (45.05, 11.0, 0.0),
    "C12": (26.0, 35.0, 0.0),
    "C13": (45.05, 35.0, 0.0),
    # Encoder pull-ups and debounce are on the back, under the body edge.
    "R8": (91.0, 12.0, 0.0),
    "R9": (95.0, 12.0, 0.0),
    "R10": (88.0, 21.0, 90.0),
    "C15": (91.0, 15.0, 0.0),
    "C16": (95.0, 15.0, 0.0),
    "C17": (88.0, 25.0, 90.0),
}

FLIPPED_REFS: tuple[str, ...] = (
    # U2/R3/R4 stay on the front with J1 so the USB pair reaches the
    # flow-through ESD array and series resistors without immediate vias.
    "U1", "J2", "F1", "Y1",
    *(f"D{index}" for index in range(1, 9)),
    *(f"R{index}" for index in range(5, 11)),
    *(f"C{index}" for index in range(1, 18)),
)

HIDE_REFERENCES: tuple[str, ...] = (
    "SW1", "SW2", "SW3", "SW4", "SW5", "J1",
    *(f"D{index}" for index in range(1, 9)),
    *(f"R{index}" for index in range(1, 11)),
    *(f"C{index}" for index in range(1, 18)),
)

MOUNTING_HOLES = (
    ("H1", 9.5, 9.5),
    ("H2", 110.5, 9.5),
    ("H3", 9.5, BOARD_H - 9.5),
    ("H4", 110.5, BOARD_H - 9.5),
)

RETRO_PAD_RULE_PROFILE = PcbRuleProfile(
    profile_id="retro-pad-6mil-budget-fab-v1",
    geometry=FabricationGeometryProfile(
        profile_id="retro-pad-geometry-v1",
        basis="project_requirement",
        minimum_trace_width_mm=0.15,
        default_signal_trace_width_mm=0.25,
        default_power_trace_width_mm=0.30,
        routing_via_diameter_mm=0.60,
        routing_via_drill_mm=0.30,
        power_via_diameter_mm=0.80,
        power_via_drill_mm=0.40,
        board_thickness_mm=1.6,
        copper_layer_count=2,
        substrate_description="FR-4",
    ),
    fab_spacing=FabElectricalSpacingProfile(
        profile_id="retro-pad-spacing-v1",
        basis="project_requirement",
        minimum_copper_clearance_mm=0.15,
        # The reverse-mount LED package intentionally places its lands close
        # to the optical aperture; 0.20 mm remains above the 6 mil project
        # minimum without inheriting the unrelated legacy 0.50 mm edge rule.
        minimum_copper_to_edge_mm=0.20,
        minimum_hole_to_copper_mm=0.25,
    ),
    insulation=DEFAULT_PCB_RULE_PROFILE.insulation,
)


def retro_pad_checks_spec() -> DesignChecksSpec:
    return DesignChecksSpec(
        net_currents=(("/VBUS_RAW", 0.5), ("/VCC", 0.5), ("/GND", 0.5)),
        # The four source-backed parts do not yet have repository component
        # cards.  Do not synthesize project-specific pseudo-cards merely to
        # satisfy the checker; source intake and exact symbol/footprint
        # parity remain authoritative for this pilot, and card generation is
        # a reusable Phase-13 prompt/source-normalization deliverable.
        component_cards=(),
        tie_nets=(("GND", "/GND"), ("VCC", "/VCC")),
        allowed_unconnected_pins=(
            ("SW5", "MP"), ("J1", "A8"), ("J1", "B8"), ("D8", "2"),
            *(("U1", pin) for pin in (
                "8", "12", "22", "28", "29", "30", "31", "32",
                "36", "37", "38", "39", "40", "41",
            )),
        ),
        connector_edge_exempt_refs=("J1", "J2"),
    )


def _pixel_heart_graphics(
    source_file: Path,
    *,
    center: tuple[float, float] = (76.0, 31.0),
    width_mm: float = 12.0,
) -> tuple[str, ...]:
    """Raster the supplied 16-cell pixel heart as filled silk scanlines."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - dependency contract
        raise RuntimeError("Install the artwork extra: pip install 'pcbsmith[artwork]'.") from exc
    image = cv2.imread(str(source_file), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(source_file)
    cells = cv2.resize(image, (16, 16), interpolation=cv2.INTER_AREA) < 127
    cell = width_mm / 16.0
    center_x, center_y = center
    left = center_x - width_mm / 2.0
    top = center_y - width_mm / 2.0
    graphics: list[str] = []
    occurrence = 0
    for row in range(16):
        column = 0
        while column < 16:
            if not bool(cells[row, column]):
                column += 1
                continue
            run_start = column
            while column + 1 < 16 and bool(cells[row, column + 1]):
                column += 1
            run_end = column
            y = top + (row + 0.5) * cell
            x1 = left + (run_start + 0.5) * cell
            x2 = left + (run_end + 0.5) * cell
            graphics.append(silk_line(
                (x1, y), (x2, y), BOARD_SHEET_ORIGIN_MM,
                width=cell * 0.94, layer="F.SilkS", occurrence=occurrence,
            ))
            occurrence += 1
            column += 1
    return tuple(graphics)


def _unrouted_layout(
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
            raise BoardGenerationError(f"Retro-Pad netlist is missing {reference}.")
        placements.append((by_ref[reference], x))
        part_y.append((reference, y))
        if rotation:
            rotations.append((reference, rotation))
    for reference, x, y in MOUNTING_HOLES:
        hole = BoardComponent(
            reference=reference,
            value="M2.5 NPTH",
            footprint="MountingHole:MountingHole_2.7mm_M2.5",
            uuid_path=stable_kicad_uuid("board-component-path", "retro-pad-hole", reference),
        )
        placements.append((hole, x))
        part_y.append((reference, y))
    graphics = (
        *_pixel_heart_graphics(silkscreen_file),
        silk_text("USB-C", (50.0, 8.8), BOARD_SHEET_ORIGIN_MM, size=0.8),
    )
    led_cutouts = tuple(
        BoardCutoutPolygon(points=(
            (x - 1.00, y - 1.00), (x + 1.00, y - 1.00),
            (x + 1.00, y + 1.00), (x - 1.00, y + 1.00),
        ))
        for x, y in ((20.0, 8.0), (35.05, 8.0), (20.0, 38.05), (35.05, 38.05))
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
        cutouts=led_cutouts,
        graphics=graphics,
        part_flip=FLIPPED_REFS,
        hide_references=HIDE_REFERENCES,
    )


def compute_retro_pad_board_layout(
    netlist: BoardNetlist,
    *,
    outline_file: Path,
    silkscreen_file: Path,
) -> BoardLayout:
    base = _unrouted_layout(
        netlist, outline_file=outline_file, silkscreen_file=silkscreen_file,
    )
    routable = {
        net.name for net in netlist.nets if len(set(net.nodes)) >= 2
    }
    priority_widths = {
        # The USB4105 A/B contact breakout is 0.5 mm pitch.  The brief's
        # exact 0.15 mm minimum trace is required here; a live 0.10 mm-grid
        # probe has no legal D- tree, while 0.05 mm lands both 0.3 mm
        # contacts without reducing clearance.
        "/USB_DM_CONN": 0.15, "/USB_DP_CONN": 0.15,
        "/USB_DM_PROTECTED": 0.15, "/USB_DP_PROTECTED": 0.15,
        "/USB_DM_MCU": 0.15, "/USB_DP_MCU": 0.15,
        # Raw VBUS claims its connector-to-fuse/MCU-sense spine before the
        # distributed VCC tree occupies the neck corridor.
        "/VBUS_RAW": 0.25,
        "/CC1": 0.15, "/CC2": 0.15,
    }
    priority = tuple(priority_widths)
    first = route_board(
        base,
        netlist,
        fine_pitch_nets=priority_widths,
        fine_grid_mm=0.05,
        profile=RETRO_PAD_RULE_PROFILE,
        skip_nets=routable - set(priority),
        max_restarts=4,
    )
    if first.failed:
        raise BoardGenerationError(
            "priority routing could not route: " + ", ".join(first.failed)
        )

    # Reserve the distributed supply tree immediately after the fine-pitch
    # USB breakout.  Leaving it until after the matrix and encoder can strand
    # the four LED bypass branches behind their board apertures.
    power = route_board(
        first.layout,
        netlist,
        net_widths={"/VCC": 0.30},
        default_width_mm=0.30,
        net_order=("/VCC",),
        skip_nets=routable - {"/VCC"},
        max_restarts=4,
        profile=RETRO_PAD_RULE_PROFILE,
    )
    if power.failed:
        raise BoardGenerationError(
            "VCC routing could not route: " + ", ".join(power.failed)
        )

    matrix_nets = ("/ROW0", "/ROW1", "/COL0", "/COL1")
    second = route_board(
        power.layout,
        netlist,
        default_width_mm=SIGNAL_W,
        net_order=matrix_nets,
        skip_nets=routable - set(matrix_nets),
        max_restarts=4,
        profile=RETRO_PAD_RULE_PROFILE,
    )
    if second.failed:
        raise BoardGenerationError(
            "matrix routing could not route: " + ", ".join(second.failed)
        )

    encoder_nets = ("/ENC_A", "/ENC_B", "/ENC_SW")
    encoder = route_board(
        second.layout,
        netlist,
        default_width_mm=SIGNAL_W,
        net_order=encoder_nets,
        skip_nets=routable - set(encoder_nets),
        max_restarts=4,
        profile=RETRO_PAD_RULE_PROFILE,
    )
    if encoder.failed:
        raise BoardGenerationError(
            "encoder routing could not route: " + ", ".join(encoder.failed)
        )

    frozen = {
        *priority, *matrix_nets, *encoder_nets,
        "/VCC", "/GND",
    }
    working = encoder.layout

    def route_domain(label: str, names: tuple[str, ...]) -> None:
        nonlocal working
        active = tuple(name for name in names if name in routable and name not in frozen)
        if not active:
            return
        result = route_board(
            working,
            netlist,
            default_width_mm=SIGNAL_W,
            skip_nets=routable - set(active),
            net_order=active,
            max_restarts=4,
            profile=RETRO_PAD_RULE_PROFILE,
        )
        if result.failed:
            raise BoardGenerationError(
                f"{label} routing could not route: " + ", ".join(result.failed)
            )
        working = result.layout
        frozen.update(active)

    route_domain(
        "ISP",
        ("/SCK", "/MOSI", "/MISO", "/RESET"),
    )
    route_domain(
        "clock-support",
        ("/XTAL1", "/XTAL2", "/UCAP", "/AREF", "/HWB"),
    )
    route_domain(
        "LED chain",
        ("/LED_DATA_MCU", "/LED_DATA_1", "/LED_LINK_1", "/LED_LINK_2",
         "/LED_LINK_3"),
    )
    route_domain(
        "key diode links",
        ("/KEY1_D", "/KEY2_D", "/KEY3_D", "/KEY4_D"),
    )
    remaining = tuple(sorted(routable - frozen))
    route_domain("remaining signals", remaining)
    ground = route_board(
        working,
        netlist,
        net_widths={"/GND": 0.30},
        default_width_mm=0.30,
        net_order=("/GND",),
        skip_nets=routable - {"/GND"},
        max_restarts=4,
        profile=RETRO_PAD_RULE_PROFILE,
    )
    if ground.failed:
        raise BoardGenerationError(
            "GND routing could not route: " + ", ".join(ground.failed)
        )
    return _repair_led_aperture_escapes(ground.layout)


def route_retro_pad_placement_layout(
    base: BoardLayout,
    netlist: BoardNetlist,
    *,
    maximum_expansions: int = 500_000,
    maximum_passes: int = 100,
    maximum_expansions_per_net: int = 100_000,
    domain_observer: Callable[[str, BoardLayout], None] | None = None,
    checkpoint_observer: (
        Callable[[str, BoardLayout, frozenset[str]], None] | None
    ) = None,
    completed_net_names: Collection[str] = (),
    route_ground_tracks: bool = True,
    route_ground_before_power: bool = False,
    route_ground_before_matrix: bool = False,
    route_clock_before_power: bool = False,
    route_led_before_power: bool = False,
    route_power_before_matrix: bool = False,
) -> BoardLayout:
    """Route a Retro-Pad-family placement without board-specific hardcoding."""

    routable = {net.name for net in netlist.nets if len(set(net.nodes)) >= 2}
    fine_widths: dict[str, float] = {
        name: width
        for name, width in {
            "/USB_DM_CONN": 0.15,
            "/USB_DP_CONN": 0.15,
            "/USB_DM_PROTECTED": 0.15,
            "/USB_DP_PROTECTED": 0.15,
            "/CC1": 0.15,
            "/CC2": 0.15,
        }.items()
        if name in routable
    }
    connector_data_widths: dict[str, float] = {
        name: fine_widths[name]
        for name in ("/USB_DM_CONN", "/USB_DP_CONN")
        if name in fine_widths
    }
    usb_support_widths: dict[str, float] = {
        name: fine_widths[name]
        for name in (
            "/USB_DM_PROTECTED",
            "/USB_DP_PROTECTED",
            "/CC1",
            "/CC2",
        )
        if name in fine_widths
    }
    working = base
    unknown_completed = set(completed_net_names) - routable
    if unknown_completed:
        raise BoardGenerationError(
            "completed routing checkpoint names unknown nets: "
            + ", ".join(sorted(unknown_completed))
        )
    frozen: set[str] = set(completed_net_names)
    used_expansions = 0
    used_passes = 0

    def route_domain(
        label: str,
        names: tuple[str, ...],
        *,
        widths: dict[str, float] | None = None,
        default_width: float = SIGNAL_W,
        grid_mm: float = 0.2,
        fine_pitch: bool = False,
        fine_grid_mm: float = 0.1,
    ) -> None:
        nonlocal working, used_expansions, used_passes
        active = tuple(name for name in names if name in routable and name not in frozen)
        if not active:
            return
        remaining_expansions = maximum_expansions - used_expansions
        remaining_passes = maximum_passes - used_passes
        if remaining_expansions <= 0 or remaining_passes <= 0:
            raise BoardGenerationError(
                f"{label} routing did not start: shared routing budget exhausted"
            )
        result = route_board(
            working,
            netlist,
            fine_pitch_nets=(widths or {}) if fine_pitch else {},
            fine_grid_mm=fine_grid_mm,
            net_widths=widths or {},
            default_width_mm=default_width,
            grid_mm=grid_mm,
            net_order=active,
            skip_nets=routable - set(active),
            max_restarts=4,
            max_passes=remaining_passes,
            max_expansions=remaining_expansions,
            max_expansions_per_net=min(
                maximum_expansions_per_net,
                remaining_expansions,
            ),
            profile=RETRO_PAD_RULE_PROFILE,
        )
        used_expansions += sum(
            item.expansion_count for item in result.run_result.passes
        )
        used_passes += len(result.run_result.passes)
        if result.failed:
            attempted = tuple(
                item
                for route_pass in result.run_result.passes
                for item in route_pass.net_telemetry
                if item.net_name in result.failed
            )
            work = ", ".join(
                f"{item.net_name}={item.expansion_count} expansions/"
                f"{item.failure_reason.value if item.failure_reason else 'unknown'}"
                for item in attempted
            )
            raise BoardGenerationError(
                f"{label} routing could not route: "
                + ", ".join(result.failed)
                + (f" ({work})" if work else "")
            )
        working = result.layout
        frozen.update(active)
        if domain_observer is not None:
            domain_observer(label, working)
        if checkpoint_observer is not None:
            checkpoint_observer(label, working, frozenset(frozen))

    led_names = tuple(
        name
        for name in (
            "/LED_DATA_MCU",
            "/LED_DATA_1",
            *(f"/LED_LINK_{index}" for index in range(1, 1 + len(routable))),
        )
        if name in routable
    )

    def route_led_chain() -> None:
        for led_name in led_names:
            route_domain(
                f"LED {led_name.removeprefix('/')}",
                (led_name,),
                fine_pitch=not route_led_before_power,
                fine_grid_mm=0.1,
            )

    clock_support = ("/XTAL1", "/XTAL2", "/UCAP", "/AREF", "/HWB")
    clock_widths = {name: SIGNAL_W for name in clock_support}

    route_domain(
        "fine-pitch connector data",
        tuple(connector_data_widths),
        widths=connector_data_widths,
        fine_pitch=True,
        fine_grid_mm=0.05,
    )
    route_domain(
        "USB protection and CC",
        tuple(usb_support_widths),
        widths=usb_support_widths,
        fine_pitch=True,
        fine_grid_mm=0.1,
    )
    route_domain(
        "raw VBUS",
        ("/VBUS_RAW",),
        widths={"/VBUS_RAW": 0.25},
        default_width=0.25,
        # VBUS joins the duplicated Type-C power pads, fuse, and MCU sense
        # input.  Treating that entire multi-terminal tree as fine pitch made
        # the search needlessly enormous and could exhaust millions of
        # expansions even though the same legal corridor is found on the
        # ordinary grid.  Reserve the fine-pitch connector escapes first, then
        # route this wider tree before the longer USB-to-MCU continuations can
        # seal its connector corridor.
        grid_mm=0.4,
    )
    route_domain(
        "USB-to-MCU",
        ("/USB_DM_MCU", "/USB_DP_MCU"),
        widths={"/USB_DM_MCU": 0.15, "/USB_DP_MCU": 0.15},
        grid_mm=0.25,
    )
    clock_routed_before_early_power = False
    if (
        route_clock_before_power
        and (route_power_before_matrix or route_ground_before_matrix)
    ):
        route_domain(
            "clock-support",
            clock_support,
            widths=clock_widths,
            fine_pitch=True,
            fine_grid_mm=0.1,
        )
        clock_routed_before_early_power = True
    if route_ground_tracks and route_ground_before_matrix:
        route_domain(
            "ground",
            ("/GND",),
            widths={"/GND": 0.30},
            default_width=0.30,
        )
    if route_power_before_matrix:
        route_domain(
            "power",
            ("/VCC",),
            widths={"/VCC": 0.30},
            default_width=0.30,
        )
    route_domain(
        "matrix",
        tuple(
            sorted(
                (name for name in routable if name.startswith("/ROW")),
                reverse=True,
            )
            + sorted(name for name in routable if name.startswith("/COL"))
        ),
    )
    if route_led_before_power:
        route_led_chain()
    if (
        route_ground_tracks
        and route_ground_before_power
        and not route_ground_before_matrix
    ):
        route_domain(
            "ground",
            ("/GND",),
            widths={"/GND": 0.30},
            default_width=0.30,
        )
    if route_clock_before_power and not clock_routed_before_early_power:
        route_domain(
            "clock-support",
            clock_support,
            widths=clock_widths,
            fine_pitch=True,
            fine_grid_mm=0.1,
        )
    if not route_power_before_matrix:
        route_domain(
            "power",
            ("/VCC",),
            widths={"/VCC": 0.30},
            default_width=0.30,
        )
    route_domain("encoder", ("/ENC_A", "/ENC_B", "/ENC_SW"))
    if not route_led_before_power:
        # The LED chain is lower priority than the power backbone and encoder,
        # but must reserve its cross-board corridors before reset and ISP.
        route_led_chain()
    route_domain(
        "reset",
        ("/RESET",),
        widths={"/RESET": SIGNAL_W},
        # Only the MCU endpoint is fine-pitch; the reset button is a distant
        # through-hole endpoint.  Searching the full run on the 0.1 mm grid
        # needlessly multiplies the state space and can exhaust the shared
        # budget after the power and encoder networks are committed.
        grid_mm=0.2,
    )
    # The local fanout reserves all three MCU-pad escapes.  From there, reserve
    # SCK's cross-board corridor first, then MISO, and leave MOSI last.
    for isp_name in ("/SCK", "/MISO", "/MOSI"):
        route_domain(
            f"ISP {isp_name.removeprefix('/')}",
            (isp_name,),
            widths={isp_name: SIGNAL_W},
            # Only the MCU endpoint is fine-pitch; the long run to the 2.54 mm
            # ISP header should use the ordinary grid.  Endpoint escape
            # geometry still honors the physical pad shape.
            grid_mm=0.2,
            fine_pitch=True,
            fine_grid_mm=0.1,
        )
    if not route_clock_before_power:
        route_domain(
            "clock-support",
            clock_support,
            widths=clock_widths,
            fine_pitch=True,
            fine_grid_mm=0.1,
        )
    for key_name in sorted(
        (name for name in routable if name.startswith("/KEY")),
        key=lambda name: int(name.removeprefix("/KEY").removesuffix("_D")),
    ):
        route_domain(
            f"key {key_name.removeprefix('/')}",
            (key_name,),
        )
    route_domain(
        "remaining signals",
        tuple(sorted(routable - frozen - {"/GND"})),
    )
    if (
        route_ground_tracks
        and not route_ground_before_power
        and not route_ground_before_matrix
    ):
        route_domain(
            "ground",
            ("/GND",),
            widths={"/GND": 0.30},
            default_width=0.30,
        )
    return working


def _repair_led_aperture_escapes(layout: BoardLayout) -> BoardLayout:
    """Replace four router diagonals that cross reverse-LED light apertures.

    The A* obstacle grid keeps ordinary routes away from the Edge.Cuts
    openings, but its short pad/via escape segments are intentionally less
    restrictive.  On this board four of those final escapes span an optical
    aperture.  Keep the routed topology and insert compact, clearance-safe
    doglegs around the affected openings.
    """
    repairs = {
        ("/LED_DATA_1", "B.Cu", 17.8, 8.6, 20.0, 6.4): (
            (17.8, 8.6), (18.5, 9.5), (21.5, 9.5),
            (21.5, 6.4), (20.0, 6.4),
        ),
        ("/LED_LINK_2", "F.Cu", 26.0, 19.2, 37.4, 7.8): (
            (26.0, 19.2), (34.0, 11.2), (36.5, 11.2), (37.4, 7.8),
        ),
        ("/LED_LINK_2", "B.Cu", 17.8, 38.6, 22.4, 34.0): (
            (17.8, 38.6), (18.45, 38.0), (18.45, 36.6), (22.4, 34.0),
        ),
        ("/GND", "B.Cu", 18.2, 39.6, 22.8, 35.0): (
            # The filled B.Cu ground plane already connects both sides of
            # this redundant diagonal.  Removing it avoids threading a
            # second trace through the LED's crowded four-pad breakout.
        ),
    }
    repaired: list[TrackSegment] = []
    applied: set[tuple[str, str, float, float, float, float]] = set()
    for segment in layout.segments:
        key = next(
            (
                candidate
                for candidate in repairs
                if _segment_matches_repair(segment, candidate)
            ),
            None,
        )
        if key is None:
            repaired.append(segment)
            continue
        points = repairs[key]
        applied.add(key)
        if not points:
            continue
        if not _points_close((segment.x1, segment.y1), points[0]):
            points = tuple(reversed(points))
        repaired.extend(
            TrackSegment(
                x1=start[0], y1=start[1], x2=end[0], y2=end[1],
                layer=segment.layer, net_name=segment.net_name,
                width_mm=segment.width_mm,
            )
            for start, end in pairwise(points)
        )
    missing = repairs.keys() - applied
    if missing:
        raise BoardGenerationError(
            "expected LED aperture escape segments were not found: "
            + ", ".join(sorted(key[0] for key in missing))
        )
    return replace(layout, segments=tuple(repaired))


def _points_close(
    first: tuple[float, float], second: tuple[float, float], *, tolerance: float = 1e-6,
) -> bool:
    return (
        abs(first[0] - second[0]) <= tolerance
        and abs(first[1] - second[1]) <= tolerance
    )


def _segment_matches_repair(
    segment: TrackSegment,
    repair: tuple[str, str, float, float, float, float],
) -> bool:
    net_name, layer, x1, y1, x2, y2 = repair
    if segment.net_name != net_name or segment.layer != layer:
        return False
    start = (segment.x1, segment.y1)
    end = (segment.x2, segment.y2)
    repair_start = (x1, y1)
    repair_end = (x2, y2)
    return (
        _points_close(start, repair_start) and _points_close(end, repair_end)
    ) or (
        _points_close(start, repair_end) and _points_close(end, repair_start)
    )


def generate_retro_pad_board(
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
    layout = compute_retro_pad_board_layout(
        netlist, outline_file=outline_file, silkscreen_file=silkscreen_file,
    )
    board_file.write_text(render_retro_pad_board(netlist, layout), encoding="utf-8")
    return netlist, layout


def generate_retro_pad_placement_board(
    *,
    schematic_file: Path,
    board_file: Path,
    outline_file: Path,
    silkscreen_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    """Write the exact unrouted placement candidate used by the routed stage."""

    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = _unrouted_layout(
        netlist,
        outline_file=outline_file,
        silkscreen_file=silkscreen_file,
    )
    board_file.write_text(render_retro_pad_board(netlist, layout), encoding="utf-8")
    return netlist, layout


def render_retro_pad_board(
    netlist: BoardNetlist,
    layout: BoardLayout,
    *,
    switch_count: int = 4,
    led_count: int = 4,
) -> str:
    """Render board-level LED apertures and suppress duplicate footprint cuts."""
    rendered = render_board_from_layout(
        netlist, layout, profile=RETRO_PAD_RULE_PROFILE,
    )
    rendered = _move_all_footprint_graphics(
        rendered,
        footprint="LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount",
        old_layer="Edge.Cuts",
        new_layer="Dwgs.User",
        expected_count=led_count,
    )
    # Preserve the switch and bulk-capacitor package outlines as mechanical
    # drawings without printing portions that the irregular board edge or
    # the encoder mounting tabs would clip in fabrication.
    rendered = _move_all_footprint_graphics(
        rendered,
        footprint="Button_Switch_Keyboard:SW_Cherry_MX_1.00u_PCB",
        old_layer="F.SilkS",
        new_layer="Dwgs.User",
        expected_count=switch_count,
    )
    rendered = _move_all_footprint_graphics(
        rendered,
        footprint="Capacitor_SMD:CP_Elec_6.3x5.8",
        old_layer="B.SilkS",
        new_layer="B.Fab",
        expected_count=1,
    )
    rendered = _replace_all_footprint_model_paths(
        rendered,
        footprint="Button_Switch_Keyboard:SW_Cherry_MX_1.00u_PCB",
        old_path=(
            "${KICAD10_3DMODEL_DIR}/Button_Switch_Keyboard.3dshapes/"
            "SW_Cherry_MX_1.00u_PCB.step"
        ),
        new_path="${KIPRJMOD}/models/retro-pad-cherry-mx-proxy.wrl",
    )
    return _replace_all_footprint_model_paths(
        rendered,
        footprint=(
            "Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm"
        ),
        old_path=(
            "${KICAD10_3DMODEL_DIR}/Rotary_Encoder.3dshapes/"
            "RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm.step"
        ),
        new_path="${KIPRJMOD}/models/retro-pad-ec11-proxy.wrl",
    )


def _move_all_footprint_graphics(
    board_text: str,
    *,
    footprint: str,
    old_layer: str,
    new_layer: str,
    expected_count: int,
) -> str:
    """Move matching graphics within every instance of one embedded footprint."""
    marker = f'  (footprint "{footprint}"'
    cursor = 0
    count = 0
    while (start := board_text.find(marker, cursor)) >= 0:
        depth = 0
        quoted = False
        escaped = False
        end = -1
        for index in range(start, len(board_text)):
            character = board_text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
                continue
            if character == '"':
                quoted = True
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end < 0:
            raise BoardGenerationError(f"unterminated footprint {footprint}")
        block = board_text[start:end]
        block = block.replace(f'(layer "{old_layer}")', f'(layer "{new_layer}")')
        board_text = board_text[:start] + block + board_text[end:]
        cursor = start + len(block)
        count += 1
    if count != expected_count:
        raise BoardGenerationError(
            f"expected {expected_count} instances of {footprint}, found {count}"
        )
    return board_text


def _replace_all_footprint_model_paths(
    board_text: str,
    *,
    footprint: str,
    old_path: str,
    new_path: str,
) -> str:
    """Replace a missing library model only inside matching footprints."""
    marker = f'  (footprint "{footprint}"'
    cursor = 0
    count = 0
    while (start := board_text.find(marker, cursor)) >= 0:
        depth = 0
        quoted = False
        escaped = False
        end = -1
        for index in range(start, len(board_text)):
            character = board_text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
                continue
            if character == '"':
                quoted = True
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end < 0:
            raise BoardGenerationError(f"unterminated footprint {footprint}")
        block = board_text[start:end]
        if old_path not in block:
            raise BoardGenerationError(
                f"footprint {footprint} is missing expected model {old_path}"
            )
        block = block.replace(old_path, new_path)
        board_text = board_text[:start] + block + board_text[end:]
        cursor = start + len(block)
        count += 1
    if count < 1:
        raise BoardGenerationError(f"rendered board is missing {footprint}")
    return board_text
