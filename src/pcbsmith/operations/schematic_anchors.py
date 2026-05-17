from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Symbol
from pcbsmith.core.schematic import Schematic, SymbolInstance


class SchematicAnchorKind(StrEnum):
    PIN = "pin"
    WIRE_ENDPOINT = "wire_endpoint"


class SchematicAnchor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: SchematicAnchorKind
    position: Point


class AnchorMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    anchor: SchematicAnchor
    distance_nm: int


def schematic_anchors(
    schematic: Schematic,
    symbols: dict[str, Symbol],
) -> tuple[SchematicAnchor, ...]:
    anchors: list[SchematicAnchor] = []
    for instance in schematic.symbols:
        symbol = symbols[instance.symbol_id]
        for pin in symbol.pins:
            anchors.append(
                SchematicAnchor(
                    id=f"{instance.reference}.{pin.number}",
                    kind=SchematicAnchorKind.PIN,
                    position=symbol_pin_position(instance, pin.position),
                )
            )

    for wire_index, wire in enumerate(schematic.wires):
        anchors.append(
            SchematicAnchor(
                id=f"wire:{wire_index}:start",
                kind=SchematicAnchorKind.WIRE_ENDPOINT,
                position=wire.points[0],
            )
        )
        anchors.append(
            SchematicAnchor(
                id=f"wire:{wire_index}:end",
                kind=SchematicAnchorKind.WIRE_ENDPOINT,
                position=wire.points[-1],
            )
        )

    return tuple(anchors)


def nearest_anchor(
    point: Point,
    anchors: tuple[SchematicAnchor, ...],
    *,
    tolerance_nm: int,
) -> AnchorMatch | None:
    candidates = [
        (anchor_priority(anchor), squared_distance(point, anchor.position), anchor)
        for anchor in anchors
        if squared_distance(point, anchor.position) <= tolerance_nm * tolerance_nm
    ]
    if not candidates:
        return None

    _priority, distance_squared, anchor = min(candidates, key=lambda item: (item[0], item[1]))
    return AnchorMatch(
        anchor=anchor,
        distance_nm=math.isqrt(distance_squared),
    )


def symbol_pin_position(instance: SymbolInstance, pin_position: Point) -> Point:
    x = -pin_position.x if instance.mirrored_x else pin_position.x
    y = pin_position.y
    x, y = rotate_offset(x, y, instance.rotation_deg)
    return Point(x=instance.position.x + x, y=instance.position.y + y)


def rotate_offset(x: int, y: int, rotation_deg: int) -> tuple[int, int]:
    rotation = rotation_deg % 360
    if rotation == 0:
        return (x, y)
    if rotation == 90:
        return (-y, x)
    if rotation == 180:
        return (-x, -y)
    if rotation == 270:
        return (y, -x)
    msg = (
        f"Unsupported symbol rotation {rotation_deg}; "
        "expected one of 0, 90, 180, or 270 degrees"
    )
    raise ValueError(msg)


def anchor_priority(anchor: SchematicAnchor) -> int:
    if anchor.kind == SchematicAnchorKind.PIN:
        return 0
    return 1


def squared_distance(first: Point, second: Point) -> int:
    dx = first.x - second.x
    dy = first.y - second.y
    return dx * dx + dy * dy


__all__ = [
    "AnchorMatch",
    "SchematicAnchor",
    "SchematicAnchorKind",
    "nearest_anchor",
    "rotate_offset",
    "schematic_anchors",
    "symbol_pin_position",
]
