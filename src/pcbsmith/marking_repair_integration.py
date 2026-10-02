"""W9-to-W8 adapter: exact KiCad marking findings become bounded repair requests."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import model_validator

from pcbsmith.automatic_review_gate import ProductionMarkingAudit
from pcbsmith.bounded_local_repair import (
    LocalRepairBudget,
    LocalRepairRequest,
    RepairFindingClass,
)
from pcbsmith.production_marking_adapter import _drc_finding_id
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class MarkingRepairPlan(SemanticIrModel):
    schema_id: Literal["pcbsmith-marking-repair-plan-v1"] = (
        "pcbsmith-marking-repair-plan-v1"
    )
    board_sha256: str
    marking_audit_fingerprint: str
    source_qualification_fingerprint: str
    repair_requests: tuple[LocalRepairRequest, ...]
    unlocalized_finding_ids: tuple[str, ...]
    plan_fingerprint: str

    @model_validator(mode="after")
    def plan_is_canonical(self) -> Self:
        for name in (
            "board_sha256",
            "marking_audit_fingerprint",
            "source_qualification_fingerprint",
            "plan_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        requests = tuple(sorted(self.repair_requests, key=lambda item: item.request_id))
        if len(requests) != len({item.request_id for item in requests}):
            raise ValueError("marking repair request identities must be unique")
        if any(item.source_board_sha256 != self.board_sha256 for item in requests):
            raise ValueError("marking repair request targets another board")
        unlocalized = tuple(sorted(self.unlocalized_finding_ids))
        if len(unlocalized) != len(set(unlocalized)):
            raise ValueError("unlocalized marking findings must be unique")
        object.__setattr__(self, "repair_requests", requests)
        object.__setattr__(self, "unlocalized_finding_ids", unlocalized)
        payload = self.model_dump(mode="json", exclude={"plan_fingerprint"})
        if self.plan_fingerprint != fingerprint(payload):
            raise ValueError("marking repair plan fingerprint is stale")
        return self


def build_marking_repair_plan(
    *,
    audit: ProductionMarkingAudit,
    drc_report: Path,
    source_qualification_fingerprint: str,
    budget: LocalRepairBudget,
    margin_mm: float = 2.0,
) -> MarkingRepairPlan:
    require_sha256(source_qualification_fingerprint, "source_qualification_fingerprint")
    if margin_mm <= 0:
        raise ValueError("marking repair localization margin must be positive")
    report = drc_report.resolve()
    raw = report.read_bytes()
    if hashlib.sha256(raw).hexdigest() != audit.drc_report_sha256:
        raise ValueError("marking repair DRC differs from the audited report")
    data = json.loads(raw)
    violations = data.get("violations", []) if isinstance(data, dict) else None
    if not isinstance(violations, list):
        raise ValueError("KiCad DRC report must contain a violations list")
    audited = set(audit.finding_ids)
    localized: set[str] = set()
    requests: list[LocalRepairRequest] = []
    marking_types = {
        "silk_over_copper",
        "silk_overlap",
        "silk_edge_clearance",
    }
    for index, violation in enumerate(violations):
        if not isinstance(violation, dict):
            continue
        kind = str(violation.get("type", ""))
        if kind not in marking_types and "courtyard" not in kind:
            continue
        finding_id = _drc_finding_id(index, violation)
        if finding_id not in audited:
            continue
        items = tuple(item for item in violation.get("items", []) if isinstance(item, dict))
        positioned = tuple(
            item
            for item in items
            if isinstance(item.get("pos"), dict)
            and isinstance(item["pos"].get("x"), (int, float))
            and isinstance(item["pos"].get("y"), (int, float))
        )
        if not positioned:
            continue
        xs = tuple(float(item["pos"]["x"]) for item in positioned)
        ys = tuple(float(item["pos"]["y"]) for item in positioned)
        descriptions = tuple(str(item.get("description", "")) for item in items)
        references = tuple(
            sorted(
                {
                    match.group(1)
                    for description in descriptions
                    for match in re.finditer(r"\bof ([A-Za-z]+\d+)\b", description)
                    if "Reference field" in description
                }
            )
        )
        immutable = tuple(
            sorted(
                str(item["uuid"])
                for item in items
                if item.get("uuid")
                and "Silkscreen" not in str(item.get("description", ""))
                and "Reference field" not in str(item.get("description", ""))
            )
        )
        request_id = f"marking:{fingerprint([audit.board_sha256, finding_id])}"
        requests.append(
            LocalRepairRequest.build(
                request_id=request_id,
                source_board_sha256=audit.board_sha256,
                source_qualification_fingerprint=source_qualification_fingerprint,
                finding_class=RepairFindingClass.SILKSCREEN_OVERLAP,
                target_finding_ids=(finding_id,),
                target_region_mm=(
                    min(xs) - margin_mm,
                    min(ys) - margin_mm,
                    max(xs) + margin_mm,
                    max(ys) + margin_mm,
                ),
                affected_net_names=(),
                immutable_object_ids=immutable,
                movable_component_references=references,
                rip_authorized_copper_ids=(),
                budget=budget,
            )
        )
        localized.add(finding_id)
    fields: dict[str, Any] = {
        "board_sha256": audit.board_sha256,
        "marking_audit_fingerprint": audit.evidence_fingerprint,
        "source_qualification_fingerprint": source_qualification_fingerprint,
        "repair_requests": tuple(sorted(requests, key=lambda item: item.request_id)),
        "unlocalized_finding_ids": tuple(sorted(audited - localized)),
    }
    provisional = MarkingRepairPlan.model_construct(**fields, plan_fingerprint="0" * 64)
    return MarkingRepairPlan(
        **fields,
        plan_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"plan_fingerprint"})
        ),
    )


__all__ = ["MarkingRepairPlan", "build_marking_repair_plan"]
