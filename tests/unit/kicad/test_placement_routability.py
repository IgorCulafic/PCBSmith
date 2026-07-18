from __future__ import annotations

from dataclasses import dataclass, fields, replace

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardCutoutPolygon,
    BoardLayout,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.placement_routability import (
    PROBE_MUTABLE_LAYOUT_FIELDS,
    PROBE_PRESERVED_LAYOUT_FIELDS,
    board_layout_fingerprint,
    build_placement_probe,
    verify_probe_preservation,
)
from pcbsmith.mask_geometry import (
    Disc,
    MaskAperture,
    MaskSide,
    MaskSourceKind,
    Point,
    ViaMaskIntent,
)
from pcbsmith.placement_ir import (
    ComponentPose,
    PlacementBudget,
    PlacementProbePolicy,
    PlacementTargetPolicy,
)


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=f"value:{reference}",
        footprint=f"fixture:{reference}",
        uuid_path=f"uuid:{reference}",
        fields=(("sentinel", reference.lower()),),
    )


def _aperture(source_id: str, side: MaskSide, x_mm: float) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=side,
        geometry=Disc(center=Point(x_mm=x_mm, y_mm=3.0), radius_mm=0.4),
        owner_ref="U1",
        copper_source_ids=(f"copper:{source_id}",),
    )


def _sentinel_shaped_template() -> BoardLayout:
    u2 = _component("U2")
    u1 = _component("U1")
    j1 = _component("J1")
    return BoardLayout(
        placements=((u2, 14.0), (u1, 6.0), (j1, 3.0)),
        segments=(
            TrackSegment(1.0, 1.0, 2.0, 1.0, "F.Cu", "/FIX", 0.25),
            TrackSegment(5.0, 5.0, 6.0, 5.0, "F.Cu", "/SIG", 0.2),
            TrackSegment(3.0, 2.0, 4.0, 2.0, "B.Cu", "/FIX", 0.3),
            TrackSegment(7.0, 6.0, 8.0, 6.0, "B.Cu", "/SIG", 0.2),
        ),
        vias=(
            ViaSpec(2.0, 1.0, "/FIX", 0.8, 0.4, ViaMaskIntent.OPEN),
            ViaSpec(6.0, 5.0, "/SIG", 0.7, 0.35, ViaMaskIntent.TENTED),
        ),
        width_mm=20.0,
        height_mm=15.0,
        parts_row_y_mm=5.0,
        part_y_mm=(("U2", 10.0), ("J1", 0.0)),
        part_rotation=(("U2", 37.0), ("J1", 0.0)),
        zones=(
            ("/FIX", "B.Cu", (0.5, 0.5, 19.5, 14.5)),
            ("/SIG", "F.Cu", (5.0, 4.0, 9.0, 7.0)),
        ),
        outline=(
            (0.0, 0.0),
            (20.0, 0.0),
            (20.0, 15.0),
            (12.0, 15.0),
            (12.0, 8.0),
            (8.0, 8.0),
            (8.0, 15.0),
            (0.0, 15.0),
        ),
        graphics=(
            '(gr_text "sentinel" (at 4 12) (layer "F.SilkS"))',
            '(gr_line (start 1 13) (end 6 13) (stroke (width 0.3) (type solid)) (layer "B.SilkS"))',
        ),
        part_flip=("U2",),
        hide_references=("U1",),
        part_reference_at=(
            ("U1", (1.0, -1.0, 15.0)),
            ("U2", (-2.0, 0.5, 217.0)),
        ),
        mask_apertures=(
            _aperture("mask:front", MaskSide.FRONT, 4.0),
            _aperture("mask:back", MaskSide.BACK, 15.0),
        ),
        cutouts=(BoardCutoutPolygon(((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0))),),
    )


def _budget() -> PlacementBudget:
    return PlacementBudget(
        max_proposals=1,
        max_legalization_evaluations=2,
        max_surrogate_evaluations=3,
        max_corridor_plans=4,
        max_detailed_candidates=5,
        max_exact_checks=6,
        max_r3_geometry_cells_per_candidate=7,
        max_r3_geometry_portals_per_candidate=8,
        max_r3_expansions_per_candidate=9,
        max_r2_passes_per_candidate=10,
        max_r2_expansions_per_candidate=11,
        max_r2_expansions_per_net=12,
        max_r2_stagnant_passes=13,
    )


def _policy(*, allow_omitted: bool = True) -> PlacementProbePolicy:
    return PlacementProbePolicy(
        required_references=("U1",),
        allow_unchanged_non_target_references=allow_omitted,
    )


def _moved_u1() -> ComponentPose:
    return ComponentPose(
        reference="U1",
        x_mm=7.25,
        y_mm=6.5,
        rotation_deg=450.0,
        side="back",
    )


def _base_poses(template: BoardLayout) -> dict[str, ComponentPose]:
    return {
        "U2": ComponentPose(reference="U2", x_mm=14.0, y_mm=10.0, rotation_deg=37.0, side="back"),
        "U1": ComponentPose(reference="U1", x_mm=6.0, y_mm=5.0, rotation_deg=0.0, side="front"),
        "J1": ComponentPose(reference="J1", x_mm=3.0, y_mm=0.0, rotation_deg=0.0, side="front"),
    }


def test_pose_policy_and_budget_are_frozen_canonical_and_versioned() -> None:
    pose = _moved_u1()
    assert pose.rotation_deg == 90.0
    assert pose.side == "back"
    assert pose.schema_version == 1
    with pytest.raises(ValidationError, match="frozen"):
        pose.x_mm = 1.0  # type: ignore[misc]
    with pytest.raises(ValidationError, match="finite"):
        ComponentPose(reference="U1", x_mm=float("inf"), y_mm=0.0, rotation_deg=0.0, side="front")

    targets = PlacementTargetPolicy(
        known_net_names=("/SIG", "/FIX"),
        target_net_names=("/SIG",),
    )
    reversed_targets = PlacementTargetPolicy(
        known_net_names=("/FIX", "/SIG"),
        target_net_names=("/SIG",),
    )
    assert targets == reversed_targets
    assert targets.semantic_fingerprint() == reversed_targets.semantic_fingerprint()
    with pytest.raises(ValidationError, match="absent from the known net set"):
        PlacementTargetPolicy(known_net_names=("/FIX",), target_net_names=("/TYPO",))
    assert (
        pose.semantic_fingerprint()
        == "96c65d8172d459f8586144763eae6966023d249757db27dd978f141dc7b4ab17"
    )
    assert (
        targets.semantic_fingerprint()
        == "0c88705af43aadf528ff7afb82decd67bb6220df9e4dddb7f166ced0c715d1e7"
    )
    with pytest.raises(ValidationError):
        PlacementBudget.model_validate({**_budget().model_dump(), "max_proposals": -1})


def test_board_layout_fingerprint_covers_every_reflected_field_and_is_literal() -> None:
    template = _sentinel_shaped_template()
    mutations = {
        "placements": ((*template.placements[:-1], (template.placements[-1][0], 3.5))),
        "segments": (*template.segments, TrackSegment(9.0, 1.0, 10.0, 1.0, "F.Cu", "/FIX", 0.2)),
        "vias": (*template.vias, ViaSpec(10.0, 2.0, "/FIX")),
        "width_mm": 21.0,
        "height_mm": 16.0,
        "parts_row_y_mm": 5.5,
        "part_y_mm": (*template.part_y_mm, ("U1", 5.25)),
        "part_rotation": (*template.part_rotation, ("U1", 45.0)),
        "zones": (*template.zones, ("/FIX", "F.Cu", (1.0, 1.0, 2.0, 2.0))),
        "outline": ((0.0, 0.0), (20.0, 0.0), (18.0, 15.0), (0.0, 15.0)),
        "graphics": (*template.graphics, '(gr_text "changed")'),
        "part_flip": (*template.part_flip, "J1"),
        "hide_references": (*template.hide_references, "U2"),
        "part_reference_at": (*template.part_reference_at, ("J1", (0.0, 0.0, 0.0))),
        "mask_apertures": (*template.mask_apertures, _aperture("mask:extra", MaskSide.FRONT, 9.0)),
        "cutouts": (BoardCutoutPolygon(((2.0, 2.0), (5.0, 2.0), (5.0, 4.0), (2.0, 4.0))),),
    }
    assert set(mutations) == {field.name for field in fields(template)}
    fingerprint = board_layout_fingerprint(template)
    assert fingerprint == "62e77850dc31dddb36fd8ffb54268039b38360b350a33307043e9ded1fad5d55"
    for field_name, value in mutations.items():
        assert board_layout_fingerprint(replace(template, **{field_name: value})) != fingerprint


def test_probe_changes_only_six_fields_and_strips_only_exact_target_copper() -> None:
    template = _sentinel_shaped_template()
    probe = build_placement_probe(
        template,
        {"U1": _moved_u1()},
        {"/SIG"},
        known_net_names={"/FIX", "/SIG"},
        policy=_policy(),
        budget=_budget(),
    )
    layout = probe.layout

    assert probe.result.telemetry.changed_layout_fields == tuple(
        sorted(PROBE_MUTABLE_LAYOUT_FIELDS)
    )
    for field in fields(template):
        if field.name not in PROBE_MUTABLE_LAYOUT_FIELDS:
            assert getattr(layout, field.name) == getattr(template, field.name)
    assert tuple(component.reference for component, _x in layout.placements) == (
        "U2",
        "U1",
        "J1",
    )
    assert all(
        original is derived
        for (original, _old_x), (derived, _new_x) in zip(
            template.placements, layout.placements, strict=True
        )
    )
    assert layout.placements[1][1] == 7.25
    assert layout.part_y_mm == (("U2", 10.0), ("J1", 0.0), ("U1", 6.5))
    assert layout.part_rotation == (("U2", 37.0), ("J1", 0.0), ("U1", 90.0))
    assert layout.part_flip == ("U2", "U1")
    assert tuple(segment.net_name for segment in layout.segments) == ("/FIX", "/FIX")
    assert tuple(via.net_name for via in layout.vias) == ("/FIX",)
    assert layout.segments == (template.segments[0], template.segments[2])
    assert layout.vias == (template.vias[0],)
    assert layout.zones == template.zones
    assert probe.result.telemetry.stripped_segment_count == 2
    assert probe.result.telemetry.stripped_via_count == 1
    assert probe.result.telemetry.explicit_pose_references == ("U1",)
    assert probe.result.telemetry.preserved_pose_references == ("J1", "U2")
    assert probe.result.telemetry.template_reference_order == ("U2", "U1", "J1")
    assert (
        probe.result.telemetry.template_fingerprint
        == "62e77850dc31dddb36fd8ffb54268039b38360b350a33307043e9ded1fad5d55"
    )
    assert (
        probe.result.telemetry.probe_layout_fingerprint
        == "36701ac136a4b8797de9b63277ed2ab4f3bfea02fac6505e6f812e070625d3e9"
    )
    assert (
        probe.result.telemetry.pose_fingerprint
        == "ac30da2e1392b970043562d9c02e17750e6aeaa24d098de3f46e7df8c5591d23"
    )
    assert (
        probe.result.telemetry.target_policy_fingerprint
        == "0c88705af43aadf528ff7afb82decd67bb6220df9e4dddb7f166ced0c715d1e7"
    )
    assert (
        probe.result.telemetry.probe_policy_fingerprint
        == "e94f51ee80e0484e98e9bad3be232b8f08bf5d304929eb0e0ec1660bba307ead"
    )
    assert (
        probe.result.telemetry.budget_fingerprint
        == "7a5f5674894a9c2bd0848585b14a68ca802e57b13ddea62e90278b38524ab861"
    )
    assert (
        probe.result.telemetry.semantic_fingerprint()
        == "bc4e37b17f861ee138958e98664f739432226752f3163ee10d994c17ea19aa50"
    )
    assert (
        probe.result.semantic_fingerprint()
        == "dd68b83c1ca1652154e1224de9813d241acee5c82245b45f86ecaff23f1a583f"
    )


def test_base_probe_round_trips_except_exact_target_route_stripping() -> None:
    template = _sentinel_shaped_template()
    probe = build_placement_probe(
        template,
        _base_poses(template),
        ("/SIG",),
        known_net_names=("/SIG", "/FIX"),
        policy=PlacementProbePolicy(allow_unchanged_non_target_references=False),
        budget=_budget(),
    )
    expected = replace(
        template,
        segments=(template.segments[0], template.segments[2]),
        vias=(template.vias[0],),
    )
    assert probe.layout == expected
    assert probe.result.telemetry.changed_layout_fields == ("segments", "vias")


def test_mapping_and_set_input_order_are_deterministic() -> None:
    template = _sentinel_shaped_template()
    poses = _base_poses(template)
    forward = build_placement_probe(
        template,
        poses,
        {"/SIG"},
        known_net_names={"/SIG", "/FIX"},
        policy=PlacementProbePolicy(allow_unchanged_non_target_references=False),
        budget=_budget(),
    )
    reverse = build_placement_probe(
        template,
        dict(reversed(tuple(poses.items()))),
        tuple(reversed(("/SIG",))),
        known_net_names=tuple(reversed(("/SIG", "/FIX"))),
        policy=PlacementProbePolicy(allow_unchanged_non_target_references=False),
        budget=_budget(),
    )
    assert forward == reverse
    assert forward.result.semantic_fingerprint() == reverse.result.semantic_fingerprint()


def test_unknown_duplicate_and_missing_references_and_nets_fail_closed() -> None:
    template = _sentinel_shaped_template()
    kwargs = {
        "known_net_names": ("/SIG", "/FIX"),
        "policy": _policy(),
        "budget": _budget(),
    }
    with pytest.raises(ValueError, match="unknown template components"):
        build_placement_probe(
            template,
            (ComponentPose(reference="X1", x_mm=1.0, y_mm=1.0, rotation_deg=0.0, side="front"),),
            ("/SIG",),
            **kwargs,
        )
    with pytest.raises(ValueError, match="unique"):
        build_placement_probe(template, (_moved_u1(), _moved_u1()), ("/SIG",), **kwargs)
    with pytest.raises(ValueError, match="missing required"):
        build_placement_probe(template, (), ("/SIG",), **kwargs)
    with pytest.raises(ValueError, match="exactly cover"):
        build_placement_probe(
            template,
            {"U1": _moved_u1()},
            ("/SIG",),
            known_net_names=("/SIG", "/FIX"),
            policy=_policy(allow_omitted=False),
            budget=_budget(),
        )
    with pytest.raises(ValidationError, match="absent from the known net set"):
        build_placement_probe(
            template,
            {"U1": _moved_u1()},
            ("/TYPO",),
            **kwargs,
        )
    with pytest.raises(ValueError, match="keys must match"):
        build_placement_probe(
            template,
            {"WRONG": _moved_u1()},
            ("/SIG",),
            **kwargs,
        )

    duplicate_template = replace(
        template,
        placements=(template.placements[0], template.placements[0]),
        part_y_mm=(("U2", 10.0),),
        part_rotation=(("U2", 37.0),),
        part_flip=("U2",),
    )
    with pytest.raises(ValueError, match="template references must be unique"):
        build_placement_probe(
            duplicate_template,
            {"U1": _moved_u1()},
            ("/SIG",),
            **kwargs,
        )


def test_future_field_preservation_is_fail_closed_until_classified() -> None:
    @dataclass(frozen=True)
    class FutureBoardLayout(BoardLayout):
        future_authority: str = "sentinel"

    base = _sentinel_shaped_template()
    template = FutureBoardLayout(
        **{field.name: getattr(base, field.name) for field in fields(BoardLayout)},
        future_authority="preserve-me",
    )
    with pytest.raises(ValueError, match="field classification is stale"):
        verify_probe_preservation(template, template)
    assert (
        verify_probe_preservation(
            template,
            template,
            preserved_fields=(*PROBE_PRESERVED_LAYOUT_FIELDS, "future_authority"),
        )
        == ()
    )

    changed = replace(template, future_authority="lost")
    with pytest.raises(ValueError, match="changed preserved BoardLayout fields"):
        verify_probe_preservation(
            template,
            changed,
            preserved_fields=(*PROBE_PRESERVED_LAYOUT_FIELDS, "future_authority"),
        )
    assert board_layout_fingerprint(template) != board_layout_fingerprint(changed)
