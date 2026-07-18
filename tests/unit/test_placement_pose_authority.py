from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.board import BoardComponent, BoardLayout
from pcbsmith.placement_pose_authority import (
    PlacementPoseAuthority,
    build_placement_pose_authority,
    derive_exact_placement_poses,
)


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=f"value-{reference}",
        footprint="Resistor_SMD:R_0603_1608Metric",
        uuid_path=f"pose/{reference.lower()}",
    )


def _layout() -> BoardLayout:
    return BoardLayout(
        placements=((_component("R1"), 1.0), (_component("R2"), 2.0), (_component("R3"), 3.0)),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=10.0,
        parts_row_y_mm=5.0,
        part_y_mm=(("R2", 6.0),),
        part_rotation=(("R2", 90.0), ("R3", 17.0)),
        part_flip=("R3",),
    )


def _moved(layout: BoardLayout) -> BoardLayout:
    placements = tuple(
        (component, 8.0 if component.reference == "R2" else x_mm)
        for component, x_mm in layout.placements
    )
    return replace(
        layout,
        placements=placements,
        part_y_mm=(("R2", 7.0),),
        part_rotation=(("R2", 181.0), ("R3", 17.0)),
        part_flip=("R2", "R3"),
    )


def test_exact_pose_closes_sparse_defaults_rotation_and_flip() -> None:
    poses = derive_exact_placement_poses(_layout())

    assert tuple(pose.reference for pose in poses) == ("R1", "R2", "R3")
    assert poses[0].model_dump() == {
        "schema_id": "pcbsmith-exact-placement-pose",
        "schema_version": 1,
        "reference": "R1",
        "x_mm": 1.0,
        "y_mm": 5.0,
        "rotation_deg": 0.0,
        "flipped": False,
    }
    assert (poses[1].x_mm, poses[1].y_mm, poses[1].rotation_deg, poses[1].flipped) == (
        2.0,
        6.0,
        90.0,
        False,
    )
    assert poses[2].rotation_deg == 17.0
    assert poses[2].flipped is True


@pytest.mark.parametrize("which", ("source", "final"))
def test_duplicate_placement_reference_is_rejected_in_source_or_final(which: str) -> None:
    source = _layout()
    duplicate = replace(source, placements=(*source.placements, source.placements[0]))

    with pytest.raises(ValueError, match="placements repeat reference 'R1'"):
        build_placement_pose_authority(
            duplicate if which == "source" else source,
            duplicate if which == "final" else source,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("part_y_mm", (("R1", 4.0), ("R1", 4.5)), "part_y_mm repeats reference"),
        (
            "part_rotation",
            (("R1", 10.0), ("R1", 20.0)),
            "part_rotation repeats reference",
        ),
        ("part_flip", ("R1", "R1"), "part_flip repeats reference"),
    ),
)
@pytest.mark.parametrize("which", ("source", "final"))
def test_duplicate_sparse_pose_records_are_rejected(
    field: str, value: object, message: str, which: str
) -> None:
    source = _layout()
    bad = replace(source, **{field: value})

    with pytest.raises(ValueError, match=message):
        build_placement_pose_authority(
            bad if which == "source" else source,
            bad if which == "final" else source,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("part_y_mm", (("GHOST", 2.0),)),
        ("part_rotation", (("GHOST", 30.0),)),
        ("part_flip", ("GHOST",)),
    ),
)
@pytest.mark.parametrize("which", ("source", "final"))
def test_shadow_pose_records_without_placements_are_rejected(
    field: str, value: object, which: str
) -> None:
    source = _layout()
    bad = replace(source, **{field: value})

    with pytest.raises(ValueError, match="shadow reference 'GHOST'"):
        build_placement_pose_authority(
            bad if which == "source" else source,
            bad if which == "final" else source,
        )


@pytest.mark.parametrize("change", ("missing", "extra"))
def test_source_and_final_reference_sets_must_match(change: str) -> None:
    source = _layout()
    if change == "missing":
        final = replace(
            source,
            placements=source.placements[:-1],
            part_rotation=(("R2", 90.0),),
            part_flip=(),
        )
    else:
        final = replace(source, placements=(*source.placements, (_component("R4"), 4.0)))

    with pytest.raises(ValueError, match="reference sets differ"):
        build_placement_pose_authority(source, final)


def test_fixed_reference_cannot_move_on_any_pose_axis() -> None:
    source = _layout()

    with pytest.raises(ValueError, match="fixed reference 'R2' changed exact pose"):
        build_placement_pose_authority(source, _moved(source), ("R1",))


def test_declared_reference_may_change_x_y_rotation_and_flip() -> None:
    source = _layout()
    authority = build_placement_pose_authority(source, _moved(source), ("R2",))

    before = next(pose for pose in authority.source_poses if pose.reference == "R2")
    after = next(pose for pose in authority.final_poses if pose.reference == "R2")
    assert (before.x_mm, before.y_mm, before.rotation_deg, before.flipped) == (
        2.0,
        6.0,
        90.0,
        False,
    )
    assert (after.x_mm, after.y_mm, after.rotation_deg, after.flipped) == (
        8.0,
        7.0,
        181.0,
        True,
    )


def test_movable_references_are_unique_known_and_canonicalized() -> None:
    source = _layout()
    final = _moved(source)
    forward = build_placement_pose_authority(source, final, ("R2", "R1"))
    reverse = build_placement_pose_authority(source, final, ("R1", "R2"))

    assert forward.movable_references == reverse.movable_references == ("R1", "R2")
    assert forward.result_fingerprint == reverse.result_fingerprint
    with pytest.raises(ValueError, match="unique references"):
        build_placement_pose_authority(source, final, ("R2", "R2"))
    with pytest.raises(ValueError, match="absent from layouts"):
        build_placement_pose_authority(source, final, ("R2", "GHOST"))


def test_json_roundtrip_replays_all_retained_evidence() -> None:
    authority = build_placement_pose_authority(_layout(), _moved(_layout()), ("R2",))

    rebuilt = PlacementPoseAuthority.model_validate_json(authority.model_dump_json())

    assert rebuilt == authority
    assert rebuilt.authority_scope == "exact_pose_only_no_render_readback_or_drc"


@pytest.mark.parametrize(
    "field",
    (
        "source_layout_snapshot_json",
        "final_layout_snapshot_json",
        "source_poses",
        "final_poses",
        "source_layout_fingerprint",
        "final_layout_fingerprint",
        "result_fingerprint",
    ),
)
def test_retained_snapshot_evidence_and_fingerprint_tampering_is_rejected(field: str) -> None:
    authority = build_placement_pose_authority(_layout(), _moved(_layout()), ("R2",))
    payload = authority.model_dump(mode="python")
    if field.endswith("snapshot_json"):
        snapshot = json.loads(payload[field])
        snapshot["width_mm"] += 1.0
        payload[field] = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    elif field in {"source_poses", "final_poses"}:
        poses = payload[field]
        poses[0]["x_mm"] += 1.0
    else:
        payload[field] = "0" * 64

    with pytest.raises((ValidationError, ValueError)):
        PlacementPoseAuthority.model_validate(payload)


def test_changed_movable_set_tampering_fails_replay() -> None:
    authority = build_placement_pose_authority(_layout(), _moved(_layout()), ("R2",))
    payload = authority.model_dump(mode="python")
    payload["movable_references"] = ("R1",)

    with pytest.raises(ValidationError, match="fixed reference 'R2'"):
        PlacementPoseAuthority.model_validate(payload)


def test_builder_detaches_from_caller_owned_movable_reference_container() -> None:
    movable_references = ["R2"]
    source = _layout()
    authority = build_placement_pose_authority(
        source, source, cast(Any, movable_references)
    )

    movable_references.append("R3")

    assert tuple(pose.reference for pose in authority.source_poses) == ("R1", "R2", "R3")
    assert authority.movable_references == ("R2",)
    assert PlacementPoseAuthority.model_validate_json(authority.model_dump_json()) == authority
