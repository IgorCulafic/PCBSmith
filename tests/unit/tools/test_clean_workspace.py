from __future__ import annotations

from pathlib import Path

import pytest
from tools.clean_workspace import archive_target, find_cleanup_targets, remove_target


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

    assert [target.path.name for target in targets] == ["__pycache__"]


def test_find_cleanup_targets_ignores_source_and_project_state(tmp_path: Path) -> None:
    for name in ("src", "tests", "docs", ".git", ".venv", ".superpowers", ".worktrees"):
        (tmp_path / name).mkdir()

    targets = find_cleanup_targets(tmp_path)

    assert targets == []


def test_cleanup_refuses_design_evidence_even_inside_cache(tmp_path):
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "accepted.kicad_pcb").write_text("retained board")
    assert find_cleanup_targets(tmp_path) == []


def test_cleanup_revalidates_contents_and_archive_confinement(tmp_path):
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    payload = cache / "nodeids"
    payload.write_text("[]")
    (target,) = find_cleanup_targets(tmp_path)
    payload.write_text("changed")
    with pytest.raises(ValueError, match="changed since"):
        remove_target(target)
    (target,) = find_cleanup_targets(tmp_path)
    outside = tmp_path.parent / "must-not-create-cleanup-archive"
    with pytest.raises(ValueError, match="outside"):
        archive_target(tmp_path, outside, target)
    assert not outside.exists()
    with pytest.raises(ValueError, match="inside the source"):
        archive_target(tmp_path, cache / "nested", target)
    destination = archive_target(tmp_path, tmp_path / ".cleanup-archive", target)
    assert (destination / "nodeids").read_text() == "changed"
    assert not cache.exists()


def test_cleanup_protects_interpreter_base_from_venv_config(tmp_path):
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text(f"home = {cache}\n")
    assert find_cleanup_targets(tmp_path) == []


def test_cleanup_removes_only_unchanged_admitted_cache(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "test.pyc").write_bytes(b"compiled cache")
    (target,) = find_cleanup_targets(tmp_path)
    remove_target(target)
    assert not cache.exists()
