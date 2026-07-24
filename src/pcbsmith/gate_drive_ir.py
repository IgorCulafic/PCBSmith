"""Evidence-bound gate-drive adequacy screening.

The evaluator compares guaranteed available gate voltage with the minimum
voltage at which a selected power-device parameter is characterized.  It does
not infer RDS(on) between datasheet test conditions and it deliberately uses
the worst-case interval endpoint for the release-facing disposition.
"""

from __future__ import annotations

from decimal import Decimal
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


class GateDriveChannelKind(StrEnum):
    HIGH_SIDE = "high_side"
    LOW_SIDE = "low_side"


class GateDriveChannelPoint(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-drive-channel-point"] = (
        "pcbsmith-gate-drive-channel-point"
    )
    schema_version: Literal[1] = 1
    channel_id: str
    kind: GateDriveChannelKind
    available_gate_voltage: BoundedQuantity
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def point_is_coherent(self) -> Self:
        require_engineering_identity(self.channel_id, "channel_id")
        if self.available_gate_voltage.unit != "V":
            raise ValueError("available gate voltage must use volts")
        bindings = canonical_engineering_identities(
            self.source_binding_ids,
            "source_binding_ids",
        )
        if not bindings:
            raise ValueError("gate-drive points require source context")
        object.__setattr__(self, "source_binding_ids", bindings)
        return self


class GateDriveProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-drive-profile"] = "pcbsmith-gate-drive-profile"
    schema_version: Literal[1] = 1
    profile_id: str
    scenario_id: str
    driver_id: str
    power_device_id: str
    driver_supply_voltage: BoundedQuantity
    characterized_gate_voltage: BoundedQuantity
    required_margin: BoundedQuantity
    channels: tuple[GateDriveChannelPoint, ...]
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_canonical(self) -> Self:
        for field_name in ("profile_id", "scenario_id", "driver_id", "power_device_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        for quantity in (
            self.driver_supply_voltage,
            self.characterized_gate_voltage,
            self.required_margin,
        ):
            if quantity.unit != "V":
                raise ValueError("gate-drive profile quantities must use volts")
        channels = tuple(sorted(self.channels, key=lambda item: item.channel_id))
        if not channels:
            raise ValueError("gate-drive profiles require at least one channel")
        if len(channels) != len({item.channel_id for item in channels}):
            raise ValueError("gate-drive channel identities must be unique")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("gate-drive profiles require source context")
        object.__setattr__(self, "channels", channels)
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class GateDriveChannelEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-drive-channel-evaluation"] = (
        "pcbsmith-gate-drive-channel-evaluation"
    )
    schema_version: Literal[1] = 1
    channel_id: str
    disposition: Literal["adequate", "inadequate", "indeterminate"]
    worst_case_margin: BoundedQuantity
    findings: tuple[str, ...]


class GateDriveEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-drive-evaluation"] = (
        "pcbsmith-gate-drive-evaluation"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["adequate", "inadequate", "indeterminate"]
    channel_evaluations: tuple[GateDriveChannelEvaluation, ...]
    findings: tuple[str, ...]


class GateChargeCapacityProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-charge-capacity-profile"] = (
        "pcbsmith-gate-charge-capacity-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    scenario_id: str
    gate_charge: BoundedQuantity
    switching_frequency: BoundedQuantity
    simultaneously_switching_high_side_count: BoundedQuantity
    simultaneously_switching_low_side_count: BoundedQuantity
    available_high_side_average_current: BoundedQuantity
    available_low_side_average_current: BoundedQuantity
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_coherent(self) -> Self:
        for field_name in ("profile_id", "scenario_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        expected_units = (
            (self.gate_charge, "nC"),
            (self.switching_frequency, "Hz"),
            (self.simultaneously_switching_high_side_count, "count"),
            (self.simultaneously_switching_low_side_count, "count"),
            (self.available_high_side_average_current, "A"),
            (self.available_low_side_average_current, "A"),
        )
        for quantity, expected in expected_units:
            if quantity.unit != expected:
                raise ValueError(f"{quantity.quantity_id} must use explicit {expected} units")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("gate-charge capacity profiles require source context")
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class GateChargeCapacityResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-charge-capacity-result"] = (
        "pcbsmith-gate-charge-capacity-result"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["adequate", "inadequate", "indeterminate"]
    required_per_switch_average_current: BoundedQuantity
    required_high_side_average_current: BoundedQuantity
    required_low_side_average_current: BoundedQuantity
    high_side_current_margin: BoundedQuantity
    low_side_current_margin: BoundedQuantity
    missing_input_ids: tuple[str, ...]
    findings: tuple[str, ...]


class DeadTimeAdequacyProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-dead-time-adequacy-profile"] = (
        "pcbsmith-dead-time-adequacy-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    scenario_id: str
    programmed_dead_time: BoundedQuantity
    turn_off_completion_time: BoundedQuantity
    propagation_mismatch: BoundedQuantity
    required_timing_margin: BoundedQuantity
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_coherent(self) -> Self:
        for field_name in ("profile_id", "scenario_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        for quantity in (
            self.programmed_dead_time,
            self.turn_off_completion_time,
            self.propagation_mismatch,
            self.required_timing_margin,
        ):
            if quantity.unit != "ns":
                raise ValueError("dead-time profile quantities must use nanoseconds")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("dead-time profiles require source context")
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class DeadTimeAdequacyResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-dead-time-adequacy-result"] = (
        "pcbsmith-dead-time-adequacy-result"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["adequate", "inadequate", "indeterminate"]
    required_dead_time: BoundedQuantity
    timing_margin: BoundedQuantity
    missing_input_ids: tuple[str, ...]
    findings: tuple[str, ...]


def _unknown_margin(channel_id: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=f"{channel_id}_gate_voltage_margin",
        unit="V",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Gate-drive margin inputs are unresolved.",
    )


def evaluate_gate_drive_adequacy(profile: GateDriveProfile) -> GateDriveEvaluation:
    """Fail closed unless guaranteed gate voltage clears the characterized point."""

    required = profile.characterized_gate_voltage
    requested_margin = profile.required_margin
    evaluations: list[GateDriveChannelEvaluation] = []
    for channel in profile.channels:
        available = channel.available_gate_voltage
        if not available.is_known or not required.is_known or not requested_margin.is_known:
            evaluations.append(
                GateDriveChannelEvaluation(
                    channel_id=channel.channel_id,
                    disposition="indeterminate",
                    worst_case_margin=_unknown_margin(channel.channel_id),
                    findings=(
                        "Known interval bounds are required; nominal substitution is forbidden.",
                    ),
                )
            )
            continue
        assert available.lower is not None
        assert available.nominal is not None
        assert available.upper is not None
        assert required.lower is not None
        assert required.nominal is not None
        assert required.upper is not None
        assert requested_margin.lower is not None
        margin_lower = available.lower - required.upper
        margin_nominal = available.nominal - required.nominal
        margin_upper = available.upper - required.lower
        bindings = tuple(
            sorted(
                {
                    *profile.source_context_ids,
                    *channel.source_binding_ids,
                    *available.evidence_binding_ids,
                    *required.evidence_binding_ids,
                    *requested_margin.evidence_binding_ids,
                }
            )
        )
        margin = BoundedQuantity(
            quantity_id=f"{channel.channel_id}_gate_voltage_margin",
            unit="V",
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            lower=margin_lower,
            nominal=margin_nominal,
            upper=margin_upper,
            evidence_binding_ids=bindings,
            rationale="Available VGS minus the selected device characterization voltage.",
        )
        adequate = margin_lower >= requested_margin.lower
        evaluations.append(
            GateDriveChannelEvaluation(
                channel_id=channel.channel_id,
                disposition="adequate" if adequate else "inadequate",
                worst_case_margin=margin,
                findings=(
                    "Worst-case available VGS clears the characterized condition."
                    if adequate
                    else (
                        "Guaranteed VGS does not clear the selected device "
                        "characterization condition."
                    ),
                ),
            )
        )
    if any(item.disposition == "inadequate" for item in evaluations):
        disposition: Literal["adequate", "inadequate", "indeterminate"] = "inadequate"
    elif any(item.disposition == "indeterminate" for item in evaluations):
        disposition = "indeterminate"
    else:
        disposition = "adequate"
    findings = (
        "Adequacy is limited to the selected characterized parameter and test condition; "
        "it is not a switching-speed, loss, or transient proof.",
    )
    return GateDriveEvaluation(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition=disposition,
        channel_evaluations=tuple(evaluations),
        findings=findings,
    )


def _unknown_quantity(quantity_id: str, unit: str, rationale: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale=rationale,
    )


def _derived_quantity(
    quantity_id: str,
    unit: str,
    lower: Decimal,
    nominal: Decimal,
    upper: Decimal,
    bindings: tuple[str, ...],
    rationale: str,
) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.DERIVED_BOUNDED,
        lower=lower,
        nominal=nominal,
        upper=upper,
        evidence_binding_ids=bindings,
        rationale=rationale,
    )


def evaluate_gate_charge_capacity(
    profile: GateChargeCapacityProfile,
) -> GateChargeCapacityResult:
    """Screen aggregate Qg times frequency against high/low supply capability."""

    charge = profile.gate_charge
    frequency = profile.switching_frequency
    high_count = profile.simultaneously_switching_high_side_count
    low_count = profile.simultaneously_switching_low_side_count
    charge_inputs_known = charge.is_known and frequency.is_known
    bindings = tuple(
        sorted(
            {
                *profile.source_context_ids,
                *charge.evidence_binding_ids,
                *frequency.evidence_binding_ids,
                *high_count.evidence_binding_ids,
                *low_count.evidence_binding_ids,
                *profile.available_high_side_average_current.evidence_binding_ids,
                *profile.available_low_side_average_current.evidence_binding_ids,
            }
        )
    )
    if charge_inputs_known:
        assert charge.lower is not None and charge.nominal is not None and charge.upper is not None
        assert frequency.lower is not None
        assert frequency.nominal is not None
        assert frequency.upper is not None
        if charge.lower < 0 or frequency.lower < 0:
            raise ValueError("gate charge and switching frequency must be non-negative")
        scale = Decimal("1e-9")
        per_switch_required = _derived_quantity(
            "required_per_switch_average_gate_current",
            "A",
            charge.lower * frequency.lower * scale,
            charge.nominal * frequency.nominal * scale,
            charge.upper * frequency.upper * scale,
            bindings,
            "Average charge-delivery screen I = Qg times switching frequency.",
        )
    else:
        per_switch_required = _unknown_quantity(
            "required_per_switch_average_gate_current",
            "A",
            "Gate charge or switching frequency is unresolved.",
        )

    missing = []
    if not charge.is_known:
        missing.append("gate_charge")
    if not frequency.is_known:
        missing.append("switching_frequency")
    if not high_count.is_known:
        missing.append("simultaneously_switching_high_side_count")
    if not low_count.is_known:
        missing.append("simultaneously_switching_low_side_count")
    for label, current in (
        (
            "available_high_side_average_current",
            profile.available_high_side_average_current,
        ),
        (
            "available_low_side_average_current",
            profile.available_low_side_average_current,
        ),
    ):
        if not current.is_known:
            missing.append(label)

    def aggregate_required(
        count: BoundedQuantity,
        quantity_id: str,
    ) -> BoundedQuantity:
        if not count.is_known or not per_switch_required.is_known:
            return _unknown_quantity(
                quantity_id,
                "A",
                "Per-switch demand or simultaneous-switch count is unresolved.",
            )
        assert count.lower is not None
        assert count.nominal is not None
        assert count.upper is not None
        assert per_switch_required.lower is not None
        assert per_switch_required.nominal is not None
        assert per_switch_required.upper is not None
        if count.lower < 0:
            raise ValueError("simultaneously switching counts must be non-negative")
        return _derived_quantity(
            quantity_id,
            "A",
            count.lower * per_switch_required.lower,
            count.nominal * per_switch_required.nominal,
            count.upper * per_switch_required.upper,
            bindings,
            "Aggregate average gate current is active-switch count times Qg times frequency.",
        )

    high_required = aggregate_required(
        high_count,
        "required_high_side_average_gate_current",
    )
    low_required = aggregate_required(
        low_count,
        "required_low_side_average_gate_current",
    )

    def margin_for(
        current: BoundedQuantity,
        required: BoundedQuantity,
        quantity_id: str,
    ) -> BoundedQuantity:
        if not current.is_known or not required.is_known:
            return _unknown_quantity(
                quantity_id,
                "A",
                "Available or required aggregate average current is unresolved.",
            )
        assert current.lower is not None
        assert current.nominal is not None
        assert current.upper is not None
        assert required.lower is not None
        assert required.nominal is not None
        assert required.upper is not None
        return _derived_quantity(
            quantity_id,
            "A",
            current.lower - required.upper,
            current.nominal - required.nominal,
            current.upper - required.lower,
            bindings,
            "Available group-average current minus aggregate Qg-times-frequency demand.",
        )

    high_side_margin = margin_for(
        profile.available_high_side_average_current,
        high_required,
        "high_side_current_margin",
    )
    low_side_margin = margin_for(
        profile.available_low_side_average_current,
        low_required,
        "low_side_current_margin",
    )
    if missing:
        disposition: Literal["adequate", "inadequate", "indeterminate"] = "indeterminate"
    else:
        assert high_required.lower is not None and high_required.upper is not None
        assert low_required.lower is not None and low_required.upper is not None
        high_side = profile.available_high_side_average_current
        low_side = profile.available_low_side_average_current
        assert high_side.lower is not None and high_side.upper is not None
        assert low_side.lower is not None and low_side.upper is not None
        if (
            high_side.lower >= high_required.upper
            and low_side.lower >= low_required.upper
        ):
            disposition = "adequate"
        elif (
            high_side.upper < high_required.lower
            or low_side.upper < low_required.lower
        ):
            disposition = "inadequate"
        else:
            disposition = "indeterminate"
    return GateChargeCapacityResult(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition=disposition,
        required_per_switch_average_current=per_switch_required,
        required_high_side_average_current=high_required,
        required_low_side_average_current=low_required,
        high_side_current_margin=high_side_margin,
        low_side_current_margin=low_side_margin,
        missing_input_ids=tuple(sorted(missing)),
        findings=(
            "Aggregate Qg-times-frequency capacity is only a sanity screen; it does "
            "not establish edge time, Miller behavior, switching loss, or ringing.",
        ),
    )


def evaluate_dead_time_adequacy(
    profile: DeadTimeAdequacyProfile,
) -> DeadTimeAdequacyResult:
    """Compare programmed dead time with bounded turn-off completion and margins."""

    terms = (
        ("turn_off_completion_time", profile.turn_off_completion_time),
        ("propagation_mismatch", profile.propagation_mismatch),
        ("required_timing_margin", profile.required_timing_margin),
    )
    bindings = tuple(
        sorted(
            {
                *profile.source_context_ids,
                *(binding for _, item in terms for binding in item.evidence_binding_ids),
                *profile.programmed_dead_time.evidence_binding_ids,
            }
        )
    )
    missing = [identity for identity, item in terms if not item.is_known]
    if not profile.programmed_dead_time.is_known:
        missing.append("programmed_dead_time")
    if any(not item.is_known for _, item in terms):
        required = _unknown_quantity(
            "required_dead_time",
            "ns",
            "Turn-off completion, propagation mismatch, or required margin is unresolved.",
        )
    else:
        lower = nominal = upper = Decimal("0")
        for _, item in terms:
            assert item.lower is not None and item.nominal is not None and item.upper is not None
            if item.lower < 0:
                raise ValueError("dead-time requirement terms must be non-negative")
            lower += item.lower
            nominal += item.nominal
            upper += item.upper
        required = _derived_quantity(
            "required_dead_time",
            "ns",
            lower,
            nominal,
            upper,
            bindings,
            "Turn-off completion plus propagation mismatch and policy margin.",
        )
    programmed = profile.programmed_dead_time
    if not programmed.is_known or not required.is_known:
        margin = _unknown_quantity(
            "dead_time_margin",
            "ns",
            "Programmed or required dead time is unresolved.",
        )
        disposition: Literal["adequate", "inadequate", "indeterminate"] = "indeterminate"
    else:
        assert programmed.lower is not None
        assert programmed.nominal is not None
        assert programmed.upper is not None
        assert required.lower is not None
        assert required.nominal is not None
        assert required.upper is not None
        margin = _derived_quantity(
            "dead_time_margin",
            "ns",
            programmed.lower - required.upper,
            programmed.nominal - required.nominal,
            programmed.upper - required.lower,
            bindings,
            "Programmed dead time minus the bounded timing requirement.",
        )
        if programmed.lower >= required.upper:
            disposition = "adequate"
        elif programmed.upper < required.lower:
            disposition = "inadequate"
        else:
            disposition = "indeterminate"
    return DeadTimeAdequacyResult(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition=disposition,
        required_dead_time=required,
        timing_margin=margin,
        missing_input_ids=tuple(sorted(missing)),
        findings=(
            "Even adequate non-overlap does not minimize body-diode loss; waveform and "
            "reverse-recovery validation remain separate requirements.",
        ),
    )
