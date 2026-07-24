from decimal import Decimal

from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge
from pcbsmith.gate_drive_ir import (
    DeadTimeAdequacyProfile,
    GateChargeCapacityProfile,
    GateDriveChannelKind,
    GateDriveChannelPoint,
    GateDriveProfile,
    evaluate_dead_time_adequacy,
    evaluate_gate_charge_capacity,
    evaluate_gate_drive_adequacy,
)


def _quantity(quantity_id: str, lower: str, nominal: str, upper: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit="V",
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal(lower),
        nominal=Decimal(nominal),
        upper=Decimal(upper),
        evidence_binding_ids=(f"evidence:{quantity_id}",),
    )


def _profile(high_side: BoundedQuantity, low_side: BoundedQuantity) -> GateDriveProfile:
    return GateDriveProfile(
        profile_id="gate-drive:test",
        scenario_id="minimum-bus",
        driver_id="driver",
        power_device_id="mosfet",
        driver_supply_voltage=_quantity("driver_supply", "9", "9", "9"),
        characterized_gate_voltage=_quantity("characterized_vgs", "6", "6", "6"),
        required_margin=_quantity("required_margin", "0", "0", "0"),
        channels=(
            GateDriveChannelPoint(
                channel_id="high-side",
                kind=GateDriveChannelKind.HIGH_SIDE,
                available_gate_voltage=high_side,
                source_binding_ids=("source:driver",),
            ),
            GateDriveChannelPoint(
                channel_id="low-side",
                kind=GateDriveChannelKind.LOW_SIDE,
                available_gate_voltage=low_side,
                source_binding_ids=("source:driver",),
            ),
        ),
        source_context_ids=("source:driver", "source:mosfet"),
    )


def test_guaranteed_high_side_undervoltage_fails_profile() -> None:
    result = evaluate_gate_drive_adequacy(
        _profile(
            _quantity("high_vgs", "5.5", "7.5", "8.5"),
            _quantity("low_vgs", "6.5", "8", "9.5"),
        )
    )
    assert result.disposition == "inadequate"
    evaluations = {item.channel_id: item for item in result.channel_evaluations}
    assert evaluations["high-side"].disposition == "inadequate"
    assert evaluations["high-side"].worst_case_margin.lower == Decimal("-0.5")
    assert evaluations["low-side"].disposition == "adequate"


def test_unknown_available_voltage_is_indeterminate() -> None:
    unknown = BoundedQuantity(
        quantity_id="high_vgs",
        unit="V",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Driver supply architecture is missing.",
    )
    result = evaluate_gate_drive_adequacy(
        _profile(unknown, _quantity("low_vgs", "6.5", "8", "9.5"))
    )
    assert result.disposition == "indeterminate"
    assert not result.channel_evaluations[0].worst_case_margin.is_known


def _point(quantity_id: str, value: str, unit: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal(value),
        nominal=Decimal(value),
        upper=Decimal(value),
        evidence_binding_ids=(f"evidence:{quantity_id}",),
    )


def test_gate_charge_capacity_computes_average_current_screen() -> None:
    profile = GateChargeCapacityProfile(
        profile_id="gate-charge:test",
        scenario_id="normal",
        gate_charge=_point("gate_charge", "100", "nC"),
        switching_frequency=_point("switching_frequency", "20000", "Hz"),
        simultaneously_switching_high_side_count=_point("high_count", "1", "count"),
        simultaneously_switching_low_side_count=_point("low_count", "1", "count"),
        available_high_side_average_current=_point("high_side_current", "0.01", "A"),
        available_low_side_average_current=_point("low_side_current", "0.01", "A"),
        source_context_ids=("source:test",),
    )
    result = evaluate_gate_charge_capacity(profile)
    assert result.disposition == "adequate"
    assert result.required_per_switch_average_current.nominal == Decimal("0.0020000")
    assert result.required_high_side_average_current.nominal == Decimal("0.0020000")


def test_gate_charge_capacity_requires_actual_current_configuration() -> None:
    unknown = BoundedQuantity(
        quantity_id="source_current",
        unit="A",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="IDRIVE configuration is missing.",
    )
    profile = GateChargeCapacityProfile(
        profile_id="gate-charge:unknown",
        scenario_id="normal",
        gate_charge=_point("gate_charge", "100", "nC"),
        switching_frequency=_point("switching_frequency", "20000", "Hz"),
        simultaneously_switching_high_side_count=_point("high_count", "1", "count"),
        simultaneously_switching_low_side_count=_point("low_count", "1", "count"),
        available_high_side_average_current=unknown,
        available_low_side_average_current=_point("low_side_current", "0.01", "A"),
        source_context_ids=("source:test",),
    )
    result = evaluate_gate_charge_capacity(profile)
    assert result.disposition == "indeterminate"
    assert result.missing_input_ids == ("available_high_side_average_current",)


def test_gate_charge_capacity_aggregates_simultaneously_switching_channels() -> None:
    profile = GateChargeCapacityProfile(
        profile_id="gate-charge:aggregate",
        scenario_id="normal",
        gate_charge=_point("gate_charge", "100", "nC"),
        switching_frequency=_point("switching_frequency", "20000", "Hz"),
        simultaneously_switching_high_side_count=_point("high_count", "3", "count"),
        simultaneously_switching_low_side_count=_point("low_count", "3", "count"),
        available_high_side_average_current=_point("high_side_current", "0.005", "A"),
        available_low_side_average_current=_point("low_side_current", "0.005", "A"),
        source_context_ids=("source:test",),
    )
    result = evaluate_gate_charge_capacity(profile)
    assert result.disposition == "inadequate"
    assert result.required_high_side_average_current.nominal == Decimal("0.0060000")


def test_dead_time_screen_uses_worst_case_non_overlap_requirement() -> None:
    profile = DeadTimeAdequacyProfile(
        profile_id="dead-time:test",
        scenario_id="normal",
        programmed_dead_time=_point("programmed_dead_time", "150", "ns"),
        turn_off_completion_time=_point("turn_off_completion_time", "80", "ns"),
        propagation_mismatch=_point("propagation_mismatch", "10", "ns"),
        required_timing_margin=_point("required_timing_margin", "20", "ns"),
        source_context_ids=("source:test",),
    )
    result = evaluate_dead_time_adequacy(profile)
    assert result.disposition == "adequate"
    assert result.required_dead_time.nominal == Decimal("110")
    assert result.timing_margin.nominal == Decimal("40")
