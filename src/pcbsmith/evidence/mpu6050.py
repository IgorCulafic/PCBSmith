"""Evidence validation for the MPU-6050 breakout.

The extracted datasheet facts validate the composition: the chosen supply
must sit inside the documented VDD window, and every support capacitor must
match the value the typical operating circuit prescribes.
"""

from __future__ import annotations

import math

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.evidence.cache import EvidenceCache
from pcbsmith.evidence.models import (
    ComponentEvidence,
    ComponentSelection,
    EvidenceSelectionReport,
)

SUPPORTED_TOPOLOGY_IDS = ("mpu6050_imu", "clover_tilt_indicator")
SENSOR_REFERENCE = "U1"
SENSOR_ROLE = "imu_sensor"

# Composition capacitor values checked against the datasheet facts.
CAPACITOR_FACTS = {
    "C1": ("regout_capacitor_f", 1e-7),
    "C2": ("vdd_bypass_capacitor_f", 1e-7),
    "C3": ("charge_pump_capacitor_f", 2.2e-9),
    "C4": ("vlogic_bypass_capacitor_f", 1e-8),
}

PASSIVES_FINDING = (
    "Datasheet validation covers the sensor (U1) and the support-capacitor "
    "values; the pullup resistors and connector carry no per-part evidence."
)


def select_mpu6050_components(
    circuit: CircuitObject,
    cache: EvidenceCache,
) -> EvidenceSelectionReport:
    if circuit.topology.topology_id not in SUPPORTED_TOPOLOGY_IDS:
        raise ValueError("Unsupported circuit for MPU-6050 evidence selection")

    candidates = cache.components_for_role(SENSOR_ROLE)
    findings: list[str] = []
    if not candidates:
        finding = f"No cached evidence found for {SENSOR_REFERENCE} role {SENSOR_ROLE}."
        selection = ComponentSelection(
            reference=SENSOR_REFERENCE,
            role=SENSOR_ROLE,
            status="missing",
            findings=(finding,),
        )
        findings.append(finding)
    else:
        selection = _evaluate_sensor(circuit, cache, candidates[0])
        findings.extend(selection.findings)

    findings.append(PASSIVES_FINDING)
    status = "failed" if selection.status == "failed" else "needs_human_review"
    return EvidenceSelectionReport(
        status=status,
        findings=tuple(findings),
        cached_files=tuple(str(path) for path in cache.cached_files),
        selections=(selection,),
    )


def _evaluate_sensor(
    circuit: CircuitObject,
    cache: EvidenceCache,
    candidate: ComponentEvidence,
) -> ComponentSelection:
    supply = float(circuit.math.calculations["supply_voltage_v"])
    missing: list[str] = []
    failed: list[str] = []

    for missing_file in cache.missing_cached_files(candidate):
        missing.append(f"U1 cached evidence file is missing: {missing_file}.")

    vdd_min = _numeric_fact(candidate, "vdd_v_min")
    vdd_max = _numeric_fact(candidate, "vdd_v_max")
    if vdd_min is None or vdd_max is None:
        missing.append("U1 is missing the vdd_v_min/vdd_v_max supply window.")
    elif not vdd_min <= supply <= vdd_max:
        failed.append(
            f"The {supply:g} V supply is outside the documented VDD window "
            f"{vdd_min:g}-{vdd_max:g} V."
        )

    vlogic_max = _numeric_fact(candidate, "vlogic_v_max")
    if vlogic_max is None:
        missing.append("U1 is missing vlogic_v_max evidence.")
    elif supply > vlogic_max:
        failed.append(
            f"VLOGIC is tied to the {supply:g} V supply, above the documented "
            f"{vlogic_max:g} V limit."
        )

    values_by_reference = {
        component.reference: component.value for component in circuit.components
    }
    for reference, (fact_name, expected_f) in CAPACITOR_FACTS.items():
        documented = _numeric_fact(candidate, fact_name)
        if documented is None:
            missing.append(f"U1 is missing {fact_name} evidence.")
            continue
        if not math.isclose(documented, expected_f, rel_tol=0.001):
            failed.append(
                f"{reference} is composed as {expected_f:g} F but the datasheet "
                f"prescribes {documented:g} F ({fact_name})."
            )
        if reference not in values_by_reference:
            failed.append(f"{reference} is missing from the composition.")

    if failed:
        status = "failed"
    elif missing:
        status = "missing"
    else:
        status = "selected"
    return ComponentSelection(
        reference=SENSOR_REFERENCE,
        role=SENSOR_ROLE,
        status=status,
        component=candidate,
        findings=(*missing, *failed),
    )


def _numeric_fact(candidate: ComponentEvidence, name: str) -> float | None:
    fact = candidate.fact(name)
    if fact is None or not isinstance(fact.value, int | float):
        return None
    return float(fact.value)
