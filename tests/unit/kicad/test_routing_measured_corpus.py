from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.golden.test_r2_negotiated_kicad import _fixture as compact_fixture
from tests.unit.kicad.test_negotiated_board_maze import (
    _route_negotiated as route_maze,
)
from tests.unit.kicad.test_negotiated_board_maze import (
    maze_board as _maze_board_fixture,
)

from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.negotiated_board import (
    ExactRouteCheckResult,
    route_board_negotiated,
)
from pcbsmith.kicad.routing_measured_corpus import (
    MeasuredNegotiatedRoutingCorpus,
    build_measured_negotiated_routing_case,
    build_measured_negotiated_routing_corpus,
)


def _compact_case():
    layout, netlist = compact_fixture()
    result = route_board_negotiated(
        layout,
        netlist,
        target_nets=("/SIG",),
        net_order=("/SIG",),
        grid_mm=0.5,
        default_width_mm=0.4,
        max_passes=2,
        max_stagnant_passes=1,
        max_expansions=20_000,
        max_expansions_per_net=20_000,
        exact_checker=lambda _layout, _netlist: ExactRouteCheckResult(
            accepted=True,
            checker_id="unit-compact-connectivity-v1",
        ),
    )
    return build_measured_negotiated_routing_case(
        case_id="compact-single-net",
        source_layout=layout,
        netlist=netlist,
        result=result,
    )


def test_r2_adversarial_and_compact_serialized_measured_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maze_board: tuple[BoardLayout, BoardNetlist] = (
        _maze_board_fixture.__wrapped__(monkeypatch)
    )
    layout, netlist = maze_board
    maze = build_measured_negotiated_routing_case(
        case_id="adversarial-order-insufficient-maze",
        source_layout=layout,
        netlist=netlist,
        result=route_maze(layout, netlist),
    )
    corpus = build_measured_negotiated_routing_corpus(
        (maze, _compact_case())
    )

    assert tuple(item.case_id for item in corpus.cases) == (
        "adversarial-order-insufficient-maze",
        "compact-single-net",
    )
    assert maze.expansion_count == 16_427
    assert maze.routed_length_mm == (("A", "16.0"), ("B", "22.0"))
    assert maze.routed_segment_count > 0
    assert "(kicad_pcb" in maze.serialized_board_text
    assert "does not establish routing superiority" in corpus.authorized_inference
    assert (
        MeasuredNegotiatedRoutingCorpus.model_validate_json(
            corpus.model_dump_json()
        )
        == corpus
    )


def test_routing_corpus_rejects_measured_and_serialized_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maze_board: tuple[BoardLayout, BoardNetlist] = (
        _maze_board_fixture.__wrapped__(monkeypatch)
    )
    layout, netlist = maze_board
    maze = build_measured_negotiated_routing_case(
        case_id="maze",
        source_layout=layout,
        netlist=netlist,
        result=route_maze(layout, netlist),
    )
    corpus = build_measured_negotiated_routing_corpus(
        (maze, _compact_case())
    )
    payload = corpus.model_dump(mode="json")
    payload["cases"][0]["expansion_count"] += 1

    with pytest.raises(ValidationError, match="expansion count"):
        MeasuredNegotiatedRoutingCorpus.model_validate(payload)
