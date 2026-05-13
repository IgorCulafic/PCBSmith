from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.services.board_intelligence import board_routing_rules_summary
from pcbsmith.services.kicad_preview import (
    KiCadPreviewReport,
    run_kicad_preview,
)
from pcbsmith.services.kicad_project import (
    render_kicad_project_file,
    render_kicad_schematic_file,
    sanitize_kicad_project_name,
)
from pcbsmith.services.kicad_validate import KiCadValidationReport, run_kicad_validation
from pcbsmith.services.led_art import (
    LedArtSpec,
    build_led_art_plan,
    build_led_art_plan_for_topology,
    compare_led_art_topologies,
    write_led_art_reports,
    write_led_art_topology_comparison_reports,
)
from pcbsmith.services.led_art_board import (
    LedArtBoardSpec,
    LedArtControlMode,
    led_art_control_summary,
    led_art_physical_branch_summary,
    render_led_art_board,
)
from pcbsmith.services.revision_brief import (
    RevisionBrief,
    build_revision_brief,
    write_revision_brief,
)

LedArtTopology = Literal["5v_one_per_led", "5v_two_led_dense", "12v_dense"]


class LedArtDesignRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(default="LED Art Design", min_length=1)
    text: str = Field(default="VIR-LAB", min_length=1)
    supply_voltage_v: float = Field(default=12.0, gt=0)
    topology: LedArtTopology | None = None
    control_mode: LedArtControlMode = "none"
    show_polarity_marks: bool = True


class DesignOperationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: str
    project_dir: Path
    project_file: Path
    schematic_file: Path
    board_file: Path
    operation_summary_file: Path
    revision_brief_file: Path
    revision_brief: RevisionBrief
    validation_status: str
    preview_status: str
    exit_code: int


def generate_led_art_design(
    request: LedArtDesignRequest,
    output_dir: Path,
    *,
    execute_kicad: bool = True,
    overwrite: bool = False,
) -> DesignOperationResult:
    project_dir = output_dir
    if project_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists: {project_dir}")
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)

    project_name = sanitize_kicad_project_name(request.name)
    topology = request.topology or _topology_for_voltage(request.supply_voltage_v)
    plan = build_led_art_plan_for_topology(LedArtSpec(text=request.text), topology)
    board_spec = LedArtBoardSpec(
        show_polarity_marks=request.show_polarity_marks,
        control_mode=request.control_mode,
    )

    project_file = project_dir / f"{project_name}.kicad_pro"
    schematic_file = project_dir / f"{project_name}.kicad_sch"
    board_file = project_dir / f"{project_name}.kicad_pcb"
    project_file.write_text(render_kicad_project_file(project_name), encoding="utf-8")
    schematic_file.write_text(render_kicad_schematic_file(uuid4()), encoding="utf-8")
    board_file.write_text(render_led_art_board(plan, board_spec), encoding="utf-8")

    _write_readme(project_dir, project_name, request, topology)
    reports_dir = project_dir / ".pcbsmith" / "reports"
    write_led_art_reports(plan, reports_dir)
    comparison = compare_led_art_topologies(build_led_art_plan(LedArtSpec(text=request.text)))
    write_led_art_topology_comparison_reports(comparison, reports_dir)

    validation: KiCadValidationReport | None = None
    preview: KiCadPreviewReport | None = None
    validation_status = "skipped"
    preview_status = "skipped"
    if execute_kicad:
        validation = run_kicad_validation(project_dir)
        preview = run_kicad_preview(project_dir)
        validation_status = "passed" if validation.exit_code == 0 else "failed"
        preview_status = "exported" if preview.exit_code == 0 else "failed"
    revision_brief = build_revision_brief(
        validation_report=validation,
        preview_report=preview,
    )
    revision_brief_file = project_dir / "revision-brief.json"
    write_revision_brief(revision_brief, revision_brief_file)

    operation_summary_file = project_dir / ".pcbsmith" / "operation.json"
    operation_summary_file.parent.mkdir(parents=True, exist_ok=True)
    operation_summary_file.write_text(
        json.dumps(
            _operation_summary(
                request,
                project_name=project_name,
                topology=topology,
                project_dir=project_dir,
                project_file=project_file,
                schematic_file=schematic_file,
                board_file=board_file,
                revision_brief_file=revision_brief_file,
                validation_status=validation_status,
                preview_status=preview_status,
                revision_brief_status=revision_brief.status,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = 0
    if validation is not None and validation.exit_code:
        exit_code = validation.exit_code
    if preview is not None and preview.exit_code and exit_code == 0:
        exit_code = preview.exit_code

    return DesignOperationResult(
        operation="led_art",
        project_dir=project_dir,
        project_file=project_file,
        schematic_file=schematic_file,
        board_file=board_file,
        operation_summary_file=operation_summary_file,
        revision_brief_file=revision_brief_file,
        revision_brief=revision_brief,
        validation_status=validation_status,
        preview_status=preview_status,
        exit_code=exit_code,
    )


def format_design_operation_result(result: DesignOperationResult) -> list[str]:
    return [
        f"Design operation: {result.operation}",
        f"Review bundle: {result.project_dir}",
        f"KiCad board: {result.board_file}",
        f"Operation summary: {result.operation_summary_file}",
        f"Revision brief: {result.revision_brief_file}",
        f"Validation: {result.validation_status}",
        f"Preview: {result.preview_status}",
        f"Revision brief status: {result.revision_brief.status}",
    ]


def _topology_for_voltage(supply_voltage_v: float) -> LedArtTopology:
    if supply_voltage_v >= 9.0:
        return "12v_dense"
    if supply_voltage_v >= 4.5:
        return "5v_two_led_dense"
    raise ValueError("LED art currently supports 5 V or 12 V style supplies")


def _write_readme(
    project_dir: Path,
    project_name: str,
    request: LedArtDesignRequest,
    topology: LedArtTopology,
) -> None:
    plan = build_led_art_plan_for_topology(LedArtSpec(text=request.text), topology)
    readme = project_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                f"# {project_name}",
                "",
                "This KiCad review bundle was generated by a structured PCBSmith design operation.",
                "",
                "- Operation: LED art.",
                f"- Text: {request.text}.",
                f"- Topology: {topology}.",
                f"- Supply: {plan.electrical.supply_voltage_v:g} V.",
                f"- Physical branch summary: {led_art_physical_branch_summary(plan)}.",
                f"- Control: {led_art_control_summary(request.control_mode)}.",
                "- Review the KiCad PCB, reports, SVG previews, Gerbers, and drill outputs.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _operation_summary(
    request: LedArtDesignRequest,
    *,
    project_name: str,
    topology: LedArtTopology,
    project_dir: Path,
    project_file: Path,
    schematic_file: Path,
    board_file: Path,
    revision_brief_file: Path,
    validation_status: str,
    preview_status: str,
    revision_brief_status: str,
) -> dict[str, object]:
    return {
        "schema": "pcbsmith-design-operation-v1",
        "operation": "led_art",
        "project_name": project_name,
        "request": {
            "name": request.name,
            "text": request.text,
            "supply_voltage_v": request.supply_voltage_v,
            "topology": topology,
            "control_mode": request.control_mode,
            "show_polarity_marks": request.show_polarity_marks,
        },
        "outputs": {
            "project_dir": str(project_dir),
            "project_file": _relative_output(project_dir, project_file),
            "schematic_file": _relative_output(project_dir, schematic_file),
            "board_file": _relative_output(project_dir, board_file),
            "revision_brief_file": _relative_output(project_dir, revision_brief_file),
            "reports_dir": ".pcbsmith/reports",
        },
        "routing_rules": board_routing_rules_summary(),
        "checks": {
            "validation": validation_status,
            "preview": preview_status,
            "revision_brief": revision_brief_status,
        },
    }


def _relative_output(project_dir: Path, output_file: Path) -> str:
    return output_file.relative_to(project_dir).as_posix()


__all__ = [
    "DesignOperationResult",
    "LedArtDesignRequest",
    "format_design_operation_result",
    "generate_led_art_design",
]
