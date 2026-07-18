"""Project exact rectangular corridor allocations onto the detailed KiCad grid."""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.corridor_guidance import CorridorNetGuide, CorridorRouteGuide
from pcbsmith.corridor_ir import (
    CorridorCell,
    CorridorGraph,
    CorridorIrModel,
    CorridorPortal,
    CorridorViaPortal,
)
from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.negotiated_grid import (
    GridNode,
    GridSoftGuide,
    GridTrackTransition,
)

_EPSILON = 1e-9


class KiCadGridNetGuide(CorridorIrModel):
    """Canonical fine-grid preference for one routed net."""

    net_name: str = Field(min_length=1)
    allowed_track_nodes: tuple[GridNode, ...]
    allowed_track_transitions: tuple[GridTrackTransition, ...]
    allowed_via_cells: tuple[tuple[int, int], ...] = ()

    @model_validator(mode="after")
    def geometry_is_canonical(self) -> Self:
        nodes = tuple(sorted(set(self.allowed_track_nodes)))
        transitions = tuple(
            sorted({tuple(sorted(transition)) for transition in self.allowed_track_transitions})
        )
        vias = tuple(sorted(set(self.allowed_via_cells)))
        node_set = set(nodes)
        for layer, ix, iy in nodes:
            if layer not in ("F.Cu", "B.Cu") or ix < 0 or iy < 0:
                raise ValueError(
                    "grid guide nodes require a supported layer and non-negative indices"
                )
        for start, end in transitions:
            if start not in node_set or end not in node_set:
                raise ValueError("grid guide transition endpoints must be allowed nodes")
            if start[0] != end[0] or max(abs(start[1] - end[1]), abs(start[2] - end[2])) != 1:
                raise ValueError("grid guide transitions require adjacent same-layer nodes")
        if any(ix < 0 or iy < 0 for ix, iy in vias):
            raise ValueError("grid guide via indices must be non-negative")
        object.__setattr__(self, "allowed_track_nodes", nodes)
        object.__setattr__(self, "allowed_track_transitions", transitions)
        object.__setattr__(self, "allowed_via_cells", vias)
        return self


class KiCadGridRouteGuide(CorridorIrModel):
    """Versioned projection whose fingerprint binds grid pitch and board bounds."""

    schema_id: Literal["pcbsmith-kicad-grid-route-guide"] = "pcbsmith-kicad-grid-route-guide"
    schema_version: Literal[1] = 1
    source_guide_fingerprint: str
    grid_mm: float = Field(gt=0)
    columns: int = Field(gt=0)
    rows: int = Field(gt=0)
    off_corridor_penalty_units: int = Field(ge=0)
    net_guides: tuple[KiCadGridNetGuide, ...]

    @field_validator("source_guide_fingerprint")
    @classmethod
    def fingerprint_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("source_guide_fingerprint must be a lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def nets_are_canonical(self) -> Self:
        by_name: dict[str, KiCadGridNetGuide] = {}
        for guide in self.net_guides:
            previous = by_name.get(guide.net_name)
            if previous is not None and previous != guide:
                raise ValueError(f"conflicting projected guide for net {guide.net_name!r}")
            by_name[guide.net_name] = guide
        if not by_name:
            raise ValueError("a projected route guide requires at least one net")
        object.__setattr__(self, "net_guides", tuple(by_name[name] for name in sorted(by_name)))
        return self

    def as_soft_guides(self) -> dict[str, GridSoftGuide]:
        """Build immutable R2 inputs without changing the versioned projection."""
        return {
            guide.net_name: GridSoftGuide(
                grid_mm=self.grid_mm,
                allowed_track_nodes=frozenset(guide.allowed_track_nodes),
                allowed_track_transitions=frozenset(guide.allowed_track_transitions),
                allowed_via_cells=frozenset(guide.allowed_via_cells),
                off_guide_transition_cost_units=self.off_corridor_penalty_units,
            )
            for guide in self.net_guides
        }


def project_corridor_route_guide(
    guide: CorridorRouteGuide,
    graph: CorridorGraph,
    layout: BoardLayout,
    *,
    grid_mm: float,
) -> KiCadGridRouteGuide:
    """Map selected cells and resources to transition-precise soft grid guidance."""
    if not math.isfinite(grid_mm) or grid_mm <= 0:
        raise ValueError("grid_mm must be finite and positive")
    if guide.graph_fingerprint != graph.semantic_fingerprint():
        raise ValueError("corridor guide and graph fingerprints do not match")
    if guide.layout_geometry_fingerprint != graph.layout_geometry_fingerprint:
        raise ValueError("corridor guide layout fingerprint does not match the graph")
    columns = int(layout.width_mm / grid_mm) + 1
    rows = int(layout.height_mm / grid_mm) + 1
    cell_by_id = {cell.cell_id: cell for cell in graph.cells}
    portal_by_id = {portal.resource_id: portal for portal in graph.portals}
    via_by_id = {portal.resource_id: portal for portal in graph.via_portals}
    projected = tuple(
        _project_net_guide(
            net_guide,
            cell_by_id,
            portal_by_id,
            via_by_id,
            grid_mm,
            columns,
            rows,
        )
        for net_guide in guide.net_guides
    )
    return KiCadGridRouteGuide(
        source_guide_fingerprint=guide.semantic_fingerprint(),
        grid_mm=grid_mm,
        columns=columns,
        rows=rows,
        off_corridor_penalty_units=guide.off_corridor_penalty_units,
        net_guides=projected,
    )


def _project_net_guide(
    guide: CorridorNetGuide,
    cells: dict[str, CorridorCell],
    portals: dict[str, CorridorPortal],
    via_portals: dict[str, CorridorViaPortal],
    grid_mm: float,
    columns: int,
    rows: int,
) -> KiCadGridNetGuide:
    memberships: dict[GridNode, set[str]] = {}
    for cell_id in guide.preferred_cell_ids:
        cell = cells.get(cell_id)
        if cell is None:
            raise ValueError(f"projected guide references unknown cell {cell_id!r}")
        min_x, min_y, max_x, max_y = cell.bounds_mm
        min_ix = max(0, math.ceil(min_x / grid_mm - _EPSILON))
        max_ix = min(columns - 1, math.floor(max_x / grid_mm + _EPSILON))
        min_iy = max(0, math.ceil(min_y / grid_mm - _EPSILON))
        max_iy = min(rows - 1, math.floor(max_y / grid_mm + _EPSILON))
        for ix in range(min_ix, max_ix + 1):
            for iy in range(min_iy, max_iy + 1):
                memberships.setdefault((cell.layer, ix, iy), set()).add(cell_id)

    selected_cuts: set[frozenset[str]] = set()
    for resource_id in guide.preferred_portal_ids:
        channel_portal = portals.get(resource_id)
        if channel_portal is None:
            raise ValueError(f"projected guide references unknown portal {resource_id!r}")
        selected_cuts.add(frozenset((channel_portal.cell_low, channel_portal.cell_high)))

    nodes = frozenset(memberships)
    transitions: set[GridTrackTransition] = set()
    for start in sorted(nodes):
        for dx, dy in (
            (1, 0),
            (-1, 0),
            (0, 1),
            (0, -1),
            (1, 1),
            (1, -1),
            (-1, 1),
            (-1, -1),
        ):
            end = (start[0], start[1] + dx, start[2] + dy)
            if end not in nodes or end <= start:
                continue
            start_cells = memberships[start]
            end_cells = memberships[end]
            crossed_cell_pairs = {
                frozenset((start_cell, end_cell))
                for start_cell in start_cells
                for end_cell in end_cells
                if start_cell != end_cell
            }
            if not crossed_cell_pairs or any(
                cell_pair in selected_cuts for cell_pair in crossed_cell_pairs
            ):
                transitions.add((start, end))

    allowed_vias: set[tuple[int, int]] = set()
    for resource_id in guide.preferred_via_resource_ids:
        via_portal = via_portals.get(resource_id)
        if via_portal is None:
            raise ValueError(f"projected guide references unknown via portal {resource_id!r}")
        for x_mm, y_mm in via_portal.candidate_sites_mm:
            ix = round(x_mm / grid_mm)
            iy = round(y_mm / grid_mm)
            if (
                abs(x_mm / grid_mm - ix) > _EPSILON
                or abs(y_mm / grid_mm - iy) > _EPSILON
                or not (0 <= ix < columns and 0 <= iy < rows)
            ):
                continue
            if ("F.Cu", ix, iy) in nodes and ("B.Cu", ix, iy) in nodes:
                allowed_vias.add((ix, iy))

    return KiCadGridNetGuide(
        net_name=guide.net_name,
        allowed_track_nodes=tuple(nodes),
        allowed_track_transitions=tuple(transitions),
        allowed_via_cells=tuple(allowed_vias),
    )
