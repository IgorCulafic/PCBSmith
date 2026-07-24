from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pcbsmith.ai.ai_plan_check import AIPlanCheckResult
from pcbsmith.kicad.kicad_preview import KiCadPreviewReport
from pcbsmith.kicad.kicad_validate import KiCadValidationReport
from pcbsmith.rules.board_manufacturability import (
    BoardManufacturabilityReport,
    ManufacturabilitySeverity,
)
from pcbsmith.rules.circuit_rules import CircuitRuleReport, CircuitRuleSeverity
from pcbsmith.rules.kicad_board_policy import (
    KiCadBoardPolicyReport,
    KiCadBoardPolicySeverity,
)

REVISION_BRIEF_SCHEMA = "pcbsmith-revision-brief-v1"

REVISION_NEXT_ACTIONS = (
    "Revise the candidate plan using only approved PCBSmith commands.",
    "Re-run circuit rules for changed electrical assumptions.",
    "Regenerate the KiCad review bundle and confirm ERC, DRC, and manufacturability.",
    "Ask for user approval before applying revised edits.",
)


class RevisionSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    ADVISORY = "advisory"


@dataclass(frozen=True)
class RevisionBriefItem:
    severity: RevisionSeverity
    source: str
    code: str
    message: str
    location: str

    def to_data(self) -> dict[str, str]:
        return {
            "severity": self.severity.value,
            "source": self.source,
            "code": self.code,
            "message": self.message,
            "location": self.location,
        }


@dataclass(frozen=True)
class RevisionBrief:
    items: tuple[RevisionBriefItem, ...]
    visual_review_status: str = "not_run"
    visual_review_message: str = "No multimodal visual review has been attached."

    @property
    def status(self) -> str:
        if any(
            item.severity in {RevisionSeverity.ERROR, RevisionSeverity.WARNING}
            for item in self.items
        ):
            return "needs_revision"
        if self.items:
            return "passed_with_advisories"
        return "passed"

    def to_data(self) -> dict[str, Any]:
        error_count = sum(
            1 for item in self.items if item.severity is RevisionSeverity.ERROR
        )
        warning_count = sum(
            1 for item in self.items if item.severity is RevisionSeverity.WARNING
        )
        advisory_count = sum(
            1 for item in self.items if item.severity is RevisionSeverity.ADVISORY
        )
        return {
            "schema": REVISION_BRIEF_SCHEMA,
            "status": self.status,
            "visual_review": {
                "status": self.visual_review_status,
                "authority": "advisory",
                "message": self.visual_review_message,
            },
            "summary": {
                "item_count": len(self.items),
                "error_count": error_count,
                "warning_count": warning_count,
                "advisory_count": advisory_count,
            },
            "items": [item.to_data() for item in self.items],
            "next_actions": (
                list(REVISION_NEXT_ACTIONS)
                if error_count > 0 or warning_count > 0
                else []
            ),
        }


def build_revision_brief(
    *,
    plan_check: AIPlanCheckResult | None = None,
    validation_report: KiCadValidationReport | None = None,
    preview_report: KiCadPreviewReport | None = None,
    manufacturability_report: BoardManufacturabilityReport | None = None,
    kicad_board_policy_report: KiCadBoardPolicyReport | None = None,
    circuit_rule_reports: tuple[CircuitRuleReport, ...] = (),
    visual_review_status: str = "not_run",
    visual_review_message: str = "No multimodal visual review has been attached.",
    visual_review_items: tuple[Mapping[str, str], ...] = (),
) -> RevisionBrief:
    items: list[RevisionBriefItem] = []
    if plan_check is not None:
        items.extend(_plan_check_items(plan_check))
    if validation_report is not None:
        items.extend(_validation_items(validation_report))
    if preview_report is not None:
        items.extend(_preview_items(preview_report))
    if manufacturability_report is not None:
        items.extend(_manufacturability_items(manufacturability_report))
    if kicad_board_policy_report is not None:
        items.extend(_kicad_board_policy_items(kicad_board_policy_report))
    for report in circuit_rule_reports:
        items.extend(_circuit_rule_items(report))
    items.extend(_visual_review_items(visual_review_items))
    return RevisionBrief(
        items=tuple(items),
        visual_review_status=visual_review_status,
        visual_review_message=visual_review_message,
    )


def format_revision_brief(brief: RevisionBrief) -> list[str]:
    item_label = "item" if len(brief.items) == 1 else "items"
    lines = [f"Revision brief: {brief.status} ({len(brief.items)} {item_label})"]
    lines.append(f"Visual review: {brief.visual_review_status} (advisory)")
    if not brief.items:
        lines.append("No revision items found.")
        return lines

    lines.extend(
        (
            f"{item.severity}: {item.source}/{item.code}: "
            f"{item.message} ({item.location})"
        )
        for item in brief.items
    )
    return lines


def write_revision_brief(brief: RevisionBrief, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(brief.to_data(), indent=2) + "\n",
        encoding="utf-8",
    )


def _plan_check_items(plan_check: AIPlanCheckResult) -> tuple[RevisionBriefItem, ...]:
    if plan_check.valid:
        return ()
    return (
        RevisionBriefItem(
            severity=RevisionSeverity.ERROR,
            source="ai_plan_check",
            code="invalid_plan",
            message=_plan_problem_message(plan_check),
            location="candidate plan",
        ),
    )


def _plan_problem_message(plan_check: AIPlanCheckResult) -> str:
    problem_lines = tuple(line for line in plan_check.lines if line.startswith("Problem:"))
    if problem_lines:
        return problem_lines[0]
    return plan_check.lines[-1] if plan_check.lines else "AI plan is invalid"


def _validation_items(
    report: KiCadValidationReport,
) -> tuple[RevisionBriefItem, ...]:
    items: list[RevisionBriefItem] = []
    if report.problem is not None:
        items.append(
            RevisionBriefItem(
                severity=RevisionSeverity.ERROR,
                source="kicad_validation",
                code="validation_unavailable",
                message=report.problem,
                location=str(report.project_dir),
            )
        )

    for check in report.checks:
        if check.status not in {"failed", "error"}:
            continue
        message = (
            check.message
            if check.status == "error" and check.message is not None
            else (
                f"{check.name} {check.status} with {check.violations} violation(s) "
                f"and {check.unconnected_items} unconnected item(s)"
            )
        )
        items.append(
            RevisionBriefItem(
                severity=RevisionSeverity.ERROR,
                source="kicad_validation",
                code=f"{check.name.lower()}_{check.status}",
                message=message,
                location=str(check.input_file),
            )
        )
    return tuple(items)


def _preview_items(report: KiCadPreviewReport) -> tuple[RevisionBriefItem, ...]:
    items: list[RevisionBriefItem] = []
    if report.problem is not None:
        items.append(
            RevisionBriefItem(
                severity=RevisionSeverity.ERROR,
                source="kicad_preview",
                code="preview_unavailable",
                message=report.problem,
                location=str(report.project_dir),
            )
        )

    for artifact in report.artifacts:
        if artifact.status != "error":
            continue
        items.append(
            RevisionBriefItem(
                severity=RevisionSeverity.ERROR,
                source="kicad_preview",
                code=f"{artifact.kind}_export_failed",
                message=artifact.message or "KiCad preview export failed",
                location=str(artifact.input_file),
            )
        )
    return tuple(items)


def _manufacturability_items(
    report: BoardManufacturabilityReport,
) -> tuple[RevisionBriefItem, ...]:
    return tuple(
        RevisionBriefItem(
            severity=_manufacturability_severity(finding.severity),
            source="board_manufacturability",
            code=finding.code,
            message=finding.message,
            location=finding.location,
        )
        for finding in report.findings
    )


def _kicad_board_policy_items(
    report: KiCadBoardPolicyReport,
) -> tuple[RevisionBriefItem, ...]:
    return tuple(
        RevisionBriefItem(
            severity=_kicad_board_policy_severity(finding.severity),
            source="kicad_board_policy",
            code=finding.code,
            message=finding.message,
            location=finding.location,
        )
        for finding in report.findings
    )


def _kicad_board_policy_severity(
    severity: KiCadBoardPolicySeverity,
) -> RevisionSeverity:
    if severity is KiCadBoardPolicySeverity.ERROR:
        return RevisionSeverity.ERROR
    return RevisionSeverity.WARNING


def _manufacturability_severity(
    severity: ManufacturabilitySeverity,
) -> RevisionSeverity:
    if severity is ManufacturabilitySeverity.ERROR:
        return RevisionSeverity.ERROR
    return RevisionSeverity.WARNING


def _circuit_rule_items(report: CircuitRuleReport) -> tuple[RevisionBriefItem, ...]:
    return tuple(
        RevisionBriefItem(
            severity=_circuit_rule_severity(finding.severity),
            source="circuit_rules",
            code=finding.code,
            message=finding.message,
            location=finding.location,
        )
        for finding in report.findings
    )


def _circuit_rule_severity(severity: CircuitRuleSeverity) -> RevisionSeverity:
    if severity is CircuitRuleSeverity.ERROR:
        return RevisionSeverity.ERROR
    return RevisionSeverity.WARNING


def _visual_review_items(
    findings: tuple[Mapping[str, str], ...],
) -> tuple[RevisionBriefItem, ...]:
    return tuple(
        RevisionBriefItem(
            severity=RevisionSeverity.ADVISORY,
            source="visual_review",
            code=finding["code"],
            message=finding["message"],
            location=finding["location"],
        )
        for finding in findings
    )


__all__ = [
    "REVISION_BRIEF_SCHEMA",
    "RevisionBrief",
    "RevisionBriefItem",
    "RevisionSeverity",
    "build_revision_brief",
    "format_revision_brief",
    "write_revision_brief",
]
