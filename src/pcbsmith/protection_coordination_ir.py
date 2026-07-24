"""Typed protection-path coverage and fault-coordination authority."""

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


class ProtectionEventKind(StrEnum):
    STALL = "stall"
    SHOOT_THROUGH = "shoot_through"
    PHASE_SHORT = "phase_short"
    BUS_OR_BATTERY_SHORT = "bus_or_battery_short"
    REVERSE_POLARITY = "reverse_polarity"
    REGENERATIVE_BUS_RISE = "regenerative_bus_rise"
    HOT_PLUG = "hot_plug"
    GATE_DRIVE_FAULT = "gate_drive_fault"
    COOLING_OR_OVERTEMPERATURE = "cooling_or_overtemperature"


class ProtectionPath(SemanticIrModel):
    schema_id: Literal["pcbsmith-protection-path"] = "pcbsmith-protection-path"
    schema_version: Literal[1] = 1
    path_id: str
    event_kinds: tuple[ProtectionEventKind, ...]
    detector_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    independent_domain_id: str
    detection_threshold: BoundedQuantity
    detection_latency: BoundedQuantity
    shutdown_latency: BoundedQuantity
    residual_energy: BoundedQuantity
    source_binding_ids: tuple[str, ...]
    notes: tuple[str, ...]

    @model_validator(mode="after")
    def path_is_coherent(self) -> Self:
        for field_name in ("path_id", "independent_domain_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        events = tuple(sorted(set(self.event_kinds), key=lambda item: item.value))
        if not events:
            raise ValueError("protection paths require at least one event")
        object.__setattr__(self, "event_kinds", events)
        for field_name in ("detector_ids", "action_ids", "source_binding_ids"):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            if not values:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, values)
        if self.detection_latency.unit != "s" or self.shutdown_latency.unit != "s":
            raise ValueError("protection latency quantities must use seconds")
        if self.residual_energy.unit != "J":
            raise ValueError("protection residual energy must use joules")
        notes = tuple(require_engineering_identity(note, "notes") for note in self.notes)
        if not notes:
            raise ValueError("protection paths require applicability notes")
        object.__setattr__(self, "notes", notes)
        return self


class ProtectionRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-protection-requirement"] = "pcbsmith-protection-requirement"
    schema_version: Literal[1] = 1
    requirement_id: str
    event_kind: ProtectionEventKind
    required_independent_domain_count: int
    required_action_ids: tuple[str, ...]
    maximum_total_latency: BoundedQuantity
    maximum_residual_energy: BoundedQuantity
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def requirement_is_coherent(self) -> Self:
        require_engineering_identity(self.requirement_id, "requirement_id")
        if self.required_independent_domain_count <= 0:
            raise ValueError("required independent-domain count must be positive")
        if self.maximum_total_latency.unit != "s":
            raise ValueError("maximum total latency must use seconds")
        if self.maximum_residual_energy.unit != "J":
            raise ValueError("maximum residual energy must use joules")
        for field_name in ("required_action_ids", "source_binding_ids"):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            if not values:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, values)
        return self


class ProtectionCoordinationProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-protection-coordination-profile"] = (
        "pcbsmith-protection-coordination-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    revision: str
    paths: tuple[ProtectionPath, ...]
    requirements: tuple[ProtectionRequirement, ...]
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_coherent(self) -> Self:
        for field_name in ("profile_id", "revision"):
            require_engineering_identity(getattr(self, field_name), field_name)
        for values, label in (
            (tuple(item.path_id for item in self.paths), "path"),
            (tuple(item.requirement_id for item in self.requirements), "requirement"),
        ):
            if not values or len(values) != len(set(values)):
                raise ValueError(f"protection {label} identities must be non-empty and unique")
        sources = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not sources:
            raise ValueError("protection profiles require source context")
        object.__setattr__(self, "source_context_ids", sources)
        return self


class ProtectionRequirementEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-protection-requirement-evaluation"] = (
        "pcbsmith-protection-requirement-evaluation"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    disposition: Literal["covered", "incomplete"]
    matching_path_ids: tuple[str, ...]
    independent_domain_ids: tuple[str, ...]
    missing_action_ids: tuple[str, ...]
    missing_input_ids: tuple[str, ...]
    findings: tuple[str, ...]


class ProtectionCoordinationReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-protection-coordination-report"] = (
        "pcbsmith-protection-coordination-report"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["complete", "incomplete"]
    evaluations: tuple[ProtectionRequirementEvaluation, ...]
    findings: tuple[str, ...]


def evaluate_protection_coordination(
    profile: ProtectionCoordinationProfile,
) -> ProtectionCoordinationReport:
    evaluations = []
    for requirement in sorted(profile.requirements, key=lambda item: item.requirement_id):
        paths = tuple(item for item in profile.paths if requirement.event_kind in item.event_kinds)
        missing_inputs: set[str] = set()
        findings = []
        requirement_known = True
        for quantity in (
            requirement.maximum_total_latency,
            requirement.maximum_residual_energy,
        ):
            if not quantity.is_known:
                missing_inputs.add(quantity.quantity_id)
                requirement_known = False
        qualifying_paths = []
        for path in paths:
            path_known = True
            for quantity in (
                path.detection_threshold,
                path.detection_latency,
                path.shutdown_latency,
                path.residual_energy,
            ):
                if not quantity.is_known:
                    missing_inputs.add(quantity.quantity_id)
                    path_known = False
            if not path_known or not requirement_known:
                continue
            assert path.detection_latency.upper is not None
            assert path.shutdown_latency.upper is not None
            assert path.residual_energy.upper is not None
            assert requirement.maximum_total_latency.lower is not None
            assert requirement.maximum_residual_energy.lower is not None
            total_latency = path.detection_latency.upper + path.shutdown_latency.upper
            latency_ok = total_latency <= requirement.maximum_total_latency.lower
            energy_ok = path.residual_energy.upper <= requirement.maximum_residual_energy.lower
            if latency_ok and energy_ok:
                qualifying_paths.append(path)
            else:
                if not latency_ok:
                    findings.append(f"Path {path.path_id} exceeds the latency limit.")
                if not energy_ok:
                    findings.append(f"Path {path.path_id} exceeds the residual-energy limit.")
        domains = tuple(sorted({item.independent_domain_id for item in qualifying_paths}))
        actions = {action for item in qualifying_paths for action in item.action_ids}
        missing_actions = tuple(sorted(set(requirement.required_action_ids) - actions))
        enough_domains = len(domains) >= requirement.required_independent_domain_count
        covered = enough_domains and not missing_actions
        if not enough_domains:
            findings.append(
                f"Requires {requirement.required_independent_domain_count} independent domains; "
                f"only {len(domains)} are declared."
            )
        if not paths:
            findings.append("No protection path is declared for this event.")
        evaluations.append(
            ProtectionRequirementEvaluation(
                requirement_id=requirement.requirement_id,
                disposition="covered" if covered else "incomplete",
                matching_path_ids=tuple(sorted(item.path_id for item in paths)),
                independent_domain_ids=domains,
                missing_action_ids=missing_actions,
                missing_input_ids=tuple(sorted(missing_inputs)),
                findings=tuple(findings),
            )
        )
    disposition: Literal["complete", "incomplete"] = (
        "complete" if all(item.disposition == "covered" for item in evaluations) else "incomplete"
    )
    return ProtectionCoordinationReport(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition=disposition,
        evaluations=tuple(evaluations),
        findings=(
            "Declared detectors do not prove threshold, timing, energy, or safe-state adequacy.",
            "Absolute maximum ratings cannot serve as protection thresholds or "
            "residual-energy limits.",
            "Firmware and hardware paths share a domain unless their independence "
            "is explicitly retained.",
        ),
    )
