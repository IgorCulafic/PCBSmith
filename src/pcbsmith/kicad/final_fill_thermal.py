"""Hash-bound KiCad thermal-relief adequacy evidence for final filled copper."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.check_reports import drc_sections, validate_native_header
from pcbsmith.kicad.final_fill_adapter import verify_native_fill_execution
from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFinalFillConnectivityObservation,
    thermal_contact_inventory,
)
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
    project_sha256: str | None = Field(default=None, exclude_if=lambda v: v is None)
    native_rules_sha256: str | None = Field(default=None, exclude_if=lambda v: v is None)
    native_execution_fingerprint: str | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def audit_is_coherent(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.drc_report_sha256, "drc_report_sha256")
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        if self.project_sha256 is not None:
            require_sha256(self.project_sha256, "project_sha256")
        if self.native_rules_sha256 is not None:
            require_sha256(self.native_rules_sha256, "native_rules_sha256")
        if self.native_execution_fingerprint is not None:
            require_sha256(self.native_execution_fingerprint, "native_execution_fingerprint")
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
            ThermalSpokeDisposition.FAIL
            if violations
            else ThermalSpokeDisposition.UNVERIFIED
            if unresolved
            else ThermalSpokeDisposition.NOT_APPLICABLE
            if not evaluated
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


def thermal_rule_context(project_file: Path) -> str:
    """Bind project severities and the presence/content of the custom-rule file."""
    rules = project_file.with_suffix(".kicad_dru")
    return fingerprint(
        {
            "project": hashlib.sha256(project_file.read_bytes()).hexdigest(),
            "custom_rules": hashlib.sha256(rules.read_bytes()).hexdigest()
            if rules.is_file()
            else None,
        }
    )


def audit_kicad_thermal_spokes(
    observation: KiCadFinalFillConnectivityObservation,
    drc_report: Path,
    *,
    drc_report_board_sha256: str,
    project_file: Path | None = None,
) -> KiCadThermalSpokeAudit:
    """Bind KiCad's starved-thermal DRC result to enumerated final-fill contacts."""

    require_sha256(drc_report_board_sha256, "drc_report_board_sha256")
    if drc_report_board_sha256 != observation.board_sha256:
        raise ValueError("DRC report targets another board revision")
    report = drc_report.resolve()
    raw = report.read_bytes()
    data = json.loads(raw)
    data = validate_native_header(data, "DRC", Path(observation.board_file))
    sections = drc_sections(data)
    if data["kicad_version"] != observation.kicad_version:
        raise ValueError("thermal observation and native DRC producer versions differ")
    evaluated, unresolved = thermal_contact_inventory(observation)
    project_sha256 = None
    native_rules_sha256 = None
    native_execution_fingerprint = None
    if evaluated or unresolved:
        if project_file is None:
            raise ValueError("applicable thermal audit requires the native project rule baseline")
        if project_file.name != Path(observation.board_file).with_suffix(".kicad_pro").name:
            raise ValueError("thermal rule baseline targets another project")
        project_raw = project_file.read_bytes()
        settings = json.loads(project_raw).get("board_design_settings", {})
        if settings.get("rule_severities", {}).get("starved_thermal") not in {"error", "warning"}:
            raise ValueError("starved_thermal must have an explicit enabled native severity")
        if settings.get("drc_exclusions", []):
            raise ValueError("thermal qualification requires an exclusion-free native baseline")
        if any(v.get("excluded", False) for values in sections.values() for v in values):
            raise ValueError("thermal qualification cannot consume excluded native findings")
        project_sha256 = hashlib.sha256(project_raw).hexdigest()
        native_rules_sha256 = thermal_rule_context(project_file)
        custom = project_file.with_suffix(".kicad_dru")
        if custom.is_file():
            rules_text = re.sub(r"(?m)#.*$", "", custom.read_text(encoding="utf-8"))
            if re.search(r"\(severity\s+ignore\s*\)", rules_text) or re.search(
                r"\(constraint\s+min_resolved_spokes\s+0\s*\)", rules_text
            ):
                raise ValueError("thermal qualification cannot use custom rule suppression")
        executed = verify_native_fill_execution(project_file.with_suffix(".kicad_pcb"), report)
        if (
            executed["board_sha256"] != observation.board_sha256
            or executed["kicad_version"] != observation.kicad_version
        ):
            raise ValueError("thermal execution targets another board or KiCad version")
        native_execution_fingerprint = executed["fingerprint"]
    violations = tuple(
        sorted(
            _violation_id(index, violation)
            for index, violation in enumerate(sections["violations"])
            if isinstance(violation, dict) and violation.get("type") == "starved_thermal"
        )
    )
    disposition = (
        ThermalSpokeDisposition.FAIL
        if violations
        else ThermalSpokeDisposition.UNVERIFIED
        if unresolved
        else ThermalSpokeDisposition.NOT_APPLICABLE
        if not evaluated
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
        "project_sha256": project_sha256,
        "native_rules_sha256": native_rules_sha256,
        "native_execution_fingerprint": native_execution_fingerprint,
    }
    provisional = KiCadThermalSpokeAudit.model_construct(**fields, evidence_fingerprint="0" * 64)
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
