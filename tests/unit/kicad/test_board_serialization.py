from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import fields, replace
from typing import Any

import pytest

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
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
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
    board_layout_snapshot_fingerprint as placement_layout_fingerprint,
)
from pcbsmith.placement_serialization_ir import (
    board_netlist_snapshot_fingerprint as placement_netlist_fingerprint,
)

TARGET = "/TARGET"
FIXED = "/FIXED"
RESISTOR = "Resistor_SMD:R_0603_1608Metric"


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


def _rich_board() -> tuple[BoardLayout, BoardNetlist]:
    r1 = _component("R1")
    r2 = _component("R2")
    r3 = _component("R3")
    layout = BoardLayout(
        placements=((r1, 6.25), (r2, 22.5), (r3, 13.0)),
        segments=(
            TrackSegment(1.0, 1.0, 5.0, 1.0, "F.Cu", FIXED, 0.31),
            TrackSegment(3.0, 18.0, 8.0, 18.0, "B.Cu", FIXED, 0.37),
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
            '  (gr_text "serializer sentinel" (at 27 36 11) (layer "F.SilkS"))',
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
            _aperture("sentinel:back", MaskSide.BACK, 26.0),
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


def _canonical(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _v1_fingerprint(schema_id: str, field_name: str, snapshot: str) -> str:
    payload = {
        "schema_id": schema_id,
        "schema_version": 1,
        field_name: json.loads(snapshot),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def test_rich_snapshots_roundtrip_exact_real_dataclasses_and_all_fields() -> None:
    layout, netlist = _rich_board()

    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)

    assert parse_canonical_board_layout_snapshot(layout_json) == layout
    assert parse_canonical_board_netlist_snapshot(netlist_json) == netlist
    assert canonical_board_layout_snapshot_json(layout) == layout_json
    assert canonical_board_netlist_snapshot_json(netlist) == netlist_json
    assert set(json.loads(layout_json)) == {field.name for field in fields(BoardLayout)}
    assert set(json.loads(netlist_json)) == {field.name for field in fields(BoardNetlist)}
    assert "sentinel/sheet/r1" in layout_json
    assert '"front_mask":"open"' in layout_json
    assert '"back_mask":"open"' in layout_json
    assert '"side":"front"' in layout_json
    assert '"side":"back"' in layout_json


def test_v1_fingerprints_match_established_placement_payload_identities() -> None:
    layout, netlist = _rich_board()
    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)

    layout_fingerprint = board_layout_snapshot_fingerprint(layout_json)
    netlist_fingerprint = board_netlist_snapshot_fingerprint(netlist_json)

    assert layout_fingerprint == placement_layout_fingerprint(layout_json)
    assert netlist_fingerprint == placement_netlist_fingerprint(netlist_json)
    assert layout_fingerprint == _v1_fingerprint(
        "pcbsmith-board-layout-schema-snapshot", "layout", layout_json
    )
    assert netlist_fingerprint == _v1_fingerprint(
        "pcbsmith-board-netlist-schema-snapshot", "netlist", netlist_json
    )
    assert len(layout_fingerprint) == len(netlist_fingerprint) == 64


def test_ordered_schema_fields_retain_order_and_affect_fingerprints() -> None:
    layout, netlist = _rich_board()
    reversed_layout = replace(
        layout,
        placements=tuple(reversed(layout.placements)),
        segments=tuple(reversed(layout.segments)),
        vias=tuple(reversed(layout.vias)),
        graphics=tuple(reversed(layout.graphics)),
        mask_apertures=tuple(reversed(layout.mask_apertures)),
    )
    reversed_netlist = replace(
        netlist,
        components=tuple(reversed(netlist.components)),
        nets=tuple(
            replace(net, nodes=tuple(reversed(net.nodes))) for net in reversed(netlist.nets)
        ),
    )

    reversed_layout_json = canonical_board_layout_snapshot_json(reversed_layout)
    reversed_netlist_json = canonical_board_netlist_snapshot_json(reversed_netlist)

    assert parse_canonical_board_layout_snapshot(reversed_layout_json) == reversed_layout
    assert parse_canonical_board_netlist_snapshot(reversed_netlist_json) == reversed_netlist
    assert board_layout_snapshot_fingerprint(reversed_layout_json) != (
        board_layout_snapshot_fingerprint(canonical_board_layout_snapshot_json(layout))
    )
    assert board_netlist_snapshot_fingerprint(reversed_netlist_json) != (
        board_netlist_snapshot_fingerprint(canonical_board_netlist_snapshot_json(netlist))
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda snapshot: snapshot + "\n",
        lambda snapshot: json.dumps(json.loads(snapshot), indent=2, ensure_ascii=False),
        lambda snapshot: "{" + snapshot[1:].replace(",", ", ", 1),
    ),
)
@pytest.mark.parametrize(
    ("snapshot", "parse"),
    (
        pytest.param(
            "layout",
            parse_canonical_board_layout_snapshot,
            id="layout",
        ),
        pytest.param(
            "netlist",
            parse_canonical_board_netlist_snapshot,
            id="netlist",
        ),
    ),
)
def test_noncanonical_json_is_rejected(
    snapshot: str,
    parse: Callable[[str], object],
    mutate: Callable[[str], str],
) -> None:
    layout, netlist = _rich_board()
    canonical = (
        canonical_board_layout_snapshot_json(layout)
        if snapshot == "layout"
        else canonical_board_netlist_snapshot_json(netlist)
    )

    with pytest.raises(ValueError, match="must equal exact canonical"):
        parse(mutate(canonical))


@pytest.mark.parametrize("problem", ("extra", "missing", "wrong_type"))
@pytest.mark.parametrize("schema", ("layout", "netlist"))
def test_schema_extra_missing_and_wrong_types_are_rejected(schema: str, problem: str) -> None:
    layout, netlist = _rich_board()
    if schema == "layout":
        parse = parse_canonical_board_layout_snapshot
        payload = json.loads(canonical_board_layout_snapshot_json(layout))
        if problem == "extra":
            payload["future_unclassified_field"] = "must not disappear"
        elif problem == "missing":
            del payload["width_mm"]
        else:
            payload["placements"] = {"R1": 6.25}
    else:
        parse = parse_canonical_board_netlist_snapshot
        payload = json.loads(canonical_board_netlist_snapshot_json(netlist))
        if problem == "extra":
            payload["future_unclassified_field"] = "must not disappear"
        elif problem == "missing":
            del payload["components"]
        else:
            payload["nets"] = "not-an-ordered-net-sequence"

    with pytest.raises(ValueError):
        parse(_canonical(payload))


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity"))
def test_nonfinite_json_numbers_are_rejected(constant: str) -> None:
    layout, _netlist = _rich_board()
    snapshot = canonical_board_layout_snapshot_json(layout)
    nonfinite = snapshot.replace('"width_mm":30.0', f'"width_mm":{constant}')
    assert nonfinite != snapshot

    with pytest.raises(ValueError, match="non-finite"):
        parse_canonical_board_layout_snapshot(nonfinite)


def test_nonfinite_real_dataclass_cannot_be_canonically_serialized() -> None:
    layout, _netlist = _rich_board()

    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_board_layout_snapshot_json(replace(layout, width_mm=float("nan")))
