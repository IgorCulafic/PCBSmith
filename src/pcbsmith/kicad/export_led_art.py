"""KiCad schematic exporter for the LED text-matrix topology.

The schematic is *data*, not code: the topology declares a ladder spec (one
column per glyph string, elements in supply-to-ground order) and the generic
builder in `kicad/schematic_builder.py` renders it. The board layout is
where the glyph geometry appears.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.generation.led_art import LedArtPlan
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SYMBOL_LIBRARY_VERSION,
    _led_symbol_drawing,
    _render_connector_01x02_library_symbol,
    _render_project,
    _render_symbol_table,
    _render_two_pin_box_library_symbol,
    _resistor_symbol_drawing,
    _validate_project_name,
)
from pcbsmith.kicad.schematic_builder import (
    LadderElement,
    LadderSpec,
    render_ladder_schematic,
)

SUPPORTED_TOPOLOGY_ID = "led_text_matrix"


def ladder_spec_for(plan: LedArtPlan) -> LadderSpec:
    return LadderSpec(
        columns=tuple(
            (
                LadderElement(reference=string.resistor_ref, lib_id="PCBSmith:R"),
                *(
                    LadderElement(reference=led_ref, lib_id="PCBSmith:LED")
                    for led_ref in string.led_refs
                ),
            )
            for string in plan.strings
        ),
    )


def export_led_art_to_kicad(
    circuit: CircuitObject,
    plan: LedArtPlan,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for KiCad export")
    project_name = _validate_project_name(project_name)

    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"
    symbol_library = output_dir / "PCBSmith.kicad_sym"
    symbol_table = output_dir / "sym-lib-table"

    schematic = render_ladder_schematic(
        circuit,
        ladder_spec_for(plan),
        project_name=project_name,
        library_symbols=_render_library_symbols(name_prefix="PCBSmith:"),
        junction_label=lambda column, link: f"S{column + 1}_{link + 1}",
    )

    project_file.write_text(_render_project(), encoding="utf-8")
    symbol_table.write_text(_render_symbol_table(), encoding="utf-8")
    symbol_library.write_text(_render_symbol_library(), encoding="utf-8")
    schematic_file.write_text(schematic, encoding="utf-8")
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
        "symbol_library": str(symbol_library),
    }


def _render_symbol_library() -> str:
    return f"""(kicad_symbol_lib
  (version {KICAD_SYMBOL_LIBRARY_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
{_render_library_symbols(name_prefix="")}
)
"""


def _render_library_symbols(*, name_prefix: str) -> str:
    return "\n\n".join(
        (
            _render_two_pin_box_library_symbol(
                f"{name_prefix}R",
                reference="R",
                value="R",
                description="Generic resistor",
                drawing=_resistor_symbol_drawing(),
                pin_length_mm="2.54",
            ),
            _render_two_pin_box_library_symbol(
                f"{name_prefix}LED",
                reference="D",
                value="LED",
                description="Matrix LED",
                drawing=_led_symbol_drawing(),
                pin_length_mm="3.81",
                pin_one_at="right",
            ),
            _render_connector_01x02_library_symbol(f"{name_prefix}CONN_01X02"),
        )
    )
