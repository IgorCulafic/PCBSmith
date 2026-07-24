from __future__ import annotations

from pathlib import Path

from tools.clean_workspace import find_cleanup_targets


def test_find_cleanup_targets_finds_generated_directories_and_files(tmp_path: Path) -> None:
    for name in (
        ".tmp",
        ".pytest-cache-leftover",
        "pytest-task9-green",
        "phase0-upload-verify",
        ".venv.broken-20260510-015725",
        "__pycache__",
    ):
        (tmp_path / name).mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "ai-context.json").write_text("generated\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("unknown\n", encoding="utf-8")

    targets = find_cleanup_targets(tmp_path)

    assert [target.path.name for target in targets] == [
        ".pytest-cache-leftover",
        ".tmp",
        ".venv.broken-20260510-015725",
        "__pycache__",
        "ai-context.json",
        "phase0-upload-verify",
        "pytest-task9-green",
    ]


def test_find_cleanup_targets_ignores_source_and_project_state(tmp_path: Path) -> None:
    for name in ("src", "tests", "docs", ".git", ".venv", ".superpowers", ".worktrees"):
        (tmp_path / name).mkdir()

    targets = find_cleanup_targets(tmp_path)

    assert targets == []
