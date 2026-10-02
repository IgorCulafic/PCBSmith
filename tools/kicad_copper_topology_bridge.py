"""KiCad pcbnew bridge for shared power trees and explicit ground escapes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median_low

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
        other = _rectangle_polygon(bounds)
        polygon.BooleanAdd(other)
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


def _corridor_rectangles(
    source: pcbnew.VECTOR2I,
    sink: pcbnew.VECTOR2I,
    half: int,
) -> tuple[tuple[int, int, int, int], ...]:
    return (
        (
            min(source.x, sink.x) - half,
            source.y - half,
            max(source.x, sink.x) + half,
            source.y + half,
        ),
        (
            sink.x - half,
            min(source.y, sink.y) - half,
            sink.x + half,
            max(source.y, sink.y) + half,
        ),
    )


def _shared_tree_rectangles(
    positions: tuple[pcbnew.VECTOR2I, ...],
    half: int,
) -> tuple[tuple[int, int, int, int], ...]:
    xs = tuple(position.x for position in positions)
    ys = tuple(position.y for position in positions)
    rectangles: list[tuple[int, int, int, int]] = []
    if max(xs) - min(xs) >= max(ys) - min(ys):
        trunk_y = int(median_low(ys))
        rectangles.append((min(xs) - half, trunk_y - half, max(xs) + half, trunk_y + half))
        for position in positions:
            rectangles.append(
                (
                    position.x - half,
                    min(position.y, trunk_y) - half,
                    position.x + half,
                    max(position.y, trunk_y) + half,
                )
            )
    else:
        trunk_x = int(median_low(xs))
        rectangles.append((trunk_x - half, min(ys) - half, trunk_x + half, max(ys) + half))
        for position in positions:
            rectangles.append(
                (
                    min(position.x, trunk_x) - half,
                    position.y - half,
                    max(position.x, trunk_x) + half,
                    position.y + half,
                )
            )
    return tuple(rectangles)


def _candidate_directions(pad: pcbnew.PAD) -> tuple[tuple[int, int], ...]:
    position = pad.GetPosition()
    parent = pad.GetParent()
    center = parent.GetPosition() if hasattr(parent, "GetPosition") else position
    dx = position.x - center.x
    dy = position.y - center.y
    primary_x = 1 if dx >= 0 else -1
    primary_y = 1 if dy >= 0 else -1
    if abs(dx) >= abs(dy):
        ordered = (
            (primary_x, 0),
            (primary_x, primary_y),
            (0, primary_y),
            (primary_x, -primary_y),
        )
    else:
        ordered = (
            (0, primary_y),
            (primary_x, primary_y),
            (primary_x, 0),
            (-primary_x, primary_y),
        )
    remaining = tuple(
        direction
        for direction in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
        if direction not in ordered
    )
    return ordered + remaining


def _candidate_clear(
    board: pcbnew.BOARD,
    pad: pcbnew.PAD,
    position: pcbnew.VECTOR2I,
    via_radius: int,
    clearance: int,
) -> bool:
    board_box = board.GetBoardEdgesBoundingBox()
    inset_box = board_box.GetInflated(-(via_radius + clearance))
    if not inset_box.Contains(position):
        return False
    net_code = pad.GetNetCode()
    for footprint in board.GetFootprints():
        for other in footprint.Pads():
            if other is pad or other.GetNetCode() == net_code:
                continue
            box = other.GetBoundingBox().GetInflated(via_radius + clearance)
            if box.Contains(position):
                return False
    for item in board.GetTracks():
        if item.GetNetCode() == net_code:
            continue
        box = item.GetBoundingBox().GetInflated(via_radius + clearance)
        if box.Contains(position):
            return False
    return True


def _escape_position(
    board: pcbnew.BOARD,
    pad: pcbnew.PAD,
    preferred_offset_mm: float,
    maximum_offset_mm: float,
    via_radius: int,
) -> pcbnew.VECTOR2I | None:
    position = pad.GetPosition()
    clearance = pcbnew.FromMM(0.2)
    offsets = []
    value = preferred_offset_mm
    while value <= maximum_offset_mm + 0.001:
        offsets.append(pcbnew.FromMM(value))
        value += 0.3
    for offset in offsets:
        for dx, dy in _candidate_directions(pad):
            scale = 0.70710678 if dx and dy else 1.0
            candidate = pcbnew.VECTOR2I(
                position.x + int(dx * offset * scale),
                position.y + int(dy * offset * scale),
            )
            if _candidate_clear(board, pad, candidate, via_radius, clearance):
                return candidate
    return None


def _add_ground_escape(board: pcbnew.BOARD, raw: dict[str, object]) -> bool:
    pad = _find_pad(board, raw["pad"])
    source_layer = int(board.GetLayerID(str(raw["source_layer"])))
    target_layer = int(board.GetLayerID(str(raw["target_layer"])))
    if target_layer < 0 or not board.GetDesignSettings().IsLayerEnabled(target_layer):
        raise ValueError(f"Copper layer is unavailable: {raw['target_layer']}")
    if not pad.IsOnLayer(source_layer) or pad.IsOnLayer(target_layer):
        return False
    via_diameter = pcbnew.FromMM(float(str(raw["via_diameter_mm"])))
    via_position = _escape_position(
        board,
        pad,
        float(str(raw["preferred_offset_mm"])),
        float(str(raw["maximum_offset_mm"])),
        via_diameter // 2,
    )
    via_in_pad = False
    if via_position is None:
        if raw.get("allow_via_in_pad_fallback") is not True:
            return False
        via_position = pad.GetPosition()
        via_in_pad = True
    net_code = pad.GetNetCode()
    if not via_in_pad:
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pad.GetPosition())
        track.SetEnd(via_position)
        track.SetWidth(pcbnew.FromMM(float(str(raw["track_width_mm"]))))
        track.SetLayer(source_layer)
        track.SetNetCode(net_code)
        board.Add(track)
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(via_position)
    via.SetWidth(via_diameter)
    via.SetDrill(pcbnew.FromMM(float(str(raw["via_drill_mm"]))))
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetNetCode(net_code)
    board.Add(via)
    return True


def apply_copper_topology(source: Path, plan_path: Path, output: Path) -> None:
    board = pcbnew.LoadBoard(str(source))
    plan = _read_object(plan_path)
    regions = plan.get("regions")
    escapes = plan.get("escapes")
    if not isinstance(regions, list) or not isinstance(escapes, list):
        raise TypeError("Copper topology plan must contain region and escape lists")
    if any(str(zone.GetZoneName()).startswith("PCBSMITH:") for zone in board.Zones()):
        raise ValueError("Board already contains PCBSMITH copper zones")
    board_box = board.GetBoardEdgesBoundingBox()
    for raw in regions:
        if not isinstance(raw, dict):
            raise TypeError("Copper topology region must be an object")
        region_id = str(raw["region_id"])
        net_name = str(raw["net_name"])
        layer = int(board.GetLayerID(str(raw["physical_layer"])))
        if layer < 0 or not board.GetDesignSettings().IsLayerEnabled(layer):
            raise ValueError(f"Copper layer is unavailable: {raw['physical_layer']}")
        kind = str(raw["kind"])
        if kind == "board_fill":
            inset = pcbnew.FromMM(float(str(raw["edge_inset_mm"])))
            rectangles = (
                (
                    board_box.GetX() + inset,
                    board_box.GetY() + inset,
                    board_box.GetRight() - inset,
                    board_box.GetBottom() - inset,
                ),
            )
        else:
            nodes = raw.get("nodes")
            if not isinstance(nodes, list) or len(nodes) < 2:
                raise TypeError(f"Region has invalid nodes: {region_id}")
            positions = tuple(_find_pad(board, node).GetPosition() for node in nodes)
            half = max(
                pcbnew.FromMM(float(str(raw["width_mm"])) / 2.0),
                pcbnew.FromMM(0.25),
            )
            if kind == "manhattan_corridor":
                rectangles = _corridor_rectangles(positions[0], positions[1], half)
            elif kind == "shared_tree":
                rectangles = _shared_tree_rectangles(positions, half)
            else:
                raise ValueError(f"Unsupported copper region kind: {kind}")
        _add_region_zone(
            board,
            net_name=net_name,
            layer=layer,
            name=f"PCBSMITH:{region_id}:{kind.upper()}",
            rectangles=rectangles,
            clearance_mm=float(str(raw["clearance_mm"])),
            priority=int(str(raw["priority"])),
        )
    for raw_escape in escapes:
        if not isinstance(raw_escape, dict):
            raise TypeError("Copper topology escape must be an object")
        _add_ground_escape(board, raw_escape)
    output.parent.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(output), board)


def _zone_covers_pad(zone: pcbnew.ZONE, pad: pcbnew.PAD) -> bool:
    layer = zone.GetLayer()
    return bool(
        pad.IsOnLayer(layer)
        and zone.HasFilledPolysForLayer(layer)
        and zone.HitTestFilledArea(layer, pad.GetPosition(), pcbnew.FromMM(0.01))
    )


def _distance_squared(first: pcbnew.VECTOR2I, second: pcbnew.VECTOR2I) -> int:
    return (first.x - second.x) ** 2 + (first.y - second.y) ** 2


def _escape_observation(
    board: pcbnew.BOARD,
    raw: dict[str, object],
) -> dict[str, object]:
    pad = _find_pad(board, raw["pad"])
    source_layer = int(board.GetLayerID(str(raw["source_layer"])))
    target_layer = int(board.GetLayerID(str(raw["target_layer"])))
    required = pad.IsOnLayer(source_layer) and not pad.IsOnLayer(target_layer)
    maximum = pcbnew.FromMM(float(str(raw["maximum_offset_mm"])) + 0.2)
    candidates = tuple(
        item
        for item in board.GetTracks()
        if isinstance(item, pcbnew.PCB_VIA)
        and item.GetNetCode() == pad.GetNetCode()
        and _distance_squared(item.GetPosition(), pad.GetPosition()) <= maximum**2
    )
    connected_via = None
    track_found = False
    via_in_pad = False
    for via in candidates:
        if via.GetPosition() == pad.GetPosition():
            connected_via = via
            track_found = True
            via_in_pad = True
            break
        for item in board.GetTracks():
            if isinstance(item, pcbnew.PCB_VIA) or item.GetNetCode() != pad.GetNetCode():
                continue
            if item.GetLayer() != source_layer:
                continue
            endpoints = (item.GetStart(), item.GetEnd())
            if pad.GetPosition() in endpoints and via.GetPosition() in endpoints:
                connected_via = via
                track_found = True
                break
        if track_found:
            break
    return {
        "pad": raw["pad"],
        "required": required,
        "via_found": connected_via is not None,
        "track_found": track_found,
        "via_in_pad_fallback_used": via_in_pad,
        "satisfied": not required or (connected_via is not None and track_found),
        "via_position_mm": (
            [
                round(float(pcbnew.ToMM(connected_via.GetPosition().x)), 6),
                round(float(pcbnew.ToMM(connected_via.GetPosition().y)), 6),
            ]
            if connected_via is not None
            else None
        ),
    }


def inspect_copper_topology(board_path: Path, plan_path: Path, output: Path) -> None:
    board = pcbnew.LoadBoard(str(board_path))
    plan = _read_object(plan_path)
    raw_regions = plan.get("regions")
    raw_paths = plan.get("paths")
    raw_escapes = plan.get("escapes")
    if not isinstance(raw_regions, list) or not isinstance(raw_paths, list):
        raise TypeError("Copper topology plan must contain region and path lists")
    if not isinstance(raw_escapes, list):
        raise TypeError("Copper topology plan must contain an escape list")
    zones = tuple(board.Zones())
    region_records: dict[str, object] = {}
    region_zones: dict[str, tuple[pcbnew.ZONE, ...]] = {}
    for raw in raw_regions:
        if not isinstance(raw, dict):
            continue
        region_id = str(raw["region_id"])
        matching = tuple(
            zone for zone in zones if str(zone.GetZoneName()).startswith(f"PCBSMITH:{region_id}:")
        )
        region_zones[region_id] = matching
        nodes = raw.get("nodes", [])
        node_coverage = {}
        if isinstance(nodes, list):
            for node in nodes:
                pad = _find_pad(board, node)
                node_coverage[f"{node[0]}.{node[1]}"] = any(
                    _zone_covers_pad(zone, pad) for zone in matching
                )
        region_records[region_id] = {
            "net_name": raw["net_name"],
            "role": raw["role"],
            "kind": raw["kind"],
            "physical_layer": raw["physical_layer"],
            "zone_count": len(matching),
            "filled_zone_count": sum(
                zone.HasFilledPolysForLayer(zone.GetLayer()) for zone in matching
            ),
            "node_coverage": node_coverage,
        }
    escape_records: dict[str, object] = {}
    escape_by_pad: dict[str, bool] = {}
    for raw in raw_escapes:
        if not isinstance(raw, dict):
            continue
        escape_id = str(raw["escape_id"])
        observation = _escape_observation(board, raw)
        escape_records[escape_id] = observation
        pad = raw["pad"]
        if isinstance(pad, list) and len(pad) == 2:
            escape_by_pad[f"{pad[0]}.{pad[1]}"] = observation["satisfied"] is True
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
        region_id = str(raw["region_id"])
        net_name = str(raw["net_name"])
        nominal = float(str(raw["nominal_width_mm"]))
        source = raw["source"]
        sink = raw["sink"]
        source_pad = _find_pad(board, source)
        sink_pad = _find_pad(board, sink)
        matching = region_zones.get(region_id, ())
        source_covered = any(_zone_covers_pad(zone, source_pad) for zone in matching)
        sink_covered = any(_zone_covers_pad(zone, sink_pad) for zone in matching)
        if net_name == "GND":
            source_covered = source_covered or escape_by_pad.get(f"{source[0]}.{source[1]}", False)
            sink_covered = sink_covered or escape_by_pad.get(f"{sink[0]}.{sink[1]}", False)
        widths = tracks_by_net.get(net_name, [])
        nominal_track_present = any(abs(width - nominal) <= 0.001 for width in widths)
        path_records[path_id] = {
            "region_id": region_id,
            "net_name": net_name,
            "source": source,
            "sink": sink,
            "role": raw["role"],
            "nominal_width_mm": nominal,
            "track_minimum_width_mm": min(widths) if widths else None,
            "track_maximum_width_mm": max(widths) if widths else None,
            "nominal_track_width_present": nominal_track_present,
            "source_topology_support": source_covered,
            "sink_topology_support": sink_covered,
            "topology_support_present": source_covered and sink_covered,
            "continuous_cross_section_qualified": False,
        }
    region_complete = all(
        isinstance(value, dict)
        and int(str(value["zone_count"])) > 0
        and int(str(value["filled_zone_count"])) > 0
        for value in region_records.values()
    )
    escape_complete = all(
        isinstance(value, dict) and value["satisfied"] is True for value in escape_records.values()
    )
    output.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-copper-topology-observation-v2",
                "case_id": plan["case_id"],
                "board_copper_layer_count": board.GetCopperLayerCount(),
                "regions": region_records,
                "escapes": escape_records,
                "paths": path_records,
                "region_application_complete": region_complete,
                "escape_application_complete": escape_complete,
                "application_complete": region_complete and escape_complete,
                "acceptance_boundary": (
                    "This observes filled shared regions, short ground escapes, and endpoint "
                    "support. It does not prove continuous cross-section, via capacity, "
                    "ampacity, voltage drop, temperature rise, or assembly suitability."
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
        apply_copper_topology(args.source.resolve(), args.plan.resolve(), args.output.resolve())
    else:
        inspect_copper_topology(args.board.resolve(), args.plan.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
