"""Evidence-bound evaluation of a saved local-routing candidate."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import Field

from pcbsmith.kicad.library import QuotedString, SExpr, parse_sexpr, serialize_sexpr
from pcbsmith.local_routing_repair import (
    RoutingCandidateMetrics,
    RoutingRepairRegion,
    SelectedRoutingDomain,
)
from pcbsmith.semantic_ir import SemanticIrModel


class SavedRouteObject(SemanticIrModel):
    schema_id: Literal["pcbsmith-saved-route-object"] = "pcbsmith-saved-route-object"
    schema_version: Literal[1] = 1
    object_id: str
    kind: Literal["segment", "via"]
    net_name: str
    content_sha256: str
    width_mm: float | None = Field(default=None, gt=0)
    length_mm: float = Field(ge=0)


class SavedRoutingSnapshot(SemanticIrModel):
    schema_id: Literal["pcbsmith-saved-routing-snapshot"] = "pcbsmith-saved-routing-snapshot"
    schema_version: Literal[1] = 1
    board_sha256: str
    non_routing_sha256: str
    objects: tuple[SavedRouteObject, ...]


def extract_saved_routing_snapshot(board: Path) -> SavedRoutingSnapshot:
    payload = board.read_bytes()
    root = parse_sexpr(payload.decode("utf-8"))
    net_names = {
        _atom(item[1]): _atom(item[2])
        for item in root
        if isinstance(item, list) and _head(item) == "net" and len(item) >= 3
    }
    objects: list[SavedRouteObject] = []
    for index, item in enumerate(root):
        if not isinstance(item, list):
            continue
        kind = _head(item)
        if kind not in {"segment", "via"}:
            continue
        uuid = _child_atom(item, "uuid")
        object_id = f"{kind}:{uuid or index}"
        net_value = _child_atom(item, "net") or ""
        net_name = net_names.get(net_value, net_value)
        rendered = serialize_sexpr(item).encode("utf-8")
        if kind == "segment":
            start = _xy(item, "start")
            end = _xy(item, "end")
            width = float(_child_atom(item, "width") or 0)
            length = math.hypot(end[0] - start[0], end[1] - start[1])
        else:
            width = None
            length = 0.0
        objects.append(
            SavedRouteObject(
                object_id=object_id,
                kind=kind,
                net_name=net_name,
                content_sha256=hashlib.sha256(rendered).hexdigest(),
                width_mm=width,
                length_mm=round(length, 6),
            )
        )
    non_routing = [item for item in root if _head(item) not in {"segment", "via"}]
    return SavedRoutingSnapshot(
        board_sha256=hashlib.sha256(payload).hexdigest(),
        non_routing_sha256=hashlib.sha256(serialize_sexpr(non_routing).encode("utf-8")).hexdigest(),
        objects=tuple(sorted(objects, key=lambda item: item.object_id)),
    )


def evaluate_saved_routing_candidate(
    *,
    source_board: Path,
    candidate_board: Path,
    domain: SelectedRoutingDomain,
    region: RoutingRepairRegion,
    drc_report: Path,
    required_widths_mm: dict[str, float],
    return_failure_count: int,
    candidate_id: str,
    engine_id: str,
    retained_directory: str,
) -> RoutingCandidateMetrics:
    """Derive routing metrics from exact saved-board and KiCad report evidence."""

    source = extract_saved_routing_snapshot(source_board)
    candidate = extract_saved_routing_snapshot(candidate_board)
    source_by_id = {item.object_id: item for item in source.objects}
    candidate_by_id = {item.object_id: item for item in candidate.objects}
    protected = dict(domain.protected_object_fingerprints)
    for object_id, expected in protected.items():
        actual = source_by_id.get(object_id)
        if actual is None or actual.content_sha256 != expected:
            raise ValueError(f"stale protected routing fingerprint: {object_id}")
    changed = {
        object_id
        for object_id in set(source_by_id) | set(candidate_by_id)
        if source_by_id.get(object_id) != candidate_by_id.get(object_id)
    }
    mutable = set(domain.mutable_object_ids)
    protected_change_count = sum(object_id not in mutable for object_id in changed)
    selected_nets = set(domain.net_names)
    unrelated_net_change_count = sum(
        _changed_net(object_id, source_by_id, candidate_by_id) not in selected_nets
        for object_id in changed
    )

    drc = json.loads(drc_report.read_text(encoding="utf-8"))
    violations = drc.get("violations")
    unconnected = drc.get("unconnected_items")
    parity = drc.get("schematic_parity")
    if not all(isinstance(section, list) for section in (violations, unconnected, parity)):
        raise ValueError("KiCad DRC report lacks list-valued exact sections")
    width_failure_count = sum(
        item.kind == "segment"
        and item.net_name in selected_nets
        and item.width_mm is not None
        and item.width_mm + 1e-9 < required_widths_mm[item.net_name]
        for item in candidate.objects
        if item.net_name in required_widths_mm
    )
    selected_segments = tuple(
        item
        for item in candidate.objects
        if item.kind == "segment" and item.net_name in selected_nets
    )
    selected_vias = tuple(
        item for item in candidate.objects if item.kind == "via" and item.net_name in selected_nets
    )
    craft_penalty = float(_non_octilinear_count(candidate_board, selected_nets))
    return RoutingCandidateMetrics(
        candidate_id=candidate_id,
        engine_id=engine_id,
        region=region,
        drc_violation_count=len(violations) + len(parity),
        open_count=len(unconnected),
        width_failure_count=width_failure_count,
        return_failure_count=return_failure_count,
        protected_change_count=protected_change_count,
        unrelated_net_change_count=unrelated_net_change_count,
        craft_penalty=craft_penalty,
        route_length_mm=round(sum(item.length_mm for item in selected_segments), 6),
        via_count=len(selected_vias),
        retained_directory=retained_directory,
    )


def _changed_net(
    object_id: str,
    source: dict[str, SavedRouteObject],
    candidate: dict[str, SavedRouteObject],
) -> str:
    item = candidate.get(object_id) or source.get(object_id)
    return item.net_name if item is not None else ""


def _non_octilinear_count(board: Path, selected_nets: set[str]) -> int:
    root = parse_sexpr(board.read_text(encoding="utf-8"))
    net_names = {
        _atom(item[1]): _atom(item[2])
        for item in root
        if isinstance(item, list) and _head(item) == "net" and len(item) >= 3
    }
    count = 0
    for item in root:
        if not isinstance(item, list):
            continue
        net_value = _child_atom(item, "net") or ""
        if _head(item) != "segment" or net_names.get(net_value, net_value) not in selected_nets:
            continue
        start = _xy(item, "start")
        end = _xy(item, "end")
        dx = abs(end[0] - start[0])
        dy = abs(end[1] - start[1])
        if dx > 1e-9 and dy > 1e-9 and not math.isclose(dx, dy, abs_tol=1e-6):
            count += 1
    return count


def _xy(node: list[SExpr], name: str) -> tuple[float, float]:
    child = next(item for item in node if isinstance(item, list) and _head(item) == name)
    return (float(_atom(child[1])), float(_atom(child[2])))


def _child_atom(node: list[SExpr], name: str) -> str | None:
    child = next((item for item in node if isinstance(item, list) and _head(item) == name), None)
    return _atom(child[1]) if child is not None and len(child) >= 2 else None


def _head(node: object) -> str:
    return _atom(node[0]) if isinstance(node, list) and node else ""


def _atom(value: object) -> str:
    return value.value if isinstance(value, QuotedString) else str(value)


__all__ = [
    "SavedRouteObject",
    "SavedRoutingSnapshot",
    "evaluate_saved_routing_candidate",
    "extract_saved_routing_snapshot",
]
