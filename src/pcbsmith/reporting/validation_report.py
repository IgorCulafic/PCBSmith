from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcbsmith.kicad.kicad_preview import KiCadPreviewReport
from pcbsmith.kicad.kicad_validate import KiCadValidationReport
from pcbsmith.rules.board_manufacturability import (
    BoardManufacturabilityReport,
    ManufacturabilitySeverity,
)
from pcbsmith.rules.circuit_rules import CircuitRuleReport, CircuitRuleSeverity

VALIDATION_REPORT_SCHEMA = "pcbsmith-validation-report-v1"
VALIDATION_REPORT_TOOL_SCHEMA = "pcbsmith-validation-report-tool-v1"


def build_validation_report(
    *,
    project_name: str,
    topology: dict[str, Any] | None = None,
    component_candidates: list[dict[str, Any]] | None = None,
    calculator_results: list[dict[str, Any]] | None = None,
    validation_report: KiCadValidationReport | None = None,
    preview_report: KiCadPreviewReport | None = None,
    manufacturability_report: BoardManufacturabilityReport | None = None,
    circuit_rule_reports: tuple[CircuitRuleReport, ...] = (),
    human_review_items: list[str] | None = None,
) -> dict[str, Any]:
    component_candidates = component_candidates or []
    calculator_results = calculator_results or []
    human_review_items = human_review_items or []
    findings = [
        *_calculator_findings(calculator_results),
        *_kicad_findings(validation_report),
        *_preview_findings(preview_report),
        *_manufacturability_findings(manufacturability_report),
        *_circuit_rule_findings(circuit_rule_reports),
        *_human_review_findings(human_review_items),
    ]
    summary = _summary(
        findings,
        calculator_count=len(calculator_results),
        component_candidate_count=len(component_candidates),
        preview_artifact_count=len(preview_report.artifacts) if preview_report else 0,
    )
    return {
        "schema": VALIDATION_REPORT_SCHEMA,
        "project": {"name": project_name},
        "status": _status(summary),
        "summary": summary,
        "topology": topology or {},
        "component_candidates": component_candidates,
        "calculators": calculator_results,
        "checks": {
            "kicad": _kicad_checks(validation_report),
            "preview": _preview_artifacts(preview_report),
            "manufacturability": _manufacturability_summary(manufacturability_report),
            "circuit_rules": _circuit_rule_summaries(circuit_rule_reports),
        },
        "findings": findings,
        "next_actions": _next_actions(summary),
    }


def format_validation_report_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# PCBSmith Validation Summary",
        "",
        f"- Project: {report['project']['name']}",
        f"- Status: {report['status']}",
        f"- Errors: {summary['error_count']}",
        f"- Warnings: {summary['warning_count']}",
        f"- Advisories: {summary['advisory_count']}",
        "",
    ]
    findings = report["findings"]
    if findings:
        lines.extend(["## Findings", ""])
        lines.extend(
            (
                f"- {finding['severity']} {finding['source']}/{finding['code']}: "
                f"{finding['message']} ({finding['location']})"
            )
            for finding in findings
        )
    else:
        lines.append("No validation findings found.")

    next_actions = report["next_actions"]
    if next_actions:
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {action}" for action in next_actions)
    return "\n".join(lines) + "\n"


def write_validation_report_files(report: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "validation-summary.json"
    markdown_path = output_dir / "validation-summary.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(format_validation_report_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def validation_report_tool_contract() -> dict[str, Any]:
    return {
        "schema": VALIDATION_REPORT_TOOL_SCHEMA,
        "output_files": [
            ".pcbsmith/reports/validation-summary.json",
            ".pcbsmith/reports/validation-summary.md",
        ],
        "instructions": [
            "Treat blocked validation reports as stopping conditions.",
            "Use validation report findings and next_actions before proposing revisions.",
            (
                "Include calculator and KiCad evidence when explaining why a board "
                "is ready or not ready."
            ),
        ],
    }


def _summary(
    findings: list[dict[str, str]],
    *,
    calculator_count: int,
    component_candidate_count: int,
    preview_artifact_count: int,
) -> dict[str, int]:
    return {
        "error_count": sum(1 for finding in findings if finding["severity"] == "error"),
        "warning_count": sum(1 for finding in findings if finding["severity"] == "warning"),
        "advisory_count": sum(
            1 for finding in findings if finding["severity"] == "advisory"
        ),
        "calculator_count": calculator_count,
        "component_candidate_count": component_candidate_count,
        "preview_artifact_count": preview_artifact_count,
    }


def _status(summary: dict[str, int]) -> str:
    if summary["error_count"] > 0:
        return "blocked"
    if summary["warning_count"] > 0 or summary["advisory_count"] > 0:
        return "needs_review"
    return "passed"


def _next_actions(summary: dict[str, int]) -> list[str]:
    actions: list[str] = []
    if summary["error_count"] > 0:
        actions.append("Fix blocking validation errors before fabrication or release.")
    if summary["warning_count"] > 0:
        actions.append("Review warnings and either revise the design or explicitly accept them.")
    if (
        summary["error_count"] == 0
        and summary["warning_count"] == 0
        and summary["advisory_count"] > 0
    ):
        actions.append("Review advisory items before presenting or fabricating the design.")
    if (
        summary["error_count"] > 0
        or summary["warning_count"] > 0
        or summary["advisory_count"] > 0
    ):
        actions.append(
            "Re-run calculators and validation after any schematic, layout, or value change."
        )
    return actions


def _calculator_findings(calculator_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for result in calculator_results:
        if result.get("status") == "error":
            findings.append(
                _finding(
                    "error",
                    "calculator",
                    str(result.get("calculator", "unknown")),
                    str(result.get("error", "Calculator failed")),
                    "calculation",
                )
            )
        for warning in result.get("warnings", []):
            findings.append(
                _finding(
                    "advisory",
                    "calculator",
                    str(result.get("calculator", "warning")),
                    str(warning),
                    "calculation",
                )
            )
    return findings


def _kicad_findings(report: KiCadValidationReport | None) -> list[dict[str, str]]:
    if report is None:
        return []
    findings: list[dict[str, str]] = []
    if report.problem is not None:
        findings.append(
            _finding(
                "error",
                "kicad_validation",
                "validation_unavailable",
                report.problem,
                str(report.project_dir),
            )
        )
    for check in report.checks:
        if check.status not in {"failed", "error"}:
            continue
        message = check.message or (
            f"{check.name} {check.status} with {check.violations} violation(s) "
            f"and {check.unconnected_items} unconnected item(s)"
        )
        findings.append(
            _finding(
                "error",
                "kicad_validation",
                f"{check.name.lower()}_{check.status}",
                message,
                str(check.input_file),
            )
        )
    return findings


def _preview_findings(report: KiCadPreviewReport | None) -> list[dict[str, str]]:
    if report is None:
        return []
    findings: list[dict[str, str]] = []
    if report.problem is not None:
        findings.append(
            _finding(
                "error",
                "kicad_preview",
                "preview_unavailable",
                report.problem,
                str(report.project_dir),
            )
        )
    for artifact in report.artifacts:
        if artifact.status == "error":
            findings.append(
                _finding(
                    "error",
                    "kicad_preview",
                    f"{artifact.kind}_export_failed",
                    artifact.message or "KiCad preview export failed",
                    str(artifact.input_file),
                )
            )
    return findings


def _manufacturability_findings(
    report: BoardManufacturabilityReport | None,
) -> list[dict[str, str]]:
    if report is None:
        return []
    return [
        _finding(
            "error" if finding.severity is ManufacturabilitySeverity.ERROR else "warning",
            "board_manufacturability",
            finding.code,
            finding.message,
            finding.location,
        )
        for finding in report.findings
    ]


def _circuit_rule_findings(
    reports: tuple[CircuitRuleReport, ...],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for report in reports:
        findings.extend(
            _finding(
                "error" if finding.severity is CircuitRuleSeverity.ERROR else "warning",
                "circuit_rules",
                finding.code,
                finding.message,
                finding.location,
            )
            for finding in report.findings
        )
    return findings


def _human_review_findings(items: list[str]) -> list[dict[str, str]]:
    return [
        _finding("advisory", "human_review", "user_check", item, "human review")
        for item in items
    ]


def _kicad_checks(report: KiCadValidationReport | None) -> list[dict[str, Any]]:
    if report is None:
        return []
    return [
        {
            "name": check.name,
            "status": check.status,
            "violations": check.violations,
            "unconnected_items": check.unconnected_items,
            "input_file": str(check.input_file),
            "report_file": str(check.report_file),
        }
        for check in report.checks
    ]


def _preview_artifacts(report: KiCadPreviewReport | None) -> list[dict[str, str | None]]:
    if report is None:
        return []
    return [
        {
            "kind": artifact.kind,
            "status": artifact.status,
            "input_file": str(artifact.input_file),
            "output_file": str(artifact.output_file),
            "message": artifact.message,
        }
        for artifact in report.artifacts
    ]


def _manufacturability_summary(
    report: BoardManufacturabilityReport | None,
) -> dict[str, int | str]:
    if report is None:
        return {"status": "not_run", "finding_count": 0, "error_count": 0, "warning_count": 0}
    error_count = sum(
        1 for finding in report.findings if finding.severity is ManufacturabilitySeverity.ERROR
    )
    warning_count = len(report.findings) - error_count
    return {
        "status": "passed" if not report.findings else "issues_found",
        "finding_count": len(report.findings),
        "error_count": error_count,
        "warning_count": warning_count,
    }


def _circuit_rule_summaries(
    reports: tuple[CircuitRuleReport, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "intent": report.intent,
            "status": report.status,
            "calculations": report.calculations,
            "finding_count": len(report.findings),
        }
        for report in reports
    ]


def _finding(
    severity: str,
    source: str,
    code: str,
    message: str,
    location: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "source": source,
        "code": code,
        "message": message,
        "location": location,
    }


__all__ = [
    "VALIDATION_REPORT_SCHEMA",
    "VALIDATION_REPORT_TOOL_SCHEMA",
    "build_validation_report",
    "format_validation_report_markdown",
    "validation_report_tool_contract",
    "write_validation_report_files",
]
