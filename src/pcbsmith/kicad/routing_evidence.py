"""Saved-board routing evidence and fail-closed release classification.

This module deliberately distinguishes copper *presence* from electrical route
completion.  Segment/via/zone inspection is an inexpensive tripwire.  KiCad
connectivity and DRC remain the final physical authority.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class RoutingArtifactState(StrEnum):
    INDETERMINATE = "indeterminate"
    PLACEMENT_ONLY = "placement_only"
    PARTIALLY_ROUTED = "partially_routed"
    ROUTED_CANDIDATE = "routed_candidate"


class SavedBoardRoutingEvidence(SemanticIrModel):
    """Objective copper inventory extracted from one saved KiCad board."""

    schema_id: Literal["pcbsmith-saved-board-routing-evidence"] = (
        "pcbsmith-saved-board-routing-evidence"
    )
    schema_version: Literal[1] = 1
    board_file: str
    board_sha256: str
    segment_count: int = Field(ge=0)
    via_count: int = Field(ge=0)
    zone_count: int = Field(ge=0)
    declared_net_count: int = Field(ge=0)
    routable_net_count: int = Field(ge=0)
    segment_net_count: int = Field(ge=0)
    via_net_count: int = Field(ge=0)
    zone_net_count: int = Field(ge=0)
    copper_carrier_net_count: int = Field(ge=0)
    track_net_coverage: float = Field(ge=0.0, le=1.0)
    copper_carrier_net_coverage: float = Field(ge=0.0, le=1.0)
    uncovered_net_names: tuple[str, ...]
    state: RoutingArtifactState
    evidence_fingerprint: str

    @model_validator(mode="after")
    def evidence_is_coherent(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        if self.copper_carrier_net_count > self.routable_net_count:
            raise ValueError("copper carrier count exceeds routable-net count")
        if self.segment_net_count > self.declared_net_count:
            raise ValueError("segment net count exceeds declared-net count")
        if self.via_net_count > self.declared_net_count:
            raise ValueError("via net count exceeds declared-net count")
        if self.zone_net_count > self.declared_net_count:
            raise ValueError("zone net count exceeds declared-net count")
        if self.routable_net_count == 0:
            if self.track_net_coverage != 0.0 or self.copper_carrier_net_coverage != 0.0:
                raise ValueError("net coverage requires at least one routable net")
            if self.state is not RoutingArtifactState.INDETERMINATE:
                raise ValueError("a board without multi-pad nets is indeterminate")
        elif self.segment_count == 0 and self.via_count == 0:
            if self.state is not RoutingArtifactState.PLACEMENT_ONLY:
                raise ValueError("a board without tracks or vias is placement-only")
        elif self.copper_carrier_net_count < self.routable_net_count:
            if self.state is not RoutingArtifactState.PARTIALLY_ROUTED:
                raise ValueError("incomplete carrier coverage is partially routed")
        elif self.state is not RoutingArtifactState.ROUTED_CANDIDATE:
            raise ValueError("complete carrier presence is only a routed candidate")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != fingerprint(payload):
            raise ValueError("saved-board routing evidence fingerprint is stale")
        return self


class KiCadDrcEvidence(SemanticIrModel):
    """Counts retained from one exact KiCad JSON DRC report."""

    schema_id: Literal["pcbsmith-kicad-drc-evidence"] = (
        "pcbsmith-kicad-drc-evidence"
    )
    schema_version: Literal[1] = 1
    report_file: str
    report_sha256: str
    violation_count: int = Field(ge=0)
    unconnected_item_count: int = Field(ge=0)
    schematic_parity_count: int = Field(ge=0)
    clean: bool
    evidence_fingerprint: str

    @model_validator(mode="after")
    def evidence_is_coherent(self) -> Self:
        require_sha256(self.report_sha256, "report_sha256")
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        expected = (
            self.violation_count == 0
            and self.unconnected_item_count == 0
            and self.schematic_parity_count == 0
        )
        if self.clean != expected:
            raise ValueError("KiCad DRC clean disposition is stale")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != fingerprint(payload):
            raise ValueError("KiCad DRC evidence fingerprint is stale")
        return self


def inspect_saved_board_routing(board_file: Path) -> SavedBoardRoutingEvidence:
    """Inspect objective copper carriers in one saved ``.kicad_pcb`` file."""

    board = board_file.resolve()
    payload = board.read_bytes()
    root = parse_sexpr(payload.decode("utf-8"))
    if not root or _atom(root[0]) != "kicad_pcb":
        raise ValueError("saved board is not a KiCad PCB document")

    direct = tuple(item for item in root[1:] if isinstance(item, list) and item)
    numbered_nets = {
        _integer(item[1]): _atom(item[2])
        for item in direct
        if _head(item) == "net" and len(item) >= 3
    }
    pad_counts: dict[str, int] = {}
    for footprint in direct:
        if _head(footprint) not in {"footprint", "module"}:
            continue
        for item in footprint:
            if not isinstance(item, list) or _head(item) != "pad":
                continue
            net_name = _node_net_name(item, numbered_nets)
            if net_name is not None:
                pad_counts[net_name] = pad_counts.get(net_name, 0) + 1

    segment_nodes = tuple(item for item in direct if _head(item) == "segment")
    via_nodes = tuple(item for item in direct if _head(item) == "via")
    zone_nodes = tuple(item for item in direct if _head(item) == "zone")
    segment_nets = _net_names(segment_nodes, numbered_nets)
    via_nets = _net_names(via_nodes, numbered_nets)
    zone_nets = _net_names(zone_nodes, numbered_nets)
    routable_nets = frozenset(
        net_name for net_name, count in pad_counts.items() if count >= 2
    )
    track_nets = (segment_nets | via_nets) & routable_nets
    copper_carrier_nets = (track_nets | zone_nets) & routable_nets
    uncovered = tuple(
        sorted(
            (
                net_name for net_name in routable_nets - copper_carrier_nets
            ),
            key=str.casefold,
        )
    )
    routable_count = len(routable_nets)
    track_coverage = len(track_nets) / routable_count if routable_count else 0.0
    carrier_coverage = (
        len(copper_carrier_nets) / routable_count if routable_count else 0.0
    )
    if routable_count == 0:
        state = RoutingArtifactState.INDETERMINATE
    elif not segment_nodes and not via_nodes:
        state = RoutingArtifactState.PLACEMENT_ONLY
    elif len(copper_carrier_nets) < routable_count:
        state = RoutingArtifactState.PARTIALLY_ROUTED
    else:
        state = RoutingArtifactState.ROUTED_CANDIDATE

    fields: dict[str, Any] = {
        "board_file": str(board),
        "board_sha256": hashlib.sha256(payload).hexdigest(),
        "segment_count": len(segment_nodes),
        "via_count": len(via_nodes),
        "zone_count": len(zone_nodes),
        "declared_net_count": len(
            frozenset(pad_counts) | segment_nets | via_nets | zone_nets
        ),
        "routable_net_count": routable_count,
        "segment_net_count": len(segment_nets),
        "via_net_count": len(via_nets),
        "zone_net_count": len(zone_nets),
        "copper_carrier_net_count": len(copper_carrier_nets),
        "track_net_coverage": track_coverage,
        "copper_carrier_net_coverage": carrier_coverage,
        "uncovered_net_names": uncovered,
        "state": state,
    }
    provisional = SavedBoardRoutingEvidence.model_construct(
        **fields, evidence_fingerprint="0" * 64
    )
    return SavedBoardRoutingEvidence(
        **fields,
        evidence_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
        ),
    )


def inspect_kicad_drc_report(report_file: Path) -> KiCadDrcEvidence:
    """Parse exact section counts from one retained KiCad JSON DRC report."""

    report = report_file.resolve()
    payload = report.read_bytes()
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("KiCad DRC report root must be a JSON object")
    counts: dict[str, int] = {}
    for section in ("violations", "unconnected_items", "schematic_parity"):
        entries = data.get(section, [])
        if not isinstance(entries, list):
            raise ValueError(f"KiCad DRC report section {section} must be a list")
        counts[section] = len(entries)
    fields: dict[str, Any] = {
        "report_file": str(report),
        "report_sha256": hashlib.sha256(payload).hexdigest(),
        "violation_count": counts["violations"],
        "unconnected_item_count": counts["unconnected_items"],
        "schematic_parity_count": counts["schematic_parity"],
        "clean": all(count == 0 for count in counts.values()),
    }
    provisional = KiCadDrcEvidence.model_construct(
        **fields, evidence_fingerprint="0" * 64
    )
    return KiCadDrcEvidence(
        **fields,
        evidence_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
        ),
    )


def retarget_saved_board_routing_evidence(
    evidence: SavedBoardRoutingEvidence,
    board_file: Path,
) -> SavedBoardRoutingEvidence:
    """Retain objective counts while moving an immutable board into a transaction."""

    fields = evidence.model_dump(
        mode="python",
        exclude={"evidence_fingerprint", "board_file"},
    )
    fields["board_file"] = str(board_file.resolve())
    provisional = SavedBoardRoutingEvidence.model_construct(
        **fields, evidence_fingerprint="0" * 64
    )
    return SavedBoardRoutingEvidence(
        **fields,
        evidence_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
        ),
    )


def retarget_kicad_drc_evidence(
    evidence: KiCadDrcEvidence,
    report_file: Path,
) -> KiCadDrcEvidence:
    """Retain exact DRC counts while moving its report into a transaction."""

    fields = evidence.model_dump(
        mode="python",
        exclude={"evidence_fingerprint", "report_file"},
    )
    fields["report_file"] = str(report_file.resolve())
    provisional = KiCadDrcEvidence.model_construct(
        **fields, evidence_fingerprint="0" * 64
    )
    return KiCadDrcEvidence(
        **fields,
        evidence_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
        ),
    )


def _net_names(
    nodes: tuple[SList, ...],
    numbered_nets: dict[int, str],
) -> frozenset[str]:
    return frozenset(
        net_name
        for node in nodes
        if (net_name := _node_net_name(node, numbered_nets)) is not None
    )


def _node_net_name(node: SList, numbered_nets: dict[int, str]) -> str | None:
    raw_name = _field_atom(node, "net_name")
    if raw_name not in {None, "", "0"}:
        return raw_name
    raw_net = _field_atom(node, "net")
    if raw_net in {None, "", "0"}:
        return None
    try:
        code = int(raw_net)
    except ValueError:
        return raw_net
    return numbered_nets.get(code, f"net-{code}") if code > 0 else None


def _field_atom(node: SList, name: str) -> str | None:
    for item in node:
        if isinstance(item, list) and _head(item) == name and len(item) >= 2:
            return _atom(item[1])
    return None


def _head(node: SList) -> str:
    return _atom(node[0]) if node else ""


def _atom(node: SExpr) -> str:
    if isinstance(node, QuotedString):
        return node.value
    if isinstance(node, str):
        return node
    raise ValueError("expected a KiCad atom")


def _integer(node: SExpr) -> int:
    value = _atom(node)
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"expected an integer KiCad atom, got {value!r}") from exc
