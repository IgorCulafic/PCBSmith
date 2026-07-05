"""Evidence validation for the LM2596 buck against the extracted datasheet.

The manifest facts (Vref, switching frequency, output-current and input
voltage limits — extracted from the TI datasheet with page/table locators)
are checked against the calculator inputs the circuit was composed with. A
mismatch means the deterministic math ran on assumptions the datasheet does
not support, which is exactly the failure mode that caused the 2026-05 buck
reset.
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

SUPPORTED_TOPOLOGY_ID = "lm2596_buck_regulator"
REGULATOR_REFERENCE = "U1"
REGULATOR_ROLE = "buck_regulator"

PASSIVES_FINDING = (
    "Datasheet validation covers the regulator (U1) only; the buck passives "
    "still carry design-procedure values without per-part evidence."
)


def select_lm2596_buck_components(
    circuit: CircuitObject,
    cache: EvidenceCache,
) -> EvidenceSelectionReport:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for LM2596 buck evidence selection")

    candidates = cache.components_for_role(REGULATOR_ROLE)
    findings: list[str] = []
    if not candidates:
        finding = f"No cached evidence found for {REGULATOR_REFERENCE} role {REGULATOR_ROLE}."
        selection = ComponentSelection(
            reference=REGULATOR_REFERENCE,
            role=REGULATOR_ROLE,
            status="missing",
            findings=(finding,),
        )
        findings.append(finding)
    else:
        selection = _evaluate_regulator(circuit, cache, candidates[0])
        findings.extend(selection.findings)

    findings.append(PASSIVES_FINDING)
    if selection.status == "failed":
        status = "failed"
    else:
        # Never "passed" while the passives lack evidence backing.
        status = "needs_human_review"
    return EvidenceSelectionReport(
        status=status,
        findings=tuple(findings),
        cached_files=tuple(str(path) for path in cache.cached_files),
        selections=(selection,),
    )


def _evaluate_regulator(
    circuit: CircuitObject,
    cache: EvidenceCache,
    candidate: ComponentEvidence,
) -> ComponentSelection:
    calculations = circuit.math.calculations
    assumptions = circuit.intent.assumptions
    missing: list[str] = []
    failed: list[str] = []

    for missing_file in cache.missing_cached_files(candidate):
        missing.append(f"U1 cached evidence file is missing: {missing_file}.")

    vref = _numeric_fact(candidate, "feedback_reference_v_typ")
    if vref is None:
        missing.append("U1 is missing feedback_reference_v_typ evidence.")
    elif not math.isclose(vref, 1.23, rel_tol=0.001):
        failed.append(
            f"U1 datasheet feedback reference {vref:g} V does not match the "
            "1.23 V the feedback divider was calculated with."
        )

    fsw_khz = _numeric_fact(candidate, "switching_frequency_khz_typ")
    calculated_hz = float(calculations["switching_frequency_hz"])
    if fsw_khz is None:
        missing.append("U1 is missing switching_frequency_khz_typ evidence.")
    elif not math.isclose(fsw_khz * 1000.0, calculated_hz, rel_tol=0.01):
        failed.append(
            f"U1 datasheet switching frequency {fsw_khz:g} kHz does not match "
            f"the {calculated_hz / 1000:g} kHz the inductor was sized with."
        )

    current_max = _numeric_fact(candidate, "output_current_a_max")
    load = float(calculations["load_current_a"])
    if current_max is None:
        missing.append("U1 is missing output_current_a_max evidence.")
    elif current_max < load:
        failed.append(
            f"U1 datasheet output limit {current_max:g} A is below the "
            f"{load:g} A design load."
        )

    vin_max_rating = _numeric_fact(candidate, "input_voltage_v_max")
    vin_max_design = float(assumptions["input_voltage_max_v"])
    if vin_max_rating is None:
        missing.append("U1 is missing input_voltage_v_max evidence.")
    elif vin_max_rating < vin_max_design:
        failed.append(
            f"U1 datasheet input limit {vin_max_rating:g} V is below the "
            f"{vin_max_design:g} V design input maximum."
        )

    if failed:
        status = "failed"
    elif missing:
        status = "missing"
    else:
        status = "selected"
    return ComponentSelection(
        reference=REGULATOR_REFERENCE,
        role=REGULATOR_ROLE,
        status=status,
        component=candidate,
        findings=(*missing, *failed),
    )


def _numeric_fact(candidate: ComponentEvidence, name: str) -> float | None:
    fact = candidate.fact(name)
    if fact is None or not isinstance(fact.value, int | float):
        return None
    return float(fact.value)
