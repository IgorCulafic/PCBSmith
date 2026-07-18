"""Exact sourced switch-node copper-area limit comparator."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from pcbsmith.routed_copper_graph_ir import ExactRational, fingerprint
from pcbsmith.semantic_ir import SemanticDisposition, SemanticVerification
from pcbsmith.switch_node_area_policy_ir import (
    SwitchNodeAreaLimitPolicy,
    SwitchNodeAreaPolicyResult,
    switch_node_area_policy_context_fingerprint,
)
from pcbsmith.switch_node_copper_ir import SwitchNodeCopperUnionResult

# A retained, integer-only enclosure based on 20 verified decimal places of pi.
# The kernel identifier makes changing either bound a schema-visible event.
PI_ENCLOSURE_KERNEL_ID = "pcbsmith-pi-enclosure-decimal20-v1"
PI_LOWER = Fraction(314159265358979323846, 10**20)
PI_UPPER = Fraction(314159265358979323847, 10**20)


def _rat(value: Fraction) -> ExactRational:
    return ExactRational.build(value)


def _authority_reasons(
    union: SwitchNodeCopperUnionResult,
    policy: SwitchNodeAreaLimitPolicy,
    context_fingerprint: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if policy.maximum_area_mm2 is None:
        reasons.append("hard_limit_threshold_missing")
    binding = policy.applicability_binding
    if binding is None:
        reasons.append("hard_limit_evidence_missing")
        return tuple(sorted(reasons))
    if binding.claim_id != policy.limit_id:
        reasons.append("hard_limit_claim_identity_mismatch")
    if (
        not binding.required_conditions
        or binding.unmatched_conditions
        or set(binding.matched_conditions) != set(binding.required_conditions)
        or binding.reviewer_record_id is None
    ):
        reasons.append("hard_limit_applicability_incomplete")
    if binding.geometry_source_fingerprint != context_fingerprint:
        reasons.append("hard_limit_context_fingerprint_mismatch")
    if not all(
        evidence.source_status == "pinned"
        and evidence.local_sha256 is not None
        and evidence.locator_status in {"text_verified", "figure_verified"}
        and evidence.applicability_status == "confirmed"
        for evidence in binding.evidence
    ):
        reasons.append("hard_limit_evidence_not_pinned_verified_applicable")
    return tuple(sorted(reasons))


def _area_bounds(union: SwitchNodeCopperUnionResult) -> tuple[Fraction, Fraction]:
    assert union.rational_mm2 is not None
    assert union.pi_coefficient_mm2 is not None
    rational = union.rational_mm2.fraction()
    coefficient = union.pi_coefficient_mm2.fraction()
    endpoints = (rational + coefficient * PI_LOWER, rational + coefficient * PI_UPPER)
    return min(endpoints), max(endpoints)


def rederive_switch_node_area_policy(
    union_result: SwitchNodeCopperUnionResult,
    limit_policy: SwitchNodeAreaLimitPolicy,
) -> dict[str, Any]:
    union = SwitchNodeCopperUnionResult.model_validate_json(union_result.model_dump_json())
    policy = SwitchNodeAreaLimitPolicy.model_validate_json(limit_policy.model_dump_json())
    context_fp = switch_node_area_policy_context_fingerprint(
        union,
        limit_id=policy.limit_id,
        mode=policy.mode,
        maximum_area_mm2=policy.maximum_area_mm2,
    )
    binding_fp = (
        None
        if policy.applicability_binding is None
        else policy.applicability_binding.semantic_fingerprint()
    )
    reasons: list[str] = []
    violations: list[str] = []
    lower: ExactRational | None = None
    upper: ExactRational | None = None

    exact_metric = (
        union.verification is SemanticVerification.EXACT
        and union.rational_mm2 is not None
        and union.pi_coefficient_mm2 is not None
        and all(
            item.verification is SemanticVerification.EXACT
            and item.rational_mm2 is not None
            and item.pi_coefficient_mm2 is not None
            for item in union.per_layer_areas
        )
    )
    if not exact_metric:
        reasons.extend(union.unknown_reasons or ("switch_node_union_not_exact",))
        comparator = "unsupported_metric"
        disposition = SemanticDisposition.UNVERIFIED
    else:
        lower_value, upper_value = _area_bounds(union)
        lower, upper = _rat(lower_value), _rat(upper_value)
        if policy.mode == "advisory":
            comparator = "advisory_not_applied"
            disposition = SemanticDisposition.ADVISORY
        else:
            authority_reasons = _authority_reasons(union, policy, context_fp)
            if authority_reasons:
                reasons.extend(authority_reasons)
                comparator = "authority_unverified"
                disposition = SemanticDisposition.UNVERIFIED
            else:
                assert policy.maximum_area_mm2 is not None
                maximum = policy.maximum_area_mm2.fraction()
                if upper_value <= maximum:
                    comparator = "within_limit"
                    disposition = SemanticDisposition.PASS
                elif lower_value > maximum:
                    comparator = "exceeds_limit"
                    disposition = SemanticDisposition.FAIL
                    violations.append("maximum_switch_node_area_exceeded")
                else:
                    comparator = "indeterminate_enclosure"
                    disposition = SemanticDisposition.UNVERIFIED
                    reasons.append("pi_enclosure_comparison_indeterminate")

    policy_fp = policy.semantic_fingerprint()
    input_fp = fingerprint(
        {
            "union_result_fingerprint": union.result_fingerprint,
            "union_evidence_fingerprint": union.evidence_fingerprint,
            "policy_fingerprint": policy_fp,
            "context_fingerprint": context_fp,
            "pi_enclosure_kernel_id": PI_ENCLOSURE_KERNEL_ID,
            "pi_lower": _rat(PI_LOWER).model_dump(mode="json"),
            "pi_upper": _rat(PI_UPPER).model_dump(mode="json"),
        }
    )
    return {
        "metric_verification": union.verification,
        "pi_enclosure_kernel_id": PI_ENCLOSURE_KERNEL_ID,
        "pi_lower_bound": _rat(PI_LOWER) if exact_metric else None,
        "pi_upper_bound": _rat(PI_UPPER) if exact_metric else None,
        "area_lower_bound_mm2": lower,
        "area_upper_bound_mm2": upper,
        "comparator_disposition": comparator,
        "disposition": disposition,
        "violation_ids": tuple(sorted(violations)),
        "unverified_reasons": tuple(sorted(set(reasons))),
        "union_result_fingerprint": union.result_fingerprint,
        "union_evidence_fingerprint": union.evidence_fingerprint,
        "policy_fingerprint": policy_fp,
        "evidence_binding_fingerprint": binding_fp,
        "context_fingerprint": context_fp,
        "input_fingerprint": input_fp,
    }


def evaluate_switch_node_area_policy(
    union: SwitchNodeCopperUnionResult,
    policy: SwitchNodeAreaLimitPolicy,
) -> SwitchNodeAreaPolicyResult:
    derived = rederive_switch_node_area_policy(union, policy)
    fields = {"union": union, "policy": policy, **derived}
    provisional = SwitchNodeAreaPolicyResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return SwitchNodeAreaPolicyResult(**fields, result_fingerprint=result_fp)
