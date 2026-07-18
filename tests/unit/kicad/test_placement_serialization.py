from __future__ import annotations

import json
from dataclasses import fields, replace
from typing import Any

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardCutoutPolygon,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.placement_serialization import (
    build_placement_serialization_authority,
)
from pcbsmith.mask_geometry import (
    Disc,
    MaskAperture,
    MaskSide,
    MaskSourceKind,
    Point,
    ViaMaskIntent,
)
from pcbsmith.placement_serialization_ir import (
    DEFAULT_SHAPED_SERIALIZATION_DELTA_POLICY,
    LayoutFieldDeltaClass,
    PlacementSerializationAuthority,
)

RESISTOR = "Resistor_SMD:R_0603_1608Metric"
TARGET = "/TARGET"
FIXED = "/FIXED"
MOVABLE = ("R1", "R2")


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=f"{reference}-10k",
        footprint=RESISTOR,
        uuid_path=f"sentinel/sheet/{reference.lower()}",
        fields=(("Tolerance", "0.1%"), ("Manufacturer", f"Exact-{reference}")),
    )


def _aperture(source_id: str, side: MaskSide, x_mm: float) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        parent_source_id=f"parent:{source_id}",
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=side,
        geometry=Disc(center=Point(x_mm=x_mm, y_mm=15.0), radius_mm=0.45),
        owner_ref="R3",
        copper_source_ids=(f"copper:{source_id}",),
        merge_group_id=f"merge:{source_id}",
    )


def _sentinel() -> tuple[BoardLayout, BoardNetlist]:
    r1 = _component("R1")
    r2 = _component("R2")
    r3 = _component("R3")
    layout = BoardLayout(
        placements=((r1, 6.25), (r2, 22.5), (r3, 13.0)),
        segments=(
            TrackSegment(1.0, 1.0, 5.0, 1.0, "F.Cu", FIXED, 0.31),
            TrackSegment(3.0, 18.0, 8.0, 18.0, "B.Cu", FIXED, 0.37),
            TrackSegment(1.0, 1.0, 5.0, 1.0, "F.Cu", FIXED, 0.31),
            TrackSegment(6.25, 6.0, 12.0, 8.0, "F.Cu", TARGET, 0.23),
            TrackSegment(12.0, 8.0, 22.5, 13.5, "B.Cu", TARGET, 0.23),
        ),
        vias=(
            ViaSpec(
                8.0,
                18.0,
                FIXED,
                0.72,
                0.34,
                ViaMaskIntent.OPEN,
                ViaMaskIntent.TENTED,
            ),
            ViaSpec(
                12.0,
                8.0,
                TARGET,
                0.66,
                0.31,
                ViaMaskIntent.TENTED,
                ViaMaskIntent.OPEN,
            ),
        ),
        width_mm=30.0,
        height_mm=20.0,
        parts_row_y_mm=10.0,
        part_y_mm=(("R1", 6.0), ("R2", 13.5), ("R3", 10.25)),
        part_rotation=(("R1", 17.0), ("R2", 223.0), ("R3", 91.0)),
        zones=((FIXED, "B.Cu", (0.75, 0.75, 29.0, 19.0)),),
        outline=(
            (0.0, 0.0),
            (30.0, 0.0),
            (30.0, 20.0),
            (20.0, 20.0),
            (18.0, 17.0),
            (12.0, 17.0),
            (10.0, 20.0),
            (0.0, 20.0),
        ),
        graphics=(
            '  (gr_text "R5.6b sentinel" (at 27 36 11) (layer "F.SilkS"))',
            "  (gr_line (start 22 38) (end 28 38) "
            '(stroke (width 0.25) (type solid)) (layer "B.SilkS"))',
        ),
        part_flip=("R2",),
        hide_references=("R3",),
        part_reference_at=(
            ("R1", (1.25, -1.5, 37.0)),
            ("R2", (-1.0, 0.75, 241.0)),
        ),
        mask_apertures=(
            _aperture("sentinel:front", MaskSide.FRONT, 4.0),
        ),
        cutouts=(BoardCutoutPolygon(((13.0, 3.0), (17.0, 3.0), (17.0, 6.0), (13.0, 6.0))),),
    )
    netlist = BoardNetlist(
        components=(r1, r2, r3),
        nets=(
            BoardNet(TARGET, (("R1", "1"), ("R2", "1"))),
            BoardNet(FIXED, (("R1", "2"), ("R2", "2"), ("R3", "1"), ("R3", "2"))),
        ),
    )
    return layout, netlist


def _build(
    final: BoardLayout | None = None,
    *,
    targets: tuple[str, ...] = (TARGET,),
    movable: tuple[str, ...] = MOVABLE,
) -> PlacementSerializationAuthority:
    source, netlist = _sentinel()
    return build_placement_serialization_authority(
        source,
        netlist,
        source if final is None else final,
        targets,
        movable,
    )


def _payload(
    authority: PlacementSerializationAuthority,
) -> dict[str, Any]:
    return authority.model_dump(mode="python")


def _moved_layout() -> BoardLayout:
    source, _netlist = _sentinel()
    return replace(
        source,
        placements=tuple(
            (component, {"R1": 7.75, "R2": 21.25}.get(component.reference, x_mm))
            for component, x_mm in source.placements
        ),
        part_y_mm=(("R1", 7.0), ("R2", 12.25), ("R3", 10.25)),
        part_rotation=(("R1", 31.0), ("R2", 197.0), ("R3", 91.0)),
    )


def test_no_change_shaped_authority_replays_and_renders_identically() -> None:
    source, netlist = _sentinel()
    authority = _build()

    assert parse_canonical_board_layout_snapshot(authority.source_layout_snapshot_json) == source
    assert parse_canonical_board_layout_snapshot(authority.final_layout_snapshot_json) == source
    assert parse_canonical_board_netlist_snapshot(authority.source_netlist_snapshot_json) == netlist
    assert authority.rendered_board_text.endswith(")\n")
    assert all(not item.changed for item in authority.field_delta_evidence)
    assert (
        PlacementSerializationAuthority.model_validate_json(authority.model_dump_json())
        == authority
    )


def test_allowed_front_and_back_moves_preserve_all_other_fields() -> None:
    final = _moved_layout()
    source, _netlist = _sentinel()

    authority = _build(final)
    changed = {item.field_name: item for item in authority.field_delta_evidence if item.changed}

    assert set(changed) == {"placements", "part_y_mm", "part_rotation"}
    assert changed["placements"].affected_references == MOVABLE
    assert changed["part_y_mm"].affected_references == MOVABLE
    assert changed["part_rotation"].affected_references == MOVABLE
    for rule in DEFAULT_SHAPED_SERIALIZATION_DELTA_POLICY.field_rules:
        if rule.delta_class is LayoutFieldDeltaClass.IMMUTABLE_PRESERVED:
            assert getattr(final, rule.field_name) == getattr(source, rule.field_name)
    assert final.part_flip == ("R2",)


def test_target_route_replacement_preserves_literal_fixed_copper() -> None:
    source, _netlist = _sentinel()
    fixed_segments = tuple(item for item in source.segments if item.net_name != TARGET)
    fixed_vias = tuple(item for item in source.vias if item.net_name != TARGET)
    final = replace(
        source,
        segments=(
            fixed_segments[0],
            TrackSegment(7.0, 7.0, 14.0, 9.0, "F.Cu", TARGET, 0.27),
            fixed_segments[1],
            fixed_segments[2],
            TrackSegment(14.0, 9.0, 21.0, 12.0, "B.Cu", TARGET, 0.27),
        ),
        vias=(
            fixed_vias[0],
            ViaSpec(
                14.0,
                9.0,
                TARGET,
                0.68,
                0.32,
                ViaMaskIntent.OPEN,
                ViaMaskIntent.OPEN,
            ),
        ),
    )

    authority = _build(final)
    evidence = {item.field_name: item for item in authority.field_delta_evidence}

    assert tuple(item for item in final.segments if item.net_name != TARGET) == fixed_segments
    assert tuple(item for item in final.vias if item.net_name != TARGET) == fixed_vias
    assert evidence["segments"].affected_target_nets == (TARGET,)
    assert evidence["vias"].affected_target_nets == (TARGET,)


def _preserved_field_mutation(layout: BoardLayout, field_name: str) -> BoardLayout:
    mutations: dict[str, Any] = {
        "width_mm": 31.0,
        "height_mm": 21.0,
        "parts_row_y_mm": 11.0,
        "zones": (*layout.zones, (TARGET, "F.Cu", (4.0, 4.0, 8.0, 8.0))),
        "outline": (
            (0.0, 0.0),
            (30.0, 0.0),
            (30.0, 20.0),
            (19.0, 20.0),
            (17.0, 18.0),
            (13.0, 18.0),
            (11.0, 20.0),
            (0.0, 20.0),
        ),
        "graphics": (*layout.graphics, '  (gr_text "tamper" (at 24 34) (layer "F.SilkS"))'),
        "hide_references": ("R1", "R3"),
        "part_reference_at": (("R1", (9.0, 9.0, 9.0)), *layout.part_reference_at[1:]),
        "mask_apertures": (
            layout.mask_apertures[0].model_copy(update={"source_id": "tampered:mask"}),
        ),
        "cutouts": (BoardCutoutPolygon(((12.5, 2.5), (17.5, 2.5), (17.5, 6.5), (12.5, 6.5))),),
    }
    return replace(layout, **{field_name: mutations[field_name]})


PRESERVED_FIELDS = tuple(
    rule.field_name
    for rule in DEFAULT_SHAPED_SERIALIZATION_DELTA_POLICY.field_rules
    if rule.delta_class is LayoutFieldDeltaClass.IMMUTABLE_PRESERVED
)


@pytest.mark.parametrize("field_name", PRESERVED_FIELDS)
def test_every_reflected_preserved_field_tamper_fires(field_name: str) -> None:
    source, netlist = _sentinel()
    final = _preserved_field_mutation(source, field_name)

    with pytest.raises(ValueError, match="preserved field"):
        build_placement_serialization_authority(source, netlist, final, (TARGET,), MOVABLE)


def test_field_classification_exactly_covers_reflected_board_layout() -> None:
    assert tuple(
        rule.field_name for rule in DEFAULT_SHAPED_SERIALIZATION_DELTA_POLICY.field_rules
    ) == tuple(field.name for field in fields(BoardLayout))


@pytest.mark.parametrize(
    ("attribute", "new_value"),
    (
        ("reference", "RX"),
        ("value", "changed-value"),
        ("footprint", "Resistor_SMD:R_0805_2012Metric"),
        ("uuid_path", "sentinel/sheet/replaced-uuid"),
        ("fields", (("Tolerance", "20%"),)),
    ),
)
def test_movable_component_identity_cannot_change(attribute: str, new_value: Any) -> None:
    source, netlist = _sentinel()
    component, x_mm = source.placements[0]
    changed = replace(component, **{attribute: new_value})
    final = replace(source, placements=((changed, x_mm), *source.placements[1:]))

    with pytest.raises(ValueError, match="component|placements"):
        build_placement_serialization_authority(source, netlist, final, (TARGET,), MOVABLE)


@pytest.mark.parametrize("axis", ("x", "y", "rotation", "flip"))
def test_fixed_reference_pose_or_flip_cannot_change(axis: str) -> None:
    source, netlist = _sentinel()
    if axis == "x":
        final = replace(
            source,
            placements=tuple(
                (component, x_mm + 1.0 if component.reference == "R3" else x_mm)
                for component, x_mm in source.placements
            ),
        )
    elif axis == "y":
        final = replace(source, part_y_mm=(*source.part_y_mm[:-1], ("R3", 11.0)))
    elif axis == "rotation":
        final = replace(source, part_rotation=(*source.part_rotation[:-1], ("R3", 92.0)))
    else:
        final = replace(source, part_flip=("R2", "R3"))

    with pytest.raises(ValueError, match="fixed component|changed a fixed|fixed reference"):
        build_placement_serialization_authority(source, netlist, final, (TARGET,), MOVABLE)


@pytest.mark.parametrize(
    ("field_name", "bad_value", "message"),
    (
        ("part_y_mm", (("R1", 6.0), ("R1", 7.0)), "part_y_mm repeats reference"),
        (
            "part_rotation",
            (("R1", 17.0), ("R1", 31.0)),
            "part_rotation repeats reference",
        ),
        ("part_flip", ("R2", "R2"), "part_flip repeats reference"),
        ("part_y_mm", (("GHOST", 6.0),), "shadow reference 'GHOST'"),
        ("part_rotation", (("GHOST", 17.0),), "shadow reference 'GHOST'"),
        ("part_flip", ("GHOST",), "shadow reference 'GHOST'"),
    ),
)
@pytest.mark.parametrize("which", ("source", "final"))
def test_duplicate_and_shadow_pose_records_fail_closed_in_shaped_authority(
    field_name: str,
    bad_value: object,
    message: str,
    which: str,
) -> None:
    source, netlist = _sentinel()
    bad = replace(source, **{field_name: bad_value})

    with pytest.raises(ValueError, match=message):
        build_placement_serialization_authority(
            bad if which == "source" else source,
            netlist,
            bad if which == "final" else source,
            (TARGET,),
            MOVABLE,
        )


@pytest.mark.parametrize("kind", ("segment", "via"))
def test_non_target_track_or_via_cannot_change(kind: str) -> None:
    source, netlist = _sentinel()
    if kind == "segment":
        changed = replace(source.segments[0], width_mm=0.32)
        final = replace(source, segments=(changed, *source.segments[1:]))
    else:
        changed_via = replace(source.vias[0], back_mask=ViaMaskIntent.OPEN)
        final = replace(source, vias=(changed_via, *source.vias[1:]))

    with pytest.raises(ValueError, match="fixed/non-target copper"):
        build_placement_serialization_authority(source, netlist, final, (TARGET,), MOVABLE)


def test_snapshots_require_real_schema_and_exact_canonical_text() -> None:
    source, netlist = _sentinel()
    layout_json = canonical_board_layout_snapshot_json(source)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)

    assert parse_canonical_board_layout_snapshot(layout_json) == source
    assert parse_canonical_board_netlist_snapshot(netlist_json) == netlist
    with pytest.raises(ValueError, match="exact canonical"):
        parse_canonical_board_layout_snapshot(layout_json + " ")
    with pytest.raises(ValueError, match="real schema"):
        parse_canonical_board_layout_snapshot('{"width_mm":30}')


@pytest.mark.parametrize(
    "tamper",
    (
        "source_snapshot_noncanonical",
        "final_snapshot",
        "netlist_snapshot",
        "render_text",
        "render_hash",
        "profile",
        "profile_hash",
        "policy_hash",
        "field_evidence",
        "component_evidence",
        "input_hash",
        "result_hash",
    ),
)
def test_retained_authority_rejects_snapshot_and_evidence_tamper(tamper: str) -> None:
    authority = _build(_moved_layout())
    payload = _payload(authority)
    if tamper == "source_snapshot_noncanonical":
        payload["source_layout_snapshot_json"] += " "
    elif tamper == "final_snapshot":
        final_payload = json.loads(payload["final_layout_snapshot_json"])
        final_payload["width_mm"] = 30.5
        payload["final_layout_snapshot_json"] = json.dumps(
            final_payload, sort_keys=True, separators=(",", ":")
        )
    elif tamper == "netlist_snapshot":
        netlist_payload = json.loads(payload["source_netlist_snapshot_json"])
        netlist_payload["components"][0]["value"] = "tampered"
        payload["source_netlist_snapshot_json"] = json.dumps(
            netlist_payload, sort_keys=True, separators=(",", ":")
        )
    elif tamper == "render_text":
        payload["rendered_board_text"] += "tamper"
    elif tamper == "render_hash":
        payload["rendered_board_sha256"] = "0" * 64
    elif tamper == "profile":
        profile = dict(payload["profile"])
        profile["profile_id"] = "tampered-valid-profile-id"
        payload["profile"] = profile
    elif tamper == "profile_hash":
        payload["profile_fingerprint"] = "0" * 64
    elif tamper == "policy_hash":
        payload["policy_fingerprint"] = "0" * 64
    elif tamper == "field_evidence":
        evidence = list(payload["field_delta_evidence"])
        changed = dict(evidence[0])
        changed["changed"] = not changed["changed"]
        evidence[0] = changed
        payload["field_delta_evidence"] = tuple(evidence)
    elif tamper == "component_evidence":
        evidence = list(payload["component_identity_evidence"])
        changed = dict(evidence[0])
        changed["component_fingerprint"] = "0" * 64
        evidence[0] = changed
        payload["component_identity_evidence"] = tuple(evidence)
    elif tamper == "input_hash":
        payload["input_fingerprint"] = "0" * 64
    else:
        payload["result_fingerprint"] = "0" * 64

    with pytest.raises(ValidationError):
        PlacementSerializationAuthority.model_validate(payload)


def test_set_like_inputs_canonicalize_but_ordered_geometry_remains_sensitive() -> None:
    source, netlist = _sentinel()
    canonical = build_placement_serialization_authority(
        source, netlist, source, (TARGET,), ("R1", "R2")
    )
    reversed_sets = build_placement_serialization_authority(
        source, netlist, source, (TARGET, TARGET), ("R2", "R1", "R2")
    )
    reordered = replace(source, segments=tuple(reversed(source.segments)))
    reordered_authority = build_placement_serialization_authority(
        reordered, netlist, reordered, (TARGET,), ("R2", "R1")
    )

    assert reversed_sets == canonical
    assert reordered_authority.source_layout_fingerprint != canonical.source_layout_fingerprint
    assert reordered_authority.rendered_board_text != canonical.rendered_board_text
    assert reordered_authority.result_fingerprint != canonical.result_fingerprint
