"""Non-selecting gate-driver package and pin-migration authority."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.engineering_quantity_ir import (
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.semantic_ir import SemanticIrModel


class MigrationDisposition(StrEnum):
    RETAINED = "retained"
    REMAPPED = "remapped"
    NEW_REQUIRED = "new_required"
    RETIRED = "retired"
    BEHAVIOR_REVIEW = "behavior_review"


class GateDriverPackageCandidate(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-driver-package-candidate"] = (
        "pcbsmith-gate-driver-package-candidate"
    )
    schema_version: Literal[1] = 1
    candidate_id: str
    orderable_part_number: str
    manufacturer_status: str
    package_code: str
    package_style: str
    signal_pin_count: int
    thermal_pad_pin_number: int
    body_width_mm: Decimal
    body_height_mm: Decimal
    pin_pitch_mm: Decimal
    proposed_footprint_id: str
    proposed_3d_model_id: str
    footprint_sha256: str
    model_sha256: str
    asset_compatibility_state: Literal["geometry_candidate"] = "geometry_candidate"
    source_binding_ids: tuple[str, ...]
    selection_state: Literal["not_selected"] = "not_selected"

    @model_validator(mode="after")
    def candidate_is_coherent(self) -> Self:
        for field_name in (
            "candidate_id",
            "orderable_part_number",
            "manufacturer_status",
            "package_code",
            "package_style",
            "proposed_footprint_id",
            "proposed_3d_model_id",
            "footprint_sha256",
            "model_sha256",
        ):
            require_engineering_identity(getattr(self, field_name), field_name)
        for field_name in ("footprint_sha256", "model_sha256"):
            value = getattr(self, field_name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        if self.signal_pin_count <= 0:
            raise ValueError("signal pin count must be positive")
        if self.thermal_pad_pin_number <= self.signal_pin_count:
            raise ValueError("thermal-pad pin must follow signal pins")
        for value in (self.body_width_mm, self.body_height_mm, self.pin_pitch_mm):
            if not value.is_finite() or value <= 0:
                raise ValueError("package dimensions must be finite and positive")
        sources = canonical_engineering_identities(
            self.source_binding_ids,
            "source_binding_ids",
        )
        if not sources:
            raise ValueError("package candidates require source bindings")
        object.__setattr__(self, "source_binding_ids", sources)
        return self


class GateDriverPinAssignment(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-driver-pin-assignment"] = (
        "pcbsmith-gate-driver-pin-assignment"
    )
    schema_version: Literal[1] = 1
    pin_number: int
    function_id: str
    proposed_net_id: str
    disposition: MigrationDisposition
    source_binding_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def assignment_is_coherent(self) -> Self:
        if self.pin_number <= 0:
            raise ValueError("pin numbers must be positive")
        require_engineering_identity(self.function_id, "function_id")
        require_engineering_identity(self.proposed_net_id, "proposed_net_id")
        sources = canonical_engineering_identities(
            self.source_binding_ids,
            "source_binding_ids",
        )
        if not sources:
            raise ValueError("pin assignments require source bindings")
        notes = tuple(require_engineering_identity(note, "notes") for note in self.notes)
        object.__setattr__(self, "source_binding_ids", sources)
        object.__setattr__(self, "notes", notes)
        return self


class GateDriverFunctionMigration(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-driver-function-migration"] = (
        "pcbsmith-gate-driver-function-migration"
    )
    schema_version: Literal[1] = 1
    function_group_id: str
    disposition: MigrationDisposition
    source_function_ids: tuple[str, ...]
    target_function_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...] = ()
    notes: tuple[str, ...]

    @model_validator(mode="after")
    def migration_is_coherent(self) -> Self:
        require_engineering_identity(self.function_group_id, "function_group_id")
        for field_name in (
            "source_function_ids",
            "target_function_ids",
            "obligation_ids",
        ):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, values)
        if self.disposition is MigrationDisposition.NEW_REQUIRED and self.source_function_ids:
            raise ValueError("new functions cannot claim source functions")
        if self.disposition is MigrationDisposition.RETIRED and self.target_function_ids:
            raise ValueError("retired functions cannot claim target functions")
        notes = tuple(require_engineering_identity(note, "notes") for note in self.notes)
        if not notes:
            raise ValueError("function migrations require rationale")
        object.__setattr__(self, "notes", notes)
        return self


class GateDriverMigrationProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-driver-migration-profile"] = (
        "pcbsmith-gate-driver-migration-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    revision: str
    current_part_id: str
    current_package_body_width_mm: Decimal
    current_package_body_height_mm: Decimal
    candidate: GateDriverPackageCandidate
    pin_assignments: tuple[GateDriverPinAssignment, ...]
    function_migrations: tuple[GateDriverFunctionMigration, ...]
    required_function_group_ids: tuple[str, ...]
    unresolved_authority_ids: tuple[str, ...]
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_coherent(self) -> Self:
        for field_name in ("profile_id", "revision", "current_part_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        for value in (
            self.current_package_body_width_mm,
            self.current_package_body_height_mm,
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError("current package dimensions must be finite and positive")
        pin_numbers = tuple(item.pin_number for item in self.pin_assignments)
        if len(pin_numbers) != len(set(pin_numbers)):
            raise ValueError("target pin assignments must be unique")
        groups = tuple(item.function_group_id for item in self.function_migrations)
        if len(groups) != len(set(groups)):
            raise ValueError("function migration groups must be unique")
        for field_name in (
            "required_function_group_ids",
            "unresolved_authority_ids",
            "source_binding_ids",
        ):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, values)
        if not self.source_binding_ids:
            raise ValueError("migration profiles require source context")
        return self


class GateDriverMigrationReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-gate-driver-migration-report"] = (
        "pcbsmith-gate-driver-migration-report"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    profile_fingerprint: str
    disposition: Literal["blocked", "conditional_candidate", "implementation_ready"]
    selection_state: Literal["not_selected"] = "not_selected"
    pin_map_complete: bool
    missing_pin_numbers: tuple[int, ...]
    missing_function_group_ids: tuple[str, ...]
    unresolved_authority_ids: tuple[str, ...]
    signal_pin_count_increase: int
    body_area_growth_ratio: Decimal
    proposed_footprint_id: str
    proposed_3d_model_id: str
    asset_compatibility_state: Literal["geometry_candidate"]
    findings: tuple[str, ...]


def evaluate_gate_driver_migration(
    profile: GateDriverMigrationProfile,
) -> GateDriverMigrationReport:
    """Check migration completeness without selecting or changing the schematic."""

    candidate = profile.candidate
    expected_pins = set(range(1, candidate.signal_pin_count + 1)) | {
        candidate.thermal_pad_pin_number
    }
    assigned_pins = {item.pin_number for item in profile.pin_assignments}
    extra_pins = assigned_pins - expected_pins
    if extra_pins:
        raise ValueError(f"target pin map contains unexpected pins: {sorted(extra_pins)}")
    missing_pins = tuple(sorted(expected_pins - assigned_pins))
    mapped_groups = {item.function_group_id for item in profile.function_migrations}
    missing_groups = tuple(sorted(set(profile.required_function_group_ids) - mapped_groups))
    if missing_pins or missing_groups:
        disposition: Literal["blocked", "conditional_candidate", "implementation_ready"] = "blocked"
    elif profile.unresolved_authority_ids:
        disposition = "conditional_candidate"
    else:
        disposition = "implementation_ready"
    current_area = profile.current_package_body_width_mm * profile.current_package_body_height_mm
    target_area = candidate.body_width_mm * candidate.body_height_mm
    return GateDriverMigrationReport(
        profile_id=profile.profile_id,
        profile_fingerprint=profile.semantic_fingerprint(),
        disposition=disposition,
        pin_map_complete=not missing_pins,
        missing_pin_numbers=missing_pins,
        missing_function_group_ids=missing_groups,
        unresolved_authority_ids=profile.unresolved_authority_ids,
        signal_pin_count_increase=candidate.signal_pin_count - 40,
        body_area_growth_ratio=(target_area / current_area) - Decimal(1),
        proposed_footprint_id=candidate.proposed_footprint_id,
        proposed_3d_model_id=candidate.proposed_3d_model_id,
        asset_compatibility_state=candidate.asset_compatibility_state,
        findings=(
            "The reviewed candidate is not pin compatible with the retained driver.",
            "A complete proposed pin map is analysis evidence, not schematic selection.",
            "Bootstrap, charge-pump, decoupling, layout, firmware, and protection "
            "obligations remain redesign work.",
        ),
    )
