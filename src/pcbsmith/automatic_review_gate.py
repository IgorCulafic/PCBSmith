"""W9 exact visual/marking gate and repair-proposal boundary."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.review.visual_package import VisualReviewManifest
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class ProductionMarkingAudit(SemanticIrModel):
    """Exact non-raster marking findings for one saved board."""

    schema_id: Literal["pcbsmith-production-marking-audit"] = "pcbsmith-production-marking-audit"
    schema_version: Literal[1] = 1
    board_sha256: str
    drc_report_sha256: str
    requirements_fingerprint: str
    inventory_fingerprint: str
    inspected_mark_count: int = Field(ge=0)
    unverified_check_ids: tuple[str, ...] = ()
    silk_over_copper_finding_ids: tuple[str, ...] = ()
    silk_over_silk_finding_ids: tuple[str, ...] = ()
    silk_edge_finding_ids: tuple[str, ...] = ()
    courtyard_finding_ids: tuple[str, ...] = ()
    missing_polarity_finding_ids: tuple[str, ...] = ()
    missing_refdes_finding_ids: tuple[str, ...] = ()
    connector_mating_visibility_finding_ids: tuple[str, ...] = ()
    evidence_fingerprint: str

    @model_validator(mode="after")
    def audit_is_bound(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.drc_report_sha256, "drc_report_sha256")
        require_sha256(self.requirements_fingerprint, "requirements_fingerprint")
        require_sha256(self.inventory_fingerprint, "inventory_fingerprint")
        unverified = tuple(sorted(self.unverified_check_ids))
        if len(unverified) != len(set(unverified)):
            raise ValueError("unverified marking checks must be unique")
        object.__setattr__(self, "unverified_check_ids", unverified)
        for name in self.finding_fields():
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique findings")
            object.__setattr__(self, name, values)
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != fingerprint(payload):
            raise ValueError("production marking evidence is stale")
        return self

    @classmethod
    def finding_fields(cls) -> tuple[str, ...]:
        return (
            "silk_over_copper_finding_ids",
            "silk_over_silk_finding_ids",
            "silk_edge_finding_ids",
            "courtyard_finding_ids",
            "missing_polarity_finding_ids",
            "missing_refdes_finding_ids",
            "connector_mating_visibility_finding_ids",
        )

    @classmethod
    def build(cls, **values: Any) -> ProductionMarkingAudit:
        fields = dict(values)
        for name in cls.finding_fields():
            fields[name] = tuple(sorted(fields.get(name, ())))
        provisional = cls.model_construct(**fields, evidence_fingerprint="0" * 64)
        return cls(
            **fields,
            evidence_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
            ),
        )

    @property
    def finding_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item for name in self.finding_fields() for item in getattr(self, name)))


class AutomaticReviewGate(SemanticIrModel):
    schema_id: Literal["pcbsmith-automatic-review-gate"] = "pcbsmith-automatic-review-gate"
    schema_version: Literal[1] = 1
    board_sha256: str
    stage: Literal["final"] = "final"
    marking_audit: ProductionMarkingAudit
    visual_manifest_fingerprint: str
    required_artifact_ids: tuple[str, ...]
    generated_artifact_ids: tuple[str, ...]
    triggered_artifact_ids: tuple[str, ...]
    proposed_repair_request_fingerprints: tuple[str, ...]
    exact_gate_passed: bool
    visual_package_complete: bool
    accepted: bool
    blocker_ids: tuple[str, ...]
    result_fingerprint: str

    @model_validator(mode="after")
    def review_is_bound_and_fail_closed(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.visual_manifest_fingerprint, "visual_manifest_fingerprint")
        if self.marking_audit.board_sha256 != self.board_sha256:
            raise ValueError("marking and review evidence target different board revisions")
        for name in (
            "required_artifact_ids",
            "generated_artifact_ids",
            "triggered_artifact_ids",
            "proposed_repair_request_fingerprints",
            "blocker_ids",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique identities")
            object.__setattr__(self, name, values)
        for value in self.proposed_repair_request_fingerprints:
            require_sha256(value, "proposed_repair_request_fingerprints")
        expected_visual = set(self.required_artifact_ids).issubset(self.generated_artifact_ids)
        expected_exact = (
            self.marking_audit.inspected_mark_count > 0
            and not self.marking_audit.finding_ids
            and not self.marking_audit.unverified_check_ids
        )
        expected_accepted = expected_visual and expected_exact and not self.blocker_ids
        if self.visual_package_complete != expected_visual:
            raise ValueError("visual package completeness is stale")
        if self.exact_gate_passed != expected_exact:
            raise ValueError("exact marking gate disposition is stale")
        if self.accepted != expected_accepted:
            raise ValueError("automatic review acceptance is stale")
        if self.proposed_repair_request_fingerprints and not self.marking_audit.finding_ids:
            raise ValueError("visual review cannot propose repair without an exact finding")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        require_sha256(self.result_fingerprint, "result_fingerprint")
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("automatic review result is stale")
        return self


CANONICAL_FINAL_ARTIFACT_IDS = (
    "2d:front-design:png",
    "2d:back-design:png",
    "2d:front-copper:png",
    "2d:back-copper:png",
    "2d:combined-copper:png",
)


def qualify_automatic_review(
    *,
    manifest: VisualReviewManifest,
    manifest_fingerprint: str,
    marking_audit: ProductionMarkingAudit,
    proposed_repair_request_fingerprints: tuple[str, ...] = (),
) -> AutomaticReviewGate:
    """Bind canonical and triggered views to exact marking evidence.

    A raster observation may request a repair only when an exact marking audit
    has produced a finding.  This function never mutates the board.
    """

    require_sha256(manifest_fingerprint, "manifest_fingerprint")
    if manifest.stage != "final":
        raise ValueError("automatic release review requires the final-stage package")

    triggered = tuple(
        sorted(
            item.artifact_id
            for item in manifest.artifacts
            if item.artifact_id.startswith("detail:") or item.artifact_id.startswith("diagnostic:")
        )
    )
    required = tuple(sorted(set(CANONICAL_FINAL_ARTIFACT_IDS) | set(triggered)))
    generated = tuple(
        sorted(
            item.artifact_id
            for item in manifest.artifacts
            if item.state == "generated" and item.sha256 is not None
        )
    )
    blockers = [f"production_marking:{item}" for item in marking_audit.finding_ids]
    blockers.extend(
        f"production_marking_unverified:{item}" for item in marking_audit.unverified_check_ids
    )
    blockers.extend(
        f"missing_review_artifact:{item}" for item in sorted(set(required) - set(generated))
    )
    artifact_by_id = {item.artifact_id: item for item in manifest.artifacts}
    for artifact_id in required:
        artifact = artifact_by_id.get(artifact_id)
        if artifact is None or artifact.state != "generated":
            continue
        if artifact.inspection == "uninspected":
            blockers.append(f"visual_inspection_unverified:{artifact_id}")
        elif artifact.inspection == "attention_required":
            blockers.append(f"visual_inspection:{artifact_id}")
    if manifest.model_preflight_status != "passed":
        blockers.append(f"model_preflight:{manifest.model_preflight_status}")
    if manifest.workflow_conformance_status == "not_evaluated":
        blockers.append("visual_workflow_unverified:not_evaluated")
    elif manifest.workflow_conformance_status == "nonconformant":
        blockers.append("visual_workflow:nonconformant")
    if manifest.package_status == "generated_pending_inspection":
        blockers.append("visual_package_unverified:generated_pending_inspection")
    elif manifest.package_status in {"generation_failed", "attention_required"}:
        blockers.append(f"visual_package:{manifest.package_status}")
    elif manifest.package_status == "accepted" and any(
        artifact_by_id.get(artifact_id) is None
        or artifact_by_id[artifact_id].state != "generated"
        or artifact_by_id[artifact_id].inspection != "accepted"
        for artifact_id in required
    ):
        blockers.append("visual_package:accepted_status_inconsistent")
    if manifest.board_sha256 != marking_audit.board_sha256:
        blockers.append("review_board_hash_mismatch")
    exact_pass = (
        marking_audit.inspected_mark_count > 0
        and not marking_audit.finding_ids
        and not marking_audit.unverified_check_ids
    )
    visual_complete = set(required).issubset(generated)
    values: dict[str, Any] = {
        "board_sha256": marking_audit.board_sha256,
        "marking_audit": marking_audit,
        "visual_manifest_fingerprint": manifest_fingerprint,
        "required_artifact_ids": required,
        "generated_artifact_ids": generated,
        "triggered_artifact_ids": triggered,
        "proposed_repair_request_fingerprints": tuple(sorted(proposed_repair_request_fingerprints)),
        "exact_gate_passed": exact_pass,
        "visual_package_complete": visual_complete,
        "accepted": exact_pass and visual_complete and not blockers,
        "blocker_ids": tuple(sorted(blockers)),
    }
    provisional = AutomaticReviewGate.model_construct(**values, result_fingerprint="0" * 64)
    return AutomaticReviewGate(
        **values,
        result_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"result_fingerprint"})
        ),
    )


__all__ = [
    "AutomaticReviewGate",
    "CANONICAL_FINAL_ARTIFACT_IDS",
    "ProductionMarkingAudit",
    "qualify_automatic_review",
]
