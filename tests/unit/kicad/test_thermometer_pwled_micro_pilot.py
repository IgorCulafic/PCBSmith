from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

import pcbsmith.kicad.thermometer_pwled_micro_pilot as micro
from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.kicad.corridor_planner import build_corridor_graph
from pcbsmith.kicad.placement_routability import build_placement_probe
from pcbsmith.kicad.thermometer_pwled_micro_pilot import (
    CROP_ORIGIN_MM,
    CROP_SIZE_MM,
    MICRO_EXCLUDED_CLAIMS,
    MICRO_REFERENCES,
    ThermometerPwledMicroPilotInput,
    build_thermometer_pwled_micro_board,
    build_thermometer_pwled_micro_pilot_input,
    parse_exact_placement_footprint_source,
)
from pcbsmith.placement_ir import ComponentPose, PlacementProbePolicy
from pcbsmith.placement_pilot_authority import PlacementPilotAuthority


def test_real_r17_d17_pwled_crop_retains_absolute_production_truth() -> None:
    pilot = build_thermometer_pwled_micro_pilot_input()
    netlist, layout = build_thermometer_pwled_micro_board()

    component_truth = tuple(
        (component.reference, component.value, component.footprint)
        for component in netlist.components
    )
    assert component_truth == (
        ("D17", "RED-0805", "LED_SMD:LED_0805_2012Metric"),
        ("R17", "1k", "Resistor_SMD:R_0603_1608Metric"),
    )
    assert netlist.nets[0].name == "/PWLED"
    assert netlist.nets[0].nodes == (("D17", "2"), ("R17", "2"))
    assert tuple(
        (pose.reference, pose.x_mm, pose.y_mm, pose.rotation_deg, pose.side)
        for pose in pilot.source_absolute_poses
    ) == (
        ("D17", 31.0, 147.0, 0.0, "front"),
        ("R17", 35.0, 147.0, 0.0, "front"),
    )
    assert (layout.width_mm, layout.height_mm) == CROP_SIZE_MM
    assert layout.outline == ((0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0))
    assert tuple((component.reference, x) for component, x in layout.placements) == (
        ("D17", 3.0),
        ("R17", 7.0),
    )
    assert layout.part_y_mm == (("D17", 3.0), ("R17", 3.0))
    assert layout.part_rotation == ()
    assert layout.part_flip == ()
    assert pilot.authority.netlist() == netlist
    assert pilot.authority.layout() == layout
    assert pilot.full_thermometer_outline_fingerprint == (
        "538c253e6f596c889f3661bd5a4d4f81aa9f1cd3e041b603c76d8f310e72428b"
    )


def test_crop_translation_is_reversible_and_one_step_moves_remain_contained() -> None:
    pilot = build_thermometer_pwled_micro_pilot_input()
    local_x = {component.reference: x for component, x in pilot.authority.layout().placements}
    local_y = dict(pilot.authority.layout().part_y_mm)
    for pose in pilot.source_absolute_poses:
        assert local_x[pose.reference] + CROP_ORIGIN_MM[0] == pose.x_mm
        assert local_y[pose.reference] + CROP_ORIGIN_MM[1] == pose.y_mm

    r17_source = next(source for source in pilot.sources if source.reference == "R17")
    half_x, half_y = 1.48, 0.73
    for delta_x, delta_y in ((-0.5, 0.0), (0.5, 0.0), (0.0, -0.5), (0.0, 0.5)):
        x = local_x["R17"] + delta_x
        y = local_y["R17"] + delta_y
        assert 0.0 <= x - half_x < x + half_x <= CROP_SIZE_MM[0]
        assert 0.0 <= y - half_y < y + half_y <= CROP_SIZE_MM[1]
    assert r17_source.courtyard.polygons[0].outer == (
        (-1.48, -0.73),
        (1.48, -0.73),
        (1.48, 0.73),
        (-1.48, 0.73),
    )
    # Fixed D17's exact courtyard is also wholly inside the crop.
    assert 0.0 <= local_x["D17"] - 1.68 < local_x["D17"] + 1.68 <= CROP_SIZE_MM[0]
    assert 0.0 <= local_y["D17"] - 0.95 < local_y["D17"] + 0.95 <= CROP_SIZE_MM[1]


def test_source_bound_shapes_are_exact_and_pinned() -> None:
    pilot = build_thermometer_pwled_micro_pilot_input()
    sources = {source.reference: source for source in pilot.sources}
    assert sources["R17"].source_text_sha256 == (
        "7190ac4a00125b807e54129ef0d87d87f2a658eeb74d025a7028203419b09f23"
    )
    assert sources["D17"].source_text_sha256 == (
        "8806125556e590701b13b47a1725dff28fc47fca41a7905c7d78c8312d08cbbd"
    )
    assert sources["R17"].upstream_kicad10_source_sha256 == (
        "03fc7902b2661df01b4d828fdb6eab9eddf974e7130ed2b98892607387a50c4b"
    )
    assert sources["D17"].upstream_kicad10_source_sha256 == (
        "ce3a8266ee445b343374e2391b3b931a2bbc27f83d4f06af397cbea91df53178"
    )
    assert sources["R17"].body.polygons[0].outer == (
        (-0.8, -0.4125),
        (0.8, -0.4125),
        (0.8, 0.4125),
        (-0.8, 0.4125),
    )
    assert sources["D17"].body.polygons[0].outer == (
        (-1.0, -0.3),
        (-0.7, -0.6),
        (1.0, -0.6),
        (1.0, 0.6),
        (-1.0, 0.6),
    )
    catalog = {item.reference: item for item in pilot.authority.geometry_catalog.components}
    for reference, source in sources.items():
        assert catalog[reference].region("body").source_fingerprint == (
            source.region_source_fingerprint("body")
        )
        assert catalog[reference].region("courtyard").source_fingerprint == (
            source.region_source_fingerprint("courtyard")
        )


def test_input_authority_replays_deterministically_without_acceptance_claim() -> None:
    first = build_thermometer_pwled_micro_pilot_input()
    second = build_thermometer_pwled_micro_pilot_input()
    retained = ThermometerPwledMicroPilotInput.model_validate_json(first.model_dump_json())
    retained_authority = PlacementPilotAuthority.model_validate_json(
        first.authority.model_dump_json()
    )
    assert first == second == retained
    assert retained_authority == first.authority
    assert first.input_fingerprint == (
        "3473b6aaef7778e2f6aff53ab56a9be0b61cd49e5b368ac491a2f5d46af99827"
    )
    assert first.authority.move_policy.movable_references == ("R17",)
    assert first.authority.move_policy.translation_step_mm == 0.5
    assert first.authority.move_policy.maximum_translation_steps == 1
    assert first.authority.move_policy.rotatable_references == ()
    assert first.authority.move_policy.flippable_references == ()
    assert first.authority.target_net_widths_mm == (("/PWLED", 0.25),)
    assert first.authority.coarse_grid_mm == 1.0
    assert first.authority.detailed_grid_mm == 0.5
    assert first.authority.corridor_capacity_quantum_mm == 0.25
    assert first.authority.placement_budget.max_r3_geometry_cells_per_candidate == 256
    assert first.authority.placement_budget.max_r3_geometry_portals_per_candidate == 512
    assert first.authority.placement_budget.max_r3_expansions_per_candidate == 2_000
    assert first.authority.placement_budget.max_r2_expansions_per_candidate == 5_000
    assert first.authority.placement_budget.max_r2_expansions_per_net == 5_000
    assert first.authority.detail_selection_policy.allow_unguided_when_corridor_unavailable
    assert first.authority.exact_budget.max_exact_checks == 0
    assert first.excluded_claims == MICRO_EXCLUDED_CLAIMS
    assert "not_full_template_preservation" in first.excluded_claims
    assert "not_full_neighbor_preservation" in first.excluded_claims


def test_reviewed_move_maps_both_terminals_and_r3_plan_succeeds_without_routing() -> None:
    """R3 review evidence only: no R2 route or exact acceptance is produced here."""

    pilot = build_thermometer_pwled_micro_pilot_input()
    authority = pilot.authority
    probe = build_placement_probe(
        authority.layout(),
        (
            ComponentPose(
                reference="D17",
                x_mm=3.0,
                y_mm=3.0,
                rotation_deg=0.0,
                side="front",
            ),
            ComponentPose(
                reference="R17",
                x_mm=6.5,
                y_mm=3.0,
                rotation_deg=0.0,
                side="front",
            ),
        ),
        authority.target_net_names,
        known_net_names=tuple(net.name for net in authority.netlist().nets),
        policy=PlacementProbePolicy(
            required_references=MICRO_REFERENCES,
            allow_unchanged_non_target_references=False,
        ),
        budget=authority.placement_budget,
    )
    built = build_corridor_graph(
        probe.layout,
        authority.netlist(),
        target_nets=authority.target_net_names,
        net_widths=dict(authority.target_net_widths_mm),
        default_width_mm=authority.r2_policy.default_width_mm,
        profile=authority.profile,
        coarse_grid_mm=authority.coarse_grid_mm,
        capacity_quantum_mm=authority.corridor_capacity_quantum_mm,
        graphics_policy=authority.corridor_graphics_policy,
        budget=authority.corridor_graph_budget,
    )
    assert built.complete and built.planning_supported
    assert len(built.graph.cells) == 56
    assert len(built.graph.portals) == 82
    assert len(built.demands) == 1
    demand_policy = authority.corridor_demand_policies[0]
    demands = tuple(
        demand.model_copy(
            update={
                "allowed_layers": demand_policy.allowed_layers,
                "via_policy": demand_policy.via_policy,
            }
        )
        for demand in built.demands
    )
    assert all(terminal.candidate_cell_ids for terminal in demands[0].terminals)
    plan = negotiate_corridor_allocations(
        built.graph,
        demands,
        budget=authority.corridor_budget,
        cost_policy=authority.corridor_cost_policy,
    )
    assert plan.guidance_ready
    assert plan.failure_reason is None
    assert plan.resource_overuse == ()
    assert sum(item.expansion_count for item in plan.passes) == 202
    assert sum(item.expansion_count for item in plan.passes) <= (
        authority.corridor_budget.max_expansions
    )
    assert probe.layout.segments == () and probe.layout.vias == ()
    assert authority.exact_budget.max_exact_checks == 0


def test_source_text_hash_and_replayed_geometry_tamper_fail_closed() -> None:
    pilot = build_thermometer_pwled_micro_pilot_input()

    stale_text = pilot.model_dump(mode="python")
    stale_text["sources"][0]["source_text"] += "\n"
    with pytest.raises(ValidationError, match="source text hash is stale"):
        ThermometerPwledMicroPilotInput.model_validate(stale_text)

    unpinned = pilot.model_dump(mode="python")
    unpinned["sources"][0]["source_text"] += "\n"
    unpinned["sources"][0]["source_text_sha256"] = hashlib.sha256(
        unpinned["sources"][0]["source_text"].encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValidationError, match="not the pinned normalized KiCad 10 file"):
        ThermometerPwledMicroPilotInput.model_validate(unpinned)

    stale_shape = pilot.model_dump(mode="python")
    outer = list(stale_shape["sources"][0]["body"]["polygons"][0]["outer"])
    outer[0] = (-1.0, -0.2)
    stale_shape["sources"][0]["body"]["polygons"][0]["outer"] = tuple(outer)
    with pytest.raises(ValidationError, match="does not replay from source"):
        ThermometerPwledMicroPilotInput.model_validate(stale_shape)


def test_scope_and_crop_tamper_are_rejected() -> None:
    pilot = build_thermometer_pwled_micro_pilot_input()
    payload = pilot.model_dump(mode="python")
    payload["excluded_claims"] = tuple(
        claim for claim in payload["excluded_claims"] if claim != "not_full_template_preservation"
    )
    with pytest.raises(ValidationError, match="exclusions changed"):
        ThermometerPwledMicroPilotInput.model_validate(payload)

    payload = pilot.model_dump(mode="python")
    payload["crop_origin_mm"] = (11.0, 89.0)
    with pytest.raises(ValidationError, match="crop changed"):
        ThermometerPwledMicroPilotInput.model_validate(payload)


def test_parser_rejects_wrong_source_open_shape_multiple_shapes_and_unsupported_shape() -> None:
    wrong_name = """(footprint "Other" (layer "F.Cu")
      (fp_rect (start -1 -1) (end 1 1) (layer "F.Fab"))
      (fp_rect (start -2 -2) (end 2 2) (layer "F.CrtYd")))"""
    with pytest.raises(ValueError, match="name does not match"):
        parse_exact_placement_footprint_source(
            wrong_name, "Resistor_SMD:R_0603_1608Metric"
        )

    open_body = """(footprint "LED_0805_2012Metric" (layer "F.Cu")
      (fp_line (start -1 -1) (end 1 -1) (layer "F.Fab"))
      (fp_line (start 1 -1) (end 1 1) (layer "F.Fab"))
      (fp_line (start 1 1) (end -1 1) (layer "F.Fab"))
      (fp_rect (start -2 -2) (end 2 2) (layer "F.CrtYd")))"""
    with pytest.raises(ValueError, match="closed, unbranched"):
        parse_exact_placement_footprint_source(open_body, "LED_SMD:LED_0805_2012Metric")

    multiple = """(footprint "R_0603_1608Metric" (layer "F.Cu")
      (fp_rect (start -1 -1) (end 1 1) (layer "F.Fab"))
      (fp_rect (start -2 -2) (end 2 2) (layer "F.Fab"))
      (fp_rect (start -3 -3) (end 3 3) (layer "F.CrtYd")))"""
    with pytest.raises(ValueError, match="exactly one relevant closed shape"):
        parse_exact_placement_footprint_source(
            multiple, "Resistor_SMD:R_0603_1608Metric"
        )

    unsupported = """(footprint "R_0603_1608Metric" (layer "F.Cu")
      (fp_circle (center 0 0) (end 1 0) (layer "F.Fab"))
      (fp_rect (start -3 -3) (end 3 3) (layer "F.CrtYd")))"""
    with pytest.raises(ValueError, match="unsupported geometry"):
        parse_exact_placement_footprint_source(
            unsupported, "Resistor_SMD:R_0603_1608Metric"
        )


def test_builder_never_falls_back_to_ambient_footprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(micro, "VENDORED_DIR", tmp_path)
    with pytest.raises(ValueError, match="exact vendored footprint is missing"):
        build_thermometer_pwled_micro_pilot_input()
