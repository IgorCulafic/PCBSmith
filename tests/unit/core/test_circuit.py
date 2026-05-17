from __future__ import annotations

import pytest

from pcbsmith.core.circuit import (
    CircuitComponent,
    CircuitDesign,
    CircuitNet,
    CircuitPin,
    compose_circuit_designs,
)


def test_compose_circuit_designs_merges_named_nets_and_preserves_components() -> None:
    led_block = CircuitDesign(
        name="led-block",
        components=(
            CircuitComponent(
                reference="R1",
                symbol_id="stdlib:R",
                value="680",
                pins=(
                    CircuitPin(number="1", net="VCC"),
                    CircuitPin(number="2", net="LED_A"),
                ),
            ),
            CircuitComponent(
                reference="LED1",
                symbol_id="stdlib:LED",
                value="Red LED",
                pins=(
                    CircuitPin(number="1", net="LED_A"),
                    CircuitPin(number="2", net="GND"),
                ),
            ),
        ),
        nets=(CircuitNet(name="VCC"), CircuitNet(name="LED_A"), CircuitNet(name="GND")),
    )
    power_block = CircuitDesign(
        name="power",
        components=(
            CircuitComponent(
                reference="J1",
                symbol_id="stdlib:CONN_01X02",
                value="5V IN",
                pins=(
                    CircuitPin(number="1", net="VCC"),
                    CircuitPin(number="2", net="GND"),
                ),
            ),
        ),
        nets=(CircuitNet(name="VCC"), CircuitNet(name="GND")),
    )

    design = compose_circuit_designs("combined", power_block, led_block)

    assert [component.reference for component in design.components] == ["J1", "R1", "LED1"]
    assert sorted(net.name for net in design.nets) == ["GND", "LED_A", "VCC"]


def test_compose_circuit_designs_rejects_duplicate_references() -> None:
    first = CircuitDesign(
        name="a",
        components=(CircuitComponent(reference="R1", symbol_id="stdlib:R", value="1k"),),
    )
    second = CircuitDesign(
        name="b",
        components=(CircuitComponent(reference="R1", symbol_id="stdlib:R", value="330"),),
    )

    with pytest.raises(ValueError, match="Duplicate circuit component reference"):
        compose_circuit_designs("bad", first, second)


def test_circuit_design_rejects_component_pin_referencing_undeclared_net() -> None:
    with pytest.raises(ValueError, match="uses undeclared net"):
        CircuitDesign(
            name="bad",
            components=(
                CircuitComponent(
                    reference="R1",
                    symbol_id="stdlib:R",
                    value="1k",
                    pins=(CircuitPin(number="1", net="MISSING"),),
                ),
            ),
            nets=(CircuitNet(name="VCC"),),
        )
