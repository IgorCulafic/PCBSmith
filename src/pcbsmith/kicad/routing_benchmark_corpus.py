"""Deterministic two-layer routing benchmark corpus for Phase 17.

The cases are board-level routing benchmarks, not electrically qualified
products. They use real KiCad footprints and pad identities, retain explicit
trace-width intent, and serialize to ordinary KiCad board/project files.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pcbsmith.kicad import board as board_module
from pcbsmith.kicad.astar_router import route_board
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    render_board_from_layout,
)
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import load_footprint
from pcbsmith.prototypes.kicad_project import render_kicad_project_file

SIGNAL_WIDTH_MM = 0.25

_FOOTPRINTS = {
    "C": "Capacitor_SMD:C_0603_1608Metric",
    "J2": "TerminalBlock_Altech:Altech_AK100_1x02_P5.00mm",
    "J8": "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
    "J20": "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical",
    "Q": "Package_TO_SOT_SMD:SOT-23",
    "QFN16": "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.9x1.9mm",
    "R": "Resistor_SMD:R_0603_1608Metric",
    "SOIC8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "TQFP32": "Package_QFP:TQFP-32_7x7mm_P0.8mm",
    "TQFP48": "Package_QFP:TQFP-48_7x7mm_P0.5mm",
    "TSSOP14": "Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
    "TSSOP20": "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
}


@dataclass(frozen=True)
class BenchmarkPlacement:
    reference: str
    value: str
    footprint: str
    x_mm: float
    y_mm: float
    rotation_deg: float = 0.0

    def record(self) -> dict[str, object]:
        return {
            "reference": self.reference,
            "value": self.value,
            "footprint": self.footprint,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "rotation_deg": self.rotation_deg,
        }


@dataclass(frozen=True)
class BenchmarkNet:
    name: str
    nodes: tuple[tuple[str, str], ...]
    width_mm: float
    width_class: str

    def record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "nodes": [list(node) for node in self.nodes],
            "width_mm": self.width_mm,
            "width_class": self.width_class,
        }


@dataclass(frozen=True)
class RoutingBenchmarkCase:
    case_id: str
    title: str
    tier: int
    difficulty: str
    board_width_mm: float
    board_height_mm: float
    placements: tuple[BenchmarkPlacement, ...]
    nets: tuple[BenchmarkNet, ...]
    tags: tuple[str, ...]
    design_note: str

    @property
    def net_widths(self) -> dict[str, float]:
        return {net.name: net.width_mm for net in self.nets}

    def record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "tier": self.tier,
            "difficulty": self.difficulty,
            "board": {
                "layers": 2,
                "width_mm": self.board_width_mm,
                "height_mm": self.board_height_mm,
            },
            "placements": [item.record() for item in self.placements],
            "nets": [net.record() for net in self.nets],
            "tags": list(self.tags),
            "design_note": self.design_note,
            "qualification_boundary": (
                "Trace widths are frozen benchmark intents. They are not IPC-2152 "
                "ampacity claims and do not establish thermal or product safety."
            ),
        }


@dataclass(frozen=True)
class RoutingBlueprint:
    title: str
    package: str
    signal_count: int
    series_count: int = 0
    power_channels: int = 0
    power_width_mm: float = 0.5
    tags: tuple[str, ...] = ()


_TIER_BLUEPRINTS: tuple[tuple[RoutingBlueprint, ...], ...] = (
    (
        RoutingBlueprint("single transistor control", "SOIC8", 2, tags=("sparse",)),
        RoutingBlueprint("LED and button control", "SOIC8", 3, 1, tags=("human-interface",)),
        RoutingBlueprint("dual RC signal path", "SOIC8", 4, 2, tags=("passive-chain",)),
        RoutingBlueprint("I2C pull-up breakout", "SOIC8", 4, 4, tags=("shared-bus",)),
        RoutingBlueprint("SPI peripheral breakout", "SOIC8", 5, 2, tags=("serial-bus",)),
        RoutingBlueprint("six-line digital adapter", "SOIC8", 6, tags=("fanout",)),
        RoutingBlueprint("buffered sensor header", "TSSOP14", 7, 3, tags=("sensor",)),
        RoutingBlueprint("eight-line GPIO pod", "TSSOP14", 8, tags=("fanout",)),
    ),
    (
        RoutingBlueprint("SOIC-8 full breakout", "SOIC8", 6, 4, tags=("full-breakout",)),
        RoutingBlueprint("TSSOP-14 sparse fanout", "TSSOP14", 9, 3, tags=("fine-pitch",)),
        RoutingBlueprint("TSSOP-14 full fanout", "TSSOP14", 12, tags=("fine-pitch",)),
        RoutingBlueprint("TSSOP-20 sensor hub", "TSSOP20", 12, 4, tags=("sensor-hub",)),
        RoutingBlueprint("TSSOP-20 dual bus", "TSSOP20", 16, tags=("dual-bus",)),
        RoutingBlueprint("QFN-16 compact breakout", "QFN16", 12, 4, tags=("qfn",)),
        RoutingBlueprint("TQFP-32 sparse controller", "TQFP32", 16, tags=("qfp",)),
        RoutingBlueprint("twenty-line header adapter", "TQFP32", 20, 6, tags=("dense-header",)),
    ),
    (
        RoutingBlueprint("TQFP-32 radial fanout", "TQFP32", 24, tags=("radial-fanout",)),
        RoutingBlueprint(
            "TQFP-32 series-terminated bus", "TQFP32", 24, 12, tags=("terminated-bus",)
        ),
        RoutingBlueprint("TQFP-48 sparse fanout", "TQFP48", 24, tags=("qfp",)),
        RoutingBlueprint("TQFP-48 crossed connector banks", "TQFP48", 30, tags=("crossed-bus",)),
        RoutingBlueprint("TQFP-48 terminated fanout", "TQFP48", 32, 16, tags=("terminated-bus",)),
        RoutingBlueprint("dense mixed sensor hub", "TQFP48", 34, 8, tags=("mixed-signal",)),
        RoutingBlueprint("thirty-six-line logic pod", "TQFP48", 36, tags=("dense-header",)),
        RoutingBlueprint("full TQFP-48 routing field", "TQFP48", 40, 20, tags=("dense-fanout",)),
    ),
    (
        RoutingBlueprint("500 mA switched output", "TSSOP14", 6, 2, 1, 0.5, ("power",)),
        RoutingBlueprint("1 A dual switched output", "TSSOP14", 7, 2, 2, 0.8, ("power",)),
        RoutingBlueprint("1.5 A triple load controller", "TSSOP20", 10, 3, 3, 1.0, ("power",)),
        RoutingBlueprint("2 A dual fan controller", "TSSOP20", 12, 4, 2, 1.2, ("power", "fan")),
        RoutingBlueprint("2.5 A four-channel low-side bank", "TQFP32", 16, 4, 4, 1.5, ("power",)),
        RoutingBlueprint(
            "3 A protected distribution node", "TQFP32", 18, 6, 3, 1.8, ("power", "protection")
        ),
        RoutingBlueprint(
            "3 A mixed control and load board", "TQFP32", 20, 8, 4, 1.8, ("mixed-signal", "power")
        ),
        RoutingBlueprint(
            "4 A six-channel load bank", "TQFP48", 24, 8, 6, 2.0, ("power", "repeated-channel")
        ),
    ),
    (
        RoutingBlueprint(
            "dense controller with one power lane", "TQFP32", 24, 8, 1, 1.2, ("stress",)
        ),
        RoutingBlueprint(
            "crossed sixteen-bit bus with power",
            "TQFP32",
            26,
            12,
            2,
            1.2,
            ("stress", "crossed-bus"),
        ),
        RoutingBlueprint("QFN corridor escape", "QFN16", 14, 10, 2, 1.0, ("stress", "qfn")),
        RoutingBlueprint(
            "eight repeated level-shift channels",
            "TQFP48",
            30,
            16,
            4,
            1.5,
            ("stress", "repeated-channel"),
        ),
        RoutingBlueprint(
            "six-load mixed-domain controller", "TQFP48", 32, 12, 6, 1.8, ("stress", "power")
        ),
        RoutingBlueprint(
            "dual connector-bank crossover", "TQFP48", 36, 18, 4, 1.5, ("stress", "crossed-bus")
        ),
        RoutingBlueprint(
            "dense control and 4 A distribution", "TQFP48", 38, 20, 6, 2.0, ("stress", "power")
        ),
        RoutingBlueprint(
            "maximum two-layer mixed routing case",
            "TQFP48",
            40,
            24,
            8,
            2.0,
            ("stress", "limit-case"),
        ),
    ),
)


def build_routing_benchmark_cases() -> tuple[RoutingBenchmarkCase, ...]:
    cases: list[RoutingBenchmarkCase] = []
    case_number = 1
    for tier, blueprints in enumerate(_TIER_BLUEPRINTS, start=1):
        for variant, blueprint in enumerate(blueprints, start=1):
            cases.append(build_routing_benchmark_case(case_number, tier, variant, blueprint))
            case_number += 1
    return tuple(cases)


def build_routing_benchmark_case(
    case_number: int,
    tier: int,
    variant: int,
    blueprint: RoutingBlueprint,
    *,
    case_prefix: str = "RC",
    difficulty: str | None = None,
) -> RoutingBenchmarkCase:
    case_id = f"{case_prefix}{case_number:02d}"
    connector_capacity = 8 if blueprint.signal_count <= 8 else 20
    connector_count = (blueprint.signal_count + connector_capacity - 1) // connector_capacity
    width = 42.0 + tier * 9.0 + variant * 1.5 + blueprint.power_channels * 3.5
    base_height = 38.0 + tier * 6.0 + max(0, blueprint.signal_count - 12) * 0.45
    height = max(base_height, 20.0 + connector_count * 30.0)
    placements: list[BenchmarkPlacement] = []
    nets: list[BenchmarkNet] = []

    ic_footprint = _FOOTPRINTS[blueprint.package]
    all_ic_pads = tuple(
        sorted(
            {item.name for item in load_footprint(ic_footprint).spec.pads if item.name},
            key=int,
        )
    )
    max_ic_pad = all_ic_pads[-1]
    ic_signal_pads = tuple(pad for pad in all_ic_pads if pad not in {"1", max_ic_pad})
    if blueprint.signal_count > len(ic_signal_pads):
        raise ValueError(f"{case_id} requests more signal pins than {blueprint.package}")

    placements.append(
        BenchmarkPlacement("U1", blueprint.package, ic_footprint, width * 0.46, height * 0.48)
    )
    placements.append(BenchmarkPlacement("J1", "POWER", _FOOTPRINTS["J2"], 8.0, 8.0))
    placements.extend(
        (
            BenchmarkPlacement("C1", "100n", _FOOTPRINTS["C"], width * 0.41, height * 0.34),
            BenchmarkPlacement("C2", "1u", _FOOTPRINTS["C"], width * 0.51, height * 0.34),
        )
    )

    connector_footprint = _FOOTPRINTS["J8"] if connector_capacity == 8 else _FOOTPRINTS["J20"]
    connector_refs: list[str] = []
    for connector_index in range(connector_count):
        ref = f"J{connector_index + 2}"
        connector_refs.append(ref)
        connector_y = height / 2.0 if connector_count == 1 else 16.0 + connector_index * 32.0
        placements.append(
            BenchmarkPlacement(
                ref,
                f"SIGNALS-{connector_index + 1}",
                connector_footprint,
                width - 8.0,
                connector_y,
            )
        )

    series_references: list[str] = []
    columns = 6
    for index in range(blueprint.series_count):
        reference = f"R{index + 1}"
        series_references.append(reference)
        row, column = divmod(index, columns)
        placements.append(
            BenchmarkPlacement(
                reference,
                "33R",
                _FOOTPRINTS["R"],
                width * 0.58 + column * 3.0,
                7.0 + row * 3.0,
            )
        )

    output_references: list[str] = []
    for channel in range(blueprint.power_channels):
        q_ref = f"Q{channel + 1}"
        r_ref = f"RG{channel + 1}"
        out_ref = f"JOUT{channel + 1}"
        output_references.append(out_ref)
        x = 15.0 + channel * 11.5
        placements.append(BenchmarkPlacement(q_ref, "NMOS", _FOOTPRINTS["Q"], x, height - 20.0))
        placements.append(BenchmarkPlacement(r_ref, "100R", _FOOTPRINTS["R"], x, height - 25.0))
        placements.append(BenchmarkPlacement(out_ref, "LOAD", _FOOTPRINTS["J2"], x, height - 8.0))

    control_net_indices: list[int] = []
    for index in range(blueprint.signal_count):
        connector_index, connector_pin_index = divmod(index, connector_capacity)
        connector_node = (connector_refs[connector_index], str(connector_pin_index + 1))
        ic_node = ("U1", ic_signal_pads[index])
        if index < blueprint.series_count:
            resistor = series_references[index]
            nets.append(
                BenchmarkNet(
                    f"SIG{index + 1}_A",
                    (ic_node, (resistor, "1")),
                    SIGNAL_WIDTH_MM,
                    "signal",
                )
            )
            control_net_indices.append(len(nets) - 1)
            nets.append(
                BenchmarkNet(
                    f"SIG{index + 1}_B",
                    ((resistor, "2"), connector_node),
                    SIGNAL_WIDTH_MM,
                    "signal",
                )
            )
        else:
            nets.append(
                BenchmarkNet(
                    f"SIG{index + 1}",
                    (ic_node, connector_node),
                    SIGNAL_WIDTH_MM,
                    "signal",
                )
            )
            control_net_indices.append(len(nets) - 1)

    power_nodes: list[tuple[str, str]] = [("J1", "1"), ("U1", "1"), ("C1", "1"), ("C2", "1")]
    ground_nodes: list[tuple[str, str]] = [
        ("J1", "2"),
        ("U1", max_ic_pad),
        ("C1", "2"),
        ("C2", "2"),
    ]
    for channel in range(blueprint.power_channels):
        q_ref = f"Q{channel + 1}"
        r_ref = f"RG{channel + 1}"
        out_ref = output_references[channel]
        control_index = control_net_indices[channel % len(control_net_indices)]
        control_net = nets[control_index]
        nets[control_index] = BenchmarkNet(
            control_net.name,
            (*control_net.nodes, (r_ref, "1")),
            control_net.width_mm,
            control_net.width_class,
        )
        nets.append(
            BenchmarkNet(
                f"GATE{channel + 1}_LOCAL",
                ((r_ref, "2"), (q_ref, "1")),
                SIGNAL_WIDTH_MM,
                "gate",
            )
        )
        nets.append(
            BenchmarkNet(
                f"LOAD{channel + 1}",
                ((q_ref, "2"), (out_ref, "2")),
                blueprint.power_width_mm,
                "load",
            )
        )
        power_nodes.append((out_ref, "1"))
        ground_nodes.append((q_ref, "3"))

    nets.append(BenchmarkNet("VIN", tuple(power_nodes), blueprint.power_width_mm, "power"))
    nets.append(BenchmarkNet("GND", tuple(ground_nodes), blueprint.power_width_mm, "return"))

    return RoutingBenchmarkCase(
        case_id=case_id,
        title=blueprint.title,
        tier=tier,
        difficulty=difficulty
        or ("introductory", "moderate", "dense", "mixed-power", "stress")[tier - 1],
        board_width_mm=round(width, 2),
        board_height_mm=round(height, 2),
        placements=tuple(placements),
        nets=tuple(nets),
        tags=(f"tier-{tier}", "two-layer", *blueprint.tags),
        design_note=(
            f"Variant {variant} of tier {tier}; {blueprint.signal_count} signal paths, "
            f"{blueprint.series_count} series elements, and "
            f"{blueprint.power_channels} switched-power channels."
        ),
    )


def case_netlist(case: RoutingBenchmarkCase) -> BoardNetlist:
    components = tuple(
        BoardComponent(
            reference=item.reference,
            value=item.value,
            footprint=item.footprint,
            uuid_path=stable_kicad_uuid("routing-benchmark", case.case_id, item.reference),
        )
        for item in case.placements
    )
    return BoardNetlist(
        components=components,
        nets=tuple(BoardNet(net.name, net.nodes) for net in case.nets),
    )


def case_layout(case: RoutingBenchmarkCase) -> BoardLayout:
    netlist = case_netlist(case)
    by_reference = {component.reference: component for component in netlist.components}
    return BoardLayout(
        placements=tuple((by_reference[item.reference], item.x_mm) for item in case.placements),
        segments=(),
        vias=(),
        width_mm=case.board_width_mm,
        height_mm=case.board_height_mm,
        part_y_mm=tuple((item.reference, item.y_mm) for item in case.placements),
        part_rotation=tuple(
            (item.reference, item.rotation_deg) for item in case.placements if item.rotation_deg
        ),
    )


def register_benchmark_footprints() -> None:
    for footprint in sorted(set(_FOOTPRINTS.values())):
        board_module.FOOTPRINT_LIBRARY[footprint] = load_footprint(footprint).spec


def write_routing_benchmark_corpus(
    output_root: Path,
    *,
    route_native: bool = False,
    max_expansions: int = 150_000,
    max_expansions_per_net: int = 30_000,
) -> dict[str, object]:
    register_benchmark_footprints()
    output_root.mkdir(parents=True, exist_ok=True)
    cases = build_routing_benchmark_cases()
    _write_json(output_root / "case-matrix.json", [case.record() for case in cases])
    _write_json(
        output_root / "protocol.json",
        {
            "schema": "pcbsmith-routing-benchmark-corpus-v1",
            "case_count": len(cases),
            "layers": 2,
            "native_router": "pcbsmith.kicad.astar_router",
            "failure_policy": "retain every result; never repair a failed route by hand",
            "qualification_boundary": (
                "Board-level routing benchmarks only; no electrical, thermal, safety, "
                "manufacturing, or current-capacity qualification is claimed."
            ),
        },
    )

    summaries: list[dict[str, object]] = []
    for case in cases:
        case_dir = output_root / "boards" / f"{case.case_id}-{_slug(case.title)}"
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_json(case_dir / "case-contract.json", case.record())
        netlist = case_netlist(case)
        placement_layout = case_layout(case)
        project_name = f"{case.case_id}-{_slug(case.title)}"
        placement_board = case_dir / f"{project_name}-placement.kicad_pcb"
        placement_board.write_text(
            render_board_from_layout(netlist, placement_layout), encoding="utf-8"
        )
        (case_dir / f"{project_name}.kicad_pro").write_text(
            render_kicad_project_file(project_name), encoding="utf-8"
        )
        route_record: dict[str, object] = {
            "attempted": route_native,
            "engine": "pcbsmith.kicad.astar_router",
        }
        if route_native:
            result = route_board(
                placement_layout,
                netlist,
                net_widths=case.net_widths,
                default_width_mm=SIGNAL_WIDTH_MM,
                max_restarts=2,
                max_expansions=max_expansions,
                max_expansions_per_net=max_expansions_per_net,
                grid_mm=0.5,
            )
            routed_board = case_dir / "native" / f"{project_name}-routed.kicad_pcb"
            routed_board.parent.mkdir(parents=True, exist_ok=True)
            routed_board.write_text(
                render_board_from_layout(netlist, result.layout), encoding="utf-8"
            )
            route_record.update(
                {
                    "success": result.run_result.success,
                    "failed_nets": list(result.failed),
                    "unresolved_nets": list(result.run_result.unresolved_net_names),
                    "segment_count": len(result.layout.segments),
                    "via_count": len(result.layout.vias),
                    "restart_count": result.restarts,
                    "expansion_count": sum(
                        item.expansion_count for item in result.run_result.passes
                    ),
                    "routed_board": routed_board.relative_to(output_root).as_posix(),
                }
            )
            _write_json(case_dir / "native" / "route-evidence.json", route_record)
        summaries.append(
            {
                "case_id": case.case_id,
                "tier": case.tier,
                "component_count": len(case.placements),
                "net_count": len(case.nets),
                "maximum_width_mm": max(net.width_mm for net in case.nets),
                "native": route_record,
            }
        )

    native_success_count = 0
    for item in summaries:
        native = item["native"]
        if isinstance(native, dict) and native.get("success") is True:
            native_success_count += 1
    summary: dict[str, object] = {
        "schema": "pcbsmith-routing-benchmark-summary-v1",
        "case_count": len(cases),
        "tier_counts": {
            str(tier): sum(case.tier == tier for case in cases) for tier in range(1, 6)
        },
        "native_attempted": route_native,
        "native_success_count": native_success_count,
        "cases": summaries,
    }
    _write_json(output_root / "summary.json", summary)
    _write_manifest(output_root)
    return summary


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _slug(value: str) -> str:
    characters = "".join(character.lower() if character.isalnum() else " " for character in value)
    return "-".join(characters.split())


def _write_manifest(root: Path) -> None:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {"artifact-manifest.json", "freerouting-artifact-manifest.json"}:
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
        )
    _write_json(root / "artifact-manifest.json", {"files": files})


__all__ = [
    "BenchmarkNet",
    "BenchmarkPlacement",
    "RoutingBlueprint",
    "RoutingBenchmarkCase",
    "build_routing_benchmark_case",
    "build_routing_benchmark_cases",
    "case_layout",
    "case_netlist",
    "register_benchmark_footprints",
    "write_routing_benchmark_corpus",
]
