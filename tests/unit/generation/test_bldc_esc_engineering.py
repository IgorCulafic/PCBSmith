import json
from decimal import Decimal

from pcbsmith.generation.bldc_esc_engineering import (
    build_bldc_esc_engineering_bundle,
    write_bldc_esc_engineering_evidence,
)
from pcbsmith.loss_stress_ir import LossCalculationState, LossMechanism


def test_bldc_bundle_retains_shunt_loss_and_marks_mosfet_screening_provisional() -> None:
    bundle = build_bldc_esc_engineering_bundle()
    ledger = bundle["loss_stress_ledger"]
    shunt = next(
        item for item in ledger.losses if item.entry_id == "normal-target-60a-continuous.rsh-u.i2r"
    )
    assert shunt.output_power.lower == Decimal("1.782000")
    assert shunt.output_power.nominal == Decimal("1.800000")
    assert shunt.output_power.upper == Decimal("1.818000")
    assert shunt.state is LossCalculationState.COMPUTED

    conduction = next(
        item
        for item in ledger.losses
        if item.scenario_id == "normal.target-60a-continuous"
        and item.mechanism is LossMechanism.CONDUCTION_I2R
        and "Q_U_HS" in item.subject_ids
    )
    assert conduction.state is LossCalculationState.VALIDATION_REQUIRED
    assert conduction.missing_input_ids == ()
    assert conduction.output_power.lower is not None
    assert conduction.output_power.nominal is not None
    assert conduction.output_power.upper is not None
    assert conduction.output_power.lower.quantize(Decimal("0.001")) == Decimal("5.016")
    assert conduction.output_power.nominal.quantize(Decimal("0.001")) == Decimal("5.148")
    assert conduction.output_power.upper.quantize(Decimal("0.001")) == Decimal("5.280")
    assert bundle["gate_drive_evaluation"].disposition == "inadequate"
    assert bundle["gate_charge_capacity_result"].disposition == "indeterminate"
    assert (
        "simultaneously_switching_high_side_count"
        in bundle["gate_charge_capacity_result"].missing_input_ids
    )
    assert bundle["dead_time_evaluation"].disposition == "indeterminate"
    assert bundle["gate_supply_decision"].recommended_option_id == (
        "change-driver-drv8334-native-9v"
    )
    assert bundle["gate_supply_decision"].selection_state == "not_selected"
    assert bundle["gate_driver_migration_report"].disposition == ("conditional_candidate")
    assert bundle["gate_driver_migration_report"].pin_map_complete
    assert bundle["gate_driver_migration_report"].selection_state == "not_selected"
    assert bundle["gate_driver_migration_profile"].candidate.orderable_part_number == "DRV8334RGZR"
    assert "Texas_RGZ0048A" in bundle["gate_driver_migration_report"].proposed_footprint_id
    assert bundle["gate_driver_migration_report"].asset_compatibility_state == "geometry_candidate"
    assert bundle["gate_driver_bootstrap_result"].disposition == "indeterminate"
    assert bundle["gate_driver_bootstrap_result"].required_effective_capacitance.upper == (
        Decimal("0.0000003946902654867256637168141593")
    )
    assert bundle["gate_driver_support_report"].definition_state == "incomplete"
    assert bundle["gate_driver_support_report"].implementation_state == "blocked"
    assert bundle["gate_driver_support_report"].physical_component_count == 10
    assert set(bundle["gate_driver_support_report"].unresolved_requirement_ids) == {
        "cpvdd",
        "cvcp",
        "cvdrain",
    }
    assert bundle["protection_coordination_report"].disposition == "incomplete"
    assert len(bundle["protection_coordination_report"].evaluations) == 9
    assert all(
        item.disposition == "incomplete"
        for item in bundle["protection_coordination_report"].evaluations
    )
    assert bundle["surge_clamp_report"].disposition == "indeterminate"
    assert bundle["surge_clamp_report"].normal_standoff_headroom.lower == Decimal("0.8")
    assert "minimum_protected_bus_voltage_limit" in (bundle["surge_clamp_report"].missing_input_ids)
    assert any(
        "conditional arithmetic screen" in note for note in bundle["engineering_readiness"]["notes"]
    )


def test_bldc_coverage_fails_closed_on_environment_faults_and_loss_budget() -> None:
    bundle = build_bldc_esc_engineering_bundle()
    scenario = bundle["scenario_coverage"]
    loss = bundle["loss_coverage"]
    assert scenario.disposition == "incomplete"
    assert loss.disposition == "incomplete"
    assert bundle["electrothermal_result"].disposition == "indeterminate"
    assert bundle["electrothermal_result"].node_results == ()
    assert bundle["cooling_assembly_evaluation"].disposition == "incomplete"
    assert bundle["cooling_assembly_evaluation"].incomplete_interface_ids
    assert bundle["cooling_candidate_evaluation"].disposition == "incomplete"
    assert "fastener_or_clamp" in {
        item.value for item in bundle["cooling_candidate_evaluation"].uncovered_role_ids
    }
    assert bundle["coupled_electrothermal_result"].disposition == "indeterminate"
    assert "resistance_reference" in bundle["coupled_electrothermal_result"].missing_input_ids
    assert bundle["transient_thermal_result"].disposition == "indeterminate"
    assert "step_power" in bundle["transient_thermal_result"].missing_input_ids
    normal_thermal = next(
        item for item in scenario.evaluations if item.requirement_id == "normal.thermal-boundary"
    )
    assert not normal_thermal.satisfied
    assert any(
        "ambient temperature is unresolved" in finding for finding in normal_thermal.findings
    )
    assert bundle["engineering_readiness"]["status"] == "incomplete"
    assert all(
        value == "not_released"
        for value in bundle["engineering_readiness"]["release_claims"].values()
    )


def test_bldc_evidence_writer_emits_parseable_authority_files(tmp_path) -> None:
    summary = write_bldc_esc_engineering_evidence(tmp_path)
    assert summary["status"] == "incomplete"
    assert len(summary["evidence_files"]) == 34
    readiness = json.loads((tmp_path / "engineering-readiness.json").read_text())
    assert readiness["loss_coverage"] == "incomplete"
    assert (tmp_path / "engineering-evidence-register.json").is_file()
    assert (tmp_path / "electrothermal-network.json").is_file()
    assert (tmp_path / "cooling-assembly-profile.json").is_file()
    assert (tmp_path / "cooling-candidate-register.json").is_file()
    assert (tmp_path / "gate-drive-evaluation.json").is_file()
    assert (tmp_path / "gate-charge-capacity-result.json").is_file()
    assert (tmp_path / "dead-time-evaluation.json").is_file()
    assert (tmp_path / "gate-supply-options.json").is_file()
    assert (tmp_path / "gate-supply-decision.json").is_file()
    assert (tmp_path / "gate-driver-migration-profile.json").is_file()
    assert (tmp_path / "gate-driver-migration-report.json").is_file()
    assert (tmp_path / "gate-driver-bootstrap-profile.json").is_file()
    assert (tmp_path / "gate-driver-bootstrap-result.json").is_file()
    assert (tmp_path / "gate-driver-support-plan.json").is_file()
    assert (tmp_path / "gate-driver-support-report.json").is_file()
    assert (tmp_path / "protection-coordination-profile.json").is_file()
    assert (tmp_path / "protection-coordination-report.json").is_file()
    assert (tmp_path / "surge-clamp-profile.json").is_file()
    assert (tmp_path / "surge-clamp-report.json").is_file()
    assert (tmp_path / "coupled-electrothermal-result.json").is_file()
    assert (tmp_path / "transient-thermal-result.json").is_file()
