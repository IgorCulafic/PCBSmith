from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.models import (
    AuthorityStatus,
    BoardReport,
    CircuitObject,
    DesignReviewReport,
    EvidenceReport,
    KiCadReport,
    ReconciliationReport,
    ReviewFinding,
    RevisionRecord,
    SimulationReport,
)
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.core.netops import derive_netlist
from pcbsmith.core.schematic import Schematic
from pcbsmith.evidence import (
    ANTHROPIC_DEFAULT_MODEL,
    LOCAL_DEFAULT_BASE_URL,
    LOCAL_DEFAULT_MODEL,
    AnthropicDatasheetClient,
    DatasheetChatClient,
    DatasheetExtractionError,
    EvidenceAcquisitionRequest,
    EvidenceAcquisitionService,
    EvidenceCache,
    EvidenceDownloadError,
    EvidenceExtractionJob,
    EvidenceExtractionService,
    LlmDatasheetExtractor,
    NexarClientCredentialsTokenProvider,
    NexarProviderError,
    NexarSupplyProvider,
    OpenAICompatibleDatasheetClient,
    UrlLibChatTransport,
    UrlLibEvidenceDownloader,
    UrlLibNexarTransport,
    register_local_evidence,
)
from pcbsmith.evidence.divider_highpass_led import (
    apply_component_selection,
    select_divider_highpass_led_components,
)
from pcbsmith.evidence.lm2596_buck import select_lm2596_buck_components
from pcbsmith.evidence.mpu6050 import select_mpu6050_components
from pcbsmith.generation.clover import compose_clover, write_clover_project
from pcbsmith.generation.divider_highpass_led import (
    compose_divider_highpass_led,
    write_divider_highpass_led_project,
)
from pcbsmith.generation.led_art import (
    LedArtPlan,
    compose_led_art,
    write_led_art_project,
)
from pcbsmith.generation.lm2596_buck import (
    compose_lm2596_buck,
    write_lm2596_buck_project,
)
from pcbsmith.generation.metal_detector import (
    compose_metal_detector,
    write_metal_detector_project,
)
from pcbsmith.generation.mpu6050 import compose_mpu6050, write_mpu6050_project
from pcbsmith.generation.pear import compose_pear, write_pear_project
from pcbsmith.kicad.board import (
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    compute_board_layout,
    generate_board,
    render_board_previews,
)
from pcbsmith.kicad.clover_board import generate_clover_board
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.export_clover import export_clover_to_kicad
from pcbsmith.kicad.export_divider_highpass_led import export_divider_highpass_led_to_kicad
from pcbsmith.kicad.export_led_art import export_led_art_to_kicad
from pcbsmith.kicad.export_lm2596_buck import export_lm2596_buck_to_kicad
from pcbsmith.kicad.export_metal_detector import export_metal_detector_to_kicad
from pcbsmith.kicad.export_mpu6050 import export_mpu6050_to_kicad
from pcbsmith.kicad.export_pear import export_pear_to_kicad
from pcbsmith.kicad.led_art_board import generate_led_art_board
from pcbsmith.kicad.metal_detector_board import generate_detector_board
from pcbsmith.kicad.pear_board import generate_pear_board, ring_unit_counts
from pcbsmith.kicad.preview import plot_board_review
from pcbsmith.kicad.spice import export_kicad_spice_netlist
from pcbsmith.kicad.validate import export_schematic_svg, run_kicad_drc, run_kicad_erc
from pcbsmith.kicad.virtual_drc import run_virtual_drc
from pcbsmith.review.authority_bundle import write_authority_review_bundle
from pcbsmith.review.circuit_bundle import write_circuit_review_bundle
from pcbsmith.revision import (
    build_revision_plan,
    collect_failure_codes,
    revision_for_authority_failure,
)
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.services.erc import run_erc
from pcbsmith.services.project_io import (
    ProjectIOError,
    create_project,
    load_board,
    load_project,
    load_schematic,
)
from pcbsmith.simulation.ngspice import run_ngspice_netlist_file, run_ngspice_simulation
from pcbsmith.simulation.ngspice_buck import run_lm2596_power_stage_simulation
from pcbsmith.simulation.ngspice_clover import run_clover_simulation
from pcbsmith.simulation.ngspice_led_art import run_led_art_simulation
from pcbsmith.simulation.ngspice_metal_detector import run_detector_simulation
from pcbsmith.simulation.ngspice_mpu6050 import run_mpu6050_simulation
from pcbsmith.simulation.ngspice_pear import run_pear_simulation

GENERIC_EVIDENCE_FINDING = "Generic passive and LED components are not datasheet-backed yet."


def _cmd_new(args: argparse.Namespace) -> int:
    project_dir = Path(args.project)
    if project_dir.exists() or (project_dir / "project.pcbsmith.json").exists():
        raise ValueError(f"Project target already exists: {project_dir}")
    project = create_project(project_dir, args.name)
    print(f"Created project '{project.name}' at {project_dir}")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    print(f"Name: {project.name}")
    print(f"Version: {project.version}")
    print(f"Schematics: {len(project.schematics)}")
    print(f"Boards: {len(project.boards)}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    project_dir = Path(args.project)
    project = load_project(project_dir)
    for schematic_path in project.schematics:
        load_schematic(project_dir, schematic_path)
    for board_path in project.boards:
        load_board(project_dir, board_path)
    print("Project is valid")
    return 0


def _load_first_schematic(project_dir: Path) -> Schematic:
    project = load_project(project_dir)
    if not project.schematics:
        raise ValueError("Project has no schematics")
    return load_schematic(project_dir, project.schematics[0])


def _format_pin(reference: tuple[str, str]) -> str:
    component, pin = reference
    return f"{component}.{pin}"


def _cmd_netlist(args: argparse.Namespace) -> int:
    schematic = _load_first_schematic(Path(args.project))
    netlist = derive_netlist(schematic, SYMBOLS)
    for net in netlist.nets:
        pins = ", ".join(_format_pin(pin) for pin in sorted(net.pins))
        print(f"{net.name}: {pins}")
    return 0


def _cmd_erc(args: argparse.Namespace) -> int:
    schematic = _load_first_schematic(Path(args.project))
    issues = run_erc(schematic, SYMBOLS)
    for issue in issues:
        print(f"{issue.code}: {issue.message} ({issue.where})")
    return 1 if issues else 0


def _prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    if overwrite or not output_dir.exists():
        return
    if any(output_dir.iterdir()):
        raise ValueError(
            f"Output directory {output_dir} already contains files. Use a fresh "
            "directory per design revision so runs stay comparable, or pass "
            "--overwrite to replace it."
        )


def _cmd_design_divider_highpass_led(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _prepare_output_dir(output_dir, overwrite=args.overwrite)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    topology = select_topology(intent)
    circuit = compose_divider_highpass_led(intent, topology)
    write_divider_highpass_led_project(circuit, output_dir, project_name=args.name)
    simulation = run_ngspice_simulation(circuit, output_dir)
    bundle_path = write_circuit_review_bundle(
        circuit,
        output_dir,
        simulation_report=simulation,
        kicad_status="not_run",
        artifacts={
            "pcbs_project": str(output_dir),
            "review_bundle": str(output_dir / "review-bundle.json"),
        },
    )
    print(f"Review bundle: {bundle_path}")
    print("Status: needs_human_review")
    return 0


def _cmd_design_divider_highpass_led_authority(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _prepare_output_dir(output_dir, overwrite=args.overwrite)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    topology = select_topology(intent)
    circuit = compose_divider_highpass_led(intent, topology)
    circuit, evidence = _apply_evidence_manifest(
        circuit,
        manifest_path=args.evidence_manifest,
    )

    write_divider_highpass_led_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_divider_highpass_led_to_kicad(
        circuit,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])

    erc_report = run_kicad_erc(schematic_file)
    schematic_svg, _svg_findings = export_schematic_svg(schematic_file)
    spice_report = export_kicad_spice_netlist(schematic_file)
    spice_netlist = spice_report.spice_netlist
    if spice_report.status == "passed" and spice_netlist is not None:
        selected_kicad_spice = True
        simulation = run_ngspice_netlist_file(Path(spice_netlist), output_dir)
    else:
        selected_kicad_spice = False
        simulation = run_ngspice_simulation(circuit, output_dir)

    kicad = _combine_kicad_reports(erc_report, spice_report)
    reconciliation = _reconcile_authorities(
        kicad=kicad,
        simulation=simulation,
        selected_kicad_spice=selected_kicad_spice,
    )
    board, design_review = _board_authority(
        output_dir=output_dir,
        project_name=args.name,
        schematic_file=schematic_file,
        erc_report=erc_report,
        simulation=simulation,
    )
    artifacts = _authority_artifacts(
        output_dir=output_dir,
        kicad_artifacts=kicad_artifacts,
        erc_report=erc_report,
        spice_report=spice_report,
        simulation=simulation,
        board=board,
    )
    _add_existing_artifact(artifacts, "kicad_schematic_svg", schematic_svg)
    revisions = _authority_revisions(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
    )

    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
        revisions=revisions,
        artifacts=artifacts,
    )
    status = _authority_bundle_status(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
    )
    print(f"Review bundle: {bundle_path}")
    print(f"Status: {status}")
    return 0


def _cmd_design_lm2596_buck_authority(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _prepare_output_dir(output_dir, overwrite=args.overwrite)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    if intent.intent_id != "lm2596_buck_regulator":
        raise ValueError(
            "The request classified as a different intent; use the matching "
            "design command instead."
        )
    topology = select_topology(intent)
    circuit = compose_lm2596_buck(intent, topology)
    if args.evidence_manifest is not None:
        try:
            cache = EvidenceCache.from_manifest(Path(args.evidence_manifest))
        except (OSError, ValidationError) as exc:
            raise ValueError(
                f"Evidence manifest could not be loaded: {args.evidence_manifest} ({exc})"
            ) from exc
        selection_report = select_lm2596_buck_components(circuit, cache)
        circuit = apply_component_selection(circuit, selection_report)
        evidence = EvidenceReport(
            status=selection_report.status,
            findings=selection_report.findings,
            cached_files=selection_report.cached_files,
        )
    else:
        evidence = EvidenceReport(
            status="needs_human_review",
            findings=(
                "No evidence manifest was supplied; pass --evidence-manifest "
                "ai_assets/evidence/lm2596-buck.manifest.json to validate the "
                "regulator against the extracted TI datasheet facts.",
            ),
        )

    write_lm2596_buck_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_lm2596_buck_to_kicad(
        circuit,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])

    erc_report = run_kicad_erc(schematic_file)
    schematic_svg, _svg_findings = export_schematic_svg(schematic_file)
    simulation = run_lm2596_power_stage_simulation(circuit, output_dir)

    kicad = erc_report.model_copy(
        update={
            "findings": (
                *erc_report.findings,
                "KiCad SPICE export was intentionally skipped: the LM2596 has no "
                "public SPICE model, so a PCBSmith behavioral power-stage netlist "
                "was simulated instead.",
            ),
        }
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=(
            "PCBSmith circuit object and KiCad schematic were generated before "
            "authority checks.",
            "ngspice ran a PCBSmith behavioral power-stage netlist, not a "
            "KiCad-exported netlist.",
        ),
        findings=(
            "The simulated netlist is a behavioral power stage derived from the "
            "circuit object; it is not translation-checked against the KiCad "
            "schematic.",
        ),
    )
    board, design_review = _board_authority(
        output_dir=output_dir,
        project_name=args.name,
        schematic_file=schematic_file,
        erc_report=erc_report,
        simulation=simulation,
        power_net_names=frozenset({"VIN", "SW", "VOUT", "GND"}),
        design_checks=DesignChecksSpec(
            switching_cluster_refs=("CIN", "CIN2", "U1", "D1"),
            sensitive_net_names=("FB",),
            inductor_references=("L1",),
        ),
        ground_pour=True,
        thermal_pour_references=("U1",),
        extra_findings=(
            "Design-rule status (docs/pcb-design-rules.md): power nets routed at "
            "0.8mm (rule 3.6, machine-enforced); power path kept contiguous by "
            "row ordering (rule 3.1, 1-D approximation only); B.Cu ground plane "
            "poured (rule 3.2); TO-263 thermal pour around the tab (rule 3.5).",
            "NOT machine-enforced yet: 2-D switching-loop area minimisation and "
            "the thermal pour AREA vs the TI ~2.5 sq in guidance - review "
            "before fabrication.",
        ),
    )
    artifacts = _authority_artifacts(
        output_dir=output_dir,
        kicad_artifacts=kicad_artifacts,
        erc_report=erc_report,
        spice_report=KiCadReport(status="not_run"),
        simulation=simulation,
        board=board,
    )
    _add_existing_artifact(artifacts, "kicad_schematic_svg", schematic_svg)
    revisions = _authority_revisions(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
    )
    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
        revisions=revisions,
        artifacts=artifacts,
    )
    status = _authority_bundle_status(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
    )
    print(f"Review bundle: {bundle_path}")
    print(f"Status: {status}")
    return 0


def _cmd_design_led_art_authority(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _prepare_output_dir(output_dir, overwrite=args.overwrite)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    if intent.intent_id != "led_text_matrix":
        raise ValueError(
            "The request classified as a different intent; use the matching "
            "design command instead."
        )
    topology = select_topology(intent)
    circuit, plan = compose_led_art(intent, topology)
    evidence = EvidenceReport(
        status="needs_human_review",
        findings=(
            "The LED forward voltage (1.85 V) comes from the extracted "
            "Kingbright datasheet facts in "
            "ai_assets/evidence/divider-highpass-led.manifest.json, but the "
            "manifest is not machine-applied to this topology yet.",
            "String resistors and the input connector are demo parts without "
            "datasheet evidence.",
        ),
    )

    write_led_art_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_led_art_to_kicad(
        circuit,
        plan,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])

    erc_report = run_kicad_erc(schematic_file)
    schematic_svg, _svg_findings = export_schematic_svg(schematic_file)
    simulation = run_led_art_simulation(circuit, plan, output_dir)

    kicad = erc_report.model_copy(
        update={
            "findings": (
                *erc_report.findings,
                "KiCad SPICE export was intentionally skipped: the matrix LEDs "
                "use a PCBSmith behavioral diode model fitted to the datasheet "
                "forward voltage.",
            ),
        }
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=(
            "PCBSmith circuit object and KiCad schematic were generated before "
            "authority checks.",
            "ngspice ran a PCBSmith behavioral string netlist, not a "
            "KiCad-exported netlist.",
        ),
        findings=(
            "The simulated netlist is built from the circuit object strings; it "
            "is not translation-checked against the KiCad schematic.",
        ),
    )
    board, design_review = _art_board_authority(
        output_dir=output_dir,
        project_name=args.name,
        schematic_file=schematic_file,
        erc_report=erc_report,
        simulation=simulation,
        plan=plan,
        power_net_names=frozenset({"VIN", "GND"}),
        design_checks=DesignChecksSpec(
            led_strings=tuple(
                (string.resistor_ref, *string.led_refs) for string in plan.strings
            ),
        ),
        extra_findings=(
            "Art-grid placement: LED positions follow the glyph dot grid; every "
            "series link is confined to its own column and the power rails "
            "frame the field (top VIN, bottom GND).",
        ),
    )
    artifacts = _authority_artifacts(
        output_dir=output_dir,
        kicad_artifacts=kicad_artifacts,
        erc_report=erc_report,
        spice_report=KiCadReport(status="not_run"),
        simulation=simulation,
        board=board,
    )
    _add_existing_artifact(artifacts, "kicad_schematic_svg", schematic_svg)
    revisions = _authority_revisions(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
    )
    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
        revisions=revisions,
        artifacts=artifacts,
    )
    status = _authority_bundle_status(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
    )
    print(f"Review bundle: {bundle_path}")
    print(f"Status: {status}")
    return 0


def _cmd_design_mpu6050_authority(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _prepare_output_dir(output_dir, overwrite=args.overwrite)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    if intent.intent_id != "mpu6050_imu":
        raise ValueError(
            "The request classified as a different intent; use the matching "
            "design command instead."
        )
    topology = select_topology(intent)
    circuit = compose_mpu6050(intent, topology)
    if args.evidence_manifest is not None:
        try:
            cache = EvidenceCache.from_manifest(Path(args.evidence_manifest))
        except (OSError, ValidationError) as exc:
            raise ValueError(
                f"Evidence manifest could not be loaded: {args.evidence_manifest} ({exc})"
            ) from exc
        selection_report = select_mpu6050_components(circuit, cache)
        circuit = apply_component_selection(circuit, selection_report)
        evidence = EvidenceReport(
            status=selection_report.status,
            findings=selection_report.findings,
            cached_files=selection_report.cached_files,
        )
    else:
        evidence = EvidenceReport(
            status="needs_human_review",
            findings=(
                "No evidence manifest was supplied; pass --evidence-manifest "
                "ai_assets/evidence/mpu6050.manifest.json to validate the "
                "sensor against the extracted datasheet facts.",
            ),
        )

    write_mpu6050_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_mpu6050_to_kicad(
        circuit,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])

    erc_report = run_kicad_erc(schematic_file)
    schematic_svg, _svg_findings = export_schematic_svg(schematic_file)
    simulation = run_mpu6050_simulation(circuit, output_dir)

    kicad = erc_report.model_copy(
        update={
            "findings": (
                *erc_report.findings,
                "KiCad SPICE export was intentionally skipped: the MPU-6050 "
                "has no SPICE model, so only the passive I2C bus network is "
                "simulated from a PCBSmith netlist.",
            ),
        }
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=(
            "PCBSmith circuit object and KiCad schematic were generated before "
            "authority checks.",
            "ngspice ran a PCBSmith idle-bus netlist, not a KiCad-exported "
            "netlist.",
        ),
        findings=(
            "The simulated netlist covers the passive bus conditioning only; "
            "it is not translation-checked against the KiCad schematic.",
        ),
    )
    board, design_review = _board_authority(
        output_dir=output_dir,
        project_name=args.name,
        schematic_file=schematic_file,
        erc_report=erc_report,
        simulation=simulation,
        power_net_names=frozenset({"VDD", "GND"}),
        design_checks=DesignChecksSpec(),
        ground_pour=True,
        extra_findings=(
            "First multi-side package board: QFN north pads route through the "
            "mirrored top channel; east/west pads fan out through per-pad "
            "escape columns (see docs/pcb-design-rules.md rule 1.1/8 notes).",
            "Decoupling-capacitor proximity to the QFN supply pins (rule 2.1) "
            "is not machine-checked yet - review before fabrication.",
        ),
    )
    artifacts = _authority_artifacts(
        output_dir=output_dir,
        kicad_artifacts=kicad_artifacts,
        erc_report=erc_report,
        spice_report=KiCadReport(status="not_run"),
        simulation=simulation,
        board=board,
    )
    _add_existing_artifact(artifacts, "kicad_schematic_svg", schematic_svg)
    revisions = _authority_revisions(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
    )
    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
        revisions=revisions,
        artifacts=artifacts,
    )
    status = _authority_bundle_status(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
    )
    print(f"Review bundle: {bundle_path}")
    print(f"Status: {status}")
    return 0


def _cmd_design_clover_authority(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _prepare_output_dir(output_dir, overwrite=args.overwrite)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    if intent.intent_id != "clover_tilt_indicator":
        raise ValueError(
            "The request classified as a different intent; use the matching "
            "design command instead."
        )
    topology = select_topology(intent)
    circuit = compose_clover(intent, topology)
    if args.evidence_manifest is not None:
        try:
            cache = EvidenceCache.from_manifest(Path(args.evidence_manifest))
        except (OSError, ValidationError) as exc:
            raise ValueError(
                f"Evidence manifest could not be loaded: {args.evidence_manifest} ({exc})"
            ) from exc
        selection_report = select_mpu6050_components(circuit, cache)
        circuit = apply_component_selection(circuit, selection_report)
        evidence = EvidenceReport(
            status=selection_report.status,
            findings=selection_report.findings,
            cached_files=selection_report.cached_files,
        )
    else:
        evidence = EvidenceReport(
            status="needs_human_review",
            findings=(
                "No evidence manifest was supplied; pass --evidence-manifest "
                "ai_assets/evidence/mpu6050.manifest.json to validate the "
                "sensor against the extracted datasheet facts.",
            ),
        )

    write_clover_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_clover_to_kicad(
        circuit,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])

    erc_report = run_kicad_erc(schematic_file)
    schematic_svg, _svg_findings = export_schematic_svg(schematic_file)
    simulation = run_clover_simulation(circuit, output_dir)

    kicad = erc_report.model_copy(
        update={
            "findings": (
                *erc_report.findings,
                "KiCad SPICE export was intentionally skipped: the MCU and "
                "MEMS sensor have no SPICE models; the passive network is "
                "simulated from a PCBSmith netlist.",
            ),
        }
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=(
            "PCBSmith circuit object and KiCad schematic were generated before "
            "authority checks.",
            "ngspice ran a PCBSmith passive-network netlist, not a "
            "KiCad-exported netlist.",
        ),
        findings=(
            "The simulated netlist covers bus conditioning and LED bias only; "
            "it is not translation-checked against the KiCad schematic.",
        ),
    )

    board: BoardReport
    design_review: DesignReviewReport | None
    if erc_report.status != "passed" or simulation.status != "passed":
        board = BoardReport(
            status="not_run",
            findings=(
                "Board generation was skipped because KiCad ERC and ngspice "
                "simulation must pass before a board is generated.",
            ),
        )
        design_review = None
    else:
        board_file = output_dir / f"{args.name}.kicad_pcb"
        try:
            board_netlist, layout = generate_clover_board(
                schematic_file=schematic_file,
                board_file=board_file,
                motto=str(intent.assumptions["motto"]),
            )
        except BoardGenerationError as exc:
            board = BoardReport(
                status="failed",
                board_file=str(board_file),
                findings=(str(exc),),
            )
            design_review = None
        else:
            design_review = run_design_checks(
                layout,
                board_netlist,
                DesignChecksSpec(
                    led_strings=(
                        ("R3", "D1"), ("R4", "D2"), ("R5", "D3"), ("R6", "D4"),
                    ),
                ),
            )
            board, design_review = _finish_board_authority(
                board_file=board_file,
                output_dir=output_dir,
                project_name=args.name,
                board_netlist=board_netlist,
                layout=layout,
                design_review=design_review,
                extra_findings=(
                    "Shaped clover outline, front silkscreen art, and a "
                    "back-side sensor/MCU cluster; the tilt behaviour is a "
                    "firmware contract recorded in the math findings.",
                ),
            )
    artifacts = _authority_artifacts(
        output_dir=output_dir,
        kicad_artifacts=kicad_artifacts,
        erc_report=erc_report,
        spice_report=KiCadReport(status="not_run"),
        simulation=simulation,
        board=board,
    )
    _add_existing_artifact(artifacts, "kicad_schematic_svg", schematic_svg)
    revisions = _authority_revisions(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
    )
    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
        revisions=revisions,
        artifacts=artifacts,
    )
    status = _authority_bundle_status(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
    )
    print(f"Review bundle: {bundle_path}")
    print(f"Status: {status}")
    return 0


def _cmd_design_pear_authority(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _prepare_output_dir(output_dir, overwrite=args.overwrite)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    if intent.intent_id != "pear_led_rings":
        raise ValueError(
            "The request classified as a different intent; use the matching "
            "design command instead."
        )
    topology = select_topology(intent)
    circuit = compose_pear(intent, topology)
    evidence = EvidenceReport(
        status="needs_human_review",
        findings=(
            "The LED forward voltage is an engineering assumption; validate "
            "a concrete part's datasheet before fabrication.",
        ),
    )

    write_pear_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_pear_to_kicad(
        circuit,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])

    erc_report = run_kicad_erc(schematic_file)
    schematic_svg, _svg_findings = export_schematic_svg(schematic_file)
    simulation = run_pear_simulation(circuit, output_dir)

    kicad = erc_report.model_copy(
        update={
            "findings": (
                *erc_report.findings,
                "KiCad SPICE export was intentionally skipped; the resistive "
                "LED branches are simulated from a PCBSmith netlist.",
            ),
        }
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=(
            "PCBSmith circuit object and KiCad schematic were generated before "
            "authority checks.",
            "ngspice ran a PCBSmith branch netlist, not a KiCad-exported "
            "netlist.",
        ),
        findings=(
            "The simulated netlist covers the LED branches only; it is not "
            "translation-checked against the KiCad schematic.",
        ),
    )

    board: BoardReport
    design_review: DesignReviewReport | None
    if erc_report.status != "passed" or simulation.status != "passed":
        board = BoardReport(
            status="not_run",
            findings=(
                "Board generation was skipped because KiCad ERC and ngspice "
                "simulation must pass before a board is generated.",
            ),
        )
        design_review = None
    else:
        board_file = output_dir / f"{args.name}.kicad_pcb"
        try:
            board_netlist, layout = generate_pear_board(
                schematic_file=schematic_file,
                board_file=board_file,
            )
        except BoardGenerationError as exc:
            board = BoardReport(
                status="failed",
                board_file=str(board_file),
                findings=(str(exc),),
            )
            design_review = None
        else:
            total_units = sum(ring_unit_counts())
            design_review = run_design_checks(
                layout,
                board_netlist,
                DesignChecksSpec(
                    led_strings=tuple(
                        (f"R{unit}", f"D{unit}")
                        for unit in range(1, total_units + 1)
                    ),
                ),
            )
            board, design_review = _finish_board_authority(
                board_file=board_file,
                output_dir=output_dir,
                project_name=args.name,
                board_netlist=board_netlist,
                layout=layout,
                design_review=design_review,
                extra_findings=(
                    "Pear-shaped outline with three independently driven LED "
                    "edge rings and the worm silkscreen; the ring switching "
                    "is an external drive contract recorded in the math "
                    "findings.",
                ),
            )
    artifacts = _authority_artifacts(
        output_dir=output_dir,
        kicad_artifacts=kicad_artifacts,
        erc_report=erc_report,
        spice_report=KiCadReport(status="not_run"),
        simulation=simulation,
        board=board,
    )
    _add_existing_artifact(artifacts, "kicad_schematic_svg", schematic_svg)
    revisions = _authority_revisions(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
    )
    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
        revisions=revisions,
        artifacts=artifacts,
    )
    status = _authority_bundle_status(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
    )
    print(f"Review bundle: {bundle_path}")
    print(f"Status: {status}")
    return 0


def _cmd_design_metal_detector_authority(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _prepare_output_dir(output_dir, overwrite=args.overwrite)
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    if intent.intent_id != "metal_detector_coil":
        raise ValueError(
            "The request classified as a different intent; use the matching "
            "design command instead."
        )
    topology = select_topology(intent)
    circuit = compose_metal_detector(intent, topology)
    evidence = EvidenceReport(
        status="needs_human_review",
        findings=(
            "The coil inductance and oscillator frequency come from textbook "
            "formulas; the transistor is a generic 2N3904-class assumption. "
            "Validate the concrete part before fabrication.",
        ),
    )

    write_metal_detector_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_metal_detector_to_kicad(
        circuit,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])

    erc_report = run_kicad_erc(schematic_file)
    schematic_svg, _svg_findings = export_schematic_svg(schematic_file)
    simulation = run_detector_simulation(circuit, output_dir)

    kicad = erc_report.model_copy(
        update={
            "findings": (
                *erc_report.findings,
                "KiCad SPICE export was intentionally skipped; the oscillator "
                "is simulated from a PCBSmith netlist with the coil as a "
                "lumped inductor plus its DC resistance.",
            ),
        }
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=(
            "PCBSmith circuit object and KiCad schematic were generated before "
            "authority checks.",
            "ngspice ran a PCBSmith oscillator netlist, not a KiCad-exported "
            "netlist.",
        ),
        findings=(
            "The simulation models the spiral as a lumped L+R; parasitics "
            "(inter-turn capacitance, self-resonance) are not modelled.",
        ),
    )

    board: BoardReport
    design_review: DesignReviewReport | None
    if erc_report.status != "passed" or simulation.status != "passed":
        board = BoardReport(
            status="not_run",
            findings=(
                "Board generation was skipped because KiCad ERC and ngspice "
                "simulation must pass before a board is generated.",
            ),
        )
        design_review = None
    else:
        board_file = output_dir / f"{args.name}.kicad_pcb"
        try:
            board_netlist, layout = generate_detector_board(
                schematic_file=schematic_file,
                board_file=board_file,
            )
        except BoardGenerationError as exc:
            board = BoardReport(
                status="failed",
                board_file=str(board_file),
                findings=(str(exc),),
            )
            design_review = None
        else:
            from pcbsmith.kicad.metal_detector_board import (
                COIL_CENTER,
                SPIRAL_OUTER_RADIUS,
            )
            design_review = run_design_checks(
                layout,
                board_netlist,
                DesignChecksSpec(
                    copper_keepouts=(
                        # The keepout is the coil itself plus half a trace
                        # width; the handle pour legitimately ends just
                        # above the outer turn.
                        (
                            COIL_CENTER[0],
                            COIL_CENTER[1],
                            SPIRAL_OUTER_RADIUS + 0.5,
                            ("/COL",),
                        ),
                    ),
                ),
            )
            board, design_review = _finish_board_authority(
                board_file=board_file,
                output_dir=output_dir,
                project_name=args.name,
                board_netlist=board_netlist,
                layout=layout,
                design_review=design_review,
                extra_findings=(
                    "The sensing coil is 20 exposed spiral turns of front "
                    "copper (soldermask opening); no ground pour under the "
                    "coil, only its single back-side return trace. Detection "
                    "is a frequency-shift contract recorded in the math "
                    "findings.",
                ),
            )
    artifacts = _authority_artifacts(
        output_dir=output_dir,
        kicad_artifacts=kicad_artifacts,
        erc_report=erc_report,
        spice_report=KiCadReport(status="not_run"),
        simulation=simulation,
        board=board,
    )
    _add_existing_artifact(artifacts, "kicad_schematic_svg", schematic_svg)
    revisions = _authority_revisions(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
    )
    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
        revisions=revisions,
        artifacts=artifacts,
    )
    status = _authority_bundle_status(
        circuit=circuit,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        board=board,
        design_review=design_review,
    )
    print(f"Review bundle: {bundle_path}")
    print(f"Status: {status}")
    return 0


def _cmd_review_comment(args: argparse.Namespace) -> int:
    revision_dir = Path(args.output)
    if not (revision_dir / "review-bundle-v2.json").exists():
        raise ValueError(f"No review bundle found in {revision_dir}")
    finding = ReviewFinding(
        rule=args.rule or "human",
        severity=args.severity,
        scope=args.scope,
        where=args.where,
        evidence=args.comment,
        suggested_action=args.action or "Address the reviewer's comment.",
        source="human",
    )
    comments_path = revision_dir / "human-review.json"
    existing: list[dict[str, object]] = []
    if comments_path.exists():
        existing = json.loads(comments_path.read_text(encoding="utf-8"))
    existing.append(finding.model_dump())
    comments_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded human finding #{len(existing)} in {comments_path}")
    print(f"[{finding.severity}/{finding.scope}] {finding.where}: {finding.evidence}")
    return 0


def _load_human_findings(revision_dir: Path) -> tuple[dict[str, object], ...]:
    comments_path = revision_dir / "human-review.json"
    if not comments_path.exists():
        return ()
    data = json.loads(comments_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{comments_path} must contain a JSON list of findings.")
    return tuple(entry for entry in data if isinstance(entry, dict))


def _cmd_revision_plan(args: argparse.Namespace) -> int:
    revision_dir = Path(args.output)
    bundle_path = revision_dir / "review-bundle-v2.json"
    if not bundle_path.exists():
        raise ValueError(f"No review bundle found at {bundle_path}")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

    history = _revision_history_codes(revision_dir)
    plan = build_revision_plan(
        bundle,
        history,
        additional_findings=_load_human_findings(revision_dir),
    )
    plan_path = revision_dir / "revision-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    print(f"Revision plan: {plan_path}")
    print(f"Decision: {plan['decision']}")
    if plan["stage"]:
        print(f"Re-enter pipeline at stage: {plan['stage']}")
    for target in plan["targets"]:
        rule = f"rule {target['rule']}" if target["rule"] else target["where"]
        print(f"- [{target['severity']}] {rule}: {target['suggested_action']}")
    for reason in plan["rationale"]:
        print(f"  ({reason})")
    return 0


def _revision_history_codes(revision_dir: Path) -> list[tuple[str, ...]]:
    """Failure codes for each sibling revision (same name stem), oldest first,
    ending with the revision under review."""
    match = re.fullmatch(r"(?P<stem>.+-r)(?P<number>\d+)", revision_dir.name)
    if match is None:
        bundle = json.loads(
            (revision_dir / "review-bundle-v2.json").read_text(encoding="utf-8")
        )
        return [collect_failure_codes(bundle)]
    stem = match.group("stem")
    current_number = int(match.group("number"))
    history: list[tuple[str, ...]] = []
    for sibling in sorted(revision_dir.parent.glob(f"{stem}*")):
        sibling_match = re.fullmatch(r".+-r(\d+)", sibling.name)
        if sibling_match is None or int(sibling_match.group(1)) > current_number:
            continue
        sibling_bundle_path = sibling / "review-bundle-v2.json"
        if not sibling_bundle_path.exists():
            continue
        sibling_bundle = json.loads(sibling_bundle_path.read_text(encoding="utf-8"))
        history.append(collect_failure_codes(sibling_bundle))
    return history


def _cmd_evidence_nexar_smoke(args: argparse.Namespace) -> int:
    client_id = os.environ.get("PCBSMITH_NEXAR_CLIENT_ID")
    client_secret = os.environ.get("PCBSMITH_NEXAR_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "Skipped Nexar smoke: set PCBSMITH_NEXAR_CLIENT_ID and "
            "PCBSMITH_NEXAR_CLIENT_SECRET to run the live opt-in check."
        )
        return 0

    transport = UrlLibNexarTransport()
    provider = NexarSupplyProvider(
        token_provider=NexarClientCredentialsTokenProvider(
            client_id=client_id,
            client_secret=client_secret,
            transport=transport,
        ),
        transport=transport,
        limit=args.limit,
    )
    request = EvidenceAcquisitionRequest(
        role=args.role,
        query=args.query,
        manufacturer=args.manufacturer,
        part_number=args.part_number,
    )
    candidates = provider.search(request)
    print(f"Nexar candidates: {len(candidates)}")
    for candidate in candidates:
        datasheet = candidate.datasheet_url or "no datasheet URL"
        print(f"- {candidate.manufacturer} {candidate.part_number}: {datasheet}")
    return 0


def _build_datasheet_client(args: argparse.Namespace) -> DatasheetChatClient:
    if args.provider == "anthropic":
        return AnthropicDatasheetClient(model=args.model or ANTHROPIC_DEFAULT_MODEL)
    base_url = (
        args.base_url
        or os.environ.get("PCBSMITH_LOCAL_AI_BASE_URL")
        or LOCAL_DEFAULT_BASE_URL
    )
    model = args.model or os.environ.get("PCBSMITH_LOCAL_AI_MODEL") or LOCAL_DEFAULT_MODEL
    return OpenAICompatibleDatasheetClient(
        transport=UrlLibChatTransport(),
        base_url=base_url,
        model=model,
        api_key=os.environ.get("PCBSMITH_LOCAL_AI_API_KEY"),
    )


def _cmd_evidence_extract(args: argparse.Namespace) -> int:
    extractor = LlmDatasheetExtractor(_build_datasheet_client(args))
    service = EvidenceExtractionService(
        manifest_path=Path(args.manifest),
        extractor=extractor,
    )
    report = service.process_pending(retry_failed=args.retry_failed)
    print(f"Processed extraction jobs: {report.processed_jobs}")
    for finding in report.findings:
        print(f"- {finding}")
    return 0


def _utc_date() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).date().isoformat()


def _cmd_evidence_add_local(args: argparse.Namespace) -> int:
    source_file = Path(args.pdf)
    if not source_file.exists():
        raise ValueError(f"Datasheet PDF not found: {source_file}")
    component = register_local_evidence(
        manifest_path=Path(args.manifest),
        source_file=source_file,
        manufacturer=args.manufacturer,
        part_number=args.part_number,
        role=args.role,
        symbol_id=args.symbol_id,
        value=args.value or args.part_number,
        footprint=args.footprint,
        source_url=args.source_url,
        clock=_utc_date,
    )
    print(
        f"Registered {component.manufacturer} {component.part_number} "
        f"for role {component.role} with a pending extraction job."
    )
    print(f"Manifest: {args.manifest}")
    return 0


def _cmd_evidence_acquire(args: argparse.Namespace) -> int:
    client_id = os.environ.get("PCBSMITH_NEXAR_CLIENT_ID")
    client_secret = os.environ.get("PCBSMITH_NEXAR_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "error: set PCBSMITH_NEXAR_CLIENT_ID and PCBSMITH_NEXAR_CLIENT_SECRET "
            "to acquire evidence from Nexar, or use evidence-add-local with a "
            "manually downloaded datasheet.",
            file=sys.stderr,
        )
        return 2

    transport = UrlLibNexarTransport()
    manifest_path = Path(args.manifest)
    service = EvidenceAcquisitionService(
        manifest_path=manifest_path,
        cache_dir=Path(args.cache_dir) if args.cache_dir else manifest_path.parent,
        provider=NexarSupplyProvider(
            token_provider=NexarClientCredentialsTokenProvider(
                client_id=client_id,
                client_secret=client_secret,
                transport=transport,
            ),
            transport=transport,
        ),
        downloader=UrlLibEvidenceDownloader(),
        clock=_utc_date,
    )
    report = service.acquire(
        EvidenceAcquisitionRequest(
            role=args.role,
            query=args.query,
            manufacturer=args.manufacturer,
            part_number=args.part_number,
        )
    )
    print(f"Acquisition status: {report.status}")
    if report.component is not None:
        print(f"Component: {report.component.manufacturer} {report.component.part_number}")
    for cached_file in report.cached_files:
        print(f"Cached: {cached_file}")
    for finding in report.findings:
        print(f"- {finding}")
    return 0 if report.status in {"cache_hit", "downloaded"} else 1


def _cmd_datasheet_facts(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise ValueError(f"Datasheet PDF not found: {pdf_path}")
    job = EvidenceExtractionJob(
        status="pending_extraction",
        component_manufacturer=args.manufacturer,
        component_part_number=args.part_number,
        role=args.role,
        local_path=str(pdf_path),
        sha256="unverified",
        created_at="unspecified",
    )
    extractor = LlmDatasheetExtractor(_build_datasheet_client(args))
    result = extractor.extract(pdf_path, job)
    print(json.dumps(result.model_dump(), indent=2))
    return 1 if result.status == "failed" else 0


def _add_datasheet_provider_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        choices=("anthropic", "local"),
        default="anthropic",
        help="anthropic uses the Claude API with native PDF input; "
        "local uses an OpenAI-compatible endpoint with pypdf text extraction",
    )
    parser.add_argument("--model")
    parser.add_argument("--base-url")


def _board_authority(
    *,
    output_dir: Path,
    project_name: str,
    schematic_file: Path,
    erc_report: KiCadReport,
    simulation: SimulationReport,
    power_net_names: frozenset[str] = frozenset(),
    extra_findings: tuple[str, ...] = (),
    design_checks: DesignChecksSpec | None = None,
    ground_pour: bool = False,
    thermal_pour_references: tuple[str, ...] = (),
) -> tuple[BoardReport, DesignReviewReport | None]:
    if erc_report.status != "passed" or simulation.status != "passed":
        return (
            BoardReport(
                status="not_run",
                findings=(
                    "Board generation was skipped because KiCad ERC and ngspice "
                    "simulation must pass before a board is generated.",
                ),
            ),
            None,
        )
    board_file = output_dir / f"{project_name}.kicad_pcb"
    sensitive_net_names = frozenset(
        design_checks.sensitive_net_names if design_checks is not None else ()
    )
    try:
        board_netlist = generate_board(
            schematic_file=schematic_file,
            board_file=board_file,
            power_net_names=power_net_names,
            sensitive_net_names=sensitive_net_names,
            ground_pour=ground_pour,
            thermal_pour_references=thermal_pour_references,
        )
    except BoardGenerationError as exc:
        return (
            BoardReport(
                status="failed",
                board_file=str(board_file),
                findings=(str(exc),),
            ),
            None,
        )
    layout = compute_board_layout(
        board_netlist,
        power_net_names,
        sensitive_net_names,
        ground_pour=ground_pour,
        thermal_pour_references=thermal_pour_references,
    )
    design_review = run_design_checks(
        layout,
        board_netlist,
        design_checks or DesignChecksSpec(),
    )
    return _finish_board_authority(
        board_file=board_file,
        output_dir=output_dir,
        project_name=project_name,
        board_netlist=board_netlist,
        layout=layout,
        design_review=design_review,
        extra_findings=extra_findings,
    )


def _art_board_authority(
    *,
    output_dir: Path,
    project_name: str,
    schematic_file: Path,
    erc_report: KiCadReport,
    simulation: SimulationReport,
    plan: LedArtPlan,
    power_net_names: frozenset[str],
    design_checks: DesignChecksSpec,
    extra_findings: tuple[str, ...] = (),
) -> tuple[BoardReport, DesignReviewReport | None]:
    if erc_report.status != "passed" or simulation.status != "passed":
        return (
            BoardReport(
                status="not_run",
                findings=(
                    "Board generation was skipped because KiCad ERC and ngspice "
                    "simulation must pass before a board is generated.",
                ),
            ),
            None,
        )
    board_file = output_dir / f"{project_name}.kicad_pcb"
    try:
        board_netlist, layout = generate_led_art_board(
            schematic_file=schematic_file,
            board_file=board_file,
            plan=plan,
            power_net_names=power_net_names,
        )
    except BoardGenerationError as exc:
        return (
            BoardReport(
                status="failed",
                board_file=str(board_file),
                findings=(str(exc),),
            ),
            None,
        )
    design_review = run_design_checks(layout, board_netlist, design_checks)
    return _finish_board_authority(
        board_file=board_file,
        output_dir=output_dir,
        project_name=project_name,
        board_netlist=board_netlist,
        layout=layout,
        design_review=design_review,
        extra_findings=extra_findings,
    )


def _finish_board_authority(
    *,
    board_file: Path,
    output_dir: Path,
    project_name: str,
    board_netlist: BoardNetlist,
    layout: BoardLayout,
    design_review: DesignReviewReport,
    extra_findings: tuple[str, ...],
) -> tuple[BoardReport, DesignReviewReport | None]:
    # Virtual DRC first: the fast geometric pre-filter (hardening plan 2.1).
    # Its model deliberately underestimates copper, so findings are
    # high-confidence; on a hit, the KiCad round trip is skipped entirely.
    virtual_findings = run_virtual_drc(layout, board_netlist)
    if virtual_findings:
        return (
            BoardReport(
                status="failed",
                board_file=str(board_file),
                findings=tuple(
                    f"virtual_drc/{finding.check}: {finding.message} "
                    f"at ({finding.x_mm:.1f}, {finding.y_mm:.1f})mm"
                    for finding in virtual_findings[:20]
                ),
            ),
            design_review,
        )
    report = run_kicad_drc(board_file)
    _, preview_findings = render_board_previews(board_file)
    try:
        plot_board_review(
            board_netlist,
            output_dir / f"{project_name}-review.png",
            layout=layout,
        )
    except BoardGenerationError as exc:
        preview_findings = (*preview_findings, str(exc))
    if report.status == "passed":
        return (
            report.model_copy(
                update={
                    "status": "needs_human_review",
                    "findings": (
                        *report.findings,
                        *preview_findings,
                        *extra_findings,
                        "KiCad DRC passed. The generated board layout still requires "
                        "human visual review before fabrication.",
                    ),
                }
            ),
            design_review,
        )
    if preview_findings or extra_findings:
        return (
            report.model_copy(
                update={
                    "findings": (*report.findings, *preview_findings, *extra_findings)
                }
            ),
            design_review,
        )
    return report, design_review


def _combine_kicad_reports(erc_report: KiCadReport, spice_report: KiCadReport) -> KiCadReport:
    findings = _prefixed_findings("KiCad ERC", erc_report.findings) + _prefixed_findings(
        "KiCad SPICE export",
        spice_report.findings,
    )
    return KiCadReport(
        status=_combined_authority_status((erc_report.status, spice_report.status)),
        command=erc_report.command + spice_report.command,
        schematic_file=erc_report.schematic_file or spice_report.schematic_file,
        erc_report=erc_report.erc_report,
        spice_netlist=spice_report.spice_netlist if spice_report.status == "passed" else None,
        findings=findings,
    )


def _combined_authority_status(statuses: tuple[AuthorityStatus, ...]) -> AuthorityStatus:
    for status in ("failed", "unavailable", "not_run", "needs_human_review", "warning"):
        if status in statuses:
            return status
    if all(status == "passed" for status in statuses):
        return "passed"
    return "not_run"


def _prefixed_findings(prefix: str, findings: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{prefix}: {finding}" for finding in findings)


def _reconcile_authorities(
    *,
    kicad: KiCadReport,
    simulation: SimulationReport,
    selected_kicad_spice: bool,
) -> ReconciliationReport:
    checks = (
        "PCBSmith circuit object and KiCad schematic were generated before authority checks.",
        "KiCad ERC and KiCad SPICE export statuses were recorded separately.",
        _simulation_input_check(
            selected_kicad_spice=selected_kicad_spice,
            simulation=simulation,
        ),
    )
    findings = [
        _simulation_input_finding(
            selected_kicad_spice=selected_kicad_spice,
            simulation=simulation,
        )
    ]
    if kicad.status != "passed":
        findings.append(f"KiCad authority status is {kicad.status}.")
    if simulation.status != "passed":
        findings.append(f"ngspice authority status is {simulation.status}.")
    return ReconciliationReport(
        status="warning",
        checks=checks,
        findings=tuple(findings),
    )


def _simulation_input_check(
    *,
    selected_kicad_spice: bool,
    simulation: SimulationReport,
) -> str:
    if selected_kicad_spice:
        if simulation.status in {"passed", "warning"}:
            return "ngspice completed from the KiCad-exported SPICE netlist."
        return (
            "KiCad-exported SPICE netlist was selected for ngspice, but "
            f"ngspice status is {simulation.status}."
        )
    if simulation.status in {"passed", "warning"}:
        return "ngspice completed from a PCBSmith-rendered fallback netlist."
    return (
        "PCBSmith-rendered fallback netlist was selected for ngspice, but "
        f"ngspice status is {simulation.status}."
    )


def _simulation_input_finding(
    *,
    selected_kicad_spice: bool,
    simulation: SimulationReport,
) -> str:
    if selected_kicad_spice:
        if simulation.status in {"passed", "warning"}:
            return "ngspice completed from the KiCad-exported SPICE netlist."
        return (
            "KiCad-exported SPICE netlist was selected for ngspice, but "
            f"ngspice status is {simulation.status}; this is not completed "
            "simulation evidence."
        )
    if simulation.status in {"passed", "warning"}:
        return (
            "KiCad SPICE export did not pass, so ngspice completed from a "
            "PCBSmith-rendered fallback netlist; this is not KiCad-exported "
            "SPICE evidence."
        )
    return (
        "KiCad SPICE export did not pass, so a PCBSmith-rendered fallback "
        f"netlist was selected for ngspice, but ngspice status is {simulation.status}; "
        "this is not completed simulation evidence or KiCad-exported SPICE evidence."
    )


def _authority_revisions(
    *,
    circuit: CircuitObject,
    evidence: EvidenceReport,
    kicad: KiCadReport,
    simulation: SimulationReport,
    reconciliation: ReconciliationReport,
    board: BoardReport | None = None,
) -> tuple[RevisionRecord, ...]:
    revisions: list[RevisionRecord] = []
    parent_revision_id: str | None = None
    if evidence.status != "passed":
        revisions.append(
            revision_for_authority_failure(
                revision_id="evidence_missing",
                parent_revision_id=None,
                failure_code="evidence_missing",
                findings=evidence.findings,
            )
        )
        parent_revision_id = revisions[-1].revision_id
    if circuit.math.status != "passed":
        revisions.append(
            revision_for_authority_failure(
                revision_id="math_mismatch",
                parent_revision_id=parent_revision_id,
                failure_code="math_mismatch",
                findings=circuit.math.findings
                or (f"PCBSmith deterministic math status is {circuit.math.status}.",),
            )
        )
        parent_revision_id = revisions[-1].revision_id
    if kicad.status != "passed":
        revisions.append(
            revision_for_authority_failure(
                revision_id="kicad_failed",
                parent_revision_id=parent_revision_id,
                failure_code="kicad_failed",
                findings=kicad.findings or (f"KiCad authority status is {kicad.status}.",),
            )
        )
        parent_revision_id = revisions[-1].revision_id
    if simulation.status != "passed":
        revisions.append(
            revision_for_authority_failure(
                revision_id="simulation_failed",
                parent_revision_id=parent_revision_id,
                failure_code="simulation_failed",
                findings=simulation.findings
                or (f"ngspice authority status is {simulation.status}.",),
            )
        )
        parent_revision_id = revisions[-1].revision_id
    if reconciliation.status != "passed":
        revisions.append(
            revision_for_authority_failure(
                revision_id="reconciliation_failed",
                parent_revision_id=parent_revision_id,
                failure_code="reconciliation_failed",
                findings=reconciliation.findings
                or (f"Reconciliation status is {reconciliation.status}.",),
            )
        )
        parent_revision_id = revisions[-1].revision_id
    if board is not None and board.status == "failed":
        revisions.append(
            revision_for_authority_failure(
                revision_id="board_failed",
                parent_revision_id=parent_revision_id,
                failure_code="board_failed",
                findings=board.findings or ("Board authority status is failed.",),
            )
        )
    return tuple(revisions)


def _apply_evidence_manifest(
    circuit: CircuitObject,
    *,
    manifest_path: str | None,
) -> tuple[CircuitObject, EvidenceReport]:
    if manifest_path is None:
        return (
            circuit,
            EvidenceReport(
                status="needs_human_review",
                findings=(GENERIC_EVIDENCE_FINDING,),
            ),
        )
    try:
        cache = EvidenceCache.from_manifest(Path(manifest_path))
    except (OSError, ValidationError) as exc:
        raise ValueError(f"Evidence manifest could not be loaded: {manifest_path} ({exc})") from exc

    selection_report = select_divider_highpass_led_components(circuit, cache)
    return (
        apply_component_selection(circuit, selection_report),
        EvidenceReport(
            status=selection_report.status,
            findings=selection_report.findings,
            cached_files=selection_report.cached_files,
        ),
    )


def _authority_artifacts(
    *,
    output_dir: Path,
    kicad_artifacts: dict[str, str],
    erc_report: KiCadReport,
    spice_report: KiCadReport,
    simulation: SimulationReport,
    board: BoardReport | None = None,
) -> dict[str, str]:
    artifacts = {
        "pcbs_project": str(output_dir / "project.pcbsmith.json"),
        "kicad_project": kicad_artifacts["project_file"],
        "review_bundle": str(output_dir / "review-bundle-v2.json"),
        "kicad_schematic": kicad_artifacts["schematic_file"],
    }
    _add_existing_artifact(artifacts, "kicad_erc_report", erc_report.erc_report)
    if spice_report.status == "passed":
        _add_existing_artifact(artifacts, "kicad_spice_netlist", spice_report.spice_netlist)
    _add_existing_artifact(artifacts, "ngspice_output", simulation.raw_output_path)
    if board is not None:
        _add_existing_artifact(artifacts, "kicad_board", board.board_file)
        _add_existing_artifact(artifacts, "kicad_drc_report", board.drc_report)
        if board.board_file is not None:
            board_path = Path(board.board_file)
            for view in ("top", "bottom", "perspective"):
                _add_existing_artifact(
                    artifacts,
                    f"board_render_{view}",
                    str(board_path.parent / f"{board_path.stem}-{view}.png"),
                )
            _add_existing_artifact(
                artifacts,
                "board_review_plot",
                str(board_path.parent / f"{board_path.stem}-review.png"),
            )
    return artifacts


def _add_existing_artifact(
    artifacts: dict[str, str],
    name: str,
    candidate: str | None,
) -> None:
    if candidate is not None and Path(candidate).exists():
        artifacts[name] = candidate


def _authority_bundle_status(
    *,
    circuit: CircuitObject,
    evidence: EvidenceReport,
    kicad: KiCadReport,
    simulation: SimulationReport,
    reconciliation: ReconciliationReport,
    board: BoardReport | None = None,
    design_review: DesignReviewReport | None = None,
) -> AuthorityStatus:
    authority_statuses = (evidence.status, kicad.status, simulation.status, reconciliation.status)
    board_status = board.status if board is not None else None
    review_status = design_review.status if design_review is not None else None
    if circuit.math.status == "failed" or "failed" in authority_statuses:
        return "failed"
    if board_status == "failed" or review_status == "failed":
        return "failed"
    if "unavailable" in authority_statuses or board_status == "unavailable":
        return "unavailable"
    if "not_run" in authority_statuses:
        return "not_run"

    if (
        circuit.math.status != "passed"
        or evidence.status != "passed"
        or kicad.status != "passed"
        or simulation.status != "passed"
        or reconciliation.status != "passed"
        or (board_status is not None and board_status != "passed")
        or (review_status is not None and review_status != "passed")
        or any(component.support_status != "supported" for component in circuit.components)
    ):
        return "needs_human_review"
    return "passed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcbsmith")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="create a new PCBSmith project")
    new_parser.add_argument("project")
    new_parser.add_argument("--name", required=True)
    new_parser.set_defaults(func=_cmd_new)

    info_parser = subparsers.add_parser("info", help="print a project summary")
    info_parser.add_argument("project")
    info_parser.set_defaults(func=_cmd_info)

    validate_parser = subparsers.add_parser("validate", help="load and validate project files")
    validate_parser.add_argument("project")
    validate_parser.set_defaults(func=_cmd_validate)

    netlist_parser = subparsers.add_parser("netlist", help="derive the first schematic netlist")
    netlist_parser.add_argument("project")
    netlist_parser.set_defaults(func=_cmd_netlist)

    erc_parser = subparsers.add_parser("erc", help="run ERC on the first schematic")
    erc_parser.add_argument("project")
    erc_parser.set_defaults(func=_cmd_erc)

    design_parser = subparsers.add_parser(
        "design-divider-highpass-led",
        help="generate the first circuit-intelligence vertical slice",
    )
    design_parser.add_argument("output")
    design_parser.add_argument("--request", required=True)
    design_parser.add_argument("--name", required=True)
    design_parser.add_argument("--overwrite", action="store_true")
    design_parser.set_defaults(func=_cmd_design_divider_highpass_led)

    authority_design_parser = subparsers.add_parser(
        "design-divider-highpass-led-authority",
        help="generate the circuit-intelligence slice with separated authority evidence",
    )
    authority_design_parser.add_argument("output")
    authority_design_parser.add_argument("--request", required=True)
    authority_design_parser.add_argument("--name", required=True)
    authority_design_parser.add_argument("--evidence-manifest")
    authority_design_parser.add_argument("--overwrite", action="store_true")
    authority_design_parser.set_defaults(func=_cmd_design_divider_highpass_led_authority)

    buck_parser = subparsers.add_parser(
        "design-lm2596-buck-authority",
        help="generate the LM2596 buck regulator slice with authority evidence "
        "(board generation gated pending switching-loop layout rules)",
    )
    buck_parser.add_argument("output")
    buck_parser.add_argument("--request", required=True)
    buck_parser.add_argument("--name", required=True)
    buck_parser.add_argument("--evidence-manifest")
    buck_parser.add_argument("--overwrite", action="store_true")
    buck_parser.set_defaults(func=_cmd_design_lm2596_buck_authority)

    led_art_parser = subparsers.add_parser(
        "design-led-art-authority",
        help="generate an LED text-matrix module (glyph dot grid, one series "
        "string per column) with authority evidence",
    )
    led_art_parser.add_argument("output")
    led_art_parser.add_argument("--request", required=True)
    led_art_parser.add_argument("--name", required=True)
    led_art_parser.add_argument("--overwrite", action="store_true")
    led_art_parser.set_defaults(func=_cmd_design_led_art_authority)

    mpu_parser = subparsers.add_parser(
        "design-mpu6050-authority",
        help="generate an MPU-6050 IMU breakout (QFN-24, I2C) with authority "
        "evidence",
    )
    mpu_parser.add_argument("output")
    mpu_parser.add_argument("--request", required=True)
    mpu_parser.add_argument("--name", required=True)
    mpu_parser.add_argument("--evidence-manifest")
    mpu_parser.add_argument("--overwrite", action="store_true")
    mpu_parser.set_defaults(func=_cmd_design_mpu6050_authority)

    clover_parser = subparsers.add_parser(
        "design-clover-authority",
        help="generate the four-leaf-clover tilt indicator (shaped outline, "
        "silkscreen art, two-sided assembly) with authority evidence",
    )
    clover_parser.add_argument("output")
    clover_parser.add_argument("--request", required=True)
    clover_parser.add_argument("--name", required=True)
    clover_parser.add_argument("--evidence-manifest")
    clover_parser.add_argument("--overwrite", action="store_true")
    clover_parser.set_defaults(func=_cmd_design_clover_authority)

    pear_parser = subparsers.add_parser(
        "design-pear-authority",
        help="generate the pear-shaped board with three LED edge rings and "
        "the worm silkscreen, with authority evidence",
    )
    pear_parser.add_argument("output")
    pear_parser.add_argument("--request", required=True)
    pear_parser.add_argument("--name", required=True)
    pear_parser.add_argument("--overwrite", action="store_true")
    pear_parser.set_defaults(func=_cmd_design_pear_authority)

    detector_parser = subparsers.add_parser(
        "design-metal-detector-authority",
        help="generate the metal detector whose exposed spiral traces are "
        "the sensing coil, with authority evidence",
    )
    detector_parser.add_argument("output")
    detector_parser.add_argument("--request", required=True)
    detector_parser.add_argument("--name", required=True)
    detector_parser.add_argument("--overwrite", action="store_true")
    detector_parser.set_defaults(func=_cmd_design_metal_detector_authority)

    revision_plan_parser = subparsers.add_parser(
        "revision-plan",
        help="analyse a revision's review bundle and decide patch, redo, or "
        "escalate for the next iteration",
    )
    revision_plan_parser.add_argument("output")
    revision_plan_parser.set_defaults(func=_cmd_revision_plan)

    review_comment_parser = subparsers.add_parser(
        "review-comment",
        help="record a human review comment on a revision as a structured "
        "finding that revision-plan takes into account",
    )
    review_comment_parser.add_argument("output")
    review_comment_parser.add_argument(
        "--where",
        required=True,
        help="what the comment is about: a reference (D1), net (/FB), or region",
    )
    review_comment_parser.add_argument("--comment", required=True)
    review_comment_parser.add_argument(
        "--severity",
        choices=("blocker", "warning", "style"),
        default="warning",
    )
    review_comment_parser.add_argument(
        "--scope",
        choices=("component", "net", "region", "global"),
        default="component",
    )
    review_comment_parser.add_argument("--rule")
    review_comment_parser.add_argument("--action")
    review_comment_parser.set_defaults(func=_cmd_review_comment)

    nexar_smoke_parser = subparsers.add_parser(
        "evidence-nexar-smoke",
        help="run an opt-in live Nexar provider smoke when credentials are configured",
    )
    nexar_smoke_parser.add_argument("--role", required=True)
    nexar_smoke_parser.add_argument("--query", required=True)
    nexar_smoke_parser.add_argument("--manufacturer")
    nexar_smoke_parser.add_argument("--part-number")
    nexar_smoke_parser.add_argument("--limit", type=int, default=3)
    nexar_smoke_parser.set_defaults(func=_cmd_evidence_nexar_smoke)

    extract_parser = subparsers.add_parser(
        "evidence-extract",
        help="run LLM datasheet fact extraction for pending manifest jobs",
    )
    extract_parser.add_argument("manifest")
    extract_parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="also re-run extraction jobs that previously failed",
    )
    _add_datasheet_provider_arguments(extract_parser)
    extract_parser.set_defaults(func=_cmd_evidence_extract)

    add_local_parser = subparsers.add_parser(
        "evidence-add-local",
        help="register a locally downloaded datasheet PDF in an evidence manifest",
    )
    add_local_parser.add_argument("manifest")
    add_local_parser.add_argument("--pdf", required=True)
    add_local_parser.add_argument("--role", required=True)
    add_local_parser.add_argument("--manufacturer", required=True)
    add_local_parser.add_argument("--part-number", required=True)
    add_local_parser.add_argument(
        "--symbol-id",
        required=True,
        help="builtin symbol binding, for example stdlib:LED or stdlib:R",
    )
    add_local_parser.add_argument("--value")
    add_local_parser.add_argument(
        "--footprint",
        help="KiCad footprint, for example LED_SMD:LED_0603_1608Metric",
    )
    add_local_parser.add_argument("--source-url")
    add_local_parser.set_defaults(func=_cmd_evidence_add_local)

    acquire_parser = subparsers.add_parser(
        "evidence-acquire",
        help="search Nexar, download the best datasheet, and register it in a manifest",
    )
    acquire_parser.add_argument("manifest")
    acquire_parser.add_argument("--role", required=True)
    acquire_parser.add_argument("--query", required=True)
    acquire_parser.add_argument("--manufacturer")
    acquire_parser.add_argument("--part-number")
    acquire_parser.add_argument(
        "--cache-dir",
        help="directory for downloaded datasheets; defaults to the manifest directory",
    )
    acquire_parser.set_defaults(func=_cmd_evidence_acquire)

    facts_parser = subparsers.add_parser(
        "datasheet-facts",
        help="extract facts from a single datasheet PDF and print them as JSON",
    )
    facts_parser.add_argument("pdf")
    facts_parser.add_argument("--role", required=True)
    facts_parser.add_argument("--manufacturer", default="Unknown manufacturer")
    facts_parser.add_argument("--part-number", required=True)
    _add_datasheet_provider_arguments(facts_parser)
    facts_parser.set_defaults(func=_cmd_datasheet_facts)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command: Callable[[argparse.Namespace], int] = args.func
        return command(args)
    except (
        ProjectIOError,
        KeyError,
        ValueError,
        NexarProviderError,
        DatasheetExtractionError,
        EvidenceDownloadError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
