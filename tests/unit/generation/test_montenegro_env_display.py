from pcbsmith.generation.montenegro_env_display import (
    LED_COUNT,
    compose_montenegro_env_display,
)


def test_montenegro_env_display_freezes_two_layer_presentation_architecture() -> None:
    circuit = compose_montenegro_env_display()
    by_ref = {component.reference: component for component in circuit.components}

    assert circuit.intent.assumptions["layer_count"] == 2.0
    assert circuit.intent.assumptions["board_width_mm"] == 150.0
    assert circuit.math.calculations["led_count"] == LED_COUNT
    assert sum(reference.startswith("D") for reference in by_ref) == LED_COUNT
    assert sum(reference.startswith("C") for reference in by_ref) == LED_COUNT + 7
    assert by_ref["U1"].footprint.endswith("ESP32-S3-WROOM-1_HomeFab")
    assert "SHT45" in by_ref["U4"].value
    assert "SSD1351" in by_ref["J2"].value
    assert by_ref["J1"].value == "USB4105-GF-A"


def test_montenegro_env_display_power_contract_is_explicit() -> None:
    circuit = compose_montenegro_env_display()
    calculations = circuit.math.calculations

    assert calculations["led_worst_case_current_a"] == LED_COUNT * 0.060
    assert calculations["total_worst_case_current_a"] < calculations["usb_c_design_supply_a"]
    assert calculations["supply_margin_a"] > 0
    assert circuit.math.status == "warning"
