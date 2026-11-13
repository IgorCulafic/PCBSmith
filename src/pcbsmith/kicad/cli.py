from __future__ import annotations

import math
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

KICAD_CLI_ENV = "PCBSMITH_KICAD_CLI"
WINDOWS_KICAD_CLI = Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")


class KiCadInstall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: Path
    source: str


class KiCadProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def find_kicad_cli() -> KiCadInstall | None:
    env_path = os.environ.get(KICAD_CLI_ENV)
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return KiCadInstall(path=candidate, source=KICAD_CLI_ENV)

    path_candidate = shutil.which("kicad-cli")
    if path_candidate:
        return KiCadInstall(path=Path(path_candidate), source="PATH")

    if WINDOWS_KICAD_CLI.exists():
        return KiCadInstall(path=WINDOWS_KICAD_CLI, source="known_windows_path")

    return None


def run_kicad_process(
    command: Sequence[str | Path],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: float = 180,
) -> KiCadProcessResult:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("KiCad execution requires a positive finite timeout")
    command_text = tuple(str(part) for part in command)
    completed = runner(
        list(command_text),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    return KiCadProcessResult(
        command=command_text,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
