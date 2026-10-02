"""Exact read-back parity and bounded review burden for routed candidates."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board_failure_classifier import BoardFailureClassification
from pcbsmith.semantic_ir import SemanticIrModel


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _sha(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


class RoutedCandidateParity(SemanticIrModel):
    schema_id: Literal["pcbsmith-routed-candidate-parity"] = "pcbsmith-routed-candidate-parity"
    schema_version: Literal[1] = 1
    footprint_pose_equal: bool
    pad_binding_equal: bool
    edge_geometry_equal: bool
    count_fields_equal: bool
    mismatch_ids: tuple[str, ...]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        mismatches = tuple(sorted(self.mismatch_ids))
        expected = tuple(
            name
            for name, equal in (
                ("edge_geometry", self.edge_geometry_equal),
                ("footprint_pose", self.footprint_pose_equal),
                ("item_counts", self.count_fields_equal),
                ("pad_binding", self.pad_binding_equal),
            )
            if not equal
        )
        if mismatches != expected:
            raise ValueError("parity mismatch identities are stale")
        object.__setattr__(self, "mismatch_ids", mismatches)
        return self


class ManualRepairBurden(SemanticIrModel):
    schema_id: Literal["pcbsmith-manual-repair-burden"] = "pcbsmith-manual-repair-burden"
    schema_version: Literal[1] = 1
    open_finding_count: int = Field(ge=0)
    violation_finding_count: int = Field(ge=0)
    parity_finding_count: int = Field(ge=0)
    continuity_finding_count: int = Field(ge=0)
    width_neckdown_segment_count: int = Field(ge=0)
    unresolved_work_item_count: int = Field(ge=0)
    scope: Literal[
        "deterministic unresolved finding count; not a labor-time or repair-action estimate"
    ] = "deterministic unresolved finding count; not a labor-time or repair-action estimate"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        expected = (
            self.open_finding_count
            + self.violation_finding_count
            + self.parity_finding_count
            + self.continuity_finding_count
            + self.width_neckdown_segment_count
        )
        if self.unresolved_work_item_count != expected:
            raise ValueError("manual-repair burden total is stale")
        return self


class RoutingCandidateQualification(SemanticIrModel):
    schema_id: Literal["pcbsmith-routing-candidate-qualification"] = (
        "pcbsmith-routing-candidate-qualification"
    )
    schema_version: Literal[1] = 1
    case_id: str
    placement_source_board_sha256: str
    routed_source_board_sha256: str
    routed_observed_board_sha256: str
    route_evidence_bound: bool
    classification_fingerprint: str
    parity: RoutedCandidateParity
    reference_continuity_disposition: str
    reference_continuity_exact_pass_authorized: bool
    automatic_multilayer_pass_prohibited: Literal[True] = True
    visual_evidence_status: Literal["revision_bound", "present_unbound", "absent"]
    manual_repair_burden: ManualRepairBurden
    release_qualified: bool
    blockers: tuple[str, ...]
    qualification_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        for name in (
            "placement_source_board_sha256",
            "routed_source_board_sha256",
            "routed_observed_board_sha256",
            "classification_fingerprint",
            "qualification_fingerprint",
        ):
            _sha(getattr(self, name), name)
        blockers = tuple(sorted(self.blockers))
        expected_reference_pass = (
            self.reference_continuity_disposition
            == "exact_geometric_continuity_observed"
        )
        if self.reference_continuity_exact_pass_authorized != expected_reference_pass:
            raise ValueError("reference-continuity exact authority is stale")
        if self.release_qualified != (not blockers):
            raise ValueError("release qualification disposition is stale")
        payload = self.model_dump(mode="json", exclude={"qualification_fingerprint"})
        if self.qualification_fingerprint != _fingerprint(payload):
            raise ValueError("qualification fingerprint is stale")
        object.__setattr__(self, "blockers", blockers)
        return self


def _identity(raw: dict[str, object]) -> dict[str, object]:
    identity = raw.get("board_identity")
    if not isinstance(identity, dict):
        raise TypeError("physical observation lacks board_identity")
    return identity


def qualify_routed_candidate(
    *,
    case_id: str,
    placement_source_board_sha256: str,
    routed_source_board_sha256: str,
    routed_observed_board_sha256: str,
    baseline_observation: dict[str, object],
    routed_observation: dict[str, object],
    classification: BoardFailureClassification,
    route_evidence: dict[str, object],
    visual_evidence_status: Literal["revision_bound", "present_unbound", "absent"],
) -> RoutingCandidateQualification:
    """Bind exact invariant parity to DRC and explicitly non-exact continuity evidence."""

    baseline = _identity(baseline_observation)
    routed = _identity(routed_observation)
    pose_equal = baseline.get("footprint_pose_fingerprint") == routed.get(
        "footprint_pose_fingerprint"
    )
    pad_equal = baseline.get("pad_binding_fingerprint") == routed.get("pad_binding_fingerprint")
    edge_equal = baseline.get("edge_geometry_fingerprint") == routed.get(
        "edge_geometry_fingerprint"
    )
    count_equal = all(
        baseline.get(name) == routed.get(name)
        for name in ("footprint_count", "pad_count", "edge_item_count")
    )
    mismatch_ids = tuple(
        name
        for name, equal in (
            ("edge_geometry", edge_equal),
            ("footprint_pose", pose_equal),
            ("item_counts", count_equal),
            ("pad_binding", pad_equal),
        )
        if not equal
    )
    parity = RoutedCandidateParity(
        footprint_pose_equal=pose_equal,
        pad_binding_equal=pad_equal,
        edge_geometry_equal=edge_equal,
        count_fields_equal=count_equal,
        mismatch_ids=mismatch_ids,
    )
    continuity = routed_observation.get("reference_continuity", {})
    if not isinstance(continuity, dict):
        raise TypeError("physical observation lacks reference_continuity")
    continuity_findings = continuity.get("findings", [])
    if not isinstance(continuity_findings, list):
        raise TypeError("reference continuity findings must be a list")
    continuity_total = (
        int(continuity.get("sample_unsupported_segment_count", 0))
        + int(continuity.get("transition_without_nearby_reference_via_count", 0))
        if (
            "sample_unsupported_segment_count" in continuity
            or "transition_without_nearby_reference_via_count" in continuity
        )
        else len(continuity_findings)
    )
    widths = route_evidence.get("widths", {})
    width_report = widths.get("report", {}) if isinstance(widths, dict) else {}
    nets = width_report.get("nets", {}) if isinstance(width_report, dict) else {}
    if not isinstance(nets, dict):
        raise TypeError("route width report nets must be a mapping")
    neckdowns = sum(
        int(item.get("narrower_segment_count", 0))
        for item in nets.values()
        if isinstance(item, dict)
    )
    burden = ManualRepairBurden(
        open_finding_count=classification.observed_unconnected_count,
        violation_finding_count=classification.observed_violation_count,
        parity_finding_count=len(parity.mismatch_ids),
        continuity_finding_count=continuity_total,
        width_neckdown_segment_count=neckdowns,
        unresolved_work_item_count=(
            classification.observed_unconnected_count
            + classification.observed_violation_count
            + len(parity.mismatch_ids)
            + continuity_total
            + neckdowns
        ),
    )
    route_evidence_bound = route_evidence.get("routed_board_sha256") == routed_source_board_sha256
    blockers: list[str] = []
    if not route_evidence_bound:
        blockers.append("route_evidence_hash_mismatch")
    if classification.observed_unconnected_count:
        blockers.append("kicad_unconnected_items")
    if classification.observed_violation_count:
        blockers.append("kicad_violations")
    if parity.mismatch_ids:
        blockers.append("protected_board_identity_changed")
    reference_pass = bool(continuity.get("exact_pass_authorized", False)) and (
        continuity.get("disposition") == "exact_geometric_continuity_observed"
    )
    if continuity.get("signal_segment_count", 0) and not reference_pass:
        blockers.append("reference_continuity_exact_unverified")
    if visual_evidence_status != "revision_bound":
        blockers.append("visual_evidence_not_revision_bound")
    payload: dict[str, object] = {
        "schema_id": "pcbsmith-routing-candidate-qualification",
        "schema_version": 1,
        "case_id": case_id,
        "placement_source_board_sha256": placement_source_board_sha256,
        "routed_source_board_sha256": routed_source_board_sha256,
        "routed_observed_board_sha256": routed_observed_board_sha256,
        "route_evidence_bound": route_evidence_bound,
        "classification_fingerprint": classification.classification_fingerprint,
        "parity": parity.model_dump(mode="json"),
        "reference_continuity_disposition": str(continuity.get("disposition", "unverified")),
        "reference_continuity_exact_pass_authorized": reference_pass,
        "automatic_multilayer_pass_prohibited": True,
        "visual_evidence_status": visual_evidence_status,
        "manual_repair_burden": burden.model_dump(mode="json"),
        "release_qualified": not blockers,
        "blockers": sorted(blockers),
    }
    payload["qualification_fingerprint"] = _fingerprint(payload)
    return RoutingCandidateQualification.model_validate(payload)
