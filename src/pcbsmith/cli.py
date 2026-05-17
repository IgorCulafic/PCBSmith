from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

from pcbsmith.ai.ai_brief import write_ai_brief
from pcbsmith.ai.ai_context import write_ai_context
from pcbsmith.ai.ai_demo_plan import write_ai_demo_plan
from pcbsmith.ai.ai_openai_compatible_plan import write_openai_compatible_plan
from pcbsmith.ai.ai_openai_compatible_review import run_openai_compatible_review
from pcbsmith.ai.ai_plan_check import check_ai_plan
from pcbsmith.ai.ai_plan_review import run_ai_plan_review
from pcbsmith.ai.ai_planner_package import write_ai_planner_package
from pcbsmith.ai.ai_proposal_bundle import run_ai_proposal_bundle
from pcbsmith.ai.local_ai_review import run_local_ai_review
from pcbsmith.ai.local_model_config import (
    format_local_model_config,
    load_local_model_config,
    write_local_model_config_template,
)
from pcbsmith.calculators.electronics import (
    SUPPORTED_CALCULATORS,
    format_calculation_result,
    run_calculator,
)
from pcbsmith.core.board import Layer
from pcbsmith.core.netops import derive_netlist
from pcbsmith.core.schematic import Schematic
from pcbsmith.kicad.kicad_backend import KICAD_CLI_ENV, find_kicad_cli
from pcbsmith.kicad.kicad_doctor import (
    format_kicad_doctor_report,
    run_kicad_doctor,
)
from pcbsmith.kicad.kicad_export import export_pcbs_project_to_kicad
from pcbsmith.kicad.kicad_library_index import (
    find_kicad_library_roots,
    kicad_library_roots_from_cli,
    write_kicad_library_index,
)
from pcbsmith.kicad.kicad_part_resolver import (
    format_kicad_part_resolution,
    resolve_kicad_part_from_index_file,
)
from pcbsmith.kicad.kicad_plan import KiCadPlanError, run_kicad_plan
from pcbsmith.kicad.kicad_preview import (
    format_kicad_preview_report,
    run_kicad_preview,
)
from pcbsmith.kicad.kicad_project import create_kicad_project_skeleton
from pcbsmith.kicad.kicad_review_bundle import (
    format_kicad_review_bundle_result,
    run_kicad_review_bundle,
)
from pcbsmith.kicad.kicad_validate import (
    format_kicad_validation_report,
    run_kicad_validation,
)
from pcbsmith.knowledge.builtin_library import SYMBOLS
from pcbsmith.knowledge.circuit_topologies import (
    SUPPORTED_TOPOLOGY_INTENTS,
    format_circuit_topology_selection,
    select_topologies_for_intent,
)
from pcbsmith.knowledge.component_knowledge_index import (
    format_component_knowledge_index_summary,
    format_component_knowledge_search_result,
    search_component_knowledge_index_file,
    write_component_knowledge_index,
)
from pcbsmith.knowledge.component_selection import (
    SUPPORTED_COMPONENT_INTENTS,
    format_component_selection_result,
    select_components_for_intent_file,
)
from pcbsmith.operations.design_operations import (
    AttinyLedControllerDesignRequest,
    LedArtDesignRequest,
    SilkscreenArtworkDesignRequest,
    format_design_operation_result,
    generate_attiny_led_controller_design,
    generate_led_art_design,
    generate_silkscreen_artwork_design,
)
from pcbsmith.operations.project_io import (
    ProjectIOError,
    create_project,
    load_board,
    load_project,
    load_schematic,
)
from pcbsmith.rules.board_manufacturability import (
    format_board_manufacturability_report,
    inspect_board_manufacturability,
)
from pcbsmith.rules.circuit_rules import (
    SUPPORTED_CIRCUIT_RULE_INTENTS,
    check_circuit_rules,
    check_circuit_rules_file,
    format_circuit_rule_report,
    parse_rule_parameters,
    write_circuit_rule_report,
)
from pcbsmith.rules.erc import run_erc


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


def _cmd_board_check(args: argparse.Namespace) -> int:
    project_dir = Path(args.project)
    project = load_project(project_dir)
    if not project.boards:
        raise ValueError("Project has no boards")
    board = load_board(project_dir, project.boards[0])
    report = inspect_board_manufacturability(board, design_rules=project.design_rules)
    for line in format_board_manufacturability_report(report):
        print(line)
    return report.exit_code


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


def _cmd_kicad_status(_args: argparse.Namespace) -> int:
    install = find_kicad_cli()
    if install is None:
        print(f"KiCad CLI not found. Install KiCad or set {KICAD_CLI_ENV}=<path-to-kicad-cli>.")
        return 1

    print(f"KiCad CLI: {install.cli_path} ({install.source})")
    return 0


def _cmd_kicad_doctor(args: argparse.Namespace) -> int:
    report = run_kicad_doctor(skip_version_check=args.skip_version_check)
    for line in format_kicad_doctor_report(report):
        print(line)
    return report.exit_code


def _cmd_kicad_new(args: argparse.Namespace) -> int:
    result = create_kicad_project_skeleton(Path(args.project), args.name)
    print(f"Created KiCad project skeleton at {result.project_dir}")
    return 0


def _cmd_kicad_export(args: argparse.Namespace) -> int:
    result = export_pcbs_project_to_kicad(
        Path(args.source_project),
        Path(args.output_project),
        project_name=args.name,
    )
    print(f"Exported PCBSmith project to KiCad handoff at {result.skeleton.project_dir}")
    return 0


def _cmd_kicad_validate(args: argparse.Namespace) -> int:
    report = run_kicad_validation(
        Path(args.project),
        execute=not args.skip_execution,
    )
    for line in format_kicad_validation_report(report):
        print(line)
    return report.exit_code


def _cmd_kicad_preview(args: argparse.Namespace) -> int:
    report = run_kicad_preview(
        Path(args.project),
        execute=not args.skip_execution,
    )
    for line in format_kicad_preview_report(report):
        print(line)
    return report.exit_code


def _cmd_kicad_library_index(args: argparse.Namespace) -> int:
    symbols_dir = Path(args.symbols_dir) if args.symbols_dir else None
    footprints_dir = Path(args.footprints_dir) if args.footprints_dir else None
    if symbols_dir is None or footprints_dir is None:
        install = find_kicad_cli()
        if install is None:
            raise ValueError(
                "KiCad CLI not found. Provide --symbols-dir and --footprints-dir "
                f"or set {KICAD_CLI_ENV}=<path-to-kicad-cli>."
            )
        roots = find_kicad_library_roots(install.cli_path)
        if roots is None:
            fallback = kicad_library_roots_from_cli(install.cli_path)
            raise ValueError(
                "KiCad library directories not found. Provide --symbols-dir and "
                f"--footprints-dir. Tried {fallback.symbols_dir} and known installs."
            )
        symbols_dir = symbols_dir or roots.symbols_dir
        footprints_dir = footprints_dir or roots.footprints_dir

    write_kicad_library_index(
        Path(args.output),
        symbols_dir=symbols_dir,
        footprints_dir=footprints_dir,
        symbol_libraries=tuple(args.symbol_library or ["Device", "power"]),
        footprint_libraries=tuple(
            args.footprint_library or ["Resistor_SMD", "Capacitor_SMD", "LED_SMD", "Diode_SMD"]
        ),
    )
    print(f"Wrote KiCad library index to {Path(args.output)}")
    return 0


def _cmd_kicad_part_resolve(args: argparse.Namespace) -> int:
    result = resolve_kicad_part_from_index_file(
        args.entry_id,
        Path(args.library_index),
    )
    for line in format_kicad_part_resolution(result):
        print(line)
    return 0 if result.available else 1


def _cmd_component_knowledge_index(args: argparse.Namespace) -> int:
    output_path = Path(args.output)
    index = write_component_knowledge_index(
        output_path,
        kicad_library_index_path=(
            Path(args.kicad_library_index) if args.kicad_library_index else None
        ),
    )
    for line in format_component_knowledge_index_summary(index, output_path=output_path):
        print(line)
    return 0


def _cmd_component_knowledge_search(args: argparse.Namespace) -> int:
    result = search_component_knowledge_index_file(
        Path(args.index),
        query=args.query,
        mounting=args.mounting,
        support_status=args.support_status,
        tags=tuple(args.tag or ()),
        limit=args.limit,
    )
    for line in format_component_knowledge_search_result(result):
        print(line)
    return 0


def _cmd_component_selection(args: argparse.Namespace) -> int:
    result = select_components_for_intent_file(
        Path(args.index),
        args.intent,
        preferred_mounting=args.preferred_mounting,
        limit=args.limit,
    )
    for line in format_component_selection_result(result):
        print(line)
    return 0


def _cmd_circuit_topologies(args: argparse.Namespace) -> int:
    result = select_topologies_for_intent(args.intent)
    for line in format_circuit_topology_selection(result):
        print(line)
    return 0


def _cmd_calculator(args: argparse.Namespace) -> int:
    result = run_calculator(args.calculator, parse_rule_parameters(tuple(args.param or ())))
    for line in format_calculation_result(result):
        print(line)
    return 1 if result["status"] == "error" else 0


def _cmd_circuit_rules(args: argparse.Namespace) -> int:
    if args.parameters_json:
        report = check_circuit_rules_file(args.intent, Path(args.parameters_json))
    else:
        report = check_circuit_rules(
            args.intent,
            parse_rule_parameters(tuple(args.param or ())),
        )
    if args.output:
        write_circuit_rule_report(report, Path(args.output))
    for line in format_circuit_rule_report(report):
        print(line)
    return report.exit_code


def _cmd_kicad_plan(args: argparse.Namespace) -> int:
    result = run_kicad_plan(
        Path(args.project),
        Path(args.package),
        apply=args.apply,
    )
    for line in result.lines:
        print(line)
    return 0


def _cmd_kicad_context(args: argparse.Namespace) -> int:
    write_ai_context(
        Path(args.project),
        Path(args.output),
        kicad_project_dir=Path(args.kicad_project) if args.kicad_project else None,
    )
    print(f"Wrote AI context package to {Path(args.output)}")
    return 0


def _cmd_kicad_review_bundle(args: argparse.Namespace) -> int:
    result = run_kicad_review_bundle(
        Path(args.source_project),
        Path(args.output_project),
        project_name=args.name,
        execute_kicad=not args.skip_execution,
    )
    for line in format_kicad_review_bundle_result(result):
        print(line)
    return result.exit_code


def _cmd_ai_brief(args: argparse.Namespace) -> int:
    request_text = Path(args.request).read_text(encoding="utf-8")
    write_ai_brief(
        Path(args.project),
        request_text,
        Path(args.output),
        kicad_project_dir=Path(args.kicad_project) if args.kicad_project else None,
    )
    print(f"Wrote AI engineering brief to {Path(args.output)}")
    return 0


def _cmd_ai_planner_package(args: argparse.Namespace) -> int:
    write_ai_planner_package(Path(args.brief), Path(args.output))
    print(f"Wrote AI planner package to {Path(args.output)}")
    return 0


def _cmd_ai_demo_plan(args: argparse.Namespace) -> int:
    write_ai_demo_plan(Path(args.planner_package), Path(args.output))
    print(f"Wrote AI demo candidate plan to {Path(args.output)}")
    return 0


def _cmd_ai_openai_plan(args: argparse.Namespace) -> int:
    write_openai_compatible_plan(
        Path(args.planner_package),
        Path(args.output),
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key
        or os.environ.get("PCBSMITH_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY"),
        timeout_seconds=args.timeout,
        use_json_mode=not args.no_json_mode,
    )
    print(f"Wrote OpenAI-compatible AI candidate plan to {Path(args.output)}")
    return 0


def _cmd_ai_openai_review(args: argparse.Namespace) -> int:
    result = run_openai_compatible_review(
        Path(args.project),
        Path(args.request),
        Path(args.output_dir),
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key
        or os.environ.get("PCBSMITH_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY"),
        timeout_seconds=args.timeout,
        use_json_mode=not args.no_json_mode,
        kicad_project_dir=Path(args.kicad_project) if args.kicad_project else None,
        apply=args.apply,
    )
    for line in result.lines:
        print(line)
    return result.exit_code


def _cmd_local_ai_config_template(args: argparse.Namespace) -> int:
    config = write_local_model_config_template(Path(args.output))
    print(f"Wrote local AI config template to {Path(args.output)}")
    for line in format_local_model_config(config):
        print(line)
    return 0


def _cmd_local_ai_config_check(args: argparse.Namespace) -> int:
    config = load_local_model_config(Path(args.config) if args.config else None)
    for line in format_local_model_config(config):
        print(line)
    return 0


def _cmd_local_ai_review(args: argparse.Namespace) -> int:
    result = run_local_ai_review(
        Path(args.project),
        Path(args.request),
        Path(args.output_dir),
        config_path=Path(args.config) if args.config else None,
        kicad_project_dir=Path(args.kicad_project) if args.kicad_project else None,
        apply=args.apply,
    )
    for line in result.lines:
        print(line)
    return result.exit_code


def _cmd_ai_plan_check(args: argparse.Namespace) -> int:
    result = check_ai_plan(Path(args.planner_package), Path(args.candidate_plan))
    for line in result.lines:
        print(line)
    return result.exit_code


def _cmd_ai_plan_review(args: argparse.Namespace) -> int:
    result = run_ai_plan_review(
        Path(args.project),
        Path(args.planner_package),
        Path(args.candidate_plan),
        apply=args.apply,
    )
    for line in result.lines:
        print(line)
    return result.exit_code


def _cmd_ai_proposal_bundle(args: argparse.Namespace) -> int:
    result = run_ai_proposal_bundle(
        Path(args.project),
        Path(args.planner_package),
        Path(args.candidate_plan),
        Path(args.output_dir),
        execute_kicad=not args.skip_execution,
    )
    for line in result.lines:
        print(line)
    return result.exit_code


def _cmd_design_led_art(args: argparse.Namespace) -> int:
    request = LedArtDesignRequest(
        name=args.name,
        text=args.text,
        supply_voltage_v=args.voltage,
        topology=args.topology,
        control_mode=args.control,
        show_polarity_marks=not args.no_polarity_marks,
    )
    result = generate_led_art_design(
        request,
        Path(args.output_project),
        execute_kicad=not args.skip_execution,
        overwrite=args.overwrite,
    )
    for line in format_design_operation_result(result):
        print(line)
    return result.exit_code


def _cmd_design_attiny_led_controller(args: argparse.Namespace) -> int:
    request = AttinyLedControllerDesignRequest(
        name=args.name,
        controller=args.controller,
        led_outputs=args.led_outputs,
        led_resistor_value=args.led_resistor,
        show_polarity_marks=not args.no_polarity_marks,
        connector_style=args.connector_style,
    )
    result = generate_attiny_led_controller_design(
        request,
        Path(args.output_project),
        execute_kicad=not args.skip_execution,
        overwrite=args.overwrite,
    )
    for line in format_design_operation_result(result):
        print(line)
    return result.exit_code


def _cmd_design_silkscreen_artwork(args: argparse.Namespace) -> int:
    request = SilkscreenArtworkDesignRequest(
        name=args.name,
        text=args.text,
        layer=Layer(args.layer),
        x_mm=args.x,
        y_mm=args.y,
        rotation_deg=args.rotation,
        size_mm=args.size,
        thickness_mm=args.thickness,
        board_width_mm=args.board_width,
        board_height_mm=args.board_height,
    )
    result = generate_silkscreen_artwork_design(
        request,
        Path(args.output_project),
        execute_kicad=not args.skip_execution,
        overwrite=args.overwrite,
    )
    for line in format_design_operation_result(result):
        print(line)
    return result.exit_code


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

    board_check_parser = subparsers.add_parser(
        "board-check",
        help="run lightweight PCBSmith manufacturability checks on the first board",
    )
    board_check_parser.add_argument("project")
    board_check_parser.set_defaults(func=_cmd_board_check)

    netlist_parser = subparsers.add_parser("netlist", help="derive the first schematic netlist")
    netlist_parser.add_argument("project")
    netlist_parser.set_defaults(func=_cmd_netlist)

    erc_parser = subparsers.add_parser("erc", help="run ERC on the first schematic")
    erc_parser.add_argument("project")
    erc_parser.set_defaults(func=_cmd_erc)

    kicad_status_parser = subparsers.add_parser(
        "kicad-status",
        help="check whether a KiCad CLI backend is available",
    )
    kicad_status_parser.set_defaults(func=_cmd_kicad_status)

    kicad_doctor_parser = subparsers.add_parser(
        "kicad-doctor",
        help="check KiCad backend readiness with a version probe",
    )
    kicad_doctor_parser.add_argument(
        "--skip-version-check",
        action="store_true",
        help="only report configured kicad-cli discovery, without running it",
    )
    kicad_doctor_parser.set_defaults(func=_cmd_kicad_doctor)

    kicad_new_parser = subparsers.add_parser(
        "kicad-new",
        help="create a KiCad project skeleton for PCBSmith handoff",
    )
    kicad_new_parser.add_argument("project")
    kicad_new_parser.add_argument("--name", required=True)
    kicad_new_parser.set_defaults(func=_cmd_kicad_new)

    kicad_export_parser = subparsers.add_parser(
        "kicad-export",
        help="export a PCBSmith project to a KiCad skeleton and handoff manifest",
    )
    kicad_export_parser.add_argument("source_project")
    kicad_export_parser.add_argument("output_project")
    kicad_export_parser.add_argument("--name")
    kicad_export_parser.set_defaults(func=_cmd_kicad_export)

    kicad_validate_parser = subparsers.add_parser(
        "kicad-validate",
        help="run KiCad ERC/DRC validation on a KiCad project folder",
    )
    kicad_validate_parser.add_argument("project")
    kicad_validate_parser.add_argument(
        "--skip-execution",
        action="store_true",
        help="discover project files and configured kicad-cli without running KiCad",
    )
    kicad_validate_parser.set_defaults(func=_cmd_kicad_validate)

    kicad_preview_parser = subparsers.add_parser(
        "kicad-preview",
        help="export KiCad schematic and board SVG previews for AI review",
    )
    kicad_preview_parser.add_argument("project")
    kicad_preview_parser.add_argument(
        "--skip-execution",
        action="store_true",
        help="discover project files and configured kicad-cli without exporting previews",
    )
    kicad_preview_parser.set_defaults(func=_cmd_kicad_preview)

    kicad_library_index_parser = subparsers.add_parser(
        "kicad-library-index",
        help="write a read-only manifest of KiCad symbols and footprints",
    )
    kicad_library_index_parser.add_argument("output")
    kicad_library_index_parser.add_argument(
        "--symbols-dir",
        help="KiCad symbols directory; defaults to the directory next to kicad-cli",
    )
    kicad_library_index_parser.add_argument(
        "--footprints-dir",
        help="KiCad footprints directory; defaults to the directory next to kicad-cli",
    )
    kicad_library_index_parser.add_argument(
        "--symbol-library",
        action="append",
        default=None,
        help="KiCad symbol library name to include, repeatable",
    )
    kicad_library_index_parser.add_argument(
        "--footprint-library",
        action="append",
        default=None,
        help="KiCad footprint library name to include, repeatable",
    )
    kicad_library_index_parser.set_defaults(func=_cmd_kicad_library_index)

    kicad_part_resolve_parser = subparsers.add_parser(
        "kicad-part-resolve",
        help="resolve a PCBSmith catalog entry against a KiCad library index",
    )
    kicad_part_resolve_parser.add_argument("entry_id")
    kicad_part_resolve_parser.add_argument("library_index")
    kicad_part_resolve_parser.set_defaults(func=_cmd_kicad_part_resolve)

    component_knowledge_index_parser = subparsers.add_parser(
        "component-knowledge-index",
        help="write a compact AI-facing index of supported component knowledge",
    )
    component_knowledge_index_parser.add_argument("output")
    component_knowledge_index_parser.add_argument(
        "--kicad-library-index",
        help="optional KiCad library index used to mark supported bindings",
    )
    component_knowledge_index_parser.set_defaults(func=_cmd_component_knowledge_index)

    component_knowledge_search_parser = subparsers.add_parser(
        "component-knowledge-search",
        help="search a component knowledge index with compact AI-facing output",
    )
    component_knowledge_search_parser.add_argument("index")
    component_knowledge_search_parser.add_argument("--query", default="")
    component_knowledge_search_parser.add_argument(
        "--mounting",
        choices=("smd", "through-hole", "virtual", "unspecified"),
        default=None,
    )
    component_knowledge_search_parser.add_argument(
        "--support-status",
        choices=("well_supported", "metadata_only", "needs_datasheet_review"),
        default=None,
    )
    component_knowledge_search_parser.add_argument(
        "--tag",
        action="append",
        default=None,
        help="required tag; repeatable",
    )
    component_knowledge_search_parser.add_argument("--limit", type=int, default=10)
    component_knowledge_search_parser.set_defaults(func=_cmd_component_knowledge_search)

    component_selection_parser = subparsers.add_parser(
        "component-select",
        aliases=["component-selection"],
        help="select ranked component candidates for an engineering intent",
    )
    component_selection_parser.add_argument("index")
    component_selection_parser.add_argument(
        "intent",
        choices=SUPPORTED_COMPONENT_INTENTS,
    )
    component_selection_parser.add_argument(
        "--preferred-mounting",
        choices=("smd", "through-hole", "virtual", "unspecified"),
        default="smd",
    )
    component_selection_parser.add_argument("--limit", type=int, default=5)
    component_selection_parser.set_defaults(func=_cmd_component_selection)

    circuit_topologies_parser = subparsers.add_parser(
        "circuit-topologies",
        help="select ranked circuit topologies for an engineering intent",
    )
    circuit_topologies_parser.add_argument("intent", choices=SUPPORTED_TOPOLOGY_INTENTS)
    circuit_topologies_parser.set_defaults(func=_cmd_circuit_topologies)

    calculator_parser = subparsers.add_parser(
        "calculator",
        help="run deterministic engineering math for AI and design operations",
    )
    calculator_parser.add_argument("calculator", choices=SUPPORTED_CALCULATORS)
    calculator_parser.add_argument(
        "--param",
        action="append",
        default=None,
        help="calculator parameter as key=value; repeatable",
    )
    calculator_parser.set_defaults(func=_cmd_calculator)

    circuit_rules_parser = subparsers.add_parser(
        "circuit-rules",
        help="check electrical assumptions for a supported circuit intent",
    )
    circuit_rules_parser.add_argument("intent", choices=SUPPORTED_CIRCUIT_RULE_INTENTS)
    circuit_rules_parser.add_argument(
        "--param",
        action="append",
        default=None,
        help="circuit parameter as key=value; repeatable",
    )
    circuit_rules_parser.add_argument(
        "--parameters-json",
        help="optional JSON object containing circuit rule parameters",
    )
    circuit_rules_parser.add_argument(
        "--output",
        help="optional path for the machine-readable JSON rule report",
    )
    circuit_rules_parser.set_defaults(func=_cmd_circuit_rules)

    kicad_plan_parser = subparsers.add_parser(
        "kicad-plan",
        help="review or apply a structured PCBSmith command package",
    )
    kicad_plan_parser.add_argument("project")
    kicad_plan_parser.add_argument("package")
    kicad_plan_parser.add_argument(
        "--apply",
        action="store_true",
        help="save the proposed changes and append an action log",
    )
    kicad_plan_parser.set_defaults(func=_cmd_kicad_plan)

    kicad_context_parser = subparsers.add_parser(
        "kicad-context",
        help="write a structured AI context package for a PCBSmith project",
    )
    kicad_context_parser.add_argument("project")
    kicad_context_parser.add_argument("output")
    kicad_context_parser.add_argument(
        "--kicad-project",
        help="optional KiCad handoff project with reports and visual references",
    )
    kicad_context_parser.set_defaults(func=_cmd_kicad_context)

    kicad_review_bundle_parser = subparsers.add_parser(
        "kicad-review-bundle",
        help="export KiCad handoff, checks, previews, and AI context into one folder",
    )
    kicad_review_bundle_parser.add_argument("source_project")
    kicad_review_bundle_parser.add_argument("output_project")
    kicad_review_bundle_parser.add_argument("--name")
    kicad_review_bundle_parser.add_argument(
        "--skip-execution",
        action="store_true",
        help="create the bundle without running KiCad validation or preview exports",
    )
    kicad_review_bundle_parser.set_defaults(func=_cmd_kicad_review_bundle)

    ai_brief_parser = subparsers.add_parser(
        "ai-brief",
        help="write a structured engineering brief from a user request",
    )
    ai_brief_parser.add_argument("project")
    ai_brief_parser.add_argument("request")
    ai_brief_parser.add_argument("output")
    ai_brief_parser.add_argument(
        "--kicad-project",
        help="optional KiCad review bundle with reports and visual references",
    )
    ai_brief_parser.set_defaults(func=_cmd_ai_brief)

    ai_planner_package_parser = subparsers.add_parser(
        "ai-planner-package",
        help="wrap an AI brief with the provider-neutral planner output contract",
    )
    ai_planner_package_parser.add_argument("brief")
    ai_planner_package_parser.add_argument("output")
    ai_planner_package_parser.set_defaults(func=_cmd_ai_planner_package)

    ai_demo_plan_parser = subparsers.add_parser(
        "ai-demo-plan",
        help="write a deterministic demo candidate plan from a planner package",
    )
    ai_demo_plan_parser.add_argument("planner_package")
    ai_demo_plan_parser.add_argument("output")
    ai_demo_plan_parser.set_defaults(func=_cmd_ai_demo_plan)

    ai_openai_plan_parser = subparsers.add_parser(
        "ai-openai-plan",
        help="call an OpenAI-compatible chat endpoint to write a candidate plan",
    )
    ai_openai_plan_parser.add_argument("planner_package")
    ai_openai_plan_parser.add_argument("output")
    ai_openai_plan_parser.add_argument(
        "--base-url",
        required=True,
        help="OpenAI-compatible API base URL, for example http://127.0.0.1:1234",
    )
    ai_openai_plan_parser.add_argument("--model", required=True)
    ai_openai_plan_parser.add_argument(
        "--api-key",
        help="optional bearer token; defaults to PCBSMITH_OPENAI_API_KEY or OPENAI_API_KEY",
    )
    ai_openai_plan_parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="request timeout in seconds",
    )
    ai_openai_plan_parser.add_argument(
        "--no-json-mode",
        action="store_true",
        help="omit response_format for local servers that do not support JSON mode",
    )
    ai_openai_plan_parser.set_defaults(func=_cmd_ai_openai_plan)

    ai_openai_review_parser = subparsers.add_parser(
        "ai-openai-review",
        help="run request-to-model-to-approval-preview with an OpenAI-compatible endpoint",
    )
    ai_openai_review_parser.add_argument("project")
    ai_openai_review_parser.add_argument("request")
    ai_openai_review_parser.add_argument("output_dir")
    ai_openai_review_parser.add_argument(
        "--base-url",
        required=True,
        help="OpenAI-compatible API base URL, for example http://127.0.0.1:1234",
    )
    ai_openai_review_parser.add_argument("--model", required=True)
    ai_openai_review_parser.add_argument(
        "--api-key",
        help="optional bearer token; defaults to PCBSMITH_OPENAI_API_KEY or OPENAI_API_KEY",
    )
    ai_openai_review_parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="request timeout in seconds",
    )
    ai_openai_review_parser.add_argument(
        "--no-json-mode",
        action="store_true",
        help="omit response_format for local servers that do not support JSON mode",
    )
    ai_openai_review_parser.add_argument(
        "--kicad-project",
        help="optional KiCad review bundle with reports and visual references",
    )
    ai_openai_review_parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the validated candidate plan instead of dry-running it",
    )
    ai_openai_review_parser.set_defaults(func=_cmd_ai_openai_review)

    local_ai_config_template_parser = subparsers.add_parser(
        "local-ai-config-template",
        help="write a safe editable config for a local OpenAI-compatible model server",
    )
    local_ai_config_template_parser.add_argument("output")
    local_ai_config_template_parser.set_defaults(func=_cmd_local_ai_config_template)

    local_ai_config_check_parser = subparsers.add_parser(
        "local-ai-config-check",
        help="print local AI endpoint configuration without contacting the model",
    )
    local_ai_config_check_parser.add_argument(
        "--config",
        help="optional local AI JSON config; otherwise PCBSmith reads environment variables",
    )
    local_ai_config_check_parser.set_defaults(func=_cmd_local_ai_config_check)

    local_ai_review_parser = subparsers.add_parser(
        "local-ai-review",
        help="run request-to-model-to-approval-preview using local AI config",
    )
    local_ai_review_parser.add_argument("project")
    local_ai_review_parser.add_argument("request")
    local_ai_review_parser.add_argument("output_dir")
    local_ai_review_parser.add_argument(
        "--config",
        help="optional local AI JSON config; otherwise PCBSmith reads environment variables",
    )
    local_ai_review_parser.add_argument(
        "--kicad-project",
        help="optional KiCad review bundle with reports and visual references",
    )
    local_ai_review_parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the validated candidate plan instead of dry-running it",
    )
    local_ai_review_parser.set_defaults(func=_cmd_local_ai_review)

    ai_plan_check_parser = subparsers.add_parser(
        "ai-plan-check",
        help="validate a candidate AI command plan against a planner package",
    )
    ai_plan_check_parser.add_argument("planner_package")
    ai_plan_check_parser.add_argument("candidate_plan")
    ai_plan_check_parser.set_defaults(func=_cmd_ai_plan_check)

    ai_plan_review_parser = subparsers.add_parser(
        "ai-plan-review",
        help="validate a candidate AI plan and run the approval preview/apply path",
    )
    ai_plan_review_parser.add_argument("project")
    ai_plan_review_parser.add_argument("planner_package")
    ai_plan_review_parser.add_argument("candidate_plan")
    ai_plan_review_parser.add_argument(
        "--apply",
        action="store_true",
        help="save the validated candidate plan through the approval loop",
    )
    ai_plan_review_parser.set_defaults(func=_cmd_ai_plan_review)

    ai_proposal_bundle_parser = subparsers.add_parser(
        "ai-proposal-bundle",
        help="stage an AI candidate plan and export KiCad previews without mutating source",
    )
    ai_proposal_bundle_parser.add_argument("project")
    ai_proposal_bundle_parser.add_argument("planner_package")
    ai_proposal_bundle_parser.add_argument("candidate_plan")
    ai_proposal_bundle_parser.add_argument("output_dir")
    ai_proposal_bundle_parser.add_argument(
        "--skip-execution",
        action="store_true",
        help="create KiCad files without running KiCad validation or preview exports",
    )
    ai_proposal_bundle_parser.set_defaults(func=_cmd_ai_proposal_bundle)

    design_led_art_parser = subparsers.add_parser(
        "design-led-art",
        help="generate a KiCad LED-art review bundle from a structured request",
    )
    design_led_art_parser.add_argument("output_project")
    design_led_art_parser.add_argument("--name", default="LED Art Design")
    design_led_art_parser.add_argument("--text", default="VIR-LAB")
    design_led_art_parser.add_argument(
        "--voltage",
        type=float,
        default=12.0,
        help="requested supply voltage; used to choose a topology if --topology is omitted",
    )
    design_led_art_parser.add_argument(
        "--topology",
        choices=("5v_one_per_led", "5v_two_led_dense", "12v_dense"),
        default=None,
    )
    design_led_art_parser.add_argument(
        "--control",
        choices=("none", "low_side_mosfet"),
        default="none",
    )
    design_led_art_parser.add_argument(
        "--no-polarity-marks",
        action="store_true",
        help="omit educational LED anode + marks from the board silkscreen",
    )
    design_led_art_parser.add_argument(
        "--skip-execution",
        action="store_true",
        help="write KiCad files and reports without running KiCad validation or preview exports",
    )
    design_led_art_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output directory",
    )
    design_led_art_parser.set_defaults(func=_cmd_design_led_art)

    design_attiny_parser = subparsers.add_parser(
        "design-attiny-led-controller",
        help="generate an ATtiny-style LED controller KiCad review bundle",
    )
    design_attiny_parser.add_argument("output_project")
    design_attiny_parser.add_argument("--name", default="ATtiny LED Controller")
    design_attiny_parser.add_argument("--controller", default="ATtiny84")
    design_attiny_parser.add_argument("--led-outputs", type=int, choices=(1, 2), default=2)
    design_attiny_parser.add_argument("--led-resistor", default="330R")
    design_attiny_parser.add_argument(
        "--connector-style",
        choices=("through_hole", "smd_pads"),
        default="through_hole",
        help="choose a solderable through-hole ISP header or compact SMD programming pads",
    )
    design_attiny_parser.add_argument(
        "--no-polarity-marks",
        action="store_true",
        help="omit educational LED anode + marks from the board silkscreen",
    )
    design_attiny_parser.add_argument(
        "--skip-execution",
        action="store_true",
        help="write KiCad files and reports without running KiCad validation or preview exports",
    )
    design_attiny_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output directory",
    )
    design_attiny_parser.set_defaults(func=_cmd_design_attiny_led_controller)

    design_silkscreen_parser = subparsers.add_parser(
        "design-silkscreen-artwork",
        help="generate a KiCad silkscreen artwork review bundle",
    )
    design_silkscreen_parser.add_argument("output_project")
    design_silkscreen_parser.add_argument("--name", default="Silkscreen Artwork")
    design_silkscreen_parser.add_argument("--text", required=True)
    design_silkscreen_parser.add_argument(
        "--layer",
        choices=(Layer.F_SILK.value, Layer.B_SILK.value),
        default=Layer.F_SILK.value,
    )
    design_silkscreen_parser.add_argument("--x", type=float, default=20.0)
    design_silkscreen_parser.add_argument("--y", type=float, default=15.0)
    design_silkscreen_parser.add_argument("--rotation", type=int, default=0)
    design_silkscreen_parser.add_argument("--size", type=float, default=1.5)
    design_silkscreen_parser.add_argument("--thickness", type=float, default=0.15)
    design_silkscreen_parser.add_argument("--board-width", type=float, default=50.0)
    design_silkscreen_parser.add_argument("--board-height", type=float, default=30.0)
    design_silkscreen_parser.add_argument(
        "--skip-execution",
        action="store_true",
        help="write KiCad files and reports without running KiCad validation or preview exports",
    )
    design_silkscreen_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output directory",
    )
    design_silkscreen_parser.set_defaults(func=_cmd_design_silkscreen_artwork)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command: Callable[[argparse.Namespace], int] = args.func
        return command(args)
    except (FileExistsError, KiCadPlanError, ProjectIOError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
