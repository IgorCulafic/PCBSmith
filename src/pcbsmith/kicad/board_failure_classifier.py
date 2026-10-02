"""Deterministic reconciliation of KiCad DRC failures and placement feasibility.

The pcbnew bridge is intentionally read-only.  It records KiCad connected
components, filled-zone islands, legal pad-escape candidates, and inexpensive
placement metrics.  This module owns the engine-neutral classification and the
fail-closed gates: every DRC item must be reconciled and every required SMD
power/return pad must have a legal escape in its current pose.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.placement_escape_repair import (
    EscapeRepairRootCause,
    EscapeRepairTerminalReason,
    PlacementEscapeRepairPlan,
)
from pcbsmith.semantic_ir import SemanticIrModel


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class OpenFailureReason(StrEnum):
    DISCONNECTED_FILLED_ZONE_ISLANDS = "disconnected_filled_zone_islands"
    MISSING_INTERLAYER_TRANSITION = "missing_interlayer_transition"
    PAD_ESCAPE_GAP = "pad_escape_gap"
    ZONE_ATTACHMENT_GAP = "zone_attachment_gap"
    TRACK_GAP_OR_ISLAND = "track_gap_or_island"
    NO_COPPER_PATH = "no_copper_path"
    DISCONNECTED_COPPER_COMPONENTS = "disconnected_copper_components"
    UNRESOLVED_BOARD_ITEM = "unresolved_board_item"


class TwoLayerFeasibility(StrEnum):
    FEASIBLE_CURRENT_PLACEMENT = "feasible_current_placement"
    PLACEMENT_CHANGE_REQUIRED = "placement_change_required"
    BOUNDED_PLACEMENT_CHANGE_AVAILABLE = "bounded_placement_change_available"
    ESCAPE_TECHNOLOGY_OR_FOOTPRINT_CHANGE_REQUIRED = (
        "escape_technology_or_footprint_change_required"
    )
    PLACEMENT_TRANSLATION_SIZE_OR_LAYER_CHANGE_REQUIRED = (
        "placement_translation_size_or_layer_change_required"
    )
    INDETERMINATE = "indeterminate"


class ClassifiedEndpoint(SemanticIrModel):
    description: str
    uuid: str
    semantic_item_id: str | None = None
    connected_component_id: str | None = None
    kind: str | None = None
    net_name: str | None = None
    layer: str | None = None
    position_mm: tuple[float, float] | None = None


class ClassifiedOpen(SemanticIrModel):
    failure_id: str
    reason: OpenFailureReason
    endpoints: tuple[ClassifiedEndpoint, ...] = Field(min_length=1)


class ClassifiedViolation(SemanticIrModel):
    failure_id: str
    violation_type: str
    severity: str
    descriptions: tuple[str, ...]


class BoardFailureClassification(SemanticIrModel):
    schema_id: Literal["pcbsmith-board-failure-classification"] = (
        "pcbsmith-board-failure-classification"
    )
    schema_version: Literal[1] = 1
    board_sha256: str
    drc_sha256: str
    opens: tuple[ClassifiedOpen, ...]
    violations: tuple[ClassifiedViolation, ...]
    observed_unconnected_count: int = Field(ge=0)
    observed_violation_count: int = Field(ge=0)
    reconciled_unconnected_count: int = Field(ge=0)
    reconciled_violation_count: int = Field(ge=0)
    reconciliation_complete: bool
    current_required_escape_count: int = Field(ge=0)
    current_legal_escape_count: int = Field(ge=0)
    all_rotations_required_escape_count: int = Field(ge=0)
    all_rotations_legal_escape_count: int = Field(ge=0)
    required_pads_without_current_escape: tuple[str, ...]
    required_pads_without_any_rotation_escape: tuple[str, ...]
    bounded_repair_plan_fingerprint: str | None = None
    bounded_repair_evaluated_proposal_count: int = Field(default=0, ge=0)
    bounded_repair_candidate_count: int = Field(default=0, ge=0)
    escape_repair_root_cause: EscapeRepairRootCause | None = None
    escape_repair_terminal_reason: EscapeRepairTerminalReason | None = None
    two_layer_feasibility: TwoLayerFeasibility
    placement_gate_passed: bool
    classification_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        for name in ("board_sha256", "drc_sha256", "classification_fingerprint"):
            value = getattr(self, name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        expected_reconciliation = (
            self.observed_unconnected_count == self.reconciled_unconnected_count
            and self.observed_violation_count == self.reconciled_violation_count
        )
        if self.reconciliation_complete != expected_reconciliation:
            raise ValueError("DRC reconciliation disposition is stale")
        expected_gate = (
            self.reconciliation_complete and not self.required_pads_without_current_escape
        )
        if self.placement_gate_passed != expected_gate:
            raise ValueError("placement gate disposition is stale")
        if self.bounded_repair_plan_fingerprint is not None:
            digest = self.bounded_repair_plan_fingerprint
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("bounded repair fingerprint must be a SHA-256 digest")
        if self.required_pads_without_any_rotation_escape and self.bounded_repair_candidate_count:
            expected_feasibility = TwoLayerFeasibility.BOUNDED_PLACEMENT_CHANGE_AVAILABLE
        elif (
            self.required_pads_without_any_rotation_escape
            and self.escape_repair_root_cause is EscapeRepairRootCause.INTRINSIC_FOOTPRINT_ESCAPE
        ):
            expected_feasibility = (
                TwoLayerFeasibility.ESCAPE_TECHNOLOGY_OR_FOOTPRINT_CHANGE_REQUIRED
            )
        elif self.required_pads_without_any_rotation_escape:
            expected_feasibility = (
                TwoLayerFeasibility.PLACEMENT_TRANSLATION_SIZE_OR_LAYER_CHANGE_REQUIRED
            )
        elif self.required_pads_without_current_escape:
            expected_feasibility = TwoLayerFeasibility.PLACEMENT_CHANGE_REQUIRED
        elif self.current_required_escape_count:
            expected_feasibility = TwoLayerFeasibility.FEASIBLE_CURRENT_PLACEMENT
        else:
            expected_feasibility = TwoLayerFeasibility.INDETERMINATE
        if self.two_layer_feasibility is not expected_feasibility:
            raise ValueError("two-layer feasibility disposition is stale")
        payload = self.model_dump(mode="json", exclude={"classification_fingerprint"})
        if self.classification_fingerprint != _fingerprint(payload):
            raise ValueError("classification fingerprint is stale")
        return self


def _endpoint(raw: object, item_by_uuid: dict[str, object]) -> ClassifiedEndpoint:
    if not isinstance(raw, dict):
        return ClassifiedEndpoint(description="unidentified", uuid="unresolved")
    uuid = str(raw.get("uuid", "unresolved"))
    observed = item_by_uuid.get(uuid)
    position = raw.get("pos")
    position_mm = None
    if isinstance(position, dict):
        position_mm = (float(str(position.get("x", 0.0))), float(str(position.get("y", 0.0))))
    if not isinstance(observed, dict):
        return ClassifiedEndpoint(
            description=str(raw.get("description", "unidentified")),
            uuid=uuid,
            position_mm=position_mm,
        )
    return ClassifiedEndpoint(
        description=str(raw.get("description", "unidentified")),
        uuid=uuid,
        semantic_item_id=str(observed["semantic_item_id"]),
        connected_component_id=str(observed["connected_component_id"]),
        kind=str(observed["kind"]),
        net_name=str(observed.get("net_name", "")) or None,
        layer=str(observed.get("layer", "")) or None,
        position_mm=position_mm,
    )


def _reason(endpoints: tuple[ClassifiedEndpoint, ...]) -> OpenFailureReason:
    if any(item.semantic_item_id is None for item in endpoints):
        return OpenFailureReason.UNRESOLVED_BOARD_ITEM
    kinds = tuple(item.kind for item in endpoints)
    layers = {item.layer for item in endpoints if item.layer}
    uuids = {item.uuid for item in endpoints}
    if len(uuids) == 1 and kinds and all(kind == "zone" for kind in kinds):
        return OpenFailureReason.DISCONNECTED_FILLED_ZONE_ISLANDS
    if len(layers) > 1:
        return OpenFailureReason.MISSING_INTERLAYER_TRANSITION
    if "zone" in kinds:
        return OpenFailureReason.ZONE_ATTACHMENT_GAP
    if "pad" in kinds and any(kind in {"track", "via"} for kind in kinds):
        return OpenFailureReason.PAD_ESCAPE_GAP
    if kinds and all(kind in {"track", "via"} for kind in kinds):
        return OpenFailureReason.TRACK_GAP_OR_ISLAND
    if kinds and all(kind == "pad" for kind in kinds):
        return OpenFailureReason.NO_COPPER_PATH
    return OpenFailureReason.DISCONNECTED_COPPER_COMPONENTS


def classify_board_failures(
    *,
    board_sha256: str,
    drc_sha256: str,
    drc_payload: dict[str, object],
    observation: dict[str, object],
    repair_plan: PlacementEscapeRepairPlan | None = None,
) -> BoardFailureClassification:
    """Classify one exact KiCad DRC report against one pcbnew observation."""

    raw_items = observation.get("items", [])
    item_by_uuid: dict[str, object] = (
        {
            str(item["uuid"]): item
            for item in raw_items
            if isinstance(item, dict) and item.get("uuid")
        }
        if isinstance(raw_items, list)
        else {}
    )
    raw_opens = drc_payload.get("unconnected_items", [])
    raw_violations = drc_payload.get("violations", [])
    if not isinstance(raw_opens, list) or not isinstance(raw_violations, list):
        raise TypeError("KiCad DRC report has invalid finding lists")

    opens: list[ClassifiedOpen] = []
    endpoints: tuple[ClassifiedEndpoint, ...]
    for index, raw in enumerate(raw_opens):
        if not isinstance(raw, dict):
            endpoints = (ClassifiedEndpoint(description="unidentified", uuid="unresolved"),)
        else:
            members = raw.get("items", [])
            endpoints = tuple(
                _endpoint(item, item_by_uuid)
                for item in (members if isinstance(members, list) else [])
            ) or (
                ClassifiedEndpoint(
                    description=str(raw.get("description", "unidentified")), uuid="unresolved"
                ),
            )
        # A self-zone DRC record denotes distinct filled islands despite one zone UUID.
        if len({item.uuid for item in endpoints}) == 1 and all(
            item.kind == "zone" for item in endpoints
        ):
            endpoints = tuple(
                item.model_copy(
                    update={
                        "connected_component_id": f"{item.connected_component_id}:island:{ordinal}"
                    }
                )
                for ordinal, item in enumerate(endpoints)
            )
        reason = _reason(endpoints)
        endpoint_fingerprint = _fingerprint([item.model_dump(mode="json") for item in endpoints])
        opens.append(
            ClassifiedOpen(
                failure_id=f"open:{index:04d}:{endpoint_fingerprint[:16]}",
                reason=reason,
                endpoints=endpoints,
            )
        )

    violations: list[ClassifiedViolation] = []
    for index, raw in enumerate(raw_violations):
        item = raw if isinstance(raw, dict) else {}
        members = item.get("items", [])
        descriptions = tuple(
            str(member.get("description", "unidentified"))
            for member in (members if isinstance(members, list) else [])
            if isinstance(member, dict)
        )
        violation_type = str(item.get("type", "unknown"))
        violation_fingerprint = _fingerprint([violation_type, descriptions])
        violations.append(
            ClassifiedViolation(
                failure_id=f"violation:{index:04d}:{violation_fingerprint[:16]}",
                violation_type=violation_type,
                severity=str(item.get("severity", "unknown")),
                descriptions=descriptions,
            )
        )

    escape_audits = observation.get("pad_escape_audits", [])
    audits = (
        [item for item in escape_audits if isinstance(item, dict)]
        if isinstance(escape_audits, list)
        else []
    )
    required = [item for item in audits if item.get("required") is True]
    missing_current = tuple(
        sorted(str(item["pad_id"]) for item in required if not item.get("current_legal_candidates"))
    )
    missing_any = tuple(
        sorted(
            str(item["pad_id"])
            for item in required
            if not item.get("any_rotation_legal_candidates")
        )
    )
    current_legal = sum(bool(item.get("current_legal_candidates")) for item in required)
    any_legal = sum(bool(item.get("any_rotation_legal_candidates")) for item in required)
    reconciled_open = sum(
        item.reason is not OpenFailureReason.UNRESOLVED_BOARD_ITEM for item in opens
    )
    reconciliation = reconciled_open == len(raw_opens) and len(violations) == len(raw_violations)
    if repair_plan is not None:
        if repair_plan.source_board_sha256 != board_sha256:
            raise ValueError("repair plan belongs to another board revision")
        if repair_plan.performed and repair_plan.base_blocked_pads != missing_current:
            raise ValueError("repair plan blocked-pad set is stale")
    if missing_any and repair_plan is not None and repair_plan.candidates:
        feasibility = TwoLayerFeasibility.BOUNDED_PLACEMENT_CHANGE_AVAILABLE
    elif (
        missing_any
        and repair_plan is not None
        and repair_plan.root_cause is EscapeRepairRootCause.INTRINSIC_FOOTPRINT_ESCAPE
    ):
        feasibility = TwoLayerFeasibility.ESCAPE_TECHNOLOGY_OR_FOOTPRINT_CHANGE_REQUIRED
    elif missing_any:
        feasibility = TwoLayerFeasibility.PLACEMENT_TRANSLATION_SIZE_OR_LAYER_CHANGE_REQUIRED
    elif missing_current:
        feasibility = TwoLayerFeasibility.PLACEMENT_CHANGE_REQUIRED
    elif required:
        feasibility = TwoLayerFeasibility.FEASIBLE_CURRENT_PLACEMENT
    else:
        feasibility = TwoLayerFeasibility.INDETERMINATE
    payload: dict[str, object] = {
        "schema_id": "pcbsmith-board-failure-classification",
        "schema_version": 1,
        "board_sha256": board_sha256,
        "drc_sha256": drc_sha256,
        "opens": [item.model_dump(mode="json") for item in opens],
        "violations": [item.model_dump(mode="json") for item in violations],
        "observed_unconnected_count": len(raw_opens),
        "observed_violation_count": len(raw_violations),
        "reconciled_unconnected_count": reconciled_open,
        "reconciled_violation_count": len(violations),
        "reconciliation_complete": reconciliation,
        "current_required_escape_count": len(required),
        "current_legal_escape_count": current_legal,
        "all_rotations_required_escape_count": len(required),
        "all_rotations_legal_escape_count": any_legal,
        "required_pads_without_current_escape": list(missing_current),
        "required_pads_without_any_rotation_escape": list(missing_any),
        "bounded_repair_plan_fingerprint": repair_plan.plan_fingerprint if repair_plan else None,
        "bounded_repair_evaluated_proposal_count": repair_plan.evaluated_proposal_count
        if repair_plan
        else 0,
        "bounded_repair_candidate_count": len(repair_plan.candidates) if repair_plan else 0,
        "escape_repair_root_cause": repair_plan.root_cause if repair_plan else None,
        "escape_repair_terminal_reason": repair_plan.terminal_reason if repair_plan else None,
        "two_layer_feasibility": feasibility,
        "placement_gate_passed": reconciliation and not missing_current,
    }
    payload["classification_fingerprint"] = _fingerprint(payload)
    return BoardFailureClassification.model_validate(payload)
