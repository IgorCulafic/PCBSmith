import json
import subprocess

import pytest

from pcbsmith.kicad.cli import KiCadInstall
from pcbsmith.kicad.native_format import upgrade_generated_native_file


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    monkeypatch.setattr(
        "pcbsmith.kicad.native_format.find_kicad_cli",
        lambda: KiCadInstall(path=tmp_path / "kicad-cli", source="fixture"),
    )
    return tmp_path


@pytest.mark.parametrize("kind,old,new", [("pcb", 20241229, 20260206), ("sch", 20250114, 20260101)])
def test_native_conversion_keeps_generator_input_and_records_actual_output(
    native, monkeypatch, kind, old, new
):
    path = native / ("board.kicad_" + kind)
    payload = f'(kicad_{kind} (version {old}) (generator "pcbsmith"))'
    path.write_text(payload)
    receipt = native / "format.json"

    def run(command, **kwargs):
        assert path.read_text() == payload  # No version stamping before native migration.
        assert command[1:] == [kind, "upgrade", str(path.resolve())]
        assert kwargs["timeout"] == 60
        path.write_text(f'(kicad_{kind} (version {new}) (generator "native-fixture"))')
        return subprocess.CompletedProcess(command, 0, "converted", "")

    monkeypatch.setattr("pcbsmith.kicad.native_format.subprocess.run", run)
    upgrade_generated_native_file(path, receipt)
    data = json.loads(receipt.read_text())
    assert data["before_version"] == old and data["after_version"] == new
    assert data["before_sha256"] != data["after_sha256"]
    assert data["status"] == "passed"


@pytest.mark.parametrize("failure", ["exit", "timeout", "downgrade"])
def test_failed_conversion_cannot_be_reported_as_finished(native, monkeypatch, failure):
    path = native / "b.kicad_pcb"
    path.write_text("(kicad_pcb (version 20260206))")

    def run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 60)
        if failure == "downgrade":
            path.write_text("(kicad_pcb (version 20241229))")
        return subprocess.CompletedProcess(command, 1 if failure == "exit" else 0, "", "fixture")

    monkeypatch.setattr("pcbsmith.kicad.native_format.subprocess.run", run)
    receipt = native / "format.json"
    with pytest.raises((RuntimeError, ValueError, subprocess.TimeoutExpired)):
        upgrade_generated_native_file(path, receipt)
    assert json.loads(receipt.read_text())["status"] == "failed"
