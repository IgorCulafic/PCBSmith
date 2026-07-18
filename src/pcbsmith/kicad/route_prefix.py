"""Pure, versioned detailed-route prefix primitives for the R3 exchange seam."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, TypeAlias

from pcbsmith.kicad.board import TrackSegment, ViaSpec
from pcbsmith.mask_geometry import ViaMaskIntent

GridNode: TypeAlias = tuple[str, int, int]
CoveredPadAnchor: TypeAlias = tuple[str, GridNode]

_LAYERS = frozenset(("F.Cu", "B.Cu"))
_GRID_ALIGNMENT_EPSILON = 1e-9


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require_identity(value: str, field_name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a canonical non-empty identity")


def _validate_node(node: GridNode, field_name: str) -> None:
    if (
        not isinstance(node, tuple)
        or len(node) != 3
        or node[0] not in _LAYERS
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in node[1:]
        )
    ):
        raise ValueError(f"{field_name} must be a supported non-negative grid node")


def _grid_index(value_mm: float, grid_mm: float, field_name: str) -> int:
    if not math.isfinite(value_mm):
        raise ValueError(f"{field_name} must be finite")
    coordinate = value_mm / grid_mm
    nearest = round(coordinate)
    if nearest < 0 or abs(coordinate - nearest) > _GRID_ALIGNMENT_EPSILON:
        raise ValueError(f"{field_name} must lie exactly on the non-negative prefix grid")
    return nearest


def _node(layer: str, x_mm: float, y_mm: float, grid_mm: float) -> GridNode:
    if layer not in _LAYERS:
        raise ValueError(f"unsupported prefix copper layer {layer!r}")
    return (
        layer,
        _grid_index(x_mm, grid_mm, "copper x coordinate"),
        _grid_index(y_mm, grid_mm, "copper y coordinate"),
    )


def _canonical_segment(segment: TrackSegment, net_name: str, grid_mm: float) -> TrackSegment:
    if segment.net_name != net_name:
        raise ValueError("prefix segment net ownership does not match the prefix net")
    if not math.isfinite(segment.width_mm) or segment.width_mm <= 0:
        raise ValueError("prefix segment width must be finite and positive")
    first = _node(segment.layer, segment.x1, segment.y1, grid_mm)
    second = _node(segment.layer, segment.x2, segment.y2, grid_mm)
    if first == second:
        raise ValueError("prefix segments must have distinct endpoints")
    low, high = sorted((first, second))
    return TrackSegment(
        x1=low[1] * grid_mm,
        y1=low[2] * grid_mm,
        x2=high[1] * grid_mm,
        y2=high[2] * grid_mm,
        layer=low[0],
        net_name=net_name,
        width_mm=segment.width_mm,
    )


def _canonical_via(via: ViaSpec, net_name: str, grid_mm: float) -> ViaSpec:
    if via.net_name != net_name:
        raise ValueError("prefix via net ownership does not match the prefix net")
    ix = _grid_index(via.x, grid_mm, "via x coordinate")
    iy = _grid_index(via.y, grid_mm, "via y coordinate")
    if (
        not math.isfinite(via.size_mm)
        or not math.isfinite(via.drill_mm)
        or via.size_mm <= 0
        or via.drill_mm <= 0
        or via.drill_mm >= via.size_mm
    ):
        raise ValueError("prefix via size and drill must be finite, positive, and ordered")
    try:
        front_mask = ViaMaskIntent(via.front_mask)
        back_mask = ViaMaskIntent(via.back_mask)
    except ValueError as error:
        raise ValueError("prefix via mask intents must be supported") from error
    return ViaSpec(
        x=ix * grid_mm,
        y=iy * grid_mm,
        net_name=net_name,
        size_mm=via.size_mm,
        drill_mm=via.drill_mm,
        front_mask=front_mask,
        back_mask=back_mask,
    )


def _segment_key(segment: TrackSegment) -> tuple[object, ...]:
    return (
        segment.layer,
        segment.x1,
        segment.y1,
        segment.x2,
        segment.y2,
        segment.net_name,
        segment.width_mm,
    )


def _via_key(via: ViaSpec) -> tuple[object, ...]:
    return (
        via.x,
        via.y,
        via.net_name,
        via.size_mm,
        via.drill_mm,
        via.front_mask.value,
        via.back_mask.value,
    )


@dataclass(frozen=True)
class GridRoutePrefix:
    """A canonical connected fine-route prefix ending at one exact grid node.

    Covered pad identities bind only explicitly supplied grid anchor nodes. This
    object does not claim that those nodes touch physical pad copper; that proof
    remains the responsibility of the later board adapter and exact checker.
    """

    alternative_id: str
    net_name: str
    grid_mm: float
    exit_node: GridNode
    covered_pad_anchors: tuple[CoveredPadAnchor, ...]
    segments: tuple[TrackSegment, ...]
    vias: tuple[ViaSpec, ...] = ()

    def __post_init__(self) -> None:
        _require_identity(self.alternative_id, "alternative_id")
        _require_identity(self.net_name, "net_name")
        if not math.isfinite(self.grid_mm) or self.grid_mm <= 0:
            raise ValueError("grid_mm must be finite and positive")
        _validate_node(self.exit_node, "exit_node")

        anchors_by_id: dict[str, GridNode] = {}
        for source_id, node in self.covered_pad_anchors:
            _require_identity(source_id, "covered pad source_id")
            _validate_node(node, "covered pad anchor")
            if source_id in anchors_by_id:
                raise ValueError("covered pad source identities must be unique")
            anchors_by_id[source_id] = node
        if not anchors_by_id:
            raise ValueError("a route prefix requires at least one covered pad anchor")

        segments_by_key: dict[tuple[object, ...], TrackSegment] = {}
        for segment_source in self.segments:
            segment = _canonical_segment(segment_source, self.net_name, self.grid_mm)
            segments_by_key[_segment_key(segment)] = segment
        vias_by_key: dict[tuple[object, ...], ViaSpec] = {}
        for via_source in self.vias:
            via = _canonical_via(via_source, self.net_name, self.grid_mm)
            vias_by_key[_via_key(via)] = via
        if not segments_by_key and not vias_by_key:
            raise ValueError("a route prefix requires copper geometry")

        anchors = tuple(sorted(anchors_by_id.items()))
        segments = tuple(segments_by_key[key] for key in sorted(segments_by_key))
        vias = tuple(vias_by_key[key] for key in sorted(vias_by_key))
        object.__setattr__(self, "covered_pad_anchors", anchors)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "vias", vias)
        self._validate_connectivity()

    def _validate_connectivity(self) -> None:
        adjacency: dict[GridNode, set[GridNode]] = {}

        def connect(first: GridNode, second: GridNode) -> None:
            adjacency.setdefault(first, set()).add(second)
            adjacency.setdefault(second, set()).add(first)

        for segment in self.segments:
            first = _node(segment.layer, segment.x1, segment.y1, self.grid_mm)
            second = _node(segment.layer, segment.x2, segment.y2, self.grid_mm)
            connect(first, second)
        for via in self.vias:
            ix = _grid_index(via.x, self.grid_mm, "via x coordinate")
            iy = _grid_index(via.y, self.grid_mm, "via y coordinate")
            connect(("F.Cu", ix, iy), ("B.Cu", ix, iy))

        if self.exit_node not in adjacency:
            raise ValueError("prefix exit_node must touch prefix copper")
        reached: set[GridNode] = set()
        pending = [self.exit_node]
        while pending:
            node = pending.pop()
            if node in reached:
                continue
            reached.add(node)
            pending.extend(sorted(adjacency[node] - reached, reverse=True))
        if reached != set(adjacency):
            raise ValueError("all prefix segment and via geometry must be connected to the exit")
        if any(node not in reached for _source_id, node in self.covered_pad_anchors):
            raise ValueError("every covered pad anchor must be connected to the prefix exit")

    def semantic_fingerprint(self) -> str:
        payload = {
            "schema_id": "pcbsmith-grid-route-prefix",
            "schema_version": 1,
            "alternative_id": self.alternative_id,
            "net_name": self.net_name,
            "grid_mm": self.grid_mm,
            "exit_node": self.exit_node,
            "covered_pad_anchors": self.covered_pad_anchors,
            "segments": [
                {
                    "start_mm": (segment.x1, segment.y1),
                    "end_mm": (segment.x2, segment.y2),
                    "layer": segment.layer,
                    "net_name": segment.net_name,
                    "width_mm": segment.width_mm,
                }
                for segment in self.segments
            ],
            "vias": [
                {
                    "at_mm": (via.x, via.y),
                    "net_name": via.net_name,
                    "size_mm": via.size_mm,
                    "drill_mm": via.drill_mm,
                    "front_mask": via.front_mask.value,
                    "back_mask": via.back_mask.value,
                }
                for via in self.vias
            ],
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
