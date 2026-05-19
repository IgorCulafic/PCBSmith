from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.models import (
    AuthorityStatus,
    EvidenceReport,
    KiCadReport,
    ReconciliationReport,
    RevisionRecord,
    SimulationReport,
)
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.core.netops import derive_netlist
from pcbsmith.core.schematic import Schematic
from pcbsmith.generation.divider_highpass_led import (
    compose_divider_highpass_led,
    write_divider_highpass_led_project,
)
from pcbsmith.kicad.export_divider_highpass_led import export_divider_highpass_led_to_kicad
from pcbsmith.kicad.spice import export_kicad_spice_netlist
from pcbsmith.kicad.validate import run_kicad_erc
from pcbsmith.review.authority_bundle import write_authority_review_bundle
from pcbsmith.review.circuit_bundle import write_circuit_review_bundle
from pcbsmith.revision import revision_for_authority_failure
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


def _cmd_design_divider_highpass_led(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
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
    intent = classify_circuit_intent(args.request)
    if intent.status != "supported":
        raise ValueError("; ".join(intent.unsupported_reasons))
    topology = select_topology(intent)
    circuit = compose_divider_highpass_led(intent, topology)

    write_divider_highpass_led_project(circuit, output_dir, project_name=args.name)
    kicad_artifacts = export_divider_highpass_led_to_kicad(
        circuit,
        output_dir,
        project_name=args.name,
    )
    schematic_file = Path(kicad_artifacts["schematic_file"])

    erc_report = run_kicad_erc(schematic_file)
    spice_report = export_kicad_spice_netlist(schematic_file)
    used_kicad_spice = spice_report.status == "passed" and spice_report.spice_netlist
    if used_kicad_spice:
        simulation = run_ngspice_netlist_file(Path(spice_report.spice_netlist), output_dir)
    else:
        simulation = run_ngspice_simulation(circuit, output_dir)

    kicad = _combine_kicad_reports(erc_report, spice_report)
    evidence = EvidenceReport(
        status="needs_human_review",
        findings=(GENERIC_EVIDENCE_FINDING,),
    )
    reconciliation = _reconcile_authorities(
        kicad=kicad,
        simulation=simulation,
        used_kicad_spice=bool(used_kicad_spice),
    )
    artifacts = _authority_artifacts(
        output_dir=output_dir,
        kicad_artifacts=kicad_artifacts,
        erc_report=erc_report,
        spice_report=spice_report,
        simulation=simulation,
    )
    revisions = _authority_revisions(
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
    )

    bundle_path = write_authority_review_bundle(
        circuit,
        output_dir,
        evidence=evidence,
        kicad=kicad,
        simulation=simulation,
        reconciliation=reconciliation,
        revisions=revisions,
        artifacts=artifacts,
    )
    status = json.loads(bundle_path.read_text(encoding="utf-8"))["status"]
    print(f"Review bundle: {bundle_path}")
    print(f"Status: {status}")
    return 0


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
    used_kicad_spice: bool,
) -> ReconciliationReport:
    checks = (
        "PCBSmith circuit object and KiCad schematic were generated before authority checks.",
        "KiCad ERC and KiCad SPICE export statuses were recorded separately.",
        (
            "ngspice was run from the KiCad-exported SPICE netlist."
            if used_kicad_spice
            else "ngspice was run from a PCBSmith-rendered fallback netlist."
        ),
    )
    findings = [
        (
            "ngspice used the KiCad-exported SPICE netlist."
            if used_kicad_spice
            else (
                "KiCad SPICE export did not pass, so ngspice used a "
                "PCBSmith-rendered fallback netlist; this is not KiCad-exported "
                "SPICE evidence."
            )
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


def _authority_revisions(
    *,
    evidence: EvidenceReport,
    kicad: KiCadReport,
    simulation: SimulationReport,
) -> tuple[RevisionRecord, ...]:
    revisions = [
        revision_for_authority_failure(
            revision_id="evidence_missing",
            parent_revision_id=None,
            failure_code="evidence_missing",
            findings=evidence.findings,
        )
    ]
    parent_revision_id = revisions[-1].revision_id
    if kicad.status in {"failed", "unavailable", "not_run"}:
        revisions.append(
            revision_for_authority_failure(
                revision_id="kicad_failed",
                parent_revision_id=parent_revision_id,
                failure_code="kicad_failed",
                findings=kicad.findings or (f"KiCad authority status is {kicad.status}.",),
            )
        )
        parent_revision_id = revisions[-1].revision_id
    if simulation.status in {"failed", "unavailable", "not_run"}:
        revisions.append(
            revision_for_authority_failure(
                revision_id="simulation_failed",
                parent_revision_id=parent_revision_id,
                failure_code="simulation_failed",
                findings=simulation.findings
                or (f"ngspice authority status is {simulation.status}.",),
            )
        )
    return tuple(revisions)


def _authority_artifacts(
    *,
    output_dir: Path,
    kicad_artifacts: dict[str, str],
    erc_report: KiCadReport,
    spice_report: KiCadReport,
    simulation: SimulationReport,
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
    return artifacts


def _add_existing_artifact(
    artifacts: dict[str, str],
    name: str,
    candidate: str | None,
) -> None:
    if candidate is not None and Path(candidate).exists():
        artifacts[name] = candidate


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
    design_parser.set_defaults(func=_cmd_design_divider_highpass_led)

    authority_design_parser = subparsers.add_parser(
        "design-divider-highpass-led-authority",
        help="generate the circuit-intelligence slice with separated authority evidence",
    )
    authority_design_parser.add_argument("output")
    authority_design_parser.add_argument("--request", required=True)
    authority_design_parser.add_argument("--name", required=True)
    authority_design_parser.set_defaults(func=_cmd_design_divider_highpass_led_authority)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command: Callable[[argparse.Namespace], int] = args.func
        return command(args)
    except (ProjectIOError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
