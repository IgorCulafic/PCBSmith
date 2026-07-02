"""LED text-matrix composition: glyphs on a 5-row dot grid.

Each glyph column becomes one series string (resistor + 1..5 LEDs) across the
supply, so every series link on the board is a short vertical hop inside its
own column and the two power rails close the circuit. The string resistor is
sized by the deterministic series-string calculator from the datasheet-backed
LED forward voltage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pcbsmith.calculators.electronics import solve_led_series_string
from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)
from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic
from pcbsmith.services.project_io import save_board, save_project, save_schematic

SUPPORTED_TOPOLOGY_ID = "led_text_matrix"
GRID_ROWS = 5
MAX_STRING_LEDS = 5

# Per glyph: one tuple per column, each listing the lit rows top (0) to
# bottom (4). Column counts differ per glyph; a space is one empty column.
GLYPHS_5ROW: dict[str, tuple[tuple[int, ...], ...]] = {
    "I": ((0, 4), (0, 1, 2, 3, 4), (0, 4)),
    "G": ((1, 2, 3), (0, 4), (0, 2, 4), (2, 3, 4)),
    "O": ((1, 2, 3), (0, 4), (0, 4), (1, 2, 3)),
    "R": ((0, 1, 2, 3, 4), (0, 2), (0, 2, 3), (1, 4)),
    "C": ((1, 2, 3), (0, 4), (0, 4), (0, 4)),
    ".": ((4,),),
    " ": ((),),
}


@dataclass(frozen=True)
class LedString:
    """One glyph column: resistor feeding LEDs in supply-to-ground order."""

    resistor_ref: str
    led_refs: tuple[str, ...]
    column: int
    rows: tuple[int, ...]
    resistor_ohms: float


@dataclass(frozen=True)
class LedArtPlan:
    text: str
    strings: tuple[LedString, ...]
    total_columns: int


def plan_led_text(text: str, *, string_solutions: dict[int, float]) -> LedArtPlan:
    unsupported = sorted({char for char in text if char not in GLYPHS_5ROW})
    if unsupported:
        raise ValueError(
            "No 5-row glyph is defined for: "
            + ", ".join(repr(char) for char in unsupported)
            + f". Supported: {', '.join(sorted(GLYPHS_5ROW))}"
        )
    strings: list[LedString] = []
    column = 0
    led_counter = 0
    for index, char in enumerate(text):
        if index > 0:
            column += 1  # one empty gap column between glyphs
        for rows in GLYPHS_5ROW[char]:
            if rows:
                led_refs = tuple(
                    f"D{led_counter + offset + 1}" for offset in range(len(rows))
                )
                led_counter += len(rows)
                strings.append(
                    LedString(
                        resistor_ref=f"R{len(strings) + 1}",
                        led_refs=led_refs,
                        column=column,
                        rows=rows,
                        resistor_ohms=string_solutions[len(rows)],
                    )
                )
            column += 1
    if not strings:
        raise ValueError("The requested text lights no LEDs.")
    return LedArtPlan(text=text, strings=tuple(strings), total_columns=column)


def compose_led_art(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> tuple[CircuitObject, LedArtPlan]:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for LED art composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for LED art composition")

    text = str(intent.assumptions["text"])
    supply_v = float(intent.assumptions["supply_voltage_v"])
    forward_v = float(intent.assumptions["led_forward_voltage_v"])
    target_a = float(intent.assumptions["led_target_current_a"])

    counts_needed = sorted(
        {
            len(rows)
            for char in text
            for rows in GLYPHS_5ROW.get(char, ())
            if rows
        }
    )
    calculations: dict[str, float] = {
        "supply_voltage_v": supply_v,
        "led_forward_voltage_v": forward_v,
        "led_target_current_a": target_a,
    }
    findings: list[str] = []
    string_solutions: dict[int, float] = {}
    string_currents: dict[int, float] = {}
    for count in counts_needed:
        result = solve_led_series_string(
            supply_voltage_v=supply_v,
            led_forward_voltage_v=forward_v,
            target_current_a=target_a,
            led_count=count,
        )
        if result["status"] == "error":
            raise ValueError(
                "LED string calculator rejected the request: "
                + "; ".join(result["errors"])
            )
        outputs = result["outputs"]
        string_solutions[count] = float(outputs["selected_resistor_ohms"])
        string_currents[count] = float(outputs["current_with_selected_a"])
        calculations[f"string_{count}_led_resistor_ohms"] = outputs["resistor_ohms"]
        calculations[f"string_{count}_led_selected_ohms"] = outputs[
            "selected_resistor_ohms"
        ]
        calculations[f"string_{count}_led_current_a"] = outputs[
            "current_with_selected_a"
        ]
        calculations[f"string_{count}_led_resistor_w"] = outputs["resistor_power_w"]
        findings.extend(str(warning) for warning in result["warnings"])

    plan = plan_led_text(text, string_solutions=string_solutions)
    total_current_a = sum(
        string_currents[len(string.rows)] for string in plan.strings
    )
    calculations["string_count"] = float(len(plan.strings))
    calculations["led_count"] = float(
        sum(len(string.led_refs) for string in plan.strings)
    )
    calculations["total_supply_current_a"] = round(total_current_a, 6)

    led_evidence = (
        EvidenceRef(
            kind="datasheet_fact",
            title="Kingbright LED forward voltage, extracted datasheet fact",
            locator=(
                "ai_assets/evidence/divider-highpass-led.manifest.json: "
                "VF typ 1.85 V"
            ),
        ),
    )
    formula_evidence = (
        EvidenceRef(
            kind="textbook_formula",
            title="Series LED string resistor equation",
            locator="R = (Vsupply - n*Vf) / I_target",
        ),
    )
    components: list[ComponentRole] = [
        ComponentRole(
            reference="P1",
            role="input_connector",
            symbol_id="stdlib:CONN_01X02",
            value=f"{supply_v:g}V input",
            support_status="demo_only",
            footprint=(
                "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
            ),
            evidence=formula_evidence,
        ),
    ]
    for string in plan.strings:
        components.append(
            ComponentRole(
                reference=string.resistor_ref,
                role="string_resistor",
                symbol_id="stdlib:R",
                value=f"{string.resistor_ohms:g}",
                support_status="demo_only",
                footprint="Resistor_SMD:R_0603_1608Metric",
                evidence=formula_evidence,
            )
        )
        for led_ref in string.led_refs:
            components.append(
                ComponentRole(
                    reference=led_ref,
                    role="matrix_led",
                    symbol_id="stdlib:LED",
                    value="LED",
                    support_status="needs_datasheet_review",
                    footprint="LED_SMD:LED_0603_1608Metric",
                    evidence=led_evidence,
                )
            )

    circuit = CircuitObject(
        intent=intent,
        topology=topology,
        components=tuple(components),
        nets=("VIN", "GND"),
        math=MathReport(
            status="warning" if findings else "passed",
            calculations=calculations,
            findings=tuple(findings),
        ),
    )
    return circuit, plan


def write_led_art_project(
    circuit: CircuitObject,
    project_dir: Path,
    *,
    project_name: str,
) -> None:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for project generation")
    project = Project(name=project_name)
    save_project(project_dir, project)
    save_schematic(project_dir, project.schematics[0], Schematic(id="main"))
    save_board(project_dir, project.boards[0], Board(id="main"))
