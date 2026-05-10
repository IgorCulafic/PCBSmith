from __future__ import annotations

import argparse
import os
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT_ONLY_NAMES = {
    ".codex-tmp",
    ".hypothesis",
    ".import_linter_cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    "__pycache__",
    "ai-context.json",
}
ROOT_ONLY_PREFIXES = (
    ".pytest-",
    ".venv.broken-",
    "phase0-",
    "pytest-",
)
NEVER_CLEAN = {
    ".cleanup-archive",
    ".git",
    ".superpowers",
    ".venv",
    ".worktrees",
    "docs",
    "src",
    "tests",
    "uv.lock",
}


@dataclass(frozen=True)
class CleanupTarget:
    path: Path
    reason: str


def find_cleanup_targets(root: Path) -> list[CleanupTarget]:
    root = root.resolve()
    targets: list[CleanupTarget] = []

    for child in root.iterdir():
        name = child.name
        if name in NEVER_CLEAN:
            continue
        if name in ROOT_ONLY_NAMES:
            targets.append(CleanupTarget(child, "generated cache or output"))
            continue
        if any(name.startswith(prefix) for prefix in ROOT_ONLY_PREFIXES):
            targets.append(CleanupTarget(child, "old generated test workspace"))

    return sorted(targets, key=lambda target: target.path.name)


def remove_target(target: CleanupTarget) -> None:
    if target.path.is_dir():
        shutil.rmtree(target.path, onerror=_retry_writable)
    else:
        target.path.unlink()


def archive_target(root: Path, archive_dir: Path, target: CleanupTarget) -> Path:
    archive_dir = archive_dir.resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)
    _require_inside(root, archive_dir)

    destination = archive_dir / target.path.name
    counter = 2
    while destination.exists():
        destination = archive_dir / f"{target.path.name}-{counter}"
        counter += 1

    shutil.move(str(target.path), str(destination))
    return destination


def _require_inside(root: Path, path: Path) -> None:
    root = root.resolve()
    path = path.resolve()
    if path != root and not path.is_relative_to(root):
        raise ValueError(f"Refusing to use a path outside the repository: {path}")


def _retry_writable(
    func: Callable[[str], object], path: str, _exc_info: object
) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List or clean generated PCBSmith workspace files."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root to inspect.")
    parser.add_argument("--apply", action="store_true", help="Delete generated cleanup targets.")
    parser.add_argument(
        "--archive",
        type=Path,
        help=(
            "Move generated cleanup targets into this repository-local folder "
            "instead of deleting."
        ),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    _require_inside(root, root)

    if args.apply and args.archive:
        parser.error("Use either --apply or --archive, not both.")

    targets = find_cleanup_targets(root)
    if not targets:
        print("No generated cleanup targets found.")
        return 0

    if args.archive:
        archive_dir = args.archive
        if not archive_dir.is_absolute():
            archive_dir = root / archive_dir
        _require_inside(root, archive_dir)
        for target in targets:
            archived = archive_target(root, archive_dir, target)
            print(f"Archived {target.path.relative_to(root)} -> {archived.relative_to(root)}")
        return 0

    if args.apply:
        for target in targets:
            remove_target(target)
            print(f"Removed {target.path.relative_to(root)}")
        return 0

    print("Dry run: generated cleanup targets that can be removed or archived:")
    for target in targets:
        print(f"- {target.path.relative_to(root)} ({target.reason})")
    print("\nRun with --apply to delete these, or --archive .cleanup-archive to move them aside.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
