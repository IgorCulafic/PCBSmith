from __future__ import annotations

from pcbsmith.services.circuit_rules import (
    CIRCUIT_RULES_SCHEMA,
    check_circuit_rules,
    circuit_rules_planner_rule_notes,
    circuit_rules_tool_contract,
    format_circuit_rule_report,
)


def test_led_current_limit_rule_calculates_current_and_flags_high_current() -> None:
    report = check_circuit_rules(
        "led-current-limit",
        {
            "supply_voltage_v": 5.0,
            "led_forward_voltage_v": 2.0,
            "resistor_ohms": 100.0,
            "resistor_power_rating_w": 0.1,
        },
    )

    assert report.to_data() == {
        "schema": CIRCUIT_RULES_SCHEMA,
        "intent": "led-current-limit",
        "status": "warning",
        "calculations": {
            "calculated_current_ma": 30.0,
            "resistor_power_w": 0.09,
        },
        "findings": [
            {
                "severity": "warning",
                "code": "led_current_high",
                "message": (
                    "Calculated LED current is 30.000 mA; keep simple indicator LEDs "
                    "at or below 20 mA unless the datasheet says otherwise"
                ),
                "location": "LED string",
            },
            {
                "severity": "warning",
                "code": "resistor_power_margin_low",
                "message": (
                    "Resistor dissipation is 0.090 W, above 75% of the 0.100 W "
                    "rating"
                ),
                "location": "current-limit resistor",
            },
        ],
    }


def test_low_side_switch_rule_flags_missing_flyback_for_inductive_load() -> None:
    report = check_circuit_rules(
        "low-side-switch",
        {
            "supply_voltage_v": 12.0,
            "load_current_a": 0.5,
            "gate_drive_voltage_v": 3.3,
            "mosfet_rds_on_ohms": 0.08,
            "inductive_load": True,
            "flyback_diode_present": False,
        },
    )

    assert report.status == "warning"
    assert report.calculations == {
        "conduction_power_w": 0.02,
    }
    assert [finding.code for finding in report.findings] == [
        "missing_flyback_protection"
    ]


def test_555_astable_rule_calculates_frequency_and_flags_supply_range() -> None:
    report = check_circuit_rules(
        "555-astable",
        {
            "supply_voltage_v": 18.0,
            "ra_ohms": 10_000.0,
            "rb_ohms": 100_000.0,
            "c_farads": 0.000001,
        },
    )

    assert report.status == "warning"
    assert report.calculations == {
        "frequency_hz": 6.857,
        "duty_cycle_percent": 52.381,
    }
    assert [finding.code for finding in report.findings] == ["ne555_supply_range"]


def test_format_circuit_rule_report_is_compact_for_ai_review() -> None:
    report = check_circuit_rules(
        "rc-filter",
        {
            "r_ohms": 10_000.0,
            "c_farads": 0.0000001,
        },
    )

    assert format_circuit_rule_report(report) == [
        "Circuit rules: rc-filter",
        "Status: passed (0 findings)",
        "cutoff_frequency_hz: 159.155",
    ]


def test_circuit_rules_tool_contract_lists_supported_intents() -> None:
    assert circuit_rules_tool_contract() == {
        "schema": "pcbsmith-circuit-rules-tool-v1",
        "cli_command": "circuit-rules <intent> --param key=value",
        "supported_intents": [
            "555-astable",
            "555-pwm",
            "led-current-limit",
            "low-side-switch",
            "power-entry",
            "rc-filter",
            "voltage-divider",
        ],
        "instructions": [
            "Use circuit rules to check electrical assumptions before proposing board edits.",
            "Treat warning and error findings as revision inputs, not as fabrication approval.",
        ],
    }
    assert circuit_rules_planner_rule_notes() == [
        "Use circuit_rules supported_intents to check electrical assumptions before board edits.",
        "Do not treat a passed circuit rule report as a substitute for KiCad ERC/DRC.",
    ]
