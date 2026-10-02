from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.kicad.check_reports import drc_sections, erc_violations
from pcbsmith.kicad.kicad_backend import KiCadInstall
from pcbsmith.kicad.kicad_validate import KiCadProcessResult, run_kicad_validation
from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        {"violations": []},
        {"violations": [], "unconnected_items": [], "schematic_parity": None},
        {"violations": [None], "unconnected_items": [], "schematic_parity": []},
    ],
)
def test_incomplete_or_malformed_drc_cannot_be_clean(tmp_path, data):
    report = tmp_path / "drc.json"
    report.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        inspect_kicad_drc_report(report)


@pytest.mark.parametrize(
    "data", [{}, [], {"sheets": []}, {"sheets": [{}]}, {"sheets": [{"violations": [None]}]}]
)
def test_incomplete_or_malformed_erc_is_rejected(data):
    with pytest.raises(ValueError):
        erc_violations(data)


def test_structurally_complete_zero_finding_reports_are_counted():
    assert not any(
        drc_sections({"violations": [], "unconnected_items": [], "schematic_parity": []}).values()
    )
    assert erc_violations({"sheets": [{"violations": []}]}) == []


@pytest.mark.parametrize("mode", ["empty", "wrong_source", "parity", "stale", "mutation"])
def test_native_validation_refuses_false_success(tmp_path, mode):
    for suffix in ("kicad_pcb", "kicad_sch"):
        (tmp_path / f"Demo.{suffix}").write_text("native fixture")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    old = b'{"old": "retained evidence"}'
    (report_dir / "drc.json").write_bytes(old)

    def runner(command):
        path = Path(command[command.index("--output") + 1])
        kind = command[2]
        data = {
            "$schema": f"https://schemas.kicad.org/{kind}.v1.json",
            "source": Path(command[-1]).name,
            "kicad_version": "10.0.3",
        }
        if kind == "erc":
            data["sheets"] = [{"violations": []}]
        else:
            data.update(violations=[], unconnected_items=[], schematic_parity=[])
        if mode == "empty":
            data = {}
        if mode == "wrong_source":
            data["source"] = "Unrelated.kicad_pcb"
        if mode == "parity" and kind == "drc":
            data["schematic_parity"] = [{"type": "mismatch"}]
        if mode == "mutation":
            Path(command[-1]).write_text("changed")
        if mode != "stale":
            path.write_text(json.dumps(data))
        return KiCadProcessResult(returncode=0, stdout="process output", stderr="diagnostic")

    result = run_kicad_validation(
        tmp_path,
        finder=lambda: KiCadInstall(cli_path=Path("kicad-cli"), source="fixture"),
        runner=runner,
        report_dir=report_dir,
    )
    assert not result.ready and result.exit_code != 0
    assert next(report_dir.glob("history/*/drc.json")).read_bytes() == old
    assert json.loads((report_dir / "drc.process.json").read_text())["stderr"] == "diagnostic"
