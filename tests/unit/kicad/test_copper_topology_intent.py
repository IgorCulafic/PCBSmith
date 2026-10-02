from __future__ import annotations

from pcbsmith.kicad.copper_topology_intent import build_copper_topology_intent
from pcbsmith.kicad.routing_benchmark_corpus import build_routing_benchmark_cases


def _contract(case_index: int) -> dict[str, object]:
    return build_routing_benchmark_cases()[case_index].record()


def test_multiterminal_power_net_uses_one_shared_tree() -> None:
    plan = build_copper_topology_intent(_contract(30)).record()
    regions = plan["regions"]
    paths = plan["paths"]

    assert isinstance(regions, list)
    assert isinstance(paths, list)
    vin_regions = [region for region in regions if region["net_name"] == "VIN"]
    assert len(vin_regions) == 1
    assert vin_regions[0]["kind"] == "shared_tree"
    vin_paths = [path for path in paths if path["net_name"] == "VIN"]
    assert len(vin_paths) > 1
    assert {path["region_id"] for path in vin_paths} == {vin_regions[0]["region_id"]}


def test_two_terminal_load_keeps_one_direct_corridor() -> None:
    plan = build_copper_topology_intent(_contract(30)).record()
    regions = plan["regions"]

    assert isinstance(regions, list)
    load_regions = [region for region in regions if str(region["net_name"]).startswith("LOAD")]
    assert load_regions
    assert all(region["kind"] == "manhattan_corridor" for region in load_regions)


def test_ground_nodes_receive_explicit_escape_intent() -> None:
    contract = _contract(30)
    plan = build_copper_topology_intent(contract).record()
    escapes = plan["escapes"]
    nets = contract["nets"]

    assert isinstance(escapes, list)
    assert isinstance(nets, list)
    ground = next(net for net in nets if isinstance(net, dict) and net["name"] == "GND")
    assert len(escapes) == len(ground["nodes"])
    assert all(escape["target_layer"] == "B.Cu" for escape in escapes)
    assert all(escape["strategy"] == "short_offset_through_via" for escape in escapes)
    assert all(escape["allow_via_in_pad_fallback"] is False for escape in escapes)


def test_diagnostic_via_in_pad_requires_explicit_opt_in() -> None:
    plan = build_copper_topology_intent(_contract(30), allow_diagnostic_via_in_pad=True).record()
    escapes = plan["escapes"]

    assert isinstance(escapes, list)
    assert all(escape["allow_via_in_pad_fallback"] is True for escape in escapes)


def test_region_priorities_are_unique() -> None:
    plan = build_copper_topology_intent(_contract(30)).record()
    regions = plan["regions"]

    assert isinstance(regions, list)
    priorities = [region["priority"] for region in regions]
    assert len(priorities) == len(set(priorities))


def test_four_layer_roles_map_to_internal_planes_without_changing_semantics() -> None:
    contract = _contract(30)
    board = contract["board"]
    assert isinstance(board, dict)
    board["layers"] = 4

    plan = build_copper_topology_intent(contract).record()
    stackup = plan["stackup"]
    escapes = plan["escapes"]

    assert isinstance(stackup, dict)
    assignments = stackup["current_role_assignments"]
    assert assignments["ground_reference"] == "In1.Cu"
    assert assignments["power_distribution"] == "In2.Cu"
    assert isinstance(escapes, list)
    assert all(escape["target_layer"] == "In1.Cu" for escape in escapes)
