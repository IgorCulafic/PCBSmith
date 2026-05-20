from __future__ import annotations

import math

from pcbsmith.circuit.models import CircuitObject, ComponentRole, EvidenceRef
from pcbsmith.evidence.cache import EvidenceCache
from pcbsmith.evidence.models import ComponentEvidence, ComponentSelection, EvidenceSelectionReport

SUPPORTED_TOPOLOGY_ID = "divider_highpass_led_indicator"
EXPECTED_ROLES = {
    "R1": "divider_top",
    "R2": "divider_bottom",
    "C1": "highpass_series_capacitor",
    "R3": "led_current_limit",
    "D1": "indicator_led",
}

EXPECTED_SYMBOLS = {
    "divider_top": "stdlib:R",
    "divider_bottom": "stdlib:R",
    "highpass_series_capacitor": "stdlib:C",
    "led_current_limit": "stdlib:R",
    "indicator_led": "stdlib:LED",
}

RESISTOR_POWER_MARGIN = 2.0
CAPACITOR_VOLTAGE_MARGIN = 1.0
LED_FORWARD_VOLTAGE_CENTER_V = 2.0
LED_FORWARD_VOLTAGE_ABS_TOLERANCE_V = 0.4


def select_divider_highpass_led_components(
    circuit: CircuitObject,
    cache: EvidenceCache,
) -> EvidenceSelectionReport:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for divider/high-pass/LED evidence selection")

    selections: list[ComponentSelection] = []
    findings: list[str] = []
    for component in circuit.components:
        if component.reference not in EXPECTED_ROLES:
            continue
        selection = _select_component(component, circuit, cache)
        selections.append(selection)
        findings.extend(selection.findings)

    selected_references = {selection.reference for selection in selections}
    for reference in EXPECTED_ROLES:
        if reference not in selected_references:
            finding = f"No circuit component found for required reference {reference}."
            selections.append(
                ComponentSelection(
                    reference=reference,
                    role=EXPECTED_ROLES[reference],
                    status="missing",
                    findings=(finding,),
                )
            )
            findings.append(finding)

    status = _selection_report_status(tuple(selections))
    return EvidenceSelectionReport(
        status=status,
        findings=tuple(findings),
        cached_files=tuple(str(path) for path in cache.cached_files),
        selections=tuple(selections),
    )


def apply_component_selection(
    circuit: CircuitObject,
    report: EvidenceSelectionReport,
) -> CircuitObject:
    selections_by_reference = {selection.reference: selection for selection in report.selections}
    components: list[ComponentRole] = []
    for component in circuit.components:
        selection = selections_by_reference.get(component.reference)
        if selection is None:
            components.append(component)
            continue
        if selection.status == "selected" and selection.component is not None:
            components.append(
                component.model_copy(
                    update={
                        "symbol_id": selection.component.symbol_id,
                        "value": selection.component.value,
                        "support_status": "supported",
                        "evidence": _component_evidence_refs(selection.component),
                    }
                )
            )
            continue
        components.append(
            component.model_copy(
                update={
                    "support_status": "unsupported"
                    if selection.status == "failed"
                    else "needs_datasheet_review",
                }
            )
        )
    return circuit.model_copy(update={"components": tuple(components)})


def _select_component(
    component: ComponentRole,
    circuit: CircuitObject,
    cache: EvidenceCache,
) -> ComponentSelection:
    candidates = cache.components_for_role(component.role)
    if not candidates:
        finding = (
            f"No cached evidence found for {component.reference} "
            f"role {component.role}."
        )
        return ComponentSelection(
            reference=component.reference,
            role=component.role,
            status="missing",
            findings=(finding,),
        )

    failed_selection: ComponentSelection | None = None
    missing_selection: ComponentSelection | None = None
    for candidate in candidates:
        status, findings = _evaluate_candidate(component, circuit, candidate, cache)
        selection = ComponentSelection(
            reference=component.reference,
            role=component.role,
            status=status,
            component=candidate,
            findings=findings,
        )
        if status == "selected":
            return selection
        if status == "failed" and failed_selection is None:
            failed_selection = selection
        if status == "missing" and missing_selection is None:
            missing_selection = selection

    if failed_selection is not None:
        return failed_selection
    if missing_selection is not None:
        return missing_selection
    raise RuntimeError("Evidence candidate evaluation produced no selection")


def _evaluate_candidate(
    component: ComponentRole,
    circuit: CircuitObject,
    candidate: ComponentEvidence,
    cache: EvidenceCache,
) -> tuple[str, tuple[str, ...]]:
    findings: list[str] = []
    missing_fact = False
    failed_rating = False

    expected_symbol = EXPECTED_SYMBOLS[component.role]
    if candidate.symbol_id != expected_symbol:
        failed_rating = True
        findings.append(
            f"{component.reference} evidence uses symbol {candidate.symbol_id}, "
            f"but {expected_symbol} is required."
        )

    missing_files = cache.missing_cached_files(candidate)
    for missing_file in missing_files:
        missing_fact = True
        findings.append(f"{component.reference} cached evidence file is missing: {missing_file}.")

    if component.role in {"divider_top", "divider_bottom"}:
        missing, failed = _check_resistor(
            component.reference,
            candidate,
            expected_ohms=10_000.0,
            minimum_power_w=_divider_resistor_minimum_power_w(circuit),
        )
    elif component.role == "led_current_limit":
        missing, failed = _check_resistor(
            component.reference,
            candidate,
            expected_ohms=680.0,
            minimum_power_w=circuit.math.calculations["led_resistor_power_w"]
            * RESISTOR_POWER_MARGIN,
        )
    elif component.role == "highpass_series_capacitor":
        missing, failed = _check_capacitor(component.reference, candidate)
    elif component.role == "indicator_led":
        missing, failed = _check_led(component.reference, circuit, candidate)
    else:
        missing = (f"{component.reference} role {component.role} is not supported.",)
        failed = ()

    findings.extend(missing)
    findings.extend(failed)
    missing_fact = missing_fact or bool(missing)
    failed_rating = failed_rating or bool(failed)

    if failed_rating:
        return "failed", tuple(findings)
    if missing_fact:
        return "missing", tuple(findings)
    return "selected", ()


def _check_resistor(
    reference: str,
    candidate: ComponentEvidence,
    *,
    expected_ohms: float,
    minimum_power_w: float,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    missing: list[str] = []
    failed: list[str] = []

    resistance = _numeric_fact(candidate, "resistance_ohms")
    if resistance is None:
        missing.append(f"{reference} is missing resistance_ohms evidence.")
    elif not math.isclose(resistance, expected_ohms, rel_tol=0.001, abs_tol=0.001):
        failed.append(
            f"{reference} resistance {resistance:g} ohm does not match required "
            f"{expected_ohms:g} ohm."
        )

    power = _numeric_fact(candidate, "power_rating_w")
    if power is None:
        missing.append(f"{reference} is missing power_rating_w evidence.")
    elif power < minimum_power_w:
        failed.append(
            f"{reference} power rating {power:g} W is below required "
            f"{minimum_power_w:g} W."
        )

    if candidate.fact("tolerance_percent") is None:
        missing.append(f"{reference} is missing tolerance_percent evidence.")
    if not candidate.footprint:
        missing.append(f"{reference} is missing footprint evidence.")
    return tuple(missing), tuple(failed)


def _check_capacitor(
    reference: str,
    candidate: ComponentEvidence,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    missing: list[str] = []
    failed: list[str] = []

    capacitance = _numeric_fact(candidate, "capacitance_f")
    if capacitance is None:
        missing.append(f"{reference} is missing capacitance_f evidence.")
    elif not math.isclose(capacitance, 100e-9, rel_tol=0.001, abs_tol=1e-12):
        failed.append(
            f"{reference} capacitance {capacitance:g} F does not match required 1e-07 F."
        )

    voltage_rating = _numeric_fact(candidate, "voltage_rating_v")
    minimum_voltage = 5.0 * CAPACITOR_VOLTAGE_MARGIN
    if voltage_rating is None:
        missing.append(f"{reference} is missing voltage_rating_v evidence.")
    elif voltage_rating < minimum_voltage:
        failed.append(
            f"{reference} voltage rating {voltage_rating:g} V is below required "
            f"{minimum_voltage:g} V."
        )

    if candidate.fact("dielectric") is None:
        missing.append(f"{reference} is missing dielectric evidence.")
    if not candidate.footprint:
        missing.append(f"{reference} is missing footprint evidence.")
    return tuple(missing), tuple(failed)


def _check_led(
    reference: str,
    circuit: CircuitObject,
    candidate: ComponentEvidence,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    missing: list[str] = []
    failed: list[str] = []

    forward_voltage = _numeric_fact(candidate, "forward_voltage_v_typ")
    if forward_voltage is None:
        missing.append(f"{reference} is missing forward_voltage_v_typ evidence.")
    elif not math.isclose(
        forward_voltage,
        LED_FORWARD_VOLTAGE_CENTER_V,
        rel_tol=0.0,
        abs_tol=LED_FORWARD_VOLTAGE_ABS_TOLERANCE_V,
    ):
        failed.append(
            f"{reference} forward voltage {forward_voltage:g} V is not compatible "
            "with the 2.0 V LED calculation assumption."
        )

    current_rating = _numeric_fact(candidate, "forward_current_ma_max")
    nominal_current = circuit.math.calculations["led_nominal_current_ma"]
    if current_rating is None:
        missing.append(f"{reference} is missing forward_current_ma_max evidence.")
    elif current_rating < nominal_current:
        failed.append(
            f"{reference} forward current rating {current_rating:g} mA is below "
            f"nominal current {nominal_current:g} mA."
        )

    if not candidate.footprint:
        missing.append(f"{reference} is missing footprint evidence.")
    return tuple(missing), tuple(failed)


def _divider_resistor_minimum_power_w(circuit: CircuitObject) -> float:
    divider_current_a = circuit.math.calculations["divider_current_ma"] / 1000.0
    return (divider_current_a * divider_current_a) * 10_000.0 * RESISTOR_POWER_MARGIN


def _numeric_fact(candidate: ComponentEvidence, name: str) -> float | None:
    fact = candidate.fact(name)
    if fact is None or not isinstance(fact.value, int | float):
        return None
    return float(fact.value)


def _component_evidence_refs(component: ComponentEvidence) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(
            kind="component_fact",
            title=f"{component.manufacturer} {component.part_number} {fact.name}",
            locator=fact.locator.describe(),
        )
        for fact in component.facts
    )


def _selection_report_status(selections: tuple[ComponentSelection, ...]) -> str:
    if any(selection.status == "failed" for selection in selections):
        return "failed"
    if any(selection.status == "missing" for selection in selections):
        return "needs_human_review"
    return "passed"
