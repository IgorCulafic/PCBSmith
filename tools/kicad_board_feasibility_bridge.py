"""Read-only pcbnew observation for routing failures and placement feasibility."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import wx

# A headless bridge must never block on a modal wx assertion dialog. Assertions are
# retained as logged Python exceptions, so the parent runner still fails closed.
_ASSERT_APP = wx.App.Get() or wx.App(False)
_ASSERT_APP.SetAssertMode(wx.APP_ASSERT_EXCEPTION)
wx.Image.CleanUpHandlers()

import pcbnew  # noqa: E402


def _fp(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mm(value: int) -> float:
    return round(float(pcbnew.ToMM(value)), 6)


def _uuid(item: pcbnew.BOARD_ITEM) -> str:
    return str(item.m_Uuid.AsString())


def _kind(item: pcbnew.BOARD_ITEM) -> str:
    if isinstance(item, pcbnew.PAD):
        return "pad"
    if isinstance(item, pcbnew.PCB_VIA):
        return "via"
    if isinstance(item, pcbnew.PCB_TRACK):
        return "track"
    if isinstance(item, pcbnew.ZONE):
        return "zone"
    return type(item).__name__.lower()


def _layer(item: pcbnew.BOARD_ITEM) -> str:
    try:
        return str(item.GetLayerName())
    except Exception:
        return ""


def _position(item: pcbnew.BOARD_ITEM) -> tuple[float, float]:
    position = item.GetPosition()
    return _mm(position.x), _mm(position.y)


def _semantic_base(item: pcbnew.BOARD_ITEM) -> str:
    kind = _kind(item)
    if isinstance(item, pcbnew.PAD):
        footprint = item.GetParentFootprint()
        return f"pad:{footprint.GetReference()}:{item.GetNumber()}"
    if isinstance(item, pcbnew.PCB_VIA):
        x, y = _position(item)
        # KiCad 10 requires an explicit layer for its via-width accessor. Even
        # querying the via bounding box can reach that assertion through the
        # SWIG wrapper, which creates a modal wxWidgets debug alert on Windows.
        # Net, exact position, and span are sufficient for a stable identity;
        # duplicate bases are disambiguated by _inventory's occurrence index.
        return (
            f"via:{item.GetNetname()}:{x:.6f}:{y:.6f}:"
            f"{int(item.TopLayer())}:{int(item.BottomLayer())}"
        )
    if isinstance(item, pcbnew.PCB_TRACK):
        start, end = item.GetStart(), item.GetEnd()
        points = sorted(((_mm(start.x), _mm(start.y)), (_mm(end.x), _mm(end.y))))
        return (
            f"track:{item.GetNetname()}:{_layer(item)}:"
            f"{points[0][0]:.6f},{points[0][1]:.6f}:"
            f"{points[1][0]:.6f},{points[1][1]:.6f}:{_mm(item.GetWidth()):.6f}"
        )
    if isinstance(item, pcbnew.ZONE):
        return f"zone:{item.GetZoneName()}:{item.GetNetname()}:{_layer(item)}"
    x, y = _position(item)
    return f"{kind}:{_layer(item)}:{x:.6f}:{y:.6f}"


def _inventory(board: pcbnew.BOARD) -> tuple[dict[str, pcbnew.BOARD_ITEM], dict[str, str]]:
    items: list[pcbnew.BOARD_ITEM] = []
    items.extend(pad for footprint in board.GetFootprints() for pad in footprint.Pads())
    items.extend(board.GetTracks())
    items.extend(board.Zones())
    bases = Counter(_semantic_base(item) for item in items)
    seen: Counter[str] = Counter()
    by_uuid: dict[str, pcbnew.BOARD_ITEM] = {}
    semantic_by_uuid: dict[str, str] = {}
    for item in items:
        base = _semantic_base(item)
        occurrence = seen[base]
        seen[base] += 1
        semantic = base if bases[base] == 1 else f"{base}:occurrence:{occurrence}"
        by_uuid[_uuid(item)] = item
        semantic_by_uuid[_uuid(item)] = semantic
    return by_uuid, semantic_by_uuid


def _connected_component_ids(
    board: pcbnew.BOARD,
    by_uuid: dict[str, pcbnew.BOARD_ITEM],
    semantic_by_uuid: dict[str, str],
) -> dict[str, str]:
    connectivity = board.GetConnectivity()
    result: dict[str, str] = {}
    for uuid, item in by_uuid.items():
        connected = tuple(connectivity.GetConnectedItems(item))
        member_ids = []
        for member in (*connected, item):
            member_uuid = _uuid(member)
            member_ids.append(
                semantic_by_uuid[member_uuid]
                if member_uuid in semantic_by_uuid
                else _semantic_base(member)
            )
        members = sorted(set(member_ids))
        result[uuid] = f"component:{_fp(members)[:24]}"
    return result


def _power_nodes(contract: dict[str, object]) -> set[tuple[str, str]]:
    raw_nets = contract.get("nets", [])
    if not isinstance(raw_nets, list):
        return set()
    result: set[tuple[str, str]] = set()
    for item in raw_nets:
        if not isinstance(item, dict) or str(item.get("width_class", "")).lower() not in {
            "power",
            "return",
            "ground",
        }:
            continue
        nodes = item.get("nodes", [])
        if isinstance(nodes, list):
            result.update(
                (str(node[0]), str(node[1]))
                for node in nodes
                if isinstance(node, list) and len(node) == 2
            )
    return result


def _board_outline(board: pcbnew.BOARD) -> pcbnew.SHAPE_POLY_SET:
    outline = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(outline, True):
        raise ValueError("KiCad could not construct a closed board outline")
    return outline


def _inside_with_radius(
    outline: pcbnew.SHAPE_POLY_SET,
    point: pcbnew.VECTOR2I,
    radius: int,
) -> bool:
    samples = (
        (0, 0),
        (radius, 0),
        (-radius, 0),
        (0, radius),
        (0, -radius),
        (int(radius * 0.7071), int(radius * 0.7071)),
        (int(radius * 0.7071), -int(radius * 0.7071)),
        (-int(radius * 0.7071), int(radius * 0.7071)),
        (-int(radius * 0.7071), -int(radius * 0.7071)),
    )
    return all(outline.Contains(pcbnew.VECTOR2I(point.x + dx, point.y + dy)) for dx, dy in samples)


def _candidate_directions(pad: pcbnew.PAD) -> tuple[tuple[int, int], ...]:
    position = pad.GetPosition()
    center = pad.GetParentFootprint().GetPosition()
    dx, dy = position.x - center.x, position.y - center.y
    sx, sy = (1 if dx >= 0 else -1), (1 if dy >= 0 else -1)
    if abs(dx) >= abs(dy):
        preferred = ((sx, 0), (sx, sy), (0, sy), (sx, -sy))
    else:
        preferred = ((0, sy), (sx, sy), (sx, 0), (-sx, sy))
    all_directions = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    return preferred + tuple(item for item in all_directions if item not in preferred)


def _copper_items(board: pcbnew.BOARD) -> tuple[pcbnew.BOARD_CONNECTED_ITEM, ...]:
    return (
        *(pad for footprint in board.GetFootprints() for pad in footprint.Pads()),
        *board.GetTracks(),
    )


def _candidate_reason(
    *,
    board: pcbnew.BOARD,
    outline: pcbnew.SHAPE_POLY_SET,
    pad: pcbnew.PAD,
    candidate: pcbnew.VECTOR2I,
    source_layer: int,
    target_layer: int,
    clearance: int,
    edge_clearance: int,
    via_radius: int,
    trace_radius: int,
) -> str | None:
    start = pad.GetPosition()
    if not _inside_with_radius(outline, candidate, via_radius + edge_clearance):
        return "board_edge"
    # Sample the complete escape envelope; this catches concave outlines too.
    dx, dy = candidate.x - start.x, candidate.y - start.y
    length = max(1.0, math.hypot(dx, dy))
    nx, ny = -dy / length, dx / length
    for step in range(9):
        t = step / 8.0
        center = pcbnew.VECTOR2I(int(start.x + dx * t), int(start.y + dy * t))
        for side in (-1, 1):
            probe = pcbnew.VECTOR2I(
                int(center.x + nx * (trace_radius + edge_clearance) * side),
                int(center.y + ny * (trace_radius + edge_clearance) * side),
            )
            if not outline.Contains(probe):
                return "board_edge"
    parent = pad.GetParentFootprint()
    parent_uuid = _uuid(parent)
    for footprint in board.GetFootprints():
        if _uuid(footprint) == parent_uuid:
            continue
        if footprint.GetBoundingBox().GetInflated(via_radius + clearance).Contains(candidate):
            return "neighbor_courtyard"
    pad_uuid = _uuid(pad)
    segment = pcbnew.SEG(start, candidate)
    for other in _copper_items(board):
        if _uuid(other) == pad_uuid or other.GetNetCode() == pad.GetNetCode():
            continue
        layers = (
            (source_layer, target_layer) if isinstance(other, pcbnew.PAD) else (other.GetLayer(),)
        )
        same_footprint = isinstance(other, pcbnew.PAD) and (
            _uuid(other.GetParentFootprint()) == parent_uuid
        )
        segment_reason = (
            "same_footprint_copper_segment" if same_footprint else "neighbor_copper_segment"
        )
        via_reason = "same_footprint_copper_via" if same_footprint else "neighbor_copper_via"
        if source_layer in layers:
            try:
                if other.GetEffectiveShape(source_layer).Collide(segment, clearance + trace_radius):
                    return segment_reason
            except Exception:
                if other.GetBoundingBox().GetInflated(clearance + trace_radius).Contains(candidate):
                    return segment_reason
        if target_layer in layers or isinstance(other, pcbnew.PCB_VIA):
            try:
                if other.GetEffectiveShape(target_layer).Collide(candidate, clearance + via_radius):
                    return via_reason
            except Exception:
                if other.GetBoundingBox().GetInflated(clearance + via_radius).Contains(candidate):
                    return via_reason
    return None


def _rotation_candidates(
    board: pcbnew.BOARD,
    pad: pcbnew.PAD,
    *,
    outline: pcbnew.SHAPE_POLY_SET,
    rotation: float,
    clearance: int,
    edge_clearance: int,
    via_diameter: int,
    trace_width: int,
) -> tuple[list[dict[str, object]], Counter[str]]:
    footprint = pad.GetParentFootprint()
    original = float(footprint.GetOrientationDegrees())
    footprint.SetOrientationDegrees(rotation)
    try:
        source_layer = pad.GetPrincipalLayer()
        target_layer = pcbnew.B_Cu if source_layer == pcbnew.F_Cu else pcbnew.F_Cu
        via_radius = via_diameter // 2
        trace_radius = trace_width // 2
        pad_box = pad.GetBoundingBox()
        half_pad = max(pad_box.GetWidth(), pad_box.GetHeight()) // 2
        minimum = max(via_radius + clearance, half_pad + via_radius + clearance // 2)
        maximum = minimum + pcbnew.FromMM(3.0)
        offsets = range(minimum, maximum + 1, pcbnew.FromMM(0.4))
        legal: list[dict[str, object]] = []
        rejected: Counter[str] = Counter()
        for offset in offsets:
            for direction_x, direction_y in _candidate_directions(pad):
                scale = 0.70710678 if direction_x and direction_y else 1.0
                start = pad.GetPosition()
                candidate = pcbnew.VECTOR2I(
                    start.x + int(direction_x * offset * scale),
                    start.y + int(direction_y * offset * scale),
                )
                reason = _candidate_reason(
                    board=board,
                    outline=outline,
                    pad=pad,
                    candidate=candidate,
                    source_layer=source_layer,
                    target_layer=target_layer,
                    clearance=clearance,
                    edge_clearance=edge_clearance,
                    via_radius=via_radius,
                    trace_radius=trace_radius,
                )
                if reason is None:
                    legal.append(
                        {
                            "x_mm": _mm(candidate.x),
                            "y_mm": _mm(candidate.y),
                            "offset_mm": round(float(pcbnew.ToMM(offset)), 6),
                            "source_layer": board.GetLayerName(source_layer),
                            "target_layer": board.GetLayerName(target_layer),
                        }
                    )
                    if len(legal) >= 4:
                        return legal, rejected
                else:
                    rejected[reason] += 1
        return legal, rejected
    finally:
        footprint.SetOrientationDegrees(original)


def _pad_escape_audits(
    board: pcbnew.BOARD,
    contract: dict[str, object],
    *,
    clearance_mm: float,
    edge_clearance_mm: float,
    via_diameter_mm: float,
    trace_width_mm: float,
) -> list[dict[str, object]]:
    power_nodes = _power_nodes(contract)
    outline = _board_outline(board)
    clearance = pcbnew.FromMM(clearance_mm)
    edge_clearance = pcbnew.FromMM(edge_clearance_mm)
    via_diameter = pcbnew.FromMM(via_diameter_mm)
    trace_width = pcbnew.FromMM(trace_width_mm)
    audits: list[dict[str, object]] = []
    for footprint in sorted(board.GetFootprints(), key=lambda item: str(item.GetReference())):
        current = float(footprint.GetOrientationDegrees()) % 360.0
        for pad in sorted(footprint.Pads(), key=lambda item: str(item.GetNumber())):
            required = (
                pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                and (str(footprint.GetReference()), str(pad.GetNumber())) in power_nodes
            )
            if not required:
                continue
            rotations: dict[str, object] = {}
            all_legal: list[dict[str, object]] = []
            for rotation in (0.0, 90.0, 180.0, 270.0):
                legal, rejected = _rotation_candidates(
                    board,
                    pad,
                    outline=outline,
                    rotation=rotation,
                    clearance=clearance,
                    edge_clearance=edge_clearance,
                    via_diameter=via_diameter,
                    trace_width=trace_width,
                )
                record = {
                    "rotation_deg": rotation,
                    "legal_candidates": legal,
                    "rejected_reason_counts": dict(sorted(rejected.items())),
                }
                rotations[str(int(rotation))] = record
                all_legal.extend({**item, "rotation_deg": rotation} for item in legal)
            current_key = str(int(round(current / 90.0) * 90) % 360)
            current_record = rotations.get(current_key, {"legal_candidates": []})
            best_rotation = min(
                (float(key) for key, value in rotations.items() if value["legal_candidates"]),
                key=lambda value: (-len(rotations[str(int(value))]["legal_candidates"]), value),
                default=None,
            )
            audits.append(
                {
                    "pad_id": f"{footprint.GetReference()}.{pad.GetNumber()}",
                    "net_name": str(pad.GetNetname()),
                    "required": True,
                    "current_rotation_deg": current,
                    "current_legal_candidates": current_record["legal_candidates"],
                    "any_rotation_legal_candidates": all_legal,
                    "recommended_rotation_deg": best_rotation,
                    "rotations": rotations,
                    "escape_envelope": {
                        "clearance_mm": clearance_mm,
                        "edge_clearance_mm": edge_clearance_mm,
                        "via_diameter_mm": via_diameter_mm,
                        "trace_width_mm": trace_width_mm,
                    },
                }
            )
    return audits


def _footprint_poses(board: pcbnew.BOARD) -> list[dict[str, object]]:
    return [
        {
            "reference": str(footprint.GetReference()),
            "x_mm": _position(footprint)[0],
            "y_mm": _position(footprint)[1],
            "rotation_deg": round(float(footprint.GetOrientationDegrees()) % 360.0, 6),
            "side": "back" if footprint.IsFlipped() else "front",
        }
        for footprint in sorted(board.GetFootprints(), key=lambda item: str(item.GetReference()))
    ]


def _current_escape_state(
    board: pcbnew.BOARD,
    contract: dict[str, object],
    *,
    outline: pcbnew.SHAPE_POLY_SET,
    clearance: int,
    edge_clearance: int,
    via_diameter: int,
    trace_width: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    required_nodes = _power_nodes(contract)
    legal: list[str] = []
    blocked: list[str] = []
    for footprint in sorted(board.GetFootprints(), key=lambda item: str(item.GetReference())):
        reference = str(footprint.GetReference())
        rotation = float(footprint.GetOrientationDegrees()) % 360.0
        for pad in sorted(footprint.Pads(), key=lambda item: str(item.GetNumber())):
            pad_id = f"{reference}.{pad.GetNumber()}"
            if not (
                pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                and (reference, str(pad.GetNumber())) in required_nodes
            ):
                continue
            candidates, _rejected = _rotation_candidates(
                board,
                pad,
                outline=outline,
                rotation=rotation,
                clearance=clearance,
                edge_clearance=edge_clearance,
                via_diameter=via_diameter,
                trace_width=trace_width,
            )
            (legal if candidates else blocked).append(pad_id)
    return tuple(sorted(legal)), tuple(sorted(blocked))


def _pose_is_legal(
    board: pcbnew.BOARD,
    footprint: pcbnew.FOOTPRINT,
    outline: pcbnew.SHAPE_POLY_SET,
    spacing: int,
) -> bool:
    box = footprint.GetBoundingBox()
    corners = (
        pcbnew.VECTOR2I(box.GetX(), box.GetY()),
        pcbnew.VECTOR2I(box.GetRight(), box.GetY()),
        pcbnew.VECTOR2I(box.GetRight(), box.GetBottom()),
        pcbnew.VECTOR2I(box.GetX(), box.GetBottom()),
    )
    if not all(outline.Contains(point) for point in corners):
        return False
    footprint_uuid = _uuid(footprint)
    inflated = box.GetInflated(spacing)
    return not any(
        inflated.Intersects(other.GetBoundingBox())
        for other in board.GetFootprints()
        if _uuid(other) != footprint_uuid
    )


def _repair_root_cause(audits: list[dict[str, object]]) -> str:
    reasons: Counter[str] = Counter()
    for audit in audits:
        if audit.get("current_legal_candidates"):
            continue
        rotations = audit.get("rotations", {})
        if not isinstance(rotations, dict):
            continue
        for rotation in rotations.values():
            if isinstance(rotation, dict):
                counts = rotation.get("rejected_reason_counts", {})
                if isinstance(counts, dict):
                    reasons.update({str(key): int(value) for key, value in counts.items()})
    families = set()
    if any(key.startswith("same_footprint_") for key in reasons):
        families.add("intrinsic_footprint_escape")
    if any(key.startswith("neighbor_") for key in reasons):
        families.add("neighbor_placement")
    if reasons.get("board_edge"):
        families.add("board_edge")
    if not families:
        return "unknown"
    if len(families) == 1:
        return next(iter(families))
    return "mixed"


def _bounded_placement_repair_search(
    board: pcbnew.BOARD,
    contract: dict[str, object],
    audits: list[dict[str, object]],
    *,
    clearance_mm: float,
    edge_clearance_mm: float,
    via_diameter_mm: float,
    trace_width_mm: float,
    translation_step_mm: float = 0.5,
    maximum_translation_steps: int = 4,
    neighbor_limit: int = 4,
    proposal_limit: int = 64,
) -> dict[str, object]:
    poses_before = _footprint_poses(board)
    pose_fingerprint = _fp(poses_before)
    blocked_before = tuple(
        sorted(
            str(audit["pad_id"])
            for audit in audits
            if audit.get("required") is True and not audit.get("current_legal_candidates")
        )
    )
    required_count = sum(audit.get("required") is True for audit in audits)
    legal_before = required_count - len(blocked_before)
    policy = {
        "translation_step_mm": translation_step_mm,
        "maximum_translation_steps": maximum_translation_steps,
        "allowed_rotation_deg": [0.0, 90.0, 180.0, 270.0],
        "neighbor_limit": neighbor_limit,
        "proposal_limit": proposal_limit,
        "pair_move_limit": 0,
        "automatic_apply_authorized": False,
    }
    if not blocked_before:
        return {
            "performed": True,
            "source_pose_fingerprint": pose_fingerprint,
            "policy": policy,
            "root_cause": "not_applicable",
            "base_required_pad_count": required_count,
            "base_legal_pad_count": legal_before,
            "base_blocked_pads": [],
            "evaluated_proposal_count": 0,
            "geometry_rejected_proposal_count": 0,
            "improving_candidates": [],
            "terminal_reason": "not_required",
        }

    footprint_by_ref = {
        str(footprint.GetReference()): footprint for footprint in board.GetFootprints()
    }
    blocked_references = tuple(sorted({pad_id.split(".", 1)[0] for pad_id in blocked_before}))
    target_centers = [_position(footprint_by_ref[reference]) for reference in blocked_references]
    movable_neighbor_prefixes = ("C", "D", "L", "Q", "R", "U")
    neighbors = tuple(
        reference
        for _distance, reference in sorted(
            (
                min(
                    math.hypot(_position(footprint)[0] - x, _position(footprint)[1] - y)
                    for x, y in target_centers
                ),
                reference,
            )
            for reference, footprint in footprint_by_ref.items()
            if reference not in blocked_references
            and reference.startswith(movable_neighbor_prefixes)
        )[:neighbor_limit]
    )
    clauses: list[dict[str, object]] = []
    for reference in blocked_references:
        footprint = footprint_by_ref[reference]
        current_rotation = float(footprint.GetOrientationDegrees()) % 360.0
        for step in range(1, maximum_translation_steps + 1):
            distance = round(translation_step_mm * step, 6)
            for delta_x, delta_y in (
                (-distance, 0.0),
                (distance, 0.0),
                (0.0, -distance),
                (0.0, distance),
            ):
                clauses.append(
                    {
                        "reference": reference,
                        "kind": "translate",
                        "delta_x_mm": delta_x,
                        "delta_y_mm": delta_y,
                    }
                )
        for rotation in (0.0, 90.0, 180.0, 270.0):
            if rotation != current_rotation:
                clauses.append({"reference": reference, "kind": "rotate", "rotation_deg": rotation})
    for reference in neighbors:
        for step in range(1, min(maximum_translation_steps, 2) + 1):
            distance = round(translation_step_mm * step, 6)
            for delta_x, delta_y in (
                (-distance, 0.0),
                (distance, 0.0),
                (0.0, -distance),
                (0.0, distance),
            ):
                clauses.append(
                    {
                        "reference": reference,
                        "kind": "translate",
                        "delta_x_mm": delta_x,
                        "delta_y_mm": delta_y,
                    }
                )

    outline = _board_outline(board)
    clearance = pcbnew.FromMM(clearance_mm)
    edge_clearance = pcbnew.FromMM(edge_clearance_mm)
    via_diameter = pcbnew.FromMM(via_diameter_mm)
    trace_width = pcbnew.FromMM(trace_width_mm)
    evaluated = 0
    geometry_rejected = 0
    improving: list[dict[str, object]] = []
    for clause in clauses[:proposal_limit]:
        evaluated += 1
        footprint = footprint_by_ref[str(clause["reference"])]
        original_position = footprint.GetPosition()
        original_rotation = float(footprint.GetOrientationDegrees())
        try:
            if clause["kind"] == "translate":
                footprint.SetPosition(
                    pcbnew.VECTOR2I(
                        original_position.x + pcbnew.FromMM(float(clause["delta_x_mm"])),
                        original_position.y + pcbnew.FromMM(float(clause["delta_y_mm"])),
                    )
                )
            else:
                footprint.SetOrientationDegrees(float(clause["rotation_deg"]))
            if not _pose_is_legal(board, footprint, outline, clearance):
                geometry_rejected += 1
                continue
            legal, blocked = _current_escape_state(
                board,
                contract,
                outline=outline,
                clearance=clearance,
                edge_clearance=edge_clearance,
                via_diameter=via_diameter,
                trace_width=trace_width,
            )
            if len(legal) <= legal_before:
                continue
            payload = {
                "source_pose_fingerprint": pose_fingerprint,
                "clause": clause,
                "legal_required_pads": list(legal),
                "blocked_required_pads": list(blocked),
            }
            fingerprint = _fp(payload)
            improving.append(
                {
                    "candidate_id": fingerprint[:12],
                    "candidate_fingerprint": fingerprint,
                    "proposal_kind": "single",
                    "clause": clause,
                    "legal_required_pad_count": len(legal),
                    "legal_required_pads": list(legal),
                    "blocked_required_pads": list(blocked),
                    "legal_gain": len(legal) - legal_before,
                    "unchanged_reference_count": len(poses_before) - 1,
                    "automatic_apply_authorized": False,
                }
            )
        finally:
            footprint.SetPosition(original_position)
            footprint.SetOrientationDegrees(original_rotation)

    if _fp(_footprint_poses(board)) != pose_fingerprint:
        raise RuntimeError("bounded placement search did not restore the source poses")
    improving.sort(
        key=lambda item: (
            -int(item["legal_gain"]),
            len(item["blocked_required_pads"]),
            str(item["candidate_fingerprint"]),
        )
    )
    return {
        "performed": True,
        "source_pose_fingerprint": pose_fingerprint,
        "policy": policy,
        "root_cause": _repair_root_cause(audits),
        "base_required_pad_count": required_count,
        "base_legal_pad_count": legal_before,
        "base_blocked_pads": list(blocked_before),
        "blocked_references": list(blocked_references),
        "neighbor_references_considered": list(neighbors),
        "evaluated_proposal_count": evaluated,
        "geometry_rejected_proposal_count": geometry_rejected,
        "improving_candidates": improving,
        "terminal_reason": (
            "improving_candidate_found" if improving else "no_improving_bounded_placement_candidate"
        ),
    }


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _crosses(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    a, b = first
    c, d = second
    if len({a, b, c, d}) < 4:
        return False
    return (
        _orientation(a, b, c) * _orientation(a, b, d) < 0
        and _orientation(c, d, a) * _orientation(c, d, b) < 0
    )


def _placement_metrics(board: pcbnew.BOARD, contract: dict[str, object]) -> dict[str, object]:
    pad_positions = {
        (str(fp.GetReference()), str(pad.GetNumber())): _position(pad)
        for fp in board.GetFootprints()
        for pad in fp.Pads()
    }
    corridors: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    raw_nets = contract.get("nets", [])
    if isinstance(raw_nets, list):
        for raw in raw_nets:
            if not isinstance(raw, dict):
                continue
            nodes = raw.get("nodes", [])
            points = (
                [
                    pad_positions[(str(node[0]), str(node[1]))]
                    for node in nodes
                    if isinstance(node, list)
                    and len(node) == 2
                    and (str(node[0]), str(node[1])) in pad_positions
                ]
                if isinstance(nodes, list)
                else []
            )
            if len(points) >= 2:
                corridors.extend(
                    (str(raw.get("name", "")), points[0], point) for point in points[1:]
                )
    crossings = sum(
        _crosses((first[1], first[2]), (second[1], second[2]))
        for index, first in enumerate(corridors)
        for second in corridors[index + 1 :]
        if first[0] != second[0]
    )
    total_manhattan = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for _net, a, b in corridors)
    density = Counter((int(x // 5.0), int(y // 5.0)) for x, y in pad_positions.values())
    bbox = board.GetBoardEdgesBoundingBox()
    left, top, right, bottom = map(
        _mm, (bbox.GetX(), bbox.GetY(), bbox.GetRight(), bbox.GetBottom())
    )
    edge_items: dict[str, float] = {}
    for fp in board.GetFootprints():
        reference = str(fp.GetReference())
        if not (reference.startswith("J") or reference.startswith("SW")):
            continue
        x, y = _position(fp)
        edge_items[reference] = round(min(x - left, right - x, y - top, bottom - y), 6)
    ic_positions = [
        _position(fp) for fp in board.GetFootprints() if str(fp.GetReference()).startswith("U")
    ]
    decoupling: dict[str, float | None] = {}
    for fp in board.GetFootprints():
        reference = str(fp.GetReference())
        if reference.startswith("C"):
            x, y = _position(fp)
            decoupling[reference] = (
                round(min(math.hypot(x - ux, y - uy) for ux, uy in ic_positions), 6)
                if ic_positions
                else None
            )
    return {
        "estimated_unrouted_corridor_count": len(corridors),
        "estimated_crossing_count": crossings,
        "total_manhattan_corridor_length_mm": round(total_manhattan, 6),
        "maximum_pads_per_5mm_cell": max(density.values(), default=0),
        "edge_interface_anchor_distance_mm": dict(sorted(edge_items.items())),
        "decoupling_to_nearest_ic_mm": dict(sorted(decoupling.items())),
        "scope": "placement-only straight-corridor estimate; not a routing proof",
    }


def _board_identity(board: pcbnew.BOARD) -> dict[str, object]:
    poses = _footprint_poses(board)
    pad_bindings = sorted(
        (
            {
                "reference": str(footprint.GetReference()),
                "pad_number": str(pad.GetNumber()),
                "net_name": str(pad.GetNetname()),
                "attribute": int(pad.GetAttribute()),
            }
            for footprint in board.GetFootprints()
            for pad in footprint.Pads()
        ),
        key=lambda item: (
            str(item["reference"]),
            str(item["pad_number"]),
            str(item["net_name"]),
            int(item["attribute"]),
        ),
    )
    edge_records: list[dict[str, object]] = []
    for drawing in board.GetDrawings():
        if drawing.GetLayer() != pcbnew.Edge_Cuts:
            continue
        box = drawing.GetBoundingBox()
        record: dict[str, object] = {
            "type": type(drawing).__name__,
            "x_mm": _mm(box.GetX()),
            "y_mm": _mm(box.GetY()),
            "right_mm": _mm(box.GetRight()),
            "bottom_mm": _mm(box.GetBottom()),
        }
        if hasattr(drawing, "GetStart") and hasattr(drawing, "GetEnd"):
            start, end = drawing.GetStart(), drawing.GetEnd()
            record["start_mm"] = [_mm(start.x), _mm(start.y)]
            record["end_mm"] = [_mm(end.x), _mm(end.y)]
        edge_records.append(record)
    edge_records.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return {
        "footprint_pose_fingerprint": _fp(poses),
        "pad_binding_fingerprint": _fp(pad_bindings),
        "edge_geometry_fingerprint": _fp(edge_records),
        "footprint_count": len(poses),
        "pad_count": len(pad_bindings),
        "edge_item_count": len(edge_records),
    }


def _reference_continuity_observation(
    board: pcbnew.BOARD, contract: dict[str, object]
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
    base = {
        "authority": "sampled-advisory-v1",
        "reference_net_names": list(reference_nets),
        "copper_layer_count": int(board.GetCopperLayerCount()),
        "automatic_multilayer_pass_prohibited": True,
        "exact_pass_authorized": False,
        "sample_count_per_segment": 5,
        "maximum_transition_stitch_distance_mm": 2.0,
    }
    if board.GetCopperLayerCount() != 2:
        return {
            **base,
            "disposition": "unsupported_stackup_unverified",
            "signal_segment_count": 0,
            "sample_supported_segment_count": 0,
            "sample_unsupported_segment_count": 0,
            "signal_transition_count": 0,
            "transition_without_nearby_reference_via_count": 0,
            "findings": [],
        }
    if not reference_nets:
        return {
            **base,
            "disposition": "reference_net_undeclared_unverified",
            "signal_segment_count": 0,
            "sample_supported_segment_count": 0,
            "sample_unsupported_segment_count": 0,
            "signal_transition_count": 0,
            "transition_without_nearby_reference_via_count": 0,
            "findings": [],
        }

    fills: dict[int, list[pcbnew.SHAPE_POLY_SET]] = {pcbnew.F_Cu: [], pcbnew.B_Cu: []}
    for zone in board.Zones():
        layer = zone.GetLayer()
        if layer in fills and str(zone.GetNetname()) in reference_nets:
            filled = zone.GetFilledPolysList(layer)
            if zone.HasFilledPolysForLayer(layer) and filled.OutlineCount():
                fills[layer].append(filled)
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
    for track in signal_segments:
        signal_layer = track.GetLayer()
        reference_layer = pcbnew.B_Cu if signal_layer == pcbnew.F_Cu else pcbnew.F_Cu
        start, end = track.GetStart(), track.GetEnd()
        samples = [
            pcbnew.VECTOR2I(
                int(start.x + (end.x - start.x) * step / 4),
                int(start.y + (end.y - start.y) * step / 4),
            )
            for step in range(5)
        ]
        covered = bool(fills[reference_layer]) and all(
            any(fill.Contains(point) for fill in fills[reference_layer]) for point in samples
        )
        if covered:
            supported += 1
        else:
            unsupported += 1
            if len(findings) < 200:
                findings.append(
                    {
                        "kind": "sampled_reference_discontinuity",
                        "track_id": _semantic_base(track),
                        "net_name": str(track.GetNetname()),
                        "signal_layer": board.GetLayerName(signal_layer),
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
                        "via_id": _semantic_base(via),
                        "net_name": str(via.GetNetname()),
                        "position_mm": list(_position(via)),
                    }
                )
    disposition = (
        "advisory_discontinuities_observed"
        if unsupported or unstitched
        else "sampled_support_observed_exactly_unverified"
    )
    return {
        **base,
        "disposition": disposition,
        "signal_segment_count": len(signal_segments),
        "sample_supported_segment_count": supported,
        "sample_unsupported_segment_count": unsupported,
        "signal_transition_count": len(signal_vias),
        "transition_without_nearby_reference_via_count": unstitched,
        "findings": findings,
        "scope": (
            "Five centerline samples per segment and a 2 mm transition-via proximity model; "
            "this is diagnostic evidence, never exact reference-continuity acceptance."
        ),
    }


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
    board = pcbnew.LoadBoard(str(board_path))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise TypeError("case contract must be a JSON object")
    by_uuid, semantic_by_uuid = _inventory(board)
    component_by_uuid = _connected_component_ids(board, by_uuid, semantic_by_uuid)
    items = []
    for uuid in sorted(by_uuid):
        item = by_uuid[uuid]
        record: dict[str, object] = {
            "uuid": uuid,
            "semantic_item_id": semantic_by_uuid[uuid],
            "connected_component_id": component_by_uuid[uuid],
            "kind": _kind(item),
            "net_name": str(item.GetNetname()) if hasattr(item, "GetNetname") else "",
            "layer": _layer(item),
            "position_mm": list(_position(item)),
        }
        if isinstance(item, pcbnew.PAD):
            record["reference"] = str(item.GetParentFootprint().GetReference())
            record["pad_number"] = str(item.GetNumber())
        items.append(record)
    zones = []
    for zone in board.Zones():
        layer = zone.GetLayer()
        filled = zone.GetFilledPolysList(layer)
        zones.append(
            {
                "semantic_item_id": semantic_by_uuid[_uuid(zone)],
                "net_name": str(zone.GetNetname()),
                "layer": str(zone.GetLayerName()),
                "filled": bool(zone.HasFilledPolysForLayer(layer)),
                "filled_outline_count": int(filled.OutlineCount()),
                "filled_hole_count": sum(
                    filled.HoleCount(index) for index in range(filled.OutlineCount())
                ),
                "filled_area_mm2": round(abs(float(filled.Area())) / 1_000_000_000_000.0, 6),
                "fragmented": filled.OutlineCount() > 1,
            }
        )
    pad_escape_audits = (
        []
        if skip_placement_audit
        else _pad_escape_audits(
            board,
            contract,
            clearance_mm=clearance_mm,
            edge_clearance_mm=edge_clearance_mm,
            via_diameter_mm=via_diameter_mm,
            trace_width_mm=trace_width_mm,
        )
    )
    placement_repair_search = (
        {
            "performed": False,
            "terminal_reason": "placement_audit_skipped",
            "improving_candidates": [],
        }
        if skip_placement_audit
        else _bounded_placement_repair_search(
            board,
            contract,
            pad_escape_audits,
            clearance_mm=clearance_mm,
            edge_clearance_mm=edge_clearance_mm,
            via_diameter_mm=via_diameter_mm,
            trace_width_mm=trace_width_mm,
        )
    )
    payload = {
        "schema": "pcbsmith-kicad-board-physical-observation-v1",
        "board_file": str(board_path),
        "copper_layer_count": int(board.GetCopperLayerCount()),
        "board_identity": _board_identity(board),
        "items": items,
        "filled_zone_evidence": zones,
        "pad_escape_audits": pad_escape_audits,
        "placement_repair_search": placement_repair_search,
        "placement_audit_performed": not skip_placement_audit,
        "placement_metrics": _placement_metrics(board, contract),
        "reference_continuity": _reference_continuity_observation(board, contract),
        "acceptance_boundary": (
            "Read-only geometry and KiCad connectivity evidence. Legal escapes are conservative "
            "via-and-segment envelopes, not routed-copper, current, thermal, or SI proof."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
