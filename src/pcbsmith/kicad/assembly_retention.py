"""Evaluate explicit process-scoped dual-side component-retention evidence."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from pcbsmith.assembly_retention_ir import (
    AdvisoryRetentionEvidence,
    AdvisoryRetentionModel,
    AssemblerRetentionRule,
    AssemblerRetentionVerdict,
    AssemblerRuleEvidence,
    AssemblyRetentionDeclaration,
    AssemblyRetentionResult,
    ComponentRetentionFinding,
    ExactRetentionRatio,
    PackageRetentionEvidence,
    RetentionModelApplicability,
    RetentionValueStatus,
    fingerprint,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
)

_EXCLUDED_CLAIMS = (
    "adhesive_performance",
    "board_mutation",
    "solder_reliability",
    "thermal_profile_validation",
    "void_prediction",
)


def _binding_is_complete(binding: EvidenceApplicabilityBinding) -> bool:
    evidence_conditions = {
        condition for item in binding.evidence for condition in item.required_conditions
    }
    return (
        binding.reviewer_record_id is not None
        and bool(binding.required_conditions)
        and not binding.unmatched_conditions
        and set(binding.matched_conditions) == set(binding.required_conditions)
        and evidence_conditions == set(binding.required_conditions)
        and bool(binding.evidence)
        and all(
            item.source_status == "pinned"
            and item.local_sha256 is not None
            and item.locator_status in {"text_verified", "figure_verified", "figure_bound"}
            and item.applicability_status == "confirmed"
            and bool(item.required_conditions)
            for item in binding.evidence
        )
    )


def _ratio(evidence: PackageRetentionEvidence) -> ExactRetentionRatio | None:
    if evidence.component_mass_ug is None or evidence.total_wetted_perimeter_um is None:
        return None
    ratio = Fraction(evidence.component_mass_ug, evidence.total_wetted_perimeter_um)
    integer_part, remainder = divmod(ratio.numerator, ratio.denominator)
    decimal_digits: list[str] = []
    for _ in range(12):
        if remainder == 0:
            break
        digit, remainder = divmod(remainder * 10, ratio.denominator)
        decimal_digits.append(str(digit))
    rendered = str(integer_part)
    if decimal_digits:
        rendered += "." + "".join(decimal_digits)
    return ExactRetentionRatio(
        numerator_mass_ug=evidence.component_mass_ug,
        denominator_wetted_perimeter_um=evidence.total_wetted_perimeter_um,
        diagnostic_ug_per_um=rendered,
    )


def _advisory_mismatches(
    declaration: AssemblyRetentionDeclaration,
    evidence: PackageRetentionEvidence,
    model: AdvisoryRetentionModel,
) -> tuple[str, ...]:
    profile = declaration.process_profile
    conditions = model.conditions
    comparisons: tuple[tuple[str, Any, Any], ...] = (
        ("sequence", profile.sequence, conditions.sequence),
        (
            "inverted_during_second_reflow_side",
            profile.inverted_during_second_reflow_side,
            conditions.inverted_side.value,
        ),
        ("alloy_id", profile.alloy_id, conditions.alloy_id),
        ("paste_id", profile.paste_id, conditions.paste_id),
        ("surface_finish_id", profile.surface_finish_id, conditions.surface_finish_id),
        ("stencil_thickness_um", profile.stencil_thickness_um, conditions.stencil_thickness_um),
        ("aperture_process_id", profile.aperture_process_id, conditions.aperture_process_id),
        ("oven_id", profile.oven_id, conditions.oven_id),
        (
            "peak_temperature_millic",
            profile.peak_temperature_millic,
            conditions.peak_temperature_millic,
        ),
        (
            "time_above_liquidus_ms",
            profile.time_above_liquidus_ms,
            conditions.time_above_liquidus_ms,
        ),
        (
            "conveyor_orientation",
            profile.conveyor_orientation,
            conditions.conveyor_orientation,
        ),
        ("turbulence_class", profile.turbulence_class, conditions.turbulence_class),
        ("board_carrier_id", profile.board_carrier_id, conditions.board_carrier_id),
        ("adhesive_policy_id", profile.adhesive_policy_id, conditions.adhesive_policy_id),
        ("handling_policy_id", profile.handling_policy_id, conditions.handling_policy_id),
        ("package_family", evidence.package_family, conditions.package_families),
        (
            "pad_pattern_fingerprint",
            evidence.pad_pattern_fingerprint,
            conditions.pad_pattern_fingerprints,
        ),
        (
            "paste_aperture_fingerprint",
            evidence.paste_aperture_fingerprint,
            conditions.paste_aperture_fingerprints,
        ),
        (
            "void_fraction_basis_points",
            evidence.void_fraction_basis_points,
            conditions.void_fraction_basis_points,
        ),
        (
            "orientation_to_conveyor_millideg",
            evidence.orientation_to_conveyor_millideg,
            conditions.component_orientation_millideg,
        ),
    )
    mismatches: list[str] = []
    for name, actual, expected in comparisons:
        if isinstance(expected, tuple):
            if actual not in expected:
                mismatches.append(name)
        elif actual != expected:
            mismatches.append(name)
    if set(profile.process_condition_ids) & set(conditions.excluded_process_condition_ids):
        mismatches.append("excluded_process_condition_ids")
    mismatches.extend(
        f"required_condition:{condition_id}"
        for condition_id in conditions.required_condition_ids
        if condition_id not in profile.process_condition_ids
    )
    return tuple(sorted(mismatches))


def _advisory_evidence(
    declaration: AssemblyRetentionDeclaration,
    evidence: PackageRetentionEvidence,
    ratio: ExactRetentionRatio | None,
    model: AdvisoryRetentionModel,
    *,
    inverted: bool,
) -> AdvisoryRetentionEvidence:
    if not inverted:
        return AdvisoryRetentionEvidence(
            model_id=model.model_id,
            applicability=RetentionModelApplicability.NOT_APPLICABLE,
            unmatched_condition_ids=(),
            comparison=None,
            disposition=SemanticDisposition.NOT_APPLICABLE,
        )
    mismatches = _advisory_mismatches(declaration, evidence, model)
    if ratio is None or mismatches:
        reasons = mismatches or ("mass_or_wetted_perimeter_unknown",)
        return AdvisoryRetentionEvidence(
            model_id=model.model_id,
            applicability=RetentionModelApplicability.UNVERIFIED,
            unmatched_condition_ids=reasons,
            comparison=None,
            disposition=SemanticDisposition.UNVERIFIED,
        )
    below = (
        ratio.numerator_mass_ug * model.advisory_limit_denominator
        <= model.advisory_limit_numerator_ug_per_um * ratio.denominator_wetted_perimeter_um
    )
    return AdvisoryRetentionEvidence(
        model_id=model.model_id,
        applicability=RetentionModelApplicability.MATCHED,
        unmatched_condition_ids=(),
        comparison="at_or_below_advisory_limit" if below else "above_advisory_limit",
        disposition=SemanticDisposition.ADVISORY,
    )


def _assembler_review_reasons(
    declaration: AssemblyRetentionDeclaration,
    evidence: PackageRetentionEvidence,
    rule: AssemblerRetentionRule,
) -> tuple[str, ...]:
    profile = declaration.process_profile
    review = rule.review
    bindings = {item.binding_id: item for item in declaration.evidence_bindings}
    reasons: list[str] = []
    if review.status != "active":
        reasons.append("review_status")
    if declaration.evaluation_date < review.effective_date or (
        review.expiry_date is not None and declaration.evaluation_date > review.expiry_date
    ):
        reasons.append("review_effective_dates")
    expected: tuple[tuple[str, Any, Any], ...] = (
        ("assembler_id", review.assembler_id, profile.assembler_id),
        (
            "board_layout_snapshot_fingerprint",
            review.board_layout_snapshot_fingerprint,
            declaration.board_layout_snapshot_fingerprint,
        ),
        (
            "board_netlist_snapshot_fingerprint",
            review.board_netlist_snapshot_fingerprint,
            declaration.board_netlist_snapshot_fingerprint,
        ),
        (
            "process_profile_fingerprint",
            review.process_profile_fingerprint,
            profile.semantic_fingerprint(),
        ),
        (
            "component_evidence_fingerprint",
            review.component_evidence_fingerprint,
            evidence.semantic_fingerprint(),
        ),
        ("package_family", review.package_family, evidence.package_family),
    )
    reasons.extend(name for name, actual, wanted in expected if actual != wanted)
    if not profile.evidence_binding_ids:
        reasons.append("process_profile_evidence_binding_ids")
    if not set(profile.process_condition_ids).issubset(review.covered_condition_ids):
        reasons.append("covered_process_condition_ids")
    if review.deviation_ids:
        reasons.append("review_deviation_ids")
    contexts = (
        (
            "review",
            review.source_binding_ids,
            review.semantic_fingerprint(),
            review.review_id,
        ),
        ("rule", rule.source_binding_ids, rule.semantic_fingerprint(), rule.rule_id),
        (
            "package",
            evidence.source_binding_ids,
            evidence.semantic_fingerprint(),
            evidence.evidence_id,
        ),
        (
            "process",
            profile.evidence_binding_ids,
            profile.semantic_fingerprint(),
            profile.profile_id,
        ),
    )
    required_binding_ids = {
        binding_id for _, binding_ids, _, _ in contexts for binding_id in binding_ids
    }
    if not required_binding_ids.issubset(bindings) or any(
        not _binding_is_complete(bindings[binding_id])
        for binding_id in required_binding_ids
        if binding_id in bindings
    ):
        reasons.append("pinned_applicable_reviewer_evidence")
    for context_name, binding_ids, object_fingerprint, claim_id in contexts:
        if not binding_ids or any(
            binding_id not in bindings
            or bindings[binding_id].geometry_source_fingerprint != object_fingerprint
            or bindings[binding_id].claim_id != claim_id
            for binding_id in binding_ids
        ):
            reasons.append(f"{context_name}_object_context_binding")
    review_source_digests = {
        item.local_sha256
        for binding_id in review.source_binding_ids
        if binding_id in bindings
        for item in bindings[binding_id].evidence
    }
    if review.qualification_source_sha256 not in review_source_digests:
        reasons.append("qualification_source_sha256")
    return tuple(sorted(set(reasons)))


def _assembler_evidence(
    declaration: AssemblyRetentionDeclaration,
    evidence: PackageRetentionEvidence,
    ratio: ExactRetentionRatio | None,
    rule: AssemblerRetentionRule,
    *,
    inverted: bool,
) -> AssemblerRuleEvidence:
    if not inverted:
        return AssemblerRuleEvidence(
            rule_id=rule.rule_id,
            review_id=rule.review.review_id,
            verdict=AssemblerRetentionVerdict.NOT_APPLICABLE,
            disposition=SemanticDisposition.NOT_APPLICABLE,
            reason_ids=(),
        )
    reasons = _assembler_review_reasons(declaration, evidence, rule)
    if ratio is None:
        reasons = tuple(sorted({*reasons, "mass_or_wetted_perimeter_unknown"}))
    if reasons:
        return AssemblerRuleEvidence(
            rule_id=rule.rule_id,
            review_id=rule.review.review_id,
            verdict=AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED,
            disposition=SemanticDisposition.UNVERIFIED,
            reason_ids=reasons,
        )
    assert ratio is not None
    passed = (
        ratio.numerator_mass_ug * rule.maximum_ratio_denominator
        <= rule.maximum_ratio_numerator_ug_per_um * ratio.denominator_wetted_perimeter_um
    )
    return AssemblerRuleEvidence(
        rule_id=rule.rule_id,
        review_id=rule.review.review_id,
        verdict=AssemblerRetentionVerdict.PASS if passed else AssemblerRetentionVerdict.FAIL,
        disposition=SemanticDisposition.PASS if passed else SemanticDisposition.FAIL,
        reason_ids=(),
    )


def _component_finding(
    declaration: AssemblyRetentionDeclaration, evidence: PackageRetentionEvidence
) -> ComponentRetentionFinding:
    profile = declaration.process_profile
    inverted = (
        profile.sequence == "double_reflow"
        and profile.inverted_during_second_reflow_side == evidence.side.value
    )
    ratio = _ratio(evidence) if inverted else None
    if not inverted:
        mass_status = RetentionValueStatus.NOT_APPLICABLE
        wetted_status = RetentionValueStatus.NOT_APPLICABLE
        process = SemanticDisposition.NOT_APPLICABLE
    else:
        mass_status = (
            RetentionValueStatus.KNOWN
            if evidence.component_mass_ug is not None
            else RetentionValueStatus.UNKNOWN
        )
        wetted_status = (
            RetentionValueStatus.KNOWN
            if evidence.total_wetted_perimeter_um is not None
            else RetentionValueStatus.UNKNOWN
        )
        process = SemanticDisposition.PASS
    advisories = tuple(
        _advisory_evidence(declaration, evidence, ratio, model, inverted=inverted)
        for model in declaration.advisory_models
    )
    assembler = tuple(
        _assembler_evidence(declaration, evidence, ratio, rule, inverted=inverted)
        for rule in declaration.assembler_rules
    )
    if not inverted:
        verdict = AssemblerRetentionVerdict.NOT_APPLICABLE
        final = SemanticDisposition.NOT_APPLICABLE
        kind = "not_applicable"
    elif ratio is None:
        verdict = (
            AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED
            if assembler
            else AssemblerRetentionVerdict.NOT_APPLICABLE
        )
        final = SemanticDisposition.UNVERIFIED
        kind = "missing_package_measurement"
    elif any(item.verdict is AssemblerRetentionVerdict.FAIL for item in assembler):
        verdict = AssemblerRetentionVerdict.FAIL
        final = SemanticDisposition.FAIL
        kind = "qualified_assembler_fail"
    elif assembler and all(item.verdict is AssemblerRetentionVerdict.PASS for item in assembler):
        verdict = AssemblerRetentionVerdict.PASS
        final = SemanticDisposition.PASS
        kind = "qualified_assembler_pass"
    elif assembler:
        verdict = AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED
        final = SemanticDisposition.UNVERIFIED
        kind = "process_review_required"
    elif any(item.disposition is SemanticDisposition.ADVISORY for item in advisories):
        verdict = AssemblerRetentionVerdict.NOT_APPLICABLE
        final = SemanticDisposition.ADVISORY
        kind = "advisory_comparison_only"
    else:
        verdict = AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED
        final = SemanticDisposition.UNVERIFIED
        kind = "process_review_required"
    return ComponentRetentionFinding(
        component_reference=evidence.component_reference,
        side=evidence.side,
        inverted_during_second_reflow=inverted,
        process_applicability=process,
        mass_status=mass_status,
        wetted_perimeter_status=wetted_status,
        ratio=ratio,
        advisory_evidence=advisories,
        assembler_evidence=assembler,
        assembler_verdict=verdict,
        final_disposition=final,
        final_finding_kind=kind,
    )


def rederive_assembly_retention(declaration: AssemblyRetentionDeclaration) -> dict[str, Any]:
    findings = tuple(_component_finding(declaration, item) for item in declaration.package_evidence)
    return {
        "inventory_scope": (
            "declared_complete_whole_board_component_inventory"
            if declaration.whole_board_component_inventory_declared
            else "declared_component_scope_only_not_whole_board"
        ),
        "excluded_claims": _EXCLUDED_CLAIMS,
        "component_findings": findings,
        "component_findings_fingerprint": fingerprint(
            [item.model_dump(mode="json") for item in findings]
        ),
    }


def evaluate_assembly_retention(
    layout: BoardLayout,
    netlist: BoardNetlist,
    declaration: AssemblyRetentionDeclaration,
) -> AssemblyRetentionResult:
    """Evaluate retained facts without mutating or inferring from caller objects."""

    layout_before = canonical_board_layout_snapshot_json(layout)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)
    if layout_before != declaration.board_layout_snapshot_json:
        raise ValueError("caller BoardLayout differs from the declaration snapshot")
    if netlist_before != declaration.board_netlist_snapshot_json:
        raise ValueError("caller BoardNetlist differs from the declaration snapshot")
    derived = rederive_assembly_retention(declaration)
    if canonical_board_layout_snapshot_json(layout) != layout_before:
        raise RuntimeError("assembly retention evaluator mutated caller BoardLayout")
    if canonical_board_netlist_snapshot_json(netlist) != netlist_before:
        raise RuntimeError("assembly retention evaluator mutated caller BoardNetlist")
    fields: dict[str, Any] = {"declaration": declaration, **derived}
    provisional = AssemblyRetentionResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return AssemblyRetentionResult(**fields, result_fingerprint=result_fp)
