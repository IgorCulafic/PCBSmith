"""Integrate exact final fill while protecting every non-fill native object."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pcbsmith.kicad.final_fill_adapter import refill_and_read_kicad_board, zone_intent_node
from pcbsmith.kicad.library import parse_sexpr, serialize_sexpr
from pcbsmith.kicad.native_edits import atom, child, children
from pcbsmith.operations.file_transaction import atomic_write

FILL_FIELDS = {"filled_polygon", "fill_segments"}


def _fill_fields(zone: list[Any]) -> list[Any]:
    return [item for item in zone if isinstance(item, list) and item and item[0] in FILL_FIELDS]


def _intent(zone: list[Any]) -> list[Any]:
    return zone_intent_node(zone)


def merge_verified_fill(
    payload: bytes, native_filled: bytes, allowed_zone_ids: tuple[str, ...]
) -> tuple[bytes, dict[str, Any]]:
    tree = parse_sexpr(payload.decode("utf-8"))
    filled = parse_sexpr(native_filled.decode("utf-8"))
    original_zones = {atom(child(z, "uuid")[1]): z for z in children(tree, "zone")}
    native_zones = {atom(child(z, "uuid")[1]): z for z in children(filled, "zone")}
    if set(original_zones) != set(native_zones) or not set(allowed_zone_ids) <= set(original_zones):
        raise ValueError("zone refill identity inventory is incomplete or changed")
    changed: list[str] = []
    closure: dict[str, Any] = {}
    for identity, zone in original_zones.items():
        new = native_zones[identity]
        if serialize_sexpr(_intent(zone)) != serialize_sexpr(_intent(new)):
            raise ValueError(f"native refill changed zone intent: {identity}")
        before, after = _fill_fields(zone), _fill_fields(new)
        if serialize_sexpr(before) == serialize_sexpr(after) and ("yes" in child(zone, "fill")) == (
            "yes" in child(new, "fill")
        ):
            continue
        if identity not in allowed_zone_ids:
            raise ValueError(f"native refill changed an undeclared zone: {identity}")
        changed.append(identity)
        zone[:] = _intent(zone) + copy.deepcopy(after)
        child(zone, "fill")[:] = copy.deepcopy(child(new, "fill"))
        closure[identity] = {
            "net": atom(child(zone, "net")[1]),
            "layer": atom(child(zone, "layer")[1]),
            "whole_zone_dependency": True,
            "outline": [serialize_sexpr(p) for p in children(zone, "polygon")],
            "filled_region_count": len(children(zone, "filled_polygon")),
        }
    result = (serialize_sexpr(tree) + "\n").encode() if changed else payload
    return result, {
        "changed_zone_ids": sorted(changed),
        "dependency_closure": closure,
        "policy": "whole declared zone fill; all non-fill objects preserved",
    }


def refill_native_edit(
    board: Path, output: Path, allowed_zone_ids: tuple[str, ...]
) -> tuple[bytes, dict[str, Any]]:
    raw, snapshot = refill_and_read_kicad_board(board, output / "native")
    atomic_write(output / "snapshot.json", (snapshot.model_dump_json(indent=2) + "\n").encode())
    if snapshot.stale_fill or not snapshot.zone_intent_unchanged:
        raise ValueError("final-fill snapshot is stale or changed zone intent")
    payload, evidence = merge_verified_fill(board.read_bytes(), raw.read_bytes(), allowed_zone_ids)
    atomic_write(output / "closure.json", (json.dumps(evidence, indent=2) + "\n").encode())
    return payload, evidence
