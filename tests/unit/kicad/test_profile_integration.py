from __future__ import annotations

import pytest
from tests.unit.kicad.test_astar_router import _fixture
from tests.unit.kicad.test_rule_profiles import qualified_values
from tests.unit.kicad.test_virtual_drc import _layout, _two_part_netlist

import pcbsmith.kicad.virtual_drc as virtual_drc
from pcbsmith.kicad.astar_router import route_net, with_route
from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
    compute_board_layout,
    render_board_from_layout,
)
from pcbsmith.kicad.layout_score import score_layout
from pcbsmith.kicad.virtual_drc import run_virtual_drc
from pcbsmith.mask_geometry import (
    Capsule,
    MaskAperture,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    Point,
    ViaMaskIntent,
)
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    CopperRole,
    InsulationProfile,
    OrdinaryClearanceRequirement,
    OuterCopperMaskState,
    PcbRuleProfile,
    qualified_insulation_clearance_groups,
)


def with_spacing(**changes: float) -> PcbRuleProfile:
    spacing = DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(update=changes)
    return DEFAULT_PCB_RULE_PROFILE.model_copy(update={"fab_spacing": spacing})


def with_pairwise(minimum_clearance_mm: float) -> PcbRuleProfile:
    requirement = OrdinaryClearanceRequirement(
        requirement_id="a-to-b",
        nets_a=("/A", "/SIG"),
        nets_b=("/B", "/WALL"),
        minimum_clearance_mm=minimum_clearance_mm,
    )
    spacing = DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
        update={"pairwise_clearances": (requirement,)}
    )
    return DEFAULT_PCB_RULE_PROFILE.model_copy(update={"fab_spacing": spacing})


def with_pairwise_selectors(
    *,
    mask_states_a: tuple[OuterCopperMaskState, ...] = (),
    mask_states_b: tuple[OuterCopperMaskState, ...] = (),
    roles_a: tuple[CopperRole, ...] = (),
    roles_b: tuple[CopperRole, ...] = (),
) -> PcbRuleProfile:
    requirement = OrdinaryClearanceRequirement(
        requirement_id="scoped-a-to-b",
        nets_a=("/A",),
        nets_b=("/B",),
        minimum_clearance_mm=0.4,
        mask_states_a=mask_states_a,
        mask_states_b=mask_states_b,
        roles_a=roles_a,
        roles_b=roles_b,
    )
    spacing = DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
        update={"pairwise_clearances": (requirement,)}
    )
    return DEFAULT_PCB_RULE_PROFILE.model_copy(update={"fab_spacing": spacing})


def _track_aperture(source_id: str, y_mm: float) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=MaskSide.FRONT,
        geometry=Capsule(
            a=Point(x_mm=5.0, y_mm=y_mm),
            b=Point(x_mm=45.0, y_mm=y_mm),
            radius_mm=0.2,
        ),
        verification=MaskVerification.EXACT,
    )


def _unresolved_front_aperture() -> MaskAperture:
    return MaskAperture(
        source_id="scoped-unresolved-front-mask",
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=MaskSide.FRONT,
        verification=MaskVerification.UNSUPPORTED,
        unsupported_reason="synthetic board mask geometry is unresolved",
    )


def _track_pair_layout(
    *,
    mask_apertures: tuple[MaskAperture, ...] = (),
    reverse_segments: bool = False,
) -> tuple[BoardLayout, BoardNetlist]:
    segments = (
        TrackSegment(
            x1=5.0,
            y1=5.0,
            x2=45.0,
            y2=5.0,
            layer="F.Cu",
            net_name="/A",
            width_mm=0.2,
        ),
        TrackSegment(
            x1=5.0,
            y1=5.5,
            x2=45.0,
            y2=5.5,
            layer="F.Cu",
            net_name="/B",
            width_mm=0.2,
        ),
    )
    if reverse_segments:
        segments = tuple(reversed(segments))
    return (
        BoardLayout(
            placements=(),
            segments=segments,
            vias=(),
            width_mm=50.0,
            height_mm=15.0,
            mask_apertures=mask_apertures,
        ),
        BoardNetlist(components=(), nets=()),
    )


def with_insulation(*, qualified: bool, clearance_mm: float) -> PcbRuleProfile:
    values = qualified_values()
    barrier = values["barriers"][0].model_copy(
        update={
            "nets_a": ("/A", "/SIG"),
            "nets_b": ("/B", "/WALL"),
            "required_clearance_mm": clearance_mm,
            "required_creepage_mm": max(6.4, clearance_mm),
        }
    )
    if qualified:
        values["barriers"] = (barrier,)
        insulation = InsulationProfile.model_validate(values)
    else:
        insulation = InsulationProfile(
            profile_id="review-only",
            status="review_required",
            barriers=(barrier,),
        )
    return DEFAULT_PCB_RULE_PROFILE.model_copy(update={"insulation": insulation})


def test_explicit_compatibility_profile_matches_implicit_drc() -> None:
    layout = _layout(vias=(ViaSpec(x=0.4, y=15.0, net_name="/A"),))
    netlist = _two_part_netlist()

    assert run_virtual_drc(layout, netlist) == run_virtual_drc(
        layout, netlist, DEFAULT_PCB_RULE_PROFILE
    )


def test_custom_clearance_changes_drc_and_score_consistently() -> None:
    layout = _layout(
        segments=(
            TrackSegment(
                x1=5.0,
                y1=5.0,
                x2=45.0,
                y2=5.0,
                layer="F.Cu",
                net_name="/A",
                width_mm=0.2,
            ),
            TrackSegment(
                x1=5.0,
                y1=5.5,
                x2=45.0,
                y2=5.5,
                layer="F.Cu",
                net_name="/B",
                width_mm=0.2,
            ),
        )
    )
    netlist = _two_part_netlist()
    profile = with_spacing(minimum_copper_clearance_mm=0.4)

    default_findings = run_virtual_drc(layout, netlist)
    custom_findings = run_virtual_drc(layout, netlist, profile)
    assert not any(item.check == "copper_clearance" for item in default_findings)
    assert any(item.check == "copper_clearance" for item in custom_findings)

    default_score = score_layout(layout, netlist)
    custom_score = score_layout(layout, netlist, profile=profile)
    assert custom_score.min_copper_margin_mm == pytest.approx(
        default_score.min_copper_margin_mm - 0.2
    )


def test_custom_edge_clearance_uses_same_profile_entrypoint() -> None:
    layout = _layout(vias=(ViaSpec(x=0.85, y=15.0, net_name="/A"),))
    netlist = _two_part_netlist()
    profile = with_spacing(minimum_copper_to_edge_mm=0.65)

    assert not any(item.check == "edge_clearance" for item in run_virtual_drc(layout, netlist))
    assert any(item.check == "edge_clearance" for item in run_virtual_drc(layout, netlist, profile))


def test_router_emits_profile_vias_and_verifier_accepts_them() -> None:
    wall = TrackSegment(
        x1=15.0,
        y1=0.8,
        x2=15.0,
        y2=11.2,
        layer="F.Cu",
        net_name="/WALL",
        width_mm=0.4,
    )
    layout, netlist = _fixture((wall,))
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={"routing_via_diameter_mm": 0.7, "routing_via_drill_mm": 0.35}
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(update={"geometry": geometry})

    result = route_net(layout, netlist, "/SIG", profile=profile)
    assert result.vias
    assert all(via.size_mm == 0.7 and via.drill_mm == 0.35 for via in result.vias)
    assert run_virtual_drc(with_route(layout, result), netlist, profile) == ()


def test_declared_pairwise_spacing_is_checked_without_changing_global_minimum() -> None:
    layout = _layout(
        segments=(
            TrackSegment(
                x1=5.0,
                y1=5.0,
                x2=45.0,
                y2=5.0,
                layer="F.Cu",
                net_name="/A",
                width_mm=0.2,
            ),
            TrackSegment(
                x1=5.0,
                y1=5.5,
                x2=45.0,
                y2=5.5,
                layer="F.Cu",
                net_name="/B",
                width_mm=0.2,
            ),
        )
    )
    netlist = _two_part_netlist()
    profile = with_pairwise(0.4)

    findings = run_virtual_drc(layout, netlist, profile)
    assert any(item.check == "ordinary_pairwise_clearance" for item in findings)
    assert profile.fab_spacing.minimum_copper_clearance_mm == 0.2


def test_fully_exposed_selector_fires_and_masked_selector_skips() -> None:
    layout, netlist = _track_pair_layout(
        mask_apertures=(
            _track_aperture("open-a", 5.0),
            _track_aperture("open-b", 5.5),
        )
    )
    fully_exposed = with_pairwise_selectors(
        mask_states_a=("fully_exposed",),
        mask_states_b=("fully_exposed",),
        roles_a=("routed_conductor",),
        roles_b=("routed_conductor",),
    )
    masked = with_pairwise_selectors(
        mask_states_a=("masked",),
        mask_states_b=("masked",),
        roles_a=("routed_conductor",),
        roles_b=("routed_conductor",),
    )

    fully_findings = run_virtual_drc(layout, netlist, fully_exposed)
    masked_findings = run_virtual_drc(layout, netlist, masked)
    assert any(item.check == "ordinary_pairwise_clearance" for item in fully_findings)
    assert not any(item.check.startswith("ordinary_pairwise_clearance") for item in masked_findings)


def test_directional_mask_and_role_selectors_survive_reversed_item_order() -> None:
    layout, netlist = _track_pair_layout(
        mask_apertures=(_track_aperture("open-a-only", 5.0),),
        reverse_segments=True,
    )
    directional = with_pairwise_selectors(
        mask_states_a=("fully_exposed",),
        mask_states_b=("masked",),
        roles_a=("routed_conductor",),
        roles_b=("routed_conductor",),
    )
    reversed_scope = with_pairwise_selectors(
        mask_states_a=("masked",),
        mask_states_b=("fully_exposed",),
        roles_a=("routed_conductor",),
        roles_b=("routed_conductor",),
    )

    findings = run_virtual_drc(layout, netlist, directional)
    wrong_scope_findings = run_virtual_drc(layout, netlist, reversed_scope)
    assert any(item.check == "ordinary_pairwise_clearance" for item in findings)
    assert not any(
        item.check.startswith("ordinary_pairwise_clearance") for item in wrong_scope_findings
    )


def test_directional_role_selectors_use_declared_net_sides_not_item_order() -> None:
    layout = BoardLayout(
        placements=(),
        # Tracks are collected before vias, so physical item order is B then A.
        segments=(
            TrackSegment(
                x1=5.0,
                y1=5.0,
                x2=45.0,
                y2=5.0,
                layer="F.Cu",
                net_name="/B",
                width_mm=0.2,
            ),
        ),
        vias=(
            ViaSpec(
                x=25.0,
                y=5.65,
                net_name="/A",
                size_mm=0.6,
                front_mask=ViaMaskIntent.TENTED,
                back_mask=ViaMaskIntent.TENTED,
            ),
        ),
        width_mm=50.0,
        height_mm=15.0,
    )
    netlist = BoardNetlist(components=(), nets=())
    directional = with_pairwise_selectors(
        mask_states_a=("masked",),
        mask_states_b=("masked",),
        roles_a=("via_land",),
        roles_b=("routed_conductor",),
    )
    swapped_roles = with_pairwise_selectors(
        mask_states_a=("masked",),
        mask_states_b=("masked",),
        roles_a=("routed_conductor",),
        roles_b=("via_land",),
    )

    findings = run_virtual_drc(layout, netlist, directional)
    wrong_role_findings = run_virtual_drc(layout, netlist, swapped_roles)
    assert any(item.check == "ordinary_pairwise_clearance" for item in findings)
    assert not any(
        item.check.startswith("ordinary_pairwise_clearance") for item in wrong_role_findings
    )


def test_empty_mask_selectors_keep_fast_path_and_role_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _track_pair_layout()
    profile = with_pairwise_selectors(
        roles_a=("routed_conductor",),
        roles_b=("routed_conductor",),
    )

    def forbidden_exposure_index(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("empty mask selectors must not collect exposure")

    monkeypatch.setattr(virtual_drc, "exposure_index", forbidden_exposure_index)
    findings = run_virtual_drc(layout, netlist, profile)
    assert any(item.check == "ordinary_pairwise_clearance" for item in findings)


def test_unknown_mask_scope_emits_one_deterministic_unverified_finding() -> None:
    layout, netlist = _track_pair_layout(mask_apertures=(_unresolved_front_aperture(),))
    profile = with_pairwise_selectors(
        mask_states_a=("fully_exposed",),
        mask_states_b=("fully_exposed",),
        roles_a=("routed_conductor",),
        roles_b=("routed_conductor",),
    )

    findings = run_virtual_drc(layout, netlist, profile)
    unverified = [
        item for item in findings if item.check == "ordinary_pairwise_clearance_scope_unverified"
    ]
    assert len(unverified) == 1
    assert not any(item.check == "ordinary_pairwise_clearance" for item in findings)
    message = unverified[0].message
    for expected in (
        "scoped-a-to-b",
        "track:0",
        "track:1",
        "F.Cu",
        "scoped-unresolved-front-mask",
        "a relevant aperture has unresolved geometry",
    ):
        assert expected in message


def test_explicit_unknown_mask_selector_matches_ordinary_violation() -> None:
    layout, netlist = _track_pair_layout(mask_apertures=(_unresolved_front_aperture(),))
    profile = with_pairwise_selectors(
        mask_states_a=("unknown",),
        mask_states_b=("unknown",),
        roles_a=("routed_conductor",),
        roles_b=("routed_conductor",),
    )

    findings = run_virtual_drc(layout, netlist, profile)
    assert any(item.check == "ordinary_pairwise_clearance" for item in findings)
    assert not any(
        item.check == "ordinary_pairwise_clearance_scope_unverified" for item in findings
    )


def test_definitive_role_mismatch_suppresses_mask_scope_warning() -> None:
    layout, netlist = _track_pair_layout(mask_apertures=(_unresolved_front_aperture(),))
    profile = with_pairwise_selectors(
        mask_states_a=("fully_exposed",),
        mask_states_b=("fully_exposed",),
        roles_a=("via_land",),
        roles_b=("routed_conductor",),
    )

    findings = run_virtual_drc(layout, netlist, profile)
    assert not any(item.check.startswith("ordinary_pairwise_clearance") for item in findings)


def test_router_and_verifier_share_pairwise_spacing() -> None:

    wall = TrackSegment(
        x1=15.0,
        y1=1.0,
        x2=15.0,
        y2=8.0,
        layer="F.Cu",
        net_name="/WALL",
        width_mm=0.4,
    )
    layout, netlist = _fixture((wall,))
    profile = with_pairwise(0.8)

    result = route_net(layout, netlist, "/SIG", profile=profile)
    findings = run_virtual_drc(with_route(layout, result), netlist, profile)
    assert not any(item.check == "ordinary_pairwise_clearance" for item in findings)


def test_generic_board_generation_uses_profile_widths_vias_and_thickness() -> None:
    netlist = _two_part_netlist()
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={
            "default_signal_trace_width_mm": 0.25,
            "default_power_trace_width_mm": 0.9,
            "routing_via_diameter_mm": 0.55,
            "routing_via_drill_mm": 0.28,
            "power_via_diameter_mm": 1.0,
            "power_via_drill_mm": 0.5,
            "board_thickness_mm": 0.8,
        }
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(update={"geometry": geometry})

    layout = compute_board_layout(
        netlist,
        power_net_names=frozenset({"A"}),
        mounting_holes=False,
        profile=profile,
    )
    power_segments = [item for item in layout.segments if item.net_name == "/A"]
    power_vias = [item for item in layout.vias if item.net_name == "/A"]
    assert any(item.width_mm == 0.9 for item in power_segments)
    assert power_vias
    assert all(item.size_mm == 1.0 and item.drill_mm == 0.5 for item in power_vias)

    board_text = render_board_from_layout(netlist, layout, profile=profile)
    assert "(thickness 0.8)" in board_text


def test_review_only_insulation_does_not_masquerade_as_approved_clearance() -> None:
    layout = _layout(
        segments=(
            TrackSegment(
                x1=5.0,
                y1=5.0,
                x2=45.0,
                y2=5.0,
                layer="F.Cu",
                net_name="/A",
                width_mm=0.2,
            ),
            TrackSegment(
                x1=5.0,
                y1=5.5,
                x2=45.0,
                y2=5.5,
                layer="F.Cu",
                net_name="/B",
                width_mm=0.2,
            ),
        )
    )
    netlist = _two_part_netlist()

    review_findings = run_virtual_drc(
        layout, netlist, with_insulation(qualified=False, clearance_mm=0.4)
    )
    qualified_findings = run_virtual_drc(
        layout, netlist, with_insulation(qualified=True, clearance_mm=0.4)
    )
    assert not any(item.check == "insulation_clearance" for item in review_findings)
    assert any(item.check == "insulation_clearance" for item in qualified_findings)


def test_router_and_verifier_share_qualified_insulation_clearance() -> None:
    wall = TrackSegment(
        x1=15.0,
        y1=1.0,
        x2=15.0,
        y2=8.0,
        layer="F.Cu",
        net_name="/WALL",
        width_mm=0.4,
    )
    layout, netlist = _fixture((wall,))
    profile = with_insulation(qualified=True, clearance_mm=0.8)

    result = route_net(layout, netlist, "/SIG", profile=profile)
    findings = run_virtual_drc(with_route(layout, result), netlist, profile)
    assert not any(item.check == "insulation_clearance" for item in findings)


def test_qualified_insulation_clearance_group_gate_is_shared() -> None:
    review = with_insulation(qualified=False, clearance_mm=0.8)
    qualified = with_insulation(qualified=True, clearance_mm=0.8)

    assert qualified_insulation_clearance_groups(review) == ()
    groups = qualified_insulation_clearance_groups(qualified)
    assert len(groups) == 1
    _barrier_id, nets_a, nets_b, gap_mm, _exempt = groups[0]
    assert nets_a == ("/A", "/SIG")
    assert nets_b == ("/B", "/WALL")
    assert gap_mm == 0.8
