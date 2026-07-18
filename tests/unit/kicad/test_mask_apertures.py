from __future__ import annotations

import pytest

import pcbsmith.kicad.mask_apertures as collector
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardLayout,
    BoardNetlist,
    ViaSpec,
)
from pcbsmith.kicad.board_mask import mask_opening_disc_aperture
from pcbsmith.kicad.copper_identity import (
    pad_copper_source_id,
    via_copper_source_id,
)
from pcbsmith.kicad.library import (
    CustomPadSource,
    FootprintLibraryError,
    FootprintSpec,
    PadSourceAnchor,
    PadSpec,
)
from pcbsmith.kicad.mask_apertures import collect_mask_apertures
from pcbsmith.kicad.virtual_drc import _placed
from pcbsmith.mask_geometry import (
    Capsule,
    Disc,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    OrientedRect,
    Point,
    RoundedRect,
    ViaMaskIntent,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

_FOOTPRINT = "Test:MaskApertures"


def _profile(expansion: float | None) -> PcbRuleProfile:
    return DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "geometry": DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
                update={"default_pad_solder_mask_expansion_mm": expansion}
            )
        }
    )


def _pad(
    name: str,
    shape: str,
    *,
    x: float = 0.0,
    y: float = 0.0,
    width: float = 2.0,
    height: float = 1.0,
    angle: float = 0.0,
    kind: str = "smd",
    layers: tuple[str, ...] = ("F.Cu", "F.Mask"),
    margin: float | None = None,
    ratio: float | None = None,
    roundrect_rratio: float | None = None,
    custom: bool = False,
) -> PadSpec:
    return PadSpec(
        name=name,
        x_mm=x,
        y_mm=y,
        kind=kind,
        width_mm=width,
        height_mm=height,
        angle_deg=angle,
        shape=shape,
        source_anchor=PadSourceAnchor(
            x_mm=x,
            y_mm=y,
            width_mm=width,
            height_mm=height,
        ),
        layers=layers,
        solder_mask_margin_mm=margin,
        solder_mask_margin_ratio=ratio,
        roundrect_rratio=roundrect_rratio,
        custom_source=(
            CustomPadSource(
                canonical_clauses=("(primitives)",),
                unsupported_reason="test custom source",
            )
            if custom
            else None
        ),
    )


def _spec(pads: tuple[PadSpec, ...]) -> FootprintSpec:
    return FootprintSpec(
        pads=pads,
        fab_rect=(-2.0, -2.0, 2.0, 2.0),
        silk_rect=None,
        x_min=-2.0,
        x_max=2.0,
        y_min=-2.0,
        y_max=2.0,
        attr="smd",
    )


def _component() -> BoardComponent:
    return BoardComponent(
        reference="U1",
        value="TEST",
        footprint=_FOOTPRINT,
        uuid_path="/stable/u1/",
    )


def _layout(
    *,
    vias: tuple[ViaSpec, ...] = (),
    mask_apertures: tuple = (),
    graphics: tuple[str, ...] = (),
    flipped: bool = False,
    rotation: float = 0.0,
) -> BoardLayout:
    component = _component()
    return BoardLayout(
        placements=((component, 10.0),),
        segments=(),
        vias=vias,
        width_mm=30.0,
        height_mm=20.0,
        part_y_mm=((component.reference, 12.0),),
        part_rotation=((component.reference, rotation),),
        part_flip=((component.reference,) if flipped else ()),
        mask_apertures=mask_apertures,
        graphics=graphics,
    )


def _install(monkeypatch: pytest.MonkeyPatch, pads: tuple[PadSpec, ...]) -> None:
    monkeypatch.setitem(FOOTPRINT_LIBRARY, _FOOTPRINT, _spec(pads))

    def no_source(_library_id: str) -> None:
        raise FootprintLibraryError("synthetic footprint has no source tree")

    monkeypatch.setattr(collector, "load_footprint", no_source)


def _collect(
    monkeypatch: pytest.MonkeyPatch,
    pads: tuple[PadSpec, ...],
    *,
    profile: PcbRuleProfile | None = None,
    layout: BoardLayout | None = None,
):
    _install(monkeypatch, pads)
    return collect_mask_apertures(
        layout or _layout(),
        BoardNetlist(components=(_component(),), nets=()),
        profile or _profile(0.0),
    )


def test_mask_layer_membership_and_flip_are_physical(monkeypatch: pytest.MonkeyPatch) -> None:
    pads = (
        _pad("front", "circle", width=1.0, height=1.0),
        _pad("back", "circle", width=1.0, height=1.0, layers=("B.Cu", "B.Mask")),
        _pad("both", "circle", width=1.0, height=1.0, layers=("*.Cu", "*.Mask")),
        _pad("none", "circle", width=1.0, height=1.0, layers=("F.Cu",)),
    )
    front = _collect(monkeypatch, pads)
    flipped = _collect(monkeypatch, pads, layout=_layout(flipped=True))

    assert [item.side for item in front] == [
        MaskSide.FRONT,
        MaskSide.BACK,
        MaskSide.FRONT,
        MaskSide.BACK,
    ]
    assert [item.side for item in flipped] == [
        MaskSide.BACK,
        MaskSide.FRONT,
        MaskSide.FRONT,
        MaskSide.BACK,
    ]
    assert [item.copper_source_ids for item in front] == [
        (pad_copper_source_id("U1", 0, "F.Cu"),),
        (pad_copper_source_id("U1", 1, "B.Cu"),),
        (pad_copper_source_id("U1", 2, "F.Cu"),),
        (pad_copper_source_id("U1", 2, "B.Cu"),),
    ]
    assert [item.copper_source_ids for item in flipped] == [
        (pad_copper_source_id("U1", 0, "B.Cu"),),
        (pad_copper_source_id("U1", 1, "F.Cu"),),
        (pad_copper_source_id("U1", 2, "F.Cu"),),
        (pad_copper_source_id("U1", 2, "B.Cu"),),
    ]


def test_npth_mask_apertures_do_not_invent_copper_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = _collect(
        monkeypatch,
        (
            _pad(
                "",
                "circle",
                kind="npth",
                width=1.0,
                height=1.0,
                layers=("*.Mask",),
            ),
        ),
    )

    assert [item.side for item in items] == [
        MaskSide.FRONT,
        MaskSide.BACK,
    ]
    assert all(item.copper_source_ids == () for item in items)


def test_local_nonzero_overrides_global_but_local_zero_inherits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = _collect(
        monkeypatch,
        (
            _pad("override", "circle", width=1.0, height=1.0, margin=0.2),
            _pad("inherit", "circle", width=1.0, height=1.0, margin=0.0),
        ),
        profile=_profile(0.1),
    )

    assert [item.geometry for item in items] == [
        Disc(center=Point(x_mm=10.0, y_mm=12.0), radius_mm=0.7),
        Disc(center=Point(x_mm=10.0, y_mm=12.0), radius_mm=0.6),
    ]


def test_exact_supported_shape_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    items = _collect(
        monkeypatch,
        (
            _pad("circle", "circle", x=-4.0, width=1.0, height=1.0),
            _pad("oval", "oval", x=-2.0, width=2.0, height=1.0),
            _pad("equal", "oval", width=1.0, height=1.0),
            _pad("rect0", "rect", x=2.0),
            _pad("rectp", "rect", x=4.0, margin=0.1),
            _pad("rectn", "rect", x=6.0, margin=-0.1),
            _pad("round", "roundrect", x=8.0, roundrect_rratio=0.2),
        ),
    )

    assert isinstance(items[0].geometry, Disc)
    assert isinstance(items[1].geometry, Capsule)
    assert isinstance(items[2].geometry, Disc)
    assert isinstance(items[3].geometry, OrientedRect)
    assert items[3].geometry.width_mm == pytest.approx(2.0)
    assert isinstance(items[4].geometry, RoundedRect)
    assert items[4].geometry.corner_radius_mm == pytest.approx(0.1)
    assert isinstance(items[5].geometry, OrientedRect)
    assert items[5].geometry.width_mm == pytest.approx(1.8)
    assert isinstance(items[6].geometry, RoundedRect)
    assert items[6].geometry.corner_radius_mm == pytest.approx(0.2)


def test_collapsed_negative_and_unimplemented_sources_are_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = _collect(
        monkeypatch,
        (
            _pad("collapse", "rect", width=0.2, height=0.2, margin=-0.1),
            _pad(
                "negative-radius",
                "roundrect",
                width=2.0,
                height=1.0,
                margin=-0.3,
                roundrect_rratio=0.2,
            ),
            _pad("ratio", "circle", width=1.0, height=1.0, ratio=0.1),
            _pad("custom", "custom", custom=True),
        ),
    )

    assert all(item.verification is MaskVerification.UNSUPPORTED for item in items)
    assert [item.copper_source_ids for item in items] == [
        (pad_copper_source_id("U1", index, "F.Cu"),) for index in range(4)
    ]
    reasons = " ".join(item.unsupported_reason or "" for item in items)
    assert "collapses" in reasons
    assert "corner radius negative" in reasons
    assert "margin_ratio" in reasons
    assert "custom" in reasons


def test_duplicate_and_unnamed_pad_ids_are_stable_and_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pads = (
        _pad("1", "circle", width=1.0, height=1.0),
        _pad("1", "circle", x=1.0, width=1.0, height=1.0),
        _pad("", "circle", x=2.0, width=1.0, height=1.0),
        _pad("", "circle", x=3.0, width=1.0, height=1.0),
    )
    first = _collect(monkeypatch, pads)
    second = _collect(monkeypatch, pads)

    assert len({item.source_id for item in first}) == 4
    assert [item.source_id for item in first] == [item.source_id for item in second]

    assert [item.copper_source_ids for item in first] == [
        (pad_copper_source_id("U1", index, "F.Cu"),) for index in range(4)
    ]


@pytest.mark.parametrize("flipped", [False, True])
def test_arbitrary_angle_placement_matches_kicad_transform(
    monkeypatch: pytest.MonkeyPatch, flipped: bool
) -> None:
    pad = _pad(
        "1",
        "rect",
        x=2.3,
        y=-1.7,
        width=2.0,
        height=0.8,
        angle=23.0,
        layers=("F.Cu", "F.Mask"),
    )
    item = _collect(
        monkeypatch,
        (pad,),
        layout=_layout(flipped=flipped, rotation=37.0),
    )[0]
    assert isinstance(item.geometry, OrientedRect)
    expected = _placed((10.0, 12.0), 37.0, (2.3, -1.7), flipped)
    assert item.geometry.center.x_mm == pytest.approx(expected[0])
    assert item.geometry.center.y_mm == pytest.approx(expected[1])
    assert item.side is (MaskSide.BACK if flipped else MaskSide.FRONT)

    expected_angle = ((180.0 + 23.0) if flipped else -23.0) - 37.0
    assert item.geometry.angle_deg == pytest.approx(expected_angle % 360.0)


def test_missing_global_expansion_is_never_assumed_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _collect(
        monkeypatch,
        (_pad("1", "circle", width=1.0, height=1.0),),
        profile=_profile(None),
    )[0]
    assert item.verification is MaskVerification.UNSUPPORTED
    assert "not declared" in (item.unsupported_reason or "")


def test_via_open_tented_and_inherit_intents(monkeypatch: pytest.MonkeyPatch) -> None:
    layout = _layout(
        vias=(
            ViaSpec(
                x=3.0,
                y=4.0,
                net_name="N",
                size_mm=0.6,
                front_mask=ViaMaskIntent.OPEN,
                back_mask=ViaMaskIntent.TENTED,
            ),
            ViaSpec(
                x=6.0,
                y=7.0,
                net_name="N",
                front_mask=ViaMaskIntent.INHERIT,
                back_mask=ViaMaskIntent.OPEN,
            ),
        )
    )
    items = _collect(monkeypatch, (), layout=layout, profile=_profile(0.05))
    vias = [item for item in items if item.source_kind is MaskSourceKind.VIA]

    assert [(item.side, item.verification) for item in vias] == [
        (MaskSide.FRONT, MaskVerification.EXACT),
        (MaskSide.FRONT, MaskVerification.UNSUPPORTED),
        (MaskSide.BACK, MaskVerification.EXACT),
    ]
    assert isinstance(vias[0].geometry, Disc)
    assert vias[0].geometry.radius_mm == pytest.approx(0.35)

    assert [item.copper_source_ids for item in vias] == [
        (via_copper_source_id(0, "F.Cu"),),
        (via_copper_source_id(1, "F.Cu"),),
        (via_copper_source_id(1, "B.Cu"),),
    ]


def test_typed_board_aperture_passes_through_and_raw_mask_is_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = mask_opening_disc_aperture((4.0, 5.0), 2.0)
    layout = _layout(
        mask_apertures=(typed,),
        graphics=(
            '(gr_circle (layer "F.Mask"))',
            '(gr_rect (layer "B.Mask"))',
            '(gr_text "F.Mask is only text" (layer "F.SilkS"))',
        ),
    )
    items = _collect(monkeypatch, (), layout=layout)

    assert typed.copper_source_ids == ()
    assert items[0] is typed
    raw = items[1:]
    assert [item.side for item in raw] == [MaskSide.FRONT, MaskSide.BACK]
    assert all(item.verification is MaskVerification.UNSUPPORTED for item in raw)

    assert all(item.copper_source_ids == () for item in raw)


def test_duplicate_typed_source_id_with_unequal_content_becomes_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = mask_opening_disc_aperture((4.0, 5.0), 2.0)
    second = first.model_copy(
        update={"geometry": Disc(center=Point(x_mm=6.0, y_mm=5.0), radius_mm=2.0)}
    )
    items = _collect(
        monkeypatch,
        (),
        layout=_layout(mask_apertures=(first, second)),
    )

    assert len(items) == 2
    assert len({item.source_id for item in items}) == 2
    assert all(item.verification is MaskVerification.UNSUPPORTED for item in items)
    assert all("duplicated" in (item.unsupported_reason or "") for item in items)
