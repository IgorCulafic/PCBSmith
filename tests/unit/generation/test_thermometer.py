"""Thermometer display composition."""

from __future__ import annotations

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.thermometer import compose_thermometer

REQUEST = (
    "Design a fully functional PCB in the shape of a classic glass "
    "thermometer with a temperature and humidity display"
)


def _circuit():
    intent = classify_circuit_intent(REQUEST)
    assert intent.intent_id == "thermometer_env_display"
    return compose_thermometer(intent, select_topology(intent))


def test_composition_carries_the_brief() -> None:
    circuit = _circuit()
    by_ref = {c.reference: c for c in circuit.components}
    # 16 mercury LEDs + their resistors + the power LED.
    assert all(f"D{i}" in by_ref for i in range(1, 17))
    assert all(by_ref[f"R{i}"].value == "270R" for i in range(1, 17))
    assert by_ref["D17"].role == "power_led"
    # The chosen parts.
    assert by_ref["U1"].value == "ESP32-C3-WROOM-02"
    assert by_ref["U4"].value == "SHT31-DIS"
    assert by_ref["U2"].value == by_ref["U3"].value == "74HC595"
    assert by_ref["U5"].value == "AP2112K-3.3"
    assert by_ref["J1"].role == "usb_c_receptacle"
    # Two OLED headers, one per I2C bus.
    assert by_ref["J2"].role == by_ref["J3"].role == "oled_header"
    # Strapping and OE discipline from the datasheets.
    assert by_ref["ROE1"].role == "oe_pullup"
    assert sum(1 for c in circuit.components if c.role == "strap_pullup") == 2


def test_findings_are_honest() -> None:
    circuit = _circuit()
    text = " ".join(circuit.math.findings)
    assert "WiFi" in text            # LDO thermal truth
    assert "OLED" in text            # module assumption
    assert "OMITTED" in text         # battery/ESD decisions
    assert "FIRMWARE CONTRACT" in text
    assert "LED16>=50" in text.replace(" ", "")


def test_blocks_match_the_composition() -> None:
    from pcbsmith.generation.blocks import MODULE_REGISTRY

    circuit = _circuit()
    composed = {c.reference: c for c in circuit.components}
    for name, refs in (
        ("usb-c-power-entry", ["J1", "F1", "RCC1", "RCC2"]),
        ("ldo-3v3-rail", ["U5", "C5", "C6", "D17", "R17"]),
    ):
        entry = MODULE_REGISTRY[name]
        parts = entry.builder()
        assert [c.reference for c in parts] == refs
        for part in parts:
            assert composed[part.reference] == part
