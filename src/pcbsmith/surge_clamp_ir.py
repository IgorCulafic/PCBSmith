"""Source-bound surge-clamp coordination authority.

Presence of a TVS is not proof that it is coordinated.  This model keeps the
normal-voltage headroom, protected-node limit, pulse current/energy, waveform
applicability, and repetition questions separate so an attractive peak-power
headline cannot silently release a protection claim.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.engineering_quantity_ir import (
    BoundedQuantity,
    QuantityKnowledge,
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.semantic_ir import SemanticIrModel


class ClampQualificationContext(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"


class SurgeClampProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-surge-clamp-profile"] = "pcbsmith-surge-clamp-profile"
    schema_version: Literal[1] = 1
    profile_id: str
    scenario_ids: tuple[str, ...]
    clamp_part_number: str
    maximum_normal_voltage: BoundedQuantity
    required_standoff_margin: BoundedQuantity
    reverse_standoff_voltage: BoundedQuantity
    breakdown_voltage: BoundedQuantity
    clamping_voltage: BoundedQuantity
    protected_voltage_limit: BoundedQuantity
    event_peak_current: BoundedQuantity
    qualified_peak_pulse_current: BoundedQuantity
    event_energy: BoundedQuantity
    qualified_peak_pulse_energy: BoundedQuantity
    qualified_peak_pulse_power: BoundedQuantity
    qualification_context: ClampQualificationContext
    event_is_repetitive: bool | None
    qualification_is_repetitive: bool
    source_context_ids: tuple[str, ...]
    notes: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_coherent(self) -> Self:
        for field_name in ("profile_id", "clamp_part_number"):
            require_engineering_identity(getattr(self, field_name), field_name)
        for field_name in ("scenario_ids", "source_context_ids", "notes"):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            if not values:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, values)
        expected_units = {
            "maximum_normal_voltage": "V",
            "required_standoff_margin": "V",
            "reverse_standoff_voltage": "V",
            "breakdown_voltage": "V",
            "clamping_voltage": "V",
            "protected_voltage_limit": "V",
            "event_peak_current": "A",
            "qualified_peak_pulse_current": "A",
            "event_energy": "J",
            "qualified_peak_pulse_energy": "J",
            "qualified_peak_pulse_power": "W",
        }
        for field_name, unit in expected_units.items():
            if getattr(self, field_name).unit != unit:
                raise ValueError(f"{field_name} must use {unit}")
        return self


class SurgeClampCoordinationReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-surge-clamp-coordination-report"] = (
        "pcbsmith-surge-clamp-coordination-report"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["coordinated", "inadequate", "indeterminate"]
    normal_standoff_headroom: BoundedQuantity
    protected_voltage_margin: BoundedQuantity
    standoff_adequate: bool | None
    clamp_voltage_adequate: bool | None
    pulse_current_adequate: bool | None
    pulse_energy_adequate: bool | None
    context_applicable: bool | None
    repetition_adequate: bool | None
    missing_input_ids: tuple[str, ...]
    findings: tuple[str, ...]


def _difference(
    quantity_id: str,
    minuend: BoundedQuantity,
    subtrahend: BoundedQuantity,
    rationale: str,
) -> BoundedQuantity:
    if not minuend.is_known or not subtrahend.is_known:
        return BoundedQuantity(
            quantity_id=quantity_id,
            unit="V",
            knowledge=QuantityKnowledge.UNRESOLVED,
            rationale=rationale,
        )
    assert minuend.lower is not None and minuend.nominal is not None and minuend.upper is not None
    assert (
        subtrahend.lower is not None
        and subtrahend.nominal is not None
        and subtrahend.upper is not None
    )
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit="V",
        knowledge=QuantityKnowledge.DERIVED_BOUNDED,
        lower=minuend.lower - subtrahend.upper,
        nominal=minuend.nominal - subtrahend.nominal,
        upper=minuend.upper - subtrahend.lower,
        evidence_binding_ids=tuple(
            sorted(
                set(minuend.evidence_binding_ids)
                | set(subtrahend.evidence_binding_ids)
                | {"method:interval-subtraction"}
            )
        ),
        rationale=rationale,
    )


def evaluate_surge_clamp(profile: SurgeClampProfile) -> SurgeClampCoordinationReport:
    missing: set[str] = set()
    findings: list[str] = []
    quantities = (
        profile.maximum_normal_voltage,
        profile.required_standoff_margin,
        profile.reverse_standoff_voltage,
        profile.clamping_voltage,
        profile.protected_voltage_limit,
        profile.event_peak_current,
        profile.qualified_peak_pulse_current,
        profile.event_energy,
        profile.qualified_peak_pulse_energy,
    )
    for quantity in quantities:
        if not quantity.is_known:
            missing.add(quantity.quantity_id)

    normal_headroom = _difference(
        "normal-to-standoff-headroom",
        profile.reverse_standoff_voltage,
        profile.maximum_normal_voltage,
        "Reverse-standoff lower bound minus the maximum-normal-voltage upper bound.",
    )
    protected_margin = _difference(
        "protected-limit-to-clamp-margin",
        profile.protected_voltage_limit,
        profile.clamping_voltage,
        "Protected-voltage lower limit minus the clamp-voltage upper bound.",
    )

    standoff_ok: bool | None = None
    if normal_headroom.is_known and profile.required_standoff_margin.is_known:
        assert normal_headroom.lower is not None
        assert profile.required_standoff_margin.upper is not None
        standoff_ok = normal_headroom.lower >= profile.required_standoff_margin.upper
        if not standoff_ok:
            findings.append("Normal-voltage standoff headroom is below the required margin.")

    clamp_ok: bool | None = None
    if protected_margin.is_known:
        assert protected_margin.lower is not None
        clamp_ok = protected_margin.lower >= 0
        if not clamp_ok:
            findings.append("Maximum clamping voltage exceeds the protected-node limit.")

    current_ok: bool | None = None
    if profile.event_peak_current.is_known and profile.qualified_peak_pulse_current.is_known:
        assert profile.event_peak_current.upper is not None
        assert profile.qualified_peak_pulse_current.lower is not None
        current_ok = profile.event_peak_current.upper <= profile.qualified_peak_pulse_current.lower
        if not current_ok:
            findings.append("Event peak current exceeds the qualified pulse-current bound.")

    energy_ok: bool | None = None
    if profile.event_energy.is_known and profile.qualified_peak_pulse_energy.is_known:
        assert profile.event_energy.upper is not None
        assert profile.qualified_peak_pulse_energy.lower is not None
        energy_ok = profile.event_energy.upper <= profile.qualified_peak_pulse_energy.lower
        if not energy_ok:
            findings.append("Event energy exceeds the qualified pulse-energy bound.")

    context_ok: bool | None = None
    if profile.qualification_context is ClampQualificationContext.APPLICABLE:
        context_ok = True
    elif profile.qualification_context is ClampQualificationContext.NOT_APPLICABLE:
        context_ok = False
        findings.append("The retained pulse qualification is not applicable to the event.")
    else:
        missing.add("qualification_context")

    repetition_ok: bool | None = None
    if profile.event_is_repetitive is None:
        missing.add("event_is_repetitive")
    else:
        repetition_ok = not profile.event_is_repetitive or profile.qualification_is_repetitive
        if not repetition_ok:
            findings.append("A repetitive event is supported only by non-repetitive qualification.")

    checks = (standoff_ok, clamp_ok, current_ok, energy_ok, context_ok, repetition_ok)
    if any(item is False for item in checks):
        disposition: Literal["coordinated", "inadequate", "indeterminate"] = "inadequate"
    elif all(item is True for item in checks):
        disposition = "coordinated"
    else:
        disposition = "indeterminate"
    if disposition == "indeterminate":
        findings.append(
            "Peak pulse power alone does not establish event energy, waveform, temperature, "
            "or repetition applicability."
        )
    return SurgeClampCoordinationReport(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition=disposition,
        normal_standoff_headroom=normal_headroom,
        protected_voltage_margin=protected_margin,
        standoff_adequate=standoff_ok,
        clamp_voltage_adequate=clamp_ok,
        pulse_current_adequate=current_ok,
        pulse_energy_adequate=energy_ok,
        context_applicable=context_ok,
        repetition_adequate=repetition_ok,
        missing_input_ids=tuple(sorted(missing)),
        findings=tuple(findings),
    )
