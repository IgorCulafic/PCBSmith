"""Deterministic, exactly legalized placement candidate generation for R5.2."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from itertools import combinations
from typing import Protocol

from pcbsmith.kicad.board import BoardLayout, placement_rotation, placement_y
from pcbsmith.kicad.placement_routability import (
    PlacementProbe,
    board_layout_fingerprint,
    build_placement_probe,
    legalize_placement_probe,
)
from pcbsmith.placement_candidate_ir import (
    PlacementCandidateDisposition,
    PlacementCandidateRecord,
    PlacementCandidateSearchResult,
    PlacementCandidateTelemetry,
    PlacementCandidateTerminalReason,
    PlacementMoveClause,
    PlacementMoveKind,
    PlacementMovePolicy,
    PlacementProposalKind,
    PlacementProposalProvenance,
    PlacementSurrogateEvidence,
    placement_candidate_fingerprint,
)
from pcbsmith.placement_ir import (
    ComponentPose,
    PlacementBudget,
    PlacementGeometryCatalog,
    PlacementLegalizationOutcome,
    PlacementLegalizationPolicy,
    PlacementLegalizationResult,
    PlacementProbePolicy,
    placement_pose_set_fingerprint,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


class PlacementSurrogateEvaluator(Protocol):
    """Temporary typed R5.2 callback seam, before R5.3 metric implementation."""

    def __call__(
        self,
        probe: PlacementProbe,
        legalization_result: PlacementLegalizationResult,
    ) -> PlacementSurrogateEvidence: ...


@dataclass(frozen=True)
class PlacementCandidateSearch:
    """Semantic result plus the lossless materialized probes in candidate order."""

    result: PlacementCandidateSearchResult
    probes: tuple[PlacementProbe, ...]

    def __post_init__(self) -> None:
        if len(self.probes) != len(self.result.candidates):
            raise ValueError("probe count does not match semantic candidates")
        for candidate, probe in zip(self.result.candidates, self.probes, strict=True):
            if candidate.probe_layout_fingerprint != board_layout_fingerprint(probe.layout):
                raise ValueError("candidate probe fingerprint is stale")


def _profile_fingerprint(profile: PcbRuleProfile) -> str:
    payload = {
        "schema_id": "pcbsmith-placement-candidate-profile",
        "schema_version": 1,
        "profile": profile.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class _Proposal:
    poses: tuple[ComponentPose, ...]
    provenance: PlacementProposalProvenance


def _base_poses(template: BoardLayout) -> tuple[ComponentPose, ...]:
    references = tuple(component.reference for component, _x in template.placements)
    if not references or len(set(references)) != len(references):
        raise ValueError("template placements must contain unique references")
    flip = set(template.part_flip)
    if not flip <= set(references):
        raise ValueError("template flip declarations reference unknown components")
    return tuple(
        sorted(
            (
                ComponentPose(
                    reference=component.reference,
                    x_mm=x_mm,
                    y_mm=placement_y(template, component.reference),
                    rotation_deg=placement_rotation(template, component.reference),
                    side="back" if component.reference in flip else "front",
                )
                for component, x_mm in template.placements
            ),
            key=lambda pose: pose.reference,
        )
    )


def _single_clauses(
    pose_by_ref: dict[str, ComponentPose],
    policy: PlacementMovePolicy,
) -> dict[str, tuple[PlacementMoveClause, ...]]:
    by_ref: dict[str, list[PlacementMoveClause]] = {
        reference: []
        for reference in sorted(
            set(policy.movable_references)
            | set(policy.rotatable_references)
            | set(policy.flippable_references)
        )
    }
    for reference in policy.movable_references:
        for step in range(1, policy.maximum_translation_steps + 1):
            distance = policy.translation_step_mm * step
            for dx, dy in ((-distance, 0.0), (distance, 0.0), (0.0, -distance), (0.0, distance)):
                by_ref[reference].append(
                    PlacementMoveClause(
                        reference=reference,
                        kind=PlacementMoveKind.TRANSLATE,
                        delta_x_mm=dx,
                        delta_y_mm=dy,
                    )
                )
    for reference in policy.rotatable_references:
        for rotation in policy.allowed_rotation_deg:
            by_ref[reference].append(
                PlacementMoveClause(
                    reference=reference,
                    kind=PlacementMoveKind.ROTATE,
                    rotation_deg=rotation,
                )
            )
    for reference in policy.flippable_references:
        by_ref[reference].append(
            PlacementMoveClause(
                reference=reference,
                kind=PlacementMoveKind.FLIP,
                side="back" if pose_by_ref[reference].side == "front" else "front",
            )
        )
    return {reference: tuple(clauses) for reference, clauses in by_ref.items()}


def _apply_clauses(
    base: tuple[ComponentPose, ...], clauses: tuple[PlacementMoveClause, ...]
) -> tuple[ComponentPose, ...]:
    clause_by_ref = {clause.reference: clause for clause in clauses}
    if len(clause_by_ref) != len(clauses):
        raise ValueError("one proposal cannot apply multiple clauses to one component")
    result: list[ComponentPose] = []
    for pose in base:
        clause = clause_by_ref.get(pose.reference)
        if clause is None:
            result.append(pose)
        elif clause.kind is PlacementMoveKind.TRANSLATE:
            assert clause.delta_x_mm is not None and clause.delta_y_mm is not None
            result.append(
                ComponentPose(
                    reference=pose.reference,
                    x_mm=pose.x_mm + clause.delta_x_mm,
                    y_mm=pose.y_mm + clause.delta_y_mm,
                    rotation_deg=pose.rotation_deg,
                    side=pose.side,
                )
            )
        elif clause.kind is PlacementMoveKind.ROTATE:
            assert clause.rotation_deg is not None
            result.append(
                ComponentPose(
                    reference=pose.reference,
                    x_mm=pose.x_mm,
                    y_mm=pose.y_mm,
                    rotation_deg=clause.rotation_deg,
                    side=pose.side,
                )
            )
        else:
            assert clause.side is not None
            result.append(
                ComponentPose(
                    reference=pose.reference,
                    x_mm=pose.x_mm,
                    y_mm=pose.y_mm,
                    rotation_deg=pose.rotation_deg,
                    side=clause.side,
                )
            )
    return tuple(result)


def _proposal_stream(
    base: tuple[ComponentPose, ...],
    policy: PlacementMovePolicy,
    template_fingerprint: str,
) -> Iterator[_Proposal]:
    base_fingerprint = placement_pose_set_fingerprint(base)
    yield _Proposal(
        poses=base,
        provenance=PlacementProposalProvenance(proposal_kind=PlacementProposalKind.BASE),
    )
    pose_by_ref = {pose.reference: pose for pose in base}
    clause_by_ref = _single_clauses(pose_by_ref, policy)
    for reference in sorted(clause_by_ref):
        for clause in clause_by_ref[reference]:
            yield _Proposal(
                poses=_apply_clauses(base, (clause,)),
                provenance=PlacementProposalProvenance(
                    proposal_kind=PlacementProposalKind.SINGLE,
                    parent_pose_fingerprint=base_fingerprint,
                    moved_references=(reference,),
                    clauses=(clause,),
                ),
            )
    pair_groups = tuple(combinations(sorted(clause_by_ref), 2))
    pair_count = sum(
        len(clause_by_ref[first_ref]) * len(clause_by_ref[second_ref])
        for first_ref, second_ref in pair_groups
    )
    if pair_count == 0:
        return
    key = hashlib.sha256(
        json.dumps(
            {
                "schema_id": "pcbsmith-placement-pair-counter-key",
                "schema_version": 1,
                "seed": policy.seed,
                "template_fingerprint": template_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).digest()
    start = int.from_bytes(key[:16], "big") % pair_count
    stride = int.from_bytes(key[16:], "big") % pair_count or 1
    while math.gcd(stride, pair_count) != 1:
        stride = (stride + 1) % pair_count or 1
    for counter in range(min(policy.pair_move_limit, pair_count)):
        index = (start + counter * stride) % pair_count
        first_clause, second_clause = _pair_clause_at(index, pair_groups, clause_by_ref)
        clauses = (first_clause, second_clause)
        moved = (first_clause.reference, second_clause.reference)
        yield _Proposal(
            poses=_apply_clauses(base, clauses),
            provenance=PlacementProposalProvenance(
                proposal_kind=PlacementProposalKind.PAIR,
                parent_pose_fingerprint=base_fingerprint,
                moved_references=moved,
                clauses=clauses,
            ),
        )


def _pair_clause_at(
    index: int,
    pair_groups: tuple[tuple[str, str], ...],
    clause_by_ref: dict[str, tuple[PlacementMoveClause, ...]],
) -> tuple[PlacementMoveClause, PlacementMoveClause]:
    """Map one counter-permuted flat index without enumerating the pair product."""

    if index < 0:
        raise ValueError("pair index must be non-negative")
    remaining = index
    for first_ref, second_ref in pair_groups:
        first_clauses = clause_by_ref[first_ref]
        second_clauses = clause_by_ref[second_ref]
        group_size = len(first_clauses) * len(second_clauses)
        if remaining < group_size:
            first_index, second_index = divmod(remaining, len(second_clauses))
            return first_clauses[first_index], second_clauses[second_index]
        remaining -= group_size
    raise ValueError("pair index exceeds the canonical pair product")


def generate_placement_candidates(
    template: BoardLayout,
    catalog: PlacementGeometryCatalog,
    move_policy: PlacementMovePolicy,
    legalization_policy: PlacementLegalizationPolicy,
    budget: PlacementBudget,
    *,
    target_nets: Collection[str],
    known_net_names: Collection[str],
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    surrogate_evaluator: PlacementSurrogateEvaluator,
) -> PlacementCandidateSearch:
    """Generate canonical proposals and legalize each unique pose exactly once."""

    base = _base_poses(template)
    known_references = {pose.reference for pose in base}
    declared = (
        set(move_policy.movable_references)
        | set(move_policy.rotatable_references)
        | set(move_policy.flippable_references)
    )
    unknown = tuple(sorted(declared - known_references))
    if unknown:
        raise ValueError(f"move policy references unknown template components: {unknown!r}")
    probe_policy = PlacementProbePolicy(
        required_references=tuple(sorted(known_references)),
        allow_unchanged_non_target_references=False,
    )
    base_probe = build_placement_probe(
        template,
        base,
        target_nets,
        known_net_names=known_net_names,
        policy=probe_policy,
        budget=budget,
    )
    template_fingerprint = base_probe.result.telemetry.template_fingerprint
    target_policy_fingerprint = base_probe.result.target_policy.semantic_fingerprint()
    catalog_fingerprint = catalog.semantic_fingerprint()
    profile_fingerprint = _profile_fingerprint(profile)
    proposals = _proposal_stream(base, move_policy, template_fingerprint)
    consumed_proposals = 0
    duplicate_proposals = 0
    legalization_work = 0
    surrogate_work = 0
    seen: set[str] = set()
    records: list[PlacementCandidateRecord] = []
    probes: list[PlacementProbe] = []
    terminal = PlacementCandidateTerminalReason.COMPLETED

    while consumed_proposals < budget.max_proposals:
        try:
            proposal = next(proposals)
        except StopIteration:
            break
        consumed_proposals += 1
        candidate_fingerprint = placement_candidate_fingerprint(
            template_fingerprint,
            target_policy_fingerprint,
            catalog_fingerprint,
            profile_fingerprint,
            proposal.poses,
            move_policy,
            legalization_policy,
        )
        if candidate_fingerprint in seen:
            duplicate_proposals += 1
            continue
        seen.add(candidate_fingerprint)
        if legalization_work == budget.max_legalization_evaluations:
            terminal = PlacementCandidateTerminalReason.LEGALIZATION_BUDGET_EXHAUSTED
            break
        probe = (
            base_probe
            if proposal.provenance.proposal_kind is PlacementProposalKind.BASE
            else build_placement_probe(
                template,
                proposal.poses,
                target_nets,
                known_net_names=known_net_names,
                policy=probe_policy,
                budget=budget,
            )
        )
        legalization = legalize_placement_probe(
            probe,
            catalog,
            legalization_policy,
            legalization_evaluations_consumed=legalization_work,
        )
        legalization_work += 1
        evidence: PlacementSurrogateEvidence | None = None
        if legalization.outcome is PlacementLegalizationOutcome.REJECTED:
            disposition = PlacementCandidateDisposition.LEGALIZATION_REJECTED
        elif legalization.outcome is PlacementLegalizationOutcome.UNVERIFIED:
            disposition = PlacementCandidateDisposition.LEGALIZATION_UNVERIFIED
        else:
            if surrogate_work == budget.max_surrogate_evaluations:
                disposition = PlacementCandidateDisposition.SURROGATE_BUDGET_EXHAUSTED
                terminal = PlacementCandidateTerminalReason.SURROGATE_BUDGET_EXHAUSTED
            else:
                surrogate_work += 1
                raw_evidence = surrogate_evaluator(probe, legalization)
                evidence = PlacementSurrogateEvidence.model_validate_json(
                    raw_evidence.model_dump_json()
                )
                disposition = PlacementCandidateDisposition.SURROGATE_EVALUATED
        record = PlacementCandidateRecord(
            candidate_id=candidate_fingerprint[:12],
            candidate_fingerprint=candidate_fingerprint,
            probe_layout_fingerprint=probe.result.telemetry.probe_layout_fingerprint,
            poses=proposal.poses,
            provenance=proposal.provenance,
            legalization_result=legalization,
            disposition=disposition,
            surrogate_evidence=evidence,
        )
        records.append(record)
        probes.append(probe)
        if terminal is PlacementCandidateTerminalReason.SURROGATE_BUDGET_EXHAUSTED:
            break
    else:
        terminal = PlacementCandidateTerminalReason.PROPOSAL_BUDGET_EXHAUSTED

    telemetry = PlacementCandidateTelemetry(
        template_fingerprint=template_fingerprint,
        target_policy_fingerprint=target_policy_fingerprint,
        catalog_fingerprint=catalog_fingerprint,
        profile_fingerprint=profile_fingerprint,
        move_policy_fingerprint=move_policy.semantic_fingerprint(),
        legalization_policy_fingerprint=legalization_policy.semantic_fingerprint(),
        budget_fingerprint=budget.semantic_fingerprint(),
        proposal_limit=budget.max_proposals,
        proposals_consumed=consumed_proposals,
        unique_candidates=len(records),
        duplicate_proposals=duplicate_proposals,
        legalization_limit=budget.max_legalization_evaluations,
        legalization_evaluations_consumed=legalization_work,
        surrogate_limit=budget.max_surrogate_evaluations,
        surrogate_evaluations_consumed=surrogate_work,
        terminal_reason=terminal,
    )
    semantic = PlacementCandidateSearchResult(
        move_policy=move_policy,
        legalization_policy=legalization_policy,
        budget=budget,
        candidates=tuple(records),
        telemetry=telemetry,
    )
    return PlacementCandidateSearch(result=semantic, probes=tuple(probes))
