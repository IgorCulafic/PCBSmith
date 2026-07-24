from decimal import Decimal

from pcbsmith.bootstrap_supply_ir import (
    BootstrapCapacitanceProfile,
    evaluate_bootstrap_capacitance,
)
from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge


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


def _profile(candidate: BoundedQuantity) -> BootstrapCapacitanceProfile:
    return BootstrapCapacitanceProfile(
        profile_id="bootstrap:test",
        driver_id="driver",
        power_device_id="mosfet",
        channel_ids=("U", "V", "W"),
        total_gate_charge=_known("qg", "C", "0.000000223"),
        gate_drive_amplitude=_known("vgs", "V", "11.3"),
        charge_multiplier=Decimal("20"),
        candidate_effective_capacitance=candidate,
        source_context_ids=("source:test",),
    )


def test_effective_capacitance_passes_only_above_worst_case_requirement() -> None:
    result = evaluate_bootstrap_capacitance(_profile(_known("cbst", "F", "0.000001")))
    assert result.disposition == "adequate"
    assert result.required_effective_capacitance.upper == Decimal(
        "0.0000003946902654867256637168141593"
    )


def test_nominal_only_candidate_fails_closed() -> None:
    candidate = BoundedQuantity(
        quantity_id="cbst_effective",
        unit="F",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="DC-bias and tolerance lower bound is missing.",
    )
    result = evaluate_bootstrap_capacitance(_profile(candidate))
    assert result.disposition == "indeterminate"
    assert result.missing_input_ids == ("cbst_effective",)
