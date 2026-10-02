"""Lineage and semantic negative controls; native exporter controls are separate."""

from __future__ import annotations

import json
import subprocess

import pytest
from tests.unit.test_manufacturing_release import (
    _artifact_payload,
    _attach_source_lineage,
    _board,
    _current_path,
    _dfm,
    _lineage_tools,
    _profile,
)

from pcbsmith.manufacturing_lineage import (
    ExportReceipt,
    file_sha256,
    native_input_hashes,
    run_recorded_export,
    saved_assembly_rows,
)
from pcbsmith.manufacturing_release import (
    MANDATORY_NEUTRAL_ROLES,
    assemble_neutral_manufacturing_package,
    extract_saved_board_manufacturing_identities,
)
from pcbsmith.manufacturing_release import (
    ManufacturingArtifactRole as Role,
)
from pcbsmith.routed_copper_graph_ir import fingerprint


def package_fixture(tmp_path):
    board = _board(tmp_path / "board.kicad_pcb")
    profile = _profile()
    sources = {}
    for role in MANDATORY_NEUTRAL_ROLES:
        path = tmp_path / (role.value + ".dat")
        path.write_bytes(_artifact_payload(role))
        sources[role] = (path,)
    _attach_source_lineage(board, profile, sources)
    return dict(
        output_directory=tmp_path / "package",
        project_id="fixture",
        board_file=board,
        profile=profile,
        identities=extract_saved_board_manufacturing_identities(board),
        current_paths=(_current_path(file_sha256(board), profile),),
        dfm_dft=_dfm(file_sha256(board)),
        source_artifacts=sources,
        tool_evidence=_lineage_tools(),
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_receipt",
        "changed_bom",
        "changed_placement",
        "missing_ibom_receipt",
        "changed_board",
        "added_project",
        "missing_output",
        "relabelled_role",
    ],
)
def test_package_rejects_missing_or_stale_export_lineage(tmp_path, fault):
    kwargs = package_fixture(tmp_path)
    sources = kwargs["source_artifacts"]
    board = kwargs["board_file"]
    if fault == "missing_receipt":
        del sources[Role.EXPORT_RECEIPT]
    elif fault in {"changed_bom", "changed_placement"}:
        role = Role.BOM if fault == "changed_bom" else Role.PLACEMENT
        path = sources[role][0]
        path.write_bytes(path.read_bytes() + b"\n")
    elif fault == "missing_ibom_receipt":
        del sources[Role.OTHER]
    elif fault == "changed_board":
        board.write_bytes(board.read_bytes() + b"\n")
    elif fault == "added_project":
        board.with_suffix(".kicad_pro").write_text("{}")
    elif fault == "missing_output":
        sources[Role.GERBER][0].unlink()
    else:
        sources[Role.GERBER], sources[Role.PASTE] = sources[Role.PASTE], sources[Role.GERBER]
    with pytest.raises((ValueError, OSError)):
        assemble_neutral_manufacturing_package(**kwargs)
    assert not kwargs["output_directory"].exists()
    assert not (tmp_path / "package.zip").exists()


def _rehash_declared_output(sources, role):
    """Deliberately self-consistent caller relabel; semantics must still reject it."""
    receipt_path = sources[Role.EXPORT_RECEIPT][0]
    receipt = json.loads(receipt_path.read_text())
    for output in receipt["outputs"]:
        if output["role"] == role.value:
            output["sha256"] = file_sha256(sources[role][0])
    receipt["receipt_fingerprint"] = fingerprint(
        {k: v for k, v in receipt.items() if k != "receipt_fingerprint"}
    )
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    ExportReceipt.model_validate_json(receipt_path.read_bytes())


@pytest.mark.parametrize(
    "fault",
    ["value", "footprint", "duplicate", "quantity", "missing", "position", "rotation", "side"],
)
def test_current_labels_and_hashes_do_not_replace_assembly_semantics(tmp_path, fault):
    kwargs = package_fixture(tmp_path)
    sources = kwargs["source_artifacts"]
    role = Role.PLACEMENT if fault in {"position", "rotation", "side"} else Role.BOM
    path = sources[role][0]
    text = path.read_text()
    if fault == "value":
        text = text.replace("TEST", "OTHER-BOARD")
    elif fault == "footprint":
        text = text.replace("Package_SO:SOIC-8", "Package_SO:SOIC-16")
    elif fault == "duplicate":
        text += text.splitlines()[1] + "\n"
    elif fault == "quantity":
        lines = text.splitlines()
        text = lines[0] + ",Qty\n" + lines[1] + ",2\n"
    elif fault == "missing":
        text = text.splitlines()[0] + "\n"
    elif fault == "position":
        text = text.replace(",10,-20,", ",99,-20,")
    elif fault == "rotation":
        text = text.replace(",90,top", ",0,top")
    else:
        text = text.replace(",top", ",bottom")
    path.write_text(text)
    _rehash_declared_output(sources, role)
    with pytest.raises(ValueError, match="BOM|placement|quantity|duplicate"):
        assemble_neutral_manufacturing_package(**kwargs)
    assert not kwargs["output_directory"].exists()


def test_archive_collision_is_not_overwritten(tmp_path):
    kwargs = package_fixture(tmp_path)
    archive = tmp_path / "package.zip"
    archive.write_bytes(b"retained archive")
    with pytest.raises(ValueError, match="target already exists"):
        assemble_neutral_manufacturing_package(**kwargs)
    assert archive.read_bytes() == b"retained archive"


def test_failed_native_command_retains_input_and_transport_diagnostics(tmp_path, monkeypatch):
    board = _board(tmp_path / "board.kicad_pcb")
    log = tmp_path / "process.json"
    records = []

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            args[0], kwargs["timeout"], output=b"partial stdout", stderr=b"partial stderr"
        )

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="retained diagnostics"):
        run_recorded_export(
            command=("fixture", "pcb", "export", "pos"),
            processes=records,
            log_file=log,
            initial_inputs=native_input_hashes(board),
        )
    payload = json.loads(log.read_text())
    assert payload["native_inputs"] == native_input_hashes(board)
    assert payload["processes"][0]["returncode"] == -1
    assert payload["processes"][0]["stdout"] == "partial stdout"
    assert "partial stderr" in payload["processes"][0]["stderr"]


def test_dnp_and_bom_position_exclusions_are_independent(tmp_path):
    footprints = []
    for reference, attrs in [
        ("R1", "smd"),
        ("DNP", "smd dnp"),
        ("BOM", "smd exclude_from_bom"),
        ("POS", "smd exclude_from_pos_files"),
        ("J1", "through_hole"),
    ]:
        footprints.append(f'''(footprint "Test:Device" (layer "F.Cu") (at 10 20 90)
            (property "Reference" "{reference}") (property "Value" "TEST") (attr {attrs}))''')
    board = tmp_path / "flags.kicad_pcb"
    board.write_text("(kicad_pcb " + "".join(footprints) + ")")
    rows = saved_assembly_rows(board)
    assert {row.reference for row in rows if row.in_bom} == {"R1", "POS", "J1"}
    assert {row.reference for row in rows if row.in_placement} == {"R1", "BOM", "J1"}


def test_export_lineage_alone_cannot_claim_production_readiness(tmp_path):
    from pcbsmith.manufacturing_ir import ManufacturingReleaseStatus

    manifest, _ = assemble_neutral_manufacturing_package(**package_fixture(tmp_path))
    assert manifest.release_status is ManufacturingReleaseStatus.BLOCKED
    assert "current production readiness/release evidence was not supplied" in manifest.blockers


def test_missing_production_generation_cannot_be_labelled_released(tmp_path):
    kwargs = package_fixture(tmp_path)
    kwargs.update(
        production_generation_root=tmp_path / "absent-generation",
        production_release_report_file=tmp_path / "absent-report.json",
    )
    with pytest.raises(OSError):
        assemble_neutral_manufacturing_package(**kwargs)
    assert not kwargs["output_directory"].exists()
