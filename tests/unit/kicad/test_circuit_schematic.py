from __future__ import annotations

from uuid import UUID

from pcbsmith.core.circuit import CircuitComponent, CircuitDesign, CircuitNet, CircuitPin
from pcbsmith.kicad.circuit_schematic import circuit_design_to_schematic
from pcbsmith.kicad.kicad_export import render_kicad_schematic_items
from pcbsmith.kicad.kicad_project import render_kicad_schematic_file


def test_circuit_design_to_schematic_places_components_and_net_labels() -> None:
    circuit = CircuitDesign(
        name="simple-led",
        components=(
            CircuitComponent(
                reference="J1",
                symbol_id="stdlib:CONN_01X02",
                value="5V IN",
                pins=(CircuitPin(number="1", net="VCC"), CircuitPin(number="2", net="GND")),
            ),
            CircuitComponent(
                reference="R1",
                symbol_id="stdlib:R",
                value="680",
                pins=(CircuitPin(number="1", net="VCC"), CircuitPin(number="2", net="LED_A")),
            ),
            CircuitComponent(
                reference="LED1",
                symbol_id="stdlib:LED",
                value="Red LED",
                pins=(CircuitPin(number="1", net="LED_A"), CircuitPin(number="2", net="GND")),
            ),
        ),
        nets=(CircuitNet(name="VCC"), CircuitNet(name="LED_A"), CircuitNet(name="GND")),
    )

    schematic = circuit_design_to_schematic(circuit)

    assert [symbol.reference for symbol in schematic.symbols] == ["J1", "R1", "LED1"]
    assert {label.name for label in schematic.labels} == {"VCC", "LED_A", "GND"}
    assert len(schematic.wires) == 6
    connector_labels = {
        label.name: label.position
        for label in schematic.labels
        if label.name in {"VCC", "GND"}
        and any(point == label.position for wire in schematic.wires[:2] for point in wire.points)
    }
    assert connector_labels["VCC"].y != connector_labels["GND"].y


def test_circuit_design_renders_as_non_empty_kicad_schematic() -> None:
    circuit = CircuitDesign(
        name="simple-led",
        components=(
            CircuitComponent(
                reference="R1",
                symbol_id="stdlib:R",
                value="680",
                pins=(CircuitPin(number="1", net="VCC"), CircuitPin(number="2", net="LED_A")),
            ),
            CircuitComponent(
                reference="LED1",
                symbol_id="stdlib:LED",
                value="Red LED",
                pins=(CircuitPin(number="1", net="LED_A"), CircuitPin(number="2", net="GND")),
            ),
        ),
        nets=(CircuitNet(name="VCC"), CircuitNet(name="LED_A"), CircuitNet(name="GND")),
    )
    schematic = circuit_design_to_schematic(circuit)

    body = render_kicad_schematic_file(
        UUID("00000000-0000-0000-0000-000000000001"),
        render_kicad_schematic_items(
            schematic,
            project_name="Circuit_Schematic_Test",
            uuid_factory=_fixed_uuid,
        ),
    )

    assert '(lib_id "PCBSmith:R")' in body
    assert '(lib_id "PCBSmith:LED")' in body
    assert '(property "Reference" "R1"' in body
    assert '(property "Reference" "LED1"' in body
    assert '(label "LED_A"' in body


def _fixed_uuid() -> UUID:
    return UUID("00000000-0000-0000-0000-000000000002")
