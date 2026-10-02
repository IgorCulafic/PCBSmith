"""Typed local deltas on native KiCad objects; no generator or router invocation."""

from __future__ import annotations

import copy
import hashlib
import math
from typing import Literal, Self
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr, serialize_sexpr
from pcbsmith.semantic_ir import SemanticIrModel


class NativeEdit(SemanticIrModel):
    kind: Literal[
        "text",
        "reference",
        "component",
        "segment",
        "segment_add",
        "segment_remove",
        "via",
        "model_offset",
        "zone_refill",
        "zone_outline",
        "zone_clearance",
    ]
    target: str = Field(min_length=1)
    position_mm: tuple[float, float] | None = None
    rotation_deg: float | None = None
    points_mm: tuple[tuple[float, float], ...] = ()
    offset_mm: tuple[float, float, float] | None = None
    attachment_policy: Literal["pad_centres", "pad_area"] = "pad_centres"
    clearance_mm: float | None = Field(default=None, gt=0)
    model_index: int = Field(default=0, ge=0)
    net_name: str | None = Field(default=None, exclude_if=lambda v: v is None)
    width_mm: float | None = Field(default=None, gt=0, exclude_if=lambda v: v is None)
    layer: Literal["F.Cu"] | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def applicable_fields(self) -> Self:
        if self.kind == "segment_add":
            if (
                not self.net_name
                or self.width_mm is None
                or self.layer is None
                or not 2 <= len(self.points_mm) <= 64
                or self.position_mm
                or self.offset_mm
                or self.rotation_deg is not None
            ):
                raise ValueError(
                    "segment insertion requires a net, width, front layer and polyline"
                )
            return self
        if self.net_name is not None or self.width_mm is not None or self.layer is not None:
            raise ValueError("new copper properties apply only to segment insertion")
        if self.kind == "segment_remove":
            if (
                self.position_mm
                or self.points_mm
                or self.offset_mm
                or self.rotation_deg is not None
            ):
                raise ValueError("segment removal accepts only its exact target")
            return self
        if self.attachment_policy != "pad_centres" and self.kind != "component":
            raise ValueError("pad attachment policy requires a component edit")
        if self.kind != "zone_clearance" and self.clearance_mm is not None:
            raise ValueError("clearance is only applicable to a zone clearance edit")
        if self.kind == "zone_clearance":
            if self.clearance_mm is None or self.position_mm or self.offset_mm or self.points_mm:
                raise ValueError("zone clearance accepts only a target and clearance")
        elif self.kind == "zone_refill":
            if self.position_mm or self.offset_mm or self.points_mm:
                raise ValueError("zone refill accepts only a target")
        elif self.kind == "zone_outline":
            if not 3 <= len(self.points_mm) <= 64 or self.position_mm or self.offset_mm:
                raise ValueError("zone outline needs 3..64 points")
        elif self.kind == "segment":
            if not 2 <= len(self.points_mm) <= 64 or self.position_mm or self.offset_mm:
                raise ValueError("segment edit needs 2..64 points and no position/offset")
        elif self.kind == "model_offset":
            if self.offset_mm is None or self.position_mm or self.points_mm:
                raise ValueError("model edit needs only an offset")
        elif self.position_mm is None or self.points_mm or self.offset_mm:
            raise ValueError("position edit needs only a position")
        if self.rotation_deg is not None and self.kind not in {"component", "text", "reference"}:
            raise ValueError("rotation is not applicable to this edit")
        if self.model_index and self.kind != "model_offset":
            raise ValueError("model index is only applicable to a model edit")
        return self


def atom(value: SExpr) -> str:
    return value.value if isinstance(value, QuotedString) else str(value)


def children(node: SList, name: str) -> list[SList]:
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def child(node: SList, name: str) -> SList:
    found = children(node, name)
    if len(found) != 1:
        raise ValueError(f"expected one {name} field, found {len(found)}")
    return found[0]


def object_id(node: SList, index: int) -> str:
    if node[0] == "embedded_fonts":
        return "@embedded_fonts"
    ids = children(node, "uuid")
    return atom(ids[0][1]) if ids else f"@{atom(node[0])}:{index}"


def object_inventory(tree: SList) -> dict[str, str]:
    result: dict[str, str] = {}
    for i, node in enumerate(tree):
        if not isinstance(node, list):
            continue
        identity = object_id(node, i)
        if identity in result:
            raise ValueError("duplicate native object identity")
        result[identity] = hashlib.sha256(serialize_sexpr(node).encode()).hexdigest()
    return result


def reference(node: SList) -> str | None:
    for prop in children(node, "property"):
        if len(prop) >= 3 and atom(prop[1]) == "Reference":
            return atom(prop[2])
    return None


def inspect_edit_objects(payload: bytes) -> list[dict[str, object]]:
    tree = parse_sexpr(payload.decode("utf-8"))
    object_inventory(tree)
    result: list[dict[str, object]] = []
    for i, node in enumerate(tree):
        if not isinstance(node, list) or node[0] not in {
            "footprint",
            "gr_text",
            "segment",
            "via",
            "zone",
        }:
            continue
        result.append(
            {
                "id": object_id(node, i),
                "kind": atom(node[0]),
                "reference": reference(node),
                "zone": {
                    "net_fields": [atom(v) for v in child(node, "net")[1:]],
                    "layer": atom(child(node, "layer")[1]),
                    "outline_points_mm": [
                        [list(_xy(xy)) for xy in children(child(poly, "pts"), "xy")]
                        for poly in children(node, "polygon")
                    ],
                    "filled_region_count": len(children(node, "filled_polygon")),
                }
                if node[0] == "zone"
                else None,
                "at": [atom(v) for v in children(node, "at")[0][1:]]
                if children(node, "at")
                else None,
                "text": atom(node[1]) if node[0] == "gr_text" else None,
                "start_mm": list(_xy(child(node, "start"))) if node[0] == "segment" else None,
                "end_mm": list(_xy(child(node, "end"))) if node[0] == "segment" else None,
                "reference_at": [atom(v) for v in child(prop, "at")[1:]]
                if (
                    prop := next(
                        (p for p in children(node, "property") if atom(p[1]) == "Reference"), None
                    )
                )
                is not None
                else None,
                "models": [
                    {
                        "index": j,
                        "path": atom(model[1]),
                        "offset_mm": [
                            float(atom(v)) for v in child(child(model, "offset"), "xyz")[1:4]
                        ],
                    }
                    for j, model in enumerate(children(node, "model"))
                ],
            }
        )
    return result


def _number(value: float) -> str:
    return format(round(value, 6), ".12g")


def _xy(node: SList) -> tuple[float, float]:
    return float(atom(node[1])), float(atom(node[2]))


def _set_position(node: SList, position: tuple[float, float], rotation: float | None) -> None:
    node[1:3] = [_number(v) for v in position]
    if rotation is not None:
        # Preserve optional fields such as 'unlocked' after the numeric angle.
        if len(node) > 3:
            try:
                float(atom(node[3]))
            except ValueError:
                node.insert(3, _number(rotation))
            else:
                node[3] = _number(rotation)
        else:
            node.append(_number(rotation))


def _pad_centres(footprint: SList) -> list[tuple[str, tuple[float, float]]]:
    if atom(child(footprint, "layer")[1]) != "F.Cu":
        raise ValueError("back-side component moves need a validated mirrored-pose adapter")
    at = child(footprint, "at")
    x, y = _xy(at)
    angle = math.radians(float(atom(at[3]))) if len(at) > 3 else 0.0
    result: list[tuple[str, tuple[float, float]]] = []
    for pad in children(footprint, "pad"):
        nets = children(pad, "net")
        if not nets:
            continue
        locations = children(pad, "at")
        px, py = _xy(locations[0]) if locations else (0.0, 0.0)
        result.append(
            (
                atom(nets[0][1]),
                (
                    round(x + px * math.cos(angle) + py * math.sin(angle), 6),
                    round(y - px * math.sin(angle) + py * math.cos(angle), 6),
                ),
            )
        )
    return result


def apply_native_edits(
    payload: bytes,
    edits: tuple[NativeEdit, ...],
    *,
    maximum_displacement_mm: float,
    maximum_changed_objects: int,
    allowed_zone_ids: tuple[str, ...] = (),
) -> tuple[bytes, dict[str, object]]:
    if not math.isfinite(maximum_displacement_mm) or maximum_displacement_mm <= 0:
        raise ValueError("displacement budget must be finite and positive")
    if maximum_changed_objects < 1:
        raise ValueError("changed-object budget must be positive")
    tree = parse_sexpr(payload.decode("utf-8"))
    if not tree or tree[0] != "kicad_pcb":
        raise ValueError("source is not a native KiCad board")
    before = object_inventory(tree)
    allowed: set[str] = set()
    targets: set[tuple[str, str, int]] = set()
    if (
        children(tree, "zone")
        and not allowed_zone_ids
        and any(
            e.kind in {"component", "segment", "segment_add", "segment_remove", "via"}
            for e in edits
        )
    ):
        raise ValueError("copper edits with zones require the existing final-fill repair adapter")
    for edit in edits:
        selector = (edit.kind, edit.target, edit.model_index)
        if selector in targets:
            raise ValueError("duplicate edit target")
        targets.add(selector)
        if edit.kind == "segment_add":
            net_fields = [
                child(pad, "net")[1:]
                for fp in children(tree, "footprint")
                for pad in children(fp, "pad")
                if children(pad, "net") and atom(child(pad, "net")[-1]) == edit.net_name
            ]
            if not net_fields:
                raise ValueError("inserted segment targets an unknown native net")
            net_value = net_fields[0][0]
            for j, (start, end) in enumerate(
                zip(edit.points_mm[:-1], edit.points_mm[1:], strict=True)
            ):
                if start == end or not all(math.isfinite(v) for p in (start, end) for v in p):
                    raise ValueError("invalid inserted segment coordinates")
                identity = str(
                    uuid5(
                        NAMESPACE_URL,
                        hashlib.sha256(payload).hexdigest() + edit.semantic_fingerprint() + str(j),
                    )
                )
                assert edit.width_mm is not None
                inserted: SList = [
                    "segment",
                    ["start", *map(_number, start)],
                    ["end", *map(_number, end)],
                    ["width", _number(edit.width_mm)],
                    ["layer", QuotedString("F.Cu")],
                    ["net", copy.deepcopy(net_value)],
                    ["uuid", QuotedString(identity)],
                ]
                tree.append(inserted)
                allowed.add(identity)
            continue
        matches = [
            (i, n)
            for i, n in enumerate(tree)
            if isinstance(n, list)
            and (
                object_id(n, i) == edit.target
                or (n[0] == "footprint" and reference(n) == edit.target)
            )
        ]
        if len(matches) != 1:
            raise ValueError(f"edit target is missing or ambiguous: {edit.target}")
        index, node = matches[0]
        expected = {
            "text": "gr_text",
            "reference": "footprint",
            "component": "footprint",
            "segment": "segment",
            "segment_remove": "segment",
            "via": "via",
            "model_offset": "footprint",
            "zone_refill": "zone",
            "zone_outline": "zone",
            "zone_clearance": "zone",
        }[edit.kind]
        if node[0] != expected:
            raise ValueError("edit kind does not match native target")
        if "locked" in node or children(node, "locked"):
            raise ValueError("locked objects cannot be edited by this operation")
        allowed.add(object_id(node, index))
        if edit.kind == "segment_remove":
            tree.remove(node)
            continue
        if edit.kind in {"zone_refill", "zone_outline", "zone_clearance"}:
            if object_id(node, index) not in allowed_zone_ids:
                raise ValueError("zone intent/refill requires explicit mutable zone authority")
            if edit.kind == "zone_clearance":
                assert edit.clearance_mm is not None
                child(child(node, "connect_pads"), "clearance")[1] = _number(edit.clearance_mm)
            if edit.kind == "zone_outline":
                points = child(child(node, "polygon"), "pts")
                old_points = children(points, "xy")
                if len(old_points) != len(edit.points_mm):
                    raise ValueError("zone outline edit must retain its vertex identities")
                for old_point, new_point in zip(old_points, edit.points_mm, strict=True):
                    if math.dist(_xy(old_point), new_point) > maximum_displacement_mm:
                        raise ValueError("zone vertex exceeds displacement budget")
                    _set_position(old_point, new_point, None)
            continue
        if edit.kind == "segment":
            original_start, original_end = _xy(child(node, "start")), _xy(child(node, "end"))
            if edit.points_mm[0] != original_start or edit.points_mm[-1] != original_end:
                raise ValueError("trace replacement must preserve its connected endpoints")
            xs, ys = zip(original_start, original_end, strict=True)
            for point in edit.points_mm:
                if not (
                    min(xs) - maximum_displacement_mm
                    <= point[0]
                    <= max(xs) + maximum_displacement_mm
                    and min(ys) - maximum_displacement_mm
                    <= point[1]
                    <= max(ys) + maximum_displacement_mm
                ):
                    raise ValueError("trace exceeds declared repair region")
            template = copy.deepcopy(node)
            for j, (start, end) in enumerate(
                zip(edit.points_mm[:-1], edit.points_mm[1:], strict=True)
            ):
                if start == end:
                    raise ValueError("zero-length segment")
                segment = node if j == 0 else copy.deepcopy(template)
                _set_position(child(segment, "start"), start, None)
                _set_position(child(segment, "end"), end, None)
                if j:
                    identity = str(
                        uuid5(
                            NAMESPACE_URL,
                            hashlib.sha256(payload).hexdigest()
                            + edit.semantic_fingerprint()
                            + str(j),
                        )
                    )
                    child(segment, "uuid")[1] = QuotedString(identity)
                    tree.append(segment)
                    allowed.add(identity)
        elif edit.kind == "model_offset":
            models = children(node, "model")
            if edit.model_index >= len(models) or edit.offset_mm is None:
                raise ValueError("selected model is missing")
            xyz = child(child(models[edit.model_index], "offset"), "xyz")
            old = tuple(float(atom(v)) for v in xyz[1:4])
            if math.dist(old, edit.offset_mm) > maximum_displacement_mm:
                raise ValueError("model offset exceeds displacement budget")
            xyz[1:4] = [_number(v) for v in edit.offset_mm]
        else:
            target = node
            if edit.kind == "reference":
                target = next(
                    prop for prop in children(node, "property") if atom(prop[1]) == "Reference"
                )
            at = child(target, "at")
            if edit.position_mm is None:
                raise ValueError("position is required")
            if math.dist(_xy(at), edit.position_mm) > maximum_displacement_mm:
                raise ValueError("edit exceeds displacement budget")
            old_pads = (
                _pad_centres(node)
                if edit.kind == "component"
                else [(atom(child(node, "net")[1]), _xy(at))]
                if edit.kind == "via"
                else []
            )
            old_pad_nodes = copy.deepcopy(children(node, "pad")) if edit.kind == "component" else []
            difference = 0.0
            if edit.kind == "component" and edit.rotation_deg is not None:
                original_angle = float(atom(at[3])) if len(at) > 3 else 0.0
                difference = edit.rotation_deg - original_angle
                # KiCad stores pad/text angles in board coordinates even though
                # their positions are footprint-local. Keep relative orientation.
                for member in node:
                    if isinstance(member, list) and member[0] in {"pad", "property", "fp_text"}:
                        for member_at in children(member, "at"):
                            angle = float(atom(member_at[3])) if len(member_at) > 3 else 0.0
                            _set_position(member_at, _xy(member_at), angle + difference)
            _set_position(at, edit.position_mm, edit.rotation_deg)
            new_pads = (
                _pad_centres(node)
                if edit.kind == "component"
                else [(atom(child(node, "net")[1]), _xy(at))]
                if edit.kind == "via"
                else []
            )
            for pad_index, ((net, old), (_, new)) in enumerate(
                zip(old_pads, new_pads, strict=True)
            ):
                if math.dist(old, new) > maximum_displacement_mm:
                    raise ValueError("moved pad exceeds displacement budget")
                if old == new:
                    continue
                for i, route in enumerate(tree):
                    if not isinstance(route, list) or route[0] not in {"segment", "arc", "via"}:
                        continue
                    if not children(route, "net") or atom(child(route, "net")[1]) != net:
                        continue
                    for endpoint_name in ("start", "end") if route[0] != "via" else ("at",):
                        endpoint_node = child(route, endpoint_name)
                        endpoint = _xy(endpoint_node)
                        attached = math.dist(endpoint, old) < 0.000001
                        if edit.attachment_policy == "pad_area":
                            pad = old_pad_nodes[pad_index]
                            size = child(pad, "size")
                            at_pad = child(pad, "at")
                            angle = math.radians(float(atom(at_pad[3])) if len(at_pad) > 3 else 0)
                            dx, dy = endpoint[0] - old[0], endpoint[1] - old[1]
                            px, py = (
                                abs(dx * math.cos(angle) - dy * math.sin(angle)),
                                abs(dx * math.sin(angle) + dy * math.cos(angle)),
                            )
                            hx, hy = float(atom(size[1])) / 2, float(atom(size[2])) / 2
                            if atom(pad[3]) not in {"rect", "roundrect"}:
                                raise ValueError(
                                    "pad-area attachment supports rectangular SMD pads"
                                )
                            radius = (
                                min(hx, hy) * 2 * float(atom(child(pad, "roundrect_rratio")[1]))
                                if atom(pad[3]) == "roundrect"
                                else 0.0
                            )
                            attached = (
                                px <= hx
                                and py <= hy
                                and math.hypot(max(px - hx + radius, 0), max(py - hy + radius, 0))
                                <= radius + 1e-6
                            )
                        if attached:
                            if (
                                route[0] != "segment"
                                or "locked" in route
                                or children(route, "locked")
                            ):
                                raise ValueError(
                                    "attached arc/via/locked copper needs an explicit repair"
                                )
                            moved = new
                            if edit.attachment_policy == "pad_area":
                                angle = math.radians(-difference)
                                dx, dy = endpoint[0] - old[0], endpoint[1] - old[1]
                                moved = (
                                    new[0] + dx * math.cos(angle) - dy * math.sin(angle),
                                    new[1] + dx * math.sin(angle) + dy * math.cos(angle),
                                )
                            _set_position(endpoint_node, moved, None)
                            allowed.add(object_id(route, i))
    after = object_inventory(tree)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if set(changed) - allowed:
        raise ValueError(f"edit changed protected native objects: {sorted(set(changed)-allowed)}")
    if len(changed) > maximum_changed_objects:
        raise ValueError("edit exceeds changed-object budget")
    output = (serialize_sexpr(tree) + "\n").encode() if changed else payload
    if object_inventory(parse_sexpr(output.decode())) != after:
        raise ValueError("native serialization changed object semantics")
    return output, {
        "changed_ids": changed,
        "protected_ids": sorted(before.keys() - set(changed)),
        "before": before,
        "after": after,
        "generator_invocations": 0,
        "router_invocations": 0,
        "endpoint_policy": "stretch exact pad-centre segments; native checks required",
    }
