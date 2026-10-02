"""Two-layer shaped PCB generation for Montenegro Environment Display R001."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pcbsmith.kicad.board as board_module
from pcbsmith.kicad.astar_router import BoardRouteResult, route_board
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    ViaSpec,
    export_kicad_netlist_xml,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import PRIVATE_ASSET_ROOT_ENV, load_footprint
from pcbsmith.kicad.montenegro_geometry import MontenegroGeometry
from pcbsmith.kicad.montenegro_led_corridor import apply_led_chain_10_corridor
from pcbsmith.kicad.shaped_board import NetLookup, Router, placed_pad, silk_text
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

ESP32_HOME_FAB_FOOTPRINT = "PCBSmith_Montenegro:ESP32-S3-WROOM-1_HomeFab"

OLED_MECHANICAL_FOOTPRINT = "PCBSmith_Montenegro:Waveshare_1p5in_OLED_Mechanical"
MOUNTING_HOLE_FOOTPRINT = "MountingHole:MountingHole_2.7mm_M2.5"
SIGNAL_WIDTH_MM = 0.25
POWER_WIDTH_MM = 0.60
POWER_VIA_OFFSET_MM = 0.95

MONTENEGRO_RULE_PROFILE = DEFAULT_PCB_RULE_PROFILE.model_copy(
    update={
        "profile_id": "montenegro-display-two-layer-6mil-v1",
        "geometry": DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
            update={
                "profile_id": "montenegro-display-geometry-6mil-v1",
                "minimum_trace_width_mm": 0.15,
                "routing_via_diameter_mm": 0.55,
                "routing_via_drill_mm": 0.30,
                "default_signal_trace_width_mm": SIGNAL_WIDTH_MM,
            }
        ),
        "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
            update={
                "profile_id": "montenegro-display-spacing-6mil-v1",
                "minimum_copper_clearance_mm": 0.15,
            }
        ),
    }
)
MONTENEGRO_ROUTING_PROFILE = MONTENEGRO_RULE_PROFILE.model_copy(
    update={
        "profile_id": "montenegro-display-two-layer-routing-margin-v1",
        "fab_spacing": MONTENEGRO_RULE_PROFILE.fab_spacing.model_copy(
            update={"minimum_copper_clearance_mm": 0.18}
        ),
    }
)
FIXED_BACK_PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "J1": (7.50, 75.00, 270.0),
    "F1": (22.00, 64.00, 0.0),
    "U3": (17.00, 75.00, 180.0),
    "R1": (13.00, 82.00, 0.0),
    "R2": (17.00, 82.00, 0.0),
    "R3": (23.00, 77.00, 0.0),
    "R4": (23.00, 73.00, 0.0),
    "U2": (36.00, 69.00, 0.0),
    "C1": (27.00, 69.00, 0.0),
    "C2": (43.00, 69.00, 0.0),
    "C7": (28.00, 64.00, 0.0),
    "U5": (32.00, 93.00, 0.0),
    "R8": (38.00, 93.00, 0.0),
    "C6": (32.00, 98.00, 0.0),
    "U1": (110.00, 70.00, 270.0),
    "R5": (98.00, 84.00, 0.0),
    "C3": (103.00, 84.00, 0.0),
    "C4": (108.00, 84.00, 0.0),
    "R9": (113.00, 84.00, 0.0),
    "R6": (66.00, 96.00, 0.0),
    "R7": (72.00, 96.00, 0.0),
    "SW1": (70.00, 105.00, 0.0),
    "SW2": (65.00, 118.00, 0.0),
    "J2": (55.00, 106.00, 0.0),
    "U4": (35.00, 122.00, 0.0),
    "C5": (35.00, 117.50, 0.0),
}

MOUNTING_HOLES = (
    ("H1", 38.0, 55.0),
    ("H2", 61.0, 55.0),
    ("H3", 45.0, 115.0),
)


def _oled_model() -> str:
    scale = 1.0 / 2.54
    return f"""#VRML V2.0 utf8
Transform {{
  translation 0 0 {0.8 * scale:.6f}
  children [ Shape {{
    appearance Appearance {{ material Material {{ diffuseColor 0.04 0.18 0.08 }} }}
    geometry Box {{ size {44.5 * scale:.6f} {37.0 * scale:.6f} {1.6 * scale:.6f} }}
  }} ]
}}
Transform {{
  translation 0 0 {3.1 * scale:.6f}
  children [ Shape {{
    appearance Appearance {{ material Material {{ diffuseColor 0.02 0.03 0.04 }} }}
    geometry Box {{ size {29.0 * scale:.6f} {29.0 * scale:.6f} {3.0 * scale:.6f} }}
  }} ]
}}
"""


def _oled_mechanical_footprint() -> str:
    return """(footprint "Waveshare_1p5in_OLED_Mechanical"
  (version 20241229)
  (generator "PCBSmith")
  (layer "F.Cu")
  (attr board_only exclude_from_pos_files exclude_from_bom)
  (property "Reference" "MECH1" (at 0 -20.5 0) (layer "F.SilkS") hide)
  (property "Value" "Waveshare 1.5in SSD1351 OLED envelope" (at 0 20.5 0) (layer "F.Fab"))
  (fp_rect (start -22.25 -18.5) (end 22.25 18.5)
    (stroke (width 0.20) (type default)) (fill none) (layer "F.SilkS"))
  (fp_rect (start -14.5 -14.5) (end 14.5 14.5)
    (stroke (width 0.15) (type default)) (fill none) (layer "F.Fab"))
  (fp_rect (start -22.5 -18.75) (end 22.5 18.75)
    (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
  (model "${KIPRJMOD}/models/waveshare-1p5in-oled-envelope.wrl"
    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
)
"""


def register_montenegro_assets(project_dir: Path) -> None:
    library = project_dir / "PCBSmith_Montenegro.pretty"
    library.mkdir(parents=True, exist_ok=True)
    (project_dir / "fp-lib-table").write_text(
        """(fp_lib_table
  (version 7)
  (lib (name "PCBSmith_Montenegro")(type "KiCad")
    (uri "${KIPRJMOD}/PCBSmith_Montenegro.pretty")(options "")(descr ""))
)
""",
        encoding="utf-8",
    )
    models = project_dir / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "waveshare-1p5in-oled-envelope.wrl").write_text(_oled_model(), encoding="ascii")
    source = library / "Waveshare_1p5in_OLED_Mechanical.kicad_mod"
    source.write_text(_oled_mechanical_footprint(), encoding="utf-8")
    upstream_esp32 = load_footprint("RF_Module:ESP32-S3-WROOM-1")
    esp32_text = upstream_esp32.source_file.read_text(encoding="utf-8")
    esp32_text = esp32_text.replace(
        '(footprint "ESP32-S3-WROOM-1"',
        '(footprint "ESP32-S3-WROOM-1_HomeFab"',
        1,
    ).replace("(drill 0.2)", "(drill 0.3)")
    esp32_source = library / "ESP32-S3-WROOM-1_HomeFab.kicad_mod"
    esp32_source.write_text(esp32_text, encoding="utf-8")

    asset_root = project_dir / ".pcbsmith" / "board-assets"
    asset_footprints = asset_root / "footprints"
    asset_footprints.mkdir(parents=True, exist_ok=True)
    os.environ[PRIVATE_ASSET_ROOT_ENV] = str(asset_root)
    shutil.copyfile(
        source,
        asset_footprints / "PCBSmith_Montenegro__Waveshare_1p5in_OLED_Mechanical.kicad_mod",
    )
    shutil.copyfile(
        esp32_source,
        asset_footprints / "PCBSmith_Montenegro__ESP32-S3-WROOM-1_HomeFab.kicad_mod",
    )
    load_footprint.cache_clear()
    board_module.FOOTPRINT_LIBRARY[OLED_MECHANICAL_FOOTPRINT] = load_footprint(
        OLED_MECHANICAL_FOOTPRINT
    ).spec
    board_module.FOOTPRINT_LIBRARY[ESP32_HOME_FAB_FOOTPRINT] = load_footprint(
        ESP32_HOME_FAB_FOOTPRINT
    ).spec


def load_schematic_netlist(schematic_file: Path) -> BoardNetlist:
    netlist_file = export_kicad_netlist_xml(schematic_file)
    return parse_board_netlist(netlist_file.read_text(encoding="utf-8"))


def _back_silk_text(text: str, at: tuple[float, float], size: float = 0.8) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    return f"""  (gr_text "{text}"
    (at {at[0] + origin:.3f} {at[1] + origin:.3f} 0)
    (layer "B.SilkS")
    (uuid {stable_kicad_uuid("montenegro-back-silk", text, str(at), str(size))})
    (effects
      (font (size {size} {size}) (thickness {size * 0.18:.2f}))
      (justify mirror)
    )
  )"""


def _toward(
    point: tuple[float, float], target: tuple[float, float], distance: float
) -> tuple[float, float]:
    dx, dy = target[0] - point[0], target[1] - point[1]
    magnitude = (dx * dx + dy * dy) ** 0.5
    if magnitude == 0:
        return (point[0] + distance, point[1])
    return (point[0] + dx * distance / magnitude, point[1] + dy * distance / magnitude)


def _base_placement(
    netlist: BoardNetlist,
    geometry: MontenegroGeometry,
    project_dir: Path,
) -> BoardLayout:
    register_montenegro_assets(project_dir)
    by_ref = {component.reference: component for component in netlist.components}
    required_footprints = {
        *(component.footprint for component in netlist.components),
        MOUNTING_HOLE_FOOTPRINT,
    }
    for footprint in required_footprints:
        if footprint not in board_module.FOOTPRINT_LIBRARY:
            board_module.FOOTPRINT_LIBRARY[footprint] = load_footprint(footprint).spec

    expected = {
        *FIXED_BACK_PLACEMENTS,
        *(f"D{index}" for index in range(1, len(geometry.led_sites) + 1)),
        *(f"C{index + 7}" for index in range(1, len(geometry.led_sites) + 1)),
    }
    if set(by_ref) != expected:
        raise BoardGenerationError(
            "Montenegro placement/netlist mismatch: "
            f"missing={sorted(expected - set(by_ref))}, extra={sorted(set(by_ref) - expected)}"
        )

    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    rotations: list[tuple[str, float]] = []
    flipped: list[str] = []
    hidden: list[str] = []

    def place(
        component: BoardComponent,
        x: float,
        y: float,
        rotation: float = 0.0,
        *,
        back: bool = False,
        hide: bool = False,
    ) -> None:
        placements.append((component, x))
        part_y.append((component.reference, y))
        if rotation:
            rotations.append((component.reference, rotation))
        if back:
            flipped.append(component.reference)
        if hide:
            hidden.append(component.reference)

    for reference, (x, y, rotation) in FIXED_BACK_PLACEMENTS.items():
        place(by_ref[reference], x, y, rotation, back=True)

    for index, site in enumerate(geometry.led_sites, start=1):
        place(by_ref[f"D{index}"], site.x_mm, site.y_mm, site.rotation_deg, hide=True)
        cap_reference = f"C{index + 7}"
        if cap_reference in {"C20", "C23", "C40"}:
            cap_offset = 7.5
        else:
            cap_offset = -2.0 if cap_reference in {"C15", "C28", "C42"} else 4.5
        cap_x, cap_y = _toward(
            (site.x_mm, site.y_mm),
            geometry.display_center_mm,
            cap_offset,
        )
        place(
            by_ref[cap_reference],
            cap_x,
            cap_y,
            site.rotation_deg,
            back=True,
        )

    mechanical = BoardComponent(
        reference="MECH1",
        value="Waveshare 1.5in SSD1351 OLED envelope",
        footprint=OLED_MECHANICAL_FOOTPRINT,
        uuid_path=stable_kicad_uuid("board-component-path", "montenegro", "MECH1"),
    )
    place(mechanical, *geometry.display_center_mm, hide=True)
    for reference, x, y in MOUNTING_HOLES:
        hole = BoardComponent(
            reference=reference,
            value="M2.5 NPTH",
            footprint=MOUNTING_HOLE_FOOTPRINT,
            uuid_path=stable_kicad_uuid("board-component-path", "montenegro", reference),
        )
        place(hole, x, y, hide=True)

    graphics = (
        silk_text(
            "MONTENEGRO",
            (geometry.display_center_mm[0], geometry.display_center_mm[1] + 23.0),
            BOARD_SHEET_ORIGIN_MM,
            size=1.15,
        ),
        _back_silk_text("USB-C 5V / DATA", (13.0, 59.0), 0.80),
        _back_silk_text("BOOT", (76.0, 104.0), 0.80),
        _back_silk_text("RESET", (72.0, 117.0), 0.80),
        _back_silk_text("SHT45 - KEEP CLEAR", (42.0, 127.0), 0.80),
        _back_silk_text("R001  TWO-LAYER PROTOTYPE", (40.0, 96.0), 0.80),
    )
    return BoardLayout(
        placements=tuple(placements),
        segments=(),
        vias=(),
        width_mm=geometry.width_mm,
        height_mm=geometry.height_mm,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(rotations),
        zones=(
            ("/+5V", "F.Cu", (0.5, 0.5, geometry.width_mm - 0.5, geometry.height_mm - 0.5)),
            ("/GND", "B.Cu", (0.5, 0.5, geometry.width_mm - 0.5, geometry.height_mm - 0.5)),
        ),
        outline=geometry.outline,
        graphics=graphics,
        part_flip=tuple(flipped),
        hide_references=tuple(hidden),
    )


def _plane_stubs(
    layout: BoardLayout,
    netlist: BoardNetlist,
    geometry: MontenegroGeometry,
) -> BoardLayout:
    lookup = NetLookup(netlist)
    anchors = {component.reference: x for component, x in layout.placements}
    anchors_y = dict(layout.part_y_mm)
    rotations = dict(layout.part_rotation)
    flipped = set(layout.part_flip)
    by_ref = {component.reference: component for component in netlist.components}
    router = Router()

    # The front plane supplies the visible LEDs directly. Their ground pads
    # use via-in-pad access to the uninterrupted back ground plane.
    for index, site in enumerate(geometry.led_sites, start=1):
        reference = f"D{index}"
        lookup.expect(reference, "3", "/GND")
        pad = placed_pad(
            by_ref[reference].footprint,
            "3",
            anchor=(site.x_mm, site.y_mm),
            rotation=site.rotation_deg,
        )
        router.via("/GND", *pad)

    # Back-side ground pads connect to B.Cu directly. Only back-side +5 V
    # consumers need a transition to the front supply plane. Via-in-pad keeps
    # those transitions inside their own copper and cannot form the obstacle
    # rings produced by offset stubs around dense packages.
    for net in netlist.nets:
        if net.name != "/+5V":
            continue
        for reference, pin in net.nodes:
            if reference.startswith("D"):
                continue
            component = by_ref[reference]
            anchor = (anchors[reference], anchors_y[reference])
            pad = placed_pad(
                component.footprint,
                pin,
                anchor=anchor,
                rotation=rotations.get(reference, 0.0),
                flipped=reference in flipped,
            )
            router.via("/+5V", *pad)

    return BoardLayout(
        **{
            **layout.__dict__,
            "segments": (*layout.segments, *router.segments),
            "vias": (*layout.vias, *router.vias),
        }
    )


def _usb_connector_escape(layout: BoardLayout, netlist: BoardNetlist) -> BoardLayout:
    """Route the USB-C receptacle's interleaved A/B USB 2.0 pads.

    The 0.5 mm connector row requires a topology-aware local escape: D+ stays
    on B.Cu while D- changes layers immediately behind the receptacle.  A
    generic single-net A* pass can route either member first but then blocks
    its mate.  This deterministic micro-route is confined to J1--U3 and leaves
    every downstream protected signal to the board router.
    """
    lookup = NetLookup(netlist)
    by_ref = {component.reference: component for component in netlist.components}
    anchors = {component.reference: x for component, x in layout.placements}
    anchors_y = dict(layout.part_y_mm)
    rotations = dict(layout.part_rotation)
    flipped = set(layout.part_flip)

    def pad(reference: str, pin: str, net: str) -> tuple[float, float]:
        lookup.expect(reference, pin, net)
        return placed_pad(
            by_ref[reference].footprint,
            pin,
            anchor=(anchors[reference], anchors_y[reference]),
            rotation=rotations.get(reference, 0.0),
            flipped=reference in flipped,
        )

    dplus = "/USB_D+_CONN"
    dp_a = pad("J1", "A6", dplus)
    dp_b = pad("J1", "B6", dplus)
    dp_esd = pad("U3", "1", dplus)
    dminus = "/USB_D-_CONN"
    dm_a = pad("J1", "A7", dminus)
    dm_b = pad("J1", "B7", dminus)
    dm_esd = pad("U3", "3", dminus)

    router = Router()
    # D+ fans out on the component side and merges before the ESD input.
    dp_merge = (14.80, 75.25)
    router.path(
        dplus,
        (dp_b, (11.80, 74.25), (12.80, 73.40), (14.40, 73.40), dp_merge),
        layer="B.Cu",
        width=0.15,
    )
    router.path(
        dplus,
        (dp_a, dp_merge),
        layer="B.Cu",
        width=0.15,
    )
    router.path(dplus, (dp_merge, dp_esd), layer="B.Cu", width=0.15)

    # D- uses three short B.Cu stubs and a front-layer bridge so its A/B
    # receptacle pads do not cross the already-routed D+ fanout.
    dm_a_via = (12.50, 74.75)
    dm_b_via = (14.00, 75.75)
    dm_esd_via = (15.00, 72.80)
    router.path(dminus, (dm_a, dm_a_via), layer="B.Cu", width=0.15)
    router.path(dminus, (dm_b, dm_b_via), layer="B.Cu", width=0.15)
    router.path(dminus, (dm_esd, dm_esd_via), layer="B.Cu", width=0.15)
    for via in (dm_a_via, dm_b_via, dm_esd_via):
        router.vias.append(
            ViaSpec(
                x=via[0],
                y=via[1],
                net_name=dminus,
                size_mm=0.55,
                drill_mm=0.30,
            )
        )
    router.path(
        dminus,
        (dm_a_via, (13.00, 73.50), dm_esd_via, (14.50, 74.80), dm_b_via),
        layer="F.Cu",
        width=0.15,
    )
    return BoardLayout(
        **{
            **layout.__dict__,
            "segments": (*layout.segments, *router.segments),
            "vias": (*layout.vias, *router.vias),
        }
    )


def _vbus_input_route(layout: BoardLayout, netlist: BoardNetlist) -> BoardLayout:
    """Create the short, explicit high-current path from USB-C to fuse/TVS."""
    lookup = NetLookup(netlist)
    by_ref = {component.reference: component for component in netlist.components}
    anchors = {component.reference: x for component, x in layout.placements}
    anchors_y = dict(layout.part_y_mm)
    rotations = dict(layout.part_rotation)
    flipped = set(layout.part_flip)

    def pad(reference: str, pin: str) -> tuple[float, float]:
        lookup.expect(reference, pin, "/VBUS_RAW")
        return placed_pad(
            by_ref[reference].footprint,
            pin,
            anchor=(anchors[reference], anchors_y[reference]),
            rotation=rotations.get(reference, 0.0),
            flipped=reference in flipped,
        )

    j_upper = pad("J1", "B4")
    j_lower = pad("J1", "A4")
    fuse = pad("F1", "1")
    esd = pad("U3", "5")
    # A4/A9 and B4/B9 are coincident physical pads in the selected footprint.
    # Each 0.6 mm land necks down only until a via; a 1 mm front-layer trunk
    # then carries the combined current without crossing the ESD data pins.
    lookup.expect("J1", "A9", "/VBUS_RAW")
    lookup.expect("J1", "B9", "/VBUS_RAW")
    router = Router()
    upper_via = (12.50, j_upper[1])
    lower_via = (12.50, j_lower[1])
    fuse_via = fuse
    esd_via = esd
    router.path(
        "/VBUS_RAW",
        (j_upper, upper_via),
        layer="B.Cu",
        width=0.40,
    )
    router.path(
        "/VBUS_RAW",
        (j_lower, lower_via),
        layer="B.Cu",
        width=0.40,
    )
    router.path(
        "/VBUS_RAW",
        (upper_via, (13.20, 70.00), (18.00, 68.00), (20.40, 68.00), fuse_via),
        layer="F.Cu",
        width=1.00,
    )
    router.path(
        "/VBUS_RAW",
        (lower_via, (13.20, 80.00), (20.00, 80.00), (20.00, 75.00), esd_via),
        layer="F.Cu",
        width=1.00,
    )
    router.path(
        "/VBUS_RAW",
        (esd_via, (20.00, 75.00), (20.00, 68.00), (18.00, 68.00)),
        layer="F.Cu",
        width=1.00,
    )
    for via, size, drill in (
        (upper_via, 0.55, 0.30),
        (lower_via, 0.55, 0.30),
        (esd_via, 0.55, 0.30),
        (fuse_via, 0.80, 0.40),
    ):
        router.vias.append(
            ViaSpec(
                x=via[0],
                y=via[1],
                net_name="/VBUS_RAW",
                size_mm=size,
                drill_mm=drill,
            )
        )
    return BoardLayout(
        **{
            **layout.__dict__,
            "segments": (*layout.segments, *router.segments),
            "vias": (*layout.vias, *router.vias),
        }
    )


def _i2c_bus_route(layout: BoardLayout, netlist: BoardNetlist) -> BoardLayout:
    """Reserve a parallel low-speed sensor corridor before general routing."""
    lookup = NetLookup(netlist)
    by_ref = {component.reference: component for component in netlist.components}
    anchors = {component.reference: x for component, x in layout.placements}
    anchors_y = dict(layout.part_y_mm)
    rotations = dict(layout.part_rotation)
    flipped = set(layout.part_flip)

    def pad(reference: str, pin: str, net: str) -> tuple[float, float]:
        lookup.expect(reference, pin, net)
        return placed_pad(
            by_ref[reference].footprint,
            pin,
            anchor=(anchors[reference], anchors_y[reference]),
            rotation=rotations.get(reference, 0.0),
            flipped=reference in flipped,
        )

    sda = "/I2C_SDA"
    sda_sensor = pad("U4", "1", sda)
    sda_pullup = pad("R6", "2", sda)
    sda_mcu = pad("U1", "12", sda)
    scl = "/I2C_SCL"
    scl_sensor = pad("U4", "2", scl)
    scl_pullup = pad("R7", "2", scl)
    scl_mcu = pad("U1", "17", scl)

    router = Router()
    router.path(
        sda,
        (
            sda_sensor,
            (57.00, 148.00),
            (57.00, 130.00),
            (75.00, 122.00),
            (83.00, 112.00),
            (87.00, 104.00),
            sda_pullup,
        ),
        layer="B.Cu",
        width=0.20,
    )
    router.path(
        sda,
        (sda_pullup, (90.00, 96.00), (104.00, 94.00), (104.00, 84.00), sda_mcu),
        layer="B.Cu",
        width=0.20,
    )
    router.path(
        scl,
        (
            scl_sensor,
            (61.00, 149.00),
            (61.00, 132.00),
            (77.00, 124.00),
            (86.00, 114.00),
            (92.00, 104.00),
            scl_pullup,
        ),
        layer="B.Cu",
        width=0.20,
    )
    router.path(
        scl,
        (scl_pullup, (94.00, 96.00), (95.00, 88.00), (95.00, 74.445), scl_mcu),
        layer="B.Cu",
        width=0.20,
    )
    return BoardLayout(
        **{
            **layout.__dict__,
            "segments": (*layout.segments, *router.segments),
            "vias": (*layout.vias, *router.vias),
        }
    )


def compute_montenegro_layout(
    netlist: BoardNetlist,
    geometry: MontenegroGeometry,
    project_dir: Path,
) -> tuple[BoardLayout, BoardRouteResult]:
    placement = _base_placement(netlist, geometry, project_dir)
    routing_base = _vbus_input_route(_usb_connector_escape(placement, netlist), netlist)
    routing_base = _plane_stubs(routing_base, netlist, geometry)
    usb_targets = (
        "/USB_D+_ESD",
        "/USB_D-_ESD",
        "/USB_D+_MCU",
        "/USB_D-_MCU",
    )
    oled_targets = (
        "/OLED_SCLK",
        "/OLED_MOSI",
        "/OLED_CS",
        "/OLED_DC",
        "/OLED_RST",
        "/LED_DATA_3V3",
    )
    usb_skip = tuple(
        net.name for net in netlist.nets if net.name not in set((*usb_targets, *oled_targets))
    )
    usb_phase = route_board(
        routing_base,
        netlist,
        profile=MONTENEGRO_ROUTING_PROFILE,
        skip_nets=usb_skip,
        fine_pitch_nets={net: 0.15 for net in usb_targets},
        max_restarts=0,
        net_order=oled_targets,
        max_expansions=4_000_000,
        max_expansions_per_net=1_000_000,
        fine_grid_mm=0.1,
    )
    if usb_phase.failed:
        return placement, usb_phase
    i2c_targets = ("/I2C_SCL", "/I2C_SDA")
    i2c_skip = tuple(net.name for net in netlist.nets if net.name not in set(i2c_targets))
    i2c_phase = route_board(
        usb_phase.layout,
        netlist,
        profile=MONTENEGRO_ROUTING_PROFILE,
        net_order=i2c_targets,
        skip_nets=i2c_skip,
        net_widths={net: 0.20 for net in i2c_targets},
        default_width_mm=0.20,
        max_restarts=0,
        max_expansions=10_000_000,
        max_expansions_per_net=5_000_000,
        grid_mm=0.25,
    )
    if i2c_phase.failed:
        return placement, i2c_phase
    power_targets = ("/+3V3",)
    power_skip = tuple(net.name for net in netlist.nets if net.name not in set(power_targets))
    power_phase = route_board(
        i2c_phase.layout,
        netlist,
        profile=MONTENEGRO_ROUTING_PROFILE,
        net_order=power_targets,
        skip_nets=power_skip,
        net_widths={"/+3V3": POWER_WIDTH_MM},
        default_width_mm=POWER_WIDTH_MM,
        max_restarts=0,
        max_expansions=12_000_000,
        max_expansions_per_net=12_000_000,
        grid_mm=0.25,
    )
    if power_phase.failed:
        return placement, power_phase
    routing_base = power_phase.layout
    routing_base = apply_led_chain_10_corridor(routing_base, netlist, geometry)
    led_nets = tuple(f"/LED_CHAIN_{index:02d}" for index in range(1, len(geometry.led_sites)))
    priority = (
        "/USB_D+_CONN",
        "/USB_D-_CONN",
        "/USB_D+_ESD",
        "/USB_D-_ESD",
        *led_nets,
        "/LED_DATA_5V",
        "/LED_DATA_5V_PRE",
        "/LED_DATA_3V3",
        "/+3V3",
        "/I2C_SDA",
        "/I2C_SCL",
        "/OLED_SCLK",
        "/OLED_MOSI",
    )
    widths = {
        "/VBUS_RAW": 1.00,
        "/+3V3": POWER_WIDTH_MM,
        "/USB_D+_CONN": 0.25,
        "/USB_D-_CONN": 0.25,
        "/USB_D+_ESD": 0.25,
        "/USB_D-_ESD": 0.25,
    }
    routed = route_board(
        routing_base,
        netlist,
        net_widths=widths,
        default_width_mm=SIGNAL_WIDTH_MM,
        profile=MONTENEGRO_ROUTING_PROFILE,
        net_order=priority,
        skip_nets=(
            "/GND",
            "/+5V",
            "/LED_CHAIN_10",
            "/I2C_SDA",
            "/I2C_SCL",
            "/+3V3",
            "/USB_D+_CONN",
            "/USB_D-_CONN",
            "/VBUS_RAW",
            "/USB_D+_ESD",
            "/USB_D-_ESD",
            "/USB_D+_MCU",
            "/USB_D-_MCU",
            "/OLED_SCLK",
            "/OLED_MOSI",
            "/OLED_CS",
            "/OLED_DC",
            "/OLED_RST",
            "/LED_DATA_3V3",
        ),
        # Preserve the successful prefix; local failures are repaired in place.
        max_restarts=0,
        max_expansions=18_000_000,
        max_expansions_per_net=500_000,
        fine_pitch_nets={
            "/LED_CHAIN_10": 0.25,
        },
        grid_mm=0.25,
    )
    return placement, routed


def write_montenegro_board(
    board_file: Path,
    netlist: BoardNetlist,
    layout: BoardLayout,
) -> None:
    board_file.write_text(
        render_board_from_layout(netlist, layout, profile=MONTENEGRO_RULE_PROFILE),
        encoding="utf-8",
    )
