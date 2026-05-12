from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

CIRCUIT_RULES_SCHEMA = "pcbsmith-circuit-rules-v1"
CIRCUIT_RULES_TOOL_SCHEMA = "pcbsmith-circuit-rules-tool-v1"

SUPPORTED_CIRCUIT_RULE_INTENTS = (
    "555-astable",
    "555-pwm",
    "led-current-limit",
    "low-side-switch",
    "power-entry",
    "rc-filter",
    "voltage-divider",
)


class CircuitRuleSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class CircuitRuleFinding:
    severity: CircuitRuleSeverity
    code: str
    message: str
    location: str


@dataclass(frozen=True)
class CircuitRuleReport:
    intent: str
    calculations: dict[str, float]
    findings: tuple[CircuitRuleFinding, ...]

    @property
    def status(self) -> str:
        if any(finding.severity is CircuitRuleSeverity.ERROR for finding in self.findings):
            return "error"
        if self.findings:
            return "warning"
        return "passed"

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "error" else 0

    def to_data(self) -> dict[str, Any]:
        return {
            "schema": CIRCUIT_RULES_SCHEMA,
            "intent": self.intent,
            "status": self.status,
            "calculations": self.calculations,
            "findings": [
                {
                    "severity": finding.severity.value,
                    "code": finding.code,
                    "message": finding.message,
                    "location": finding.location,
                }
                for finding in self.findings
            ],
        }


def check_circuit_rules(
    intent: str,
    parameters: dict[str, Any],
) -> CircuitRuleReport:
    if intent == "led-current-limit":
        return _check_led_current_limit(parameters)
    if intent == "low-side-switch":
        return _check_low_side_switch(parameters)
    if intent == "555-astable":
        return _check_555_astable(parameters)
    if intent == "555-pwm":
        return _check_555_pwm(parameters)
    if intent == "rc-filter":
        return _check_rc_filter(parameters)
    if intent == "voltage-divider":
        return _check_voltage_divider(parameters)
    if intent == "power-entry":
        return _check_power_entry(parameters)
    raise ValueError(f"Unsupported circuit rule intent: {intent}")


def check_circuit_rules_file(
    intent: str,
    parameters_path: Path,
) -> CircuitRuleReport:
    data = json.loads(parameters_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected circuit rule parameters JSON object: {parameters_path}")
    return check_circuit_rules(intent, data)


def parse_rule_parameters(values: tuple[str, ...]) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        if not separator or not key:
            raise ValueError(f"Expected --param key=value, got: {value}")
        parameters[key] = _parse_parameter_value(raw)
    return parameters


def format_circuit_rule_report(report: CircuitRuleReport) -> list[str]:
    finding_label = "finding" if len(report.findings) == 1 else "findings"
    lines = [
        f"Circuit rules: {report.intent}",
        f"Status: {report.status} ({len(report.findings)} {finding_label})",
    ]
    for key, value in report.calculations.items():
        lines.append(f"{key}: {_format_number(value)}")
    lines.extend(
        (
            f"{finding.severity}: {finding.code}: {finding.message} "
            f"({finding.location})"
        )
        for finding in report.findings
    )
    return lines


def circuit_rules_tool_contract() -> dict[str, Any]:
    return {
        "schema": CIRCUIT_RULES_TOOL_SCHEMA,
        "cli_command": "circuit-rules <intent> --param key=value",
        "supported_intents": list(SUPPORTED_CIRCUIT_RULE_INTENTS),
        "instructions": [
            "Use circuit rules to check electrical assumptions before proposing board edits.",
            "Treat warning and error findings as revision inputs, not as fabrication approval.",
        ],
    }


def circuit_rules_planner_rule_notes() -> list[str]:
    return [
        "Use circuit_rules supported_intents to check electrical assumptions before board edits.",
        "Do not treat a passed circuit rule report as a substitute for KiCad ERC/DRC.",
    ]


def write_circuit_rule_report(report: CircuitRuleReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_data(), indent=2) + "\n", encoding="utf-8")


def _check_led_current_limit(parameters: dict[str, Any]) -> CircuitRuleReport:
    supply_voltage_v = _positive_float(parameters, "supply_voltage_v")
    led_forward_voltage_v = _positive_float(parameters, "led_forward_voltage_v")
    resistor_ohms = _positive_float(parameters, "resistor_ohms")
    resistor_power_rating_w = _optional_positive_float(
        parameters,
        "resistor_power_rating_w",
        default=0.125,
    )
    findings: list[CircuitRuleFinding] = []
    calculations: dict[str, float] = {}

    if led_forward_voltage_v >= supply_voltage_v:
        findings.append(
            _error(
                "led_forward_voltage_exceeds_supply",
                "LED forward voltage must be below the supply voltage",
                "LED string",
            )
        )
        return CircuitRuleReport("led-current-limit", calculations, tuple(findings))

    current_a = (supply_voltage_v - led_forward_voltage_v) / resistor_ohms
    current_ma = _round(current_a * 1000.0)
    resistor_power_w = _round((current_a * current_a) * resistor_ohms)
    calculations.update(
        {
            "calculated_current_ma": current_ma,
            "resistor_power_w": resistor_power_w,
        }
    )
    if current_ma > 20.0:
        findings.append(
            _warning(
                "led_current_high",
                (
                    f"Calculated LED current is {current_ma:.3f} mA; keep simple "
                    "indicator LEDs at or below 20 mA unless the datasheet says otherwise"
                ),
                "LED string",
            )
        )
    if resistor_power_w > resistor_power_rating_w:
        findings.append(
            _error(
                "resistor_power_exceeds_rating",
                (
                    f"Resistor dissipation is {resistor_power_w:.3f} W, above the "
                    f"{resistor_power_rating_w:.3f} W rating"
                ),
                "current-limit resistor",
            )
        )
    elif resistor_power_w >= resistor_power_rating_w * 0.75:
        findings.append(
            _warning(
                "resistor_power_margin_low",
                (
                    f"Resistor dissipation is {resistor_power_w:.3f} W, above 75% "
                    f"of the {resistor_power_rating_w:.3f} W rating"
                ),
                "current-limit resistor",
            )
        )
    return CircuitRuleReport("led-current-limit", calculations, tuple(findings))


def _check_low_side_switch(parameters: dict[str, Any]) -> CircuitRuleReport:
    _positive_float(parameters, "supply_voltage_v")
    load_current_a = _positive_float(parameters, "load_current_a")
    gate_drive_voltage_v = _positive_float(parameters, "gate_drive_voltage_v")
    threshold_v = _optional_positive_float(parameters, "mosfet_vgs_threshold_v", default=0.0)
    rds_on_ohms = _optional_positive_float(parameters, "mosfet_rds_on_ohms", default=0.0)
    inductive_load = _bool(parameters, "inductive_load", default=False)
    flyback_present = _bool(parameters, "flyback_diode_present", default=False)

    calculations: dict[str, float] = {}
    findings: list[CircuitRuleFinding] = []
    if rds_on_ohms > 0:
        calculations["conduction_power_w"] = _round((load_current_a * load_current_a) * rds_on_ohms)
    if threshold_v > 0 and gate_drive_voltage_v <= threshold_v + 1.0:
        findings.append(
            _warning(
                "gate_drive_margin_low",
                "Gate drive voltage may not fully enhance the MOSFET",
                "MOSFET gate",
            )
        )
    if inductive_load and not flyback_present:
        findings.append(
            _warning(
                "missing_flyback_protection",
                "Inductive loads need flyback protection across the load or switching path",
                "switched load",
            )
        )
    return CircuitRuleReport("low-side-switch", calculations, tuple(findings))


def _check_555_astable(parameters: dict[str, Any]) -> CircuitRuleReport:
    supply_voltage_v = _positive_float(parameters, "supply_voltage_v")
    ra_ohms = _positive_float(parameters, "ra_ohms")
    rb_ohms = _positive_float(parameters, "rb_ohms")
    c_farads = _positive_float(parameters, "c_farads")
    findings = _ne555_supply_findings(supply_voltage_v)
    frequency_hz = 1.44 / ((ra_ohms + (2 * rb_ohms)) * c_farads)
    duty_cycle = ((ra_ohms + rb_ohms) / (ra_ohms + (2 * rb_ohms))) * 100.0
    return CircuitRuleReport(
        "555-astable",
        {
            "frequency_hz": _round(frequency_hz),
            "duty_cycle_percent": _round(duty_cycle),
        },
        tuple(findings),
    )


def _check_555_pwm(parameters: dict[str, Any]) -> CircuitRuleReport:
    supply_voltage_v = _positive_float(parameters, "supply_voltage_v")
    timing_cap_farads = _positive_float(parameters, "timing_cap_farads")
    pot_ohms = _positive_float(parameters, "pot_ohms")
    findings = _ne555_supply_findings(supply_voltage_v)
    nominal_frequency_hz = 1.44 / (pot_ohms * timing_cap_farads)
    return CircuitRuleReport(
        "555-pwm",
        {"nominal_frequency_hz": _round(nominal_frequency_hz)},
        tuple(findings),
    )


def _check_rc_filter(parameters: dict[str, Any]) -> CircuitRuleReport:
    r_ohms = _positive_float(parameters, "r_ohms")
    c_farads = _positive_float(parameters, "c_farads")
    cutoff_hz = 1.0 / (2.0 * math.pi * r_ohms * c_farads)
    return CircuitRuleReport(
        "rc-filter",
        {"cutoff_frequency_hz": _round(cutoff_hz)},
        (),
    )


def _check_voltage_divider(parameters: dict[str, Any]) -> CircuitRuleReport:
    input_voltage_v = _positive_float(parameters, "input_voltage_v")
    r_top_ohms = _positive_float(parameters, "r_top_ohms")
    r_bottom_ohms = _positive_float(parameters, "r_bottom_ohms")
    output_voltage_v = input_voltage_v * (r_bottom_ohms / (r_top_ohms + r_bottom_ohms))
    divider_current_ma = (input_voltage_v / (r_top_ohms + r_bottom_ohms)) * 1000.0
    findings: list[CircuitRuleFinding] = []
    load_ohms = _optional_positive_float(parameters, "load_ohms", default=0.0)
    if load_ohms > 0 and load_ohms < r_bottom_ohms * 10:
        findings.append(
            _warning(
                "divider_load_too_low",
                "Load resistance is close enough to alter the divider output materially",
                "divider output",
            )
        )
    return CircuitRuleReport(
        "voltage-divider",
        {
            "output_voltage_v": _round(output_voltage_v),
            "divider_current_ma": _round(divider_current_ma),
        },
        tuple(findings),
    )


def _check_power_entry(parameters: dict[str, Any]) -> CircuitRuleReport:
    _positive_float(parameters, "input_voltage_v")
    expected_current_a = _positive_float(parameters, "expected_current_a")
    fuse_current_a = _optional_positive_float(parameters, "fuse_current_a", default=0.0)
    reverse_protection = _bool(parameters, "reverse_polarity_protection", default=False)
    polarity_labelled = _bool(parameters, "polarity_labelled", default=False)
    findings: list[CircuitRuleFinding] = []
    if fuse_current_a > 0 and fuse_current_a < expected_current_a:
        findings.append(
            _error(
                "fuse_below_expected_current",
                "Fuse current rating is below the expected load current",
                "power entry",
            )
        )
    if not reverse_protection:
        findings.append(
            _warning(
                "missing_reverse_polarity_protection",
                "Consider reverse-polarity protection for user-facing power inputs",
                "power entry",
            )
        )
    if not polarity_labelled:
        findings.append(
            _warning(
                "missing_polarity_label",
                "Input pads or connectors should clearly mark polarity",
                "power entry silkscreen",
            )
        )
    return CircuitRuleReport("power-entry", {}, tuple(findings))


def _ne555_supply_findings(supply_voltage_v: float) -> list[CircuitRuleFinding]:
    if supply_voltage_v < 4.5 or supply_voltage_v > 16.0:
        return [
            _warning(
                "ne555_supply_range",
                "Generic NE555 assumptions expect roughly 4.5 V to 16 V supply",
                "NE555 VCC",
            )
        ]
    return []


def _positive_float(parameters: dict[str, Any], key: str) -> float:
    if key not in parameters:
        raise ValueError(f"Missing required circuit rule parameter: {key}")
    value = parameters[key]
    if not isinstance(value, int | float):
        raise ValueError(f"Circuit rule parameter must be numeric: {key}")
    result = float(value)
    if result <= 0:
        raise ValueError(f"Circuit rule parameter must be positive: {key}")
    return result


def _optional_positive_float(
    parameters: dict[str, Any],
    key: str,
    *,
    default: float,
) -> float:
    if key not in parameters:
        return default
    return _positive_float(parameters, key)


def _bool(parameters: dict[str, Any], key: str, *, default: bool) -> bool:
    value = parameters.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"Circuit rule parameter must be boolean: {key}")
    return value


def _parse_parameter_value(raw: str) -> Any:
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _warning(code: str, message: str, location: str) -> CircuitRuleFinding:
    return CircuitRuleFinding(
        severity=CircuitRuleSeverity.WARNING,
        code=code,
        message=message,
        location=location,
    )


def _error(code: str, message: str, location: str) -> CircuitRuleFinding:
    return CircuitRuleFinding(
        severity=CircuitRuleSeverity.ERROR,
        code=code,
        message=message,
        location=location,
    )


def _round(value: float) -> float:
    return round(value, 3)


def _format_number(value: float) -> str:
    if value == round(value):
        return str(round(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


__all__ = [
    "CIRCUIT_RULES_SCHEMA",
    "CIRCUIT_RULES_TOOL_SCHEMA",
    "SUPPORTED_CIRCUIT_RULE_INTENTS",
    "CircuitRuleFinding",
    "CircuitRuleReport",
    "CircuitRuleSeverity",
    "check_circuit_rules",
    "check_circuit_rules_file",
    "circuit_rules_planner_rule_notes",
    "circuit_rules_tool_contract",
    "format_circuit_rule_report",
    "parse_rule_parameters",
    "write_circuit_rule_report",
]
