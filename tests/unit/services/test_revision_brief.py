from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.services.ai_plan_check import AIPlanCheckResult
from pcbsmith.services.board_manufacturability import (
    BoardManufacturabilityFinding,
    BoardManufacturabilityReport,
    ManufacturabilitySeverity,
)
from pcbsmith.services.circuit_rules import check_circuit_rules
from pcbsmith.services.kicad_validate import KiCadValidationCheck, KiCadValidationReport
from pcbsmith.services.revision_brief import (
    REVISION_BRIEF_SCHEMA,
    build_revision_brief,
    format_revision_brief,
    write_revision_brief,
)


def _validation_report(tmp_path: Path) -> KiCadValidationReport:
    return KiCadValidationReport(
        project_dir=tmp_path / "kicad",
        cli_path=Path("C:/Tools/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
        ready=False,
        problem=None,
        checks=(
            KiCadValidationCheck(
                name="ERC",
                input_file=tmp_path / "demo.kicad_sch",
                report_file=tmp_path / "erc.json",
                status="failed",
                violations=2,
                unconnected_items=0,
                message=None,
            ),
        ),
        exit_code=1,
    )


def test_build_revision_brief_merges_review_findings(tmp_path: Path) -> None:
    plan_check = AIPlanCheckResult(
        valid=False,
        lines=("AI plan: invalid", "Problem: command type is not allowed: delete"),
        exit_code=1,
    )
    circuit_report = check_circuit_rules(
        "low-side-switch",
        {
            "supply_voltage_v": 12,
            "load_current_a": 0.5,
            "gate_drive_voltage_v": 3.3,
            "inductive_load": True,
            "flyback_diode_present": False,
        },
    )
    board_report = BoardManufacturabilityReport(
        findings=(
            BoardManufacturabilityFinding(
                severity=ManufacturabilitySeverity.WARNING,
                code="non_preferred_trace_angle",
                message="Trace uses non-preferred routing",
                location="trace 1 segment 1",
            ),
        )
    )

    brief = build_revision_brief(
        plan_check=plan_check,
        validation_report=_validation_report(tmp_path),
        manufacturability_report=board_report,
        circuit_rule_reports=(circuit_report,),
    )

    assert brief.to_data() == {
        "schema": REVISION_BRIEF_SCHEMA,
        "status": "needs_revision",
        "summary": {
            "item_count": 4,
            "error_count": 2,
            "warning_count": 2,
        },
        "items": [
            {
                "severity": "error",
                "source": "ai_plan_check",
                "code": "invalid_plan",
                "message": "Problem: command type is not allowed: delete",
                "location": "candidate plan",
            },
            {
                "severity": "error",
                "source": "kicad_validation",
                "code": "erc_failed",
                "message": "ERC failed with 2 violation(s) and 0 unconnected item(s)",
                "location": str(tmp_path / "demo.kicad_sch"),
            },
            {
                "severity": "warning",
                "source": "board_manufacturability",
                "code": "non_preferred_trace_angle",
                "message": "Trace uses non-preferred routing",
                "location": "trace 1 segment 1",
            },
            {
                "severity": "warning",
                "source": "circuit_rules",
                "code": "missing_flyback_protection",
                "message": (
                    "Inductive loads need flyback protection across the load or "
                    "switching path"
                ),
                "location": "switched load",
            },
        ],
        "next_actions": [
            "Revise the candidate plan using only approved PCBSmith commands.",
            "Re-run circuit rules for changed electrical assumptions.",
            "Regenerate the KiCad review bundle and confirm ERC, DRC, and manufacturability.",
            "Ask for user approval before applying revised edits.",
        ],
    }


def test_write_revision_brief_writes_pretty_json(tmp_path: Path) -> None:
    output_path = tmp_path / "revision-brief.json"
    brief = build_revision_brief(
        plan_check=AIPlanCheckResult(
            valid=True,
            lines=("AI plan: valid",),
            exit_code=0,
        )
    )

    write_revision_brief(brief, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == brief.to_data()
    assert output_path.read_text(encoding="utf-8").endswith("\n")


def test_format_revision_brief_is_compact() -> None:
    brief = build_revision_brief(
        plan_check=AIPlanCheckResult(
            valid=True,
            lines=("AI plan: valid",),
            exit_code=0,
        )
    )

    assert format_revision_brief(brief) == [
        "Revision brief: passed (0 items)",
        "No revision items found.",
    ]
