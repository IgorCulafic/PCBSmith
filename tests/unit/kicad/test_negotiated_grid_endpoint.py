"""Certified same-layer endpoint-to-portal negotiated search."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pcbsmith.kicad.astar_router import RoutingError
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
)
from pcbsmith.kicad.negotiated_grid import (
    CertifiedEndpointConnection,
    CertifiedEndpointGraph,
    CertifiedEndpointTerminalSource,
    GridNode,
    certified_endpoint_graph_fingerprint,
    ordinary_claim_domain,
    route_certified_endpoint_to_portal,
)
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    OccupancyLedger,
    RoutingResourceKey,
    capsule_move_claims,
)
from pcbsmith.routing_ir import RoutingFailureReason

GRID_MM = 1.0
TRACK_WIDTH_MM = 0.4
RESISTOR = "Resistor_SMD:R_0603_1608Metric"
SOURCE_NODE: GridNode = ("F.Cu", 6, 6)
PORTAL_NODE: GridNode = ("F.Cu", 12, 6)


def _fixture() -> tuple[BoardLayout, BoardNetlist]:
    components = (
        BoardComponent("R1", "1k", RESISTOR, "r1"),
        BoardComponent("R2", "1k", RESISTOR, "r2"),
    )
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet("/SIG", (("R1", "2"), ("R2", "1"))),
            BoardNet("/A", (("R1", "1"),)),
            BoardNet("/B", (("R2", "2"),)),
        ),
    )
    layout = BoardLayout(
        placements=((components[0], 5.0), (components[1], 25.0)),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
        part_y_mm=(("R1", 6.0), ("R2", 6.0)),
    )
    return layout, netlist


def _source(**changes: object) -> CertifiedEndpointTerminalSource:
    source = CertifiedEndpointTerminalSource(
        component_ref="R1",
        pad_number="2",
        net_name="/SIG",
        physical_pad_source_id="pad:R1:1",
        source_node=SOURCE_NODE,
    )
    return replace(source, **changes)


def _graph(
    nodes: frozenset[GridNode],
    transitions: frozenset[tuple[GridNode, GridNode]],
    *,
    portal: GridNode = PORTAL_NODE,
) -> CertifiedEndpointGraph:
    fingerprint = certified_endpoint_graph_fingerprint(
        grid_mm=GRID_MM,
        layer="F.Cu",
        portal_node=portal,
        allowed_track_nodes=nodes,
        allowed_track_transitions=transitions,
    )
    return CertifiedEndpointGraph(
        grid_mm=GRID_MM,
        layer="F.Cu",
        portal_node=portal,
        allowed_track_nodes=nodes,
        allowed_track_transitions=transitions,
        graph_fingerprint=fingerprint,
    )


def _path_graph(path: tuple[GridNode, ...]) -> CertifiedEndpointGraph:
    return _graph(
        frozenset(path),
        frozenset(zip(path, path[1:], strict=False)),
        portal=path[-1],
    )


def _direct_graph() -> CertifiedEndpointGraph:
    return _path_graph(tuple(("F.Cu", x, 6) for x in range(6, 13)))


def _route(
    graph: CertifiedEndpointGraph,
    *,
    layout: BoardLayout | None = None,
    netlist: BoardNetlist | None = None,
    source: CertifiedEndpointTerminalSource | None = None,
    ledger: OccupancyLedger | None = None,
    history: dict[RoutingResourceKey, int] | None = None,
    hard_forbidden: frozenset[RoutingResourceKey] = frozenset(),
    max_expansions: int = 100,
) -> CertifiedEndpointConnection:
    fixture_layout, fixture_netlist = _fixture()
    return route_certified_endpoint_to_portal(
        layout or fixture_layout,
        netlist or fixture_netlist,
        source or _source(),
        graph,
        graph.portal_node,
        ledger or OccupancyLedger(),
        history or {},
        1,
        track_width_mm=TRACK_WIDTH_MM,
        hard_forbidden_resources=hard_forbidden,
        max_expansions=max_expansions,
    )


def test_raw_exact_path_claims_and_reversed_construction_are_pinned() -> None:
    graph = _direct_graph()
    layout, netlist = _fixture()
    ledger = OccupancyLedger()
    before = ledger.semantic_fingerprint()

    forward = _route(graph, layout=layout, netlist=netlist, ledger=ledger)
    reversed_netlist = replace(
        netlist,
        components=tuple(reversed(netlist.components)),
        nets=tuple(
            replace(net, nodes=tuple(reversed(net.nodes))) for net in reversed(netlist.nets)
        ),
    )
    reversed_layout = replace(
        layout,
        placements=tuple(reversed(layout.placements)),
        part_y_mm=tuple(reversed(layout.part_y_mm)),
    )
    reverse_graph = _graph(
        frozenset(reversed(tuple(graph.allowed_track_nodes))),
        frozenset(
            (second, first) for first, second in reversed(tuple(graph.allowed_track_transitions))
        ),
    )
    reverse = _route(reverse_graph, layout=reversed_layout, netlist=reversed_netlist)

    assert forward.path == tuple(("F.Cu", x, 6) for x in range(6, 13))
    assert len(forward.route.result.segments) == 6
    assert forward.route.result.vias == ()
    assert forward.route.claims.resources
    assert forward.expansion_count == 6
    assert ledger.semantic_fingerprint() == before
    assert forward.graph.graph_fingerprint == reverse.graph.graph_fingerprint
    assert forward.semantic_fingerprint() == reverse.semantic_fingerprint()
    assert (
        forward.semantic_fingerprint()
        == "849341d6cc38d515580c0e2049aaacfb7029edd04c78245f4fc8ba90f97d2aac"
    )
    assert (
        forward.search_input_fingerprint
        == "2d6dee6455537c4f0776311638aa9993fe736e7c3d7187a4af0483fcdb0d82dd"
    )
    assert (
        forward.terminal_source_fingerprint
        == "7e7441bd8c9682fba5a264cdaa2ab198628518c2bd569e776e5310cae1e15e7c"
    )
    assert (
        forward.graph_fingerprint
        == "749396b40d14bab511c2701fcaa80b7ef5e702c8aabf959a8438912d34a08d8b"
    )


def test_wrong_portal_net_and_layer_fail_before_search() -> None:
    graph = _direct_graph()
    layout, netlist = _fixture()
    with pytest.raises(ValueError, match="requested portal"):
        route_certified_endpoint_to_portal(
            layout,
            netlist,
            _source(),
            graph,
            ("F.Cu", 11, 6),
            OccupancyLedger(),
            {},
            0,
            max_expansions=100,
        )
    wrong_net_graph = _path_graph(tuple(("F.Cu", x, 6) for x in range(4, 13)))
    with pytest.raises(ValueError, match="wrong net"):
        _route(
            wrong_net_graph,
            source=_source(
                pad_number="1",
                physical_pad_source_id="pad:R1:0",
                source_node=("F.Cu", 4, 6),
            ),
        )
    with pytest.raises(ValueError, match="source node"):
        _route(graph, source=_source(source_node=("B.Cu", 6, 6)))
    with pytest.raises(ValueError, match="fingerprint is stale"):
        replace(graph, portal_node=("F.Cu", 11, 6))


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("component_ref", " R1"),
        ("pad_number", "2 "),
        ("net_name", " /SIG"),
        ("physical_pad_source_id", "pad:R1:1 "),
    ),
)
def test_terminal_identity_strings_must_be_canonical_and_stripped(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="non-empty and stripped"):
        _source(**{field_name: value})


def test_search_input_provenance_and_connection_coherence_are_live() -> None:
    graph = _direct_graph()
    baseline = _route(graph)
    resource = RoutingResourceKey("ordinary", "F.Cu", "cell", 20, 9)
    changed = _route(graph, history={resource: 1})

    assert baseline.search_input_fingerprint != changed.search_input_fingerprint
    payload = baseline.search_binding.canonical_payload_json
    for required in (
        "static_layout_fingerprint",
        "netlist_fingerprint",
        "ledger_fingerprint",
        "history_costs",
        "cost_policy",
        "profile",
        "clearance_groups",
        "claim_domains",
        "hard_forbidden_resource_ids",
        "max_expansions",
    ):
        assert f'"{required}"' in payload
    with pytest.raises(ValueError, match="search-input fingerprint is stale"):
        replace(baseline, search_input_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="unsupported guidance or prefix state"):
        replace(baseline, route=replace(baseline.route, guidance_cost_units=1))


def test_concave_allowed_graph_is_followed_without_smoothing() -> None:
    path: tuple[GridNode, ...] = (
        ("F.Cu", 6, 6),
        ("F.Cu", 7, 6),
        ("F.Cu", 7, 7),
        ("F.Cu", 8, 7),
        ("F.Cu", 8, 8),
        ("F.Cu", 9, 8),
        ("F.Cu", 10, 8),
        ("F.Cu", 10, 7),
        ("F.Cu", 11, 7),
        ("F.Cu", 11, 6),
        ("F.Cu", 12, 6),
    )
    result = _route(_path_graph(path))

    assert result.path == path
    assert len(result.route.result.segments) == len(path) - 1


def test_diagonal_cannot_cut_a_missing_certified_corner() -> None:
    source = SOURCE_NODE
    portal: GridNode = ("F.Cu", 7, 7)
    graph = _graph(
        frozenset((source, portal)),
        frozenset(((source, portal),)),
        portal=portal,
    )

    with pytest.raises(RoutingError) as caught:
        _route(graph)

    assert caught.value.reason is RoutingFailureReason.UNROUTABLE
    assert caught.value.expansion_count == 1


def test_static_foreign_copper_is_hard_even_inside_certified_graph() -> None:
    layout, netlist = _fixture()
    blocked = replace(
        layout,
        segments=(TrackSegment(9.0, 5.0, 9.0, 7.0, "F.Cu", "/BLOCK", 0.4),),
    )

    with pytest.raises(RoutingError) as caught:
        _route(_direct_graph(), layout=blocked, netlist=netlist)

    assert caught.value.reason is RoutingFailureReason.UNROUTABLE
    assert caught.value.expansion_count > 0


def test_hard_forbidden_resource_beats_cheaper_negotiated_path() -> None:
    direct = tuple(("F.Cu", x, 6) for x in range(6, 13))
    detour: tuple[GridNode, ...] = (
        ("F.Cu", 6, 6),
        ("F.Cu", 6, 7),
        ("F.Cu", 6, 8),
        ("F.Cu", 7, 8),
        ("F.Cu", 8, 8),
        ("F.Cu", 9, 8),
        ("F.Cu", 10, 8),
        ("F.Cu", 11, 8),
        ("F.Cu", 12, 8),
        ("F.Cu", 12, 7),
        ("F.Cu", 12, 6),
    )
    transitions = frozenset(
        (*zip(direct, direct[1:], strict=False), *zip(detour, detour[1:], strict=False))
    )
    graph = _graph(frozenset((*direct, *detour)), transitions)
    domain = ordinary_claim_domain(TRACK_WIDTH_MM)
    forbidden = RoutingResourceKey("ordinary", "F.Cu", "edge", 8, 6, 9, 6)
    detour_history: dict[RoutingResourceKey, int] = {}
    for first, second in zip(detour, detour[1:], strict=False):
        for resource in capsule_move_claims(
            domain.domain_id,
            "F.Cu",
            first[1:],
            second[1:],
            GRID_MM,
            domain.track_halo_radius_mm,
        ):
            detour_history[resource] = 100_000

    cheap = _route(graph, history=detour_history)
    forced = _route(
        graph,
        history=detour_history,
        hard_forbidden=frozenset((forbidden,)),
        max_expansions=1_000,
    )

    assert cheap.path == direct
    assert forced.path == detour
    assert forbidden in cheap.route.claims.resources
    assert forbidden not in forced.route.claims.resources
    assert forced.route.congestion_cost_units > cheap.route.congestion_cost_units


@pytest.mark.parametrize("limit", (0, 5))
def test_zero_and_one_less_expansion_budgets_report_exact_work(limit: int) -> None:
    ledger = OccupancyLedger(
        (
            NetResourceClaims(
                "/OTHER", frozenset((RoutingResourceKey("ordinary", "F.Cu", "cell", 20, 9),))
            ),
        )
    )
    before = ledger.semantic_fingerprint()

    with pytest.raises(RoutingError) as caught:
        _route(_direct_graph(), ledger=ledger, max_expansions=limit)

    assert caught.value.reason is RoutingFailureReason.EXPANSION_BUDGET
    assert caught.value.expansion_count == limit
    assert ledger.semantic_fingerprint() == before
    assert _route(_direct_graph(), max_expansions=6).expansion_count == 6


def test_duplicate_physical_pad_number_is_rejected_as_ambiguous() -> None:
    switch = BoardComponent(
        "SW1",
        "push",
        "Button_Switch_THT:SW_PUSH_6mm",
        "sw1",
    )
    netlist = BoardNetlist(
        components=(switch,),
        nets=(
            BoardNet("/SIG", (("SW1", "1"),)),
            BoardNet("/OTHER", (("SW1", "2"),)),
        ),
    )
    layout = BoardLayout(
        placements=((switch, 15.0),),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=30.0,
        part_y_mm=(("SW1", 15.0),),
    )
    graph = _path_graph(tuple(("F.Cu", x, 6) for x in range(6, 13)))

    with pytest.raises(ValueError, match="exactly one physical pad"):
        _route(
            graph,
            layout=layout,
            netlist=netlist,
            source=CertifiedEndpointTerminalSource(
                "SW1",
                "1",
                "/SIG",
                "pad:SW1:0",
                SOURCE_NODE,
            ),
        )
