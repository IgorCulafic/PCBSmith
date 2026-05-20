from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

from pcbsmith import cli as cli_module
from pcbsmith.circuit.models import KiCadReport, SimulationReport
from pcbsmith.cli import main

FIXTURE_MANIFEST = Path("tests/fixtures/evidence/divider_highpass_led_complete.json")


def test_authority_cli_writes_kicad_and_authority_bundle(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_erc(schematic_file: Path) -> KiCadReport:
        report_file = schematic_file.parent / ".pcbsmith" / "kicad" / "erc.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text('{"sheets":[]}', encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
        )

    def fake_spice_export(schematic_file: Path) -> KiCadReport:
        netlist_file = schematic_file.parent / ".pcbsmith" / "kicad" / "Slice.cir"
        netlist_file.parent.mkdir(parents=True, exist_ok=True)
        netlist_file.write_text("* KiCad exported netlist\n.op\n.end\n", encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
        )

    def fake_ngspice_from_netlist(netlist_file: Path, output_dir: Path) -> SimulationReport:
        assert netlist_file.name == "Slice.cir"
        output_file = output_dir / ".pcbsmith" / "simulation" / "Slice-ngspice-output.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("ngspice completed", encoding="utf-8")
        return SimulationReport(
            backend="ngspice",
            status="passed",
            raw_output_path=str(output_file),
        )

    def fail_fallback(_circuit: object, _output_dir: Path) -> SimulationReport:
        raise AssertionError("PCBSmith fallback simulation should not run")

    monkeypatch.setattr(cli_module, "run_kicad_erc", fake_erc, raising=True)
    monkeypatch.setattr(cli_module, "export_kicad_spice_netlist", fake_spice_export, raising=True)
    monkeypatch.setattr(
        cli_module,
        "run_ngspice_netlist_file",
        fake_ngspice_from_netlist,
        raising=True,
    )
    monkeypatch.setattr(cli_module, "run_ngspice_simulation", fail_fallback, raising=True)

    exit_code = main(
        [
            "design-divider-highpass-led-authority",
            str(tmp_path),
            "--name",
            "Slice",
            "--request",
            "Generate a voltage divider connected to a high-pass filter and LED indicator",
        ]
    )

    bundle_path = tmp_path / "review-bundle-v2.json"
    data = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert (tmp_path / "Slice.kicad_sch").exists()
    assert data["schema"] == "pcbsmith-circuit-review-bundle-v2"
    assert "kicad" in data
    assert "ngspice" in data
    assert "reconciliation" in data
    assert data["kicad"]["status"] == "passed"
    assert data["artifacts"]["kicad_spice_netlist"].endswith("Slice.cir")


def test_authority_cli_truthfully_marks_pcbs_fallback_when_kicad_spice_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_erc(schematic_file: Path) -> KiCadReport:
        report_file = schematic_file.parent / ".pcbsmith" / "kicad" / "erc.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text('{"sheets":[]}', encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
        )

    def fake_spice_export(schematic_file: Path) -> KiCadReport:
        netlist_file = schematic_file.parent / ".pcbsmith" / "kicad" / "Slice.cir"
        return KiCadReport(
            status="failed",
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
            findings=("KiCad SPICE export failed before writing a usable netlist.",),
        )

    def fail_kicad_netlist(_netlist_file: Path, _output_dir: Path) -> SimulationReport:
        raise AssertionError("KiCad-exported netlist simulation should not run")

    def fake_pcbs_fallback(_circuit: object, output_dir: Path) -> SimulationReport:
        output_file = (
            output_dir
            / ".pcbsmith"
            / "simulation"
            / "divider_highpass_led-ngspice-output.txt"
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("fallback ngspice completed", encoding="utf-8")
        return SimulationReport(
            backend="ngspice",
            status="passed",
            raw_output_path=str(output_file),
        )

    monkeypatch.setattr(cli_module, "run_kicad_erc", fake_erc, raising=True)
    monkeypatch.setattr(cli_module, "export_kicad_spice_netlist", fake_spice_export, raising=True)
    monkeypatch.setattr(cli_module, "run_ngspice_netlist_file", fail_kicad_netlist, raising=True)
    monkeypatch.setattr(cli_module, "run_ngspice_simulation", fake_pcbs_fallback, raising=True)

    exit_code = main(
        [
            "design-divider-highpass-led-authority",
            str(tmp_path),
            "--name",
            "Slice",
            "--request",
            "Generate a voltage divider connected to a high-pass filter and LED indicator",
        ]
    )

    data = json.loads((tmp_path / "review-bundle-v2.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert data["status"] == "failed"
    assert data["kicad"]["status"] == "failed"
    assert data["ngspice"]["status"] == "passed"
    assert data["reconciliation"]["status"] == "warning"
    assert any(
        "PCBSmith-rendered fallback netlist" in finding
        for finding in data["reconciliation"]["findings"]
    )
    assert "kicad_spice_netlist" not in data["artifacts"]
    assert {revision["revision_id"] for revision in data["revisions"]} >= {
        "evidence_missing",
        "kicad_failed",
    }


def test_authority_cli_does_not_overstate_selected_kicad_netlist_when_ngspice_unavailable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_erc(schematic_file: Path) -> KiCadReport:
        report_file = schematic_file.parent / ".pcbsmith" / "kicad" / "erc.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text('{"sheets":[]}', encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
        )

    def fake_spice_export(schematic_file: Path) -> KiCadReport:
        netlist_file = schematic_file.parent / ".pcbsmith" / "kicad" / "Slice.cir"
        netlist_file.parent.mkdir(parents=True, exist_ok=True)
        netlist_file.write_text("* KiCad exported netlist\n.op\n.end\n", encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
        )

    def fake_ngspice_unavailable(
        netlist_file: Path,
        output_dir: Path,
    ) -> SimulationReport:
        assert netlist_file.name == "Slice.cir"
        output_file = output_dir / ".pcbsmith" / "simulation" / "Slice-ngspice-output.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("", encoding="utf-8")
        return SimulationReport(
            backend="ngspice",
            status="unavailable",
            findings=("ngspice executable was not found.",),
            raw_output_path=str(output_file),
        )

    def fail_fallback(_circuit: object, _output_dir: Path) -> SimulationReport:
        raise AssertionError("PCBSmith fallback simulation should not run")

    monkeypatch.setattr(cli_module, "run_kicad_erc", fake_erc, raising=True)
    monkeypatch.setattr(cli_module, "export_kicad_spice_netlist", fake_spice_export, raising=True)
    monkeypatch.setattr(
        cli_module,
        "run_ngspice_netlist_file",
        fake_ngspice_unavailable,
        raising=True,
    )
    monkeypatch.setattr(cli_module, "run_ngspice_simulation", fail_fallback, raising=True)

    exit_code = main(
        [
            "design-divider-highpass-led-authority",
            str(tmp_path),
            "--name",
            "Slice",
            "--request",
            "Generate a voltage divider connected to a high-pass filter and LED indicator",
        ]
    )

    data = json.loads((tmp_path / "review-bundle-v2.json").read_text(encoding="utf-8"))
    reconciliation_text = " ".join(data["reconciliation"]["findings"])

    assert exit_code == 0
    assert data["status"] == "unavailable"
    assert data["kicad"]["status"] == "passed"
    assert data["ngspice"]["status"] == "unavailable"
    assert "KiCad-exported SPICE netlist was selected for ngspice" in reconciliation_text
    assert "not completed simulation evidence" in reconciliation_text
    assert "ngspice used the KiCad-exported SPICE netlist" not in reconciliation_text
    assert {revision["revision_id"] for revision in data["revisions"]} >= {
        "evidence_missing",
        "simulation_failed",
    }


def test_authority_cli_routes_simulation_warning_to_revision(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_erc(schematic_file: Path) -> KiCadReport:
        report_file = schematic_file.parent / ".pcbsmith" / "kicad" / "erc.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text('{"sheets":[]}', encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
        )

    def fake_spice_export(schematic_file: Path) -> KiCadReport:
        netlist_file = schematic_file.parent / ".pcbsmith" / "kicad" / "Slice.cir"
        netlist_file.parent.mkdir(parents=True, exist_ok=True)
        netlist_file.write_text("* KiCad exported netlist\n.op\n.end\n", encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
        )

    def fake_ngspice_warning(_netlist_file: Path, output_dir: Path) -> SimulationReport:
        output_file = output_dir / ".pcbsmith" / "simulation" / "Slice-ngspice-output.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("ngspice completed with warning", encoding="utf-8")
        return SimulationReport(
            backend="ngspice",
            status="warning",
            findings=("AC gain was outside expected tolerance.",),
            raw_output_path=str(output_file),
        )

    def fail_fallback(_circuit: object, _output_dir: Path) -> SimulationReport:
        raise AssertionError("PCBSmith fallback simulation should not run")

    monkeypatch.setattr(cli_module, "run_kicad_erc", fake_erc, raising=True)
    monkeypatch.setattr(cli_module, "export_kicad_spice_netlist", fake_spice_export, raising=True)
    monkeypatch.setattr(cli_module, "run_ngspice_netlist_file", fake_ngspice_warning, raising=True)
    monkeypatch.setattr(cli_module, "run_ngspice_simulation", fail_fallback, raising=True)

    exit_code = main(
        [
            "design-divider-highpass-led-authority",
            str(tmp_path),
            "--name",
            "Slice",
            "--request",
            "Generate a voltage divider connected to a high-pass filter and LED indicator",
        ]
    )

    data = json.loads((tmp_path / "review-bundle-v2.json").read_text(encoding="utf-8"))
    revisions = {revision["revision_id"]: revision for revision in data["revisions"]}

    assert exit_code == 0
    assert data["status"] == "needs_human_review"
    assert data["ngspice"]["status"] == "warning"
    assert "simulation_failed" in revisions
    assert revisions["simulation_failed"]["findings"] == [
        "AC gain was outside expected tolerance.",
    ]


def test_authority_cli_uses_cached_evidence_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_erc(schematic_file: Path) -> KiCadReport:
        report_file = schematic_file.parent / ".pcbsmith" / "kicad" / "erc.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text('{"sheets":[]}', encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
        )

    def fake_spice_export(schematic_file: Path) -> KiCadReport:
        netlist_file = schematic_file.parent / ".pcbsmith" / "kicad" / "Slice.cir"
        netlist_file.parent.mkdir(parents=True, exist_ok=True)
        netlist_file.write_text("* KiCad exported netlist\n.op\n.end\n", encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            spice_netlist=str(netlist_file),
        )

    def fake_ngspice_from_netlist(netlist_file: Path, output_dir: Path) -> SimulationReport:
        assert netlist_file.name == "Slice.cir"
        output_file = output_dir / ".pcbsmith" / "simulation" / "Slice-ngspice-output.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("ngspice completed", encoding="utf-8")
        return SimulationReport(
            backend="ngspice",
            status="passed",
            raw_output_path=str(output_file),
        )

    def fail_fallback(_circuit: object, _output_dir: Path) -> SimulationReport:
        raise AssertionError("PCBSmith fallback simulation should not run")

    monkeypatch.setattr(cli_module, "run_kicad_erc", fake_erc, raising=True)
    monkeypatch.setattr(cli_module, "export_kicad_spice_netlist", fake_spice_export, raising=True)
    monkeypatch.setattr(
        cli_module,
        "run_ngspice_netlist_file",
        fake_ngspice_from_netlist,
        raising=True,
    )
    monkeypatch.setattr(cli_module, "run_ngspice_simulation", fail_fallback, raising=True)

    exit_code = main(
        [
            "design-divider-highpass-led-authority",
            str(tmp_path),
            "--name",
            "Slice",
            "--request",
            "Generate a voltage divider connected to a high-pass filter and LED indicator",
            "--evidence-manifest",
            str(FIXTURE_MANIFEST),
        ]
    )

    data = json.loads((tmp_path / "review-bundle-v2.json").read_text(encoding="utf-8"))
    revisions = {revision["revision_id"] for revision in data["revisions"]}
    components = {
        component["reference"]: component for component in data["pcbs_internal"]["components"]
    }

    assert exit_code == 0
    assert data["evidence"]["status"] == "passed"
    assert data["evidence"]["cached_files"]
    assert "evidence_missing" not in revisions
    assert "math_mismatch" in revisions
    assert "reconciliation_failed" in revisions
    assert components["D1"]["value"] == "Fixture red LED"
    assert components["D1"]["support_status"] == "supported"
    assert "FIX-RED-LED-0603-D1" in components["D1"]["evidence"][0]["title"]
