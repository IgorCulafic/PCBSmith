"""Readable one-sheet schematic arrangement for Retro-Pad R003.

Only drawing coordinates change here.  Pin-to-net authority remains the
verified mapping in :mod:`pcbsmith.kicad.export_retro_pad`.
"""

from __future__ import annotations

from pcbsmith.kicad.export_retro_pad import INSTANCES, SchematicInstance


def _positions() -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {
        # USB power/data chain, MCU clock/programming, and encoder are kept as
        # three visually separate blocks instead of one crowded row.
        "J1": (35.56, 58.42),
        "U2": (81.28, 58.42),
        "R3": (106.68, 50.80),
        "R4": (106.68, 66.04),
        "F1": (139.70, 58.42),
        "U1": (205.74, 58.42),
        "Y1": (264.16, 58.42),
        "J2": (307.34, 58.42),
        "SW5": (307.34, 104.14),
        # The electrical 2x2 key matrix is drawn as two roomy pairs.
        "SW1": (35.56, 127.00),
        "D1": (60.96, 127.00),
        "SW2": (101.60, 127.00),
        "D2": (127.00, 127.00),
        "SW3": (193.04, 127.00),
        "D3": (218.44, 127.00),
        "SW4": (259.08, 127.00),
        "D4": (284.48, 127.00),
        # Four addressable pixels remain in explicit DIN/DOUT order.
        "D5": (35.56, 190.50),
        "D6": (96.52, 190.50),
        "D7": (157.48, 190.50),
        "D8": (218.44, 190.50),
    }
    support_refs = (
        "R1", "R2", "R5", "R6", "R7", "R8", "R9", "R10",
        "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9",
        "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17",
    )
    for index, reference in enumerate(support_refs):
        row, column = divmod(index, 13)
        positions[reference] = (30.48 + column * 25.40, 254.00 + row * 55.88)
    return positions


def retro_pad_r003_schematic_instances() -> tuple[SchematicInstance, ...]:
    positions = _positions()
    missing = {reference for reference, *_rest in INSTANCES} - positions.keys()
    if missing:
        raise ValueError(f"R003 schematic placement is missing: {sorted(missing)}")
    return tuple(
        (reference, lib_id, *positions[reference], pin_nets)
        for reference, lib_id, _x, _y, pin_nets in INSTANCES
    )


R003_SCHEMATIC_INSTANCES = retro_pad_r003_schematic_instances()
