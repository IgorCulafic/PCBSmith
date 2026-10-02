"""Exact saved-board/DRC adapter for W9 production marking evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import model_validator

from pcbsmith.automatic_review_gate import ProductionMarkingAudit
from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class ProductionMarkingRequirements(SemanticIrModel):
    schema_id: Literal["pcbsmith-production-marking-requirements-v1"] = (
        "pcbsmith-production-marking-requirements-v1"
    )
    board_sha256: str
    source_authority_sha256: str
    declaration_complete: bool
    required_refdes_refs: tuple[str, ...]
    required_polarity_refs: tuple[str, ...] = ()
    required_connector_mating_refs: tuple[str, ...] = ()
    requirements_fingerprint: str

    @model_validator(mode="after")
    def requirements_are_canonical(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.source_authority_sha256, "source_authority_sha256")
        require_sha256(self.requirements_fingerprint, "requirements_fingerprint")
        for name in (
            "required_refdes_refs",
            "required_polarity_refs",
            "required_connector_mating_refs",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique references")
            object.__setattr__(self, name, values)
        payload = self.model_dump(mode="json", exclude={"requirements_fingerprint"})
        if self.requirements_fingerprint != fingerprint(payload):
            raise ValueError("production marking requirements fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> ProductionMarkingRequirements:
        canonical = dict(values)
        for name in (
            "required_refdes_refs",
            "required_polarity_refs",
            "required_connector_mating_refs",
        ):
            canonical[name] = tuple(sorted(canonical.get(name, ())))
        provisional = cls.model_construct(**canonical, requirements_fingerprint="0" * 64)
        return cls(
            **canonical,
            requirements_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"requirements_fingerprint"})
            ),
        )


class SavedBoardMarkingInventory(SemanticIrModel):
    schema_id: Literal["pcbsmith-saved-board-marking-inventory-v1"] = (
        "pcbsmith-saved-board-marking-inventory-v1"
    )
    board_file: str
    board_sha256: str
    footprint_refs: tuple[str, ...]
    visible_silkscreen_refdes_refs: tuple[str, ...]
    silkscreen_item_count: int
    verified_polarity_refs: tuple[str, ...] = ()
    verified_connector_mating_refs: tuple[str, ...] = ()
    polarity_semantics_supported: bool = False
    connector_mating_semantics_supported: bool = False
    inventory_fingerprint: str

    @model_validator(mode="after")
    def inventory_is_canonical(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.inventory_fingerprint, "inventory_fingerprint")
        for name in (
            "footprint_refs",
            "visible_silkscreen_refdes_refs",
            "verified_polarity_refs",
            "verified_connector_mating_refs",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique references")
            object.__setattr__(self, name, values)
        payload = self.model_dump(mode="json", exclude={"inventory_fingerprint"})
        if self.inventory_fingerprint != fingerprint(payload):
            raise ValueError("saved-board marking inventory fingerprint is stale")
        return self


def inspect_saved_board_markings(board_file: Path) -> SavedBoardMarkingInventory:
    board = board_file.resolve()
    raw = board.read_bytes()
    root = parse_sexpr(raw.decode("utf-8"))
    if not isinstance(root, list) or _head(root) != "kicad_pcb":
        raise ValueError("saved board is not a KiCad PCB document")
    footprints: list[str] = []
    visible_refs: list[str] = []
    verified_polarity: list[str] = []
    verified_mating: list[str] = []
    polarity_declarations = 0
    mating_declarations = 0
    silk_count = 0
    global_silk_texts = tuple(
        _atom(item[1])
        for item in root
        if isinstance(item, list)
        and _head(item) == "gr_text"
        and len(item) >= 2
        and _silk_layer(item)
        and not _has_child(item, "hide")
    )
    for footprint in _children(root, "footprint") + _children(root, "module"):
        reference_node = next(
            (
                item
                for item in footprint
                if isinstance(item, list)
                and _head(item) == "property"
                and len(item) >= 3
                and _atom(item[1]) == "Reference"
            ),
            None,
        )
        if reference_node is None:
            continue
        reference = _atom(reference_node[2])
        footprints.append(reference)
        properties = {
            _atom(item[1]): _atom(item[2])
            for item in footprint
            if isinstance(item, list) and _head(item) == "property" and len(item) >= 3
        }
        footprint_silk_texts = tuple(
            _atom(item[2])
            for item in footprint
            if isinstance(item, list)
            and _head(item) == "fp_text"
            and len(item) >= 3
            and _silk_layer(item)
            and not _has_child(item, "hide")
        )
        polarity = properties.get("PCBSmith_Polarity")
        if polarity is not None:
            polarity_declarations += 1
            roles = _parse_pad_roles(polarity)
            markers = set(footprint_silk_texts)
            if roles and _polarity_marker_is_visible(roles, markers):
                verified_polarity.append(reference)
        mating = properties.get("PCBSmith_Mating")
        if mating is not None:
            mating_declarations += 1
            visible_texts = (*footprint_silk_texts, *global_silk_texts)
            if mating and any(mating.upper() in text.upper() for text in visible_texts):
                verified_mating.append(reference)
        if _silk_layer(reference_node) and not _has_child(reference_node, "hide"):
            visible_refs.append(reference)
            silk_count += 1
        silk_count += sum(
            _head(item) in {"fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_text"}
            and _silk_layer(item)
            and not _has_child(item, "hide")
            for item in footprint
            if isinstance(item, list)
        )
    silk_count += sum(
        _head(item) in {"gr_line", "gr_rect", "gr_circle", "gr_arc", "gr_poly", "gr_text"}
        and _silk_layer(item)
        and not _has_child(item, "hide")
        for item in root
        if isinstance(item, list)
    )
    fields: dict[str, Any] = {
        "board_file": str(board),
        "board_sha256": hashlib.sha256(raw).hexdigest(),
        "footprint_refs": tuple(sorted(footprints)),
        "visible_silkscreen_refdes_refs": tuple(sorted(visible_refs)),
        "silkscreen_item_count": silk_count,
        "verified_polarity_refs": tuple(sorted(verified_polarity)),
        "verified_connector_mating_refs": tuple(sorted(verified_mating)),
        "polarity_semantics_supported": polarity_declarations > 0,
        "connector_mating_semantics_supported": mating_declarations > 0,
    }
    provisional = SavedBoardMarkingInventory.model_construct(
        **fields, inventory_fingerprint="0" * 64
    )
    return SavedBoardMarkingInventory(
        **fields,
        inventory_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"inventory_fingerprint"})
        ),
    )


def _parse_pad_roles(value: str) -> dict[str, str]:
    roles: dict[str, str] = {}
    for item in value.split(";"):
        if "=" not in item:
            return {}
        pad, role = (part.strip() for part in item.split("=", 1))
        if not pad or not role or pad in roles:
            return {}
        roles[pad] = role.upper()
    return roles


def _polarity_marker_is_visible(roles: dict[str, str], markers: set[str]) -> bool:
    normalized = {marker.strip().upper() for marker in markers}
    if "K" in roles.values():
        return "K" in normalized
    if "+" in roles.values():
        return "+" in normalized
    return False


def audit_kicad_production_markings(
    *,
    inventory: SavedBoardMarkingInventory,
    requirements: ProductionMarkingRequirements,
    drc_report: Path,
    drc_report_board_sha256: str,
) -> ProductionMarkingAudit:
    if inventory.board_sha256 != requirements.board_sha256:
        raise ValueError("marking inventory and requirements target different boards")
    if drc_report_board_sha256 != inventory.board_sha256:
        raise ValueError("marking DRC targets another board revision")
    report = drc_report.resolve()
    raw = report.read_bytes()
    data = json.loads(raw)
    violations = data.get("violations", []) if isinstance(data, dict) else None
    if not isinstance(violations, list):
        raise ValueError("KiCad DRC report must contain a violations list")
    by_type: dict[str, list[str]] = {
        "silk_over_copper": [],
        "silk_overlap": [],
        "silk_edge_clearance": [],
        "courtyard": [],
    }
    for index, item in enumerate(violations):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type", ""))
        target = kind if kind in by_type else "courtyard" if "courtyard" in kind else None
        if target is not None:
            by_type[target].append(_drc_finding_id(index, item))
    visible = set(inventory.visible_silkscreen_refdes_refs)
    missing_refdes = tuple(
        f"missing_refdes:{reference}"
        for reference in requirements.required_refdes_refs
        if reference not in visible
    )
    missing_polarity = (
        tuple(
            f"missing_polarity:{reference}"
            for reference in requirements.required_polarity_refs
            if reference not in inventory.verified_polarity_refs
        )
        if inventory.polarity_semantics_supported
        else ()
    )
    missing_mating = (
        tuple(
            f"connector_mating_visibility:{reference}"
            for reference in requirements.required_connector_mating_refs
            if reference not in inventory.verified_connector_mating_refs
        )
        if inventory.connector_mating_semantics_supported
        else ()
    )
    unverified: list[str] = []
    if not requirements.declaration_complete:
        unverified.append("requirements_declaration_incomplete")
    if requirements.required_polarity_refs and not inventory.polarity_semantics_supported:
        unverified.extend(
            f"polarity_semantics:{item}" for item in requirements.required_polarity_refs
        )
    if (
        requirements.required_connector_mating_refs
        and not inventory.connector_mating_semantics_supported
    ):
        unverified.extend(
            f"connector_mating_semantics:{item}"
            for item in requirements.required_connector_mating_refs
        )
    return ProductionMarkingAudit.build(
        board_sha256=inventory.board_sha256,
        drc_report_sha256=hashlib.sha256(raw).hexdigest(),
        requirements_fingerprint=requirements.requirements_fingerprint,
        inventory_fingerprint=inventory.inventory_fingerprint,
        inspected_mark_count=inventory.silkscreen_item_count,
        unverified_check_ids=tuple(sorted(unverified)),
        silk_over_copper_finding_ids=tuple(by_type["silk_over_copper"]),
        silk_over_silk_finding_ids=tuple(by_type["silk_overlap"]),
        silk_edge_finding_ids=tuple(by_type["silk_edge_clearance"]),
        courtyard_finding_ids=tuple(by_type["courtyard"]),
        missing_polarity_finding_ids=missing_polarity,
        missing_refdes_finding_ids=missing_refdes,
        connector_mating_visibility_finding_ids=missing_mating,
    )


def _drc_finding_id(index: int, item: dict[str, Any]) -> str:
    uuids = tuple(
        sorted(
            str(value.get("uuid"))
            for value in item.get("items", [])
            if isinstance(value, dict) and value.get("uuid")
        )
    )
    stable_identity: object = uuids if uuids else ("index_without_item_uuid", index)
    return f"drc:{item.get('type', 'unknown')}:{fingerprint(stable_identity)}"


def _children(node: list[SExpr], name: str) -> tuple[SList, ...]:
    return tuple(item for item in node if isinstance(item, list) and _head(item) == name)


def _head(node: object) -> str:
    return _atom(node[0]) if isinstance(node, list) and node else ""


def _atom(value: object) -> str:
    if isinstance(value, QuotedString):
        return value.value
    if isinstance(value, str):
        return value
    raise ValueError("expected KiCad atomic value")


def _has_child(node: list[SExpr], name: str) -> bool:
    return any(isinstance(item, list) and _head(item) == name for item in node)


def _silk_layer(node: list[SExpr]) -> bool:
    layer = next(
        (
            item
            for item in node
            if isinstance(item, list) and _head(item) == "layer" and len(item) >= 2
        ),
        None,
    )
    return layer is not None and _atom(layer[1]) in {"F.SilkS", "B.SilkS"}


__all__ = [
    "ProductionMarkingRequirements",
    "SavedBoardMarkingInventory",
    "audit_kicad_production_markings",
    "inspect_saved_board_markings",
]
