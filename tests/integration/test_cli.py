from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
