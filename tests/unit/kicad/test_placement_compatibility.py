from __future__ import annotations

import json
from dataclasses import fields, replace
from typing import Any

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.astar_router import route_board
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.kicad.placement_candidates import generate_placement_candidates
from pcbsmith.kicad.placement_compatibility import (
    adapt_legacy_rectangular_placement,
)
from pcbsmith.kicad.placement_detail import (
    PlacementDetailInput,
    evaluate_placement_details,
)
from pcbsmith.kicad.placement_exact import evaluate_placement_exact
from pcbsmith.kicad.placement_routability import (
    PlacementProbe,
    bind_component_placement_geometry,
    build_placement_geometry_catalog,
)
from pcbsmith.kicad.placement_surrogates import evaluate_placement_surrogates
from pcbsmith.placement_candidate_ir import (
    PlacementMovePolicy,
    PlacementSurrogateEvidence,
)
from pcbsmith.placement_compatibility_ir import (
    LegacyRectangularPlacementAdapterResult,
)
from pcbsmith.placement_detail_ir import (
    PlacementDetailBudget,
    PlacementDetailSelectionPolicy,
    PlacementR2Policy,
)
from pcbsmith.placement_exact_ir import PlacementExactBudget, PlacementExactPolicy
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.placement_ir import (
    FootprintPlacementRegion,
    PlacementBudget,
    PlacementLegalizationPolicy,
    PlacementOccupancySpan,
    PlacementRegionVerification,
)
from pcbsmith.placement_surrogate_ir import EscapeRay, PlacedTerminalCopper
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

CHECKER_ID = "r5.6-rectangular-compatibility-fixture-v1"


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _fixture() -> tuple[BoardLayout, BoardNetlist, TrackSegment, ViaSpec]:
    component = BoardComponent("U1", "fixture", "fixture:U1", "uuid:U1")
    fixed = TrackSegment(0.5, 1.0, 2.0, 1.0, "B.Cu", "FIXED", 0.3)
    stale_target = TrackSegment(0.5, 2.0, 2.0, 2.0, "F.Cu", "A", 0.2)
    fixed_via = ViaSpec(2.0, 1.0, "FIXED", 0.7, 0.35)
    stale_target_via = ViaSpec(2.0, 2.0, "A", 0.6, 0.3)
    layout = BoardLayout(
        placements=((component, 5.0),),
        segments=(fixed, stale_target),
        vias=(fixed_via, stale_target_via),
        width_mm=12.0,
        height_mm=10.0,
        parts_row_y_mm=4.0,
        part_y_mm=(("U1", 5.0),),
        part_rotation=(("U1", 90.0),),
        zones=(("FIXED", "B.Cu", (0.5, 0.5, 3.0, 3.0)),),
        outline=((0.0, 0.0), (12.0, 0.0), (12.0, 10.0), (0.0, 10.0)),
        graphics=('(gr_text sentinel (at 1 1) (layer "F.SilkS"))',),
        part_flip=("U1",),
        hide_references=("U1",),
        part_reference_at=(("U1", (0.2, -0.1, 90.0)),),
    )
    netlist = BoardNetlist(
        components=(component,),
        nets=(
            BoardNet("A", (("U1", "1"),)),
            BoardNet("FIXED", (("U1", "2"),)),
        ),
    )
    return layout, netlist, fixed, fixed_via


def _budget() -> PlacementBudget:
    return PlacementBudget(
        max_proposals=1,
        max_legalization_evaluations=1,
        max_surrogate_evaluations=1,
        max_corridor_plans=0,
        max_detailed_candidates=1,
        max_exact_checks=1,
        max_r3_geometry_cells_per_candidate=0,
        max_r3_geometry_portals_per_candidate=0,
        max_r3_expansions_per_candidate=0,
        max_r2_passes_per_candidate=2,
        max_r2_expansions_per_candidate=10,
        max_r2_expansions_per_net=10,
        max_r2_stagnant_passes=1,
    )


def _catalog(layout: BoardLayout):
    component = layout.placements[0][0]
    body = _rect(-0.2, -0.2, 0.2, 0.2)
    courtyard = _rect(-0.3, -0.3, 0.3, 0.3)
    regions = (
        FootprintPlacementRegion(
            region_id="U1:body",
            purpose="body",
            occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
            local_compound=body,
            verification=PlacementRegionVerification.EXACT,
            source_layers=("B.Fab",),
            source_fingerprint=body.semantic_fingerprint(),
        ),
        FootprintPlacementRegion(
            region_id="U1:courtyard",
            purpose="courtyard",
            occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
            local_compound=courtyard,
            verification=PlacementRegionVerification.EXACT,
            source_layers=("B.CrtYd",),
            source_fingerprint=courtyard.semantic_fingerprint(),
        ),
    )
    return build_placement_geometry_catalog(
        layout, (bind_component_placement_geometry(component, regions=regions),)
    )


def test_opt_in_rectangular_adapter_preserves_fields_and_source_authority() -> None:
    layout, netlist, fixed, fixed_via = _fixture()
    budget = _budget()
    adapted = adapt_legacy_rectangular_placement(layout, netlist, ("A",), budget=budget)
    assert adapted.source_layout is layout
    assert adapted.source_netlist is netlist
    assert adapted.source_profile is DEFAULT_PCB_RULE_PROFILE
    assert adapted.result.compatibility_only
    assert not adapted.result.exact_shaped_body_authority
    assert (
        adapted.result.semantic_fingerprint()
        == "74400f87b973134bdeff897b4ae37693965af489a6299162098955c27dc425cd"
    )
    assert (
        adapted.result.source_authority_fingerprint
        == "484ddc8250208d5a88b371e72daa9117a79d3214b446d786b12c3f7ca93c3ec6"
    )
    assert (
        adapted.result.input_fingerprint
        == "e47cdef9170ca5e234338b28f3d2e50a0c6c232e9e225b2b59f27218a605a4c1"
    )
    assert (
        adapted.result.probe_result_fingerprint
        == "33b5e675159de56d3130abaea4e49d2aa22a7959e0d3f2efaf5cdfd686f997c2"
    )
    for field in fields(BoardLayout):
        if field.name not in {"segments", "vias"}:
            assert getattr(adapted.probe.layout, field.name) == getattr(layout, field.name)
    assert adapted.probe.layout.segments == (fixed,)
    assert adapted.probe.layout.vias == (fixed_via,)
    restored = LegacyRectangularPlacementAdapterResult.model_validate_json(
        adapted.result.model_dump_json()
    )
    assert restored == adapted.result


RESISTOR = "Resistor_SMD:R_0603_1608Metric"


def _real_route_fixture() -> tuple[BoardLayout, BoardNetlist]:
    components = (
        BoardComponent("R1", "1k", RESISTOR, "uuid:R1"),
        BoardComponent("R2", "1k", RESISTOR, "uuid:R2"),
    )
    return (
        BoardLayout(
            placements=((components[0], 5.0), (components[1], 25.0)),
            segments=(),
            vias=(),
            width_mm=30.0,
            height_mm=12.0,
            part_y_mm=(("R1", 6.0), ("R2", 6.0)),
        ),
        BoardNetlist(
            components=components,
            nets=(
                BoardNet("/SIG", (("R1", "2"), ("R2", "1"))),
                BoardNet("/A", (("R1", "1"),)),
                BoardNet("/B", (("R2", "2"),)),
            ),
        ),
    )


def _real_catalog(layout: BoardLayout):
    bound = []
    for component, _x_mm in layout.placements:
        body = _rect(-0.8, -0.4, 0.8, 0.4)
        courtyard = _rect(-0.9, -0.5, 0.9, 0.5)
        regions = (
            FootprintPlacementRegion(
                region_id=f"{component.reference}:body",
                purpose="body",
                occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
                local_compound=body,
                verification=PlacementRegionVerification.EXACT,
                source_layers=("F.Fab",),
                source_fingerprint=body.semantic_fingerprint(),
            ),
            FootprintPlacementRegion(
                region_id=f"{component.reference}:courtyard",
                purpose="courtyard",
                occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
                local_compound=courtyard,
                verification=PlacementRegionVerification.EXACT,
                source_layers=("F.CrtYd",),
                source_fingerprint=courtyard.semantic_fingerprint(),
            ),
        )
        bound.append(bind_component_placement_geometry(component, regions=regions))
    return build_placement_geometry_catalog(layout, tuple(bound))


class _RealSurrogate:
    def __init__(self) -> None:
        self.result: Any = None

    def __call__(self, probe: PlacementProbe, legalization: Any) -> PlacementSurrogateEvidence:
        assert legalization.telemetry.pose_fingerprint == probe.result.telemetry.pose_fingerprint
        terminals = (
            PlacedTerminalCopper(
                terminal_id="R1:2",
                source_id="source:R1:2:F.Cu",
                component_reference="R1",
                net_name="/SIG",
                layer="F.Cu",
                center_mm=(5.8, 6.0),
                copper=_rect(5.7, 5.9, 5.9, 6.1),
                escape_rays=(EscapeRay(dx=1, dy=0),),
            ),
            PlacedTerminalCopper(
                terminal_id="R2:1",
                source_id="source:R2:1:F.Cu",
                component_reference="R2",
                net_name="/SIG",
                layer="F.Cu",
                center_mm=(24.2, 6.0),
                copper=_rect(24.1, 5.9, 24.3, 6.1),
                escape_rays=(EscapeRay(dx=-1, dy=0),),
            ),
        )
        self.result = evaluate_placement_surrogates(
            terminals,
            pose_fingerprint=probe.result.telemetry.pose_fingerprint,
            probe_layout_fingerprint=probe.result.telemetry.probe_layout_fingerprint,
        )
        return PlacementSurrogateEvidence(
            evaluator_id="r5.6-real-route-surrogate-v1",
            evidence_fingerprint=self.result.semantic_fingerprint(),
        )


def test_real_r5_route_matches_unchanged_legacy_route_board_exactly() -> None:
    layout, netlist = _real_route_fixture()
    budget = _budget().model_copy(
        update={
            "max_r2_passes_per_candidate": 4,
            "max_r2_expansions_per_candidate": 50_000,
            "max_r2_expansions_per_net": 50_000,
            "max_r2_stagnant_passes": 4,
        }
    )
    adapted = adapt_legacy_rectangular_placement(layout, netlist, ("/SIG",), budget=budget)
    legacy = route_board(
        adapted.probe.layout,
        netlist,
        default_width_mm=0.4,
        net_order=("/SIG",),
        max_passes=4,
        max_expansions=50_000,
        max_expansions_per_net=50_000,
        grid_mm=0.25,
    )
    assert legacy.run_result.success and legacy.failed == ()

    surrogate = _RealSurrogate()
    search = generate_placement_candidates(
        adapted.source_layout,
        _real_catalog(adapted.source_layout),
        PlacementMovePolicy(
            translation_step_mm=1.0,
            maximum_translation_steps=0,
            pair_move_limit=0,
            seed=7,
        ),
        PlacementLegalizationPolicy(
            policy_id="r5.6-real-route-compatibility-v1",
            minimum_body_spacing_mm=0.01,
            minimum_courtyard_spacing_mm=0.0,
            minimum_body_outer_edge_clearance_mm=0.01,
            minimum_body_cutout_clearance_mm=0.01,
            require_courtyard_containment=False,
            minimum_courtyard_outer_edge_clearance_mm=0.0,
        ),
        budget,
        target_nets=("/SIG",),
        known_net_names=("/A", "/B", "/SIG"),
        surrogate_evaluator=surrogate,
    )
    assert len(search.probes) == 1 and search.probes[0] == adapted.probe
    candidate = search.result.candidates[0]
    assert surrogate.result is not None
    detail = evaluate_placement_details(
        {
            candidate.candidate_fingerprint: PlacementDetailInput(
                candidate=candidate,
                probe=search.probes[0],
                surrogate=surrogate.result,
                netlist=netlist,
            )
        },
        selection_policy=PlacementDetailSelectionPolicy(coarse_failure_exploration_quota=0),
        budget=PlacementDetailBudget(
            max_selected_candidates=1,
            max_corridor_evaluations=0,
            max_routing_evaluations=1,
        ),
        r2_policy=PlacementR2Policy(
            target_nets=("/SIG",),
            default_width_mm=0.4,
            grid_mm=0.25,
            max_passes=4,
            max_expansions=50_000,
            max_expansions_per_net=50_000,
            max_stagnant_passes=4,
        ),
    )
    assert detail.routed_layouts == ((candidate.candidate_fingerprint, legacy.layout),)

    def checker(checked: BoardLayout, checked_netlist: BoardNetlist) -> ExactRouteCheckResult:
        assert checked == legacy.layout
        assert checked_netlist == netlist
        return ExactRouteCheckResult(accepted=True, checker_id=CHECKER_ID)

    exact = evaluate_placement_exact(
        detail,
        netlists_by_candidate_fingerprint={candidate.candidate_fingerprint: netlist},
        policy=PlacementExactPolicy(checker_id=CHECKER_ID),
        budget=PlacementExactBudget(max_exact_checks=1),
        checker=checker,
    )
    assert exact.result.accepted_candidate_fingerprints == (candidate.candidate_fingerprint,)


@pytest.mark.parametrize("source", ("layout", "netlist", "profile"))
def test_serialized_source_snapshot_tampering_is_rejected(source: str) -> None:
    layout, netlist, _fixed, _fixed_via = _fixture()
    result = adapt_legacy_rectangular_placement(layout, netlist, ("A",), budget=_budget()).result
    payload = json.loads(result.model_dump_json())
    if source == "layout":
        snapshot = json.loads(payload["source_layout_snapshot_json"])
        for item in snapshot["fields"]:
            if item[0] == "width_mm":
                item[1] = 13.0
                break
        payload["source_layout_snapshot_json"] = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":")
        )
    elif source == "netlist":
        snapshot = json.loads(payload["source_netlist_snapshot_json"])
        snapshot["components"][0]["value"] = "tampered"
        payload["source_netlist_snapshot_json"] = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":")
        )
    else:
        payload["source_profile"]["geometry"]["substrate_description"] = "tampered"
    message = (
        "source profile fingerprint"
        if source == "profile"
        else f"source {source} snapshot fingerprint"
    )
    with pytest.raises(ValidationError, match=message):
        LegacyRectangularPlacementAdapterResult.model_validate(payload)


def test_snapshot_text_is_copy_isolated_and_noncanonical_json_is_rejected() -> None:
    layout, netlist, _fixed, _fixed_via = _fixture()
    result = adapt_legacy_rectangular_placement(layout, netlist, ("A",), budget=_budget()).result
    before_json = result.source_layout_snapshot_json
    before_fingerprint = result.semantic_fingerprint()
    detached = json.loads(before_json)
    detached["fields"][0][1] = "detached mutation"
    assert result.source_layout_snapshot_json == before_json
    assert result.semantic_fingerprint() == before_fingerprint

    payload = json.loads(result.model_dump_json())
    payload["source_layout_snapshot_json"] = before_json + " "
    with pytest.raises(ValidationError, match="snapshot JSON must be canonical"):
        LegacyRectangularPlacementAdapterResult.model_validate(payload)


def test_adapter_rejects_shaped_authority_and_is_explicitly_opt_in() -> None:
    layout, netlist, _fixed, _fixed_via = _fixture()
    shaped = replace(
        layout,
        outline=((0.0, 0.0), (12.0, 0.0), (8.0, 6.0), (0.0, 10.0)),
    )
    with pytest.raises(ValueError, match="not exact shaped-body authority"):
        adapt_legacy_rectangular_placement(shaped, netlist, ("A",), budget=_budget())
