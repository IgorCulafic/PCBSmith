"""Typed gate-supply architecture options and non-selecting decision authority."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.engineering_quantity_ir import (
    BoundedQuantity,
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.gate_drive_ir import (
    GateDriveChannelKind,
    GateDriveChannelPoint,
    GateDriveProfile,
    evaluate_gate_drive_adequacy,
)
from pcbsmith.semantic_ir import SemanticIrModel


class GateSupplyArchitectureKind(StrEnum):
    BUS_COUPLED = "bus_coupled"
    SEPARATE_REGULATED = "separate_regulated"
    CHANGE_POWER_DEVICE = "change_power_device"
    CHANGE_GATE_DRIVER = "change_gate_driver"


class GateSupplyOption(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-supply-option"] = "pcbsmith-gate-supply-option"
    schema_version: Literal[1] = 1
    option_id: str
    kind: GateSupplyArchitectureKind
    driver_id: str
    power_device_id: str
    driver_supply_voltage: BoundedQuantity
    high_side_gate_voltage: BoundedQuantity
    low_side_gate_voltage: BoundedQuantity
    characterized_gate_voltage: BoundedQuantity
    required_margin: BoundedQuantity
    hardware_change_ids: tuple[str, ...]
    unresolved_authority_ids: tuple[str, ...]
    source_binding_ids: tuple[str, ...]
    notes: tuple[str, ...]

    @model_validator(mode="after")
    def option_is_coherent(self) -> Self:
        for field_name in ("option_id", "driver_id", "power_device_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        for quantity in (
            self.driver_supply_voltage,
            self.high_side_gate_voltage,
            self.low_side_gate_voltage,
            self.characterized_gate_voltage,
            self.required_margin,
        ):
            if quantity.unit != "V":
                raise ValueError("gate-supply option quantities must use volts")
        for field_name in (
            "hardware_change_ids",
            "unresolved_authority_ids",
            "source_binding_ids",
        ):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, values)
        if not self.source_binding_ids:
            raise ValueError("gate-supply options require source context")
        notes = tuple(require_engineering_identity(note, "notes") for note in self.notes)
        if not notes:
            raise ValueError("gate-supply options require limitations or rationale")
        object.__setattr__(self, "notes", notes)
        return self


class GateSupplyOptionEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-supply-option-evaluation"] = (
        "pcbsmith-gate-supply-option-evaluation"
    )
    schema_version: Literal[1] = 1
    option_id: str
    disposition: Literal["infeasible", "conditional_candidate", "feasible"]
    gate_voltage_disposition: Literal["adequate", "inadequate", "indeterminate"]
    high_side_margin: BoundedQuantity
    low_side_margin: BoundedQuantity
    unresolved_authority_ids: tuple[str, ...]
    findings: tuple[str, ...]


class GateSupplyDecisionReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-supply-decision-report"] = (
        "pcbsmith-gate-supply-decision-report"
    )
    schema_version: Literal[1] = 1
    report_id: str
    revision: str
    option_fingerprints: tuple[str, ...]
    evaluations: tuple[GateSupplyOptionEvaluation, ...]
    recommended_option_id: str | None
    recommendation_state: Literal["preferred_for_next_iteration", "no_viable_option"]
    selection_state: Literal["not_selected"] = "not_selected"
    findings: tuple[str, ...]


def evaluate_gate_supply_options(
    *,
    report_id: str,
    revision: str,
    options: tuple[GateSupplyOption, ...],
    preferred_option_id: str | None,
) -> GateSupplyDecisionReport:
    """Evaluate voltage applicability while refusing to select hardware."""

    require_engineering_identity(report_id, "report_id")
    require_engineering_identity(revision, "revision")
    ordered = tuple(sorted(options, key=lambda item: item.option_id))
    if not ordered:
        raise ValueError("gate-supply decisions require at least one option")
    if len(ordered) != len({item.option_id for item in ordered}):
        raise ValueError("gate-supply option identities must be unique")
    evaluations = []
    for option in ordered:
        profile = GateDriveProfile(
            profile_id=f"{option.option_id}:gate-voltage",
            scenario_id="architecture-screen",
            driver_id=option.driver_id,
            power_device_id=option.power_device_id,
            driver_supply_voltage=option.driver_supply_voltage,
            characterized_gate_voltage=option.characterized_gate_voltage,
            required_margin=option.required_margin,
            channels=(
                GateDriveChannelPoint(
                    channel_id=f"{option.option_id}:high-side",
                    kind=GateDriveChannelKind.HIGH_SIDE,
                    available_gate_voltage=option.high_side_gate_voltage,
                    source_binding_ids=option.source_binding_ids,
                ),
                GateDriveChannelPoint(
                    channel_id=f"{option.option_id}:low-side",
                    kind=GateDriveChannelKind.LOW_SIDE,
                    available_gate_voltage=option.low_side_gate_voltage,
                    source_binding_ids=option.source_binding_ids,
                ),
            ),
            source_context_ids=option.source_binding_ids,
        )
        gate_result = evaluate_gate_drive_adequacy(profile)
        margins = {
            item.channel_id.rsplit(":", 1)[-1]: item.worst_case_margin
            for item in gate_result.channel_evaluations
        }
        if gate_result.disposition == "inadequate":
            disposition: Literal["infeasible", "conditional_candidate", "feasible"] = (
                "infeasible"
            )
        elif gate_result.disposition == "indeterminate" or option.unresolved_authority_ids:
            disposition = "conditional_candidate"
        else:
            disposition = "feasible"
        evaluations.append(
            GateSupplyOptionEvaluation(
                option_id=option.option_id,
                disposition=disposition,
                gate_voltage_disposition=gate_result.disposition,
                high_side_margin=margins["high-side"],
                low_side_margin=margins["low-side"],
                unresolved_authority_ids=option.unresolved_authority_ids,
                findings=option.notes,
            )
        )
    known_ids = {item.option_id for item in evaluations}
    if preferred_option_id is not None and preferred_option_id not in known_ids:
        raise ValueError("preferred gate-supply option is absent")
    preferred = next(
        (item for item in evaluations if item.option_id == preferred_option_id),
        None,
    )
    if preferred is not None and preferred.disposition == "infeasible":
        raise ValueError("an infeasible gate-supply option cannot be preferred")
    recommendation_state: Literal["preferred_for_next_iteration", "no_viable_option"]
    if preferred is None:
        recommendation_state = "no_viable_option"
    else:
        recommendation_state = "preferred_for_next_iteration"
    return GateSupplyDecisionReport(
        report_id=report_id,
        revision=revision,
        option_fingerprints=tuple(item.semantic_fingerprint() for item in ordered),
        evaluations=tuple(evaluations),
        recommended_option_id=preferred_option_id,
        recommendation_state=recommendation_state,
        findings=(
            "A preferred option is an analysis recommendation, not a selected schematic part.",
            "Every unresolved authority must close before implementation or release.",
        ),
    )
