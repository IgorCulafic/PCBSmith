from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge
from pcbsmith.operating_scenario_ir import (
    AirflowState,
    EnclosureState,
    MissionProfile,
    OperatingEnvironment,
    OperatingScenario,
    ScenarioCoverageRequirement,
    ScenarioRole,
    evaluate_scenario_coverage,
)


def _quantity(
    quantity_id: str,
    nominal: str,
    *,
    unit: str,
    knowledge: QuantityKnowledge = QuantityKnowledge.DESIGN_TARGET,
) -> BoundedQuantity:
    value = Decimal(nominal)
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=knowledge,
        lower=value,
        nominal=value,
        upper=value,
        evidence_binding_ids=("evidence:project-brief",),
    )


def _environment(
    *,
    airflow: AirflowState = AirflowState.STILL_AIR,
    enclosure: EnclosureState = EnclosureState.OPEN_BENCH,
) -> OperatingEnvironment:
    return OperatingEnvironment(
        ambient_temperature=_quantity("ambient_temperature", "25", unit="degC"),
        airflow_state=airflow,
        enclosure_state=enclosure,
        orientation="horizontal_component_side_up",
        condition_ids=("condition:bench",),
    )


def _scenario(
    scenario_id: str,
    role: ScenarioRole,
    *,
    current: BoundedQuantity | None = None,
    duty: str | None = None,
    fault: bool = False,
    environment: OperatingEnvironment | None = None,
) -> OperatingScenario:
    quantities = (
        _quantity("dc_bus_voltage", "48", unit="V"),
        current or _quantity("phase_current_rms", "20", unit="A"),
    )
    return OperatingScenario(
        scenario_id=scenario_id,
        role=role,
        description=f"Fixture {role.value} operating condition.",
        steady_state=role in {ScenarioRole.NORMAL, ScenarioRole.PEAK},
        fault_scenario=fault,
        duration=_quantity("duration", "10", unit="s"),
        duty_fraction=None if duty is None else Decimal(duty),
        electrical_quantities=quantities,
        environment=environment or _environment(),
        active_path_ids=("path:phase-u",),
        source_context_ids=("source:fixture",),
    )


def _profile(*scenarios: OperatingScenario, complete: bool = False) -> MissionProfile:
    return MissionProfile(
        profile_id="mission:fixture",
        revision="r1",
        scenarios=scenarios,
        duty_cycle_complete=complete,
        intended_claim_ids=("claim:thermal-screening",),
        source_context_ids=("source:fixture",),
    )


def test_evidence_bound_quantity_requires_source_binding() -> None:
    with pytest.raises(ValidationError, match="require evidence bindings"):
        BoundedQuantity(
            quantity_id="gate_charge",
            unit="nC",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            lower=Decimal("80"),
            nominal=Decimal("100"),
            upper=Decimal("130"),
        )


def test_unknown_quantity_cannot_disguise_a_nominal_value() -> None:
    with pytest.raises(ValidationError, match="cannot carry numeric bounds"):
        BoundedQuantity(
            quantity_id="airflow_velocity",
            unit="m/s",
            knowledge=QuantityKnowledge.UNRESOLVED,
            lower=Decimal("0"),
            nominal=Decimal("0"),
            upper=Decimal("0"),
            rationale="No enclosure or fan has been selected.",
        )


def test_mission_profile_is_order_independent_and_fingerprint_stable() -> None:
    normal = _scenario("scenario:normal", ScenarioRole.NORMAL, duty="0.8")
    peak = _scenario("scenario:peak", ScenarioRole.PEAK, duty="0.2")

    first = _profile(normal, peak, complete=True)
    second = _profile(peak, normal, complete=True)

    assert first.scenarios == second.scenarios
    assert first.semantic_fingerprint() == second.semantic_fingerprint()


def test_nominal_only_profile_does_not_satisfy_peak_stall_and_cooling_coverage() -> None:
    profile = _profile(_scenario("scenario:normal", ScenarioRole.NORMAL, duty="1"), complete=True)
    requirements = (
        ScenarioCoverageRequirement(
            requirement_id="coverage:normal",
            role=ScenarioRole.NORMAL,
            required_quantity_ids=("dc_bus_voltage", "phase_current_rms"),
            requires_duty_fraction=True,
            rationale="Nominal loss point.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="coverage:peak",
            role=ScenarioRole.PEAK,
            required_quantity_ids=("dc_bus_voltage", "phase_current_rms"),
            requires_duration=True,
            rationale="Peak pulse stress.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="coverage:stall",
            role=ScenarioRole.OVERLOAD_OR_STALL,
            required_quantity_ids=("phase_current_rms",),
            requires_duration=True,
            rationale="Current-limit and fault-energy boundary.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="coverage:cooling-failure",
            role=ScenarioRole.COOLING_FAILURE,
            required_quantity_ids=("phase_current_rms",),
            requires_known_enclosure=True,
            rationale="Loss of intended cooling must remain visible.",
        ),
    )

    report = evaluate_scenario_coverage(profile, requirements)

    assert report.disposition == "incomplete"
    status = {item.requirement_id: item.satisfied for item in report.evaluations}
    assert status == {
        "coverage:cooling-failure": False,
        "coverage:normal": True,
        "coverage:peak": False,
        "coverage:stall": False,
    }


def test_unresolved_required_quantity_keeps_scenario_incomplete() -> None:
    unresolved_current = BoundedQuantity(
        quantity_id="phase_current_rms",
        unit="A",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Motor winding, modulation, and current limit are not selected.",
    )
    peak = _scenario(
        "scenario:peak",
        ScenarioRole.PEAK,
        current=unresolved_current,
    )
    report = evaluate_scenario_coverage(
        _profile(peak),
        (
            ScenarioCoverageRequirement(
                requirement_id="coverage:peak",
                role=ScenarioRole.PEAK,
                required_quantity_ids=("phase_current_rms",),
                requires_duration=True,
                rationale="Peak current is necessary for loss and SOA checks.",
            ),
        ),
    )

    assert report.disposition == "incomplete"
    assert report.evaluations[0].incomplete_scenario_ids == ("scenario:peak",)
    assert "unresolved quantities" in report.evaluations[0].findings[0]


def test_normal_duty_fractions_cannot_exceed_one() -> None:
    with pytest.raises(ValidationError, match="exceed 1"):
        _profile(
            _scenario("scenario:normal", ScenarioRole.NORMAL, duty="0.8"),
            _scenario("scenario:peak", ScenarioRole.PEAK, duty="0.3"),
        )
