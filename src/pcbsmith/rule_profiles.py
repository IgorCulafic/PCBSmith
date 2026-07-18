"""Typed rule profiles separating fabrication from safety coordination.

The legacy KiCad geometry values remain available as an explicit compatibility
profile. They are project defaults, not universal statements about a fabricator
or an insulation standard. Safety requirements can become executable only after
the complete application context and qualified evidence are recorded.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.circuit.models import EvidenceRef

ProfileBasis = Literal[
    "legacy_compatibility",
    "manufacturer_capability",
    "manufacturer_design_target",
    "project_requirement",
]
InsulationStatus = Literal["not_applicable", "incomplete", "review_required", "qualified"]
OuterCopperMaskState = Literal[
    "masked",
    "partially_exposed",
    "fully_exposed",
    "unknown",
]
CopperRole = Literal[
    "component_termination",
    "routed_conductor",
    "via_land",
    "copper_pour",
    "board_copper_graphic",
    "unknown",
]


class OrdinaryClearanceRequirement(BaseModel):
    """Declared ordinary pairwise spacing; it is never inferred from voltage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: str = Field(min_length=1)
    nets_a: tuple[str, ...] = Field(min_length=1)
    nets_b: tuple[str, ...] = Field(min_length=1)
    minimum_clearance_mm: float = Field(gt=0)
    mask_states_a: tuple[OuterCopperMaskState, ...] = ()
    mask_states_b: tuple[OuterCopperMaskState, ...] = ()
    roles_a: tuple[CopperRole, ...] = ()
    roles_b: tuple[CopperRole, ...] = ()
    exempt_component_refs: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def net_groups_are_disjoint(self) -> Self:
        overlap = set(self.nets_a) & set(self.nets_b)
        if overlap:
            raise ValueError("ordinary clearance net groups overlap: " + ", ".join(sorted(overlap)))
        return self


class FabricationGeometryProfile(BaseModel):
    """Manufacturing geometry, independent of electrical insulation safety."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    basis: ProfileBasis = "legacy_compatibility"
    manufacturer_process_id: str | None = None
    minimum_trace_width_mm: float = Field(default=0.2, gt=0)
    default_signal_trace_width_mm: float = Field(default=0.3, gt=0)
    default_power_trace_width_mm: float = Field(default=0.8, gt=0)
    routing_via_diameter_mm: float = Field(default=0.6, gt=0)
    routing_via_drill_mm: float = Field(default=0.3, gt=0)
    power_via_diameter_mm: float = Field(default=0.8, gt=0)
    power_via_drill_mm: float = Field(default=0.4, gt=0)
    board_thickness_mm: float = Field(default=1.6, gt=0)
    copper_layer_count: int = Field(default=2, ge=1)
    outer_copper_thickness_um: float = Field(default=35.0, gt=0)
    inner_copper_thickness_um: float | None = Field(default=None, gt=0)
    substrate_description: str = Field(default="FR-4", min_length=1)
    trace_thermal_model_id: Literal[
        "legacy_ipc_2221a_external_fit", "profile_table", "not_declared"
    ] = "legacy_ipc_2221a_external_fit"
    trace_temperature_rise_c: float = Field(default=10.0, gt=0)
    minimum_finished_hole_mm: float | None = Field(default=None, gt=0)
    minimum_annular_ring_mm: float | None = Field(default=None, gt=0)
    minimum_hole_to_hole_web_mm: float | None = Field(default=None, gt=0)
    default_pad_solder_mask_expansion_mm: float | None = Field(default=None, allow_inf_nan=False)
    minimum_solder_mask_web_mm: float | None = Field(default=None, gt=0)
    minimum_component_body_to_edge_mm: float | None = Field(default=None, gt=0)
    evidence: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def via_diameter_exceeds_drill(self) -> Self:
        if self.routing_via_diameter_mm <= self.routing_via_drill_mm:
            raise ValueError("routing via diameter must exceed its drill diameter")
        if self.power_via_diameter_mm <= self.power_via_drill_mm:
            raise ValueError("power via diameter must exceed its drill diameter")
        if (
            self.default_signal_trace_width_mm < self.minimum_trace_width_mm
            or self.default_power_trace_width_mm < self.minimum_trace_width_mm
        ):
            raise ValueError("default trace widths cannot be below the minimum")
        if self.minimum_finished_hole_mm is not None:
            if self.routing_via_drill_mm < self.minimum_finished_hole_mm:
                raise ValueError("routing via drill is below the minimum finished hole")
            if self.power_via_drill_mm < self.minimum_finished_hole_mm:
                raise ValueError("power via drill is below the minimum finished hole")
        if self.minimum_annular_ring_mm is not None:
            routing_ring = (self.routing_via_diameter_mm - self.routing_via_drill_mm) / 2
            power_ring = (self.power_via_diameter_mm - self.power_via_drill_mm) / 2
            if min(routing_ring, power_ring) < self.minimum_annular_ring_mm:
                raise ValueError("generated via annular ring is below the minimum")
        return self


class FabElectricalSpacingProfile(BaseModel):
    """Ordinary PCB production spacing; never an insulation-safety lookup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    basis: ProfileBasis = "legacy_compatibility"
    manufacturer_process_id: str | None = None
    minimum_copper_clearance_mm: float = Field(default=0.2, gt=0)
    minimum_copper_to_edge_mm: float = Field(default=0.5, gt=0)
    minimum_hole_to_copper_mm: float = Field(default=0.25, gt=0)
    pairwise_clearances: tuple[OrdinaryClearanceRequirement, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()


class StandardEditionRef(BaseModel):
    """Identified standard edition with evidence locators."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: str = Field(min_length=1)
    edition: str = Field(min_length=1)
    amendments: tuple[str, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()


class InsulationBarrier(BaseModel):
    """Reviewed result for one insulation boundary; no lookup is performed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    barrier_id: str = Field(min_length=1)
    nets_a: tuple[str, ...] = Field(min_length=1)
    nets_b: tuple[str, ...] = Field(min_length=1)
    insulation_type: Literal["functional", "basic", "supplementary", "double", "reinforced"]
    working_voltage_rms_v: float | None = Field(default=None, ge=0)
    working_voltage_peak_v: float | None = Field(default=None, ge=0)
    temporary_overvoltage_v: float | None = Field(default=None, ge=0)
    rated_impulse_voltage_v: float | None = Field(default=None, ge=0)
    maximum_working_frequency_hz: float | None = Field(default=None, gt=0)
    required_clearance_mm: float | None = Field(default=None, gt=0)
    required_creepage_mm: float | None = Field(default=None, gt=0)
    clearance_path_ids: tuple[str, ...] = ()
    creepage_path_ids: tuple[str, ...] = ()
    exempt_component_refs: tuple[str, ...] = ()
    derivation_rule_ids: tuple[str, ...] = ()
    high_frequency_basis_rule_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def barrier_geometry_and_groups_are_coherent(self) -> Self:
        overlap = set(self.nets_a) & set(self.nets_b)
        if overlap:
            raise ValueError("insulation barrier net groups overlap: " + ", ".join(sorted(overlap)))
        if (
            self.required_clearance_mm is not None
            and self.required_creepage_mm is not None
            and self.required_creepage_mm < self.required_clearance_mm
        ):
            raise ValueError("required creepage cannot be below required clearance")
        return self


class QualifiedInsulationReview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["needs_human_review", "qualified_review_complete"] = "needs_human_review"
    reviewer: str | None = None
    review_record_id: str | None = None
    reviewed_on: date | None = None


class InsulationProfile(BaseModel):
    """Complete application context and reviewed results for safety spacing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    status: InsulationStatus = "incomplete"
    product_standard: StandardEditionRef | None = None
    coordination_standards: tuple[StandardEditionRef, ...] = ()
    overvoltage_category: Literal["I", "II", "III", "IV", "not_applicable", "unknown"] = "unknown"
    pollution_degree: int | None = Field(default=None, ge=1, le=4)
    material_group: Literal["I", "II", "IIIa", "IIIb"] | None = None
    minimum_cti_v: float | None = Field(default=None, ge=0)
    maximum_altitude_m: float | None = Field(default=None, ge=0)
    field_case: Literal["inhomogeneous", "homogeneous", "unknown"] = "unknown"
    protection_regime: Literal[
        "none", "conformal_coating", "encapsulation", "potting", "other", "unknown"
    ] = "unknown"
    protection_qualification_rule_ids: tuple[str, ...] = ()
    barriers: tuple[InsulationBarrier, ...] = ()
    review: QualifiedInsulationReview = QualifiedInsulationReview()

    def missing_qualification_context(self) -> tuple[str, ...]:
        missing: list[str] = []
        for name in (
            "product_standard",
            "pollution_degree",
            "material_group",
            "minimum_cti_v",
            "maximum_altitude_m",
        ):
            if getattr(self, name) is None:
                missing.append(name)
        if self.overvoltage_category == "unknown":
            missing.append("overvoltage_category")
        if self.field_case == "unknown":
            missing.append("field_case")
        if self.protection_regime == "unknown":
            missing.append("protection_regime")
        if not self.coordination_standards:
            missing.append("coordination_standards")
        if not self.barriers:
            missing.append("barriers")
        if self.review.status != "qualified_review_complete":
            missing.append("qualified_review")
        elif not (
            self.review.reviewer and self.review.review_record_id and self.review.reviewed_on
        ):
            missing.append("qualified_review_identity")
        return tuple(missing)

    @model_validator(mode="after")
    def qualified_profiles_close_every_gate(self) -> Self:
        if self.status != "qualified":
            return self
        missing = self.missing_qualification_context()
        if missing:
            raise ValueError("qualified insulation profile is missing: " + ", ".join(missing))
        if self.protection_regime != "none" and not self.protection_qualification_rule_ids:
            raise ValueError(
                "qualified insulation profile credits protection without qualification rules"
            )
        standards = (self.product_standard, *self.coordination_standards)
        for standard in standards:
            if standard is None:
                continue
            if not any(
                item.source_status == "pinned"
                and item.local_sha256 is not None
                and len(item.local_sha256) == 64
                and all(char in "0123456789abcdefABCDEF" for char in item.local_sha256)
                and item.locator_status in {"text_verified", "figure_verified"}
                and item.applicability_status == "confirmed"
                for item in standard.evidence
            ):
                raise ValueError(
                    "qualified insulation standard "
                    f"{standard.identifier} requires checksum-pinned, "
                    "verified, applicability-confirmed evidence"
                )
        for barrier in self.barriers:
            barrier_missing = [
                name
                for name in (
                    "working_voltage_rms_v",
                    "working_voltage_peak_v",
                    "temporary_overvoltage_v",
                    "rated_impulse_voltage_v",
                    "maximum_working_frequency_hz",
                    "required_clearance_mm",
                    "required_creepage_mm",
                )
                if getattr(barrier, name) is None
            ]
            if not barrier.clearance_path_ids:
                barrier_missing.append("clearance_path_ids")
            if not barrier.creepage_path_ids:
                barrier_missing.append("creepage_path_ids")
            if not barrier.derivation_rule_ids:
                barrier_missing.append("derivation_rule_ids")
            if barrier_missing:
                raise ValueError(
                    f"qualified barrier {barrier.barrier_id} is missing: "
                    + ", ".join(barrier_missing)
                )
            frequency = barrier.maximum_working_frequency_hz or 0.0
            if frequency > 30_000 and not barrier.high_frequency_basis_rule_ids:
                raise ValueError(
                    f"qualified barrier {barrier.barrier_id} above 30 kHz "
                    "requires a high-frequency basis"
                )
        return self


class PcbRuleProfile(BaseModel):
    """One explicit bundle consumed by geometry, routing, and review stages."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    geometry: FabricationGeometryProfile
    fab_spacing: FabElectricalSpacingProfile
    insulation: InsulationProfile


DEFAULT_PCB_RULE_PROFILE = PcbRuleProfile(
    profile_id="pcbsmith-legacy-default-v1",
    geometry=FabricationGeometryProfile(profile_id="legacy-kicad-geometry-v1"),
    fab_spacing=FabElectricalSpacingProfile(profile_id="legacy-kicad-spacing-v1"),
    insulation=InsulationProfile(
        profile_id="ordinary-low-voltage-unspecified-v1",
        status="not_applicable",
    ),
)


QualifiedInsulationClearanceGroup = tuple[
    str,
    tuple[str, ...],
    tuple[str, ...],
    float,
    tuple[str, ...],
]


def qualified_insulation_clearance_groups(
    profile: PcbRuleProfile,
) -> tuple[QualifiedInsulationClearanceGroup, ...]:
    """Executable air-clearance constraints from a completed safety review.

    Review-only and incomplete profiles intentionally produce no constraints.
    Creepage is excluded because it requires explicit surface-path geometry.
    """
    if profile.insulation.status != "qualified":
        return ()
    return tuple(
        (
            barrier.barrier_id,
            barrier.nets_a,
            barrier.nets_b,
            barrier.required_clearance_mm,
            barrier.exempt_component_refs,
        )
        for barrier in profile.insulation.barriers
        if barrier.required_clearance_mm is not None
    )
