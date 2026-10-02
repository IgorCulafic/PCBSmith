"""Measure placement and routing quality for the frozen Phase 17 corpus.

The strict result answers whether a board completed DRC/connectivity.  This
audit deliberately asks a different question: did the placer give the router
an electrically sensible problem?  Metrics are derived from the frozen case
matrix, real footprint pad geometry, and the final routed KiCad boards.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

from pcbsmith.kicad.library import load_footprint, rotate_offset

SEGMENT_RE = re.compile(
    r"\(segment\s+\(start\s+([-0-9.]+)\s+([-0-9.]+)\)\s+"
    r"\(end\s+([-0-9.]+)\s+([-0-9.]+)\)\s+"
    r"\(width\s+([-0-9.]+)\)\s+\(layer\s+\"([^\"]+)\"\)\s+"
    r"\(net\s+\"([^\"]+)\"\)",
    re.MULTILINE,
)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def placement_map(case: dict[str, object]) -> dict[str, dict[str, object]]:
    return {item["reference"]: item for item in case["placements"]}


def pad_position(
    placements: dict[str, dict[str, object]], reference: str, pad_name: str
) -> tuple[float, float]:
    placed = placements[reference]
    footprint = load_footprint(str(placed["footprint"])).spec
    pad = footprint.pads_named(pad_name)[0]
    dx, dy = rotate_offset(pad.x_mm, pad.y_mm, float(placed["rotation_deg"]))
    return float(placed["x_mm"]) + dx, float(placed["y_mm"]) + dy


def occupied_bbox(case: dict[str, object]) -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []
    for placed in case["placements"]:
        spec = load_footprint(str(placed["footprint"])).spec
        rotation = float(placed["rotation_deg"])
        for x in (spec.x_min, spec.x_max):
            for y in (spec.y_min, spec.y_max):
                dx, dy = rotate_offset(x, y, rotation)
                points.append((float(placed["x_mm"]) + dx, float(placed["y_mm"]) + dy))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def find_final_board(root: Path, result: dict[str, object]) -> Path:
    return root / str(result["routed_board"])


def route_metrics(board_path: Path) -> dict[str, object]:
    text = board_path.read_text(encoding="utf-8")
    layer_lengths: dict[str, float] = defaultdict(float)
    net_lengths: dict[str, float] = defaultdict(float)
    segment_count = 0
    for match in SEGMENT_RE.finditer(text):
        x1, y1, x2, y2 = map(float, match.group(1, 2, 3, 4))
        length = math.hypot(x2 - x1, y2 - y1)
        layer_lengths[match.group(6)] += length
        net_lengths[match.group(7)] += length
        segment_count += 1
    total = sum(layer_lengths.values())
    return {
        "segment_count_parsed": segment_count,
        "route_length_mm": round(total, 3),
        "front_route_length_mm": round(layer_lengths.get("F.Cu", 0.0), 3),
        "back_route_length_mm": round(layer_lengths.get("B.Cu", 0.0), 3),
        "power_route_length_mm": round(net_lengths.get("VIN", 0.0), 3),
        "return_route_length_mm": round(net_lengths.get("GND", 0.0), 3),
        "zone_count": len(re.findall(r"^\s*\(zone\s*$", text, re.MULTILINE)),
        "via_count_parsed": len(re.findall(r"^\s*\(via\s*$", text, re.MULTILINE)),
    }


def analyze_case(
    case: dict[str, object], result: dict[str, object], root: Path
) -> dict[str, object]:
    placements = placement_map(case)
    nets = {net["name"]: net for net in case["nets"]}
    placements["U1"]
    u1_ground_pad = next(pad for ref, pad in nets["GND"]["nodes"] if ref == "U1")

    decoupling_loops: list[float] = []
    for ref in ("C1", "C2"):
        decoupling_loops.append(
            distance(pad_position(placements, "U1", "1"), pad_position(placements, ref, "1"))
            + distance(
                pad_position(placements, "U1", str(u1_ground_pad)),
                pad_position(placements, ref, "2"),
            )
        )

    series_source_distances: list[float] = []
    series_path_excess: list[float] = []
    net_by_node: dict[tuple[str, str], dict[str, object]] = {}
    for net in case["nets"]:
        for node in net["nodes"]:
            net_by_node[tuple(node)] = net
    for ref in sorted(
        (ref for ref in placements if re.fullmatch(r"R\d+", ref)), key=lambda x: int(x[1:])
    ):
        input_net = net_by_node[(ref, "1")]
        u1_node = next(tuple(node) for node in input_net["nodes"] if node[0] == "U1")
        output_net = net_by_node[(ref, "2")]
        connector_node = next(
            tuple(node) for node in output_net["nodes"] if node[0].startswith("J")
        )
        source = pad_position(placements, *u1_node)
        r1 = pad_position(placements, ref, "1")
        r2 = pad_position(placements, ref, "2")
        sink = pad_position(placements, *connector_node)
        series_source_distances.append(distance(source, r1))
        direct = max(distance(source, sink), 1e-9)
        series_path_excess.append((distance(source, r1) + distance(r2, sink)) / direct)

    gate_distances: list[float] = []
    load_distances: list[float] = []
    for ref in sorted(
        (ref for ref in placements if ref.startswith("RG")), key=lambda x: int(x[2:])
    ):
        channel = ref[2:]
        gate_distances.append(
            distance(
                pad_position(placements, ref, "2"), pad_position(placements, f"Q{channel}", "1")
            )
        )
        load_distances.append(
            distance(
                pad_position(placements, f"Q{channel}", "2"),
                pad_position(placements, f"JOUT{channel}", "2"),
            )
        )

    x0, y0, x1, y1 = occupied_bbox(case)
    board_width = float(case["board"]["width_mm"])
    board_height = float(case["board"]["height_mm"])
    bbox_utilization = ((x1 - x0) * (y1 - y0)) / (board_width * board_height)
    unique_rotations = sorted({float(item["rotation_deg"]) % 360 for item in case["placements"]})

    route = route_metrics(find_final_board(root, result))
    avg_series_distance = mean(series_source_distances) if series_source_distances else 0.0
    max_series_excess = max(series_path_excess, default=1.0)
    avg_gate_distance = mean(gate_distances) if gate_distances else 0.0
    flags: list[str] = []
    if max(decoupling_loops) > 8.0:
        flags.append("decoupling-loop-long")
    if avg_series_distance > 8.0:
        flags.append("series-elements-remote")
    if max_series_excess > 1.25:
        flags.append("series-path-detour")
    if avg_gate_distance > 4.0:
        flags.append("gate-element-remote")
    if bbox_utilization < 0.65:
        flags.append("low-placement-utilization")
    if len(unique_rotations) == 1:
        flags.append("rotation-search-unused")
    if route["zone_count"] == 0:
        flags.append("no-plane-or-pour")
    if not result["success"]:
        flags.append("strict-route-failure")

    return {
        "case_id": case["case_id"],
        "tier": case["difficulty"],
        "title": case["title"],
        "strict_success": bool(result["success"]),
        "unconnected": int(result["unconnected"]),
        "component_count": len(case["placements"]),
        "board_area_mm2": round(board_width * board_height, 2),
        "occupied_bbox_utilization": round(bbox_utilization, 4),
        "unique_rotations": ";".join(str(int(value)) for value in unique_rotations),
        "c1_loop_span_mm": round(decoupling_loops[0], 3),
        "c2_loop_span_mm": round(decoupling_loops[1], 3),
        "mean_series_source_distance_mm": round(avg_series_distance, 3),
        "max_series_path_excess_ratio": round(max_series_excess, 3),
        "mean_gate_element_distance_mm": round(avg_gate_distance, 3),
        "mean_load_path_terminal_distance_mm": round(mean(load_distances), 3)
        if load_distances
        else 0.0,
        **route,
        "review_flags": ";".join(flags),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cases = json.loads((args.corpus / "case-matrix.json").read_text(encoding="utf-8"))
    results_document = json.loads((args.corpus / "results.json").read_text(encoding="utf-8"))
    results = {item["case_id"]: item for item in results_document["cases"]}
    rows = [analyze_case(case, results[case["case_id"]], args.corpus) for case in cases]

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "board-placement-routing-metrics.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output / "board-placement-routing-metrics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    tier_summary: dict[str, dict[str, object]] = {}
    for tier in dict.fromkeys(row["tier"] for row in rows):
        group = [row for row in rows if row["tier"] == tier]
        tier_summary[str(tier)] = {
            "boards": len(group),
            "strict_passes": sum(bool(row["strict_success"]) for row in group),
            "mean_decoupling_loop_span_mm": round(
                mean(
                    (float(row["c1_loop_span_mm"]) + float(row["c2_loop_span_mm"])) / 2
                    for row in group
                ),
                3,
            ),
            "mean_occupied_bbox_utilization": round(
                mean(float(row["occupied_bbox_utilization"]) for row in group), 4
            ),
            "mean_route_length_mm": round(mean(float(row["route_length_mm"]) for row in group), 3),
            "boards_without_plane_or_pour": sum(int(row["zone_count"]) == 0 for row in group),
        }
    (args.output / "placement-routing-summary.json").write_text(
        json.dumps(tier_summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(tier_summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
