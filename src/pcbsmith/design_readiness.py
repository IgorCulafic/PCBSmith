"""Fail-closed design-readiness contracts exposed by candidate review failures.

This module deliberately sits above individual component and layout evaluators.
It does not replace datasheet evidence, DRC, model preflight, or the existing
iterative-fixing graph.  It closes the workflow gaps between those authorities:

* functional intent is recorded before a component/package is selected;
* mandatory support circuits are covered by evidence, not merely connected;
* source, inrush, conversion, rail-load, and thermal claims form one power path;
* required visual subjects must be measurably present in declared crops;
* release language follows explicit automatic and human gate states; and
* small changes invalidate a declared downstream scope instead of the whole board.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from enum import StrEnum
from pathlib import Path
from statistics import median
from typing import Any, Literal, Self, cast

from pydantic import Field, model_validator

from pcbsmith.kicad.model_preflight import ModelPreflightReport
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class ReadinessDisposition(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    UNVERIFIED = "unverified"


class ComponentUseIntent(SemanticIrModel):
    intent_id: str
    role_id: str
    required_capabilities: tuple[str, ...] = Field(min_length=1)
    forbidden_capabilities: tuple[str, ...] = ()
    preferred_mounting: Literal["smd", "through_hole", "either"] = "smd"
    hand_assembly_required: bool = False
    maximum_body_width_mm: float | None = Field(default=None, gt=0)
    maximum_body_height_mm: float | None = Field(default=None, gt=0)
    maximum_pin_count: int | None = Field(default=None, ge=2)
    maximum_unit_current_a: float | None = Field(default=None, ge=0)
    require_minimal_behavioral_scope: bool = True
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def intent_is_canonical(self) -> Self:
        require_identity(self.intent_id, "intent_id")
        require_identity(self.role_id, "role_id")
        for name in ("required_capabilities", "forbidden_capabilities", "evidence_ids"):
            values = tuple(sorted(require_identity(item, name) for item in getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique identities")
            object.__setattr__(self, name, values)
        overlap = set(self.required_capabilities) & set(self.forbidden_capabilities)
        if overlap:
            raise ValueError("required and forbidden capabilities overlap")
        return self


class ComponentCandidate(SemanticIrModel):
    candidate_id: str
    manufacturer_part_number: str
    capabilities: tuple[str, ...] = Field(min_length=1)
    behavioral_capabilities: tuple[str, ...] = ()
    mounting: Literal["smd", "through_hole"]
    body_width_mm: float = Field(gt=0)
    body_height_mm: float = Field(gt=0)
    pin_count: int = Field(ge=2)
    maximum_unit_current_a: float = Field(ge=0)
    hand_assembly_suitable: bool
    model_classification: Literal[
        "exact_package", "complete_module", "connector_only", "proxy", "unknown", "none"
    ] = "unknown"
    support_requirement_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def candidate_is_canonical(self) -> Self:
        require_identity(self.candidate_id, "candidate_id")
        require_identity(self.manufacturer_part_number, "manufacturer_part_number")
        for name in (
            "capabilities",
            "behavioral_capabilities",
            "support_requirement_ids",
            "evidence_ids",
        ):
            values = tuple(sorted(require_identity(item, name) for item in getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique identities")
            object.__setattr__(self, name, values)
        if not set(self.behavioral_capabilities).issubset(self.capabilities):
            raise ValueError("behavioral capabilities must be included in capabilities")
        return self


class ComponentCandidateAssessment(SemanticIrModel):
    candidate_id: str
    compatible: bool
    rank: int = Field(ge=1)
    blockers: tuple[str, ...]
    additional_behavioral_capabilities: tuple[str, ...]
    comparison_key: tuple[int, int, float, int, float, int, str]


class ComponentAlternativeReview(SemanticIrModel):
    schema_id: Literal["pcbsmith-component-alternative-review-v1"] = (
        "pcbsmith-component-alternative-review-v1"
    )
    intent: ComponentUseIntent
    candidates: tuple[ComponentCandidate, ...] = Field(min_length=2)
    selected_candidate_id: str
    assessments: tuple[ComponentCandidateAssessment, ...]
    recommended_candidate_id: str | None
    disposition: ReadinessDisposition
    blockers: tuple[str, ...]
    review_fingerprint: str

    @model_validator(mode="after")
    def review_is_replay_bound(self) -> Self:
        require_sha256(self.review_fingerprint, "review_fingerprint")
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("component candidates must have unique identities")
        if self.selected_candidate_id not in set(candidate_ids):
            raise ValueError("selected component candidate is absent")
        if {item.candidate_id for item in self.assessments} != set(candidate_ids):
            raise ValueError("component assessment coverage is incomplete")
        payload = self.model_dump(mode="json", exclude={"review_fingerprint"})
        if self.review_fingerprint != fingerprint(payload):
            raise ValueError("component alternative review fingerprint is stale")
        return self


def review_component_alternatives(
    *,
    intent: ComponentUseIntent,
    candidates: tuple[ComponentCandidate, ...],
    selected_candidate_id: str,
) -> ComponentAlternativeReview:
    if len(candidates) < 2:
        raise ValueError("component selection requires at least two alternatives")
    if selected_candidate_id not in {item.candidate_id for item in candidates}:
        raise ValueError("selected component candidate is absent")
    raw: list[tuple[ComponentCandidate, tuple[str, ...], tuple[str, ...], tuple[Any, ...]]] = []
    for candidate in candidates:
        blockers: list[str] = []
        missing = set(intent.required_capabilities) - set(candidate.capabilities)
        forbidden = set(intent.forbidden_capabilities) & set(candidate.capabilities)
        blockers.extend(f"missing_capability:{item}" for item in sorted(missing))
        blockers.extend(f"forbidden_capability:{item}" for item in sorted(forbidden))
        if (
            intent.preferred_mounting != "either"
            and candidate.mounting != intent.preferred_mounting
        ):
            blockers.append("mounting_style_mismatch")
        if intent.hand_assembly_required and not candidate.hand_assembly_suitable:
            blockers.append("hand_assembly_unsuitable")
        if (
            intent.maximum_body_width_mm is not None
            and candidate.body_width_mm > intent.maximum_body_width_mm
        ):
            blockers.append("body_width_exceeds_intent")
        if (
            intent.maximum_body_height_mm is not None
            and candidate.body_height_mm > intent.maximum_body_height_mm
        ):
            blockers.append("body_height_exceeds_intent")
        if intent.maximum_pin_count is not None and candidate.pin_count > intent.maximum_pin_count:
            blockers.append("pin_count_exceeds_intent")
        if (
            intent.maximum_unit_current_a is not None
            and candidate.maximum_unit_current_a > intent.maximum_unit_current_a
        ):
            blockers.append("unit_current_exceeds_intent")
        additional = tuple(
            sorted(set(candidate.behavioral_capabilities) - set(intent.required_capabilities))
        )
        model_rank = {
            "exact_package": 0,
            "complete_module": 0,
            "connector_only": 1,
            "proxy": 2,
            "unknown": 3,
            "none": 4,
        }[candidate.model_classification]
        comparison_key = (
            len(blockers),
            len(additional) if intent.require_minimal_behavioral_scope else 0,
            candidate.body_width_mm * candidate.body_height_mm,
            candidate.pin_count,
            candidate.maximum_unit_current_a,
            model_rank,
            candidate.candidate_id,
        )
        raw.append((candidate, tuple(blockers), additional, comparison_key))
    ordered = sorted(raw, key=lambda item: item[3])
    rank_by_id = {item[0].candidate_id: rank for rank, item in enumerate(ordered, start=1)}
    assessments = tuple(
        ComponentCandidateAssessment(
            candidate_id=candidate.candidate_id,
            compatible=not blockers,
            rank=rank_by_id[candidate.candidate_id],
            blockers=blockers,
            additional_behavioral_capabilities=additional,
            comparison_key=key,
        )
        for candidate, blockers, additional, key in sorted(
            raw, key=lambda item: item[0].candidate_id
        )
    )
    compatible = tuple(item for item in assessments if item.compatible)
    recommended = min(compatible, key=lambda item: item.rank).candidate_id if compatible else None
    selected = next(item for item in assessments if item.candidate_id == selected_candidate_id)
    blockers = list(selected.blockers)
    if not compatible:
        blockers.append("no_compatible_component_alternative")
    if selected.compatible and recommended is not None:
        best = next(item for item in assessments if item.candidate_id == recommended)
        # Candidate ID orders display ties; it is not an engineering preference.
        # Keep all substantive minimality checks, allowing equally scored choices.
        if selected.comparison_key[:-1] != best.comparison_key[:-1]:
            blockers.append(f"selected_candidate_not_minimal:{recommended}")
    fields: dict[str, Any] = {
        "intent": intent,
        "candidates": tuple(sorted(candidates, key=lambda item: item.candidate_id)),
        "selected_candidate_id": selected_candidate_id,
        "assessments": assessments,
        "recommended_candidate_id": recommended,
        "disposition": ReadinessDisposition.READY if not blockers else ReadinessDisposition.BLOCKED,
        "blockers": tuple(blockers),
    }
    provisional = ComponentAlternativeReview.model_construct(**fields, review_fingerprint="0" * 64)
    return ComponentAlternativeReview(
        **fields,
        review_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"review_fingerprint"})
        ),
    )


class SupportRequirementKind(StrEnum):
    CONNECTION_POLARITY = "connection_polarity"
    CURRENT_LIMITING = "current_limiting"
    LOCAL_DECOUPLING = "local_decoupling"
    BULK_CAPACITANCE = "bulk_capacitance"
    PULL_UP_OR_DOWN = "pull_up_or_down"
    ESD_PROTECTION = "esd_protection"
    INRUSH_LIMITING = "inrush_limiting"
    RESET_STARTUP = "reset_startup"
    THERMAL_ISOLATION = "thermal_isolation"
    AIR_EXPOSURE = "air_exposure"
    FLYBACK_OR_CLAMP = "flyback_or_clamp"
    SERIES_DAMPING = "series_damping"


class SupportRequirement(SemanticIrModel):
    requirement_id: str
    subject_reference: str
    kind: SupportRequirementKind
    mandatory: bool = True
    maximum_distance_mm: float | None = Field(default=None, ge=0)
    minimum_value: float | None = None
    maximum_value: float | None = None
    units: str | None = None
    source_ids: tuple[str, ...] = Field(min_length=1)
    rationale: str

    @model_validator(mode="after")
    def requirement_is_coherent(self) -> Self:
        require_identity(self.requirement_id, "requirement_id")
        require_identity(self.subject_reference, "subject_reference")
        require_identity(self.rationale, "rationale")
        sources = tuple(sorted(require_identity(item, "source_ids") for item in self.source_ids))
        if len(sources) != len(set(sources)):
            raise ValueError("support source identities must be unique")
        object.__setattr__(self, "source_ids", sources)
        if self.minimum_value is not None and self.maximum_value is not None:
            if self.minimum_value > self.maximum_value:
                raise ValueError("support value range is reversed")
        if (self.minimum_value is not None or self.maximum_value is not None) and not self.units:
            raise ValueError("support value limits require units")
        return self


class SupportObservation(SemanticIrModel):
    requirement_id: str
    disposition: Literal["verified", "failed", "unverified", "not_applicable"]
    supporting_references: tuple[str, ...] = ()
    measured_distance_mm: float | None = Field(default=None, ge=0)
    observed_value: float | None = None
    evidence_ids: tuple[str, ...] = ()
    rationale: str

    @model_validator(mode="after")
    def observation_is_canonical(self) -> Self:
        require_identity(self.requirement_id, "requirement_id")
        require_identity(self.rationale, "rationale")
        for name in ("supporting_references", "evidence_ids"):
            values = tuple(sorted(require_identity(item, name) for item in getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique identities")
            object.__setattr__(self, name, values)
        if self.disposition == "verified" and not self.evidence_ids:
            raise ValueError("verified support observation requires evidence")
        return self


class SupportCircuitReview(SemanticIrModel):
    schema_id: Literal["pcbsmith-support-circuit-review-v1"] = "pcbsmith-support-circuit-review-v1"
    requirements: tuple[SupportRequirement, ...]
    observations: tuple[SupportObservation, ...]
    disposition: ReadinessDisposition
    blockers: tuple[str, ...]
    review_fingerprint: str

    @model_validator(mode="after")
    def review_is_replay_bound(self) -> Self:
        require_sha256(self.review_fingerprint, "review_fingerprint")
        payload = self.model_dump(mode="json", exclude={"review_fingerprint"})
        if self.review_fingerprint != fingerprint(payload):
            raise ValueError("support-circuit review fingerprint is stale")
        return self


def review_support_circuits(
    *,
    requirements: tuple[SupportRequirement, ...],
    observations: tuple[SupportObservation, ...],
) -> SupportCircuitReview:
    requirement_by_id = {item.requirement_id: item for item in requirements}
    if len(requirement_by_id) != len(requirements):
        raise ValueError("support requirement identities must be unique")
    observation_by_id = {item.requirement_id: item for item in observations}
    if len(observation_by_id) != len(observations):
        raise ValueError("support observation identities must be unique")
    unknown = set(observation_by_id) - set(requirement_by_id)
    if unknown:
        raise ValueError("support observations reference unknown requirements")
    blockers: list[str] = []
    unverified: list[str] = []
    for requirement_id, requirement in sorted(requirement_by_id.items()):
        observation = observation_by_id.get(requirement_id)
        if observation is None:
            target = blockers if requirement.mandatory else unverified
            target.append(f"{requirement_id}:missing_observation")
            continue
        if observation.disposition == "failed":
            blockers.append(f"{requirement_id}:failed")
            continue
        if observation.disposition in {"unverified", "not_applicable"}:
            target = blockers if requirement.mandatory else unverified
            target.append(f"{requirement_id}:{observation.disposition}")
            continue
        if requirement.maximum_distance_mm is not None:
            if observation.measured_distance_mm is None:
                blockers.append(f"{requirement_id}:distance_unverified")
            elif observation.measured_distance_mm > requirement.maximum_distance_mm:
                blockers.append(f"{requirement_id}:placement_too_far")
        if requirement.minimum_value is not None:
            if observation.observed_value is None:
                blockers.append(f"{requirement_id}:value_unverified")
            elif observation.observed_value < requirement.minimum_value:
                blockers.append(f"{requirement_id}:value_below_minimum")
        if requirement.maximum_value is not None:
            if observation.observed_value is None:
                blockers.append(f"{requirement_id}:value_unverified")
            elif observation.observed_value > requirement.maximum_value:
                blockers.append(f"{requirement_id}:value_above_maximum")
    disposition = (
        ReadinessDisposition.BLOCKED
        if blockers
        else ReadinessDisposition.UNVERIFIED
        if unverified
        else ReadinessDisposition.READY
    )
    findings = tuple(dict.fromkeys((*blockers, *unverified)))
    fields: dict[str, Any] = {
        "requirements": tuple(sorted(requirements, key=lambda item: item.requirement_id)),
        "observations": tuple(sorted(observations, key=lambda item: item.requirement_id)),
        "disposition": disposition,
        "blockers": findings,
    }
    provisional = SupportCircuitReview.model_construct(**fields, review_fingerprint="0" * 64)
    return SupportCircuitReview(
        **fields,
        review_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"review_fingerprint"})
        ),
    )


class SourceCurrentAuthority(StrEnum):
    USB2_DEFAULT = "usb2_default"
    USB3_DEFAULT = "usb3_default"
    TYPE_C_1P5 = "type_c_1p5"
    TYPE_C_3P0 = "type_c_3p0"
    USB_PD = "usb_pd"
    DEDICATED_SUPPLY = "dedicated_supply"
    UNRESOLVED = "unresolved"


_CURRENT_AUTHORITY_LIMIT_A: dict[SourceCurrentAuthority, float | None] = {
    SourceCurrentAuthority.USB2_DEFAULT: 0.5,
    SourceCurrentAuthority.USB3_DEFAULT: 0.9,
    SourceCurrentAuthority.TYPE_C_1P5: 1.5,
    SourceCurrentAuthority.TYPE_C_3P0: 3.0,
    SourceCurrentAuthority.USB_PD: None,
    SourceCurrentAuthority.DEDICATED_SUPPLY: None,
    SourceCurrentAuthority.UNRESOLVED: 0.0,
}


class PowerSourceContract(SemanticIrModel):
    source_id: str
    rail_id: str
    voltage_v: float = Field(gt=0)
    available_continuous_current_a: float = Field(gt=0)
    available_peak_current_a: float = Field(gt=0)
    current_authority: SourceCurrentAuthority
    current_detection_verified: bool
    direct_input_capacitance_uf: float = Field(ge=0)
    direct_input_capacitance_limit_uf: float | None = Field(default=None, gt=0)
    inrush_limiting_verified: bool = False
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def source_is_canonical(self) -> Self:
        require_identity(self.source_id, "source_id")
        require_identity(self.rail_id, "rail_id")
        if self.available_peak_current_a < self.available_continuous_current_a:
            raise ValueError("source peak current cannot be below continuous current")
        evidence = tuple(
            sorted(require_identity(item, "evidence_ids") for item in self.evidence_ids)
        )
        if len(evidence) != len(set(evidence)):
            raise ValueError("source evidence identities must be unique")
        object.__setattr__(self, "evidence_ids", evidence)
        return self


class PowerRailLoad(SemanticIrModel):
    load_id: str
    rail_id: str
    continuous_current_a: float = Field(ge=0)
    peak_current_a: float = Field(ge=0)
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def load_is_canonical(self) -> Self:
        require_identity(self.load_id, "load_id")
        require_identity(self.rail_id, "rail_id")
        if self.peak_current_a < self.continuous_current_a:
            raise ValueError("load peak current cannot be below continuous current")
        return self


class PowerConversionContract(SemanticIrModel):
    conversion_id: str
    input_rail_id: str
    output_rail_id: str
    input_voltage_v: float = Field(gt=0)
    output_voltage_v: float = Field(gt=0)
    kind: Literal["linear", "switching"]
    efficiency: float = Field(gt=0, le=1)
    maximum_output_current_a: float = Field(gt=0)
    thermal_verification_required: bool = True
    verified_dissipation_limit_w: float | None = Field(default=None, gt=0)
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def conversion_is_canonical(self) -> Self:
        require_identity(self.conversion_id, "conversion_id")
        require_identity(self.input_rail_id, "input_rail_id")
        require_identity(self.output_rail_id, "output_rail_id")
        if self.input_rail_id == self.output_rail_id:
            raise ValueError("power conversion cannot use the same input and output rail")
        if self.kind == "linear" and self.output_voltage_v > self.input_voltage_v:
            raise ValueError("linear conversion cannot raise voltage")
        return self


class PowerRailDemand(SemanticIrModel):
    rail_id: str
    continuous_current_a: float = Field(ge=0)
    peak_current_a: float = Field(ge=0)


class PowerPathReview(SemanticIrModel):
    schema_id: Literal["pcbsmith-power-path-review-v1"] = "pcbsmith-power-path-review-v1"
    source: PowerSourceContract
    loads: tuple[PowerRailLoad, ...]
    conversions: tuple[PowerConversionContract, ...]
    rail_demands: tuple[PowerRailDemand, ...]
    disposition: ReadinessDisposition
    blockers: tuple[str, ...]
    review_fingerprint: str

    @model_validator(mode="after")
    def review_is_replay_bound(self) -> Self:
        require_sha256(self.review_fingerprint, "review_fingerprint")
        payload = self.model_dump(mode="json", exclude={"review_fingerprint"})
        if self.review_fingerprint != fingerprint(payload):
            raise ValueError("power-path review fingerprint is stale")
        return self


def review_power_path(
    *,
    source: PowerSourceContract,
    loads: tuple[PowerRailLoad, ...],
    conversions: tuple[PowerConversionContract, ...],
) -> PowerPathReview:
    if len({item.load_id for item in loads}) != len(loads):
        raise ValueError("power load identities must be unique")
    by_output = {item.output_rail_id: item for item in conversions}
    if len(by_output) != len(conversions):
        raise ValueError("power conversions must have unique output rails")
    direct: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for load in loads:
        direct[load.rail_id][0] += load.continuous_current_a
        direct[load.rail_id][1] += load.peak_current_a
    blockers: list[str] = []
    memo: dict[str, tuple[float, float]] = {}

    def demand(rail_id: str, active: tuple[str, ...] = ()) -> tuple[float, float]:
        if rail_id in memo:
            return memo[rail_id]
        if rail_id in active:
            blockers.append(f"power_cycle:{rail_id}")
            return (0.0, 0.0)
        continuous, peak = direct[rail_id]
        for conversion in conversions:
            if conversion.input_rail_id != rail_id:
                continue
            output_continuous, output_peak = demand(conversion.output_rail_id, (*active, rail_id))
            if output_peak > conversion.maximum_output_current_a:
                blockers.append(f"{conversion.conversion_id}:output_peak_exceeds_rating")
            if conversion.kind == "linear":
                input_continuous = output_continuous
                input_peak = output_peak
                dissipation = (
                    conversion.input_voltage_v - conversion.output_voltage_v
                ) * output_continuous
            else:
                input_continuous = (conversion.output_voltage_v * output_continuous) / (
                    conversion.input_voltage_v * conversion.efficiency
                )
                input_peak = (conversion.output_voltage_v * output_peak) / (
                    conversion.input_voltage_v * conversion.efficiency
                )
                dissipation = (conversion.output_voltage_v * output_continuous) * (
                    1.0 / conversion.efficiency - 1.0
                )
            if conversion.thermal_verification_required:
                if conversion.verified_dissipation_limit_w is None:
                    blockers.append(f"{conversion.conversion_id}:thermal_limit_unverified")
                elif dissipation > conversion.verified_dissipation_limit_w:
                    blockers.append(f"{conversion.conversion_id}:dissipation_exceeds_limit")
            continuous += input_continuous
            peak += input_peak
        memo[rail_id] = (continuous, peak)
        return memo[rail_id]

    source_continuous, source_peak = demand(source.rail_id)
    for rail_id in sorted(set(direct) | {source.rail_id} | set(by_output)):
        demand(rail_id)
    authority_limit = _CURRENT_AUTHORITY_LIMIT_A[source.current_authority]
    if source.current_authority is SourceCurrentAuthority.UNRESOLVED:
        blockers.append(f"{source.source_id}:source_current_authority_unresolved")
    if authority_limit is not None and source.available_continuous_current_a > authority_limit:
        blockers.append(f"{source.source_id}:claimed_current_exceeds_authority")
    if (
        source.current_authority
        in {
            SourceCurrentAuthority.TYPE_C_1P5,
            SourceCurrentAuthority.TYPE_C_3P0,
            SourceCurrentAuthority.USB_PD,
        }
        and not source.current_detection_verified
    ):
        blockers.append(f"{source.source_id}:source_current_detection_unverified")
    if source_continuous > source.available_continuous_current_a:
        blockers.append(f"{source.source_id}:continuous_load_exceeds_source")
    if source_peak > source.available_peak_current_a:
        blockers.append(f"{source.source_id}:peak_load_exceeds_source")
    if (
        source.direct_input_capacitance_limit_uf is not None
        and source.direct_input_capacitance_uf > source.direct_input_capacitance_limit_uf
        and not source.inrush_limiting_verified
    ):
        blockers.append(f"{source.source_id}:input_capacitance_requires_inrush_limiting")
    fields: dict[str, Any] = {
        "source": source,
        "loads": tuple(sorted(loads, key=lambda item: item.load_id)),
        "conversions": tuple(sorted(conversions, key=lambda item: item.conversion_id)),
        "rail_demands": tuple(
            PowerRailDemand(
                rail_id=rail_id,
                continuous_current_a=memo[rail_id][0],
                peak_current_a=memo[rail_id][1],
            )
            for rail_id in sorted(memo)
        ),
        "disposition": ReadinessDisposition.READY if not blockers else ReadinessDisposition.BLOCKED,
        "blockers": tuple(dict.fromkeys(blockers)),
    }
    provisional = PowerPathReview.model_construct(**fields, review_fingerprint="0" * 64)
    return PowerPathReview(
        **fields,
        review_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"review_fingerprint"})
        ),
    )


class VisualSubjectRequirement(SemanticIrModel):
    subject_id: str
    component_reference: str
    artifact_id: str
    minimum_crop_width_px: int = Field(ge=16)
    minimum_crop_height_px: int = Field(ge=16)
    minimum_occupancy_fraction: float = Field(gt=0, le=1)
    model_required: bool = False
    aligned_model_required: bool = False


class VisualSubjectObservation(SemanticIrModel):
    subject_id: str
    artifact_sha256: str
    crop_px: tuple[int, int, int, int]
    crop_width_px: int = Field(gt=0)
    crop_height_px: int = Field(gt=0)
    occupancy_fraction: float = Field(ge=0, le=1)
    model_presence: Literal["present", "absent", "not_applicable", "unverified"]
    model_alignment: Literal["passed", "failed", "not_declared", "not_applicable"]

    @model_validator(mode="after")
    def observation_is_exact(self) -> Self:
        require_identity(self.subject_id, "subject_id")
        require_sha256(self.artifact_sha256, "artifact_sha256")
        left, top, right, bottom = self.crop_px
        if right <= left or bottom <= top:
            raise ValueError("visual crop is empty or reversed")
        if right - left != self.crop_width_px or bottom - top != self.crop_height_px:
            raise ValueError("visual crop dimensions are stale")
        return self


class VisualSubjectReview(SemanticIrModel):
    schema_id: Literal["pcbsmith-visual-subject-review-v1"] = "pcbsmith-visual-subject-review-v1"
    requirements: tuple[VisualSubjectRequirement, ...]
    observations: tuple[VisualSubjectObservation, ...]
    disposition: ReadinessDisposition
    blockers: tuple[str, ...]
    review_fingerprint: str

    @model_validator(mode="after")
    def review_is_replay_bound(self) -> Self:
        require_sha256(self.review_fingerprint, "review_fingerprint")
        payload = self.model_dump(mode="json", exclude={"review_fingerprint"})
        if self.review_fingerprint != fingerprint(payload):
            raise ValueError("visual-subject review fingerprint is stale")
        return self


def visual_model_state_from_preflight(
    report: ModelPreflightReport,
    component_reference: str,
) -> tuple[
    Literal["present", "absent", "not_applicable", "unverified"],
    Literal["passed", "failed", "not_declared", "not_applicable"],
]:
    """Translate exact model preflight into independent presence/alignment states."""

    require_identity(component_reference, "component_reference")
    if report.applicability == "not_applicable":
        return ("not_applicable", "not_applicable")
    candidates = tuple(item for item in report.models if item.reference == component_reference)
    resolved = tuple(item for item in candidates if item.status == "resolved")
    if not candidates:
        return (
            ("absent", "not_applicable")
            if component_reference in set(report.required_references)
            else ("unverified", "not_applicable")
        )
    if not resolved:
        return ("absent", "not_applicable")
    alignments = {item.transform_alignment for item in resolved}
    if "passed" in alignments:
        return ("present", "passed")
    if "failed" in alignments:
        return ("present", "failed")
    return ("present", "not_declared")


def inspect_visual_subject_crop(
    *,
    image_file: Path,
    subject_id: str,
    crop_px: tuple[int, int, int, int],
    background_delta: int = 18,
    model_presence: Literal["present", "absent", "not_applicable", "unverified"] = (
        "not_applicable"
    ),
    model_alignment: Literal[
        "passed", "failed", "not_declared", "not_applicable"
    ] = "not_applicable",
) -> VisualSubjectObservation:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - exercised in minimal installations
        raise RuntimeError("Pillow is required for quantitative visual crop inspection") from exc
    raw = image_file.read_bytes()
    with Image.open(image_file) as opened:
        image = opened.convert("RGB")
        left, top, right, bottom = crop_px
        if left < 0 or top < 0 or right > image.width or bottom > image.height:
            raise ValueError("visual crop lies outside the source image")
        crop = image.crop(crop_px)
        pixels = [
            cast(tuple[int, int, int], crop.getpixel((x, y)))
            for y in range(crop.height)
            for x in range(crop.width)
        ]
        boundary: list[tuple[int, int, int]] = []
        for x in range(crop.width):
            boundary.append(cast(tuple[int, int, int], crop.getpixel((x, 0))))
            boundary.append(cast(tuple[int, int, int], crop.getpixel((x, crop.height - 1))))
        for y in range(crop.height):
            boundary.append(cast(tuple[int, int, int], crop.getpixel((0, y))))
            boundary.append(cast(tuple[int, int, int], crop.getpixel((crop.width - 1, y))))
        background = tuple(
            int(median(pixel[channel] for pixel in boundary)) for channel in range(3)
        )
        foreground_count = sum(
            max(abs(pixel[channel] - background[channel]) for channel in range(3))
            >= background_delta
            for pixel in pixels
        )
    return VisualSubjectObservation(
        subject_id=subject_id,
        artifact_sha256=hashlib.sha256(raw).hexdigest(),
        crop_px=crop_px,
        crop_width_px=right - left,
        crop_height_px=bottom - top,
        occupancy_fraction=foreground_count / len(pixels),
        model_presence=model_presence,
        model_alignment=model_alignment,
    )


def review_visual_subjects(
    *,
    requirements: tuple[VisualSubjectRequirement, ...],
    observations: tuple[VisualSubjectObservation, ...],
) -> VisualSubjectReview:
    requirement_by_id = {item.subject_id: item for item in requirements}
    observation_by_id = {item.subject_id: item for item in observations}
    if len(requirement_by_id) != len(requirements):
        raise ValueError("visual subject requirement identities must be unique")
    if len(observation_by_id) != len(observations):
        raise ValueError("visual subject observation identities must be unique")
    if set(observation_by_id) - set(requirement_by_id):
        raise ValueError("visual subject observation references an unknown subject")
    blockers: list[str] = []
    for subject_id, requirement in sorted(requirement_by_id.items()):
        observation = observation_by_id.get(subject_id)
        if observation is None:
            blockers.append(f"{subject_id}:missing_crop")
            continue
        if observation.crop_width_px < requirement.minimum_crop_width_px:
            blockers.append(f"{subject_id}:crop_too_narrow")
        if observation.crop_height_px < requirement.minimum_crop_height_px:
            blockers.append(f"{subject_id}:crop_too_short")
        if observation.occupancy_fraction < requirement.minimum_occupancy_fraction:
            blockers.append(f"{subject_id}:subject_not_measurably_visible")
        if requirement.model_required and observation.model_presence != "present":
            blockers.append(f"{subject_id}:required_model_not_visible")
        if requirement.aligned_model_required and observation.model_alignment != "passed":
            blockers.append(f"{subject_id}:model_alignment_not_verified")
    fields: dict[str, Any] = {
        "requirements": tuple(sorted(requirements, key=lambda item: item.subject_id)),
        "observations": tuple(sorted(observations, key=lambda item: item.subject_id)),
        "disposition": ReadinessDisposition.READY if not blockers else ReadinessDisposition.BLOCKED,
        "blockers": tuple(blockers),
    }
    provisional = VisualSubjectReview.model_construct(**fields, review_fingerprint="0" * 64)
    return VisualSubjectReview(
        **fields,
        review_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"review_fingerprint"})
        ),
    )


class DesignReadinessStage(StrEnum):
    PREDESIGN = "predesign"
    SAVED_CANDIDATE = "saved_candidate"


class DesignReadinessReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-design-readiness-report-v1"] = (
        "pcbsmith-design-readiness-report-v1"
    )
    stage: DesignReadinessStage
    component_reviews: tuple[ComponentAlternativeReview, ...]
    support_review: SupportCircuitReview
    power_review: PowerPathReview
    visual_review: VisualSubjectReview | None
    disposition: ReadinessDisposition
    blockers: tuple[str, ...]
    report_fingerprint: str

    @model_validator(mode="after")
    def report_is_replay_bound(self) -> Self:
        require_sha256(self.report_fingerprint, "report_fingerprint")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("design readiness report fingerprint is stale")
        return self


def evaluate_design_readiness(
    *,
    stage: DesignReadinessStage,
    component_reviews: tuple[ComponentAlternativeReview, ...],
    support_review: SupportCircuitReview,
    power_review: PowerPathReview,
    visual_review: VisualSubjectReview | None = None,
) -> DesignReadinessReport:
    blockers: list[str] = []
    for review in component_reviews:
        blockers.extend(f"component:{review.intent.role_id}:{item}" for item in review.blockers)
    blockers.extend(f"support:{item}" for item in support_review.blockers)
    blockers.extend(f"power:{item}" for item in power_review.blockers)
    if stage is DesignReadinessStage.SAVED_CANDIDATE:
        if visual_review is None:
            blockers.append("visual:review_missing")
        else:
            blockers.extend(f"visual:{item}" for item in visual_review.blockers)
    elif visual_review is not None and visual_review.disposition is not ReadinessDisposition.READY:
        blockers.extend(f"visual:{item}" for item in visual_review.blockers)
    fields: dict[str, Any] = {
        "stage": stage,
        "component_reviews": tuple(
            sorted(component_reviews, key=lambda item: item.intent.intent_id)
        ),
        "support_review": support_review,
        "power_review": power_review,
        "visual_review": visual_review,
        "disposition": ReadinessDisposition.READY if not blockers else ReadinessDisposition.BLOCKED,
        "blockers": tuple(blockers),
    }
    provisional = DesignReadinessReport.model_construct(**fields, report_fingerprint="0" * 64)
    return DesignReadinessReport(
        **fields,
        report_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"report_fingerprint"})
        ),
    )


def require_design_readiness(report: DesignReadinessReport) -> None:
    # Recompute decisions, not just the outer self-reported fingerprint/status.
    components = tuple(
        review_component_alternatives(
            intent=item.intent,
            candidates=item.candidates,
            selected_candidate_id=item.selected_candidate_id,
        )
        for item in report.component_reviews
    )
    support = review_support_circuits(
        requirements=report.support_review.requirements,
        observations=report.support_review.observations,
    )
    power = review_power_path(
        source=report.power_review.source,
        loads=report.power_review.loads,
        conversions=report.power_review.conversions,
    )
    visual = (
        None
        if report.visual_review is None
        else review_visual_subjects(
            requirements=report.visual_review.requirements,
            observations=report.visual_review.observations,
        )
    )
    expected = evaluate_design_readiness(
        stage=report.stage,
        component_reviews=components,
        support_review=support,
        power_review=power,
        visual_review=visual,
    )
    if expected != report:
        raise ValueError("design readiness decisions do not replay from their inputs")
    if report.disposition is not ReadinessDisposition.READY:
        detail = "; ".join(report.blockers) or report.disposition.value
        raise ValueError(f"design readiness gate blocked publication: {detail}")


class AutomaticGateState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"
    NOT_APPLICABLE = "not_applicable"


class DesignReleaseState(StrEnum):
    GENERATION_FAILED = "generation_failed"
    CANDIDATE_GENERATED = "candidate_generated"
    INSPECTION_PENDING = "inspection_pending"
    INSPECTION_FAILED = "inspection_failed"
    ENGINEERING_HOLD = "engineering_hold"
    RELEASE_CANDIDATE = "release_candidate"
    RELEASED = "released"


class ReleaseGateSnapshot(SemanticIrModel):
    candidate_generated: bool
    review_package_generated: bool
    visual_inspection: AutomaticGateState
    routing: AutomaticGateState
    drc: AutomaticGateState
    design_readiness: AutomaticGateState
    model_preflight: AutomaticGateState
    release_approved: bool = False


class DesignReleaseRecord(SemanticIrModel):
    snapshot: ReleaseGateSnapshot
    state: DesignReleaseState
    blockers: tuple[str, ...]


def derive_design_release(snapshot: ReleaseGateSnapshot) -> DesignReleaseRecord:
    blockers: list[str] = []
    if not snapshot.candidate_generated:
        return DesignReleaseRecord(
            snapshot=snapshot,
            state=DesignReleaseState.GENERATION_FAILED,
            blockers=("candidate_not_generated",),
        )
    if not snapshot.review_package_generated:
        return DesignReleaseRecord(
            snapshot=snapshot,
            state=DesignReleaseState.CANDIDATE_GENERATED,
            blockers=("review_package_not_generated",),
        )
    engineering = {
        "routing": snapshot.routing,
        "drc": snapshot.drc,
        "design_readiness": snapshot.design_readiness,
        "model_preflight": snapshot.model_preflight,
    }
    blockers.extend(
        f"{name}:{state.value}"
        for name, state in engineering.items()
        if state is not AutomaticGateState.PASSED
    )
    if snapshot.visual_inspection is AutomaticGateState.FAILED:
        return DesignReleaseRecord(
            snapshot=snapshot,
            state=DesignReleaseState.INSPECTION_FAILED,
            blockers=tuple((*blockers, "visual_inspection:failed")),
        )
    if blockers:
        return DesignReleaseRecord(
            snapshot=snapshot,
            state=DesignReleaseState.ENGINEERING_HOLD,
            blockers=tuple(blockers),
        )
    if snapshot.visual_inspection is AutomaticGateState.PENDING:
        return DesignReleaseRecord(
            snapshot=snapshot,
            state=DesignReleaseState.INSPECTION_PENDING,
            blockers=("visual_inspection:pending",),
        )
    if snapshot.visual_inspection is not AutomaticGateState.PASSED:
        return DesignReleaseRecord(
            snapshot=snapshot,
            state=DesignReleaseState.ENGINEERING_HOLD,
            blockers=(f"visual_inspection:{snapshot.visual_inspection.value}",),
        )
    return DesignReleaseRecord(
        snapshot=snapshot,
        state=(
            DesignReleaseState.RELEASED
            if snapshot.release_approved
            else DesignReleaseState.RELEASE_CANDIDATE
        ),
        blockers=(),
    )


class DesignChangeKind(StrEnum):
    COMPONENT_SELECTION = "component_selection"
    SUPPORT_CIRCUIT = "support_circuit"
    POWER_PATH = "power_path"
    PLACEMENT = "placement"
    ROUTING = "routing"
    POUR = "pour"
    MODEL = "model"
    MARKING = "marking"
    ARCHITECTURE = "architecture"


class InvalidatedArtifact(StrEnum):
    SCHEMATIC = "schematic"
    NETLIST = "netlist"
    PLACEMENT = "placement"
    ROUTING = "routing"
    POURS = "pours"
    MODEL_PREFLIGHT = "model_preflight"
    VISUAL_REVIEW = "visual_review"
    ELECTRICAL_CHECKS = "electrical_checks"
    RELEASE_RECORD = "release_record"


_INVALIDATION_POLICY: dict[DesignChangeKind, tuple[InvalidatedArtifact, ...]] = {
    DesignChangeKind.COMPONENT_SELECTION: tuple(InvalidatedArtifact),
    DesignChangeKind.SUPPORT_CIRCUIT: tuple(InvalidatedArtifact),
    DesignChangeKind.POWER_PATH: tuple(InvalidatedArtifact),
    DesignChangeKind.PLACEMENT: (
        InvalidatedArtifact.PLACEMENT,
        InvalidatedArtifact.ROUTING,
        InvalidatedArtifact.POURS,
        InvalidatedArtifact.MODEL_PREFLIGHT,
        InvalidatedArtifact.VISUAL_REVIEW,
        InvalidatedArtifact.ELECTRICAL_CHECKS,
        InvalidatedArtifact.RELEASE_RECORD,
    ),
    DesignChangeKind.ROUTING: (
        InvalidatedArtifact.ROUTING,
        InvalidatedArtifact.POURS,
        InvalidatedArtifact.VISUAL_REVIEW,
        InvalidatedArtifact.ELECTRICAL_CHECKS,
        InvalidatedArtifact.RELEASE_RECORD,
    ),
    DesignChangeKind.POUR: (
        InvalidatedArtifact.POURS,
        InvalidatedArtifact.VISUAL_REVIEW,
        InvalidatedArtifact.ELECTRICAL_CHECKS,
        InvalidatedArtifact.RELEASE_RECORD,
    ),
    DesignChangeKind.MODEL: (
        InvalidatedArtifact.MODEL_PREFLIGHT,
        InvalidatedArtifact.VISUAL_REVIEW,
        InvalidatedArtifact.RELEASE_RECORD,
    ),
    DesignChangeKind.MARKING: (
        InvalidatedArtifact.VISUAL_REVIEW,
        InvalidatedArtifact.RELEASE_RECORD,
    ),
    DesignChangeKind.ARCHITECTURE: tuple(InvalidatedArtifact),
}


class ScopedDesignChange(SemanticIrModel):
    change_id: str
    kind: DesignChangeKind
    component_references: tuple[str, ...] = ()
    net_names: tuple[str, ...] = ()
    regions_mm: tuple[tuple[float, float, float, float], ...] = ()
    rationale: str


class DependencyScopedInvalidationPlan(SemanticIrModel):
    schema_id: Literal["pcbsmith-dependency-scoped-invalidation-v1"] = (
        "pcbsmith-dependency-scoped-invalidation-v1"
    )
    changes: tuple[ScopedDesignChange, ...]
    invalidated_artifacts: tuple[InvalidatedArtifact, ...]
    preserved_artifacts: tuple[InvalidatedArtifact, ...]
    component_references: tuple[str, ...]
    net_names: tuple[str, ...]
    regions_mm: tuple[tuple[float, float, float, float], ...]
    whole_board_restart_required: bool


def plan_dependency_scoped_invalidation(
    changes: tuple[ScopedDesignChange, ...],
) -> DependencyScopedInvalidationPlan:
    if not changes:
        raise ValueError("at least one scoped design change is required")
    if len({item.change_id for item in changes}) != len(changes):
        raise ValueError("scoped design change identities must be unique")
    invalidated = {artifact for change in changes for artifact in _INVALIDATION_POLICY[change.kind]}
    architecture = any(change.kind is DesignChangeKind.ARCHITECTURE for change in changes)
    components = tuple(sorted({item for change in changes for item in change.component_references}))
    nets = tuple(sorted({item for change in changes for item in change.net_names}))
    regions = tuple(sorted({item for change in changes for item in change.regions_mm}))
    return DependencyScopedInvalidationPlan(
        changes=tuple(sorted(changes, key=lambda item: item.change_id)),
        invalidated_artifacts=tuple(sorted(invalidated, key=lambda item: item.value)),
        preserved_artifacts=tuple(
            sorted(set(InvalidatedArtifact) - invalidated, key=lambda item: item.value)
        ),
        component_references=components,
        net_names=nets,
        regions_mm=regions,
        whole_board_restart_required=architecture,
    )


__all__ = [
    "AutomaticGateState",
    "ComponentAlternativeReview",
    "ComponentCandidate",
    "ComponentUseIntent",
    "DependencyScopedInvalidationPlan",
    "DesignChangeKind",
    "DesignReadinessReport",
    "DesignReadinessStage",
    "DesignReleaseRecord",
    "DesignReleaseState",
    "InvalidatedArtifact",
    "PowerConversionContract",
    "PowerPathReview",
    "PowerRailLoad",
    "PowerSourceContract",
    "ReadinessDisposition",
    "ReleaseGateSnapshot",
    "ScopedDesignChange",
    "SourceCurrentAuthority",
    "SupportCircuitReview",
    "SupportObservation",
    "SupportRequirement",
    "SupportRequirementKind",
    "VisualSubjectObservation",
    "VisualSubjectRequirement",
    "VisualSubjectReview",
    "derive_design_release",
    "evaluate_design_readiness",
    "inspect_visual_subject_crop",
    "plan_dependency_scoped_invalidation",
    "require_design_readiness",
    "review_component_alternatives",
    "review_power_path",
    "review_support_circuits",
    "review_visual_subjects",
    "visual_model_state_from_preflight",
]
