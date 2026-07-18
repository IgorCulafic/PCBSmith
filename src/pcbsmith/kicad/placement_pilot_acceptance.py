"""Replay-bound acceptance composition for the synthetic placement pilot.

This wrapper connects the input-only :class:`PlacementPilotAuthority` to the
already accepted placement/aggregate manifest without weakening either
schema.  It intentionally makes no application-readiness or circuit-to-board
equivalence claim.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.corridor_ir import CorridorGraph, CorridorPlanResult
from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    parse_canonical_board_layout_snapshot,
)
from pcbsmith.kicad.corridor_planner import build_corridor_graph
from pcbsmith.kicad.placement_acceptance_manifest import PlacementAcceptanceManifest
from pcbsmith.kicad.placement_exact import placement_exact_netlist_fingerprint
from pcbsmith.kicad.placement_routability import (
    board_layout_fingerprint,
    build_placement_probe,
)
from pcbsmith.placement_candidate_ir import (
    PlacementCandidateDisposition,
    PlacementCandidateRecord,
    PlacementCandidateSearchResult,
)
from pcbsmith.placement_ir import PlacementProbePolicy
from pcbsmith.placement_pilot_authority import PlacementPilotAuthority
from pcbsmith.placement_surrogate_ir import PlacementCorridorState, PlacementSurrogateResult


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _detail_input_fingerprint(
    candidate: PlacementCandidateRecord,
    probe_layout_fingerprint: str,
    surrogate: PlacementSurrogateResult,
    netlist_fingerprint: str,
    graph: CorridorGraph | None,
    plan: CorridorPlanResult | None,
) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-placement-detail-candidate-input",
            "schema_version": 1,
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "candidate_record_fingerprint": candidate.semantic_fingerprint(),
            "probe_layout_fingerprint": probe_layout_fingerprint,
            "surrogate_fingerprint": surrogate.semantic_fingerprint(),
            "netlist_fingerprint": netlist_fingerprint,
            "corridor_graph_fingerprint": (None if graph is None else graph.semantic_fingerprint()),
            "corridor_plan_fingerprint": None if plan is None else plan.semantic_fingerprint(),
        }
    )


class PlacementPilotCandidateInput(BaseModel):
    """Lossless, serializable authority used for one R5.4 candidate input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-placement-pilot-candidate-input"] = (
        "pcbsmith-placement-pilot-candidate-input"
    )
    schema_version: Literal[1] = 1
    candidate_fingerprint: str
    candidate_record_fingerprint: str
    probe_layout_snapshot_json: str = Field(min_length=2)
    probe_layout_snapshot_fingerprint: str
    probe_layout_fingerprint: str
    surrogate: PlacementSurrogateResult
    surrogate_fingerprint: str
    corridor_graph: CorridorGraph | None = None
    corridor_graph_fingerprint: str | None = None
    corridor_plan: CorridorPlanResult | None = None
    corridor_plan_fingerprint: str | None = None
    detail_input_fingerprint: str
    input_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"input_fingerprint"})

    @model_validator(mode="after")
    def replay_local_authority(self) -> Self:
        for name in (
            "candidate_fingerprint",
            "candidate_record_fingerprint",
            "probe_layout_snapshot_fingerprint",
            "probe_layout_fingerprint",
            "surrogate_fingerprint",
            "detail_input_fingerprint",
            "input_fingerprint",
        ):
            _require_sha256(getattr(self, name), name)
        layout = parse_canonical_board_layout_snapshot(self.probe_layout_snapshot_json)
        if self.probe_layout_snapshot_fingerprint != board_layout_snapshot_fingerprint(
            self.probe_layout_snapshot_json
        ):
            raise ValueError("candidate probe snapshot fingerprint is stale")
        if self.probe_layout_fingerprint != board_layout_fingerprint(layout):
            raise ValueError("candidate probe layout fingerprint is stale")
        if self.surrogate.probe_layout_fingerprint != self.probe_layout_fingerprint:
            raise ValueError("candidate surrogate belongs to another probe layout")
        if self.surrogate_fingerprint != self.surrogate.semantic_fingerprint():
            raise ValueError("candidate surrogate fingerprint is stale")
        for name in ("corridor_graph_fingerprint", "corridor_plan_fingerprint"):
            value = getattr(self, name)
            if value is not None:
                _require_sha256(value, name)
        if (self.corridor_graph is None) != (self.corridor_plan is None):
            raise ValueError("candidate corridor graph and plan must be retained together")
        if (self.corridor_graph is None) != (self.corridor_graph_fingerprint is None) or (
            self.corridor_plan is None
        ) != (self.corridor_plan_fingerprint is None):
            raise ValueError("candidate corridor fingerprints must match retained authority")
        verified = self.surrogate.corridor.verified_summary
        if self.corridor_graph is None:
            if self.surrogate.corridor.state is not PlacementCorridorState.ABSENT:
                raise ValueError("candidate without R3 authority must retain an absent corridor")
        else:
            assert self.corridor_plan is not None
            if self.corridor_graph_fingerprint != self.corridor_graph.semantic_fingerprint():
                raise ValueError("candidate corridor graph fingerprint is stale")
            if self.corridor_plan_fingerprint != self.corridor_plan.semantic_fingerprint():
                raise ValueError("candidate corridor plan fingerprint is stale")
            if (
                self.surrogate.corridor.state is not PlacementCorridorState.READY
                or verified is None
                or verified.graph != self.corridor_graph
                or verified.plan != self.corridor_plan
            ):
                raise ValueError("candidate surrogate lacks the retained ready R3 graph and plan")
            if self.corridor_plan.graph_fingerprint != self.corridor_graph_fingerprint:
                raise ValueError("candidate corridor plan belongs to another graph")
        if self.input_fingerprint != _fingerprint(self.fingerprint_payload()):
            raise ValueError("candidate input fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        candidate: PlacementCandidateRecord,
        probe_layout_snapshot_json: str,
        surrogate: PlacementSurrogateResult,
        corridor_graph: CorridorGraph | None,
        corridor_plan: CorridorPlanResult | None,
        netlist_fingerprint: str,
    ) -> Self:
        layout = parse_canonical_board_layout_snapshot(probe_layout_snapshot_json)
        fields_: dict[str, Any] = {
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "candidate_record_fingerprint": candidate.semantic_fingerprint(),
            "probe_layout_snapshot_json": probe_layout_snapshot_json,
            "probe_layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(
                probe_layout_snapshot_json
            ),
            "probe_layout_fingerprint": board_layout_fingerprint(layout),
            "surrogate": surrogate,
            "surrogate_fingerprint": surrogate.semantic_fingerprint(),
            "corridor_graph": corridor_graph,
            "corridor_graph_fingerprint": (
                None if corridor_graph is None else corridor_graph.semantic_fingerprint()
            ),
            "corridor_plan": corridor_plan,
            "corridor_plan_fingerprint": (
                None if corridor_plan is None else corridor_plan.semantic_fingerprint()
            ),
            "detail_input_fingerprint": _detail_input_fingerprint(
                candidate,
                board_layout_fingerprint(layout),
                surrogate,
                netlist_fingerprint,
                corridor_graph,
                corridor_plan,
            ),
        }
        provisional = cls.model_construct(**fields_, input_fingerprint="0" * 64)
        return cls(**fields_, input_fingerprint=_fingerprint(provisional.fingerprint_payload()))


class PlacementPilotAcceptance(BaseModel):
    """Accepted reduced-pilot composition with fully retained replay authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-placement-pilot-acceptance"] = (
        "pcbsmith-placement-pilot-acceptance"
    )
    schema_version: Literal[1] = 1
    authority: PlacementPilotAuthority
    authority_fingerprint: str
    candidate_search_result: PlacementCandidateSearchResult
    candidate_search_fingerprint: str
    candidate_inputs: tuple[PlacementPilotCandidateInput, ...] = Field(min_length=1)
    candidate_input_fingerprints: tuple[tuple[str, str], ...]
    accepted_candidate_fingerprint: str
    accepted_r3_graph_fingerprint: str
    accepted_r3_plan_fingerprint: str
    accepted_r3_guide_fingerprint: str
    accepted_r2_routing_fingerprint: str
    exact_result_fingerprint: str
    aggregate_evidence_fingerprint: str
    manifest: PlacementAcceptanceManifest
    manifest_fingerprint: str
    circuit_board_equivalence_claimed: Literal[False] = False
    thermometer_readiness_claimed: Literal[False] = False
    live_tool_execution_claimed: Literal[False] = False
    superiority_claimed: Literal[False] = False
    authority_scope_note: Literal[
        "Synthetic authority composition only; no circuit-to-board equivalence, "
        "thermometer readiness, live-tool execution, or superiority claim."
    ] = (
        "Synthetic authority composition only; no circuit-to-board equivalence, "
        "thermometer readiness, live-tool execution, or superiority claim."
    )
    acceptance_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"acceptance_fingerprint"})

    @model_validator(mode="after")
    def replay_and_cross_bind(self) -> Self:
        authority = PlacementPilotAuthority.model_validate_json(self.authority.model_dump_json())
        search = PlacementCandidateSearchResult.model_validate_json(
            self.candidate_search_result.model_dump_json()
        )
        manifest = PlacementAcceptanceManifest.model_validate_json(self.manifest.model_dump_json())
        for name in (
            "authority_fingerprint",
            "candidate_search_fingerprint",
            "accepted_candidate_fingerprint",
            "accepted_r3_graph_fingerprint",
            "accepted_r3_plan_fingerprint",
            "accepted_r3_guide_fingerprint",
            "accepted_r2_routing_fingerprint",
            "exact_result_fingerprint",
            "aggregate_evidence_fingerprint",
            "manifest_fingerprint",
            "acceptance_fingerprint",
        ):
            _require_sha256(getattr(self, name), name)
        if self.authority_fingerprint != authority.authority_fingerprint:
            raise ValueError("pilot authority fingerprint is stale")
        if self.candidate_search_fingerprint != search.semantic_fingerprint():
            raise ValueError("candidate search fingerprint is stale")
        if search.move_policy != authority.move_policy:
            raise ValueError("candidate search move policy differs from pilot authority")
        if search.legalization_policy != authority.legalization_policy:
            raise ValueError("candidate search legalization policy differs from pilot authority")
        if search.budget != authority.placement_budget:
            raise ValueError("candidate search budget differs from pilot authority")
        telemetry = search.telemetry
        if telemetry.template_fingerprint != board_layout_fingerprint(authority.layout()):
            raise ValueError("candidate search template differs from pilot layout")
        if telemetry.catalog_fingerprint != authority.geometry_catalog_fingerprint:
            raise ValueError("candidate search catalog differs from pilot authority")
        expected_profile_fingerprint = _fingerprint(
            {
                "schema_id": "pcbsmith-placement-candidate-profile",
                "schema_version": 1,
                "profile": authority.profile.model_dump(mode="json"),
            }
        )
        if telemetry.profile_fingerprint != expected_profile_fingerprint:
            raise ValueError("candidate search profile differs from pilot authority")

        candidates = {item.candidate_fingerprint: item for item in search.candidates}
        inputs = tuple(sorted(self.candidate_inputs, key=lambda item: item.candidate_fingerprint))
        if inputs != self.candidate_inputs or set(candidates) != {
            item.candidate_fingerprint for item in inputs
        }:
            raise ValueError("candidate inputs must exactly and canonically cover the search")
        expected_input_fingerprints = tuple(
            (item.candidate_fingerprint, item.input_fingerprint) for item in inputs
        )
        if self.candidate_input_fingerprints != expected_input_fingerprints:
            raise ValueError("candidate input fingerprint catalog is stale")

        netlist = authority.netlist()
        netlist_fingerprint = placement_exact_netlist_fingerprint(netlist)
        probe_policy = PlacementProbePolicy(
            required_references=tuple(
                sorted(component.reference for component, _x in authority.layout().placements)
            ),
            allow_unchanged_non_target_references=False,
        )
        detail_by_candidate = {
            item.candidate_fingerprint: item
            for item in manifest.placement_exact_result.detail_result.candidate_records
        }
        for retained in inputs:
            candidate = candidates[retained.candidate_fingerprint]
            if candidate.disposition is not PlacementCandidateDisposition.SURROGATE_EVALUATED:
                raise ValueError("retained downstream candidate was not surrogate evaluated")
            if retained.candidate_record_fingerprint != candidate.semantic_fingerprint():
                raise ValueError("retained candidate record differs from search result")
            if candidate.surrogate_evidence is None or (
                candidate.surrogate_evidence.evidence_fingerprint
                != retained.surrogate.semantic_fingerprint()
            ):
                raise ValueError("candidate search does not bind retained typed surrogate")
            if (
                retained.surrogate.pose_fingerprint
                != candidate.legalization_result.telemetry.pose_fingerprint
            ):
                raise ValueError("retained surrogate belongs to another candidate pose")
            expected_probe = build_placement_probe(
                authority.layout(),
                candidate.poses,
                authority.target_net_names,
                known_net_names=tuple(item.name for item in netlist.nets),
                policy=probe_policy,
                budget=authority.placement_budget,
            )
            if (
                parse_canonical_board_layout_snapshot(retained.probe_layout_snapshot_json)
                != expected_probe.layout
            ):
                raise ValueError(
                    "retained probe is not the pilot-authorized candidate materialization"
                )
            if (
                telemetry.target_policy_fingerprint
                != expected_probe.result.target_policy.semantic_fingerprint()
            ):
                raise ValueError("candidate search target policy differs from pilot authority")
            graph = retained.corridor_graph
            clearance_groups = tuple(
                (
                    group.nets_a,
                    group.nets_b,
                    group.minimum_clearance_mm,
                    group.exempt_component_refs,
                )
                for group in authority.clearance_groups
            )
            rebuilt = build_corridor_graph(
                expected_probe.layout,
                netlist,
                target_nets=authority.target_net_names,
                net_widths=dict(authority.target_net_widths_mm),
                default_width_mm=authority.r2_policy.default_width_mm,
                profile=authority.profile,
                clearance_groups=clearance_groups,
                coarse_grid_mm=authority.coarse_grid_mm,
                capacity_quantum_mm=authority.corridor_capacity_quantum_mm,
                graphics_policy=authority.corridor_graphics_policy,
                budget=authority.corridor_graph_budget,
            )
            if graph is None:
                if rebuilt.planning_supported:
                    raise ValueError("candidate omitted available pilot R3 authority")
            else:
                plan = retained.corridor_plan
                assert plan is not None
                if (
                    graph.coarse_grid_mm != authority.coarse_grid_mm
                    or graph.capacity_quantum_mm != authority.corridor_capacity_quantum_mm
                ):
                    raise ValueError("retained R3 graph uses stale pilot grids")
                if not rebuilt.complete or rebuilt.graph != graph:
                    raise ValueError(
                        "retained R3 graph is not reproduced by pilot geometry authority"
                    )
                verified = retained.surrogate.corridor.verified_summary
                assert verified is not None
                demand_policy = {item.net_name: item for item in authority.corridor_demand_policies}
                if (
                    plan.budget != authority.corridor_budget
                    or plan.cost_policy_fingerprint
                    != authority.corridor_cost_policy.semantic_fingerprint()
                    or {demand.net_name for demand in verified.demands}
                    != set(authority.target_net_names)
                    or any(
                        demand.width_mm != dict(authority.target_net_widths_mm)[demand.net_name]
                        or demand.allowed_layers != demand_policy[demand.net_name].allowed_layers
                        or demand.via_policy is not demand_policy[demand.net_name].via_policy
                        for demand in verified.demands
                    )
                ):
                    raise ValueError(
                        "retained R3 authority differs from pilot targets, demand policy, "
                        "cost, or budget"
                    )
            expected_detail_input = _detail_input_fingerprint(
                candidate,
                retained.probe_layout_fingerprint,
                retained.surrogate,
                netlist_fingerprint,
                retained.corridor_graph,
                retained.corridor_plan,
            )
            if retained.detail_input_fingerprint != expected_detail_input:
                raise ValueError("retained detail-input fingerprint is stale")
            detail = detail_by_candidate.get(candidate.candidate_fingerprint)
            if detail is None or detail.detail_input_fingerprint != expected_detail_input:
                raise ValueError("exact result did not consume the retained pilot candidate input")

        exact = manifest.placement_exact_result
        detail_result = exact.detail_result
        if (
            detail_result.selection_policy != authority.detail_selection_policy
            or detail_result.budget != authority.detail_budget
            or detail_result.r2_policy != authority.r2_policy
            or exact.exact_policy != authority.exact_policy
            or exact.exact_budget != authority.exact_budget
        ):
            raise ValueError("detail, R2, or exact policy/budget differs from pilot authority")
        accepted_id = manifest.accepted_candidate_fingerprint
        accepted_input = next(
            (item for item in inputs if item.candidate_fingerprint == accepted_id), None
        )
        if accepted_input is None or self.accepted_candidate_fingerprint != accepted_id:
            raise ValueError("accepted candidate was not generated under pilot authority")
        if accepted_input.corridor_graph is None or accepted_input.corridor_plan is None:
            raise ValueError("accepted candidate lacks pilot-authorized R3 authority")
        accepted_detail = manifest.accepted_candidate_record.detail_record
        if (
            accepted_detail.routing_run is None
            or accepted_detail.guidance is None
            or self.accepted_r3_graph_fingerprint != accepted_input.corridor_graph_fingerprint
            or self.accepted_r3_plan_fingerprint != accepted_input.corridor_plan_fingerprint
            or self.accepted_r3_guide_fingerprint != accepted_detail.guidance.guide_fingerprint
            or self.accepted_r2_routing_fingerprint
            != accepted_detail.routing_run.semantic_fingerprint()
        ):
            raise ValueError("accepted R3/R2 fingerprint bindings are stale")
        if (
            self.exact_result_fingerprint != exact.semantic_fingerprint()
            or self.aggregate_evidence_fingerprint
            != manifest.aggregate_evidence.evidence_fingerprint
            or self.manifest_fingerprint != manifest.manifest_fingerprint
        ):
            raise ValueError("exact, aggregate, or manifest fingerprint binding is stale")
        if manifest.netlist_fingerprint != netlist_fingerprint:
            raise ValueError("final exact/aggregate netlist differs from pilot netlist")

        probe_layout = parse_canonical_board_layout_snapshot(
            accepted_input.probe_layout_snapshot_json
        )
        final_layout = parse_canonical_board_layout_snapshot(
            manifest.aggregate_evidence.layout_snapshot_json
        )
        target_nets = set(authority.target_net_names)
        for field in fields(probe_layout):
            if field.name not in {"segments", "vias"} and getattr(
                probe_layout, field.name
            ) != getattr(final_layout, field.name):
                raise ValueError(
                    f"final routing changed preserved BoardLayout field {field.name!r}"
                )
        if tuple(
            item for item in probe_layout.segments if item.net_name not in target_nets
        ) != tuple(
            item for item in final_layout.segments if item.net_name not in target_nets
        ) or tuple(item for item in probe_layout.vias if item.net_name not in target_nets) != tuple(
            item for item in final_layout.vias if item.net_name not in target_nets
        ):
            raise ValueError("final routing changed fixed or non-target copper")
        if self.acceptance_fingerprint != _fingerprint(self.fingerprint_payload()):
            raise ValueError("pilot acceptance fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        authority: PlacementPilotAuthority,
        candidate_search_result: PlacementCandidateSearchResult,
        candidate_inputs: tuple[PlacementPilotCandidateInput, ...],
        manifest: PlacementAcceptanceManifest,
    ) -> Self:
        inputs = tuple(sorted(candidate_inputs, key=lambda item: item.candidate_fingerprint))
        accepted = manifest.accepted_candidate_record.detail_record
        if accepted.routing_run is None or accepted.guidance is None:
            raise ValueError("accepted manifest candidate lacks R3/R2 authority")
        fields_: dict[str, Any] = {
            "authority": authority,
            "authority_fingerprint": authority.authority_fingerprint,
            "candidate_search_result": candidate_search_result,
            "candidate_search_fingerprint": candidate_search_result.semantic_fingerprint(),
            "candidate_inputs": inputs,
            "candidate_input_fingerprints": tuple(
                (item.candidate_fingerprint, item.input_fingerprint) for item in inputs
            ),
            "accepted_candidate_fingerprint": manifest.accepted_candidate_fingerprint,
            "accepted_r3_graph_fingerprint": manifest.corridor_graph_fingerprint,
            "accepted_r3_plan_fingerprint": manifest.corridor_plan_fingerprint,
            "accepted_r3_guide_fingerprint": manifest.corridor_guide_fingerprint,
            "accepted_r2_routing_fingerprint": accepted.routing_run.semantic_fingerprint(),
            "exact_result_fingerprint": manifest.placement_exact_result.semantic_fingerprint(),
            "aggregate_evidence_fingerprint": manifest.aggregate_evidence.evidence_fingerprint,
            "manifest": manifest,
            "manifest_fingerprint": manifest.manifest_fingerprint,
        }
        provisional = cls.model_construct(**fields_, acceptance_fingerprint="0" * 64)
        return cls(
            **fields_, acceptance_fingerprint=_fingerprint(provisional.fingerprint_payload())
        )


def build_pilot_candidate_input(
    *,
    candidate: PlacementCandidateRecord,
    probe_layout: BoardLayout,
    surrogate: PlacementSurrogateResult,
    corridor_graph: CorridorGraph | None,
    corridor_plan: CorridorPlanResult | None,
    netlist_fingerprint: str,
) -> PlacementPilotCandidateInput:
    """Build a retained candidate input from an existing materialized probe layout."""

    return PlacementPilotCandidateInput.build(
        candidate=candidate,
        probe_layout_snapshot_json=canonical_board_layout_snapshot_json(probe_layout),
        surrogate=surrogate,
        corridor_graph=corridor_graph,
        corridor_plan=corridor_plan,
        netlist_fingerprint=netlist_fingerprint,
    )
