from decimal import Decimal

import pytest

from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge
from pcbsmith.gate_supply_architecture_ir import (
    GateSupplyArchitectureKind,
    GateSupplyOption,
    evaluate_gate_supply_options,
)


def _voltage(quantity_id: str, lower: str, nominal: str, upper: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit="V",
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal(lower),
        nominal=Decimal(nominal),
        upper=Decimal(upper),
        evidence_binding_ids=(f"source:{quantity_id}",),
    )


def _option(
    option_id: str,
    high: tuple[str, str, str],
    low: tuple[str, str, str],
    unresolved: tuple[str, ...],
) -> GateSupplyOption:
    return GateSupplyOption(
        option_id=option_id,
        kind=GateSupplyArchitectureKind.SEPARATE_REGULATED,
        driver_id="driver",
        power_device_id="mosfet",
        driver_supply_voltage=_voltage("vm", "12", "12", "12"),
        high_side_gate_voltage=_voltage("high_vgs", *high),
        low_side_gate_voltage=_voltage("low_vgs", *low),
        characterized_gate_voltage=_voltage("characterized_vgs", "6", "6", "6"),
        required_margin=_voltage("required_margin", "1", "1", "1"),
        hardware_change_ids=("add-regulated-vm",),
        unresolved_authority_ids=unresolved,
        source_binding_ids=("source:driver", "source:mosfet"),
        notes=("Screening option only.",),
    )


def test_options_separate_infeasible_voltage_from_conditional_candidate() -> None:
    inadequate = _option("bus-9v", ("5.5", "7.5", "8.5"), ("6.5", "8", "9.5"), ())
    candidate = _option(
        "regulated-12v",
        ("7.5", "10", "11.5"),
        ("9", "10.5", "12"),
        ("converter-selection",),
    )
    result = evaluate_gate_supply_options(
        report_id="decision:test",
        revision="1",
        options=(candidate, inadequate),
        preferred_option_id="regulated-12v",
    )
    evaluations = {item.option_id: item for item in result.evaluations}
    assert evaluations["bus-9v"].disposition == "infeasible"
    assert evaluations["regulated-12v"].disposition == "conditional_candidate"
    assert result.selection_state == "not_selected"
    assert result.recommended_option_id == "regulated-12v"


def test_infeasible_option_cannot_be_preferred() -> None:
    option = _option("bus-9v", ("5.5", "7.5", "8.5"), ("6.5", "8", "9.5"), ())
    with pytest.raises(ValueError, match="infeasible"):
        evaluate_gate_supply_options(
            report_id="decision:test",
            revision="1",
            options=(option,),
            preferred_option_id="bus-9v",
        )
