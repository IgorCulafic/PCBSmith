from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pcbsmith.kicad.kicad_backend import KICAD_CLI_ENV, KiCadInstall, find_kicad_cli


class KiCadPreviewProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    stdout: str
    stderr: str


class KiCadPreviewArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    input_file: Path
    output_file: Path
    status: str
    message: str | None


class KiCadPreviewReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_dir: Path
    cli_path: Path | None
    source: str | None
    ready: bool
    problem: str | None
    artifacts: tuple[KiCadPreviewArtifact, ...]
    exit_code: int


def run_kicad_preview(
    project_dir: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadPreviewProcessResult] | None = None,
    output_dir: Path | None = None,
    execute: bool = True,
) -> KiCadPreviewReport:
    install = finder()
    schematic_file = _single_project_file(project_dir, "*.kicad_sch", "schematic")
    board_file = _single_project_file(project_dir, "*.kicad_pcb", "board")
    output_dir = project_dir / ".pcbsmith" / "visual" if output_dir is None else output_dir
    artifacts = _planned_artifacts(schematic_file, board_file, output_dir)

    if install is None:
        return KiCadPreviewReport(
            project_dir=project_dir,
            cli_path=None,
            source=None,
            ready=False,
            problem=f"Install KiCad or set {KICAD_CLI_ENV}=<path-to-kicad-cli>.",
            artifacts=(),
            exit_code=1,
        )

    if not execute:
        skipped_artifacts = tuple(
            artifact.model_copy(update={"status": "skipped"}) for artifact in artifacts
        )
        return KiCadPreviewReport(
            project_dir=project_dir,
            cli_path=install.cli_path,
            source=install.source,
            ready=False,
            problem=None,
            artifacts=skipped_artifacts,
            exit_code=0,
        )

    runner = _run_kicad_process if runner is None else runner
    output_dir.mkdir(parents=True, exist_ok=True)
    completed_artifacts = tuple(
        _run_artifact_export(install.cli_path, artifact, output_dir, runner)
        for artifact in artifacts
    )
    has_error = any(artifact.status == "error" for artifact in completed_artifacts)

    return KiCadPreviewReport(
        project_dir=project_dir,
        cli_path=install.cli_path,
        source=install.source,
        ready=not has_error,
        problem=None,
        artifacts=completed_artifacts,
        exit_code=2 if has_error else 0,
    )


def format_kicad_preview_report(report: KiCadPreviewReport) -> list[str]:
    lines = [f"KiCad project: {report.project_dir}"]
    if report.cli_path is None:
        lines.append("KiCad CLI: missing")
    else:
        lines.append(f"KiCad CLI: {report.cli_path} ({report.source})")

    if report.problem is not None:
        lines.append(f"Problem: {report.problem}")
        return lines

    for artifact in report.artifacts:
        lines.append(_format_artifact(artifact))
    return lines


def _planned_artifacts(
    schematic_file: Path,
    board_file: Path,
    output_dir: Path,
) -> tuple[KiCadPreviewArtifact, ...]:
    fabrication_dir = output_dir.parent / "fabrication"
    gerber_dir = fabrication_dir / "gerbers"
    drill_dir = fabrication_dir / "drill"
    return (
        KiCadPreviewArtifact(
            kind="schematic",
            input_file=schematic_file,
            output_file=output_dir / f"{schematic_file.stem}-schematic.svg",
            status="pending",
            message=None,
        ),
        KiCadPreviewArtifact(
            kind="board",
            input_file=board_file,
            output_file=output_dir / f"{board_file.stem}-board.svg",
            status="pending",
            message=None,
        ),
        KiCadPreviewArtifact(
            kind="laser-f-cu",
            input_file=board_file,
            output_file=fabrication_dir / f"{board_file.stem}-fcu-laser.svg",
            status="pending",
            message=None,
        ),
        KiCadPreviewArtifact(
            kind="gerbers",
            input_file=board_file,
            output_file=gerber_dir,
            status="pending",
            message=None,
        ),
        KiCadPreviewArtifact(
            kind="drill",
            input_file=board_file,
            output_file=drill_dir,
            status="pending",
            message=None,
        ),
    )


def _run_artifact_export(
    cli_path: Path,
    artifact: KiCadPreviewArtifact,
    output_dir: Path,
    runner: Callable[[Sequence[str]], KiCadPreviewProcessResult],
) -> KiCadPreviewArtifact:
    if artifact.kind == "schematic":
        return _run_schematic_export(cli_path, artifact, output_dir, runner)
    if artifact.kind == "board":
        return _run_board_export(cli_path, artifact, runner, laser=False)
    if artifact.kind == "laser-f-cu":
        return _run_board_export(cli_path, artifact, runner, laser=True)
    if artifact.kind == "gerbers":
        return _run_fabrication_dir_export(
            _gerber_command(cli_path, artifact.input_file, artifact.output_file),
            artifact,
            runner,
            missing_message="no Gerber files produced",
        )
    if artifact.kind == "drill":
        return _run_fabrication_dir_export(
            _drill_command(cli_path, artifact.input_file, artifact.output_file),
            artifact,
            runner,
            missing_message="no drill files produced",
        )
    raise ValueError(f"Unsupported KiCad preview artifact: {artifact.kind}")


def _run_schematic_export(
    cli_path: Path,
    artifact: KiCadPreviewArtifact,
    output_dir: Path,
    runner: Callable[[Sequence[str]], KiCadPreviewProcessResult],
) -> KiCadPreviewArtifact:
    work_dir = output_dir / ".work" / "schematic"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    process_result = runner(_schematic_command(cli_path, artifact.input_file, work_dir))
    if process_result.returncode != 0:
        return artifact.model_copy(
            update={"status": "error", "message": _process_message(process_result)}
        )

    generated_svgs = sorted(work_dir.glob("*.svg"))
    if not generated_svgs:
        return artifact.model_copy(
            update={"status": "error", "message": "no schematic SVG produced"}
        )

    shutil.copyfile(generated_svgs[0], artifact.output_file)
    return artifact.model_copy(update={"status": "exported"})


def _run_board_export(
    cli_path: Path,
    artifact: KiCadPreviewArtifact,
    runner: Callable[[Sequence[str]], KiCadPreviewProcessResult],
    *,
    laser: bool,
) -> KiCadPreviewArtifact:
    artifact.output_file.parent.mkdir(parents=True, exist_ok=True)
    process_result = runner(
        _laser_f_cu_command(cli_path, artifact.input_file, artifact.output_file)
        if laser
        else _board_command(cli_path, artifact.input_file, artifact.output_file)
    )
    if process_result.returncode != 0:
        return artifact.model_copy(
            update={"status": "error", "message": _process_message(process_result)}
        )
    if not artifact.output_file.exists():
        return artifact.model_copy(
            update={"status": "error", "message": "no board SVG produced"}
        )
    return artifact.model_copy(update={"status": "exported"})


def _run_fabrication_dir_export(
    command: Sequence[str],
    artifact: KiCadPreviewArtifact,
    runner: Callable[[Sequence[str]], KiCadPreviewProcessResult],
    *,
    missing_message: str,
) -> KiCadPreviewArtifact:
    if artifact.output_file.exists():
        shutil.rmtree(artifact.output_file)
    artifact.output_file.mkdir(parents=True, exist_ok=True)
    process_result = runner(command)
    if process_result.returncode != 0:
        return artifact.model_copy(
            update={"status": "error", "message": _process_message(process_result)}
        )
    if not any(artifact.output_file.iterdir()):
        return artifact.model_copy(
            update={"status": "error", "message": missing_message}
        )
    return artifact.model_copy(update={"status": "exported"})


def _schematic_command(cli_path: Path, input_file: Path, output_dir: Path) -> list[str]:
    return [
        str(cli_path),
        "sch",
        "export",
        "svg",
        "--output",
        str(output_dir),
        "--exclude-drawing-sheet",
        "--no-background-color",
        str(input_file),
    ]


def _board_command(cli_path: Path, input_file: Path, output_file: Path) -> list[str]:
    return [
        str(cli_path),
        "pcb",
        "export",
        "svg",
        "--output",
        str(output_file),
        "--layers",
        "F.Cu,F.SilkS,Edge.Cuts",
        "--page-size-mode",
        "2",
        "--fit-page-to-board",
        "--exclude-drawing-sheet",
        "--mode-single",
        str(input_file),
    ]


def _laser_f_cu_command(cli_path: Path, input_file: Path, output_file: Path) -> list[str]:
    return [
        str(cli_path),
        "pcb",
        "export",
        "svg",
        "--output",
        str(output_file),
        "--layers",
        "F.Cu",
        "--page-size-mode",
        "2",
        "--fit-page-to-board",
        "--exclude-drawing-sheet",
        "--black-and-white",
        "--drill-shape-opt",
        "0",
        "--mode-single",
        str(input_file),
    ]


def _gerber_command(cli_path: Path, input_file: Path, output_dir: Path) -> list[str]:
    return [
        str(cli_path),
        "pcb",
        "export",
        "gerbers",
        "--output",
        str(output_dir),
        "--layers",
        "F.Cu,F.Mask,F.SilkS,Edge.Cuts",
        "--subtract-soldermask",
        "--precision",
        "6",
        str(input_file),
    ]


def _drill_command(cli_path: Path, input_file: Path, output_dir: Path) -> list[str]:
    return [
        str(cli_path),
        "pcb",
        "export",
        "drill",
        "--output",
        str(output_dir),
        "--format",
        "excellon",
        "--excellon-units",
        "mm",
        "--generate-map",
        "--map-format",
        "svg",
        "--generate-report",
        "--report-path",
        str(output_dir / "drill-report.txt"),
        str(input_file),
    ]


def _format_artifact(artifact: KiCadPreviewArtifact) -> str:
    labels = {
        "schematic": "Schematic SVG",
        "board": "Board SVG",
        "laser-f-cu": "Laser F.Cu SVG",
        "gerbers": "Gerber package",
        "drill": "Drill package",
    }
    label = labels.get(artifact.kind, artifact.kind)
    if artifact.status == "error":
        return f"{label}: error ({artifact.message})"
    return f"{label}: {artifact.status} ({artifact.output_file})"


def _run_kicad_process(command: Sequence[str]) -> KiCadPreviewProcessResult:
    completed = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )
    return KiCadPreviewProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _process_message(result: KiCadPreviewProcessResult) -> str:
    return result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"


def _single_project_file(project_dir: Path, pattern: str, label: str) -> Path:
    matches = sorted(project_dir.glob(pattern))
    if not matches:
        raise ValueError(f"KiCad {label} file not found in {project_dir}")
    if len(matches) > 1:
        raise ValueError(f"Multiple KiCad {label} files found in {project_dir}")
    return matches[0]


__all__ = [
    "KiCadPreviewArtifact",
    "KiCadPreviewProcessResult",
    "KiCadPreviewReport",
    "format_kicad_preview_report",
    "run_kicad_preview",
]
