from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.board import Board, Layer
from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import Schematic
from pcbsmith.generators.buck_converter import (
    BuckConverterSpec,
    buck_converter_calculation,
    buck_converter_to_circuit_design,
    render_buck_converter_board,
)
from pcbsmith.generators.controller_boards import (
    AttinyLedControllerSpec,
    ConnectorStyle,
    render_attiny_led_controller_board,
)
from pcbsmith.generators.led_art import (
    LedArtSpec,
    build_led_art_plan,
    build_led_art_plan_for_topology,
    compare_led_art_topologies,
    write_led_art_reports,
    write_led_art_topology_comparison_reports,
)
from pcbsmith.generators.led_art_board import (
    LedArtBoardSpec,
    LedArtControlMode,
    led_art_control_summary,
    led_art_physical_branch_summary,
    render_led_art_board,
)
from pcbsmith.generators.led_art_circuit import led_art_plan_to_circuit_design
from pcbsmith.kicad.circuit_schematic import circuit_design_to_schematic
from pcbsmith.kicad.kicad_export import (
    PCBSMITH_SYMBOL_LIBRARY_FILE_NAME,
    PCBSMITH_SYMBOL_TABLE_FILE_NAME,
    render_kicad_board_items,
    render_kicad_schematic_items,
    render_pcbs_kicad_embedded_symbols,
    render_pcbs_kicad_symbol_library,
    render_pcbs_kicad_symbol_table,
)
from pcbsmith.kicad.kicad_preview import (
    KiCadPreviewReport,
    run_kicad_preview,
)
from pcbsmith.kicad.kicad_project import (
    render_kicad_board_file,
    render_kicad_project_file,
    render_kicad_schematic_file,
    sanitize_kicad_project_name,
)
from pcbsmith.kicad.kicad_validate import KiCadValidationReport, run_kicad_validation
from pcbsmith.knowledge.circuit_topologies import select_topologies_for_intent
from pcbsmith.operations.revision_brief import (
    RevisionBrief,
    build_revision_brief,
    write_revision_brief,
)
from pcbsmith.rules.board_conventions import board_annotation_rules_summary
from pcbsmith.rules.board_intelligence import board_routing_rules_summary
from pcbsmith.rules.kicad_board_policy import (
    KiCadBoardPolicyReport,
    inspect_kicad_board_policy,
    write_kicad_board_policy_report,
)
from pcbsmith.rules.silkscreen_artwork import (
    SilkscreenArtworkRequest,
    SilkscreenPreflightFrame,
    SilkscreenPreflightReport,
    apply_silkscreen_artwork,
    inspect_silkscreen_artwork,
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


class AttinyLedControllerDesignRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(default="ATtiny LED Controller", min_length=1)
    controller: str = Field(default="ATtiny84", min_length=1)
    led_outputs: int = Field(default=2, ge=1, le=2)
    led_resistor_value: str = Field(default="330R", min_length=1)
    show_polarity_marks: bool = True
    connector_style: ConnectorStyle = "through_hole"


class SilkscreenArtworkDesignRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(default="Silkscreen Artwork", min_length=1)
    text: str = Field(min_length=1)
    layer: Layer = Layer.F_SILK
    x_mm: float = Field(default=20.0, ge=0)
    y_mm: float = Field(default=15.0, ge=0)
    rotation_deg: int = 0
    size_mm: float = Field(default=1.5, gt=0)
    thickness_mm: float = Field(default=0.15, gt=0)
    board_width_mm: float = Field(default=50.0, gt=0)
    board_height_mm: float = Field(default=30.0, gt=0)


class BuckConverterDesignRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(default="LM2596 Buck Demo", min_length=1)
    input_voltage_min_v: float = Field(default=7.0, gt=0)
    input_voltage_nominal_v: float = Field(default=12.0, gt=0)
    input_voltage_max_v: float = Field(default=24.0, gt=0)
    output_voltage_v: float = Field(default=5.0, gt=0)
    load_current_a: float = Field(default=1.0, gt=0)


class DesignOperationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: str
    project_dir: Path
    project_file: Path
    schematic_file: Path
    board_file: Path
    operation_summary_file: Path
    revision_brief_file: Path
    kicad_board_policy_report_file: Path
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
    _write_pcbs_symbol_library(project_dir)
    circuit = led_art_plan_to_circuit_design(plan, control_mode=request.control_mode)
    schematic = circuit_design_to_schematic(circuit)
    schematic_file.write_text(
        render_kicad_schematic_file(
            uuid4(),
            render_kicad_schematic_items(schematic, project_name=project_name),
            lib_symbol_items=render_pcbs_kicad_embedded_symbols(),
        ),
        encoding="utf-8",
    )
    board_file.write_text(render_led_art_board(plan, board_spec), encoding="utf-8")

    _write_readme(project_dir, project_name, request, topology)
    reports_dir = project_dir / ".pcbsmith" / "reports"
    board_reports_dir = project_dir / ".pcbsmith" / "board-reports"
    kicad_board_policy_report, kicad_board_policy_report_file = _write_board_policy(
        board_file,
        board_reports_dir,
    )
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
        kicad_board_policy_report=kicad_board_policy_report,
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
                kicad_board_policy_report_file=kicad_board_policy_report_file,
                kicad_board_policy_status=_board_policy_status(
                    kicad_board_policy_report
                ),
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
    if kicad_board_policy_report.exit_code and exit_code == 0:
        exit_code = kicad_board_policy_report.exit_code

    return DesignOperationResult(
        operation="led_art",
        project_dir=project_dir,
        project_file=project_file,
        schematic_file=schematic_file,
        board_file=board_file,
        operation_summary_file=operation_summary_file,
        revision_brief_file=revision_brief_file,
        kicad_board_policy_report_file=kicad_board_policy_report_file,
        revision_brief=revision_brief,
        validation_status=validation_status,
        preview_status=preview_status,
        exit_code=exit_code,
    )


def generate_attiny_led_controller_design(
    request: AttinyLedControllerDesignRequest,
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
    project_file = project_dir / f"{project_name}.kicad_pro"
    schematic_file = project_dir / f"{project_name}.kicad_sch"
    board_file = project_dir / f"{project_name}.kicad_pcb"
    project_file.write_text(render_kicad_project_file(project_name), encoding="utf-8")
    schematic_file.write_text(
        render_kicad_schematic_file(
            uuid4(),
            _board_only_schematic_items(
                title="Board-first ATtiny LED controller design",
                message="PCB layout is the authoritative generated artifact.",
            ),
        ),
        encoding="utf-8",
    )
    board_file.write_text(
        render_attiny_led_controller_board(
            AttinyLedControllerSpec(
                title=request.name,
                controller=request.controller,
                led_outputs=request.led_outputs,
                led_resistor_value=request.led_resistor_value,
                show_polarity_marks=request.show_polarity_marks,
                connector_style=request.connector_style,
            )
        ),
        encoding="utf-8",
    )
    kicad_board_policy_report, kicad_board_policy_report_file = _write_board_policy(
        board_file,
        project_dir / ".pcbsmith" / "board-reports",
    )

    _write_attiny_readme(project_dir, project_name, request)
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
        kicad_board_policy_report=kicad_board_policy_report,
    )
    revision_brief_file = project_dir / "revision-brief.json"
    write_revision_brief(revision_brief, revision_brief_file)

    operation_summary_file = project_dir / ".pcbsmith" / "operation.json"
    operation_summary_file.parent.mkdir(parents=True, exist_ok=True)
    operation_summary_file.write_text(
        json.dumps(
            _attiny_operation_summary(
                request,
                project_name=project_name,
                project_dir=project_dir,
                project_file=project_file,
                schematic_file=schematic_file,
                board_file=board_file,
                revision_brief_file=revision_brief_file,
                kicad_board_policy_report_file=kicad_board_policy_report_file,
                kicad_board_policy_status=_board_policy_status(
                    kicad_board_policy_report
                ),
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
    if kicad_board_policy_report.exit_code and exit_code == 0:
        exit_code = kicad_board_policy_report.exit_code

    return DesignOperationResult(
        operation="attiny_led_controller",
        project_dir=project_dir,
        project_file=project_file,
        schematic_file=schematic_file,
        board_file=board_file,
        operation_summary_file=operation_summary_file,
        revision_brief_file=revision_brief_file,
        kicad_board_policy_report_file=kicad_board_policy_report_file,
        revision_brief=revision_brief,
        validation_status=validation_status,
        preview_status=preview_status,
        exit_code=exit_code,
    )


def generate_buck_converter_design(
    request: BuckConverterDesignRequest,
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
    spec = BuckConverterSpec(
        name=request.name,
        input_voltage_min_v=request.input_voltage_min_v,
        input_voltage_nominal_v=request.input_voltage_nominal_v,
        input_voltage_max_v=request.input_voltage_max_v,
        output_voltage_v=request.output_voltage_v,
        load_current_a=request.load_current_a,
    )
    calculation = buck_converter_calculation(spec)
    if calculation["status"] == "error":
        errors = calculation.get("errors", ())
        if isinstance(errors, (tuple, list)):
            message = ", ".join(str(error) for error in errors)
        else:
            message = str(errors)
        raise ValueError(f"buck converter calculator failed: {message}")

    project_file = project_dir / f"{project_name}.kicad_pro"
    schematic_file = project_dir / f"{project_name}.kicad_sch"
    board_file = project_dir / f"{project_name}.kicad_pcb"
    project_file.write_text(render_kicad_project_file(project_name), encoding="utf-8")
    _write_pcbs_symbol_library(project_dir)

    circuit = buck_converter_to_circuit_design(spec, calculation)
    schematic = circuit_design_to_schematic(circuit)
    schematic_file.write_text(
        render_kicad_schematic_file(
            uuid4(),
            render_kicad_schematic_items(schematic, project_name=project_name),
            lib_symbol_items=render_pcbs_kicad_embedded_symbols(),
        ),
        encoding="utf-8",
    )
    board_file.write_text(render_buck_converter_board(spec, calculation), encoding="utf-8")

    _write_buck_readme(project_dir, project_name, request, calculation)
    reports_dir = project_dir / ".pcbsmith" / "reports"
    calculation_report_file = reports_dir / "buck-calculation.json"
    _write_calculation_report(calculation, calculation_report_file)
    kicad_board_policy_report, kicad_board_policy_report_file = _write_board_policy(
        board_file,
        project_dir / ".pcbsmith" / "board-reports",
    )

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
        kicad_board_policy_report=kicad_board_policy_report,
    )
    revision_brief_file = project_dir / "revision-brief.json"
    write_revision_brief(revision_brief, revision_brief_file)

    operation_summary_file = project_dir / ".pcbsmith" / "operation.json"
    operation_summary_file.parent.mkdir(parents=True, exist_ok=True)
    topology = select_topologies_for_intent("buck-converter")["topologies"][0]
    operation_summary_file.write_text(
        json.dumps(
            _buck_operation_summary(
                request,
                project_name=project_name,
                project_dir=project_dir,
                project_file=project_file,
                schematic_file=schematic_file,
                board_file=board_file,
                revision_brief_file=revision_brief_file,
                kicad_board_policy_report_file=kicad_board_policy_report_file,
                calculation_report_file=calculation_report_file,
                topology=topology,
                calculation=calculation,
                kicad_board_policy_status=_board_policy_status(
                    kicad_board_policy_report
                ),
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
    if kicad_board_policy_report.exit_code and exit_code == 0:
        exit_code = kicad_board_policy_report.exit_code

    return DesignOperationResult(
        operation="buck_converter",
        project_dir=project_dir,
        project_file=project_file,
        schematic_file=schematic_file,
        board_file=board_file,
        operation_summary_file=operation_summary_file,
        revision_brief_file=revision_brief_file,
        kicad_board_policy_report_file=kicad_board_policy_report_file,
        revision_brief=revision_brief,
        validation_status=validation_status,
        preview_status=preview_status,
        exit_code=exit_code,
    )


def generate_silkscreen_artwork_design(
    request: SilkscreenArtworkDesignRequest,
    output_dir: Path,
    *,
    execute_kicad: bool = True,
    overwrite: bool = False,
) -> DesignOperationResult:
    project_dir = output_dir
    if project_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists: {project_dir}")

    project_name = sanitize_kicad_project_name(request.name)
    frame = SilkscreenPreflightFrame(
        width_mm=request.board_width_mm,
        height_mm=request.board_height_mm,
    )
    artwork_request = _silkscreen_artwork_request(request)
    source_board = Board(id="silkscreen-artwork")
    preflight = inspect_silkscreen_artwork(
        source_board,
        (artwork_request,),
        frame=frame,
    )
    if not preflight.passed:
        raise ValueError(
            "silkscreen preflight failed: "
            + ", ".join(finding.code for finding in preflight.findings)
        )
    board = apply_silkscreen_artwork(source_board, (artwork_request,), frame=frame)

    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)

    project_file = project_dir / f"{project_name}.kicad_pro"
    schematic_file = project_dir / f"{project_name}.kicad_sch"
    board_file = project_dir / f"{project_name}.kicad_pcb"

    project_file.write_text(render_kicad_project_file(project_name), encoding="utf-8")
    schematic_file.write_text(
        render_kicad_schematic_file(
            uuid4(),
            _board_only_schematic_items(
                title="Board-first silkscreen artwork design",
                message="PCB layout is the authoritative generated artifact.",
            ),
        ),
        encoding="utf-8",
    )
    board_file.write_text(
        render_kicad_board_file(
            uuid4(),
            render_kicad_board_items(Schematic(id="main"), board=board),
            outline_end_mm=f"{request.board_width_mm:g} {request.board_height_mm:g}",
        ),
        encoding="utf-8",
    )
    kicad_board_policy_report, kicad_board_policy_report_file = _write_board_policy(
        board_file,
        project_dir / ".pcbsmith" / "board-reports",
    )

    _write_silkscreen_readme(project_dir, project_name, request)
    reports_dir = project_dir / ".pcbsmith" / "reports"
    preflight_report_file = reports_dir / "silkscreen-preflight.json"
    _write_silkscreen_preflight_report(preflight, preflight_report_file)

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
        kicad_board_policy_report=kicad_board_policy_report,
    )
    revision_brief_file = project_dir / "revision-brief.json"
    write_revision_brief(revision_brief, revision_brief_file)

    operation_summary_file = project_dir / ".pcbsmith" / "operation.json"
    operation_summary_file.parent.mkdir(parents=True, exist_ok=True)
    operation_summary_file.write_text(
        json.dumps(
            _silkscreen_operation_summary(
                request,
                project_name=project_name,
                project_dir=project_dir,
                project_file=project_file,
                schematic_file=schematic_file,
                board_file=board_file,
                revision_brief_file=revision_brief_file,
                kicad_board_policy_report_file=kicad_board_policy_report_file,
                kicad_board_policy_status=_board_policy_status(
                    kicad_board_policy_report
                ),
                preflight_report_file=preflight_report_file,
                validation_status=validation_status,
                preview_status=preview_status,
                preflight_status="passed",
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
    if kicad_board_policy_report.exit_code and exit_code == 0:
        exit_code = kicad_board_policy_report.exit_code

    return DesignOperationResult(
        operation="silkscreen_artwork",
        project_dir=project_dir,
        project_file=project_file,
        schematic_file=schematic_file,
        board_file=board_file,
        operation_summary_file=operation_summary_file,
        revision_brief_file=revision_brief_file,
        kicad_board_policy_report_file=kicad_board_policy_report_file,
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
        f"KiCad board policy: {result.kicad_board_policy_report_file}",
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


def _board_only_schematic_items(title: str, message: str) -> tuple[str, ...]:
    return (
        _schematic_text(title, x_mm=30.0, y_mm=40.0, size_mm=2.0),
        _schematic_text(message, x_mm=30.0, y_mm=48.0, size_mm=1.27),
    )


def _schematic_text(text: str, *, x_mm: float, y_mm: float, size_mm: float) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f"""  (text "{escaped}"
    (at {x_mm:.2f} {y_mm:.2f} 0)
    (effects
      (font
        (size {size_mm:.2f} {size_mm:.2f})
      )
      (justify left)
    )
    (uuid "{uuid4()}")
  )"""


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


def _write_attiny_readme(
    project_dir: Path,
    project_name: str,
    request: AttinyLedControllerDesignRequest,
) -> None:
    readme = project_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                f"# {project_name}",
                "",
                "This KiCad review bundle was generated by a structured PCBSmith "
                "R6 design operation.",
                "",
                "- Operation: ATtiny LED controller.",
                f"- Controller: {request.controller}.",
                f"- LED outputs: {request.led_outputs}.",
                f"- Connector style: {request.connector_style}.",
                "- Includes 5 V/GND input pads, ISP pads, reset pull-up, "
                "decoupling, and status LEDs.",
                "- Review the KiCad PCB, revision brief, SVG previews, Gerbers, and drill outputs.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_silkscreen_readme(
    project_dir: Path,
    project_name: str,
    request: SilkscreenArtworkDesignRequest,
) -> None:
    readme = project_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                f"# {project_name}",
                "",
                "This KiCad review bundle was generated by a structured PCBSmith "
                "R7A silkscreen artwork operation.",
                "",
                "- Operation: silkscreen artwork.",
                f"- Text: {request.text}.",
                f"- Layer: {request.layer.value}.",
                f"- Position: {request.x_mm:g}, {request.y_mm:g} mm.",
                "- Review the KiCad PCB, silkscreen preflight report, revision brief, "
                "and SVG previews.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_buck_readme(
    project_dir: Path,
    project_name: str,
    request: BuckConverterDesignRequest,
    calculation: dict[str, object],
) -> None:
    outputs = calculation["outputs"]
    assert isinstance(outputs, dict)
    readme = project_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                f"# {project_name}",
                "",
                "This KiCad review bundle was generated by a structured PCBSmith "
                "buck-converter design operation.",
                "",
                "- Operation: LM2596 adjustable buck converter.",
                f"- Input: {request.input_voltage_min_v:g}-"
                f"{request.input_voltage_max_v:g} V "
                f"(nominal {request.input_voltage_nominal_v:g} V).",
                f"- Output: {request.output_voltage_v:g} V at "
                f"{request.load_current_a:g} A.",
                f"- Selected inductor: {outputs['selected_inductance_uH']:g} uH.",
                f"- Feedback divider: {outputs['selected_feedback_upper_ohms']:g} ohm "
                f"over {outputs['feedback_lower_ohms']:g} ohm.",
                "- Uses a dedicated switching-regulator topology, not a timer or "
                "microcontroller placeholder.",
                "- Review the KiCad PCB, schematic, calculator report, revision brief, "
                "SVG previews, Gerbers, and drill outputs.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_calculation_report(
    calculation: dict[str, object],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(calculation, indent=2) + "\n", encoding="utf-8")


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
    kicad_board_policy_report_file: Path,
    kicad_board_policy_status: str,
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
            "kicad_board_policy_report_file": _relative_output(
                project_dir,
                kicad_board_policy_report_file,
            ),
            "reports_dir": ".pcbsmith/reports",
        },
        "routing_rules": board_routing_rules_summary(),
        "annotation_rules": board_annotation_rules_summary(),
        "checks": {
            "validation": validation_status,
            "preview": preview_status,
            "kicad_board_policy": kicad_board_policy_status,
            "revision_brief": revision_brief_status,
        },
    }


def _attiny_operation_summary(
    request: AttinyLedControllerDesignRequest,
    *,
    project_name: str,
    project_dir: Path,
    project_file: Path,
    schematic_file: Path,
    board_file: Path,
    revision_brief_file: Path,
    kicad_board_policy_report_file: Path,
    kicad_board_policy_status: str,
    validation_status: str,
    preview_status: str,
    revision_brief_status: str,
) -> dict[str, object]:
    return {
        "schema": "pcbsmith-design-operation-v1",
        "operation": "attiny_led_controller",
        "project_name": project_name,
        "request": {
            "name": request.name,
            "controller": request.controller,
            "led_outputs": request.led_outputs,
            "led_resistor_value": request.led_resistor_value,
            "show_polarity_marks": request.show_polarity_marks,
            "connector_style": request.connector_style,
        },
        "outputs": {
            "project_dir": str(project_dir),
            "project_file": _relative_output(project_dir, project_file),
            "schematic_file": _relative_output(project_dir, schematic_file),
            "board_file": _relative_output(project_dir, board_file),
            "revision_brief_file": _relative_output(project_dir, revision_brief_file),
            "kicad_board_policy_report_file": _relative_output(
                project_dir,
                kicad_board_policy_report_file,
            ),
        },
        "routing_rules": board_routing_rules_summary(),
        "annotation_rules": board_annotation_rules_summary(),
        "checks": {
            "validation": validation_status,
            "preview": preview_status,
            "kicad_board_policy": kicad_board_policy_status,
            "revision_brief": revision_brief_status,
        },
    }


def _buck_operation_summary(
    request: BuckConverterDesignRequest,
    *,
    project_name: str,
    project_dir: Path,
    project_file: Path,
    schematic_file: Path,
    board_file: Path,
    revision_brief_file: Path,
    kicad_board_policy_report_file: Path,
    calculation_report_file: Path,
    topology: dict[str, object],
    calculation: dict[str, object],
    kicad_board_policy_status: str,
    validation_status: str,
    preview_status: str,
    revision_brief_status: str,
) -> dict[str, object]:
    return {
        "schema": "pcbsmith-design-operation-v1",
        "operation": "buck_converter",
        "project_name": project_name,
        "request": {
            "name": request.name,
            "input_voltage_min_v": request.input_voltage_min_v,
            "input_voltage_nominal_v": request.input_voltage_nominal_v,
            "input_voltage_max_v": request.input_voltage_max_v,
            "output_voltage_v": request.output_voltage_v,
            "load_current_a": request.load_current_a,
        },
        "topology": topology,
        "calculator": calculation,
        "outputs": {
            "project_dir": str(project_dir),
            "project_file": _relative_output(project_dir, project_file),
            "schematic_file": _relative_output(project_dir, schematic_file),
            "board_file": _relative_output(project_dir, board_file),
            "revision_brief_file": _relative_output(project_dir, revision_brief_file),
            "kicad_board_policy_report_file": _relative_output(
                project_dir,
                kicad_board_policy_report_file,
            ),
            "calculation_report_file": _relative_output(
                project_dir,
                calculation_report_file,
            ),
        },
        "routing_rules": board_routing_rules_summary(),
        "annotation_rules": board_annotation_rules_summary(),
        "checks": {
            "validation": validation_status,
            "preview": preview_status,
            "kicad_board_policy": kicad_board_policy_status,
            "revision_brief": revision_brief_status,
        },
    }


def _silkscreen_operation_summary(
    request: SilkscreenArtworkDesignRequest,
    *,
    project_name: str,
    project_dir: Path,
    project_file: Path,
    schematic_file: Path,
    board_file: Path,
    revision_brief_file: Path,
    kicad_board_policy_report_file: Path,
    kicad_board_policy_status: str,
    preflight_report_file: Path,
    validation_status: str,
    preview_status: str,
    preflight_status: str,
    revision_brief_status: str,
) -> dict[str, object]:
    return {
        "schema": "pcbsmith-design-operation-v1",
        "operation": "silkscreen_artwork",
        "project_name": project_name,
        "request": {
            "name": request.name,
            "text": request.text,
            "layer": request.layer.value,
            "position_mm": {"x": request.x_mm, "y": request.y_mm},
            "rotation_deg": request.rotation_deg,
            "size_mm": request.size_mm,
            "thickness_mm": request.thickness_mm,
            "board_width_mm": request.board_width_mm,
            "board_height_mm": request.board_height_mm,
        },
        "outputs": {
            "project_dir": str(project_dir),
            "project_file": _relative_output(project_dir, project_file),
            "schematic_file": _relative_output(project_dir, schematic_file),
            "board_file": _relative_output(project_dir, board_file),
            "revision_brief_file": _relative_output(project_dir, revision_brief_file),
            "kicad_board_policy_report_file": _relative_output(
                project_dir,
                kicad_board_policy_report_file,
            ),
            "preflight_report_file": _relative_output(project_dir, preflight_report_file),
        },
        "annotation_rules": board_annotation_rules_summary(),
        "checks": {
            "silkscreen_preflight": preflight_status,
            "validation": validation_status,
            "preview": preview_status,
            "kicad_board_policy": kicad_board_policy_status,
            "revision_brief": revision_brief_status,
        },
    }


def _silkscreen_artwork_request(
    request: SilkscreenArtworkDesignRequest,
) -> SilkscreenArtworkRequest:
    return SilkscreenArtworkRequest(
        text=request.text,
        layer=request.layer,
        position=Point.from_mm(request.x_mm, request.y_mm),
        rotation_deg=request.rotation_deg,
        size=int(request.size_mm * 1_000_000),
        thickness=int(request.thickness_mm * 1_000_000),
    )


def _write_silkscreen_preflight_report(
    report: SilkscreenPreflightReport,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-silkscreen-preflight-v1",
                "summary": {
                    "finding_count": len(report.findings),
                    "status": "passed" if report.passed else "failed",
                },
                "findings": [
                    {
                        "code": finding.code,
                        "message": finding.message,
                        "location": finding.location,
                    }
                    for finding in report.findings
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_pcbs_symbol_library(project_dir: Path) -> None:
    (project_dir / PCBSMITH_SYMBOL_LIBRARY_FILE_NAME).write_text(
        render_pcbs_kicad_symbol_library(),
        encoding="utf-8",
    )
    (project_dir / PCBSMITH_SYMBOL_TABLE_FILE_NAME).write_text(
        render_pcbs_kicad_symbol_table(),
        encoding="utf-8",
    )


def _write_board_policy(
    board_file: Path,
    output_dir: Path,
) -> tuple[KiCadBoardPolicyReport, Path]:
    report = inspect_kicad_board_policy(board_file.read_text(encoding="utf-8"))
    output_path = output_dir / "kicad-board-policy.json"
    write_kicad_board_policy_report(report, output_path)
    return report, output_path


def _board_policy_status(report: KiCadBoardPolicyReport) -> str:
    if report.exit_code != 0:
        return "failed"
    if report.findings:
        return "needs_review"
    return "passed"


def _relative_output(project_dir: Path, output_file: Path) -> str:
    return output_file.relative_to(project_dir).as_posix()


__all__ = [
    "AttinyLedControllerDesignRequest",
    "BuckConverterDesignRequest",
    "DesignOperationResult",
    "LedArtDesignRequest",
    "SilkscreenArtworkDesignRequest",
    "format_design_operation_result",
    "generate_attiny_led_controller_design",
    "generate_buck_converter_design",
    "generate_led_art_design",
    "generate_silkscreen_artwork_design",
]
