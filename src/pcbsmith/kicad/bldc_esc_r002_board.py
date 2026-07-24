"""Thermal-mechanical R002 placement variant for the BLDC ESC pilot."""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path

from pcbsmith.kicad import board as board_module
from pcbsmith.kicad.bldc_esc_board import (
    _as_four_layer,
    compute_bldc_esc_placement_layout,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNetlist,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import PRIVATE_ASSET_ROOT_ENV, load_footprint

HEATSINK_CENTER_MM = (109.0, 43.0)
PHASE_MOSFET_POSES = (
    ("TIM1", 99.0, 14.0, 270.0),
    ("TIM2", 118.0, 14.0, 270.0),
    ("TIM3", 99.0, 43.0, 270.0),
    ("TIM4", 118.0, 43.0, 270.0),
    ("TIM5", 99.0, 72.0, 270.0),
    ("TIM6", 118.0, 72.0, 270.0),
)
CLAMP_POSES = (
    ("H5", 92.0, 28.5),
    ("H6", 126.0, 28.5),
    ("H7", 92.0, 57.5),
    ("H8", 126.0, 57.5),
)

MECHANICAL_FOOTPRINTS = {
    "PCBSmith_Mechanical:BLDC_R002_Heatsink_42x82": "BLDC_R002_Heatsink_42x82",
    "PCBSmith_Mechanical:BLDC_R002_TIM_10p3x15p4": "BLDC_R002_TIM_10p3x15p4",
    "PCBSmith_Mechanical:BLDC_R002_Clamp_Standoff_M3": "BLDC_R002_Clamp_Standoff_M3",
}


def _mechanical_footprint_texts() -> dict[str, str]:
    return {
        "BLDC_R002_Heatsink_42x82": """(footprint "BLDC_R002_Heatsink_42x82"
  (version 20241229)
  (generator "PCBSmith")
  (layer "F.Cu")
  (descr "R002 common isolated top-side heatsink envelope; exact part not selected")
  (attr board_only exclude_from_pos_files exclude_from_bom)
  (fp_text reference "REF**" (at 0 -42.8) (layer "F.Fab") hide
    (effects (font (size 1 1) (thickness 0.15))))
  (fp_rect (start -21 -41) (end 21 41)
    (stroke (width 0.25) (type default)) (fill none) (layer "F.Fab"))
  (model "${KIPRJMOD}/models/bldc-r002-heatsink-envelope.wrl"
    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
)
""",
        "BLDC_R002_TIM_10p3x15p4": """(footprint "BLDC_R002_TIM_10p3x15p4"
  (version 20241229)
  (generator "PCBSmith")
  (layer "F.Cu")
  (descr "R002 electrically isolating TIM envelope; material not selected")
  (attr board_only exclude_from_pos_files exclude_from_bom)
  (fp_text reference "REF**" (at 0 0) (layer "F.Fab") hide
    (effects (font (size 0.7 0.7) (thickness 0.1))))
  (fp_rect (start -5.15 -7.7) (end 5.15 7.7)
    (stroke (width 0.15) (type default)) (fill none) (layer "F.Fab"))
  (model "${KIPRJMOD}/models/bldc-r002-isolating-tim-envelope.wrl"
    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
)
""",
        "BLDC_R002_Clamp_Standoff_M3": """(footprint "BLDC_R002_Clamp_Standoff_M3"
  (version 20241229)
  (generator "PCBSmith")
  (layer "F.Cu")
  (descr "R002 M3 clamp hole and board-bending support envelope")
  (attr board_only exclude_from_pos_files exclude_from_bom)
  (fp_text reference "REF**" (at 0 -3.7) (layer "F.Fab") hide
    (effects (font (size 0.8 0.8) (thickness 0.12))))
  (fp_circle (center 0 0) (end 3.0 0)
    (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
  (pad "" np_thru_hole circle (at 0 0) (size 5.5 5.5) (drill 3.2)
    (layers "*.Cu" "*.Mask"))
  (model "${KIPRJMOD}/models/bldc-r002-clamp-standoff-envelope.wrl"
    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
)
""",
    }


def register_r002_mechanical_footprints(project_dir: Path) -> None:
    """Install project-local mechanical envelopes without global KiCad changes."""
    library = project_dir / "PCBSmith_Mechanical.pretty"
    library.mkdir(parents=True, exist_ok=True)
    asset_root = project_dir / ".pcbsmith" / "board-assets"
    asset_footprints = asset_root / "footprints"
    asset_footprints.mkdir(parents=True, exist_ok=True)
    os.environ[PRIVATE_ASSET_ROOT_ENV] = str(asset_root)
    for library_id, name in MECHANICAL_FOOTPRINTS.items():
        source = library / f"{name}.kicad_mod"
        source.write_text(_mechanical_footprint_texts()[name], encoding="utf-8")
        target = asset_footprints / f"PCBSmith_Mechanical__{name}.kicad_mod"
        shutil.copyfile(source, target)
        load_footprint.cache_clear()
        board_module.FOOTPRINT_LIBRARY[library_id] = load_footprint(library_id).spec


def compute_bldc_esc_r002_layout(
    netlist: BoardNetlist,
    *,
    project_dir: Path,
    include_heatsink: bool = True,
) -> BoardLayout:
    base = compute_bldc_esc_placement_layout(netlist, project_dir=project_dir)
    register_r002_mechanical_footprints(project_dir)
    additions: list[tuple[BoardComponent, float]] = []
    part_y = list(base.part_y_mm)
    rotations = list(base.part_rotation)
    hidden = list(base.hide_references)

    if include_heatsink:
        additions.append(
            (
                BoardComponent(
                    reference="HS1",
                    value="COMMON TOP HEATSPREADER ENVELOPE",
                    footprint="PCBSmith_Mechanical:BLDC_R002_Heatsink_42x82",
                    uuid_path=stable_kicad_uuid("board-component-path", "bldc-esc-r002", "HS1"),
                ),
                HEATSINK_CENTER_MM[0],
            )
        )
        part_y.append(("HS1", HEATSINK_CENTER_MM[1]))
        hidden.append("HS1")

    for reference, x, y, rotation in PHASE_MOSFET_POSES:
        additions.append(
            (
                BoardComponent(
                    reference=reference,
                    value="ELECTRICALLY ISOLATING TIM ENVELOPE",
                    footprint="PCBSmith_Mechanical:BLDC_R002_TIM_10p3x15p4",
                    uuid_path=stable_kicad_uuid(
                        "board-component-path", "bldc-esc-r002", reference
                    ),
                ),
                x,
            )
        )
        part_y.append((reference, y))
        rotations.append((reference, rotation))
        hidden.append(reference)

    for reference, x, y in CLAMP_POSES:
        additions.append(
            (
                BoardComponent(
                    reference=reference,
                    value="M3 CLAMP / SUPPORT",
                    footprint="PCBSmith_Mechanical:BLDC_R002_Clamp_Standoff_M3",
                    uuid_path=stable_kicad_uuid(
                        "board-component-path", "bldc-esc-r002", reference
                    ),
                ),
                x,
            )
        )
        part_y.append((reference, y))
        hidden.append(reference)

    return replace(
        base,
        placements=(*base.placements, *additions),
        part_y_mm=tuple(part_y),
        part_rotation=tuple(rotations),
        hide_references=tuple(sorted(set(hidden))),
    )


def generate_bldc_esc_r002_board(
    *,
    netlist_file: Path,
    board_file: Path,
    include_heatsink: bool = True,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_bldc_esc_r002_layout(
        netlist,
        project_dir=board_file.parent,
        include_heatsink=include_heatsink,
    )
    rendered = _as_four_layer(render_board_from_layout(netlist, layout)).replace(
        "BLDC ESC R001 - PLACEMENT ONLY",
        "BLDC ESC R002 - COOLING REVIEW",
        1,
    )
    board_file.write_text(rendered, encoding="utf-8")
    return netlist, layout
