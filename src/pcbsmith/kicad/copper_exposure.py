"""Collect exact outer copper for solder-mask exposure classification."""

from __future__ import annotations

import math

from pcbsmith.copper_exposure import (
    CopperExposureResult,
    CopperGeometryVerification,
    OuterCopperRegion,
    classify_outer_copper_exposure,
)
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
)
from pcbsmith.kicad.copper_identity import (
    pad_copper_source_id,
    track_copper_source_id,
    via_copper_source_id,
)
from pcbsmith.kicad.library import FootprintSpec, PadSpec
from pcbsmith.kicad.mask_apertures import collect_mask_apertures, pad_local_geometry
from pcbsmith.mask_geometry import (
    Capsule,
    Disc,
    GeometryTransform,
    MaskGeometry,
    MaskSide,
    Point,
    transform_geometry,
)
from pcbsmith.rule_profiles import PcbRuleProfile

_NO_NET = "<no-net>"
_OUTER_LAYER_TO_SIDE = {"F.Cu": MaskSide.FRONT, "B.Cu": MaskSide.BACK}


def collect_outer_copper_regions(
    layout: BoardLayout,
    netlist: BoardNetlist,
) -> tuple[OuterCopperRegion, ...]:
    """Collect exact or explicitly unsupported copper on the two outer layers."""
    regions: list[OuterCopperRegion] = []
    pad_nets = _named_pad_nets(netlist)
    for component, anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        bindings = _component_pad_nets(component, spec, pad_nets)
        regions.extend(_component_pad_regions(layout, component, anchor_x, spec, bindings))
    regions.extend(_track_regions(layout))
    regions.extend(_via_regions(layout))
    regions.extend(_zone_regions(layout))
    return tuple(regions)


def exposure_index(
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
) -> dict[str, CopperExposureResult]:
    """Collect each physical model once and index deterministic exposure results."""
    apertures = collect_mask_apertures(layout, netlist, profile)
    copper = collect_outer_copper_regions(layout, netlist)
    results = classify_outer_copper_exposure(copper, apertures)
    indexed: dict[str, CopperExposureResult] = {}
    for result in results:
        if result.copper_source_id in indexed:
            raise ValueError(f"duplicate copper exposure result key: {result.copper_source_id}")
        indexed[result.copper_source_id] = result
    return indexed


def _named_pad_nets(netlist: BoardNetlist) -> dict[tuple[str, str], str]:
    return {(reference, pin): net.name for net in netlist.nets for reference, pin in net.nodes}


def _component_pad_nets(
    component: BoardComponent,
    spec: FootprintSpec,
    pad_nets: dict[tuple[str, str], str],
) -> dict[str, str]:
    bindings = {
        pad.name: net_name
        for pad in spec.pads
        if (net_name := pad_nets.get((component.reference, pad.name))) is not None
    }
    if "" in bindings:
        return bindings
    for unnamed in (pad for pad in spec.pads if not pad.name):
        for named in spec.pads:
            if not named.name or named.name not in bindings:
                continue
            if (
                abs(unnamed.x_mm - named.x_mm) * 2 < unnamed.width_mm + named.width_mm
                and abs(unnamed.y_mm - named.y_mm) * 2 < unnamed.height_mm + named.height_mm
            ):
                bindings[""] = bindings[named.name]
                return bindings
    return bindings


def _component_pad_regions(
    layout: BoardLayout,
    component: BoardComponent,
    anchor_x: float,
    spec: FootprintSpec,
    bindings: dict[str, str],
) -> list[OuterCopperRegion]:
    flipped = component.reference in layout.part_flip
    transform = GeometryTransform(
        translate_x_mm=anchor_x,
        translate_y_mm=placement_y(layout, component.reference),
        rotation_deg=-placement_rotation(layout, component.reference),
        mirror_x=flipped,
    )
    regions: list[OuterCopperRegion] = []
    for pad_index, pad in enumerate(spec.pads):
        if pad.kind == "npth":
            continue
        sides, layer_reason = _pad_copper_sides(pad, flipped)
        if not sides:
            continue
        geometry, geometry_reason = _exact_pad_geometry(pad)
        reason = layer_reason or geometry_reason
        for side in sides:
            layer = _copper_layer(side)
            common = {
                "source_id": pad_copper_source_id(component.reference, pad_index, layer),
                "parent_source_id": f"pad:{component.reference}:{pad_index}",
                "side": side,
                "net_name": bindings.get(pad.name, _NO_NET),
                "owner_ref": component.reference,
                "role": "component_termination",
            }
            if reason is not None or geometry is None:
                regions.append(
                    OuterCopperRegion(
                        **common,
                        verification=CopperGeometryVerification.UNSUPPORTED,
                        unsupported_reason=reason or "pad copper geometry is unsupported",
                    )
                )
            else:
                regions.append(
                    OuterCopperRegion(
                        **common,
                        geometry=transform_geometry(geometry, transform),
                        verification=CopperGeometryVerification.EXACT,
                    )
                )
    return regions


def _pad_copper_sides(
    pad: PadSpec,
    flipped: bool,
) -> tuple[tuple[MaskSide, ...], str | None]:
    if not pad.layers:
        return (
            (MaskSide.FRONT, MaskSide.BACK),
            "pad source layers are unknown; outer-copper membership is unresolved",
        )
    source_sides: set[MaskSide] = set()
    if "*.Cu" in pad.layers:
        source_sides.update((MaskSide.FRONT, MaskSide.BACK))
    if "F.Cu" in pad.layers:
        source_sides.add(MaskSide.FRONT)
    if "B.Cu" in pad.layers:
        source_sides.add(MaskSide.BACK)
    physical = {_flip_side(side) if flipped else side for side in source_sides}
    return tuple(side for side in MaskSide if side in physical), None


def _exact_pad_geometry(pad: PadSpec) -> tuple[MaskGeometry | None, str | None]:
    anchor = pad.source_anchor
    if anchor is None:
        return None, "pad source anchor was not preserved"
    if not all(
        math.isfinite(value)
        for value in (
            anchor.x_mm,
            anchor.y_mm,
            anchor.width_mm,
            anchor.height_mm,
            pad.angle_deg,
        )
    ):
        return None, "pad source anchor contains non-finite geometry"
    if pad.chamfer_ratio is not None or pad.chamfer_positions:
        return None, "chamfered pad copper geometry is not implemented exactly"
    if pad.shape == "custom" or pad.custom_source is not None:
        return None, "custom pad source is preserved but exact copper is unsupported"
    if pad.shape not in {"circle", "oval", "rect", "roundrect"}:
        return None, f"pad shape {pad.shape or '<unknown>'!r} has no exact copper model"
    return pad_local_geometry(pad, 0.0)


def _track_regions(layout: BoardLayout) -> list[OuterCopperRegion]:
    result: list[OuterCopperRegion] = []
    for segment_index, segment in enumerate(layout.segments):
        side = _OUTER_LAYER_TO_SIDE.get(segment.layer)
        if side is None:
            continue
        common = {
            "source_id": track_copper_source_id(segment_index),
            "side": side,
            "net_name": segment.net_name or _NO_NET,
            "role": "routed_conductor",
        }
        values = (segment.x1, segment.y1, segment.x2, segment.y2, segment.width_mm)
        if not all(math.isfinite(value) for value in values) or segment.width_mm <= 0.0:
            result.append(
                OuterCopperRegion(
                    **common,
                    verification=CopperGeometryVerification.UNSUPPORTED,
                    unsupported_reason="track coordinates and width must be finite and positive",
                )
            )
            continue
        center_a = Point(x_mm=segment.x1, y_mm=segment.y1)
        geometry: MaskGeometry
        if segment.x1 == segment.x2 and segment.y1 == segment.y2:
            geometry = Disc(center=center_a, radius_mm=segment.width_mm / 2.0)
        else:
            geometry = Capsule(
                a=center_a,
                b=Point(x_mm=segment.x2, y_mm=segment.y2),
                radius_mm=segment.width_mm / 2.0,
            )
        result.append(
            OuterCopperRegion(
                **common,
                geometry=geometry,
                verification=CopperGeometryVerification.EXACT,
            )
        )
    return result


def _via_regions(layout: BoardLayout) -> list[OuterCopperRegion]:
    result: list[OuterCopperRegion] = []
    for via_index, via in enumerate(layout.vias):
        valid = all(math.isfinite(value) for value in (via.x, via.y, via.size_mm))
        for side in MaskSide:
            layer = _copper_layer(side)
            common = {
                "source_id": via_copper_source_id(via_index, layer),
                "parent_source_id": f"via:{via_index}",
                "side": side,
                "net_name": via.net_name or _NO_NET,
                "role": "via_land",
            }
            if not valid or via.size_mm <= 0.0:
                result.append(
                    OuterCopperRegion(
                        **common,
                        verification=CopperGeometryVerification.UNSUPPORTED,
                        unsupported_reason="via position and size must be finite and positive",
                    )
                )
            else:
                result.append(
                    OuterCopperRegion(
                        **common,
                        geometry=Disc(
                            center=Point(x_mm=via.x, y_mm=via.y),
                            radius_mm=via.size_mm / 2.0,
                        ),
                        verification=CopperGeometryVerification.EXACT,
                    )
                )
    return result


def _zone_regions(layout: BoardLayout) -> list[OuterCopperRegion]:
    result: list[OuterCopperRegion] = []
    for zone_index, (net_name, layer, _rect) in enumerate(layout.zones):
        side = _OUTER_LAYER_TO_SIDE.get(layer)
        if side is None:
            continue
        result.append(
            OuterCopperRegion(
                source_id=f"zone:{zone_index}:copper:{layer}",
                parent_source_id=f"zone:{zone_index}",
                side=side,
                net_name=net_name or _NO_NET,
                role="copper_pour",
                verification=CopperGeometryVerification.UNSUPPORTED,
                unsupported_reason=(
                    "zone rectangle is unflooded intent, not KiCad's clipped final copper fill"
                ),
            )
        )
    return result


def _copper_layer(side: MaskSide) -> str:
    return "F.Cu" if side is MaskSide.FRONT else "B.Cu"


def _flip_side(side: MaskSide) -> MaskSide:
    return MaskSide.BACK if side is MaskSide.FRONT else MaskSide.FRONT
