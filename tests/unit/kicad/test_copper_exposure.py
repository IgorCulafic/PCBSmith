from __future__ import annotations

import pytest

import pcbsmith.kicad.copper_exposure as collector
from pcbsmith.copper_exposure import (
    CopperExposureResult,
    CopperGeometryVerification,
)
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.board_mask import mask_opening_disc_aperture
from pcbsmith.kicad.copper_exposure import collect_outer_copper_regions, exposure_index
from pcbsmith.kicad.copper_identity import (
    pad_copper_source_id,
    track_copper_source_id,
    via_copper_source_id,
)
from pcbsmith.kicad.library import (
    CustomPadSource,
    FootprintSpec,
    PadSourceAnchor,
    PadSpec,
)
from pcbsmith.mask_geometry import (
    Capsule,
    Disc,
    MaskSide,
    OrientedRect,
    ViaMaskIntent,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

_FOOTPRINT = "Test:CopperExposure"


def _pad(
    name: str,
    shape: str = "circle",
    *,
    x: float = 0.0,
    y: float = 0.0,
    width: float = 2.0,
    height: float = 2.0,
    kind: str = "smd",
    layers: tuple[str, ...] = ("F.Cu", "F.Mask"),
    margin: float | None = None,
    source: bool = True,
    custom: bool = False,
) -> PadSpec:
    return PadSpec(
        name=name,
        x_mm=x,
        y_mm=y,
        kind=kind,
        width_mm=width,
        height_mm=height,
        shape=shape,
        source_anchor=(
            PadSourceAnchor(x_mm=x, y_mm=y, width_mm=width, height_mm=height) if source else None
        ),
        layers=layers,
        solder_mask_margin_mm=margin,
        custom_source=(
            CustomPadSource(
                canonical_clauses=("(primitives)",),
                unsupported_reason="synthetic custom pad",
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


def _install(monkeypatch: pytest.MonkeyPatch, pads: tuple[PadSpec, ...]) -> None:
    monkeypatch.setitem(FOOTPRINT_LIBRARY, _FOOTPRINT, _spec(pads))


def _layout(
    *,
    placements: bool = True,
    segments: tuple[TrackSegment, ...] = (),
    vias: tuple[ViaSpec, ...] = (),
    zones: tuple[tuple[str, str, tuple[float, float, float, float]], ...] = (),
    flipped: bool = False,
    mask_apertures: tuple = (),
) -> BoardLayout:
    component = _component()
    return BoardLayout(
        placements=(((component, 10.0),) if placements else ()),
        segments=segments,
        vias=vias,
        width_mm=30.0,
        height_mm=20.0,
        part_y_mm=(((component.reference, 12.0),) if placements else ()),
        part_flip=(((component.reference),) if flipped else ()),
        zones=zones,
        mask_apertures=mask_apertures,
    )


def _netlist(*nodes: tuple[str, str], components: bool = True) -> BoardNetlist:
    return BoardNetlist(
        components=((_component(),) if components else ()),
        nets=((BoardNet(name="N", nodes=nodes),) if nodes else ()),
    )


def _profile(expansion: float = 0.0) -> PcbRuleProfile:
    return DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "geometry": DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
                update={"default_pad_solder_mask_expansion_mm": expansion}
            )
        }
    )


def test_collects_exact_pad_tracks_and_via_lands(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, (_pad("1"),))
    layout = _layout(
        segments=(
            TrackSegment(1.0, 2.0, 4.0, 2.0, "F.Cu", "N", 0.4),
            TrackSegment(6.0, 7.0, 6.0, 7.0, "B.Cu", "N", 0.6),
            TrackSegment(0.0, 0.0, 1.0, 1.0, "In1.Cu", "N", 0.2),
        ),
        vias=(ViaSpec(x=8.0, y=9.0, net_name="N", size_mm=0.8),),
    )
    regions = {
        item.source_id: item for item in collect_outer_copper_regions(layout, _netlist(("U1", "1")))
    }

    pad = regions[pad_copper_source_id("U1", 0, "F.Cu")]
    assert isinstance(pad.geometry, Disc)
    assert pad.geometry.center.x_mm == pytest.approx(10.0)
    assert pad.geometry.center.y_mm == pytest.approx(12.0)
    assert pad.net_name == "N"
    assert pad.role == "component_termination"

    assert isinstance(regions[track_copper_source_id(0)].geometry, Capsule)
    assert isinstance(regions[track_copper_source_id(1)].geometry, Disc)
    assert track_copper_source_id(2) not in regions
    assert regions[track_copper_source_id(0)].role == "routed_conductor"

    front_via = regions[via_copper_source_id(0, "F.Cu")]
    back_via = regions[via_copper_source_id(0, "B.Cu")]
    assert front_via.side is MaskSide.FRONT
    assert back_via.side is MaskSide.BACK
    assert isinstance(front_via.geometry, Disc)
    assert front_via.geometry.radius_mm == pytest.approx(0.4)
    assert front_via.role == "via_land"


def test_pad_flip_side_net_binding_no_net_and_npth_omission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pads = (
        _pad("1"),
        _pad("", x=0.2, width=0.4, height=0.4),
        _pad("2", x=3.0),
        _pad("", x=6.0, width=0.3, height=0.3),
        _pad("M", kind="npth", layers=("*.Cu", "*.Mask")),
    )
    _install(monkeypatch, pads)
    regions = collect_outer_copper_regions(
        _layout(flipped=True),
        _netlist(("U1", "1")),
    )
    by_id = {item.source_id: item for item in regions}

    assert all(item.side is MaskSide.BACK for item in regions)
    assert by_id[pad_copper_source_id("U1", 0, "B.Cu")].net_name == "N"
    assert by_id[pad_copper_source_id("U1", 1, "B.Cu")].net_name == "N"
    assert by_id[pad_copper_source_id("U1", 2, "B.Cu")].net_name == "<no-net>"
    # KiCad binds by pad name, so once one unnamed overlapping pad inherits N,
    # every other unnamed pad receives that same rendered binding.
    assert by_id[pad_copper_source_id("U1", 3, "B.Cu")].net_name == "N"
    assert not any(item.source_id.startswith("pad:U1:4:") for item in regions)


def test_pad_transform_matches_mask_transform(monkeypatch: pytest.MonkeyPatch) -> None:
    pad = _pad("1", "rect", x=2.0, y=-1.0, width=2.0, height=1.0)
    _install(monkeypatch, (pad,))
    component = _component()
    layout = BoardLayout(
        placements=((component, 10.0),),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=20.0,
        part_y_mm=((component.reference, 12.0),),
        part_rotation=((component.reference, 90.0),),
    )
    region = collect_outer_copper_regions(layout, _netlist(("U1", "1")))[0]
    assert isinstance(region.geometry, OrientedRect)
    assert region.geometry.center.x_mm == pytest.approx(9.0)
    assert region.geometry.center.y_mm == pytest.approx(10.0)
    assert region.geometry.angle_deg == pytest.approx(270.0)


def test_custom_unpreserved_and_unknown_layer_pads_are_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pads = (
        _pad("1", "custom", custom=True),
        _pad("2", source=False),
        _pad("3", layers=()),
    )
    _install(monkeypatch, pads)
    regions = collect_outer_copper_regions(_layout(), _netlist())

    assert len(regions) == 4
    assert all(item.verification is CopperGeometryVerification.UNSUPPORTED for item in regions)
    reasons = " ".join(item.unsupported_reason or "" for item in regions)
    assert "custom" in reasons
    assert "not preserved" in reasons
    assert "layers are unknown" in reasons


def test_outer_zones_are_unique_unsupported_pour_intent() -> None:
    layout = _layout(
        placements=False,
        zones=(
            ("N", "F.Cu", (1.0, 1.0, 5.0, 5.0)),
            ("N", "F.Cu", (1.0, 1.0, 5.0, 5.0)),
            ("N", "In1.Cu", (1.0, 1.0, 5.0, 5.0)),
        ),
    )
    first = collect_outer_copper_regions(layout, _netlist(components=False))
    second = collect_outer_copper_regions(layout, _netlist(components=False))

    assert first == second
    assert [item.source_id for item in first] == [
        "zone:0:copper:F.Cu",
        "zone:1:copper:F.Cu",
    ]
    assert all(item.role == "copper_pour" for item in first)
    assert all(item.verification is CopperGeometryVerification.UNSUPPORTED for item in first)
    assert all(item.geometry is None for item in first)


def test_via_open_tented_and_inherit_are_classified_per_side() -> None:
    layout = _layout(
        placements=False,
        vias=(
            ViaSpec(
                x=2.0,
                y=2.0,
                net_name="N",
                size_mm=0.8,
                front_mask=ViaMaskIntent.OPEN,
                back_mask=ViaMaskIntent.TENTED,
            ),
            ViaSpec(
                x=8.0,
                y=8.0,
                net_name="N",
                size_mm=0.8,
                front_mask=ViaMaskIntent.INHERIT,
                back_mask=ViaMaskIntent.OPEN,
            ),
        ),
    )
    indexed = exposure_index(layout, _netlist(components=False), _profile())

    assert indexed[via_copper_source_id(0, "F.Cu")].state == "fully_exposed"
    assert indexed[via_copper_source_id(0, "B.Cu")].state == "masked"
    inherited = indexed[via_copper_source_id(1, "F.Cu")]
    assert inherited.state == "unknown"
    assert inherited.unresolved_aperture_source_ids
    assert indexed[via_copper_source_id(1, "B.Cu")].state == "fully_exposed"


def test_negative_pad_margin_is_partial_and_front_opening_does_not_reach_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pad = _pad("1", layers=("*.Cu", "*.Mask"), margin=-0.2)
    _install(monkeypatch, (pad,))
    layout = _layout(
        segments=(TrackSegment(0.0, 0.0, 0.0, 0.0, "B.Cu", "N", 0.4),),
        mask_apertures=(mask_opening_disc_aperture((0.0, 0.0), 1.0),),
    )
    indexed = exposure_index(layout, _netlist(("U1", "1")), _profile())

    assert indexed[pad_copper_source_id("U1", 0, "F.Cu")].state == "partially_exposed"
    assert indexed[pad_copper_source_id("U1", 0, "B.Cu")].state == "partially_exposed"
    assert indexed[track_copper_source_id(0)].state == "masked"


def test_exposure_index_collects_apertures_once_and_rejects_duplicate_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(placements=False)
    netlist = _netlist(components=False)
    calls = 0
    real_collect = collector.collect_mask_apertures

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_collect(*args, **kwargs)

    monkeypatch.setattr(collector, "collect_mask_apertures", counted)
    assert exposure_index(layout, netlist, _profile()) == {}
    assert calls == 1

    duplicate = CopperExposureResult(
        copper_source_id="duplicate",
        side=MaskSide.FRONT,
        state="masked",
        role="routed_conductor",
        reason="synthetic duplicate fixture",
    )
    monkeypatch.setattr(
        collector,
        "classify_outer_copper_exposure",
        lambda _copper, _apertures: (duplicate, duplicate),
    )
    with pytest.raises(ValueError, match="duplicate copper exposure result key"):
        exposure_index(layout, netlist, _profile())
