from __future__ import annotations

from pathlib import Path

import pytest

import pcbsmith.kicad.reader_netlist_live as live
from pcbsmith.circuit.models import KiCadReport
from pcbsmith.kicad.aggregate_exact_checker import (
    AggregateSubcheckKind,
    AggregateSubcheckRequirement,
    StableAggregateExactCheckerPolicy,
)
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNetlist
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def test_owned_role_cleanup_is_confined_and_removes_only_managed_content(
    tmp_path: Path,
) -> None:
    role_dir = live._clean_owned_role_dir(tmp_path, "machine")
    marker = role_dir / "stale.txt"
    marker.write_text("stale", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve", encoding="utf-8")

    repeated = live._clean_owned_role_dir(tmp_path, "machine")

    assert repeated == role_dir
    assert not marker.exists()
    assert outside.read_text(encoding="utf-8") == "preserve"
    with pytest.raises(ValueError, match="escaped"):
        live._clean_owned_role_dir(tmp_path, "../outside")


def test_owned_role_cleanup_refuses_managed_reparse_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managed = tmp_path / ".pcbsmith-reader-netlist-live"
    managed.mkdir()
    monkeypatch.setattr(live, "_is_reparse_point", lambda path: path == managed)

    with pytest.raises(ValueError, match="reparse point"):
        live._clean_owned_role_dir(tmp_path, "machine")


def test_owned_cleanup_unlinks_nested_reparse_without_descending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    role_dir = live._clean_owned_role_dir(tmp_path, "machine")
    nested = role_dir / "nested-link"
    nested.mkdir()
    monkeypatch.setattr(live, "_is_reparse_point", lambda path: path == nested)

    repeated = live._clean_owned_role_dir(tmp_path, "machine")

    assert repeated == role_dir
    assert not nested.exists()


def test_live_reader_staging_rejects_ambient_only_footprints(tmp_path: Path) -> None:
    component = BoardComponent(
        "R1",
        "1k",
        "AmbientOnly:DefinitelyNotVendored",
        "fixture-uuid-r1",
    )
    netlist = BoardNetlist(components=(component,), nets=())

    with pytest.raises(ValueError, match="exact vendored footprint"):
        live._stage_vendored_project_footprints(netlist, tmp_path)


def test_live_reader_rejects_executable_changed_during_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "kicad-cli.exe"
    executable.write_bytes(b"pinned executable\n")
    install = KiCadInstall(path=executable, source="unit-test")
    layout = BoardLayout(
        placements=(), segments=(), vias=(), width_mm=20.0, height_mm=20.0
    )
    netlist = BoardNetlist(components=(), nets=())
    policy = StableAggregateExactCheckerPolicy.build(
        policy_id="reader-live-sha-guard",
        policy_version="1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=(
            AggregateSubcheckRequirement(
                subcheck_id="design",
                subcheck_version="1",
                kind=AggregateSubcheckKind.DESIGN_CHECKS,
            ),
            AggregateSubcheckRequirement(
                subcheck_id="virtual",
                subcheck_version="1",
                kind=AggregateSubcheckKind.VIRTUAL_DRC,
            ),
        ),
    )
    export_count = 0

    def fake_process(command: tuple[Path | str, ...]) -> KiCadProcessResult:
        return KiCadProcessResult(
            command=tuple(str(part) for part in command),
            returncode=0,
            stdout="10.0.3\n",
            stderr="",
        )

    def fake_erc(schematic_file: Path, **_kwargs: object) -> KiCadReport:
        report_file = schematic_file.parent / ".pcbsmith" / "kicad" / "erc.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text('{"sheets":[]}', encoding="utf-8")
        return KiCadReport(
            status="passed",
            schematic_file=str(schematic_file),
            erc_report=str(report_file),
        )

    def fake_export(schematic_file: Path, **_kwargs: object) -> Path:
        nonlocal export_count
        export_count += 1
        netlist_file = schematic_file.parent / ".pcbsmith" / "kicad" / "fixture.net.xml"
        netlist_file.parent.mkdir(parents=True, exist_ok=True)
        netlist_file.write_text(
            "<export><design><source>Fixture.kicad_sch</source></design></export>",
            encoding="utf-8",
        )
        if export_count == 2:
            executable.write_bytes(b"changed executable\n")
        return netlist_file

    monkeypatch.setattr(live, "find_kicad_cli", lambda: install)
    monkeypatch.setattr(live, "run_kicad_process", fake_process)
    monkeypatch.setattr(live, "run_kicad_erc", fake_erc)
    monkeypatch.setattr(live, "export_kicad_netlist_xml", fake_export)

    with pytest.raises(
        RuntimeError, match="KiCad CLI executable changed during live reader production"
    ):
        live.verify_reader_netlist_equality_live(
            layout=layout,
            netlist=netlist,
            policy=policy,
            subcheck_id="reader-equality",
            subcheck_version="1",
            machine_schematic_text="(kicad_sch machine)",
            reader_schematic_text="(kicad_sch reader)",
            machine_schematic_artifact_id="machine:Fixture.kicad_sch",
            reader_schematic_artifact_id="reader:Fixture.kicad_sch",
            schematic_file_name="Fixture.kicad_sch",
            output_root=tmp_path / "output",
            config_identity="reader-live-sha-guard-v1",
            config={"fixture": "executable-sha-change"},
        )

    assert export_count == 2
