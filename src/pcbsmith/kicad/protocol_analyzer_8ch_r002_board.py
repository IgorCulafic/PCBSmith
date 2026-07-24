"""Compact R002 placement for the eight-channel protocol analyzer."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.kicad import board as board_module
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    export_kicad_netlist_xml,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import PRIVATE_ASSET_ROOT_ENV, load_footprint
from pcbsmith.kicad.protocol_analyzer_8ch_board import (
    PROTOCOL_ANALYZER_RULE_PROFILE,
)
from pcbsmith.kicad.shaped_board import silk_text

BOARD_W = 70.0
BOARD_H = 42.0
SWITCH_FOOTPRINT = "PCBSmith_Protocol:Alps_SKRTLAE010_RightAngle"
UPSTREAM_SWITCH_FOOTPRINT = (
    "Button_Switch_SMD:SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010"
)

# Coordinates were legalized against exact KiCad courtyard hulls. J1's mating
# region and the SW1/SW2 actuator regions are the only intentional overhangs.
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "J1": (35.0, 4.8, 0.0),
    "J2": (2.0, 8.8, 0.0),
    "J3": (45.5, 37.5, 90.0),
    "SW1": (68.0, 14.0, 90.0),
    "SW2": (68.0, 28.0, 90.0),
    "U6": (10.0, 13.0, 90.0),
    "U7": (10.0, 27.0, 90.0),
    "U4": (22.0, 20.0, 0.0),
    "R11": (14.0, 9.5, 0.0),
    "R12": (14.0, 12.5, 0.0),
    "R13": (14.0, 15.5, 0.0),
    "R14": (14.0, 18.5, 0.0),
    "R15": (14.0, 21.5, 0.0),
    "R16": (14.0, 24.5, 0.0),
    "R17": (14.0, 27.5, 0.0),
    "R18": (14.0, 30.5, 0.0),
    "U1": (36.0, 21.0, 0.0),
    "U2": (36.0, 32.0, 0.0),
    "Y1": (28.0, 31.0, 0.0),
    "R5": (31.0, 31.0, 90.0),
    "C5": (27.0, 27.0, 0.0),
    "C6": (30.0, 27.0, 0.0),
    "U8": (35.0, 11.0, 0.0),
    "R3": (31.0, 14.5, 90.0),
    "R4": (33.5, 14.5, 90.0),
    "U3": (44.0, 10.0, 0.0),
    "C1": (42.5, 5.5, 0.0),
    "C2": (46.0, 5.5, 0.0),
    "C3": (48.0, 10.0, 90.0),
    "C4": (49.5, 5.5, 0.0),
    "R1": (27.0, 9.0, 0.0),
    "R2": (27.0, 11.5, 0.0),
    "R6": (64.0, 14.0, 0.0),
    "R7": (61.0, 11.0, 0.0),
    "R8": (64.0, 28.0, 0.0),
    "D1": (52.5, 8.0, 0.0),
    "R9": (55.5, 8.0, 0.0),
    "D2": (52.5, 11.0, 0.0),
    "R10": (55.5, 11.0, 0.0),
    "U9": (59.0, 32.0, 90.0),
    "D3": (50.5, 32.0, 0.0),
    "R19": (54.0, 32.0, 0.0),
    "R22": (62.0, 35.0, 0.0),
    "R20": (57.0, 37.0, 0.0),
    "R21": (61.0, 39.0, 0.0),
    "C19": (57.0, 40.0, 0.0),
    "C7": (24.0, 15.0, 90.0),
    "C8": (24.0, 25.0, 90.0),
    "C9": (59.0, 29.0, 0.0),
    "C10": (29.0, 18.0, 90.0),
    "C11": (41.0, 18.0, 90.0),
    "C12": (31.0, 24.0, 90.0),
    "C13": (41.0, 24.0, 90.0),
    "C14": (33.0, 27.0, 0.0),
    "C15": (39.0, 27.0, 0.0),
    "C16": (40.5, 31.0, 90.0),
    "C17": (36.0, 26.5, 0.0),
    "C18": (31.0, 35.5, 0.0),
}

MOUNTING_HOLES = (
    ("H1", 4.0, 4.0),
    ("H2", 66.0, 4.0),
    ("H3", 4.0, 38.0),
    ("H4", 66.0, 38.0),
)


def _box(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    z_center_mm: float,
    color: str,
    *,
    y_center_mm: float = 0.0,
) -> str:
    scale = 1.0 / 2.54
    return f"""Transform {{
  translation 0 {y_center_mm * scale:.6f} {z_center_mm * scale:.6f}
  children [ Shape {{
    appearance Appearance {{ material Material {{ diffuseColor {color} }} }}
    geometry Box {{ size {x_mm * scale:.6f} {y_mm * scale:.6f} {z_mm * scale:.6f} }}
  }} ]
}}"""


def _switch_proxy_model() -> str:
    """Dimensioned visual envelope, not assembly-authoritative supplier CAD."""
    return "\n".join(
        (
            "#VRML V2.0 utf8",
            "# PCBSmith visual proxy based on the Alps SKRT footprint/datasheet envelope.",
            "# It demonstrates actuator access only; use supplier CAD for enclosure sign-off.",
            _box(4.5, 2.6, 1.8, 0.9, "0.18 0.18 0.20"),
            _box(
                2.0,
                1.8,
                1.2,
                1.0,
                "0.72 0.72 0.74",
                y_center_mm=2.0,
            ),
            "",
        )
    )


def register_protocol_analyzer_r002_assets(project_dir: Path) -> None:
    """Install the upstream switch geometry plus a local 3D proxy."""
    library = project_dir / "PCBSmith_Protocol.pretty"
    library.mkdir(parents=True, exist_ok=True)
    (project_dir / "fp-lib-table").write_text(
        """(fp_lib_table
  (version 7)
  (lib (name "PCBSmith_Protocol")(type "KiCad")
    (uri "${KIPRJMOD}/PCBSmith_Protocol.pretty")(options "")(descr ""))
)
""",
        encoding="utf-8",
    )
    model_dir = project_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_file = model_dir / "alps-skrtlae010-right-angle-proxy.wrl"
    model_file.write_text(_switch_proxy_model(), encoding="ascii")

    imported = load_footprint(UPSTREAM_SWITCH_FOOTPRINT)
    footprint_text = imported.source_file.read_text(encoding="utf-8")
    footprint_text = footprint_text.replace(
        '(footprint "SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010"',
        '(footprint "Alps_SKRTLAE010_RightAngle"',
        1,
    )
    # KiCad 10's footprint declares an upstream STEP path that is absent from
    # the installed 3D library. Remove that final model node before adding the
    # explicit project-local proxy, otherwise preflight correctly reports a
    # misleading unresolved model alongside the working proxy.
    upstream_model_start = footprint_text.rfind("\n\t(model ")
    root_end = footprint_text.rfind("\n)")
    if upstream_model_start >= 0 and upstream_model_start < root_end:
        footprint_text = footprint_text[:upstream_model_start] + footprint_text[root_end:]
    footprint_text = (
        footprint_text.rstrip()[:-1]
        + """
  (model "${KIPRJMOD}/models/alps-skrtlae010-right-angle-proxy.wrl"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0)))
)
"""
    )
    source = library / "Alps_SKRTLAE010_RightAngle.kicad_mod"
    source.write_text(footprint_text, encoding="utf-8")

    asset_root = project_dir / ".pcbsmith" / "board-assets"
    asset_footprints = asset_root / "footprints"
    asset_footprints.mkdir(parents=True, exist_ok=True)
    os.environ[PRIVATE_ASSET_ROOT_ENV] = str(asset_root)
    shutil.copyfile(
        source,
        asset_footprints / "PCBSmith_Protocol__Alps_SKRTLAE010_RightAngle.kicad_mod",
    )
    load_footprint.cache_clear()
    board_module.FOOTPRINT_LIBRARY[SWITCH_FOOTPRINT] = load_footprint(
        SWITCH_FOOTPRINT
    ).spec


def compute_protocol_analyzer_r002_placement(netlist: BoardNetlist) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    if set(by_ref) != set(PLACEMENTS):
        missing = sorted(set(PLACEMENTS) - set(by_ref))
        extra = sorted(set(by_ref) - set(PLACEMENTS))
        raise BoardGenerationError(
            f"R002 placement/netlist mismatch: missing={missing}, extra={extra}"
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
            value="M2.5 NPTH",
            footprint="MountingHole:MountingHole_2.7mm_M2.5",
            uuid_path=stable_kicad_uuid(
                "board-component-path", "protocol-analyzer-r002-hole", reference
            ),
        )
        placements.append((hole, x))
        part_y.append((reference, y))

    graphics = (
        silk_text("TARGET", (7.0, 39.5), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("BOOT", (64.0, 18.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("RESET", (63.0, 33.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
        silk_text("8-CH ANALYZER R002", (24.0, 40.0), BOARD_SHEET_ORIGIN_MM, size=0.80),
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
        hide_references=tuple(PLACEMENTS),
    )


def generate_protocol_analyzer_r002_placement_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    register_protocol_analyzer_r002_assets(board_file.parent)
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    for footprint in {component.footprint for component in netlist.components}:
        if footprint not in FOOTPRINT_LIBRARY:
            FOOTPRINT_LIBRARY[footprint] = load_footprint(footprint).spec
    layout = compute_protocol_analyzer_r002_placement(netlist)
    board_file.write_text(
        render_board_from_layout(
            netlist,
            layout,
            profile=PROTOCOL_ANALYZER_RULE_PROFILE,
        ),
        encoding="utf-8",
    )
    return netlist, layout
