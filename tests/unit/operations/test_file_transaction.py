from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pcbsmith.operations import file_transaction as ft
from pcbsmith.operations.project_io import ProjectIOError, create_project, load_project


def test_create_refuses_existing_and_orphaned_artifacts(tmp_path: Path) -> None:
    create_project(tmp_path, "Original")
    files = [
        tmp_path / p
        for p in ("project.pcbsmith.json", "schematics/main.sch.json", "boards/main.brd.json")
    ]
    original = {p: p.read_bytes() for p in files}
    with pytest.raises(ProjectIOError, match="already exists"):
        create_project(tmp_path, "Replacement")
    assert {p: p.read_bytes() for p in files} == original
    files[0].unlink()
    with pytest.raises(ProjectIOError, match="already exists"):
        create_project(tmp_path, "Orphan replacement")
    assert not files[0].exists()
    assert files[1].read_bytes() == original[files[1]]


def test_creation_preserves_unrelated_files(tmp_path: Path) -> None:
    note = tmp_path / "notes.txt"
    note.write_bytes(b"keep")
    create_project(tmp_path, "New")
    assert note.read_bytes() == b"keep"


def test_atomic_write_keeps_destination_on_replace_failure(tmp_path, monkeypatch) -> None:
    target = tmp_path / "saved.json"
    target.write_bytes(b"old")

    def fail_replace(source, destination):
        raise PermissionError("locked destination")

    monkeypatch.setattr(ft.os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        ft.atomic_write(target, b"new")
    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("failed_target", ["a.json", "b.json", "log.jsonl", "journal.json"])
def test_multifile_failure_restores_files_and_log(tmp_path, monkeypatch, failed_target) -> None:
    for name in ["a.json", "b.json", "log.jsonl"]:
        (tmp_path / name).write_bytes(b"old-" + name.encode())
    actual = ft.atomic_write
    fired = False

    def fail_once(path, payload):
        nonlocal fired
        is_commit = path.name == "journal.json" and b'"committed"' in payload
        is_target = path.parent == tmp_path and path.name == failed_target
        if not fired and (is_target or (failed_target == "journal.json" and is_commit)):
            fired = True
            raise OSError("injected publication failure")
        actual(path, payload)

    monkeypatch.setattr(ft, "atomic_write", fail_once)
    with pytest.raises(ft.FileTransactionError, match="rolled back"):
        ft.commit_project_files(
            tmp_path,
            {"a.json": b"new-a", "b.json": b"new-b"},
            append_payloads={"log.jsonl": b"new-event\n"},
        )
    assert fired
    for name in ["a.json", "b.json", "log.jsonl"]:
        assert (tmp_path / name).read_bytes() == b"old-" + name.encode()
    ft.require_complete_project(tmp_path)
    journals = list(tmp_path.glob(".pcbsmith/file-transactions/*/journal.json"))
    assert json.loads(journals[0].read_text())["state"] == "rolled_back"


def test_interrupted_process_blocks_reads_and_recovers(tmp_path, monkeypatch) -> None:
    create_project(tmp_path, "Original")
    a = tmp_path / "a.json"
    a.write_bytes(b"old")
    actual = ft.atomic_write

    def interrupt(path, payload):
        if path.name == "b.json":
            raise KeyboardInterrupt("simulated process interruption")
        actual(path, payload)

    with monkeypatch.context() as m:
        m.setattr(ft, "atomic_write", interrupt)
        with pytest.raises(KeyboardInterrupt):
            ft.commit_project_files(tmp_path, {"a.json": b"new", "b.json": b"created"})
    assert a.read_bytes() == b"new"
    with pytest.raises(ProjectIOError, match="Incomplete project edit"):
        load_project(tmp_path)
    assert ft.recover_project_files(tmp_path)
    assert a.read_bytes() == b"old"
    assert not (tmp_path / "b.json").exists()
    assert load_project(tmp_path).name == "Original"
    assert not ft.recover_project_files(tmp_path)


def test_recovery_refuses_external_edits(tmp_path, monkeypatch) -> None:
    (tmp_path / "a.json").write_bytes(b"old")
    actual = ft.atomic_write

    def interrupt(path, payload):
        if path.name == "b.json":
            raise KeyboardInterrupt
        actual(path, payload)

    with monkeypatch.context() as m:
        m.setattr(ft, "atomic_write", interrupt)
        with pytest.raises(KeyboardInterrupt):
            ft.commit_project_files(tmp_path, {"a.json": b"new", "b.json": b"new"})
    (tmp_path / "a.json").write_bytes(b"external change")
    with pytest.raises(ft.FileTransactionError, match="external edit"):
        ft.recover_project_files(tmp_path)
    assert (tmp_path / "a.json").read_bytes() == b"external change"


def test_conflicting_writer_and_stale_inputs_are_rejected(tmp_path) -> None:
    (tmp_path / "a.json").write_bytes(b"current")
    with ft._project_lock(tmp_path):
        with pytest.raises(ft.FileTransactionError, match="Another process"):
            ft.commit_project_files(tmp_path, {"a.json": b"wrong"})
    with pytest.raises(ft.FileTransactionError, match="changed since"):
        ft.commit_project_files(
            tmp_path,
            {"a.json": b"wrong"},
            expected_sha256s={"a.json": hashlib.sha256(b"old").hexdigest()},
        )
    assert (tmp_path / "a.json").read_bytes() == b"current"


@pytest.mark.parametrize("relative", ["../outside.json", ".pcbsmith/pending-edit.json"])
def test_transaction_refuses_escape_and_control_files(tmp_path, relative) -> None:
    with pytest.raises(ft.FileTransactionError):
        ft.commit_project_files(tmp_path, {relative: b"bad"})


def test_expected_absence_protects_concurrent_journal_creation(tmp_path):
    (tmp_path / "board").write_bytes(b"old")
    (tmp_path / "journal").write_bytes(b"concurrent")
    with pytest.raises(ft.FileTransactionError, match="changed since"):
        ft.commit_project_files(
            tmp_path, {"board": b"new", "journal": b"wrong"}, expected_sha256s={"journal": None}
        )
    assert (tmp_path / "board").read_bytes() == b"old"
    assert (tmp_path / "journal").read_bytes() == b"concurrent"
    ft.commit_project_files(
        tmp_path, {"new-journal": b"new"}, expected_sha256s={"new-journal": None}
    )
    assert (tmp_path / "new-journal").read_bytes() == b"new"
