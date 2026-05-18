from __future__ import annotations

from pathlib import Path

from pcbsmith.calculators.passive import (
    led_current_limit,
    rc_highpass_cutoff_hz,
    voltage_divider,
)
from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)
from pcbsmith.core.board import Board
from pcbsmith.core.geom import Point
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire
from pcbsmith.services.project_io import save_board, save_project, save_schematic

NM = 1_000_000


def compose_divider_highpass_led(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported intent for divider/high-pass/LED composition")
    if topology.topology_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported topology for divider/high-pass/LED composition")

    divider = voltage_divider(
        input_voltage_v=5.0,
        r_top_ohms=10_000.0,
        r_bottom_ohms=10_000.0,
    )
    led = led_current_limit(
        supply_voltage_v=5.0,
        led_forward_voltage_v=2.0,
        resistor_ohms=680.0,
    )
    calculations = {
        "divider_output_voltage_v": divider["output_voltage_v"],
        "divider_current_ma": divider["divider_current_ma"],
        "highpass_cutoff_hz": rc_highpass_cutoff_hz(r_ohms=10_000.0, c_farads=100e-9),
        "led_nominal_current_ma": led["led_current_ma"],
        "led_resistor_power_w": led["resistor_power_w"],
    }
    demo_evidence = (
        EvidenceRef(
            kind="assumption",
            title="Generic passive SMD roles",
            locator="0603 R/C/LED are demo bindings until KiCad/library evidence is restored.",
        ),
    )
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=(
            ComponentRole(
                reference="R1",
                role="divider_top",
                symbol_id="stdlib:R",
                value="10k",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
            ComponentRole(
                reference="R2",
                role="divider_bottom",
                symbol_id="stdlib:R",
                value="10k",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
            ComponentRole(
                reference="C1",
                role="highpass_series_capacitor",
                symbol_id="stdlib:C",
                value="100nF",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
            ComponentRole(
                reference="R3",
                role="led_current_limit",
                symbol_id="stdlib:R",
                value="680R",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
            ComponentRole(
                reference="D1",
                role="indicator_led",
                symbol_id="stdlib:LED",
                value="Generic red LED",
                support_status="demo_only",
                evidence=demo_evidence,
            ),
        ),
        nets=("VIN", "DIV_OUT", "HP_OUT", "LED_K", "GND"),
        math=MathReport(
            status="warning",
            calculations=calculations,
            findings=(
                "LED after AC coupling is signal-dependent; deterministic LED current "
                "is only a nominal rail-reference check.",
                "Generic LED/passive bindings are demo-only until backed by real KiCad "
                "library and datasheet evidence.",
            ),
        ),
    )


def write_divider_highpass_led_project(
    circuit: CircuitObject,
    project_dir: Path,
    *,
    project_name: str,
) -> None:
    if circuit.topology.topology_id != "divider_highpass_led_indicator":
        raise ValueError("Unsupported circuit for project generation")
    project = Project(name=project_name)
    save_project(project_dir, project)
    save_schematic(project_dir, project.schematics[0], _schematic_for_divider_highpass_led())
    save_board(project_dir, project.boards[0], Board(id="main"))


def _schematic_for_divider_highpass_led() -> Schematic:
    return Schematic(
        id="main",
        symbols=(
            SymbolInstance(
                reference="P1",
                symbol_id="stdlib:CONN_01X02",
                value="5V input",
                position=Point(x=0, y=0),
            ),
            SymbolInstance(
                reference="R1",
                symbol_id="stdlib:R",
                value="10k",
                position=Point(x=15 * NM, y=0),
            ),
            SymbolInstance(
                reference="R2",
                symbol_id="stdlib:R",
                value="10k",
                position=Point(x=15 * NM, y=10 * NM),
                rotation_deg=90,
            ),
            SymbolInstance(
                reference="C1",
                symbol_id="stdlib:C",
                value="100nF",
                position=Point(x=30 * NM, y=0),
            ),
            SymbolInstance(
                reference="RLOAD",
                symbol_id="stdlib:R",
                value="10k",
                position=Point(x=45 * NM, y=10 * NM),
                rotation_deg=90,
            ),
            SymbolInstance(
                reference="R3",
                symbol_id="stdlib:R",
                value="680R",
                position=Point(x=60 * NM, y=0),
            ),
            SymbolInstance(
                reference="D1",
                symbol_id="stdlib:LED",
                value="Generic red LED",
                position=Point(x=75 * NM, y=0),
                rotation_deg=180,
            ),
            SymbolInstance(
                reference="GND1",
                symbol_id="stdlib:GND",
                value="GND",
                position=Point(x=0, y=20 * NM),
            ),
        ),
        wires=(
            Wire(points=(Point(x=0, y=0), Point(x=9_920_000, y=0))),
            Wire(points=(Point(x=20_080_000, y=0), Point(x=24_920_000, y=0))),
            Wire(points=(Point(x=15_000_000, y=4_920_000), Point(x=15_000_000, y=5_920_000))),
            Wire(points=(Point(x=15_000_000, y=15_080_000), Point(x=15_000_000, y=16_080_000))),
            Wire(points=(Point(x=35_080_000, y=0), Point(x=54_920_000, y=0))),
            Wire(points=(Point(x=45_000_000, y=4_920_000), Point(x=45_000_000, y=5_920_000))),
            Wire(points=(Point(x=45_000_000, y=15_080_000), Point(x=45_000_000, y=16_080_000))),
            Wire(points=(Point(x=65_080_000, y=0), Point(x=69_920_000, y=0))),
            Wire(points=(Point(x=80_080_000, y=0), Point(x=80_080_000, y=1_000_000))),
            Wire(points=(Point(x=0, y=2_540_000), Point(x=0, y=20_000_000))),
        ),
        labels=(
            NetLabel(name="VIN", position=Point(x=5 * NM, y=0)),
            NetLabel(name="DIV_OUT", position=Point(x=22 * NM, y=0)),
            NetLabel(name="DIV_OUT", position=Point(x=15 * NM, y=5_920_000)),
            NetLabel(name="HP_OUT", position=Point(x=50 * NM, y=0)),
            NetLabel(name="HP_OUT", position=Point(x=45 * NM, y=5_920_000)),
            NetLabel(name="GND", position=Point(x=15 * NM, y=16_080_000)),
            NetLabel(name="GND", position=Point(x=45 * NM, y=16_080_000)),
            NetLabel(name="GND", position=Point(x=80_080_000, y=1_000_000)),
            NetLabel(name="GND", position=Point(x=0, y=20 * NM)),
        ),
    )
