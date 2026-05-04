from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE = Path("tests/fixtures/voltage_divider")


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
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
