from decimal import Decimal

from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge
from pcbsmith.gate_driver_support_ir import (
    GateDriverSupportPlan,
    GateDriverSupportRequirement,
    GateDriverSupportRole,
    evaluate_gate_driver_support_plan,
)


def _known(quantity_id: str, unit: str, value: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal(value),
        nominal=Decimal(value),
        upper=Decimal(value),
        evidence_binding_ids=("source:driver",),
    )


def _unknown(quantity_id: str, unit: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Required operating bound is missing.",
    )


def _requirement(
    requirement_id: str,
    voltage: BoundedQuantity,
    *,
    selected: bool = False,
) -> GateDriverSupportRequirement:
    return GateDriverSupportRequirement(
        requirement_id=requirement_id,
        role=GateDriverSupportRole.SUPPLY_BYPASS,
        pin_ids=("PVDD", "GND"),
        component_count=1,
        recommended_nominal_value=_known("nominal", "F", "0.00001"),
        minimum_effective_value=_known("effective", "F", "0.00001"),
        maximum_applied_voltage=voltage,
        selected_mpn="CAP-1" if selected else None,
        selected_footprint_id="Capacitor_SMD:C_1210" if selected else None,
        placement_obligation_ids=("close-to-pvdd",),
        source_binding_ids=("source:driver",),
        notes=("Effective value required.",),
    )


def test_unresolved_voltage_and_unselected_mpn_block_support_plan() -> None:
    plan = GateDriverSupportPlan(
        plan_id="support:test",
        revision="1",
        driver_candidate_id="driver",
        requirements=(_requirement("cpvdd", _unknown("pvdd", "V")),),
        source_context_ids=("source:driver",),
    )
    report = evaluate_gate_driver_support_plan(plan)
    assert report.definition_state == "incomplete"
    assert report.implementation_state == "blocked"
    assert report.unresolved_requirement_ids == ("cpvdd",)
    assert report.unselected_requirement_ids == ("cpvdd",)


def test_fully_bounded_selected_requirements_are_ready_without_selecting_driver() -> None:
    plan = GateDriverSupportPlan(
        plan_id="support:test",
        revision="1",
        driver_candidate_id="driver",
        requirements=(_requirement("cpvdd", _known("pvdd", "V", "25.2"), selected=True),),
        source_context_ids=("source:driver",),
    )
    report = evaluate_gate_driver_support_plan(plan)
    assert report.definition_state == "complete"
    assert report.implementation_state == "ready"
    assert report.selection_state == "not_selected"
