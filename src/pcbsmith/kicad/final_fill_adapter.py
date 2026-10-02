"""Transactional KiCad final-fill reader and exact saved-region inventory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.check_reports import drc_sections, validate_native_header
from pcbsmith.kicad.cli import KiCadInstall, find_kicad_cli, run_kicad_process
from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.project_dependencies import native_project_hashes, retain_native_project
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class FillReachability(StrEnum):
    SOURCE_REACHABLE = "source_reachable"
    FLOATING = "floating"
    UNVERIFIED = "unverified"


class ExactFillPoint(SemanticIrModel):
    x_mm: Decimal
    y_mm: Decimal


class KiCadZoneIntentRecord(SemanticIrModel):
    zone_id: str
    zone_index: int = Field(ge=0)
    zone_uuid: str
    net_name: str
    layer: str
    priority: int
    clearance_mm: Decimal | None
    minimum_thickness_mm: Decimal | None
    thermal_gap_mm: Decimal | None
    thermal_bridge_width_mm: Decimal | None
    island_removal_mode: int | None
    pad_connection_mode: str | None
    outline_point_loops: tuple[tuple[ExactFillPoint, ...], ...] = Field(min_length=1)
    canonical_intent_sexpr: str
    intent_fingerprint: str

    @model_validator(mode="after")
    def intent_is_canonical(self) -> Self:
        for name in ("zone_id", "zone_uuid", "net_name", "layer"):
            require_identity(getattr(self, name), name)
        if any(len(loop) < 3 for loop in self.outline_point_loops):
            raise ValueError("zone outline loops require at least three points")
        require_identity(self.canonical_intent_sexpr, "canonical_intent_sexpr")
        require_sha256(self.intent_fingerprint, "intent_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"intent_fingerprint"}))
        if self.intent_fingerprint != expected:
            raise ValueError("zone intent fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> KiCadZoneIntentRecord:
        provisional = cls.model_construct(**values, intent_fingerprint="0" * 64)
        return cls(
            **values,
            intent_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"intent_fingerprint"})
            ),
        )


class KiCadFilledCopperRegion(SemanticIrModel):
    region_id: str
    zone_id: str
    zone_uuid: str
    region_index: int = Field(ge=0)
    net_name: str
    layer: str
    exact_point_walk: tuple[ExactFillPoint, ...] = Field(min_length=3)
    canonical_filled_polygon_sexpr: str
    source_artifact_sha256: str
    reachability: FillReachability = FillReachability.UNVERIFIED
    reachability_evidence_ids: tuple[str, ...] = ()
    region_fingerprint: str

    @model_validator(mode="after")
    def region_is_source_bound(self) -> Self:
        for name in ("region_id", "zone_id", "zone_uuid", "net_name", "layer"):
            require_identity(getattr(self, name), name)
        require_identity(
            self.canonical_filled_polygon_sexpr,
            "canonical_filled_polygon_sexpr",
        )
        require_sha256(self.source_artifact_sha256, "source_artifact_sha256")
        evidence = tuple(sorted(self.reachability_evidence_ids))
        if self.reachability is FillReachability.UNVERIFIED and evidence:
            raise ValueError("unverified fill reachability cannot carry positive evidence")
        if self.reachability is not FillReachability.UNVERIFIED and not evidence:
            raise ValueError("classified fill reachability requires evidence")
        object.__setattr__(self, "reachability_evidence_ids", evidence)
        require_sha256(self.region_fingerprint, "region_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"region_fingerprint"}))
        if self.region_fingerprint != expected:
            raise ValueError("filled copper region fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> KiCadFilledCopperRegion:
        provisional = cls.model_construct(**values, region_fingerprint="0" * 64)
        return cls(
            **values,
            region_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"region_fingerprint"})
            ),
        )


class KiCadFinalFillSnapshot(SemanticIrModel):
    schema_id: Literal["pcbsmith-kicad-final-fill-snapshot"] = "pcbsmith-kicad-final-fill-snapshot"
    schema_version: Literal[1] = 1
    source_board_sha256: str
    filled_board_sha256: str
    kicad_version: str
    source_zone_intent_fingerprint: str
    filled_zone_intent_fingerprint: str
    zone_intent_unchanged: bool
    refilled_by_kicad: bool
    stale_fill: bool
    zones: tuple[KiCadZoneIntentRecord, ...]
    regions: tuple[KiCadFilledCopperRegion, ...]
    unverified_region_ids: tuple[str, ...]
    snapshot_fingerprint: str

    @model_validator(mode="after")
    def snapshot_is_replay_bound(self) -> Self:
        for name in (
            "source_board_sha256",
            "filled_board_sha256",
            "source_zone_intent_fingerprint",
            "filled_zone_intent_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        require_identity(self.kicad_version, "kicad_version")
        expected_unchanged = (
            self.source_zone_intent_fingerprint == self.filled_zone_intent_fingerprint
        )
        if self.zone_intent_unchanged != expected_unchanged:
            raise ValueError("zone intent unchanged disposition is stale")
        expected_stale = not self.refilled_by_kicad or not self.regions or not expected_unchanged
        if self.stale_fill != expected_stale:
            raise ValueError("stale-fill disposition is stale")
        unverified = tuple(
            sorted(
                item.region_id
                for item in self.regions
                if item.reachability is FillReachability.UNVERIFIED
            )
        )
        if self.unverified_region_ids != unverified:
            raise ValueError("unverified fill-region inventory is stale")
        require_sha256(self.snapshot_fingerprint, "snapshot_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"snapshot_fingerprint"}))
        if self.snapshot_fingerprint != expected:
            raise ValueError("final-fill snapshot fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> KiCadFinalFillSnapshot:
        values["zone_intent_unchanged"] = (
            values["source_zone_intent_fingerprint"] == values["filled_zone_intent_fingerprint"]
        )
        values["stale_fill"] = (
            not values["refilled_by_kicad"]
            or not values["regions"]
            or not values["zone_intent_unchanged"]
        )
        values["unverified_region_ids"] = tuple(
            sorted(
                item.region_id
                for item in values["regions"]
                if item.reachability is FillReachability.UNVERIFIED
            )
        )
        provisional = cls.model_construct(**values, snapshot_fingerprint="0" * 64)
        return cls(
            **values,
            snapshot_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"snapshot_fingerprint"})
            ),
        )


def _atom(value: object) -> str:
    if isinstance(value, QuotedString):
        return value.value
    if isinstance(value, str):
        return value
    raise ValueError("expected KiCad atomic value")


def _head(node: object) -> str:
    return _atom(node[0]) if isinstance(node, list) and node else ""


def _children(node: Sequence[SExpr], name: str) -> tuple[SList, ...]:
    return tuple(child for child in node if isinstance(child, list) and _head(child) == name)


def _first_atom(node: Sequence[SExpr], name: str) -> str | None:
    clauses = _children(node, name)
    if not clauses or len(clauses[0]) < 2:
        return None
    return _atom(clauses[0][1])


def _nested_atom(node: Sequence[SExpr], parent: str, child: str) -> str | None:
    parents = _children(node, parent)
    if not parents:
        return None
    return _first_atom(parents[0], child)


def _zone_pad_connection_mode(zone: Sequence[SExpr]) -> str | None:
    clauses = _children(zone, "connect_pads")
    if not clauses:
        return None
    if len(clauses[0]) < 2 or isinstance(clauses[0][1], list):
        return "thermal"
    return _atom(clauses[0][1])


def _points(node: Sequence[SExpr]) -> tuple[ExactFillPoint, ...]:
    points: list[ExactFillPoint] = []
    pts = _children(node, "pts")
    if not pts:
        return ()
    for xy in _children(pts[0], "xy"):
        if len(xy) != 3:
            raise ValueError("malformed KiCad xy point")
        points.append(ExactFillPoint(x_mm=Decimal(_atom(xy[1])), y_mm=Decimal(_atom(xy[2]))))
    return tuple(points)


def zone_intent_node(zone: Sequence[SExpr]) -> SList:
    """Exclude computed polygons and KiCad's derived `(fill yes ...)` state only.

    Thermal, clearance, island and all other fill parameters remain authoritative.
    """
    result: SList = []
    for item in zone:
        if isinstance(item, list) and item:
            if item[0] in {"filled_polygon", "fill_segments"}:
                continue
            if item[0] == "fill":
                result.append([part for part in item if part != "yes"])
                continue
        result.append(item)
    return result


def _parse_zone_intents(tree: Sequence[SExpr]) -> tuple[KiCadZoneIntentRecord, ...]:
    records: list[KiCadZoneIntentRecord] = []
    for index, zone in enumerate(_children(tree, "zone")):
        uuid = _first_atom(zone, "uuid") or f"index-{index}"
        net = _first_atom(zone, "net") or "<no-net>"
        layer = _first_atom(zone, "layer") or "<unknown-layer>"
        loops = tuple(
            points for polygon in _children(zone, "polygon") if (points := _points(polygon))
        )
        if not loops:
            raise ValueError(f"zone {uuid} has no polygon outline")
        canonical = serialize_sexpr(zone_intent_node(zone))
        values = {
            "zone_id": f"zone:{uuid}",
            "zone_index": index,
            "zone_uuid": uuid,
            "net_name": net,
            "layer": layer,
            "priority": int(_first_atom(zone, "priority") or "0"),
            "clearance_mm": (
                None
                if (value := _nested_atom(zone, "connect_pads", "clearance")) is None
                else Decimal(value)
            ),
            "minimum_thickness_mm": (
                None if (value := _first_atom(zone, "min_thickness")) is None else Decimal(value)
            ),
            "thermal_gap_mm": (
                None
                if (value := _nested_atom(zone, "fill", "thermal_gap")) is None
                else Decimal(value)
            ),
            "thermal_bridge_width_mm": (
                None
                if (value := _nested_atom(zone, "fill", "thermal_bridge_width")) is None
                else Decimal(value)
            ),
            "island_removal_mode": (
                None
                if (value := _nested_atom(zone, "fill", "island_removal_mode")) is None
                else int(value)
            ),
            "pad_connection_mode": _zone_pad_connection_mode(zone),
            "outline_point_loops": loops,
            "canonical_intent_sexpr": canonical,
        }
        records.append(KiCadZoneIntentRecord.build(**values))
    return tuple(records)


def _zone_set_fingerprint(zones: tuple[KiCadZoneIntentRecord, ...]) -> str:
    return fingerprint(tuple(item.intent_fingerprint for item in zones))


def parse_kicad_final_fill_snapshot(
    source_board: Path,
    filled_board: Path,
    *,
    kicad_version: str,
    refilled_by_kicad: bool,
) -> KiCadFinalFillSnapshot:
    source_tree = parse_sexpr(source_board.read_text(encoding="utf-8"))
    filled_tree = parse_sexpr(filled_board.read_text(encoding="utf-8"))
    if not isinstance(source_tree, list) or not isinstance(filled_tree, list):
        raise ValueError("KiCad board root must be an s-expression list")
    source_zones = _parse_zone_intents(source_tree)
    filled_zones = _parse_zone_intents(filled_tree)
    filled_sha = hashlib.sha256(filled_board.read_bytes()).hexdigest()
    regions: list[KiCadFilledCopperRegion] = []
    for zone_record, zone_node in zip(
        filled_zones,
        _children(filled_tree, "zone"),
        strict=True,
    ):
        for region_index, polygon in enumerate(_children(zone_node, "filled_polygon")):
            points = _points(polygon)
            if len(points) < 3:
                raise ValueError("filled polygon requires at least three exact points")
            canonical = serialize_sexpr(polygon)
            regions.append(
                KiCadFilledCopperRegion.build(
                    region_id=f"{zone_record.zone_id}:filled:{region_index}",
                    zone_id=zone_record.zone_id,
                    zone_uuid=zone_record.zone_uuid,
                    region_index=region_index,
                    net_name=zone_record.net_name,
                    layer=_first_atom(polygon, "layer") or zone_record.layer,
                    exact_point_walk=points,
                    canonical_filled_polygon_sexpr=canonical,
                    source_artifact_sha256=filled_sha,
                    reachability=FillReachability.UNVERIFIED,
                    reachability_evidence_ids=(),
                )
            )
    return KiCadFinalFillSnapshot.build(
        source_board_sha256=hashlib.sha256(source_board.read_bytes()).hexdigest(),
        filled_board_sha256=filled_sha,
        kicad_version=kicad_version,
        source_zone_intent_fingerprint=_zone_set_fingerprint(source_zones),
        filled_zone_intent_fingerprint=_zone_set_fingerprint(filled_zones),
        refilled_by_kicad=refilled_by_kicad,
        zones=filled_zones,
        regions=tuple(regions),
    )


def refill_and_read_kicad_board(
    source_board: Path,
    transaction_dir: Path,
) -> tuple[Path, KiCadFinalFillSnapshot]:
    """Refill an isolated candidate copy, never the caller's source board."""

    install: KiCadInstall | None = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad CLI is unavailable; exact final fill cannot be established")
    if transaction_dir.exists():
        raise ValueError("final-fill transaction directory must be fresh")
    source_before = source_board.read_bytes()
    inputs = retain_native_project(source_board, transaction_dir)
    candidate = transaction_dir / source_board.name
    report = transaction_dir / "fill-drc.json"
    command = (
        str(install.path),
        "pcb",
        "drc",
        "--format",
        "json",
        "--refill-zones",
        "--save-board",
        "--output",
        str(report),
        str(candidate),
    )
    result = run_kicad_process(command)
    (transaction_dir / "fill-process.json").write_text(
        json.dumps(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "source_inputs": inputs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0 or not report.is_file():
        raise RuntimeError("native final-fill execution failed; retained process log available")
    drc_sections(validate_native_header(json.loads(report.read_bytes()), "DRC", candidate))
    expected = dict(inputs)
    expected[candidate.name] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if native_project_hashes(candidate) != expected:
        raise ValueError("native refill changed project rules or dependencies")
    if native_project_hashes(source_board) != inputs or source_board.read_bytes() != source_before:
        raise ValueError("final-fill transaction changed its source")
    version_result = run_kicad_process((install.path, "--version"))
    kicad_version = (
        version_result.stdout.strip()
        if version_result.returncode == 0 and version_result.stdout.strip()
        else f"unavailable:{install.source}"
    )
    snapshot = parse_kicad_final_fill_snapshot(
        source_board,
        candidate,
        kicad_version=kicad_version,
        refilled_by_kicad=True,
    )
    return candidate, snapshot


__all__ = [
    "ExactFillPoint",
    "FillReachability",
    "KiCadFilledCopperRegion",
    "KiCadFinalFillSnapshot",
    "KiCadZoneIntentRecord",
    "parse_kicad_final_fill_snapshot",
    "refill_and_read_kicad_board",
]
