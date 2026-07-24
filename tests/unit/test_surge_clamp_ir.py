from decimal import Decimal

from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge
from pcbsmith.surge_clamp_ir import (
    ClampQualificationContext,
    SurgeClampProfile,
    evaluate_surge_clamp,
)


def _known(quantity_id: str, unit: str, value: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal(value),
        nominal=Decimal(value),
        upper=Decimal(value),
        evidence_binding_ids=("source:test",),
    )


def _unknown(quantity_id: str, unit: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Missing test authority.",
    )


def _profile(*, unresolved_event: bool = False) -> SurgeClampProfile:
    return SurgeClampProfile(
        profile_id="clamp:test",
        scenario_ids=("event:test",),
        clamp_part_number="TVS-TEST",
        maximum_normal_voltage=_known("normal", "V", "25"),
        required_standoff_margin=_known("headroom", "V", "1"),
        reverse_standoff_voltage=_known("standoff", "V", "30"),
        breakdown_voltage=_known("breakdown", "V", "35"),
        clamping_voltage=_known("clamp", "V", "40"),
        protected_voltage_limit=_known("protected", "V", "50"),
        event_peak_current=(
            _unknown("event-current", "A")
            if unresolved_event
            else _known("event-current", "A", "100")
        ),
        qualified_peak_pulse_current=_known("qualified-current", "A", "150"),
        event_energy=(
            _unknown("event-energy", "J") if unresolved_event else _known("event-energy", "J", "2")
        ),
        qualified_peak_pulse_energy=_known("qualified-energy", "J", "5"),
        qualified_peak_pulse_power=_known("qualified-power", "W", "7000"),
        qualification_context=ClampQualificationContext.APPLICABLE,
        event_is_repetitive=False,
        qualification_is_repetitive=False,
        source_context_ids=("source:test",),
        notes=("Synthetic coordination fixture.",),
    )


def test_fully_bounded_clamp_can_be_coordinated() -> None:
    report = evaluate_surge_clamp(_profile())
    assert report.disposition == "coordinated"
    assert report.normal_standoff_headroom.lower == Decimal("5")
    assert report.protected_voltage_margin.lower == Decimal("10")


def test_unresolved_event_current_and_energy_fail_closed() -> None:
    report = evaluate_surge_clamp(_profile(unresolved_event=True))
    assert report.disposition == "indeterminate"
    assert set(report.missing_input_ids) >= {"event-current", "event-energy"}


def test_known_repetitive_event_is_not_released_by_nonrepetitive_rating() -> None:
    profile = _profile().model_copy(update={"event_is_repetitive": True})
    report = evaluate_surge_clamp(profile)
    assert report.disposition == "inadequate"
    assert report.repetition_adequate is False
