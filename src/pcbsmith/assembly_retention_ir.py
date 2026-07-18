"""Replay-bound IR for process-scoped dual-side component retention review.

This module deliberately records process and package evidence.  It does not
infer an assembly sequence from front/back placement and it does not promote
the narrow SAC305 experimental ratio to a qualified process rule.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticIrModel,
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _identity(value: str, name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed identity")
    return value


def _sha(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _identities(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    result = tuple(sorted(_identity(value, name) for value in values))
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must contain unique identities")
    return result


class ComponentSide(StrEnum):
    FRONT = "front"
    BACK = "back"


class RetentionValueStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class RetentionModelApplicability(StrEnum):
    MATCHED = "matched"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"


class AssemblerRetentionVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    PROCESS_REVIEW_REQUIRED = "process_review_required"
    NOT_APPLICABLE = "not_applicable"


class AssemblyProcessProfile(SemanticIrModel):
    """Exact declared process facts; every unknown remains ``None``."""

    schema_id: Literal["pcbsmith-retention-assembly-process-profile"] = (
        "pcbsmith-retention-assembly-process-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    assembler_id: str | None = None
    process_revision: str
    sequence: Literal[
        "single_reflow",
        "double_reflow",
        "reflow_then_wave",
        "selective",
        "hand_assembly",
        "other",
    ]
    first_reflow_side: Literal["front", "back", "not_applicable"]
    second_reflow_side: Literal["front", "back", "not_applicable"]
    inverted_during_second_reflow_side: Literal["front", "back", "none"]
    alloy_id: str | None = None
    paste_id: str | None = None
    surface_finish_id: str | None = None
    stencil_thickness_um: int | None = Field(default=None, gt=0)
    aperture_process_id: str | None = None
    oven_id: str | None = None
    peak_temperature_millic: int | None = Field(default=None, gt=0)
    time_above_liquidus_ms: int | None = Field(default=None, ge=0)
    conveyor_orientation: str | None = None
    turbulence_class: str | None = None
    board_carrier_id: str | None = None
    adhesive_policy_id: str | None = None
    handling_policy_id: str | None = None
    process_condition_ids: tuple[str, ...] = ()
    evidence_binding_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def explicit_process_is_coherent(self) -> Self:
        for name in ("profile_id", "process_revision"):
            _identity(getattr(self, name), name)
        for name in (
            "assembler_id",
            "alloy_id",
            "paste_id",
            "surface_finish_id",
            "aperture_process_id",
            "oven_id",
            "conveyor_orientation",
            "turbulence_class",
            "board_carrier_id",
            "adhesive_policy_id",
            "handling_policy_id",
        ):
            if (value := getattr(self, name)) is not None:
                _identity(value, name)
        if self.sequence == "single_reflow" and (
            self.second_reflow_side != "not_applicable"
            or self.inverted_during_second_reflow_side != "none"
        ):
            raise ValueError("single reflow cannot declare a second-pass inverted side")
        if self.sequence == "double_reflow":
            if (
                self.first_reflow_side not in {"front", "back"}
                or self.second_reflow_side not in {"front", "back"}
                or self.first_reflow_side == self.second_reflow_side
                or self.inverted_during_second_reflow_side != self.first_reflow_side
            ):
                raise ValueError(
                    "double reflow requires two distinct sides and explicitly identifies "
                    "the first side as inverted during pass two"
                )
        object.__setattr__(
            self,
            "process_condition_ids",
            _identities(self.process_condition_ids, "process_condition_ids"),
        )
        object.__setattr__(
            self,
            "evidence_binding_ids",
            _identities(self.evidence_binding_ids, "evidence_binding_ids"),
        )
        return self


class PackageRetentionEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-package-retention-evidence"] = (
        "pcbsmith-package-retention-evidence"
    )
    schema_version: Literal[1] = 1
    evidence_id: str
    component_reference: str
    footprint: str
    side: ComponentSide
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    package_family: str
    component_mass_ug: int | None = Field(default=None, gt=0)
    mass_source: Literal["manufacturer", "measured", "estimated", "unknown"]
    joint_ids: tuple[str, ...] = Field(min_length=1)
    total_wetted_perimeter_um: int | None = Field(default=None, gt=0)
    perimeter_geometry_kind: Literal["wetted_joint_interface", "body_outline", "unknown"]
    wetted_perimeter_method_id: str | None = None
    pad_pattern_fingerprint: str
    paste_aperture_fingerprint: str | None = None
    void_fraction_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    orientation_to_conveyor_millideg: int | None = None
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def package_evidence_is_exact_and_typed(self) -> Self:
        for name in ("evidence_id", "component_reference", "footprint", "package_family"):
            _identity(getattr(self, name), name)
        for name in (
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
            "pad_pattern_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if self.paste_aperture_fingerprint is not None:
            _sha(self.paste_aperture_fingerprint, "paste_aperture_fingerprint")
        if (self.component_mass_ug is None) != (self.mass_source == "unknown"):
            raise ValueError("mass value and mass source must become known together")
        if self.total_wetted_perimeter_um is None:
            if self.wetted_perimeter_method_id is not None:
                raise ValueError("unknown wetted perimeter cannot carry a calculation method")
        else:
            if self.perimeter_geometry_kind != "wetted_joint_interface":
                raise ValueError("body outline is not wetted joint-interface perimeter")
            if self.wetted_perimeter_method_id is None:
                raise ValueError("known wetted perimeter requires a method identity")
            _identity(self.wetted_perimeter_method_id, "wetted_perimeter_method_id")
        object.__setattr__(self, "joint_ids", _identities(self.joint_ids, "joint_ids"))
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class RetentionApplicabilityConditions(SemanticIrModel):
    """Narrow, exact conditions for one advisory experimental model."""

    schema_id: Literal["pcbsmith-retention-applicability-conditions"] = (
        "pcbsmith-retention-applicability-conditions"
    )
    schema_version: Literal[1] = 1
    sequence: Literal["double_reflow"]
    inverted_side: ComponentSide
    alloy_id: str
    paste_id: str
    surface_finish_id: str
    stencil_thickness_um: int = Field(gt=0)
    aperture_process_id: str
    oven_id: str
    peak_temperature_millic: int
    time_above_liquidus_ms: int = Field(ge=0)
    conveyor_orientation: str
    turbulence_class: str
    board_carrier_id: str
    adhesive_policy_id: str
    handling_policy_id: str
    package_families: tuple[str, ...] = Field(min_length=1)
    pad_pattern_fingerprints: tuple[str, ...] = Field(min_length=1)
    paste_aperture_fingerprints: tuple[str, ...] = Field(min_length=1)
    void_fraction_basis_points: int = Field(ge=0, le=10_000)
    component_orientation_millideg: int
    required_condition_ids: tuple[str, ...] = Field(min_length=1)
    excluded_process_condition_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def narrow_conditions_are_complete(self) -> Self:
        for name in (
            "alloy_id",
            "paste_id",
            "surface_finish_id",
            "aperture_process_id",
            "oven_id",
            "conveyor_orientation",
            "turbulence_class",
            "board_carrier_id",
            "adhesive_policy_id",
            "handling_policy_id",
        ):
            _identity(getattr(self, name), name)
        object.__setattr__(
            self, "package_families", _identities(self.package_families, "package_families")
        )
        pads = tuple(
            sorted(
                _sha(value, "pad_pattern_fingerprints") for value in self.pad_pattern_fingerprints
            )
        )
        apertures = tuple(
            sorted(
                _sha(value, "paste_aperture_fingerprints")
                for value in self.paste_aperture_fingerprints
            )
        )
        if len(pads) != len(set(pads)) or len(apertures) != len(set(apertures)):
            raise ValueError("condition fingerprints must be unique")
        object.__setattr__(self, "pad_pattern_fingerprints", pads)
        object.__setattr__(self, "paste_aperture_fingerprints", apertures)
        object.__setattr__(
            self,
            "required_condition_ids",
            _identities(self.required_condition_ids, "required_condition_ids"),
        )
        object.__setattr__(
            self,
            "excluded_process_condition_ids",
            _identities(self.excluded_process_condition_ids, "excluded_process_condition_ids"),
        )
        return self


class AdvisoryRetentionModel(SemanticIrModel):
    schema_id: Literal["pcbsmith-advisory-retention-model"] = "pcbsmith-advisory-retention-model"
    schema_version: Literal[1] = 1
    model_id: str
    model_revision: str
    model_kind: Literal["narrow_sac305_experiment"]
    authority: Literal[SemanticAuthorityClass.ADVISORY_HYPOTHESIS]
    calculation_kind: Literal["mass_per_wetted_perimeter"]
    advisory_limit_numerator_ug_per_um: int = Field(gt=0)
    advisory_limit_denominator: int = Field(gt=0)
    conditions: RetentionApplicabilityConditions
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def model_is_narrow_and_canonical(self) -> Self:
        _identity(self.model_id, "model_id")
        _identity(self.model_revision, "model_revision")
        if self.conditions.alloy_id != "SAC305":
            raise ValueError("the narrow SAC305 experiment cannot be relabeled for another alloy")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        return self


class QualifiedAssemblerReview(SemanticIrModel):
    schema_id: Literal["pcbsmith-qualified-assembler-retention-review"] = (
        "pcbsmith-qualified-assembler-retention-review"
    )
    schema_version: Literal[1] = 1
    review_id: str
    assembler_id: str
    reviewer_identity: str
    qualification_record_id: str
    qualification_source_sha256: str
    status: Literal["active", "suspended", "expired", "revoked"]
    effective_date: date
    expiry_date: date | None = None
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    process_profile_fingerprint: str
    component_evidence_fingerprint: str
    package_family: str
    rule_context_fingerprint: str
    covered_condition_ids: tuple[str, ...] = Field(min_length=1)
    required_restriction_ids: tuple[str, ...] = Field(min_length=1)
    deviation_ids: tuple[str, ...] = ()
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def qualified_review_is_bound(self) -> Self:
        for name in (
            "review_id",
            "assembler_id",
            "reviewer_identity",
            "qualification_record_id",
            "package_family",
        ):
            _identity(getattr(self, name), name)
        for name in (
            "qualification_source_sha256",
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
            "process_profile_fingerprint",
            "component_evidence_fingerprint",
            "rule_context_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if self.expiry_date is not None and self.expiry_date < self.effective_date:
            raise ValueError("review expiry cannot precede its effective date")
        for name in (
            "covered_condition_ids",
            "required_restriction_ids",
            "deviation_ids",
            "source_binding_ids",
        ):
            object.__setattr__(self, name, _identities(getattr(self, name), name))
        return self


class AssemblerRetentionRule(SemanticIrModel):
    schema_id: Literal["pcbsmith-assembler-retention-rule"] = "pcbsmith-assembler-retention-rule"
    schema_version: Literal[1] = 1
    rule_id: str
    authority: Literal[SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT]
    calculation_kind: Literal["mass_per_wetted_perimeter"]
    maximum_ratio_numerator_ug_per_um: int = Field(gt=0)
    maximum_ratio_denominator: int = Field(gt=0)
    review: QualifiedAssemblerReview
    source_binding_ids: tuple[str, ...] = Field(min_length=1)

    def rule_context(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "calculation_kind": self.calculation_kind,
            "maximum_ratio_numerator_ug_per_um": self.maximum_ratio_numerator_ug_per_um,
            "maximum_ratio_denominator": self.maximum_ratio_denominator,
        }

    @model_validator(mode="after")
    def rule_is_bound_to_review(self) -> Self:
        _identity(self.rule_id, "rule_id")
        object.__setattr__(
            self, "source_binding_ids", _identities(self.source_binding_ids, "source_binding_ids")
        )
        if self.review.rule_context_fingerprint != fingerprint(self.rule_context()):
            raise ValueError("qualified review is bound to another rule or threshold")
        if self.rule_id not in self.review.required_restriction_ids:
            raise ValueError("qualified review does not declare this restriction")
        return self


class AssemblyRetentionDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-assembly-retention-declaration"] = (
        "pcbsmith-assembly-retention-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str
    evaluation_date: date
    board_layout_snapshot_json: str
    board_netlist_snapshot_json: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    process_profile: AssemblyProcessProfile
    scoped_component_references: tuple[str, ...] = Field(min_length=1)
    whole_board_component_inventory_declared: bool = False
    package_evidence: tuple[PackageRetentionEvidence, ...] = Field(min_length=1)
    advisory_models: tuple[AdvisoryRetentionModel, ...] = ()
    assembler_rules: tuple[AssemblerRetentionRule, ...] = ()
    evidence_bindings: tuple[EvidenceApplicabilityBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_replay_scope_is_bound(self) -> Self:
        _identity(self.declaration_id, "declaration_id")
        layout = parse_canonical_board_layout_snapshot(self.board_layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.board_netlist_snapshot_json)
        if canonical_board_layout_snapshot_json(layout) != self.board_layout_snapshot_json:
            raise ValueError("BoardLayout snapshot is noncanonical")
        if canonical_board_netlist_snapshot_json(netlist) != self.board_netlist_snapshot_json:
            raise ValueError("BoardNetlist snapshot is noncanonical")
        if (
            board_layout_snapshot_fingerprint(self.board_layout_snapshot_json)
            != self.board_layout_snapshot_fingerprint
            or board_netlist_snapshot_fingerprint(self.board_netlist_snapshot_json)
            != self.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("board snapshot fingerprint is stale")
        scoped = _identities(self.scoped_component_references, "scoped_component_references")
        netlist_by_ref = {item.reference: item for item in netlist.components}
        placement_refs = {item.reference for item, _ in layout.placements}
        if not set(scoped).issubset(netlist_by_ref) or not set(scoped).issubset(placement_refs):
            raise ValueError("retention scope references an absent or unplaced component")
        if self.whole_board_component_inventory_declared and set(scoped) != set(netlist_by_ref):
            raise ValueError("whole-board inventory claim requires every BoardNetlist component")
        bindings = tuple(sorted(self.evidence_bindings, key=lambda item: item.binding_id))
        binding_ids = {item.binding_id for item in bindings}
        if len(binding_ids) != len(bindings):
            raise ValueError("evidence binding identities must be unique")
        evidence = tuple(sorted(self.package_evidence, key=lambda item: item.component_reference))
        if tuple(item.component_reference for item in evidence) != scoped:
            raise ValueError("package evidence must exactly cover the declared component scope")
        flip_refs = set(layout.part_flip)
        for item in evidence:
            component = netlist_by_ref[item.component_reference]
            expected_side = (
                ComponentSide.BACK if item.component_reference in flip_refs else ComponentSide.FRONT
            )
            if (
                item.footprint != component.footprint
                or item.side is not expected_side
                or item.board_layout_snapshot_fingerprint != self.board_layout_snapshot_fingerprint
                or item.board_netlist_snapshot_fingerprint
                != self.board_netlist_snapshot_fingerprint
            ):
                raise ValueError(
                    "package evidence is stale for component, footprint, side, or board"
                )
            if not set(item.source_binding_ids).issubset(binding_ids):
                raise ValueError("package evidence references unknown source bindings")
        if not set(self.process_profile.evidence_binding_ids).issubset(binding_ids):
            raise ValueError("process profile references unknown source bindings")
        models = tuple(sorted(self.advisory_models, key=lambda item: item.model_id))
        rules = tuple(sorted(self.assembler_rules, key=lambda item: item.rule_id))
        if len({item.model_id for item in models}) != len(models):
            raise ValueError("advisory model identities must be unique")
        if len({item.rule_id for item in rules}) != len(rules):
            raise ValueError("assembler rule identities must be unique")
        for model in models:
            if not set(model.source_binding_ids).issubset(binding_ids):
                raise ValueError("retention model/rule references unknown source bindings")
        for rule in rules:
            if not set(rule.source_binding_ids).issubset(binding_ids):
                raise ValueError("retention model/rule references unknown source bindings")
        object.__setattr__(self, "scoped_component_references", scoped)
        object.__setattr__(self, "evidence_bindings", bindings)
        object.__setattr__(self, "package_evidence", evidence)
        object.__setattr__(self, "advisory_models", models)
        object.__setattr__(self, "assembler_rules", rules)
        return self


class ExactRetentionRatio(SemanticIrModel):
    schema_id: Literal["pcbsmith-exact-retention-ratio"] = "pcbsmith-exact-retention-ratio"
    schema_version: Literal[1] = 1
    numerator_mass_ug: int = Field(gt=0)
    denominator_wetted_perimeter_um: int = Field(gt=0)
    diagnostic_ug_per_um: str


class AdvisoryRetentionEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-advisory-retention-evidence"] = (
        "pcbsmith-advisory-retention-evidence"
    )
    schema_version: Literal[1] = 1
    model_id: str
    applicability: RetentionModelApplicability
    unmatched_condition_ids: tuple[str, ...] = ()
    comparison: Literal["at_or_below_advisory_limit", "above_advisory_limit"] | None
    disposition: SemanticDisposition


class AssemblerRuleEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-assembler-rule-evidence"] = "pcbsmith-assembler-rule-evidence"
    schema_version: Literal[1] = 1
    rule_id: str
    review_id: str
    verdict: AssemblerRetentionVerdict
    disposition: SemanticDisposition
    reason_ids: tuple[str, ...] = ()


class ComponentRetentionFinding(SemanticIrModel):
    schema_id: Literal["pcbsmith-component-retention-finding"] = (
        "pcbsmith-component-retention-finding"
    )
    schema_version: Literal[1] = 1
    component_reference: str
    side: ComponentSide
    inverted_during_second_reflow: bool
    process_applicability: SemanticDisposition
    mass_status: RetentionValueStatus
    wetted_perimeter_status: RetentionValueStatus
    ratio: ExactRetentionRatio | None
    advisory_evidence: tuple[AdvisoryRetentionEvidence, ...]
    assembler_evidence: tuple[AssemblerRuleEvidence, ...]
    assembler_verdict: AssemblerRetentionVerdict
    final_disposition: SemanticDisposition
    final_finding_kind: Literal[
        "not_applicable",
        "missing_package_measurement",
        "advisory_comparison_only",
        "process_review_required",
        "qualified_assembler_pass",
        "qualified_assembler_fail",
    ]


class AssemblyRetentionResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-assembly-retention-result"] = "pcbsmith-assembly-retention-result"
    schema_version: Literal[1] = 1
    inventory_scope: Literal[
        "declared_component_scope_only_not_whole_board",
        "declared_complete_whole_board_component_inventory",
    ]
    excluded_claims: tuple[
        Literal[
            "solder_reliability",
            "void_prediction",
            "thermal_profile_validation",
            "adhesive_performance",
            "board_mutation",
        ],
        ...,
    ]
    declaration: AssemblyRetentionDeclaration
    component_findings: tuple[ComponentRetentionFinding, ...]
    component_findings_fingerprint: str
    result_fingerprint: str

    @field_validator("component_findings_fingerprint", "result_fingerprint")
    @classmethod
    def valid_fingerprint(cls, value: str, info: Any) -> str:
        return _sha(value, info.field_name)

    @model_validator(mode="after")
    def exact_replay_equality(self) -> Self:
        from pcbsmith.kicad.assembly_retention import rederive_assembly_retention

        expected = rederive_assembly_retention(self.declaration)
        for name in (
            "inventory_scope",
            "excluded_claims",
            "component_findings",
            "component_findings_fingerprint",
        ):
            if getattr(self, name) != expected[name]:
                raise ValueError("assembly retention result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("assembly retention result fingerprint is stale")
        return self
