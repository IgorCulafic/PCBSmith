"""Unrouted four-layer placement board for BLDC ESC R001.

The placement is intentionally free of tracks, pours, and routing vias.  Its
purpose is to validate exact package containment, power-cell repetition,
terminal geometry, assembly sides, and review-image coverage before any
high-current copper is committed.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path

from pcbsmith.kicad import board as board_module
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import PRIVATE_ASSET_ROOT_ENV, load_footprint
from pcbsmith.kicad.shaped_board import silk_text

BOARD_W = 140.0
BOARD_H = 90.0

CUSTOM_FOOTPRINTS = (
    "PCBSmith_Power:Texas_RTA0040B_WQFN-40-1EP",
    "PCBSmith_Power:Infineon_PG-HDSOP-16_TOLT",
    "PCBSmith_Power:Vishay_WSLP2726",
    "PCBSmith_Power:KEMET_A781_10x12.4mm_AntiVibration",
    "PCBSmith_Power:Vishay_SMPD_TO-263AC",
    "REDCUBE_THT_Wurth:MP_Wurth_WP-BUTR_7461057",
)

MOUNTING_HOLES = (
    ("H1", 5.0, 5.0),
    ("H2", 135.0, 5.0),
    ("H3", 5.0, 85.0),
    ("H4", 135.0, 85.0),
)


def _flat_asset_name(library_id: str) -> str:
    library, name = library_id.split(":", 1)
    return f"{library}__{name}.kicad_mod"


def register_project_footprints(project_dir: Path) -> None:
    """Register generated exact footprints without mutating global KiCad libraries."""
    asset_root = project_dir / ".pcbsmith" / "board-assets"
    footprint_root = asset_root / "footprints"
    footprint_root.mkdir(parents=True, exist_ok=True)
    sources = {
        "PCBSmith_Power:Texas_RTA0040B_WQFN-40-1EP": (
            project_dir / "PCBSmith_Power.pretty" / "Texas_RTA0040B_WQFN-40-1EP.kicad_mod"
        ),
        "PCBSmith_Power:Infineon_PG-HDSOP-16_TOLT": (
            project_dir / "PCBSmith_Power.pretty" / "Infineon_PG-HDSOP-16_TOLT.kicad_mod"
        ),
        "PCBSmith_Power:Vishay_WSLP2726": (
            project_dir / "PCBSmith_Power.pretty" / "Vishay_WSLP2726.kicad_mod"
        ),
        "PCBSmith_Power:KEMET_A781_10x12.4mm_AntiVibration": (
            project_dir / "PCBSmith_Power.pretty" / "KEMET_A781_10x12.4mm_AntiVibration.kicad_mod"
        ),
        "PCBSmith_Power:Vishay_SMPD_TO-263AC": (
            project_dir / "PCBSmith_Power.pretty" / "Vishay_SMPD_TO-263AC.kicad_mod"
        ),
        "REDCUBE_THT_Wurth:MP_Wurth_WP-BUTR_7461057": (
            project_dir / "REDCUBE_THT_Wurth.pretty" / "MP_Wurth_WP-BUTR_7461057.kicad_mod"
        ),
    }
    for library_id, source in sources.items():
        if not source.exists():
            raise BoardGenerationError(f"Placement footprint source is missing: {source}")
        shutil.copyfile(source, footprint_root / _flat_asset_name(library_id))

    os.environ[PRIVATE_ASSET_ROOT_ENV] = str(asset_root)
    load_footprint.cache_clear()


def _register_netlist_footprints(netlist: BoardNetlist) -> None:
    for component in netlist.components:
        if not component.footprint:
            continue
        imported = load_footprint(component.footprint)
        board_module.FOOTPRINT_LIBRARY[component.footprint] = imported.spec


def _grid(
    references: Iterable[str],
    *,
    x0: float,
    y0: float,
    columns: int,
    dx: float,
    dy: float,
) -> dict[str, tuple[float, float, float]]:
    return {
        reference: (x0 + (index % columns) * dx, y0 + (index // columns) * dy, 0.0)
        for index, reference in enumerate(references)
    }


def _pack_back_components(
    references: tuple[str, ...],
    by_ref: dict[str, BoardComponent],
    *,
    x_min: float = 42.0,
    y_min: float = 5.0,
    x_max: float = 88.0,
    y_max: float = 75.0,
    gap: float = 2.0,
) -> dict[str, tuple[float, float, float]]:
    packed: dict[str, tuple[float, float, float]] = {}
    cursor_x = x_min
    cursor_y = y_min
    row_height = 0.0
    for reference in references:
        spec = board_module.FOOTPRINT_LIBRARY[by_ref[reference].footprint]
        width = spec.x_max - spec.x_min
        height = spec.y_max - spec.y_min
        if cursor_x + width > x_max and cursor_x > x_min:
            cursor_x = x_min
            cursor_y += row_height + gap
            row_height = 0.0
        if cursor_y + height > y_max:
            raise BoardGenerationError(f"Back-side placement area exhausted at {reference}.")
        packed[reference] = (cursor_x - spec.x_min, cursor_y - spec.y_min, 0.0)
        cursor_x += width + gap
        row_height = max(row_height, height)
    return packed


def _placement_contract(
    by_ref: dict[str, BoardComponent],
) -> tuple[
    dict[str, tuple[float, float, float]],
    frozenset[str],
]:
    placements: dict[str, tuple[float, float, float]] = {
        # Opposing high-current edges and distributed DC-link bank.
        "J1": (6.8, 28.0, 0.0),
        "J2": (6.8, 62.0, 0.0),
        "J3": (132.0, 14.0, 0.0),
        "J4": (132.0, 43.0, 0.0),
        "J5": (132.0, 72.0, 0.0),
        "D1": (48.0, 12.0, 0.0),
        # Gate driver at the geometric center of the repeated phase cells.
        "U2": (82.0, 43.0, 0.0),
    }
    for index in range(8):
        column = index // 4
        row = index % 4
        placements[f"CB{index + 1}"] = (20.0 + column * 14.0, 10.0 + row * 22.0, 0.0)

    phase_rows = (14.0, 43.0, 72.0)
    for phase_index, row_y in enumerate(phase_rows):
        high = phase_index * 2 + 1
        low = high + 1
        placements[f"Q{high}"] = (99.0, row_y, 270.0)
        placements[f"Q{low}"] = (118.0, row_y, 270.0)
        placements[f"RSH{phase_index + 1}"] = (118.0, row_y + 10.5, 0.0)
        placements[f"CHF{high}"] = (86.0, row_y - 7.5, 0.0)
        placements[f"CHF{low}"] = (86.0, row_y + 7.5, 0.0)
        placements[f"RG{high}"] = (107.0, row_y - 7.0, 0.0)
        placements[f"RGS{high}"] = (111.0, row_y - 7.0, 0.0)
        placements[f"RG{low}"] = (124.0, row_y + 7.0, 0.0)
        placements[f"RGS{low}"] = (128.0, row_y + 7.0, 0.0)
        placements[f"NTC{phase_index + 1}"] = (105.0, row_y + 8.0, 0.0)

    driver_support = (
        "CCP1",
        "CVCP1",
        "CVGLS1",
        "CDVDD1",
        "CVREF1",
        "CVM1",
        "CVM2",
        "RFAULT1",
        "RSDO1",
        "REN1",
        "RBRAKE1",
        "RAGND1",
    )
    placements.update(_grid(driver_support, x0=67.0, y0=28.0, columns=2, dx=7.0, dy=5.5))

    # Back-side control and quiet-power clusters remain physically separate
    # from the exposed front-side switch nodes.
    mcu_support = (
        "RNRST1",
        "RLED1",
        "CNRST1",
        "CM1",
        "CM2",
        "CM3",
        "CM4",
        "CMA1",
        "CMA2",
    )
    buck_support = (
        "RRON1",
        "RFB1",
        "RFB2",
        "RRA1",
        "RUV1",
        "RUV2",
        "CIN1",
        "CIN2",
        "CBST1",
        "CRA1",
        "CRB1",
        "COUT1",
        "COUT2",
        "CLDOIN1",
        "CLDOOUT1",
    )
    sensing = (
        "RUH1",
        "RUH2",
        "RUL1",
        "RVH1",
        "RVH2",
        "RVL1",
        "RWH1",
        "RWH2",
        "RWL1",
        "RBATH1",
        "RBATH2",
        "RBATL1",
        "RNTC1",
        "RNTC2",
        "RNTC3",
        "CSENSE1",
        "CSENSE2",
        "CSENSE3",
        "CNTC1",
        "CNTC2",
        "CNTC3",
        "CBATS1",
    )
    back_order = (
        "U1",
        *mcu_support,
        "U3",
        "L1",
        *buck_support,
        "U4",
        "FB1",
        *sensing,
        "D2",
    )
    placements.update(_pack_back_components(back_order, by_ref))
    placements.update(
        {
            "J6": (48.0, 82.0, 0.0),
            "J7": (62.0, 82.0, 0.0),
            "J8": (80.0, 82.0, 90.0),
        }
    )
    back_refs = {*back_order, "J6", "J7", "J8"}
    return placements, frozenset(back_refs)


def compute_bldc_esc_placement_layout(
    netlist: BoardNetlist,
    *,
    project_dir: Path,
) -> BoardLayout:
    register_project_footprints(project_dir)
    _register_netlist_footprints(netlist)
    by_ref = {component.reference: component for component in netlist.components}
    contract, back_refs = _placement_contract(by_ref)
    expected = {reference for reference, component in by_ref.items() if component.footprint}
    missing = expected - contract.keys()
    unknown = contract.keys() - expected
    if missing or unknown:
        detail = f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        raise BoardGenerationError(f"BLDC placement contract mismatch; {detail}")

    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    rotations: list[tuple[str, float]] = []
    for reference, (x, y, rotation) in contract.items():
        placements.append((by_ref[reference], x))
        part_y.append((reference, y))
        if rotation:
            rotations.append((reference, rotation))
    for reference, x, y in MOUNTING_HOLES:
        placements.append(
            (
                BoardComponent(
                    reference=reference,
                    value="M3 NPTH",
                    footprint="MountingHole:MountingHole_3.2mm_M3",
                    uuid_path=stable_kicad_uuid("board-component-path", "bldc-esc-r001", reference),
                ),
                x,
            )
        )
        part_y.append((reference, y))

    graphics = (
        silk_text("BLDC ESC R001 - PLACEMENT ONLY", (49.0, 3.0), BOARD_SHEET_ORIGIN_MM),
        silk_text("BAT+", (2.0, 20.0), BOARD_SHEET_ORIGIN_MM),
        silk_text("BAT-", (2.0, 54.0), BOARD_SHEET_ORIGIN_MM),
        silk_text("PHASE U", (123.0, 5.0), BOARD_SHEET_ORIGIN_MM),
        silk_text("PHASE V", (123.0, 34.0), BOARD_SHEET_ORIGIN_MM),
        silk_text("PHASE W", (123.0, 63.0), BOARD_SHEET_ORIGIN_MM),
    )
    # Alternate long reference labels above and below the dense back-side
    # passives.  The component courtyards already clear; this keeps the
    # assembly-identification silk legible without hiding those references.
    reference_at = (
        ("D1", (0.0, 9.3, 0.0)),
        ("Q2", (-6.3, 0.0, 0.0)),
        ("Q4", (-6.3, 0.0, 0.0)),
        ("Q6", (-6.3, 0.0, 0.0)),
        ("CLDOOUT1", (0.0, 1.68, 0.0)),
        ("RBATH2", (0.0, -2.8, 0.0)),
        ("CSENSE1", (0.0, 1.43, 0.0)),
        ("CSENSE3", (0.0, 1.43, 0.0)),
    )
    return BoardLayout(
        placements=tuple(placements),
        segments=(),
        vias=(),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(rotations),
        graphics=graphics,
        part_flip=tuple(sorted(back_refs)),
        part_reference_at=reference_at,
    )


def _as_four_layer(board_text: str) -> str:
    old = '    (0 "F.Cu" signal)\n    (31 "B.Cu" signal)'
    new = (
        '    (0 "F.Cu" signal)\n'
        '    (2 "In1.Cu" power)\n'
        '    (4 "In2.Cu" power)\n'
        '    (31 "B.Cu" signal)'
    )
    if old not in board_text:
        raise BoardGenerationError("Could not promote rendered board to four copper layers.")
    board_text = board_text.replace(old, new, 1)
    missing_model_replacements = {
        (
            "${KICAD10_3DMODEL_DIR}/Package_SO.3dshapes/"
            "SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.71x3.4mm.step"
        ): "${KIPRJMOD}/models/lm5164-dda-envelope.wrl",
        (
            "${KICAD10_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/"
            "DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm.step"
        ): "${KIPRJMOD}/models/tlv767-drb-envelope.wrl",
    }
    for unresolved, proxy in missing_model_replacements.items():
        if unresolved not in board_text:
            raise BoardGenerationError(
                f"Expected unresolved model path was not found: {unresolved}"
            )
        board_text = board_text.replace(unresolved, proxy, 1)
    return board_text


def generate_bldc_esc_placement_board(
    *,
    netlist_file: Path,
    board_file: Path,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_bldc_esc_placement_layout(netlist, project_dir=board_file.parent)
    rendered = render_board_from_layout(netlist, layout)
    board_file.write_text(_as_four_layer(rendered), encoding="utf-8")
    return netlist, layout
