"""Typed external-support requirements for a candidate gate driver."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.engineering_quantity_ir import (
    BoundedQuantity,
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.semantic_ir import SemanticIrModel


class GateDriverSupportRole(StrEnum):
    SUPPLY_BYPASS = "supply_bypass"
    CHARGE_PUMP_FLYING = "charge_pump_flying"
    CHARGE_PUMP_RESERVOIR = "charge_pump_reservoir"
    BOOTSTRAP = "bootstrap"
    REFERENCE_BYPASS = "reference_bypass"


class GateDriverSupportRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-driver-support-requirement"] = (
        "pcbsmith-gate-driver-support-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    role: GateDriverSupportRole
    pin_ids: tuple[str, ...]
    component_count: int
    recommended_nominal_value: BoundedQuantity
    minimum_effective_value: BoundedQuantity
    maximum_applied_voltage: BoundedQuantity
    selected_mpn: str | None = None
    selected_footprint_id: str | None = None
    placement_obligation_ids: tuple[str, ...]
    source_binding_ids: tuple[str, ...]
    notes: tuple[str, ...]

    @model_validator(mode="after")
    def requirement_is_coherent(self) -> Self:
        require_engineering_identity(self.requirement_id, "requirement_id")
        if self.component_count <= 0:
            raise ValueError("support component count must be positive")
        if self.recommended_nominal_value.unit != self.minimum_effective_value.unit:
            raise ValueError("nominal and effective values must use the same unit")
        if self.maximum_applied_voltage.unit != "V":
            raise ValueError("support applied voltage must use volts")
        for field_name in (
            "pin_ids",
            "placement_obligation_ids",
            "source_binding_ids",
        ):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            if not values:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, values)
        if (self.selected_mpn is None) != (self.selected_footprint_id is None):
            raise ValueError("selected MPN and footprint must be supplied together")
        if self.selected_mpn is not None:
            require_engineering_identity(self.selected_mpn, "selected_mpn")
            assert self.selected_footprint_id is not None
            require_engineering_identity(self.selected_footprint_id, "selected_footprint_id")
        notes = tuple(require_engineering_identity(note, "notes") for note in self.notes)
        if not notes:
            raise ValueError("support requirements need source/applicability notes")
        object.__setattr__(self, "notes", notes)
        return self


class GateDriverSupportPlan(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-driver-support-plan"] = "pcbsmith-gate-driver-support-plan"
    schema_version: Literal[1] = 1
    plan_id: str
    revision: str
    driver_candidate_id: str
    requirements: tuple[GateDriverSupportRequirement, ...]
    source_context_ids: tuple[str, ...]
    selection_state: Literal["not_selected"] = "not_selected"

    @model_validator(mode="after")
    def plan_is_coherent(self) -> Self:
        for field_name in ("plan_id", "revision", "driver_candidate_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        requirement_ids = tuple(item.requirement_id for item in self.requirements)
        if not requirement_ids or len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("support requirement identities must be non-empty and unique")
        sources = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not sources:
            raise ValueError("support plans require source context")
        object.__setattr__(self, "source_context_ids", sources)
        return self


class GateDriverSupportPlanReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-driver-support-plan-report"] = (
        "pcbsmith-gate-driver-support-plan-report"
    )
    schema_version: Literal[1] = 1
    plan_id: str
    plan_fingerprint: str
    definition_state: Literal["complete", "incomplete"]
    selection_state: Literal["not_selected"] = "not_selected"
    implementation_state: Literal["blocked", "ready"]
    physical_component_count: int
    unresolved_requirement_ids: tuple[str, ...]
    unselected_requirement_ids: tuple[str, ...]
    findings: tuple[str, ...]


def evaluate_gate_driver_support_plan(
    plan: GateDriverSupportPlan,
) -> GateDriverSupportPlanReport:
    unresolved = tuple(
        sorted(
            item.requirement_id
            for item in plan.requirements
            if not item.minimum_effective_value.is_known
            or not item.maximum_applied_voltage.is_known
        )
    )
    unselected = tuple(
        sorted(item.requirement_id for item in plan.requirements if item.selected_mpn is None)
    )
    implementation_state: Literal["blocked", "ready"] = (
        "blocked" if unresolved or unselected else "ready"
    )
    return GateDriverSupportPlanReport(
        plan_id=plan.plan_id,
        plan_fingerprint=plan.semantic_fingerprint(),
        definition_state="incomplete" if unresolved else "complete",
        implementation_state=implementation_state,
        physical_component_count=sum(item.component_count for item in plan.requirements),
        unresolved_requirement_ids=unresolved,
        unselected_requirement_ids=unselected,
        findings=(
            "Datasheet-recommended nominal capacitance is not an effective-capacitance guarantee.",
            "Selection requires exact MPN, footprint, bias/temperature/tolerance "
            "bounds, and placement review.",
            "A complete support plan cannot select the gate-driver architecture by itself.",
        ),
    )
