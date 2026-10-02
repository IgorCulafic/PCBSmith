from __future__ import annotations

from dataclasses import replace

from pcbsmith.kicad.routing_benchmark_corpus import (
    case_layout,
    case_netlist,
    register_benchmark_footprints,
)
from pcbsmith.kicad.routing_real_test_corpus import build_real_test_cases
from pcbsmith.kicad.two_layer_topology_placement import (
    build_two_layer_critical_preroutes,
    build_two_layer_series_escape_preroutes,
    propose_two_layer_topology_placement,
)

REPRESENTATIVE_CASES = {
    "RT01",
    "RT10",
    "RT17",
    "RT24",
    "RT31",
    "RT35",
    "RT37",
    "RT40",
}


def _cases():
    return tuple(case for case in build_real_test_cases() if case.case_id in REPRESENTATIVE_CASES)


def test_two_layer_proposals_are_deterministic_and_preserve_inventory() -> None:
    for case in _cases():
        first = propose_two_layer_topology_placement(case)
        second = propose_two_layer_topology_placement(case)

        assert first == second
        assert set(first.poses) == {placement.reference for placement in case.placements}
        assert first.evidence.layer_count == 2
        assert first.evidence.four_layer_escalation_allowed is False
        assert first.evidence.reference_net == "GND"
        assert first.evidence.reference_layer == "B.Cu"
        assert first.ground_zone == (
            "GND",
            "B.Cu",
            (0.75, 0.75, case.board_width_mm - 0.75, case.board_height_mm - 0.75),
        )


def test_representative_proposals_improve_topology_metrics_before_r5() -> None:
    for case in _cases():
        evidence = propose_two_layer_topology_placement(case).evidence

        assert max(evidence.proposed_decoupling_loop_span_mm) < 9.0
        assert all(
            proposed < original
            for original, proposed in zip(
                evidence.initial_decoupling_loop_span_mm,
                evidence.proposed_decoupling_loop_span_mm,
                strict=True,
            )
        )
        if evidence.initial_mean_series_source_distance_mm:
            assert evidence.proposed_mean_series_source_distance_mm < 7.0
            assert (
                evidence.proposed_mean_series_source_distance_mm
                < evidence.initial_mean_series_source_distance_mm
            )
        if evidence.initial_mean_gate_distance_mm:
            assert evidence.proposed_mean_gate_distance_mm < 2.1
            assert evidence.proposed_mean_gate_distance_mm < evidence.initial_mean_gate_distance_mm


def test_dense_tqfp48_proposals_use_rotation_and_staggered_series_escapes() -> None:
    cases = {case.case_id: case for case in _cases()}
    for case_id in ("RT37", "RT40"):
        proposal = propose_two_layer_topology_placement(cases[case_id])
        assert proposal.evidence.selected_u1_rotation_deg == 90.0
        resistor_poses = tuple(
            pose
            for reference, pose in proposal.poses.items()
            if reference.startswith("R") and reference[1:].isdigit()
        )
        assert len({(round(x, 3), round(y, 3)) for x, y, _rotation in resistor_poses}) == len(
            resistor_poses
        )


def test_critical_preroutes_are_bounded_neckdowns_with_home_drillable_ground_vias() -> None:
    for case in _cases():
        proposal = propose_two_layer_topology_placement(case)
        segments, vias = build_two_layer_critical_preroutes(case, proposal)

        u1 = next(item for item in case.placements if item.reference == "U1")
        assert len(segments) == 5
        assert len(vias) == 3
        assert {segment.net_name for segment in segments} == {"VIN", "GND"}
        power_widths = {
            segment.width_mm for segment in segments if segment.net_name in {"VIN", "GND"}
        }
        assert len(power_widths) == 1
        assert 0.30 <= next(iter(power_widths)) <= 0.50
        if "TQFP-48" in u1.footprint:
            assert power_widths == {0.30}
        assert {via.net_name for via in vias} == {"GND"}
        assert {via.size_mm for via in vias} == {1.40}
        assert {via.drill_mm for via in vias} == {0.60}
        assert (segments, vias) == build_two_layer_critical_preroutes(case, proposal)


def _repaired_case(case):
    proposal = propose_two_layer_topology_placement(case)
    repaired = replace(
        case,
        placements=tuple(
            replace(
                placement,
                x_mm=proposal.poses[placement.reference][0],
                y_mm=proposal.poses[placement.reference][1],
                rotation_deg=proposal.poses[placement.reference][2],
            )
            for placement in case.placements
        ),
    )
    segments, vias = build_two_layer_critical_preroutes(repaired, proposal)
    layout = replace(
        case_layout(repaired),
        segments=segments,
        vias=vias,
        zones=(proposal.ground_zone,),
    )
    return repaired, layout


def test_dense_two_layer_series_escapes_are_front_only_and_deterministic() -> None:
    register_benchmark_footprints()
    cases = {case.case_id: case for case in _cases()}
    for case_id in ("RT37", "RT40"):
        repaired, layout = _repaired_case(cases[case_id])
        netlist = case_netlist(repaired)

        required_net = "SIG6_A" if case_id == "RT37" else "SIG7_A"
        targets = frozenset({required_net})
        first_routes, first_evidence = build_two_layer_series_escape_preroutes(
            repaired, layout, netlist, target_net_names=targets
        )
        second_routes, second_evidence = build_two_layer_series_escape_preroutes(
            repaired, layout, netlist, target_net_names=targets
        )

        assert (first_routes, first_evidence) == (second_routes, second_evidence)
        assert first_evidence.requested_count == 1
        assert first_evidence.accepted_count == 1
        assert first_evidence.rejected_count == 0
        assert first_evidence.attempts[0].net_name == required_net
        assert first_evidence.attempts[0].status == "accepted"
        assert first_routes
        assert {segment.layer for segment in first_routes} == {"F.Cu"}
        accepted = tuple(
            attempt for attempt in first_evidence.attempts if attempt.status == "accepted"
        )
        assert {attempt.via_count for attempt in accepted} == {0}
        assert max(attempt.route_length_mm for attempt in accepted) <= 8.1
        assert {attempt.track_width_mm for attempt in first_evidence.attempts} == {0.20}
        assert {attempt.grid_mm for attempt in first_evidence.attempts} == {0.05}
