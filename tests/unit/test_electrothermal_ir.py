from decimal import Decimal

from pcbsmith.electrothermal_ir import (
    CoupledElectrothermalPointModel,
    ElectrothermalNetwork,
    ThermalHeatInjection,
    ThermalLink,
    ThermalNode,
    ThermalNodeKind,
    TransientThermalBranch,
    TransientThermalModel,
    solve_coupled_electrothermal_point,
    solve_steady_state_point_network,
    solve_transient_foster_step_point,
)
from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge


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


def _network(resistance: BoundedQuantity | None = None) -> ElectrothermalNetwork:
    return ElectrothermalNetwork(
        network_id="thermal:q1",
        scenario_id="normal",
        mission_profile_fingerprint="a" * 64,
        loss_ledger_fingerprint="b" * 64,
        nodes=(
            ThermalNode(
                node_id="ambient",
                kind=ThermalNodeKind.LOCAL_AMBIENT,
                subject_ids=("air",),
                fixed_temperature=_point("ambient_temperature", "25", "degC"),
            ),
            ThermalNode(
                node_id="case",
                kind=ThermalNodeKind.CASE,
                subject_ids=("Q1",),
            ),
            ThermalNode(
                node_id="junction",
                kind=ThermalNodeKind.JUNCTION,
                subject_ids=("Q1",),
            ),
        ),
        links=(
            ThermalLink(
                link_id="junction-case",
                node_a_id="junction",
                node_b_id="case",
                thermal_resistance=_point("rth_jc", "2", "K/W"),
                source_binding_ids=("evidence:rth_jc",),
            ),
            ThermalLink(
                link_id="case-ambient",
                node_a_id="case",
                node_b_id="ambient",
                thermal_resistance=resistance or _point("rth_ca", "3", "K/W"),
                source_binding_ids=("evidence:rth_ca",),
            ),
        ),
        heat_injections=(
            ThermalHeatInjection(
                injection_id="q1-loss",
                node_id="junction",
                power=_point("q1_power", "4", "W"),
                loss_identity_ids=("normal:Q1:total",),
            ),
        ),
        source_context_ids=("model:test",),
    )


def test_point_network_solves_series_temperature_rise() -> None:
    result = solve_steady_state_point_network(_network())
    assert result.disposition == "solved"
    temperatures = {item.node_id: item.temperature.nominal for item in result.node_results}
    assert temperatures == {
        "ambient": Decimal("25"),
        "case": Decimal("37"),
        "junction": Decimal("45"),
    }


def test_interval_input_fails_closed_instead_of_using_nominal() -> None:
    interval = BoundedQuantity(
        quantity_id="rth_ca",
        unit="K/W",
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal("2"),
        nominal=Decimal("3"),
        upper=Decimal("4"),
        evidence_binding_ids=("evidence:rth_ca",),
    )
    result = solve_steady_state_point_network(_network(interval))
    assert result.disposition == "indeterminate"
    assert result.node_results == ()
    assert "link:case-ambient:thermal_resistance_point" in result.missing_input_ids


def test_unresolved_power_is_not_treated_as_zero() -> None:
    network = _network()
    injection = network.heat_injections[0].model_copy(
        update={
            "power": BoundedQuantity(
                quantity_id="q1_power",
                unit="W",
                knowledge=QuantityKnowledge.UNRESOLVED,
                rationale="Switching loss is missing.",
            )
        }
    )
    result = solve_steady_state_point_network(
        network.model_copy(update={"heat_injections": (injection,)})
    )
    assert result.disposition == "indeterminate"
    assert "injection:q1-loss:power_point" in result.missing_input_ids


def _transient_model(*, power: BoundedQuantity | None = None) -> TransientThermalModel:
    return TransientThermalModel(
        model_id="transient:q1",
        scenario_id="peak",
        subject_id="Q1",
        steady_network_fingerprint="c" * 64,
        ambient_temperature=_point("ambient_temperature", "25", "degC"),
        step_power=power or _point("step_power", "4", "W"),
        duration=_point("duration", "10", "s"),
        branches=(
            TransientThermalBranch(
                branch_id="die-package",
                thermal_resistance=_point("branch_rth", "2", "K/W"),
                time_constant=_point("branch_tau", "5", "s"),
                source_binding_ids=("evidence:zth-fit",),
            ),
        ),
        source_context_ids=("model:test",),
    )


def test_point_foster_step_matches_first_order_response() -> None:
    result = solve_transient_foster_step_point(_transient_model())
    assert result.disposition == "solved"
    assert result.temperature_rise.nominal is not None
    assert abs(result.temperature_rise.nominal - Decimal("6.917317734107098")) < Decimal("1e-12")
    assert result.endpoint_temperature.nominal is not None
    assert abs(result.endpoint_temperature.nominal - Decimal("31.917317734107098")) < Decimal(
        "1e-12"
    )


def test_transient_solver_rejects_unresolved_loss() -> None:
    power = BoundedQuantity(
        quantity_id="step_power",
        unit="W",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Peak MOSFET loss is unresolved.",
    )
    result = solve_transient_foster_step_point(_transient_model(power=power))
    assert result.disposition == "indeterminate"
    assert "step_power" in result.missing_input_ids
    assert not result.endpoint_temperature.is_known


def _coupled_model(
    *,
    current: BoundedQuantity | None = None,
    thermal_resistance: BoundedQuantity | None = None,
    coefficient: BoundedQuantity | None = None,
) -> CoupledElectrothermalPointModel:
    return CoupledElectrothermalPointModel(
        model_id="coupled:q1",
        scenario_id="normal",
        subject_id="Q1",
        ambient_temperature=_point("ambient_temperature", "25", "degC"),
        current_rms=current or _point("current_rms", "10", "A"),
        conduction_fraction=_point("conduction_fraction", "0.5", "1"),
        resistance_reference=_point("resistance_reference", "0.01", "ohm"),
        resistance_reference_temperature=_point(
            "resistance_reference_temperature", "25", "degC"
        ),
        resistance_temperature_coefficient=coefficient
        or _point("resistance_temperature_coefficient", "0.004", "1/K"),
        fixed_loss=_point("fixed_loss", "1", "W"),
        junction_to_ambient_rth=thermal_resistance
        or _point("junction_to_ambient_rth", "2", "K/W"),
        convergence_tolerance=_point("convergence_tolerance", "0.000001", "K"),
        source_context_ids=("model:test",),
    )


def test_coupled_point_solver_converges_temperature_dependent_i2r() -> None:
    result = solve_coupled_electrothermal_point(_coupled_model())
    assert result.disposition == "solved"
    assert result.junction_temperature.nominal is not None
    assert abs(result.junction_temperature.nominal - Decimal("28.012048")) < Decimal(
        "0.000002"
    )
    assert result.conduction_loss.nominal is not None
    assert abs(result.conduction_loss.nominal - Decimal("0.506024")) < Decimal(
        "0.000002"
    )


def test_coupled_point_solver_fails_closed_for_unresolved_input() -> None:
    unknown_current = BoundedQuantity(
        quantity_id="current_rms",
        unit="A",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Current interpretation is unresolved.",
    )
    result = solve_coupled_electrothermal_point(_coupled_model(current=unknown_current))
    assert result.disposition == "indeterminate"
    assert result.missing_input_ids == ("current_rms",)
    assert not result.junction_temperature.is_known


def test_coupled_point_solver_detects_unstable_linearized_loop() -> None:
    result = solve_coupled_electrothermal_point(
        _coupled_model(
            current=_point("current_rms", "100", "A"),
            thermal_resistance=_point("junction_to_ambient_rth", "2", "K/W"),
            coefficient=_point("resistance_temperature_coefficient", "0.01", "1/K"),
        )
    )
    assert result.disposition == "nonconvergent"
    assert result.missing_input_ids == ("model:stable_electrothermal_loop_gain",)
