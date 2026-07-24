"""Typed operating-scenario and mission-profile authority."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.engineering_quantity_ir import (
    BoundedQuantity,
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.semantic_ir import SemanticIrModel


class ScenarioRole(StrEnum):
    STANDBY = "standby"
    STARTUP = "startup"
    NORMAL = "normal"
    PEAK = "peak"
    OVERLOAD_OR_STALL = "overload_or_stall"
    REGENERATIVE = "regenerative"
    HOT_PLUG = "hot_plug"
    BROWNOUT = "brownout"
    SHUTDOWN = "shutdown"
    SHORT_CIRCUIT = "short_circuit"
    COOLING_FAILURE = "cooling_failure"
    ENVIRONMENTAL_CORNER = "environmental_corner"


class AirflowState(StrEnum):
    STILL_AIR = "still_air"
    FORCED = "forced"
    UNKNOWN = "unknown"


class EnclosureState(StrEnum):
    OPEN_BENCH = "open_bench"
    ENCLOSED = "enclosed"
    UNKNOWN = "unknown"


class OperatingEnvironment(SemanticIrModel):
    schema_id: Literal["pcbsmith-operating-environment"] = "pcbsmith-operating-environment"
    schema_version: Literal[1] = 1
    ambient_temperature: BoundedQuantity
    airflow_state: AirflowState
    airflow_velocity: BoundedQuantity | None = None
    enclosure_state: EnclosureState
    orientation: str
    condition_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def environment_is_coherent(self) -> Self:
        if self.ambient_temperature.unit not in {"degC", "K"}:
            raise ValueError("ambient temperature must use explicit degC or K units")
        if self.airflow_state is AirflowState.FORCED:
            if self.airflow_velocity is None or not self.airflow_velocity.is_known:
                raise ValueError("forced airflow requires a known velocity interval")
        elif self.airflow_state is AirflowState.UNKNOWN and self.airflow_velocity is not None:
            raise ValueError("unknown airflow cannot carry a velocity claim")
        if self.airflow_velocity is not None and self.airflow_velocity.unit != "m/s":
            raise ValueError("airflow velocity must use m/s")
        require_engineering_identity(self.orientation, "orientation")
        object.__setattr__(
            self,
            "condition_ids",
            canonical_engineering_identities(self.condition_ids, "condition_ids"),
        )
        return self


class OperatingScenario(SemanticIrModel):
    schema_id: Literal["pcbsmith-operating-scenario"] = "pcbsmith-operating-scenario"
    schema_version: Literal[1] = 1
    scenario_id: str
    role: ScenarioRole
    description: str
    steady_state: bool
    fault_scenario: bool
    duration: BoundedQuantity | None = None
    duty_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    electrical_quantities: tuple[BoundedQuantity, ...]
    environment: OperatingEnvironment
    active_path_ids: tuple[str, ...]
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def scenario_is_canonical(self) -> Self:
        require_engineering_identity(self.scenario_id, "scenario_id")
        require_engineering_identity(self.description, "description")
        if self.duration is not None and self.duration.unit != "s":
            raise ValueError("scenario duration must use seconds")
        if self.fault_scenario and self.duty_fraction is not None:
            raise ValueError("fault scenarios cannot consume normal mission duty fraction")
        quantities = tuple(sorted(self.electrical_quantities, key=lambda item: item.quantity_id))
        if len(quantities) != len({item.quantity_id for item in quantities}):
            raise ValueError("scenario electrical quantity identities must be unique")
        object.__setattr__(self, "electrical_quantities", quantities)
        for field_name in ("active_path_ids", "source_context_ids"):
            object.__setattr__(
                self,
                field_name,
                canonical_engineering_identities(getattr(self, field_name), field_name),
            )
        if not self.source_context_ids:
            raise ValueError("operating scenarios require source-context identity")
        return self

    def quantity(self, quantity_id: str) -> BoundedQuantity | None:
        return next(
            (item for item in self.electrical_quantities if item.quantity_id == quantity_id),
            None,
        )


class MissionProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-mission-profile"] = "pcbsmith-mission-profile"
    schema_version: Literal[1] = 1
    profile_id: str
    revision: str
    scenarios: tuple[OperatingScenario, ...]
    duty_cycle_complete: bool = False
    intended_claim_ids: tuple[str, ...]
    source_context_ids: tuple[str, ...]
    reviewer_record_id: str | None = None

    @model_validator(mode="after")
    def mission_is_canonical(self) -> Self:
        require_engineering_identity(self.profile_id, "profile_id")
        require_engineering_identity(self.revision, "revision")
        scenarios = tuple(sorted(self.scenarios, key=lambda item: item.scenario_id))
        if len(scenarios) != len({item.scenario_id for item in scenarios}):
            raise ValueError("mission scenario identities must be unique")
        duty_sum = sum(
            (item.duty_fraction or Decimal("0")) for item in scenarios if not item.fault_scenario
        )
        if duty_sum > Decimal("1"):
            raise ValueError("normal mission duty fractions exceed 1")
        if self.duty_cycle_complete and duty_sum != Decimal("1"):
            raise ValueError("complete mission duty fractions must sum exactly to 1")
        object.__setattr__(self, "scenarios", scenarios)
        for field_name in ("intended_claim_ids", "source_context_ids"):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            if not values:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, values)
        if self.reviewer_record_id is not None:
            require_engineering_identity(self.reviewer_record_id, "reviewer_record_id")
        return self


class ScenarioCoverageRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-scenario-coverage-requirement"] = (
        "pcbsmith-scenario-coverage-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    role: ScenarioRole
    minimum_scenarios: int = Field(default=1, ge=1)
    required_quantity_ids: tuple[str, ...] = ()
    requires_duration: bool = False
    requires_duty_fraction: bool = False
    requires_known_airflow: bool = False
    requires_known_enclosure: bool = False
    requires_known_ambient_temperature: bool = False
    rationale: str

    @model_validator(mode="after")
    def requirement_is_canonical(self) -> Self:
        require_engineering_identity(self.requirement_id, "requirement_id")
        require_engineering_identity(self.rationale, "rationale")
        object.__setattr__(
            self,
            "required_quantity_ids",
            canonical_engineering_identities(
                self.required_quantity_ids,
                "required_quantity_ids",
            ),
        )
        return self


class ScenarioCoverageEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-scenario-coverage-evaluation"] = (
        "pcbsmith-scenario-coverage-evaluation"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    complete_scenario_ids: tuple[str, ...]
    incomplete_scenario_ids: tuple[str, ...]
    satisfied: bool
    findings: tuple[str, ...] = ()


class ScenarioCoverageReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-scenario-coverage-report"] = "pcbsmith-scenario-coverage-report"
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["complete", "incomplete"]
    evaluations: tuple[ScenarioCoverageEvaluation, ...]


def evaluate_scenario_coverage(
    profile: MissionProfile,
    requirements: tuple[ScenarioCoverageRequirement, ...],
) -> ScenarioCoverageReport:
    ordered = tuple(sorted(requirements, key=lambda item: item.requirement_id))
    if len(ordered) != len({item.requirement_id for item in ordered}):
        raise ValueError("scenario coverage requirement identities must be unique")
    evaluations: list[ScenarioCoverageEvaluation] = []
    for requirement in ordered:
        matching = tuple(item for item in profile.scenarios if item.role is requirement.role)
        complete: list[str] = []
        incomplete: list[str] = []
        findings: list[str] = []
        for scenario in matching:
            missing: list[str] = []
            for quantity_id in requirement.required_quantity_ids:
                quantity = scenario.quantity(quantity_id)
                if quantity is None or not quantity.is_known:
                    missing.append(quantity_id)
            conditions: list[str] = []
            if missing:
                conditions.append("unresolved quantities: " + ", ".join(missing))
            if requirement.requires_duration and (
                scenario.duration is None or not scenario.duration.is_known
            ):
                conditions.append("known duration is required")
            if requirement.requires_duty_fraction and scenario.duty_fraction is None:
                conditions.append("duty fraction is required")
            if (
                requirement.requires_known_airflow
                and scenario.environment.airflow_state is AirflowState.UNKNOWN
            ):
                conditions.append("airflow state is unresolved")
            if (
                requirement.requires_known_enclosure
                and scenario.environment.enclosure_state is EnclosureState.UNKNOWN
            ):
                conditions.append("enclosure state is unresolved")
            if (
                requirement.requires_known_ambient_temperature
                and not scenario.environment.ambient_temperature.is_known
            ):
                conditions.append("ambient temperature is unresolved")
            if conditions:
                incomplete.append(scenario.scenario_id)
                findings.append(f"{scenario.scenario_id}: " + "; ".join(conditions))
            else:
                complete.append(scenario.scenario_id)
        if len(complete) < requirement.minimum_scenarios:
            findings.append(
                f"role {requirement.role.value} has {len(complete)} complete scenario(s); "
                f"{requirement.minimum_scenarios} required"
            )
        evaluations.append(
            ScenarioCoverageEvaluation(
                requirement_id=requirement.requirement_id,
                complete_scenario_ids=tuple(sorted(complete)),
                incomplete_scenario_ids=tuple(sorted(incomplete)),
                satisfied=len(complete) >= requirement.minimum_scenarios,
                findings=tuple(findings),
            )
        )
    disposition: Literal["complete", "incomplete"] = (
        "complete" if all(item.satisfied for item in evaluations) else "incomplete"
    )
    return ScenarioCoverageReport(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition=disposition,
        evaluations=tuple(evaluations),
    )
