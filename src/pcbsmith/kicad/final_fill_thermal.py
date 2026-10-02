"""Hash-bound KiCad thermal-relief adequacy evidence for final filled copper."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.final_fill_connectivity import KiCadFinalFillConnectivityObservation
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class ThermalSpokeDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    UNVERIFIED = "unverified"


class KiCadThermalSpokeAudit(SemanticIrModel):
    schema_id: Literal["pcbsmith-kicad-thermal-spoke-audit-v1"] = (
        "pcbsmith-kicad-thermal-spoke-audit-v1"
    )
    board_sha256: str
    drc_report_file: str
    drc_report_sha256: str
    kicad_version: str
    evaluated_pad_ids: tuple[str, ...]
    unresolved_pad_ids: tuple[str, ...]
    starved_thermal_violation_ids: tuple[str, ...]
    evaluated_object_count: int = Field(ge=0)
    disposition: ThermalSpokeDisposition
    qualification_boundary: str
    evidence_fingerprint: str

    @model_validator(mode="after")
    def audit_is_coherent(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.drc_report_sha256, "drc_report_sha256")
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        evaluated = tuple(sorted(self.evaluated_pad_ids))
        unresolved = tuple(sorted(self.unresolved_pad_ids))
        violations = tuple(sorted(self.starved_thermal_violation_ids))
        for label, values in (
            ("evaluated pad", evaluated),
            ("unresolved pad", unresolved),
            ("thermal violation", violations),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} identities must be unique")
        if self.evaluated_object_count != len(evaluated):
            raise ValueError("thermal evaluated-object count is stale")
        expected = (
            ThermalSpokeDisposition.UNVERIFIED
            if unresolved
            else ThermalSpokeDisposition.NOT_APPLICABLE
            if not evaluated
            else ThermalSpokeDisposition.FAIL
            if violations
            else ThermalSpokeDisposition.PASS
        )
        if self.disposition is not expected:
            raise ValueError("thermal-spoke disposition is stale")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != fingerprint(payload):
            raise ValueError("thermal-spoke evidence fingerprint is stale")
        object.__setattr__(self, "evaluated_pad_ids", evaluated)
        object.__setattr__(self, "unresolved_pad_ids", unresolved)
        object.__setattr__(self, "starved_thermal_violation_ids", violations)
        return self


def audit_kicad_thermal_spokes(
    observation: KiCadFinalFillConnectivityObservation,
    drc_report: Path,
    *,
    drc_report_board_sha256: str,
) -> KiCadThermalSpokeAudit:
    """Bind KiCad's starved-thermal DRC result to enumerated final-fill contacts."""

    require_sha256(drc_report_board_sha256, "drc_report_board_sha256")
    if drc_report_board_sha256 != observation.board_sha256:
        raise ValueError("DRC report targets another board revision")
    report = drc_report.resolve()
    raw = report.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("violations", []), list):
        raise ValueError("KiCad DRC report must contain a violations list")
    evaluated = tuple(
        sorted({pad for record in observation.records for pad in record.thermal_applicable_pad_ids})
    )
    unresolved = tuple(
        sorted(
            {
                pad
                for record in observation.records
                for pad in record.thermal_resolution_unverified_pad_ids
            }
        )
    )
    violations = tuple(
        sorted(
            _violation_id(index, violation)
            for index, violation in enumerate(data.get("violations", []))
            if isinstance(violation, dict) and violation.get("type") == "starved_thermal"
        )
    )
    disposition = (
        ThermalSpokeDisposition.UNVERIFIED
        if unresolved
        else ThermalSpokeDisposition.NOT_APPLICABLE
        if not evaluated
        else ThermalSpokeDisposition.FAIL
        if violations
        else ThermalSpokeDisposition.PASS
    )
    fields: dict[str, Any] = {
        "board_sha256": observation.board_sha256,
        "drc_report_file": str(report),
        "drc_report_sha256": hashlib.sha256(raw).hexdigest(),
        "kicad_version": observation.kicad_version,
        "evaluated_pad_ids": evaluated,
        "unresolved_pad_ids": unresolved,
        "starved_thermal_violation_ids": violations,
        "evaluated_object_count": len(evaluated),
        "disposition": disposition,
        "qualification_boundary": (
            "KiCad final-fill pad/zone connection-mode applicability plus exact-revision "
            "starved_thermal DRC. This does not establish electrical ampacity or temperature."
        ),
    }
    provisional = KiCadThermalSpokeAudit.model_construct(
        **fields, evidence_fingerprint="0" * 64
    )
    return KiCadThermalSpokeAudit(
        **fields,
        evidence_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
        ),
    )


def _violation_id(index: int, violation: dict[str, Any]) -> str:
    uuids = tuple(
        sorted(
            str(item.get("uuid"))
            for item in violation.get("items", [])
            if isinstance(item, dict) and item.get("uuid")
        )
    )
    return fingerprint({"index": index, "type": "starved_thermal", "uuids": uuids})


__all__ = [
    "KiCadThermalSpokeAudit",
    "ThermalSpokeDisposition",
    "audit_kicad_thermal_spokes",
]
