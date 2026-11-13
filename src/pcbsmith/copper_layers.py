"""Ordered copper surfaces for the supported production routing stackups.

Layer count is geometry, not a qualified laminate, impedance, or current rating.
The one-sided process keeps KiCad's unused back layer in its native file.
"""

from collections.abc import Iterable
from typing import Literal, TypeAlias

CopperLayer: TypeAlias = Literal["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def routing_copper_layers(count: int) -> tuple[CopperLayer, ...]:
    if type(count) is not int or count not in (1, 2, 4):
        raise ValueError("production routing supports one, two, or four copper layers")
    stacks: dict[int, tuple[CopperLayer, ...]] = {
        1: ("F.Cu",),
        2: ("F.Cu", "B.Cu"),
        4: ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
    }
    return stacks[count]


def native_copper_layers(count: int) -> tuple[CopperLayer, ...]:
    layers = routing_copper_layers(count)
    return ("F.Cu", "B.Cu") if len(layers) == 1 else layers


def ordered_copper_layers(layers: Iterable[str]) -> tuple[CopperLayer, ...]:
    """Validate a complete routing stack, independent of IR identity sorting."""
    supplied = tuple(layers)
    expected = routing_copper_layers(len(supplied))
    if set(supplied) != set(expected):
        raise ValueError("unsupported or incomplete copper layer set")
    return expected


def via_copper_span(layers: Iterable[str], start: str, end: str) -> tuple[CopperLayer, ...]:
    """All copper surfaces a via touches, including intervening inner layers."""
    ordered = ordered_copper_layers(layers)
    first, last = ordered.index(start), ordered.index(end)
    if first == last:
        raise ValueError("a via must span distinct copper layers")
    return ordered[min(first, last) : max(first, last) + 1]
