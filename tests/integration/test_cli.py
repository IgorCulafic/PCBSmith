from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURE = Path("tests/fixtures/voltage_divider")


def _write_plan(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "description": "CLI resistor plan",
                "schematic": "schematics/main.sch.json",
                "commands": [
                    {
                        "type": "place_symbol",
                        "symbol_id": "stdlib:R",
                        "value": "1k",
                        "position": {"x": 15_240_000, "y": 0},
                        "footprint_id": "stdlib:R_0603",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _run_cli(
    *args: str,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    if extra_env is not None:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pcbsmith.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_info_prints_project_summary(tmp_path: Path) -> None:
    project_dir = tmp_path / "voltage_divider"
    shutil.copytree(FIXTURE, project_dir)

    result = _run_cli("info", str(project_dir))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Name: Voltage Divider",
        "Version: 1",
        "Schematics: 1",
        "Boards: 1",
    ]


def test_netlist_prints_first_schematic_nets(tmp_path: Path) -> None:
    project_dir = tmp_path / "voltage_divider"
    shutil.copytree(FIXTURE, project_dir)

    result = _run_cli("netlist", str(project_dir))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "GND: G1.1, R2.2",
        "OUT: R1.2, R2.1",
        "VCC: R1.1, V1.1",
    ]


def test_new_creates_project_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "created"

    result = _run_cli("new", str(project_dir), "--name", "Created Board")

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"Created project 'Created Board' at {project_dir}"
    assert (project_dir / "project.pcbsmith.json").exists()
    assert (project_dir / "schematics" / "main.sch.json").exists()
    assert (project_dir / "boards" / "main.brd.json").exists()


def test_new_refuses_to_overwrite_existing_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "created"
    project_dir.mkdir()

    result = _run_cli("new", str(project_dir), "--name", "Created Board")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error:")
    assert not (project_dir / "project.pcbsmith.json").exists()
    assert not (project_dir / "schematics" / "main.sch.json").exists()
    assert not (project_dir / "boards" / "main.brd.json").exists()


def test_new_refuses_to_overwrite_existing_project_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "created"
    project_dir.mkdir()
    project_file = project_dir / "project.pcbsmith.json"
    project_file.write_text("existing project\n", encoding="utf-8")

    result = _run_cli("new", str(project_dir), "--name", "Created Board")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error:")
    assert project_file.read_text(encoding="utf-8") == "existing project\n"


def test_validate_loads_referenced_design_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "voltage_divider"
    shutil.copytree(FIXTURE, project_dir)

    result = _run_cli("validate", str(project_dir))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == "Project is valid"


def test_board_check_reports_clean_first_board(tmp_path: Path) -> None:
    project_dir = tmp_path / "voltage_divider"
    shutil.copytree(FIXTURE, project_dir)

    result = _run_cli("board-check", str(project_dir))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Board manufacturability: passed (0 findings)",
    ]


def test_board_check_reports_trace_clearance_errors(tmp_path: Path) -> None:
    project_dir = tmp_path / "voltage_divider"
    shutil.copytree(FIXTURE, project_dir)
    board_file = project_dir / "boards" / "main.brd.json"
    board_file.write_text(
        json.dumps(
            {
                "id": "main",
                "traces": [
                    {
                        "net_name": "A",
                        "layer": "F.Cu",
                        "points": [{"x": 0, "y": 0}, {"x": 10_000_000, "y": 0}],
                        "width": 400_000,
                    },
                    {
                        "net_name": "B",
                        "layer": "F.Cu",
                        "points": [{"x": 0, "y": 500_000}, {"x": 10_000_000, "y": 500_000}],
                        "width": 400_000,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli("board-check", str(project_dir))

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Board manufacturability: 1 finding(s)",
        (
            "error: trace_clearance_risk: A and B clearance is 0.100 mm; "
            "required 0.150 mm (trace 1 to trace 2 on F.Cu)"
        ),
    ]


def test_missing_project_returns_cli_error(tmp_path: Path) -> None:
    result = _run_cli("info", str(tmp_path / "missing"))

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error: Project file not found:")


def test_kicad_status_reports_explicit_cli_path() -> None:
    result = _run_cli(
        "kicad-status",
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == (
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)"
    )


def test_kicad_doctor_reports_configured_cli_without_version_check() -> None:
    result = _run_cli(
        "kicad-doctor",
        "--skip-version-check",
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "KiCad version: skipped",
        "KiCad backend configured but not version-checked",
    ]


def test_kicad_validate_can_skip_execution(tmp_path: Path) -> None:
    project_dir = tmp_path / "kicad-demo"

    create_result = _run_cli("kicad-new", str(project_dir), "--name", "LED Blinker")
    assert create_result.returncode == 0

    result = _run_cli(
        "kicad-validate",
        str(project_dir),
        "--skip-execution",
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"KiCad project: {project_dir}",
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        "ERC: skipped (LED_Blinker.kicad_sch)",
        "DRC: skipped (LED_Blinker.kicad_pcb)",
    ]


def test_kicad_preview_can_skip_execution(tmp_path: Path) -> None:
    project_dir = tmp_path / "kicad-demo"

    create_result = _run_cli("kicad-new", str(project_dir), "--name", "LED Blinker")
    assert create_result.returncode == 0

    result = _run_cli(
        "kicad-preview",
        str(project_dir),
        "--skip-execution",
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )

    assert result.returncode == 0
    assert result.stderr == ""
    schematic_preview = project_dir / ".pcbsmith" / "visual" / "LED_Blinker-schematic.svg"
    board_preview = project_dir / ".pcbsmith" / "visual" / "LED_Blinker-board.svg"
    fabrication_dir = project_dir / ".pcbsmith" / "fabrication"
    laser_preview = fabrication_dir / "LED_Blinker-fcu-laser.svg"
    assert result.stdout.splitlines() == [
        f"KiCad project: {project_dir}",
        "KiCad CLI: C:\\Tools\\KiCad\\bin\\kicad-cli.exe (PCBSMITH_KICAD_CLI)",
        f"Schematic SVG: skipped ({schematic_preview})",
        f"Board SVG: skipped ({board_preview})",
        f"Laser F.Cu SVG: skipped ({laser_preview})",
        f"Gerber package: skipped ({fabrication_dir / 'gerbers'})",
        f"Drill package: skipped ({fabrication_dir / 'drill'})",
    ]


def test_kicad_library_index_writes_read_only_library_manifest(tmp_path: Path) -> None:
    symbols_dir = tmp_path / "symbols"
    footprints_dir = tmp_path / "footprints"
    output_path = tmp_path / "kicad-library-index.json"
    footprints_library = footprints_dir / "Resistor_SMD.pretty"
    symbols_dir.mkdir()
    footprints_library.mkdir(parents=True)
    (symbols_dir / "Device.kicad_sym").write_text(
        """
(kicad_symbol_lib
\t(symbol "R")
)
""".lstrip(),
        encoding="utf-8",
    )
    (footprints_library / "R_0603_1608Metric.kicad_mod").write_text(
        "(footprint \"R_0603_1608Metric\")\n",
        encoding="utf-8",
    )

    result = _run_cli(
        "kicad-library-index",
        str(output_path),
        "--symbols-dir",
        str(symbols_dir),
        "--footprints-dir",
        str(footprints_dir),
        "--symbol-library",
        "Device",
        "--footprint-library",
        "Resistor_SMD",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"Wrote KiCad library index to {output_path}"
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["symbols"] == [{"library": "Device", "name": "R", "id": "Device:R"}]
    assert data["footprints"] == [
        {
            "library": "Resistor_SMD",
            "name": "R_0603_1608Metric",
            "id": "Resistor_SMD:R_0603_1608Metric",
        }
    ]


def test_kicad_part_resolve_checks_catalog_binding_against_index(tmp_path: Path) -> None:
    index_path = tmp_path / "kicad-library-index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-kicad-library-index-v1",
                "symbols": [{"id": "Device:R", "library": "Device", "name": "R"}],
                "footprints": [
                    {
                        "id": "Resistor_SMD:R_0603_1608Metric",
                        "library": "Resistor_SMD",
                        "name": "R_0603_1608Metric",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli("kicad-part-resolve", "pcbs:resistor_0603", str(index_path))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Catalog entry: pcbs:resistor_0603",
        "Available: yes",
        "Symbol: Device:R (found)",
        "Footprint: Resistor_SMD:R_0603_1608Metric (found)",
        "KiCad part binding available",
    ]


def test_component_knowledge_index_writes_ai_facing_catalog(tmp_path: Path) -> None:
    library_index_path = tmp_path / "kicad-library-index.json"
    output_path = tmp_path / "component-knowledge-index.json"
    library_index_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-kicad-library-index-v1",
                "symbols": [
                    {"id": "Device:R"},
                    {"id": "Device:C"},
                    {"id": "Device:LED"},
                    {"id": "Device:D"},
                    {"id": "Device:D_Zener"},
                    {"id": "Device:Fuse"},
                    {"id": "Device:L"},
                    {"id": "power:VCC"},
                    {"id": "power:GND"},
                ],
                "footprints": [
                    {"id": "Resistor_SMD:R_0603_1608Metric"},
                    {"id": "Capacitor_SMD:C_0603_1608Metric"},
                    {"id": "LED_SMD:LED_0603_1608Metric"},
                    {"id": "Diode_SMD:D_0603_1608Metric"},
                    {"id": "Inductor_SMD:L_0603_1608Metric"},
                    {"id": "Fuse:Fuse_0603_1608Metric"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli(
        "component-knowledge-index",
        str(output_path),
        "--kicad-library-index",
        str(library_index_path),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"Wrote component knowledge index to {output_path}",
        "Tier 1 entries: 19",
        "Families: 17",
        "Coverage: well_supported=9, metadata_only=10, needs_datasheet_review=0",
        "Mounting: smd=10, through-hole=7, virtual=2, unspecified=0",
    ]
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["schema"] == "pcbsmith-component-knowledge-index-v1"
    assert output["coverage_summary"]["well_supported"] == 9


def test_component_knowledge_search_finds_filtered_parts(tmp_path: Path) -> None:
    output_path = tmp_path / "component-knowledge-index.json"

    _run_cli("component-knowledge-index", str(output_path))

    result = _run_cli(
        "component-knowledge-search",
        str(output_path),
        "--query",
        "pot",
        "--mounting",
        "smd",
        "--limit",
        "2",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Component knowledge search: pot",
        "Matches: 1",
        (
            "pcbs:potentiometer_3pin_smd | Potentiometer 3-pin SMD | smd | "
            "metadata_only | tags: adjustable, potentiometer, resistor, smd, 3-pin"
        ),
    ]


def test_component_selection_returns_intent_ranked_candidates(tmp_path: Path) -> None:
    output_path = tmp_path / "component-knowledge-index.json"

    _run_cli("component-knowledge-index", str(output_path))

    result = _run_cli(
        "component-selection",
        str(output_path),
        "low-side-switch",
        "--limit",
        "1",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Component selection: low-side-switch",
        "Preferred mounting: smd",
        "Matches: 1",
        (
            "1. pcbs:nmos_sot23 | N-MOSFET SOT-23 | smd | "
            "metadata_only | needs_review"
        ),
        (
            "   reasons: Matches intent low-side-switch; Matches required tags: "
            "mosfet, nmos, switching; Uses preferred mounting: smd"
        ),
        (
            "   warnings: KiCad availability is not confirmed; resolve symbol and "
            "footprint before automated placement.; Verify Vgs(th), Rds(on), current "
            "rating, package heat, and gate drive before fabrication."
        ),
        (
            "Next checks: Confirm load current and supply voltage.; Confirm "
            "gate-drive voltage fully enhances the selected MOSFET.; Add flyback "
            "protection for inductive loads."
        ),
    ]


def test_kicad_review_bundle_writes_context_with_skip_execution(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "review-bundle"
    shutil.copytree(FIXTURE, source_project)

    result = _run_cli(
        "kicad-review-bundle",
        str(source_project),
        str(output_project),
        "--skip-execution",
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"Review bundle: {output_project}",
        f"Exported KiCad handoff: {output_project}",
        "Validation: skipped",
        "Preview: skipped",
        "Board manufacturability: passed",
        f"AI context: {output_project / 'ai-context.json'}",
    ]
    assert (output_project / "Voltage_Divider.kicad_pro").exists()
    assert (output_project / "ai-context.json").exists()
    assert (
        output_project / ".pcbsmith" / "board-reports" / "manufacturability.json"
    ).exists()


def test_kicad_new_creates_kicad_project_skeleton(tmp_path: Path) -> None:
    project_dir = tmp_path / "kicad-demo"

    result = _run_cli("kicad-new", str(project_dir), "--name", "LED Blinker")

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"Created KiCad project skeleton at {project_dir}"
    assert (project_dir / "LED_Blinker.kicad_pro").exists()
    assert (project_dir / "LED_Blinker.kicad_sch").exists()
    assert (project_dir / "LED_Blinker.kicad_pcb").exists()


def test_kicad_new_refuses_existing_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "kicad-demo"
    project_dir.mkdir()
    (project_dir / "existing.txt").write_text("existing\n", encoding="utf-8")

    result = _run_cli("kicad-new", str(project_dir), "--name", "LED Blinker")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error: Project target already exists:")


def test_kicad_export_creates_skeleton_and_handoff_manifest(tmp_path: Path) -> None:
    source_project = tmp_path / "source"
    output_project = tmp_path / "kicad-export"
    shutil.copytree(FIXTURE, source_project)

    result = _run_cli(
        "kicad-export",
        str(source_project),
        str(output_project),
        "--name",
        "Voltage Divider",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == (
        f"Exported PCBSmith project to KiCad handoff at {output_project}"
    )
    assert (output_project / "Voltage_Divider.kicad_pro").exists()
    assert (output_project / "pcbsmith_handoff.json").exists()


def test_kicad_plan_dry_run_prints_proposed_commands(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    package_path = tmp_path / "plan.json"
    create_result = _run_cli("new", str(project_dir), "--name", "Plan Demo")
    assert create_result.returncode == 0
    _write_plan(package_path)

    result = _run_cli("kicad-plan", str(project_dir), str(package_path))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Plan: CLI resistor plan",
        "Target schematic: schematics/main.sch.json",
        "1. place_symbol stdlib:R value=1k at 15.24, 0 mm",
        "Dry run only; no files changed. Pass --apply to save changes.",
    ]
    assert not (project_dir / ".pcbsmith" / "action-log.jsonl").exists()


def test_kicad_plan_apply_writes_project_and_action_log(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    package_path = tmp_path / "plan.json"
    create_result = _run_cli("new", str(project_dir), "--name", "Plan Demo")
    assert create_result.returncode == 0
    _write_plan(package_path)

    result = _run_cli("kicad-plan", str(project_dir), str(package_path), "--apply")
    schematic_text = (project_dir / "schematics" / "main.sch.json").read_text(
        encoding="utf-8"
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines()[-1] == (
        "Applied 1 commands and wrote .pcbsmith/action-log.jsonl"
    )
    assert '"reference": "R1"' in schematic_text
    assert (project_dir / ".pcbsmith" / "action-log.jsonl").exists()


def test_kicad_context_writes_ai_context_package(tmp_path: Path) -> None:
    project_dir = tmp_path / "source"
    output_path = tmp_path / "context" / "ai-context.json"
    shutil.copytree(FIXTURE, project_dir)

    result = _run_cli("kicad-context", str(project_dir), str(output_path))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"Wrote AI context package to {output_path}"
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-ai-context-v1"
    assert data["project"]["name"] == "Voltage Divider"
    assert data["schematics"][0]["symbol_count"] == 4


def test_kicad_context_can_include_kicad_project_refs(tmp_path: Path) -> None:
    project_dir = tmp_path / "source"
    kicad_dir = tmp_path / "kicad"
    output_path = tmp_path / "ai-context.json"
    shutil.copytree(FIXTURE, project_dir)
    report_dir = kicad_dir / ".pcbsmith" / "kicad-reports"
    report_dir.mkdir(parents=True)
    (report_dir / "erc.json").write_text(
        json.dumps({"sheets": [{"violations": []}]}),
        encoding="utf-8",
    )

    result = _run_cli(
        "kicad-context",
        str(project_dir),
        str(output_path),
        "--kicad-project",
        str(kicad_dir),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["kicad"]["project_dir"] == str(kicad_dir)
    assert data["kicad"]["reports"][0]["name"] == "erc"


def test_ai_brief_writes_engineering_brief_from_request_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "source"
    request_path = tmp_path / "request.txt"
    output_path = tmp_path / "brief.json"
    shutil.copytree(FIXTURE, project_dir)
    request_path.write_text("Check this LED circuit before changing it\n", encoding="utf-8")

    result = _run_cli(
        "ai-brief",
        str(project_dir),
        str(request_path),
        str(output_path),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"Wrote AI engineering brief to {output_path}"
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-ai-brief-v1"
    assert data["intent"]["next_operation_type"] == "review_only"


def test_ai_planner_package_writes_provider_neutral_package(tmp_path: Path) -> None:
    brief_path = tmp_path / "brief.json"
    output_path = tmp_path / "planner-package.json"
    brief_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-ai-brief-v1",
                "request": {"text": "Add an LED"},
                "intent": {
                    "category": "schematic_edit",
                    "next_operation_type": "schematic_edit",
                    "confidence": "medium",
                },
                "context": {
                    "project": {
                        "name": "CLI Brief",
                        "schematics": ["schematics/main.sch.json"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli("ai-planner-package", str(brief_path), str(output_path))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"Wrote AI planner package to {output_path}"
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-ai-planner-package-v1"
    assert data["allowed_command_types"] == [
        "place_symbol",
        "add_wire",
        "add_label",
        "route_segment",
        "place_text",
    ]


def test_ai_plan_check_validates_candidate_plan(tmp_path: Path) -> None:
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    planner_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-ai-planner-package-v1",
                "planner_mode": "structured_command_proposal",
                "allowed_command_types": ["place_symbol", "add_wire"],
                "target_plan_schema": {
                    "version": 1,
                    "schematic": "schematics/main.sch.json",
                    "commands": [],
                },
            }
        ),
        encoding="utf-8",
    )
    _write_plan(candidate_path)

    result = _run_cli("ai-plan-check", str(planner_path), str(candidate_path))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "AI plan: valid",
        "Target schematic: schematics/main.sch.json",
        "Commands: 1",
    ]


def test_ai_demo_plan_writes_candidate_plan(tmp_path: Path) -> None:
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    planner_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-ai-planner-package-v1",
                "planner_mode": "structured_command_proposal",
                "brief": {
                    "request": {
                        "text": "Add a resistor to the LED circuit",
                    },
                },
                "allowed_command_types": ["place_symbol", "add_wire"],
                "target_plan_schema": {
                    "version": 1,
                    "schematic": "schematics/main.sch.json",
                    "commands": [],
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli("ai-demo-plan", str(planner_path), str(candidate_path))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"Wrote AI demo candidate plan to {candidate_path}"
    data = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert data["description"] == "Demo plan: add a resistor"
    assert data["commands"][0]["symbol_id"] == "stdlib:R"


def test_ai_openai_plan_writes_candidate_plan_from_local_endpoint(tmp_path: Path) -> None:
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    planner_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-ai-planner-package-v1",
                "planner_mode": "structured_command_proposal",
                "brief": {"request": {"text": "Add a resistor"}},
                "allowed_command_types": ["place_symbol", "add_wire"],
                "target_plan_schema": {
                    "version": 1,
                    "schematic": "schematics/main.sch.json",
                    "commands": [],
                },
            }
        ),
        encoding="utf-8",
    )
    response_content = {
        "version": 1,
        "description": "Local model resistor plan",
        "schematic": "schematics/main.sch.json",
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "1k",
                "position": {"x": 0, "y": 0},
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            request_body = json.loads(self.rfile.read(length).decode("utf-8"))
            self.server.seen_request_body = request_body
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "choices": [
                            {"message": {"content": json.dumps(response_content)}}
                        ]
                    }
                ).encode("utf-8")
            )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_cli(
            "ai-openai-plan",
            str(planner_path),
            str(candidate_path),
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--model",
            "local-test",
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == (
        f"Wrote OpenAI-compatible AI candidate plan to {candidate_path}"
    )
    assert server.seen_request_body["model"] == "local-test"
    data = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert data["description"] == "Local model resistor plan"


def test_ai_openai_review_runs_request_to_approval_preview(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    request_path = tmp_path / "request.txt"
    output_dir = tmp_path / "ai-run"
    create_result = _run_cli("new", str(project_dir), "--name", "OpenAI Review Demo")
    assert create_result.returncode == 0
    request_path.write_text("Add a resistor to the circuit\n", encoding="utf-8")
    response_content = {
        "version": 1,
        "description": "Local model review resistor plan",
        "schematic": "schematics/main.sch.json",
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "1k",
                "position": {"x": 0, "y": 0},
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "choices": [
                            {"message": {"content": json.dumps(response_content)}}
                        ]
                    }
                ).encode("utf-8")
            )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_cli(
            "ai-openai-review",
            str(project_dir),
            str(request_path),
            str(output_dir),
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--model",
            "local-test",
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"AI OpenAI-compatible review bundle: {output_dir}",
        f"Brief: {output_dir / 'ai-brief.json'}",
        f"Planner package: {output_dir / 'ai-planner-package.json'}",
        f"Candidate plan: {output_dir / 'candidate-plan.json'}",
        "AI plan: valid",
        "Target schematic: schematics/main.sch.json",
        "Commands: 1",
        "Approval preview:",
        "Plan: Local model review resistor plan",
        "Target schematic: schematics/main.sch.json",
        "1. place_symbol stdlib:R value=1k at 0, 0 mm",
        "Dry run only; no files changed. Pass --apply to save changes.",
    ]
    assert (output_dir / "ai-brief.json").exists()
    assert (output_dir / "ai-planner-package.json").exists()
    assert (output_dir / "candidate-plan.json").exists()


def test_ai_plan_review_validates_and_dry_runs_candidate_plan(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    create_result = _run_cli("new", str(project_dir), "--name", "AI Review Demo")
    assert create_result.returncode == 0
    planner_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-ai-planner-package-v1",
                "planner_mode": "structured_command_proposal",
                "allowed_command_types": ["place_symbol", "add_wire"],
                "target_plan_schema": {
                    "version": 1,
                    "schematic": "schematics/main.sch.json",
                    "commands": [],
                },
            }
        ),
        encoding="utf-8",
    )
    _write_plan(candidate_path)

    result = _run_cli(
        "ai-plan-review",
        str(project_dir),
        str(planner_path),
        str(candidate_path),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "AI plan: valid",
        "Target schematic: schematics/main.sch.json",
        "Commands: 1",
        "Approval preview:",
        "Plan: CLI resistor plan",
        "Target schematic: schematics/main.sch.json",
        "1. place_symbol stdlib:R value=1k at 15.24, 0 mm",
        "Dry run only; no files changed. Pass --apply to save changes.",
    ]
    assert not (project_dir / ".pcbsmith" / "action-log.jsonl").exists()


def test_ai_proposal_bundle_stages_plan_and_exports_kicad_review(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    planner_path = tmp_path / "planner-package.json"
    candidate_path = tmp_path / "candidate-plan.json"
    output_dir = tmp_path / "proposal"
    create_result = _run_cli("new", str(project_dir), "--name", "Proposal Demo")
    assert create_result.returncode == 0
    planner_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-ai-planner-package-v1",
                "planner_mode": "structured_command_proposal",
                "allowed_command_types": ["place_symbol"],
                "target_plan_schema": {
                    "version": 1,
                    "schematic": "schematics/main.sch.json",
                    "commands": [],
                },
            }
        ),
        encoding="utf-8",
    )
    _write_plan(candidate_path)

    result = _run_cli(
        "ai-proposal-bundle",
        str(project_dir),
        str(planner_path),
        str(candidate_path),
        str(output_dir),
        "--skip-execution",
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"AI proposal bundle: {output_dir}",
        f"Staged PCBSmith project: {output_dir / 'pcbs-project'}",
        "AI plan: valid",
        "Target schematic: schematics/main.sch.json",
        "Commands: 1",
        "Applied candidate plan to staged copy only.",
        f"Review bundle: {output_dir / 'kicad-review'}",
        f"Exported KiCad handoff: {output_dir / 'kicad-review'}",
        "Validation: skipped",
        "Preview: skipped",
        "Board manufacturability: passed",
        f"AI context: {output_dir / 'kicad-review' / 'ai-context.json'}",
    ]
    original_text = (project_dir / "schematics" / "main.sch.json").read_text(
        encoding="utf-8"
    )
    staged_text = (
        output_dir / "pcbs-project" / "schematics" / "main.sch.json"
    ).read_text(encoding="utf-8")
    assert '"reference": "R1"' not in original_text
    assert '"reference": "R1"' in staged_text
    assert (output_dir / "kicad-review" / "Proposal_Demo.kicad_pro").exists()


def test_design_led_art_writes_structured_review_bundle(tmp_path: Path) -> None:
    output_dir = tmp_path / "led-art-review"

    result = _run_cli(
        "design-led-art",
        str(output_dir),
        "--name",
        "AI VIR LAB",
        "--text",
        "VIR-LAB",
        "--topology",
        "12v_dense",
        "--control",
        "low_side_mosfet",
        "--skip-execution",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Design operation: led_art",
        f"Review bundle: {output_dir}",
        f"KiCad board: {output_dir / 'AI_VIR_LAB.kicad_pcb'}",
        f"Operation summary: {output_dir / '.pcbsmith' / 'operation.json'}",
        "Validation: skipped",
        "Preview: skipped",
    ]
    assert (output_dir / "AI_VIR_LAB.kicad_pcb").exists()
    summary = json.loads(
        (output_dir / ".pcbsmith" / "operation.json").read_text(encoding="utf-8")
    )
    assert summary["request"]["control_mode"] == "low_side_mosfet"
