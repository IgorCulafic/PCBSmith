"""Failure-safe project file updates, with retained rollback/recovery evidence.

Single-file replacement is atomic. A multi-file edit has a durable pending
marker, so project readers refuse a partially published edit until recovery.
The journal retains both revisions; it is not a substitute for a backup.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4


class FileTransactionError(RuntimeError):
    pass


def atomic_write(path: Path, payload: bytes) -> None:
    """Write completely beside the destination before replacing it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            if handle.write(payload) != len(payload):
                raise OSError(f"Incomplete write: {path}")
            handle.flush()
            os.fsync(handle.fileno())
        # Windows readers/virus scanners can briefly deny an otherwise valid rename.
        # Retry the same fully flushed file; never delete or rewrite the destination.
        for attempt in range(4):
            try:
                os.replace(temporary, path)
                break
            except OSError as exc:
                if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 3:
                    raise
                time.sleep(0.05 * (2**attempt))
    finally:
        temporary.unlink(missing_ok=True)


def project_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or ":" in relative
        or any(part.endswith((".", " ")) for part in candidate.parts)
    ):
        raise FileTransactionError(f"Project path must be relative and confined: {relative}")
    resolved_root = root.resolve()
    target = (resolved_root / candidate).resolve()
    if target == resolved_root or not target.is_relative_to(resolved_root):
        raise FileTransactionError(f"Project path escapes project directory: {relative}")
    return target


def _edit_target(root: Path, relative: str) -> Path:
    target = project_path(root, relative)
    normalized = target.relative_to(root.resolve()).as_posix().casefold()
    if normalized.startswith(
        (".pcbsmith/file-transactions", ".pcbsmith/pending-edit", ".pcbsmith/edit.lock")
    ):
        raise FileTransactionError("Cannot edit transaction control files")
    return target


def _validate_records(root: Path, value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise FileTransactionError("Invalid recovery file records")
    seen: set[Path] = set()
    records: list[dict[str, Any]] = []
    for record in value:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise FileTransactionError("Invalid recovery file record")
        target = _edit_target(root, record["path"])
        if target in seen:
            raise FileTransactionError("Duplicate recovery target")
        seen.add(target)
        for key in ("old_sha256", "new_sha256"):
            digest = record.get(key)
            if key == "old_sha256" and key in record and digest is None:
                continue
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise FileTransactionError("Invalid recovery digest")
        records.append(record)
    return records


def require_complete_project(root: Path) -> None:
    if project_path(root, ".pcbsmith/pending-edit.json").exists():
        raise FileTransactionError(
            "Incomplete project edit; recover_project_files must complete recovery before use"
        )


@contextmanager
def _project_lock(root: Path) -> Iterator[None]:
    """An OS lock is released on process death; the lock file may remain."""
    lock_path = project_path(root, ".pcbsmith/edit.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise FileTransactionError("Another process is editing this project") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise FileTransactionError("Another process is editing this project") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _sha(payload: bytes | None) -> str | None:
    return hashlib.sha256(payload).hexdigest() if payload is not None else None


def _json_write(path: Path, value: object) -> None:
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def _restore(root: Path, directory: Path, records: list[dict[str, Any]]) -> None:
    # Validate the complete restore before modifying any target. External edits
    # after interruption must never be silently overwritten by recovery.
    restores: list[tuple[Path, bytes | None]] = []
    for index, record in enumerate(records):
        target = _edit_target(root, record["path"])
        current = target.read_bytes() if target.exists() else None
        if _sha(current) not in {record["old_sha256"], record["new_sha256"]}:
            raise FileTransactionError(f"Recovery conflicts with an external edit: {target}")
        old = (directory / f"{index}.old").read_bytes() if record["old_sha256"] else None
        if _sha(old) != record["old_sha256"]:
            raise FileTransactionError(f"Retained recovery payload is corrupt: {target}")
        restores.append((target, old))
    for target, old in reversed(restores):
        if old is None:
            target.unlink(missing_ok=True)
        else:
            atomic_write(target, old)


def commit_project_files(
    root: Path,
    payloads: Mapping[str, bytes],
    *,
    append_payloads: Mapping[str, bytes] | None = None,
    create_only: bool = False,
    expected_sha256s: Mapping[str, str | None] | None = None,
) -> str:
    """Commit an edit or roll it back; retain recoverable state if rollback fails."""
    root = root.resolve()
    with _project_lock(root):
        require_complete_project(root)
        contents = dict(payloads)
        for relative, addition in (append_payloads or {}).items():
            if relative in contents:
                raise FileTransactionError(f"Cannot replace and append the same file: {relative}")
            path = project_path(root, relative)
            contents[relative] = (path.read_bytes() if path.exists() else b"") + addition
        targets = {relative: _edit_target(root, relative) for relative in contents}
        if not targets:
            raise FileTransactionError("Project edit contains no files")
        if len(set(targets.values())) != len(targets):
            raise FileTransactionError("Duplicate project edit target")
        for target in targets.values():
            if create_only and target.exists():
                raise FileTransactionError(f"Project artifact already exists: {target}")
        for relative, expected in (expected_sha256s or {}).items():
            path = project_path(root, relative)
            if expected is None:
                changed = path.exists()
            else:
                changed = not path.is_file() or _sha(path.read_bytes()) != expected
            if changed:
                raise FileTransactionError(f"Project changed since it was loaded: {relative}")

        transaction_id = uuid4().hex
        directory = project_path(root, f".pcbsmith/file-transactions/{transaction_id}")
        directory.mkdir(parents=True)
        records: list[dict[str, Any]] = []
        for index, (relative, target) in enumerate(targets.items()):
            old = target.read_bytes() if target.exists() else None
            if old is not None:
                atomic_write(directory / f"{index}.old", old)
            atomic_write(directory / f"{index}.new", contents[relative])
            records.append(
                {"path": relative, "old_sha256": _sha(old), "new_sha256": _sha(contents[relative])}
            )
        journal = {"schema": "pcbsmith-file-edit-v1", "state": "prepared", "files": records}
        _json_write(directory / "journal.json", journal)
        pending = project_path(root, ".pcbsmith/pending-edit.json")
        _json_write(pending, {"transaction_id": transaction_id})
        try:
            for relative, target in targets.items():
                atomic_write(target, contents[relative])
            journal["state"] = "committed"
            _json_write(directory / "journal.json", journal)
            pending.unlink()
        except Exception as exc:
            journal["error"] = f"{type(exc).__name__}: {exc}"
            try:
                journal["state"] = "rolling_back"
                _json_write(directory / "journal.json", journal)
                _restore(root, directory, records)
                journal["state"] = "rolled_back"
                _json_write(directory / "journal.json", journal)
                pending.unlink()
            except Exception as recovery_error:
                raise FileTransactionError(
                    f"Edit interrupted; recovery required using {directory}: {recovery_error}"
                ) from exc
            raise FileTransactionError(f"Project edit rolled back: {exc}") from exc
        return transaction_id


def recover_project_files(root: Path) -> bool:
    """Recover an interrupted edit without replacing unrelated external changes."""
    root = root.resolve()
    with _project_lock(root):
        pending = project_path(root, ".pcbsmith/pending-edit.json")
        if not pending.exists():
            return False
        transaction_id = json.loads(pending.read_text(encoding="utf-8"))["transaction_id"]
        if not isinstance(transaction_id, str) or not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
            raise FileTransactionError("Invalid pending transaction identity")
        directory = project_path(root, f".pcbsmith/file-transactions/{transaction_id}")
        journal = json.loads((directory / "journal.json").read_text(encoding="utf-8"))
        if not isinstance(journal, dict) or journal.get("schema") != "pcbsmith-file-edit-v1":
            raise FileTransactionError("Unsupported recovery journal")
        if journal.get("state") not in {"prepared", "committed", "rolling_back", "rolled_back"}:
            raise FileTransactionError("Invalid recovery state")
        records = _validate_records(root, journal.get("files"))
        if journal["state"] == "committed":
            for record in records:
                if _sha(project_path(root, record["path"]).read_bytes()) != record["new_sha256"]:
                    raise FileTransactionError("Committed recovery files have changed")
        else:
            _restore(root, directory, records)
            journal["state"] = "rolled_back"
            _json_write(directory / "journal.json", journal)
        pending.unlink()
        return True
