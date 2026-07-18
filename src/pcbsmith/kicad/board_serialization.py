"""Canonical, schema-driven snapshots for the neutral KiCad board IR.

These helpers intentionally serialize the real frozen ``BoardLayout`` and
``BoardNetlist`` dataclasses.  They do not render KiCad text or attach any
placement, routing, or verification semantics to the retained values.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from pydantic import TypeAdapter

from pcbsmith.kicad.board import BoardLayout, BoardNetlist

_T = TypeVar("_T")
_LAYOUT_ADAPTER = TypeAdapter(BoardLayout)
_NETLIST_ADAPTER = TypeAdapter(BoardNetlist)


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _load_json(snapshot_json: str, name: str) -> Any:
    try:
        return json.loads(
            snapshot_json,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"{name} snapshot contains non-finite {value}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{name} snapshot JSON is invalid: {error}") from error


def _canonical_snapshot(value: _T, adapter: TypeAdapter[_T]) -> str:
    return _canonical_json(adapter.dump_python(value, mode="json"))


def _parse_snapshot(snapshot_json: str, name: str, adapter: TypeAdapter[_T]) -> _T:
    payload = _load_json(snapshot_json, name)
    try:
        parsed = adapter.validate_python(payload)
    except ValueError as error:
        raise ValueError(f"{name} snapshot does not parse as its real schema: {error}") from error
    try:
        canonical = _canonical_snapshot(parsed, adapter)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} snapshot is not canonically serializable: {error}") from error
    if snapshot_json != canonical:
        raise ValueError(f"{name} snapshot must equal exact canonical schema serialization")
    return parsed


def _fingerprint(schema_id: str, field_name: str, value: Any) -> str:
    payload = {
        "schema_id": schema_id,
        "schema_version": 1,
        field_name: value,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_board_layout_snapshot_json(layout: BoardLayout) -> str:
    """Serialize every real ``BoardLayout`` field to canonical JSON."""

    return _canonical_snapshot(layout, _LAYOUT_ADAPTER)


def parse_canonical_board_layout_snapshot(snapshot_json: str) -> BoardLayout:
    """Parse a layout snapshot only when it is already exact canonical JSON."""

    return _parse_snapshot(snapshot_json, "BoardLayout", _LAYOUT_ADAPTER)


def board_layout_snapshot_fingerprint(snapshot_json: str) -> str:
    """Fingerprint a validated layout snapshot with the established v1 identity."""

    layout = parse_canonical_board_layout_snapshot(snapshot_json)
    return _fingerprint(
        "pcbsmith-board-layout-schema-snapshot",
        "layout",
        _LAYOUT_ADAPTER.dump_python(layout, mode="json"),
    )


def canonical_board_netlist_snapshot_json(netlist: BoardNetlist) -> str:
    """Serialize every real ``BoardNetlist`` field to canonical JSON."""

    return _canonical_snapshot(netlist, _NETLIST_ADAPTER)


def parse_canonical_board_netlist_snapshot(snapshot_json: str) -> BoardNetlist:
    """Parse a netlist snapshot only when it is already exact canonical JSON."""

    return _parse_snapshot(snapshot_json, "BoardNetlist", _NETLIST_ADAPTER)


def board_netlist_snapshot_fingerprint(snapshot_json: str) -> str:
    """Fingerprint a validated netlist snapshot with the established v1 identity."""

    netlist = parse_canonical_board_netlist_snapshot(snapshot_json)
    return _fingerprint(
        "pcbsmith-board-netlist-schema-snapshot",
        "netlist",
        _NETLIST_ADAPTER.dump_python(netlist, mode="json"),
    )
