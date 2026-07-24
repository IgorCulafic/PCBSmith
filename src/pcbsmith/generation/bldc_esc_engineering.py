"""Evidence-bound operating, loss, and readiness authority for the BLDC ESC.

This slice intentionally stops at what the retained request and selected-part
datasheets support.  It does not turn typical switching data, absolute maximum
ratings, or an unrouted placement into a 60 A or thermal-capability claim.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from pcbsmith.bootstrap_supply_ir import (
    BootstrapCapacitanceProfile,
    evaluate_bootstrap_capacitance,
)
from pcbsmith.cooling_assembly_ir import (
    CoolingAssemblyProfile,
    CoolingAssemblyRequirement,
    CoolingCandidateRegister,
    CoolingCandidateStatus,
    CoolingInterface,
    CoolingPart,
    CoolingPartCandidate,
    CoolingPartRole,
    CoolingSelectionState,
    evaluate_cooling_assembly,
    evaluate_cooling_candidates,
)
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
from pcbsmith.engineering_evidence_ir import (
    EngineeringEvidenceFact,
    EngineeringEvidenceRegister,
)
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
from pcbsmith.gate_driver_migration_ir import (
    GateDriverFunctionMigration,
    GateDriverMigrationProfile,
    GateDriverPackageCandidate,
    GateDriverPinAssignment,
    MigrationDisposition,
    evaluate_gate_driver_migration,
)
from pcbsmith.gate_driver_support_ir import (
    GateDriverSupportPlan,
    GateDriverSupportRequirement,
    GateDriverSupportRole,
    evaluate_gate_driver_support_plan,
)
from pcbsmith.gate_supply_architecture_ir import (
    GateSupplyArchitectureKind,
    GateSupplyOption,
    evaluate_gate_supply_options,
)
from pcbsmith.loss_stress_ir import (
    LossCoverageRequirement,
    LossMechanism,
    LossStressLedger,
    calculate_i2r_duty_screening,
    calculate_i2r_loss,
    evaluate_loss_coverage,
    unresolved_loss_entry,
)
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
from pcbsmith.protection_coordination_ir import (
    ProtectionCoordinationProfile,
    ProtectionEventKind,
    ProtectionPath,
    ProtectionRequirement,
    evaluate_protection_coordination,
)
from pcbsmith.surge_clamp_ir import (
    ClampQualificationContext,
    SurgeClampProfile,
    evaluate_surge_clamp,
)

REQUEST_SOURCE_ID = "request:bldc-esc-baseline-2026-07"
MOSFET_SOURCE_ID = "part:Infineon:IPTC011N08NM5ATMA1:datasheet"
MOSFET_SHA256 = "e30473eeb2699eb28ad595b93dac5846efee85ad0364b56eeffd3a42da8a0222"
SHUNT_SOURCE_ID = "part:Vishay:WSLP2726L5000FEA:datasheet"
SHUNT_SHA256 = "1c3385e4b14f07808333c026393b88e0da1c23671fbb30e66a3fb86e3960a337"
CURRENT_INTERPRETATION_ID = "assumption:esc-current-is-phase-shunt-rms-r1"
SIX_STEP_CONDUCTION_ID = "assumption:six-step-phase-leg-pair-duty-r1"
HOT_RDSON_SCREEN_ID = "assumption:typical-rdson-temperature-factor-screen-r1"
COOLING_ENVELOPE_ID = "assumption:bldc-r002-cooling-envelope-r1"
INFINEON_ASSEMBLY_SOURCE_ID = "guide:Infineon:package-assembly:DS1-2008-03"
INFINEON_ASSEMBLY_SHA256 = "577388400a5e888a869b81a7cf9d4f494cdda874a233a2b806ee17b75966ac71"
INFINEON_MOSFET_GUIDE_SOURCE_ID = "guide:Infineon:designing-power-mosfets:v1.1"
INFINEON_MOSFET_GUIDE_SHA256 = "4b94b144f51a63300da52def2d882b41c2851abf589d81e2cde3514699b52fae"
TOLT_GUIDE_SOURCE_ID = "guide:Infineon:TOLT-package:v1.1"
TOLT_GUIDE_SHA256 = "1f3e5659896485157124bee19163528b1ca10d2c00c3c34ca23b4a136ccbf3c6"
HENKEL_TIM_SOURCE_ID = "part:Henkel:BERGQUIST-SIL-PAD-TSP-A2000:tds"
HENKEL_TIM_SHA256 = "f6e3207f2ebdfc0c6a5c263c1c3e2277134606922c80eb105875fa550e71002c"
BOYD_SINK_SOURCE_ID = "part:Boyd:MaxClip-78045:catalog"
BOYD_SINK_SHA256 = "331a7fd3e836e27da6bcf8e3decdc413acb73d72fc98b87940c42c2ea12f8314"
DELTA_FAN_SOURCE_ID = "part:Delta:AUB0405VD-00:datasheet"
DELTA_FAN_SHA256 = "db4fb38a4a37e03e32e83a600a05dbb6ac97b0ac7fa25019a4fc45af61507b01"
GATE_DRIVER_SOURCE_ID = "part:TI:DRV8353:datasheet"
GATE_DRIVER_SHA256 = "f440d3fae4c79d04078679ee6f3122d9aae2e169833a577fd993780204c3849e"
DRV8334_SOURCE_ID = "part:TI:DRV8334:datasheet"
DRV8334_SHA256 = "cbd131d62e0eb44f1e18b9ded61d296bfd789451674e5305a637c2c0a3fa9ecc"
TVS_SOURCE_ID = "part:Vishay:7KPD26A-M3-I:datasheet"
TVS_SHA256 = "6b6ac7931656bd87412967f26e2d71455f3f4e578513ea395c639240fea91c90"
DRV8334_KICAD_FOOTPRINT_ID = "Package_DFN_QFN:Texas_RGZ0048A_VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm"
DRV8334_KICAD_FOOTPRINT_SHA256 = "739d7f90af78d0a6076f7f0d7f699f1729aca5fea3f7e8871c2d3ee9a4732d2f"
DRV8334_KICAD_MODEL_ID = (
    "Package_DFN_QFN.3dshapes/Texas_RGZ0048A_VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm.step"
)
DRV8334_KICAD_MODEL_SHA256 = "e9db0afa44d256cc5824b646bd84781f9960a1e23484fcee1060e6055c441674"
UNSPECIFIED_MINIMUM_RATIONALE = (
    "No minimum is specified; zero is retained as the non-claiming lower bound."
)


def _known(
    quantity_id: str,
    unit: str,
    lower: str,
    nominal: str,
    upper: str,
    *,
    knowledge: QuantityKnowledge,
    evidence: tuple[str, ...],
    rationale: str | None = None,
) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=knowledge,
        lower=Decimal(lower),
        nominal=Decimal(nominal),
        upper=Decimal(upper),
        evidence_binding_ids=evidence,
        rationale=rationale,
    )


def _unknown(quantity_id: str, unit: str, rationale: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale=rationale,
    )


def build_bldc_esc_evidence_register() -> EngineeringEvidenceRegister:
    """Internalize only directly inspected values and their test conditions."""

    facts = (
        EngineeringEvidenceFact(
            fact_id="mosfet.breakdown-voltage-min",
            subject_id="IPTC011N08NM5ATMA1",
            parameter_id="drain_source_breakdown_voltage_min",
            quantity=_known(
                "drain_source_breakdown_voltage_min",
                "V",
                "80",
                "80",
                "80",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(MOSFET_SOURCE_ID,),
            ),
            source_id=MOSFET_SOURCE_ID,
            source_sha256=MOSFET_SHA256,
            locator="Rev. 2.0, page 4, Table 4",
            test_condition_ids=("VGS=0V", "ID=1mA", "Tj=25degC unless specified"),
            applicability_notes=(
                "Breakdown minimum is not a permitted operating point.",
                "Drain overshoot and a project derating policy remain unresolved.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="mosfet.gate-charge-total",
            subject_id="IPTC011N08NM5ATMA1",
            parameter_id="total_gate_charge",
            quantity=_known(
                "total_gate_charge",
                "nC",
                "0",
                "178",
                "223",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(MOSFET_SOURCE_ID,),
                rationale=UNSPECIFIED_MINIMUM_RATIONALE,
            ),
            source_id=MOSFET_SOURCE_ID,
            source_sha256=MOSFET_SHA256,
            locator="Rev. 2.0, page 4, Table 6",
            test_condition_ids=("VDD=40V", "ID=100A", "VGS=0V-to-10V"),
            applicability_notes=(
                "The ESC bus is 9V to 25.2V, so direct use requires an applicability model.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="mosfet.rds-on-25c-10v",
            subject_id="IPTC011N08NM5ATMA1",
            parameter_id="drain_source_on_resistance",
            quantity=_known(
                "drain_source_on_resistance",
                "ohm",
                "0",
                "0.0010",
                "0.0011",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(MOSFET_SOURCE_ID,),
                rationale=UNSPECIFIED_MINIMUM_RATIONALE,
            ),
            source_id=MOSFET_SOURCE_ID,
            source_sha256=MOSFET_SHA256,
            locator="Rev. 2.0, page 4, Table 4",
            test_condition_ids=("VGS=10V", "ID=150A", "Tj=25degC"),
            applicability_notes=(
                "This is not hot RDS(on).",
                "Page 8 Diagram 9 is typical-only and cannot create a guaranteed hot maximum.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="mosfet.rds-on-25c-6v",
            subject_id="IPTC011N08NM5ATMA1",
            parameter_id="drain_source_on_resistance",
            quantity=_known(
                "drain_source_on_resistance_at_6v",
                "ohm",
                "0",
                "0.0015",
                "0.0017",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(MOSFET_SOURCE_ID,),
                rationale=UNSPECIFIED_MINIMUM_RATIONALE,
            ),
            source_id=MOSFET_SOURCE_ID,
            source_sha256=MOSFET_SHA256,
            locator="Rev. 2.0, page 4, Table 4",
            test_condition_ids=("VGS=6V", "ID=75A", "Tj=25degC"),
            applicability_notes=(
                "This is the lowest tabulated gate-voltage condition in the datasheet.",
                "It is not characterized below 6V or at 100A under the 6V condition.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="driver.high-side-vgs-at-vm-9v",
            subject_id="DRV8353",
            parameter_id="high_side_gate_drive_voltage",
            quantity=_known(
                "high_side_gate_drive_voltage_at_vm_9v",
                "V",
                "5.5",
                "7.5",
                "8.5",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(GATE_DRIVER_SOURCE_ID,),
            ),
            source_id=GATE_DRIVER_SOURCE_ID,
            source_sha256=GATE_DRIVER_SHA256,
            locator="Revision D, electrical characteristics, GHx high-level voltage",
            test_condition_ids=("VM=9V", "IGATE=10mA"),
            applicability_notes=(
                "The retained schematic ties VM and VDRAIN to BAT_P.",
                "The minimum is below the MOSFET's lowest 6V RDS(on) condition.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="driver.low-side-vgs-at-vm-9v",
            subject_id="DRV8353",
            parameter_id="low_side_gate_drive_voltage",
            quantity=_known(
                "low_side_gate_drive_voltage_at_vm_9v",
                "V",
                "6.5",
                "8",
                "9.5",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(GATE_DRIVER_SOURCE_ID,),
            ),
            source_id=GATE_DRIVER_SOURCE_ID,
            source_sha256=GATE_DRIVER_SHA256,
            locator="Revision D, electrical characteristics, GLx high-level voltage",
            test_condition_ids=("VM=9V", "IGATE=10mA"),
            applicability_notes=(
                "This clears 6V only at the guaranteed minimum; no design margin is present.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="mosfet.rth-junction-case",
            subject_id="IPTC011N08NM5ATMA1",
            parameter_id="thermal_resistance_junction_case",
            quantity=_known(
                "thermal_resistance_junction_case",
                "degC/W",
                "0",
                "0.2",
                "0.4",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(MOSFET_SOURCE_ID,),
                rationale=UNSPECIFIED_MINIMUM_RATIONALE,
            ),
            source_id=MOSFET_SOURCE_ID,
            source_sha256=MOSFET_SHA256,
            locator="Rev. 2.0, page 3, Table 3",
            test_condition_ids=("junction-to-case path",),
            applicability_notes=(
                "This excludes TIM, clamp, spreader, heatsink, and ambient resistances.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="mosfet.rds-temperature-factor-175c-screening",
            subject_id="IPTC011N08NM5ATMA1",
            parameter_id="typical_normalized_rds_temperature_factor",
            quantity=_known(
                "rds_temperature_factor_175c_screening",
                "ratio",
                "1.9",
                "1.95",
                "2.0",
                knowledge=QuantityKnowledge.ASSUMPTION,
                evidence=(MOSFET_SOURCE_ID, HOT_RDSON_SCREEN_ID),
                rationale=(
                    "Manually bounded reading of the typical-only normalized RDS(on) "
                    "curve. It is a screening assumption, not a guaranteed maximum."
                ),
            ),
            source_id=MOSFET_SOURCE_ID,
            source_sha256=MOSFET_SHA256,
            locator="Rev. 2.0, page 8, Diagram 9",
            test_condition_ids=("ID=150A", "VGS=10V", "Tj=175degC-screening"),
            applicability_notes=(
                "Diagram 9 is a typical characteristic and cannot satisfy a release limit.",
                "The 1.9 to 2.0 interval is a manually bounded graph reading for screening.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="mosfet.reverse-diode-forward-voltage",
            subject_id="IPTC011N08NM5ATMA1",
            parameter_id="reverse_diode_forward_voltage",
            quantity=_known(
                "reverse_diode_forward_voltage",
                "V",
                "0",
                "0.88",
                "1.0",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(MOSFET_SOURCE_ID,),
                rationale=UNSPECIFIED_MINIMUM_RATIONALE,
            ),
            source_id=MOSFET_SOURCE_ID,
            source_sha256=MOSFET_SHA256,
            locator="Rev. 2.0, page 5, Table 7",
            test_condition_ids=("VGS=0V", "IF=150A", "Tj=25degC"),
            applicability_notes=(
                "Dead time and the actual diode-current waveform remain unresolved.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="shunt.resistance-25c-tolerance",
            subject_id="WSLP2726L5000FEA",
            parameter_id="resistance",
            quantity=_known(
                "shunt_resistance",
                "ohm",
                "0.000495",
                "0.000500",
                "0.000505",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(SHUNT_SOURCE_ID,),
            ),
            source_id=SHUNT_SOURCE_ID,
            source_sha256=SHUNT_SHA256,
            locator="Rev. 29-Jun-2026, page 1, ordering-code table",
            test_condition_ids=("L5000=0.0005ohm", "F=tolerance-plus-minus-1percent"),
            applicability_notes=(
                "Temperature coefficient and terminal heating are not included in this interval.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="shunt.thermal-resistance",
            subject_id="WSLP2726L5000FEA",
            parameter_id="thermal_resistance_element_to_terminal",
            quantity=_known(
                "thermal_resistance_element_to_terminal",
                "degC/W",
                "6",
                "6",
                "6",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(SHUNT_SOURCE_ID,),
            ),
            source_id=SHUNT_SOURCE_ID,
            source_sha256=SHUNT_SHA256,
            locator="Rev. 29-Jun-2026, page 2, 0.5mOhm row",
            test_condition_ids=("resistance=0.5mohm", "element-to-terminal path"),
            applicability_notes=(
                "PCB-to-ambient thermal resistance and pad temperature remain unresolved.",
            ),
        ),
        EngineeringEvidenceFact(
            fact_id="shunt.power-rating-conditional",
            subject_id="WSLP2726L5000FEA",
            parameter_id="conditional_power_rating",
            quantity=_known(
                "conditional_power_rating",
                "W",
                "12",
                "12",
                "12",
                knowledge=QuantityKnowledge.DATASHEET_BOUND,
                evidence=(SHUNT_SOURCE_ID,),
            ),
            source_id=SHUNT_SOURCE_ID,
            source_sha256=SHUNT_SHA256,
            locator="Rev. 29-Jun-2026, page 1, standard electrical specifications",
            test_condition_ids=("resistance=0.2mohm-to-0.5mohm", "terminal_temperature=100degC"),
            applicability_notes=(
                "The datasheet says full rating depends on PCB heat dissipation.",
                "It must not be used as an unconditional 12W pass limit.",
            ),
        ),
    )
    return EngineeringEvidenceRegister(
        register_id="bldc-esc-r002-engineering-facts",
        revision="1",
        facts=facts,
        source_context_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            SHUNT_SOURCE_ID,
            HOT_RDSON_SCREEN_ID,
            INFINEON_ASSEMBLY_SOURCE_ID,
            INFINEON_MOSFET_GUIDE_SOURCE_ID,
            GATE_DRIVER_SOURCE_ID,
        ),
    )


def _environment(role: str) -> OperatingEnvironment:
    return OperatingEnvironment(
        ambient_temperature=_unknown(
            "ambient_temperature",
            "degC",
            f"Ambient temperature for the {role} scenario was not specified.",
        ),
        airflow_state=AirflowState.UNKNOWN,
        enclosure_state=EnclosureState.UNKNOWN,
        orientation="unresolved mounting orientation",
        condition_ids=("RC vehicle or robotics vibration/noise environment",),
    )


def _request_voltage() -> BoundedQuantity:
    return _known(
        "dc_bus_voltage_operating",
        "V",
        "9",
        "22.2",
        "25.2",
        knowledge=QuantityKnowledge.DESIGN_TARGET,
        evidence=(REQUEST_SOURCE_ID,),
        rationale="22.2V is the nominal voltage of the requested 6S upper configuration.",
    )


def _request_pwm() -> BoundedQuantity:
    return _known(
        "pwm_frequency",
        "Hz",
        "20000",
        "25000",
        "30000",
        knowledge=QuantityKnowledge.DESIGN_TARGET,
        evidence=(REQUEST_SOURCE_ID,),
    )


def _rated_current(quantity_id: str, amperes: str) -> BoundedQuantity:
    return _known(
        quantity_id,
        "A",
        amperes,
        amperes,
        amperes,
        knowledge=QuantityKnowledge.DESIGN_TARGET,
        evidence=(REQUEST_SOURCE_ID,),
        rationale=(
            "The request does not define whether this rating is DC-bus, motor-line RMS, "
            "or phase-peak current."
        ),
    )


def _assumed_phase_shunt_rms(amperes: str) -> BoundedQuantity:
    return _known(
        "phase_shunt_current_rms",
        "A",
        amperes,
        amperes,
        amperes,
        knowledge=QuantityKnowledge.ASSUMPTION,
        evidence=(REQUEST_SOURCE_ID, CURRENT_INTERPRETATION_ID),
        rationale=(
            "Conservative preliminary interpretation: the ambiguous controller current "
            "rating is treated as RMS current through one active inline phase shunt. "
            "This is not a confirmed motor waveform definition."
        ),
    )


def build_bldc_esc_mission_profile() -> MissionProfile:
    prototype = OperatingScenario(
        scenario_id="normal.prototype-30a-limit",
        role=ScenarioRole.NORMAL,
        description="Initial firmware-limited prototype operation.",
        steady_state=True,
        fault_scenario=False,
        duty_fraction=None,
        electrical_quantities=(
            _request_voltage(),
            _request_pwm(),
            _rated_current("controller_current_target", "30"),
            _assumed_phase_shunt_rms("30"),
        ),
        environment=_environment("prototype"),
        active_path_ids=("dc-link", "phase-u-half-bridge", "phase-u-inline-shunt"),
        source_context_ids=(REQUEST_SOURCE_ID, CURRENT_INTERPRETATION_ID),
    )
    continuous = OperatingScenario(
        scenario_id="normal.target-60a-continuous",
        role=ScenarioRole.NORMAL,
        description="Requested 60A continuous target; not a released capability.",
        steady_state=True,
        fault_scenario=False,
        duty_fraction=None,
        electrical_quantities=(
            _request_voltage(),
            _request_pwm(),
            _rated_current("controller_current_target", "60"),
            _assumed_phase_shunt_rms("60"),
        ),
        environment=_environment("60A continuous target"),
        active_path_ids=("dc-link", "phase-u-half-bridge", "phase-u-inline-shunt"),
        source_context_ids=(REQUEST_SOURCE_ID, CURRENT_INTERPRETATION_ID),
    )
    peak = OperatingScenario(
        scenario_id="peak.target-100a-10s",
        role=ScenarioRole.PEAK,
        description="Requested 100A peak target for no more than ten seconds.",
        steady_state=False,
        fault_scenario=False,
        duration=_known(
            "scenario_duration",
            "s",
            "0",
            "10",
            "10",
            knowledge=QuantityKnowledge.DESIGN_TARGET,
            evidence=(REQUEST_SOURCE_ID,),
        ),
        electrical_quantities=(
            _request_voltage(),
            _request_pwm(),
            _rated_current("controller_current_target", "100"),
            _assumed_phase_shunt_rms("100"),
        ),
        environment=_environment("100A peak target"),
        active_path_ids=("dc-link", "phase-u-half-bridge", "phase-u-inline-shunt"),
        source_context_ids=(REQUEST_SOURCE_ID, CURRENT_INTERPRETATION_ID),
    )

    def unresolved_scenario(
        scenario_id: str,
        role: ScenarioRole,
        description: str,
        quantities: tuple[BoundedQuantity, ...],
        *,
        fault_scenario: bool = True,
    ) -> OperatingScenario:
        return OperatingScenario(
            scenario_id=scenario_id,
            role=role,
            description=description,
            steady_state=False,
            fault_scenario=fault_scenario,
            duration=_unknown(
                "scenario_duration",
                "s",
                f"Clearing or persistence time for {scenario_id} is not yet defined.",
            ),
            electrical_quantities=quantities,
            environment=_environment(scenario_id),
            active_path_ids=("dc-link", "phase-u-half-bridge"),
            source_context_ids=(REQUEST_SOURCE_ID,),
        )

    scenarios = (
        prototype,
        continuous,
        peak,
        unresolved_scenario(
            "transient.startup",
            ScenarioRole.STARTUP,
            "Power-stage enable and motor-start transient.",
            (
                _request_voltage(),
                _unknown(
                    "startup_current",
                    "A",
                    "Motor, ramp, commutation, and load are not selected.",
                ),
            ),
            fault_scenario=False,
        ),
        unresolved_scenario(
            "fault.motor-stall",
            ScenarioRole.OVERLOAD_OR_STALL,
            "Motor-stall current and hardware trip response.",
            (
                _request_voltage(),
                _unknown("fault_current", "A", "Motor impedance and trip threshold are unknown."),
            ),
        ),
        unresolved_scenario(
            "fault.regenerative-overvoltage",
            ScenarioRole.REGENERATIVE,
            "Regenerative current raises the local DC bus.",
            (
                _unknown(
                    "dc_bus_voltage_peak", "V", "Motor energy and clamp behavior are unknown."
                ),
                _unknown("regenerative_current", "A", "Regenerative current is not specified."),
            ),
        ),
        unresolved_scenario(
            "fault.hot-plug",
            ScenarioRole.HOT_PLUG,
            "Battery hot-plug/inrush and cable-inductance overshoot.",
            (
                _unknown(
                    "dc_bus_voltage_peak", "V", "Cable inductance and inrush network are unknown."
                ),
                _unknown(
                    "inrush_current_peak",
                    "A",
                    "Source impedance and anti-spark behavior are unknown.",
                ),
            ),
        ),
        unresolved_scenario(
            "fault.phase-short",
            ScenarioRole.SHORT_CIRCUIT,
            "Phase or bridge short before hardware shutdown.",
            (
                _unknown(
                    "fault_current", "A", "Loop impedance and hardware trip threshold are unknown."
                ),
                _unknown(
                    "mosfet_drain_voltage_peak",
                    "V",
                    "Short-circuit commutation overshoot is unknown.",
                ),
            ),
        ),
        unresolved_scenario(
            "fault.cooling-loss",
            ScenarioRole.COOLING_FAILURE,
            "Forced airflow is lost and passive-current derating must protect the assembly.",
            (
                _unknown(
                    "allowed_controller_current", "A", "Passive cooling derating is not defined."
                ),
                _unknown(
                    "mosfet_junction_temperature", "degC", "Electrothermal model is incomplete."
                ),
            ),
        ),
        unresolved_scenario(
            "transient.shutdown",
            ScenarioRole.SHUTDOWN,
            "Commanded or fault shutdown while motor and DC-link energy decay.",
            (
                _unknown(
                    "shutdown_phase_current",
                    "A",
                    "Motor current at shutdown is operating-point dependent.",
                ),
                _unknown(
                    "dc_bus_voltage_peak",
                    "V",
                    "Shutdown regeneration and clamp response are unresolved.",
                ),
            ),
            fault_scenario=False,
        ),
    )
    return MissionProfile(
        profile_id="bldc-esc-r002-mission-profile",
        revision="1",
        scenarios=scenarios,
        duty_cycle_complete=False,
        intended_claim_ids=(
            "prototype-30a-bringup-candidate",
            "target-60a-continuous",
            "target-100a-10s-peak",
        ),
        source_context_ids=(REQUEST_SOURCE_ID,),
    )


def bldc_esc_scenario_requirements() -> tuple[ScenarioCoverageRequirement, ...]:
    return (
        ScenarioCoverageRequirement(
            requirement_id="normal.electrical-definition",
            role=ScenarioRole.NORMAL,
            minimum_scenarios=2,
            required_quantity_ids=(
                "controller_current_target",
                "dc_bus_voltage_operating",
                "pwm_frequency",
            ),
            rationale="Prototype and target operation need explicit electrical boundaries.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="normal.thermal-boundary",
            role=ScenarioRole.NORMAL,
            minimum_scenarios=2,
            required_quantity_ids=("phase_shunt_current_rms",),
            requires_duty_fraction=True,
            requires_known_airflow=True,
            requires_known_enclosure=True,
            requires_known_ambient_temperature=True,
            rationale="A continuous thermal claim requires environment and mission duty.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="peak.electrical-definition",
            role=ScenarioRole.PEAK,
            required_quantity_ids=("controller_current_target", "phase_shunt_current_rms"),
            requires_duration=True,
            rationale="Peak loss and transient thermal impedance require magnitude and duration.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="transient.startup",
            role=ScenarioRole.STARTUP,
            required_quantity_ids=("startup_current",),
            requires_duration=True,
            rationale="Startup loss and fault behavior require a motor/load ramp boundary.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="fault.stall",
            role=ScenarioRole.OVERLOAD_OR_STALL,
            required_quantity_ids=("fault_current",),
            requires_duration=True,
            rationale="Stall survival requires current and hardware clearing time.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="fault.regeneration",
            role=ScenarioRole.REGENERATIVE,
            required_quantity_ids=("dc_bus_voltage_peak", "regenerative_current"),
            requires_duration=True,
            rationale="Regenerative overvoltage needs an energy/current boundary.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="fault.hot-plug",
            role=ScenarioRole.HOT_PLUG,
            required_quantity_ids=("dc_bus_voltage_peak", "inrush_current_peak"),
            requires_duration=True,
            rationale="Hot-plug protection needs source impedance and transient duration.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="fault.short-circuit",
            role=ScenarioRole.SHORT_CIRCUIT,
            required_quantity_ids=("fault_current", "mosfet_drain_voltage_peak"),
            requires_duration=True,
            rationale="Short-circuit safety needs bounded hardware response.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="fault.cooling-loss",
            role=ScenarioRole.COOLING_FAILURE,
            required_quantity_ids=("allowed_controller_current", "mosfet_junction_temperature"),
            requires_duration=True,
            rationale="Loss of airflow needs a verified passive derating state.",
        ),
        ScenarioCoverageRequirement(
            requirement_id="transient.shutdown",
            role=ScenarioRole.SHUTDOWN,
            required_quantity_ids=("dc_bus_voltage_peak", "shutdown_phase_current"),
            requires_duration=True,
            rationale="Shutdown needs motor-energy, clamp, and safe-state timing boundaries.",
        ),
    )


def _hot_rdson_screening(
    register: EngineeringEvidenceRegister,
) -> BoundedQuantity:
    """Return a conservative-but-typical hot RDS(on) screen, never a release bound."""

    room = register.fact("mosfet.rds-on-25c-10v").quantity
    factor = register.fact("mosfet.rds-temperature-factor-175c-screening").quantity
    assert room.upper is not None
    assert factor.lower is not None and factor.nominal is not None and factor.upper is not None
    return BoundedQuantity(
        quantity_id="hot_rds_on_175c_screening",
        unit="ohm",
        knowledge=QuantityKnowledge.DERIVED_BOUNDED,
        lower=room.upper * factor.lower,
        nominal=room.upper * factor.nominal,
        upper=room.upper * factor.upper,
        evidence_binding_ids=(MOSFET_SOURCE_ID, HOT_RDSON_SCREEN_ID),
        rationale=(
            "The guaranteed maximum 25 degC RDS(on) is multiplied by a manually bounded "
            "typical-only 175 degC factor. This is deliberately screening-only."
        ),
    )


def _six_step_pair_conduction_fraction() -> BoundedQuantity:
    value = Decimal("0.6666666666666666666666666667")
    return BoundedQuantity(
        quantity_id="phase_leg_pair_conduction_fraction_screening",
        unit="ratio",
        knowledge=QuantityKnowledge.ASSUMPTION,
        lower=value,
        nominal=value,
        upper=value,
        evidence_binding_ids=(SIX_STEP_CONDUCTION_ID,),
        rationale=(
            "Preliminary aggregate high-side plus low-side phase-leg conduction fraction "
            "for six-step commutation. PWM strategy and current waveform remain unconfirmed."
        ),
    )


def build_bldc_esc_loss_ledger(
    profile: MissionProfile,
    register: EngineeringEvidenceRegister,
) -> LossStressLedger:
    shunt_resistance = register.fact("shunt.resistance-25c-tolerance").quantity
    hot_rdson_screening = _hot_rdson_screening(register)
    conduction_fraction = _six_step_pair_conduction_fraction()
    losses = []
    selected = (
        "normal.prototype-30a-limit",
        "normal.target-60a-continuous",
        "peak.target-100a-10s",
    )
    for scenario_id in selected:
        scenario = next(item for item in profile.scenarios if item.scenario_id == scenario_id)
        current = scenario.quantity("phase_shunt_current_rms")
        assert current is not None
        token = scenario_id.replace(".", "-")
        losses.append(
            calculate_i2r_loss(
                entry_id=f"{token}.rsh-u.i2r",
                loss_identity_id=f"{scenario_id}:RSH_U:resistive-element",
                scenario_id=scenario_id,
                subject_ids=("RSH_U", "phase-u-power-path"),
                mechanism=LossMechanism.CONDUCTION_I2R,
                current=current,
                resistance=shunt_resistance,
                source_binding_ids=(SHUNT_SOURCE_ID, CURRENT_INTERPRETATION_ID),
            )
        )
        losses.append(
            calculate_i2r_duty_screening(
                entry_id=f"{token}.phase-u-mosfets.conduction_i2r",
                loss_identity_id=f"{scenario_id}:Q_U_HS+Q_U_LS:conduction_i2r",
                scenario_id=scenario_id,
                subject_ids=("Q_U_HS", "Q_U_LS", "phase-u-power-path"),
                current=current,
                resistance=hot_rdson_screening,
                conduction_fraction=conduction_fraction,
                source_binding_ids=(
                    MOSFET_SOURCE_ID,
                    HOT_RDSON_SCREEN_ID,
                    SIX_STEP_CONDUCTION_ID,
                ),
                applicability_condition_ids=(
                    "VGS=10V-at-each-conducting-MOSFET",
                    "ID-condition-applicability-reviewed",
                    "Tj-screening-target=175degC",
                    "phase-current-semantics=phase-shunt-rms",
                    "commutation=six-step-preliminary-duty",
                ),
                findings=(
                    "Current semantics are an explicit preliminary phase-RMS assumption.",
                    "The 175 degC resistance factor is typical-only, not guaranteed.",
                    "Aggregate conduction duty requires commutation and PWM validation.",
                    "No electrothermal convergence has been performed.",
                ),
            )
        )
        missing_by_mechanism = {
            LossMechanism.SWITCHING: (
                "measured_or_bounded_vds_transition",
                "measured_or_bounded_id_transition",
                "gate_resistance_and_driver_impedance",
            ),
            LossMechanism.GATE_DRIVE: (
                "actual_gate_drive_voltage",
                "gate_charge_applicability_model",
            ),
            LossMechanism.BODY_DIODE_DEAD_TIME: (
                "dead_time",
                "diode_current_waveform",
                "hot_forward_voltage",
            ),
        }
        for mechanism, missing in missing_by_mechanism.items():
            losses.append(
                unresolved_loss_entry(
                    entry_id=f"{token}.phase-u-mosfets.{mechanism.value}",
                    loss_identity_id=(f"{scenario_id}:Q_U_HS+Q_U_LS:{mechanism.value}"),
                    scenario_id=scenario_id,
                    subject_ids=("Q_U_HS", "Q_U_LS", "phase-u-power-path"),
                    mechanism=mechanism,
                    missing_input_ids=missing,
                    source_binding_ids=(MOSFET_SOURCE_ID,),
                    rationale=(
                        f"{mechanism.value} is not numerically released because required "
                        "operating or applicability inputs are unresolved."
                    ),
                )
            )

    continuous_id = "normal.target-60a-continuous"
    for mechanism, subject, missing in (
        (
            LossMechanism.CONNECTOR_CONTACT,
            "J_BAT_POS+J_BAT_NEG+J_PHASE_U",
            ("contact_resistance_hot", "terminal_current_distribution"),
        ),
        (
            LossMechanism.PCB_COPPER,
            "phase-u-and-dc-link-copper",
            ("routed_geometry", "stackup_foil_and_plating", "copper_temperature"),
        ),
        (
            LossMechanism.CAPACITOR_ESR,
            "dc-link-capacitor-bank",
            ("phase_resolved_ripple_current", "hot_esr", "capacitor_current_sharing"),
        ),
    ):
        losses.append(
            unresolved_loss_entry(
                entry_id=f"normal-target-60a.{mechanism.value}",
                loss_identity_id=f"{continuous_id}:{subject}:{mechanism.value}",
                scenario_id=continuous_id,
                subject_ids=(subject, "phase-u-power-path"),
                mechanism=mechanism,
                missing_input_ids=missing,
                source_binding_ids=(REQUEST_SOURCE_ID,),
                rationale=(
                    f"{mechanism.value} requires the routed board and selected hot component data."
                ),
            )
        )

    return LossStressLedger(
        ledger_id="bldc-esc-r002-loss-stress-ledger",
        mission_profile_id=profile.profile_id,
        mission_profile_fingerprint=profile.semantic_fingerprint(),
        losses=tuple(losses),
        stress_limits=(),
        stress_results=(),
        source_context_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            SHUNT_SOURCE_ID,
            CURRENT_INTERPRETATION_ID,
            HOT_RDSON_SCREEN_ID,
            SIX_STEP_CONDUCTION_ID,
        ),
    )


def bldc_esc_loss_requirements() -> tuple[LossCoverageRequirement, ...]:
    requirements = []
    mechanisms = (
        LossMechanism.CONDUCTION_I2R,
        LossMechanism.SWITCHING,
        LossMechanism.GATE_DRIVE,
        LossMechanism.BODY_DIODE_DEAD_TIME,
    )
    for scenario_id in (
        "normal.prototype-30a-limit",
        "normal.target-60a-continuous",
        "peak.target-100a-10s",
    ):
        requirements.append(
            LossCoverageRequirement(
                requirement_id=f"{scenario_id}.phase-u-mosfet-losses",
                scenario_id=scenario_id,
                subject_id="Q_U_HS",
                required_mechanisms=mechanisms,
                rationale=(
                    "Each switch position needs conduction, transition, drive, and dead-time loss."
                ),
            )
        )
        requirements.append(
            LossCoverageRequirement(
                requirement_id=f"{scenario_id}.phase-u-shunt-loss",
                scenario_id=scenario_id,
                subject_id="RSH_U",
                required_mechanisms=(LossMechanism.CONDUCTION_I2R,),
                rationale="Inline shunt self-heating is part of the phase loss budget.",
            )
        )
    requirements.append(
        LossCoverageRequirement(
            requirement_id="normal.target-60a-continuous.path-parasitic-losses",
            scenario_id="normal.target-60a-continuous",
            subject_id="phase-u-power-path",
            required_mechanisms=(
                LossMechanism.CONNECTOR_CONTACT,
                LossMechanism.PCB_COPPER,
                LossMechanism.CAPACITOR_ESR,
            ),
            rationale=(
                "A bridge loss budget must include connectors, routed copper, and DC-link ESR."
            ),
        )
    )
    return tuple(requirements)


def build_bldc_esc_electrothermal_network(
    profile: MissionProfile,
    ledger: LossStressLedger,
) -> ElectrothermalNetwork:
    """Declare the Phase-U heat-flow topology without inventing missing values."""

    continuous = next(
        item for item in profile.scenarios if item.scenario_id == "normal.target-60a-continuous"
    )
    ambient = continuous.environment.ambient_temperature
    unknown_resistances = {
        "switch-pair-junction-to-package-surface": (
            "Equivalent Rth depends on high/low-side loss split and package temperatures."
        ),
        "package-surface-to-tim": (
            "Selected TIM material, thickness, area, pressure, and contact resistance are missing."
        ),
        "tim-to-spreader": ("TIM wetting/contact and exact spreader interface are unqualified."),
        "spreader-to-heatsink": (
            "Spreader/heatsink contact construction and clamp force are unresolved."
        ),
        "heatsink-to-local-ambient": (
            "Selected heatsink geometry, orientation, airflow, and enclosure are unresolved."
        ),
        "package-surface-to-pcb-territory": (
            "Routed copper, solder, pad, stackup, and lateral board spreading are unresolved."
        ),
        "pcb-territory-to-local-ambient": (
            "Board convection/radiation and enclosure boundary conditions are unresolved."
        ),
    }

    def resistance(link_id: str) -> BoundedQuantity:
        return _unknown(
            "thermal_resistance",
            "K/W",
            unknown_resistances[link_id],
        )

    nodes = (
        ThermalNode(
            node_id="phase-u-switch-pair-junction-equivalent",
            kind=ThermalNodeKind.JUNCTION,
            subject_ids=("Q_U_HS", "Q_U_LS"),
        ),
        ThermalNode(
            node_id="phase-u-package-top-surface",
            kind=ThermalNodeKind.PACKAGE_SURFACE,
            subject_ids=("Q_U_HS", "Q_U_LS"),
        ),
        ThermalNode(
            node_id="phase-u-tim",
            kind=ThermalNodeKind.TIM,
            subject_ids=("TIM_U_HS", "TIM_U_LS"),
        ),
        ThermalNode(
            node_id="shared-spreader",
            kind=ThermalNodeKind.SPREADER,
            subject_ids=("shared-spreader",),
        ),
        ThermalNode(
            node_id="shared-heatsink",
            kind=ThermalNodeKind.HEATSINK,
            subject_ids=("HS1",),
        ),
        ThermalNode(
            node_id="phase-u-pcb-territory",
            kind=ThermalNodeKind.PCB_TERRITORY,
            subject_ids=("phase-u-copper-territory",),
        ),
        ThermalNode(
            node_id="local-ambient",
            kind=ThermalNodeKind.LOCAL_AMBIENT,
            subject_ids=("air-boundary-near-phase-u",),
            fixed_temperature=ambient,
        ),
    )
    link_pairs = (
        (
            "switch-pair-junction-to-package-surface",
            "phase-u-switch-pair-junction-equivalent",
            "phase-u-package-top-surface",
            (MOSFET_SOURCE_ID,),
        ),
        (
            "package-surface-to-tim",
            "phase-u-package-top-surface",
            "phase-u-tim",
            ("mechanical:TIM_U_HS+TIM_U_LS:selection-required",),
        ),
        (
            "tim-to-spreader",
            "phase-u-tim",
            "shared-spreader",
            ("mechanical:shared-spreader:interface-required",),
        ),
        (
            "spreader-to-heatsink",
            "shared-spreader",
            "shared-heatsink",
            ("mechanical:HS1:clamp-and-contact-required",),
        ),
        (
            "heatsink-to-local-ambient",
            "shared-heatsink",
            "local-ambient",
            ("environment:airflow-and-enclosure-required",),
        ),
        (
            "package-surface-to-pcb-territory",
            "phase-u-package-top-surface",
            "phase-u-pcb-territory",
            ("board:routed-phase-u-thermal-territory-required",),
        ),
        (
            "pcb-territory-to-local-ambient",
            "phase-u-pcb-territory",
            "local-ambient",
            ("environment:board-convection-and-radiation-required",),
        ),
    )
    links = tuple(
        ThermalLink(
            link_id=link_id,
            node_a_id=node_a,
            node_b_id=node_b,
            thermal_resistance=resistance(link_id),
            source_binding_ids=bindings,
            applicability_notes=(unknown_resistances[link_id],),
        )
        for link_id, node_a, node_b, bindings in link_pairs
    )
    mosfet_loss_identities = tuple(
        item.loss_identity_id
        for item in ledger.losses
        if item.scenario_id == continuous.scenario_id
        and ("Q_U_HS" in item.subject_ids or "Q_U_LS" in item.subject_ids)
    )
    injection = ThermalHeatInjection(
        injection_id="phase-u-switch-pair-total-loss",
        node_id="phase-u-switch-pair-junction-equivalent",
        power=_unknown(
            "phase_u_switch_pair_total_loss",
            "W",
            "MOSFET conduction, switching, gate-drive, and dead-time losses are incomplete.",
        ),
        loss_identity_ids=mosfet_loss_identities,
    )
    return ElectrothermalNetwork(
        network_id="bldc-esc-r002-phase-u-electrothermal",
        scenario_id=continuous.scenario_id,
        mission_profile_fingerprint=profile.semantic_fingerprint(),
        loss_ledger_fingerprint=ledger.semantic_fingerprint(),
        nodes=nodes,
        links=links,
        heat_injections=(injection,),
        source_context_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            "board:bldc-esc-r002:thermal-placement",
        ),
    )


def build_bldc_esc_gate_drive_profile(
    register: EngineeringEvidenceRegister,
) -> GateDriveProfile:
    """Bind the retained minimum-bus driver architecture to MOSFET conditions."""

    return GateDriveProfile(
        profile_id="bldc-esc-r002-minimum-bus-gate-drive",
        scenario_id="normal.minimum-input-voltage",
        driver_id="DRV8353",
        power_device_id="IPTC011N08NM5ATMA1",
        driver_supply_voltage=_known(
            "driver_supply_voltage",
            "V",
            "9",
            "9",
            "9",
            knowledge=QuantityKnowledge.DESIGN_TARGET,
            evidence=(REQUEST_SOURCE_ID, "board:bldc-esc-r002:DRV8353-VM-to-BAT_P"),
            rationale="The retained board ties VM and VDRAIN to the 9V minimum BAT_P bus.",
        ),
        characterized_gate_voltage=_known(
            "mosfet_lowest_characterized_gate_voltage",
            "V",
            "6",
            "6",
            "6",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(MOSFET_SOURCE_ID,),
            rationale="Lowest RDS(on) gate-voltage condition tabulated for the MOSFET.",
        ),
        required_margin=_known(
            "minimum_gate_voltage_margin",
            "V",
            "0",
            "0",
            "0",
            knowledge=QuantityKnowledge.DESIGN_TARGET,
            evidence=("policy:gate-drive-characterization-floor",),
            rationale="Zero is only a characterization floor, not the eventual design margin.",
        ),
        channels=(
            GateDriveChannelPoint(
                channel_id="drv8353-high-side-at-vm-9v",
                kind=GateDriveChannelKind.HIGH_SIDE,
                available_gate_voltage=register.fact("driver.high-side-vgs-at-vm-9v").quantity,
                source_binding_ids=(GATE_DRIVER_SOURCE_ID,),
            ),
            GateDriveChannelPoint(
                channel_id="drv8353-low-side-at-vm-9v",
                kind=GateDriveChannelKind.LOW_SIDE,
                available_gate_voltage=register.fact("driver.low-side-vgs-at-vm-9v").quantity,
                source_binding_ids=(GATE_DRIVER_SOURCE_ID,),
            ),
        ),
        source_context_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            GATE_DRIVER_SOURCE_ID,
            "board:bldc-esc-r002:DRV8353-VM-to-BAT_P",
        ),
    )


def build_bldc_esc_gate_charge_capacity_profile(
    profile: MissionProfile,
    register: EngineeringEvidenceRegister,
) -> GateChargeCapacityProfile:
    continuous = next(
        item for item in profile.scenarios if item.scenario_id == "normal.target-60a-continuous"
    )
    frequency = continuous.quantity("pwm_frequency")
    assert frequency is not None
    return GateChargeCapacityProfile(
        profile_id="bldc-esc-r002-gate-charge-capacity",
        scenario_id=continuous.scenario_id,
        gate_charge=register.fact("mosfet.gate-charge-total").quantity,
        switching_frequency=frequency,
        simultaneously_switching_high_side_count=_unknown(
            "simultaneously_switching_high_side_count",
            "count",
            "The retained firmware does not establish which high-side channels receive PWM.",
        ),
        simultaneously_switching_low_side_count=_unknown(
            "simultaneously_switching_low_side_count",
            "count",
            "The retained firmware does not establish which low-side channels receive PWM.",
        ),
        available_high_side_average_current=_known(
            "characterized_high_side_average_gate_current_at_vm_9v",
            "A",
            "0.010",
            "0.010",
            "0.010",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(GATE_DRIVER_SOURCE_ID,),
            rationale=(
                "VM=9V gate-voltage characterization covers IVCP/IVGLS from 0 to 10mA; "
                "this is used as a conservative characterized average-current ceiling."
            ),
        ),
        available_low_side_average_current=_known(
            "characterized_low_side_average_gate_current_at_vm_9v",
            "A",
            "0.010",
            "0.010",
            "0.010",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(GATE_DRIVER_SOURCE_ID,),
            rationale=(
                "VM=9V gate-voltage characterization covers IVCP/IVGLS from 0 to 10mA; "
                "this is not a peak IDRIVE value."
            ),
        ),
        source_context_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            GATE_DRIVER_SOURCE_ID,
            "screen:DRV8353-vm9-average-gate-current-characterization",
            "firmware:six-step-pwm-strategy:missing",
        ),
    )


def build_bldc_esc_dead_time_profile() -> DeadTimeAdequacyProfile:
    return DeadTimeAdequacyProfile(
        profile_id="bldc-esc-r002-dead-time-adequacy",
        scenario_id="normal.target-60a-continuous",
        programmed_dead_time=_unknown(
            "programmed_dead_time",
            "ns",
            "The retained firmware/register image does not establish the dead-time setting.",
        ),
        turn_off_completion_time=_unknown(
            "turn_off_completion_time",
            "ns",
            "No bounded or measured MOSFET turn-off completion time exists for this layout.",
        ),
        propagation_mismatch=_unknown(
            "propagation_mismatch",
            "ns",
            "Driver, isolator, MCU, and channel mismatch have not been bounded.",
        ),
        required_timing_margin=_unknown(
            "required_dead_time_margin",
            "ns",
            "No reviewed project dead-time margin policy exists.",
        ),
        source_context_ids=(
            MOSFET_SOURCE_ID,
            GATE_DRIVER_SOURCE_ID,
            "firmware:DRV8353-register-configuration:missing",
            "measurement:gate-and-switch-node-timing:missing",
        ),
    )


def build_bldc_esc_gate_supply_options() -> tuple[GateSupplyOption, ...]:
    """Retain architecture alternatives without mutating the R002 schematic."""

    characterized = _known(
        "mosfet_characterized_gate_voltage_floor",
        "V",
        "6",
        "6",
        "6",
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        evidence=(MOSFET_SOURCE_ID,),
        rationale="Lowest tabulated RDS(on) gate-voltage condition for the retained MOSFET.",
    )
    margin = _known(
        "gate_voltage_architecture_margin",
        "V",
        "1",
        "1",
        "1",
        knowledge=QuantityKnowledge.DESIGN_TARGET,
        evidence=("policy:gate-drive-characterization-margin-r1",),
        rationale="Preliminary one-volt floor above the characterized VGS condition.",
    )

    def voltage(
        quantity_id: str,
        lower: str,
        nominal: str,
        upper: str,
    ) -> BoundedQuantity:
        return _known(
            quantity_id,
            "V",
            lower,
            nominal,
            upper,
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(GATE_DRIVER_SOURCE_ID,),
        )

    def option(
        option_id: str,
        kind: GateSupplyArchitectureKind,
        vm: str,
        high: tuple[str, str, str],
        low: tuple[str, str, str],
        changes: tuple[str, ...],
        unresolved: tuple[str, ...],
        notes: tuple[str, ...],
    ) -> GateSupplyOption:
        return GateSupplyOption(
            option_id=option_id,
            kind=kind,
            driver_id="DRV8353",
            power_device_id="IPTC011N08NM5ATMA1",
            driver_supply_voltage=_known(
                f"{option_id}_driver_supply_voltage",
                "V",
                vm,
                vm,
                vm,
                knowledge=QuantityKnowledge.DESIGN_TARGET,
                evidence=(REQUEST_SOURCE_ID, GATE_DRIVER_SOURCE_ID),
            ),
            high_side_gate_voltage=voltage(f"{option_id}_high_side_vgs", *high),
            low_side_gate_voltage=voltage(f"{option_id}_low_side_vgs", *low),
            characterized_gate_voltage=characterized,
            required_margin=margin,
            hardware_change_ids=changes,
            unresolved_authority_ids=unresolved,
            source_binding_ids=(
                REQUEST_SOURCE_ID,
                MOSFET_SOURCE_ID,
                GATE_DRIVER_SOURCE_ID,
                "policy:gate-drive-characterization-margin-r1",
            ),
            notes=notes,
        )

    regulated_open = (
        "gate-supply-converter-exact-selection",
        "gate-supply-line-load-transient-bounds",
        "gate-supply-startup-shutdown-sequencing",
        "gate-supply-fault-supervision",
        "gate-supply-layout-and-emi",
        "idriven-edge-rate-and-switching-loss",
    )
    drv8334_gate_voltage = _known(
        "drv8334_gate_voltage_at_pvdd_9v",
        "V",
        "11.3",
        "11.3",
        "13.5",
        knowledge=QuantityKnowledge.DERIVED_BOUNDED,
        evidence=(DRV8334_SOURCE_ID,),
        rationale=(
            "At PVDD from 7.2V to 18V, GVDD is bounded 11.5V to 13.5V at 50mA; "
            "the gate high-level output is within 0.2V of GVDD at 10mA."
        ),
    )
    drv8334_option = GateSupplyOption(
        option_id="change-driver-drv8334-native-9v",
        kind=GateSupplyArchitectureKind.CHANGE_GATE_DRIVER,
        driver_id="DRV8334",
        power_device_id="IPTC011N08NM5ATMA1",
        driver_supply_voltage=_known(
            "drv8334_pvdd",
            "V",
            "9",
            "9",
            "9",
            knowledge=QuantityKnowledge.DESIGN_TARGET,
            evidence=(REQUEST_SOURCE_ID, DRV8334_SOURCE_ID),
        ),
        high_side_gate_voltage=drv8334_gate_voltage,
        low_side_gate_voltage=drv8334_gate_voltage,
        characterized_gate_voltage=_known(
            "mosfet_10v_rds_characterization",
            "V",
            "10",
            "10",
            "10",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(MOSFET_SOURCE_ID,),
        ),
        required_margin=margin,
        hardware_change_ids=(
            "replace-DRV8353-with-DRV8334",
            "redesign-gate-driver-symbol-footprint-and-pinout",
            "redesign-bootstrap-charge-pump-and-decoupling",
            "remap-current-sense-protection-and-firmware-registers",
        ),
        unresolved_authority_ids=(
            "drv8334-rgz-land-pattern-and-paste-release-review",
            "drv8334-placement-and-local-routing-feasibility",
            "protection-threshold-and-fault-response-mapping",
            "current-sense-range-and-accuracy",
            "gate-current-dead-time-and-switching-loss-configuration",
            "bootstrap-charge-pump-startup-and-100-percent-duty-review",
            "60v-driver-rating-derating-and-transient-vdrain-observation",
            "layout-emi-and-thermal-validation",
        ),
        source_binding_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            DRV8334_SOURCE_ID,
            "policy:gate-drive-characterization-margin-r1",
        ),
        notes=(
            "Native 9V operation guarantees a gate rail above the MOSFET 10V condition.",
            "Avoids a separate buck-boost VM rail but requires a gate-driver redesign.",
            "Preferred architecture candidate; not an approved component selection.",
        ),
    )
    return (
        drv8334_option,
        option(
            "bus-coupled-vm-9v",
            GateSupplyArchitectureKind.BUS_COUPLED,
            "9",
            ("5.5", "7.5", "8.5"),
            ("6.5", "8", "9.5"),
            (),
            (),
            ("Retained R002 topology; fails the one-volt characterization margin.",),
        ),
        option(
            "bus-coupled-vm-10v-minimum",
            GateSupplyArchitectureKind.BUS_COUPLED,
            "10",
            ("6", "8", "9.5"),
            ("7.5", "9", "10.5"),
            ("raise-product-minimum-input-to-10v",),
            ("input-specification-user-approval",),
            ("High-side VGS only reaches the 6V condition with zero guaranteed margin.",),
        ),
        option(
            "separate-regulated-vm-12v",
            GateSupplyArchitectureKind.SEPARATE_REGULATED,
            "12",
            ("7.5", "10", "11.5"),
            ("9", "10.5", "12"),
            (
                "separate-VM-from-VDRAIN",
                "retain-VDRAIN-at-BAT_P",
                "add-12v-buck-boost-gate-rail",
            ),
            regulated_open,
            (
                "Lowest inspected DRV8353 table point that clears the 6V condition by 1V.",
                "Preferred for the next design iteration, but not selected or released.",
            ),
        ),
        option(
            "separate-regulated-vm-15v",
            GateSupplyArchitectureKind.SEPARATE_REGULATED,
            "15",
            ("9", "10.5", "12"),
            ("9.5", "11", "12.5"),
            (
                "separate-VM-from-VDRAIN",
                "retain-VDRAIN-at-BAT_P",
                "add-15v-buck-boost-gate-rail",
            ),
            (*regulated_open, "higher-gate-drive-energy-and-emissions-review"),
            (
                "Provides more VGS margin but increases gate-drive energy and edge-rate risk.",
                "It still does not guarantee the MOSFET's exact 10V RDS(on) test condition.",
            ),
        ),
    )


def build_bldc_esc_gate_driver_migration_profile() -> GateDriverMigrationProfile:
    """Propose a complete DRV8334RGZR pin map without selecting the part."""

    candidate = GateDriverPackageCandidate(
        candidate_id="drv8334-rgzr-native-9v-candidate",
        orderable_part_number="DRV8334RGZR",
        manufacturer_status="ACTIVE-production",
        package_code="RGZ0048N",
        package_style="VQFN-48-exposed-pad",
        signal_pin_count=48,
        thermal_pad_pin_number=49,
        body_width_mm=Decimal("7"),
        body_height_mm=Decimal("7"),
        pin_pitch_mm=Decimal("0.5"),
        proposed_footprint_id=DRV8334_KICAD_FOOTPRINT_ID,
        proposed_3d_model_id=DRV8334_KICAD_MODEL_ID,
        footprint_sha256=DRV8334_KICAD_FOOTPRINT_SHA256,
        model_sha256=DRV8334_KICAD_MODEL_SHA256,
        source_binding_ids=(DRV8334_SOURCE_ID,),
    )
    pin_map = {
        1: ("GLC", "DRV_GL_W"),
        2: ("SLC", "WSHUNT_H"),
        3: ("SPA", "USHUNT_H"),
        4: ("SNA", "PGND"),
        5: ("SPB", "VSHUNT_H"),
        6: ("SNB", "PGND"),
        7: ("SPC", "WSHUNT_H"),
        8: ("SNC", "PGND"),
        9: ("DRVOFF", "DRV_OFF_NEW"),
        10: ("AGND", "AGND"),
        11: ("INHA", "PWM_UH"),
        12: ("INLA", "PWM_UL"),
        13: ("INHB", "PWM_VH"),
        14: ("INLB", "PWM_VL"),
        15: ("INHC", "PWM_WH"),
        16: ("INLC", "PWM_WL"),
        17: ("SDO", "DRV_SDO"),
        18: ("SDI", "DRV_SDI"),
        19: ("SCLK", "DRV_SCLK"),
        20: ("nSCS", "DRV_NSCS"),
        21: ("nSLEEP", "DRV_EN"),
        22: ("nFAULT", "DRV_NFAULT"),
        23: ("VREF", "3V3A"),
        24: ("SOC", "CSA_W"),
        25: ("SOB", "CSA_V"),
        26: ("SOA", "CSA_U"),
        27: ("GND", "PGND"),
        28: ("CPL", "DRV_CPL"),
        29: ("CPH", "DRV_CPH"),
        30: ("GVDD", "DRV_GVDD_NEW"),
        31: ("PVDD", "BAT_P"),
        32: ("CPTL", "DRV_CPTL_NEW"),
        33: ("CPTH", "DRV_CPTH_NEW"),
        34: ("VCP", "DRV_VCP"),
        35: ("VDRAIN", "BAT_P"),
        36: ("BSTA", "DRV_BST_U_NEW"),
        37: ("SHA", "PHASE_U"),
        38: ("GHA", "DRV_GH_U"),
        39: ("GLA", "DRV_GL_U"),
        40: ("SLA", "USHUNT_H"),
        41: ("SLB", "VSHUNT_H"),
        42: ("GLB", "DRV_GL_V"),
        43: ("GHB", "DRV_GH_V"),
        44: ("SHB", "PHASE_V"),
        45: ("BSTB", "DRV_BST_V_NEW"),
        46: ("BSTC", "DRV_BST_W_NEW"),
        47: ("SHC", "PHASE_W"),
        48: ("GHC", "DRV_GH_W"),
        49: ("THERMAL_PAD", "THERMAL_GND"),
    }
    new_functions = {"DRVOFF", "GVDD", "CPTL", "CPTH", "BSTA", "BSTB", "BSTC"}
    behavior_review = {"nSLEEP", "THERMAL_PAD"}
    assignments = tuple(
        GateDriverPinAssignment(
            pin_number=pin_number,
            function_id=function_id,
            proposed_net_id=net_id,
            disposition=(
                MigrationDisposition.NEW_REQUIRED
                if function_id in new_functions
                else MigrationDisposition.BEHAVIOR_REVIEW
                if function_id in behavior_review
                else MigrationDisposition.REMAPPED
            ),
            source_binding_ids=(DRV8334_SOURCE_ID,),
            notes=(
                "THERMAL_GND is a proposed layout identity; TI states that the pad "
                "is thermal rather than the primary electrical ground."
                if function_id == "THERMAL_PAD"
                else "DRV_EN can be reused only after nSLEEP timing and reset "
                "behavior are reviewed."
                if function_id == "nSLEEP"
                else "New support net and component placement are required."
                if function_id in new_functions
                else "Functional net retained with a new physical pin number.",
            ),
        )
        for pin_number, (function_id, net_id) in sorted(pin_map.items())
    )

    def migration(
        group_id: str,
        disposition: MigrationDisposition,
        source_functions: tuple[str, ...],
        target_functions: tuple[str, ...],
        obligations: tuple[str, ...],
        note: str,
    ) -> GateDriverFunctionMigration:
        return GateDriverFunctionMigration(
            function_group_id=group_id,
            disposition=disposition,
            source_function_ids=source_functions,
            target_function_ids=target_functions,
            obligation_ids=obligations,
            notes=(note,),
        )

    migrations = (
        migration(
            "phase-gate-and-source-sense",
            MigrationDisposition.REMAPPED,
            ("GHA/B/C", "GLA/B/C", "SHA/B/C", "SLA/B/C"),
            ("GHA/B/C", "GLA/B/C", "SHA/B/C", "SLA/B/C"),
            ("gate-loop-layout-review", "slx-source-sense-routing"),
            "All six drive outputs and six source/switch-node senses remain, with "
            "new pin locations.",
        ),
        migration(
            "phase-current-sense",
            MigrationDisposition.REMAPPED,
            ("SPA/B/C", "SNA/B/C", "SOA/B/C"),
            ("SPA/B/C", "SNA/B/C", "SOA/B/C"),
            ("kelvin-input-filter-review", "csa-range-and-accuracy-review"),
            "Three shunt channels remain but filtering and accuracy must be re-qualified.",
        ),
        migration(
            "pwm-control",
            MigrationDisposition.REMAPPED,
            ("INHA/B/C", "INLA/B/C"),
            ("INHA/B/C", "INLA/B/C"),
            ("pwm-mode-and-firmware-review",),
            "The six retained PWM nets can map to the six DRV8334 inputs.",
        ),
        migration(
            "spi-and-fault",
            MigrationDisposition.REMAPPED,
            ("nSCS", "SCLK", "SDI", "SDO", "nFAULT"),
            ("nSCS", "SCLK", "SDI", "SDO", "nFAULT"),
            ("register-map-rewrite", "fault-policy-review"),
            "The physical interface remains SPI, but register semantics and diagnostics differ.",
        ),
        migration(
            "enable-and-independent-shutdown",
            MigrationDisposition.BEHAVIOR_REVIEW,
            ("ENABLE",),
            ("nSLEEP", "DRVOFF"),
            ("drv-off-safe-state", "mcu-gpio-allocation", "startup-shutdown-sequence"),
            "ENABLE is not a behavioral drop-in for the separate nSLEEP and DRVOFF controls.",
        ),
        migration(
            "supply-and-reference",
            MigrationDisposition.REMAPPED,
            ("VM", "VDRAIN", "VREF", "AGND", "GND"),
            ("PVDD", "VDRAIN", "VREF", "AGND", "GND"),
            ("pvdd-vdrain-decoupling", "ground-partition-review"),
            "The native battery supply is retained, with different local bypass requirements.",
        ),
        migration(
            "gate-and-charge-pump-support",
            MigrationDisposition.BEHAVIOR_REVIEW,
            ("CPH", "CPL", "VCP", "VGLS"),
            ("CPH", "CPL", "VCP", "GVDD", "CPTH", "CPTL", "BSTA/B/C"),
            ("support-component-reselection", "bootstrap-sizing", "local-placement-review"),
            "DRV8334 adds a trickle-pump capacitor and three bootstrap networks "
            "and changes flying-cap values.",
        ),
        migration(
            "digital-regulator-output",
            MigrationDisposition.RETIRED,
            ("DVDD",),
            (),
            ("remove-dvdd-decoupling-and-net-use-review",),
            "DRV8334 has no DRV8353-style DVDD output; downstream use must be "
            "proven absent before removal.",
        ),
        migration(
            "exposed-thermal-pad",
            MigrationDisposition.BEHAVIOR_REVIEW,
            ("THERMAL_PAD",),
            ("THERMAL_PAD",),
            ("thermal-pad-land-pattern", "thermal-ground-connection-review"),
            "The exposed pad must be soldered and tied to the best thermal ground "
            "without treating it as primary signal ground.",
        ),
    )
    return GateDriverMigrationProfile(
        profile_id="bldc-esc-r002-drv8353-to-drv8334-migration",
        revision="1",
        current_part_id="DRV8353SRTAT",
        current_package_body_width_mm=Decimal("6"),
        current_package_body_height_mm=Decimal("6"),
        candidate=candidate,
        pin_assignments=assignments,
        function_migrations=migrations,
        required_function_group_ids=tuple(item.function_group_id for item in migrations),
        unresolved_authority_ids=(
            "drv8334-rgz-land-pattern-and-paste-release-review",
            "drv8334-placement-and-local-routing-feasibility",
            "bootstrap-and-charge-pump-component-selection",
            "drv8334-register-map-and-firmware-migration",
            "protection-threshold-and-fault-response-mapping",
            "current-sense-range-filter-and-accuracy",
            "gate-current-dead-time-and-switching-loss-configuration",
            "startup-shutdown-and-100-percent-duty-review",
            "60v-driver-derating-and-vdrain-transient-observation",
            "bench-and-emc-validation",
        ),
        source_binding_ids=(
            GATE_DRIVER_SOURCE_ID,
            DRV8334_SOURCE_ID,
            MOSFET_SOURCE_ID,
            REQUEST_SOURCE_ID,
        ),
    )


def build_bldc_esc_drv8334_bootstrap_profile() -> BootstrapCapacitanceProfile:
    """Screen the DRV8334 source formula without inventing capacitor derating."""

    return BootstrapCapacitanceProfile(
        profile_id="bldc-esc-r002-drv8334-bootstrap-screen",
        driver_id="DRV8334RGZR-candidate",
        power_device_id="IPTC011N08NM5ATMA1",
        channel_ids=("phase-U", "phase-V", "phase-W"),
        total_gate_charge=_known(
            "drv8334_candidate_mosfet_total_gate_charge",
            "C",
            "0",
            "0.000000178",
            "0.000000223",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(MOSFET_SOURCE_ID,),
            rationale=UNSPECIFIED_MINIMUM_RATIONALE,
        ),
        gate_drive_amplitude=_known(
            "drv8334_candidate_gate_drive_amplitude",
            "V",
            "11.3",
            "11.3",
            "13.5",
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            evidence=(DRV8334_SOURCE_ID,),
            rationale=(
                "Derived from the 11.5V minimum GVDD and at most 0.2V high-level "
                "drop at the inspected operating point."
            ),
        ),
        charge_multiplier=Decimal("20"),
        candidate_effective_capacitance=_unknown(
            "drv8334_bootstrap_candidate_effective_capacitance",
            "F",
            "The 1uF nominal recommendation has no selected MPN or retained "
            "DC-bias, tolerance, aging, and temperature lower bound.",
        ),
        source_context_ids=(
            DRV8334_SOURCE_ID,
            MOSFET_SOURCE_ID,
            "formula:DRV8334:CBST>20*Qg/(VGHx-VSHx)",
        ),
    )


def build_bldc_esc_drv8334_support_plan(
    bootstrap_minimum: BoundedQuantity,
) -> GateDriverSupportPlan:
    """Retain all mandatory DRV8334 capacitor roles without inventing MPNs."""

    def capacitance(
        quantity_id: str,
        value: str,
    ) -> BoundedQuantity:
        return _known(
            quantity_id,
            "F",
            value,
            value,
            value,
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(DRV8334_SOURCE_ID,),
            rationale="TI states that recommended capacitances are effective values.",
        )

    def voltage(
        quantity_id: str,
        value: str,
        rationale: str,
    ) -> BoundedQuantity:
        return _known(
            quantity_id,
            "V",
            value,
            value,
            value,
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            evidence=(DRV8334_SOURCE_ID, REQUEST_SOURCE_ID),
            rationale=rationale,
        )

    def requirement(
        requirement_id: str,
        role: GateDriverSupportRole,
        pins: tuple[str, ...],
        count: int,
        nominal: BoundedQuantity,
        effective: BoundedQuantity,
        applied_voltage: BoundedQuantity,
        placement: tuple[str, ...],
        note: str,
    ) -> GateDriverSupportRequirement:
        return GateDriverSupportRequirement(
            requirement_id=requirement_id,
            role=role,
            pin_ids=pins,
            component_count=count,
            recommended_nominal_value=nominal,
            minimum_effective_value=effective,
            maximum_applied_voltage=applied_voltage,
            placement_obligation_ids=placement,
            source_binding_ids=(DRV8334_SOURCE_ID,),
            notes=(note,),
        )

    one_microfarad = capacitance("drv8334_recommended_1uf_effective", "0.000001")
    ten_microfarad = capacitance("drv8334_recommended_10uf_effective", "0.000010")
    one_hundred_nanofarad = capacitance(
        "drv8334_recommended_100nf_effective",
        "0.0000001",
    )
    gate_rail_voltage = voltage(
        "drv8334_support_gate_rail_maximum",
        "13.5",
        "Upper GVDD and gate-amplitude bound under the inspected 9V operating point.",
    )
    return GateDriverSupportPlan(
        plan_id="bldc-esc-r002-drv8334-support-plan",
        revision="1",
        driver_candidate_id="DRV8334RGZR",
        requirements=(
            requirement(
                "cpvdd",
                GateDriverSupportRole.SUPPLY_BYPASS,
                ("PVDD", "GND"),
                1,
                ten_microfarad,
                ten_microfarad,
                _unknown(
                    "cpvdd_maximum_applied_voltage",
                    "V",
                    "The 25.2V normal bus is known, but regenerative and hot-plug "
                    "transients have not been bounded.",
                ),
                ("close-to-PVDD-pin", "short-return-to-GND"),
                "TI recommends 10uF effective at PVDD and warns about DC derating.",
            ),
            requirement(
                "cgvdd",
                GateDriverSupportRole.SUPPLY_BYPASS,
                ("GVDD", "GND"),
                1,
                ten_microfarad,
                ten_microfarad,
                gate_rail_voltage,
                ("close-to-GVDD-pin", "short-return-to-GND"),
                "TI recommends 10uF effective at GVDD.",
            ),
            requirement(
                "ccp-fly",
                GateDriverSupportRole.CHARGE_PUMP_FLYING,
                ("CPH", "CPL"),
                1,
                one_microfarad,
                one_microfarad,
                gate_rail_voltage,
                ("adjacent-to-CPH-CPL", "minimum-loop-area"),
                "DRV8334 changes the retained DRV8353 flying capacitor from 47nF to 1uF effective.",
            ),
            requirement(
                "ccpt-fly",
                GateDriverSupportRole.CHARGE_PUMP_FLYING,
                ("CPTH", "CPTL"),
                1,
                one_microfarad,
                one_microfarad,
                gate_rail_voltage,
                ("adjacent-to-CPTH-CPTL", "minimum-loop-area"),
                "The trickle-charge-pump flying capacitor is new to the candidate architecture.",
            ),
            requirement(
                "cvcp",
                GateDriverSupportRole.CHARGE_PUMP_RESERVOIR,
                ("VCP", "VDRAIN"),
                1,
                one_microfarad,
                one_microfarad,
                _unknown(
                    "cvcp_maximum_applied_voltage",
                    "V",
                    "The VCP-to-VDRAIN operating and transient differential has not "
                    "been retained across all scenarios.",
                ),
                ("close-to-VCP-VDRAIN", "minimum-loop-area"),
                "TI recommends 1uF effective rated for the VCP application voltage.",
            ),
            requirement(
                "cvdrain",
                GateDriverSupportRole.SUPPLY_BYPASS,
                ("VDRAIN", "GND"),
                1,
                one_microfarad,
                one_microfarad,
                _unknown(
                    "cvdrain_maximum_applied_voltage",
                    "V",
                    "MOSFET-drain overshoot during switching, regeneration, and faults "
                    "has not been measured or conservatively bounded.",
                ),
                ("close-to-VDRAIN-pin", "short-return-to-GND"),
                "TI recommends 1uF effective at VDRAIN for charge-pump switching current.",
            ),
            requirement(
                "cbst-u-v-w",
                GateDriverSupportRole.BOOTSTRAP,
                ("BSTA/BSTB/BSTC", "SHA/SHB/SHC"),
                3,
                one_microfarad,
                bootstrap_minimum,
                gate_rail_voltage,
                ("one-capacitor-adjacent-to-each-BSTx-SHx-pair", "minimum-loop-area"),
                "Each phase needs more than the calculated effective minimum; TI "
                "recommends 1uF, 20V nominal.",
            ),
            requirement(
                "cvref",
                GateDriverSupportRole.REFERENCE_BYPASS,
                ("VREF", "GND"),
                1,
                one_hundred_nanofarad,
                one_hundred_nanofarad,
                voltage(
                    "drv8334_vref_applied_voltage",
                    "3.3",
                    "R002 drives VREF from the retained 3V3A rail.",
                ),
                ("close-to-VREF-pin", "quiet-analog-return"),
                "TI recommends 0.1uF at VREF; analog return routing remains separate work.",
            ),
        ),
        source_context_ids=(DRV8334_SOURCE_ID, MOSFET_SOURCE_ID, REQUEST_SOURCE_ID),
    )


def build_bldc_esc_protection_coordination_profile() -> ProtectionCoordinationProfile:
    """Declare protection paths while leaving unproven timing and energy open."""

    def path(
        path_id: str,
        events: tuple[ProtectionEventKind, ...],
        detectors: tuple[str, ...],
        actions: tuple[str, ...],
        domain: str,
        threshold_unit: str,
        sources: tuple[str, ...],
        note: str,
    ) -> ProtectionPath:
        return ProtectionPath(
            path_id=path_id,
            event_kinds=events,
            detector_ids=detectors,
            action_ids=actions,
            independent_domain_id=domain,
            detection_threshold=_unknown(
                f"{path_id}.detection-threshold",
                threshold_unit,
                "The selected threshold/register setting and tolerance are not retained.",
            ),
            detection_latency=_unknown(
                f"{path_id}.detection-latency",
                "s",
                "Worst-case detector/filter/blanking latency is not retained.",
            ),
            shutdown_latency=_unknown(
                f"{path_id}.shutdown-latency",
                "s",
                "Worst-case action and power-stage turn-off latency is not retained.",
            ),
            residual_energy=_unknown(
                f"{path_id}.residual-energy",
                "J",
                "Fault current, bus/motor energy, parasitics, and interruption waveform "
                "are not bounded.",
            ),
            source_binding_ids=sources,
            notes=(note,),
        )

    paths = (
        path(
            "drv8334-vds-ocp",
            (ProtectionEventKind.SHOOT_THROUGH, ProtectionEventKind.PHASE_SHORT),
            ("DRV8334-VDS-monitor",),
            ("gate-soft-shutdown", "nFAULT-report"),
            "gate-driver-hardware",
            "V",
            (DRV8334_SOURCE_ID, MOSFET_SOURCE_ID),
            "The candidate supports configurable VDS monitoring, but no threshold "
            "or response is selected.",
        ),
        path(
            "drv8334-rsense-ocp",
            (ProtectionEventKind.STALL, ProtectionEventKind.PHASE_SHORT),
            ("DRV8334-RSENSE-monitor",),
            ("gate-soft-shutdown", "nFAULT-report"),
            "gate-driver-hardware",
            "V",
            (DRV8334_SOURCE_ID, SHUNT_SOURCE_ID),
            "Shunt-monitor configuration and its relationship to the 60A/100A scenarios are open.",
        ),
        path(
            "mcu-current-limit",
            (ProtectionEventKind.STALL, ProtectionEventKind.PHASE_SHORT),
            ("phase-CSA-ADC",),
            ("pwm-disable",),
            "mcu-firmware",
            "A",
            (REQUEST_SOURCE_ID, SHUNT_SOURCE_ID),
            "ADC/filter/control-loop timing and firmware safe-state behavior are unverified.",
        ),
        path(
            "passive-bus-tvs-clamp",
            (ProtectionEventKind.REGENERATIVE_BUS_RISE, ProtectionEventKind.HOT_PLUG),
            ("7KPD26A-avalanche",),
            ("bus-voltage-clamp",),
            "passive-tvs",
            "V",
            (REQUEST_SOURCE_ID, TVS_SOURCE_ID),
            "The populated TVS is not coordinated to source impedance, pulse shape, "
            "fuse, or bus capacitance.",
        ),
        path(
            "mcu-bus-overvoltage",
            (ProtectionEventKind.REGENERATIVE_BUS_RISE,),
            ("VBUS-SENSE-ADC",),
            ("pwm-disable", "regeneration-command-stop"),
            "mcu-firmware",
            "V",
            (REQUEST_SOURCE_ID,),
            "The divider exists, but firmware threshold, braking policy, and bus "
            "response are not retained.",
        ),
        path(
            "drv8334-vgs-monitor",
            (ProtectionEventKind.GATE_DRIVE_FAULT,),
            ("DRV8334-VGS-monitor",),
            ("gate-soft-shutdown", "nFAULT-report"),
            "gate-driver-hardware",
            "V",
            (DRV8334_SOURCE_ID,),
            "VGS monitoring exists in the candidate; configuration and diagnostic "
            "coverage remain open.",
        ),
        path(
            "drv8334-thermal-shutdown",
            (ProtectionEventKind.COOLING_OR_OVERTEMPERATURE,),
            ("DRV8334-die-temperature",),
            ("gate-shutdown", "nFAULT-report"),
            "gate-driver-hardware",
            "degC",
            (DRV8334_SOURCE_ID,),
            "Driver thermal shutdown does not by itself protect MOSFET junctions "
            "or the shared sink.",
        ),
        path(
            "phase-ntc-firmware",
            (ProtectionEventKind.COOLING_OR_OVERTEMPERATURE,),
            ("NTC-U", "NTC-V", "NTC-W"),
            ("pwm-derate", "pwm-disable"),
            "mcu-firmware",
            "degC",
            (REQUEST_SOURCE_ID,),
            "NTC-to-junction correlation, thresholds, filtering, and sensor fault "
            "handling are open.",
        ),
    )

    def requirement(
        requirement_id: str,
        event: ProtectionEventKind,
        domains: int,
        actions: tuple[str, ...],
    ) -> ProtectionRequirement:
        return ProtectionRequirement(
            requirement_id=requirement_id,
            event_kind=event,
            required_independent_domain_count=domains,
            required_action_ids=actions,
            maximum_total_latency=_unknown(
                f"{requirement_id}.maximum-total-latency",
                "s",
                "No fault-specific safe interruption time has been derived from "
                "device and system stress.",
            ),
            maximum_residual_energy=_unknown(
                f"{requirement_id}.maximum-residual-energy",
                "J",
                "No fault-specific energy withstand budget has been established.",
            ),
            source_binding_ids=(REQUEST_SOURCE_ID, "policy:protection-coordination:missing"),
        )

    requirements = (
        requirement(
            "protect-stall",
            ProtectionEventKind.STALL,
            2,
            ("gate-soft-shutdown", "pwm-disable"),
        ),
        requirement(
            "protect-shoot-through",
            ProtectionEventKind.SHOOT_THROUGH,
            1,
            ("gate-soft-shutdown",),
        ),
        requirement(
            "protect-phase-short",
            ProtectionEventKind.PHASE_SHORT,
            1,
            ("gate-soft-shutdown",),
        ),
        requirement(
            "protect-bus-or-battery-short",
            ProtectionEventKind.BUS_OR_BATTERY_SHORT,
            1,
            ("fault-current-interrupt",),
        ),
        requirement(
            "protect-reverse-polarity",
            ProtectionEventKind.REVERSE_POLARITY,
            1,
            ("reverse-current-block",),
        ),
        requirement(
            "protect-regenerative-bus-rise",
            ProtectionEventKind.REGENERATIVE_BUS_RISE,
            2,
            ("bus-voltage-clamp", "regeneration-command-stop"),
        ),
        requirement(
            "protect-hot-plug",
            ProtectionEventKind.HOT_PLUG,
            1,
            ("bus-voltage-clamp",),
        ),
        requirement(
            "protect-gate-drive-fault",
            ProtectionEventKind.GATE_DRIVE_FAULT,
            1,
            ("gate-soft-shutdown",),
        ),
        requirement(
            "protect-cooling-or-overtemperature",
            ProtectionEventKind.COOLING_OR_OVERTEMPERATURE,
            2,
            ("gate-shutdown", "pwm-disable"),
        ),
    )
    return ProtectionCoordinationProfile(
        profile_id="bldc-esc-r002-drv8334-protection-coordination",
        revision="1",
        paths=paths,
        requirements=requirements,
        source_context_ids=(
            REQUEST_SOURCE_ID,
            DRV8334_SOURCE_ID,
            MOSFET_SOURCE_ID,
            SHUNT_SOURCE_ID,
            TVS_SOURCE_ID,
        ),
    )


def build_bldc_esc_surge_clamp_profile() -> SurgeClampProfile:
    """Bind the populated TVS table row without inventing event applicability."""

    return SurgeClampProfile(
        profile_id="bldc-esc-r002-7kpd26a-surge-clamp",
        scenario_ids=("fault.hot-plug", "fault.regenerative-overvoltage"),
        clamp_part_number="7KPD26A-M3/I",
        maximum_normal_voltage=_known(
            "maximum_normal_bus_voltage",
            "V",
            "9",
            "22.2",
            "25.2",
            knowledge=QuantityKnowledge.DESIGN_TARGET,
            evidence=(REQUEST_SOURCE_ID,),
            rationale="Requested 3S-to-6S operating range, including 6S full charge.",
        ),
        required_standoff_margin=_unknown(
            "required_tvs_standoff_margin",
            "V",
            "No reviewed tolerance, charger, wiring-drop, or non-clamping transient "
            "headroom policy exists.",
        ),
        reverse_standoff_voltage=_known(
            "7kpd26a_reverse_standoff_voltage",
            "V",
            "26",
            "26",
            "26",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(TVS_SOURCE_ID,),
            rationale="Vishay 7KPD26A electrical-characteristics row, VRWM.",
        ),
        breakdown_voltage=_known(
            "7kpd26a_breakdown_voltage",
            "V",
            "28.9",
            "30.4",
            "31.9",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(TVS_SOURCE_ID,),
            rationale="Vishay 7KPD26A row at 5 mA and 25 degC.",
        ),
        clamping_voltage=_known(
            "7kpd26a_maximum_clamping_voltage",
            "V",
            "0",
            "42.1",
            "42.1",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(TVS_SOURCE_ID,),
            rationale=(
                "Only a 42.1V maximum is specified for the 166A 10/1000us row; "
                "zero is retained as a non-claiming lower bound."
            ),
        ),
        protected_voltage_limit=_unknown(
            "minimum_protected_bus_voltage_limit",
            "V",
            "The minimum derated transient limit across every BAT_P-connected part, "
            "including capacitor bias/life policy, is not retained.",
        ),
        event_peak_current=_unknown(
            "hotplug_or_regeneration_tvs_peak_current",
            "A",
            "Battery/wiring source impedance, motor regeneration, and bus parasitics "
            "do not yet bound TVS current.",
        ),
        qualified_peak_pulse_current=_known(
            "7kpd26a_qualified_peak_pulse_current",
            "A",
            "0",
            "166",
            "166",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(TVS_SOURCE_ID,),
            rationale=(
                "166A is the table-row peak for the non-repetitive 10/1000us waveform "
                "at 25 degC; zero is a non-claiming lower bound."
            ),
        ),
        event_energy=_unknown(
            "hotplug_or_regeneration_tvs_event_energy",
            "J",
            "No source/load waveform or energy partition among bus capacitance, TVS, "
            "battery, wiring, and switching devices is bounded.",
        ),
        qualified_peak_pulse_energy=_unknown(
            "7kpd26a_qualified_peak_pulse_energy",
            "J",
            "The datasheet gives peak power for a shaped waveform, not a universal "
            "joule rating; peak power times pulse width is not substituted.",
        ),
        qualified_peak_pulse_power=_known(
            "7kpd26a_qualified_peak_pulse_power",
            "W",
            "0",
            "7000",
            "7000",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(TVS_SOURCE_ID,),
            rationale=(
                "7000W headline applies to one non-repetitive 10/1000us pulse at "
                "25 degC; zero is a non-claiming lower bound."
            ),
        ),
        qualification_context=ClampQualificationContext.UNRESOLVED,
        event_is_repetitive=None,
        qualification_is_repetitive=False,
        source_context_ids=(REQUEST_SOURCE_ID, TVS_SOURCE_ID),
        notes=(
            "The physical normal-to-standoff headroom is only 0.8V at 25.2V bus.",
            "The 42.1V maximum clamp point is conditional on 166A and 10/1000us.",
            "This profile does not establish fuse coordination or downstream survival.",
        ),
    )


def build_bldc_esc_cooling_candidates() -> CoolingCandidateRegister:
    """Retain sourced candidates without promoting them to selected hardware."""

    def candidate_value(
        quantity_id: str,
        unit: str,
        value: str,
        source_id: str,
        rationale: str,
        *,
        knowledge: QuantityKnowledge = QuantityKnowledge.DATASHEET_BOUND,
    ) -> BoundedQuantity:
        return _known(
            quantity_id,
            unit,
            value,
            value,
            value,
            knowledge=knowledge,
            evidence=(source_id,),
            rationale=rationale,
        )

    candidates = (
        CoolingPartCandidate(
            candidate_id="tim-henkel-a2000-idh-2196652",
            roles=(CoolingPartRole.TIM, CoolingPartRole.INSULATING_HARDWARE),
            manufacturer="Henkel",
            ordering_identity="BERGQUIST SIL PAD TSP A2000, IDH 2196652",
            configuration="0.254 mm electrically isolating sheet, custom die-cut required",
            status=CoolingCandidateStatus.VENDOR_CONFIRMATION_REQUIRED,
            properties=(
                candidate_value(
                    "candidate_thickness",
                    "mm",
                    "0.254",
                    HENKEL_TIM_SOURCE_ID,
                    "TDS typical/reference value; compressed thickness remains unqualified.",
                    knowledge=QuantityKnowledge.ASSUMPTION,
                ),
                candidate_value(
                    "candidate_thermal_conductivity",
                    "W/(m*K)",
                    "2.0",
                    HENKEL_TIM_SOURCE_ID,
                    "TDS typical/reference value; application resistance depends on assembly.",
                    knowledge=QuantityKnowledge.ASSUMPTION,
                ),
                candidate_value(
                    "candidate_dielectric_breakdown",
                    "V",
                    "6000",
                    HENKEL_TIM_SOURCE_ID,
                    "TDS typical/reference test value, not an assigned system withstand.",
                    knowledge=QuantityKnowledge.ASSUMPTION,
                ),
            ),
            source_binding_ids=(HENKEL_TIM_SOURCE_ID, TOLT_GUIDE_SOURCE_ID),
            applicability_notes=(
                "Vendor confirmation is required for die-cut geometry, tolerance, and lot data.",
                "Clamp pressure, creepage, puncture risk, and system hipot require validation.",
            ),
        ),
        CoolingPartCandidate(
            candidate_id="heatsink-boyd-maxclip-78045",
            roles=(CoolingPartRole.HEATSINK,),
            manufacturer="Boyd",
            ordering_identity="MaxClip extrusion profile 78045",
            configuration="40 mm by 40 mm cross-section, custom 82 mm cut and machining",
            status=CoolingCandidateStatus.SYSTEM_VALIDATION_REQUIRED,
            properties=(
                candidate_value(
                    "candidate_profile_width",
                    "mm",
                    "40",
                    BOYD_SINK_SOURCE_ID,
                    "Catalog extrusion cross-section width.",
                ),
                candidate_value(
                    "candidate_profile_height",
                    "mm",
                    "40",
                    BOYD_SINK_SOURCE_ID,
                    "Catalog extrusion cross-section height.",
                ),
                candidate_value(
                    "catalog_forced_air_thermal_resistance",
                    "K/W",
                    "0.64",
                    BOYD_SINK_SOURCE_ID,
                    "Catalog point at 150 mm length and 2 m/s; not valid for the 82 mm assembly.",
                    knowledge=QuantityKnowledge.ASSUMPTION,
                ),
            ),
            source_binding_ids=(BOYD_SINK_SOURCE_ID, TOLT_GUIDE_SOURCE_ID),
            applicability_notes=(
                "Catalog thermal resistance must be corrected or tested at the actual cut length.",
                "Base flatness, machining, mounting holes, airflow direction, and "
                "mass remain open.",
            ),
        ),
        CoolingPartCandidate(
            candidate_id="fan-delta-aub0405vd-00",
            roles=(CoolingPartRole.AIR_MOVER,),
            manufacturer="Delta Electronics",
            ordering_identity="AUB0405VD-00",
            configuration="40 mm by 40 mm by 20 mm, 5 V, tachometer output",
            status=CoolingCandidateStatus.SYSTEM_VALIDATION_REQUIRED,
            properties=(
                candidate_value(
                    "candidate_nominal_voltage",
                    "V",
                    "5",
                    DELTA_FAN_SOURCE_ID,
                    "Datasheet nominal voltage.",
                ),
                candidate_value(
                    "candidate_free_air_flow",
                    "CFM",
                    "9.56",
                    DELTA_FAN_SOURCE_ID,
                    "Free-air endpoint, not the system operating point.",
                ),
                candidate_value(
                    "candidate_max_static_pressure",
                    "mmH2O",
                    "5.99",
                    DELTA_FAN_SOURCE_ID,
                    "Zero-flow endpoint, not simultaneous with free-air flow.",
                ),
            ),
            source_binding_ids=(DELTA_FAN_SOURCE_ID,),
            applicability_notes=(
                "The fan operating point requires a duct and system-impedance curve.",
                "Fan supply, tach monitoring, obstruction, failure response, and "
                "acoustics are open.",
            ),
        ),
    )
    return CoolingCandidateRegister(
        register_id="bldc-esc-r002-cooling-candidates",
        revision="1",
        candidates=candidates,
        source_context_ids=(
            TOLT_GUIDE_SOURCE_ID,
            HENKEL_TIM_SOURCE_ID,
            BOYD_SINK_SOURCE_ID,
            DELTA_FAN_SOURCE_ID,
        ),
    )


def build_bldc_esc_coupled_electrothermal_model(
    profile: MissionProfile,
) -> CoupledElectrothermalPointModel:
    """Create the coupled model while preserving unresolved R002 authority."""

    continuous = next(
        item for item in profile.scenarios if item.scenario_id == "normal.target-60a-continuous"
    )
    current = continuous.quantity("phase_shunt_current_rms")
    assert current is not None
    return CoupledElectrothermalPointModel(
        model_id="bldc-esc-r002-phase-u-coupled-screen",
        scenario_id=continuous.scenario_id,
        subject_id="Q_U_HS+Q_U_LS",
        ambient_temperature=continuous.environment.ambient_temperature,
        current_rms=current,
        conduction_fraction=_known(
            "coupled_conduction_fraction",
            "1",
            "0.6666666666666666666666666667",
            "0.6666666666666666666666666667",
            "0.6666666666666666666666666667",
            knowledge=QuantityKnowledge.ASSUMPTION,
            evidence=(SIX_STEP_CONDUCTION_ID,),
            rationale="Preliminary phase-leg pair duty for six-step commutation.",
        ),
        resistance_reference=_unknown(
            "coupled_resistance_reference",
            "ohm",
            "No guaranteed RDS(on) applies at the 5.5V minimum high-side drive.",
        ),
        resistance_reference_temperature=_known(
            "coupled_resistance_reference_temperature",
            "degC",
            "25",
            "25",
            "25",
            knowledge=QuantityKnowledge.DATASHEET_BOUND,
            evidence=(MOSFET_SOURCE_ID,),
        ),
        resistance_temperature_coefficient=_unknown(
            "coupled_resistance_temperature_coefficient",
            "1/K",
            "Only a typical normalized curve has been screened; no release coefficient exists.",
        ),
        fixed_loss=_unknown(
            "coupled_fixed_loss",
            "W",
            "Switching, gate-drive, dead-time, copper, and interface losses are incomplete.",
        ),
        junction_to_ambient_rth=_unknown(
            "coupled_junction_to_ambient_rth",
            "K/W",
            "No selected and correlated cooling assembly establishes junction-to-ambient Rth.",
        ),
        convergence_tolerance=_known(
            "coupled_convergence_tolerance",
            "K",
            "0.001",
            "0.001",
            "0.001",
            knowledge=QuantityKnowledge.DESIGN_TARGET,
            evidence=("solver-policy:coupled-electrothermal-point-v1",),
        ),
        source_context_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            GATE_DRIVER_SOURCE_ID,
            SIX_STEP_CONDUCTION_ID,
        ),
    )


def build_bldc_esc_cooling_assembly(
    board_sha256: str | None,
) -> tuple[CoolingAssemblyProfile, tuple[CoolingAssemblyRequirement, ...]]:
    """Bind the retained cooling geometry while refusing to treat proxies as parts."""

    def assumed(
        quantity_id: str,
        unit: str,
        value: str,
        rationale: str,
    ) -> BoundedQuantity:
        return _known(
            quantity_id,
            unit,
            value,
            value,
            value,
            knowledge=QuantityKnowledge.ASSUMPTION,
            evidence=(COOLING_ENVELOPE_ID,),
            rationale=rationale,
        )

    parts = (
        CoolingPart(
            part_id="power-mosfet-tolt-package-bank",
            role=CoolingPartRole.HEAT_SOURCE_PACKAGE,
            selection_state=CoolingSelectionState.EXACT_SELECTED,
            manufacturer="Infineon",
            mpn="IPTC011N08NM5ATMA1",
            occurrence_ids=("Q1", "Q2", "Q3", "Q4", "Q5", "Q6"),
            properties=(
                _known(
                    "junction_to_case_rth_max",
                    "K/W",
                    "0.4",
                    "0.4",
                    "0.4",
                    knowledge=QuantityKnowledge.DATASHEET_BOUND,
                    evidence=(MOSFET_SOURCE_ID,),
                ),
            ),
            source_binding_ids=(MOSFET_SOURCE_ID,),
            notes=("Exact electrical part; package-to-cooling assembly is not qualified.",),
        ),
        CoolingPart(
            part_id="tim-envelope-bank",
            role=CoolingPartRole.TIM,
            selection_state=CoolingSelectionState.GEOMETRY_PROXY,
            occurrence_ids=("TIM1", "TIM2", "TIM3", "TIM4", "TIM5", "TIM6"),
            properties=(
                assumed(
                    "thickness",
                    "mm",
                    "0.3",
                    "Placement envelope thickness; no material or compressed thickness selected.",
                ),
                _unknown(
                    "thermal_conductivity",
                    "W/(m*K)",
                    "No TIM material or guaranteed conductivity is selected.",
                ),
                _unknown(
                    "dielectric_withstand",
                    "V",
                    "No electrical-isolation system or voltage rating is selected.",
                ),
                _unknown(
                    "max_operating_temperature",
                    "degC",
                    "No TIM material temperature rating is selected.",
                ),
            ),
            source_binding_ids=(COOLING_ENVELOPE_ID, INFINEON_ASSEMBLY_SOURCE_ID),
            notes=("The six retained solids are visual envelopes, not orderable TIM parts.",),
        ),
        CoolingPart(
            part_id="shared-heatsink-envelope",
            role=CoolingPartRole.HEATSINK,
            selection_state=CoolingSelectionState.GEOMETRY_PROXY,
            occurrence_ids=("HS1",),
            properties=(
                assumed("width", "mm", "42", "Retained visual envelope width."),
                assumed("length", "mm", "82", "Retained visual envelope length."),
                assumed("base_thickness", "mm", "2", "Retained visual envelope base."),
                assumed("fin_height", "mm", "9", "Retained visual envelope fin height."),
                _unknown(
                    "sink_to_ambient_rth",
                    "K/W",
                    "No orderable heatsink, orientation, or airflow curve is selected.",
                ),
            ),
            source_binding_ids=(COOLING_ENVELOPE_ID, INFINEON_ASSEMBLY_SOURCE_ID),
            notes=("Envelope dimensions do not establish material, mass, or thermal rating.",),
        ),
        CoolingPart(
            part_id="m3-clamp-support-envelope",
            role=CoolingPartRole.FASTENER_OR_CLAMP,
            selection_state=CoolingSelectionState.GEOMETRY_PROXY,
            occurrence_ids=("H5", "H6", "H7", "H8"),
            properties=(
                assumed("hole_diameter", "mm", "3.2", "Retained M3 support-hole envelope."),
                _unknown("clamp_force", "N", "No clamp, spring, or force range is selected."),
                _unknown(
                    "installation_torque",
                    "N*m",
                    "No fastener stack or torque specification is selected.",
                ),
            ),
            source_binding_ids=(COOLING_ENVELOPE_ID, INFINEON_ASSEMBLY_SOURCE_ID),
            notes=("Support holes alone do not define MOSFET contact pressure.",),
        ),
        CoolingPart(
            part_id="shared-sink-insulation-system",
            role=CoolingPartRole.INSULATING_HARDWARE,
            selection_state=CoolingSelectionState.UNSELECTED,
            occurrence_ids=("required-for-shared-sink",),
            properties=(
                _unknown(
                    "dielectric_withstand",
                    "V",
                    "The isolation architecture for phase-dependent package surfaces is unset.",
                ),
            ),
            source_binding_ids=(INFINEON_ASSEMBLY_SOURCE_ID,),
            notes=("Electrical potential mapping must precede shared-sink release.",),
        ),
        CoolingPart(
            part_id="forced-air-system",
            role=CoolingPartRole.AIR_MOVER,
            selection_state=CoolingSelectionState.UNSELECTED,
            occurrence_ids=("forced-air-capability",),
            properties=(
                _unknown(
                    "airflow_velocity",
                    "m/s",
                    "Fan, duct, impedance curve, and failure-state airflow are unspecified.",
                ),
            ),
            source_binding_ids=(REQUEST_SOURCE_ID,),
            notes=("An airflow arrow in a visual study is not an airflow boundary condition.",),
        ),
    )
    interfaces = tuple(
        CoolingInterface(
            interface_id=f"{mosfet.lower()}-to-{tim.lower()}",
            part_a_id="power-mosfet-tolt-package-bank",
            part_b_id="tim-envelope-bank",
            contact_area=assumed(
                "package_contact_area",
                "mm^2",
                "158.62",
                "Package-envelope area of 10.3 mm by 15.4 mm; effective wetted area unknown.",
            ),
            thermal_resistance=_unknown(
                "package_to_tim_interface_rth",
                "K/W",
                "TIM conductivity, compressed thickness, wetting, flatness, and "
                "pressure are unset.",
            ),
            clamp_force=_unknown(
                "package_clamp_force",
                "N",
                "No selected clamp or per-package force distribution is defined.",
            ),
            requires_electrical_isolation=True,
            isolation_withstand=_unknown(
                "package_interface_isolation_withstand",
                "V",
                "Required withstand must follow the surface-potential and surge analysis.",
            ),
            surface_potential_ids=(
                f"{mosfet}:package-top-potential",
                "HS1:shared-heatsink-potential",
            ),
            source_binding_ids=(
                COOLING_ENVELOPE_ID,
                INFINEON_ASSEMBLY_SOURCE_ID,
                INFINEON_MOSFET_GUIDE_SOURCE_ID,
            ),
            notes=(f"Retained geometry pairs {mosfet} with {tim}; interface is unqualified.",),
        )
        for mosfet, tim in zip(
            ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6"),
            ("TIM1", "TIM2", "TIM3", "TIM4", "TIM5", "TIM6"),
            strict=True,
        )
    )
    profile = CoolingAssemblyProfile(
        profile_id="bldc-esc-r002-cooling-assembly",
        revision="1",
        geometry_authority_sha256=board_sha256,
        parts=parts,
        interfaces=interfaces,
        source_context_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            COOLING_ENVELOPE_ID,
            INFINEON_ASSEMBLY_SOURCE_ID,
            INFINEON_MOSFET_GUIDE_SOURCE_ID,
        ),
    )
    accepted = (
        CoolingSelectionState.EXACT_SELECTED,
        CoolingSelectionState.QUALIFIED_ALTERNATE,
    )
    requirements = (
        CoolingAssemblyRequirement(
            requirement_id="cooling.mosfet-package",
            role=CoolingPartRole.HEAT_SOURCE_PACKAGE,
            minimum_parts=1,
            accepted_selection_states=accepted,
            required_property_ids=("junction_to_case_rth_max",),
            rationale="The heat-source package and junction-to-case authority must be exact.",
        ),
        CoolingAssemblyRequirement(
            requirement_id="cooling.tim-selection",
            role=CoolingPartRole.TIM,
            minimum_parts=1,
            accepted_selection_states=accepted,
            required_property_ids=(
                "thickness",
                "thermal_conductivity",
                "dielectric_withstand",
                "max_operating_temperature",
            ),
            rationale="TIM selection must cover thermal, mechanical, and isolation behavior.",
        ),
        CoolingAssemblyRequirement(
            requirement_id="cooling.heatsink-selection",
            role=CoolingPartRole.HEATSINK,
            minimum_parts=1,
            accepted_selection_states=accepted,
            required_property_ids=("sink_to_ambient_rth",),
            rationale="An orderable sink needs a boundary-condition-specific thermal rating.",
        ),
        CoolingAssemblyRequirement(
            requirement_id="cooling.clamp-selection",
            role=CoolingPartRole.FASTENER_OR_CLAMP,
            minimum_parts=1,
            accepted_selection_states=accepted,
            required_property_ids=("clamp_force", "installation_torque"),
            rationale="The assembly must control force without package or board damage.",
        ),
        CoolingAssemblyRequirement(
            requirement_id="cooling.isolation-selection",
            role=CoolingPartRole.INSULATING_HARDWARE,
            minimum_parts=1,
            accepted_selection_states=accepted,
            required_property_ids=("dielectric_withstand",),
            rationale="A shared sink must have explicit electrical-isolation authority.",
        ),
        CoolingAssemblyRequirement(
            requirement_id="cooling.forced-air-selection",
            role=CoolingPartRole.AIR_MOVER,
            minimum_parts=1,
            accepted_selection_states=accepted,
            required_property_ids=("airflow_velocity",),
            rationale="Forced-air claims require a selected fan/duct operating point.",
        ),
    )
    return profile, requirements


def build_bldc_esc_transient_model(
    profile: MissionProfile,
    network: ElectrothermalNetwork,
) -> TransientThermalModel:
    peak = next(item for item in profile.scenarios if item.scenario_id == "peak.target-100a-10s")
    return TransientThermalModel(
        model_id="bldc-esc-r002-phase-u-100a-10s-transient",
        scenario_id=peak.scenario_id,
        subject_id="Q_U_HS+Q_U_LS",
        steady_network_fingerprint=network.semantic_fingerprint(),
        ambient_temperature=peak.environment.ambient_temperature,
        step_power=_unknown(
            "phase_u_switch_pair_peak_step_power",
            "W",
            "Peak conduction, switching, gate-drive, and dead-time losses are incomplete.",
        ),
        duration=_known(
            "transient_evaluation_duration",
            "s",
            "10",
            "10",
            "10",
            knowledge=QuantityKnowledge.DESIGN_TARGET,
            evidence=(REQUEST_SOURCE_ID,),
            rationale="Evaluate the requested ten-second peak endpoint.",
        ),
        branches=(
            TransientThermalBranch(
                branch_id="mosfet-junction-to-cooling-assembly-zth-fit",
                thermal_resistance=_unknown(
                    "foster_branch_thermal_resistance",
                    "K/W",
                    "No reviewed Zth curve digitization or correlated Foster fit exists.",
                ),
                time_constant=_unknown(
                    "foster_branch_time_constant",
                    "s",
                    "No reviewed Zth curve digitization or correlated Foster fit exists.",
                ),
                source_binding_ids=(MOSFET_SOURCE_ID, INFINEON_MOSFET_GUIDE_SOURCE_ID),
            ),
        ),
        source_context_ids=(
            REQUEST_SOURCE_ID,
            MOSFET_SOURCE_ID,
            INFINEON_MOSFET_GUIDE_SOURCE_ID,
        ),
    )


def build_bldc_esc_engineering_bundle(
    *,
    board_sha256: str | None = None,
) -> dict[str, Any]:
    register = build_bldc_esc_evidence_register()
    profile = build_bldc_esc_mission_profile()
    scenario_coverage = evaluate_scenario_coverage(
        profile,
        bldc_esc_scenario_requirements(),
    )
    ledger = build_bldc_esc_loss_ledger(profile, register)
    loss_coverage = evaluate_loss_coverage(ledger, bldc_esc_loss_requirements())
    electrothermal_network = build_bldc_esc_electrothermal_network(profile, ledger)
    electrothermal_result = solve_steady_state_point_network(electrothermal_network)
    cooling_assembly_profile, cooling_requirements = build_bldc_esc_cooling_assembly(board_sha256)
    cooling_assembly_evaluation = evaluate_cooling_assembly(
        cooling_assembly_profile,
        cooling_requirements,
    )
    cooling_candidate_register = build_bldc_esc_cooling_candidates()
    cooling_candidate_evaluation = evaluate_cooling_candidates(
        cooling_candidate_register,
        (
            CoolingPartRole.TIM,
            CoolingPartRole.HEATSINK,
            CoolingPartRole.FASTENER_OR_CLAMP,
            CoolingPartRole.INSULATING_HARDWARE,
            CoolingPartRole.AIR_MOVER,
        ),
    )
    gate_drive_profile = build_bldc_esc_gate_drive_profile(register)
    gate_drive_evaluation = evaluate_gate_drive_adequacy(gate_drive_profile)
    gate_charge_capacity_profile = build_bldc_esc_gate_charge_capacity_profile(
        profile,
        register,
    )
    gate_charge_capacity_result = evaluate_gate_charge_capacity(gate_charge_capacity_profile)
    dead_time_profile = build_bldc_esc_dead_time_profile()
    dead_time_evaluation = evaluate_dead_time_adequacy(dead_time_profile)
    gate_supply_options = build_bldc_esc_gate_supply_options()
    gate_supply_decision = evaluate_gate_supply_options(
        report_id="bldc-esc-r002-gate-supply-decision",
        revision="1",
        options=gate_supply_options,
        preferred_option_id="change-driver-drv8334-native-9v",
    )
    gate_driver_migration_profile = build_bldc_esc_gate_driver_migration_profile()
    gate_driver_migration_report = evaluate_gate_driver_migration(gate_driver_migration_profile)
    bootstrap_profile = build_bldc_esc_drv8334_bootstrap_profile()
    bootstrap_result = evaluate_bootstrap_capacitance(bootstrap_profile)
    driver_support_plan = build_bldc_esc_drv8334_support_plan(
        bootstrap_result.required_effective_capacitance
    )
    driver_support_report = evaluate_gate_driver_support_plan(driver_support_plan)
    protection_profile = build_bldc_esc_protection_coordination_profile()
    protection_report = evaluate_protection_coordination(protection_profile)
    surge_clamp_profile = build_bldc_esc_surge_clamp_profile()
    surge_clamp_report = evaluate_surge_clamp(surge_clamp_profile)
    coupled_electrothermal_model = build_bldc_esc_coupled_electrothermal_model(profile)
    coupled_electrothermal_result = solve_coupled_electrothermal_point(coupled_electrothermal_model)
    transient_thermal_model = build_bldc_esc_transient_model(
        profile,
        electrothermal_network,
    )
    transient_thermal_result = solve_transient_foster_step_point(transient_thermal_model)
    unresolved_scenario_requirements = tuple(
        item.requirement_id for item in scenario_coverage.evaluations if not item.satisfied
    )
    unresolved_loss_requirements = tuple(
        item.requirement_id
        for item in loss_coverage.evaluations
        if item.disposition == "incomplete"
    )
    readiness = {
        "schema": "pcbsmith-bldc-esc-engineering-readiness-v1",
        "status": "incomplete",
        "release_claims": {
            "30a_prototype": "not_released",
            "60a_continuous": "not_released",
            "100a_10s_peak": "not_released",
            "thermal_adequacy": "not_released",
        },
        "scenario_coverage": scenario_coverage.disposition,
        "loss_coverage": loss_coverage.disposition,
        "electrothermal_status": electrothermal_result.disposition,
        "cooling_assembly_status": cooling_assembly_evaluation.disposition,
        "cooling_candidate_status": cooling_candidate_evaluation.disposition,
        "gate_drive_status": gate_drive_evaluation.disposition,
        "gate_charge_capacity_status": gate_charge_capacity_result.disposition,
        "dead_time_status": dead_time_evaluation.disposition,
        "gate_supply_recommendation": gate_supply_decision.recommended_option_id,
        "gate_supply_selection_state": gate_supply_decision.selection_state,
        "gate_driver_migration_status": gate_driver_migration_report.disposition,
        "gate_driver_candidate": (gate_driver_migration_profile.candidate.orderable_part_number),
        "gate_driver_candidate_selection_state": (gate_driver_migration_report.selection_state),
        "gate_driver_bootstrap_status": bootstrap_result.disposition,
        "gate_driver_support_definition_state": driver_support_report.definition_state,
        "gate_driver_support_implementation_state": (driver_support_report.implementation_state),
        "protection_coordination_status": protection_report.disposition,
        "surge_clamp_coordination_status": surge_clamp_report.disposition,
        "coupled_electrothermal_status": coupled_electrothermal_result.disposition,
        "transient_thermal_status": transient_thermal_result.disposition,
        "retained_source_sha256": {
            MOSFET_SOURCE_ID: MOSFET_SHA256,
            SHUNT_SOURCE_ID: SHUNT_SHA256,
            INFINEON_ASSEMBLY_SOURCE_ID: INFINEON_ASSEMBLY_SHA256,
            INFINEON_MOSFET_GUIDE_SOURCE_ID: INFINEON_MOSFET_GUIDE_SHA256,
            TOLT_GUIDE_SOURCE_ID: TOLT_GUIDE_SHA256,
            HENKEL_TIM_SOURCE_ID: HENKEL_TIM_SHA256,
            BOYD_SINK_SOURCE_ID: BOYD_SINK_SHA256,
            DELTA_FAN_SOURCE_ID: DELTA_FAN_SHA256,
            GATE_DRIVER_SOURCE_ID: GATE_DRIVER_SHA256,
            DRV8334_SOURCE_ID: DRV8334_SHA256,
            TVS_SOURCE_ID: TVS_SHA256,
        },
        "retained_local_asset_sha256": {
            DRV8334_KICAD_FOOTPRINT_ID: DRV8334_KICAD_FOOTPRINT_SHA256,
            DRV8334_KICAD_MODEL_ID: DRV8334_KICAD_MODEL_SHA256,
        },
        "unresolved_scenario_requirement_ids": unresolved_scenario_requirements,
        "unresolved_loss_requirement_ids": unresolved_loss_requirements,
        "blocking_authorities": (
            "confirmed current-rating semantics and motor/load waveform",
            "complete mission duty cycle and environmental envelope",
            "measured or conservatively bounded switching transitions and dead time",
            "revised gate-supply architecture or narrowed input range with guaranteed VGS",
            "approved gate-driver selection and closed DRV8353-to-DRV8334 migration obligations",
            "retained IDRIVE and dead-time register configuration",
            "bounded or measured gate and switch-node transition timing",
            "guaranteed hot RDS(on) model at the selected gate drive",
            "routed copper/terminal/capacitor parasitic-loss model",
            "selected TIM, clamp, isolation, heatsink, and air-mover assembly",
            "coordinated bus TVS, fault interrupter, and reverse-polarity protection",
            "reviewed Zth curve fit and correlated transient thermal network",
            "project derating policy and transient VDS observations",
            "bench, oscilloscope, thermal-imaging, and load-test validation records",
        ),
        "notes": (
            "Shunt I^2R is computed. The prior 10V MOSFET conduction interval is a "
            "conditional arithmetic screen only: it is not applicable to the full "
            "9V minimum-bus scenario because guaranteed high-side VGS falls to 5.5V.",
            "Cooling parts are candidate records only. They do not satisfy cooling "
            "selection or assembly-validation requirements.",
            "Absolute maximum ratings are retained as evidence facts, not accepted "
            "operating limits.",
            "The placement-stage board contains no routed high-current copper authority.",
        ),
    }
    return {
        "evidence_register": register,
        "mission_profile": profile,
        "scenario_coverage": scenario_coverage,
        "loss_stress_ledger": ledger,
        "loss_coverage": loss_coverage,
        "electrothermal_network": electrothermal_network,
        "electrothermal_result": electrothermal_result,
        "cooling_assembly_profile": cooling_assembly_profile,
        "cooling_assembly_evaluation": cooling_assembly_evaluation,
        "cooling_candidate_register": cooling_candidate_register,
        "cooling_candidate_evaluation": cooling_candidate_evaluation,
        "gate_drive_profile": gate_drive_profile,
        "gate_drive_evaluation": gate_drive_evaluation,
        "gate_charge_capacity_profile": gate_charge_capacity_profile,
        "gate_charge_capacity_result": gate_charge_capacity_result,
        "dead_time_profile": dead_time_profile,
        "dead_time_evaluation": dead_time_evaluation,
        "gate_supply_options": {
            "schema": "pcbsmith-gate-supply-option-register-v1",
            "options": [item.model_dump(mode="json") for item in gate_supply_options],
        },
        "gate_supply_decision": gate_supply_decision,
        "gate_driver_migration_profile": gate_driver_migration_profile,
        "gate_driver_migration_report": gate_driver_migration_report,
        "gate_driver_bootstrap_profile": bootstrap_profile,
        "gate_driver_bootstrap_result": bootstrap_result,
        "gate_driver_support_plan": driver_support_plan,
        "gate_driver_support_report": driver_support_report,
        "protection_coordination_profile": protection_profile,
        "protection_coordination_report": protection_report,
        "surge_clamp_profile": surge_clamp_profile,
        "surge_clamp_report": surge_clamp_report,
        "coupled_electrothermal_model": coupled_electrothermal_model,
        "coupled_electrothermal_result": coupled_electrothermal_result,
        "transient_thermal_model": transient_thermal_model,
        "transient_thermal_result": transient_thermal_result,
        "engineering_readiness": readiness,
    }


def write_bldc_esc_engineering_evidence(evidence_dir: Path) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    board_path = evidence_dir.parent / "bldc-esc-60a-r002-thermal-placement.kicad_pcb"
    board_sha256 = (
        hashlib.sha256(board_path.read_bytes()).hexdigest() if board_path.is_file() else None
    )
    bundle = build_bldc_esc_engineering_bundle(board_sha256=board_sha256)
    names = {
        "evidence_register": "engineering-evidence-register.json",
        "mission_profile": "operating-scenarios.json",
        "scenario_coverage": "scenario-coverage.json",
        "loss_stress_ledger": "loss-stress-ledger.json",
        "loss_coverage": "loss-coverage.json",
        "electrothermal_network": "electrothermal-network.json",
        "electrothermal_result": "electrothermal-result.json",
        "cooling_assembly_profile": "cooling-assembly-profile.json",
        "cooling_assembly_evaluation": "cooling-assembly-evaluation.json",
        "cooling_candidate_register": "cooling-candidate-register.json",
        "cooling_candidate_evaluation": "cooling-candidate-evaluation.json",
        "gate_drive_profile": "gate-drive-profile.json",
        "gate_drive_evaluation": "gate-drive-evaluation.json",
        "gate_charge_capacity_profile": "gate-charge-capacity-profile.json",
        "gate_charge_capacity_result": "gate-charge-capacity-result.json",
        "dead_time_profile": "dead-time-profile.json",
        "dead_time_evaluation": "dead-time-evaluation.json",
        "gate_supply_options": "gate-supply-options.json",
        "gate_supply_decision": "gate-supply-decision.json",
        "gate_driver_migration_profile": "gate-driver-migration-profile.json",
        "gate_driver_migration_report": "gate-driver-migration-report.json",
        "gate_driver_bootstrap_profile": "gate-driver-bootstrap-profile.json",
        "gate_driver_bootstrap_result": "gate-driver-bootstrap-result.json",
        "gate_driver_support_plan": "gate-driver-support-plan.json",
        "gate_driver_support_report": "gate-driver-support-report.json",
        "protection_coordination_profile": "protection-coordination-profile.json",
        "protection_coordination_report": "protection-coordination-report.json",
        "surge_clamp_profile": "surge-clamp-profile.json",
        "surge_clamp_report": "surge-clamp-report.json",
        "coupled_electrothermal_model": "coupled-electrothermal-model.json",
        "coupled_electrothermal_result": "coupled-electrothermal-result.json",
        "transient_thermal_model": "transient-thermal-model.json",
        "transient_thermal_result": "transient-thermal-result.json",
        "engineering_readiness": "engineering-readiness.json",
    }
    for key, filename in names.items():
        value = bundle[key]
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        (evidence_dir / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "status": bundle["engineering_readiness"]["status"],
        "scenario_coverage": bundle["scenario_coverage"].disposition,
        "loss_coverage": bundle["loss_coverage"].disposition,
        "cooling_assembly_status": bundle["cooling_assembly_evaluation"].disposition,
        "gate_drive_status": bundle["gate_drive_evaluation"].disposition,
        "gate_charge_capacity_status": bundle["gate_charge_capacity_result"].disposition,
        "dead_time_status": bundle["dead_time_evaluation"].disposition,
        "gate_supply_recommendation": bundle["gate_supply_decision"].recommended_option_id,
        "gate_supply_selection_state": bundle["gate_supply_decision"].selection_state,
        "gate_driver_migration_status": bundle["gate_driver_migration_report"].disposition,
        "gate_driver_candidate_selection_state": bundle[
            "gate_driver_migration_report"
        ].selection_state,
        "gate_driver_bootstrap_status": bundle["gate_driver_bootstrap_result"].disposition,
        "gate_driver_support_definition_state": bundle[
            "gate_driver_support_report"
        ].definition_state,
        "gate_driver_support_implementation_state": bundle[
            "gate_driver_support_report"
        ].implementation_state,
        "protection_coordination_status": bundle["protection_coordination_report"].disposition,
        "surge_clamp_coordination_status": bundle["surge_clamp_report"].disposition,
        "coupled_electrothermal_status": bundle["coupled_electrothermal_result"].disposition,
        "transient_thermal_status": bundle["transient_thermal_result"].disposition,
        "evidence_files": tuple(str(evidence_dir / name) for name in names.values()),
    }
