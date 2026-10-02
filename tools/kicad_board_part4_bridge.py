"""Part 4 exact reference-continuity bridge layered over the read-only observer."""

from __future__ import annotations

import argparse
import json
import math
from fractions import Fraction
from pathlib import Path

import kicad_board_feasibility_bridge as base

pcbnew = base.pcbnew

Point = tuple[int, int]
Contour = tuple[Point, ...]
Polygon = tuple[Contour, tuple[Contour, ...]]


def _contour(chain: object) -> Contour:
    return tuple(
        (int(chain.CPoint(index).x), int(chain.CPoint(index).y))
        for index in range(chain.PointCount())
    )


def _filled_polygons(poly_set: object) -> tuple[Polygon, ...]:
    polygons: list[Polygon] = []
    for outline_index in range(poly_set.OutlineCount()):
        outline = _contour(poly_set.COutline(outline_index))
        holes = tuple(
            _contour(poly_set.CHole(outline_index, hole_index))
            for hole_index in range(poly_set.HoleCount(outline_index))
        )
        polygons.append((outline, holes))
    return tuple(polygons)


def _point_on_segment(point: tuple[Fraction, Fraction], start: Point, end: Point) -> bool:
    px, py = point
    ax, ay = start
    bx, by = end
    return (
        (px - ax) * (by - ay) == (py - ay) * (bx - ax)
        and min(ax, bx) <= px <= max(ax, bx)
        and min(ay, by) <= py <= max(ay, by)
    )


def _point_in_contour(point: tuple[Fraction, Fraction], contour: Contour) -> tuple[bool, bool]:
    """Return (inside, on_boundary) using exact rational arithmetic."""

    if len(contour) < 3:
        return False, False
    inside = False
    px, py = point
    for index, start in enumerate(contour):
        end = contour[(index + 1) % len(contour)]
        if _point_on_segment(point, start, end):
            return True, True
        ax, ay = start
        bx, by = end
        if (ay > py) == (by > py):
            continue
        crossing_x = Fraction(ax) + Fraction((py - ay) * (bx - ax), by - ay)
        if crossing_x > px:
            inside = not inside
    return inside, False


def _covered(point: tuple[Fraction, Fraction], polygons: tuple[Polygon, ...]) -> bool:
    for outline, holes in polygons:
        inside, boundary = _point_in_contour(point, outline)
        if not inside:
            continue
        if boundary:
            return True
        rejected = False
        for hole in holes:
            in_hole, on_hole = _point_in_contour(point, hole)
            if on_hole:
                return True
            if in_hole:
                rejected = True
                break
        if not rejected:
            return True
    return False


def _cross(a: Point, b: Point) -> int:
    return a[0] * b[1] - a[1] * b[0]


def _boundary_parameters(start: Point, end: Point, contour: Contour) -> set[Fraction]:
    parameters: set[Fraction] = set()
    direction = (end[0] - start[0], end[1] - start[1])
    denominator_axis = 0 if abs(direction[0]) >= abs(direction[1]) else 1
    for index, boundary_start in enumerate(contour):
        boundary_end = contour[(index + 1) % len(contour)]
        boundary_direction = (
            boundary_end[0] - boundary_start[0],
            boundary_end[1] - boundary_start[1],
        )
        offset = (boundary_start[0] - start[0], boundary_start[1] - start[1])
        denominator = _cross(direction, boundary_direction)
        if denominator:
            t = Fraction(_cross(offset, boundary_direction), denominator)
            u = Fraction(_cross(offset, direction), denominator)
            if 0 <= t <= 1 and 0 <= u <= 1:
                parameters.add(t)
            continue
        if _cross(offset, direction) or direction == (0, 0):
            continue
        axis_delta = direction[denominator_axis]
        for point in (boundary_start, boundary_end):
            t = Fraction(point[denominator_axis] - start[denominator_axis], axis_delta)
            if 0 <= t <= 1:
                parameters.add(t)
    return parameters


def segment_fully_covered(start: Point, end: Point, polygons: tuple[Polygon, ...]) -> bool:
    """Prove continuous centerline coverage, including holes and zone unions."""

    if start == end:
        return _covered((Fraction(start[0]), Fraction(start[1])), polygons)
    parameters: set[Fraction] = {Fraction(0), Fraction(1)}
    for outline, holes in polygons:
        parameters.update(_boundary_parameters(start, end, outline))
        for hole in holes:
            parameters.update(_boundary_parameters(start, end, hole))
    ordered = sorted(parameters)

    def point_at(t: Fraction) -> tuple[Fraction, Fraction]:
        return (
            Fraction(start[0]) + t * (end[0] - start[0]),
            Fraction(start[1]) + t * (end[1] - start[1]),
        )

    if any(not _covered(point_at(t), polygons) for t in ordered):
        return False
    return all(
        _covered(point_at((left + right) / 2), polygons)
        for left, right in zip(ordered, ordered[1:], strict=False)
        if left != right
    )


def exact_reference_continuity(
    board: object, contract: dict[str, object]
) -> dict[str, object]:
    reference_nets = tuple(
        sorted(
            {
                str(item.get("name", ""))
                for item in contract.get("nets", [])
                if isinstance(item, dict)
                and str(item.get("width_class", "")).lower() in {"ground", "return"}
                and str(item.get("name", ""))
            }
        )
    )
    fills: dict[int, list[Polygon]] = {pcbnew.F_Cu: [], pcbnew.B_Cu: []}
    for zone in board.Zones():
        layer = zone.GetLayer()
        if layer in fills and str(zone.GetNetname()) in reference_nets:
            filled = zone.GetFilledPolysList(layer)
            if zone.HasFilledPolysForLayer(layer) and filled.OutlineCount():
                fills[layer].extend(_filled_polygons(filled))
    signal_segments = [
        item
        for item in board.GetTracks()
        if isinstance(item, pcbnew.PCB_TRACK)
        and not isinstance(item, pcbnew.PCB_VIA)
        and str(item.GetNetname())
        and str(item.GetNetname()) not in reference_nets
        and item.GetLayer() in {pcbnew.F_Cu, pcbnew.B_Cu}
    ]
    findings: list[dict[str, object]] = []
    supported = 0
    unsupported = 0
    unsupported_geometry = 0
    for track in signal_segments:
        if isinstance(track, pcbnew.PCB_ARC):
            unsupported_geometry += 1
            if len(findings) < 200:
                findings.append(
                    {
                        "kind": "unsupported_track_geometry",
                        "track_id": base._semantic_base(track),
                        "net_name": str(track.GetNetname()),
                        "geometry": type(track).__name__,
                    }
                )
            continue
        reference_layer = pcbnew.B_Cu if track.GetLayer() == pcbnew.F_Cu else pcbnew.F_Cu
        start, end = track.GetStart(), track.GetEnd()
        covered = bool(fills[reference_layer]) and segment_fully_covered(
            (int(start.x), int(start.y)),
            (int(end.x), int(end.y)),
            tuple(fills[reference_layer]),
        )
        if covered:
            supported += 1
        else:
            unsupported += 1
            if len(findings) < 200:
                findings.append(
                    {
                        "kind": "exact_centerline_reference_discontinuity",
                        "track_id": base._semantic_base(track),
                        "net_name": str(track.GetNetname()),
                        "signal_layer": board.GetLayerName(track.GetLayer()),
                        "reference_layer": board.GetLayerName(reference_layer),
                    }
                )
    reference_vias = [
        item
        for item in board.GetTracks()
        if isinstance(item, pcbnew.PCB_VIA) and str(item.GetNetname()) in reference_nets
    ]
    signal_vias = [
        item
        for item in board.GetTracks()
        if isinstance(item, pcbnew.PCB_VIA)
        and str(item.GetNetname())
        and str(item.GetNetname()) not in reference_nets
    ]
    unstitched = 0
    maximum_distance = pcbnew.FromMM(2.0)
    for via in signal_vias:
        point = via.GetPosition()
        nearby = any(
            math.hypot(
                reference.GetPosition().x - point.x,
                reference.GetPosition().y - point.y,
            )
            <= maximum_distance
            for reference in reference_vias
        )
        if not nearby:
            unstitched += 1
            if len(findings) < 200:
                findings.append(
                    {
                        "kind": "signal_transition_without_nearby_reference_via",
                        "via_id": base._semantic_base(via),
                        "net_name": str(via.GetNetname()),
                        "position_mm": list(base._position(via)),
                    }
                )
    stackup_supported = board.GetCopperLayerCount() == 2
    exact_pass = bool(
        stackup_supported
        and reference_nets
        and not unsupported
        and not unsupported_geometry
        and not unstitched
    )
    if not stackup_supported:
        disposition = "unsupported_stackup_unverified"
    elif not reference_nets:
        disposition = "reference_net_undeclared_unverified"
    elif unsupported_geometry:
        disposition = "unsupported_track_geometry_unverified"
    elif exact_pass:
        disposition = "exact_geometric_continuity_observed"
    else:
        disposition = "exact_geometric_discontinuities_observed"
    result: dict[str, object] = {
        "schema_id": "pcbsmith-reference-continuity-evidence",
        "schema_version": 1,
        "authority": "exact-straight-centerline-geometric-v1",
        "reference_net_names": list(reference_nets),
        "copper_layer_count": int(board.GetCopperLayerCount()),
        "signal_segment_count": len(signal_segments),
        "exact_supported_segment_count": supported,
        "exact_unsupported_segment_count": unsupported,
        "unsupported_geometry_segment_count": unsupported_geometry,
        "signal_transition_count": len(signal_vias),
        "transition_without_nearby_reference_via_count": unstitched,
        "maximum_transition_stitch_distance_mm": 2.0,
        "exact_pass_authorized": exact_pass,
        "automatic_multilayer_pass_prohibited": True,
        "disposition": disposition,
        "findings": findings,
        "scope": (
            "Exact rational coverage of every straight signal-segment centerline by the union "
            "of filled reference-net contours on the opposite layer, plus exact Euclidean "
            "application of a 2 mm transition-via proximity policy. This does not establish "
            "full conductor-width support, impedance, SI/EMC, current density, or thermal adequacy."
        ),
    }
    result["evidence_fingerprint"] = base._fp(result)
    return result


def observe(
    board_path: Path,
    contract_path: Path,
    output_path: Path,
    *,
    clearance_mm: float,
    edge_clearance_mm: float,
    via_diameter_mm: float,
    trace_width_mm: float,
    skip_placement_audit: bool,
) -> None:
    base.observe(
        board_path,
        contract_path,
        output_path,
        clearance_mm=clearance_mm,
        edge_clearance_mm=edge_clearance_mm,
        via_diameter_mm=via_diameter_mm,
        trace_width_mm=trace_width_mm,
        skip_placement_audit=skip_placement_audit,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    base.wx.Image.CleanUpHandlers()
    board = pcbnew.LoadBoard(str(board_path))
    payload["reference_continuity"] = exact_reference_continuity(board, contract)
    payload["acceptance_boundary"] = (
        "Read-only KiCad geometry/connectivity evidence. Reference continuity is exact only "
        "for the declared straight-centerline model; it is not SI, EMC, current, or thermal proof."
    )
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--clearance-mm", type=float, default=0.2)
    parser.add_argument("--edge-clearance-mm", type=float, default=0.5)
    parser.add_argument("--via-diameter-mm", type=float, default=0.8)
    parser.add_argument("--trace-width-mm", type=float, default=0.5)
    parser.add_argument("--skip-placement-audit", action="store_true")
    args = parser.parse_args()
    observe(
        args.board.resolve(),
        args.contract.resolve(),
        args.output.resolve(),
        clearance_mm=args.clearance_mm,
        edge_clearance_mm=args.edge_clearance_mm,
        via_diameter_mm=args.via_diameter_mm,
        trace_width_mm=args.trace_width_mm,
        skip_placement_audit=args.skip_placement_audit,
    )


if __name__ == "__main__":
    main()
