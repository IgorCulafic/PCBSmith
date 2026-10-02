"""Frozen four-tier routing evaluation corpus for user-reviewable KiCad boards.

This corpus deliberately evaluates board placement, routing, width preservation,
KiCad read-back, DRC, and visual review.  It is not a substitute for electrical
design qualification or a schematic/firmware product test.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from pcbsmith.kicad.board import render_board_from_layout
from pcbsmith.kicad.routing_benchmark_corpus import (
    RoutingBenchmarkCase,
    RoutingBlueprint,
    build_routing_benchmark_case,
    case_layout,
    case_netlist,
    register_benchmark_footprints,
)
from pcbsmith.prototypes.kicad_project import render_kicad_project_file

TIER_LABELS = ("very_simple", "simple", "beginner", "medium")

_FOUR_TIER_BLUEPRINTS: tuple[tuple[RoutingBlueprint, ...], ...] = (
    (
        RoutingBlueprint("two-line sensor adapter", "SOIC8", 2, tags=("sensor", "sparse")),
        RoutingBlueprint("status LED controller", "SOIC8", 2, 1, tags=("indicator",)),
        RoutingBlueprint("button input conditioner", "SOIC8", 3, 1, tags=("human-interface",)),
        RoutingBlueprint("dual analog buffer", "SOIC8", 3, tags=("analog",)),
        RoutingBlueprint("I2C pull-up adapter", "SOIC8", 4, 2, tags=("i2c",)),
        RoutingBlueprint("three-wire serial adapter", "SOIC8", 4, 1, tags=("serial",)),
        RoutingBlueprint("dual RC monitor", "SOIC8", 4, 2, tags=("passive-chain",)),
        RoutingBlueprint("four-line GPIO adapter", "SOIC8", 4, tags=("gpio",)),
        RoutingBlueprint("five-line peripheral pod", "SOIC8", 5, 1, tags=("fanout",)),
        RoutingBlueprint("six-line logic adapter", "SOIC8", 6, 2, tags=("fanout",)),
    ),
    (
        RoutingBlueprint("full SOIC breakout", "SOIC8", 6, tags=("breakout",)),
        RoutingBlueprint("terminated SPI adapter", "SOIC8", 5, 3, tags=("spi",)),
        RoutingBlueprint("buffered I2C sensor hub", "TSSOP14", 6, 2, tags=("i2c", "sensor")),
        RoutingBlueprint("seven-line GPIO pod", "TSSOP14", 7, tags=("gpio",)),
        RoutingBlueprint("eight-line digital pod", "TSSOP14", 8, 2, tags=("fanout",)),
        RoutingBlueprint("small mixed sensor hub", "TSSOP14", 8, 3, tags=("mixed-signal",)),
        RoutingBlueprint("single switched indicator", "TSSOP14", 6, 2, 1, 0.5, ("power",)),
        RoutingBlueprint("protected low-current output", "TSSOP14", 7, 2, 1, 0.6, ("power",)),
        RoutingBlueprint("nine-line control adapter", "TSSOP14", 9, 3, tags=("fanout",)),
        RoutingBlueprint("ten-line peripheral hub", "TSSOP14", 10, 4, tags=("sensor-hub",)),
    ),
    (
        RoutingBlueprint("TSSOP sensor concentrator", "TSSOP20", 10, 3, tags=("sensor-hub",)),
        RoutingBlueprint("twelve-line logic pod", "TSSOP20", 12, tags=("fanout",)),
        RoutingBlueprint("terminated twelve-line bus", "TSSOP20", 12, 6, tags=("terminated-bus",)),
        RoutingBlueprint("dual serial bus bridge", "TSSOP20", 14, 4, tags=("dual-bus",)),
        RoutingBlueprint("single 800 mA load control", "TSSOP20", 10, 3, 1, 0.8, ("power",)),
        RoutingBlueprint("dual 800 mA load control", "TSSOP20", 10, 3, 2, 0.8, ("power",)),
        RoutingBlueprint("dual fan control", "TSSOP20", 12, 4, 2, 1.0, ("power", "fan")),
        RoutingBlueprint("sixteen-line controller", "TQFP32", 16, 4, tags=("qfp",)),
        RoutingBlueprint(
            "mixed control and one load", "TQFP32", 16, 5, 1, 1.0, ("mixed-signal", "power")
        ),
        RoutingBlueprint("eighteen-line header adapter", "TQFP32", 18, 6, tags=("dense-header",)),
    ),
    (
        RoutingBlueprint("twenty-line controller pod", "TQFP32", 20, 6, tags=("qfp",)),
        RoutingBlueprint("terminated twenty-line bus", "TQFP32", 20, 10, tags=("terminated-bus",)),
        RoutingBlueprint("dual 1 A output controller", "TQFP32", 16, 6, 2, 1.2, ("power",)),
        RoutingBlueprint("triple 1 A load controller", "TQFP32", 18, 6, 3, 1.2, ("power",)),
        RoutingBlueprint(
            "four-channel low-side bank", "TQFP32", 18, 6, 4, 1.5, ("power", "repeated-channel")
        ),
        RoutingBlueprint(
            "mixed sensor and load hub", "TQFP32", 20, 8, 2, 1.2, ("mixed-signal", "power")
        ),
        RoutingBlueprint("TQFP48 sparse controller", "TQFP48", 22, 6, tags=("qfp",)),
        RoutingBlueprint("TQFP48 terminated fanout", "TQFP48", 24, 10, tags=("terminated-bus",)),
        RoutingBlueprint(
            "three-load mixed controller", "TQFP48", 24, 8, 3, 1.5, ("mixed-signal", "power")
        ),
        RoutingBlueprint(
            "four-load medium controller", "TQFP48", 26, 10, 4, 1.5, ("power", "repeated-channel")
        ),
    ),
)


def build_real_test_cases() -> tuple[RoutingBenchmarkCase, ...]:
    cases: list[RoutingBenchmarkCase] = []
    case_number = 1
    for tier, blueprints in enumerate(_FOUR_TIER_BLUEPRINTS, start=1):
        difficulty = TIER_LABELS[tier - 1]
        for variant, blueprint in enumerate(blueprints, start=1):
            cases.append(
                build_routing_benchmark_case(
                    case_number,
                    tier,
                    variant,
                    blueprint,
                    case_prefix="RT",
                    difficulty=difficulty,
                )
            )
            case_number += 1
    return tuple(cases)


def write_real_test_corpus(output_root: Path) -> dict[str, object]:
    register_benchmark_footprints()
    output_root.mkdir(parents=True, exist_ok=True)
    cases = build_real_test_cases()
    _write_json(output_root / "case-matrix.json", [case.record() for case in cases])
    _write_json(
        output_root / "protocol.json",
        {
            "schema": "pcbsmith-four-tier-real-routing-test-v1",
            "case_count": 40,
            "tier_order": list(TIER_LABELS),
            "tier_counts": {label: 10 for label in TIER_LABELS},
            "layers": 2,
            "routing_engine": "freerouting-2.2.4-through-kicad-dsn-ses",
            "pass_gate": (
                "KiCad export, router, import, width read-back, and DRC must complete; "
                "all requested widths must be accepted; DRC violations and unconnected "
                "items must both be zero."
            ),
            "failure_policy": "retain every result; never repair or exclude a failed case",
            "scope": (
                "Placement/routing/width/read-back/DRC/visual-review evaluation using "
                "ordinary KiCad PCB and project files; no schematic or firmware is claimed."
            ),
            "qualification_boundary": (
                "A passing board is not electrically, thermally, mechanically, safety, "
                "DFM, assembly, or current-capacity qualified."
            ),
        },
    )

    records: list[dict[str, object]] = []
    for case in cases:
        started = time.perf_counter()
        slug = _slug(case.title)
        project_name = f"{case.case_id}-{slug}"
        case_dir = output_root / "boards" / project_name
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_json(case_dir / "case-contract.json", case.record())
        board = case_dir / f"{project_name}-placement.kicad_pcb"
        project = case_dir / f"{project_name}.kicad_pro"
        board.write_text(
            render_board_from_layout(case_netlist(case), case_layout(case)), encoding="utf-8"
        )
        project.write_text(render_kicad_project_file(project_name), encoding="utf-8")
        evidence = {
            "schema": "pcbsmith-real-test-generation-evidence-v1",
            "case_id": case.case_id,
            "tier": case.difficulty,
            "success": True,
            "seconds": time.perf_counter() - started,
            "component_count": len(case.placements),
            "net_count": len(case.nets),
            "maximum_width_mm": max(net.width_mm for net in case.nets),
            "placement_board": board.name,
            "placement_board_sha256": _sha256(board),
            "project_file": project.name,
            "project_file_sha256": _sha256(project),
        }
        _write_json(case_dir / "generation-evidence.json", evidence)
        records.append(evidence)

    summary: dict[str, object] = {
        "schema": "pcbsmith-four-tier-generation-summary-v1",
        "case_count": len(records),
        "success_count": sum(record["success"] is True for record in records),
        "tier_counts": dict(Counter(str(record["tier"]) for record in records)),
        "component_count_range": [
            min(len(case.placements) for case in cases),
            max(len(case.placements) for case in cases),
        ],
        "net_count_range": [
            min(len(case.nets) for case in cases),
            max(len(case.nets) for case in cases),
        ],
        "cases": records,
    }
    _write_json(output_root / "generation-summary.json", summary)
    _write_manifest(output_root, "generation-artifact-manifest.json")
    return summary


def _slug(value: str) -> str:
    characters = "".join(character.lower() if character.isalnum() else " " for character in value)
    return "-".join(characters.split())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_manifest(root: Path, name: str) -> None:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name.endswith("artifact-manifest.json"):
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    _write_json(root / name, {"files": files})


__all__ = ["TIER_LABELS", "build_real_test_cases", "write_real_test_corpus"]
