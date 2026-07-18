"""Collect KiCad solder-mask intent into engine-neutral aperture geometry.

Collection is deliberately conservative: exact geometry is returned only for
KiCad 10 semantics pinned by local export fixtures.  Every observable source
whose final aperture cannot be resolved is retained as ``UNSUPPORTED``.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import cast

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardLayout,
    BoardNetlist,
    ViaSpec,
    _via_identity,
    placement_rotation,
    placement_y,
)
from pcbsmith.kicad.copper_identity import pad_copper_source_id, via_copper_source_id
from pcbsmith.kicad.library import (
    FootprintLibraryError,
    PadSpec,
    QuotedString,
    SExpr,
    SList,
    load_footprint,
    serialize_sexpr,
)
from pcbsmith.mask_geometry import (
    MASK_GEOMETRY_EPSILON_MM,
    Capsule,
    Disc,
    GeometryTransform,
    MaskAperture,
    MaskGeometry,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    OrientedRect,
    Point,
    RoundedRect,
    ViaMaskIntent,
    stable_mask_source_id,
    transform_geometry,
)
from pcbsmith.rule_profiles import PcbRuleProfile

_FOOTPRINT_MASK_GRAPHICS = frozenset({"fp_line", "fp_rect", "fp_circle", "fp_poly", "fp_arc"})
_RAW_MASK_LAYER = re.compile(r"\((?:layer|layers)\s+[^)]*?\"?([FB])\.Mask\"?(?=\s|\))")


def collect_mask_apertures(
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
) -> tuple[MaskAperture, ...]:
    """Return resolved and explicitly unresolved physical mask sources."""
    del netlist  # Reserved for later copper-source linkage.
    result: list[MaskAperture] = []
    result.extend(_collect_pad_apertures(layout, profile))
    result.extend(_collect_via_apertures(layout, profile))
    result.extend(_collect_typed_board_apertures(layout))
    result.extend(_collect_raw_board_graphics(layout))
    result.extend(_collect_raw_footprint_graphics(layout))
    return tuple(result)


def _collect_pad_apertures(layout: BoardLayout, profile: PcbRuleProfile) -> Iterable[MaskAperture]:
    for component, anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        flipped = component.reference in layout.part_flip
        transform = GeometryTransform(
            translate_x_mm=anchor_x,
            translate_y_mm=placement_y(layout, component.reference),
            rotation_deg=-placement_rotation(layout, component.reference),
            mirror_x=flipped,
        )
        name_occurrences: Counter[str] = Counter()
        for pad_index, pad in enumerate(spec.pads):
            occurrence = name_occurrences[pad.name]
            name_occurrences[pad.name] += 1
            sides = _pad_sides(pad, flipped)
            for side in sides:
                source_id = stable_mask_source_id(
                    "placed-pad-aperture-v1",
                    component.uuid_path.strip("/"),
                    component.reference,
                    pad.name,
                    str(occurrence),
                    side.value,
                )
                reason = _pad_unsupported_reason(pad, profile)
                copper_source_ids = (
                    ()
                    if pad.kind == "npth"
                    else (
                        pad_copper_source_id(component.reference, pad_index, _copper_layer(side)),
                    )
                )
                if reason is not None:
                    yield _unsupported(
                        source_id,
                        MaskSourceKind.PAD,
                        side,
                        reason,
                        owner_ref=component.reference,
                        copper_source_ids=copper_source_ids,
                    )
                    continue
                expansion = _effective_pad_expansion(pad, profile)
                if expansion is None:  # narrowed by _pad_unsupported_reason
                    raise AssertionError("resolved pad expansion unexpectedly missing")
                geometry, geometry_reason = pad_local_geometry(pad, expansion)
                if geometry is None:
                    yield _unsupported(
                        source_id,
                        MaskSourceKind.PAD,
                        side,
                        geometry_reason or "pad mask geometry is unsupported",
                        owner_ref=component.reference,
                        copper_source_ids=copper_source_ids,
                    )
                    continue
                yield MaskAperture(
                    source_id=source_id,
                    source_kind=MaskSourceKind.PAD,
                    side=side,
                    geometry=transform_geometry(geometry, transform),
                    owner_ref=component.reference,
                    verification=MaskVerification.EXACT,
                    copper_source_ids=copper_source_ids,
                )


def _pad_sides(pad: PadSpec, flipped: bool) -> tuple[MaskSide, ...]:
    if not pad.layers:
        return (MaskSide.FRONT, MaskSide.BACK)
    source_sides: set[MaskSide] = set()
    if "*.Mask" in pad.layers:
        source_sides.update((MaskSide.FRONT, MaskSide.BACK))
    if "F.Mask" in pad.layers:
        source_sides.add(MaskSide.FRONT)
    if "B.Mask" in pad.layers:
        source_sides.add(MaskSide.BACK)
    physical = {_flip_side(side) if flipped else side for side in source_sides}
    return tuple(side for side in MaskSide if side in physical)


def _pad_unsupported_reason(pad: PadSpec, profile: PcbRuleProfile) -> str | None:
    if not pad.layers:
        return "pad source layers are unknown; mask-side membership is unresolved"
    if pad.solder_mask_margin_ratio is not None:
        return "KiCad 10 rejects solder_mask_margin_ratio; aperture is unresolved"
    if pad.source_anchor is None:
        return "pad source anchor was not preserved; routing bounds are not mask geometry"
    if not all(
        math.isfinite(value)
        for value in (
            pad.source_anchor.x_mm,
            pad.source_anchor.y_mm,
            pad.source_anchor.width_mm,
            pad.source_anchor.height_mm,
            pad.angle_deg,
        )
    ):
        return "pad source anchor contains non-finite geometry"
    if pad.chamfer_ratio is not None or pad.chamfer_positions:
        return "chamfered pad mask geometry is not implemented exactly"
    if pad.shape == "custom" or pad.custom_source is not None:
        return "custom pad source is preserved but its exact mask geometry is unsupported"
    if pad.shape not in {"circle", "oval", "rect", "roundrect"}:
        return f"pad shape {pad.shape or '<unknown>'!r} has no exact mask model"
    if _effective_pad_expansion(pad, profile) is None:
        return "default pad solder-mask expansion is not declared"
    return None


def _effective_pad_expansion(pad: PadSpec, profile: PcbRuleProfile) -> float | None:
    local = pad.solder_mask_margin_mm
    if local is not None and local != 0.0:
        return local
    return profile.geometry.default_pad_solder_mask_expansion_mm


def pad_local_geometry(pad: PadSpec, expansion: float) -> tuple[MaskGeometry | None, str | None]:
    anchor = pad.source_anchor
    if anchor is None:
        return None, "pad source anchor is missing"
    width = anchor.width_mm + 2.0 * expansion
    height = anchor.height_mm + 2.0 * expansion
    if width <= MASK_GEOMETRY_EPSILON_MM or height <= MASK_GEOMETRY_EPSILON_MM:
        return None, "mask expansion collapses a pad aperture axis"
    center = Point(x_mm=anchor.x_mm, y_mm=anchor.y_mm)
    angle = -pad.angle_deg

    if pad.shape == "circle":
        if not math.isclose(
            anchor.width_mm,
            anchor.height_mm,
            rel_tol=0.0,
            abs_tol=MASK_GEOMETRY_EPSILON_MM,
        ):
            return None, "circle pad source has unequal axes"
        return Disc(center=center, radius_mm=width / 2.0), None

    if pad.shape == "oval":
        if math.isclose(width, height, rel_tol=0.0, abs_tol=MASK_GEOMETRY_EPSILON_MM):
            return Disc(center=center, radius_mm=min(width, height) / 2.0), None
        radius = min(width, height) / 2.0
        half_axis = (max(width, height) - min(width, height)) / 2.0
        local_angle = angle + (0.0 if width > height else 90.0)
        radians = math.radians(local_angle)
        dx = half_axis * math.cos(radians)
        dy = half_axis * math.sin(radians)
        return (
            Capsule(
                a=Point(x_mm=center.x_mm - dx, y_mm=center.y_mm - dy),
                b=Point(x_mm=center.x_mm + dx, y_mm=center.y_mm + dy),
                radius_mm=radius,
            ),
            None,
        )

    if pad.shape == "rect":
        if expansion > 0.0:
            return (
                RoundedRect(
                    center=center,
                    width_mm=width,
                    height_mm=height,
                    corner_radius_mm=expansion,
                    angle_deg=angle,
                ),
                None,
            )
        return (
            OrientedRect(
                center=center,
                width_mm=width,
                height_mm=height,
                angle_deg=angle,
            ),
            None,
        )

    if pad.roundrect_rratio is None:
        return None, "roundrect pad is missing its source corner-radius ratio"
    base_radius = min(anchor.width_mm, anchor.height_mm) * pad.roundrect_rratio
    radius = base_radius + expansion
    if radius < 0.0:
        return None, "negative expansion makes the roundrect corner radius negative"
    if radius > min(width, height) / 2.0 + MASK_GEOMETRY_EPSILON_MM:
        return None, "roundrect source ratio or expansion produces an invalid radius"
    return (
        RoundedRect(
            center=center,
            width_mm=width,
            height_mm=height,
            corner_radius_mm=max(radius, 0.0),
            angle_deg=angle,
        ),
        None,
    )


def _collect_via_apertures(layout: BoardLayout, profile: PcbRuleProfile) -> Iterable[MaskAperture]:
    occurrences: Counter[tuple[str, ...]] = Counter()
    for via_index, via in enumerate(layout.vias):
        identity = _via_identity(via)
        occurrence = occurrences[identity]
        occurrences[identity] += 1
        for side, intent in (
            (MaskSide.FRONT, _via_intent(via, "front_mask")),
            (MaskSide.BACK, _via_intent(via, "back_mask")),
        ):
            source_id = stable_mask_source_id(
                "placed-via-aperture-v1", *identity, str(occurrence), side.value
            )
            copper_source_ids = (via_copper_source_id(via_index, _copper_layer(side)),)
            if intent is ViaMaskIntent.TENTED:
                continue
            if intent is ViaMaskIntent.INHERIT:
                yield _unsupported(
                    source_id,
                    MaskSourceKind.VIA,
                    side,
                    "via mask intent inherits an unresolved profile/toolchain policy",
                    copper_source_ids=copper_source_ids,
                )
                continue
            expansion = profile.geometry.default_pad_solder_mask_expansion_mm
            diameter = via.size_mm + 2.0 * expansion if expansion is not None else None
            if diameter is None:
                yield _unsupported(
                    source_id,
                    MaskSourceKind.VIA,
                    side,
                    "open via aperture requires a declared global mask expansion",
                    copper_source_ids=copper_source_ids,
                )
            elif diameter <= MASK_GEOMETRY_EPSILON_MM:
                yield _unsupported(
                    source_id,
                    MaskSourceKind.VIA,
                    side,
                    "global mask expansion collapses the open via aperture",
                    copper_source_ids=copper_source_ids,
                )
            else:
                yield MaskAperture(
                    source_id=source_id,
                    source_kind=MaskSourceKind.VIA,
                    side=side,
                    geometry=Disc(
                        center=Point(x_mm=via.x, y_mm=via.y),
                        radius_mm=diameter / 2.0,
                    ),
                    verification=MaskVerification.EXACT,
                    copper_source_ids=copper_source_ids,
                )


def _via_intent(via: ViaSpec, field: str) -> ViaMaskIntent:
    value = getattr(via, field, ViaMaskIntent.INHERIT)
    return value if isinstance(value, ViaMaskIntent) else ViaMaskIntent(cast(str, value))


def _collect_typed_board_apertures(layout: BoardLayout) -> Iterable[MaskAperture]:
    by_id: dict[str, list[MaskAperture]] = defaultdict(list)
    for aperture in layout.mask_apertures:
        by_id[aperture.source_id].append(aperture)
    for source_id, items in by_id.items():
        if len(items) == 1 and items[0].source_kind is MaskSourceKind.BOARD_GRAPHIC:
            yield items[0]
            continue
        if len(items) > 1 and len({item.semantic_json() for item in items}) == 1:
            item = items[0]
            if item.source_kind is MaskSourceKind.BOARD_GRAPHIC:
                yield item
                continue
        reason = (
            "typed board aperture has a non-board source kind"
            if len(items) == 1
            else "typed board aperture source ID is duplicated with unequal content"
        )
        for index, item in enumerate(items):
            yield _unsupported(
                stable_mask_source_id(
                    "typed-board-aperture-integrity-v1",
                    source_id,
                    item.semantic_fingerprint(),
                    str(index),
                ),
                MaskSourceKind.BOARD_GRAPHIC,
                item.side,
                reason,
            )


def _collect_raw_board_graphics(layout: BoardLayout) -> Iterable[MaskAperture]:
    for index, graphic in enumerate(layout.graphics):
        digest = hashlib.sha256(graphic.encode("utf-8")).hexdigest()
        for side in _raw_string_mask_sides(graphic):
            yield _unsupported(
                stable_mask_source_id("raw-board-mask-graphic-v1", str(index), digest, side.value),
                MaskSourceKind.BOARD_GRAPHIC,
                side,
                "raw board mask graphic is opaque and has no verified exact geometry",
            )


def _collect_raw_footprint_graphics(layout: BoardLayout) -> Iterable[MaskAperture]:
    for component, _anchor_x in layout.placements:
        flipped = component.reference in layout.part_flip
        try:
            tree = load_footprint(component.footprint).tree
        except FootprintLibraryError:
            continue
        for index, node in enumerate(tree):
            if not isinstance(node, list) or _node_head(node) not in _FOOTPRINT_MASK_GRAPHICS:
                continue
            canonical = serialize_sexpr(node)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            for source_side in _node_mask_sides(node):
                side = _flip_side(source_side) if flipped else source_side
                yield _unsupported(
                    stable_mask_source_id(
                        "raw-footprint-mask-graphic-v1",
                        component.uuid_path.strip("/"),
                        component.reference,
                        str(index),
                        digest,
                        side.value,
                    ),
                    MaskSourceKind.FOOTPRINT_GRAPHIC,
                    side,
                    "raw footprint mask graphic is opaque and has no verified exact geometry",
                    owner_ref=component.reference,
                )


def _node_mask_sides(node: SList) -> tuple[MaskSide, ...]:
    layers: set[str] = set()
    for child in node:
        if isinstance(child, list) and _node_head(child) == "layer":
            layers.update(_atom(item) for item in child[1:] if not isinstance(item, list))
    return _layer_mask_sides(layers)


def _raw_string_mask_sides(graphic: str) -> tuple[MaskSide, ...]:
    sides = {
        MaskSide.FRONT if match.group(1) == "F" else MaskSide.BACK
        for match in _RAW_MASK_LAYER.finditer(graphic)
    }
    if re.search(r"\((?:layer|layers)\s+[^)]*?\"?\*\.Mask\"?(?=\s|\))", graphic):
        sides.update((MaskSide.FRONT, MaskSide.BACK))
    return tuple(side for side in MaskSide if side in sides)


def _layer_mask_sides(layers: set[str]) -> tuple[MaskSide, ...]:
    sides: set[MaskSide] = set()
    if "*.Mask" in layers:
        sides.update((MaskSide.FRONT, MaskSide.BACK))
    if "F.Mask" in layers:
        sides.add(MaskSide.FRONT)
    if "B.Mask" in layers:
        sides.add(MaskSide.BACK)
    return tuple(side for side in MaskSide if side in sides)


def _node_head(node: SList) -> str | None:
    return _atom(node[0]) if node and not isinstance(node[0], list) else None


def _atom(node: SExpr) -> str:
    if isinstance(node, QuotedString):
        return node.value
    if isinstance(node, str):
        return node
    raise TypeError("expected S-expression atom")


def _flip_side(side: MaskSide) -> MaskSide:
    return MaskSide.BACK if side is MaskSide.FRONT else MaskSide.FRONT


def _unsupported(
    source_id: str,
    source_kind: MaskSourceKind,
    side: MaskSide,
    reason: str,
    *,
    owner_ref: str | None = None,
    copper_source_ids: tuple[str, ...] = (),
) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        source_kind=source_kind,
        side=side,
        owner_ref=owner_ref,
        verification=MaskVerification.UNSUPPORTED,
        copper_source_ids=copper_source_ids,
        unsupported_reason=reason,
    )


def _copper_layer(side: MaskSide) -> str:
    return "F.Cu" if side is MaskSide.FRONT else "B.Cu"
