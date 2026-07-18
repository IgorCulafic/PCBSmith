"""Replay-bound execution of the isolated thermometer R17/D17 PWLED pilot.

This is intentionally an offline micro-pilot, not a board acceptance record.
It executes one caller-reviewed R17 translation, retains the resulting R3
planning evidence, and truthfully records that bounded pad geometry prevents
the plan from becoming an exact corridor guide.  Detailed routing therefore
uses the authority's explicitly permitted ordinary R2 fallback.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    CorridorGuidanceReport,
)
from pcbsmith.corridor_ir import CorridorNetDemand, CorridorPlanResult
from pcbsmith.corridor_summary import (
    VerifiedCorridorPlanSummary,
    verify_corridor_plan_summary,
)
from pcbsmith.kicad.aggregate_exact_checker import (
    AggregateSubcheckKind,
    AggregateSubcheckRequirement,
    StableAggregateExactCheckerPolicy,
    StableAggregateExactCheckEvidence,
    evaluate_stable_aggregate_exact_check,
)
from pcbsmith.kicad.board import BoardLayout, placement_rotation, placement_y
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.corridor_planner import CorridorGraphBuildResult, build_corridor_graph
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.negotiated_board import route_board_corridor_guided
from pcbsmith.kicad.placement_routability import (
    build_placement_probe,
    legalize_placement_probe,
)
from pcbsmith.kicad.placement_serialization import build_placement_serialization_authority
from pcbsmith.kicad.thermometer_pwled_micro_pilot import (
    ThermometerPwledMicroPilotInput,
    build_thermometer_pwled_micro_pilot_input,
)
from pcbsmith.placement_ir import (
    ComponentPose,
    PlacementIrModel,
    PlacementLegalizationOutcome,
    PlacementLegalizationResult,
    PlacementProbePolicy,
    PlacementProbeResult,
)
from pcbsmith.placement_serialization_ir import PlacementSerializationAuthority
from pcbsmith.routing_ir import RoutingRunResult

EXECUTION_SCOPE: Literal["offline_r17_d17_pwled_micro_pilot_only"] = (
    "offline_r17_d17_pwled_micro_pilot_only"
)
REVIEWED_R17_DELTA_X_MM = -0.5
EXPECTED_ROUTE_SEGMENT_COUNT = 5


def _json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class ThermometerPwledReviewedMove(PlacementIrModel):
    """The sole human-reviewed placement delta in this pilot."""

    schema_id: Literal["pcbsmith-thermometer-pwled-reviewed-move"] = (
        "pcbsmith-thermometer-pwled-reviewed-move"
    )
    schema_version: Literal[1] = 1
    reference: Literal["R17"] = "R17"
    delta_x_mm: float = REVIEWED_R17_DELTA_X_MM
    delta_y_mm: float = 0.0
    rotation_delta_deg: float = 0.0
    side_changed: Literal[False] = False
    d17_pose_unchanged: Literal[True] = True

    @model_validator(mode="after")
    def delta_is_the_reviewed_translation(self) -> Self:
        if (
            self.delta_x_mm != REVIEWED_R17_DELTA_X_MM
            or self.delta_y_mm != 0.0
            or self.rotation_delta_deg != 0.0
        ):
            raise ValueError("reviewed move must be exactly R17 x=-0.5 mm")
        return self


class ThermometerPwledRouteSegment(PlacementIrModel):
    """Canonical serializable form of one retained target-net segment."""

    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    layer: Literal["F.Cu"]
    net_name: Literal["/PWLED"]
    width_mm: float

    @model_validator(mode="after")
    def width_is_the_authorized_pwled_width(self) -> Self:
        if self.width_mm != 0.25:
            raise ValueError("PWLED route segment width must be exactly 0.25 mm")
        return self


class ThermometerPwledExecutionFingerprints(PlacementIrModel):
    """Stable fingerprints for every large retained authority boundary."""

    base_layout: str
    probe_layout: str
    final_layout: str
    netlist: str
    input_authority: str
    reviewed_move: str
    probe_result: str
    legalization: str
    graph_build: str
    demands: str
    corridor_plan: str
    verified_summary: str
    routing_run: str
    guidance: str
    route_geometry: str
    serialization: str
    aggregate: str

    @field_validator("*")
    @classmethod
    def values_are_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("execution fingerprints must be lowercase SHA-256 values")
        return value


@dataclass(frozen=True)
class _ExecutedStages:
    base_layout_snapshot_json: str
    probe_layout_snapshot_json: str
    final_layout_snapshot_json: str
    netlist_snapshot_json: str
    reviewed_move: ThermometerPwledReviewedMove
    probe_result: PlacementProbeResult
    legalization: PlacementLegalizationResult
    graph_build: CorridorGraphBuildResult
    demands: tuple[CorridorNetDemand, ...]
    corridor_plan: CorridorPlanResult
    verified_summary: VerifiedCorridorPlanSummary
    routing_run: RoutingRunResult
    guidance: CorridorGuidanceReport
    route_segments: tuple[ThermometerPwledRouteSegment, ...]
    route_via_count: int
    serialization: PlacementSerializationAuthority
    aggregate: StableAggregateExactCheckEvidence
    fingerprints: ThermometerPwledExecutionFingerprints


def _poses_with_reviewed_move(layout: BoardLayout) -> tuple[ComponentPose, ...]:
    return tuple(
        ComponentPose(
            reference=component.reference,
            x_mm=x_mm + (REVIEWED_R17_DELTA_X_MM if component.reference == "R17" else 0.0),
            y_mm=placement_y(layout, component.reference),
            rotation_deg=placement_rotation(layout, component.reference),
            side="back" if component.reference in layout.part_flip else "front",
        )
        for component, x_mm in layout.placements
    )


def _aggregate_policy(
    pilot_input: ThermometerPwledMicroPilotInput,
) -> StableAggregateExactCheckerPolicy:
    return StableAggregateExactCheckerPolicy.build(
        policy_id="thermometer-pwled-micro-offline-aggregate",
        policy_version="1",
        profile=pilot_input.authority.profile,
        design_checks_spec=DesignChecksSpec(),
        subchecks=(
            AggregateSubcheckRequirement(
                subcheck_id="design-checks",
                subcheck_version="1",
                kind=AggregateSubcheckKind.DESIGN_CHECKS,
            ),
            AggregateSubcheckRequirement(
                subcheck_id="virtual-drc",
                subcheck_version="1",
                kind=AggregateSubcheckKind.VIRTUAL_DRC,
            ),
        ),
    )


def _execute(
    pilot_input: ThermometerPwledMicroPilotInput,
) -> _ExecutedStages:
    retained_input = ThermometerPwledMicroPilotInput.model_validate_json(
        pilot_input.model_dump_json()
    )
    authority = retained_input.authority
    base_layout = authority.layout()
    netlist = authority.netlist()
    reviewed_move = ThermometerPwledReviewedMove()
    base_layout_json = canonical_board_layout_snapshot_json(base_layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)

    probe = build_placement_probe(
        base_layout,
        _poses_with_reviewed_move(base_layout),
        authority.target_net_names,
        known_net_names=tuple(net.name for net in netlist.nets),
        policy=PlacementProbePolicy(
            required_references=tuple(
                component.reference for component, _x_mm in base_layout.placements
            )
        ),
        budget=authority.placement_budget,
    )
    legalization = legalize_placement_probe(
        probe,
        authority.geometry_catalog,
        authority.legalization_policy,
    )
    if legalization.outcome is not PlacementLegalizationOutcome.LEGAL_EXACT:
        raise ValueError("reviewed PWLED move must legalize as LEGAL_EXACT")

    graph_build = build_corridor_graph(
        probe.layout,
        netlist,
        target_nets=authority.target_net_names,
        net_widths=dict(authority.target_net_widths_mm),
        default_width_mm=authority.r2_policy.default_width_mm,
        profile=authority.profile,
        clearance_groups=(),
        coarse_grid_mm=authority.coarse_grid_mm,
        capacity_quantum_mm=authority.corridor_capacity_quantum_mm,
        graphics_policy=authority.corridor_graphics_policy,
        budget=authority.corridor_graph_budget,
    )
    if not graph_build.complete or not graph_build.planning_supported:
        raise ValueError("PWLED corridor graph must be complete and planning-supported")
    demand_policy_by_net = {
        policy.net_name: policy for policy in authority.corridor_demand_policies
    }
    demands = tuple(
        CorridorNetDemand.model_validate(
            {
                **demand.model_dump(mode="python"),
                "allowed_layers": demand_policy_by_net[demand.net_name].allowed_layers,
                "via_policy": demand_policy_by_net[demand.net_name].via_policy,
            }
        )
        for demand in graph_build.demands
    )
    if len(demands) != 1 or demands[0].net_name != "/PWLED":
        raise ValueError("PWLED graph must derive exactly one target demand")
    if demands[0].allowed_layers != ("F.Cu",) or demands[0].via_policy.value != "forbidden":
        raise ValueError("PWLED demand must remain front-only and via-forbidden")

    corridor_plan = negotiate_corridor_allocations(
        graph_build.graph,
        demands,
        budget=authority.corridor_budget,
        cost_policy=authority.corridor_cost_policy,
    )
    verified_summary = verify_corridor_plan_summary(graph_build.graph, demands, corridor_plan)
    summary = verified_summary.summary
    if (
        not corridor_plan.guidance_ready
        or summary.channel_total_overflow_units != 0
        or summary.via_total_overflow_units != 0
    ):
        raise ValueError("PWLED corridor plan must succeed without resource overuse")

    r2 = authority.r2_policy
    routed = route_board_corridor_guided(
        probe.layout,
        netlist,
        corridor_graph=graph_build.graph,
        corridor_plan=corridor_plan,
        off_corridor_penalty_units=r2.off_corridor_penalty_units,
        target_nets=r2.target_nets,
        net_widths=dict(r2.net_widths_mm),
        default_width_mm=r2.default_width_mm,
        profile=authority.profile,
        net_order=r2.net_order,
        grid_mm=r2.grid_mm,
        clearance_groups=(),
        max_passes=r2.max_passes,
        max_expansions=r2.max_expansions,
        max_expansions_per_net=r2.max_expansions_per_net,
        max_stagnant_passes=r2.max_stagnant_passes,
        cost_policy=authority.negotiated_cost_policy.reconstruct(),
    )
    route_result = routed.route_result
    if (
        routed.guidance.disposition is not CorridorGuidanceDisposition.INCOMPATIBLE
        or routed.guidance.guided_net_names
        or routed.guidance.unguided_net_names != ("/PWLED",)
    ):
        raise ValueError("bounded geometry must retain an incompatible, unguided disposition")
    if (
        not route_result.run_result.success
        or route_result.run_result.resource_overuse
        or route_result.run_result.unresolved_net_names
        or route_result.exact_check is not None
    ):
        raise ValueError("ordinary R2 fallback must succeed without overuse or exact claims")
    if len(route_result.layout.segments) != EXPECTED_ROUTE_SEGMENT_COUNT:
        raise ValueError("deterministic PWLED route segment count changed")
    if route_result.layout.vias:
        raise ValueError("PWLED fallback route must remain via-free")
    route_segments = tuple(
        ThermometerPwledRouteSegment(
            x1_mm=segment.x1,
            y1_mm=segment.y1,
            x2_mm=segment.x2,
            y2_mm=segment.y2,
            layer=segment.layer,
            net_name=segment.net_name,
            width_mm=segment.width_mm,
        )
        for segment in route_result.layout.segments
    )
    final_layout_json = canonical_board_layout_snapshot_json(route_result.layout)
    serialization = build_placement_serialization_authority(
        base_layout,
        netlist,
        route_result.layout,
        authority.target_net_names,
        authority.movable_references,
        profile=authority.profile,
    )
    aggregate = evaluate_stable_aggregate_exact_check(
        route_result.layout,
        netlist,
        _aggregate_policy(retained_input),
        (),
    )
    if not aggregate.aggregate_result.accepted:
        raise ValueError("required in-process offline aggregate checks must pass")

    probe_json = canonical_board_layout_snapshot_json(probe.layout)
    fingerprints = ThermometerPwledExecutionFingerprints(
        base_layout=board_layout_snapshot_fingerprint(base_layout_json),
        probe_layout=board_layout_snapshot_fingerprint(probe_json),
        final_layout=board_layout_snapshot_fingerprint(final_layout_json),
        netlist=board_netlist_snapshot_fingerprint(netlist_json),
        input_authority=retained_input.input_fingerprint,
        reviewed_move=reviewed_move.semantic_fingerprint(),
        probe_result=probe.result.semantic_fingerprint(),
        legalization=legalization.semantic_fingerprint(),
        graph_build=graph_build.semantic_fingerprint(),
        demands=_sha([demand.model_dump(mode="json") for demand in demands]),
        corridor_plan=corridor_plan.semantic_fingerprint(),
        verified_summary=verified_summary.semantic_fingerprint(),
        routing_run=route_result.run_result.semantic_fingerprint(),
        guidance=routed.guidance.semantic_fingerprint(),
        route_geometry=_sha([segment.model_dump(mode="json") for segment in route_segments]),
        serialization=serialization.result_fingerprint,
        aggregate=aggregate.evidence_fingerprint,
    )
    return _ExecutedStages(
        base_layout_snapshot_json=base_layout_json,
        probe_layout_snapshot_json=probe_json,
        final_layout_snapshot_json=final_layout_json,
        netlist_snapshot_json=netlist_json,
        reviewed_move=reviewed_move,
        probe_result=probe.result,
        legalization=legalization,
        graph_build=graph_build,
        demands=demands,
        corridor_plan=corridor_plan,
        verified_summary=verified_summary,
        routing_run=route_result.run_result,
        guidance=routed.guidance,
        route_segments=route_segments,
        route_via_count=len(route_result.layout.vias),
        serialization=serialization,
        aggregate=aggregate,
        fingerprints=fingerprints,
    )


class ThermometerPwledMicroPilotExecution(PlacementIrModel):
    """Frozen evidence envelope that validates itself by full deterministic replay."""

    schema_id: Literal["pcbsmith-thermometer-pwled-micro-pilot-execution"] = (
        "pcbsmith-thermometer-pwled-micro-pilot-execution"
    )
    schema_version: Literal[1] = 1
    scope: Literal["offline_r17_d17_pwled_micro_pilot_only"] = EXECUTION_SCOPE
    pilot_input: ThermometerPwledMicroPilotInput
    base_layout_snapshot_json: str = Field(min_length=2)
    probe_layout_snapshot_json: str = Field(min_length=2)
    final_layout_snapshot_json: str = Field(min_length=2)
    netlist_snapshot_json: str = Field(min_length=2)
    reviewed_move: ThermometerPwledReviewedMove
    probe_result: PlacementProbeResult
    legalization: PlacementLegalizationResult
    graph_build: CorridorGraphBuildResult
    demands: tuple[CorridorNetDemand, ...] = Field(min_length=1, max_length=1)
    corridor_plan: CorridorPlanResult
    verified_summary: VerifiedCorridorPlanSummary
    routing_run: RoutingRunResult
    guidance: CorridorGuidanceReport
    route_segments: tuple[ThermometerPwledRouteSegment, ...] = Field(
        min_length=EXPECTED_ROUTE_SEGMENT_COUNT,
        max_length=EXPECTED_ROUTE_SEGMENT_COUNT,
    )
    route_via_count: Literal[0] = 0
    serialization: PlacementSerializationAuthority
    aggregate: StableAggregateExactCheckEvidence
    fingerprints: ThermometerPwledExecutionFingerprints
    execution_fingerprint: str

    full_board_claimed: Literal[False] = False
    full_template_preservation_claimed: Literal[False] = False
    fixed_neighbor_preservation_claimed: Literal[False] = False
    circuit_board_equivalence_claimed: Literal[False] = False
    thermometer_readiness_claimed: Literal[False] = False
    r3_guided_routing_claimed: Literal[False] = False
    routing_superiority_claimed: Literal[False] = False
    reader_schematic_checked: Literal[False] = False
    simulation_checked: Literal[False] = False
    kicad_live_checked: Literal[False] = False

    @field_validator("execution_fingerprint")
    @classmethod
    def execution_fingerprint_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("execution_fingerprint must be a lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def retained_evidence_equals_full_replay(self) -> Self:
        replayed = _execute(self.pilot_input)
        retained = {name: getattr(self, name) for name in _ExecutedStages.__dataclass_fields__}
        expected = {name: getattr(replayed, name) for name in _ExecutedStages.__dataclass_fields__}
        if retained != expected:
            raise ValueError("retained PWLED execution evidence differs from deterministic replay")
        payload = self.model_dump(mode="json", exclude={"execution_fingerprint"})
        if self.execution_fingerprint != _sha(payload):
            raise ValueError("PWLED execution fingerprint is stale")
        return self


def build_thermometer_pwled_micro_pilot_execution() -> ThermometerPwledMicroPilotExecution:
    """Execute and retain the honest offline PWLED micro-pilot."""

    pilot_input = build_thermometer_pwled_micro_pilot_input()
    stages = _execute(pilot_input)
    fields: dict[str, Any] = {
        "pilot_input": pilot_input,
        **{name: getattr(stages, name) for name in _ExecutedStages.__dataclass_fields__},
    }
    provisional = ThermometerPwledMicroPilotExecution.model_construct(
        **fields,
        execution_fingerprint="0" * 64,
    )
    return ThermometerPwledMicroPilotExecution(
        **fields,
        execution_fingerprint=_sha(
            provisional.model_dump(mode="json", exclude={"execution_fingerprint"})
        ),
    )


__all__ = [
    "EXECUTION_SCOPE",
    "EXPECTED_ROUTE_SEGMENT_COUNT",
    "REVIEWED_R17_DELTA_X_MM",
    "ThermometerPwledMicroPilotExecution",
    "ThermometerPwledReviewedMove",
    "ThermometerPwledRouteSegment",
    "build_thermometer_pwled_micro_pilot_execution",
]
