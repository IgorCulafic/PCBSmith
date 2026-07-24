from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

KICAD_CLI_ENV = "PCBSMITH_KICAD_CLI"


class KiCadInstall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cli_path: Path
    source: str


def default_kicad_cli_candidates() -> tuple[Path, ...]:
    return (
        Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"),
        Path("C:/Program Files/KiCad/9.0/bin/kicad-cli.exe"),
        Path("C:/Program Files/KiCad/8.0/bin/kicad-cli.exe"),
        Path("C:/Program Files/KiCad/bin/kicad-cli.exe"),
        Path("C:/Program Files (x86)/KiCad/10.0/bin/kicad-cli.exe"),
        Path("C:/Program Files (x86)/KiCad/9.0/bin/kicad-cli.exe"),
        Path("C:/Program Files (x86)/KiCad/8.0/bin/kicad-cli.exe"),
        Path("C:/Program Files (x86)/KiCad/bin/kicad-cli.exe"),
    )


def find_kicad_cli(
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    candidate_paths: Sequence[Path] | None = None,
    exists: Callable[[Path], bool] = Path.exists,
) -> KiCadInstall | None:
    env = os.environ if env is None else env
    explicit_path = env.get(KICAD_CLI_ENV, "").strip()
    if explicit_path:
        return KiCadInstall(cli_path=Path(explicit_path), source=KICAD_CLI_ENV)

    path_match = which("kicad-cli")
    if path_match:
        return KiCadInstall(cli_path=Path(path_match), source="PATH")

    for candidate in candidate_paths or default_kicad_cli_candidates():
        if exists(candidate):
            return KiCadInstall(cli_path=candidate, source="known install path")

    return None


__all__ = [
    "KICAD_CLI_ENV",
    "KiCadInstall",
    "default_kicad_cli_candidates",
    "find_kicad_cli",
]
