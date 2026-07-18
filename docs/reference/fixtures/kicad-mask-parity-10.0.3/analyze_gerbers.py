"""Small reproducible parser for the KiCad solder-mask parity probe outputs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GERBERS = sorted(ROOT.glob("out-*/*.gbr"))


def normalized_bytes(path: Path) -> bytes:
    lines = []
    for line in path.read_text(encoding="ascii").splitlines():
        if "TF.CreationDate" in line or "Created by KiCad" in line or "TF.ProjectId" in line:
            continue
        lines.append(line)
    return ("\n".join(lines) + "\n").encode("ascii")


def parse(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="ascii")
    apertures = {
        match.group(1): match.group(2)
        for match in re.finditer(r"^%ADD(\d+)(.+)\*%$", text, re.MULTILINE)
    }
    flashes: list[dict[str, object]] = []
    current_aperture: str | None = None
    for line in text.splitlines():
        select = re.fullmatch(r"D(\d+)\*", line)
        if select:
            current_aperture = select.group(1)
            continue
        flash = re.fullmatch(r"X(-?\d+)Y(-?\d+)D03\*", line)
        if flash:
            flashes.append(
                {
                    "x_mm": int(flash.group(1)) / 1_000_000,
                    "y_mm": int(flash.group(2)) / 1_000_000,
                    "aperture": current_aperture,
                    "definition": apertures.get(current_aperture or ""),
                }
            )
    raw = path.read_bytes()
    normalized = normalized_bytes(path)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
        "apertures": apertures,
        "flashes": flashes,
    }


result = {
    "parser": "Gerber X/Y coordinates use FSLAX46Y46 and MOMM from each fixture.",
    "files": [parse(path) for path in GERBERS],
}
(ROOT / "measurements.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)

hash_lines = []
for path in sorted(ROOT.rglob("*")):
    if path.is_file() and path.name != "hashes.sha256":
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hash_lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}")
(ROOT / "hashes.sha256").write_text("\n".join(hash_lines) + "\n", encoding="ascii")
