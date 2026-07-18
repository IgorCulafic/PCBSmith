"""Topology-as-data schematic generation.

A topology that fits the *ladder* pattern — parallel columns of stacked
two-pin elements between a top supply rail and a bottom return rail, fed by
one edge connector — no longer needs a hand-written KiCad exporter. It
declares a :class:`LadderSpec` (which references go in which column, in
supply-to-ground order) and this builder emits the schematic: symbols,
gap wires, per-junction labels (rule 7.2: every net is labelled), and the
segmented rails whose T-joints KiCad's connectivity requires.

The LED text matrix is the first topology expressed this way; the divider
and buck exporters remain hand-written until their patterns (mid-column
taps, multi-pin ICs) get their own specs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    _label,
    _symbol,
    _wire,
)
from pcbsmith.kicad.identity import stable_kicad_uuid

COLUMN_PITCH_MM = 10.16
FIRST_COLUMN_X_MM = 25.4
ELEMENT_PITCH_MM = 12.7
FIRST_ELEMENT_Y_MM = 35.56
PIN_TIP_OFFSET_MM = 5.08
TOP_RAIL_Y_MM = 25.4
BOTTOM_RAIL_Y_MM = 114.3
CONNECTOR_X_MM = 15.24
CONNECTOR_Y_MM = 50.8
CONNECTOR_TOP_STUB_X_MM = 17.78
CONNECTOR_BOTTOM_STUB_X_MM = 12.7
# Rotation 270 puts the LEFT symbol pin at the TOP. With KiCad pin numbering
# (rule 8.4) polarized parts then face their anode/positive pin 2 toward the
# supply rail, so current flows top rail -> pin 2 -> pin 1 -> next element.
ELEMENT_ROTATION = 270


@dataclass(frozen=True)
class LadderElement:
    reference: str
    lib_id: str


@dataclass(frozen=True)
class LadderSpec:
    """Declarative ladder schematic: columns of stacked two-pin elements."""

    columns: tuple[tuple[LadderElement, ...], ...]
    connector_reference: str = "P1"
    connector_lib_id: str = "PCBSmith:CONN_01X02"
    top_rail: str = "VIN"
    bottom_rail: str = "GND"


def render_ladder_schematic(
    circuit: CircuitObject,
    spec: LadderSpec,
    *,
    project_name: str,
    library_symbols: str,
    junction_label: Callable[[int, int], str],
    paper: str = "A3",
) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }
    missing = [
        element.reference
        for column in spec.columns
        for element in column
        if element.reference not in fields
    ]
    if spec.connector_reference not in fields:
        missing.append(spec.connector_reference)
    if missing:
        raise ValueError(
            "Ladder schematic missing required components: " + ", ".join(missing)
        )

    def sym(lib: str, reference: str, x_mm: float, y_mm: float, rotation: int) -> str:
        value, footprint = fields[reference]
        return _symbol(
            lib,
            reference,
            value,
            x_mm,
            y_mm,
            project_name,
            rotation=rotation,
            exclude_from_sim=True,
            footprint=footprint,
        )

    symbols: list[str] = [
        sym(spec.connector_lib_id, spec.connector_reference, CONNECTOR_X_MM, CONNECTOR_Y_MM, 0)
    ]
    wires: list[str] = [
        # Connector pin 1 detours right, then up to the top rail, staying
        # clear of the pin-2 tip directly above the anchor.
        _wire((CONNECTOR_X_MM, CONNECTOR_Y_MM), (CONNECTOR_TOP_STUB_X_MM, CONNECTOR_Y_MM)),
        _wire(
            (CONNECTOR_TOP_STUB_X_MM, CONNECTOR_Y_MM),
            (CONNECTOR_TOP_STUB_X_MM, TOP_RAIL_Y_MM),
        ),
        _wire(
            (CONNECTOR_X_MM, CONNECTOR_Y_MM - 2.54),
            (CONNECTOR_BOTTOM_STUB_X_MM, CONNECTOR_Y_MM - 2.54),
        ),
        _wire(
            (CONNECTOR_BOTTOM_STUB_X_MM, CONNECTOR_Y_MM - 2.54),
            (CONNECTOR_BOTTOM_STUB_X_MM, BOTTOM_RAIL_Y_MM),
        ),
    ]
    labels: list[str] = []
    top_taps: list[float] = [CONNECTOR_TOP_STUB_X_MM]
    bottom_taps: list[float] = [CONNECTOR_BOTTOM_STUB_X_MM]

    for column_index, column in enumerate(spec.columns):
        x = FIRST_COLUMN_X_MM + column_index * COLUMN_PITCH_MM
        top_taps.append(x)
        bottom_taps.append(x)
        for position, element in enumerate(column):
            y = FIRST_ELEMENT_Y_MM + position * ELEMENT_PITCH_MM
            symbols.append(sym(element.lib_id, element.reference, x, y, ELEMENT_ROTATION))
        first_top = FIRST_ELEMENT_Y_MM - PIN_TIP_OFFSET_MM
        wires.append(_wire((x, TOP_RAIL_Y_MM), (x, first_top)))
        for position in range(len(column) - 1):
            upper_bottom = (
                FIRST_ELEMENT_Y_MM + position * ELEMENT_PITCH_MM + PIN_TIP_OFFSET_MM
            )
            lower_top = (
                FIRST_ELEMENT_Y_MM
                + (position + 1) * ELEMENT_PITCH_MM
                - PIN_TIP_OFFSET_MM
            )
            wires.append(_wire((x, upper_bottom), (x, lower_top)))
            # Rule 7.2: kicad-cli silently drops UNLABELLED nets from both
            # ERC connectivity and the exported netlist.
            labels.append(
                _label(
                    junction_label(column_index, position),
                    x,
                    (upper_bottom + lower_top) / 2,
                )
            )
        last_bottom = (
            FIRST_ELEMENT_Y_MM + (len(column) - 1) * ELEMENT_PITCH_MM + PIN_TIP_OFFSET_MM
        )
        wires.append(_wire((x, last_bottom), (x, BOTTOM_RAIL_Y_MM)))

    # Rails segmented at every tap so KiCad connectivity sees T junctions.
    for taps, rail_y in ((top_taps, TOP_RAIL_Y_MM), (bottom_taps, BOTTOM_RAIL_Y_MM)):
        ordered = sorted(set(taps))
        for left, right in zip(ordered, ordered[1:], strict=False):
            wires.append(_wire((left, rail_y), (right, rail_y)))

    labels.append(
        _label(spec.top_rail, (CONNECTOR_TOP_STUB_X_MM + FIRST_COLUMN_X_MM) / 2, TOP_RAIL_Y_MM)
    )
    labels.append(
        _label(
            spec.bottom_rail,
            (CONNECTOR_BOTTOM_STUB_X_MM + FIRST_COLUMN_X_MM) / 2,
            BOTTOM_RAIL_Y_MM,
        )
    )
    items = "\n".join((*symbols, *wires, *labels))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {stable_kicad_uuid(
      "schematic-root",
      "machine",
      project_name,
      circuit.topology.topology_id,
  )})
  (paper "{paper}")

  (lib_symbols
{library_symbols}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
