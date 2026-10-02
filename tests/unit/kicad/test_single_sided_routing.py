"""Single copper side must constrain search, not merely filter its output."""

from dataclasses import replace

import pytest
from tests.unit.kicad.test_routing_candidate_adapter import _fixture, _request

from pcbsmith.kicad.astar_router import GridRouter, RoutingError, route_board
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.routing_candidate_adapter import (
    native_routing_profile_fingerprint,
    route_native_candidate,
)
from pcbsmith.routing_ir import PartialCandidateStatus
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def single_profile():
    return DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "geometry": DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
                update={"copper_layer_count": 1}
            )
        }
    )


def test_front_route_has_no_vias_or_rear_segments():
    layout, netlist = _fixture()
    result = GridRouter(
        layout, netlist, net_name="/SIG", track_width_mm=0.4, profile=single_profile()
    ).route()
    assert result.segments
    assert not result.vias
    assert {s.layer for s in result.segments} == {"F.Cu"}


def test_front_barrier_cannot_escape_onto_absent_back_copper():
    layout, netlist = _fixture()
    wall = TrackSegment(net_name="/A", x1=15, y1=-1, x2=15, y2=13, width_mm=1, layer="F.Cu")
    layout = replace(layout, segments=(wall,))
    two = GridRouter(layout, netlist, net_name="/SIG", track_width_mm=0.4).route()
    assert two.vias and any(s.layer == "B.Cu" for s in two.segments)
    with pytest.raises(RoutingError, match="No route"):
        GridRouter(
            layout, netlist, net_name="/SIG", track_width_mm=0.4, profile=single_profile()
        ).route()


def test_back_only_smd_terminal_is_not_silently_omitted():
    layout, netlist = _fixture()
    layout = replace(layout, part_flip=("R2",))
    with pytest.raises(RoutingError, match="back-only pad"):
        GridRouter(layout, netlist, net_name="/SIG", track_width_mm=0.4, profile=single_profile())


def test_retained_back_copper_rejected_even_when_nets_skipped():
    layout, netlist = _fixture()
    rear = TrackSegment(net_name="/SIG", x1=7, y1=6, x2=23, y2=6, width_mm=0.4, layer="B.Cu")
    with pytest.raises(ValueError, match="retained vias or back-layer copper"):
        route_board(
            replace(layout, segments=(rear,)),
            netlist,
            profile=single_profile(),
            skip_nets=("/SIG",),
        )


def test_adapter_consumes_profile_bound_one_sided_request():
    layout, netlist = _fixture()
    profile = single_profile()
    request = _request(layout, netlist)
    request = request.model_copy(
        update={
            "allowed_layers": ("F.Cu",),
            "via_technologies": (),
            "inputs": request.inputs.model_copy(
                update={"rules_sha256": native_routing_profile_fingerprint(profile)}
            ),
        }
    )
    result = route_native_candidate(
        request=request, layout=layout, netlist=netlist, profile=profile
    )
    assert result.partial_status == PartialCandidateStatus.COMPLETE
    assert not result.via_deltas
    assert all(
        delta.after is not None and delta.after.layer == "F.Cu" for delta in result.segment_deltas
    )


def test_adapter_rejects_request_profile_layer_mismatch():
    layout, netlist = _fixture()
    request = _request(layout, netlist).model_copy(
        update={"allowed_layers": ("F.Cu",), "via_technologies": ()}
    )
    result = route_native_candidate(request=request, layout=layout, netlist=netlist)
    assert result.partial_status == PartialCandidateStatus.FAILED_NO_DELTA
    assert any("layers matching" in item.message for item in result.failures)


def test_plane_requires_exact_request_binding_and_valid_target():
    from pcbsmith.kicad.routing_candidate_adapter import NativePlanePour

    layout, netlist = _fixture()
    request = _request(layout, netlist)
    pour = NativePlanePour(net_name="/SIG")
    with pytest.raises(ValueError, match="not bound"):
        route_native_candidate(request=request, layout=layout, netlist=netlist, plane_pour=pour)
    request = request.model_copy(update={"additional_constraint_ids": (pour.constraint_id,)})
    result = route_native_candidate(
        request=request, layout=layout, netlist=netlist, plane_pour=pour
    )
    assert result.partial_status == PartialCandidateStatus.COMPLETE
    assert len(result.zone_deltas) == 1
    missing = route_native_candidate(request=request, layout=layout, netlist=netlist)
    assert missing.partial_status == PartialCandidateStatus.FAILED_NO_DELTA
    for invalid in (
        NativePlanePour(net_name="/missing"),
        NativePlanePour(net_name="/SIG", layer="In1.Cu"),
        NativePlanePour(net_name="/SIG", edge_inset_mm=7),
    ):
        with pytest.raises(ValueError):
            invalid.zone(layout, request)


def test_ordinary_request_binds_single_side_and_plane():
    from types import SimpleNamespace

    from tests.unit.kicad.test_routing_candidate_transaction import _snapshot

    from pcbsmith.kicad.routing_candidate_adapter import NativePlanePour
    from pcbsmith.production_routing import _request as ordinary_request

    layout, netlist = _fixture()
    profile = single_profile()
    snapshot, _ = _snapshot(layout, netlist, profile=profile)
    pour = NativePlanePour(net_name="/SIG")
    request = ordinary_request(
        snapshot,
        layout,
        netlist,
        profile,
        SimpleNamespace(
            saved_board_sha256=snapshot.identity.board_sha256, budget_profile_name="standard"
        ),
        plane_pour=pour,
    )
    assert request.allowed_layers == ("F.Cu",)
    assert not request.via_technologies
    assert request.additional_constraint_ids == (pour.constraint_id,)


def test_plane_connectivity_is_explicit_hashed_and_emits_no_redundant_trace():
    from pcbsmith.kicad.routing_candidate_adapter import NativePlanePour

    layout, netlist = _fixture()
    default = NativePlanePour(net_name="/SIG")
    plane = NativePlanePour(net_name="/SIG", connect_by_plane=True)
    assert "connect_by_plane" not in default.model_dump(mode="json")
    assert default.constraint_id != plane.constraint_id
    request = _request(layout, netlist).model_copy(
        update={"additional_constraint_ids": (plane.constraint_id,)}
    )
    result = route_native_candidate(
        request=request, layout=layout, netlist=netlist, plane_pour=plane
    )
    assert result.partial_status == PartialCandidateStatus.COMPLETE
    assert not result.segment_deltas
    assert len(result.zone_deltas) == 1
    assert result.zone_deltas[0].after.net_name == "/SIG"
    with pytest.raises(ValueError, match="not bound"):
        route_native_candidate(request=request, layout=layout, netlist=netlist, plane_pour=default)
