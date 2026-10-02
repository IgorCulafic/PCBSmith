from pathlib import Path

import pytest

from pcbsmith.operations import file_transaction as ft


def denial(code):
    error = OSError("Windows rename denied")
    error.winerror = code
    return error


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_lock_retries_same_payload(tmp_path, monkeypatch, code):
    target = tmp_path / "ledger.json"
    target.write_bytes(b"old")
    real_replace = ft.os.replace
    calls = []
    waits = []

    def replace(source, destination):
        calls.append((source, destination))
        assert Path(source).read_bytes() == b"new"
        assert target.read_bytes() == b"old"
        if len(calls) < 3:
            raise denial(code)
        real_replace(source, destination)

    monkeypatch.setattr(ft.os, "replace", replace)
    monkeypatch.setattr(ft.time, "sleep", waits.append)
    ft.atomic_write(target, b"new")
    assert target.read_bytes() == b"new"
    assert len(set(calls)) == 1
    assert waits == [0.05, 0.1]
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("code", [5, 32, 33])
def test_persistent_windows_denial_is_bounded_and_preserves_target(tmp_path, monkeypatch, code):
    target = tmp_path / "ledger.json"
    target.write_bytes(b"old")
    calls = []
    waits = []

    def replace(source, destination):
        calls.append((source, destination))
        raise denial(code)

    monkeypatch.setattr(ft.os, "replace", replace)
    monkeypatch.setattr(ft.time, "sleep", waits.append)
    with pytest.raises(OSError):
        ft.atomic_write(target, b"new")
    assert len(calls) == 4
    assert waits == [0.05, 0.1, 0.2]
    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("code", [None, 2, 112])
def test_unrelated_error_is_not_retried(tmp_path, monkeypatch, code):
    target = tmp_path / "ledger.json"
    target.write_bytes(b"old")
    waits = []
    calls = []

    def replace(source, destination):
        calls.append(source)
        raise denial(code)

    monkeypatch.setattr(ft.os, "replace", replace)
    monkeypatch.setattr(ft.time, "sleep", waits.append)
    with pytest.raises(OSError):
        ft.atomic_write(target, b"new")
    assert len(calls) == 1
    assert waits == []
    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]
