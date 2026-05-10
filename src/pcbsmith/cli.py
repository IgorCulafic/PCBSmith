from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from pcbsmith.core.netops import derive_netlist
from pcbsmith.core.schematic import Schematic
from pcbsmith.services.ai_brief import write_ai_brief
from pcbsmith.services.ai_context import write_ai_context
from pcbsmith.services.ai_plan_check import check_ai_plan
from pcbsmith.services.ai_planner_package import write_ai_planner_package
from pcbsmith.services.builtin_library import SYMBOLS
from pcbsmith.services.erc import run_erc
from pcbsmith.services.kicad_backend import KICAD_CLI_ENV, find_kicad_cli
from pcbsmith.services.kicad_doctor import (
    format_kicad_doctor_report,
    run_kicad_doctor,
)
from pcbsmith.services.kicad_export import export_pcbs_project_to_kicad
from pcbsmith.services.kicad_plan import KiCadPlanError, run_kicad_plan
from pcbsmith.services.kicad_preview import (
    format_kicad_preview_report,
    run_kicad_preview,
)
from pcbsmith.services.kicad_project import create_kicad_project_skeleton
from pcbsmith.services.kicad_review_bundle import (
    format_kicad_review_bundle_result,
    run_kicad_review_bundle,
)
from pcbsmith.services.kicad_validate import (
    format_kicad_validation_report,
    run_kicad_validation,
)
from pcbsmith.services.project_io import (
    ProjectIOError,
    create_project,
    load_board,
    load_project,
    load_schematic,
)


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


def _cmd_kicad_status(_args: argparse.Namespace) -> int:
    install = find_kicad_cli()
    if install is None:
        print(
            "KiCad CLI not found. Install KiCad or set "
            f"{KICAD_CLI_ENV}=<path-to-kicad-cli>."
        )
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


def _cmd_ai_plan_check(args: argparse.Namespace) -> int:
    result = check_ai_plan(Path(args.planner_package), Path(args.candidate_plan))
    for line in result.lines:
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

    ai_plan_check_parser = subparsers.add_parser(
        "ai-plan-check",
        help="validate a candidate AI command plan against a planner package",
    )
    ai_plan_check_parser.add_argument("planner_package")
    ai_plan_check_parser.add_argument("candidate_plan")
    ai_plan_check_parser.set_defaults(func=_cmd_ai_plan_check)

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
