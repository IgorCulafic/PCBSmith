"""Inspect every software archive entry before any release; never publish it."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

SDIST_ROOT_FILES = frozenset(
    {
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "uv.lock",
        "PKG-INFO",
        ".gitignore",
        "THIRD_PARTY_NOTICES.md",
    }
)
REQUIRED_MODULES = frozenset({"__init__.py", "cli.py", "ui/app.py"})


def inspect_distribution(path: Path) -> dict[str, object]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
        wheel = True
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if any(not (m.isfile() or m.isdir()) for m in members):
                raise ValueError("Source archive contains links or special files")
            names = [member.name for member in members if member.isfile()]
        wheel = False
    else:
        raise ValueError(f"Unsupported software archive: {path}")
    modules = set()
    for name in names:
        entry = PurePosixPath(name)
        if entry.is_absolute() or ".." in entry.parts or "\\" in name:
            raise ValueError(f"Unsafe archive entry: {name}")
        parts = entry.parts
        if not wheel:
            if not parts or not parts[0].startswith("pcbsmith-"):
                raise ValueError(f"Unexpected source root: {name}")
            parts = parts[1:]
        if wheel and parts and parts[0].endswith(".dist-info"):
            continue
        if not wheel and parts[:2] in {
            ("ai_assets", "kicad_footprints"),
            ("ai_assets", "kicad_symbols"),
        }:
            if entry.suffix not in {".kicad_mod", ".kicad_sym", ".md"}:
                raise ValueError(f"Unapproved runtime asset: {name}")
            continue
        prefix = ("pcbsmith",) if wheel else ("src", "pcbsmith")
        if parts[: len(prefix)] == prefix:
            relative = PurePosixPath(*parts[len(prefix) :]).as_posix()
            if "__pycache__" in parts or entry.suffix in {".pyc", ".pyo"}:
                raise ValueError(f"Compiled cache in distribution: {name}")
            modules.add(relative)
        elif wheel or len(parts) != 1 or parts[0] not in SDIST_ROOT_FILES:
            raise ValueError(f"Unapproved distribution entry: {name}")
    if not REQUIRED_MODULES.issubset(modules):
        raise ValueError("Software archive omits required entry points")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "entry_count": len(names),
        "package_files": len(modules),
        "approved": True,
        "entries": sorted(names),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {
        "schema": "pcbsmith-software-distribution-check-v1",
        "archives": [inspect_distribution(path) for path in args.archives],
    }
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for archive in result["archives"]:
        print(f"Approved contents: {archive['path']} ({archive['entry_count']} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
