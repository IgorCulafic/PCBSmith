from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge
from pcbsmith.loss_stress_ir import (
    LossCalculationState,
    LossCoverageRequirement,
    LossMechanism,
    LossStressLedger,
    StressLimit,
    calculate_i2r_duty_screening,
    calculate_i2r_loss,
    compare_maximum_stress,
    evaluate_loss_coverage,
    unresolved_loss_entry,
)


def _quantity(
    quantity_id: str,
    *,
    unit: str,
    lower: str,
    nominal: str,
    upper: str,
) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal(lower),
        nominal=Decimal(nominal),
        upper=Decimal(upper),
        evidence_binding_ids=(f"evidence:{quantity_id}",),
    )


def _loss(*, current: BoundedQuantity | None = None):
    return calculate_i2r_loss(
        entry_id="loss:q1:normal:conduction",
        loss_identity_id="physical-loss:q1-channel",
        scenario_id="scenario:normal",
        subject_ids=("Q1", "phase-u"),
        mechanism=LossMechanism.CONDUCTION_I2R,
        current=current
        or _quantity(
            "phase_current_rms",
            unit="A",
            lower="10",
            nominal="11",
            upper="12",
        ),
        resistance=_quantity(
            "rdson_at_temperature",
            unit="ohm",
            lower="0.010",
            nominal="0.012",
            upper="0.015",
        ),
        source_binding_ids=("model:i2r-v1",),
    )


def test_i2r_uses_conservative_decimal_interval() -> None:
    loss = _loss()

    assert loss.state.value == "computed"
    assert loss.output_power.lower == Decimal("1.000")
    assert loss.output_power.nominal == Decimal("1.452")
    assert loss.output_power.upper == Decimal("2.160")
    assert "evidence:phase_current_rms" in loss.source_binding_ids
    assert "evidence:rdson_at_temperature" in loss.source_binding_ids


def test_i2r_refuses_implicit_unit_conversion() -> None:
    with pytest.raises(ValueError, match="current in A"):
        calculate_i2r_loss(
            entry_id="loss:bad-units",
            loss_identity_id="physical-loss:bad-units",
            scenario_id="scenario:normal",
            subject_ids=("Q1",),
            mechanism=LossMechanism.CONDUCTION_I2R,
            current=_quantity(
                "phase_current_rms",
                unit="mA",
                lower="10000",
                nominal="11000",
                upper="12000",
            ),
            resistance=_quantity(
                "rdson_at_temperature",
                unit="ohm",
                lower="0.01",
                nominal="0.012",
                upper="0.015",
            ),
            source_binding_ids=("model:i2r-v1",),
        )


def test_unresolved_input_emits_no_numeric_loss() -> None:
    current = BoundedQuantity(
        quantity_id="phase_current_rms",
        unit="A",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Motor and current limit are not selected.",
    )

    loss = _loss(current=current)

    assert loss.state.value == "unresolved"
    assert not loss.output_power.is_known
    assert loss.missing_input_ids == ("phase_current_rms",)


def _limit() -> StressLimit:
    return StressLimit(
        limit_id="limit:q1-vds-derated",
        subject_id="Q1",
        parameter_id="vds_peak",
        maximum_allowed=_quantity(
            "vds_derated_limit",
            unit="V",
            lower="70",
            nominal="72",
            upper="75",
        ),
        derating_policy_id="policy:mosfet-vds-80-percent",
        evidence_binding_ids=("evidence:q1-datasheet", "policy:mosfet-vds-80-percent"),
    )


@pytest.mark.parametrize(
    ("lower", "nominal", "upper", "expected"),
    (
        ("55", "60", "65", "pass"),
        ("68", "72", "76", "indeterminate"),
        ("76", "78", "80", "fail"),
    ),
)
def test_stress_comparison_uses_guaranteed_interval_boundaries(
    lower: str,
    nominal: str,
    upper: str,
    expected: str,
) -> None:
    result = compare_maximum_stress(
        result_id=f"stress:q1:{expected}",
        scenario_id="scenario:peak",
        observed=_quantity(
            "vds_peak",
            unit="V",
            lower=lower,
            nominal=nominal,
            upper=upper,
        ),
        limit=_limit(),
    )

    assert result.disposition == expected


def test_loss_coverage_does_not_treat_conduction_as_complete_mosfet_loss() -> None:
    conduction = _loss()
    ledger = LossStressLedger(
        ledger_id="ledger:fixture",
        mission_profile_id="mission:fixture",
        mission_profile_fingerprint="a" * 64,
        losses=(conduction,),
        source_context_ids=("source:fixture",),
    )
    report = evaluate_loss_coverage(
        ledger,
        (
            LossCoverageRequirement(
                requirement_id="coverage:q1:normal",
                scenario_id="scenario:normal",
                subject_id="Q1",
                required_mechanisms=(
                    LossMechanism.CONDUCTION_I2R,
                    LossMechanism.SWITCHING,
                    LossMechanism.GATE_DRIVE,
                ),
                rationale="MOSFET temperature work needs every material loss mechanism.",
            ),
        ),
    )

    assert report.disposition == "incomplete"
    evaluation = report.evaluations[0]
    assert evaluation.unresolved_mechanisms == (
        LossMechanism.GATE_DRIVE,
        LossMechanism.SWITCHING,
    )


def test_explicit_unresolved_loss_never_emits_zero_power() -> None:
    entry = unresolved_loss_entry(
        entry_id="loss.switching",
        loss_identity_id="normal:Q1:switching",
        scenario_id="normal",
        subject_ids=("Q1",),
        mechanism=LossMechanism.SWITCHING,
        missing_input_ids=("drain_transition",),
        source_binding_ids=("part:q1:datasheet",),
        rationale="Measured transition waveforms are missing.",
    )
    assert entry.state is LossCalculationState.UNRESOLVED
    assert not entry.output_power.is_known
    assert entry.output_power.lower is None


def test_assumption_bearing_conduction_screen_does_not_satisfy_coverage() -> None:
    screening = calculate_i2r_duty_screening(
        entry_id="loss:q1:screening",
        loss_identity_id="normal:Q1:conduction",
        scenario_id="scenario:normal",
        subject_ids=("Q1",),
        current=_quantity(
            "phase_current_rms",
            unit="A",
            lower="10",
            nominal="10",
            upper="10",
        ),
        resistance=_quantity(
            "hot_rdson_screening",
            unit="ohm",
            lower="0.002",
            nominal="0.002",
            upper="0.002",
        ),
        conduction_fraction=_quantity(
            "conduction_fraction",
            unit="ratio",
            lower="0.5",
            nominal="0.5",
            upper="0.5",
        ),
        source_binding_ids=("assumption:screening",),
        applicability_condition_ids=("VGS=10V", "Tj=175degC-screen"),
        findings=("Hot RDS(on) and duty need validation.",),
    )
    assert screening.state is LossCalculationState.VALIDATION_REQUIRED
    assert screening.output_power.nominal == Decimal("0.1000")
    assert screening.applicability_condition_ids == (
        "Tj=175degC-screen",
        "VGS=10V",
    )
    ledger = LossStressLedger(
        ledger_id="ledger:screening",
        mission_profile_id="mission:fixture",
        mission_profile_fingerprint="a" * 64,
        losses=(screening,),
        source_context_ids=("source:fixture",),
    )
    report = evaluate_loss_coverage(
        ledger,
        (
            LossCoverageRequirement(
                requirement_id="coverage:q1:normal",
                scenario_id="scenario:normal",
                subject_id="Q1",
                required_mechanisms=(LossMechanism.CONDUCTION_I2R,),
                rationale="Release coverage requires a computed, not screening, loss.",
            ),
        ),
    )
    assert report.disposition == "incomplete"
    assert report.evaluations[0].unresolved_mechanisms == (
        LossMechanism.CONDUCTION_I2R,
    )


def test_ledger_rejects_duplicate_physical_loss_identity() -> None:
    loss = _loss()
    with pytest.raises(ValidationError, match="prevent double counting"):
        LossStressLedger(
            ledger_id="ledger:duplicate",
            mission_profile_id="mission:fixture",
            mission_profile_fingerprint="a" * 64,
            losses=(loss, loss.model_copy(update={"entry_id": "loss:q1:duplicate"})),
            source_context_ids=("source:fixture",),
        )
