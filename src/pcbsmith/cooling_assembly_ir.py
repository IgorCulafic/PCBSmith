"""Typed cooling-assembly, interface, clamping, and isolation authority."""

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


class CoolingPartRole(StrEnum):
    HEAT_SOURCE_PACKAGE = "heat_source_package"
    TIM = "tim"
    SPREADER = "spreader"
    HEATSINK = "heatsink"
    FASTENER_OR_CLAMP = "fastener_or_clamp"
    INSULATING_HARDWARE = "insulating_hardware"
    AIR_MOVER = "air_mover"


class CoolingSelectionState(StrEnum):
    EXACT_SELECTED = "exact_selected"
    QUALIFIED_ALTERNATE = "qualified_alternate"
    GEOMETRY_PROXY = "geometry_proxy"
    UNSELECTED = "unselected"


class CoolingCandidateStatus(StrEnum):
    SCREENED = "screened"
    VENDOR_CONFIRMATION_REQUIRED = "vendor_confirmation_required"
    SYSTEM_VALIDATION_REQUIRED = "system_validation_required"
    REJECTED = "rejected"


class CoolingPart(SemanticIrModel):
    schema_id: Literal["pcbsmith-cooling-part"] = "pcbsmith-cooling-part"
    schema_version: Literal[1] = 1
    part_id: str
    role: CoolingPartRole
    selection_state: CoolingSelectionState
    manufacturer: str | None = None
    mpn: str | None = None
    occurrence_ids: tuple[str, ...]
    properties: tuple[BoundedQuantity, ...] = ()
    source_binding_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def part_is_coherent(self) -> Self:
        require_engineering_identity(self.part_id, "part_id")
        occurrences = canonical_engineering_identities(
            self.occurrence_ids,
            "occurrence_ids",
        )
        if not occurrences:
            raise ValueError("cooling parts require at least one occurrence")
        properties = tuple(sorted(self.properties, key=lambda item: item.quantity_id))
        if len(properties) != len({item.quantity_id for item in properties}):
            raise ValueError("cooling-part property identities must be unique")
        bindings = canonical_engineering_identities(
            self.source_binding_ids,
            "source_binding_ids",
        )
        if not bindings:
            raise ValueError("cooling parts require source or assumption bindings")
        if self.selection_state in {
            CoolingSelectionState.EXACT_SELECTED,
            CoolingSelectionState.QUALIFIED_ALTERNATE,
        }:
            if self.manufacturer is None or self.mpn is None:
                raise ValueError("selected cooling parts require manufacturer and MPN")
        for field_name in ("manufacturer", "mpn"):
            value = getattr(self, field_name)
            if value is not None:
                require_engineering_identity(value, field_name)
        notes = tuple(require_engineering_identity(note, "notes") for note in self.notes)
        object.__setattr__(self, "occurrence_ids", occurrences)
        object.__setattr__(self, "properties", properties)
        object.__setattr__(self, "source_binding_ids", bindings)
        object.__setattr__(self, "notes", notes)
        return self

    def property(self, quantity_id: str) -> BoundedQuantity | None:
        return next(
            (item for item in self.properties if item.quantity_id == quantity_id),
            None,
        )


class CoolingInterface(SemanticIrModel):
    schema_id: Literal["pcbsmith-cooling-interface"] = "pcbsmith-cooling-interface"
    schema_version: Literal[1] = 1
    interface_id: str
    part_a_id: str
    part_b_id: str
    contact_area: BoundedQuantity
    thermal_resistance: BoundedQuantity
    clamp_force: BoundedQuantity
    requires_electrical_isolation: bool
    isolation_withstand: BoundedQuantity
    surface_potential_ids: tuple[str, ...]
    source_binding_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def interface_is_coherent(self) -> Self:
        for field_name in ("interface_id", "part_a_id", "part_b_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        if self.part_a_id == self.part_b_id:
            raise ValueError("cooling interface requires two distinct parts")
        expected_units = (
            (self.contact_area, "mm^2"),
            (self.thermal_resistance, "K/W"),
            (self.clamp_force, "N"),
            (self.isolation_withstand, "V"),
        )
        for quantity, expected_unit in expected_units:
            if quantity.unit != expected_unit:
                raise ValueError(f"{quantity.quantity_id} must use explicit {expected_unit} units")
        potentials = canonical_engineering_identities(
            self.surface_potential_ids,
            "surface_potential_ids",
        )
        if self.requires_electrical_isolation and not potentials:
            raise ValueError("isolating interfaces require surface-potential identities")
        bindings = canonical_engineering_identities(
            self.source_binding_ids,
            "source_binding_ids",
        )
        if not bindings:
            raise ValueError("cooling interfaces require source context")
        notes = tuple(require_engineering_identity(note, "notes") for note in self.notes)
        object.__setattr__(self, "surface_potential_ids", potentials)
        object.__setattr__(self, "source_binding_ids", bindings)
        object.__setattr__(self, "notes", notes)
        return self


class CoolingAssemblyProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-cooling-assembly-profile"] = "pcbsmith-cooling-assembly-profile"
    schema_version: Literal[1] = 1
    profile_id: str
    revision: str
    geometry_authority_sha256: str | None
    parts: tuple[CoolingPart, ...]
    interfaces: tuple[CoolingInterface, ...]
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_canonical(self) -> Self:
        require_engineering_identity(self.profile_id, "profile_id")
        require_engineering_identity(self.revision, "revision")
        if self.geometry_authority_sha256 is not None and (
            len(self.geometry_authority_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in self.geometry_authority_sha256
            )
        ):
            raise ValueError("geometry authority must be a lowercase SHA-256 digest")
        parts = tuple(sorted(self.parts, key=lambda item: item.part_id))
        interfaces = tuple(sorted(self.interfaces, key=lambda item: item.interface_id))
        if len(parts) != len({item.part_id for item in parts}):
            raise ValueError("cooling part identities must be unique")
        if len(interfaces) != len({item.interface_id for item in interfaces}):
            raise ValueError("cooling interface identities must be unique")
        part_ids = {item.part_id for item in parts}
        if any(
            item.part_a_id not in part_ids or item.part_b_id not in part_ids for item in interfaces
        ):
            raise ValueError("cooling interface references an unknown part")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("cooling assembly requires source context")
        object.__setattr__(self, "parts", parts)
        object.__setattr__(self, "interfaces", interfaces)
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class CoolingAssemblyRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-cooling-assembly-requirement"] = (
        "pcbsmith-cooling-assembly-requirement"
    )
    schema_version: Literal[1] = 1
    requirement_id: str
    role: CoolingPartRole
    minimum_parts: int
    accepted_selection_states: tuple[CoolingSelectionState, ...]
    required_property_ids: tuple[str, ...]
    rationale: str

    @model_validator(mode="after")
    def requirement_is_coherent(self) -> Self:
        require_engineering_identity(self.requirement_id, "requirement_id")
        require_engineering_identity(self.rationale, "rationale")
        if self.minimum_parts < 1:
            raise ValueError("cooling requirement minimum_parts must be positive")
        states = tuple(sorted(set(self.accepted_selection_states), key=lambda item: item.value))
        if not states:
            raise ValueError("cooling requirement needs accepted selection states")
        properties = canonical_engineering_identities(
            self.required_property_ids,
            "required_property_ids",
        )
        object.__setattr__(self, "accepted_selection_states", states)
        object.__setattr__(self, "required_property_ids", properties)
        return self


class CoolingAssemblyEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-cooling-assembly-evaluation"] = (
        "pcbsmith-cooling-assembly-evaluation"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["complete", "incomplete"]
    satisfied_requirement_ids: tuple[str, ...]
    unsatisfied_requirement_ids: tuple[str, ...]
    incomplete_interface_ids: tuple[str, ...]
    findings: tuple[str, ...]


class CoolingPartCandidate(SemanticIrModel):
    """A sourced candidate that is deliberately not an approved selection."""

    schema_id: Literal["pcbsmith-cooling-part-candidate"] = (
        "pcbsmith-cooling-part-candidate"
    )
    schema_version: Literal[1] = 1
    candidate_id: str
    roles: tuple[CoolingPartRole, ...]
    manufacturer: str
    ordering_identity: str
    configuration: str
    status: CoolingCandidateStatus
    properties: tuple[BoundedQuantity, ...]
    source_binding_ids: tuple[str, ...]
    applicability_notes: tuple[str, ...]

    @model_validator(mode="after")
    def candidate_is_coherent(self) -> Self:
        for field_name in (
            "candidate_id",
            "manufacturer",
            "ordering_identity",
            "configuration",
        ):
            require_engineering_identity(getattr(self, field_name), field_name)
        roles = tuple(sorted(set(self.roles), key=lambda item: item.value))
        if not roles:
            raise ValueError("cooling candidates require at least one role")
        properties = tuple(sorted(self.properties, key=lambda item: item.quantity_id))
        if len(properties) != len({item.quantity_id for item in properties}):
            raise ValueError("cooling-candidate property identities must be unique")
        bindings = canonical_engineering_identities(
            self.source_binding_ids,
            "source_binding_ids",
        )
        if not bindings:
            raise ValueError("cooling candidates require source context")
        notes = tuple(
            require_engineering_identity(note, "applicability_notes")
            for note in self.applicability_notes
        )
        if not notes:
            raise ValueError("cooling candidates require applicability notes")
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "properties", properties)
        object.__setattr__(self, "source_binding_ids", bindings)
        object.__setattr__(self, "applicability_notes", notes)
        return self


class CoolingCandidateRegister(SemanticIrModel):
    schema_id: Literal["pcbsmith-cooling-candidate-register"] = (
        "pcbsmith-cooling-candidate-register"
    )
    schema_version: Literal[1] = 1
    register_id: str
    revision: str
    candidates: tuple[CoolingPartCandidate, ...]
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def register_is_canonical(self) -> Self:
        require_engineering_identity(self.register_id, "register_id")
        require_engineering_identity(self.revision, "revision")
        candidates = tuple(sorted(self.candidates, key=lambda item: item.candidate_id))
        if len(candidates) != len({item.candidate_id for item in candidates}):
            raise ValueError("cooling candidate identities must be unique")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("cooling candidate registers require source context")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class CoolingCandidateEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-cooling-candidate-evaluation"] = (
        "pcbsmith-cooling-candidate-evaluation"
    )
    schema_version: Literal[1] = 1
    register_id: str
    register_fingerprint: str
    disposition: Literal["candidates_available", "incomplete", "no_candidates"]
    covered_role_ids: tuple[CoolingPartRole, ...]
    uncovered_role_ids: tuple[CoolingPartRole, ...]
    blocked_candidate_ids: tuple[str, ...]
    findings: tuple[str, ...]


def evaluate_cooling_assembly(
    profile: CoolingAssemblyProfile,
    requirements: tuple[CoolingAssemblyRequirement, ...],
) -> CoolingAssemblyEvaluation:
    ordered = tuple(sorted(requirements, key=lambda item: item.requirement_id))
    if len(ordered) != len({item.requirement_id for item in ordered}):
        raise ValueError("cooling requirement identities must be unique")
    satisfied: list[str] = []
    unsatisfied: list[str] = []
    findings: list[str] = []
    for requirement in ordered:
        candidates = tuple(item for item in profile.parts if item.role is requirement.role)
        complete = []
        for part in candidates:
            missing = tuple(
                property_id
                for property_id in requirement.required_property_ids
                if (quantity := part.property(property_id)) is None or not quantity.is_known
            )
            if part.selection_state not in requirement.accepted_selection_states:
                findings.append(
                    f"{part.part_id}: selection state {part.selection_state.value} is not accepted"
                )
            elif missing:
                findings.append(f"{part.part_id}: unresolved properties: {', '.join(missing)}")
            else:
                complete.append(part.part_id)
        if len(complete) >= requirement.minimum_parts:
            satisfied.append(requirement.requirement_id)
        else:
            unsatisfied.append(requirement.requirement_id)
            findings.append(
                f"{requirement.requirement_id}: {len(complete)} complete part(s); "
                f"{requirement.minimum_parts} required"
            )

    incomplete_interfaces: list[str] = []
    for interface in profile.interfaces:
        interface_missing: list[str] = []
        for quantity in (
            interface.contact_area,
            interface.thermal_resistance,
            interface.clamp_force,
        ):
            if not quantity.is_known:
                interface_missing.append(quantity.quantity_id)
        if interface.requires_electrical_isolation and not interface.isolation_withstand.is_known:
            interface_missing.append(interface.isolation_withstand.quantity_id)
        if interface_missing:
            incomplete_interfaces.append(interface.interface_id)
            findings.append(
                f"{interface.interface_id}: unresolved interface quantities: "
                + ", ".join(interface_missing)
            )
    if profile.geometry_authority_sha256 is None:
        findings.append("Cooling assembly has no pinned board-geometry authority hash.")
    assembly_complete = (
        not unsatisfied
        and not incomplete_interfaces
        and (profile.geometry_authority_sha256 is not None)
    )
    return CoolingAssemblyEvaluation(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition="complete" if assembly_complete else "incomplete",
        satisfied_requirement_ids=tuple(satisfied),
        unsatisfied_requirement_ids=tuple(unsatisfied),
        incomplete_interface_ids=tuple(sorted(incomplete_interfaces)),
        findings=tuple(findings),
    )


def evaluate_cooling_candidates(
    register: CoolingCandidateRegister,
    required_roles: tuple[CoolingPartRole, ...],
) -> CoolingCandidateEvaluation:
    """Report candidate coverage without promoting candidates into selections."""

    required = tuple(sorted(set(required_roles), key=lambda item: item.value))
    if not required:
        raise ValueError("candidate evaluation requires at least one cooling role")
    covered = tuple(
        role
        for role in required
        if any(
            role in candidate.roles and candidate.status is not CoolingCandidateStatus.REJECTED
            for candidate in register.candidates
        )
    )
    uncovered = tuple(role for role in required if role not in covered)
    blocked = tuple(
        candidate.candidate_id
        for candidate in register.candidates
        if candidate.status
        in {
            CoolingCandidateStatus.VENDOR_CONFIRMATION_REQUIRED,
            CoolingCandidateStatus.SYSTEM_VALIDATION_REQUIRED,
            CoolingCandidateStatus.REJECTED,
        }
    )
    findings = [
        "Candidate coverage does not satisfy cooling-assembly selection requirements."
    ]
    findings.extend(
        f"{candidate.candidate_id}: {candidate.status.value}"
        for candidate in register.candidates
        if candidate.candidate_id in blocked
    )
    findings.extend(f"No non-rejected candidate covers {role.value}." for role in uncovered)
    if not register.candidates:
        disposition: Literal["candidates_available", "incomplete", "no_candidates"] = (
            "no_candidates"
        )
    elif uncovered:
        disposition = "incomplete"
    else:
        disposition = "candidates_available"
    return CoolingCandidateEvaluation(
        register_id=register.register_id,
        register_fingerprint=register.semantic_fingerprint(),
        disposition=disposition,
        covered_role_ids=covered,
        uncovered_role_ids=uncovered,
        blocked_candidate_ids=blocked,
        findings=tuple(findings),
    )
