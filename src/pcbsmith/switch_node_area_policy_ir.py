"""Sourced policy evidence for the restricted switch-node copper-area metric.

This schema is deliberately limited to comparing the already-derived planar
copper union with a sourced area limit.  It makes no electromagnetic, thermal,
current-capacity, exclusion, or copper-mutation claim.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import field_validator, model_validator

from pcbsmith.routed_copper_graph_ir import (
    ExactRational,
    fingerprint,
    require_identity,
    require_sha256,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticIrModel,
    SemanticVerification,
)
from pcbsmith.switch_node_copper_ir import SwitchNodeCopperUnionResult


class SwitchNodeAreaLimitPolicy(SemanticIrModel):
    schema_id: Literal["pcbsmith-switch-node-area-limit-policy"] = (
        "pcbsmith-switch-node-area-limit-policy"
    )
    schema_version: Literal[1] = 1
    limit_id: str
    mode: Literal["advisory", "sourced_hard"]
    maximum_area_mm2: ExactRational | None
    applicability_binding: EvidenceApplicabilityBinding | None

    @model_validator(mode="after")
    def policy_is_typed(self) -> Self:
        require_identity(self.limit_id, "limit_id")
        if self.maximum_area_mm2 is not None and self.maximum_area_mm2.fraction() < 0:
            raise ValueError("switch-node maximum area cannot be negative")
        if self.mode == "advisory" and self.applicability_binding is not None:
            raise ValueError("advisory limits cannot carry sourced-hard authority")
        return self


def switch_node_area_policy_context_fingerprint(
    union: SwitchNodeCopperUnionResult,
    *,
    limit_id: str,
    mode: str,
    maximum_area_mm2: ExactRational | None,
) -> str:
    """Bind a limit to the complete replayed union and its explicit scope."""

    require_identity(limit_id, "limit_id")
    return fingerprint(
        {
            "schema_id": "pcbsmith-switch-node-area-policy-context",
            "schema_version": 1,
            "union_result_fingerprint": union.result_fingerprint,
            "union_evidence_fingerprint": union.evidence_fingerprint,
            "declaration": union.declaration.model_dump(mode="json"),
            "net_names": union.declaration.net_names,
            "layers": union.declaration.layers,
            "source_coverage_ids": union.source_coverage_ids,
            "per_layer_areas": [item.model_dump(mode="json") for item in union.per_layer_areas],
            "rational_mm2": (
                None if union.rational_mm2 is None else union.rational_mm2.model_dump(mode="json")
            ),
            "pi_coefficient_mm2": (
                None
                if union.pi_coefficient_mm2 is None
                else union.pi_coefficient_mm2.model_dump(mode="json")
            ),
            "limit_id": limit_id,
            "mode": mode,
            "maximum_area_mm2": (
                None if maximum_area_mm2 is None else maximum_area_mm2.model_dump(mode="json")
            ),
        }
    )


class SwitchNodeAreaPolicyResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-switch-node-area-policy-result"] = (
        "pcbsmith-switch-node-area-policy-result"
    )
    schema_version: Literal[1] = 1
    scope_statement: Literal[
        "sourced planar copper-area policy only; no electromagnetic, thermal, "
        "current-capacity, exclusion, or mutation claim"
    ] = (
        "sourced planar copper-area policy only; no electromagnetic, thermal, "
        "current-capacity, exclusion, or mutation claim"
    )
    union: SwitchNodeCopperUnionResult
    policy: SwitchNodeAreaLimitPolicy
    metric_verification: SemanticVerification
    pi_enclosure_kernel_id: str
    pi_lower_bound: ExactRational | None
    pi_upper_bound: ExactRational | None
    area_lower_bound_mm2: ExactRational | None
    area_upper_bound_mm2: ExactRational | None
    comparator_disposition: Literal[
        "unsupported_metric",
        "advisory_not_applied",
        "authority_unverified",
        "within_limit",
        "exceeds_limit",
        "indeterminate_enclosure",
    ]
    disposition: SemanticDisposition
    violation_ids: tuple[str, ...]
    unverified_reasons: tuple[str, ...]
    union_result_fingerprint: str
    union_evidence_fingerprint: str
    policy_fingerprint: str
    evidence_binding_fingerprint: str | None
    context_fingerprint: str
    input_fingerprint: str
    result_fingerprint: str

    @field_validator(
        "union_result_fingerprint",
        "union_evidence_fingerprint",
        "policy_fingerprint",
        "context_fingerprint",
        "input_fingerprint",
        "result_fingerprint",
    )
    @classmethod
    def digest_is_valid(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @field_validator("pi_enclosure_kernel_id")
    @classmethod
    def kernel_identity_is_valid(cls, value: str) -> str:
        return require_identity(value, "pi_enclosure_kernel_id")

    @field_validator("evidence_binding_fingerprint")
    @classmethod
    def optional_digest_is_valid(cls, value: str | None) -> str | None:
        return None if value is None else require_sha256(value, "evidence_binding_fingerprint")

    @model_validator(mode="after")
    def result_replays(self) -> Self:
        from pcbsmith.kicad.switch_node_area_policy import rederive_switch_node_area_policy

        expected = rederive_switch_node_area_policy(self.union, self.policy)
        compared = (
            "metric_verification",
            "pi_enclosure_kernel_id",
            "pi_lower_bound",
            "pi_upper_bound",
            "area_lower_bound_mm2",
            "area_upper_bound_mm2",
            "comparator_disposition",
            "disposition",
            "violation_ids",
            "unverified_reasons",
            "union_result_fingerprint",
            "union_evidence_fingerprint",
            "policy_fingerprint",
            "evidence_binding_fingerprint",
            "context_fingerprint",
            "input_fingerprint",
        )
        if any(getattr(self, name) != expected[name] for name in compared):
            raise ValueError("switch-node area policy result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("switch-node area policy result fingerprint is stale")
        return self
