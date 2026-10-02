"""KiCad pcbnew bridge for deterministic copper-intent regions and read-back."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pcbnew


def _read_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return payload


def _find_pad(board: pcbnew.BOARD, node: object) -> pcbnew.PAD:
    if not isinstance(node, list) or len(node) != 2:
        raise TypeError(f"Invalid node: {node!r}")
    reference, number = str(node[0]), str(node[1])
    for footprint in board.GetFootprints():
        if str(footprint.GetReference()) != reference:
            continue
        for pad in footprint.Pads():
            if str(pad.GetNumber()) == number:
                return pad
    raise KeyError(f"Pad not found: {reference}.{number}")


def _rectangle_polygon(bounds: tuple[int, int, int, int]) -> pcbnew.SHAPE_POLY_SET:
    left, top, right, bottom = bounds
    if right <= left or bottom <= top:
        raise ValueError(f"Degenerate copper rectangle: {bounds}")
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in ((left, top), (right, top), (right, bottom), (left, bottom)):
        chain.Append(x, y)
    chain.SetClosed(True)
    polygon = pcbnew.SHAPE_POLY_SET()
    polygon.AddOutline(chain)
    return polygon


def _add_region_zone(
    board: pcbnew.BOARD,
    *,
    net_name: str,
    layer: int,
    name: str,
    rectangles: tuple[tuple[int, int, int, int], ...],
    clearance_mm: float,
    priority: int,
) -> None:
    if not rectangles:
        raise ValueError(f"Copper region has no geometry: {name}")
    polygon = _rectangle_polygon(rectangles[0])
    for bounds in rectangles[1:]:
        polygon.BooleanAdd(_rectangle_polygon(bounds))
    polygon.Simplify()
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNetCode(board.FindNet(net_name).GetNetCode())
    zone.SetZoneName(name)
    zone.SetLocalClearance(pcbnew.FromMM(clearance_mm))
    zone.SetMinThickness(pcbnew.FromMM(0.2))
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    zone.SetAssignedPriority(priority)
    for outline_index in range(polygon.OutlineCount()):
        zone.AddPolygon(polygon.COutline(outline_index))
    board.Add(zone)


def apply_copper_intent(source: Path, plan_path: Path, output: Path) -> None:
    """Add deterministic zones without treating their presence as qualification."""
    board = pcbnew.LoadBoard(str(source))
    plan = _read_object(plan_path)
    regions = plan.get("regions")
    if not isinstance(regions, list):
        raise TypeError("Copper-intent regions must be a list")
    existing_names = {str(zone.GetZoneName()) for zone in board.Zones()}
    if any(name.startswith("PCBSMITH:") for name in existing_names):
        raise ValueError("Board already contains PCBSMITH copper-intent zones")
    board_box = board.GetBoardEdgesBoundingBox()
    for raw in regions:
        if not isinstance(raw, dict):
            raise TypeError("Copper-intent region must be an object")
        region_id = str(raw["region_id"])
        net_name = str(raw["net_name"])
        layer_name = str(raw["physical_layer"])
        layer = int(board.GetLayerID(layer_name))
        if layer < 0 or not board.GetDesignSettings().IsLayerEnabled(layer):
            raise ValueError(f"Copper layer is unavailable: {layer_name}")
        clearance = float(str(raw["clearance_mm"]))
        priority = int(str(raw["priority"]))
        kind = str(raw["kind"])
        prefix = f"PCBSMITH:{region_id}"
        if kind == "board_fill":
            inset = pcbnew.FromMM(float(str(raw["edge_inset_mm"])))
            _add_region_zone(
                board,
                net_name=net_name,
                layer=layer,
                name=f"{prefix}:BOARD",
                rectangles=(
                    (
                        board_box.GetX() + inset,
                        board_box.GetY() + inset,
                        board_box.GetRight() - inset,
                        board_box.GetBottom() - inset,
                    ),
                ),
                clearance_mm=clearance,
                priority=priority,
            )
            continue
        if kind != "manhattan_corridor":
            raise ValueError(f"Unsupported copper region kind: {kind}")
        source_pad = _find_pad(board, raw.get("source"))
        sink_pad = _find_pad(board, raw.get("sink"))
        source_pos = source_pad.GetPosition()
        sink_pos = sink_pad.GetPosition()
        width = float(str(raw["width_mm"]))
        half = max(pcbnew.FromMM(width / 2.0), pcbnew.FromMM(0.25))
        horizontal = (
            min(source_pos.x, sink_pos.x) - half,
            source_pos.y - half,
            max(source_pos.x, sink_pos.x) + half,
            source_pos.y + half,
        )
        vertical = (
            sink_pos.x - half,
            min(source_pos.y, sink_pos.y) - half,
            sink_pos.x + half,
            max(source_pos.y, sink_pos.y) + half,
        )
        _add_region_zone(
            board,
            net_name=net_name,
            layer=layer,
            name=f"{prefix}:CORRIDOR",
            rectangles=(horizontal, vertical),
            clearance_mm=clearance,
            priority=priority,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(output), board)


def _zone_covers_pad(zone: pcbnew.ZONE, pad: pcbnew.PAD) -> bool:
    layer = zone.GetLayer()
    return bool(
        pad.IsOnLayer(layer)
        and zone.HasFilledPolysForLayer(layer)
        and zone.HitTestFilledArea(layer, pad.GetPosition(), pcbnew.FromMM(0.01))
    )


def inspect_copper_intent(board_path: Path, plan_path: Path, output: Path) -> None:
    board = pcbnew.LoadBoard(str(board_path))
    plan = _read_object(plan_path)
    raw_regions = plan.get("regions")
    raw_paths = plan.get("paths")
    if not isinstance(raw_regions, list) or not isinstance(raw_paths, list):
        raise TypeError("Copper-intent plan must contain region and path lists")
    zones = tuple(board.Zones())
    region_records: dict[str, object] = {}
    for raw in raw_regions:
        if not isinstance(raw, dict):
            continue
        region_id = str(raw["region_id"])
        matching = tuple(
            zone for zone in zones if str(zone.GetZoneName()).startswith(f"PCBSMITH:{region_id}:")
        )
        source = raw.get("source")
        sink = raw.get("sink")
        source_covered = None
        sink_covered = None
        if source is not None:
            source_pad = _find_pad(board, source)
            source_covered = any(_zone_covers_pad(zone, source_pad) for zone in matching)
        if sink is not None:
            sink_pad = _find_pad(board, sink)
            sink_covered = any(_zone_covers_pad(zone, sink_pad) for zone in matching)
        region_records[region_id] = {
            "net_name": raw["net_name"],
            "role": raw["role"],
            "kind": raw["kind"],
            "physical_layer": raw["physical_layer"],
            "zone_count": len(matching),
            "filled_zone_count": sum(
                zone.HasFilledPolysForLayer(zone.GetLayer()) for zone in matching
            ),
            "source_covered": source_covered,
            "sink_covered": sink_covered,
            "endpoint_coverage": (
                source_covered is True and sink_covered is True
                if source is not None and sink is not None
                else None
            ),
        }
    tracks_by_net: dict[str, list[float]] = {}
    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA):
            continue
        tracks_by_net.setdefault(str(item.GetNetname()), []).append(
            round(float(pcbnew.ToMM(item.GetWidth())), 6)
        )
    path_records: dict[str, object] = {}
    for raw in raw_paths:
        if not isinstance(raw, dict):
            continue
        path_id = str(raw["path_id"])
        net_name = str(raw["net_name"])
        nominal = float(str(raw["nominal_width_mm"]))
        region = region_records.get(path_id)
        region_record = region if isinstance(region, dict) else {}
        if not region_record and net_name == "GND":
            ground_region = region_records.get("gnd-reference-plane")
            if isinstance(ground_region, dict):
                source_pad = _find_pad(board, raw["source"])
                sink_pad = _find_pad(board, raw["sink"])
                matching_ground_zones = tuple(
                    zone
                    for zone in zones
                    if str(zone.GetZoneName()).startswith("PCBSMITH:gnd-reference-plane:")
                )
                region_record = {
                    **ground_region,
                    "endpoint_coverage": any(
                        _zone_covers_pad(zone, source_pad) and _zone_covers_pad(zone, sink_pad)
                        for zone in matching_ground_zones
                    ),
                }
        widths = tracks_by_net.get(net_name, [])
        nominal_track_present = any(abs(width - nominal) <= 0.001 for width in widths)
        path_records[path_id] = {
            "net_name": net_name,
            "source": raw["source"],
            "sink": raw["sink"],
            "role": raw["role"],
            "nominal_width_mm": nominal,
            "track_minimum_width_mm": min(widths) if widths else None,
            "track_maximum_width_mm": max(widths) if widths else None,
            "nominal_track_width_present": nominal_track_present,
            "zone_endpoint_coverage": region_record.get("endpoint_coverage"),
            "topology_support_present": (
                region_record.get("endpoint_coverage") is True or nominal_track_present
            ),
            "continuous_cross_section_qualified": False,
        }
    output.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-copper-intent-observation-v1",
                "case_id": plan["case_id"],
                "board_copper_layer_count": board.GetCopperLayerCount(),
                "regions": region_records,
                "paths": path_records,
                "region_application_complete": all(
                    isinstance(value, dict)
                    and int(str(value["zone_count"])) > 0
                    and int(str(value["filled_zone_count"])) > 0
                    for value in region_records.values()
                ),
                "acceptance_boundary": (
                    "This observes filled-region and endpoint coverage plus track widths. "
                    "It does not prove continuous copper cross-section, via capacity, "
                    "ampacity, voltage drop, or temperature rise."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("source", type=Path)
    apply_parser.add_argument("plan", type=Path)
    apply_parser.add_argument("output", type=Path)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("board", type=Path)
    inspect_parser.add_argument("plan", type=Path)
    inspect_parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "apply":
        apply_copper_intent(args.source.resolve(), args.plan.resolve(), args.output.resolve())
    else:
        inspect_copper_intent(args.board.resolve(), args.plan.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
