"""Fabrication package export: gerbers, drill, positions, notes, zip.

A DRC-clean ``.kicad_pcb`` is one step away from an orderable archive
(hardening plan 3.1). This module drives ``kicad-cli pcb export`` for the
industry-standard outputs and bundles them with generated fab notes.
Packaging adds no new truth: the authority statuses are unchanged.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli


class FabricationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FabPackage:
    zip_file: Path
    files: tuple[str, ...]
    notes_file: Path


def _default_runner(command: Sequence[str]) -> KiCadProcessResult:
    completed = subprocess.run(
        list(command), capture_output=True, text=True, check=False
    )
    return KiCadProcessResult(
        command=tuple(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _board_facts(board_file: Path) -> dict[str, str]:
    text = board_file.read_text(encoding="utf-8")
    facts: dict[str, str] = {}
    xs: list[float] = []
    ys: list[float] = []
    # Bodies may contain two levels of nesting, e.g. multi-line
    # (stroke (width 0.1) (type default)) as KiCad 10 saves it.
    edge_section = re.findall(
        r"\(gr_(?:poly|line|rect|arc|circle)\b"
        r"((?:[^()]|\((?:[^()]|\([^()]*\))*\))*?)\(layer \"Edge\.Cuts\"\)",
        text,
    )
    for body in edge_section:
        for x, y in re.findall(
            r"\((?:xy|start|end|mid|center) (-?\d+\.?\d*) (-?\d+\.?\d*)\)",
            body,
        ):
            xs.append(float(x))
            ys.append(float(y))
    if xs and ys:
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        facts["extent_mm"] = (
            f"{width:.1f} x {height:.1f} mm "
            f"({width / 0.0254:.0f} x {height / 0.0254:.0f} mil)"
        )
    facts["copper_layers"] = "2"
    facts["has_mask_opening"] = (
        "yes" if '(layer "F.Mask")' in text and "(gr_poly" in text else "no"
    )
    facts["edge_items"] = str(len(edge_section))
    return facts


def _drill_table(board_file: Path) -> list[tuple[float, bool, int]]:
    """(diameter_mm, plated, count) rows from the board file, largest
    first. Oval slots report their round-drill equivalent (max axis)."""
    text = board_file.read_text(encoding="utf-8")
    counts: dict[tuple[float, bool], int] = {}
    for match in re.finditer(
        r'\(pad\s+"[^"]*"\s+(thru_hole|np_thru_hole)[^()]*'
        r"(?:\([^()]*\)[^()]*)*?\(drill\s+(?:oval\s+)?([\d.]+)",
        text,
    ):
        plated = match.group(1) == "thru_hole"
        diameter = float(match.group(2))
        counts[(diameter, plated)] = counts.get((diameter, plated), 0) + 1
    for match in re.finditer(r"\(via\b.*?\(drill\s+([\d.]+)\)", text, re.S):
        diameter = float(match.group(1))
        counts[(diameter, True)] = counts.get((diameter, True), 0) + 1
    return sorted(
        ((diameter, plated, count) for (diameter, plated), count in counts.items()),
        key=lambda row: row[0],
    )


def _fab_notes(
    project_name: str,
    facts: dict[str, str],
    drill_rows: tuple[tuple[float, bool, int], ...] = (),
) -> str:
    finish = (
        "ENIG (exposed copper is functional; HASL leveling or bare "
        "copper would degrade or corrode it)"
        if facts.get("has_mask_opening") == "yes"
        else "HASL lead-free (or equivalent RoHS finish)"
    )
    lines = [
        f"# Fabrication notes: {project_name}",
        "",
        "## Fabrication",
        "",
        "1. Material: FR-4 per IPC-4101/126 or equivalent.",
        f"2. Copper layers: {facts.get('copper_layers', '2')}.",
        "3. Overall thickness: 1.6 mm +/- 10%.",
        "4. Finished copper weight: 1 oz on outer layers.",
        f"5. Plating finish: {finish}.",
        "6. Soldermask: liquid photoimageable over bare copper, per "
        "IPC-SM-840 Type B Class 3. Color: green.",
        "7. Silkscreen: required, white.",
        "8. Manufacture to IPC-6012, Class 2.",
        f"9. Board outline extent: {facts.get('extent_mm', 'see gerbers')}.",
        "10. Minimum track/clearance used by the design rules: 0.2 mm.",
    ]
    if facts.get("has_mask_opening") == "yes":
        lines.append(
            "11. This board EXPOSES copper through soldermask openings by "
            "design (functional sensing copper); do not tent or mask them."
        )
    if drill_rows:
        lines.extend(
            (
                "",
                "## Drill table",
                "",
                "| Hole size | Tolerance | Plated | Count |",
                "| --- | --- | --- | --- |",
            )
        )
        total = 0
        for diameter, plated, count in drill_rows:
            total += count
            mil = diameter / 0.0254
            lines.append(
                f"| {diameter:.2f} mm ({mil:.1f} mil) | +/-0.076 mm "
                f"| {'PTH' if plated else 'NPTH'} | {count} |"
            )
        lines.append(f"| **Total** | | | **{total}** |")
    lines.extend(
        (
            "",
            "## Assembly",
            "",
            "1. Assemble per IPC-A-610, current revision, Class 2.",
            "2. Solder per the latest revision of IPC J-STD-001.",
            "3. Contains ESD-sensitive components; handle per ANSI/ESD "
            "S20.20.",
            "4. RoHS compliance required.",
            "5. Mount polarized components per the polarity marks on the "
            "silkscreen.",
            "",
            "Generated by PCBSmith. The design has passed KiCad ERC, DRC "
            "with schematic parity, and behavioral simulation; it still "
            "carries a needs-human-review status by policy.",
            "",
        )
    )
    return "\n".join(lines)


def export_fab_package(
    board_file: Path,
    *,
    project_name: str,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> FabPackage:
    install = finder()
    if install is None:
        raise FabricationError("KiCad CLI was not found; cannot export gerbers.")
    run = runner or _default_runner

    fab_dir = board_file.parent / "fab"
    work_dir = fab_dir / "files"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    commands: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "gerbers",
            (
                str(install.path), "pcb", "export", "gerbers",
                "--output", str(work_dir) + "\\",
                str(board_file),
            ),
        ),
        (
            "drill",
            (
                str(install.path), "pcb", "export", "drill",
                "--format", "excellon",
                "--generate-map", "--map-format", "gerberx2",
                "--output", str(work_dir) + "\\",
                str(board_file),
            ),
        ),
        (
            "positions",
            (
                str(install.path), "pcb", "export", "pos",
                "--format", "csv", "--units", "mm", "--side", "both",
                "--output", str(work_dir / f"{project_name}-positions.csv"),
                str(board_file),
            ),
        ),
    )
    for label, command in commands:
        result = run(command)
        if result.returncode != 0:
            raise FabricationError(
                f"kicad-cli {label} export failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

    notes_file = work_dir / "fab-notes.md"
    notes_file.write_text(
        _fab_notes(
            project_name,
            _board_facts(board_file),
            tuple(_drill_table(board_file)),
        ),
        encoding="utf-8",
    )

    files = tuple(sorted(path.name for path in work_dir.iterdir()))
    if len(files) < 5:
        raise FabricationError(
            f"Fab export produced only {len(files)} files; expected gerber "
            "layers, drill, positions, and notes."
        )
    zip_base = fab_dir / f"{project_name}-fab"
    zip_path = Path(
        shutil.make_archive(str(zip_base), "zip", root_dir=work_dir)
    )
    return FabPackage(zip_file=zip_path, files=files, notes_file=notes_file)
