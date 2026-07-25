from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.schematic_review_package import (
    ConnectedSchematicReviewManifest,
    generate_connected_schematic_review,
)


def _finder() -> KiCadInstall:
    return KiCadInstall(path=Path("fixture-kicad-cli"), source="fixture")


def _runner(
    command: Sequence[str],
    *,
    page_count: int = 3,
    erc_findings: bool = False,
) -> KiCadProcessResult:
    command = tuple(command)
    if command[1:] == ("--version",):
        return KiCadProcessResult(
            command=command,
            returncode=0,
            stdout="10.0.3\n",
            stderr="",
        )
    if command[1:4] == ("sch", "erc", "--format"):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        violations = [{"severity": "error", "description": "fixture error"}] if erc_findings else []
        output.write_text(
            json.dumps(
                {
                    "$schema": "https://schemas.kicad.org/erc.v1.json",
                    "date": "fixture-time",
                    "sheets": [{"path": "/", "violations": violations}],
                }
            ),
            encoding="utf-8",
        )
        return KiCadProcessResult(
            command=command,
            returncode=1 if erc_findings else 0,
            stdout="",
            stderr="",
        )
    if command[1:5] == ("sch", "export", "netlist", "--format"):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            (
                '<export version="E"><design><source>C:/tmp/root.kicad_sch</source>'
                "<date>fixture-time</date></design><components/><nets/></export>"
            ),
            encoding="utf-8",
        )
        return KiCadProcessResult(command=command, returncode=0, stdout="", stderr="")
    if command[1:4] == ("sch", "export", "svg"):
        output_dir = Path(command[command.index("--output") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        if "--pages" in command:
            pages = (int(command[command.index("--pages") + 1]),)
        else:
            pages = tuple(range(1, page_count + 1))
        for page in pages:
            (output_dir / f"root-{page}.svg").write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg"><text>{page}</text></svg>',
                encoding="utf-8",
            )
        return KiCadProcessResult(command=command, returncode=0, stdout="", stderr="")
    if command[1:4] == ("sch", "export", "pdf"):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        selected = command[command.index("--pages") + 1] if "--pages" in command else "all"
        output.write_bytes(f"%PDF fixture {selected}".encode())
        return KiCadProcessResult(command=command, returncode=0, stdout="", stderr="")
    raise AssertionError(f"unexpected fixture command: {command}")


def test_connected_schematic_review_exports_every_page_and_electrical_identity(
    tmp_path: Path,
) -> None:
    schematic = tmp_path / "root.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    output = tmp_path / "review"

    manifest = generate_connected_schematic_review(
        project_id="fixture-project",
        schematic_file=schematic,
        output_dir=output,
        finder=_finder,
        runner=_runner,
    )

    assert manifest.ready_for_review
    assert manifest.page_count == 3
    assert [page.page_role for page in manifest.pages] == [
        "root",
        "hierarchical_sheet",
        "hierarchical_sheet",
    ]
    assert all((output / page.svg_relative_path).is_file() for page in manifest.pages)
    assert all((output / page.pdf_relative_path).is_file() for page in manifest.pages)
    assert (
        ConnectedSchematicReviewManifest.model_validate_json(
            (output / "manifest.json").read_text(encoding="utf-8")
        )
        == manifest
    )


def test_connected_schematic_review_retains_erc_failure_without_losing_views(
    tmp_path: Path,
) -> None:
    schematic = tmp_path / "root.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    manifest = generate_connected_schematic_review(
        project_id="fixture-project",
        schematic_file=schematic,
        output_dir=tmp_path / "review",
        finder=_finder,
        runner=lambda command: _runner(
            command,
            page_count=1,
            erc_findings=True,
        ),
    )

    assert not manifest.ready_for_review
    assert manifest.erc_findings == ("error: fixture error",)
    assert manifest.page_count == 1


def test_connected_schematic_review_fails_closed_on_missing_page_output(
    tmp_path: Path,
) -> None:
    schematic = tmp_path / "root.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")

    def broken_runner(command: Sequence[str]) -> KiCadProcessResult:
        result = _runner(command, page_count=1)
        command = tuple(command)
        if command[1:4] == ("sch", "export", "svg") and "--pages" in command:
            output_dir = Path(command[command.index("--output") + 1])
            for path in output_dir.glob("*.svg"):
                path.unlink()
        return result

    with pytest.raises(ValueError, match="produced 0 files"):
        generate_connected_schematic_review(
            project_id="fixture-project",
            schematic_file=schematic,
            output_dir=tmp_path / "review",
            finder=_finder,
            runner=broken_runner,
        )
    assert not (tmp_path / "review").exists()


def test_schematic_review_package_cli_is_registered() -> None:
    from pcbsmith.cli import build_parser

    arguments = build_parser().parse_args(
        (
            "schematic-review-package",
            "design.kicad_sch",
            "review",
            "--project-id",
            "fixture-project",
        )
    )

    assert arguments.func.__name__ == "_cmd_schematic_review_package"
