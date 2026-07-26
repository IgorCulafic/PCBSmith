"""Exact placement and deterministic routing for AeroSense-2F R001."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from pcbsmith.kicad import board as board_module
from pcbsmith.kicad.astar_router import (
    route_board,
    route_net_pad_subset,
    with_route,
)
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
from pcbsmith.kicad.library import PRIVATE_ASSET_ROOT_ENV, load_footprint
from pcbsmith.kicad.shaped_board import silk_text
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    FabElectricalSpacingProfile,
    FabricationGeometryProfile,
    PcbRuleProfile,
)

BOARD_W = 70.0
BOARD_H = 50.0
SIGNAL_W = 0.20
OLED_FOOTPRINT = "PCBSmith_AeroSense:Adafruit_4440_OLED_Module"
SHT45_FOOTPRINT = "PCBSmith_AeroSense:Sensirion_SHT45_NoCentralPad"
TUSB320_FOOTPRINT = "PCBSmith_AeroSense:TUSB320_X2QFN12"
VBUS_ESD_FOOTPRINT = "PCBSmith_AeroSense:TPD1E10B06_DPY2"

AEROSENSE_RULE_PROFILE = PcbRuleProfile(
    profile_id="aerosense-2f-budget-fab-v1",
    geometry=FabricationGeometryProfile(
        profile_id="aerosense-2f-geometry-v1",
        basis="project_requirement",
        minimum_trace_width_mm=0.153,
        default_signal_trace_width_mm=SIGNAL_W,
        default_power_trace_width_mm=0.80,
        routing_via_diameter_mm=0.60,
        routing_via_drill_mm=0.30,
        power_via_diameter_mm=0.80,
        power_via_drill_mm=0.40,
        board_thickness_mm=1.6,
        copper_layer_count=2,
        substrate_description="FR-4, 1 oz copper each side",
    ),
    fab_spacing=FabElectricalSpacingProfile(
        profile_id="aerosense-2f-spacing-v1",
        basis="project_requirement",
        minimum_copper_clearance_mm=0.153,
        minimum_copper_to_edge_mm=0.30,
        minimum_hole_to_copper_mm=0.25,
    ),
    insulation=DEFAULT_PCB_RULE_PROFILE.insulation,
)

# Exact component anchors in board coordinates. Back-side parts retain the
# same board-space anchors and are mirrored by BoardLayout.part_flip.
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "J1": (3.10, 25.00, 90.0),
    "U7": (10.20, 25.00, 0.0),
    "U9": (8.20, 18.50, 0.0),
    "U10": (7.80, 31.00, 0.0),
    "U3": (10.50, 16.00, 0.0),
    "U4": (11.00, 33.00, 0.0),
    "R1": (41.50, 20.50, 90.0),
    "R2": (36.00, 20.50, 90.0),
    "R6": (13.50, 30.00, 0.0),
    "R7": (17.00, 30.00, 0.0),
    "R8": (11.00, 36.00, 0.0),
    "C1": (6.00, 16.00, 0.0),
    "C2": (11.00, 13.00, 0.0),
    "C3": (14.00, 16.00, 90.0),
    "C17": (14.00, 34.00, 0.0),
    "DS1": (33.50, 10.50, 0.0),
    "J6": (34.00, 11.00, 0.0),
    "U1": (31.00, 27.00, 0.0),
    "U2": (21.50, 27.50, 90.0),
    "Y1": (35.00, 34.00, 0.0),
    "R3": (30.50, 33.00, 180.0),
    "R4": (20.00, 22.00, 0.0),
    "R5": (38.00, 28.00, 0.0),
    "R34": (21.00, 20.50, 0.0),
    "SW4": (39.50, 25.00, 0.0),
    "SW5": (39.50, 30.00, 0.0),
    "FB1": (37.00, 24.50, 0.0),
    "C4": (25.50, 24.50, 90.0),
    "C5": (25.50, 27.50, 90.0),
    "C6": (25.50, 30.50, 90.0),
    "C7": (37.50, 26.50, 90.0),
    "C8": (36.00, 23.00, 90.0),
    "C9": (36.00, 30.00, 90.0),
    "C10": (28.00, 29.50, 0.0),
    "C11": (31.00, 29.50, 0.0),
    "C12": (34.00, 29.50, 0.0),
    "C13": (37.00, 29.50, 0.0),
    "C14": (22.50, 27.00, 0.0),
    "C15": (37.00, 37.50, 0.0),
    "C16": (34.00, 37.50, 0.0),
    "C28": (47.00, 19.00, 90.0),
    "J4": (58.00, 11.00, 90.0),
    "J5": (58.00, 24.00, 90.0),
    "U5": (46.00, 26.00, 0.0),
    "U6": (52.00, 26.00, 0.0),
    "Q1": (47.00, 30.00, 0.0),
    "Q2": (53.00, 30.00, 0.0),
    "R9": (42.50, 25.00, 90.0),
    "R10": (53.00, 26.00, 90.0),
    "R11": (43.00, 28.00, 0.0),
    "R12": (57.00, 30.00, 0.0),
    "R13": (43.00, 31.50, 0.0),
    "R14": (55.00, 33.00, 0.0),
    "R15": (64.00, 8.00, 90.0),
    "R16": (64.00, 21.00, 90.0),
    "R17": (64.00, 13.00, 90.0),
    "R18": (64.00, 26.00, 90.0),
    "R19": (47.00, 28.00, 0.0),
    "R20": (53.00, 30.00, 0.0),
    "R21": (47.00, 31.50, 0.0),
    "R22": (51.00, 33.00, 0.0),
    "C18": (47.00, 23.50, 0.0),
    "C19": (53.00, 23.50, 0.0),
    "C20": (65.00, 8.00, 0.0),
    "C21": (64.00, 18.50, 0.0),
    "C22": (65.00, 11.50, 0.0),
    "C23": (64.00, 23.50, 0.0),
    "C29": (67.00, 14.00, 90.0),
    "C30": (67.00, 27.00, 90.0),
    "U8": (14.00, 43.00, 0.0),
    "C24": (17.00, 43.00, 90.0),
    "J3": (28.00, 40.60, 0.0),
    "U11": (18.00, 32.50, 90.0),
    "R29": (22.00, 41.00, 0.0),
    "R30": (27.00, 34.50, 90.0),
    "R31": (29.50, 34.50, 90.0),
    "R32": (32.00, 34.50, 90.0),
    "R33": (34.80, 41.00, 0.0),
    "C25": (22.00, 45.00, 0.0),
    "C26": (34.80, 45.00, 90.0),
    "SW1": (40.00, 35.00, 0.0),
    "SW2": (50.00, 35.00, 0.0),
    "SW3": (60.00, 35.00, 0.0),
    "R23": (40.00, 38.00, 0.0),
    "R24": (50.00, 38.00, 0.0),
    "R25": (60.00, 38.00, 0.0),
    "D1": (39.00, 43.00, 0.0),
    "D2": (49.00, 43.00, 0.0),
    "D3": (59.00, 43.00, 0.0),
    "R26": (39.00, 45.50, 0.0),
    "R27": (49.00, 45.50, 0.0),
    "R28": (59.00, 45.50, 0.0),
    "C27": (43.50, 17.00, 0.0),
    "TP1": (8.00, 5.00, 0.0),
    "TP2": (14.00, 5.00, 0.0),
    "TP3": (20.00, 5.00, 0.0),
    "TP4": (26.00, 5.00, 0.0),
    "TP5": (44.00, 5.00, 0.0),
    "TP6": (59.50, 14.00, 0.0),
    "TP7": (61.00, 31.00, 0.0),
}

BACK_PARTS = frozenset(
    {
        "J6",
        "Y1",
        "C6",
        "C10",
        "C11",
        "C12",
        "C13",
        "C14",
        "C15",
        "C16",
        "C27",
        "C28",
        "C29",
        "C30",
        "FB1",
        "R1",
        "R2",
        "R3",
        "R5",
        "R9",
        "R10",
        "R11",
        "R12",
        "R13",
        "R14",
        "R15",
        "R16",
        "R17",
        "R18",
        "R19",
        "R20",
        "R21",
        "R22",
        "R23",
        "R24",
        "R25",
        "R29",
        "R30",
        "R31",
        "R32",
        "R33",
        "R34",
        "C25",
        "C26",
        "TP1",
        "TP2",
        "TP3",
        "TP4",
        "TP5",
        "TP6",
        "TP7",
    }
)

HIDDEN_REFERENCES = (
    "J1",
    "J3",
    "DS1",
    "U2",
    "U3",
    "U5",
    "U6",
    "U9",
    "U10",
    "U11",
    "Y1",
    "Q1",
    "Q2",
    "R4",
    "R6",
    "R7",
    "R8",
    "R3",
    "R11",
    "C3",
    "C4",
    "C5",
    "C6",
    "C7",
    "C8",
    "C9",
    "C10",
    "C11",
    "C12",
    "C13",
    "C15",
    "C16",
)

MOUNTING_HOLES = (
    ("H1", 3.0, 3.0),
    ("H2", 67.0, 3.0),
    ("H3", 3.0, 47.0),
    ("H4", 67.0, 47.0),
)


def _box_model(
    width_mm: float,
    depth_mm: float,
    height_mm: float,
    color: str,
) -> str:
    scale = 1.0 / 2.54
    return f"""#VRML V2.0 utf8
Transform {{
  translation 0 0 {height_mm * scale / 2:.6f}
  children [ Shape {{
    appearance Appearance {{ material Material {{ diffuseColor {color} }} }}
    geometry Box {{ size {width_mm * scale:.6f} {depth_mm * scale:.6f} {height_mm * scale:.6f} }}
  }} ]
}}
"""


def _oled_footprint() -> str:
    pads = "\n".join(
        f"""  (pad "{index}" thru_hole {"rect" if index == 1 else "circle"}
    (at {x:.2f} 7.96) (size 1.78 1.78) (drill 1.0) (layers "*.Cu" "*.Mask"))"""
        for index, x in enumerate((-6.35, -3.81, -1.27, 1.27, 3.81, 6.35), start=1)
    )
    return f"""(footprint "Adafruit_4440_OLED_Module"
  (version 20241229)
  (generator "PCBSmith")
  (layer "F.Cu")
  (attr through_hole)
  (property "Reference" "DS1" (at 0 -11 0) (layer "F.SilkS"))
  (property "Value" "Adafruit 4440 OLED" (at 0 11 0) (layer "F.Fab"))
  (fp_rect (start -17.5 -10) (end 17.5 10)
    (stroke (width 0.25) (type default)) (fill none) (layer "F.SilkS"))
  (fp_rect (start -17.75 -10.25) (end 17.75 10.25)
    (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
  (fp_rect (start -17.5 -10) (end 17.5 10)
    (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))
  (fp_rect (start -13.5 -5.5) (end 13.5 5.5)
    (stroke (width 0.2) (type default)) (fill none) (layer "F.Fab"))
{pads}
  (model "${{KIPRJMOD}}/models/adafruit-4440-oled-proxy.wrl"
    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
)
"""


def register_aerosense_assets(project_dir: Path) -> None:
    library = project_dir / "PCBSmith_AeroSense.pretty"
    library.mkdir(parents=True, exist_ok=True)
    (project_dir / "fp-lib-table").write_text(
        """(fp_lib_table
  (version 7)
  (lib (name "PCBSmith_AeroSense")(type "KiCad")
    (uri "${KIPRJMOD}/PCBSmith_AeroSense.pretty")(options "")(descr ""))
)
""",
        encoding="utf-8",
    )
    model_dir = project_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "adafruit-4440-oled-proxy.wrl").write_text(
        _box_model(35.0, 20.0, 4.0, "0.05 0.08 0.10"),
        encoding="ascii",
    )
    (model_dir / "sensirion-sht45-proxy.wrl").write_text(
        _box_model(1.5, 1.5, 0.5, "0.12 0.12 0.12"),
        encoding="ascii",
    )
    (model_dir / "tusb320-x2qfn12-proxy.wrl").write_text(
        _box_model(1.6, 1.6, 0.4, "0.10 0.10 0.10"),
        encoding="ascii",
    )
    (model_dir / "tpd1e10b06-dpy2-proxy.wrl").write_text(
        _box_model(0.6, 1.0, 0.35, "0.10 0.10 0.10"),
        encoding="ascii",
    )
    oled_source = library / "Adafruit_4440_OLED_Module.kicad_mod"
    oled_source.write_text(_oled_footprint(), encoding="utf-8")

    upstream = load_footprint(
        "Sensor_Humidity:Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_NoCentralPad"
    )
    sht_text = upstream.source_file.read_text(encoding="utf-8").replace(
        '(footprint "Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_NoCentralPad"',
        '(footprint "Sensirion_SHT45_NoCentralPad"',
        1,
    )
    upstream_model_start = sht_text.rfind("\n\t(model ")
    root_end = sht_text.rfind("\n)")
    if upstream_model_start >= 0 and upstream_model_start < root_end:
        sht_text = sht_text[:upstream_model_start] + sht_text[root_end:]
    sht_text = (
        sht_text.rstrip()[:-1]
        + """
  (model "${KIPRJMOD}/models/sensirion-sht45-proxy.wrl"
    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
)
"""
    )
    sht_source = library / "Sensirion_SHT45_NoCentralPad.kicad_mod"
    sht_source.write_text(sht_text, encoding="utf-8")

    aliases = (
        (
            "Package_DFN_QFN:Texas_X2QFN-12_1.6x1.6mm_P0.4mm",
            "TUSB320_X2QFN12",
            "tusb320-x2qfn12-proxy.wrl",
        ),
        (
            "Package_SON:Texas_DPY0002A_0.6x1mm_P0.65mm",
            "TPD1E10B06_DPY2",
            "tpd1e10b06-dpy2-proxy.wrl",
        ),
    )
    alias_sources: list[tuple[str, Path]] = []
    for upstream_id, alias_name, model_name in aliases:
        imported = load_footprint(upstream_id)
        text = imported.source_file.read_text(encoding="utf-8")
        upstream_name = upstream_id.split(":", 1)[1]
        text = text.replace(
            f'(footprint "{upstream_name}"',
            f'(footprint "{alias_name}"',
            1,
        )
        model_start = text.rfind("\n\t(model ")
        root_end = text.rfind("\n)")
        if model_start >= 0 and model_start < root_end:
            text = text[:model_start] + text[root_end:]
        text = (
            text.rstrip()[:-1]
            + f"""
  (model "${{KIPRJMOD}}/models/{model_name}"
    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
)
"""
        )
        source = library / f"{alias_name}.kicad_mod"
        source.write_text(text, encoding="utf-8")
        alias_sources.append((alias_name, source))

    asset_root = project_dir / ".pcbsmith" / "board-assets"
    asset_footprints = asset_root / "footprints"
    asset_footprints.mkdir(parents=True, exist_ok=True)
    os.environ[PRIVATE_ASSET_ROOT_ENV] = str(asset_root)
    shutil.copyfile(
        oled_source,
        asset_footprints / "PCBSmith_AeroSense__Adafruit_4440_OLED_Module.kicad_mod",
    )
    shutil.copyfile(
        sht_source,
        asset_footprints / "PCBSmith_AeroSense__Sensirion_SHT45_NoCentralPad.kicad_mod",
    )
    for alias_name, source in alias_sources:
        shutil.copyfile(
            source,
            asset_footprints / f"PCBSmith_AeroSense__{alias_name}.kicad_mod",
        )
    load_footprint.cache_clear()
    board_module.FOOTPRINT_LIBRARY[OLED_FOOTPRINT] = load_footprint(OLED_FOOTPRINT).spec
    board_module.FOOTPRINT_LIBRARY[SHT45_FOOTPRINT] = load_footprint(SHT45_FOOTPRINT).spec
    board_module.FOOTPRINT_LIBRARY[TUSB320_FOOTPRINT] = load_footprint(
        TUSB320_FOOTPRINT
    ).spec
    board_module.FOOTPRINT_LIBRARY[VBUS_ESD_FOOTPRINT] = load_footprint(
        VBUS_ESD_FOOTPRINT
    ).spec


def compute_aerosense_placement(netlist: BoardNetlist) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    if set(by_ref) != set(PLACEMENTS):
        missing = sorted(set(PLACEMENTS) - set(by_ref))
        extra = sorted(set(by_ref) - set(PLACEMENTS))
        raise BoardGenerationError(
            f"AeroSense placement/netlist mismatch: missing={missing}, extra={extra}"
        )
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    rotations: list[tuple[str, float]] = []
    for reference, (x, y, rotation) in PLACEMENTS.items():
        placements.append((by_ref[reference], x))
        part_y.append((reference, y))
        if rotation:
            rotations.append((reference, rotation))
    for reference, x, y in MOUNTING_HOLES:
        hole = BoardComponent(
            reference=reference,
            value="M3 NPTH",
            footprint="MountingHole:MountingHole_3.2mm_M3",
            uuid_path=stable_kicad_uuid(
                "board-component-path", "aerosense-r001-hole", reference
            ),
        )
        placements.append((hole, x))
        part_y.append((reference, y))

    graphics = (
        silk_text("USB", (1.5, 18.0), BOARD_SHEET_ORIGIN_MM, size=0.75),
        silk_text("OLED", (11.0, 6.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("FAN1", (65.5, 14.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("FAN2", (65.5, 29.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("MODE", (40.0, 32.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("SELECT", (50.0, 32.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("LOG", (60.0, 32.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("SD", (37.0, 47.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("AeroSense-2F R001", (42.0, 48.0), BOARD_SHEET_ORIGIN_MM, size=0.75),
    )
    return BoardLayout(
        placements=tuple(placements),
        segments=(),
        vias=(),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(rotations),
        part_flip=tuple(sorted(BACK_PARTS)),
        hide_references=HIDDEN_REFERENCES,
        zones=(("GND", "B.Cu", (0.40, 0.40, 69.60, 49.60)),),
        graphics=graphics,
    )


def compute_aerosense_routed_layout(
    netlist: BoardNetlist,
    *,
    checkpoint_dir: Path | None = None,
) -> BoardLayout:
    def checkpoint(stage: str, candidate: BoardLayout) -> None:
        if checkpoint_dir is None:
            return
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        (checkpoint_dir / f"{stage}.kicad_pcb").write_text(
            render_board_from_layout(
                netlist,
                candidate,
                profile=AEROSENSE_RULE_PROFILE,
            ),
            encoding="utf-8",
        )

    placement = _seed_typec_cc_pair(
        _seed_usb_esd_pair(
            _seed_usb_connector_pair(
                _seed_usb_mcu_pair(
                    _seed_qspi_ss(
                        _seed_vbus_spine(compute_aerosense_placement(netlist))
                    )
                )
            )
        )
    )
    # The 3V3 rail uses an F.Cu pour to reach the RP2040's interleaved
    # 0.4-mm-pitch supply pins without blocking the adjacent 1V1 and USB
    # escapes. Back-side 3V3 parts are first joined into a routed backbone;
    # the DS1 through-hole pad bonds that backbone to the front-side pour.
    back_3v3_references = {
        "DS1",
        "J6",
        "R5",
        "FB1",
        "C6",
        "C10",
        "C11",
        "C28",
        "R13",
        "R14",
        "R15",
        "R16",
        "R23",
        "R24",
        "R25",
        "R29",
        "R33",
        "C25",
        "C26",
        "C27",
        "TP2",
    }
    placement = with_route(
        placement,
        route_net_pad_subset(
            placement,
            netlist,
            "/3V3",
            back_3v3_references,
            track_width_mm=0.20,
            grid_mm=0.10,
            profile=AEROSENSE_RULE_PROFILE,
            max_expansions=5_000_000,
        ),
    )
    routable = {
        net.name for net in netlist.nets if len(set(net.nodes)) >= 2
    }
    power_widths = {
        "/VBUS": 0.80,
        "/FAN1_5V": 0.80,
        "/FAN2_5V": 0.80,
        # RP2040 supply pins are on a 0.4-mm pitch. These low-current rails
        # therefore use a manufacturable 0.20-mm neck-down throughout; the
        # high-current 5 V fan paths retain the 0.80-mm power width.
        "/3V3": 0.20,
        "/1V1": 0.20,
        "/ADC_3V3": 0.20,
    }
    fine_names = {
        "/USB_DP_CONN",
        "/USB_DM_CONN",
        "/USB_DP_ESD",
        "/USB_DM_ESD",
        "/USB_DP_MCU",
        "/USB_DM_MCU",
        "/QSPI_SCLK",
        "/QSPI_SD0",
        "/QSPI_SD1",
        "/QSPI_SD2",
        "/QSPI_SD3",
        "/QSPI_SS",
    }
    routing_stages = (
        (
            "core_local",
            (
                "/VBUS_DET",
                "/ADC_3V3",
                "/QSPI_SCLK",
                "/QSPI_SD0",
                "/QSPI_SD1",
                "/QSPI_SD2",
                "/QSPI_SD3",
                "/QSPI_SS",
            ),
        ),
        (
            "typec_state",
            (
                "/TYPEC_OUT2",
                "/TYPEC_OUT1",
            ),
        ),
        (
            "core_supply",
            (
                "/1V1",
            ),
        ),
        (
            "oscillator",
            (
                "/XIN",
                "/XOUT_RAW",
                "/XOUT",
            ),
        ),
        (
            "display_sensor",
            (
                "/OLED_RESET",
                "/I2C_SCL",
                "/I2C_SDA",
            ),
        ),
        (
            "core_io",
            (
                "/USB_DP_CONN",
                "/USB_DM_CONN",
                "/USB_DP_ESD",
                "/USB_DM_ESD",
                "/USB_DP_MCU",
                "/USB_DM_MCU",
                "/CC1",
                "/CC2",
            ),
        ),
        (
            "storage",
            (
                "/SD_MISO",
                "/SD_CS_MCU",
                "/SD_CS_CARD",
                "/SD_SCLK_MCU",
                "/SD_SCLK_CARD",
                "/SD_MOSI_MCU",
                "/SD_MOSI_CARD",
                "/SD_DETECT",
            ),
        ),
        (
            "fans",
            (
                "/FAN1_5V",
                "/FAN2_5V",
                "/FAN1_EN",
                "/FAN2_EN",
                "/FAN1_FAULT_N",
                "/FAN2_FAULT_N",
                "/FAN1_ILIM",
                "/FAN2_ILIM",
                "/FAN1_PWM_GPIO",
                "/FAN2_PWM_GPIO",
                "/FAN1_PWM_GATE",
                "/FAN2_PWM_GATE",
                "/FAN1_PWM",
                "/FAN2_PWM",
                "/FAN1_TACH_RAW",
                "/FAN2_TACH_RAW",
                "/FAN1_TACH",
                "/FAN2_TACH",
            ),
        ),
        (
            "ui_debug",
            (
                "/BOOT_BTN",
                "/RUN",
                "/SWCLK",
                "/SWDIO",
                "/SW_MODE",
                "/SW_SELECT",
                "/SW_LOG",
                "/LED_PWR_A",
                "/LED_FAULT_A",
                "/LED_LOG_A",
                "/LED1_ANODE",
                "/LED2_ANODE",
                "/LED3_ANODE",
            ),
        ),
    )
    manual_nets = {
        "/VBUS",
        "/3V3",
        "/QSPI_SS",
        "/USB_DM_MCU",
        "/USB_DP_MCU",
        "/USB_DM_CONN",
        "/USB_DP_CONN",
        "/USB_DM_ESD",
        "/USB_DP_ESD",
        "/CC1",
        "/CC2",
        "/SD_MISO",
        "/SD_CS_MCU",
        "/SD_CS_CARD",
        "/SD_SCLK_MCU",
        "/SD_SCLK_CARD",
        "/SD_MOSI_MCU",
        "/SD_MOSI_CARD",
        "/SD_DETECT",
        "/OLED_RESET",
        "/I2C_SCL",
        "/I2C_SDA",
    }
    widths = {
        **{
            name: width
            for name, width in power_widths.items()
            if name in routable
        },
        **{name: 0.18 for name in fine_names if name in routable},
        "/TYPEC_OUT1": 0.20,
        "/TYPEC_OUT2": 0.20,
    }
    working = placement
    completed_nets = set(manual_nets)
    checkpoint("00-seeded", working)
    for stage_name, requested_order in routing_stages:
        stage_order = tuple(
            name
            for name in requested_order
            if name in routable and name not in completed_nets
        )
        if stage_name == "typec_state":
            working = _seed_typec_state_pair(working)
            completed_nets.update(stage_order)
            checkpoint(f"{stage_name}-passed", working)
            continue
        if stage_name == "oscillator":
            working = _seed_oscillator_network(working)
            completed_nets.update(stage_order)
            checkpoint(f"{stage_name}-passed", working)
            continue
        if stage_name == "display_sensor":
            working = _seed_i2c_bundle(_seed_oled_reset(working))
            completed_nets.update(stage_order)
            checkpoint(f"{stage_name}-passed", working)
            continue
        if stage_name == "storage":
            working = _seed_sd_mcu_escape(working)
        stage_result = route_board(
            working,
            netlist,
            net_widths=widths,
            default_width_mm=SIGNAL_W,
            net_order=stage_order,
            skip_nets=completed_nets | (routable - set(stage_order)),
            grid_mm=0.10,
            max_restarts=3,
            max_expansions=30_000_000,
            max_expansions_per_net=3_000_000,
            profile=AEROSENSE_RULE_PROFILE,
        )
        if stage_result.failed:
            checkpoint(f"{stage_name}-failed", stage_result.layout)
            raise BoardGenerationError(
                f"AeroSense {stage_name} routing could not route: "
                + ", ".join(stage_result.failed)
            )
        working = stage_result.layout
        completed_nets.update(stage_order)
        checkpoint(f"{stage_name}-passed", working)
    result = route_board(
        working,
        netlist,
        net_widths=widths,
        default_width_mm=SIGNAL_W,
        skip_nets=completed_nets,
        grid_mm=0.10,
        max_restarts=5,
        max_expansions=50_000_000,
        max_expansions_per_net=3_000_000,
        profile=AEROSENSE_RULE_PROFILE,
    )
    if result.failed:
        checkpoint("remainder-failed", result.layout)
        raise BoardGenerationError(
            "AeroSense routing could not route: " + ", ".join(result.failed)
        )
    final_layout = replace(
        result.layout,
        zones=(
            ("3V3", "F.Cu", (0.40, 0.40, 69.60, 49.60)),
            ("GND", "B.Cu", (0.40, 0.40, 69.60, 49.60)),
        ),
    )
    checkpoint("final-routed", final_layout)
    return final_layout


def _seed_oled_reset(layout: BoardLayout) -> BoardLayout:
    """Escape OLED reset under the module before general routing.

    The OLED module courtyard surrounds its through-hole header, so a generic
    body-obstacle router cannot enter the pad from outside.  The RP2040 escape
    also has to cross the already constrained USB pair.  A short front escape
    and one back-layer run make that topology explicit without using a
    via-in-pad.
    """

    tracks = (
        TrackSegment(
            34.4375,
            27.20,
            35.50,
            27.20,
            "F.Cu",
            "/OLED_RESET",
            0.20,
        ),
        TrackSegment(
            35.50,
            27.20,
            34.30,
            26.00,
            "B.Cu",
            "/OLED_RESET",
            0.20,
        ),
        TrackSegment(
            34.30,
            26.00,
            34.30,
            19.00,
            "B.Cu",
            "/OLED_RESET",
            0.20,
        ),
        TrackSegment(
            34.30,
            19.00,
            34.77,
            18.46,
            "B.Cu",
            "/OLED_RESET",
            0.20,
        ),
    )
    vias = (ViaSpec(35.50, 27.20, "/OLED_RESET"),)
    return replace(
        layout,
        segments=(*layout.segments, *tracks),
        vias=(*layout.vias, *vias),
    )


def _seed_sd_mcu_escape(layout: BoardLayout) -> BoardLayout:
    """Route the three-point MISO net through the card/ESD corridor."""

    segments = (
        TrackSegment(27.5625, 25.60, 26.40, 25.60, "F.Cu", "/SD_MISO", 0.20),
        TrackSegment(26.40, 25.60, 25.60, 24.80, "B.Cu", "/SD_MISO", 0.20),
        TrackSegment(25.60, 24.80, 23.50, 24.80, "B.Cu", "/SD_MISO", 0.20),
        TrackSegment(23.50, 24.80, 23.50, 29.50, "B.Cu", "/SD_MISO", 0.20),
        TrackSegment(23.50, 29.50, 24.00, 31.50, "F.Cu", "/SD_MISO", 0.20),
        TrackSegment(24.00, 31.50, 24.175, 32.875, "F.Cu", "/SD_MISO", 0.20),
        TrackSegment(24.00, 31.50, 18.00, 31.00, "B.Cu", "/SD_MISO", 0.20),
        TrackSegment(18.00, 31.00, 16.00, 31.00, "B.Cu", "/SD_MISO", 0.20),
        TrackSegment(16.00, 31.00, 17.00, 32.115, "F.Cu", "/SD_MISO", 0.20),
        TrackSegment(27.5625, 26.00, 25.60, 26.00, "F.Cu", "/SD_CS_MCU", 0.20),
        TrackSegment(25.60, 26.00, 25.20, 27.00, "B.Cu", "/SD_CS_MCU", 0.20),
        TrackSegment(25.20, 27.00, 25.20, 30.20, "B.Cu", "/SD_CS_MCU", 0.20),
        TrackSegment(25.20, 30.20, 27.00, 32.00, "B.Cu", "/SD_CS_MCU", 0.20),
        TrackSegment(27.00, 32.00, 27.00, 35.325, "B.Cu", "/SD_CS_MCU", 0.20),
        # Card-side chip select tree: series resistor, socket, ESD and pull-up.
        TrackSegment(27.00, 33.675, 28.50, 33.675, "B.Cu", "/SD_CS_CARD", 0.20),
        TrackSegment(28.50, 33.675, 30.775, 32.875, "F.Cu", "/SD_CS_CARD", 0.20),
        TrackSegment(27.00, 33.675, 22.00, 34.50, "B.Cu", "/SD_CS_CARD", 0.20),
        TrackSegment(22.00, 34.50, 20.00, 36.00, "B.Cu", "/SD_CS_CARD", 0.20),
        TrackSegment(20.00, 36.00, 21.175, 41.00, "B.Cu", "/SD_CS_CARD", 0.20),
        TrackSegment(22.00, 34.50, 18.50, 33.50, "B.Cu", "/SD_CS_CARD", 0.20),
        TrackSegment(18.50, 33.50, 19.00, 32.115, "F.Cu", "/SD_CS_CARD", 0.20),
        TrackSegment(27.5625, 26.40, 26.40, 26.80, "F.Cu", "/SD_SCLK_MCU", 0.20),
        TrackSegment(26.40, 26.80, 27.20, 27.60, "B.Cu", "/SD_SCLK_MCU", 0.20),
        TrackSegment(27.20, 27.60, 28.00, 30.50, "B.Cu", "/SD_SCLK_MCU", 0.20),
        TrackSegment(28.00, 30.50, 30.50, 33.00, "B.Cu", "/SD_SCLK_MCU", 0.20),
        TrackSegment(30.50, 33.00, 32.00, 35.325, "B.Cu", "/SD_SCLK_MCU", 0.20),
        # Card-side clock tree.
        TrackSegment(32.00, 33.675, 28.00, 34.20, "B.Cu", "/SD_SCLK_CARD", 0.20),
        TrackSegment(28.00, 34.20, 26.00, 34.20, "B.Cu", "/SD_SCLK_CARD", 0.20),
        TrackSegment(26.00, 34.20, 26.375, 32.875, "F.Cu", "/SD_SCLK_CARD", 0.20),
        TrackSegment(32.00, 33.675, 33.00, 34.675, "B.Cu", "/SD_SCLK_CARD", 0.20),
        TrackSegment(33.00, 34.675, 33.00, 37.50, "B.Cu", "/SD_SCLK_CARD", 0.20),
        TrackSegment(33.00, 37.50, 20.00, 37.50, "B.Cu", "/SD_SCLK_CARD", 0.20),
        TrackSegment(20.00, 37.50, 17.00, 34.00, "B.Cu", "/SD_SCLK_CARD", 0.20),
        TrackSegment(17.00, 34.00, 17.50, 32.115, "F.Cu", "/SD_SCLK_CARD", 0.20),
        TrackSegment(27.5625, 26.80, 25.60, 27.20, "F.Cu", "/SD_MOSI_MCU", 0.20),
        TrackSegment(25.60, 27.20, 26.00, 28.00, "B.Cu", "/SD_MOSI_MCU", 0.20),
        TrackSegment(26.00, 28.00, 26.00, 30.00, "B.Cu", "/SD_MOSI_MCU", 0.20),
        TrackSegment(26.00, 30.00, 29.50, 33.00, "B.Cu", "/SD_MOSI_MCU", 0.20),
        TrackSegment(29.50, 33.00, 29.50, 35.325, "B.Cu", "/SD_MOSI_MCU", 0.20),
        # Card-side MOSI tree.
        TrackSegment(29.50, 33.675, 28.575, 34.50, "B.Cu", "/SD_MOSI_CARD", 0.20),
        TrackSegment(28.575, 34.50, 28.575, 32.875, "F.Cu", "/SD_MOSI_CARD", 0.20),
        TrackSegment(29.50, 33.675, 30.50, 35.00, "B.Cu", "/SD_MOSI_CARD", 0.20),
        TrackSegment(30.50, 35.00, 30.50, 36.50, "B.Cu", "/SD_MOSI_CARD", 0.20),
        TrackSegment(30.50, 36.50, 19.50, 36.50, "B.Cu", "/SD_MOSI_CARD", 0.20),
        TrackSegment(19.50, 36.50, 18.00, 34.00, "B.Cu", "/SD_MOSI_CARD", 0.20),
        TrackSegment(18.00, 34.00, 18.50, 32.115, "F.Cu", "/SD_MOSI_CARD", 0.20),
        # Card-detect return and pull-up.
        TrackSegment(34.4375, 27.60, 35.50, 27.60, "F.Cu", "/SD_DETECT", 0.20),
        TrackSegment(35.50, 27.60, 36.20, 28.30, "F.Cu", "/SD_DETECT", 0.20),
        TrackSegment(36.20, 28.30, 36.20, 37.50, "B.Cu", "/SD_DETECT", 0.20),
        TrackSegment(36.20, 37.50, 33.975, 41.00, "B.Cu", "/SD_DETECT", 0.20),
        TrackSegment(33.975, 41.00, 22.50, 42.00, "B.Cu", "/SD_DETECT", 0.20),
        TrackSegment(22.50, 42.00, 21.50, 42.00, "B.Cu", "/SD_DETECT", 0.20),
        TrackSegment(21.50, 42.00, 21.175, 43.375, "F.Cu", "/SD_DETECT", 0.20),
    )
    vias = (
        ViaSpec(26.40, 25.60, "/SD_MISO"),
        ViaSpec(23.50, 29.50, "/SD_MISO"),
        ViaSpec(24.00, 31.50, "/SD_MISO"),
        ViaSpec(16.00, 31.00, "/SD_MISO"),
        ViaSpec(25.60, 26.00, "/SD_CS_MCU"),
        ViaSpec(28.50, 33.675, "/SD_CS_CARD"),
        ViaSpec(18.50, 33.50, "/SD_CS_CARD"),
        ViaSpec(26.40, 26.80, "/SD_SCLK_MCU"),
        ViaSpec(26.00, 34.20, "/SD_SCLK_CARD"),
        ViaSpec(17.00, 34.00, "/SD_SCLK_CARD"),
        ViaSpec(25.60, 27.20, "/SD_MOSI_MCU"),
        ViaSpec(28.575, 34.50, "/SD_MOSI_CARD"),
        ViaSpec(18.00, 34.00, "/SD_MOSI_CARD"),
        ViaSpec(36.20, 28.30, "/SD_DETECT"),
        ViaSpec(21.50, 42.00, "/SD_DETECT"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _seed_i2c_bundle(layout: BoardLayout) -> BoardLayout:
    """Route SCL/SDA as one coordinated, branched bus.

    Both nets have three physical endpoints (MCU, OLED header and SHT45).
    Independent shortest-path routing always lets the first net consume the
    only two-layer corridor around the MCU.  These lanes reserve the pair
    together, keeping 0.8 mm separation through the long sensor branch and
    entering the OLED header from below on B.Cu.
    """

    segments = (
        # SDA fanout from RP2040 pad 2.
        TrackSegment(27.5625, 24.80, 26.00, 24.80, "F.Cu", "/I2C_SDA", 0.20),
        # SDA OLED branch.
        TrackSegment(26.00, 24.80, 25.20, 24.00, "B.Cu", "/I2C_SDA", 0.20),
        TrackSegment(25.20, 24.00, 25.20, 20.00, "B.Cu", "/I2C_SDA", 0.20),
        TrackSegment(25.20, 20.00, 39.85, 18.80, "F.Cu", "/I2C_SDA", 0.20),
        TrackSegment(39.85, 18.80, 39.85, 18.46, "F.Cu", "/I2C_SDA", 0.20),
        # SDA SHT45 branch.
        TrackSegment(26.00, 24.80, 24.80, 26.00, "B.Cu", "/I2C_SDA", 0.20),
        TrackSegment(24.80, 26.00, 24.80, 37.00, "B.Cu", "/I2C_SDA", 0.20),
        TrackSegment(24.80, 37.00, 12.00, 42.60, "B.Cu", "/I2C_SDA", 0.20),
        TrackSegment(12.00, 42.60, 13.30, 42.60, "F.Cu", "/I2C_SDA", 0.20),
        # SCL fanout from RP2040 pad 3.
        TrackSegment(27.5625, 25.20, 27.00, 25.20, "F.Cu", "/I2C_SCL", 0.20),
        TrackSegment(27.00, 25.20, 26.80, 25.60, "F.Cu", "/I2C_SCL", 0.20),
        # SCL OLED branch.
        TrackSegment(26.80, 25.60, 26.40, 25.20, "B.Cu", "/I2C_SCL", 0.20),
        TrackSegment(26.40, 25.20, 26.40, 19.40, "B.Cu", "/I2C_SCL", 0.20),
        TrackSegment(26.40, 19.40, 37.31, 18.90, "F.Cu", "/I2C_SCL", 0.20),
        TrackSegment(37.31, 18.90, 37.31, 18.46, "F.Cu", "/I2C_SCL", 0.20),
        # SCL SHT45 branch.
        TrackSegment(26.80, 25.60, 25.60, 26.80, "B.Cu", "/I2C_SCL", 0.20),
        TrackSegment(25.60, 26.80, 24.00, 28.40, "B.Cu", "/I2C_SCL", 0.20),
        TrackSegment(24.00, 28.40, 24.00, 37.80, "B.Cu", "/I2C_SCL", 0.20),
        TrackSegment(24.00, 37.80, 12.00, 43.40, "B.Cu", "/I2C_SCL", 0.20),
        TrackSegment(12.00, 43.40, 13.30, 43.40, "F.Cu", "/I2C_SCL", 0.20),
    )
    vias = (
        ViaSpec(26.00, 24.80, "/I2C_SDA"),
        ViaSpec(25.20, 20.00, "/I2C_SDA"),
        ViaSpec(12.00, 42.60, "/I2C_SDA"),
        ViaSpec(26.80, 25.60, "/I2C_SCL"),
        ViaSpec(26.40, 19.40, "/I2C_SCL"),
        ViaSpec(12.00, 43.40, "/I2C_SCL"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _seed_typec_state_pair(layout: BoardLayout) -> BoardLayout:
    """Route the adjacent Type-C state outputs as staggered paired lanes.

    Sequential single-net A* used a needless excursion across the MCU for
    OUT2 and then sealed OUT1 off. These retained lanes share the open lower
    corridor but use separate, staggered layer changes near the MCU.
    """
    segments = (
        # OUT2: upper corridor lane.
        TrackSegment(12.05, 32.80, 15.00, 32.80, "F.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(15.00, 32.80, 17.825, 29.925, "F.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(17.825, 29.925, 18.10, 30.30, "F.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(18.10, 30.30, 20.60, 32.80, "F.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(20.60, 32.80, 20.60, 33.40, "F.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(20.60, 33.40, 21.80, 34.60, "F.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(21.80, 34.60, 26.80, 34.60, "F.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(26.80, 34.60, 28.60, 32.80, "B.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(28.60, 32.80, 29.60, 31.80, "F.Cu", "/TYPEC_OUT2", 0.20),
        TrackSegment(29.60, 31.80, 29.60, 30.10, "F.Cu", "/TYPEC_OUT2", 0.20),
        # OUT1: lower corridor lane.
        TrackSegment(12.05, 33.20, 13.50, 34.65, "F.Cu", "/TYPEC_OUT1", 0.20),
        TrackSegment(12.05, 33.20, 13.50, 31.75, "F.Cu", "/TYPEC_OUT1", 0.20),
        TrackSegment(13.50, 31.75, 14.325, 30.00, "F.Cu", "/TYPEC_OUT1", 0.20),
        TrackSegment(13.50, 34.65, 19.50, 35.50, "F.Cu", "/TYPEC_OUT1", 0.20),
        TrackSegment(19.50, 35.50, 25.80, 35.50, "F.Cu", "/TYPEC_OUT1", 0.20),
        TrackSegment(25.80, 35.50, 27.60, 33.80, "B.Cu", "/TYPEC_OUT1", 0.20),
        TrackSegment(27.60, 33.80, 29.20, 32.20, "F.Cu", "/TYPEC_OUT1", 0.20),
        TrackSegment(29.20, 32.20, 29.20, 30.10, "F.Cu", "/TYPEC_OUT1", 0.20),
    )
    vias = (
        ViaSpec(26.80, 34.60, "/TYPEC_OUT2"),
        ViaSpec(28.60, 32.80, "/TYPEC_OUT2"),
        ViaSpec(25.80, 35.50, "/TYPEC_OUT1"),
        ViaSpec(27.60, 33.80, "/TYPEC_OUT1"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _seed_oscillator_network(layout: BoardLayout) -> BoardLayout:
    """Retain the short RP2040 crystal fanout and local load network."""
    segments = (
        # XOUT_RAW: stagger right of the Type-C escapes, then enter R3 pad 1.
        TrackSegment(30.80, 30.775, 31.40, 31.40, "F.Cu", "/XOUT_RAW", 0.20),
        TrackSegment(31.40, 31.40, 29.675, 33.00, "B.Cu", "/XOUT_RAW", 0.20),
        # XIN: independent rightward fanout into Y1 pad 1 and C15.
        TrackSegment(30.40, 30.775, 30.40, 31.20, "F.Cu", "/XIN", 0.20),
        TrackSegment(30.40, 31.20, 32.40, 33.20, "F.Cu", "/XIN", 0.20),
        TrackSegment(32.40, 33.20, 34.00, 34.80, "B.Cu", "/XIN", 0.20),
        TrackSegment(34.00, 34.80, 36.10, 34.85, "B.Cu", "/XIN", 0.20),
        TrackSegment(36.10, 34.85, 37.775, 37.50, "B.Cu", "/XIN", 0.20),
        # XOUT: R3 pad 2 now faces Y1 pad 3; branch locally to C16.
        TrackSegment(31.325, 33.00, 33.90, 33.15, "B.Cu", "/XOUT", 0.20),
        TrackSegment(33.90, 33.15, 34.775, 37.50, "B.Cu", "/XOUT", 0.20),
    )
    vias = (
        ViaSpec(31.40, 31.40, "/XOUT_RAW"),
        ViaSpec(32.40, 33.20, "/XIN"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _seed_vbus_spine(layout: BoardLayout) -> BoardLayout:
    """Provide the 0.8-mm VBUS trunk before dense signal routing.

    The trunk occupies the clear corridor between the OLED edge and the MCU,
    with short local drops into both protected fan channels.  Remaining VBUS
    loads are connected to this retained tree by the ordinary router.
    """

    segments = (
        TrackSegment(8.20, 20.80, 55.00, 20.80, "F.Cu", "/VBUS", 0.80),
        TrackSegment(6.78, 22.60, 8.20, 22.60, "F.Cu", "/VBUS", 0.30),
        TrackSegment(8.20, 22.60, 8.20, 20.80, "F.Cu", "/VBUS", 0.80),
        TrackSegment(44.8625, 25.05, 44.8625, 20.80, "F.Cu", "/VBUS", 0.80),
        TrackSegment(50.8625, 25.05, 50.8625, 20.80, "F.Cu", "/VBUS", 0.80),
        TrackSegment(46.225, 23.50, 46.225, 20.80, "F.Cu", "/VBUS", 0.80),
        TrackSegment(52.225, 23.50, 52.225, 20.80, "F.Cu", "/VBUS", 0.80),
        TrackSegment(8.55, 18.50, 8.20, 20.80, "F.Cu", "/VBUS", 0.30),
        TrackSegment(9.3625, 16.95, 8.55, 18.50, "F.Cu", "/VBUS", 0.30),
        TrackSegment(9.3625, 15.05, 8.00, 15.05, "F.Cu", "/VBUS", 0.30),
        TrackSegment(8.00, 15.05, 8.00, 17.50, "F.Cu", "/VBUS", 0.30),
        TrackSegment(8.00, 17.50, 8.55, 18.50, "F.Cu", "/VBUS", 0.30),
        TrackSegment(5.05, 16.00, 4.00, 16.00, "F.Cu", "/VBUS", 0.50),
        TrackSegment(4.00, 16.00, 4.00, 14.00, "F.Cu", "/VBUS", 0.50),
        TrackSegment(4.00, 14.00, 8.00, 14.00, "F.Cu", "/VBUS", 0.50),
        TrackSegment(8.00, 14.00, 8.00, 15.05, "F.Cu", "/VBUS", 0.50),
        TrackSegment(10.05, 13.00, 8.00, 14.00, "F.Cu", "/VBUS", 0.50),
        TrackSegment(8.00, 5.00, 8.00, 11.00, "B.Cu", "/VBUS", 0.50),
        TrackSegment(8.00, 11.00, 10.05, 13.00, "F.Cu", "/VBUS", 0.50),
        TrackSegment(11.3375, 25.00, 12.50, 25.00, "F.Cu", "/VBUS", 0.30),
        TrackSegment(12.50, 25.00, 12.50, 20.80, "F.Cu", "/VBUS", 0.50),
        TrackSegment(6.78, 27.40, 8.20, 27.40, "F.Cu", "/VBUS", 0.30),
        TrackSegment(8.20, 27.40, 12.50, 27.40, "B.Cu", "/VBUS", 0.50),
        TrackSegment(12.50, 27.40, 12.50, 20.80, "B.Cu", "/VBUS", 0.50),
        TrackSegment(10.175, 36.00, 9.00, 36.00, "F.Cu", "/VBUS", 0.20),
        TrackSegment(9.00, 36.00, 12.50, 27.40, "B.Cu", "/VBUS", 0.20),
    )
    vias = (
        ViaSpec(8.00, 11.00, "/VBUS", size_mm=0.80, drill_mm=0.40),
        ViaSpec(8.20, 27.40, "/VBUS", size_mm=0.80, drill_mm=0.40),
        ViaSpec(12.50, 20.80, "/VBUS", size_mm=0.80, drill_mm=0.40),
        ViaSpec(9.00, 36.00, "/VBUS", size_mm=0.60, drill_mm=0.30),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _seed_qspi_ss(layout: BoardLayout) -> BoardLayout:
    """Route the four-node boot-select net before the dense QSPI bundle.

    The flash sits left of the MCU while the BOOTSEL resistor is on the back.
    This deterministic escape goes around the flash body and prevents the
    sequential router from boxing in QSPI_SS after routing the other five
    QSPI conductors.
    """

    segments = (
        TrackSegment(28.40, 23.5625, 27.00, 21.80, "F.Cu", "/QSPI_SS", 0.18),
        TrackSegment(27.00, 21.80, 20.825, 22.00, "F.Cu", "/QSPI_SS", 0.18),
        TrackSegment(20.825, 22.00, 23.00, 23.50, "F.Cu", "/QSPI_SS", 0.18),
        TrackSegment(23.00, 23.50, 23.00, 20.50, "B.Cu", "/QSPI_SS", 0.18),
        TrackSegment(23.00, 20.50, 21.825, 20.50, "B.Cu", "/QSPI_SS", 0.18),
        TrackSegment(23.00, 20.50, 23.00, 18.50, "B.Cu", "/QSPI_SS", 0.18),
        TrackSegment(23.00, 18.50, 17.50, 18.50, "B.Cu", "/QSPI_SS", 0.18),
        TrackSegment(17.50, 18.50, 17.50, 30.80, "B.Cu", "/QSPI_SS", 0.18),
        TrackSegment(17.50, 30.80, 19.595, 30.80, "B.Cu", "/QSPI_SS", 0.18),
        TrackSegment(19.595, 30.80, 19.595, 29.975, "F.Cu", "/QSPI_SS", 0.18),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(
            *layout.vias,
            ViaSpec(23.00, 23.50, "/QSPI_SS"),
            ViaSpec(19.595, 30.80, "/QSPI_SS"),
        ),
    )


def _seed_usb_connector_pair(layout: BoardLayout) -> BoardLayout:
    """Merge the reversible Type-C D+/D- pads before the ESD array.

    The four receptacle data pads are interleaved.  Each duplicate pair is
    folded behind the connector on B.Cu, while the primary front-layer lanes
    diverge directly into the USBLC6-2SC6.  This is the standard topology the
    sequential router cannot infer from four alternating source pads.
    """

    segments = (
        # D+ primary lane and duplicate-pad foldback.
        TrackSegment(6.78, 24.75, 9.0625, 24.05, "F.Cu", "/USB_DP_CONN", 0.18),
        TrackSegment(6.78, 24.75, 6.00, 24.75, "F.Cu", "/USB_DP_CONN", 0.18),
        TrackSegment(6.78, 25.75, 6.00, 25.75, "F.Cu", "/USB_DP_CONN", 0.18),
        TrackSegment(6.00, 24.75, 6.00, 25.75, "B.Cu", "/USB_DP_CONN", 0.18),
        # D- primary lane and a separate foldback lane.
        TrackSegment(6.78, 25.25, 9.0625, 25.95, "F.Cu", "/USB_DM_CONN", 0.18),
        TrackSegment(6.78, 24.25, 5.20, 24.25, "F.Cu", "/USB_DM_CONN", 0.18),
        TrackSegment(6.78, 25.25, 5.20, 25.25, "F.Cu", "/USB_DM_CONN", 0.18),
        TrackSegment(5.20, 24.25, 5.20, 25.25, "B.Cu", "/USB_DM_CONN", 0.18),
    )
    vias = (
        ViaSpec(6.00, 24.75, "/USB_DP_CONN"),
        ViaSpec(6.00, 25.75, "/USB_DP_CONN"),
        ViaSpec(5.20, 24.25, "/USB_DM_CONN"),
        ViaSpec(5.20, 25.25, "/USB_DM_CONN"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _seed_typec_cc_pair(layout: BoardLayout) -> BoardLayout:
    """Route CC1/CC2 through the local ESD device into the Type-C controller."""

    segments = (
        # CC1 crosses the interleaved USB pad field on B.Cu.
        TrackSegment(6.78, 23.75, 7.50, 23.00, "F.Cu", "/CC1", 0.20),
        TrackSegment(7.50, 23.00, 7.50, 29.50, "B.Cu", "/CC1", 0.20),
        TrackSegment(7.50, 29.50, 6.50, 30.50, "B.Cu", "/CC1", 0.20),
        TrackSegment(6.50, 30.50, 7.45, 31.425, "F.Cu", "/CC1", 0.20),
        TrackSegment(7.45, 31.425, 10.275, 32.80, "F.Cu", "/CC1", 0.20),
        # CC2 leaves below the USB pad field and remains on the front.
        TrackSegment(6.78, 26.75, 6.80, 29.50, "F.Cu", "/CC2", 0.20),
        TrackSegment(6.80, 29.50, 8.15, 31.425, "F.Cu", "/CC2", 0.20),
        TrackSegment(8.15, 31.425, 10.275, 33.20, "F.Cu", "/CC2", 0.20),
    )
    vias = (
        ViaSpec(7.50, 23.00, "/CC1"),
        ViaSpec(6.50, 30.50, "/CC1"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _seed_usb_esd_pair(layout: BoardLayout) -> BoardLayout:
    """Carry the protected USB pair beneath the OLED to the resistors.

    The wide VBUS trunk is crossed only on B.Cu.  Both signals then return to
    F.Cu in the otherwise unused region beneath the OLED module and drop onto
    the back-side series-resistor pads through staggered vias.
    """

    segments = (
        # Protected D+.
        TrackSegment(11.3375, 24.05, 12.50, 24.05, "F.Cu", "/USB_DP_ESD", 0.18),
        TrackSegment(12.50, 24.05, 13.00, 19.00, "B.Cu", "/USB_DP_ESD", 0.18),
        TrackSegment(13.00, 19.00, 13.00, 15.50, "F.Cu", "/USB_DP_ESD", 0.18),
        TrackSegment(13.00, 15.50, 36.00, 15.50, "F.Cu", "/USB_DP_ESD", 0.18),
        TrackSegment(36.00, 15.50, 36.00, 19.675, "B.Cu", "/USB_DP_ESD", 0.18),
        # Protected D-.
        TrackSegment(11.3375, 25.95, 14.50, 25.95, "F.Cu", "/USB_DM_ESD", 0.18),
        TrackSegment(14.50, 25.95, 15.00, 19.00, "B.Cu", "/USB_DM_ESD", 0.18),
        TrackSegment(15.00, 19.00, 15.00, 17.00, "F.Cu", "/USB_DM_ESD", 0.18),
        TrackSegment(15.00, 17.00, 41.50, 17.00, "F.Cu", "/USB_DM_ESD", 0.18),
        TrackSegment(41.50, 17.00, 41.50, 19.675, "B.Cu", "/USB_DM_ESD", 0.18),
    )
    vias = (
        ViaSpec(12.50, 24.05, "/USB_DP_ESD"),
        ViaSpec(13.00, 19.00, "/USB_DP_ESD"),
        ViaSpec(36.00, 15.50, "/USB_DP_ESD"),
        ViaSpec(14.50, 25.95, "/USB_DM_ESD"),
        ViaSpec(15.00, 19.00, "/USB_DM_ESD"),
        ViaSpec(41.50, 17.00, "/USB_DM_ESD"),
    )
    return replace(
        layout,
        segments=(*layout.segments, *segments),
        vias=(*layout.vias, *vias),
    )


def _seed_usb_mcu_pair(layout: BoardLayout) -> BoardLayout:
    """Retain a short, ordered USB pair between series resistors and RP2040.

    The series resistors are on the back to keep the connector/ESD corridor
    unobstructed.  These paired escapes preserve D+/D- ordering, converge from
    1.6-mm resistor spacing to the RP2040's 0.4-mm pitch, and avoid a late
    sequential-router dead end at the QFN edge.
    """

    segments = (
        TrackSegment(36.00, 21.325, 33.50, 21.80, "B.Cu", "/USB_DP_MCU", 0.18),
        TrackSegment(33.50, 21.80, 31.80, 21.80, "B.Cu", "/USB_DP_MCU", 0.18),
        TrackSegment(31.80, 21.80, 31.80, 22.50, "F.Cu", "/USB_DP_MCU", 0.18),
        TrackSegment(31.80, 22.50, 32.00, 22.50, "F.Cu", "/USB_DP_MCU", 0.18),
        TrackSegment(32.00, 22.50, 32.00, 23.5625, "F.Cu", "/USB_DP_MCU", 0.18),
        TrackSegment(41.50, 21.325, 39.00, 22.50, "B.Cu", "/USB_DM_MCU", 0.18),
        TrackSegment(39.00, 22.50, 35.00, 22.50, "B.Cu", "/USB_DM_MCU", 0.18),
        TrackSegment(35.00, 22.50, 32.40, 22.50, "F.Cu", "/USB_DM_MCU", 0.18),
        TrackSegment(32.40, 22.50, 32.40, 23.5625, "F.Cu", "/USB_DM_MCU", 0.18),
    )
    vias = (
        ViaSpec(31.80, 21.80, "/USB_DP_MCU"),
        ViaSpec(35.00, 22.50, "/USB_DM_MCU"),
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
    register_aerosense_assets(board_file.parent)
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    for footprint in {component.footprint for component in netlist.components}:
        if footprint not in FOOTPRINT_LIBRARY:
            FOOTPRINT_LIBRARY[footprint] = load_footprint(footprint).spec
    layout = (
        compute_aerosense_routed_layout(
            netlist,
            checkpoint_dir=board_file.parent
            / ".pcbsmith"
            / "routing-checkpoints",
        )
        if routed
        else compute_aerosense_placement(netlist)
    )
    board_file.write_text(
        render_board_from_layout(netlist, layout, profile=AEROSENSE_RULE_PROFILE),
        encoding="utf-8",
    )
    return netlist, layout


def generate_aerosense_placement_board(
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


def generate_aerosense_routed_board(
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
