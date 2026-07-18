"""Exact projection of coarse corridor guidance onto the KiCad routing grid."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pcbsmith.corridor_guidance import CorridorNetGuide, CorridorRouteGuide
from pcbsmith.corridor_ir import (
    CorridorCell,
    CorridorGeometryVerification,
    CorridorGraph,
    CorridorPortal,
    CorridorViaPortal,
)
from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.corridor_guidance import project_corridor_route_guide


def _digest(character: str) -> str:
    return character * 64


def _cell(
    cell_id: str,
    layer: str,
    bounds_mm: tuple[float, float, float, float],
) -> CorridorCell:
    return CorridorCell(
        cell_id=cell_id,
        layer=layer,
        ix=0,
        iy=0,
        bounds_mm=bounds_mm,
    )


def _portal(resource_id: str, low: str, high: str) -> CorridorPortal:
    return CorridorPortal(
        resource_id=resource_id,
        layer="F.Cu",
        cell_low=low,
        cell_high=high,
        orientation="vertical_cut",
        guaranteed_span_units=1,
        possible_span_units=1,
        verification=CorridorGeometryVerification.EXACT,
    )


def _graph(
    *,
    cells: tuple[CorridorCell, ...],
    portals: tuple[CorridorPortal, ...] = (),
    via_portals: tuple[CorridorViaPortal, ...] = (),
    reverse: bool = False,
) -> CorridorGraph:
    if reverse:
        cells = tuple(reversed(cells))
        portals = tuple(reversed(portals))
        via_portals = tuple(reversed(via_portals))
    return CorridorGraph(
        profile_fingerprint=_digest("a"),
        layout_geometry_fingerprint=_digest("b"),
        coarse_grid_mm=1.0,
        capacity_quantum_mm=0.1,
        cells=cells,
        portals=portals,
        via_portals=via_portals,
    )


def _net_guide(
    net_name: str,
    *,
    cells: tuple[str, ...],
    portals: tuple[str, ...] = (),
    vias: tuple[str, ...] = (),
) -> CorridorNetGuide:
    return CorridorNetGuide(
        net_name=net_name,
        demand_id=f"demand:{net_name}",
        allocation_fingerprint=_digest("c"),
        preferred_cell_ids=cells,
        preferred_portal_ids=portals,
        preferred_via_resource_ids=vias,
    )


def _route_guide(
    graph: CorridorGraph,
    *net_guides: CorridorNetGuide,
) -> CorridorRouteGuide:
    return CorridorRouteGuide(
        plan_fingerprint=_digest("d"),
        graph_fingerprint=graph.semantic_fingerprint(),
        layout_geometry_fingerprint=graph.layout_geometry_fingerprint,
        off_corridor_penalty_units=123,
        net_guides=net_guides,
    )


def _layout(width_mm: float = 4.0, height_mm: float = 3.0) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=width_mm,
        height_mm=height_mm,
    )


def test_closed_bounds_include_edges_and_same_cell_cardinal_and_diagonal_moves() -> None:
    graph = _graph(cells=(_cell("front", "F.Cu", (0.0, 0.0, 1.0, 1.0)),))
    projected = project_corridor_route_guide(
        _route_guide(graph, _net_guide("/A", cells=("front",))),
        graph,
        _layout(),
        grid_mm=1.0,
    ).net_guides[0]

    assert projected.allowed_track_nodes == (
        ("F.Cu", 0, 0),
        ("F.Cu", 0, 1),
        ("F.Cu", 1, 0),
        ("F.Cu", 1, 1),
    )
    assert (("F.Cu", 0, 0), ("F.Cu", 1, 0)) in projected.allowed_track_transitions
    assert (("F.Cu", 0, 0), ("F.Cu", 1, 1)) in projected.allowed_track_transitions


def test_only_selected_portal_allows_crossing_between_adjacent_cell_memberships() -> None:
    cells = (
        _cell("a", "F.Cu", (0.0, 0.0, 1.49, 2.0)),
        _cell("b", "F.Cu", (1.51, 0.0, 2.49, 2.0)),
        _cell("c", "F.Cu", (2.51, 0.0, 3.49, 2.0)),
    )
    graph = _graph(
        cells=cells,
        portals=(_portal("portal:a-b", "a", "b"), _portal("portal:b-c", "b", "c")),
    )
    projected = project_corridor_route_guide(
        _route_guide(
            graph,
            _net_guide(
                "/A",
                cells=("a", "b", "c"),
                portals=("portal:a-b",),
            ),
        ),
        graph,
        _layout(),
        grid_mm=1.0,
    ).net_guides[0]

    transitions = set(projected.allowed_track_transitions)
    assert (("F.Cu", 1, 1), ("F.Cu", 2, 1)) in transitions
    assert (("F.Cu", 2, 1), ("F.Cu", 3, 1)) not in transitions


def test_selected_via_requires_exact_alignment_and_both_layer_memberships() -> None:
    front = _cell("front", "F.Cu", (0.0, 0.0, 2.0, 2.0))
    back = _cell("back", "B.Cu", (0.0, 0.0, 2.0, 2.0))
    via = CorridorViaPortal(
        resource_id="via:front-back",
        front_cell_id="front",
        back_cell_id="back",
        guaranteed_site_count=1,
        possible_site_count=3,
        candidate_sites_mm=((1.0, 1.0), (1.25, 1.0), (3.0, 1.0)),
        verification=CorridorGeometryVerification.EXACT,
    )
    graph = _graph(cells=(front, back), via_portals=(via,))
    projected = project_corridor_route_guide(
        _route_guide(
            graph,
            _net_guide(
                "/A",
                cells=("front", "back"),
                vias=("via:front-back",),
            ),
        ),
        graph,
        _layout(),
        grid_mm=1.0,
    ).net_guides[0]

    assert projected.allowed_via_cells == ((1, 1),)


def test_reversed_inputs_have_stable_projection_fingerprint_and_soft_guides() -> None:
    cells = (
        _cell("a", "F.Cu", (0.0, 0.0, 1.49, 2.0)),
        _cell("b", "F.Cu", (1.51, 0.0, 2.49, 2.0)),
    )
    portals = (_portal("portal:a-b", "a", "b"),)
    first_graph = _graph(cells=cells, portals=portals)
    reversed_graph = _graph(cells=cells, portals=portals, reverse=True)
    guide_a = _net_guide("/A", cells=("a", "b"), portals=("portal:a-b",))
    guide_b = _net_guide("/B", cells=("b", "a"), portals=("portal:a-b",))

    first = project_corridor_route_guide(
        _route_guide(first_graph, guide_a, guide_b),
        first_graph,
        _layout(),
        grid_mm=1.0,
    )
    reversed_projection = project_corridor_route_guide(
        _route_guide(reversed_graph, guide_b, guide_a),
        reversed_graph,
        _layout(),
        grid_mm=1.0,
    )

    assert first.semantic_fingerprint() == reversed_projection.semantic_fingerprint()
    assert first.as_soft_guides() == reversed_projection.as_soft_guides()


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda graph, guide: guide.model_copy(update={"graph_fingerprint": _digest("e")}),
            "graph fingerprints do not match",
        ),
        (
            lambda graph, guide: guide.model_copy(
                update={"layout_geometry_fingerprint": _digest("e")}
            ),
            "layout fingerprint does not match",
        ),
        (
            lambda graph, guide: _route_guide(
                graph,
                _net_guide("/A", cells=("missing",)),
            ),
            "unknown cell",
        ),
        (
            lambda graph, guide: _route_guide(
                graph,
                _net_guide("/A", cells=("front",), portals=("missing",)),
            ),
            "unknown portal",
        ),
        (
            lambda graph, guide: _route_guide(
                graph,
                _net_guide("/A", cells=("front",), vias=("missing",)),
            ),
            "unknown via portal",
        ),
    ),
)
def test_projection_rejects_mismatches_and_unknown_references(
    mutate: Callable[[CorridorGraph, CorridorRouteGuide], CorridorRouteGuide],
    message: str,
) -> None:
    graph = _graph(cells=(_cell("front", "F.Cu", (0.0, 0.0, 2.0, 2.0)),))
    guide = _route_guide(graph, _net_guide("/A", cells=("front",)))

    with pytest.raises(ValueError, match=message):
        project_corridor_route_guide(
            mutate(graph, guide),
            graph,
            _layout(),
            grid_mm=1.0,
        )
