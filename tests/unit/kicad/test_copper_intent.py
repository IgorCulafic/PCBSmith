from __future__ import annotations

import json
from pathlib import Path

from tools.run_phase17_copper_region_pilot import (
    _drc_metrics,
    _next_attempt,
    _unconnected_signatures,
)

from pcbsmith.kicad.copper_intent import build_copper_intent
from pcbsmith.kicad.routing_benchmark_corpus import build_routing_benchmark_cases


def _contract(case_index: int) -> dict[str, object]:
    return build_routing_benchmark_cases()[case_index].record()


def test_two_layer_power_case_separates_logical_and_physical_roles() -> None:
    plan = build_copper_intent(_contract(30)).record()

    stackup = plan["stackup"]
    assert isinstance(stackup, dict)
    assignments = stackup["current_role_assignments"]
    assert assignments == {
        "ground_reference": "B.Cu",
        "power_distribution": "F.Cu",
        "primary_signal": "F.Cu",
        "secondary_signal": "B.Cu",
    }
    assert stackup["dedicated_plane_threshold"] == 4


def test_power_case_has_ground_plane_and_power_corridors() -> None:
    plan = build_copper_intent(_contract(30)).record()
    regions = plan["regions"]
    paths = plan["paths"]

    assert isinstance(regions, list)
    assert isinstance(paths, list)
    assert any(region["kind"] == "board_fill" and region["net_name"] == "GND" for region in regions)
    assert any(
        region["kind"] == "manhattan_corridor" and region["net_name"] == "VIN" for region in regions
    )
    assert any(str(region["net_name"]).startswith("LOAD") for region in regions)
    assert all(path["maximum_escape_length_mm"] == 3.0 for path in paths)
    priorities = [region["priority"] for region in regions]
    assert len(priorities) == len(set(priorities))


def test_four_layer_contract_reserves_dedicated_internal_roles() -> None:
    contract = _contract(30)
    board = contract["board"]
    assert isinstance(board, dict)
    board["layers"] = 4

    plan = build_copper_intent(contract).record()
    stackup = plan["stackup"]
    assert isinstance(stackup, dict)
    assignments = stackup["current_role_assignments"]
    assert isinstance(assignments, dict)
    assert assignments["ground_reference"] == "In1.Cu"
    assert assignments["power_distribution"] == "In2.Cu"


def test_next_pilot_attempt_is_append_only(tmp_path: Path) -> None:
    first = _next_attempt(tmp_path)
    (first / "evidence.json").write_text("{}\n", encoding="utf-8")

    second = _next_attempt(tmp_path)

    assert first.name == "attempt-01"
    assert second.name == "attempt-02"
    assert (first / "evidence.json").exists()


def test_drc_metrics_extracts_unconnected_net_names(tmp_path: Path) -> None:
    report = tmp_path / "drc.json"
    report.write_text(
        json.dumps(
            {
                "violations": [{"type": "clearance"}],
                "unconnected_items": [
                    {
                        "items": [
                            {"description": "Pad 1 [VIN] of C1 on F.Cu"},
                            {"description": "Track [GND] on B.Cu"},
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    violations, unconnected, nets, types = _drc_metrics(report)

    assert violations == 1
    assert unconnected == 1
    assert nets == {"VIN", "GND"}
    assert types == ("clearance",)


def test_unconnected_signatures_are_stable_uuid_pairs(tmp_path: Path) -> None:
    report = tmp_path / "drc.json"
    report.write_text(
        json.dumps(
            {
                "unconnected_items": [
                    {
                        "items": [
                            {"uuid": "uuid-b"},
                            {"uuid": "uuid-a"},
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _unconnected_signatures(report) == ("uuid-a|uuid-b",)
