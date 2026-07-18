"""Opt-in deterministic R5.4 Pareto selection and detailed R3/R2 evaluation."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any, Protocol

from pcbsmith.corridor_ir import (
    CorridorGraph,
    CorridorPlanResult,
    corridor_allocations_fingerprint,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.negotiated_board import (
    CorridorGuidedBoardRouteResult,
    route_board_corridor_guided,
)
from pcbsmith.kicad.negotiated_graph import NegotiatedCostPolicy
from pcbsmith.kicad.placement_routability import PlacementProbe, board_layout_fingerprint
from pcbsmith.placement_candidate_ir import (
    PlacementCandidateDisposition,
    PlacementCandidateRecord,
    PlacementProposalKind,
)
from pcbsmith.placement_detail_ir import (
    PlacementCandidateDetailRecord,
    PlacementDetailBudget,
    PlacementDetailRunResult,
    PlacementDetailSelectionPolicy,
    PlacementDetailState,
    PlacementMarginRank,
    PlacementParetoEvidence,
    PlacementR2Policy,
    PlacementSelectionReason,
    PrimaryPlacementVector,
)
from pcbsmith.placement_surrogate_ir import (
    PlacementCorridorState,
    PlacementSurrogateResult,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


def _fp(payload: object) -> str:
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _netlist_fingerprint(netlist: BoardNetlist) -> str:
    components = tuple(
        {
            "reference": item.reference,
            "value": item.value,
            "footprint": item.footprint,
            "uuid_path": item.uuid_path,
            "fields": item.fields,
        }
        for item in sorted(netlist.components, key=lambda item: item.reference)
    )
    nets = tuple(
        {"name": item.name, "nodes": tuple(sorted(item.nodes))}
        for item in sorted(netlist.nets, key=lambda item: item.name)
    )
    return _fp(
        {
            "schema_id": "pcbsmith-board-netlist",
            "schema_version": 1,
            "components": components,
            "nets": nets,
        }
    )


def _profile_fingerprint(profile: PcbRuleProfile) -> str:
    return _fp(
        {
            "schema_id": "pcbsmith-placement-detail-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


def _route_geometry_fingerprint(layout: BoardLayout, target_nets: frozenset[str]) -> str:
    return _fp(
        {
            "schema_id": "pcbsmith-placement-detail-route-geometry",
            "schema_version": 1,
            "segments": [asdict(item) for item in layout.segments if item.net_name in target_nets],
            "vias": [asdict(item) for item in layout.vias if item.net_name in target_nets],
        }
    )


def _verify_materialization_preserves_probe(
    probe: BoardLayout,
    routed: BoardLayout,
    target_nets: frozenset[str],
) -> None:
    for field in fields(probe):
        if field.name not in {"segments", "vias"} and getattr(probe, field.name) != getattr(
            routed, field.name
        ):
            raise ValueError(f"detailed routing changed preserved probe field {field.name!r}")
    probe_segments = tuple(x for x in probe.segments if x.net_name not in target_nets)
    routed_segments = tuple(x for x in routed.segments if x.net_name not in target_nets)
    probe_vias = tuple(x for x in probe.vias if x.net_name not in target_nets)
    routed_vias = tuple(x for x in routed.vias if x.net_name not in target_nets)
    if probe_segments != routed_segments or probe_vias != routed_vias:
        raise ValueError("detailed routing changed preserved non-target copper")


@dataclass(frozen=True)
class PlacementDetailInput:
    candidate: PlacementCandidateRecord
    probe: PlacementProbe
    surrogate: PlacementSurrogateResult
    netlist: BoardNetlist
    corridor_graph: CorridorGraph | None = None
    corridor_plan: CorridorPlanResult | None = None

    def __post_init__(self) -> None:
        candidate = PlacementCandidateRecord.model_validate_json(self.candidate.model_dump_json())
        surrogate = PlacementSurrogateResult.model_validate_json(self.surrogate.model_dump_json())
        if candidate.disposition is not PlacementCandidateDisposition.SURROGATE_EVALUATED:
            raise ValueError("R5.4 requires a legal surrogate-evaluated candidate")
        pose = candidate.legalization_result.telemetry.pose_fingerprint
        telemetry = self.probe.result.telemetry
        if telemetry.pose_fingerprint != pose:
            raise ValueError("candidate and probe pose fingerprints disagree")
        if telemetry.probe_layout_fingerprint != candidate.probe_layout_fingerprint:
            raise ValueError("candidate and probe layout fingerprints disagree")
        if surrogate.pose_fingerprint != pose:
            raise ValueError("surrogate and candidate pose fingerprints disagree")
        if surrogate.probe_layout_fingerprint != candidate.probe_layout_fingerprint:
            raise ValueError("surrogate and probe layout fingerprints disagree")
        if (
            candidate.surrogate_evidence is None
            or candidate.surrogate_evidence.evidence_fingerprint != surrogate.semantic_fingerprint()
        ):
            raise ValueError("candidate does not bind the supplied surrogate result")
        summary = surrogate.corridor.summary
        if summary is None:
            if self.corridor_graph is not None or self.corridor_plan is not None:
                raise ValueError("corridor-absent surrogate cannot receive graph/plan authority")
        else:
            if self.corridor_graph is None or self.corridor_plan is None:
                raise ValueError("corridor summary requires graph and plan authority")
            graph_fp = self.corridor_graph.semantic_fingerprint()
            plan_fp = self.corridor_plan.semantic_fingerprint()
            if (
                summary.graph_fingerprint != graph_fp
                or summary.plan_fingerprint != plan_fp
                or self.corridor_plan.graph_fingerprint != graph_fp
                or summary.demand_fingerprint != self.corridor_plan.demand_fingerprint
            ):
                raise ValueError("corridor graph/plan fingerprints do not match the surrogate")
        object.__setattr__(self, "candidate", candidate)
        object.__setattr__(self, "surrogate", surrogate)

    def semantic_fingerprint(self) -> str:
        return _fp(
            {
                "schema_id": "pcbsmith-placement-detail-candidate-input",
                "schema_version": 1,
                "candidate_fingerprint": self.candidate.candidate_fingerprint,
                "candidate_record_fingerprint": self.candidate.semantic_fingerprint(),
                "probe_layout_fingerprint": self.probe.result.telemetry.probe_layout_fingerprint,
                "surrogate_fingerprint": self.surrogate.semantic_fingerprint(),
                "netlist_fingerprint": _netlist_fingerprint(self.netlist),
                "corridor_graph_fingerprint": (
                    None
                    if self.corridor_graph is None
                    else self.corridor_graph.semantic_fingerprint()
                ),
                "corridor_plan_fingerprint": (
                    None
                    if self.corridor_plan is None
                    else self.corridor_plan.semantic_fingerprint()
                ),
            }
        )


class PlacementR2Evaluator(Protocol):
    def __call__(
        self,
        source: PlacementDetailInput,
        *,
        use_guidance: bool,
        policy: PlacementR2Policy,
        profile: PcbRuleProfile,
    ) -> CorridorGuidedBoardRouteResult: ...


class KiCadPlacementR2Evaluator:
    """Fresh-ledger R2 adapter; each call creates an independent routing run."""

    def __call__(
        self,
        source: PlacementDetailInput,
        *,
        use_guidance: bool,
        policy: PlacementR2Policy,
        profile: PcbRuleProfile,
    ) -> CorridorGuidedBoardRouteResult:
        cost = NegotiatedCostPolicy(
            length_units_per_grid=policy.length_units_per_grid,
            diagonal_length_units=policy.diagonal_length_units,
            via_cost_units=policy.via_cost_units,
            turn_cost_units=policy.turn_cost_units,
            present_factor_units=policy.present_factor_units,
            present_growth_numerator=policy.present_growth_numerator,
            present_growth_denominator=policy.present_growth_denominator,
            history_increment_units=policy.history_increment_units,
        )
        return route_board_corridor_guided(
            source.probe.layout,
            source.netlist,
            corridor_graph=source.corridor_graph if use_guidance else None,
            corridor_plan=source.corridor_plan if use_guidance else None,
            off_corridor_penalty_units=policy.off_corridor_penalty_units,
            target_nets=policy.target_nets,
            net_widths=dict(policy.net_widths_mm),
            default_width_mm=policy.default_width_mm,
            profile=profile,
            net_order=policy.net_order or None,
            grid_mm=policy.grid_mm,
            max_passes=policy.max_passes,
            max_expansions=policy.max_expansions,
            max_expansions_per_net=policy.max_expansions_per_net,
            max_stagnant_passes=policy.max_stagnant_passes,
            cost_policy=cost,
            exact_checker=None,
        )


@dataclass(frozen=True)
class PlacementDetailRun:
    result: PlacementDetailRunResult
    routed_layouts: tuple[tuple[str, BoardLayout], ...] = ()

    def __post_init__(self) -> None:
        layouts = tuple(sorted(self.routed_layouts, key=lambda item: item[0]))
        if len({item[0] for item in layouts}) != len(layouts):
            raise ValueError("routed layouts must have unique candidate fingerprints")
        records = {item.candidate_fingerprint: item for item in self.result.candidate_records}
        for candidate_fingerprint, layout in layouts:
            record = records.get(candidate_fingerprint)
            if record is None or record.materialized_layout_fingerprint != board_layout_fingerprint(
                layout
            ):
                raise ValueError("routed layout does not match its detail record")
        expected_layouts = {
            item.candidate_fingerprint
            for item in self.result.candidate_records
            if item.materialized_layout_fingerprint is not None
        }
        if {item[0] for item in layouts} != expected_layouts:
            raise ValueError("routed layouts must exactly cover materialized detail records")
        object.__setattr__(self, "routed_layouts", layouts)


def _primary(source: PlacementDetailInput) -> PrimaryPlacementVector:
    result = source.surrogate
    summary = result.corridor.summary
    unresolved = 0 if summary is None else len(summary.unresolved_demand_ids)
    unsupported = int(result.corridor.state is PlacementCorridorState.ABSENT)
    total_overflow = 0
    maximum_overflow = 0
    if summary is not None:
        unsupported = len(summary.geometry_issues)
        if result.corridor.state is PlacementCorridorState.UNSUPPORTED:
            unsupported = max(1, unsupported)
        total_overflow = summary.channel_total_overflow_units + summary.via_total_overflow_units
        maximum_overflow = max(
            summary.channel_maximum_overflow_units,
            summary.via_maximum_overflow_units,
        )
    return (
        result.terminal_clearance_violation_count,
        result.unescaped_terminal_count,
        unresolved,
        unsupported,
        total_overflow,
        maximum_overflow,
        result.declared_order_conflict_count,
        result.geometric_crossing_count,
        result.constrained_escape_count,
    )


def _dominates(first: PrimaryPlacementVector, second: PrimaryPlacementVector) -> bool:
    return all(a <= b for a, b in zip(first, second, strict=True)) and any(
        a < b for a, b in zip(first, second, strict=True)
    )


def _margin_rank(value: int | None) -> PlacementMarginRank:
    if value is None:
        return PlacementMarginRank.UNKNOWN
    if value >= 0:
        return PlacementMarginRank.KNOWN_NONNEGATIVE
    return PlacementMarginRank.KNOWN_NEGATIVE


def _secondary(source: PlacementDetailInput) -> tuple[int, int, int, str]:
    margin = source.surrogate.minimum_terminal_margin_um
    if margin is not None and margin >= 0:
        margin_key = (0, -margin)
    elif margin is None:
        margin_key = (1, 0)
    else:
        margin_key = (2, -margin)
    return (
        source.surrogate.total_hpwl_um,
        margin_key[0],
        margin_key[1],
        source.candidate.candidate_fingerprint,
    )


def _fronts(
    values: tuple[PlacementDetailInput, ...],
) -> tuple[tuple[PlacementDetailInput, ...], ...]:
    remaining = set(range(len(values)))
    fronts: list[tuple[PlacementDetailInput, ...]] = []
    primary = tuple(_primary(item) for item in values)
    while remaining:
        front_indices = tuple(
            index
            for index in sorted(remaining)
            if not any(
                _dominates(primary[other], primary[index]) for other in remaining if other != index
            )
        )
        front = tuple(sorted((values[index] for index in front_indices), key=_secondary))
        fronts.append(front)
        remaining.difference_update(front_indices)
    return tuple(fronts)


def _select(
    values: tuple[PlacementDetailInput, ...],
    fronts: tuple[tuple[PlacementDetailInput, ...], ...],
    policy: PlacementDetailSelectionPolicy,
    budget: PlacementDetailBudget,
) -> dict[str, PlacementSelectionReason]:
    limit = budget.max_selected_candidates
    chosen: dict[str, PlacementSelectionReason] = {}

    def add(source: PlacementDetailInput, reason: PlacementSelectionReason) -> None:
        if len(chosen) < limit:
            chosen.setdefault(source.candidate.candidate_fingerprint, reason)

    base = tuple(
        sorted(
            (
                item
                for item in values
                if item.candidate.provenance.proposal_kind is PlacementProposalKind.BASE
            ),
            key=_secondary,
        )
    )
    if base:
        add(base[0], PlacementSelectionReason.BASE)

    coarse = tuple(
        sorted(
            (
                item
                for item in values
                if item.surrogate.corridor.summary is not None
                and not item.surrogate.corridor.summary.guidance_ready
                and item.candidate.candidate_fingerprint not in chosen
            ),
            key=lambda item: (
                next(i for i, front in enumerate(fronts) if item in front),
                _secondary(item),
            ),
        )
    )
    for item in coarse[: policy.coarse_failure_exploration_quota]:
        add(item, PlacementSelectionReason.COARSE_FAILURE_EXPLORATION)

    for front in fronts:
        if len(chosen) >= limit:
            break
        leader = front[0]
        add(leader, PlacementSelectionReason.FRONT_LEADER)
        covered_allocations = {
            (
                None
                if item.corridor_plan is None
                else corridor_allocations_fingerprint(item.corridor_plan.allocations)
            )
            for item in front
            if item.candidate.candidate_fingerprint in chosen
        }
        for item in front:
            allocation = (
                None
                if item.corridor_plan is None
                else corridor_allocations_fingerprint(item.corridor_plan.allocations)
            )
            if allocation not in covered_allocations:
                add(item, PlacementSelectionReason.CORRIDOR_DIVERSITY)
                covered_allocations.add(allocation)
        covered_flip_buckets = {
            (
                tuple(
                    sorted(pose.reference for pose in item.candidate.poses if pose.side == "back")
                ),
                bisect_right(
                    policy.portal_overflow_bucket_upper_bounds,
                    _primary(item)[4],
                ),
            )
            for item in front
            if item.candidate.candidate_fingerprint in chosen
        }
        for item in front:
            key = (
                tuple(
                    sorted(pose.reference for pose in item.candidate.poses if pose.side == "back")
                ),
                bisect_right(policy.portal_overflow_bucket_upper_bounds, _primary(item)[4]),
            )
            if key not in covered_flip_buckets:
                add(item, PlacementSelectionReason.FLIP_BUCKET_DIVERSITY)
                covered_flip_buckets.add(key)
        for item in front:
            add(item, PlacementSelectionReason.FRONT_FILL)
    return chosen


def evaluate_placement_details(
    inputs_by_candidate_fingerprint: Mapping[str, PlacementDetailInput],
    *,
    selection_policy: PlacementDetailSelectionPolicy,
    budget: PlacementDetailBudget,
    r2_policy: PlacementR2Policy,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    r2_evaluator: PlacementR2Evaluator | None = None,
) -> PlacementDetailRun:
    if not inputs_by_candidate_fingerprint:
        raise ValueError("R5.4 needs at least one detailed candidate input")
    sources = tuple(
        sorted(
            inputs_by_candidate_fingerprint.values(),
            key=lambda x: x.candidate.candidate_fingerprint,
        )
    )
    if len({item.candidate.candidate_fingerprint for item in sources}) != len(sources):
        raise ValueError("detailed candidates must be unique")
    if any(
        key != value.candidate.candidate_fingerprint
        for key, value in inputs_by_candidate_fingerprint.items()
    ):
        raise ValueError("detail input mapping keys must equal candidate fingerprints")

    fronts = _fronts(sources)
    front_index = {
        item.candidate.candidate_fingerprint: index
        for index, front in enumerate(fronts)
        for item in front
    }
    selected = _select(sources, fronts, selection_policy, budget)
    evaluator = r2_evaluator or KiCadPlacementR2Evaluator()
    r3_consumed = 0
    r2_consumed = 0
    layouts: list[tuple[str, BoardLayout]] = []
    records: list[PlacementCandidateDetailRecord] = []
    target_nets = frozenset(r2_policy.target_nets)

    for source in sources:
        fingerprint = source.candidate.candidate_fingerprint
        is_selected = fingerprint in selected
        common: dict[str, Any] = {
            "candidate_fingerprint": fingerprint,
            "detail_input_fingerprint": source.semantic_fingerprint(),
            "selected": is_selected,
            "corridor_graph_fingerprint": (
                None
                if source.corridor_graph is None
                else source.corridor_graph.semantic_fingerprint()
            ),
            "corridor_plan_fingerprint": (
                None
                if source.corridor_plan is None
                else source.corridor_plan.semantic_fingerprint()
            ),
        }
        if not is_selected:
            records.append(
                PlacementCandidateDetailRecord(
                    **common,
                    state=PlacementDetailState.NOT_SELECTED,
                    r3_evaluations_consumed=0,
                    r2_evaluations_consumed=0,
                )
            )
            continue

        has_corridor = source.corridor_plan is not None
        if has_corridor and r3_consumed == budget.max_corridor_evaluations:
            records.append(
                PlacementCandidateDetailRecord(
                    **common,
                    state=PlacementDetailState.CORRIDOR_BUDGET_EXHAUSTED,
                    r3_evaluations_consumed=0,
                    r2_evaluations_consumed=0,
                )
            )
            continue
        r3_work = int(has_corridor)
        r3_consumed += r3_work
        use_guidance = bool(source.corridor_plan and source.corridor_plan.guidance_ready)
        if not use_guidance and not selection_policy.allow_unguided_when_corridor_unavailable:
            records.append(
                PlacementCandidateDetailRecord(
                    **common,
                    state=PlacementDetailState.UNGUIDED_FORBIDDEN,
                    r3_evaluations_consumed=r3_work,
                    r2_evaluations_consumed=0,
                )
            )
            continue
        if r2_consumed == budget.max_routing_evaluations:
            records.append(
                PlacementCandidateDetailRecord(
                    **common,
                    state=PlacementDetailState.ROUTING_BUDGET_EXHAUSTED,
                    r3_evaluations_consumed=r3_work,
                    r2_evaluations_consumed=0,
                )
            )
            continue

        routed = evaluator(
            source,
            use_guidance=use_guidance,
            policy=r2_policy,
            profile=profile,
        )
        r2_consumed += 1
        if routed.route_result.exact_check is not None:
            raise ValueError("R5.4 must not invoke an exact checker")
        _verify_materialization_preserves_probe(
            source.probe.layout,
            routed.route_result.layout,
            target_nets,
        )
        routing = routed.route_result.run_result
        zero = not routing.resource_overuse
        unchecked = routing.success and zero and routing.exact_check_accepted is None
        records.append(
            PlacementCandidateDetailRecord(
                **common,
                state=(
                    PlacementDetailState.ROUTED_UNCHECKED
                    if unchecked
                    else PlacementDetailState.ROUTING_FAILED
                ),
                r3_evaluations_consumed=r3_work,
                r2_evaluations_consumed=1,
                guidance=routed.guidance,
                routing_run=routing,
                materialized_layout_fingerprint=board_layout_fingerprint(
                    routed.route_result.layout
                ),
                route_geometry_fingerprint=_route_geometry_fingerprint(
                    routed.route_result.layout,
                    target_nets,
                ),
                algorithmic_success=routing.success,
                zero_overuse=zero,
                routed_unchecked=unchecked,
            )
        )
        layouts.append((fingerprint, routed.route_result.layout))

    pareto: list[PlacementParetoEvidence] = []
    for source in sources:
        fingerprint = source.candidate.candidate_fingerprint
        primary = _primary(source)
        dominators = tuple(
            other.candidate.candidate_fingerprint
            for other in sources
            if other is not source and _dominates(_primary(other), primary)
        )
        summary = source.surrogate.corridor.summary
        allocation = (
            None
            if source.corridor_plan is None
            else corridor_allocations_fingerprint(source.corridor_plan.allocations)
        )
        margin = source.surrogate.minimum_terminal_margin_um
        pareto.append(
            PlacementParetoEvidence(
                candidate_fingerprint=fingerprint,
                primary_vector=primary,
                hpwl_total_um=source.surrogate.total_hpwl_um,
                minimum_margin_rank=_margin_rank(margin),
                minimum_terminal_margin_um=margin,
                corridor_allocation_fingerprint=allocation,
                flip_set=tuple(
                    pose.reference for pose in source.candidate.poses if pose.side == "back"
                ),
                portal_overflow_bucket=bisect_right(
                    selection_policy.portal_overflow_bucket_upper_bounds,
                    primary[4],
                ),
                base_candidate=(
                    source.candidate.provenance.proposal_kind is PlacementProposalKind.BASE
                ),
                coarse_failure=bool(summary is not None and not summary.guidance_ready),
                pareto_front_index=front_index[fingerprint],
                dominated_by_candidate_fingerprints=dominators,
                selected=fingerprint in selected,
                selection_reason=selected.get(fingerprint, PlacementSelectionReason.NOT_SELECTED),
            )
        )

    input_catalog_fingerprint = _fp(
        {
            "schema_id": "pcbsmith-placement-detail-input-catalog",
            "schema_version": 1,
            "inputs": [item.semantic_fingerprint() for item in sources],
        }
    )
    selection_policy_fingerprint = selection_policy.semantic_fingerprint()
    budget_fingerprint = budget.semantic_fingerprint()
    r2_policy_fingerprint = r2_policy.semantic_fingerprint()
    profile_fingerprint = _profile_fingerprint(profile)
    input_components = {
        "input_catalog_fingerprint": input_catalog_fingerprint,
        "selection_policy_fingerprint": selection_policy_fingerprint,
        "budget_fingerprint": budget_fingerprint,
        "r2_policy_fingerprint": r2_policy_fingerprint,
        "profile_fingerprint": profile_fingerprint,
    }
    result = PlacementDetailRunResult(
        **input_components,
        input_fingerprint=_fp(
            {
                "schema_id": "pcbsmith-placement-detail-input",
                "schema_version": 1,
                **input_components,
            }
        ),
        selection_policy=selection_policy,
        budget=budget,
        r2_policy=r2_policy,
        pareto_evidence=tuple(pareto),
        selected_candidate_fingerprints=tuple(selected),
        candidate_records=tuple(records),
        corridor_evaluations_consumed=r3_consumed,
        routing_evaluations_consumed=r2_consumed,
    )
    return PlacementDetailRun(result=result, routed_layouts=tuple(layouts))
