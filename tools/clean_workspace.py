"""Conservative cleanup: preview content identities, then select exact cache targets.

Test workspaces, .tmp, runtimes, papers and board evidence are never inferred to
be disposable from their names. This tool does not migrate those categories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CACHE_NAMES = frozenset(
    {
        ".hypothesis",
        ".import_linter_cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    }
)
PROTECTED_SUFFIXES = frozenset(
    {
        ".kicad_pcb",
        ".kicad_sch",
        ".kicad_pro",
        ".kicad_dru",
        ".kicad_mod",
        ".gguf",
        ".safetensors",
        ".pdf",
        ".docx",
        ".csv",
        ".zip",
        ".sch",
        ".brd",
        ".py",
        ".toml",
        ".tex",
        ".png",
        ".svg",
        ".step",
        ".stp",
    }
)


@dataclass(frozen=True)
class CleanupTarget:
    path: Path
    reason: str
    root: Path
    content_sha256: str


def _require_inside(root: Path, path: Path) -> None:
    root, path = root.resolve(), path.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f"Refusing path outside or equal to repository root: {path}")


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _runtime_paths(root: Path) -> set[Path]:
    paths = {
        Path(sys.executable).resolve(),
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        root / ".venv",
    }
    config = root / ".venv" / "pyvenv.cfg"
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"home", "executable", "base-executable"}:
                paths.add(Path(value.strip()).resolve())
    return paths


def _cache_digest(root: Path, path: Path) -> str:
    _require_inside(root, path)
    if path.parent.resolve() != root.resolve() or path.name not in CACHE_NAMES:
        raise ValueError(f"Not an admitted root cache: {path}")
    if _linked(path) or not path.is_dir():
        raise ValueError(f"Cache must be an ordinary directory: {path}")
    resolved = path.resolve()
    if any(p == resolved or p.is_relative_to(resolved) for p in _runtime_paths(root)):
        raise ValueError(f"Active runtime dependency: {path}")
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", path.name], capture_output=True, check=False
        )
        if result.returncode or result.stdout.strip():
            raise ValueError(f"Cache contains tracked files or Git inspection failed: {path}")
    digest = hashlib.sha256()
    for directory, subdirs, files in os.walk(path, followlinks=False):
        subdirs.sort()
        for name in sorted([*subdirs, *files]):
            entry = Path(directory) / name
            if _linked(entry):
                raise ValueError(f"Cache contains a filesystem link: {entry}")
            _require_inside(path, entry)
            relative = entry.relative_to(path).as_posix()
            digest.update(relative.encode() + b"\0")
            if entry.is_file():
                if (
                    entry.suffix.casefold() in PROTECTED_SUFFIXES
                    or (entry.suffix.casefold() == ".md" and entry.name != "README.md")
                    or any(
                        word in entry.name.casefold()
                        for word in ("manifest", "ledger", "receipt", "pending-edit")
                    )
                ):
                    raise ValueError(f"Potential source, design or retained evidence: {entry}")
                digest.update(hashlib.sha256(entry.read_bytes()).digest())
            else:
                digest.update(b"directory")
    return digest.hexdigest()


def find_cleanup_targets(root: Path) -> list[CleanupTarget]:
    root = root.resolve()
    targets = []
    for child in sorted(root.iterdir()):
        if child.name not in CACHE_NAMES:
            continue
        try:
            digest = _cache_digest(root, child)
        except ValueError:
            continue
        targets.append(CleanupTarget(child, "rebuildable tool cache", root, digest))
    return targets


def _validate_target(target: CleanupTarget) -> None:
    if _cache_digest(target.root, target.path) != target.content_sha256:
        raise ValueError(f"Cache changed since preview; inspect it again: {target.path}")


def remove_target(target: CleanupTarget) -> None:
    _validate_target(target)
    shutil.rmtree(target.path, onerror=_retry_writable)


def archive_target(root: Path, archive_dir: Path, target: CleanupTarget) -> Path:
    if root.resolve() != target.root:
        raise ValueError("Target belongs to another repository")
    _validate_target(target)
    _require_inside(root, archive_dir)
    if archive_dir.resolve() == target.path.resolve() or archive_dir.resolve().is_relative_to(
        target.path.resolve()
    ):
        raise ValueError("Archive cannot be inside the source cache")
    # Validate every existing path component before creating or moving anything.
    for parent in (archive_dir, *archive_dir.parents):
        if _linked(parent):
            raise ValueError(f"Archive contains a filesystem link: {parent}")
        if parent.resolve() == root.resolve():
            break
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / target.path.name
    counter = 2
    while destination.exists():
        destination = archive_dir / f"{target.path.name}-{counter}"
        counter += 1
    _require_inside(root, destination)
    shutil.move(str(target.path), str(destination))
    return destination


def _retry_writable(func: Callable[[str], object], path: str, _exc_info: object) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive", type=Path)
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Exact cache name from the preview; repeat to select more.",
    )
    parser.add_argument(
        "--manifest", type=Path, help="Write the dry-run paths, roles and content digests as JSON."
    )
    args = parser.parse_args()
    if args.apply and args.archive:
        parser.error("Use either --apply or --archive, not both")
    if (args.apply or args.archive) and not args.target:
        parser.error("Inspect the dry run, then select each cache with --target")
    root = args.root.resolve()
    targets = find_cleanup_targets(root)
    available = {target.path.name: target for target in targets}
    if any(name not in available for name in args.target):
        parser.error("A selected target is protected, changed, or not an admitted cache")
    selected = [available[name] for name in dict.fromkeys(args.target)] if args.target else targets
    if args.manifest:
        args.manifest.write_text(
            json.dumps(
                {
                    "schema": "pcbsmith-cleanup-preview-v1",
                    "root": str(root),
                    "protected": [
                        ".tmp",
                        ".venv",
                        "models",
                        "old_files",
                        "papers",
                        "outputs",
                        "experiments",
                        "test workspaces",
                        "tracked files",
                        "filesystem links",
                    ],
                    "targets": [
                        {
                            "path": str(t.path),
                            "content_sha256": t.content_sha256,
                            "reason": t.reason,
                        }
                        for t in selected
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    for target in selected:
        if args.archive:
            archive = args.archive if args.archive.is_absolute() else root / args.archive
            destination = archive_target(root, archive, target)
            print(f"Archived {target.path} -> {destination}")
        elif args.apply:
            remove_target(target)
            print(f"Removed {target.path}")
        else:
            print(f"Dry run: {target.path} sha256={target.content_sha256}")
    if not selected:
        print("No admitted disposable caches found; protected material was left in place.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
