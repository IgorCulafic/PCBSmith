from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.calculators.electronics import solve_lc_resonance
from pcbsmith.kicad.kicad_preview import KiCadPreviewArtifact, KiCadPreviewReport
from pcbsmith.kicad.kicad_validate import KiCadValidationCheck, KiCadValidationReport
from pcbsmith.reporting.validation_report import (
    VALIDATION_REPORT_SCHEMA,
    build_validation_report,
    format_validation_report_markdown,
    validation_report_tool_contract,
    write_validation_report_files,
)
from pcbsmith.rules.board_manufacturability import (
    BoardManufacturabilityFinding,
    BoardManufacturabilityReport,
    ManufacturabilitySeverity,
)
from pcbsmith.rules.circuit_rules import (
    CircuitRuleFinding,
    CircuitRuleReport,
    CircuitRuleSeverity,
)
from pcbsmith.rules.kicad_board_policy import (
    KiCadBoardPolicyFinding,
    KiCadBoardPolicyReport,
    KiCadBoardPolicySeverity,
)


def test_validation_report_aggregates_evidence_and_blocks_on_errors(tmp_path: Path) -> None:
    validation = KiCadValidationReport(
        project_dir=tmp_path / "demo",
        cli_path=Path("C:/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
        ready=False,
        problem=None,
        checks=(
            KiCadValidationCheck(
                name="ERC",
                input_file=tmp_path / "demo.kicad_sch",
                report_file=tmp_path / "erc.json",
                status="passed",
                violations=0,
                unconnected_items=0,
                message=None,
            ),
            KiCadValidationCheck(
                name="DRC",
                input_file=tmp_path / "demo.kicad_pcb",
                report_file=tmp_path / "drc.json",
                status="failed",
                violations=2,
                unconnected_items=1,
                message=None,
            ),
        ),
        exit_code=1,
    )
    preview = KiCadPreviewReport(
        project_dir=tmp_path / "demo",
        cli_path=Path("C:/KiCad/bin/kicad-cli.exe"),
        source="PCBSMITH_KICAD_CLI",
        ready=True,
        problem=None,
        artifacts=(
            KiCadPreviewArtifact(
                kind="board",
                input_file=tmp_path / "demo.kicad_pcb",
                output_file=tmp_path / "demo-board.svg",
                status="exported",
                message=None,
            ),
        ),
        exit_code=0,
    )
    manufacturability = BoardManufacturabilityReport(
        findings=(
            BoardManufacturabilityFinding(
                severity=ManufacturabilitySeverity.WARNING,
                code="non_preferred_trace_angle",
                message="Trace SIG uses 17 degree routing",
                location="trace 1 segment 1",
            ),
        )
    )
    kicad_board_policy = KiCadBoardPolicyReport(
        findings=(
            KiCadBoardPolicyFinding(
                severity=KiCadBoardPolicySeverity.ERROR,
                code="via_in_smd_pad_keepout",
                message="Via sits under an SMD pad",
                location="via 1",
            ),
        )
    )
    circuit_rules = (
        CircuitRuleReport(
            intent="power-entry",
            calculations={},
            findings=(
                CircuitRuleFinding(
                    severity=CircuitRuleSeverity.WARNING,
                    code="missing_reverse_polarity_protection",
                    message="Consider reverse-polarity protection",
                    location="power entry",
                ),
            ),
        ),
    )
    calculation = solve_lc_resonance(inductance_uH=35.5609, capacitance_nF=10)

    report = build_validation_report(
        project_name="Metal detector demo",
        topology={"id": "metal-detector-lc-oscillator", "confidence": "medium"},
        component_candidates=[
            {"reference": "Q1", "role": "oscillator transistor", "candidate": "MMBT3904"},
        ],
        calculator_results=[calculation],
        validation_report=validation,
        preview_report=preview,
        manufacturability_report=manufacturability,
        kicad_board_policy_report=kicad_board_policy,
        circuit_rule_reports=circuit_rules,
        human_review_items=["Confirm coil estimate with measured prototype frequency."],
    )

    assert report["schema"] == VALIDATION_REPORT_SCHEMA
    assert report["status"] == "blocked"
    assert report["summary"] == {
        "error_count": 2,
        "warning_count": 2,
        "advisory_count": 1,
        "calculator_count": 1,
        "component_candidate_count": 1,
        "preview_artifact_count": 1,
    }
    assert report["topology"]["id"] == "metal-detector-lc-oscillator"
    assert report["calculators"][0]["calculator"] == "lc-resonance"
    assert report["checks"]["kicad"][1]["status"] == "failed"
    assert report["findings"][0]["source"] == "kicad_validation"
    assert report["findings"][1]["source"] == "board_manufacturability"
    assert report["findings"][2]["source"] == "kicad_board_policy"
    assert report["findings"][3]["source"] == "circuit_rules"
    assert report["findings"][4]["source"] == "human_review"
    assert report["next_actions"] == [
        "Fix blocking validation errors before fabrication or release.",
        "Review warnings and either revise the design or explicitly accept them.",
        "Re-run calculators and validation after any schematic, layout, or value change.",
    ]


def test_validation_report_writes_json_and_markdown(tmp_path: Path) -> None:
    report = build_validation_report(project_name="Clean demo")

    paths = write_validation_report_files(report, tmp_path)

    assert paths["json"] == tmp_path / "validation-summary.json"
    assert paths["markdown"] == tmp_path / "validation-summary.md"
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["status"] == "passed"
    assert paths["markdown"].read_text(encoding="utf-8").splitlines() == [
        "# PCBSmith Validation Summary",
        "",
        "- Project: Clean demo",
        "- Status: passed",
        "- Errors: 0",
        "- Warnings: 0",
        "- Advisories: 0",
        "",
        "No validation findings found.",
    ]


def test_validation_report_tool_contract_is_ai_facing() -> None:
    assert validation_report_tool_contract() == {
        "schema": "pcbsmith-validation-report-tool-v1",
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


def test_format_validation_report_markdown_lists_findings() -> None:
    report = build_validation_report(
        project_name="Warn demo",
        human_review_items=["Check board shape against enclosure drawing."],
    )

    assert format_validation_report_markdown(report).splitlines() == [
        "# PCBSmith Validation Summary",
        "",
        "- Project: Warn demo",
        "- Status: needs_review",
        "- Errors: 0",
        "- Warnings: 0",
        "- Advisories: 1",
        "",
        "## Findings",
        "",
        (
            "- advisory human_review/user_check: Check board shape against enclosure "
            "drawing. (human review)"
        ),
        "",
        "## Next Actions",
        "",
        "- Review advisory items before presenting or fabricating the design.",
        "- Re-run calculators and validation after any schematic, layout, or value change.",
    ]
