from __future__ import annotations

import subprocess
from pathlib import Path

from pcbsmith.kicad.cli import KiCadInstall, find_kicad_cli, run_kicad_process


def test_find_kicad_cli_uses_environment_override(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "kicad-cli.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("PCBSMITH_KICAD_CLI", str(executable))

    assert find_kicad_cli() == KiCadInstall(path=executable, source="PCBSMITH_KICAD_CLI")


def test_run_kicad_process_captures_command_output() -> None:
    def fake_runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="10.0.2\n", stderr="")

    result = run_kicad_process(
        (Path("kicad-cli.exe"), "version"),
        runner=fake_runner,
    )

    assert result.returncode == 0
    assert result.command == ("kicad-cli.exe", "version")
    assert result.stdout == "10.0.2\n"
    assert result.stderr == ""


def test_run_kicad_erc_rejects_path_traversal_report_names() -> None:
    from pathlib import Path

    import pytest

    from pcbsmith.kicad.validate import run_kicad_erc

    for bad in ("../escape.json", "sub/dir.json", "..", ""):
        with pytest.raises(ValueError, match="bare file name"):
            run_kicad_erc(Path("x.kicad_sch"), report_name=bad)
