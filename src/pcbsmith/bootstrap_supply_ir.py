"""Bounded bootstrap-capacitance screening for high-side gate drivers."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.engineering_quantity_ir import (
    BoundedQuantity,
    QuantityKnowledge,
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.semantic_ir import SemanticIrModel


class BootstrapCapacitanceProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-bootstrap-capacitance-profile"] = (
        "pcbsmith-bootstrap-capacitance-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    driver_id: str
    power_device_id: str
    channel_ids: tuple[str, ...]
    total_gate_charge: BoundedQuantity
    gate_drive_amplitude: BoundedQuantity
    charge_multiplier: Decimal
    candidate_effective_capacitance: BoundedQuantity
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_coherent(self) -> Self:
        for field_name in ("profile_id", "driver_id", "power_device_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        if self.total_gate_charge.unit != "C":
            raise ValueError("total gate charge must use coulombs")
        if self.gate_drive_amplitude.unit != "V":
            raise ValueError("gate-drive amplitude must use volts")
        if self.candidate_effective_capacitance.unit != "F":
            raise ValueError("candidate effective capacitance must use farads")
        if not self.charge_multiplier.is_finite() or self.charge_multiplier <= 0:
            raise ValueError("bootstrap charge multiplier must be finite and positive")
        for field_name in ("channel_ids", "source_context_ids"):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            if not values:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, values)
        return self


class BootstrapCapacitanceResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-bootstrap-capacitance-result"] = (
        "pcbsmith-bootstrap-capacitance-result"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["adequate", "inadequate", "indeterminate"]
    required_effective_capacitance: BoundedQuantity
    worst_case_margin: BoundedQuantity
    missing_input_ids: tuple[str, ...]
    findings: tuple[str, ...]


def evaluate_bootstrap_capacitance(
    profile: BootstrapCapacitanceProfile,
) -> BootstrapCapacitanceResult:
    """Evaluate the source-defined Qg/V rule against effective capacitance."""

    missing = tuple(
        quantity.quantity_id
        for quantity in (
            profile.total_gate_charge,
            profile.gate_drive_amplitude,
            profile.candidate_effective_capacitance,
        )
        if not quantity.is_known
    )
    charge = profile.total_gate_charge
    voltage = profile.gate_drive_amplitude
    if not charge.is_known or not voltage.is_known:
        required = BoundedQuantity(
            quantity_id="required_bootstrap_effective_capacitance",
            unit="F",
            knowledge=QuantityKnowledge.UNRESOLVED,
            rationale="Gate charge or gate-drive amplitude is unresolved.",
        )
    else:
        assert charge.lower is not None and charge.nominal is not None and charge.upper is not None
        assert (
            voltage.lower is not None and voltage.nominal is not None and voltage.upper is not None
        )
        if voltage.lower <= 0:
            raise ValueError("gate-drive amplitude lower bound must be positive")
        required = BoundedQuantity(
            quantity_id="required_bootstrap_effective_capacitance",
            unit="F",
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            lower=profile.charge_multiplier * charge.lower / voltage.upper,
            nominal=profile.charge_multiplier * charge.nominal / voltage.nominal,
            upper=profile.charge_multiplier * charge.upper / voltage.lower,
            evidence_binding_ids=profile.source_context_ids,
            rationale="Computed as multiplier times total gate charge divided by gate amplitude.",
        )
    candidate = profile.candidate_effective_capacitance
    if not required.is_known or not candidate.is_known:
        margin = BoundedQuantity(
            quantity_id="bootstrap_effective_capacitance_margin",
            unit="F",
            knowledge=QuantityKnowledge.UNRESOLVED,
            rationale="Required or candidate effective capacitance is unresolved.",
        )
        disposition: Literal["adequate", "inadequate", "indeterminate"] = "indeterminate"
    else:
        assert required.lower is not None and required.nominal is not None
        assert required.upper is not None
        assert candidate.lower is not None and candidate.nominal is not None
        assert candidate.upper is not None
        margin = BoundedQuantity(
            quantity_id="bootstrap_effective_capacitance_margin",
            unit="F",
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            lower=candidate.lower - required.upper,
            nominal=candidate.nominal - required.nominal,
            upper=candidate.upper - required.lower,
            evidence_binding_ids=profile.source_context_ids,
        )
        assert margin.lower is not None
        disposition = "adequate" if margin.lower >= 0 else "inadequate"
    return BootstrapCapacitanceResult(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition=disposition,
        required_effective_capacitance=required,
        worst_case_margin=margin,
        missing_input_ids=missing,
        findings=(
            "The result uses effective capacitance at operating bias and temperature, "
            "not nominal marking.",
            "One result applies to each listed phase only when its gate-charge and "
            "voltage bounds apply.",
        ),
    )
