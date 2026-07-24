from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError
from tests.fixtures.routing.reduced_capacity_two_stem import (
    CAPACITY_QUANTUM_MM,
    COARSE_GRID_MM,
    DETAILED_GRID_MM,
    NET_NAMES,
    TRACK_WIDTH_MM,
    make_reduced_capacity_two_stem_board,
)

import pcbsmith.kicad.placement_routability as routability
from pcbsmith.corridor_ir import CorridorBudget, CorridorCostPolicy, CorridorViaPolicy
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.corridor_planner import CorridorGraphBuildBudget, OpaqueGraphicsPolicy
from pcbsmith.kicad.negotiated_graph import NegotiatedCostPolicy
from pcbsmith.kicad.placement_candidates import generate_placement_candidates
from pcbsmith.kicad.placement_routability import (
    PlacementProbe,
    bind_component_placement_geometry,
    build_placement_geometry_catalog,
    build_placement_probe,
    legalize_placement_probe,
)
from pcbsmith.placement_candidate_ir import (
    PlacementCandidateDisposition,
    PlacementMovePolicy,
    PlacementProposalKind,
    PlacementSurrogateEvidence,
)
from pcbsmith.placement_detail_ir import (
    PlacementDetailBudget,
    PlacementDetailSelectionPolicy,
    PlacementR2Policy,
)
from pcbsmith.placement_exact_ir import PlacementExactBudget, PlacementExactPolicy
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.placement_ir import (
    ComponentPose,
    FootprintPlacementRegion,
    PlacementBudget,
    PlacementGeometryCatalog,
    PlacementLegalizationOutcome,
    PlacementLegalizationPolicy,
    PlacementLegalizationResult,
    PlacementOccupancySpan,
    PlacementProbePolicy,
    PlacementRegionVerification,
    PlacementSidePermission,
)
from pcbsmith.placement_pilot_authority import (
    PlacementPilotAuthority,
    PlacementPilotCorridorDemandPolicy,
    build_placement_pilot_authority,
)
from pcbsmith.placement_surrogate_ir import (
    CallerClearanceGroup,
    PlacementSurrogatePolicy,
)
from pcbsmith.routing_ir import RoutingBudget
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

MOVABLE = ("J1", "J2")
REDUCED_STEM_AGGREGATE_CHECKER_ID = (
    "synthetic-routing-only-placement-checker@2:"
    "a98e1dacdb1125a0dc2ee1f6dff414490bca78b7aae3a792dfe1c68d11ed60c7"
)


def _rect(size: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(outer=((-size, -size), (size, -size), (size, size), (-size, size))),
        )
    )


def _region(reference: str, purpose: str, size: float) -> FootprintPlacementRegion:
    compound = _rect(size)
    return FootprintPlacementRegion(
        region_id=f"reduced-stem:{reference}:{purpose}",
        purpose=purpose,
        occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
        local_compound=compound,
        verification=PlacementRegionVerification.EXACT,
        source_layers=("F.Fab" if purpose == "body" else "F.CrtYd",),
        source_fingerprint=compound.semantic_fingerprint(),
    )


def _catalog(
    *,
    layout: BoardLayout | None = None,
    unsupported_reference: str | None = None,
) -> PlacementGeometryCatalog:
    board = make_reduced_capacity_two_stem_board()
    source_layout = board.layout if layout is None else layout
    components = []
    for component, _x in source_layout.placements:
        if component.reference == unsupported_reference:
            unsupported = FootprintPlacementRegion(
                region_id=f"reduced-stem:{component.reference}:body",
                purpose="body",
                occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
                local_compound=None,
                verification=PlacementRegionVerification.UNSUPPORTED,
                source_layers=(),
                source_fingerprint=hashlib.sha256(
                    f"unsupported:{component.reference}".encode()
                ).hexdigest(),
            )
            body = unsupported
        else:
            body = _region(component.reference, "body", 0.4)
        components.append(
            bind_component_placement_geometry(
                component,
                regions=(body, _region(component.reference, "courtyard", 0.5)),
            )
        )
    return build_placement_geometry_catalog(source_layout, tuple(components))


def _move_policy(**changes: Any) -> PlacementMovePolicy:
    values: dict[str, Any] = {
        "movable_references": MOVABLE,
        "rotatable_references": MOVABLE,
        "flippable_references": MOVABLE,
        "translation_step_mm": COARSE_GRID_MM,
        "maximum_translation_steps": 1,
        "allowed_rotation_deg": (90.0,),
        "pair_move_limit": 0,
        "seed": 20260717,
    }
    values.update(changes)
    return PlacementMovePolicy(**values)


def _legalization_policy(**changes: Any) -> PlacementLegalizationPolicy:
    values: dict[str, Any] = {
        "policy_id": "reduced-stem-placement-pilot-v1",
        "minimum_body_spacing_mm": 0.1,
        "minimum_courtyard_spacing_mm": 0.0,
        "minimum_body_outer_edge_clearance_mm": 0.1,
        "minimum_body_cutout_clearance_mm": 0.1,
        "require_courtyard_containment": True,
        "minimum_courtyard_outer_edge_clearance_mm": 0.0,
        "side_permissions": tuple(
            PlacementSidePermission(reference=reference, allowed_sides=("front", "back"))
            for reference in MOVABLE
        ),
        "edge_exceptions": (),
    }
    values.update(changes)
    return PlacementLegalizationPolicy(**values)


def _placement_budget(**changes: int) -> PlacementBudget:
    values = {
        "max_proposals": 2,
        "max_legalization_evaluations": 2,
        "max_surrogate_evaluations": 2,
        "max_corridor_plans": 1,
        "max_detailed_candidates": 1,
        "max_exact_checks": 1,
        "max_r3_geometry_cells_per_candidate": 126,
        "max_r3_geometry_portals_per_candidate": 200,
        "max_r3_expansions_per_candidate": 300,
        "max_r2_passes_per_candidate": 4,
        "max_r2_expansions_per_candidate": 1000,
        "max_r2_expansions_per_net": 600,
        "max_r2_stagnant_passes": 2,
    }
    values.update(changes)
    return PlacementBudget(**values)


def _kwargs() -> dict[str, Any]:
    return {
        "geometry_catalog": _catalog(),
        "movable_references": MOVABLE,
        "move_policy": _move_policy(),
        "legalization_policy": _legalization_policy(),
        "target_net_names": NET_NAMES,
        "target_net_widths_mm": tuple((name, TRACK_WIDTH_MM) for name in NET_NAMES),
        "corridor_demand_policies": tuple(
            PlacementPilotCorridorDemandPolicy(
                net_name=name,
                allowed_layers=("F.Cu",),
                via_policy=CorridorViaPolicy.FORBIDDEN,
            )
            for name in NET_NAMES
        ),
        "profile": DEFAULT_PCB_RULE_PROFILE,
        "clearance_groups": (
            CallerClearanceGroup(
                nets_a=(NET_NAMES[0],),
                nets_b=(NET_NAMES[1],),
                minimum_clearance_mm=0.2,
            ),
        ),
        "coarse_grid_mm": COARSE_GRID_MM,
        "detailed_grid_mm": DETAILED_GRID_MM,
        "corridor_capacity_quantum_mm": CAPACITY_QUANTUM_MM,
        "placement_budget": _placement_budget(),
        "surrogate_policy": PlacementSurrogatePolicy(
            clearance_review_bands_um=(100,), escape_grid_mm=0.25
        ),
        "corridor_graphics_policy": OpaqueGraphicsPolicy.REJECT_OPAQUE,
        "corridor_graph_budget": CorridorGraphBuildBudget(max_cells=126, max_portals=200),
        "corridor_budget": CorridorBudget(
            max_passes=3,
            max_expansions=300,
            max_expansions_per_demand=200,
            max_stagnant_passes=1,
        ),
        "corridor_cost_policy": CorridorCostPolicy(
            channel_step_cost_units=1000,
            via_step_cost_units=5000,
            present_factor_units=1,
            present_growth_numerator=2,
            present_growth_denominator=1,
            history_increment_units=4,
        ),
        "detail_selection_policy": PlacementDetailSelectionPolicy(
            policy_id="reduced-stem-detail-v1",
            portal_overflow_bucket_upper_bounds=(0, 1, 3),
            coarse_failure_exploration_quota=1,
            allow_unguided_when_corridor_unavailable=False,
        ),
        "detail_budget": PlacementDetailBudget(
            max_selected_candidates=1,
            max_corridor_evaluations=1,
            max_routing_evaluations=1,
        ),
        "r2_policy": PlacementR2Policy(
            target_nets=NET_NAMES,
            net_widths_mm=tuple((name, TRACK_WIDTH_MM) for name in NET_NAMES),
            net_order=NET_NAMES,
            default_width_mm=TRACK_WIDTH_MM,
            grid_mm=DETAILED_GRID_MM,
            off_corridor_penalty_units=50,
            max_passes=4,
            max_expansions=1000,
            max_expansions_per_net=600,
            max_stagnant_passes=2,
            length_units_per_grid=1000,
            diagonal_length_units=1414,
            via_cost_units=5000,
            turn_cost_units=100,
            present_factor_units=1,
            present_growth_numerator=2,
            present_growth_denominator=1,
            history_increment_units=4,
        ),
        "routing_budget": RoutingBudget(
            max_passes=4,
            max_expansions=1000,
            max_expansions_per_net=600,
            max_stagnant_passes=2,
            max_exact_check_rejections=0,
        ),
        "negotiated_cost_policy": NegotiatedCostPolicy(),
        "exact_policy": PlacementExactPolicy(
            policy_id="reduced-stem-exact-v1",
            checker_id=REDUCED_STEM_AGGREGATE_CHECKER_ID,
        ),
        "exact_budget": PlacementExactBudget(max_exact_checks=1),
    }


def _authority(**changes: Any) -> PlacementPilotAuthority:
    board = make_reduced_capacity_two_stem_board()
    values = _kwargs()
    values.update(changes)
    return build_placement_pilot_authority(board.layout, board.netlist, **values)


class _FixtureSurrogate:
    def __call__(
        self,
        probe: PlacementProbe,
        legalization_result: PlacementLegalizationResult,
    ) -> PlacementSurrogateEvidence:
        assert legalization_result.outcome is PlacementLegalizationOutcome.LEGAL_EXACT
        return PlacementSurrogateEvidence(
            evaluator_id="reduced-stem-typed-fixture-boundary",
            evidence_fingerprint=hashlib.sha256(
                probe.result.telemetry.pose_fingerprint.encode()
            ).hexdigest(),
        )


def test_reduced_stem_authority_and_base_and_translated_candidate_replay_exactly() -> None:
    board = make_reduced_capacity_two_stem_board()
    authority = _authority()
    retained = PlacementPilotAuthority.model_validate_json(authority.model_dump_json())
    assert retained == authority
    assert retained.layout() == board.layout
    assert retained.netlist() == board.netlist
    assert retained.authority_scope == "input_only_no_algorithm_routing_acceptance_or_readiness"
    assert (
        retained.authority_fingerprint
            == "a81f4479bc959156175b4a9e3947878ba1831f44935f3ca905924ccf683b13a9"
    )

    base_poses = tuple(
        ComponentPose(
            reference=component.reference,
            x_mm=x,
            y_mm=dict(board.layout.part_y_mm)[component.reference],
            rotation_deg=0.0,
            side="front",
        )
        for component, x in board.layout.placements
    )
    base_probe = build_placement_probe(
        board.layout,
        base_poses,
        NET_NAMES,
        known_net_names=NET_NAMES,
        policy=PlacementProbePolicy(
            required_references=tuple(pose.reference for pose in base_poses),
            allow_unchanged_non_target_references=False,
        ),
        budget=authority.placement_budget,
    )
    base_legal = legalize_placement_probe(
        base_probe,
        authority.geometry_catalog,
        authority.legalization_policy,
        legalization_evaluations_consumed=0,
    )
    assert base_legal.outcome is PlacementLegalizationOutcome.LEGAL_EXACT

    search = generate_placement_candidates(
        board.layout,
        authority.geometry_catalog,
        authority.move_policy,
        authority.legalization_policy,
        authority.placement_budget,
        target_nets=authority.target_net_names,
        known_net_names=NET_NAMES,
        profile=authority.profile,
        surrogate_evaluator=_FixtureSurrogate(),
    )
    assert len(search.result.candidates) == 2
    base, translated = search.result.candidates
    assert base.provenance.proposal_kind is PlacementProposalKind.BASE
    assert translated.provenance.proposal_kind is PlacementProposalKind.SINGLE
    assert translated.provenance.moved_references == ("J1",)
    assert translated.provenance.clauses[0].delta_x_mm == -COARSE_GRID_MM
    assert translated.disposition is PlacementCandidateDisposition.SURROGATE_EVALUATED
    assert translated.legalization_result.outcome is PlacementLegalizationOutcome.LEGAL_EXACT
    assert (
        base.candidate_fingerprint
        == "f7ae17969195bccc5f2d64e1e54657f3341936b6d22af6647c64b75f9c7fff53"
    )
    assert (
        translated.candidate_fingerprint
        == "f5550a624f6326463b8df0e9a6d041d1e2efe0c7b30ceb638ee1d41232ee4f0a"
    )

    for probe in search.probes:
        assert probe.layout.outline == board.layout.outline
        assert probe.layout.graphics == board.layout.graphics
        assert probe.layout.zones == board.layout.zones
        assert probe.layout.mask_apertures == board.layout.mask_apertures
        assert probe.layout.cutouts == board.layout.cutouts
        assert probe.layout.segments == board.layout.segments
        assert probe.layout.vias == board.layout.vias
        assert tuple(component for component, _x in probe.layout.placements) == tuple(
            component for component, _x in board.layout.placements
        )
    repeated = _authority()
    reversed_inputs = _authority(
        movable_references=tuple(reversed(MOVABLE)),
        target_net_names=tuple(reversed(NET_NAMES)),
        target_net_widths_mm=tuple(reversed(tuple((name, TRACK_WIDTH_MM) for name in NET_NAMES))),
    )
    assert repeated == authority == reversed_inputs


@pytest.mark.parametrize(
    "demand_update",
    (
        {"allowed_layers": ("B.Cu",)},
        {"via_policy": CorridorViaPolicy.ALLOWED},
    ),
)
def test_corridor_demand_policy_tamper_is_fingerprint_bound(
    demand_update: dict[str, Any],
) -> None:
    payload = _authority().model_dump(mode="python")
    first = payload["corridor_demand_policies"][0]
    payload["corridor_demand_policies"] = (
        {**first, **demand_update},
        *payload["corridor_demand_policies"][1:],
    )
    with pytest.raises(ValidationError, match="policy bundle fingerprint"):
        PlacementPilotAuthority.model_validate(payload)


def test_bare_or_stale_exact_checker_identity_is_rejected() -> None:
    payload = _authority().model_dump(mode="python")
    payload["exact_policy"] = {
        **payload["exact_policy"],
        "checker_id": "aggregate-exact-v1",
    }
    with pytest.raises(ValidationError, match="policy bundle fingerprint"):
        PlacementPilotAuthority.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_net_widths_mm", ((NET_NAMES[0], TRACK_WIDTH_MM),)),
        (
            "target_net_widths_mm",
            (
                (NET_NAMES[0], TRACK_WIDTH_MM),
                (NET_NAMES[1], TRACK_WIDTH_MM),
                ("/EXTRA", TRACK_WIDTH_MM),
            ),
        ),
        ("movable_references", ("J1", "FOREIGN")),
        ("coarse_grid_mm", 0.0),
        ("detailed_grid_mm", float("inf")),
        ("corridor_capacity_quantum_mm", 0.0),
    ],
)
def test_authority_rejects_incomplete_foreign_or_nonfinite_inputs(field: str, value: Any) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _authority(**{field: value})


def test_authority_rejects_missing_and_unsupported_movable_geometry() -> None:
    catalog = _catalog()
    with pytest.raises((ValidationError, ValueError), match="exactly cover"):
        _authority(geometry_catalog=replace_catalog(catalog, catalog.components[:-1]))
    with pytest.raises((ValidationError, ValueError), match="exact and supported"):
        _authority(geometry_catalog=_catalog(unsupported_reference="J1"))


def replace_catalog(
    catalog: PlacementGeometryCatalog, components: tuple[Any, ...]
) -> PlacementGeometryCatalog:
    return PlacementGeometryCatalog(
        template_fingerprint=catalog.template_fingerprint,
        components=components,
    )


def test_authority_rejects_foreign_clearance_and_illegal_move_permissions() -> None:
    with pytest.raises((ValidationError, ValueError), match="foreign net"):
        _authority(
            clearance_groups=(
                CallerClearanceGroup(
                    nets_a=(NET_NAMES[0],),
                    nets_b=("/FOREIGN",),
                    minimum_clearance_mm=0.2,
                ),
            )
        )
    with pytest.raises((ValidationError, ValueError), match="front/back"):
        _authority(
            legalization_policy=_legalization_policy(
                side_permissions=(
                    PlacementSidePermission(reference="J1", allowed_sides=("front",)),
                    PlacementSidePermission(reference="J2", allowed_sides=("front", "back")),
                )
            )
        )
    with pytest.raises((ValidationError, ValueError), match="bounded"):
        _authority(
            movable_references=("J1", "J2", "J3"),
            move_policy=_move_policy(rotatable_references=("J1", "J2", "J3")),
        )


@pytest.mark.parametrize(
    "field",
    [
        "layout_snapshot_fingerprint",
        "netlist_snapshot_fingerprint",
        "geometry_catalog_fingerprint",
        "profile_fingerprint",
        "policy_bundle_fingerprint",
        "budget_bundle_fingerprint",
        "grid_fingerprint",
        "clearance_fingerprint",
        "authority_fingerprint",
    ],
)
def test_stale_top_level_fingerprints_are_rejected(field: str) -> None:
    payload = _authority().model_dump(mode="json")
    payload[field] = "f" * 64
    with pytest.raises((ValidationError, ValueError), match="stale"):
        PlacementPilotAuthority.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "nested", "value"),
    [
        ("profile", "profile_id", "tampered-profile"),
        ("move_policy", "seed", 99),
        ("legalization_policy", "policy_id", "tampered-legalization"),
        ("placement_budget", "max_proposals", 1),
        ("surrogate_policy", "escape_grid_mm", 0.5),
        ("corridor_graph_budget", "max_cells", 99),
        ("corridor_budget", "max_passes", 2),
        ("corridor_cost_policy", "channel_step_cost_units", 999),
        ("detail_selection_policy", "policy_id", "tampered-detail"),
        ("routing_budget", "max_exact_check_rejections", 1),
        ("exact_policy", "checker_id", "tampered-checker"),
    ],
)
def test_nested_tamper_is_rejected(field: str, nested: str, value: Any) -> None:
    payload = _authority().model_dump(mode="json")
    payload[field][nested] = value
    with pytest.raises((ValidationError, ValueError)):
        PlacementPilotAuthority.model_validate(payload)


def test_snapshot_tamper_and_negotiated_cost_payload_tamper_are_rejected() -> None:
    authority = _authority()
    payload = authority.model_dump(mode="json")
    payload["layout_snapshot_json"] = payload["layout_snapshot_json"].replace(
        '"width_mm":14.0', '"width_mm":14.5'
    )
    with pytest.raises((ValidationError, ValueError), match="fingerprint"):
        PlacementPilotAuthority.model_validate(payload)
    payload = authority.model_dump(mode="json")
    payload["netlist_snapshot_json"] = payload["netlist_snapshot_json"].replace(
        '"name":"/STEM_A"', '"name":"/STEM_A_TAMPERED"'
    )
    with pytest.raises((ValidationError, ValueError), match="fingerprint"):
        PlacementPilotAuthority.model_validate(payload)
    payload = authority.model_dump(mode="json")
    payload["geometry_catalog"]["components"][0]["regions"][0]["source_fingerprint"] = "a" * 64
    with pytest.raises((ValidationError, ValueError), match="catalog fingerprint"):
        PlacementPilotAuthority.model_validate(payload)
    payload = authority.model_dump(mode="json")
    payload["clearance_groups"][0]["minimum_clearance_mm"] = 0.3
    with pytest.raises((ValidationError, ValueError), match="clearance fingerprint"):
        PlacementPilotAuthority.model_validate(payload)
    payload = authority.model_dump(mode="json")
    payload["negotiated_cost_policy"]["semantic_payload"].pop("turn_cost_units")
    with pytest.raises((ValidationError, ValueError), match="exactly cover"):
        PlacementPilotAuthority.model_validate(payload)
    payload = authority.model_dump(mode="json")
    payload["corridor_graphics_policy"] = OpaqueGraphicsPolicy.ASSERT_NON_EDGE_CUTS.value
    with pytest.raises((ValidationError, ValueError), match="policy bundle fingerprint"):
        PlacementPilotAuthority.model_validate(payload)


def test_budget_cross_bindings_and_exact_zero_one_less_semantics() -> None:
    with pytest.raises((ValidationError, ValueError), match="cross-bind"):
        _authority(placement_budget=_placement_budget(max_r2_expansions_per_candidate=999))
    zero = PlacementExactBudget(max_exact_checks=0)
    one = PlacementExactBudget(max_exact_checks=1)
    assert zero.max_exact_checks == one.max_exact_checks - 1
    with pytest.raises((ValidationError, ValueError), match="cross-bind"):
        _authority(exact_budget=zero)


def test_existing_probe_field_sentinel_detects_future_unclassified_layout_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = make_reduced_capacity_two_stem_board()
    probe = build_placement_probe(
        board.layout,
        (
            ComponentPose(
                reference=component.reference,
                x_mm=x,
                y_mm=dict(board.layout.part_y_mm)[component.reference],
                rotation_deg=0.0,
                side="front",
            )
            for component, x in board.layout.placements
        ),
        NET_NAMES,
        known_net_names=NET_NAMES,
        policy=PlacementProbePolicy(
            required_references=tuple(
                component.reference for component, _x in board.layout.placements
            )
        ),
        budget=_placement_budget(),
    )
    monkeypatch.setattr(
        routability,
        "PROBE_PRESERVED_LAYOUT_FIELDS",
        routability.PROBE_PRESERVED_LAYOUT_FIELDS - {"graphics"},
    )
    with pytest.raises(ValueError, match="classification is stale"):
        routability.verify_probe_preservation(
            board.layout,
            probe.layout,
            preserved_fields=routability.PROBE_PRESERVED_LAYOUT_FIELDS,
        )


def test_builder_does_not_mutate_callers_and_retains_exact_snapshots() -> None:
    board = make_reduced_capacity_two_stem_board()
    layout_before = canonical_board_layout_snapshot_json(board.layout)
    netlist_before = canonical_board_netlist_snapshot_json(board.netlist)
    kwargs = _kwargs()
    groups_before = kwargs["clearance_groups"]
    authority = build_placement_pilot_authority(board.layout, board.netlist, **kwargs)
    assert canonical_board_layout_snapshot_json(board.layout) == layout_before
    assert canonical_board_netlist_snapshot_json(board.netlist) == netlist_before
    assert kwargs["clearance_groups"] is groups_before
    assert authority.layout_snapshot_json == layout_before
    assert authority.netlist_snapshot_json == netlist_before


def test_layout_only_fixed_mechanical_placement_is_retained_but_cannot_supply_net_nodes() -> None:
    board = make_reduced_capacity_two_stem_board()
    mechanical = BoardComponent(
        reference="H1",
        value="M3",
        footprint="MountingHole:MountingHole_3.2mm_M3",
        uuid_path="reduced-stem-layout-only-h1",
    )
    layout = replace(
        board.layout,
        placements=(*board.layout.placements, (mechanical, 7.0)),
        part_y_mm=(*board.layout.part_y_mm, ("H1", 9.0)),
    )
    kwargs = _kwargs()
    kwargs["geometry_catalog"] = _catalog(layout=layout)
    authority = build_placement_pilot_authority(layout, board.netlist, **kwargs)
    assert authority.layout().placements[-1][0] == mechanical
    assert all(
        reference != "H1" for net in authority.netlist().nets for reference, _pad in net.nodes
    )
    invalid_netlist = replace(
        board.netlist,
        nets=(*board.netlist.nets, BoardNet(name="/MECHANICAL", nodes=(("H1", "1"),))),
    )
    with pytest.raises(ValueError, match="nodes without components"):
        build_placement_pilot_authority(layout, invalid_netlist, **kwargs)


def test_missing_or_identity_mismatched_netlisted_placement_is_rejected() -> None:
    board = make_reduced_capacity_two_stem_board()
    missing_layout = replace(
        board.layout,
        placements=board.layout.placements[1:],
        part_y_mm=board.layout.part_y_mm[1:],
    )
    kwargs = _kwargs()
    kwargs["geometry_catalog"] = _catalog(layout=missing_layout)
    with pytest.raises(ValueError, match="exact layout placement"):
        build_placement_pilot_authority(missing_layout, board.netlist, **kwargs)

    old, x_mm = board.layout.placements[0]
    changed = replace(old, uuid_path="identity-mismatch")
    mismatch_layout = replace(
        board.layout,
        placements=((changed, x_mm), *board.layout.placements[1:]),
    )
    kwargs = _kwargs()
    kwargs["geometry_catalog"] = _catalog(layout=mismatch_layout)
    with pytest.raises(ValueError, match="mismatched"):
        build_placement_pilot_authority(mismatch_layout, board.netlist, **kwargs)


def test_translation_step_and_coarse_routing_grid_are_independent_reviewed_inputs() -> None:
    authority = _authority(
        move_policy=_move_policy(translation_step_mm=1.5),
        coarse_grid_mm=COARSE_GRID_MM,
    )
    retained = PlacementPilotAuthority.model_validate_json(authority.model_dump_json())
    assert retained.move_policy.translation_step_mm == 1.5
    assert retained.coarse_grid_mm == COARSE_GRID_MM
