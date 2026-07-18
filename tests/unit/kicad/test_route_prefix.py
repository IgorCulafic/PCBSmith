from __future__ import annotations

import pytest

from pcbsmith.kicad.board import TrackSegment, ViaSpec
from pcbsmith.kicad.negotiated_resources import (
    NetResourceClaims,
    RoutingResourceKey,
    union_net_resource_claims,
)
from pcbsmith.kicad.route_prefix import GridRoutePrefix


def _segment(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    layer: str,
    net_name: str = "N",
) -> TrackSegment:
    return TrackSegment(*start, *end, layer, net_name, 0.2)


def _two_layer_prefix(*, reverse: bool = False) -> GridRoutePrefix:
    front = _segment((0.0, 0.0), (1.0, 0.0), layer="F.Cu")
    back = _segment((1.0, 0.0), (2.0, 0.0), layer="B.Cu")
    segments = (back, front, front) if reverse else (front, back)
    anchors = (("pad-b", ("F.Cu", 0, 0)), ("pad-a", ("F.Cu", 0, 0)))
    if reverse:
        anchors = tuple(reversed(anchors))
    return GridRoutePrefix(
        alternative_id="escape-a",
        net_name="N",
        grid_mm=1.0,
        exit_node=("B.Cu", 2, 0),
        covered_pad_anchors=anchors,
        segments=segments,
        vias=(ViaSpec(1.0, 0.0, "N", 0.8, 0.4),),
    )


def test_prefix_is_connected_from_every_anchor_to_exact_exit_across_via() -> None:
    prefix = _two_layer_prefix()

    assert prefix.exit_node == ("B.Cu", 2, 0)
    assert tuple(source_id for source_id, _node in prefix.covered_pad_anchors) == (
        "pad-a",
        "pad-b",
    )
    assert len(prefix.segments) == 2


def test_prefix_rejects_disconnected_geometry_and_missing_layer_change_via() -> None:
    with pytest.raises(ValueError, match="connected"):
        GridRoutePrefix(
            alternative_id="escape-a",
            net_name="N",
            grid_mm=1.0,
            exit_node=("B.Cu", 2, 0),
            covered_pad_anchors=(("pad-a", ("F.Cu", 0, 0)),),
            segments=(
                _segment((0.0, 0.0), (1.0, 0.0), layer="F.Cu"),
                _segment((1.0, 0.0), (2.0, 0.0), layer="B.Cu"),
            ),
        )


def test_prefix_rejects_foreign_copper_owners() -> None:
    with pytest.raises(ValueError, match="segment net ownership"):
        GridRoutePrefix(
            alternative_id="escape-a",
            net_name="N",
            grid_mm=1.0,
            exit_node=("F.Cu", 1, 0),
            covered_pad_anchors=(("pad-a", ("F.Cu", 0, 0)),),
            segments=(_segment((0.0, 0.0), (1.0, 0.0), layer="F.Cu", net_name="X"),),
        )

    with pytest.raises(ValueError, match="via net ownership"):
        GridRoutePrefix(
            alternative_id="escape-a",
            net_name="N",
            grid_mm=1.0,
            exit_node=("B.Cu", 1, 0),
            covered_pad_anchors=(("pad-a", ("F.Cu", 0, 0)),),
            segments=(_segment((0.0, 0.0), (1.0, 0.0), layer="F.Cu"),),
            vias=(ViaSpec(1.0, 0.0, "X", 0.8, 0.4),),
        )


def test_prefix_requires_exact_grid_geometry_and_supported_exit_layer() -> None:
    with pytest.raises(ValueError, match="exactly on"):
        GridRoutePrefix(
            alternative_id="escape-a",
            net_name="N",
            grid_mm=1.0,
            exit_node=("F.Cu", 1, 0),
            covered_pad_anchors=(("pad-a", ("F.Cu", 0, 0)),),
            segments=(_segment((0.0, 0.0), (1.1, 0.0), layer="F.Cu"),),
        )

    with pytest.raises(ValueError, match="via x coordinate"):
        GridRoutePrefix(
            alternative_id="escape-a",
            net_name="N",
            grid_mm=1.0,
            exit_node=("B.Cu", 1, 0),
            covered_pad_anchors=(("pad-a", ("F.Cu", 0, 0)),),
            segments=(_segment((0.0, 0.0), (1.0, 0.0), layer="F.Cu"),),
            vias=(ViaSpec(1.1, 0.0, "N", 0.8, 0.4),),
        )

    with pytest.raises(ValueError, match="exit_node"):
        GridRoutePrefix(
            alternative_id="escape-a",
            net_name="N",
            grid_mm=1.0,
            exit_node=("In1.Cu", 1, 0),
            covered_pad_anchors=(("pad-a", ("F.Cu", 0, 0)),),
            segments=(_segment((0.0, 0.0), (1.0, 0.0), layer="F.Cu"),),
        )


def test_prefix_fingerprint_and_canonical_geometry_ignore_input_order_and_duplicates() -> None:
    forward = _two_layer_prefix()
    reversed_input = _two_layer_prefix(reverse=True)

    assert forward == reversed_input
    assert forward.semantic_fingerprint() == reversed_input.semantic_fingerprint()
    assert len(forward.semantic_fingerprint()) == 64


def test_same_owner_claim_union_is_deterministic_and_deduplicates_resources() -> None:
    first = RoutingResourceKey("ordinary", "F.Cu", "cell", 0, 0)
    second = RoutingResourceKey("ordinary", "B.Cu", "cell", 1, 0)

    forward = union_net_resource_claims(
        "N",
        NetResourceClaims("N", frozenset((first, second))),
        NetResourceClaims("N", frozenset((first,))),
    )
    reverse = union_net_resource_claims(
        "N",
        NetResourceClaims("N", frozenset((first,))),
        NetResourceClaims("N", frozenset((second, first))),
    )

    assert forward == reverse == NetResourceClaims("N", frozenset((first, second)))


def test_same_owner_claim_union_rejects_owner_mismatch() -> None:
    resource = RoutingResourceKey("ordinary", "F.Cu", "cell", 0, 0)

    with pytest.raises(ValueError, match="does not match"):
        union_net_resource_claims(
            "N",
            NetResourceClaims("N", frozenset((resource,))),
            NetResourceClaims("X", frozenset((resource,))),
        )
